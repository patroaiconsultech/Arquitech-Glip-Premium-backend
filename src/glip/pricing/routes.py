from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_principal
from ..context import project_or_404
from ..database import get_db
from ..models import (
    PriceSourceSnapshot,
    PriceSourceItem,
    QuantityPriceMapping,
    PricingEstimate,
    VerticalCostLedger,
)
from .service import (
    PricingError,
    create_price_snapshot,
    approve_price_snapshot,
    create_quantity_mapping,
    approve_quantity_mapping,
    estimate_construction,
    estimate_professional_fee,
    add_realized_cost,
)
from .sources import REGISTRY
from .adapters import contract_for, OfficialSourceContractError

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


def _pricing_error(exc: PricingError):
    code = str(exc)
    status = 403 if code == "FINANCIAL_APPROVER_REQUIRED" else (404 if code.endswith("_NOT_FOUND") else 422)
    raise HTTPException(status, code) from exc


@router.get("/sources")
def pricing_sources(p=Depends(get_principal)):
    return {
        "schema_version": "glip.price-source-registry.v1",
        "tenant_id": p.tenant_id,
        "billing_scope": "glip",
        "llm_numeric_authority": False,
        "items": REGISTRY.manifest(),
    }


@router.get("/sources/{source_key}/contract")
def pricing_source_contract(source_key: str, p=Depends(get_principal)):
    try:
        return {
            **contract_for(source_key).manifest(),
            "tenant_id": p.tenant_id,
            "billing_scope": "glip",
        }
    except OfficialSourceContractError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/snapshots", status_code=201)
def create_snapshot(body: dict, p=Depends(get_principal), db: Session = Depends(get_db)):
    try:
        obj = create_price_snapshot(db, p.tenant_id, p.subject, body)
        db.commit()
        db.refresh(obj)
        return _snapshot_body(db, obj)
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.post("/snapshots/{snapshot_id}/approve", status_code=200)
def approve_snapshot(snapshot_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    try:
        obj = approve_price_snapshot(db, p.tenant_id, p.subject, p.role, snapshot_id)
        db.commit()
        db.refresh(obj)
        return _snapshot_body(db, obj)
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.get("/snapshots")
def list_snapshots(p=Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PriceSourceSnapshot)
        .where(
            PriceSourceSnapshot.tenant_id == p.tenant_id,
            PriceSourceSnapshot.billing_scope == "glip",
        )
        .order_by(PriceSourceSnapshot.created_at.desc())
    ).all()
    return [_snapshot_body(db, x) for x in rows]


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    obj = db.scalar(select(PriceSourceSnapshot).where(
        PriceSourceSnapshot.id == snapshot_id,
        PriceSourceSnapshot.tenant_id == p.tenant_id,
        PriceSourceSnapshot.billing_scope == "glip",
    ))
    if not obj:
        raise HTTPException(404, "PRICE_SOURCE_SNAPSHOT_NOT_FOUND")
    return _snapshot_body(db, obj)


@router.post("/projects/{project_id}/mappings", status_code=201)
def create_mapping(project_id: str, body: dict, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    try:
        obj = create_quantity_mapping(db, p.tenant_id, project_id, p.subject, body)
        db.commit()
        db.refresh(obj)
        return obj
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.post("/projects/{project_id}/mappings/{mapping_id}/approve", status_code=200)
def approve_mapping(project_id: str, mapping_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    try:
        obj = approve_quantity_mapping(
            db, p.tenant_id, project_id, p.subject, p.role, mapping_id
        )
        db.commit()
        db.refresh(obj)
        return obj
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.get("/projects/{project_id}/mappings")
def list_mappings(project_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    return db.scalars(
        select(QuantityPriceMapping)
        .where(
            QuantityPriceMapping.tenant_id == p.tenant_id,
            QuantityPriceMapping.project_id == project_id,
        )
        .order_by(QuantityPriceMapping.created_at.desc())
    ).all()


@router.post("/projects/{project_id}/estimates/construction", status_code=201)
def construction_estimate(project_id: str, body: dict, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    try:
        obj = estimate_construction(
            db,
            p.tenant_id,
            project_id,
            p.subject,
            p.role,
            list(body.get("mapping_ids") or []),
            scenario=str(body.get("scenario") or "probable"),
            factor_bps=int(body.get("factor_bps") if body.get("factor_bps") is not None else 10000),
        )
        db.commit()
        db.refresh(obj)
        return obj
    except (PricingError, ValueError, TypeError) as exc:
        db.rollback()
        if not isinstance(exc, PricingError):
            exc = PricingError("PRICING_FACTOR_INVALID")
        _pricing_error(exc)


@router.post("/projects/{project_id}/estimates/professional-fee", status_code=201)
def professional_fee_estimate(project_id: str, body: dict, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    try:
        obj = estimate_professional_fee(db, p.tenant_id, project_id, p.subject, p.role, body)
        db.commit()
        db.refresh(obj)
        return obj
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.get("/projects/{project_id}/estimates")
def list_estimates(project_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    return db.scalars(
        select(PricingEstimate)
        .where(
            PricingEstimate.tenant_id == p.tenant_id,
            PricingEstimate.project_id == project_id,
        )
        .order_by(PricingEstimate.created_at.desc())
    ).all()


@router.post("/projects/{project_id}/cost-ledger", status_code=201)
def create_cost_event(project_id: str, body: dict, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    try:
        obj = add_realized_cost(db, p.tenant_id, project_id, p.subject, p.role, body)
        db.commit()
        db.refresh(obj)
        return obj
    except PricingError as exc:
        db.rollback()
        _pricing_error(exc)


@router.get("/projects/{project_id}/cost-ledger")
def cost_ledger(project_id: str, p=Depends(get_principal), db: Session = Depends(get_db)):
    project_or_404(db, p.tenant_id, project_id)
    return db.scalars(
        select(VerticalCostLedger)
        .where(
            VerticalCostLedger.tenant_id == p.tenant_id,
            VerticalCostLedger.project_id == project_id,
            VerticalCostLedger.billing_scope == "glip",
        )
        .order_by(VerticalCostLedger.created_at.desc())
    ).all()


def _snapshot_body(db: Session, snapshot: PriceSourceSnapshot) -> dict:
    items = db.scalars(
        select(PriceSourceItem)
        .where(
            PriceSourceItem.tenant_id == snapshot.tenant_id,
            PriceSourceItem.snapshot_id == snapshot.id,
        )
        .order_by(PriceSourceItem.source_code)
    ).all()
    return {
        "id": snapshot.id,
        "tenant_id": snapshot.tenant_id,
        "source_key": snapshot.source_key,
        "provider": snapshot.provider,
        "publisher": snapshot.publisher,
        "roles": snapshot.roles_json,
        "geography": snapshot.geography_json,
        "competency": snapshot.competency,
        "source_ref": snapshot.source_ref,
        "evidence_sha256": snapshot.evidence_sha256,
        "retrieved_at": snapshot.retrieved_at,
        "validity_status": snapshot.validity_status,
        "authority_status": snapshot.authority_status,
        "authority_method": snapshot.authority_method,
        "authority_by": snapshot.authority_by,
        "authority_at": snapshot.authority_at,
        "metadata": snapshot.raw_metadata_json,
        "billing_scope": snapshot.billing_scope,
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at,
        "items": items,
    }
