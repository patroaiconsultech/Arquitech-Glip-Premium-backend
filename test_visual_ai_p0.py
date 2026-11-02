from __future__ import annotations

import struct
import zlib
from uuid import uuid4

from glip.config import settings
from glip.models import ArtifactAsset, ArtifactJob, ArtifactUsageEvent, Membership, Project, Tenant
from glip.visual_ai_worker import claim_visual_job, process_visual_job


def png(width=128, height=96):
    def chunk(name, content):
        return struct.pack(">I", len(content)) + name + content + struct.pack(">I", zlib.crc32(name + content) & 0xffffffff)
    raw = b"\x00" + b"\xc1\xd7\xe6" * width
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw * height))
            + chunk(b"IEND", b""))


def setup(db, tid, user, role="owner"):
    db.add(Tenant(id=tid, name=tid))
    db.add(Membership(tenant_id=tid, external_subject=user, role=role, active=True))
    project = Project(id=str(uuid4()), tenant_id=tid, name="Projeto Visual", created_by=user)
    db.add(project)
    db.commit()
    return project.id, {"X-GLIP-Tenant-ID": tid, "X-GLIP-User-ID": user}


def enable(monkeypatch, tmp_path, *, provider="openai", quota=10):
    monkeypatch.setattr(settings, "visual_ai_enabled", True)
    monkeypatch.setattr(settings, "visual_ai_provider", provider)
    monkeypatch.setattr(settings, "visual_ai_openai_api_key", "test-fake-never-sent")
    monkeypatch.setattr(settings, "visual_ai_max_daily_edits", quota)
    monkeypatch.setattr(settings, "artifact_storage_backend", "local")
    monkeypatch.setattr(settings, "artifact_storage_path", str(tmp_path))


def upload(client, project, headers, data=None):
    return client.post(f"/api/v1/projects/{project}/visual-ai/images",
                       headers=headers, files={"file": ("fachada.png", data or png(), "image/png")})


def edit(client, project, asset, headers, consent=True):
    return client.post(f"/api/v1/projects/{project}/visual-ai/images/{asset}/edits",
                       headers=headers, json={"prompt": "Substitua o revestimento por madeira.",
                                              "consent_external_processing": consent})


def test_visual_ai_disabled_by_default(client, db, monkeypatch):
    monkeypatch.setattr(settings, "visual_ai_enabled", False)
    project, headers = setup(db, "tenant-disabled", "owner")
    caps = client.get(f"/api/v1/projects/{project}/visual-ai/capabilities", headers=headers)
    assert caps.status_code == 200 and not caps.json()["enabled"]
    assert upload(client, project, headers).status_code == 404


def test_upload_is_immutable_and_tenant_scoped(client, db, monkeypatch, tmp_path):
    enable(monkeypatch, tmp_path)
    a, ah = setup(db, "tenant-v1", "owner-a")
    b, bh = setup(db, "tenant-v2", "owner-b")
    result = upload(client, a, ah)
    assert result.status_code == 201, result.text
    original = result.json()
    assert original["kind"] == "original"
    assert original["approval_status"] is None
    assert upload(client, a, ah, b"not an image").status_code == 422
    assert client.get(f"/api/v1/projects/{a}/visual-ai/images", headers=bh).status_code == 404
    assert client.get(f"/api/v1/projects/{a}/visual-ai/images/{original['id']}/content", headers=bh).status_code == 404
    assert client.get(f"/api/v1/projects/{a}/visual-ai/images/{original['id']}/content", headers=ah).content == png()
    assert client.get(f"/api/v1/projects/{b}/visual-ai/images", headers=bh).json() == []
    stored = db.query(ArtifactAsset).filter_by(id=original["id"]).one()
    assert stored.artifact_kind == "visual_ai_original"
    assert stored.metadata_json["source"] == "manual_upload"


def test_edit_consent_quota_and_review(client, db, monkeypatch, tmp_path):
    enable(monkeypatch, tmp_path, quota=1)
    project, owner = setup(db, "tenant-edit", "owner")
    source = upload(client, project, owner).json()
    source_id = source["id"]
    assert edit(client, project, source_id, owner, False).status_code == 422
    queued = edit(client, project, source_id, owner)
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]
    assert edit(client, project, source_id, owner).status_code == 429
    assert client.get(f"/api/v1/projects/{project}/visual-ai/jobs", headers=owner).json()[0]["status"] == "queued"
    assert claim_visual_job(db) == job_id
    db.commit()
    provider_calls = []
    def provider(**kwargs):
        provider_calls.append(kwargs)
        return png(96, 96), {"input_tokens": 17, "output_tokens": 20}
    created = process_visual_job(db, settings=settings, job_id=job_id, provider=provider)
    assert provider_calls and provider_calls[0]["source_bytes"] == png()
    assert db.query(ArtifactJob).filter_by(id=job_id).one().status == "completed"
    assert db.query(ArtifactUsageEvent).filter_by(artifact_job_id=job_id).one().cost_microusd is None
    items = client.get(f"/api/v1/projects/{project}/visual-ai/images", headers=owner).json()
    assert len(items) == 2
    derived = next(i for i in items if i["id"] == created)
    assert derived["approval_status"] == "pending_review"
    assert derived["source_asset_id"] == source_id
    assert client.get(f"/api/v1/projects/{project}/visual-ai/images/{source_id}/content", headers=owner).content == png()
    assert client.get(f"/api/v1/projects/{project}/visual-ai/images/{created}/content", headers=owner).content == png(96,96)
    path = f"/api/v1/projects/{project}/visual-ai/images/{created}/decision"
    assert client.post(path, json={"decision": "approved"}, headers=owner).status_code == 200
    assert client.post(path, json={"decision": "rejected"}, headers=owner).status_code == 409
    assert client.post(f"/api/v1/projects/{project}/visual-ai/images/{source_id}/decision",
                       json={"decision": "approved"}, headers=owner).status_code == 409


def test_member_cannot_approve_and_provider_disabled(client,db,monkeypatch,tmp_path):
    enable(monkeypatch,tmp_path,provider="disabled")
    project, owner = setup(db, "tenant-member", "owner")
    db.add(Membership(tenant_id="tenant-member", external_subject="member", role="member", active=True))
    db.commit()
    member = {"X-GLIP-Tenant-ID": "tenant-member", "X-GLIP-User-ID": "member"}
    original = upload(client,project,member)
    assert original.status_code == 201
    assert edit(client,project,original.json()["id"],owner).status_code == 503
    asset = db.query(ArtifactAsset).filter_by(id=original.json()["id"]).one()
    asset.artifact_kind = "visual_ai_derived"
    asset.metadata_json = {"approval_status": "pending_review"}
    db.commit()
    r = client.post(f"/api/v1/projects/{project}/visual-ai/images/{asset.id}/decision",
                    json={"decision": "approved"}, headers=member)
    assert r.status_code == 403


def test_archived_project_read_only(client,db,monkeypatch,tmp_path):
    from datetime import datetime, timezone
    enable(monkeypatch,tmp_path)
    project, h = setup(db,"tenant-archived","owner")
    db.query(Project).filter_by(id=project).one().archived_at=datetime.now(timezone.utc)
    db.commit()
    assert upload(client,project,h).status_code == 409


def test_image_header_rejects_oversized_dimensions(client,db,monkeypatch,tmp_path):
    enable(monkeypatch,tmp_path)
    project, h = setup(db,"tenant-images","owner")
    broken = bytearray(png())
    broken[16:24] = struct.pack(">II", 9000, 9000)
    assert upload(client,project,h,bytes(broken)).status_code == 422


def test_native_session_cookie_visual_upload(client, db, monkeypatch, tmp_path):
    from glip.models import NativeCredential
    from glip.native_auth import new_password_record
    enable(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "auth_mode", "native_session")
    monkeypatch.setattr(settings, "auth_session_secret", "s" * 40)
    monkeypatch.setattr(settings, "auth_password_pepper", "p" * 40)
    monkeypatch.setattr(settings, "auth_session_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "auth_idle_ttl_seconds", 900)
    monkeypatch.setattr(settings, "auth_session_touch_interval_seconds", 60)
    tid = "tenant-cookie"
    project, _ = setup(db, tid, "temp-owner")
    cid = str(uuid4())
    membership = db.query(Membership).filter_by(tenant_id=tid).one()
    membership.external_subject = "native:" + cid
    salt, digest = new_password_record("StrongVisualPassword#2026")
    db.add(NativeCredential(
        id=cid, tenant_id=tid, membership_id=membership.id,
        email_normalized="owner@example.com", password_salt_b64=salt,
        password_hash_b64=digest, active=True,
    ))
    db.commit()
    login = client.post("/api/v1/auth/login", json={
        "tenant_id": tid, "email": "owner@example.com", "password": "StrongVisualPassword#2026",
    })
    assert login.status_code == 200, login.text
    original = upload(client, project, {})
    assert original.status_code == 201, original.text
    assert client.get(f"/api/v1/projects/{project}/visual-ai/images").status_code == 200


def test_openai_provider_request_is_sanitized(monkeypatch):
    import base64
    from glip.visual_ai_worker import openai_edit
    image = png()
    request = {}
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"b64_json": base64.b64encode(image).decode()}],
                    "usage": {"total_tokens": 123}}
    class Client:
        def __init__(self, **kwargs):pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            request.update(url=url, **kwargs)
            return Response()
    monkeypatch.setattr("glip.visual_ai_worker.httpx.Client", Client)
    monkeypatch.setattr(settings,"visual_ai_provider","openai")
    monkeypatch.setattr(settings,"visual_ai_openai_api_key","fake-secret")
    data, usage = openai_edit(
        settings=settings,source_bytes=image,source_mime="image/png",
        prompt="Coloque um novo jardim no pátio."
    )
    assert data == image and usage["total_tokens"] == 123
    assert request["url"] == "https://api.openai.com/v1/images/edits"
    assert request["data"]["model"] == settings.visual_ai_model
    assert request["files"]["image"][1] == image
    assert "fake-secret" not in str(request["data"])
