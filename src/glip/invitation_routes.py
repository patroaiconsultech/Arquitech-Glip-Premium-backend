"""Public one-time invitation activation; token never stored in plaintext."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Membership, NativeCredential, TenantAuditEvent, UserInvitation
from .native_auth import new_password_record

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])


class AcceptRequest(BaseModel):
    token: str
    password: str


def _time(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.post("/accept")
def accept_invitation(
    body: AcceptRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    # Refuse oversize/ill-shaped inputs before querying; generic invalid response.
    if not (32 <= len(body.token) <= 256):
        raise HTTPException(404, "invitation_unavailable")
    digest = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    row = db.scalar(
        select(UserInvitation)
        .where(UserInvitation.token_digest == digest)
        .with_for_update()
    )
    current = datetime.now(timezone.utc)
    if row is None or row.status != "pending" or _time(row.expires_at) <= current:
        raise HTTPException(404, "invitation_unavailable")
    if row.role != "member":
        raise HTTPException(409, "invitation_role_unsupported")

    if db.scalar(
        select(NativeCredential.id).where(
            NativeCredential.tenant_id == row.tenant_id,
            NativeCredential.email_normalized == row.email_normalized,
        )
    ):
        raise HTTPException(409, "account_already_exists")
    try:
        salt_b64, hash_b64 = new_password_record(body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    cred_id = str(uuid4())
    membership_id = str(uuid4())
    membership = Membership(
        id=membership_id, tenant_id=row.tenant_id,
        external_subject=f"native:{cred_id}",
        display_name=row.display_name or row.email_normalized.split("@")[0],
        role="member", active=True,
    )
    credential = NativeCredential(
        id=cred_id, tenant_id=row.tenant_id, membership_id=membership_id,
        email_normalized=row.email_normalized,
        password_salt_b64=salt_b64, password_hash_b64=hash_b64,
        active=True, failed_attempts=0,
    )
    db.add(membership)
    db.flush()
    db.add(credential)
    row.status = "accepted"
    row.accepted_membership_id = membership_id
    row.accepted_at = current
    db.add(TenantAuditEvent(
        id=str(uuid4()), tenant_id=row.tenant_id, actor_id=f"invite:{row.id}",
        event_type="invitation_accepted", target_type="membership",
        target_id=membership_id, payload={"role": "member"},
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "invitation_conflict") from exc
    response.headers["Cache-Control"] = "no-store"
    return {"status": "activated", "tenant_id": row.tenant_id}
