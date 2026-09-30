from __future__ import annotations

from sqlalchemy.orm import Session

from .access_models import TenantAuditEvent


_ALLOWED_FIELDS = {
    "invitation.created":{"invitation_id","email_masked","role","token_version","expires_at"},
    "invitation.rotated":{"invitation_id","token_version","expires_at"},
    "invitation.reissued":{"invitation_id","token_version","expires_at"},
    "invitation.revoked":{"invitation_id","token_version"},
    "invitation.expired":{"invitation_id","token_version"},
    "invitation.accepted":{"invitation_id","membership_id","role"},
}


def emit_tenant_audit(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    event_type: str,
    target_type: str|None=None,
    target_id: str|None=None,
    correlation_id: str|None=None,
    payload: dict|None=None,
) -> None:
    allowed=_ALLOWED_FIELDS.get(event_type,set())
    raw=payload or {}
    safe={key:raw[key] for key in allowed if key in raw}
    db.add(TenantAuditEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        payload=safe,
    ))
