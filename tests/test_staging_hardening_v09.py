import pytest
from sqlalchemy import create_engine, text
from glip.config import Settings
from glip.readiness import database_readiness, EXPECTED_MIGRATION_HEAD

def base(**overrides):
    values={
        "environment":"test",
        "database_url":"sqlite://",
        "auth_mode":"dev_headers",
        "orkio_mode":"disabled",
    }
    values.update(overrides)
    return Settings(**values)

def test_staging_requires_postgresql_and_migration_head():
    with pytest.raises(ValueError,match="postgresql_required_outside_dev"):
        base(environment="staging",database_url="sqlite://",require_migration_head=True)
    with pytest.raises(ValueError,match="migration_head_check_required_outside_dev"):
        base(environment="staging",database_url="postgresql+psycopg://x:y@localhost/db",require_migration_head=False)

def test_production_cors_rejects_http_and_localhost():
    common={
        "environment":"production",
        "database_url":"postgresql+psycopg://x:y@db/glip",
        "require_migration_head":True,
        "auth_mode":"native_session",
        "auth_session_secret":"s"*40,
        "auth_password_pepper":"p"*40,
    }
    with pytest.raises(ValueError,match="production_cors_https_required"):
        Settings(**common,cors_origins="http://glip.example")
    with pytest.raises(ValueError,match="production_cors_localhost_forbidden"):
        Settings(**common,cors_origins="https://localhost")

def test_readiness_requires_exact_alembic_head_when_enabled():
    engine=create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('wrong_head')"))
    checks=database_readiness(engine,require_migration_head=True)
    assert checks["database_connect"] is True
    assert checks["migration_current"] is False
    assert checks["migration_head"]=="wrong_head"

def test_readiness_accepts_current_explicit_head():
    engine=create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES (:head)"),{"head":EXPECTED_MIGRATION_HEAD})
    checks=database_readiness(engine,require_migration_head=True)
    assert checks["migration_current"] is True
    assert checks["migration_head"]==EXPECTED_MIGRATION_HEAD
