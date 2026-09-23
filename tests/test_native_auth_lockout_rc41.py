from sqlalchemy.dialects import postgresql

from glip.native_auth import credential_for_login_statement


def test_fnd008_login_credential_query_compiles_to_postgres_for_update():
    stmt=credential_for_login_statement(
        tenant_id="tenant-a",
        email_normalized="owner@example.com",
    )
    sql=str(stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds":True},
    )).upper()
    assert "FOR UPDATE" in sql
    assert "NATIVE_CREDENTIALS.TENANT_ID = 'TENANT-A'" in sql
    assert "NATIVE_CREDENTIALS.EMAIL_NORMALIZED = 'OWNER@EXAMPLE.COM'" in sql


def test_fnd008_waiter_forces_refresh_after_row_lock_wait():
    stmt=credential_for_login_statement(
        tenant_id="tenant-a",
        email_normalized="owner@example.com",
    )
    assert stmt._for_update_arg is not None
    assert stmt.get_execution_options().get("populate_existing") is True
