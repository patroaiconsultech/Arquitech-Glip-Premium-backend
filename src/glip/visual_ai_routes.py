"""Project-scoped visual image studies. Reuses immutable ArtifactAsset / ArtifactJob tables.

No writes to Revit/Optiwork. Generated results are non-authoritative studies and
never overwrite the input. Worker operates outside the API process.
"""
from __future__ import annotations

import hashlib
import re
import struct
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .artifacts.storage import BlobStorageError, build_blob_storage
from .auth import Principal, get_principal
from .config import settings
from .context import mutable_project_or_409, project_or_404
from .database import get_db
from .models import ArtifactAsset, ArtifactJob, Tenant, TenantAuditEvent

router = APIRouter(prefix="/api/v1/projects/{project_id}/visual-ai", tags=["visual-ai"])
ORIGINAL = "visual_ai_original"
DERIVED = "visual_ai_derived"
JOB_KIND = "visual_ai_edit"
MAX_PIXELS = 32_000_000


def _enabled() -> None:
    if not settings.visual_ai_enabled:
        raise HTTPException(404, "visual_ai_disabled")


def _image_kind(raw: bytes) -> tuple[str, str, str, int, int]:
    """Validate basic image envelope and dimensions; never trust the supplied MIME."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        if len(raw) < 33:
            raise ValueError("image_invalid")
        width, height = struct.unpack(">II", raw[16:24])
        result = "png", "image/png", ".png", width, height
    elif raw[:3] == b"\xff\xd8\xff" and raw[-2:] == b"\xff\xd9":
        position = 2
        result = None
        while position + 4 < len(raw):
            if raw[position] != 0xFF:
                break
            while position < len(raw) and raw[position] == 0xFF:
                position += 1
            if position >= len(raw):
                break
            marker = raw[position]
            position += 1
            if marker in (0xD8, 0xD9):
                continue
            if marker in (0x01, *range(0xD0, 0xD8)):
                continue
            if position + 2 > len(raw):
                break
            length = int.from_bytes(raw[position:position+2], "big")
            if length < 2 or position + length > len(raw):
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if length < 7:
                    break
                height = int.from_bytes(raw[position+3:position+5], "big")
                width = int.from_bytes(raw[position+5:position+7], "big")
                result = "jpeg", "image/jpeg", ".jpg", width, height
                break
            position += length
        if result is None:
            raise ValueError("image_invalid")
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        if len(raw) < 30 or int.from_bytes(raw[4:8], "little") + 8 != len(raw):
            raise ValueError("image_invalid")
        kind = raw[12:16]
        if kind == b"VP8X":
            width = 1 + int.from_bytes(raw[24:27], "little")
            height = 1 + int.from_bytes(raw[27:30], "little")
        elif kind == b"VP8 " and len(raw) >= 30 and raw[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(raw[26:28], "little") & 0x3FFF
            height = int.from_bytes(raw[28:30], "little") & 0x3FFF
        elif kind == b"VP8L" and len(raw) >= 25 and raw[20] == 0x2F:
            bits = int.from_bytes(raw[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
        else:
            raise ValueError("image_invalid")
        result = "webp", "image/webp", ".webp", width, height
    else:
        raise ValueError("image_format_invalid")
    fmt, mime, extension, width, height = result
    if not (64 <= width <= 8192 and 64 <= height <= 8192 and width * height <= MAX_PIXELS):
        raise ValueError("image_dimensions_invalid")
    return fmt, mime, extension, width, height


def _asset_dict(asset: ArtifactAsset) -> dict:
    meta = asset.metadata_json or {}
    return {
        "id": asset.id,
        "filename": asset.filename,
        "sha256": asset.sha256,
        "size_bytes": asset.size_bytes,
        "format": asset.format,
        "kind": "original" if asset.artifact_kind == ORIGINAL else "derived",
        "source_asset_id": meta.get("source_asset_id"),
        "approval_status": meta.get("approval_status"),
        "created_at": asset.created_at,
        "prompt": meta.get("prompt") if asset.artifact_kind == DERIVED else None,
    }


def _asset_or_404(db: Session, tenant_id: str, project_id: str, asset_id: str) -> ArtifactAsset:
    asset = db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id == asset_id, ArtifactAsset.tenant_id == tenant_id,
        ArtifactAsset.project_id == project_id,
        ArtifactAsset.artifact_kind.in_([ORIGINAL, DERIVED]),
    ))
    if asset is None:
        raise HTTPException(404, "visual_image_not_found")
    return asset


@router.get("/capabilities")
def capabilities(project_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    return {
        "schema_version": "architech.visual-ai.v1",
        "enabled": settings.visual_ai_enabled,
        "editing_available": settings.visual_ai_enabled and settings.visual_ai_provider == "openai"
            and bool(settings.visual_ai_openai_api_key),
        "formats": ["png", "jpeg", "webp"],
        "max_upload_bytes": settings.visual_ai_max_input_bytes,
        "max_daily_edits": settings.visual_ai_max_daily_edits,
        "disclaimer": "Estudo visual, não revisão geométrica/BIM.",
    }


@router.get("/images")
def images(project_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    project_or_404(db, p.tenant_id, project_id)
    assets = db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.tenant_id == p.tenant_id,
        ArtifactAsset.project_id == project_id,
        ArtifactAsset.artifact_kind.in_([ORIGINAL, DERIVED]),
    ).order_by(ArtifactAsset.created_at.desc(), ArtifactAsset.id.desc()).limit(200)).all()
    return [_asset_dict(a) for a in assets]


@router.post("/images", status_code=201)
def upload_image(
    project_id: str,
    file: UploadFile = File(...),
    classification: str = Form("project_internal"),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _enabled()
    mutable_project_or_409(db, p.tenant_id, project_id)
    if classification not in {"project_internal", "confidential"}:
        raise HTTPException(422, "visual_classification_invalid")
    raw = file.file.read(settings.visual_ai_max_input_bytes + 1)
    if not raw or len(raw) > settings.visual_ai_max_input_bytes:
        raise HTTPException(413, "visual_image_size_invalid")
    try:
        fmt, mime, ext, width, height = _image_kind(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", (file.filename or "imagem").rsplit(".", 1)[0])[:90] or "imagem"
    asset_id = str(uuid4())
    key = f"{p.tenant_id}/visual-ai/{project_id}/{asset_id}{ext}"
    storage = build_blob_storage(settings)
    stored = False
    try:
        stored = storage.put_if_absent(key, raw, content_type=mime)
        if not stored:
            raise HTTPException(409, "visual_storage_conflict")
        asset = ArtifactAsset(
            id=asset_id, tenant_id=p.tenant_id, project_id=project_id,
            artifact_kind=ORIGINAL, format=fmt, filename=f"{safe_stem}{ext}",
            mime_type=mime, storage_key=key, sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), classification=classification, version=1,
            metadata_json={"source": "manual_upload", "width": width, "height": height},
            created_by=p.subject,
        )
        db.add(asset)
        db.flush()
        db.commit()
        return _asset_dict(asset)
    except Exception:
        db.rollback()
        if stored:
            try:
                storage.delete(key)
            except BlobStorageError:
                pass
        raise


@router.get("/images/{asset_id}/content")
def image_content(project_id: str, asset_id: str,
                  p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    project_or_404(db, p.tenant_id, project_id)
    asset = _asset_or_404(db, p.tenant_id, project_id, asset_id)
    try:
        raw = build_blob_storage(settings).get(asset.storage_key)
    except BlobStorageError as exc:
        raise HTTPException(503, "visual_image_unavailable") from exc
    return Response(
        raw, media_type=asset.mime_type, headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="visual-study.' + asset.format + '"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class EditRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=1500)
    consent_external_processing: bool


@router.post("/images/{asset_id}/edits", status_code=202)
def request_edit(project_id: str, asset_id: str, body: EditRequest,
                 p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    mutable_project_or_409(db, p.tenant_id, project_id)
    _asset_or_404(db, p.tenant_id, project_id, asset_id)
    if not body.consent_external_processing:
        raise HTTPException(422, "visual_external_processing_consent_required")
    if settings.visual_ai_provider != "openai" or not settings.visual_ai_openai_api_key:
        raise HTTPException(503, "visual_provider_not_configured")
    prompt = body.prompt.strip()
    if len(prompt) < 10:
        raise HTTPException(422, "visual_prompt_too_short")
    # Serialize issuance by tenant. PostgreSQL row lock is authoritative in production.
    db.scalar(select(Tenant).where(Tenant.id == p.tenant_id).with_for_update())
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    used = db.scalar(select(func.count(ArtifactJob.id)).where(
        ArtifactJob.tenant_id == p.tenant_id,
        ArtifactJob.artifact_kind == JOB_KIND,
        ArtifactJob.created_at >= cutoff,
    )) or 0
    if used >= settings.visual_ai_max_daily_edits:
        raise HTTPException(429, "visual_daily_quota_exceeded")
    job = ArtifactJob(
        tenant_id=p.tenant_id, project_id=project_id,
        artifact_kind=JOB_KIND, requested_format="png", status="queued",
        source_kind="visual_ai_asset", source_ref=asset_id,
        request_json={"prompt": prompt, "external_consent": True,
                      "model": settings.visual_ai_model},
        billing_scope="glip", provider_profile_ref="visual-ai-openai",
        requested_by=p.subject,
    )
    db.add(job)
    db.commit()
    return {"id": job.id, "status": job.status, "message": "Edição enfileirada. Estudo sujeito à revisão."}


@router.get("/jobs")
def jobs(project_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    project_or_404(db, p.tenant_id, project_id)
    records = db.scalars(select(ArtifactJob).where(
        ArtifactJob.tenant_id == p.tenant_id,
        ArtifactJob.project_id == project_id,
        ArtifactJob.artifact_kind == JOB_KIND,
    ).order_by(ArtifactJob.created_at.desc()).limit(100)).all()
    return [{
        "id": j.id, "status": j.status, "source_asset_id": j.source_ref,
        "error_code": j.error_code, "created_at": j.created_at,
        "completed_at": j.completed_at,
    } for j in records]


class DecisionRequest(BaseModel):
    decision: str


@router.post("/images/{asset_id}/decision")
def decide(project_id: str, asset_id: str, body: DecisionRequest,
           p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    mutable_project_or_409(db, p.tenant_id, project_id)
    if p.role not in {"owner", "admin", "architect"}:
        raise HTTPException(403, "visual_review_role_required")
    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(422, "visual_decision_invalid")
    asset = _asset_or_404(db, p.tenant_id, project_id, asset_id)
    if asset.artifact_kind != DERIVED:
        raise HTTPException(409, "visual_original_cannot_be_reviewed")
    # A row lock prevents concurrent/double review in PostgreSQL.
    db.scalar(select(ArtifactAsset).where(ArtifactAsset.id == asset.id)
              .with_for_update().execution_options(populate_existing=True))
    if (asset.metadata_json or {}).get("approval_status") != "pending_review":
        raise HTTPException(409, "visual_already_reviewed")
    asset.metadata_json = {**(asset.metadata_json or {}),
                           "approval_status": body.decision, "reviewed_by": p.subject,
                           "reviewed_at": datetime.now(timezone.utc).isoformat()}
    db.add(TenantAuditEvent(
        tenant_id=p.tenant_id, actor_id=p.subject, event_type="visual_image_review",
        target_type="artifact_asset", target_id=asset.id,
        payload={"project_id": project_id, "decision": body.decision},
    ))
    db.commit()
    return _asset_dict(asset)
