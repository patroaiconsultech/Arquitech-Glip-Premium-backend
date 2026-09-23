from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from glip.config import settings
from glip.models import ArchitecturalScene, ArchitecturalSource, BIMExtractionJob
from glip.bim.ifc_semantics import SemanticExtractionResult, IfcOpenShellSemanticEngine
from glip.bim.service import process_bim_extraction_job


class FakeIfcEngine:
    name = "ifcopenshell"
    def available(self): return True
    def extract(self, path:Path, *, source_sha256:str, max_elements:int):
        assert path.exists()
        assert path.read_bytes().startswith(b"ISO-10303-21")
        assert max_elements >= 100
        scene = {
            "schema_version":"glip.arch.scene.v1",
            "units":"m",
            "semantic_source":{
                "format":"ifc",
                "source_sha256":source_sha256,
                "ifc_schema":"IFC4X3_ADD2",
                "engine":"ifcopenshell",
                "engine_version":"test",
                "unit_scale_to_m":0.001,
            },
            "spatial_structure":[
                {"guid":"STOREY-1","ifc_class":"IfcBuildingStorey","name":"Térreo","elevation_m":0.0}
            ],
            "elements":[
                {
                    "guid":"WALL-1","step_id":42,"ifc_class":"IfcWall","name":"Parede 01",
                    "container":{"guid":"STOREY-1","ifc_class":"IfcBuildingStorey","name":"Térreo"},
                    "materials":[{"ifc_class":"IfcMaterial","name":"Alvenaria"}],
                    "property_sets":{"Pset_WallCommon":{"IsExternal":False}},
                    "placement_m":{"x_m":1.0,"y_m":2.0,"z_m":0.0},
                }
            ],
            "statistics":{"element_count":1,"spatial_count":1,"by_class":{"IfcWall":1}},
            "geometry":{
                "status":"PENDING_GATE_3",
                "distribution_format":"glb/gltf",
                "semantic_source_of_truth":"ifc",
            },
        }
        return SemanticExtractionResult(
            scene=scene, engine="ifcopenshell", engine_version="test",
            statistics=scene["statistics"],
        )


def _project(client, headers, name="BIM Semantic Project"):
    r=client.post("/api/v1/projects",headers=headers,json={"name":name})
    assert r.status_code==201,r.text
    return r.json()["id"]


def _upload_ifc(client, headers, project_id):
    payload=(
        b"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4X3_ADD2'));\nENDSEC;\n"
        b"DATA;\n#42=IFCWALL('WALL-1',$,'Parede 01',$,$,$,$,$);\nENDSEC;\n"
        b"END-ISO-10303-21;"
    )
    r=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources",
        headers=headers,
        files={"file":("modelo.ifc",payload,"application/x-step")},
        data={"classification":"project_internal"},
    )
    assert r.status_code==201,r.text
    return r.json()


def test_ifcopenshell_adapter_fails_closed_when_runtime_is_missing(monkeypatch):
    engine=IfcOpenShellSemanticEngine()
    monkeypatch.setattr(engine,"available",lambda:False)
    try:
        engine.extract(Path("/tmp/missing.ifc"),source_sha256="a"*64,max_elements=1000)
        assert False,"expected BIM_ENGINE_UNAVAILABLE"
    except Exception as exc:
        assert str(exc)=="BIM_ENGINE_UNAVAILABLE"


def test_bim_semantic_job_queue_is_tenant_scoped(client,auth_a,auth_b,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"architecture_uploads_enabled",True)
    monkeypatch.setattr(settings,"bim_semantic_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"arch"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")

    project_id=_project(client,auth_a)
    source=_upload_ifc(client,auth_a,project_id)
    r=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources/{source['source_id']}/semantic-extractions",
        headers=auth_a,
    )
    assert r.status_code==202,r.text
    body=r.json()
    assert body["status"]=="queued"
    assert body["engine"]=="ifcopenshell"
    assert body["billing_scope"]=="glip"

    denied=client.get(
        f"/api/v1/projects/{project_id}/architecture/bim-jobs/{body['job_id']}",
        headers=auth_b,
    )
    assert denied.status_code==404


def test_fake_worker_persists_semantic_scene(client,auth_a,tmp_path,monkeypatch,db):
    monkeypatch.setattr(settings,"architecture_uploads_enabled",True)
    monkeypatch.setattr(settings,"bim_semantic_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"arch"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")
    monkeypatch.setattr(settings,"bim_semantic_max_elements",1000)

    project_id=_project(client,auth_a,"IFC Semantics")
    source_body=_upload_ifc(client,auth_a,project_id)
    queued=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources/{source_body['source_id']}/semantic-extractions",
        headers=auth_a,
    )
    assert queued.status_code==202,queued.text

    job=db.scalar(select(BIMExtractionJob).where(BIMExtractionJob.id==queued.json()["job_id"]))
    assert job is not None
    job.status="processing"
    db.commit()

    scene=process_bim_extraction_job(
        db,settings=settings,job=job,engine=FakeIfcEngine()
    )
    db.commit()

    assert scene.status=="semantic_ready"
    assert scene.scene_json["semantic_source"]["ifc_schema"]=="IFC4X3_ADD2"
    assert scene.scene_json["statistics"]["by_class"]["IfcWall"]==1
    assert scene.scene_json["elements"][0]["guid"]=="WALL-1"
    assert scene.scene_json["geometry"]["semantic_source_of_truth"]=="ifc"

    db.refresh(job)
    assert job.status=="completed"
    assert job.scene_id==scene.id
    assert job.engine_version=="test"


def test_non_ifc_source_cannot_queue_bim_semantics(client,auth_a,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"architecture_uploads_enabled",True)
    monkeypatch.setattr(settings,"bim_semantic_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"arch"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")

    project_id=_project(client,auth_a,"DXF")
    r=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources",
        headers=auth_a,
        files={"file":("planta.dxf",b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF","application/dxf")},
        data={"classification":"project_internal"},
    )
    assert r.status_code==201,r.text
    q=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources/{r.json()['source_id']}/semantic-extractions",
        headers=auth_a,
    )
    assert q.status_code==422
    assert q.json()["detail"]=="BIM_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED"


def test_architecture_manifest_exposes_gate2_adapter(client,auth_a,monkeypatch):
    monkeypatch.setattr(settings,"bim_semantic_enabled",True)
    project_id=_project(client,auth_a,"Caps BIM")
    r=client.get(f"/api/v1/projects/{project_id}/architecture/capabilities",headers=auth_a)
    assert r.status_code==200
    assert r.json()["bim"]["semantic_parser_status"]=="ADAPTER_READY"
