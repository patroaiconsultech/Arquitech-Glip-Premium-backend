from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT=Path(__file__).resolve().parents[1]
MIGRATION=ROOT/"migrations/versions/0001_glip_baseline_v08.py"

def test_explicit_v08_baseline_is_preserved_as_root():
    files=sorted(
        p.name for p in (ROOT/"migrations/versions").glob("*.py")
        if p.name!="__init__.py"
    )
    assert "0001_glip_baseline_v08.py" in files
    assert "0002_glip_orkio_contract_v10.py" in files

    text=MIGRATION.read_text(encoding="utf-8")
    assert "Base.metadata" not in text
    assert "create_all" not in text
    assert "drop_all" not in text
    assert text.count("op.create_table(")>=20
    assert text.count("op.drop_table(")>=20

def test_v08_baseline_is_root_and_v10_is_current_head():
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert len(script.get_heads())==1
    baseline=script.get_revision("0001_glip_baseline_v08")
    assert baseline.down_revision is None
