from __future__ import annotations

import hashlib
import pytest

from glip.pricing.adapters import (
    OFFICIAL_SOURCE_CONTRACTS,
    OfficialSourceContractError,
    OfficialSourceRuntimeNotProven,
    prepare_normalized_snapshot,
    require_live_runtime,
)


def test_official_price_source_contracts_are_fail_closed_until_real_runtime_is_proven():
    assert set(OFFICIAL_SOURCE_CONTRACTS) == {
        "sidra_ibge", "sinapi_caixa", "sicro_dnit", "sinduscon_regional"
    }
    for source_key, contract in OFFICIAL_SOURCE_CONTRACTS.items():
        manifest = contract.manifest()
        assert manifest["live_runtime_status"] == "NOT_PROVEN"
        assert manifest["fail_closed"] is True
        with pytest.raises(OfficialSourceRuntimeNotProven):
            require_live_runtime(source_key)


def test_sinapi_normalized_contract_hashes_exact_evidence_and_downgrades_zero_price_to_partial():
    evidence = b"synthetic-official-evidence-for-contract-test"
    payload = prepare_normalized_snapshot(
        "sinapi_caixa",
        evidence_bytes=evidence,
        source_ref="caixa:sinapi:2026-01:rs",
        competency="2026-01",
        geography={"country": "BR", "uf": "RS"},
        records=[{
            "source_code": "ZERO-001",
            "description": "Published reference with unavailable monetary value",
            "unit": "m2",
            "role": "UNIT_PRICE",
            "unit_price_cents": 0,
        }],
        requested_validity_status="valid",
    )
    assert payload["evidence_sha256"] == hashlib.sha256(evidence).hexdigest()
    assert payload["validity_status"] == "partial"
    assert payload["metadata"]["zero_monetary_values"] == 1
    assert payload["metadata"]["monetary_authority"] is False


def test_sinduscon_contract_rejects_unit_price_role_and_preserves_benchmark_role():
    with pytest.raises(OfficialSourceContractError, match="PRICE_SOURCE_ROLE_NOT_ALLOWED"):
        prepare_normalized_snapshot(
            "sinduscon_regional",
            evidence_bytes=b"cub-evidence",
            source_ref="sinduscon-rs:cub:2026-08",
            competency="2026-08",
            geography={"country": "BR", "uf": "RS"},
            records=[{
                "source_code": "CUB-R8",
                "description": "CUB/m2",
                "unit": "m2",
                "role": "UNIT_PRICE",
                "unit_price_cents": 300000,
            }],
        )

    payload = prepare_normalized_snapshot(
        "sinduscon_regional",
        evidence_bytes=b"cub-evidence",
        source_ref="sinduscon-rs:cub:2026-08",
        competency="2026-08",
        geography={"country": "BR", "uf": "RS"},
        records=[{
            "source_code": "CUB-R8",
            "description": "CUB/m2",
            "unit": "m2",
            "role": "BENCHMARK",
            "unit_price_cents": 300000,
        }],
    )
    assert payload["roles"] == ["BENCHMARK"]


def test_official_source_contract_endpoint_is_tenant_scoped_and_unknown_source_is_404(client, auth_a):
    r = client.get("/api/v1/pricing/sources/sinapi_caixa/contract", headers=auth_a)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["billing_scope"] == "glip"
    assert body["live_runtime_status"] == "NOT_PROVEN"

    missing = client.get("/api/v1/pricing/sources/not-real/contract", headers=auth_a)
    assert missing.status_code == 404
