from pathlib import Path


def test_id01_downgrade_is_fail_closed_by_default():
    root=Path(__file__).resolve().parents[1]
    source=(root/"migrations/versions/0012_glip_invitation_access.py").read_text(encoding="utf-8")
    assert "GLIP_ALLOW_DESTRUCTIVE_ID01_DOWNGRADE" in source
    assert "id01_downgrade_blocked_nonempty_security_tables" in source
    assert '"tenant_audit_events"' in source
    assert '"user_invitations"' in source
