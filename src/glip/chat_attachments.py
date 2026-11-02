"""Project-scoped, private chat attachments; no implicit AI ingestion.

Uses existing ArtifactAsset rows and BlobStorage. All downloads and uses
are scoped to tenant, project, thread, and uploading user.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
from urllib.parse import quote
import hashlib
import re
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .artifacts.storage import BlobStorageError, build_blob_storage
from .audit import emit
from .auth import Principal, get_principal
from .chat_models import ChatThread
from .config import settings
from .context import mutable_project_or_409, project_or_404
from .database import get_db
from .models import ArtifactAsset

router = APIRouter(prefix="/api/v1/chat", tags=["chat-attachments"])
TEXT_LIMIT = 10_000
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt", ".md", ".docx"}


def _enabled():
    if not settings.chat_attachments_enabled:
        raise HTTPException(404, "chat_attachments_disabled")


def _thread(db: Session, p: Principal, thread_id: str) -> ChatThread:
    row = db.scalar(select(ChatThread).where(
        ChatThread.id == thread_id,
        ChatThread.tenant_id == p.tenant_id,
        ChatThread.status == "active",
    ))
    if row is None:
        raise HTTPException(404, "chat_thread_not_found")
    if row.project_id is None:
        raise HTTPException(422, "chat_attachment_requires_project")
    # Attachment threads are restricted to their creator, avoiding disclosure
    # of sensitive file-derived conversation content within a shared tenant.
    if row.created_by != p.subject:
        raise HTTPException(404, "chat_thread_not_found")
    project_or_404(db, p.tenant_id, row.project_id)
    return row


def _clean_name(name: str) -> str:
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    if not name or len(name) > 160:
        raise HTTPException(422, "chat_attachment_filename_invalid")
    return name


def _detect(filename: str, data: bytes) -> tuple[str, str]:
    suffix = PurePath(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "chat_attachment_format_unsupported")
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"):
        return "jpeg", "image/jpeg"
    if suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if suffix == ".docx" and zipfile.is_zipfile(BytesIO(data)):
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".txt", ".md"} and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeError as exc:
            raise HTTPException(415, "chat_attachment_text_encoding_invalid") from exc
        return suffix[1:], "text/plain; charset=utf-8"
    raise HTTPException(415, "chat_attachment_content_invalid")


def _text_preview(fmt: str, data: bytes) -> tuple[str, str]:
    """Extract a bounded preview; failure never silently implies readable data."""
    if fmt in {"png", "jpeg", "webp"}:
        return "", "image_not_analyzed"
    if fmt in {"txt", "md"}:
        text = data.decode("utf-8").strip()
        return text[:TEXT_LIMIT], "ready" if text else "no_extractable_text"
    if fmt == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data), strict=False)
            if len(reader.pages) > 30:
                return "", "page_limit_exceeded"
            chunks = []
            for page in reader.pages:
                chunks.append(page.extract_text() or "")
                if sum(len(c) for c in chunks) >= TEXT_LIMIT:
                    break
            result = "\n".join(chunks).strip()[:TEXT_LIMIT]
            return result, "ready" if result else "no_extractable_text"
        except Exception:
            return "", "extraction_failed"
    if fmt == "docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                parts = z.infolist()
                if len(parts) > 150 or sum(x.file_size for x in parts) > 32_000_000:
                    return "", "extraction_limits_exceeded"
                if "word/document.xml" not in z.namelist():
                    return "", "extraction_failed"
                node = z.getinfo("word/document.xml")
                if node.file_size > 12_000_000:
                    return "", "extraction_limits_exceeded"
                from defusedxml import ElementTree as SafeET
                xml = SafeET.fromstring(z.read(node))
            words = []
            for el in xml.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                if el.text:
                    words.append(el.text)
                if sum(map(len, words)) >= TEXT_LIMIT:
                    break
            result = " ".join(words).strip()[:TEXT_LIMIT]
            return result, "ready" if result else "no_extractable_text"
        except Exception:
            return "", "extraction_failed"
    return "", "unsupported"


def _payload(item: ArtifactAsset) -> dict:
    metadata = item.metadata_json or {}
    return {
        "id": item.id,
        "filename": item.filename,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "extraction_status": metadata.get("extraction_status", "unknown"),
        "linked_message_id": metadata.get("linked_message_id"),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _assets(db: Session, p: Principal, thread: ChatThread) -> list[ArtifactAsset]:
    return db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.tenant_id == p.tenant_id,
        ArtifactAsset.project_id == thread.project_id,
        ArtifactAsset.artifact_kind == "chat_attachment",
        ArtifactAsset.created_by == p.subject,
    )).all()


def resolve_for_message(
    db: Session, p: Principal, thread: ChatThread, ids: object
) -> tuple[list[ArtifactAsset], list[dict]]:
    """Validate ownership/scope before invoking the model or persisting message."""
    if not ids:
        return [], []
    _enabled()
    if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(i, str) for i in ids):
        raise HTTPException(422, "chat_attachment_ids_invalid")
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "chat_attachment_ids_repeated")
    _thread(db, p, thread.id)
    rows = db.scalars(select(ArtifactAsset).where(
        ArtifactAsset.id.in_(ids),
        ArtifactAsset.tenant_id == p.tenant_id,
        ArtifactAsset.project_id == thread.project_id,
        ArtifactAsset.artifact_kind == "chat_attachment",
        ArtifactAsset.created_by == p.subject,
    )).all()
    if len(rows) != len(ids) or any((r.metadata_json or {}).get("thread_id") != thread.id for r in rows):
        raise HTTPException(404, "chat_attachment_not_found")
    if any((r.metadata_json or {}).get("linked_message_id") for r in rows):
        raise HTTPException(409, "chat_attachment_already_used")
    ordered = {r.id: r for r in rows}
    rows = [ordered[i] for i in ids]
    context = []
    for row in rows:
        meta = row.metadata_json or {}
        context.append({
            "source_ref": f"glip-chat-attachment:{row.id}",
            "filename": row.filename,
            "extraction_status": meta.get("extraction_status"),
            "extracted_text": meta.get("preview_text", "")[:TEXT_LIMIT],
        })
    return rows, context


@router.get("/threads/{thread_id}/attachments")
def list_attachments(thread_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _enabled()
    thread = _thread(db, p, thread_id)
    return [_payload(a) for a in _assets(db, p, thread) if (a.metadata_json or {}).get("thread_id") == thread.id]


@router.post("/threads/{thread_id}/attachments", status_code=201)
async def upload_attachment(
    thread_id: str,
    file: UploadFile = File(...),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _enabled()
    thread = _thread(db, p, thread_id)
    mutable_project_or_409(db, p.tenant_id, thread.project_id)
    existing = _assets(db, p, thread)
    if sum((a.metadata_json or {}).get("thread_id") == thread.id for a in existing) >= 20:
        raise HTTPException(429, "chat_attachment_thread_limit")

    filename = _clean_name(file.filename)
    data = await file.read(settings.chat_attachment_max_bytes + 1)
    if not data:
        raise HTTPException(422, "chat_attachment_empty")
    if len(data) > settings.chat_attachment_max_bytes:
        raise HTTPException(413, "chat_attachment_too_large")
    fmt, mime = _detect(filename, data)
    preview, extraction = await run_in_threadpool(_text_preview, fmt, data)
    digest = hashlib.sha256(data).hexdigest()

    asset = ArtifactAsset(
        tenant_id=p.tenant_id,
        project_id=thread.project_id,
        artifact_kind="chat_attachment",
        format=fmt,
        filename=filename,
        mime_type=mime,
        storage_key="",  # filled after generation of DB identity
        sha256=digest,
        size_bytes=len(data),
        classification="project_internal",
        metadata_json={
            "thread_id": thread.id,
            "linked_message_id": None,
            "extraction_status": extraction,
            "preview_text": preview,
        },
        created_by=p.subject,
    )
    db.add(asset)
    db.flush()
    asset.storage_key = f"chat-attachments/{p.tenant_id}/{thread.project_id}/{asset.id}/{digest}"
    storage = build_blob_storage(settings)
    written = False
    try:
        written = storage.put_if_absent(asset.storage_key, data, content_type=mime)
        if not written:
            raise BlobStorageError("BLOB_KEY_COLLISION")
        emit(db, tenant_id=p.tenant_id, project_id=thread.project_id, actor_id=p.subject,
             event_type="chat.attachment.uploaded", payload={
                 "thread_id": thread.id, "asset_id": asset.id, "sha256": digest,
                 "size_bytes": len(data), "extraction_status": extraction,
             })
        db.commit()
        db.refresh(asset)
    except Exception:
        db.rollback()
        if written:
            try:
                storage.delete(asset.storage_key)
            except Exception:
                pass
        raise HTTPException(503, "chat_attachment_storage_unavailable")
    return _payload(asset)


@router.get("/threads/{thread_id}/attachments/{attachment_id}/download")
def download_attachment(
    thread_id: str,
    attachment_id: str,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _enabled()
    thread = _thread(db, p, thread_id)
    item = db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id == attachment_id,
        ArtifactAsset.tenant_id == p.tenant_id,
        ArtifactAsset.project_id == thread.project_id,
        ArtifactAsset.artifact_kind == "chat_attachment",
        ArtifactAsset.created_by == p.subject,
    ))
    if not item or (item.metadata_json or {}).get("thread_id") != thread.id:
        raise HTTPException(404, "chat_attachment_not_found")
    try:
        raw = build_blob_storage(settings).get(item.storage_key)
    except BlobStorageError as exc:
        raise HTTPException(503, "chat_attachment_storage_unavailable") from exc
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(item.filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(raw, media_type=item.mime_type, headers=headers)


@router.delete("/threads/{thread_id}/attachments/{attachment_id}", status_code=204)
def delete_unlinked_attachment(
    thread_id: str,
    attachment_id: str,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """The uploader may remove a pending upload before submitting it to chat."""
    _enabled()
    thread = _thread(db, p, thread_id)
    item = db.scalar(select(ArtifactAsset).where(
        ArtifactAsset.id == attachment_id,
        ArtifactAsset.tenant_id == p.tenant_id,
        ArtifactAsset.project_id == thread.project_id,
        ArtifactAsset.artifact_kind == "chat_attachment",
        ArtifactAsset.created_by == p.subject,
    ))
    if not item or (item.metadata_json or {}).get("thread_id") != thread.id:
        raise HTTPException(404, "chat_attachment_not_found")
    if (item.metadata_json or {}).get("linked_message_id"):
        raise HTTPException(409, "chat_attachment_already_used")

    # DB first avoids exposing an unreferenced file; a failed object delete may
    # leave an orphan, to be reconciled by storage lifecycle policy.
    key = item.storage_key
    db.delete(item)
    emit(db, tenant_id=p.tenant_id, project_id=thread.project_id, actor_id=p.subject,
         event_type="chat.attachment.deleted", payload={
             "thread_id": thread.id, "asset_id": attachment_id,
         })
    db.commit()
    try:
        build_blob_storage(settings).delete(key)
    except BlobStorageError as exc:
        # Explicitly observable failure; DB delete has already committed.
        raise HTTPException(503, "chat_attachment_blob_cleanup_pending") from exc
    return Response(status_code=204)
