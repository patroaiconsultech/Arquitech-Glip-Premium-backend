from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable

from .sources import (
    REGISTRY,
    DETAILED_COST_ROLES,
    PriceSourceError,
)


class OfficialSourceContractError(ValueError):
    pass


class OfficialSourceRuntimeNotProven(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialSourceContract:
    source_key: str
    transport_kind: str
    publisher: str
    authority_note: str
    live_runtime_status: str = "NOT_PROVEN"

    def manifest(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "transport_kind": self.transport_kind,
            "publisher": self.publisher,
            "authority_note": self.authority_note,
            "normalized_record_schema": {
                "source_code": "required string",
                "description": "required string",
                "unit": "required string",
                "role": "required registry role",
                "unit_price_cents": "integer|null",
                "currency": "BRL default",
                "evidence": "object",
                "manually_approved": "boolean",
            },
            "live_runtime_status": self.live_runtime_status,
            "fail_closed": True,
        }


OFFICIAL_SOURCE_CONTRACTS: dict[str, OfficialSourceContract] = {
    "sidra_ibge": OfficialSourceContract(
        source_key="sidra_ibge",
        transport_kind="IBGE_SIDRA_API_OR_EXPORTED_DATA",
        publisher="IBGE",
        authority_note="BENCHMARK_ONLY; never detailed unit-price authority.",
    ),
    "sinapi_caixa": OfficialSourceContract(
        source_key="sinapi_caixa",
        transport_kind="CAIXA_MONTHLY_ZIP_XLSX_PDF",
        publisher="CAIXA / IBGE",
        authority_note="UNIT_PRICE/COMPOSITION_REFERENCE only when publication carries usable monetary values.",
    ),
    "sicro_dnit": OfficialSourceContract(
        source_key="sicro_dnit",
        transport_kind="DNIT_UF_COMPETENCY_ARCHIVE",
        publisher="DNIT",
        authority_note="UNIT_PRICE/COMPOSITION_REFERENCE subject to exact UF, competency and evidence.",
    ),
    "sinduscon_regional": OfficialSourceContract(
        source_key="sinduscon_regional",
        transport_kind="REGIONAL_CUB_PUBLICATION",
        publisher="Sinduscon regional",
        authority_note="BENCHMARK_ONLY; CUB must never be transformed into detailed unit price.",
    ),
}


def contract_for(source_key: str) -> OfficialSourceContract:
    key = str(source_key or "").strip().lower()
    contract = OFFICIAL_SOURCE_CONTRACTS.get(key)
    if not contract:
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_CONTRACT_NOT_FOUND")
    return contract


def require_live_runtime(source_key: str) -> None:
    contract = contract_for(source_key)
    if contract.live_runtime_status != "PROVEN":
        raise OfficialSourceRuntimeNotProven("OFFICIAL_PRICE_SOURCE_LIVE_RUNTIME_NOT_PROVEN")


def prepare_normalized_snapshot(
    source_key: str,
    *,
    evidence_bytes: bytes,
    source_ref: str,
    competency: str,
    geography: dict[str, Any],
    records: Iterable[dict[str, Any]],
    retrieved_at: str | None = None,
    requested_validity_status: str = "valid",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Contract boundary for official-source importers.

    It intentionally does not download or guess vendor layouts. An upstream
    source-specific extractor must provide normalized rows plus the exact raw
    evidence bytes. This function validates authority/roles, computes the
    evidence hash, and fails closed on unusable monetary values.
    """
    contract = contract_for(source_key)
    try:
        registry_adapter = REGISTRY.get(source_key)
    except PriceSourceError as exc:
        raise OfficialSourceContractError(str(exc)) from exc

    if not evidence_bytes:
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_EVIDENCE_REQUIRED")
    if not str(source_ref or "").strip():
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_REF_REQUIRED")
    if not str(competency or "").strip():
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_COMPETENCY_REQUIRED")
    if not isinstance(geography, dict) or not geography:
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_GEOGRAPHY_REQUIRED")

    normalized: list[dict[str, Any]] = []
    roles: list[str] = []
    zero_monetary_values = 0
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_RECORD_INVALID")
        code = str(raw.get("source_code") or "").strip()
        description = str(raw.get("description") or "").strip()
        unit = str(raw.get("unit") or "").strip()
        role = str(raw.get("role") or "").strip().upper()
        if not code or not description or not unit or not role:
            raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_RECORD_REQUIRED_FIELDS")
        try:
            registry_adapter.validate_roles([role])
        except PriceSourceError as exc:
            raise OfficialSourceContractError(str(exc)) from exc

        amount = raw.get("unit_price_cents")
        if amount is not None:
            try:
                amount = int(amount)
            except (TypeError, ValueError) as exc:
                raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_AMOUNT_INVALID") from exc
            if amount < 0:
                raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_AMOUNT_INVALID")
            if role in DETAILED_COST_ROLES and amount == 0:
                zero_monetary_values += 1

        roles.append(role)
        normalized.append({
            "source_code": code,
            "description": description,
            "unit": unit,
            "role": role,
            "currency": str(raw.get("currency") or "BRL").upper(),
            "unit_price_cents": amount,
            "evidence": {
                **(raw.get("evidence") or {}),
                "normalized_record_index": index,
            },
            "manually_approved": bool(raw.get("manually_approved", False)),
        })

    if not normalized:
        raise OfficialSourceContractError("OFFICIAL_PRICE_SOURCE_RECORDS_REQUIRED")

    # Defense in depth: official evidence with zero monetary values is useful
    # for audit, but must not be labeled fully valid for detailed costing.
    validity = str(requested_validity_status or "human_review_required").strip().lower()
    if zero_monetary_values and validity == "valid":
        validity = "partial"

    meta = dict(metadata or {})
    meta.update({
        "adapter_contract": "glip.official-price-source.normalized.v1",
        "transport_kind": contract.transport_kind,
        "live_runtime_status": contract.live_runtime_status,
        "fail_closed": True,
        "zero_monetary_values": zero_monetary_values,
        "monetary_authority": zero_monetary_values == 0,
    })

    return {
        "source_key": source_key,
        "publisher": contract.publisher,
        "roles": list(dict.fromkeys(roles)),
        "geography": geography,
        "competency": competency,
        "source_ref": source_ref,
        "evidence_sha256": sha256(evidence_bytes).hexdigest(),
        "retrieved_at": retrieved_at,
        "validity_status": validity,
        "metadata": meta,
        "items": normalized,
    }
