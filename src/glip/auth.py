from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Membership
from .native_auth import authenticate_session


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    role: str
    display_name: str | None = None


def _membership(db:Session,subject:str,tenant:str)->Membership:
    membership=db.scalar(select(Membership).where(
        Membership.external_subject==subject,
        Membership.tenant_id==tenant,
        Membership.active.is_(True),
    ))
    if membership is None:
        raise HTTPException(403,"principal_not_provisioned")
    return membership


def get_principal(
    request:Request,
    x_glip_user_id:str|None=Header(None),
    x_glip_tenant_id:str|None=Header(None),
    db:Session=Depends(get_db),
):
    if settings.auth_mode=="dev_headers":
        if settings.environment not in {"development","test"}:
            raise HTTPException(500,"dev_headers_forbidden")
        if not x_glip_user_id or not x_glip_tenant_id:
            raise HTTPException(401,"missing_dev_identity")
        membership=_membership(db,x_glip_user_id,x_glip_tenant_id)
        return Principal(
            membership.external_subject,
            membership.tenant_id,
            membership.role,
            membership.display_name,
        )

    if settings.auth_mode!="native_session":
        raise HTTPException(500,"unsupported_auth_mode")

    raw=request.cookies.get(settings.auth_session_cookie_name)
    membership,_=authenticate_session(db,raw_token=raw or "")
    return Principal(
        membership.external_subject,
        membership.tenant_id,
        membership.role,
        membership.display_name,
    )
