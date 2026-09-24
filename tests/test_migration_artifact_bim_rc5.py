from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]

def test_rc5_artifact_bim_migration_is_linear_and_reversible():
    p=ROOT/"migrations/versions/0005_glip_artifact_bim_foundation.py"
    text=p.read_text(encoding="utf-8")
    assert 'down_revision = "0004a_alembic_version_128"' in text
    for table in (
        "artifact_jobs","artifact_assets","artifact_usage_events",
        "architectural_sources","architectural_scenes","render_jobs",
    ):
        assert f'"{table}"' in text
        assert f'op.drop_table("{table}")' in text
    assert '"billing_scope"' in text
    assert '"ifc_schema"' in text

def test_rc5_is_single_migration_head():
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert len(script.get_heads())==1
