from datetime import datetime, timedelta, timezone

from glip.config import settings
from glip.models import Membership, Tenant, NativeCredential, UserInvitation
from glip.native_auth import verify_password


PASSWORD = "VerySecureUniquePassphrase#2026"


def seed(db, tenant, subject, role="owner"):
    db.add(Tenant(id=tenant, name=tenant))
    db.add(Membership(tenant_id=tenant, external_subject=subject, role=role, active=True))
    db.commit()
    return {"X-GLIP-Tenant-ID": tenant, "X-GLIP-User-ID": subject}


def invite(client, header, email="sabrina@example.com"):
    return client.post("/api/v1/admin/invitations", headers=header, json={
        "email": email, "display_name": "Sabrina"
    })


def test_owner_invite_accept_member_and_one_time(client, db, monkeypatch):
    monkeypatch.setattr(settings, "auth_password_pepper", "x" * 40)
    h=seed(db,"ten-a","native:owner")
    r=invite(client,h)
    assert r.status_code==201, r.text
    secret=r.json()["activation_token"]
    assert len(secret)>32 and "sabrina" not in secret
    dbrow=db.query(UserInvitation).filter_by(tenant_id="ten-a").one()
    assert secret != dbrow.token_digest
    assert dbrow.role=="member"
    listing=client.get("/api/v1/admin/invitations",headers=h)
    assert listing.status_code==200
    assert "activation_token" not in listing.text
    accept=client.post("/api/v1/invitations/accept",json={"token":secret,"password":PASSWORD})
    assert accept.status_code==200, accept.text
    assert accept.json()["tenant_id"]=="ten-a"
    member=db.query(Membership).filter_by(tenant_id="ten-a",role="member").one()
    credential=db.query(NativeCredential).filter_by(membership_id=member.id).one()
    assert credential.email_normalized=="sabrina@example.com"
    assert credential.password_hash_b64 != PASSWORD
    assert verify_password(PASSWORD,credential)
    assert member.external_subject == "native:"+credential.id
    assert client.post("/api/v1/invitations/accept",json={"token":secret,"password":PASSWORD}).status_code==404


def test_non_owner_cannot_invite_or_list(client,db):
    h=seed(db,"tenant-2","subject-2","member")
    assert client.get("/api/v1/admin/users",headers=h).status_code==403
    assert client.get("/api/v1/admin/invitations",headers=h).status_code==403
    assert invite(client,h).status_code==403


def test_cross_tenant_isolation(client,db):
    a=seed(db,"tenant-a","owner-a")
    b=seed(db,"tenant-b","owner-b")
    r=invite(client,a)
    assert r.status_code==201
    token_id=r.json()["id"]
    assert client.get("/api/v1/admin/invitations",headers=b).json()==[]
    assert client.post(f"/api/v1/admin/invitations/{token_id}/revoke",headers=b).status_code==404
    assert client.get("/api/v1/admin/users",headers=b).status_code==200


def test_revoked_or_expired_tokens_are_not_accepted(client,db,monkeypatch):
    monkeypatch.setattr(settings,"auth_password_pepper","x"*40)
    h=seed(db,"t-revoke","owner-x")
    r=invite(client,h)
    secret=r.json()["activation_token"]
    id_=r.json()["id"]
    assert client.post(f"/api/v1/admin/invitations/{id_}/revoke",headers=h).status_code==200
    assert client.post("/api/v1/invitations/accept",json={"token":secret,"password":PASSWORD}).status_code==404
    renewed=invite(client,h)
    assert renewed.status_code==201
    assert renewed.json()["activation_token"]!=secret
    obj=db.query(UserInvitation).filter_by(id=id_).one()
    obj.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    db.commit()
    assert client.post("/api/v1/invitations/accept",
                       json={"token":renewed.json()["activation_token"],"password":PASSWORD}).status_code==404


def test_duplicate_invite_and_invalid_password_fail_closed(client,db,monkeypatch):
    monkeypatch.setattr(settings,"auth_password_pepper","x"*40)
    h=seed(db,"t-one","owner-y")
    first=invite(client,h)
    assert first.status_code==201
    assert invite(client,h).status_code==409
    assert client.post("/api/v1/invitations/accept",
                       json={"token":first.json()["activation_token"],"password":"short"}).status_code==422
    assert not db.query(NativeCredential).filter_by(tenant_id="t-one").count()
    assert db.query(UserInvitation).filter_by(tenant_id="t-one").one().status=="pending"


def test_invitation_token_not_leaked_in_list_or_audit(client,db):
    h=seed(db,"t-clean","owner")
    r=invite(client,h)
    assert r.status_code==201
    raw=r.json()["activation_token"]
    assert raw not in client.get("/api/v1/admin/invitations",headers=h).text
    assert raw not in client.get("/api/v1/admin/users",headers=h).text
    from glip.models import TenantAuditEvent
    assert raw not in str([(a.payload,a.actor_id) for a in db.query(TenantAuditEvent).all()])

def test_production_like_cookie_owner_to_invite_to_new_user_login(client,db,monkeypatch):
    from uuid import uuid4
    from glip.native_auth import new_password_record

    monkeypatch.setattr(settings,"auth_mode","native_session")
    monkeypatch.setattr(settings,"auth_session_secret","s"*40)
    monkeypatch.setattr(settings,"auth_password_pepper","p"*40)
    monkeypatch.setattr(settings,"auth_session_ttl_seconds",3600)
    monkeypatch.setattr(settings,"auth_idle_ttl_seconds",900)
    monkeypatch.setattr(settings,"auth_session_touch_interval_seconds",60)
    db.add(Tenant(id="prod-like",name="Production-like"))
    cid=str(uuid4())
    member=Membership(
        id=str(uuid4()),tenant_id="prod-like",external_subject="native:"+cid,
        role="owner",active=True,display_name="Owner",
    )
    salt,digest=new_password_record(PASSWORD)
    db.add(member)
    db.add(NativeCredential(
        id=cid,tenant_id="prod-like",membership_id=member.id,email_normalized="owner@example.com",
        password_salt_b64=salt,password_hash_b64=digest,active=True,
    ))
    db.commit()
    login=client.post("/api/v1/auth/login",json={
        "tenant_id":"prod-like","email":"owner@example.com","password":PASSWORD,
    })
    assert login.status_code==200,login.text
    inv=client.post("/api/v1/admin/invitations",
                    json={"email":"new@example.com","display_name":"Sabrina"})
    assert inv.status_code==201,inv.text
    created=client.post("/api/v1/invitations/accept",json={
        "token":inv.json()["activation_token"],"password":PASSWORD+"2",
    })
    assert created.status_code==200,created.text
    client.post("/api/v1/auth/logout")
    login2=client.post("/api/v1/auth/login",json={
        "tenant_id":"prod-like","email":"new@example.com","password":PASSWORD+"2",
    })
    assert login2.status_code==200,login2.text
    assert client.get("/api/v1/admin/users").status_code==403
    assert client.get("/api/v1/me").json()["role"]=="member"



def test_tenant_quota_durable_across_revoked_reissues(client, db):
    from glip.models import InvitationRateLimitBucket
    h = seed(db, "tenant-quota", "owner-quota")
    ids = []
    for i in range(10):
        result = invite(client, h, email=f"person{i}@example.com")
        assert result.status_code == 201, result.text
        ids.append(result.json()["id"])
    blocked = invite(client, h, email="number11@example.com")
    assert blocked.status_code == 429, blocked.text
    assert db.query(InvitationRateLimitBucket).one().count == 10

    # Revocation does not restore quota.
    assert client.post(f"/api/v1/admin/invitations/{ids[0]}/revoke", headers=h).status_code == 200
    again = invite(client, h, email="person0@example.com")
    assert again.status_code == 429, again.text


def test_invite_quota_tenant_isolation(client, db):
    from glip.models import InvitationRateLimitBucket
    a = seed(db, "tenant-quota-a", "owner-a")
    b = seed(db, "tenant-quota-b", "owner-b")
    for i in range(10):
        assert invite(client, a, f"a{i}@example.com").status_code == 201
    assert invite(client, a, "more@example.com").status_code == 429
    assert invite(client, b, "more@example.com").status_code == 201
    assert db.query(InvitationRateLimitBucket).count() == 2



def test_cookie_owner_invitation_requires_trusted_origin(client, db, monkeypatch):
    """Staging/production session writes reject missing and cross-origin headers."""
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from glip.main import app
    from glip.native_auth import new_password_record

    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "cors_origins", "https://app.example")
    monkeypatch.setattr(settings, "auth_mode", "native_session")
    monkeypatch.setattr(settings, "auth_session_secret", "s" * 40)
    monkeypatch.setattr(settings, "auth_password_pepper", "p" * 40)

    db.add(Tenant(id="csrf-test", name="CSRF Test"))
    cred_id = str(uuid4())
    member = Membership(
        id=str(uuid4()), tenant_id="csrf-test", external_subject="native:" + cred_id,
        role="owner", active=True, display_name="Owner",
    )
    salt, digest = new_password_record(PASSWORD)
    db.add(member)
    db.add(NativeCredential(
        id=cred_id, tenant_id="csrf-test", membership_id=member.id,
        email_normalized="owner@example.com", password_salt_b64=salt,
        password_hash_b64=digest, active=True,
    ))
    db.commit()

    with TestClient(app, base_url="https://app.example") as secure_client:
        login = secure_client.post("/api/v1/auth/login", headers={"origin": "https://app.example"}, json={
            "tenant_id": "csrf-test", "email": "owner@example.com", "password": PASSWORD,
        })
        assert login.status_code == 200, login.text
        body = {"email": "invited@example.com", "display_name": "Invited"}
        assert secure_client.post("/api/v1/admin/invitations", json=body).status_code == 403
        assert secure_client.post(
            "/api/v1/admin/invitations",
            headers={"origin": "https://evil.example"}, json=body,
        ).status_code == 403
        accepted = secure_client.post(
            "/api/v1/admin/invitations",
            headers={"origin": "https://app.example"}, json=body,
        )
        assert accepted.status_code == 201, accepted.text
