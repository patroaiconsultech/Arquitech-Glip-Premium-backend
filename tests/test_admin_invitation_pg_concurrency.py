"""Opt-in PostgreSQL concurrency proof; never connects without explicit isolated-test approval."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session

from glip.admin_routes import CreateInvite, create_invitation
from glip.auth import Principal
from glip.models import InvitationRateLimitBucket, Membership, Tenant
from glip.orm import Base


@pytest.mark.skipif(
    os.environ.get("GLIP_TEST_POSTGRES_ISOLATED") != "YES"
    or not os.environ.get("GLIP_TEST_POSTGRES_URL"),
    reason="requires explicit isolated PostgreSQL test DSN and approval flag",
)
def test_postgresql_concurrent_invitation_quota_is_atomic():
    url = os.environ["GLIP_TEST_POSTGRES_URL"]
    if not url.startswith("postgresql"):
        pytest.fail("isolated test URL must use PostgreSQL")
    # This schema is ephemeral and never touches public or production schemas.
    schema = "glip_admin_test_" + uuid4().hex[:14]
    admin_engine = create_engine(url, pool_pre_ping=True)
    engine = None
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            url, pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(engine)
        tenant_id = "test-admin-pg-tenant"
        owner = Principal(subject="native:test-owner", tenant_id=tenant_id, role="owner")
        with Session(engine) as db:
            db.add(Tenant(id=tenant_id, name="Test PG"))
            db.add(Membership(tenant_id=tenant_id, external_subject=owner.subject,
                              role="owner", active=True))
            db.commit()

        def create(i: int):
            with Session(engine) as db:
                try:
                    created = create_invitation(
                        CreateInvite(email=f"test{i}@example.invalid", display_name="Test"),
                        Response(), owner, db,
                    )
                    return created["id"]
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(create, range(12)))
        assert sum(isinstance(result, str) for result in results) == 10
        assert results.count(429) == 2
        with Session(engine) as db:
            rows = db.scalars(select(InvitationRateLimitBucket)).all()
            assert len(rows) == 1
            assert rows[0].count == 10
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
