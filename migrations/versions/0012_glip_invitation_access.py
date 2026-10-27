"""GLIP ID-01 invitation and tenant admin audit.

Revision ID: 0012_glip_invitation_access
Revises: 0011_glip_chat_mvp
"""
from alembic import op
import os
import sqlalchemy as sa


revision = "0012_glip_invitation_access"
down_revision = "0011_glip_chat_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_invitations",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),sa.ForeignKey("tenants.id"),nullable=False),
        sa.Column("email_normalized",sa.String(320),nullable=False),
        sa.Column("display_name",sa.String(200),nullable=True),
        sa.Column("role",sa.String(64),nullable=False),
        sa.Column("token_digest",sa.String(64),nullable=False),
        sa.Column("token_version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("status",sa.String(32),nullable=False,server_default="pending"),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("invited_by",sa.String(255),nullable=False),
        sa.Column("accepted_membership_id",sa.String(64),sa.ForeignKey("memberships.id"),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("accepted_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("revoked_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("tenant_id","email_normalized",name="uq_user_invitation_tenant_email"),
        sa.UniqueConstraint("token_digest",name="uq_user_invitation_token_digest"),
    )
    op.create_index("ix_user_invitations_tenant_id","user_invitations",["tenant_id"])
    op.create_index("ix_user_invitations_email_normalized","user_invitations",["email_normalized"])
    op.create_index("ix_user_invitations_token_digest","user_invitations",["token_digest"])
    op.create_index("ix_user_invitations_status","user_invitations",["status"])
    op.create_index("ix_user_invitations_expires_at","user_invitations",["expires_at"])

    op.create_table(
        "tenant_audit_events",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),sa.ForeignKey("tenants.id"),nullable=False),
        sa.Column("actor_id",sa.String(255),nullable=False),
        sa.Column("event_type",sa.String(100),nullable=False),
        sa.Column("target_type",sa.String(80),nullable=True),
        sa.Column("target_id",sa.String(64),nullable=True),
        sa.Column("correlation_id",sa.String(128),nullable=True),
        sa.Column("payload",sa.JSON(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_tenant_audit_events_tenant_id","tenant_audit_events",["tenant_id"])
    op.create_index("ix_tenant_audit_events_actor_id","tenant_audit_events",["actor_id"])
    op.create_index("ix_tenant_audit_events_event_type","tenant_audit_events",["event_type"])
    op.create_index("ix_tenant_audit_events_target_id","tenant_audit_events",["target_id"])
    op.create_index("ix_tenant_audit_events_correlation_id","tenant_audit_events",["correlation_id"])
    op.create_index("ix_tenant_audit_events_created_at","tenant_audit_events",["created_at"])

    op.create_table(
        "invitation_rate_limit_buckets",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("key_digest",sa.String(64),nullable=False),
        sa.Column("window_started_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("count",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("key_digest","window_started_at",name="uq_invitation_rate_limit_bucket"),
    )
    op.create_index("ix_invitation_rate_limit_key","invitation_rate_limit_buckets",["key_digest"])
    op.create_index("ix_invitation_rate_limit_window","invitation_rate_limit_buckets",["window_started_at"])


def _allow_destructive_downgrade() -> bool:
    return os.getenv("GLIP_ALLOW_DESTRUCTIVE_ID01_DOWNGRADE","").strip().lower() in {"1","true","yes"}


def _row_count(bind, table_name: str) -> int:
    return int(bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0)


def downgrade() -> None:
    bind=op.get_bind()
    protected_tables=("user_invitations","tenant_audit_events","invitation_rate_limit_buckets")
    populated=[name for name in protected_tables if _row_count(bind,name)>0]
    if populated and not _allow_destructive_downgrade():
        raise RuntimeError(
            "id01_downgrade_blocked_nonempty_security_tables:"
            + ",".join(populated)
        )

    op.drop_table("invitation_rate_limit_buckets")
    op.drop_table("tenant_audit_events")
    op.drop_table("user_invitations")
