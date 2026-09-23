"""GLIP v1.0 ORKIO integration execution ledger.

Revision ID: 0002_glip_orkio_contract_v10
Revises: 0001_glip_baseline_v08

Additive and reversible. No existing domain table is modified.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_glip_orkio_contract_v10"
down_revision = "0001_glip_baseline_v08"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "integration_executions",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("tenant_id",sa.String(64),nullable=False),
        sa.Column("project_id",sa.String(64),nullable=False),
        sa.Column("destination_service",sa.String(80),nullable=False),
        sa.Column("capability_id",sa.String(160),nullable=False),
        sa.Column("capability_version",sa.String(32),nullable=False),
        sa.Column("request_id",sa.String(128),nullable=False),
        sa.Column("execution_id",sa.String(128),nullable=False),
        sa.Column("correlation_id",sa.String(128),nullable=False),
        sa.Column("idempotency_key",sa.String(200),nullable=False),
        sa.Column("request_sha256",sa.String(64),nullable=False),
        sa.Column("request_json",sa.JSON(),nullable=False),
        sa.Column("upstream_response_json",sa.JSON(),nullable=True),
        sa.Column("domain_response_json",sa.JSON(),nullable=True),
        sa.Column("draft_id",sa.String(64),nullable=False),
        sa.Column("cognitive_execution_id",sa.String(64),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="contextualized"),
        sa.Column("latency_ms",sa.Integer(),nullable=True),
        sa.Column("retry_count",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("error_code",sa.String(120),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("tenant_id","destination_service","idempotency_key",name="uq_integration_idempotency"),
        sa.UniqueConstraint("tenant_id","execution_id",name="uq_integration_execution_id"),
    )
    for name,cols in (
        ("ix_integration_executions_tenant_id",["tenant_id"]),
        ("ix_integration_executions_project_id",["project_id"]),
        ("ix_integration_executions_capability_id",["capability_id"]),
        ("ix_integration_executions_request_id",["request_id"]),
        ("ix_integration_executions_execution_id",["execution_id"]),
        ("ix_integration_executions_correlation_id",["correlation_id"]),
        ("ix_integration_executions_idempotency_key",["idempotency_key"]),
        ("ix_integration_executions_draft_id",["draft_id"]),
        ("ix_integration_executions_cognitive_execution_id",["cognitive_execution_id"]),
    ):
        op.create_index(name,"integration_executions",cols)

def downgrade() -> None:
    op.drop_table("integration_executions")
