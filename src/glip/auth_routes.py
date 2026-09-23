from __future__ import annotations

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .native_auth import authenticate_native, revoke_session


router=APIRouter(prefix="/api/v1/auth",tags=["auth"])


class NativeLoginRequest(BaseModel):
    tenant_id: str
    email: str
    password: str


@router.get("/mode")
def auth_mode():
    return {
        "mode":settings.auth_mode,
        "native_session":settings.auth_mode=="native_session",
        "self_registration":False,
        "tenant_required":True,
    }


@router.post("/login")
def login(request:Request,body:NativeLoginRequest,db:Session=Depends(get_db)):
    if settings.environment in {"staging","production"}:
        origin=request.headers.get("origin")
        if origin and origin not in settings.cors_list:
            raise HTTPException(403,"csrf_origin_rejected")
    result=authenticate_native(
        db,
        tenant_id=body.tenant_id,
        email=str(body.email),
        password=body.password,
    )
    response=JSONResponse({
        "status":"authenticated",
        "tenant_id":result.membership.tenant_id,
        "subject":result.membership.external_subject,
        "role":result.membership.role,
        "display_name":result.membership.display_name,
    })
    response.set_cookie(
        settings.auth_session_cookie_name,
        result.raw_session_token,
        httponly=True,
        secure=settings.environment in {"staging","production"},
        samesite="strict",
        max_age=settings.auth_session_ttl_seconds,
        path="/",
    )
    return response


@router.post("/logout")
def logout(request:Request,db:Session=Depends(get_db)):
    revoke_session(
        db,
        raw_token=request.cookies.get(settings.auth_session_cookie_name) or "",
    )
    response=JSONResponse({"status":"logged_out"})
    response.delete_cookie(
        settings.auth_session_cookie_name,
        path="/",
        samesite="strict",
        secure=settings.environment in {"staging","production"},
    )
    return response
