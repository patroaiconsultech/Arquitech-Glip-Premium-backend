from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]

def test_v10_rc1_migration_remains_additive_and_reversible():
    text=(ROOT/"migrations/versions/0002_glip_orkio_contract_v10.py").read_text(encoding="utf-8")
    assert 'down_revision = "0001_glip_baseline_v08"' in text
    assert '"integration_executions"' in text
    assert 'op.drop_table("integration_executions")' in text
    assert "ALTER TABLE" not in text.upper()
    assert "Base.metadata" not in text

def test_rc2_lease_migration_is_additive_over_rc1():
    text=(ROOT/"migrations/versions/0003_glip_integration_lease_rc2.py").read_text(encoding="utf-8")
    assert 'down_revision = "0002_glip_orkio_contract_v10"' in text
    assert 'op.add_column("integration_executions"' in text
    assert 'op.drop_column("integration_executions"' in text
    assert 'op.drop_table("integration_executions")' not in text

def test_current_head_is_rc2_lease_migration():
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert len(script.get_heads())==1
