from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]


def test_pricing_authority_migration_is_linear_additive_and_reversible():
    path=ROOT/"migrations/versions/0009_glip_pricing_authority_hardening.py"
    text=path.read_text(encoding="utf-8")
    assert 'revision = "0009_glip_pricing_authority_hardening"' in text
    assert 'down_revision = "0008_glip_pricing_cost_intelligence"' in text
    for field in ("authority_status","authority_method","authority_by","authority_at"):
        assert field in text
    assert "def downgrade()" in text
    assert 'drop_column("authority_status")' in text

    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert script.get_heads()==["0009_glip_pricing_authority_hardening"]
