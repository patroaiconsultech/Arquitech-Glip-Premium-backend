from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .orm import Base
from .models import uid, now


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="Nova conversa")
    created_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at = mapped_column(DateTime(timezone=True), default=now)
    updated_at = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_threads.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=now, index=True)
