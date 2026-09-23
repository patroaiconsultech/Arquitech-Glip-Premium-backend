"""GLIP standalone v0.8 explicit baseline.

Revision ID: 0001_glip_baseline_v08
Revises: none

This repository has not yet been promoted to an official database. The historical
development migration shortcuts are replaced by this explicit baseline before the first controlled deployment.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_glip_baseline_v08"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('approval_decisions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('approval_request_id', sa.String(length=64), nullable=False),
    sa.Column('draft_id', sa.String(length=64), nullable=False),
    sa.Column('draft_version_id', sa.String(length=64), nullable=False),
    sa.Column('decision', sa.String(length=32), nullable=False),
    sa.Column('approved_content_sha256', sa.String(length=64), nullable=True),
    sa.Column('actor_id', sa.String(length=255), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approval_decisions_approval_request_id'), 'approval_decisions', ['approval_request_id'], unique=False)
    op.create_index(op.f('ix_approval_decisions_draft_id'), 'approval_decisions', ['draft_id'], unique=False)
    op.create_index(op.f('ix_approval_decisions_draft_version_id'), 'approval_decisions', ['draft_version_id'], unique=False)
    op.create_index(op.f('ix_approval_decisions_project_id'), 'approval_decisions', ['project_id'], unique=False)
    op.create_index(op.f('ix_approval_decisions_tenant_id'), 'approval_decisions', ['tenant_id'], unique=False)
    op.create_table('approval_requests',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('draft_id', sa.String(length=64), nullable=False),
    sa.Column('draft_version_id', sa.String(length=64), nullable=False),
    sa.Column('requested_content_sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('requested_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approval_requests_draft_id'), 'approval_requests', ['draft_id'], unique=False)
    op.create_index(op.f('ix_approval_requests_draft_version_id'), 'approval_requests', ['draft_version_id'], unique=False)
    op.create_index(op.f('ix_approval_requests_project_id'), 'approval_requests', ['project_id'], unique=False)
    op.create_index(op.f('ix_approval_requests_tenant_id'), 'approval_requests', ['tenant_id'], unique=False)
    op.create_table('approved_versions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('draft_id', sa.String(length=64), nullable=False),
    sa.Column('draft_version_id', sa.String(length=64), nullable=False),
    sa.Column('approval_decision_id', sa.String(length=64), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('capability_id', sa.String(length=160), nullable=False),
    sa.Column('capability_version', sa.String(length=32), nullable=False),
    sa.Column('voice_profile_id', sa.String(length=160), nullable=True),
    sa.Column('approved_by', sa.String(length=255), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'draft_version_id', name='uq_approved_draft_version')
    )
    op.create_index(op.f('ix_approved_versions_approval_decision_id'), 'approved_versions', ['approval_decision_id'], unique=False)
    op.create_index(op.f('ix_approved_versions_content_sha256'), 'approved_versions', ['content_sha256'], unique=False)
    op.create_index(op.f('ix_approved_versions_draft_id'), 'approved_versions', ['draft_id'], unique=False)
    op.create_index(op.f('ix_approved_versions_draft_version_id'), 'approved_versions', ['draft_version_id'], unique=False)
    op.create_index(op.f('ix_approved_versions_project_id'), 'approved_versions', ['project_id'], unique=False)
    op.create_index(op.f('ix_approved_versions_tenant_id'), 'approved_versions', ['tenant_id'], unique=False)
    op.create_table('budget_snapshots',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_budget_snapshots_project_id'), 'budget_snapshots', ['project_id'], unique=False)
    op.create_index(op.f('ix_budget_snapshots_tenant_id'), 'budget_snapshots', ['tenant_id'], unique=False)
    op.create_table('clients',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clients_tenant_id'), 'clients', ['tenant_id'], unique=False)
    op.create_table('cognitive_executions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('capability_id', sa.String(length=160), nullable=False),
    sa.Column('capability_version', sa.String(length=32), nullable=False),
    sa.Column('project_context_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cognitive_executions_correlation_id'), 'cognitive_executions', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_cognitive_executions_project_id'), 'cognitive_executions', ['project_id'], unique=False)
    op.create_index(op.f('ix_cognitive_executions_request_id'), 'cognitive_executions', ['request_id'], unique=False)
    op.create_index(op.f('ix_cognitive_executions_tenant_id'), 'cognitive_executions', ['tenant_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('storage_ref', sa.String(length=500), nullable=False),
    sa.Column('classification', sa.String(length=80), nullable=False),
    sa.Column('allowed_purposes', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_project_id'), 'documents', ['project_id'], unique=False)
    op.create_index(op.f('ix_documents_tenant_id'), 'documents', ['tenant_id'], unique=False)
    op.create_table('draft_versions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('draft_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_by_type', sa.String(length=32), nullable=False),
    sa.Column('created_by_id', sa.String(length=255), nullable=False),
    sa.Column('capability_id', sa.String(length=160), nullable=False),
    sa.Column('capability_version', sa.String(length=32), nullable=False),
    sa.Column('voice_profile_id', sa.String(length=160), nullable=True),
    sa.Column('project_context_version', sa.Integer(), nullable=False),
    sa.Column('risk_scan', sa.JSON(), nullable=False),
    sa.Column('source_refs', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('draft_id', 'version', name='uq_draft_version')
    )
    op.create_index(op.f('ix_draft_versions_content_sha256'), 'draft_versions', ['content_sha256'], unique=False)
    op.create_index(op.f('ix_draft_versions_draft_id'), 'draft_versions', ['draft_id'], unique=False)
    op.create_index(op.f('ix_draft_versions_project_id'), 'draft_versions', ['project_id'], unique=False)
    op.create_index(op.f('ix_draft_versions_tenant_id'), 'draft_versions', ['tenant_id'], unique=False)
    op.create_table('drafts',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drafts_project_id'), 'drafts', ['project_id'], unique=False)
    op.create_index(op.f('ix_drafts_tenant_id'), 'drafts', ['tenant_id'], unique=False)
    op.create_table('external_deliveries',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('approved_version_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('provider_message_id', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_external_deliveries_approved_version_id'), 'external_deliveries', ['approved_version_id'], unique=False)
    op.create_index(op.f('ix_external_deliveries_idempotency_key'), 'external_deliveries', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_external_deliveries_project_id'), 'external_deliveries', ['project_id'], unique=False)
    op.create_index(op.f('ix_external_deliveries_tenant_id'), 'external_deliveries', ['tenant_id'], unique=False)
    op.create_table('memberships',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('external_subject', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=True),
    sa.Column('role', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'external_subject', name='uq_membership_subject')
    )
    op.create_index(op.f('ix_memberships_external_subject'), 'memberships', ['external_subject'], unique=False)
    op.create_index(op.f('ix_memberships_tenant_id'), 'memberships', ['tenant_id'], unique=False)
    op.create_table('memory_candidates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('source_approved_version_id', sa.String(length=64), nullable=False),
    sa.Column('candidate_type', sa.String(length=120), nullable=False),
    sa.Column('source_content_sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_by', sa.String(length=255), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memory_candidates_project_id'), 'memory_candidates', ['project_id'], unique=False)
    op.create_index(op.f('ix_memory_candidates_source_approved_version_id'), 'memory_candidates', ['source_approved_version_id'], unique=False)
    op.create_index(op.f('ix_memory_candidates_tenant_id'), 'memory_candidates', ['tenant_id'], unique=False)
    op.create_table('milestones',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_milestones_project_id'), 'milestones', ['project_id'], unique=False)
    op.create_index(op.f('ix_milestones_tenant_id'), 'milestones', ['tenant_id'], unique=False)
    op.create_table('outbox_events',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=True),
    sa.Column('event_type', sa.String(length=160), nullable=False),
    sa.Column('event_version', sa.Integer(), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('causation_id', sa.String(length=64), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_events_correlation_id'), 'outbox_events', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_outbox_events_project_id'), 'outbox_events', ['project_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_tenant_id'), 'outbox_events', ['tenant_id'], unique=False)
    op.create_table('project_assets',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('asset_type', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('storage_ref', sa.String(length=500), nullable=False),
    sa.Column('mime_type', sa.String(length=160), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('classification', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_assets_project_id'), 'project_assets', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_assets_tenant_id'), 'project_assets', ['tenant_id'], unique=False)
    op.create_table('project_audit_events',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=True),
    sa.Column('actor_id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=160), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_audit_events_correlation_id'), 'project_audit_events', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_project_audit_events_event_type'), 'project_audit_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_project_audit_events_project_id'), 'project_audit_events', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_audit_events_tenant_id'), 'project_audit_events', ['tenant_id'], unique=False)
    op.create_table('project_cognitive_profiles',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('baseline_id', sa.String(length=160), nullable=False),
    sa.Column('baseline_version', sa.String(length=32), nullable=False),
    sa.Column('policy_profile_id', sa.String(length=160), nullable=False),
    sa.Column('voice_profile_id', sa.String(length=160), nullable=False),
    sa.Column('memory_namespace', sa.String(length=255), nullable=False),
    sa.Column('enabled_capabilities', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'project_id', name='uq_project_cognitive_profile')
    )
    op.create_index(op.f('ix_project_cognitive_profiles_memory_namespace'), 'project_cognitive_profiles', ['memory_namespace'], unique=True)
    op.create_index(op.f('ix_project_cognitive_profiles_project_id'), 'project_cognitive_profiles', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_cognitive_profiles_tenant_id'), 'project_cognitive_profiles', ['tenant_id'], unique=False)
    op.create_table('project_communications',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('direction', sa.String(length=32), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('contact_ref', sa.String(length=255), nullable=True),
    sa.Column('subject', sa.String(length=255), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('approved_version_id', sa.String(length=64), nullable=True),
    sa.Column('external_message_id', sa.String(length=255), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_communications_project_id'), 'project_communications', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_communications_tenant_id'), 'project_communications', ['tenant_id'], unique=False)
    op.create_table('project_decisions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('decision', sa.Text(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.String(length=255), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_decisions_project_id'), 'project_decisions', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_decisions_tenant_id'), 'project_decisions', ['tenant_id'], unique=False)
    op.create_table('project_knowledge_items',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('knowledge_key', sa.String(length=180), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('source_ref', sa.String(length=500), nullable=False),
    sa.Column('classification', sa.String(length=80), nullable=False),
    sa.Column('allowed_purposes', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('approved_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_knowledge_items_project_id'), 'project_knowledge_items', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_knowledge_items_tenant_id'), 'project_knowledge_items', ['tenant_id'], unique=False)
    op.create_table('project_memory_facts',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('fact_key', sa.String(length=180), nullable=False),
    sa.Column('fact_value', sa.Text(), nullable=False),
    sa.Column('classification', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('source_approved_version_id', sa.String(length=64), nullable=False),
    sa.Column('approved_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'project_id', 'fact_key', 'version', name='uq_project_memory_fact_version')
    )
    op.create_index(op.f('ix_project_memory_facts_project_id'), 'project_memory_facts', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_memory_facts_source_approved_version_id'), 'project_memory_facts', ['source_approved_version_id'], unique=False)
    op.create_index(op.f('ix_project_memory_facts_tenant_id'), 'project_memory_facts', ['tenant_id'], unique=False)
    op.create_table('project_providers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=160), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'project_id', 'provider_id', name='uq_project_provider')
    )
    op.create_index(op.f('ix_project_providers_project_id'), 'project_providers', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_providers_provider_id'), 'project_providers', ['provider_id'], unique=False)
    op.create_index(op.f('ix_project_providers_tenant_id'), 'project_providers', ['tenant_id'], unique=False)
    op.create_table('project_stages',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_stages_project_id'), 'project_stages', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_stages_tenant_id'), 'project_stages', ['tenant_id'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('code', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('current_stage', sa.String(length=120), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('address_summary', sa.Text(), nullable=True),
    sa.Column('context_version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_project_code')
    )
    op.create_index(op.f('ix_projects_client_id'), 'projects', ['client_id'], unique=False)
    op.create_index(op.f('ix_projects_tenant_id'), 'projects', ['tenant_id'], unique=False)
    op.create_table('providers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('specialty', sa.String(length=160), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_providers_tenant_id'), 'providers', ['tenant_id'], unique=False)
    op.create_table('schedule_items',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_ref', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_schedule_items_project_id'), 'schedule_items', ['project_id'], unique=False)
    op.create_index(op.f('ix_schedule_items_tenant_id'), 'schedule_items', ['tenant_id'], unique=False)
    op.create_table('tasks',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_project_id'), 'tasks', ['project_id'], unique=False)
    op.create_index(op.f('ix_tasks_tenant_id'), 'tasks', ['tenant_id'], unique=False)
    op.create_table('tenants',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('tenants')
    op.drop_index(op.f('ix_tasks_tenant_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_project_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_schedule_items_tenant_id'), table_name='schedule_items')
    op.drop_index(op.f('ix_schedule_items_project_id'), table_name='schedule_items')
    op.drop_table('schedule_items')
    op.drop_index(op.f('ix_providers_tenant_id'), table_name='providers')
    op.drop_table('providers')
    op.drop_index(op.f('ix_projects_tenant_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_client_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_project_stages_tenant_id'), table_name='project_stages')
    op.drop_index(op.f('ix_project_stages_project_id'), table_name='project_stages')
    op.drop_table('project_stages')
    op.drop_index(op.f('ix_project_providers_tenant_id'), table_name='project_providers')
    op.drop_index(op.f('ix_project_providers_provider_id'), table_name='project_providers')
    op.drop_index(op.f('ix_project_providers_project_id'), table_name='project_providers')
    op.drop_table('project_providers')
    op.drop_index(op.f('ix_project_memory_facts_tenant_id'), table_name='project_memory_facts')
    op.drop_index(op.f('ix_project_memory_facts_source_approved_version_id'), table_name='project_memory_facts')
    op.drop_index(op.f('ix_project_memory_facts_project_id'), table_name='project_memory_facts')
    op.drop_table('project_memory_facts')
    op.drop_index(op.f('ix_project_knowledge_items_tenant_id'), table_name='project_knowledge_items')
    op.drop_index(op.f('ix_project_knowledge_items_project_id'), table_name='project_knowledge_items')
    op.drop_table('project_knowledge_items')
    op.drop_index(op.f('ix_project_decisions_tenant_id'), table_name='project_decisions')
    op.drop_index(op.f('ix_project_decisions_project_id'), table_name='project_decisions')
    op.drop_table('project_decisions')
    op.drop_index(op.f('ix_project_communications_tenant_id'), table_name='project_communications')
    op.drop_index(op.f('ix_project_communications_project_id'), table_name='project_communications')
    op.drop_table('project_communications')
    op.drop_index(op.f('ix_project_cognitive_profiles_tenant_id'), table_name='project_cognitive_profiles')
    op.drop_index(op.f('ix_project_cognitive_profiles_project_id'), table_name='project_cognitive_profiles')
    op.drop_index(op.f('ix_project_cognitive_profiles_memory_namespace'), table_name='project_cognitive_profiles')
    op.drop_table('project_cognitive_profiles')
    op.drop_index(op.f('ix_project_audit_events_tenant_id'), table_name='project_audit_events')
    op.drop_index(op.f('ix_project_audit_events_project_id'), table_name='project_audit_events')
    op.drop_index(op.f('ix_project_audit_events_event_type'), table_name='project_audit_events')
    op.drop_index(op.f('ix_project_audit_events_correlation_id'), table_name='project_audit_events')
    op.drop_table('project_audit_events')
    op.drop_index(op.f('ix_project_assets_tenant_id'), table_name='project_assets')
    op.drop_index(op.f('ix_project_assets_project_id'), table_name='project_assets')
    op.drop_table('project_assets')
    op.drop_index(op.f('ix_outbox_events_tenant_id'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_project_id'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_event_type'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_correlation_id'), table_name='outbox_events')
    op.drop_table('outbox_events')
    op.drop_index(op.f('ix_milestones_tenant_id'), table_name='milestones')
    op.drop_index(op.f('ix_milestones_project_id'), table_name='milestones')
    op.drop_table('milestones')
    op.drop_index(op.f('ix_memory_candidates_tenant_id'), table_name='memory_candidates')
    op.drop_index(op.f('ix_memory_candidates_source_approved_version_id'), table_name='memory_candidates')
    op.drop_index(op.f('ix_memory_candidates_project_id'), table_name='memory_candidates')
    op.drop_table('memory_candidates')
    op.drop_index(op.f('ix_memberships_tenant_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_external_subject'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_external_deliveries_tenant_id'), table_name='external_deliveries')
    op.drop_index(op.f('ix_external_deliveries_project_id'), table_name='external_deliveries')
    op.drop_index(op.f('ix_external_deliveries_idempotency_key'), table_name='external_deliveries')
    op.drop_index(op.f('ix_external_deliveries_approved_version_id'), table_name='external_deliveries')
    op.drop_table('external_deliveries')
    op.drop_index(op.f('ix_drafts_tenant_id'), table_name='drafts')
    op.drop_index(op.f('ix_drafts_project_id'), table_name='drafts')
    op.drop_table('drafts')
    op.drop_index(op.f('ix_draft_versions_tenant_id'), table_name='draft_versions')
    op.drop_index(op.f('ix_draft_versions_project_id'), table_name='draft_versions')
    op.drop_index(op.f('ix_draft_versions_draft_id'), table_name='draft_versions')
    op.drop_index(op.f('ix_draft_versions_content_sha256'), table_name='draft_versions')
    op.drop_table('draft_versions')
    op.drop_index(op.f('ix_documents_tenant_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_project_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_cognitive_executions_tenant_id'), table_name='cognitive_executions')
    op.drop_index(op.f('ix_cognitive_executions_request_id'), table_name='cognitive_executions')
    op.drop_index(op.f('ix_cognitive_executions_project_id'), table_name='cognitive_executions')
    op.drop_index(op.f('ix_cognitive_executions_correlation_id'), table_name='cognitive_executions')
    op.drop_table('cognitive_executions')
    op.drop_index(op.f('ix_clients_tenant_id'), table_name='clients')
    op.drop_table('clients')
    op.drop_index(op.f('ix_budget_snapshots_tenant_id'), table_name='budget_snapshots')
    op.drop_index(op.f('ix_budget_snapshots_project_id'), table_name='budget_snapshots')
    op.drop_table('budget_snapshots')
    op.drop_index(op.f('ix_approved_versions_tenant_id'), table_name='approved_versions')
    op.drop_index(op.f('ix_approved_versions_project_id'), table_name='approved_versions')
    op.drop_index(op.f('ix_approved_versions_draft_version_id'), table_name='approved_versions')
    op.drop_index(op.f('ix_approved_versions_draft_id'), table_name='approved_versions')
    op.drop_index(op.f('ix_approved_versions_content_sha256'), table_name='approved_versions')
    op.drop_index(op.f('ix_approved_versions_approval_decision_id'), table_name='approved_versions')
    op.drop_table('approved_versions')
    op.drop_index(op.f('ix_approval_requests_tenant_id'), table_name='approval_requests')
    op.drop_index(op.f('ix_approval_requests_project_id'), table_name='approval_requests')
    op.drop_index(op.f('ix_approval_requests_draft_version_id'), table_name='approval_requests')
    op.drop_index(op.f('ix_approval_requests_draft_id'), table_name='approval_requests')
    op.drop_table('approval_requests')
    op.drop_index(op.f('ix_approval_decisions_tenant_id'), table_name='approval_decisions')
    op.drop_index(op.f('ix_approval_decisions_project_id'), table_name='approval_decisions')
    op.drop_index(op.f('ix_approval_decisions_draft_version_id'), table_name='approval_decisions')
    op.drop_index(op.f('ix_approval_decisions_draft_id'), table_name='approval_decisions')
    op.drop_index(op.f('ix_approval_decisions_approval_request_id'), table_name='approval_decisions')
    op.drop_table('approval_decisions')
