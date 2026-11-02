"""Dedicated Visual AI worker, not executed from the HTTP request path.

At-most-once processing: a crash during provider execution leaves the job in
processing for operator review instead of silently retrying a billable image edit.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .artifacts.storage import BlobStorageError, build_blob_storage
from .models import ArtifactAsset, ArtifactJob, ArtifactUsageEvent, TenantAuditEvent
from .visual_ai_routes import DERIVED, JOB_KIND, ORIGINAL, _image_kind


class VisualAIError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def openai_edit(*, settings, source_bytes: bytes, source_mime: str, prompt: str, model: str | None = None):
    """Returns (PNG bytes, provider usage). No raw provider response in logs."""
    if settings.visual_ai_provider != "openai" or not settings.visual_ai_openai_api_key:
        raise VisualAIError("VISUAL_PROVIDER_NOT_CONFIGURED")
    selected_model = model or settings.visual_ai_model
    if not selected_model.startswith("gpt-image-"):
        raise VisualAIError("VISUAL_MODEL_INVALID")
    safe_instructions = (
        "Architectural conceptual study for professional review. "
        "Preserve original building geometry and camera composition where possible, "
        "unless the user expressly requests a different composition. "
        "Output a concept image, not a technically validated BIM update.\n"
        + prompt
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = client.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {settings.visual_ai_openai_api_key}"},
                data={"model": selected_model, "prompt": safe_instructions,
                      "output_format": "png"},
                files={"image": ("source-image", source_bytes, source_mime)},
            )
            response.raise_for_status()
            payload = response.json()
        encoded = payload["data"][0]["b64_json"]
        if not isinstance(encoded, str) or len(encoded) > 30_000_000:
            raise VisualAIError("VISUAL_PROVIDER_RESULT_INVALID")
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > 16_000_000:
            raise VisualAIError("VISUAL_PROVIDER_RESULT_TOO_LARGE")
        fmt, mime, _, _, _ = _image_kind(data)
        if fmt != "png" or mime != "image/png":
            raise VisualAIError("VISUAL_PROVIDER_RESULT_NOT_PNG")
        usage = payload.get("usage")
        return data, usage if isinstance(usage, dict) else {}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, binascii.Error) as exc:
        raise VisualAIError("VISUAL_PROVIDER_FAILED") from exc


def claim_visual_job(db: Session) -> str | None:
    job = db.scalar(select(ArtifactJob).where(
        ArtifactJob.artifact_kind == JOB_KIND, ArtifactJob.status == "queued",
    ).order_by(ArtifactJob.created_at, ArtifactJob.id).with_for_update(skip_locked=True))
    if not job:
        return None
    job.status = "processing"
    db.flush()
    return job.id


def process_visual_job(db: Session, *, settings, job_id: str, provider=openai_edit) -> str:
    job = db.scalar(select(ArtifactJob).where(
        ArtifactJob.id == job_id, ArtifactJob.artifact_kind == JOB_KIND,
        ArtifactJob.status == "processing",
    ))
    if not job:
        raise VisualAIError("VISUAL_JOB_NOT_PROCESSING")
    source = db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id == job.source_ref,
        ArtifactAsset.tenant_id == job.tenant_id,
        ArtifactAsset.project_id == job.project_id,
        ArtifactAsset.artifact_kind.in_([ORIGINAL, DERIVED]),
    ))
    if source is None:
        raise VisualAIError("VISUAL_SOURCE_MISSING")
    params = job.request_json or {}
    if not params.get("external_consent") or not isinstance(params.get("prompt"), str):
        raise VisualAIError("VISUAL_JOB_CONSENT_MISSING")
    storage = build_blob_storage(settings)
    try:
        source_bytes = storage.get(source.storage_key)
    except BlobStorageError as exc:
        raise VisualAIError("VISUAL_SOURCE_UNAVAILABLE") from exc
    # Avoid provider calls on unexpectedly substituted/corrupt source blobs.
    if hashlib.sha256(source_bytes).hexdigest() != source.sha256:
        raise VisualAIError("VISUAL_SOURCE_CHECKSUM_MISMATCH")
    output_bytes, usage = provider(
        settings=settings, source_bytes=source_bytes, source_mime=source.mime_type,
        prompt=params["prompt"], model=params.get("model"),
    )
    try:
        fmt, mime, ext, width, height = _image_kind(output_bytes)
    except ValueError as exc:
        raise VisualAIError("VISUAL_OUTPUT_INVALID") from exc
    if fmt != "png" or len(output_bytes) > 16_000_000:
        raise VisualAIError("VISUAL_OUTPUT_INVALID")
    asset_id = str(uuid4())
    key = f"{job.tenant_id}/visual-ai/{job.project_id}/{asset_id}{ext}"
    try:
        stored = storage.put_if_absent(key, output_bytes, content_type=mime)
        if not stored:
            raise VisualAIError("VISUAL_STORAGE_CONFLICT")
    except BlobStorageError as exc:
        raise VisualAIError("VISUAL_STORAGE_FAILED") from exc
    try:
        asset = ArtifactAsset(
            id=asset_id, tenant_id=job.tenant_id, project_id=job.project_id,
            artifact_kind=DERIVED, job_id=job.id, format=fmt,
            filename=f"estudo-visual-{asset_id[:8]}.png",
            mime_type=mime, storage_key=key,
            sha256=hashlib.sha256(output_bytes).hexdigest(),
            size_bytes=len(output_bytes), classification=source.classification,
            version=1, created_by=job.requested_by,
            metadata_json={
                "source": "ai_edit", "source_asset_id": source.id,
                "approval_status": "pending_review",
                "prompt": params["prompt"], "model": params.get("model"),
                "width": width, "height": height, "is_technical_revision": False,
            },
        )
        db.add(asset)
        db.add(ArtifactUsageEvent(
            tenant_id=job.tenant_id, project_id=job.project_id,
            artifact_job_id=job.id, billing_scope="glip",
            usage_type="visual_ai_image_edit", provider="openai",
            provider_profile_ref="visual-ai-openai",
            # Cost is intentionally unknown until reconciled with provider billing.
            cost_microusd=None, units_json={"provider_usage": usage},
        ))
        db.add(TenantAuditEvent(
            tenant_id=job.tenant_id, actor_id=job.requested_by,
            event_type="visual_image_generated", target_type="artifact_asset",
            target_id=asset.id, payload={"project_id": job.project_id, "source_asset_id": source.id},
        ))
        job.status = "completed"
        job.completed_at = _utcnow()
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete(key)
        except BlobStorageError:
            pass
        raise
    return asset_id
