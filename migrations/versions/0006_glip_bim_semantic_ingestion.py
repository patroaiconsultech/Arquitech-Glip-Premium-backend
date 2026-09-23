"""GLIP RC6 BIM semantic ingestion queue.

Revision ID: 0006_glip_bim_semantic_ingestion
Revises: 0005_glip_artifact_bim_foundation

Additive and reversible. Adds only BIM extraction job state. IFC remains the
semantic source-of-truth; scenes are persisted in the existing
architectural_scenes table.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_glip_bim_semantic_ingestion"
down_revision = "0005_glip_artifact_bim_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bim_extraction_jobs",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("source_id",sa.String(64),nullable=False),
        sa.Column("source_sha256",sa.String(64),nullable=False),
        sa.Column("engine",sa.String(64),nullable=False,server_default="ifcopenshell"),
        sa.Column("engine_version",sa.String(64),nullable=True),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),
        sa.Column("scene_id",sa.String(64),nullable=True),
        sa.Column("statistics_json",sa.JSON(),nullable=False),
        sa.Column("error_code",sa.String(120),nullable=True),
        sa.Column("requested_by",sa.String(255),nullable=False),
        sa.Column("attempt_count",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("lease_owner",sa.String(160),nullable=True),
        sa.Column("lease_expires_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("completed_at",sa.DateTime(timezone=True),nullable=True),
    )
    for name,col in (
        ("ix_bim_extraction_jobs_tenant_id","tenant_id"),
        ("ix_bim_extraction_jobs_project_id","project_id"),
        ("ix_bim_extraction_jobs_source_id","source_id"),
        ("ix_bim_extraction_jobs_source_sha256","source_sha256"),
        ("ix_bim_extraction_jobs_status","status"),
        ("ix_bim_extraction_jobs_scene_id","scene_id"),
    ):
        op.create_index(name,"bim_extraction_jobs",[col])


def downgrade() -> None:
    op.drop_table("bim_extraction_jobs")
