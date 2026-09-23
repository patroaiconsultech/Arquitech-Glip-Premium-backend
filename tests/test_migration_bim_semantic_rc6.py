from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]

def test_rc6_bim_semantic_migration_is_linear_and_reversible():
    p=ROOT/"migrations/versions/0006_glip_bim_semantic_ingestion.py"
    text=p.read_text(encoding="utf-8")
    assert 'down_revision = "0005_glip_artifact_bim_foundation"' in text
    assert '"bim_extraction_jobs"' in text
    assert 'op.drop_table("bim_extraction_jobs")' in text
    for field in ("source_sha256","engine_version","lease_owner","lease_expires_at","statistics_json"):
        assert f'"{field}"' in text

def test_rc6_is_single_migration_head():
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert len(script.get_heads())==1
