
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest
from sqlalchemy import select

from glip.config import settings
from glip.models import (
    ArchitecturalScene, ArchitecturalSource, CADExtractionJob, GeometryBuildJob, ArtifactAsset
)
from glip.pricing.quantities import extract_ifc_quantity_takeoff
from glip.cad.dxf_semantics import CADSemanticResult, EzdxfSemanticEngine
from glip.cad.service import process_cad_extraction_job
from glip.geometry.glb_preview import GLBPreviewResult, TrimeshLinePreviewEngine
from glip.geometry.service import process_geometry_build_job


def _project(client,headers,name="RC7 Project"):
    r=client.post("/api/v1/projects",headers=headers,json={"name":name})
    assert r.status_code==201,r.text
    return r.json()["id"]


def _upload(client,headers,project_id,name,data,mime):
    r=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources",
        headers=headers,
        files={"file":(name,data,mime)},
        data={"classification":"project_internal"},
    )
    assert r.status_code==201,r.text
    return r.json()


def test_ifc_qto_normalizes_linear_area_volume_and_refuses_custom_numeric_properties():
    scene={
        "semantic_source":{"format":"ifc","source_sha256":"a"*64,"unit_scale_to_m":0.001},
        "elements":[{
            "guid":"W1","ifc_class":"IfcWall",
            "property_sets":{
                "Qto_WallBaseQuantities":{
                    "Length":1000.0,
                    "NetSideArea":2_000_000.0,
                    "NetVolume":3_000_000_000.0,
                    "Count":2,
                },
                "Pset_Custom":{"BudgetGuess":999999.0},
            },
        }],
    }
    out=extract_ifc_quantity_takeoff(scene)
    values={(x["quantity_name"],x["unit"]):x["value"] for x in out["items"]}
    assert values[("Length","m")]==1.0
    assert values[("NetSideArea","m2")]==2.0
    assert values[("NetVolume","m3")]==3.0
    assert values[("Count","count")]==2.0
    assert all(x["quantity_name"]!="BudgetGuess" for x in out["items"])
    assert out["pricing_readiness"]["llm_numeric_authority"] is False


class FakeCAD:
    name="ezdxf"
    version="test"
    def extract(self,path:Path,*,source_sha256:str,max_entities:int):
        assert path.exists() and max_entities>=100
        scene={
            "schema_version":"glip.arch.scene.v1","units":"m",
            "semantic_source":{"format":"dxf","source_sha256":source_sha256,"engine":"ezdxf","engine_version":"test"},
            "layers":[{"name":"A-WALL","entity_count":2,"length_m":12.5,"area_m2":0.0,"blocks":{}}],
            "elements":[],
            "statistics":{"entity_count":2,"layer_count":1,"by_type":{"LINE":2},"preview_path_count":1},
            "geometry":{
                "status":"CAD_PREVIEW_READY","authority":"2d_cad_source",
                "preview_kind":"linework",
                "paths":[{"handle":"1","layer":"A-WALL","type":"LINE","closed":False,"points_m":[[0,0,0],[12.5,0,0]]}],
                "distribution_format":"glb/gltf","three_d_semantics_status":"MAPPING_REQUIRED",
            },
            "quantity_takeoff":{
                "schema_version":"glip.quantity-takeoff.v1",
                "source_kind":"cad_raw","items":[],
                "pricing_readiness":{"status":"SEMANTIC_MAPPING_REQUIRED","llm_numeric_authority":False},
            },
        }
        return CADSemanticResult(scene=scene,engine="ezdxf",engine_version="test",statistics=scene["statistics"])


class FakeGLB:
    name="trimesh"
    version="test"
    def build(self,scene,*,max_paths:int,max_points:int):
        data=b"glTF"+b"\x00"*64
        return GLBPreviewResult(
            data=data,sha256=hashlib.sha256(data).hexdigest(),
            engine="trimesh",engine_version="test",
            statistics={"path_count":1,"point_count":2,"edge_count":1,"bytes":len(data),"preview_only":True},
        )


def test_cad_and_geometry_jobs_are_tenant_scoped_and_persist_source_provenance(
    client,auth_a,auth_b,tmp_path,monkeypatch,db
):
    monkeypatch.setattr(settings,"architecture_uploads_enabled",True)
    monkeypatch.setattr(settings,"cad_semantic_enabled",True)
    monkeypatch.setattr(settings,"geometry_build_enabled",True)
    monkeypatch.setattr(settings,"artifact_storage_backend","local")
    monkeypatch.setattr(settings,"artifact_storage_path",str(tmp_path/"arch"))
    monkeypatch.setattr(settings,"artifact_provider_profile_ref","glip-local")

    project_id=_project(client,auth_a)
    source_body=_upload(
        client,auth_a,project_id,"planta.dxf",
        b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n","application/dxf"
    )

    q=client.post(
        f"/api/v1/projects/{project_id}/architecture/sources/{source_body['source_id']}/cad-extractions",
        headers=auth_a,
    )
    assert q.status_code==202,q.text
    denied=client.get(f"/api/v1/projects/{project_id}/architecture/cad-jobs/{q.json()['job_id']}",headers=auth_b)
    assert denied.status_code==404

    job=db.get(CADExtractionJob,q.json()["job_id"])
    job.status="processing";db.commit()
    scene=process_cad_extraction_job(db,settings=settings,job=job,engine=FakeCAD())
    db.commit()
    assert scene.status=="cad_semantic_ready"
    assert scene.source_sha256==source_body["sha256"]
    assert scene.scene_json["geometry"]["three_d_semantics_status"]=="MAPPING_REQUIRED"

    gq=client.post(
        f"/api/v1/projects/{project_id}/architecture/scenes/{scene.id}/geometry-builds",
        headers=auth_a,json={"build_kind":"preview_glb"},
    )
    assert gq.status_code==202,gq.text
    gjob=db.get(GeometryBuildJob,gq.json()["job_id"])
    gjob.status="processing";db.commit()
    asset=process_geometry_build_job(db,settings=settings,job=gjob,engine=FakeGLB())
    db.commit()
    assert asset.artifact_kind=="model3d"
    assert asset.format=="glb"
    assert asset.metadata_json["preview_only"] is True
    assert asset.metadata_json["source_sha256"]==source_body["sha256"]

    blocked=client.get(
        f"/api/v1/projects/{project_id}/architecture/models/{asset.id}/download",
        headers=auth_b,
    )
    assert blocked.status_code==404
    ok=client.get(
        f"/api/v1/projects/{project_id}/architecture/models/{asset.id}/download",
        headers=auth_a,
    )
    assert ok.status_code==200
    assert ok.headers["x-artifact-sha256"]==asset.sha256


def test_real_ezdxf_adapter_with_synthetic_dxf_when_worker_dependency_is_present(tmp_path):
    ezdxf=pytest.importorskip("ezdxf")
    doc=ezdxf.new("R2018")
    doc.header["$INSUNITS"]=4  # millimeters
    msp=doc.modelspace()
    msp.add_line((0,0),(1000,0),dxfattribs={"layer":"A-WALL"})
    msp.add_line((1000,0),(1000,2000),dxfattribs={"layer":"A-WALL"})
    path=tmp_path/"synthetic.dxf";doc.saveas(path)

    result=EzdxfSemanticEngine().extract(path,source_sha256="b"*64,max_entities=100)
    wall=next(x for x in result.scene["layers"] if x["name"]=="A-WALL")
    assert wall["entity_count"]==2
    assert wall["length_m"]==3.0
    assert result.scene["quantity_takeoff"]["pricing_readiness"]["status"]=="SEMANTIC_MAPPING_REQUIRED"


def test_real_trimesh_glb_line_preview_when_worker_dependency_is_present():
    pytest.importorskip("trimesh")
    scene={"geometry":{"paths":[{"points_m":[[0,0,0],[1,0,0],[1,1,0]],"closed":False}]}}
    result=TrimeshLinePreviewEngine().build(scene,max_paths=100,max_points=1000)
    assert result.data[:4]==b"glTF"
    assert result.statistics["edge_count"]==2
    assert result.statistics["preview_only"] is True


def test_architecture_manifest_exposes_quantity_and_pricing_safety(client,auth_a,monkeypatch):
    monkeypatch.setattr(settings,"cad_semantic_enabled",True)
    monkeypatch.setattr(settings,"geometry_build_enabled",True)
    project_id=_project(client,auth_a,"Pricing Ready")
    r=client.get(f"/api/v1/projects/{project_id}/architecture/capabilities",headers=auth_a)
    assert r.status_code==200
    body=r.json()
    assert body["scene"]["quantity_schema"]=="glip.quantity-takeoff.v1"
    assert body["pricing"]["quantity_takeoff_status"]=="FOUNDATION_READY"
    assert body["pricing"]["llm_numeric_authority"] is False
    assert body["cad"]["dxf_semantic_parser_status"]=="ADAPTER_READY"
    assert body["scene"]["geometry_preview_status"]=="ADAPTER_READY"
