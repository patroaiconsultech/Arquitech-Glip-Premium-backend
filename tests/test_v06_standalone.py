import json
import pytest
from glip.config import Settings
from glip.integrations.orkio import client as orkio_client

def test_core_readiness_does_not_require_external_realtime_voice_avatar(client):
    r=client.get("/health/ready")
    assert r.status_code==200
    body=r.json()
    assert body["status"]=="ready"
    assert body["optional"]["realtime"]=="pending_external"
    assert body["optional"]["voice"]=="pending_external"
    assert body["optional"]["avatar"]=="pending_external"

def test_system_status_exposes_external_capabilities_without_claiming_enabled(client,auth_a):
    r=client.get("/api/v1/system/status",headers=auth_a)
    assert r.status_code==200
    body=r.json()
    assert body["realtime"]["mode"]=="pending_external"
    assert body["voice"]["mode"]=="pending_external"
    assert body["avatar"]["mode"]=="pending_external"
    assert body["realtime"]["blocking"] is False

def test_orkio_disabled_probe_performs_zero_network(monkeypatch):
    called={"value":False}
    def fail(*a,**k):
        called["value"]=True
        raise AssertionError("network must not be called")
    monkeypatch.setattr("glip.integrations.orkio.client.httpx.Client",fail)
    data=orkio_client.probe()
    assert data["mode"]=="mock" or data["mode"]=="disabled"
    if data["mode"]=="disabled":
        assert called["value"] is False

def test_native_session_requires_server_secrets():
    with pytest.raises(ValueError,match="auth_session_secret_too_short"):
        Settings(
            environment="test",
            auth_mode="native_session",
            database_url="sqlite://",
        )

def test_capability_v1_requires_m2m_and_execute_path():
    with pytest.raises(ValueError):
        Settings(
            environment="development",
            auth_mode="dev_headers",
            orkio_mode="capability_v1",
            orkio_base_url="https://orkio.example.invalid",
        )

def test_operational_domains_are_tenant_isolated(client,auth_a,auth_b):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto A"}).json()
    for path,payload in [
        ("decisions",{"title":"Aprovar layout"}),
        ("assets",{"name":"Modelo BIM","asset_type":"bim","storage_ref":"private://bim/model.ifc"}),
        ("communications",{"summary":"Contato registrado","channel":"internal"}),
        ("documents",{"name":"Briefing","storage_ref":"private://docs/briefing.pdf"}),
    ]:
        r=client.post(f"/api/v1/projects/{p['id']}/{path}",headers=auth_a,json=payload)
        assert r.status_code==201
        assert client.get(f"/api/v1/projects/{p['id']}/{path}",headers=auth_b).status_code==404

def test_project_overview_counts_new_domains(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    client.post(f"/api/v1/projects/{p['id']}/decisions",headers=auth_a,json={"title":"Decisão"})
    client.post(f"/api/v1/projects/{p['id']}/assets",headers=auth_a,json={
        "name":"Referência","asset_type":"reference","storage_ref":"private://ref/1"
    })
    ov=client.get(f"/api/v1/projects/{p['id']}/overview",headers=auth_a)
    assert ov.status_code==200
    body=ov.json()
    assert body["counts"]["decisions"]==1
    assert body["counts"]["assets"]==1
    assert body["external_capabilities"]["voice"]=="pending_external"
