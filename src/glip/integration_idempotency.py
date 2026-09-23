from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IntegrationExecution


EXPECTED_IDEMPOTENCY_CONSTRAINT = "uq_integration_idempotency"


@dataclass(frozen=True, slots=True)
class ClaimResult:
    row: IntegrationExecution
    disposition: str  # NEW | REPLAY | IN_PROGRESS | FAILED | ACQUIRED
    owner_token: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def find_execution(
    db: Session,
    *,
    tenant_id: str,
    destination_service: str,
    idempotency_key: str,
) -> IntegrationExecution | None:
    return db.scalar(select(IntegrationExecution).where(
        IntegrationExecution.tenant_id == tenant_id,
        IntegrationExecution.destination_service == destination_service,
        IntegrationExecution.idempotency_key == idempotency_key,
    ))


def _integrity_is_expected_idempotency(exc: IntegrityError) -> bool:
    text = " ".join(
        str(part)
        for part in (
            exc,
            getattr(exc, "orig", ""),
            getattr(getattr(exc, "orig", None), "diag", ""),
        )
    ).lower()
    # PostgreSQL typically reports the constraint name; SQLite reports columns.
    return (
        EXPECTED_IDEMPOTENCY_CONSTRAINT.lower() in text
        or (
            "unique constraint failed" in text
            and "integration_executions.tenant_id" in text
            and "integration_executions.destination_service" in text
            and "integration_executions.idempotency_key" in text
        )
    )


def commit_new_or_recover_winner(
    db: Session,
    *,
    candidate: IntegrationExecution,
    request_sha256: str,
) -> ClaimResult:
    db.add(candidate)
    try:
        db.commit()
        return ClaimResult(candidate, "NEW")
    except IntegrityError as exc:
        db.rollback()
        if not _integrity_is_expected_idempotency(exc):
            raise
        winner = find_execution(
            db,
            tenant_id=candidate.tenant_id,
            destination_service=candidate.destination_service,
            idempotency_key=candidate.idempotency_key,
        )
        if winner is None:
            raise HTTPException(409, "idempotency_winner_not_visible") from exc
        if winner.request_sha256 != request_sha256:
            raise HTTPException(409, "idempotency_key_reused_with_different_request") from exc
        if winner.status == "completed" and winner.domain_response_json:
            return ClaimResult(winner, "REPLAY")
        if winner.status == "failed":
            return ClaimResult(winner, "FAILED")
        return ClaimResult(winner, "IN_PROGRESS")


def acquire_execution_lease(
    db: Session,
    *,
    row: IntegrationExecution,
    lease_seconds: int,
    owner_token: str | None = None,
) -> ClaimResult:
    owner = owner_token or str(uuid4())
    now = _utcnow()
    expires = now + timedelta(seconds=lease_seconds)

    result = db.execute(
        update(IntegrationExecution)
        .where(
            IntegrationExecution.id == row.id,
            IntegrationExecution.tenant_id == row.tenant_id,
            IntegrationExecution.request_sha256 == row.request_sha256,
            IntegrationExecution.status.in_(["contextualized", "calling"]),
            or_(
                IntegrationExecution.owner_token.is_(None),
                IntegrationExecution.lease_expires_at.is_(None),
                IntegrationExecution.lease_expires_at <= now,
                IntegrationExecution.owner_token == owner,
            ),
        )
        .values(
            status="calling",
            owner_token=owner,
            lease_expires_at=expires,
            attempt_count=IntegrationExecution.attempt_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    # Bulk UPDATE deliberately bypasses ORM synchronization to avoid timezone
    # comparisons in Python. Reload authoritative row state from the database.
    db.expire_all()
    fresh = db.get(IntegrationExecution, row.id)
    if result.rowcount == 1 and fresh is not None and fresh.owner_token == owner:
        return ClaimResult(fresh, "ACQUIRED", owner)

    if fresh is None:
        raise HTTPException(409, "integration_execution_disappeared")
    if fresh.status == "completed" and fresh.domain_response_json:
        return ClaimResult(fresh, "REPLAY")
    if fresh.status == "failed":
        return ClaimResult(fresh, "FAILED")

    lease = _as_utc(fresh.lease_expires_at)
    if fresh.status == "calling" and fresh.owner_token and lease and lease > now:
        return ClaimResult(fresh, "IN_PROGRESS")
    raise HTTPException(409, "integration_execution_claim_conflict")


def finalize_execution_if_owner(
    db: Session,
    *,
    execution_id: str,
    tenant_id: str,
    owner_token: str,
    upstream_response_json: dict,
    domain_response_json: dict,
    latency_ms: int,
    retry_count: int,
) -> IntegrationExecution:
    """Atomically finalize only if this owner still holds a live lease.

    The ownership predicate and state transition are a single SQL UPDATE.
    Database time is authoritative for lease validity.
    """
    from sqlalchemy import func

    result = db.execute(
        update(IntegrationExecution)
        .where(
            IntegrationExecution.id == execution_id,
            IntegrationExecution.tenant_id == tenant_id,
            IntegrationExecution.status == "calling",
            IntegrationExecution.owner_token == owner_token,
            IntegrationExecution.lease_expires_at.is_not(None),
            IntegrationExecution.lease_expires_at > func.now(),
        )
        .values(
            status="completed",
            upstream_response_json=upstream_response_json,
            domain_response_json=domain_response_json,
            latency_ms=latency_ms,
            retry_count=retry_count,
            error_code=None,
            completed_at=func.now(),
            owner_token=None,
            lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "integration_execution_ownership_lost")

    db.flush()
    db.expire_all()
    row = db.get(IntegrationExecution, execution_id)
    if row is None:
        db.rollback()
        raise HTTPException(409, "integration_execution_disappeared")
    return row


def fail_execution_if_owner(
    db: Session,
    *,
    execution_id: str,
    tenant_id: str,
    owner_token: str,
    error_code: str,
) -> IntegrationExecution:
    """Atomically fail only if this owner still holds a live lease."""
    from sqlalchemy import func

    result = db.execute(
        update(IntegrationExecution)
        .where(
            IntegrationExecution.id == execution_id,
            IntegrationExecution.tenant_id == tenant_id,
            IntegrationExecution.status == "calling",
            IntegrationExecution.owner_token == owner_token,
            IntegrationExecution.lease_expires_at.is_not(None),
            IntegrationExecution.lease_expires_at > func.now(),
        )
        .values(
            status="failed",
            error_code=error_code,
            completed_at=func.now(),
            owner_token=None,
            lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "integration_execution_ownership_lost")

    db.flush()
    db.expire_all()
    row = db.get(IntegrationExecution, execution_id)
    if row is None:
        db.rollback()
        raise HTTPException(409, "integration_execution_disappeared")
    return row
