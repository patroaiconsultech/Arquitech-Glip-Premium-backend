"""GLIP RC7 geometry, CAD semantic and quantity foundation.

Revision ID: 0007_glip_geometry_quantity_foundation
Revises: 0006_glip_bim_semantic_ingestion

Additive and reversible. Adds CAD extraction and deterministic geometry build
job state. Quantity takeoff remains embedded in versioned ArchitecturalScene
JSON so the IFC/CAD source provenance travels with the measurements.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_glip_geometry_quantity_foundation"
down_revision = "0006_glip_bim_semantic_ingestion"
branch_labels = None
depends_on = None


def _indexes(table: str, pairs: tuple[tuple[str,str], ...]) -> None:
    for name,col in pairs:
        op.create_index(name,table,[col])


def upgrade() -> None:
    op.create_table(
        "cad_extraction_jobs",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("source_id",sa.String(64),nullable=False),
        sa.Column("source_sha256",sa.String(64),nullable=False),
        sa.Column("engine",sa.String(64),nullable=False,server_default="ezdxf"),
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
    _indexes("cad_extraction_jobs",(
        ("ix_cad_extraction_jobs_tenant_id","tenant_id"),
        ("ix_cad_extraction_jobs_project_id","project_id"),
        ("ix_cad_extraction_jobs_source_id","source_id"),
        ("ix_cad_extraction_jobs_source_sha256","source_sha256"),
        ("ix_cad_extraction_jobs_status","status"),
        ("ix_cad_extraction_jobs_scene_id","scene_id"),
    ))

    op.create_table(
        "geometry_build_jobs",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("scene_id",sa.String(64),nullable=False),
        sa.Column("source_id",sa.String(64),nullable=False),
        sa.Column("source_sha256",sa.String(64),nullable=False),
        sa.Column("build_kind",sa.String(48),nullable=False,server_default="preview_glb"),
        sa.Column("engine",sa.String(64),nullable=False,server_default="trimesh"),
        sa.Column("engine_version",sa.String(64),nullable=True),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),
        sa.Column("output_artifact_id",sa.String(64),nullable=True),
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
    _indexes("geometry_build_jobs",(
        ("ix_geometry_build_jobs_tenant_id","tenant_id"),
        ("ix_geometry_build_jobs_project_id","project_id"),
        ("ix_geometry_build_jobs_scene_id","scene_id"),
        ("ix_geometry_build_jobs_source_id","source_id"),
        ("ix_geometry_build_jobs_source_sha256","source_sha256"),
        ("ix_geometry_build_jobs_status","status"),
        ("ix_geometry_build_jobs_output_artifact_id","output_artifact_id"),
    ))


def downgrade() -> None:
    op.drop_table("geometry_build_jobs")
    op.drop_table("cad_extraction_jobs")
