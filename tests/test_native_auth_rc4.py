from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select
from glip.config import settings
from glip.models import Membership, NativeAuthEvent, NativeAuthSession, NativeCredential, Tenant
from glip.native_auth import new_password_record

PASSWORD="Correct-Horse-Battery-777"

def configure(monkeypatch):
    monkeypatch.setattr(settings,"auth_mode","native_session")
    monkeypatch.setattr(settings,"auth_session_secret","s"*40)
    monkeypatch.setattr(settings,"auth_password_pepper","p"*40)
    monkeypatch.setattr(settings,"auth_session_ttl_seconds",3600)
    monkeypatch.setattr(settings,"auth_idle_ttl_seconds",900)
    monkeypatch.setattr(settings,"auth_session_touch_interval_seconds",60)

def seed(db,tenant_id="tenant-native",email="owner@example.com",password=PASSWORD,active=True):
    credential_id=str(uuid4()); membership_id=str(uuid4())
    db.add(Tenant(id=tenant_id,name="Native Tenant"))
    membership=Membership(
        id=membership_id,tenant_id=tenant_id,external_subject=f"native:{credential_id}",
        display_name="Owner",role="owner",active=active,
    )
    salt,hashed=new_password_record(password)
    credential=NativeCredential(
        id=credential_id,tenant_id=tenant_id,membership_id=membership_id,
        email_normalized=email,password_salt_b64=salt,password_hash_b64=hashed,active=active,
    )
    db.add_all([membership,credential]); db.commit()
    return credential,membership

def login(client,tenant="tenant-native",email="owner@example.com",password=PASSWORD):
    return client.post("/api/v1/auth/login",json={"tenant_id":tenant,"email":email,"password":password})

def test_native_login_me_logout(client,db,monkeypatch):
    configure(monkeypatch); seed(db)
    r=login(client,email="OWNER@example.com")
    assert r.status_code==200
    assert "glip_session=" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]
    assert client.get("/api/v1/me").json()["tenant_id"]=="tenant-native"
    assert client.post("/api/v1/auth/logout").status_code==200
    assert client.get("/api/v1/me").status_code==401

@pytest.mark.parametrize("tenant,email,password",[
    ("tenant-wrong","owner@example.com",PASSWORD),
    ("tenant-native","missing@example.com",PASSWORD),
    ("tenant-native","owner@example.com","wrong-password-123"),
])
def test_invalid_identity_inputs_are_uniform(client,db,monkeypatch,tenant,email,password):
    configure(monkeypatch); seed(db)
    r=login(client,tenant,email,password)
    assert r.status_code==401
    assert r.json()["detail"]=="invalid_credentials"

def test_inactive_identity_is_uniform(client,db,monkeypatch):
    configure(monkeypatch); seed(db,active=False)
    r=login(client)
    assert r.status_code==401
    assert r.json()["detail"]=="invalid_credentials"

def test_failed_login_event_uses_hash_not_email(client,db,monkeypatch):
    configure(monkeypatch); seed(db)
    login(client,password="wrong-password-123")
    event=db.scalar(select(NativeAuthEvent).where(NativeAuthEvent.event_code=="LOGIN_REJECTED"))
    assert event is not None
    assert len(event.identity_fingerprint)==64
    assert "owner@example.com" not in event.identity_fingerprint

def test_absolute_expired_session_fails_closed(client,db,monkeypatch):
    configure(monkeypatch); credential,_=seed(db); login(client)
    s=db.scalar(select(NativeAuthSession).where(NativeAuthSession.credential_id==credential.id))
    s.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    assert client.get("/api/v1/me").status_code==401

def test_idle_expired_session_fails_closed(client,db,monkeypatch):
    configure(monkeypatch); credential,_=seed(db); login(client)
    s=db.scalar(select(NativeAuthSession).where(NativeAuthSession.credential_id==credential.id))
    s.idle_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    assert client.get("/api/v1/me").status_code==401

def test_session_tenant_binding_fails_closed(client,db,monkeypatch):
    configure(monkeypatch); credential,_=seed(db); login(client)
    s=db.scalar(select(NativeAuthSession).where(NativeAuthSession.credential_id==credential.id))
    s.tenant_id="tenant-other"; db.commit()
    assert client.get("/api/v1/me").status_code==401

def test_no_public_registration_route(client,monkeypatch):
    configure(monkeypatch)
    assert client.post("/api/v1/auth/register",json={}).status_code==404

def test_mode_declares_native_tenant_required(client,monkeypatch):
    configure(monkeypatch)
    assert client.get("/api/v1/auth/mode").json()=={
        "mode":"native_session","native_session":True,"self_registration":False,"tenant_required":True,
    }

def test_foreign_origin_blocks_cookie_write(client,db,monkeypatch):
    configure(monkeypatch); seed(db); login(client)
    monkeypatch.setattr(settings,"environment","staging")
    monkeypatch.setattr(settings,"cors_origins","https://glip.example")
    r=client.post("/api/v1/clients",headers={"Origin":"https://evil.example"},json={"name":"Blocked"})
    assert r.status_code==403
    assert r.json()["detail"]=="csrf_origin_rejected"

def test_allowed_origin_allows_cookie_write(client,db,monkeypatch):
    configure(monkeypatch); seed(db); login(client)
    monkeypatch.setattr(settings,"environment","staging")
    monkeypatch.setattr(settings,"cors_origins","https://glip.example")
    r=client.post("/api/v1/clients",headers={"Origin":"https://glip.example"},json={"name":"Allowed"})
    assert r.status_code==201


def test_password_record_is_salted_and_not_plaintext(monkeypatch):
    configure(monkeypatch)
    salt_a,hash_a=new_password_record(PASSWORD)
    salt_b,hash_b=new_password_record(PASSWORD)
    assert salt_a!=salt_b
    assert hash_a!=hash_b
    assert PASSWORD not in hash_a
    assert PASSWORD not in hash_b


def test_production_login_cookie_is_secure_strict(client,db,monkeypatch):
    configure(monkeypatch); seed(db)
    monkeypatch.setattr(settings,"environment","production")
    monkeypatch.setattr(settings,"cors_origins","https://glip.example")
    r=login(client)
    assert r.status_code==200
    cookie=r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie


def test_raw_session_token_is_not_persisted(client,db,monkeypatch):
    configure(monkeypatch); credential,_=seed(db)
    r=login(client)
    raw_cookie=r.headers["set-cookie"].split("glip_session=",1)[1].split(";",1)[0]
    session=db.scalar(select(NativeAuthSession).where(NativeAuthSession.credential_id==credential.id))
    assert raw_cookie!=session.token_digest
    assert len(session.token_digest)==64


def test_backend_human_auth_source_contains_no_oidc_or_jwks_contract():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    source="\n".join(
        (root/path).read_text(encoding="utf-8")
        for path in [
            "src/glip/auth.py",
            "src/glip/auth_routes.py",
            "src/glip/native_auth.py",
            ".env.example",
        ]
    ).lower()
    assert "oidc" not in source
    assert "jwks" not in source
    assert "authorization_url" not in source
    assert "client_secret" not in source


def test_repeated_failures_lock_credential_but_external_error_stays_uniform(client,db,monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings,"auth_max_failed_attempts",3)
    monkeypatch.setattr(settings,"auth_lockout_seconds",900)
    credential,_=seed(db)

    for _ in range(3):
        r=login(client,password="wrong-password-123")
        assert r.status_code==401
        assert r.json()["detail"]=="invalid_credentials"

    db.refresh(credential)
    assert credential.failed_attempts==3
    assert credential.locked_until is not None

    # Even the correct password stays externally indistinguishable while locked.
    r=login(client,password=PASSWORD)
    assert r.status_code==401
    assert r.json()["detail"]=="invalid_credentials"


def test_expired_lock_allows_correct_password_and_clears_failure_state(client,db,monkeypatch):
    configure(monkeypatch)
    credential,_=seed(db)
    credential.failed_attempts=8
    credential.locked_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    db.commit()

    r=login(client,password=PASSWORD)
    assert r.status_code==200
    db.refresh(credential)
    assert credential.failed_attempts==0
    assert credential.locked_until is None


def test_foreign_origin_is_rejected_on_native_login_in_production(client,db,monkeypatch):
    configure(monkeypatch); seed(db)
    monkeypatch.setattr(settings,"environment","production")
    monkeypatch.setattr(settings,"cors_origins","https://glip.example")
    r=client.post(
        "/api/v1/auth/login",
        headers={"Origin":"https://evil.example"},
        json={"tenant_id":"tenant-native","email":"owner@example.com","password":PASSWORD},
    )
    assert r.status_code==403
    assert r.json()["detail"]=="csrf_origin_rejected"


def test_allowed_origin_login_succeeds_in_production(client,db,monkeypatch):
    configure(monkeypatch); seed(db)
    monkeypatch.setattr(settings,"environment","production")
    monkeypatch.setattr(settings,"cors_origins","https://glip.example")
    r=client.post(
        "/api/v1/auth/login",
        headers={"Origin":"https://glip.example"},
        json={"tenant_id":"tenant-native","email":"owner@example.com","password":PASSWORD},
    )
    assert r.status_code==200
