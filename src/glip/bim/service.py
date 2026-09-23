from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..artifacts.storage import build_blob_storage
from ..models import ArchitecturalScene, ArchitecturalSource, BIMExtractionJob, ArtifactUsageEvent
from .ifc_semantics import BIMSemanticError, IfcOpenShellSemanticEngine, SemanticExtractionResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_bim_extraction(
    db: Session,
    *,
    settings,
    tenant_id: str,
    project_id: str,
    source: ArchitecturalSource,
    actor_id: str,
) -> BIMExtractionJob:
    if not getattr(settings, "bim_semantic_enabled", False):
        raise BIMSemanticError("BIM_SEMANTIC_DISABLED")
    if source.source_format != "ifc":
        raise BIMSemanticError("BIM_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED")

    existing = db.scalar(select(BIMExtractionJob).where(
        BIMExtractionJob.tenant_id == tenant_id,
        BIMExtractionJob.project_id == project_id,
        BIMExtractionJob.source_id == source.id,
        BIMExtractionJob.source_sha256 == source.sha256,
        BIMExtractionJob.status.in_(["queued","processing","completed"]),
    ).order_by(BIMExtractionJob.created_at.desc()))
    if existing:
        return existing

    job = BIMExtractionJob(
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source.id,
        source_sha256=source.sha256,
        engine=getattr(settings, "bim_semantic_engine", "ifcopenshell"),
        status="queued",
        requested_by=actor_id,
    )
    db.add(job)
    db.flush()
    return job


def claim_next_bim_job(db: Session, *, settings, worker_id: str) -> BIMExtractionJob | None:
    lease_seconds = int(getattr(settings, "bim_job_lease_seconds", 300))
    now = utcnow()
    stmt = (
        select(BIMExtractionJob)
        .where(
            (BIMExtractionJob.status == "queued")
            | (
                (BIMExtractionJob.status == "processing")
                & (BIMExtractionJob.lease_expires_at.is_not(None))
                & (BIMExtractionJob.lease_expires_at < now)
            )
        )
        .order_by(BIMExtractionJob.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    job = db.scalar(stmt)
    if not job:
        return None
    job.status = "processing"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.started_at = job.started_at or now
    job.attempt_count = int(job.attempt_count or 0) + 1
    db.flush()
    return job


def _persist_scene(
    db: Session,
    *,
    source: ArchitecturalSource,
    job: BIMExtractionJob,
    actor_id: str,
    result: SemanticExtractionResult,
) -> ArchitecturalScene:
    latest = db.scalars(select(ArchitecturalScene).where(
        ArchitecturalScene.tenant_id == source.tenant_id,
        ArchitecturalScene.project_id == source.project_id,
        ArchitecturalScene.source_id == source.id,
    ).order_by(ArchitecturalScene.version.desc())).first()

    scene = ArchitecturalScene(
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        source_id=source.id,
        scene_schema_version="glip.arch.scene.v1",
        units="m",
        source_format=source.source_format,
        source_sha256=source.sha256,
        status="semantic_ready",
        scene_json=result.scene,
        version=(latest.version + 1 if latest else 1),
        created_by=actor_id,
    )
    db.add(scene)
    db.flush()
    job.scene_id = scene.id
    job.engine_version = result.engine_version
    job.statistics_json = result.statistics
    return scene


def process_bim_extraction_job(
    db: Session,
    *,
    settings,
    job: BIMExtractionJob,
    engine=None,
) -> ArchitecturalScene:
    source = db.scalar(select(ArchitecturalSource).where(
        ArchitecturalSource.id == job.source_id,
        ArchitecturalSource.tenant_id == job.tenant_id,
        ArchitecturalSource.project_id == job.project_id,
    ))
    if not source:
        job.status = "failed"
        job.error_code = "BIM_SOURCE_NOT_FOUND"
        job.completed_at = utcnow()
        db.flush()
        raise BIMSemanticError("BIM_SOURCE_NOT_FOUND")
    if source.source_format != "ifc":
        job.status = "failed"
        job.error_code = "BIM_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED"
        job.completed_at = utcnow()
        db.flush()
        raise BIMSemanticError("BIM_SEMANTIC_SOURCE_FORMAT_UNSUPPORTED")

    engine = engine or IfcOpenShellSemanticEngine()
    if getattr(settings, "bim_semantic_engine", "ifcopenshell") != "ifcopenshell":
        raise BIMSemanticError("BIM_ENGINE_UNSUPPORTED")

    storage = build_blob_storage(settings)
    suffix = ".ifc"
    with tempfile.NamedTemporaryFile(prefix="glip-bim-", suffix=suffix, delete=False) as tmp:
        path = Path(tmp.name)
    try:
        storage.materialize(source.storage_key, path)
        digest = __import__("hashlib").sha256()
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != source.sha256:
            raise BIMSemanticError("BIM_SOURCE_INTEGRITY_MISMATCH")
        result = engine.extract(
            path,
            source_sha256=source.sha256,
            max_elements=int(getattr(settings, "bim_semantic_max_elements", 100000)),
        )
        scene = _persist_scene(
            db,
            source=source,
            job=job,
            actor_id=job.requested_by,
            result=result,
        )
        job.status = "completed"
        job.error_code = None
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        source.status = "semantic_ready"
        db.add(ArtifactUsageEvent(
            tenant_id=source.tenant_id,
            project_id=source.project_id,
            billing_scope="glip",
            usage_type="bim_semantic_extraction",
            provider=result.engine,
            provider_profile_ref="glip-bim",
            units_json={
                "source_format":"ifc",
                "elements":result.statistics.get("element_count",0),
                "spatial":result.statistics.get("spatial_count",0),
            },
            cost_microusd=None,
        ))
        db.flush()
        return scene
    except BIMSemanticError as exc:
        job.status = "failed"
        job.error_code = str(exc)
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        db.flush()
        raise
    except Exception as exc:
        job.status = "failed"
        job.error_code = "BIM_SEMANTIC_INTERNAL_ERROR"
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        db.flush()
        raise BIMSemanticError("BIM_SEMANTIC_INTERNAL_ERROR") from exc
    finally:
        path.unlink(missing_ok=True)
