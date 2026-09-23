from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, Integer, BigInteger, Boolean, DateTime, JSON, Numeric, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .orm import Base

def uid() -> str:
    return str(uuid4())

def now() -> datetime:
    return datetime.now(timezone.utc)

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id","external_subject",name="uq_membership_subject"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    external_subject: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str|None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="member")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NativeCredential(Base):
    __tablename__ = "native_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id","email_normalized",name="uq_native_credential_tenant_email"),
        UniqueConstraint("membership_id",name="uq_native_credential_membership"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    membership_id: Mapped[str] = mapped_column(String(64), ForeignKey("memberships.id"), index=True)
    email_normalized: Mapped[str] = mapped_column(String(320), index=True)
    password_salt_b64: Mapped[str] = mapped_column(String(128))
    password_hash_b64: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeAuthSession(Base):
    __tablename__ = "native_auth_sessions"
    __table_args__ = (UniqueConstraint("token_digest",name="uq_native_auth_session_digest"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(64), ForeignKey("native_credentials.id"), index=True)
    membership_id: Mapped[str] = mapped_column(String(64), ForeignKey("memberships.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeAuthEvent(Base):
    __tablename__ = "native_auth_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    identity_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    event_code: Mapped[str] = mapped_column(String(80), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(240))
    email: Mapped[str|None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str|None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id","code",name="uq_project_code"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(240))
    code: Mapped[str|None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    current_stage: Mapped[str|None] = mapped_column(String(120), nullable=True)
    description: Mapped[str|None] = mapped_column(Text, nullable=True)
    address_summary: Mapped[str|None] = mapped_column(Text, nullable=True)
    context_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ProjectCognitiveProfile(Base):
    __tablename__ = "project_cognitive_profiles"
    __table_args__ = (UniqueConstraint("tenant_id","project_id",name="uq_project_cognitive_profile"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    baseline_id: Mapped[str] = mapped_column(String(160))
    baseline_version: Mapped[str] = mapped_column(String(32))
    policy_profile_id: Mapped[str] = mapped_column(String(160))
    voice_profile_id: Mapped[str] = mapped_column(String(160))
    memory_namespace: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    enabled_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ProjectStage(Base):
    __tablename__ = "project_stages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")

class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(240))
    email: Mapped[str|None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str|None] = mapped_column(String(64), nullable=True)
    specialty: Mapped[str|None] = mapped_column(String(160), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ProjectProvider(Base):
    __tablename__ = "project_providers"
    __table_args__ = (UniqueConstraint("tenant_id","project_id","provider_id",name="uq_project_provider"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str|None] = mapped_column(String(160), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open")
    due_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="planned")
    due_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80), default="project")
    status: Mapped[str] = mapped_column(String(32), default="planned")
    starts_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_ref: Mapped[str|None] = mapped_column(String(255), nullable=True)

class BudgetSnapshot(Base):
    __tablename__ = "budget_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(8), default="BRL")
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    storage_ref: Mapped[str] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(80), default="project_internal")
    allowed_purposes: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ProjectKnowledgeItem(Base):
    __tablename__ = "project_knowledge_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_key: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(80), default="INTERNAL")
    allowed_purposes: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")
    approved_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class ProjectMemoryFact(Base):
    __tablename__ = "project_memory_facts"
    __table_args__ = (UniqueConstraint("tenant_id","project_id","fact_key","version",name="uq_project_memory_fact_version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    fact_key: Mapped[str] = mapped_column(String(180))
    fact_value: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(80), default="INTERNAL")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")
    source_approved_version_id: Mapped[str] = mapped_column(String(64), index=True)
    approved_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class MemoryCandidate(Base):
    __tablename__ = "memory_candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_approved_version_id: Mapped[str] = mapped_column(String(64), index=True)
    candidate_type: Mapped[str] = mapped_column(String(120), default="approved_communication_pattern")
    source_content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_by: Mapped[str|None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class CognitiveExecution(Base):
    __tablename__ = "cognitive_executions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    capability_id: Mapped[str] = mapped_column(String(160))
    capability_version: Mapped[str] = mapped_column(String(32))
    project_context_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int|None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="requested")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (UniqueConstraint("draft_id","version",name="uq_draft_version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by_type: Mapped[str] = mapped_column(String(32))
    created_by_id: Mapped[str] = mapped_column(String(255))
    capability_id: Mapped[str] = mapped_column(String(160), default="glip.draft_message")
    capability_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    voice_profile_id: Mapped[str|None] = mapped_column(String(160), nullable=True)
    project_context_version: Mapped[int] = mapped_column(Integer)
    risk_scan: Mapped[dict] = mapped_column(JSON, default=dict)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_version_id: Mapped[str] = mapped_column(String(64), index=True)
    requested_content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval")
    requested_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    approval_request_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_version_id: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    approved_content_sha256: Mapped[str|None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ApprovedVersion(Base):
    __tablename__ = "approved_versions"
    __table_args__ = (UniqueConstraint("tenant_id","draft_version_id",name="uq_approved_draft_version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_version_id: Mapped[str] = mapped_column(String(64), index=True)
    approval_decision_id: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    capability_id: Mapped[str] = mapped_column(String(160))
    capability_version: Mapped[str] = mapped_column(String(32))
    voice_profile_id: Mapped[str|None] = mapped_column(String(160), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(255))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ExternalDelivery(Base):
    """
    Reserved system-of-record table for a future approved delivery adapter.
    V0.5 intentionally exposes NO send/publish endpoint.
    """
    __tablename__ = "external_deliveries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    approved_version_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="not_dispatched")
    provider_message_id: Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(160), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    causation_id: Mapped[str|None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ProjectAuditEvent(Base):
    __tablename__ = "project_audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(160), index=True)
    correlation_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectDecision(Base):
    __tablename__ = "project_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open")
    decision: Mapped[str|None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str|None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class ProjectAsset(Base):
    __tablename__ = "project_assets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), default="media")
    name: Mapped[str] = mapped_column(String(255))
    storage_ref: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str|None] = mapped_column(String(160), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    classification: Mapped[str] = mapped_column(String(80), default="project_internal")
    status: Mapped[str] = mapped_column(String(32), default="active")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ProjectCommunication(Base):
    __tablename__ = "project_communications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(32), default="internal")
    channel: Mapped[str] = mapped_column(String(32), default="internal")
    contact_ref: Mapped[str|None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str|None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="recorded")
    approved_version_id: Mapped[str|None] = mapped_column(String(64), nullable=True)
    external_message_id: Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntegrationExecution(Base):
    __tablename__ = "integration_executions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id","destination_service","idempotency_key",
            name="uq_integration_idempotency",
        ),
        UniqueConstraint(
            "tenant_id","execution_id",
            name="uq_integration_execution_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    destination_service: Mapped[str] = mapped_column(String(80), default="orkio")
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    capability_version: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[str] = mapped_column(String(128), index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSON)
    upstream_response_json: Mapped[dict|None] = mapped_column(JSON, nullable=True)
    domain_response_json: Mapped[dict|None] = mapped_column(JSON, nullable=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    cognitive_execution_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="contextualized")
    owner_token: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    lease_expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int|None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class ArtifactJob(Base):
    __tablename__ = "artifact_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), default="document")
    requested_format: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    source_kind: Mapped[str] = mapped_column(String(64), default="user_content")
    source_ref: Mapped[str|None] = mapped_column(String(255), nullable=True)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    billing_scope: Mapped[str] = mapped_column(String(64), default="glip", index=True)
    provider_profile_ref: Mapped[str|None] = mapped_column(String(160), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArtifactAsset(Base):
    __tablename__ = "artifact_assets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), default="document", index=True)
    format: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(160))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(80), default="project_internal")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArtifactUsageEvent(Base):
    __tablename__ = "artifact_usage_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_job_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    render_job_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    billing_scope: Mapped[str] = mapped_column(String(64), default="glip", index=True)
    usage_type: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str|None] = mapped_column(String(80), nullable=True)
    provider_profile_ref: Mapped[str|None] = mapped_column(String(160), nullable=True)
    units_json: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_microusd: Mapped[int|None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArchitecturalSource(Base):
    __tablename__ = "architectural_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id","project_id","sha256",name="uq_arch_source_project_sha"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_format: Mapped[str] = mapped_column(String(32), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str|None] = mapped_column(String(160), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(80), default="project_internal")
    ifc_schema: Mapped[str|None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArchitecturalScene(Base):
    __tablename__ = "architectural_scenes"
    __table_args__ = (
        UniqueConstraint("tenant_id","project_id","source_id","version",name="uq_arch_scene_source_version"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    scene_schema_version: Mapped[str] = mapped_column(String(64), default="glip.arch.scene.v1")
    units: Mapped[str] = mapped_column(String(16), default="mm")
    source_format: Mapped[str] = mapped_column(String(32))
    source_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    scene_json: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)



class BIMExtractionJob(Base):
    __tablename__ = "bim_extraction_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    engine: Mapped[str] = mapped_column(String(64), default="ifcopenshell")
    engine_version: Mapped[str|None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    scene_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    statistics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str|None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class RenderJob(Base):
    __tablename__ = "render_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    scene_id: Mapped[str] = mapped_column(String(64), index=True)
    render_type: Mapped[str] = mapped_column(String(32), default="technical")
    engine: Mapped[str] = mapped_column(String(64), default="blender")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_artifact_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    billing_scope: Mapped[str] = mapped_column(String(64), default="glip", index=True)
    provider_profile_ref: Mapped[str|None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)



class CADExtractionJob(Base):
    __tablename__ = "cad_extraction_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    engine: Mapped[str] = mapped_column(String(64), default="ezdxf")
    engine_version: Mapped[str|None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    scene_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    statistics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str|None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class GeometryBuildJob(Base):
    __tablename__ = "geometry_build_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    scene_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    build_kind: Mapped[str] = mapped_column(String(48), default="preview_glb")
    engine: Mapped[str] = mapped_column(String(64), default="trimesh")
    engine_version: Mapped[str|None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    output_artifact_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    statistics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str|None] = mapped_column(String(120), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str|None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class PriceSourceSnapshot(Base):
    __tablename__ = "price_source_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id","source_key","evidence_sha256",name="uq_price_snapshot_evidence"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    source_key: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(120), index=True)
    publisher: Mapped[str] = mapped_column(String(200))
    roles_json: Mapped[list] = mapped_column(JSON, default=list)
    geography_json: Mapped[dict] = mapped_column(JSON, default=dict)
    competency: Mapped[str] = mapped_column(String(32), index=True)
    source_ref: Mapped[str] = mapped_column(String(1000))
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    validity_status: Mapped[str] = mapped_column(String(40), default="human_review_required", index=True)
    authority_status: Mapped[str] = mapped_column(String(40), default="unverified", index=True)
    authority_method: Mapped[str|None] = mapped_column(String(80), nullable=True)
    authority_by: Mapped[str|None] = mapped_column(String(255), nullable=True)
    authority_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    billing_scope: Mapped[str] = mapped_column(String(64), default="glip", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PriceSourceItem(Base):
    __tablename__ = "price_source_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id","source_code","unit","role",name="uq_price_item_snapshot_code_unit_role"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), index=True)
    source_code: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="BRL")
    unit_price_cents: Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    manually_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuantityPriceMapping(Base):
    __tablename__ = "quantity_price_mappings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    canonical_item_id: Mapped[str] = mapped_column(String(160), index=True)
    quantity_source_ref: Mapped[str] = mapped_column(String(500))
    quantity_value: Mapped[float] = mapped_column(Numeric(20,6))
    quantity_unit: Mapped[str] = mapped_column(String(32))
    quantity_provenance: Mapped[str] = mapped_column(String(64), index=True)
    price_source_item_id: Mapped[str] = mapped_column(String(64), index=True)
    mapping_explanation: Mapped[str|None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    approved_by: Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PricingEstimate(Base):
    __tablename__ = "pricing_estimates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    estimate_mode: Mapped[str] = mapped_column(String(48), index=True)
    scenario: Mapped[str] = mapped_column(String(32), default="probable", index=True)
    status: Mapped[str] = mapped_column(String(32), default="estimated", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="BRL")
    total_cents: Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    inputs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    lines_json: Mapped[list] = mapped_column(JSON, default=list)
    provenance_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VerticalCostLedger(Base):
    __tablename__ = "vertical_cost_ledger"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    event_kind: Mapped[str] = mapped_column(String(64), index=True)
    evidence_status: Mapped[str] = mapped_column(String(32), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="BRL")
    amount_cents: Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str|None] = mapped_column(String(500), nullable=True)
    billing_scope: Mapped[str] = mapped_column(String(64), default="glip", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
