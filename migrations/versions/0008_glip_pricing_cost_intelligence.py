"""GLIP RC8 pricing and cost intelligence foundation.

Revision ID: 0008_glip_pricing_cost_intelligence
Revises: 0007_glip_geometry_quantity_foundation

Additive and reversible. Adds immutable price-source snapshots/items,
tenant-scoped quantity-to-price mappings, deterministic estimate persistence,
and a GLIP-only vertical cost ledger.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_glip_pricing_cost_intelligence"
down_revision = "0007_glip_geometry_quantity_foundation"
branch_labels = None
depends_on = None


def _indexes(table: str, pairs: tuple[tuple[str, str], ...]) -> None:
    for name, col in pairs:
        op.create_index(name, table, [col])


def upgrade() -> None:
    op.create_table(
        "price_source_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("geography_json", sa.JSON(), nullable=False),
        sa.Column("competency", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(1000), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_status", sa.String(40), nullable=False, server_default="human_review_required"),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=False),
        sa.Column("billing_scope", sa.String(64), nullable=False, server_default="glip"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "source_key", "evidence_sha256", name="uq_price_snapshot_evidence"),
    )
    _indexes("price_source_snapshots", (
        ("ix_price_source_snapshots_tenant_id", "tenant_id"),
        ("ix_price_source_snapshots_source_key", "source_key"),
        ("ix_price_source_snapshots_provider", "provider"),
        ("ix_price_source_snapshots_competency", "competency"),
        ("ix_price_source_snapshots_evidence_sha256", "evidence_sha256"),
        ("ix_price_source_snapshots_validity_status", "validity_status"),
        ("ix_price_source_snapshots_billing_scope", "billing_scope"),
    ))

    op.create_table(
        "price_source_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("source_code", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="BRL"),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("manually_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("snapshot_id", "source_code", "unit", "role", name="uq_price_item_snapshot_code_unit_role"),
    )
    _indexes("price_source_items", (
        ("ix_price_source_items_tenant_id", "tenant_id"),
        ("ix_price_source_items_snapshot_id", "snapshot_id"),
        ("ix_price_source_items_source_code", "source_code"),
        ("ix_price_source_items_unit", "unit"),
        ("ix_price_source_items_role", "role"),
    ))

    op.create_table(
        "quantity_price_mappings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("canonical_item_id", sa.String(160), nullable=False),
        sa.Column("quantity_source_ref", sa.String(500), nullable=False),
        sa.Column("quantity_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("quantity_unit", sa.String(32), nullable=False),
        sa.Column("quantity_provenance", sa.String(64), nullable=False),
        sa.Column("price_source_item_id", sa.String(64), nullable=False),
        sa.Column("mapping_explanation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("approved_by", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _indexes("quantity_price_mappings", (
        ("ix_quantity_price_mappings_tenant_id", "tenant_id"),
        ("ix_quantity_price_mappings_project_id", "project_id"),
        ("ix_quantity_price_mappings_canonical_item_id", "canonical_item_id"),
        ("ix_quantity_price_mappings_quantity_provenance", "quantity_provenance"),
        ("ix_quantity_price_mappings_price_source_item_id", "price_source_item_id"),
        ("ix_quantity_price_mappings_status", "status"),
    ))

    op.create_table(
        "pricing_estimates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("estimate_mode", sa.String(48), nullable=False),
        sa.Column("scenario", sa.String(32), nullable=False, server_default="probable"),
        sa.Column("status", sa.String(32), nullable=False, server_default="estimated"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="BRL"),
        sa.Column("total_cents", sa.BigInteger(), nullable=True),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("lines_json", sa.JSON(), nullable=False),
        sa.Column("provenance_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _indexes("pricing_estimates", (
        ("ix_pricing_estimates_tenant_id", "tenant_id"),
        ("ix_pricing_estimates_project_id", "project_id"),
        ("ix_pricing_estimates_estimate_mode", "estimate_mode"),
        ("ix_pricing_estimates_scenario", "scenario"),
        ("ix_pricing_estimates_status", "status"),
        ("ix_pricing_estimates_provenance_sha256", "provenance_sha256"),
    ))

    op.create_table(
        "vertical_cost_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("event_kind", sa.String(64), nullable=False),
        sa.Column("evidence_status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="BRL"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("billing_scope", sa.String(64), nullable=False, server_default="glip"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _indexes("vertical_cost_ledger", (
        ("ix_vertical_cost_ledger_tenant_id", "tenant_id"),
        ("ix_vertical_cost_ledger_project_id", "project_id"),
        ("ix_vertical_cost_ledger_event_kind", "event_kind"),
        ("ix_vertical_cost_ledger_evidence_status", "evidence_status"),
        ("ix_vertical_cost_ledger_billing_scope", "billing_scope"),
    ))


def downgrade() -> None:
    op.drop_table("vertical_cost_ledger")
    op.drop_table("pricing_estimates")
    op.drop_table("quantity_price_mappings")
    op.drop_table("price_source_items")
    op.drop_table("price_source_snapshots")
