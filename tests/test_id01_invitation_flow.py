import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from glip.invitation_service import persist_invitation_create
from datetime import timedelta
from urllib.parse import urlsplit

from glip.access_models import TenantAuditEvent, UserInvitation
from glip.models import Membership, NativeCredential
from glip.invitation_service import utcnow


def _token_from_activation_url(value: str) -> str:
    fragment=urlsplit(value).fragment
    assert fragment.startswith("token=")
    return fragment.split("=",1)[1]


def test_owner_can_invite_activate_and_token_is_single_use(client,db,auth_a,monkeypatch):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    created=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":"sabrina@example.com",
        "display_name":"Sabrina",
        "role":"architect",
    })
    assert created.status_code==201
    assert created.headers["cache-control"]=="no-store"
    assert created.headers["referrer-policy"]=="no-referrer"
    token=_token_from_activation_url(created.json()["activation_url"])

    invitation=db.query(UserInvitation).filter_by(tenant_id="tenant-a",email_normalized="sabrina@example.com").one()
    assert token not in invitation.token_digest
    assert invitation.role=="architect"

    inspected=client.post("/api/v1/auth/invitations/inspect",json={"token":token})
    assert inspected.status_code==200
    assert inspected.json()["tenant_id"]=="tenant-a"
    assert inspected.json()["role"]=="architect"

    activated=client.post("/api/v1/auth/invitations/activate",json={
        "token":token,
        "password":"correct-horse-battery",
    })
    assert activated.status_code==200
    assert activated.json()["login_required"] is True

    membership=db.query(Membership).filter_by(tenant_id="tenant-a",display_name="Sabrina").one()
    credential=db.query(NativeCredential).filter_by(tenant_id="tenant-a",membership_id=membership.id).one()
    assert membership.role=="architect"
    assert membership.external_subject==f"native:{credential.id}"

    replay=client.post("/api/v1/auth/invitations/activate",json={
        "token":token,
        "password":"another-correct-password",
    })
    assert replay.status_code==409

    audit_rows=db.query(TenantAuditEvent).filter_by(tenant_id="tenant-a").all()
    serialized=" ".join(str(row.payload) for row in audit_rows)
    assert token not in serialized
    assert "correct-horse-battery" not in serialized


def test_cross_tenant_invitation_admin_is_hidden(client,db,auth_a,auth_b,monkeypatch):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    created=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":"invitee@example.com","display_name":"Invitee","role":"architect",
    })
    invitation_id=created.json()["invitation_id"]
    denied=client.post(
        f"/api/v1/admin/invitations/{invitation_id}/revoke",
        headers=auth_b,
        json={"expected_token_version":1},
    )
    assert denied.status_code==404


def test_expired_revoke_persists_expired_not_revoked(client,db,auth_a,monkeypatch):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    created=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":"expired@example.com","display_name":"Expired","role":"member",
    })
    invitation=db.get(UserInvitation,created.json()["invitation_id"])
    invitation.expires_at=utcnow()-timedelta(minutes=1)
    db.commit()

    response=client.post(
        f"/api/v1/admin/invitations/{invitation.id}/revoke",
        headers=auth_a,
        json={"expected_token_version":1},
    )
    assert response.status_code==410
    db.refresh(invitation)
    assert invitation.status=="expired"
    events=db.query(TenantAuditEvent).filter_by(target_id=invitation.id).all()
    assert [e.event_type for e in events][-1]=="invitation.expired"


def test_admin_cannot_invite_admin(client,db,auth_a,monkeypatch):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    actor=db.query(Membership).filter_by(tenant_id="tenant-a",external_subject="user-a").one()
    actor.role="admin"
    db.commit()
    response=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":"otheradmin@example.com","display_name":"Other Admin","role":"admin",
    })
    assert response.status_code==403


def test_invitation_create_integrityerror_returns_controlled_conflict():
    class FakeDB:
        def __init__(self):
            self.rolled_back=False
        def add(self, _value):
            pass
        def flush(self):
            raise IntegrityError("INSERT user_invitations",{},Exception("unique"))
        def rollback(self):
            self.rolled_back=True
        def scalar(self, _statement):
            return object()

    fake=FakeDB()
    invitation=SimpleNamespace(tenant_id="tenant-a",email_normalized="race@example.com")
    with pytest.raises(HTTPException) as caught:
        persist_invitation_create(fake,invitation)
    assert caught.value.status_code==409
    assert caught.value.detail=="invitation_already_exists"
    assert fake.rolled_back is True


@pytest.mark.parametrize("action",["rotate","reissue","revoke"])
def test_invitation_missing_version_has_literal_contract(client,auth_a,monkeypatch,action):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    created=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":f"missing-{action}@example.com",
        "display_name":"Missing Version",
        "role":"architect",
    })
    assert created.status_code==201
    invitation_id=created.json()["invitation_id"]

    if action=="reissue":
        revoked=client.post(
            f"/api/v1/admin/invitations/{invitation_id}/revoke",
            headers=auth_a,
            json={"expected_token_version":1},
        )
        assert revoked.status_code==200

    response=client.post(
        f"/api/v1/admin/invitations/{invitation_id}/{action}",
        headers=auth_a,
        json={},
    )
    assert response.status_code==422
    assert response.json()["detail"]=="missing_expected_token_version"


def test_terminal_token_inspect_returns_no_pii(client,auth_a,monkeypatch):
    monkeypatch.setenv("GLIP_PUBLIC_APP_URL","https://glip.example")
    created=client.post("/api/v1/admin/invitations",headers=auth_a,json={
        "email":"terminal@example.com",
        "display_name":"Terminal Person",
        "role":"architect",
    })
    token=_token_from_activation_url(created.json()["activation_url"])
    activated=client.post("/api/v1/auth/invitations/activate",json={
        "token":token,
        "password":"correct-horse-battery",
    })
    assert activated.status_code==200

    inspected=client.post("/api/v1/auth/invitations/inspect",json={"token":token})
    assert inspected.status_code==410
    body=inspected.json()
    assert body=={"detail":"invitation_unavailable"}
    serialized=str(body)
    assert "terminal@example.com" not in serialized
    assert "Terminal Person" not in serialized
