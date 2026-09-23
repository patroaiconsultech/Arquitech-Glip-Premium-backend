from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ROLE_UNIT_PRICE = "UNIT_PRICE"
ROLE_COMPOSITION_REFERENCE = "COMPOSITION_REFERENCE"
ROLE_BENCHMARK = "BENCHMARK"
ROLE_FEE_REFERENCE = "FEE_REFERENCE"
ROLE_REALIZED_COST = "REALIZED_COST"
ROLE_MARKET_QUOTE = "MARKET_QUOTE"

VALID_ROLES = frozenset({
    ROLE_UNIT_PRICE,
    ROLE_COMPOSITION_REFERENCE,
    ROLE_BENCHMARK,
    ROLE_FEE_REFERENCE,
    ROLE_REALIZED_COST,
    ROLE_MARKET_QUOTE,
})

VALID_SOURCE_STATUSES = frozenset({
    "valid",
    "partial",
    "unavailable",
    "human_review_required",
})

# Only these roles are allowed to carry a line-level monetary authority into
# a deterministic construction estimate. BENCHMARK is deliberately excluded.
DETAILED_COST_ROLES = frozenset({
    ROLE_UNIT_PRICE,
    ROLE_MARKET_QUOTE,
    ROLE_REALIZED_COST,
})


class PriceSourceError(ValueError):
    pass


@dataclass(frozen=True)
class PriceSourceAdapter:
    key: str
    provider: str
    publisher: str
    allowed_roles: frozenset[str]
    structured_status: str = "ADAPTER_CONTRACT_READY"
    external_runtime_status: str = "NOT_PROVEN"

    def validate_roles(self, roles: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(x).strip().upper() for x in roles if str(x).strip()))
        if not normalized:
            raise PriceSourceError("PRICE_SOURCE_ROLE_REQUIRED")
        unknown = set(normalized) - VALID_ROLES
        if unknown:
            raise PriceSourceError("PRICE_SOURCE_ROLE_UNKNOWN")
        if not set(normalized).issubset(self.allowed_roles):
            raise PriceSourceError("PRICE_SOURCE_ROLE_NOT_ALLOWED")
        return normalized


class PriceSourceRegistry:
    def __init__(self, adapters: Iterable[PriceSourceAdapter]):
        self._adapters = {a.key: a for a in adapters}

    def get(self, key: str) -> PriceSourceAdapter:
        adapter = self._adapters.get(str(key or "").strip().lower())
        if not adapter:
            raise PriceSourceError("PRICE_SOURCE_UNKNOWN")
        return adapter

    def manifest(self) -> list[dict]:
        return [
            {
                "key": a.key,
                "provider": a.provider,
                "publisher": a.publisher,
                "allowed_roles": sorted(a.allowed_roles),
                "structured_status": a.structured_status,
                "external_runtime_status": a.external_runtime_status,
                "billing_scope": "glip",
            }
            for a in sorted(self._adapters.values(), key=lambda x: x.key)
        ]


REGISTRY = PriceSourceRegistry([
    PriceSourceAdapter(
        key="sidra_ibge",
        provider="ibge_sidra",
        publisher="IBGE",
        allowed_roles=frozenset({ROLE_BENCHMARK}),
        structured_status="CONTRACT_READY",
    ),
    PriceSourceAdapter(
        key="sinapi_caixa",
        provider="caixa_sinapi",
        publisher="CAIXA / IBGE",
        allowed_roles=frozenset({ROLE_UNIT_PRICE, ROLE_COMPOSITION_REFERENCE}),
    ),
    PriceSourceAdapter(
        key="sicro_dnit",
        provider="dnit_sicro",
        publisher="DNIT",
        allowed_roles=frozenset({ROLE_UNIT_PRICE, ROLE_COMPOSITION_REFERENCE}),
    ),
    PriceSourceAdapter(
        key="sinduscon_regional",
        provider="sinduscon_regional",
        publisher="Sinduscon regional",
        allowed_roles=frozenset({ROLE_BENCHMARK}),
    ),
    PriceSourceAdapter(
        key="supplier_quote",
        provider="supplier_quote",
        publisher="Fornecedor aprovado",
        allowed_roles=frozenset({ROLE_MARKET_QUOTE}),
        external_runtime_status="HUMAN_INPUT",
    ),
    PriceSourceAdapter(
        key="glip_historical",
        provider="glip_historical",
        publisher="GLIP",
        allowed_roles=frozenset({ROLE_REALIZED_COST}),
        external_runtime_status="INTERNAL",
    ),
    PriceSourceAdapter(
        key="cau_fee_reference",
        provider="cau_reference",
        publisher="CAU",
        allowed_roles=frozenset({ROLE_FEE_REFERENCE}),
    ),
])


def detailed_cost_role_allowed(role: str) -> bool:
    return str(role or "").upper() in DETAILED_COST_ROLES
