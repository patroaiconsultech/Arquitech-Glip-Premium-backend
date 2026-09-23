"""GLIP RC4 native authentication.

Revision ID: 0004_glip_native_auth_rc4
Revises: 0003_glip_integration_lease_rc2

Additive GLIP-owned native credentials, server-side sessions and sanitized auth events.
No OIDC account linking or public self-registration is introduced.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_glip_native_auth_rc4"
down_revision = "0003_glip_integration_lease_rc2"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "native_credentials",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),sa.ForeignKey("tenants.id"),nullable=False),
        sa.Column("membership_id",sa.String(64),sa.ForeignKey("memberships.id"),nullable=False),
        sa.Column("email_normalized",sa.String(320),nullable=False),
        sa.Column("password_salt_b64",sa.String(128),nullable=False),
        sa.Column("password_hash_b64",sa.String(256),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("failed_attempts",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("locked_until",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("password_changed_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_login_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("tenant_id","email_normalized",name="uq_native_credential_tenant_email"),
        sa.UniqueConstraint("membership_id",name="uq_native_credential_membership"),
    )
    op.create_index("ix_native_credentials_tenant_id","native_credentials",["tenant_id"])
    op.create_index("ix_native_credentials_membership_id","native_credentials",["membership_id"])
    op.create_index("ix_native_credentials_email_normalized","native_credentials",["email_normalized"])
    op.create_index("ix_native_credentials_locked_until","native_credentials",["locked_until"])

    op.create_table(
        "native_auth_sessions",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),sa.ForeignKey("tenants.id"),nullable=False),
        sa.Column("credential_id",sa.String(64),sa.ForeignKey("native_credentials.id"),nullable=False),
        sa.Column("membership_id",sa.String(64),sa.ForeignKey("memberships.id"),nullable=False),
        sa.Column("token_digest",sa.String(64),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("idle_expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("revoked_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("token_digest",name="uq_native_auth_session_digest"),
    )
    for name,column in (
        ("ix_native_auth_sessions_tenant_id","tenant_id"),
        ("ix_native_auth_sessions_credential_id","credential_id"),
        ("ix_native_auth_sessions_membership_id","membership_id"),
        ("ix_native_auth_sessions_token_digest","token_digest"),
        ("ix_native_auth_sessions_expires_at","expires_at"),
        ("ix_native_auth_sessions_idle_expires_at","idle_expires_at"),
    ):
        op.create_index(name,"native_auth_sessions",[column])

    op.create_table(
        "native_auth_events",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=True),
        sa.Column("identity_fingerprint",sa.String(64),nullable=False),
        sa.Column("event_code",sa.String(80),nullable=False),
        sa.Column("success",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_native_auth_events_tenant_id","native_auth_events",["tenant_id"])
    op.create_index("ix_native_auth_events_identity_fingerprint","native_auth_events",["identity_fingerprint"])
    op.create_index("ix_native_auth_events_event_code","native_auth_events",["event_code"])

def downgrade() -> None:
    op.drop_table("native_auth_events")
    op.drop_table("native_auth_sessions")
    op.drop_table("native_credentials")
