"""GLIP RC8 pricing authority hardening.

Revision ID: 0009_glip_pricing_authority_hardening
Revises: 0008_glip_pricing_cost_intelligence

Additive and reversible. Makes price-source trust state explicit and
server-owned without rewriting the externally audited 0008 migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_glip_pricing_authority_hardening"
down_revision = "0008_glip_pricing_cost_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_source_snapshots") as batch:
        batch.add_column(sa.Column("authority_status", sa.String(40), nullable=False, server_default="unverified"))
        batch.add_column(sa.Column("authority_method", sa.String(80), nullable=True))
        batch.add_column(sa.Column("authority_by", sa.String(255), nullable=True))
        batch.add_column(sa.Column("authority_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_price_source_snapshots_authority_status", ["authority_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("price_source_snapshots") as batch:
        batch.drop_index("ix_price_source_snapshots_authority_status")
        batch.drop_column("authority_at")
        batch.drop_column("authority_by")
        batch.drop_column("authority_method")
        batch.drop_column("authority_status")
