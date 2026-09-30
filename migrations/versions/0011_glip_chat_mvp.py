"""GLIP Intelligence chat MVP.

Revision ID: 0011_glip_chat_mvp
Revises: 0010_glip_project_lifecycle
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_glip_chat_mvp"
down_revision = "0010_glip_project_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default="Nova conversa"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chat_threads_tenant_id", "chat_threads", ["tenant_id"])
    op.create_index("ix_chat_threads_project_id", "chat_threads", ["project_id"])
    op.create_index("ix_chat_threads_status", "chat_threads", ["status"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), sa.ForeignKey("chat_threads.id"), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])
    op.create_index("ix_chat_messages_project_id", "chat_messages", ["project_id"])
    op.create_index("ix_chat_messages_role", "chat_messages", ["role"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
