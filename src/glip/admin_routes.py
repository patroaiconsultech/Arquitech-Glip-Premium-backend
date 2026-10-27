"""Owner-only, tenant-scoped administration. Proposal ID01-P0.

Uses existing revision 0012 tables; no client-supplied tenant/role elevation.
Manual sharing of the one-time activation link is a pilot-only delivery method.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_db
from .models import InvitationRateLimitBucket, Membership, NativeCredential, TenantAuditEvent, UserInvitation
from .native_auth import normalize_email, valid_email_shape

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def owner(p: Principal = Depends(get_principal)) -> Principal:
    if p.role != "owner":
        raise HTTPException(403, "owner_required")
    return p


class CreateInvite(BaseModel):
    email: str
    display_name: str | None = None


def _time(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _invite(row: UserInvitation):
    return {
        "id": row.id,
        "email": row.email_normalized,
        "display_name": row.display_name,
        "role": row.role,
        "status": row.status,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
    }


@router.get("/users")
def users(p: Principal = Depends(owner), db: Session = Depends(get_db)):
    stmt = (
        select(Membership, NativeCredential.email_normalized)
        .outerjoin(
            NativeCredential,
            (NativeCredential.membership_id == Membership.id)
            & (NativeCredential.tenant_id == Membership.tenant_id),
        )
        .where(Membership.tenant_id == p.tenant_id)
        .order_by(Membership.created_at.desc())
        .limit(200)
    )
    return [
        {
            "id": m.id,
            "display_name": m.display_name,
            "email": email,
            "role": m.role,
            "active": m.active,
        }
        for m, email in db.execute(stmt)
    ]


@router.get("/invitations")
def invitations(p: Principal = Depends(owner), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(UserInvitation)
        .where(UserInvitation.tenant_id == p.tenant_id)
        .order_by(UserInvitation.created_at.desc())
        .limit(100)
    ).all()
    return [_invite(row) for row in rows]


@router.post("/invitations", status_code=201)
def create_invitation(
    body: CreateInvite,
    response: Response,
    p: Principal = Depends(owner),
    db: Session = Depends(get_db),
):
    email = normalize_email(body.email)
    if not valid_email_shape(email):
        raise HTTPException(422, "invalid_email")
    display_name = (body.display_name or "").strip()[:200] or None
    current = datetime.now(timezone.utc)

    # Serialize invite issuance per tenant inside the same PostgreSQL transaction.
    # Count rows alone is neither concurrency safe nor robust for revoked/reissued invites.
    # Collision of the advisory-lock hash can only cause extra serialization.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"glip:invitation-issuance:v1:{p.tenant_id}"},
        )

    # Locking precedes all uniqueness and quota checks (also for a reissue).
    existing_credential = db.scalar(
        select(NativeCredential.id).where(
            NativeCredential.tenant_id == p.tenant_id,
            NativeCredential.email_normalized == email,
        )
    )
    if existing_credential is not None:
        raise HTTPException(409, "user_already_exists")

    row = db.scalar(
        select(UserInvitation)
        .where(
            UserInvitation.tenant_id == p.tenant_id,
            UserInvitation.email_normalized == email,
        )
        .with_for_update()
    )
    if row and row.status == "accepted":
        raise HTTPException(409, "invitation_already_accepted")
    if row and row.status == "pending" and _time(row.expires_at) > current:
        raise HTTPException(409, "invitation_already_pending")

    # Fixed UTC hour. Every successful issuance consumes one durable slot,
    # including a reissue of a revoked/expired invitation.
    hour = current.replace(minute=0, second=0, microsecond=0)
    key_digest = hashlib.sha256(
        f"glip:invitation-rate:v1:{p.tenant_id}".encode("utf-8")
    ).hexdigest()
    bucket = db.scalar(
        select(InvitationRateLimitBucket).where(
            InvitationRateLimitBucket.key_digest == key_digest,
            InvitationRateLimitBucket.window_started_at == hour,
        ).with_for_update()
    )
    if bucket is not None and bucket.count >= 10:
        raise HTTPException(429, "invitation_rate_limited")
    if bucket is None:
        bucket = InvitationRateLimitBucket(
            id=str(uuid4()), key_digest=key_digest, window_started_at=hour,
            count=1, created_at=current, updated_at=current,
        )
        db.add(bucket)
    else:
        bucket.count += 1
        bucket.updated_at = current

    raw_token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    if row is None:
        row = UserInvitation(
            id=str(uuid4()), tenant_id=p.tenant_id, email_normalized=email,
            display_name=display_name, role="member", token_digest=digest,
            invited_by=p.subject, expires_at=current + timedelta(hours=48),
            status="pending", created_at=current, updated_at=current,
        )
        db.add(row)
    else:
        row.token_version += 1
        row.token_digest = digest
        row.display_name = display_name
        row.role = "member"
        row.invited_by = p.subject
        row.status = "pending"
        row.expires_at = current + timedelta(hours=48)
        row.created_at = current
        row.updated_at = current
        row.accepted_at = None
        row.revoked_at = None
        row.accepted_membership_id = None

    db.add(TenantAuditEvent(
        id=str(uuid4()), tenant_id=p.tenant_id, actor_id=p.subject,
        event_type="invitation_created", target_type="user_invitation",
        target_id=row.id, payload={"role": "member"},
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "invitation_conflict") from exc
    response.headers["Cache-Control"] = "no-store"
    return {**_invite(row), "activation_token": raw_token}


@router.post("/invitations/{invitation_id}/revoke")
def revoke(
    invitation_id: str,
    p: Principal = Depends(owner),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(UserInvitation)
        .where(
            UserInvitation.tenant_id == p.tenant_id,
            UserInvitation.id == invitation_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "invitation_not_found")
    if row.status != "pending":
        raise HTTPException(409, "invitation_not_pending")
    row.status = "revoked"
    row.revoked_at = datetime.now(timezone.utc)
    db.add(TenantAuditEvent(
        id=str(uuid4()), tenant_id=p.tenant_id, actor_id=p.subject,
        event_type="invitation_revoked", target_type="user_invitation",
        target_id=row.id, payload={},
    ))
    db.commit()
    return _invite(row)
