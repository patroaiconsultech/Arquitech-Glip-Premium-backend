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
    finalize_execution_if_owner,
    commit_new_or_recover_winner,
)


def candidate(*, row_id:str, digest:str="same-digest"):
    return IntegrationExecution(
        id=row_id,
        tenant_id="tenant-a",
        project_id="project-a",
        destination_service="orkio",
        capability_id="glip.draft_message",
        capability_version="1.0.0",
        request_id="request-race-1",
        execution_id=f"execution-{row_id}",
        correlation_id="corr-race-1",
        idempotency_key="idem-race-1",
        request_sha256=digest,
        request_json={"schema_version":"ORKIO-CAPABILITY-REQUEST-1"},
        draft_id=f"draft-{row_id}",
        cognitive_execution_id=f"cog-{row_id}",
        status="contextualized",
    )


@pytest.fixture()
def sessions(tmp_path):
    db_path=tmp_path/"race.sqlite"
    engine=create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread":False},
    )
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    with Session() as a, Session() as b:
        yield a,b


def test_unique_race_loser_recovers_winner_without_500(sessions):
    a,b=sessions
    winner=commit_new_or_recover_winner(
        a,candidate=candidate(row_id="winner"),request_sha256="same-digest"
    )
    assert winner.disposition=="NEW"

    loser=commit_new_or_recover_winner(
        b,candidate=candidate(row_id="loser"),request_sha256="same-digest"
    )
    assert loser.disposition=="IN_PROGRESS"
    assert loser.row.id=="winner"


def test_unique_race_with_changed_payload_is_deterministic_conflict(sessions):
    a,b=sessions
    commit_new_or_recover_winner(
        a,candidate=candidate(row_id="winner",digest="digest-a"),request_sha256="digest-a"
    )
    with pytest.raises(HTTPException) as exc:
        commit_new_or_recover_winner(
            b,candidate=candidate(row_id="loser",digest="digest-b"),request_sha256="digest-b"
        )
    assert exc.value.status_code==409
    assert exc.value.detail=="idempotency_key_reused_with_different_request"


def test_only_one_owner_can_hold_live_lease(sessions):
    a,b=sessions
    row=commit_new_or_recover_winner(
        a,candidate=candidate(row_id="winner"),request_sha256="same-digest"
    ).row

    first=acquire_execution_lease(
        a,row=row,lease_seconds=90,owner_token="owner-a"
    )
    assert first.disposition=="ACQUIRED"
    assert first.row.status=="calling"
    assert first.row.attempt_count==1

    b.expire_all()
    same=b.get(IntegrationExecution,row.id)
    second=acquire_execution_lease(
        b,row=same,lease_seconds=90,owner_token="owner-b"
    )
    assert second.disposition=="IN_PROGRESS"
    assert second.row.owner_token=="owner-a"
    assert second.row.attempt_count==1


def test_expired_lease_can_be_taken_over_and_old_owner_loses_cas(sessions):
    a,b=sessions
    row=commit_new_or_recover_winner(
        a,candidate=candidate(row_id="winner"),request_sha256="same-digest"
    ).row
    first=acquire_execution_lease(
        a,row=row,lease_seconds=90,owner_token="owner-a"
    )
    assert first.disposition=="ACQUIRED"

    a.execute(
        update(IntegrationExecution)
        .where(IntegrationExecution.id==row.id)
        .values(lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=5))
    )
    a.commit()

    b.expire_all()
    takeover=acquire_execution_lease(
        b,row=b.get(IntegrationExecution,row.id),lease_seconds=90,owner_token="owner-b"
    )
    assert takeover.disposition=="ACQUIRED"
    assert takeover.row.owner_token=="owner-b"
    assert takeover.row.attempt_count==2

    a.expire_all()
    with pytest.raises(HTTPException) as exc:
        finalize_execution_if_owner(
            a,
            execution_id=row.id,
            tenant_id="tenant-a",
            owner_token="owner-a",
            upstream_response_json={},
            domain_response_json={"draft":"stale"},
            latency_ms=0,
            retry_count=0,
        )
    assert exc.value.status_code==409
    assert exc.value.detail=="integration_execution_ownership_lost"



def test_unrelated_unique_integrity_error_is_not_masked(sessions):
    from sqlalchemy.exc import IntegrityError

    a,b=sessions
    first=candidate(row_id="winner")
    first.execution_id="execution-collision"
    first.idempotency_key="idem-a"
    commit_new_or_recover_winner(a,candidate=first,request_sha256="same-digest")

    second=candidate(row_id="loser")
    second.execution_id="execution-collision"
    second.idempotency_key="idem-b"
    with pytest.raises(IntegrityError):
        commit_new_or_recover_winner(
            b,candidate=second,request_sha256="same-digest"
        )



def test_two_contenders_allow_exactly_one_upstream_eligible_owner(sessions):
    a,b=sessions
    winner=commit_new_or_recover_winner(
        a,candidate=candidate(row_id="winner"),request_sha256="same-digest"
    )
    loser=commit_new_or_recover_winner(
        b,candidate=candidate(row_id="loser"),request_sha256="same-digest"
    )
    assert winner.row.id==loser.row.id=="winner"

    first=acquire_execution_lease(
        a,row=winner.row,lease_seconds=90,owner_token="owner-a"
    )
    b.expire_all()
    second=acquire_execution_lease(
        b,row=b.get(IntegrationExecution,"winner"),lease_seconds=90,owner_token="owner-b"
    )

    upstream_eligible=[
        claim for claim in (first,second)
        if claim.disposition=="ACQUIRED"
    ]
    assert len(upstream_eligible)==1
    assert first.disposition=="ACQUIRED"
    assert second.disposition=="IN_PROGRESS"
