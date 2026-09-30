from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access_audit import emit_tenant_audit
from .access_models import InvitationRateLimitBucket, UserInvitation
from .config import settings
from .models import Membership, NativeCredential, Tenant, uid
from .native_auth import new_password_record, normalize_email, valid_email_shape


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime|None) -> datetime|None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def invitation_ttl_seconds() -> int:
    try:
        return max(900,min(int(os.getenv("GLIP_INVITATION_TTL_SECONDS","604800")),2_592_000))
    except ValueError:
        return 604800


def public_app_url() -> str:
    value=os.getenv("GLIP_PUBLIC_APP_URL","").strip().rstrip("/")
    if not value:
        raise HTTPException(503,"invitation_public_app_url_not_configured")
    if settings.environment=="production" and not value.startswith("https://"):
        raise HTTPException(500,"invitation_public_app_url_must_be_https")
    return value


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_token() -> tuple[str,str]:
    raw=secrets.token_urlsafe(48)
    return raw,token_digest(raw)


def activation_url(raw_token: str) -> str:
    return f"{public_app_url()}/activate#token={raw_token}"


def mask_email(email: str) -> str:
    local,domain=email.split("@",1)
    visible=(local[:2] if len(local)>1 else local[:1])
    return f"{visible}***@{domain}"


def effective_status(invitation: UserInvitation) -> str:
    if invitation.status=="pending":
        expiry=as_utc(invitation.expires_at)
        if expiry is not None and utcnow()>=expiry:
            return "expired"
    return invitation.status


def invitation_for_update_by_id(db: Session, *, tenant_id: str, invitation_id: str) -> UserInvitation:
    invitation=db.scalar(
        select(UserInvitation)
        .where(UserInvitation.id==invitation_id,UserInvitation.tenant_id==tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invitation is None:
        raise HTTPException(404,"invitation_not_found")
    return invitation


def invitation_for_update_by_token(db: Session, *, digest: str) -> UserInvitation:
    invitation=db.scalar(
        select(UserInvitation)
        .where(UserInvitation.token_digest==digest)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invitation is None:
        raise HTTPException(404,"invitation_not_found")
    return invitation


def persist_invitation_create(db: Session, invitation: UserInvitation) -> None:
    """Insert an invitation and convert the known tenant/email uniqueness race to 409."""
    try:
        db.add(invitation)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        winner=db.scalar(
            select(UserInvitation).where(
                UserInvitation.tenant_id==invitation.tenant_id,
                UserInvitation.email_normalized==invitation.email_normalized,
            )
        )
        if winner is not None:
            raise HTTPException(409,"invitation_already_exists") from exc
        raise


def materialize_expiry(
    db: Session,
    *,
    invitation: UserInvitation,
    correlation_id: str|None,
) -> bool:
    if invitation.status!="pending":
        return False
    expiry=as_utc(invitation.expires_at)
    if expiry is None or utcnow()<expiry:
        return False
    invitation.status="expired"
    emit_tenant_audit(
        db,
        tenant_id=invitation.tenant_id,
        actor_id="system:invitation-expiry",
        event_type="invitation.expired",
        target_type="user_invitation",
        target_id=invitation.id,
        correlation_id=correlation_id,
        payload={"invitation_id":invitation.id,"token_version":invitation.token_version},
    )
    return True


def consume_rate_limit(db: Session, *, key: str, limit: int) -> None:
    limit=max(1,limit)
    now=utcnow()
    window=now.replace(second=0,microsecond=0)
    digest=hashlib.sha256(key.encode("utf-8")).hexdigest()

    def locked():
        return db.scalar(
            select(InvitationRateLimitBucket)
            .where(
                InvitationRateLimitBucket.key_digest==digest,
                InvitationRateLimitBucket.window_started_at==window,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    row=locked()
    if row is None:
        db.add(InvitationRateLimitBucket(
            key_digest=digest,
            window_started_at=window,
            count=1,
        ))
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            row=locked()

    if row is None:
        raise HTTPException(429,"rate_limited")
    if int(row.count or 0)>=limit:
        db.rollback()
        raise HTTPException(429,"rate_limited")
    row.count=int(row.count or 0)+1
    db.commit()


def create_identity_from_invitation(
    db: Session,
    *,
    invitation: UserInvitation,
    password: str,
    correlation_id: str|None,
) -> tuple[Membership,NativeCredential]:
    email=normalize_email(invitation.email_normalized)
    if not valid_email_shape(email):
        raise HTTPException(422,"invalid_email")

    existing=db.scalar(select(NativeCredential).where(
        NativeCredential.tenant_id==invitation.tenant_id,
        NativeCredential.email_normalized==email,
    ))
    if existing is not None:
        raise HTTPException(409,"membership_identity_conflict")

    try:
        salt_b64,hash_b64=new_password_record(password)
    except ValueError as exc:
        detail="password_policy_violation"
        if str(exc) in {"password_too_short","password_too_long"}:
            detail=str(exc)
        raise HTTPException(422,detail) from exc

    credential_id=uid()
    membership_id=uid()
    membership=Membership(
        id=membership_id,
        tenant_id=invitation.tenant_id,
        external_subject=f"native:{credential_id}",
        display_name=invitation.display_name,
        role=invitation.role,
        active=True,
    )
    credential=NativeCredential(
        id=credential_id,
        tenant_id=invitation.tenant_id,
        membership_id=membership_id,
        email_normalized=email,
        password_salt_b64=salt_b64,
        password_hash_b64=hash_b64,
        active=True,
        failed_attempts=0,
    )
    db.add(membership)
    db.add(credential)
    db.flush()

    invitation.status="accepted"
    invitation.accepted_at=utcnow()
    invitation.accepted_membership_id=membership.id
    emit_tenant_audit(
        db,
        tenant_id=invitation.tenant_id,
        actor_id=membership.external_subject,
        event_type="invitation.accepted",
        target_type="user_invitation",
        target_id=invitation.id,
        correlation_id=correlation_id,
        payload={
            "invitation_id":invitation.id,
            "membership_id":membership.id,
            "role":membership.role,
        },
    )
    return membership,credential
