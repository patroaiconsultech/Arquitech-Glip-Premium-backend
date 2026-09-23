from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_principal
from .config import settings
from .context import project_or_404
from .database import get_db
from .models import (
    ArtifactAsset, ArtifactUsageEvent, ArchitecturalScene, ArchitecturalSource, BIMExtractionJob,
    CADExtractionJob, GeometryBuildJob,
)
from .artifacts.service import (
    ArtifactError, ArtifactFormatUnsupported, ArtifactValidationFailed,
    artifact_capability_manifest, persist_artifact, render_and_validate,
)
from .artifacts.storage import BlobStorageError, build_blob_storage
from .architecture import (
    ArchitecturalSourceError, architecture_capability_manifest,
    ingest_architectural_source,
)
from .bim.ifc_semantics import BIMSemanticError
from .bim.service import enqueue_bim_extraction
from .cad.dxf_semantics import CADSemanticError
from .cad.service import enqueue_cad_extraction
from .geometry.glb_preview import GeometryPreviewError
from .geometry.service import enqueue_geometry_build

router=APIRouter(prefix="/api/v1",tags=["artifacts","architecture"])


def _require_artifacts_enabled() -> None:
    if not settings.artifacts_enabled:
        raise HTTPException(404,"artifacts_disabled")


@router.get("/projects/{project_id}/artifact-capabilities")
def artifact_capabilities(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return artifact_capability_manifest(settings)


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.tenant_id==p.tenant_id,
        ArtifactAsset.project_id==project_id,
    ).order_by(ArtifactAsset.created_at.desc())).all()


@router.post("/projects/{project_id}/artifacts/render",status_code=201)
def render_artifact(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    _require_artifacts_enabled()
    project_or_404(db,p.tenant_id,project_id)
    fmt=str(body.get("format") or "").strip().lower()
    content=str(body.get("content") or "")
    filename=body.get("filename")
    classification=str(body.get("classification") or "project_internal")
    if classification not in {"project_internal","confidential","client_shareable"}:
        raise HTTPException(422,"artifact_classification_invalid")
    try:
        validated=render_and_validate(format=fmt,content=content,filename=filename)
        job,asset=persist_artifact(
            db,settings=settings,tenant_id=p.tenant_id,project_id=project_id,
            actor_id=p.subject,validated=validated,classification=classification,
            source_kind=str(body.get("source_kind") or "user_content"),
            source_ref=body.get("source_ref"),
        )
        db.commit(); db.refresh(asset); db.refresh(job)
    except ArtifactFormatUnsupported as exc:
        db.rollback(); raise HTTPException(422,str(exc)) from exc
    except ArtifactValidationFailed as exc:
        db.rollback(); raise HTTPException(422,str(exc)) from exc
    except (ArtifactError,BlobStorageError) as exc:
        db.rollback(); raise HTTPException(503,str(exc)) from exc
    except Exception:
        # Object storage and SQL cannot share a transaction. Best-effort cleanup
        # prevents an orphan when DB commit fails after the blob was written.
        db.rollback()
        try:
            if "asset" in locals():
                build_blob_storage(settings).delete(asset.storage_key)
        finally:
            raise
    return {
        "schema_version":"glip.artifact.response.v1",
        "status":"completed",
        "job_id":job.id,
        "artifact_id":asset.id,
        "filename":asset.filename,
        "format":asset.format,
        "mime_type":asset.mime_type,
        "sha256":asset.sha256,
        "size_bytes":asset.size_bytes,
        "billing_scope":"glip",
        "download_path":f"/api/v1/projects/{project_id}/artifacts/{asset.id}/download",
    }


@router.get("/projects/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(project_id:str,artifact_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    _require_artifacts_enabled()
    project_or_404(db,p.tenant_id,project_id)
    asset=db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id==artifact_id,
        ArtifactAsset.tenant_id==p.tenant_id,
        ArtifactAsset.project_id==project_id,
    ))
    if not asset: raise HTTPException(404,"artifact_not_found")
    try:
        data=build_blob_storage(settings).get(asset.storage_key)
    except BlobStorageError as exc:
        raise HTTPException(404,str(exc)) from exc
    if __import__("hashlib").sha256(data).hexdigest()!=asset.sha256:
        raise HTTPException(500,"artifact_integrity_mismatch")
    return Response(
        content=data,media_type=asset.mime_type,
        headers={
            "Content-Disposition":f'attachment; filename="{asset.filename}"',
            "X-Artifact-SHA256":asset.sha256,
        },
    )


@router.get("/projects/{project_id}/artifact-usage")
def artifact_usage(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    rows=db.scalars(select(ArtifactUsageEvent).where(
        ArtifactUsageEvent.tenant_id==p.tenant_id,
        ArtifactUsageEvent.project_id==project_id,
        ArtifactUsageEvent.billing_scope=="glip",
    ).order_by(ArtifactUsageEvent.created_at.desc())).all()
    return {
        "schema_version":"glip.artifact-usage.v1",
        "billing_scope":"glip",
        "items":rows,
    }


@router.get("/projects/{project_id}/architecture/capabilities")
def architecture_capabilities(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return architecture_capability_manifest(settings)


@router.get("/projects/{project_id}/architecture/sources")
def architecture_sources(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ArchitecturalSource).where(
        ArchitecturalSource.tenant_id==p.tenant_id,
        ArchitecturalSource.project_id==project_id,
    ).order_by(ArchitecturalSource.created_at.desc())).all()


@router.post("/projects/{project_id}/architecture/sources",status_code=201)
async def upload_architecture_source(
    project_id:str,
    file:UploadFile=File(...),
    classification:str=Form("project_internal"),
    p=Depends(get_principal),
    db:Session=Depends(get_db),
):
    project_or_404(db,p.tenant_id,project_id)
    if classification not in {"project_internal","confidential","client_shareable"}:
        raise HTTPException(422,"architecture_classification_invalid")
    row=None; duplicate=False
    try:
        row,duplicate=await ingest_architectural_source(
            db,settings=settings,tenant_id=p.tenant_id,project_id=project_id,
            actor_id=p.subject,upload=file,classification=classification,
        )
        db.commit(); db.refresh(row)
    except ArchitecturalSourceError as exc:
        db.rollback()
        code=str(exc)
        status=404 if code=="ARCHITECTURE_UPLOADS_DISABLED" else 413 if code=="ARCH_SOURCE_TOO_LARGE" else 422
        raise HTTPException(status,code) from exc
    except Exception:
        db.rollback()
        if row is not None and not duplicate:
            try: build_blob_storage(settings).delete(row.storage_key)
            except Exception: pass
        raise
    return {
        "schema_version":"glip.arch-source.response.v1",
        "status":"existing" if duplicate else "uploaded",
        "source_id":row.id,
        "source_format":row.source_format,
        "filename":row.original_filename,
        "sha256":row.sha256,
        "size_bytes":row.size_bytes,
        "ifc_schema":row.ifc_schema,
        "billing_scope":"glip",
    }




@router.get("/projects/{project_id}/architecture/bim-jobs")
def architecture_bim_jobs(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(BIMExtractionJob).where(
        BIMExtractionJob.tenant_id==p.tenant_id,
        BIMExtractionJob.project_id==project_id,
    ).order_by(BIMExtractionJob.created_at.desc())).all()


@router.get("/projects/{project_id}/architecture/bim-jobs/{job_id}")
def architecture_bim_job(project_id:str,job_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    job=db.scalar(select(BIMExtractionJob).where(
        BIMExtractionJob.id==job_id,
        BIMExtractionJob.tenant_id==p.tenant_id,
        BIMExtractionJob.project_id==project_id,
    ))
    if not job: raise HTTPException(404,"bim_job_not_found")
    return job


@router.post("/projects/{project_id}/architecture/sources/{source_id}/semantic-extractions",status_code=202)
def queue_bim_semantic_extraction(
    project_id:str,source_id:str,p=Depends(get_principal),db:Session=Depends(get_db)
):
    project_or_404(db,p.tenant_id,project_id)
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==source_id,
        ArchitecturalSource.tenant_id==p.tenant_id,
        ArchitecturalSource.project_id==project_id,
    ))
    if not source: raise HTTPException(404,"architecture_source_not_found")
    try:
        job=enqueue_bim_extraction(
            db,settings=settings,tenant_id=p.tenant_id,project_id=project_id,
            source=source,actor_id=p.subject,
        )
        db.commit(); db.refresh(job)
    except BIMSemanticError as exc:
        db.rollback()
        code=str(exc)
        status=404 if code=="BIM_SEMANTIC_DISABLED" else 422
        raise HTTPException(status,code) from exc
    return {
        "schema_version":"glip.bim-extraction.response.v1",
        "job_id":job.id,
        "source_id":job.source_id,
        "status":job.status,
        "engine":job.engine,
        "billing_scope":"glip",
    }


@router.get("/projects/{project_id}/architecture/scenes")
def architecture_scenes(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ArchitecturalScene).where(
        ArchitecturalScene.tenant_id==p.tenant_id,
        ArchitecturalScene.project_id==project_id,
    ).order_by(ArchitecturalScene.created_at.desc())).all()


@router.post("/projects/{project_id}/architecture/scenes",status_code=201)
def create_architecture_scene(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    source_id=str(body.get("source_id") or "").strip()
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==source_id,
        ArchitecturalSource.tenant_id==p.tenant_id,
        ArchitecturalSource.project_id==project_id,
    ))
    if not source: raise HTTPException(404,"architecture_source_not_found")
    scene=dict(body.get("scene") or {})
    if not scene: raise HTTPException(422,"scene_required")
    schema=str(scene.get("schema_version") or "glip.arch.scene.v1")
    if schema!="glip.arch.scene.v1": raise HTTPException(422,"scene_schema_unsupported")
    units=str(scene.get("units") or body.get("units") or "mm").lower()
    if units not in {"mm","cm","m"}: raise HTTPException(422,"scene_units_invalid")
    latest=db.scalars(select(ArchitecturalScene).where(
        ArchitecturalScene.tenant_id==p.tenant_id,
        ArchitecturalScene.project_id==project_id,
        ArchitecturalScene.source_id==source.id,
    ).order_by(ArchitecturalScene.version.desc())).first()
    obj=ArchitecturalScene(
        tenant_id=p.tenant_id,project_id=project_id,source_id=source.id,
        scene_schema_version=schema,units=units,source_format=source.source_format,
        source_sha256=source.sha256,status=str(body.get("status") or "draft"),
        scene_json=scene,version=(latest.version+1 if latest else 1),created_by=p.subject,
    )
    db.add(obj); db.commit(); db.refresh(obj); return obj



@router.get("/projects/{project_id}/architecture/cad-jobs")
def architecture_cad_jobs(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(CADExtractionJob).where(
        CADExtractionJob.tenant_id==p.tenant_id,
        CADExtractionJob.project_id==project_id,
    ).order_by(CADExtractionJob.created_at.desc())).all()


@router.get("/projects/{project_id}/architecture/cad-jobs/{job_id}")
def architecture_cad_job(project_id:str,job_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    job=db.scalar(select(CADExtractionJob).where(
        CADExtractionJob.id==job_id,
        CADExtractionJob.tenant_id==p.tenant_id,
        CADExtractionJob.project_id==project_id,
    ))
    if not job: raise HTTPException(404,"cad_job_not_found")
    return job


@router.post("/projects/{project_id}/architecture/sources/{source_id}/cad-extractions",status_code=202)
def queue_cad_semantic_extraction(
    project_id:str,source_id:str,p=Depends(get_principal),db:Session=Depends(get_db)
):
    project_or_404(db,p.tenant_id,project_id)
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==source_id,
        ArchitecturalSource.tenant_id==p.tenant_id,
        ArchitecturalSource.project_id==project_id,
    ))
    if not source: raise HTTPException(404,"architecture_source_not_found")
    try:
        job=enqueue_cad_extraction(
            db,settings=settings,tenant_id=p.tenant_id,project_id=project_id,
            source=source,actor_id=p.subject,
        )
        db.commit();db.refresh(job)
    except CADSemanticError as exc:
        db.rollback()
        code=str(exc)
        status=404 if code=="CAD_SEMANTIC_DISABLED" else 422
        raise HTTPException(status,code) from exc
    return {
        "schema_version":"glip.cad-extraction.response.v1",
        "job_id":job.id,
        "source_id":job.source_id,
        "status":job.status,
        "engine":job.engine,
        "billing_scope":"glip",
    }


@router.get("/projects/{project_id}/architecture/geometry-jobs")
def architecture_geometry_jobs(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(GeometryBuildJob).where(
        GeometryBuildJob.tenant_id==p.tenant_id,
        GeometryBuildJob.project_id==project_id,
    ).order_by(GeometryBuildJob.created_at.desc())).all()


@router.post("/projects/{project_id}/architecture/scenes/{scene_id}/geometry-builds",status_code=202)
def queue_scene_geometry_build(
    project_id:str,scene_id:str,body:dict|None=None,p=Depends(get_principal),db:Session=Depends(get_db)
):
    project_or_404(db,p.tenant_id,project_id)
    scene=db.scalar(select(ArchitecturalScene).where(
        ArchitecturalScene.id==scene_id,
        ArchitecturalScene.tenant_id==p.tenant_id,
        ArchitecturalScene.project_id==project_id,
    ))
    if not scene: raise HTTPException(404,"architecture_scene_not_found")
    build_kind=str((body or {}).get("build_kind") or "preview_glb")
    try:
        job=enqueue_geometry_build(
            db,settings=settings,tenant_id=p.tenant_id,project_id=project_id,
            scene=scene,actor_id=p.subject,build_kind=build_kind,
        )
        db.commit();db.refresh(job)
    except GeometryPreviewError as exc:
        db.rollback()
        code=str(exc)
        status=404 if code=="GEOMETRY_BUILD_DISABLED" else 422
        raise HTTPException(status,code) from exc
    return {
        "schema_version":"glip.geometry-build.response.v1",
        "job_id":job.id,
        "scene_id":job.scene_id,
        "status":job.status,
        "build_kind":job.build_kind,
        "billing_scope":"glip",
    }


@router.get("/projects/{project_id}/architecture/models/{artifact_id}/download")
def download_architecture_model(project_id:str,artifact_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    asset=db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id==artifact_id,
        ArtifactAsset.tenant_id==p.tenant_id,
        ArtifactAsset.project_id==project_id,
        ArtifactAsset.artifact_kind=="model3d",
    ))
    if not asset: raise HTTPException(404,"architecture_model_not_found")
    try:
        data=build_blob_storage(settings).get(asset.storage_key)
    except BlobStorageError as exc:
        raise HTTPException(404,str(exc)) from exc
    if __import__("hashlib").sha256(data).hexdigest()!=asset.sha256:
        raise HTTPException(500,"architecture_model_integrity_mismatch")
    return Response(
        content=data,media_type=asset.mime_type,
        headers={
            "Content-Disposition":f'attachment; filename="{asset.filename}"',
            "X-Artifact-SHA256":asset.sha256,
        },
    )
