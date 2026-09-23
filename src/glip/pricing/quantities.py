
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math


class QuantityTakeoffError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuantityItem:
    element_guid: str | None
    ifc_class: str
    quantity_set: str
    quantity_name: str
    value: float
    unit: str
    raw_value: float
    confidence: str = "authoritative_ifc"
    normalization_method: str = "IFC_QTO_NAME_DIMENSION"

    def as_dict(self) -> dict[str, Any]:
        return {
            "element_guid": self.element_guid,
            "ifc_class": self.ifc_class,
            "quantity_set": self.quantity_set,
            "quantity_name": self.quantity_name,
            "value": self.value,
            "unit": self.unit,
            "raw_value": self.raw_value,
            "confidence": self.confidence,
            "normalization_method": self.normalization_method,
        }


def _dimension_for_quantity(name: str) -> tuple[str, int] | None:
    n=(name or "").strip().lower()
    # Standard IFC base quantity names commonly end in these dimensions.
    if any(token in n for token in ("area",)):
        return ("m2",2)
    if any(token in n for token in ("volume",)):
        return ("m3",3)
    if any(token in n for token in ("length","height","width","depth","perimeter","thickness")):
        return ("m",1)
    if n.endswith("count") or n in {"count","number","quantity"}:
        return ("count",0)
    return None


def extract_ifc_quantity_takeoff(scene: dict[str, Any]) -> dict[str, Any]:
    """Extract normalized IFC quantity-set values from a semantic scene.

    Only Qto_* sets and recognized dimensions are included. This prevents
    arbitrary custom numeric properties from silently becoming billable
    quantities. Linear model-unit scale is raised to the quantity dimension.
    """
    semantic_source=dict(scene.get("semantic_source") or {})
    try:
        unit_scale=float(semantic_source.get("unit_scale_to_m",1.0) or 1.0)
    except Exception as exc:
        raise QuantityTakeoffError("QUANTITY_UNIT_SCALE_INVALID") from exc
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise QuantityTakeoffError("QUANTITY_UNIT_SCALE_INVALID")

    items: list[QuantityItem]=[]
    for element in list(scene.get("elements") or []):
        if not isinstance(element,dict):
            continue
        guid=element.get("guid")
        ifc_class=str(element.get("ifc_class") or "IfcElement")
        psets=element.get("property_sets") or {}
        if not isinstance(psets,dict):
            continue
        for set_name,props in psets.items():
            set_name=str(set_name or "")
            if not set_name.lower().startswith("qto_") or not isinstance(props,dict):
                continue
            for quantity_name,raw in props.items():
                dim=_dimension_for_quantity(str(quantity_name))
                if not dim:
                    continue
                if isinstance(raw,bool):
                    continue
                try:
                    raw_value=float(raw)
                except Exception:
                    continue
                if not math.isfinite(raw_value) or raw_value < 0:
                    continue
                unit,power=dim
                value=raw_value * (unit_scale ** power)
                items.append(QuantityItem(
                    element_guid=str(guid) if guid is not None else None,
                    ifc_class=ifc_class,
                    quantity_set=set_name[:160],
                    quantity_name=str(quantity_name)[:160],
                    value=round(value,9),
                    unit=unit,
                    raw_value=raw_value,
                ))

    aggregates: dict[tuple[str,str,str],dict[str,Any]]={}
    for item in items:
        key=(item.ifc_class,item.quantity_name,item.unit)
        agg=aggregates.setdefault(key,{
            "ifc_class":item.ifc_class,
            "quantity_name":item.quantity_name,
            "unit":item.unit,
            "value":0.0,
            "element_count":0,
            "confidence":"authoritative_ifc",
        })
        agg["value"]+=item.value
        agg["element_count"]+=1
    aggregate_rows=[]
    for key in sorted(aggregates):
        row=aggregates[key]
        row["value"]=round(float(row["value"]),9)
        aggregate_rows.append(row)

    return {
        "schema_version":"glip.quantity-takeoff.v1",
        "source_kind":"ifc_qto",
        "source_sha256":semantic_source.get("source_sha256"),
        "unit_scale_to_m":unit_scale,
        "items":[x.as_dict() for x in items],
        "aggregates":aggregate_rows,
        "statistics":{
            "item_count":len(items),
            "aggregate_count":len(aggregate_rows),
            "element_count_with_quantities":len({x.element_guid for x in items if x.element_guid}),
        },
        "pricing_readiness":{
            "status":"QUANTITIES_READY" if items else "NO_STANDARD_QTO_FOUND",
            "price_authority":"NOT_ASSIGNED",
            "llm_numeric_authority":False,
        },
    }


def extract_cad_raw_quantities(cad_scene: dict[str,Any]) -> dict[str,Any]:
    """Aggregate DXF-derived raw measurements by layer.

    These are *not* construction quantities until a layer/semantic mapping is
    approved. They are intentionally marked low-confidence for pricing.
    """
    rows=[]
    for layer in list(cad_scene.get("layers") or []):
        if not isinstance(layer,dict):
            continue
        name=str(layer.get("name") or "0")
        for field,unit in (("length_m","m"),("area_m2","m2"),("entity_count","count")):
            value=layer.get(field)
            if value is None:
                continue
            try:
                value=float(value)
            except Exception:
                continue
            if value < 0 or not math.isfinite(value):
                continue
            rows.append({
                "layer":name,
                "quantity_name":field,
                "value":round(value,9),
                "unit":unit,
                "confidence":"cad_raw_unmapped",
                "pricing_eligible":False,
            })
    return {
        "schema_version":"glip.quantity-takeoff.v1",
        "source_kind":"cad_raw",
        "items":rows,
        "aggregates":rows,
        "statistics":{"item_count":len(rows)},
        "pricing_readiness":{
            "status":"SEMANTIC_MAPPING_REQUIRED",
            "price_authority":"NOT_ASSIGNED",
            "llm_numeric_authority":False,
        },
    }
