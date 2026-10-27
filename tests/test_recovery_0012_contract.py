"""Fail-closed consistency checks for the restored 0012 Alembic revision."""
import json
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

from glip.readiness import EXPECTED_MIGRATION_HEAD

ROOT=Path(__file__).resolve().parents[1]


def test_0012_is_the_only_declared_head_and_readiness_matches():
    scripts=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
    assert scripts.get_heads()==["0012_glip_invitation_access"]
    assert scripts.get_revision("0012_glip_invitation_access").down_revision=="0011_glip_chat_mvp"
    assert EXPECTED_MIGRATION_HEAD==scripts.get_heads()[0]
    for name in ("SOURCE_MANIFEST.json","release-manifest.template.json"):
        assert json.loads((ROOT/name).read_text(encoding="utf-8"))["migration_head"]==EXPECTED_MIGRATION_HEAD


def test_0012_schema_is_additive_and_has_guarded_downgrade():
    content=(ROOT/"migrations/versions/0012_glip_invitation_access.py").read_text(encoding="utf-8")
    import ast
    module=ast.parse(content)
    created={
        call.args[0].value
        for node in ast.walk(module)
        if isinstance(node,ast.Call)
        for call in [node]
        if isinstance(call.func,ast.Attribute)
        and isinstance(call.func.value,ast.Name)
        and call.func.value.id=="op"
        and call.func.attr=="create_table"
        and call.args and isinstance(call.args[0],ast.Constant)
    }
    assert {"user_invitations","tenant_audit_events","invitation_rate_limit_buckets"} <= created
    assert "GLIP_ALLOW_DESTRUCTIVE_ID01_DOWNGRADE" in content
    assert "id01_downgrade_blocked_nonempty_security_tables" in content
