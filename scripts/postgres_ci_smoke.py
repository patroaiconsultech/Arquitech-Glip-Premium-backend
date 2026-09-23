#!/usr/bin/env python3
"""Real PostgreSQL smoke for CI/staging only."""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker

from glip.integration_idempotency import (
    acquire_execution_lease,
    commit_new_or_recover_winner,
    finalize_execution_if_owner,
)
from glip.models import IntegrationExecution
from glip.readiness import EXPECTED_MIGRATION_HEAD

url=os.environ.get("GLIP_DATABASE_URL","").strip()
if not url.startswith("postgresql"):
    raise SystemExit("GLIP_DATABASE_URL must be PostgreSQL")
if url.startswith("postgresql://"):
    url="postgresql+psycopg://"+url[len("postgresql://"):]
elif url.startswith("postgres://"):
    url="postgresql+psycopg://"+url[len("postgres://"):]

engine=create_engine(url,pool_pre_ping=True)
Session=sessionmaker(bind=engine,expire_on_commit=False)

with engine.connect() as conn:
    assert conn.dialect.name=="postgresql"
    head=conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head==EXPECTED_MIGRATION_HEAD, (head,EXPECTED_MIGRATION_HEAD)

def candidate(row_id):
    return IntegrationExecution(
        id=row_id,
        tenant_id="ci-tenant",
        project_id="ci-project",
        destination_service="orkio",
        capability_id="glip.draft_message",
        capability_version="1.0.0",
        request_id="ci-request",
        execution_id=f"ci-execution-{row_id}",
        correlation_id="ci-correlation",
        idempotency_key="ci-idempotency",
        request_sha256="ci-digest",
        request_json={"schema_version":"ORKIO-CAPABILITY-REQUEST-1"},
        draft_id=f"ci-draft-{row_id}",
        cognitive_execution_id=f"ci-cognitive-{row_id}",
        status="contextualized",
    )

with engine.begin() as conn:
    conn.execute(text("DELETE FROM integration_executions WHERE tenant_id='ci-tenant'"))

with Session() as a, Session() as b:
    winner=commit_new_or_recover_winner(a,candidate=candidate("winner"),request_sha256="ci-digest")
    loser=commit_new_or_recover_winner(b,candidate=candidate("loser"),request_sha256="ci-digest")
    assert winner.row.id==loser.row.id=="winner"

    first=acquire_execution_lease(a,row=winner.row,lease_seconds=90,owner_token="owner-a")
    assert first.disposition=="ACQUIRED"

    a.execute(
        update(IntegrationExecution)
        .where(IntegrationExecution.id=="winner")
        .values(lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=5))
        .execution_options(synchronize_session=False)
    )
    a.commit()

    b.expire_all()
    second=acquire_execution_lease(
        b,row=b.get(IntegrationExecution,"winner"),lease_seconds=90,owner_token="owner-b"
    )
    assert second.disposition=="ACQUIRED"

    blocked=False
    try:
        finalize_execution_if_owner(
            a,
            execution_id="winner",
            tenant_id="ci-tenant",
            owner_token="owner-a",
            upstream_response_json={},
            domain_response_json={"draft":"stale"},
            latency_ms=1,
            retry_count=0,
        )
    except Exception:
        blocked=True
    assert blocked

    b.expire_all()
    row=b.get(IntegrationExecution,"winner")
    assert row.owner_token=="owner-b"
    assert row.status=="calling"
    assert row.domain_response_json is None

with engine.begin() as conn:
    conn.execute(text("DELETE FROM integration_executions WHERE tenant_id='ci-tenant'"))

print("POSTGRES_CI_SMOKE_PASS")
