from __future__ import annotations

from glip.models import Membership


def _project(client, headers, name):
    r = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _member_headers(db, tenant_id="tenant-a", subject="member-a"):
    db.add(Membership(
        tenant_id=tenant_id,
        external_subject=subject,
        display_name=subject,
        role="member",
        active=True,
    ))
    db.commit()
    return {"X-GLIP-Tenant-ID": tenant_id, "X-GLIP-User-ID": subject}


def _supplier_payload(price=999999):
    return {
        "source_key": "supplier_quote",
        "roles": ["MARKET_QUOTE"],
        "geography": {"country": "BR", "uf": "RS"},
        "competency": "2026-09",
        "source_ref": "supplier:unverified-submission",
        "evidence_sha256": "f" * 64,
        "validity_status": "valid",
        "items": [{
            "source_code": "QUOTE-X",
            "description": "Caller submitted quote",
            "unit": "m2",
            "role": "MARKET_QUOTE",
            "unit_price_cents": price,
            "manually_approved": True,
        }],
    }


def _official_payload():
    return {
        "source_key": "sinapi_caixa",
        "roles": ["UNIT_PRICE"],
        "geography": {"country": "BR", "uf": "RS"},
        "competency": "2026-09",
        "source_ref": "caller:claims:sinapi",
        "evidence_sha256": "e" * 64,
        "validity_status": "valid",
        "items": [{
            "source_code": "SIN-ARBITRARY",
            "description": "Caller claims official source",
            "unit": "m2",
            "role": "UNIT_PRICE",
            "unit_price_cents": 999999,
            "manually_approved": True,
        }],
    }


def test_caller_claimed_official_source_stays_unverified_and_cannot_be_human_promoted(client, auth_a):
    created = client.post("/api/v1/pricing/snapshots", headers=auth_a, json=_official_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validity_status"] == "human_review_required"
    assert body["authority_status"] == "unverified"
    assert body["metadata"]["evidence_hash_trust"] == "caller_claimed"
    assert body["metadata"]["monetary_authority"] is False
    assert body["items"][0]["manually_approved"] is False

    promoted = client.post(
        f"/api/v1/pricing/snapshots/{body['id']}/approve",
        headers=auth_a,
    )
    assert promoted.status_code == 422
    assert promoted.json()["detail"] == "PRICE_SOURCE_SERVER_VERIFICATION_REQUIRED"


def test_member_cannot_promote_or_execute_financial_authority(client, auth_a, db):
    member = _member_headers(db)
    project_id = _project(client, auth_a, "Financial auth guard")

    submitted = client.post("/api/v1/pricing/snapshots", headers=member, json=_supplier_payload())
    assert submitted.status_code == 201
    sid = submitted.json()["id"]

    denied_snapshot = client.post(f"/api/v1/pricing/snapshots/{sid}/approve", headers=member)
    assert denied_snapshot.status_code == 403
    assert denied_snapshot.json()["detail"] == "FINANCIAL_APPROVER_REQUIRED"

    approved_snapshot = client.post(f"/api/v1/pricing/snapshots/{sid}/approve", headers=auth_a)
    assert approved_snapshot.status_code == 200
    item_id = approved_snapshot.json()["items"][0]["id"]

    mapping = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings",
        headers=member,
        json={
            "canonical_item_id": "wall.finish",
            "quantity_source_ref": "qto:wall.finish",
            "quantity_value": "2",
            "quantity_unit": "m2",
            "quantity_provenance": "authoritative_ifc",
            "price_source_item_id": item_id,
        },
    )
    assert mapping.status_code == 201
    mid = mapping.json()["id"]

    denied_mapping = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings/{mid}/approve",
        headers=member,
    )
    assert denied_mapping.status_code == 403
    assert denied_mapping.json()["detail"] == "FINANCIAL_APPROVER_REQUIRED"

    approved_mapping = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings/{mid}/approve",
        headers=auth_a,
    )
    assert approved_mapping.status_code == 200

    denied_estimate = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/construction",
        headers=member,
        json={"mapping_ids": [mid]},
    )
    assert denied_estimate.status_code == 403
    assert denied_estimate.json()["detail"] == "FINANCIAL_APPROVER_REQUIRED"

    denied_fee = client.post(
        f"/api/v1/pricing/projects/{project_id}/estimates/professional-fee",
        headers=member,
        json={"expected_hours": 1, "hourly_cost_cents": 1000},
    )
    assert denied_fee.status_code == 403
    assert denied_fee.json()["detail"] == "FINANCIAL_APPROVER_REQUIRED"


def test_client_cannot_inline_approve_mapping(client, auth_a):
    project_id = _project(client, auth_a, "Inline approval guard")
    snapshot = client.post("/api/v1/pricing/snapshots", headers=auth_a, json=_supplier_payload())
    assert snapshot.status_code == 201
    item_id = snapshot.json()["items"][0]["id"]

    mapping = client.post(
        f"/api/v1/pricing/projects/{project_id}/mappings",
        headers=auth_a,
        json={
            "canonical_item_id": "wall.finish",
            "quantity_source_ref": "qto:wall.finish",
            "quantity_value": "2",
            "quantity_unit": "m2",
            "quantity_provenance": "authoritative_ifc",
            "price_source_item_id": item_id,
            "status": "approved",
        },
    )
    assert mapping.status_code == 422
    assert mapping.json()["detail"] == "QUANTITY_MAPPING_APPROVAL_REQUIRES_APPROVAL_ENDPOINT"


def test_cross_tenant_price_item_injection_is_rejected(client, auth_a, auth_b):
    snapshot = client.post("/api/v1/pricing/snapshots", headers=auth_a, json=_supplier_payload())
    assert snapshot.status_code == 201
    foreign_item_id = snapshot.json()["items"][0]["id"]
    project_b = _project(client, auth_b, "Tenant B pricing")

    injected = client.post(
        f"/api/v1/pricing/projects/{project_b}/mappings",
        headers=auth_b,
        json={
            "canonical_item_id": "wall.finish",
            "quantity_source_ref": "qto:wall.finish",
            "quantity_value": "2",
            "quantity_unit": "m2",
            "quantity_provenance": "authoritative_ifc",
            "price_source_item_id": foreign_item_id,
        },
    )
    assert injected.status_code == 404
    assert injected.json()["detail"] == "PRICE_SOURCE_ITEM_NOT_FOUND"


def test_actual_cost_rejects_cross_tenant_and_arbitrary_evidence(client, auth_a, auth_b):
    project_a = _project(client, auth_a, "Evidence A")
    project_b = _project(client, auth_b, "Evidence B")
    doc_a = client.post(
        f"/api/v1/projects/{project_a}/documents",
        headers=auth_a,
        json={
            "name": "Invoice A",
            "storage_ref": "glip://tenant-a/invoice-a",
            "allowed_purposes": ["cost_evidence"],
        },
    )
    assert doc_a.status_code == 201

    arbitrary = client.post(
        f"/api/v1/pricing/projects/{project_b}/cost-ledger",
        headers=auth_b,
        json={
            "evidence_status": "actual",
            "amount_cents": 123,
            "source_type": "invoice",
            "source_ref": "https://caller.example/invoice",
        },
    )
    assert arbitrary.status_code == 422
    assert arbitrary.json()["detail"] == "ACTUAL_COST_EVIDENCE_REF_INVALID"

    cross = client.post(
        f"/api/v1/pricing/projects/{project_b}/cost-ledger",
        headers=auth_b,
        json={
            "evidence_status": "actual",
            "amount_cents": 123,
            "source_type": "invoice",
            "source_ref": f"document:{doc_a.json()['id']}",
        },
    )
    assert cross.status_code == 404
    assert cross.json()["detail"] == "ACTUAL_COST_EVIDENCE_NOT_FOUND"


def test_member_cannot_record_actual_even_with_valid_document(client, auth_a, db):
    member = _member_headers(db, subject="member-cost")
    project_id = _project(client, auth_a, "Actual role guard")
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents",
        headers=auth_a,
        json={
            "name": "Invoice",
            "storage_ref": "glip://invoice/member-guard",
            "allowed_purposes": ["cost_evidence"],
        },
    )
    assert doc.status_code == 201

    denied = client.post(
        f"/api/v1/pricing/projects/{project_id}/cost-ledger",
        headers=member,
        json={
            "evidence_status": "actual",
            "amount_cents": 1000,
            "source_type": "invoice",
            "source_ref": f"document:{doc.json()['id']}",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "FINANCIAL_APPROVER_REQUIRED"


def test_glip_historical_source_is_not_publicly_assertable(client, auth_a):
    payload = {
        "source_key": "glip_historical",
        "roles": ["REALIZED_COST"],
        "geography": {"country": "BR"},
        "competency": "2026-09",
        "source_ref": "caller:fake-history",
        "evidence_sha256": "c" * 64,
        "validity_status": "valid",
        "items": [{
            "source_code": "HIST-1",
            "description": "Caller fake historical",
            "unit": "m2",
            "role": "REALIZED_COST",
            "unit_price_cents": 100,
        }],
    }
    r = client.post("/api/v1/pricing/snapshots", headers=auth_a, json=payload)
    assert r.status_code == 422
    assert r.json()["detail"] == "PRICE_SOURCE_INTERNAL_ONLY"
