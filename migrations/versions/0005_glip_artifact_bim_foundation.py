"""GLIP RC5 artifact + CAD/BIM foundation.

Revision ID: 0005_glip_artifact_bim_foundation
Revises: 0004a_alembic_version_128

Additive and reversible. Introduces GLIP-owned artifact jobs/assets/usage and
architectural source/scene/render job records. No Efata storage, billing or
provider credential is referenced.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_glip_artifact_bim_foundation"
down_revision = "0004a_alembic_version_128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_jobs",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("artifact_kind",sa.String(64),nullable=False,server_default="document"),
        sa.Column("requested_format",sa.String(32),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),
        sa.Column("source_kind",sa.String(64),nullable=False,server_default="user_content"),
        sa.Column("source_ref",sa.String(255),nullable=True),
        sa.Column("request_json",sa.JSON(),nullable=False),
        sa.Column("billing_scope",sa.String(64),nullable=False,server_default="glip"),
        sa.Column("provider_profile_ref",sa.String(160),nullable=True),
        sa.Column("requested_by",sa.String(255),nullable=False),
        sa.Column("error_code",sa.String(120),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at",sa.DateTime(timezone=True),nullable=True),
    )
    for name,col in (
        ("ix_artifact_jobs_tenant_id","tenant_id"),
        ("ix_artifact_jobs_project_id","project_id"),
        ("ix_artifact_jobs_requested_format","requested_format"),
        ("ix_artifact_jobs_status","status"),
        ("ix_artifact_jobs_billing_scope","billing_scope"),
    ):
        op.create_index(name,"artifact_jobs",[col])

    op.create_table(
        "artifact_assets",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("job_id",sa.String(64),nullable=True),
        sa.Column("artifact_kind",sa.String(64),nullable=False,server_default="document"),
        sa.Column("format",sa.String(32),nullable=False),
        sa.Column("filename",sa.String(255),nullable=False),
        sa.Column("mime_type",sa.String(160),nullable=False),
        sa.Column("storage_key",sa.String(500),nullable=False),
        sa.Column("sha256",sa.String(64),nullable=False),
        sa.Column("size_bytes",sa.Integer(),nullable=False),
        sa.Column("classification",sa.String(80),nullable=False,server_default="project_internal"),
        sa.Column("metadata_json",sa.JSON(),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("created_by",sa.String(255),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("storage_key",name="uq_artifact_assets_storage_key"),
    )
    for name,col in (
        ("ix_artifact_assets_tenant_id","tenant_id"),
        ("ix_artifact_assets_project_id","project_id"),
        ("ix_artifact_assets_job_id","job_id"),
        ("ix_artifact_assets_artifact_kind","artifact_kind"),
        ("ix_artifact_assets_format","format"),
        ("ix_artifact_assets_sha256","sha256"),
    ):
        op.create_index(name,"artifact_assets",[col])

    op.create_table(
        "artifact_usage_events",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("artifact_job_id",sa.String(64),nullable=True),
        sa.Column("render_job_id",sa.String(64),nullable=True),
        sa.Column("billing_scope",sa.String(64),nullable=False,server_default="glip"),
        sa.Column("usage_type",sa.String(64),nullable=False),
        sa.Column("provider",sa.String(80),nullable=True),
        sa.Column("provider_profile_ref",sa.String(160),nullable=True),
        sa.Column("units_json",sa.JSON(),nullable=False),
        sa.Column("cost_microusd",sa.Integer(),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for name,col in (
        ("ix_artifact_usage_events_tenant_id","tenant_id"),
        ("ix_artifact_usage_events_project_id","project_id"),
        ("ix_artifact_usage_events_artifact_job_id","artifact_job_id"),
        ("ix_artifact_usage_events_render_job_id","render_job_id"),
        ("ix_artifact_usage_events_billing_scope","billing_scope"),
        ("ix_artifact_usage_events_usage_type","usage_type"),
    ):
        op.create_index(name,"artifact_usage_events",[col])

    op.create_table(
        "architectural_sources",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("source_format",sa.String(32),nullable=False),
        sa.Column("original_filename",sa.String(255),nullable=False),
        sa.Column("mime_type",sa.String(160),nullable=True),
        sa.Column("storage_key",sa.String(500),nullable=False),
        sa.Column("sha256",sa.String(64),nullable=False),
        sa.Column("size_bytes",sa.Integer(),nullable=False),
        sa.Column("classification",sa.String(80),nullable=False,server_default="project_internal"),
        sa.Column("ifc_schema",sa.String(64),nullable=True),
        sa.Column("status",sa.String(32),nullable=False,server_default="uploaded"),
        sa.Column("version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("created_by",sa.String(255),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id","project_id","sha256",name="uq_arch_source_project_sha"),
        sa.UniqueConstraint("storage_key",name="uq_arch_source_storage_key"),
    )
    for name,col in (
        ("ix_architectural_sources_tenant_id","tenant_id"),
        ("ix_architectural_sources_project_id","project_id"),
        ("ix_architectural_sources_source_format","source_format"),
        ("ix_architectural_sources_sha256","sha256"),
        ("ix_architectural_sources_status","status"),
    ):
        op.create_index(name,"architectural_sources",[col])

    op.create_table(
        "architectural_scenes",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("source_id",sa.String(64),nullable=False),
        sa.Column("scene_schema_version",sa.String(64),nullable=False,server_default="glip.arch.scene.v1"),
        sa.Column("units",sa.String(16),nullable=False,server_default="mm"),
        sa.Column("source_format",sa.String(32),nullable=False),
        sa.Column("source_sha256",sa.String(64),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="draft"),
        sa.Column("scene_json",sa.JSON(),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("created_by",sa.String(255),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id","project_id","source_id","version",name="uq_arch_scene_source_version"),
    )
    for name,col in (
        ("ix_architectural_scenes_tenant_id","tenant_id"),
        ("ix_architectural_scenes_project_id","project_id"),
        ("ix_architectural_scenes_source_id","source_id"),
        ("ix_architectural_scenes_status","status"),
    ):
        op.create_index(name,"architectural_scenes",[col])

    op.create_table(
        "render_jobs",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("scene_id",sa.String(64),nullable=False),
        sa.Column("render_type",sa.String(32),nullable=False,server_default="technical"),
        sa.Column("engine",sa.String(64),nullable=False,server_default="blender"),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),
        sa.Column("request_json",sa.JSON(),nullable=False),
        sa.Column("output_artifact_id",sa.String(64),nullable=True),
        sa.Column("billing_scope",sa.String(64),nullable=False,server_default="glip"),
        sa.Column("provider_profile_ref",sa.String(160),nullable=True),
        sa.Column("error_code",sa.String(120),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at",sa.DateTime(timezone=True),nullable=True),
    )
    for name,col in (
        ("ix_render_jobs_tenant_id","tenant_id"),
        ("ix_render_jobs_project_id","project_id"),
        ("ix_render_jobs_scene_id","scene_id"),
        ("ix_render_jobs_status","status"),
        ("ix_render_jobs_output_artifact_id","output_artifact_id"),
        ("ix_render_jobs_billing_scope","billing_scope"),
    ):
        op.create_index(name,"render_jobs",[col])


def downgrade() -> None:
    op.drop_table("render_jobs")
    op.drop_table("architectural_scenes")
    op.drop_table("architectural_sources")
    op.drop_table("artifact_usage_events")
    op.drop_table("artifact_assets")
    op.drop_table("artifact_jobs")
