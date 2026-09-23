from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Membership, NativeAuthEvent, NativeAuthSession, NativeCredential


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def valid_email_shape(value: str) -> bool:
    if not value or len(value)>320 or value.count("@")!=1:
        return False
    local,domain=value.rsplit("@",1)
    return bool(local and domain and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def validate_password_policy(password: str) -> None:
    if len(password) < settings.auth_password_min_length:
        raise ValueError("password_too_short")
    if len(password) > settings.auth_password_max_length:
        raise ValueError("password_too_long")


def _password_material(password: str) -> bytes:
    return hmac.new(
        settings.auth_password_pepper.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def derive_password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        _password_material(password),
        salt=salt,
        n=settings.auth_scrypt_n,
        r=settings.auth_scrypt_r,
        p=settings.auth_scrypt_p,
        dklen=64,
    )


def new_password_record(password: str) -> tuple[str, str]:
    validate_password_policy(password)
    salt=secrets.token_bytes(16)
    digest=derive_password_hash(password,salt)
    return (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


_DUMMY_SALT=b"GLIP-native-dmy1"


def verify_password(password: str, credential: NativeCredential | None) -> bool:
    if credential is None:
        expected=derive_password_hash("dummy-invalid-password",_DUMMY_SALT)
        candidate=derive_password_hash(password,_DUMMY_SALT)
        hmac.compare_digest(candidate,expected)
        return False

    try:
        salt=base64.b64decode(credential.password_salt_b64.encode("ascii"),validate=True)
        expected=base64.b64decode(credential.password_hash_b64.encode("ascii"),validate=True)
    except Exception:
        # Preserve comparable KDF work, then fail closed.
        derive_password_hash(password,_DUMMY_SALT)
        return False

    candidate=derive_password_hash(password,salt)
    return hmac.compare_digest(candidate,expected)


def session_digest(raw_token: str) -> str:
    return hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def identity_fingerprint(tenant_id: str, email_normalized: str) -> str:
    raw=f"{tenant_id}\n{email_normalized}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def credential_for_login_statement(*, tenant_id: str, email_normalized: str):
    """Lock and refresh the exact native credential for the login transaction.

    PostgreSQL serializes concurrent attempts for the same credential row.
    populate_existing is required so a waiter observes the state committed by
    the previous lock owner instead of stale Session identity-map values.
    """
    return (
        select(NativeCredential)
        .where(
            NativeCredential.tenant_id==tenant_id,
            NativeCredential.email_normalized==email_normalized,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def record_auth_event(
    db: Session,
    *,
    tenant_id: str | None,
    email_normalized: str,
    event_code: str,
    success: bool,
) -> None:
    db.add(NativeAuthEvent(
        tenant_id=tenant_id or None,
        identity_fingerprint=identity_fingerprint(tenant_id or "",email_normalized),
        event_code=event_code,
        success=success,
    ))


@dataclass(frozen=True)
class NativeLoginResult:
    raw_session_token: str
    membership: Membership
    expires_at: datetime


def authenticate_native(
    db: Session,
    *,
    tenant_id: str,
    email: str,
    password: str,
) -> NativeLoginResult:
    tenant_id=tenant_id.strip()
    email_normalized=normalize_email(email)
    if (
        not tenant_id
        or len(tenant_id)>64
        or not valid_email_shape(email_normalized)
        or not password
        or len(password)>settings.auth_password_max_length
    ):
        # Preserve password KDF work for malformed identities too.
        verify_password(password or "invalid-password",None)
        raise HTTPException(401,"invalid_credentials")

    credential=db.scalar(credential_for_login_statement(
        tenant_id=tenant_id,
        email_normalized=email_normalized,
    ))

    now=utcnow()
    locked=bool(
        credential
        and credential.locked_until is not None
        and as_utc(credential.locked_until) is not None
        and now < as_utc(credential.locked_until)
    )

    # Still perform KDF work before any rejection; lock status is not disclosed.
    password_ok=verify_password(password,credential)
    membership=None
    if credential is not None:
        membership=db.scalar(select(Membership).where(
            Membership.id==credential.membership_id,
            Membership.tenant_id==tenant_id,
        ))

    valid=bool(
        credential
        and not locked
        and password_ok
        and credential.active
        and membership
        and membership.active
        and membership.external_subject==f"native:{credential.id}"
    )

    if not valid:
        if credential is not None:
            if locked:
                event_code="LOGIN_REJECTED_LOCKED"
            else:
                credential.failed_attempts=int(credential.failed_attempts or 0)+1
                if credential.failed_attempts >= settings.auth_max_failed_attempts:
                    credential.locked_until=now+timedelta(seconds=settings.auth_lockout_seconds)
                    event_code="LOGIN_LOCKED"
                else:
                    event_code="LOGIN_REJECTED"
        else:
            event_code="LOGIN_REJECTED"
        record_auth_event(
            db,
            tenant_id=tenant_id or None,
            email_normalized=email_normalized,
            event_code=event_code,
            success=False,
        )
        db.commit()
        # Uniform external response: no tenant/user/password/active/lock enumeration.
        raise HTTPException(401,"invalid_credentials")

    credential.failed_attempts=0
    credential.locked_until=None
    credential.last_login_at=now

    raw_token=secrets.token_urlsafe(48)
    expires_at=now+timedelta(seconds=settings.auth_session_ttl_seconds)
    idle_expires_at=min(
        expires_at,
        now+timedelta(seconds=settings.auth_idle_ttl_seconds),
    )
    db.add(NativeAuthSession(
        tenant_id=tenant_id,
        credential_id=credential.id,
        membership_id=membership.id,
        token_digest=session_digest(raw_token),
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at,
        idle_expires_at=idle_expires_at,
    ))
    record_auth_event(
        db,
        tenant_id=tenant_id,
        email_normalized=email_normalized,
        event_code="LOGIN_SUCCESS",
        success=True,
    )
    db.commit()
    return NativeLoginResult(raw_token,membership,expires_at)


def authenticate_session(
    db: Session,
    *,
    raw_token: str,
) -> tuple[Membership, NativeAuthSession]:
    if not raw_token:
        raise HTTPException(401,"missing_session")

    digest=session_digest(raw_token)
    session=db.scalar(select(NativeAuthSession).where(
        NativeAuthSession.token_digest==digest,
        NativeAuthSession.revoked_at.is_(None),
    ))
    if session is None:
        raise HTTPException(401,"invalid_session")

    now=utcnow()
    expires_at=as_utc(session.expires_at)
    idle_expires_at=as_utc(session.idle_expires_at)
    if (
        expires_at is None
        or idle_expires_at is None
        or now>=expires_at
        or now>=idle_expires_at
    ):
        session.revoked_at=now
        db.commit()
        raise HTTPException(401,"expired_session")

    credential=db.get(NativeCredential,session.credential_id)
    membership=db.get(Membership,session.membership_id)
    if (
        credential is None
        or membership is None
        or not credential.active
        or not membership.active
        or credential.tenant_id!=session.tenant_id
        or membership.tenant_id!=session.tenant_id
        or membership.external_subject!=f"native:{credential.id}"
    ):
        session.revoked_at=now
        db.commit()
        raise HTTPException(401,"invalid_session_identity")

    last_seen=as_utc(session.last_seen_at) or now
    if (now-last_seen).total_seconds() >= settings.auth_session_touch_interval_seconds:
        session.last_seen_at=now
        session.idle_expires_at=min(
            expires_at,
            now+timedelta(seconds=settings.auth_idle_ttl_seconds),
        )
        db.commit()

    return membership,session


def revoke_session(db: Session, *, raw_token: str) -> None:
    if not raw_token:
        return
    digest=session_digest(raw_token)
    session=db.scalar(select(NativeAuthSession).where(
        NativeAuthSession.token_digest==digest,
        NativeAuthSession.revoked_at.is_(None),
    ))
    if session is not None:
        session.revoked_at=utcnow()
        db.commit()


def revoke_all_credential_sessions(db: Session, *, credential_id: str) -> int:
    sessions=db.scalars(select(NativeAuthSession).where(
        NativeAuthSession.credential_id==credential_id,
        NativeAuthSession.revoked_at.is_(None),
    )).all()
    now=utcnow()
    for session in sessions:
        session.revoked_at=now
    db.commit()
    return len(sessions)
