from sqlalchemy import text

EXPECTED_MIGRATION_HEAD="0009_glip_pricing_authority_hardening"

def database_readiness(engine, *, require_migration_head: bool) -> dict:
    checks={
        "database_connect":False,
        "database_driver":None,
        "migration_current":False if require_migration_head else None,
        "migration_head":None,
        "migration_expected":EXPECTED_MIGRATION_HEAD,
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database_connect"]=True
            checks["database_driver"]=conn.dialect.name
            if require_migration_head:
                try:
                    head=conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                except Exception:
                    head=None
                checks["migration_head"]=head
                checks["migration_current"]=(head==EXPECTED_MIGRATION_HEAD)
    except Exception:
        return checks
    return checks
