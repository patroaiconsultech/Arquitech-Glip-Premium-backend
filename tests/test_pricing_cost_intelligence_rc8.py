from __future__ import annotations

from sqlalchemy import select

from glip.models import PriceSourceSnapshot, VerticalCostLedger
from glip.pricing.sources import detailed_cost_role_allowed


def _project(client, headers, name="Pricing Project"):
    r = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _snapshot_payload(
    source_key="supplier_quote",
    role="MARKET_QUOTE",
    price=1250,
    code="QUOTE-001",
    unit="m2",
):
    return {
        "source_key": source_key,
        "roles": [role],
        "geography": {"country": "BR", "uf": "RS"},
        "competency": "2026-08",
        "source_ref": f"https://example.invalid/{source_key}/2026-08",
        "evidence_sha256": ("a" if source_key == "sinapi_caixa" else "b") * 64,
        "validity_status": "valid",
        "items": [{
            "source_code": code,
            "description": "Reference item",
            "unit": unit,
            "role": role,
            "currency": "BRL",
            "unit_price_cents": price,
            "evidence": {"row": 1},
            # Caller input must not grant authority.
            "manually_approved": True,
        }],
    }


def _create_and_approve_snapshot(client, headers, payload):
    created = client.post("/api/v1/pricing/snapshots", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["authority_status"] == "unverified"
    approved = client.post(
        f"/api/v1/pricing/snapshots/{created.json()['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["authority_status"] == "human_approved"
    return approved.json()


def _create_and_approve_mapping(client, headers, project_id, *, item_id, quantity="10.5", unit="m2", canonical="wall.finish.area"):
    created = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings",
        headers=headers,
        json={
            "canonical_item_id": canonical,
            "quantity_source_ref": "scene:ifc-1:qto:NetSideArea",
            "quantity_value": quantity,
            "quantity_unit": unit,
            "quantity_provenance": "authoritative_ifc",
            "price_source_item_id": item_id,
            "mapping_explanation": "Exact unit and canonical mapping",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "proposed"
    approved = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings/{created.json()['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    return approved.json()


def _mark_server_verified(db, snapshot_id):
    snapshot = db.scalar(select(PriceSourceSnapshot).where(PriceSourceSnapshot.id == snapshot_id))
    assert snapshot is not None
    snapshot.validity_status = "valid"
    snapshot.authority_status = "server_verified"
    snapshot.authority_method = "synthetic_test_fixture"
    snapshot.authority_by = "test-server"
    db.commit()


def test_price_source_registry_declares_roles_and_blocks_benchmark_as_detailed_cost_authority(client, auth_a):
    r = client.get("/api/v1/pricing/sources", headers=auth_a)
    assert r.status_code == 200
    body = r.json()
    assert body["billing_scope"] == "glip"
    assert body["llm_numeric_authority"] is False
    manifest = {x["key"]: x for x in body["items"]}
    assert "BENCHMARK" in manifest["sinduscon_regional"]["allowed_roles"]
    assert "UNIT_PRICE" not in manifest["sinduscon_regional"]["allowed_roles"]
    assert detailed_cost_role_allowed("BENCHMARK") is False
    assert detailed_cost_role_allowed("UNIT_PRICE") is True


def test_price_source_snapshot_is_tenant_scoped_immutable_and_untrusted_by_default(client, auth_a, auth_b):
    created = client.post(
        "/api/v1/pricing/snapshots",
        headers=auth_a,
        json=_snapshot_payload(source_key="sinapi_caixa", role="UNIT_PRICE", code="SIN-001"),
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["billing_scope"] == "glip"
    assert created.json()["validity_status"] == "human_review_required"
    assert created.json()["authority_status"] == "unverified"
    assert created.json()["items"][0]["manually_approved"] is False

    own = client.get(f"/api/v1/pricing/snapshots/{sid}", headers=auth_a)
    other = client.get(f"/api/v1/pricing/snapshots/{sid}", headers=auth_b)
    mutate = client.patch(f"/api/v1/pricing/snapshots/{sid}", headers=auth_a, json={"validity_status": "valid"})
    assert own.status_code == 200
    assert other.status_code == 404
    assert mutate.status_code == 405


def test_construction_estimate_is_reconstructible_from_explicitly_approved_quote_and_mapping(client, auth_a):
    project_id = _project(client, auth_a)
    snap = _create_and_approve_snapshot(client, auth_a, _snapshot_payload(price=2500, unit="m2"))
    item_id = snap["items"][0]["id"]
    mapping = _create_and_approve_mapping(
        client, auth_a, project_id, item_id=item_id, quantity="10.5", unit="m2"
    )

    estimate = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/construction",
        headers=auth_a,
        json={"mapping_ids": [mapping["id"]], "scenario": "probable", "factor_bps": 10000},
    )
    assert estimate.status_code == 201, estimate.text
    body = estimate.json()
    assert body["total_cents"] == 26250
    assert body["status"] == "estimated"
    assert body["lines_json"][0]["quantity_provenance"] == "authoritative_ifc"
    assert body["lines_json"][0]["unit_price_cents"] == 2500
    assert len(body["provenance_sha256"]) == 64


def test_benchmark_snapshot_cannot_be_used_as_detailed_unit_price_even_if_server_verified(client, auth_a, db):
    project_id = _project(client, auth_a, "Benchmark guard")
    snap = client.post(
        "/api/v1/pricing/snapshots",
        headers=auth_a,
        json=_snapshot_payload(
            source_key="sinduscon_regional",
            role="BENCHMARK",
            price=450000,
            code="CUB-R8",
            unit="m2",
        ),
    )
    assert snap.status_code == 201, snap.text
    _mark_server_verified(db, snap.json()["id"])
    item_id = snap.json()["items"][0]["id"]
    mapping = _create_and_approve_mapping(
        client, auth_a, project_id, item_id=item_id, quantity="100", unit="m2",
        canonical="construction.high_level_benchmark",
    )

    estimate = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/construction",
        headers=auth_a,
        json={"mapping_ids": [mapping["id"]]},
    )
    assert estimate.status_code == 422
    assert estimate.json()["detail"] == "PRICE_ROLE_NOT_DETAILED_COST_AUTHORITY"


def test_raw_cad_quantity_fails_closed_before_pricing(client, auth_a):
    project_id = _project(client, auth_a, "CAD guard")
    snap = client.post("/api/v1/pricing/snapshots", headers=auth_a, json=_snapshot_payload())
    item_id = snap.json()["items"][0]["id"]
    mapping = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings",
        headers=auth_a,
        json={
            "canonical_item_id": "wall.raw.length",
            "quantity_source_ref": "cad:layer:A-WALL",
            "quantity_value": 12,
            "quantity_unit": "m2",
            "quantity_provenance": "cad_raw_unmapped",
            "price_source_item_id": item_id,
        },
    )
    assert mapping.status_code == 422
    assert mapping.json()["detail"] == "QUANTITY_PROVENANCE_NOT_PRICING_ELIGIBLE"


def test_professional_fee_engine_is_owner_gated_deterministic_and_ledger_is_glip_only(client, auth_a, auth_b, db):
    project_id = _project(client, auth_a, "Fee project")
    r = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/professional-fee",
        headers=auth_a,
        json={
            "expected_hours": "100",
            "hourly_cost_cents": 10000,
            "overhead_bps": 2000,
            "taxes_bps": 1000,
            "target_margin_bps": 2000,
            "scenario": "probable",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_cents"] == 1650000

    db.add(VerticalCostLedger(
        tenant_id="tenant-a",
        project_id=project_id,
        event_kind="foreign_cost",
        evidence_status="estimated",
        currency="BRL",
        amount_cents=999,
        source_type="efata",
        source_ref="foreign",
        billing_scope="efata",
        metadata_json={},
        created_by="test",
    ))
    db.commit()

    ledger = client.get(f"/api/v1/pricing/projects/{project_id}/cost-ledger", headers=auth_a)
    assert ledger.status_code == 200
    assert len(ledger.json()) == 1
    assert ledger.json()[0]["billing_scope"] == "glip"
    denied = client.get(f"/api/v1/pricing/projects/{project_id}/cost-ledger", headers=auth_b)
    assert denied.status_code == 404


def test_actual_cost_requires_resolved_tenant_project_document_with_cost_evidence_purpose(client, auth_a):
    project_id = _project(client, auth_a, "Cost evidence")
    unknown = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=auth_a,
        json={"evidence_status": "unknown", "source_type": "manual"},
    )
    assert unknown.status_code == 201
    assert unknown.json()["amount_cents"] is None

    bad_unknown = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=auth_a,
        json={"evidence_status": "unknown", "amount_cents": 10, "source_type": "manual"},
    )
    assert bad_unknown.status_code == 422

    arbitrary = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=auth_a,
        json={
            "evidence_status": "actual",
            "amount_cents": 10000,
            "source_type": "invoice",
            "source_ref": "document:does-not-exist",
        },
    )
    assert arbitrary.status_code == 404
    assert arbitrary.json()["detail"] == "ACTUAL_COST_EVIDENCE_NOT_FOUND"

    no_purpose = client.post(
        f"/api/v1/projects/{project_id}/documents",
        headers=auth_a,
        json={"name": "Invoice no purpose", "storage_ref": "glip://invoice/no-purpose"},
    )
    assert no_purpose.status_code == 201
    rejected = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=auth_a,
        json={
            "evidence_status": "actual",
            "amount_cents": 10000,
            "source_type": "invoice",
            "source_ref": f"document:{no_purpose.json()['id']}",
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "ACTUAL_COST_EVIDENCE_PURPOSE_REQUIRED"

    evidence = client.post(
        f"/api/v1/projects/{project_id}/documents",
        headers=auth_a,
        json={
            "name": "Invoice 123",
            "storage_ref": "glip://invoice/123",
            "allowed_purposes": ["cost_evidence"],
        },
    )
    assert evidence.status_code == 201
    actual = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=auth_a,
        json={
            "evidence_status": "actual",
            "amount_cents": 10000,
            "source_type": "invoice",
            "source_ref": f"document:{evidence.json()['id']}",
        },
    )
    assert actual.status_code == 201, actual.text
    assert actual.json()["evidence_status"] == "actual"
    assert actual.json()["metadata_json"]["evidence_document_id"] == evidence.json()["id"]


def test_sinapi_zero_price_is_blocked_even_if_server_verified(client, auth_a, db):
    project_id = _project(client, auth_a, "SINAPI zero guard")
    snapshot = client.post(
        "/api/v1/pricing/snapshots",
        headers=auth_a,
        json=_snapshot_payload(
            source_key="sinapi_caixa",
            role="UNIT_PRICE",
            price=0,
            code="SINAPI-ZERO",
            unit="m2",
        ),
    )
    assert snapshot.status_code == 201
    _mark_server_verified(db, snapshot.json()["id"])
    item_id = snapshot.json()["items"][0]["id"]
    mapping = _create_and_approve_mapping(
        client, auth_a, project_id, item_id=item_id, quantity="25", unit="m2",
        canonical="wall.finish",
    )
    estimate = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/construction",
        json={"mapping_ids": [mapping["id"]], "scenario": "probable", "factor_bps": 10000},
        headers=auth_a,
    )
    assert estimate.status_code == 422
    assert estimate.json()["detail"] == "PRICE_ITEM_NON_POSITIVE_NOT_COST_AUTHORITY"
