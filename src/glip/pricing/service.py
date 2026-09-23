from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PriceSourceSnapshot,
    PriceSourceItem,
    QuantityPriceMapping,
    PricingEstimate,
    VerticalCostLedger,
    Document,
)
from .sources import (
    REGISTRY,
    VALID_SOURCE_STATUSES,
    detailed_cost_role_allowed,
    PriceSourceError,
)
from .adapters import OFFICIAL_SOURCE_CONTRACTS

ELIGIBLE_QUANTITY_PROVENANCE = frozenset({
    "authoritative_ifc",
    "geometry_derived",
    "cad_mapped",
    "manual_approved",
})

FINANCIAL_APPROVER_ROLES = frozenset({"owner"})
SERVER_VERIFIED_SOURCE_KEYS = frozenset({
    *OFFICIAL_SOURCE_CONTRACTS.keys(),
    "cau_fee_reference",
    "glip_historical",
})
MANUAL_APPROVABLE_SOURCE_KEYS = frozenset({"supplier_quote"})
EXECUTABLE_AUTHORITY_STATES = frozenset({"server_verified", "human_approved"})



class PricingError(ValueError):
    pass


def _require_financial_approver(role: str) -> None:
    if str(role or "").strip().lower() not in FINANCIAL_APPROVER_ROLES:
        raise PricingError("FINANCIAL_APPROVER_REQUIRED")


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _positive_decimal(value: Any, code: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PricingError(code) from exc
    if not out.is_finite() or out <= 0:
        raise PricingError(code)
    return out


def create_price_snapshot(db: Session, tenant_id: str, actor: str, body: dict) -> PriceSourceSnapshot:
    """Persist caller-submitted pricing evidence without granting authority."""
    source_key = str(body.get("source_key") or "").strip().lower()
    try:
        adapter = REGISTRY.get(source_key)
        roles = adapter.validate_roles(body.get("roles") or [])
    except PriceSourceError as exc:
        raise PricingError(str(exc)) from exc

    if source_key == "glip_historical":
        raise PricingError("PRICE_SOURCE_INTERNAL_ONLY")

    requested_status = str(body.get("validity_status") or "human_review_required").strip().lower()
    if requested_status not in VALID_SOURCE_STATUSES:
        raise PricingError("PRICE_SOURCE_STATUS_INVALID")

    competency = str(body.get("competency") or "").strip()
    source_ref = str(body.get("source_ref") or "").strip()
    evidence_sha256 = str(body.get("evidence_sha256") or "").strip().lower()
    geography = body.get("geography") or {}
    if not competency:
        raise PricingError("PRICE_SOURCE_COMPETENCY_REQUIRED")
    if not source_ref:
        raise PricingError("PRICE_SOURCE_REF_REQUIRED")
    if len(evidence_sha256) != 64 or any(c not in "0123456789abcdef" for c in evidence_sha256):
        raise PricingError("PRICE_SOURCE_EVIDENCE_SHA256_INVALID")
    if not isinstance(geography, dict) or not geography:
        raise PricingError("PRICE_SOURCE_GEOGRAPHY_REQUIRED")

    metadata = dict(body.get("metadata") or {})
    metadata.update({
        "submission_trust": "caller_unverified",
        "requested_validity_status": requested_status,
        "evidence_hash_trust": "caller_claimed",
        "monetary_authority": False,
    })

    snapshot = PriceSourceSnapshot(
        tenant_id=tenant_id,
        source_key=source_key,
        provider=adapter.provider,
        publisher=str(body.get("publisher") or adapter.publisher).strip()[:200],
        roles_json=list(roles),
        geography_json=geography,
        competency=competency[:32],
        source_ref=source_ref[:1000],
        evidence_sha256=evidence_sha256,
        retrieved_at=_parse_dt(body.get("retrieved_at")) or datetime.now(timezone.utc),
        validity_status="human_review_required",
        authority_status="unverified",
        authority_method="client_submission",
        authority_by=None,
        authority_at=None,
        raw_metadata_json=metadata,
        billing_scope="glip",
        created_by=actor,
    )
    db.add(snapshot)
    db.flush()

    for raw in body.get("items") or []:
        role = str(raw.get("role") or "").strip().upper()
        if role not in roles:
            raise PricingError("PRICE_ITEM_ROLE_NOT_IN_SNAPSHOT")
        code = str(raw.get("source_code") or "").strip()
        description = str(raw.get("description") or "").strip()
        unit = str(raw.get("unit") or "").strip()
        if not code or not description or not unit:
            raise PricingError("PRICE_ITEM_CODE_DESCRIPTION_UNIT_REQUIRED")
        cents = raw.get("unit_price_cents")
        if cents is not None:
            try:
                cents = int(cents)
            except Exception as exc:
                raise PricingError("PRICE_ITEM_PRICE_INVALID") from exc
            if cents < 0:
                raise PricingError("PRICE_ITEM_PRICE_INVALID")
        db.add(PriceSourceItem(
            tenant_id=tenant_id,
            snapshot_id=snapshot.id,
            source_code=code[:160],
            description=description,
            unit=unit[:32],
            role=role,
            currency=str(raw.get("currency") or "BRL").upper()[:8],
            unit_price_cents=cents,
            evidence_json=raw.get("evidence") or {},
            manually_approved=False,
        ))

    db.flush()
    return snapshot


def approve_price_snapshot(
    db: Session,
    tenant_id: str,
    actor: str,
    actor_role: str,
    snapshot_id: str,
) -> PriceSourceSnapshot:
    _require_financial_approver(actor_role)
    snapshot = db.scalar(select(PriceSourceSnapshot).where(
        PriceSourceSnapshot.id == snapshot_id,
        PriceSourceSnapshot.tenant_id == tenant_id,
        PriceSourceSnapshot.billing_scope == "glip",
    ))
    if not snapshot:
        raise PricingError("PRICE_SOURCE_SNAPSHOT_NOT_FOUND")
    if snapshot.source_key in SERVER_VERIFIED_SOURCE_KEYS:
        raise PricingError("PRICE_SOURCE_SERVER_VERIFICATION_REQUIRED")
    if snapshot.source_key not in MANUAL_APPROVABLE_SOURCE_KEYS:
        raise PricingError("PRICE_SOURCE_MANUAL_APPROVAL_NOT_ALLOWED")

    items = db.scalars(select(PriceSourceItem).where(
        PriceSourceItem.snapshot_id == snapshot.id,
        PriceSourceItem.tenant_id == tenant_id,
    )).all()
    if not items:
        raise PricingError("PRICE_SOURCE_ITEMS_REQUIRED")

    snapshot.validity_status = "valid"
    snapshot.authority_status = "human_approved"
    snapshot.authority_method = "tenant_owner_approval"
    snapshot.authority_by = actor
    snapshot.authority_at = datetime.now(timezone.utc)
    metadata = dict(snapshot.raw_metadata_json or {})
    metadata["monetary_authority"] = True
    metadata["authority_transition"] = "explicit_human_approval"
    snapshot.raw_metadata_json = metadata
    for item in items:
        item.manually_approved = True
    db.flush()
    return snapshot

def create_quantity_mapping(
    db: Session,
    tenant_id: str,
    project_id: str,
    actor: str,
    body: dict,
) -> QuantityPriceMapping:
    item = db.scalar(select(PriceSourceItem).where(
        PriceSourceItem.id == str(body.get("price_source_item_id") or ""),
        PriceSourceItem.tenant_id == tenant_id,
    ))
    if not item:
        raise PricingError("PRICE_SOURCE_ITEM_NOT_FOUND")

    snapshot = db.scalar(select(PriceSourceSnapshot).where(
        PriceSourceSnapshot.id == item.snapshot_id,
        PriceSourceSnapshot.tenant_id == tenant_id,
    ))
    if not snapshot:
        raise PricingError("PRICE_SOURCE_SNAPSHOT_NOT_FOUND")

    provenance = str(body.get("quantity_provenance") or "").strip().lower()
    if provenance not in ELIGIBLE_QUANTITY_PROVENANCE:
        raise PricingError("QUANTITY_PROVENANCE_NOT_PRICING_ELIGIBLE")

    quantity = _positive_decimal(body.get("quantity_value"), "QUANTITY_VALUE_INVALID")
    quantity_unit = str(body.get("quantity_unit") or "").strip()
    if not quantity_unit:
        raise PricingError("QUANTITY_UNIT_REQUIRED")
    if quantity_unit != item.unit:
        raise PricingError("QUANTITY_PRICE_UNIT_MISMATCH")

    requested_status = str(body.get("status") or "proposed").strip().lower()
    if requested_status not in {"proposed", "approved"}:
        raise PricingError("QUANTITY_MAPPING_STATUS_INVALID")
    if requested_status == "approved":
        raise PricingError("QUANTITY_MAPPING_APPROVAL_REQUIRES_APPROVAL_ENDPOINT")

    mapping = QuantityPriceMapping(
        tenant_id=tenant_id,
        project_id=project_id,
        canonical_item_id=str(body.get("canonical_item_id") or "").strip()[:160],
        quantity_source_ref=str(body.get("quantity_source_ref") or "").strip()[:500],
        quantity_value=quantity,
        quantity_unit=quantity_unit[:32],
        quantity_provenance=provenance,
        price_source_item_id=item.id,
        mapping_explanation=(str(body.get("mapping_explanation")) if body.get("mapping_explanation") else None),
        status="proposed",
        approved_by=None,
        created_by=actor,
    )
    if not mapping.canonical_item_id or not mapping.quantity_source_ref:
        raise PricingError("QUANTITY_MAPPING_ID_AND_SOURCE_REQUIRED")
    db.add(mapping)
    db.flush()
    return mapping


def approve_quantity_mapping(
    db: Session,
    tenant_id: str,
    project_id: str,
    actor: str,
    actor_role: str,
    mapping_id: str,
) -> QuantityPriceMapping:
    _require_financial_approver(actor_role)
    mapping = db.scalar(select(QuantityPriceMapping).where(
        QuantityPriceMapping.id == mapping_id,
        QuantityPriceMapping.tenant_id == tenant_id,
        QuantityPriceMapping.project_id == project_id,
    ))
    if not mapping:
        raise PricingError("QUANTITY_MAPPING_NOT_FOUND")
    mapping.status = "approved"
    mapping.approved_by = actor
    db.flush()
    return mapping

def estimate_construction(
    db: Session,
    tenant_id: str,
    project_id: str,
    actor: str,
    actor_role: str,
    mapping_ids: list[str],
    *,
    scenario: str = "probable",
    factor_bps: int = 10000,
) -> PricingEstimate:
    _require_financial_approver(actor_role)
    if scenario not in {"conservative", "probable", "premium"}:
        raise PricingError("PRICING_SCENARIO_INVALID")
    if not isinstance(factor_bps, int) or factor_bps <= 0 or factor_bps > 50000:
        raise PricingError("PRICING_FACTOR_INVALID")
    if not mapping_ids:
        raise PricingError("PRICING_MAPPINGS_REQUIRED")

    mappings = db.scalars(select(QuantityPriceMapping).where(
        QuantityPriceMapping.tenant_id == tenant_id,
        QuantityPriceMapping.project_id == project_id,
        QuantityPriceMapping.id.in_(mapping_ids),
    )).all()
    by_id = {m.id: m for m in mappings}
    if len(by_id) != len(set(mapping_ids)):
        raise PricingError("QUANTITY_MAPPING_NOT_FOUND")

    lines = []
    base_total = Decimal(0)
    for mapping_id in mapping_ids:
        mapping = by_id[mapping_id]
        if mapping.status != "approved" or not mapping.approved_by:
            raise PricingError("QUANTITY_MAPPING_NOT_APPROVED")
        if mapping.quantity_provenance not in ELIGIBLE_QUANTITY_PROVENANCE:
            raise PricingError("QUANTITY_PROVENANCE_NOT_PRICING_ELIGIBLE")
        item = db.scalar(select(PriceSourceItem).where(
            PriceSourceItem.id == mapping.price_source_item_id,
            PriceSourceItem.tenant_id == tenant_id,
        ))
        if not item:
            raise PricingError("PRICE_SOURCE_ITEM_NOT_FOUND")
        snapshot = db.scalar(select(PriceSourceSnapshot).where(
            PriceSourceSnapshot.id == item.snapshot_id,
            PriceSourceSnapshot.tenant_id == tenant_id,
        ))
        if not snapshot:
            raise PricingError("PRICE_SOURCE_SNAPSHOT_NOT_FOUND")
        if snapshot.validity_status != "valid":
            raise PricingError("PRICE_SOURCE_NOT_VALID")
        if snapshot.authority_status not in EXECUTABLE_AUTHORITY_STATES:
            raise PricingError("PRICE_SOURCE_NOT_AUTHORIZED")
        if snapshot.source_key in SERVER_VERIFIED_SOURCE_KEYS and snapshot.authority_status != "server_verified":
            raise PricingError("PRICE_SOURCE_SERVER_VERIFICATION_REQUIRED")
        if snapshot.authority_status == "human_approved" and not item.manually_approved:
            raise PricingError("PRICE_ITEM_NOT_HUMAN_APPROVED")
        if not detailed_cost_role_allowed(item.role):
            raise PricingError("PRICE_ROLE_NOT_DETAILED_COST_AUTHORITY")
        if item.unit_price_cents is None:
            raise PricingError("PRICE_ITEM_AMOUNT_REQUIRED")
        # Zero is preserved at snapshot level when an official publication
        # carries it as evidence, but it is never monetary authority for an
        # executable construction estimate. This is especially important for
        # exceptional SINAPI publications whose price/cost fields may be zero.
        if int(item.unit_price_cents) <= 0:
            raise PricingError("PRICE_ITEM_NON_POSITIVE_NOT_COST_AUTHORITY")
        if item.unit != mapping.quantity_unit:
            raise PricingError("QUANTITY_PRICE_UNIT_MISMATCH")

        quantity = Decimal(mapping.quantity_value)
        subtotal = (quantity * Decimal(item.unit_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        base_total += subtotal
        lines.append({
            "canonical_item_id": mapping.canonical_item_id,
            "mapping_id": mapping.id,
            "quantity": str(quantity.normalize()),
            "unit": mapping.quantity_unit,
            "quantity_provenance": mapping.quantity_provenance,
            "price_source_snapshot_id": snapshot.id,
            "price_source_item_id": item.id,
            "price_source": snapshot.source_key,
            "source_code": item.source_code,
            "role": item.role,
            "unit_price_cents": int(item.unit_price_cents),
            "competency": snapshot.competency,
            "geography": snapshot.geography_json,
            "base_subtotal_cents": int(subtotal),
            "mapping_explanation": mapping.mapping_explanation,
            "approval_status": mapping.status,
        })

    total = (base_total * Decimal(factor_bps) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    provenance = {
        "schema_version": "glip.pricing-estimate.v1",
        "mode": "construction_cost",
        "scenario": scenario,
        "factor_bps": factor_bps,
        "lines": lines,
    }
    estimate = PricingEstimate(
        tenant_id=tenant_id,
        project_id=project_id,
        estimate_mode="construction_cost",
        scenario=scenario,
        status="estimated",
        currency="BRL",
        total_cents=int(total),
        inputs_json={"mapping_ids": mapping_ids, "factor_bps": factor_bps},
        lines_json=lines,
        provenance_sha256=_canonical_sha256(provenance),
        created_by=actor,
    )
    db.add(estimate)
    db.flush()
    db.add(VerticalCostLedger(
        tenant_id=tenant_id,
        project_id=project_id,
        event_kind="construction_estimate",
        evidence_status="estimated",
        currency="BRL",
        amount_cents=int(total),
        source_type="pricing_estimate",
        source_ref=estimate.id,
        billing_scope="glip",
        metadata_json={"scenario": scenario, "provenance_sha256": estimate.provenance_sha256},
        created_by=actor,
    ))
    db.flush()
    return estimate


def estimate_professional_fee(
    db: Session,
    tenant_id: str,
    project_id: str,
    actor: str,
    actor_role: str,
    body: dict,
) -> PricingEstimate:
    _require_financial_approver(actor_role)
    hours = _positive_decimal(body.get("expected_hours"), "FEE_EXPECTED_HOURS_INVALID")
    hourly = int(body.get("hourly_cost_cents") or 0)
    if hourly <= 0:
        raise PricingError("FEE_HOURLY_COST_INVALID")

    def bps(name: str) -> int:
        try:
            value = int(body.get(name) or 0)
        except Exception as exc:
            raise PricingError("FEE_BPS_INVALID") from exc
        if value < 0 or value > 100000:
            raise PricingError("FEE_BPS_INVALID")
        return value

    overhead = bps("overhead_bps")
    taxes = bps("taxes_bps")
    margin = bps("target_margin_bps")
    if margin >= 10000:
        raise PricingError("FEE_MARGIN_MUST_BE_BELOW_100_PERCENT")

    labor = (hours * Decimal(hourly)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    cost_with_overhead = (labor * (Decimal(10000 + overhead) / Decimal(10000))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    pre_tax = (cost_with_overhead / (Decimal(1) - (Decimal(margin) / Decimal(10000)))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    total = (pre_tax * (Decimal(10000 + taxes) / Decimal(10000))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    lines = [{
        "expected_hours": str(hours.normalize()),
        "hourly_cost_cents": hourly,
        "labor_cost_cents": int(labor),
        "overhead_bps": overhead,
        "taxes_bps": taxes,
        "target_margin_bps": margin,
        "explicit_office_parameters": True,
        "llm_numeric_authority": False,
    }]
    provenance = {
        "schema_version": "glip.pricing-estimate.v1",
        "mode": "professional_fee",
        "inputs": lines[0],
    }
    estimate = PricingEstimate(
        tenant_id=tenant_id,
        project_id=project_id,
        estimate_mode="professional_fee",
        scenario=str(body.get("scenario") or "probable"),
        status="estimated",
        currency="BRL",
        total_cents=int(total),
        inputs_json=lines[0],
        lines_json=lines,
        provenance_sha256=_canonical_sha256(provenance),
        created_by=actor,
    )
    db.add(estimate)
    db.flush()
    db.add(VerticalCostLedger(
        tenant_id=tenant_id,
        project_id=project_id,
        event_kind="professional_fee_estimate",
        evidence_status="estimated",
        currency="BRL",
        amount_cents=int(total),
        source_type="pricing_estimate",
        source_ref=estimate.id,
        billing_scope="glip",
        metadata_json={"provenance_sha256": estimate.provenance_sha256},
        created_by=actor,
    ))
    db.flush()
    return estimate


def add_realized_cost(
    db: Session,
    tenant_id: str,
    project_id: str,
    actor: str,
    actor_role: str,
    body: dict,
) -> VerticalCostLedger:
    amount = body.get("amount_cents")
    evidence_status = str(body.get("evidence_status") or "unknown").strip().lower()
    if evidence_status not in {"unknown", "estimated", "actual"}:
        raise PricingError("COST_EVIDENCE_STATUS_INVALID")

    if evidence_status == "unknown":
        if amount is not None:
            raise PricingError("UNKNOWN_COST_MUST_NOT_HAVE_AMOUNT")
        amount_int = None
    else:
        try:
            amount_int = int(amount)
        except Exception as exc:
            raise PricingError("COST_AMOUNT_INVALID") from exc
        if amount_int < 0:
            raise PricingError("COST_AMOUNT_INVALID")

    source_ref = str(body.get("source_ref") or "").strip() or None
    metadata = dict(body.get("metadata") or {})

    if evidence_status == "actual":
        _require_financial_approver(actor_role)
        if not source_ref:
            raise PricingError("ACTUAL_COST_EVIDENCE_REQUIRED")
        if not source_ref.startswith("document:") or not source_ref.split(":", 1)[1]:
            raise PricingError("ACTUAL_COST_EVIDENCE_REF_INVALID")

        document_id = source_ref.split(":", 1)[1]
        document = db.scalar(select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.project_id == project_id,
            Document.active.is_(True),
        ))
        if not document:
            raise PricingError("ACTUAL_COST_EVIDENCE_NOT_FOUND")
        purposes = {str(x).strip().lower() for x in (document.allowed_purposes or [])}
        if "cost_evidence" not in purposes:
            raise PricingError("ACTUAL_COST_EVIDENCE_PURPOSE_REQUIRED")

        metadata.update({
            "evidence_document_id": document.id,
            "evidence_document_version": document.version,
            "evidence_verified_tenant": tenant_id,
            "evidence_verified_project": project_id,
        })

    event = VerticalCostLedger(
        tenant_id=tenant_id,
        project_id=project_id,
        event_kind=str(body.get("event_kind") or "realized_cost")[:64],
        evidence_status=evidence_status,
        currency=str(body.get("currency") or "BRL").upper()[:8],
        amount_cents=amount_int,
        source_type=str(body.get("source_type") or "manual")[:64],
        source_ref=source_ref,
        billing_scope="glip",
        metadata_json=metadata,
        created_by=actor,
    )
    db.add(event)
    db.flush()
    return event

def _parse_dt(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricingError("PRICE_SOURCE_RETRIEVED_AT_INVALID") from exc
