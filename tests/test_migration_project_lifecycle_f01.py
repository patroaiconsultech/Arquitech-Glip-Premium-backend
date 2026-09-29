from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]


def test_f01_project_lifecycle_migration_is_linear_additive_and_reversible():
    path=ROOT/"migrations/versions/0010_glip_project_lifecycle.py"
    text=path.read_text(encoding="utf-8")
    assert 'revision = "0010_glip_project_lifecycle"' in text
    assert 'down_revision = "0009_glip_pricing_authority_hardening"' in text
    assert '"archived_at"' in text
    assert '"archived_by"' in text
    assert '"project_create_idempotency"' in text
    assert '"uq_project_create_idempotency"' in text
    assert "def downgrade()" in text
    assert 'op.drop_table("project_create_idempotency")' in text
    assert 'batch.drop_column("archived_at")' in text

    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert script.get_heads()==["0010_glip_project_lifecycle"]
