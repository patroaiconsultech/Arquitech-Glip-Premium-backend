from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
ROOT=Path(__file__).resolve().parents[1]

def test_native_auth_migration_is_linear_additive_and_reversible():
    text=(ROOT/"migrations/versions/0004_glip_native_auth_rc4.py").read_text()
    assert 'down_revision = "0003_glip_integration_lease_rc2"' in text
    assert '"native_credentials"' in text
    assert '"native_auth_sessions"' in text
    assert '"native_auth_events"' in text
    assert 'op.drop_table("native_credentials")' in text
    assert 'op.drop_table("integration_executions")' not in text

def test_current_head_is_native_auth_rc4():
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert len(script.get_heads())==1



def test_native_auth_migration_contains_lockout_and_fk_integrity():
    text=(ROOT/"migrations/versions/0004_glip_native_auth_rc4.py").read_text()
    assert '"locked_until"' in text
    assert 'sa.ForeignKey("tenants.id")' in text
    assert 'sa.ForeignKey("memberships.id")' in text
    assert 'sa.ForeignKey("native_credentials.id")' in text
