from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access_audit import emit_tenant_audit
from .access_models import UserInvitation
from .auth import Principal, get_principal
from .authz import require_capability
from .database import get_db
from .invitation_service import (
    activation_url,
    consume_rate_limit,
    effective_status,
    invitation_for_update_by_id,
    invitation_ttl_seconds,
    mask_email,
    materialize_expiry,
    new_token,
    persist_invitation_create,
    utcnow,
)
from .models import Membership, NativeCredential
from .native_auth import normalize_email, valid_email_shape


router=APIRouter(prefix="/api/v1/admin",tags=["admin"])


class InvitationCreateRequest(BaseModel):
    email: str=Field(min_length=3,max_length=320)
    display_name: str|None=Field(default=None,max_length=200)
    role: str=Field(default="architect",max_length=64)


class VersionRequest(BaseModel):
    expected_token_version: int|None=None


def _expected_version(body: VersionRequest) -> int:
    value=body.expected_token_version
    if value is None:
        raise HTTPException(422,"missing_expected_token_version")
    if value < 1:
        raise HTTPException(422,"invalid_expected_token_version")
    return value


def _sensitive(payload: dict, *, status_code: int=200) -> JSONResponse:
    response=JSONResponse(payload,status_code=status_code)
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"
    response.headers["Referrer-Policy"]="no-referrer"
    return response


def _allowed_target_role(actor_role: str, target_role: str) -> bool:
    actor=actor_role.strip().lower()
    target=target_role.strip().lower()
    if actor=="owner":
        return target in {"admin","architect","member"}
    if actor=="admin":
        return target in {"architect","member"}
    return False


def _serialize_invitation(item: UserInvitation) -> dict:
    return {
        "id":item.id,
        "email":item.email_normalized,
        "display_name":item.display_name,
        "role":item.role,
        "status":effective_status(item),
        "token_version":item.token_version,
        "expires_at":item.expires_at.isoformat() if item.expires_at else None,
        "created_at":item.created_at.isoformat() if item.created_at else None,
        "accepted_at":item.accepted_at.isoformat() if item.accepted_at else None,
    }


@router.get("/memberships")
def list_memberships(
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"membership.list")
    rows=db.execute(
        select(Membership,NativeCredential)
        .outerjoin(
            NativeCredential,
            (NativeCredential.membership_id==Membership.id)
            & (NativeCredential.tenant_id==Membership.tenant_id),
        )
        .where(Membership.tenant_id==p.tenant_id)
        .order_by(Membership.created_at.asc())
    ).all()
    return [{
        "membership_id":membership.id,
        "display_name":membership.display_name,
        "role":membership.role,
        "active":membership.active,
        "email":credential.email_normalized if credential else None,
        "last_login_at":credential.last_login_at.isoformat() if credential and credential.last_login_at else None,
    } for membership,credential in rows]


@router.get("/invitations")
def list_invitations(
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"invitation.list")
    items=db.scalars(
        select(UserInvitation)
        .where(UserInvitation.tenant_id==p.tenant_id)
        .order_by(UserInvitation.created_at.desc())
    ).all()
    return [_serialize_invitation(item) for item in items]


@router.post("/invitations")
def create_invitation(
    request:Request,
    body:InvitationCreateRequest,
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"membership.invite")
    consume_rate_limit(db,key=f"admin-create:{p.tenant_id}:{p.subject}",limit=30)

    email=normalize_email(body.email)
    role=body.role.strip().lower()
    if not valid_email_shape(email):
        raise HTTPException(422,"invalid_email")
    if not _allowed_target_role(p.role,role):
        raise HTTPException(403,"role_escalation_denied")

    existing_credential=db.scalar(select(NativeCredential).where(
        NativeCredential.tenant_id==p.tenant_id,
        NativeCredential.email_normalized==email,
    ))
    if existing_credential is not None:
        raise HTTPException(409,"membership_identity_conflict")

    existing=db.scalar(
        select(UserInvitation)
        .where(
            UserInvitation.tenant_id==p.tenant_id,
            UserInvitation.email_normalized==email,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        if materialize_expiry(
            db,
            invitation=existing,
            correlation_id=getattr(request.state,"correlation_id",None),
        ):
            db.commit()
        raise HTTPException(409,"invitation_already_exists")

    raw,digest=new_token()
    invitation=UserInvitation(
        tenant_id=p.tenant_id,
        email_normalized=email,
        display_name=(body.display_name or "").strip() or None,
        role=role,
        token_digest=digest,
        token_version=1,
        status="pending",
        expires_at=utcnow()+timedelta(seconds=invitation_ttl_seconds()),
        invited_by=p.subject,
    )
    persist_invitation_create(db,invitation)
    emit_tenant_audit(
        db,
        tenant_id=p.tenant_id,
        actor_id=p.subject,
        event_type="invitation.created",
        target_type="user_invitation",
        target_id=invitation.id,
        correlation_id=getattr(request.state,"correlation_id",None),
        payload={
            "invitation_id":invitation.id,
            "email_masked":mask_email(email),
            "role":role,
            "token_version":1,
            "expires_at":invitation.expires_at.isoformat(),
        },
    )
    db.commit()
    return _sensitive({
        "status":"pending",
        "invitation_id":invitation.id,
        "token_version":1,
        "expires_at":invitation.expires_at.isoformat(),
        "activation_url":activation_url(raw),
    },status_code=201)


@router.post("/invitations/{invitation_id}/rotate")
def rotate_invitation(
    invitation_id:str,
    request:Request,
    body:VersionRequest,
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"invitation.rotate")
    invitation=invitation_for_update_by_id(db,tenant_id=p.tenant_id,invitation_id=invitation_id)
    if materialize_expiry(db,invitation=invitation,correlation_id=getattr(request.state,"correlation_id",None)):
        db.commit()
        raise HTTPException(410,"invitation_expired")
    if invitation.status!="pending":
        raise HTTPException(409,"invitation_terminal")
    expected_version=_expected_version(body)
    if invitation.token_version!=expected_version:
        raise HTTPException(409,"invitation_version_conflict")

    raw,digest=new_token()
    invitation.token_digest=digest
    invitation.token_version+=1
    invitation.expires_at=utcnow()+timedelta(seconds=invitation_ttl_seconds())
    emit_tenant_audit(
        db,tenant_id=p.tenant_id,actor_id=p.subject,event_type="invitation.rotated",
        target_type="user_invitation",target_id=invitation.id,
        correlation_id=getattr(request.state,"correlation_id",None),
        payload={"invitation_id":invitation.id,"token_version":invitation.token_version,"expires_at":invitation.expires_at.isoformat()},
    )
    db.commit()
    return _sensitive({
        "status":"pending","invitation_id":invitation.id,
        "token_version":invitation.token_version,
        "expires_at":invitation.expires_at.isoformat(),
        "activation_url":activation_url(raw),
    })


@router.post("/invitations/{invitation_id}/reissue")
def reissue_invitation(
    invitation_id:str,
    request:Request,
    body:VersionRequest,
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"invitation.reissue")
    invitation=invitation_for_update_by_id(db,tenant_id=p.tenant_id,invitation_id=invitation_id)
    materialized=materialize_expiry(db,invitation=invitation,correlation_id=getattr(request.state,"correlation_id",None))
    if invitation.status not in {"expired","revoked"}:
        if materialized:
            db.commit()
        raise HTTPException(409,"invitation_reissue_not_allowed")
    try:
        expected_version=_expected_version(body)
    except HTTPException:
        if materialized:
            db.commit()
        raise
    if invitation.token_version!=expected_version:
        if materialized:
            db.commit()
        raise HTTPException(409,"invitation_version_conflict")

    raw,digest=new_token()
    invitation.status="pending"
    invitation.token_digest=digest
    invitation.token_version+=1
    invitation.expires_at=utcnow()+timedelta(seconds=invitation_ttl_seconds())
    invitation.revoked_at=None
    invitation.accepted_at=None
    invitation.accepted_membership_id=None
    emit_tenant_audit(
        db,tenant_id=p.tenant_id,actor_id=p.subject,event_type="invitation.reissued",
        target_type="user_invitation",target_id=invitation.id,
        correlation_id=getattr(request.state,"correlation_id",None),
        payload={"invitation_id":invitation.id,"token_version":invitation.token_version,"expires_at":invitation.expires_at.isoformat()},
    )
    db.commit()
    return _sensitive({
        "status":"pending","invitation_id":invitation.id,
        "token_version":invitation.token_version,
        "expires_at":invitation.expires_at.isoformat(),
        "activation_url":activation_url(raw),
    })


@router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(
    invitation_id:str,
    request:Request,
    body:VersionRequest,
    p:Principal=Depends(get_principal),
    db:Session=Depends(get_db),
):
    require_capability(p,"invitation.revoke")
    invitation=invitation_for_update_by_id(db,tenant_id=p.tenant_id,invitation_id=invitation_id)
    if materialize_expiry(db,invitation=invitation,correlation_id=getattr(request.state,"correlation_id",None)):
        db.commit()
        raise HTTPException(410,"invitation_expired")
    if invitation.status!="pending":
        raise HTTPException(409,"invitation_terminal")
    expected_version=_expected_version(body)
    if invitation.token_version!=expected_version:
        raise HTTPException(409,"invitation_version_conflict")

    invitation.status="revoked"
    invitation.revoked_at=utcnow()
    emit_tenant_audit(
        db,tenant_id=p.tenant_id,actor_id=p.subject,event_type="invitation.revoked",
        target_type="user_invitation",target_id=invitation.id,
        correlation_id=getattr(request.state,"correlation_id",None),
        payload={"invitation_id":invitation.id,"token_version":invitation.token_version},
    )
    db.commit()
    return {"status":"revoked","invitation_id":invitation.id,"token_version":invitation.token_version}
