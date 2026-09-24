"""Expand Alembic version_num capacity before long revision ids."""

from alembic import op
import sqlalchemy as sa


revision = "0004a_alembic_version_128"
down_revision = "0004_glip_native_auth_rc4"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_context().dialect.name

    if dialect == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def downgrade():
    dialect = op.get_context().dialect.name

    if dialect == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
