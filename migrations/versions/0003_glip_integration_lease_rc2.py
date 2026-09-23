"""GLIP v1.0 RC2 integration ownership/lease hardening.

Revision ID: 0003_glip_integration_lease_rc2
Revises: 0002_glip_orkio_contract_v10

Additive. It preserves the v1.0 RC1 ledger and only adds processing metadata.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_glip_integration_lease_rc2"
down_revision = "0002_glip_orkio_contract_v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integration_executions", sa.Column("owner_token", sa.String(64), nullable=True))
    op.add_column("integration_executions", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "integration_executions",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_integration_executions_owner_token",
        "integration_executions",
        ["owner_token"],
    )
    op.create_index(
        "ix_integration_executions_lease_expires_at",
        "integration_executions",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_executions_lease_expires_at", table_name="integration_executions")
    op.drop_index("ix_integration_executions_owner_token", table_name="integration_executions")
    op.drop_column("integration_executions", "attempt_count")
    op.drop_column("integration_executions", "lease_expires_at")
    op.drop_column("integration_executions", "owner_token")
