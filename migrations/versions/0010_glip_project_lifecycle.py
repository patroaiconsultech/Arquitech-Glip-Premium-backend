"""GLIP F01 project lifecycle, mutation authorization support and create idempotency.

Revision ID: 0010_glip_project_lifecycle
Revises: 0009_glip_pricing_authority_hardening

Additive and reversible:
- archive metadata on projects;
- durable per-tenant/per-actor idempotency records for project creation.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_glip_project_lifecycle"
down_revision = "0009_glip_pricing_authority_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("archived_by", sa.String(255), nullable=True))
        batch.create_index("ix_projects_archived_at", ["archived_at"], unique=False)

    op.create_table(
        "project_create_idempotency",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "idempotency_key",
            name="uq_project_create_idempotency",
        ),
    )
    op.create_index(
        "ix_project_create_idempotency_tenant_id",
        "project_create_idempotency",
        ["tenant_id"],
    )
    op.create_index(
        "ix_project_create_idempotency_actor_id",
        "project_create_idempotency",
        ["actor_id"],
    )
    op.create_index(
        "ix_project_create_idempotency_project_id",
        "project_create_idempotency",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_table("project_create_idempotency")
    with op.batch_alter_table("projects") as batch:
        batch.drop_index("ix_projects_archived_at")
        batch.drop_column("archived_by")
        batch.drop_column("archived_at")
