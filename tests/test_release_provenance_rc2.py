from pathlib import Path
import json
import tomllib

from alembic.config import Config
from alembic.script import ScriptDirectory

from glip.readiness import EXPECTED_MIGRATION_HEAD

ROOT=Path(__file__).resolve().parents[1]


def test_current_package_release_readiness_and_alembic_head_are_aligned():
    pyproject=tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))
    release=json.loads((ROOT/"release-manifest.template.json").read_text(encoding="utf-8"))
    source=json.loads((ROOT/"SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    main=(ROOT/"src/glip/main.py").read_text(encoding="utf-8")
    script=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))

    assert pyproject["project"]["version"]=="1.0.0rc8"
    assert release["version"]=="1.0.0rc8"
    assert source["version"]=="1.0.0rc8"
    assert 'version="1.0.0rc8"' in main
    assert script.get_heads()==[EXPECTED_MIGRATION_HEAD]
    assert release["migration_head"]==EXPECTED_MIGRATION_HEAD
    assert source["migration_head"]==EXPECTED_MIGRATION_HEAD
    assert source["candidate_label"]==release["candidate_label"]
    assert EXPECTED_MIGRATION_HEAD=="0009_glip_pricing_authority_hardening"


def test_release_template_keeps_orkio_contract_versioned_without_runtime_claim():
    release=json.loads((ROOT/"release-manifest.template.json").read_text(encoding="utf-8"))
    target=release["orkio_contract"]
    assert target["request"]=="ORKIO-CAPABILITY-REQUEST-1"
    assert target["response"]=="ORKIO-RESPONSE-1"
    assert target["real_wire"]=="NOT_PROVEN"
