from sqlalchemy.orm import Session
from .models import ProjectAuditEvent

def emit(db: Session, *, tenant_id: str, actor_id: str, event_type: str,
         project_id: str|None=None, correlation_id: str|None=None, payload: dict|None=None):
    db.add(ProjectAuditEvent(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        event_type=event_type,
        correlation_id=correlation_id,
        payload=payload or {},
    ))
