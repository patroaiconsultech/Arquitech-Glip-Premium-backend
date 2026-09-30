from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import emit
from .auth import Principal, get_principal
from .chat_models import ChatMessage, ChatThread
from .chat_service import ChatProviderError, chat_status, generate_reply
from .context import build, project_or_404
from .database import get_db
from .models import now


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _thread_or_404(db: Session, tenant_id: str, thread_id: str) -> ChatThread:
    thread = db.scalar(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.tenant_id == tenant_id,
            ChatThread.status == "active",
        )
    )
    if not thread:
        raise HTTPException(404, "chat_thread_not_found")
    return thread


def _message_payload(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "project_id": message.project_id,
        "role": message.role,
        "content": message.content,
        "actor_id": message.actor_id,
        "provider": message.provider,
        "model": message.model,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.get("/status")
def status(p: Principal = Depends(get_principal)):
    return {
        "status": "available" if chat_status()["configured"] else "not_configured",
        **chat_status(),
    }


@router.get("/threads")
def list_threads(
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    items = db.scalars(
        select(ChatThread).where(
            ChatThread.tenant_id == p.tenant_id,
            ChatThread.status == "active",
        ).order_by(ChatThread.updated_at.desc())
    ).all()
    return [
        {
            "id": x.id,
            "project_id": x.project_id,
            "title": x.title,
            "created_by": x.created_by,
            "created_at": x.created_at.isoformat() if x.created_at else None,
            "updated_at": x.updated_at.isoformat() if x.updated_at else None,
        }
        for x in items
    ]


@router.post("/threads", status_code=201)
def create_thread(
    body: dict,
    x_correlation_id: str | None = Header(None),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    project_id = str(body.get("project_id") or "").strip() or None
    if project_id:
        project_or_404(db, p.tenant_id, project_id)

    title = str(body.get("title") or "Nova conversa").strip()[:200] or "Nova conversa"
    thread = ChatThread(
        tenant_id=p.tenant_id,
        project_id=project_id,
        title=title,
        created_by=p.subject,
        status="active",
    )
    db.add(thread)
    db.flush()
    emit(
        db,
        tenant_id=p.tenant_id,
        project_id=project_id,
        actor_id=p.subject,
        event_type="chat.thread.created",
        correlation_id=x_correlation_id,
        payload={"thread_id": thread.id},
    )
    db.commit()
    db.refresh(thread)
    return {
        "id": thread.id,
        "project_id": thread.project_id,
        "title": thread.title,
        "created_by": thread.created_by,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
    }


@router.get("/threads/{thread_id}/messages")
def list_messages(
    thread_id: str,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    thread = _thread_or_404(db, p.tenant_id, thread_id)
    items = db.scalars(
        select(ChatMessage).where(
            ChatMessage.tenant_id == p.tenant_id,
            ChatMessage.thread_id == thread.id,
        ).order_by(ChatMessage.created_at.asc())
    ).all()
    return [_message_payload(x) for x in items]


@router.post("/threads/{thread_id}/messages")
def send_message(
    thread_id: str,
    body: dict,
    x_request_id: str | None = Header(None),
    x_correlation_id: str | None = Header(None),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    thread = _thread_or_404(db, p.tenant_id, thread_id)
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(422, "chat_message_required")
    if len(content) > 8000:
        raise HTTPException(422, "chat_message_too_long")

    request_id = x_request_id or str(uuid4())
    correlation_id = x_correlation_id or request_id

    context = None
    if thread.project_id:
        # Read-only project context. Archived projects remain readable.
        context = build(
            db,
            p.tenant_id,
            thread.project_id,
            p.subject,
            correlation_id,
            purpose="chat",
        )

    previous = db.scalars(
        select(ChatMessage).where(
            ChatMessage.tenant_id == p.tenant_id,
            ChatMessage.thread_id == thread.id,
        ).order_by(ChatMessage.created_at.desc()).limit(20)
    ).all()
    history = [
        {"role": x.role, "content": x.content}
        for x in reversed(previous)
        if x.role in {"user", "assistant"}
    ]

    user_message = ChatMessage(
        tenant_id=p.tenant_id,
        thread_id=thread.id,
        project_id=thread.project_id,
        role="user",
        content=content,
        actor_id=p.subject,
    )
    db.add(user_message)
    if thread.title == "Nova conversa":
        thread.title = content[:80]
    thread.updated_at = now()
    emit(
        db,
        tenant_id=p.tenant_id,
        project_id=thread.project_id,
        actor_id=p.subject,
        event_type="chat.message.user",
        correlation_id=correlation_id,
        payload={"thread_id": thread.id, "message_id": user_message.id},
    )
    db.commit()
    db.refresh(user_message)

    try:
        answer, provider, model = generate_reply(
            messages=history + [{"role": "user", "content": content}],
            project_context=context,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except ChatProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

    assistant_message = ChatMessage(
        tenant_id=p.tenant_id,
        thread_id=thread.id,
        project_id=thread.project_id,
        role="assistant",
        content=answer,
        actor_id="glip-intelligence",
        provider=provider,
        model=model,
    )
    db.add(assistant_message)
    thread.updated_at = now()
    emit(
        db,
        tenant_id=p.tenant_id,
        project_id=thread.project_id,
        actor_id="glip-intelligence",
        event_type="chat.message.assistant",
        correlation_id=correlation_id,
        payload={
            "thread_id": thread.id,
            "message_id": assistant_message.id,
            "provider": provider,
            "model": model,
        },
    )
    db.commit()
    db.refresh(assistant_message)

    return {
        "thread_id": thread.id,
        "user_message": _message_payload(user_message),
        "assistant_message": _message_payload(assistant_message),
    }
