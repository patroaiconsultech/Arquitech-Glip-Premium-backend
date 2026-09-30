from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access_models import UserInvitation
from .database import get_db
from .invitation_service import (
    as_utc,
    consume_rate_limit,
    create_identity_from_invitation,
    effective_status,
    invitation_for_update_by_token,
    materialize_expiry,
    token_digest,
    utcnow,
)
from .models import Tenant


router=APIRouter(prefix="/api/v1/auth/invitations",tags=["auth"])


class InspectRequest(BaseModel):
    token: str=Field(min_length=32,max_length=256)


class ActivateRequest(InspectRequest):
    password: str=Field(min_length=1,max_length=256)


def _sensitive(payload: dict, *, status_code: int=200) -> JSONResponse:
    response=JSONResponse(payload,status_code=status_code)
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"
    response.headers["Referrer-Policy"]="no-referrer"
    return response


def _client_key(request:Request) -> str:
    host=request.client.host if request.client else "unknown"
    return host[:128]


@router.post("/inspect")
def inspect_invitation(
    request:Request,
    body:InspectRequest,
    db:Session=Depends(get_db),
):
    client_key=_client_key(request)
    digest=token_digest(body.token)
    consume_rate_limit(db,key=f"invite-inspect-client:{client_key}",limit=60)
    consume_rate_limit(db,key=f"invite-inspect-token:{client_key}:{digest}",limit=12)
    invitation=db.scalar(select(UserInvitation).where(UserInvitation.token_digest==digest))
    if invitation is None:
        raise HTTPException(404,"invitation_not_found")
    tenant=db.get(Tenant,invitation.tenant_id)
    status=effective_status(invitation)
    if status!="pending":
        return _sensitive({"detail":"invitation_unavailable"},status_code=410)
    return _sensitive({
        "status":"pending",
        "tenant_id":invitation.tenant_id,
        "tenant_name":tenant.name if tenant else invitation.tenant_id,
        "email":invitation.email_normalized,
        "display_name":invitation.display_name,
        "role":invitation.role,
        "expires_at":invitation.expires_at.isoformat() if invitation.expires_at else None,
    })


@router.post("/activate")
def activate_invitation(
    request:Request,
    body:ActivateRequest,
    db:Session=Depends(get_db),
):
    client_key=_client_key(request)
    digest=token_digest(body.token)
    consume_rate_limit(db,key=f"invite-activate-client:{client_key}",limit=30)
    consume_rate_limit(db,key=f"invite-activate-token:{client_key}:{digest}",limit=8)
    invitation=invitation_for_update_by_token(db,digest=digest)

    if materialize_expiry(
        db,
        invitation=invitation,
        correlation_id=getattr(request.state,"correlation_id",None),
    ):
        db.commit()
        raise HTTPException(410,"invitation_expired")

    if invitation.status=="revoked":
        raise HTTPException(410,"invitation_revoked")
    if invitation.status=="accepted":
        raise HTTPException(409,"invitation_already_accepted")
    if invitation.status!="pending":
        raise HTTPException(409,"invitation_terminal")

    try:
        membership,_=create_identity_from_invitation(
            db,
            invitation=invitation,
            password=body.password,
            correlation_id=getattr(request.state,"correlation_id",None),
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    return _sensitive({
        "status":"activated",
        "tenant_id":invitation.tenant_id,
        "email":invitation.email_normalized,
        "membership_id":membership.id,
        "role":membership.role,
        "login_required":True,
    })
