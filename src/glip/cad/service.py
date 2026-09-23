
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from glip.artifacts.storage import build_blob_storage
from glip.models import ArchitecturalScene, ArchitecturalSource, ArtifactUsageEvent, CADExtractionJob
from .dxf_semantics import CADSemanticError, EzdxfSemanticEngine, CADSemanticResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_cad_extraction(
    db: Session,
    *,
    settings,
    tenant_id: str,
    project_id: str,
    source: ArchitecturalSource,
    actor_id: str,
) -> CADExtractionJob:
    if not getattr(settings,"cad_semantic_enabled",False):
        raise CADSemanticError("CAD_SEMANTIC_DISABLED")
    if source.source_format != "dxf":
        raise CADSemanticError("CAD_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED")
    existing=db.scalar(select(CADExtractionJob).where(
        CADExtractionJob.tenant_id==tenant_id,
        CADExtractionJob.project_id==project_id,
        CADExtractionJob.source_id==source.id,
        CADExtractionJob.source_sha256==source.sha256,
        CADExtractionJob.status.in_(["queued","processing","completed"]),
    ).order_by(CADExtractionJob.created_at.desc()))
    if existing:
        return existing
    job=CADExtractionJob(
        tenant_id=tenant_id,project_id=project_id,source_id=source.id,
        source_sha256=source.sha256,engine=getattr(settings,"cad_semantic_engine","ezdxf"),
        status="queued",requested_by=actor_id,
    )
    db.add(job);db.flush()
    return job


def claim_next_cad_job(db: Session, *, settings, worker_id: str) -> CADExtractionJob | None:
    seconds=int(getattr(settings,"cad_job_lease_seconds",300))
    now=utcnow()
    job=db.scalar(
        select(CADExtractionJob)
        .where(
            (CADExtractionJob.status=="queued")
            | (
                (CADExtractionJob.status=="processing")
                & (CADExtractionJob.lease_expires_at.is_not(None))
                & (CADExtractionJob.lease_expires_at<now)
            )
        )
        .order_by(CADExtractionJob.created_at.asc())
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


def _persist_scene(
    db:Session,*,source:ArchitecturalSource,job:CADExtractionJob,
    actor_id:str,result:CADSemanticResult,
)->ArchitecturalScene:
    latest=db.scalars(select(ArchitecturalScene).where(
        ArchitecturalScene.tenant_id==source.tenant_id,
        ArchitecturalScene.project_id==source.project_id,
        ArchitecturalScene.source_id==source.id,
    ).order_by(ArchitecturalScene.version.desc())).first()
    scene=ArchitecturalScene(
        tenant_id=source.tenant_id,project_id=source.project_id,source_id=source.id,
        scene_schema_version="glip.arch.scene.v1",units="m",
        source_format=source.source_format,source_sha256=source.sha256,
        status="cad_semantic_ready",scene_json=result.scene,
        version=(latest.version+1 if latest else 1),created_by=actor_id,
    )
    db.add(scene);db.flush()
    job.scene_id=scene.id
    job.engine_version=result.engine_version
    job.statistics_json=result.statistics
    return scene


def process_cad_extraction_job(
    db:Session,*,settings,job:CADExtractionJob,engine=None,
)->ArchitecturalScene:
    source=db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id==job.source_id,
        ArchitecturalSource.tenant_id==job.tenant_id,
        ArchitecturalSource.project_id==job.project_id,
    ))
    if not source:
        job.status="failed";job.error_code="CAD_SOURCE_NOT_FOUND";job.completed_at=utcnow();db.flush()
        raise CADSemanticError("CAD_SOURCE_NOT_FOUND")
    if source.source_format!="dxf":
        job.status="failed";job.error_code="CAD_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED";job.completed_at=utcnow();db.flush()
        raise CADSemanticError("CAD_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED")
    engine=engine or EzdxfSemanticEngine()
    if getattr(settings,"cad_semantic_engine","ezdxf")!="ezdxf":
        raise CADSemanticError("CAD_ENGINE_UNSUPPORTED")
    storage=build_blob_storage(settings)
    with tempfile.NamedTemporaryFile(prefix="glip-cad-",suffix=".dxf",delete=False) as tmp:
        path=Path(tmp.name)
    try:
        storage.materialize(source.storage_key,path)
        h=hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):
                h.update(chunk)
        if h.hexdigest()!=source.sha256:
            raise CADSemanticError("CAD_SOURCE_INTEGRITY_MISMATCH")
        result=engine.extract(
            path,source_sha256=source.sha256,
            max_entities=int(getattr(settings,"cad_semantic_max_entities",100_000)),
        )
        scene=_persist_scene(db,source=source,job=job,actor_id=job.requested_by,result=result)
        job.status="completed";job.error_code=None;job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None
        source.status="cad_semantic_ready"
        db.add(ArtifactUsageEvent(
            tenant_id=source.tenant_id,project_id=source.project_id,billing_scope="glip",
            usage_type="cad_semantic_extraction",provider=result.engine,
            provider_profile_ref="glip-cad",
            units_json={
                "source_format":"dxf",
                "entities":result.statistics.get("entity_count",0),
                "layers":result.statistics.get("layer_count",0),
            },
            cost_microusd=None,
        ))
        db.flush()
        return scene
    except CADSemanticError as exc:
        job.status="failed";job.error_code=str(exc);job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None;db.flush();raise
    except Exception as exc:
        job.status="failed";job.error_code="CAD_SEMANTIC_INTERNAL_ERROR";job.completed_at=utcnow()
        job.lease_owner=None;job.lease_expires_at=None;db.flush()
        raise CADSemanticError("CAD_SEMANTIC_INTERNAL_ERROR") from exc
    finally:
        path.unlink(missing_ok=True)
