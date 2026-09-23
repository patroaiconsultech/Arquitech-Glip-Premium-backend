
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
import uuid

from glip.artifacts.storage import build_blob_storage, BlobStorageError
from glip.models import (
    ArchitecturalScene, ArchitecturalSource, ArtifactAsset, ArtifactUsageEvent, GeometryBuildJob
)
from .glb_preview import GeometryPreviewError, TrimeshLinePreviewEngine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_geometry_build(
    db:Session,*,
    settings,
    tenant_id:str,
    project_id:str,
    scene:ArchitecturalScene,
    actor_id:str,
    build_kind:str="preview_glb",
)->GeometryBuildJob:
    if not getattr(settings,"geometry_build_enabled",False):
        raise GeometryPreviewError("GEOMETRY_BUILD_DISABLED")
    if build_kind!="preview_glb":
        raise GeometryPreviewError("GEOMETRY_BUILD_KIND_UNSUPPORTED")
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==scene.source_id,
        ArchitecturalSource.tenant_id==tenant_id,
        ArchitecturalSource.project_id==project_id,
    ))
    if not source:
        raise GeometryPreviewError("GEOMETRY_SOURCE_NOT_FOUND")
    existing=db.scalar(select(GeometryBuildJob).where(
        GeometryBuildJob.tenant_id==tenant_id,
        GeometryBuildJob.project_id==project_id,
        GeometryBuildJob.scene_id==scene.id,
        GeometryBuildJob.source_sha256==source.sha256,
        GeometryBuildJob.build_kind==build_kind,
        GeometryBuildJob.status.in_(["queued","processing","completed"]),
    ).order_by(GeometryBuildJob.created_at.desc()))
    if existing:
        return existing
    job=GeometryBuildJob(
        tenant_id=tenant_id,project_id=project_id,scene_id=scene.id,
        source_id=source.id,source_sha256=source.sha256,build_kind=build_kind,
        engine=getattr(settings,"geometry_preview_engine","trimesh"),
        status="queued",requested_by=actor_id,
    )
    db.add(job);db.flush()
    return job


def claim_next_geometry_job(db:Session,*,settings,worker_id:str)->GeometryBuildJob|None:
    seconds=int(getattr(settings,"geometry_job_lease_seconds",300))
    now=utcnow()
    job=db.scalar(
        select(GeometryBuildJob)
        .where(
            (GeometryBuildJob.status=="queued")
            | (
                (GeometryBuildJob.status=="processing")
                & (GeometryBuildJob.lease_expires_at.is_not(None))
                & (GeometryBuildJob.lease_expires_at<now)
            )
        )
        .order_by(GeometryBuildJob.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    if not job:
        return None
    job.status="processing"
    job.lease_owner=worker_id
    job.lease_expires_at=now+timedelta(seconds=seconds)
    job.started_at=job.started_at or now
    job.attempt_count=int(job.attempt_count or 0)+1
    db.flush()
    return job


def process_geometry_build_job(
    db:Session,*,
    settings,
    job:GeometryBuildJob,
    engine=None,
)->ArtifactAsset:
    scene=db.scalar(select(ArchitecturalScene).where(
        ArchitecturalScene.id==job.scene_id,
        ArchitecturalScene.tenant_id==job.tenant_id,
        ArchitecturalScene.project_id==job.project_id,
    ))
    if not scene:
        job.status="failed";job.error_code="GEOMETRY_SCENE_NOT_FOUND";job.completed_at=utcnow();db.flush()
        raise GeometryPreviewError("GEOMETRY_SCENE_NOT_FOUND")
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==job.source_id,
        ArchitecturalSource.tenant_id==job.tenant_id,
        ArchitecturalSource.project_id==job.project_id,
    ))
    if not source:
        job.status="failed";job.error_code="GEOMETRY_SOURCE_NOT_FOUND";job.completed_at=utcnow();db.flush()
        raise GeometryPreviewError("GEOMETRY_SOURCE_NOT_FOUND")
    if job.build_kind!="preview_glb":
        raise GeometryPreviewError("GEOMETRY_BUILD_KIND_UNSUPPORTED")

    engine=engine or TrimeshLinePreviewEngine()
    try:
        result=engine.build(
            scene.scene_json,
            max_paths=int(getattr(settings,"geometry_preview_max_paths",20_000)),
            max_points=int(getattr(settings,"geometry_preview_max_points",500_000)),
        )
        asset_id=str(uuid.uuid4())
        filename=f"{source.original_filename.rsplit('.',1)[0]}-preview.glb"
        key=f"{job.tenant_id}/{job.project_id}/architecture/derived/{asset_id}-{filename}"
        storage=build_blob_storage(settings)
        created=storage.put_if_absent(key,result.data,content_type="model/gltf-binary")
        if not created:
            raise GeometryPreviewError("GEOMETRY_STORAGE_COLLISION")
        asset=ArtifactAsset(
            id=asset_id,tenant_id=job.tenant_id,project_id=job.project_id,job_id=None,
            artifact_kind="model3d",format="glb",filename=filename,mime_type="model/gltf-binary",
            storage_key=key,sha256=result.sha256,size_bytes=len(result.data),
            classification=source.classification,
            metadata_json={
                "source_id":source.id,
                "source_sha256":source.sha256,
                "scene_id":scene.id,
                "scene_version":scene.version,
                "build_kind":"preview_glb",
                "preview_only":True,
                "geometry_authority":"source_linework",
                "engine":result.engine,
                "engine_version":result.engine_version,
                "statistics":result.statistics,
            },
            version=1,created_by=job.requested_by,
        )
        db.add(asset);db.flush()
        job.status="completed";job.output_artifact_id=asset.id
        job.engine_version=result.engine_version;job.statistics_json=result.statistics
        job.error_code=None;job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None
        db.add(ArtifactUsageEvent(
            tenant_id=job.tenant_id,project_id=job.project_id,billing_scope="glip",
            usage_type="geometry_preview_glb",provider=result.engine,
            provider_profile_ref="glip-geometry",
            units_json=result.statistics,cost_microusd=None,
        ))
        db.flush()
        return asset
    except GeometryPreviewError as exc:
        job.status="failed";job.error_code=str(exc);job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None;db.flush();raise
    except BlobStorageError as exc:
        job.status="failed";job.error_code="GEOMETRY_STORAGE_FAILED";job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None;db.flush()
        raise GeometryPreviewError("GEOMETRY_STORAGE_FAILED") from exc
    except Exception as exc:
        job.status="failed";job.error_code="GEOMETRY_INTERNAL_ERROR";job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None;db.flush()
        raise GeometryPreviewError("GEOMETRY_INTERNAL_ERROR") from exc
