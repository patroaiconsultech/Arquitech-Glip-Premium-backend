from __future__ import annotations

from pathlib import Path

from glip.config import settings


def _project(client,headers,name="Artifact Project"):
    r=client.post("/api/v1/projects",headers=headers,json={"name":name})
    assert r.status_code==201,r.text
    return r.json()["id"]


def test_document_artifact_roundtrip_is_tenant_scoped(client,auth_a,auth_b,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"artifacts_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"artifacts"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")
    project_id=_project(client,auth_a)
    r=client.post(
        f"/api/v1/projects/{project_id}/artifacts/render",
        headers=auth_a,
        json={
            "format":"pdf",
            "filename":"memorial.pdf",
            "content":"# Memorial\n\n## Projeto\n\nConteúdo técnico do projeto GLIP.",
        },
    )
    assert r.status_code==201,r.text
    body=r.json()
    assert body["billing_scope"]=="glip"
    assert body["sha256"]
    d=client.get(body["download_path"],headers=auth_a)
    assert d.status_code==200
    assert d.content.startswith(b"%PDF")
    denied=client.get(body["download_path"],headers=auth_b)
    assert denied.status_code==404


def test_ifc_upload_is_project_scoped_and_detects_schema(client,auth_a,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"architecture_uploads_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"arch"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")
    project_id=_project(client,auth_a,"BIM Project")
    payload=(
        b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
        b"FILE_SCHEMA(('IFC4X3_ADD2'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"
    )
    r=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources",
        headers=auth_a,
        files={"file":("modelo.ifc",payload,"application/x-step")},
        data={"classification":"project_internal"},
    )
    assert r.status_code==201,r.text
    data=r.json()
    assert data["source_format"]=="ifc"
    assert data["ifc_schema"]=="IFC4X3_ADD2"
    assert data["billing_scope"]=="glip"

    listing=client.get(f"/api/v1/projects/{project_id}/architecture/sources",headers=auth_a)
    assert listing.status_code==200
    assert len(listing.json())==1


def test_architecture_capabilities_are_honest_about_future_gates(client,auth_a):
    project_id=_project(client,auth_a,"Capabilities")
    r=client.get(f"/api/v1/projects/{project_id}/architecture/capabilities",headers=auth_a)
    assert r.status_code==200
    data=r.json()
    assert data["bim"]["ifc_first_class"] is True
    assert data["bim"]["semantic_parser_status"]=="PENDING_GATE_2"
    assert data["render"]["status"]=="PENDING_GATE_4"
