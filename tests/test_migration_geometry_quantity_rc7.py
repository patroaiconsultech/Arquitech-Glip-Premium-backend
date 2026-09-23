
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]


def test_rc7_migration_is_linear_additive_and_reversible():
    p=ROOT/"migrations/versions/0007_glip_geometry_quantity_foundation.py"
    text=p.read_text()
    assert 'revision = "0007_glip_geometry_quantity_foundation"' in text
    assert 'down_revision = "0006_glip_bim_semantic_ingestion"' in text
    assert '"cad_extraction_jobs"' in text
    assert '"geometry_build_jobs"' in text
    assert 'def downgrade()' in text
    assert 'drop_table("geometry_build_jobs")' in text
    assert 'drop_table("cad_extraction_jobs")' in text

    cfg=Config(str(ROOT/"alembic.ini"))
    script=ScriptDirectory.from_config(cfg)
    assert len(script.get_heads())==1
