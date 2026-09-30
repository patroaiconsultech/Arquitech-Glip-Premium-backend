from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import now, uid
from .orm import Base


class UserInvitation(Base):
    __tablename__ = "user_invitations"
    __table_args__ = (
        UniqueConstraint("tenant_id","email_normalized",name="uq_user_invitation_tenant_email"),
        UniqueConstraint("token_digest",name="uq_user_invitation_token_digest"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    email_normalized: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str|None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(64))
    token_digest: Mapped[str] = mapped_column(String(64), index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    invited_by: Mapped[str] = mapped_column(String(255))
    accepted_membership_id: Mapped[str|None] = mapped_column(String(64), ForeignKey("memberships.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    accepted_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantAuditEvent(Base):
    __tablename__ = "tenant_audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str|None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str|None] = mapped_column(String(128), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class InvitationRateLimitBucket(Base):
    __tablename__ = "invitation_rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint("key_digest","window_started_at",name="uq_invitation_rate_limit_bucket"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    key_digest: Mapped[str] = mapped_column(String(64), index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
