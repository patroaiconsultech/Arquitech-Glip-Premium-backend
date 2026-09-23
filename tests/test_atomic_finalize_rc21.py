from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from glip.orm import Base
from glip.models import IntegrationExecution
from glip.integration_idempotency import (
    acquire_execution_lease,
    commit_new_or_recover_winner,
    fail_execution_if_owner,
    finalize_execution_if_owner,
)


def candidate():
    return IntegrationExecution(
        id="race-row",
        tenant_id="tenant-a",
        project_id="project-a",
        destination_service="orkio",
        capability_id="glip.draft_message",
        capability_version="1.0.0",
        request_id="request-race",
        execution_id="execution-race",
        correlation_id="corr-race",
        idempotency_key="idem-race",
        request_sha256="digest",
        request_json={"schema_version":"ORKIO-CAPABILITY-REQUEST-1"},
        draft_id="draft-race",
        cognitive_execution_id="cog-race",
        status="contextualized",
    )


@pytest.fixture()
def sessions(tmp_path):
    engine=create_engine(
        f"sqlite:///{tmp_path/'atomic.sqlite'}",
        connect_args={"check_same_thread":False},
    )
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    with Session() as a, Session() as b:
        yield a,b


def takeover(a,b):
    row=commit_new_or_recover_winner(
        a,candidate=candidate(),request_sha256="digest"
    ).row
    first=acquire_execution_lease(
        a,row=row,lease_seconds=90,owner_token="owner-a"
    )
    assert first.disposition=="ACQUIRED"

    # This reproduces the critical RC2 timing: A has already observed valid
    # ownership, then its lease expires before finalization.
    a.execute(
        update(IntegrationExecution)
        .where(IntegrationExecution.id==row.id)
        .values(lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=5))
        .execution_options(synchronize_session=False)
    )
    a.commit()

    b.expire_all()
    second=acquire_execution_lease(
        b,row=b.get(IntegrationExecution,row.id),lease_seconds=90,owner_token="owner-b"
    )
    assert second.disposition=="ACQUIRED"
    assert second.row.owner_token=="owner-b"
    return row.id


def test_stale_owner_cannot_finalize_after_takeover(sessions):
    a,b=sessions
    row_id=takeover(a,b)

    with pytest.raises(HTTPException) as exc:
        finalize_execution_if_owner(
            a,
            execution_id=row_id,
            tenant_id="tenant-a",
            owner_token="owner-a",
            upstream_response_json={"message_id":"old-owner"},
            domain_response_json={"draft":"stale"},
            latency_ms=10,
            retry_count=0,
        )
    assert exc.value.status_code==409
    assert exc.value.detail=="integration_execution_ownership_lost"

    b.expire_all()
    final=b.get(IntegrationExecution,row_id)
    assert final.status=="calling"
    assert final.owner_token=="owner-b"
    assert final.attempt_count==2
    assert final.domain_response_json is None


def test_stale_owner_cannot_mark_failed_after_takeover(sessions):
    a,b=sessions
    row_id=takeover(a,b)

    with pytest.raises(HTTPException) as exc:
        fail_execution_if_owner(
            a,
            execution_id=row_id,
            tenant_id="tenant-a",
            owner_token="owner-a",
            error_code="stale-owner-error",
        )
    assert exc.value.status_code==409
    assert exc.value.detail=="integration_execution_ownership_lost"

    b.expire_all()
    final=b.get(IntegrationExecution,row_id)
    assert final.status=="calling"
    assert final.owner_token=="owner-b"
    assert final.error_code is None


def test_current_owner_can_finalize_with_live_lease(sessions):
    a,_=sessions
    row=commit_new_or_recover_winner(
        a,candidate=candidate(),request_sha256="digest"
    ).row
    claim=acquire_execution_lease(
        a,row=row,lease_seconds=90,owner_token="owner-a"
    )
    completed=finalize_execution_if_owner(
        a,
        execution_id=row.id,
        tenant_id="tenant-a",
        owner_token="owner-a",
        upstream_response_json={"message_id":"m1"},
        domain_response_json={"draft":"ok"},
        latency_ms=7,
        retry_count=1,
    )
    a.commit()
    assert completed.status=="completed"
    assert completed.owner_token is None
    assert completed.domain_response_json=={"draft":"ok"}


def test_expired_owner_cannot_finalize_even_without_takeover(sessions):
    a,_=sessions
    row=commit_new_or_recover_winner(
        a,candidate=candidate(),request_sha256="digest"
    ).row
    acquire_execution_lease(
        a,row=row,lease_seconds=90,owner_token="owner-a"
    )
    a.execute(
        update(IntegrationExecution)
        .where(IntegrationExecution.id==row.id)
        .values(lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=5))
        .execution_options(synchronize_session=False)
    )
    a.commit()

    with pytest.raises(HTTPException,match="409"):
        finalize_execution_if_owner(
            a,
            execution_id=row.id,
            tenant_id="tenant-a",
            owner_token="owner-a",
            upstream_response_json={},
            domain_response_json={"draft":"late"},
            latency_ms=1,
            retry_count=0,
        )
