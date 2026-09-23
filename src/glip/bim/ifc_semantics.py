from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
from typing import Any, Protocol

from glip.pricing.quantities import extract_ifc_quantity_takeoff


class BIMSemanticError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticExtractionResult:
    scene: dict[str, Any]
    engine: str
    engine_version: str
    statistics: dict[str, Any]


class BIMSemanticEngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def extract(self, path: Path, *, source_sha256: str, max_elements: int) -> SemanticExtractionResult: ...


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)[:500]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k)[:160]: _json_safe(v, depth=depth + 1) for k, v in list(value.items())[:128]}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth=depth + 1) for v in list(value)[:256]]
    try:
        return float(value)
    except Exception:
        return str(value)[:500]


class IfcOpenShellSemanticEngine:
    name = "ifcopenshell"

    def available(self) -> bool:
        return util.find_spec("ifcopenshell") is not None

    @property
    def version(self) -> str:
        try:
            return metadata.version("ifcopenshell")
        except Exception:
            return "unknown"

    def extract(self, path: Path, *, source_sha256: str, max_elements: int) -> SemanticExtractionResult:
        if not self.available():
            raise BIMSemanticError("BIM_ENGINE_UNAVAILABLE")
        try:
            import ifcopenshell
            import ifcopenshell.util.element as element_util
            import ifcopenshell.util.placement as placement_util
            import ifcopenshell.util.unit as unit_util
        except Exception as exc:
            raise BIMSemanticError("BIM_ENGINE_IMPORT_FAILED") from exc

        try:
            model = ifcopenshell.open(str(path))
        except Exception as exc:
            raise BIMSemanticError("IFC_OPEN_FAILED") from exc

        schema = str(getattr(model, "schema_identifier", None) or getattr(model, "schema", "UNKNOWN"))
        try:
            unit_scale = float(unit_util.calculate_unit_scale(model))
        except Exception:
            unit_scale = 1.0

        spatial_classes = ("IfcProject","IfcSite","IfcBuilding","IfcBuildingStorey","IfcSpace")
        spatial: list[dict[str, Any]] = []
        for cls in spatial_classes:
            try:
                entities = model.by_type(cls)
            except Exception:
                entities = []
            for entity in entities:
                item = {
                    "guid": getattr(entity, "GlobalId", None),
                    "ifc_class": entity.is_a(),
                    "name": getattr(entity, "Name", None),
                    "description": getattr(entity, "Description", None),
                }
                if cls == "IfcBuildingStorey":
                    elev = getattr(entity, "Elevation", None)
                    if elev is not None:
                        try: item["elevation_m"] = float(elev) * unit_scale
                        except Exception: pass
                spatial.append(_json_safe(item))

        try:
            all_elements = list(model.by_type("IfcElement"))
        except Exception as exc:
            raise BIMSemanticError("IFC_ELEMENT_ENUMERATION_FAILED") from exc
        if len(all_elements) > max_elements:
            raise BIMSemanticError("BIM_ELEMENT_LIMIT_EXCEEDED")

        by_class: dict[str, int] = {}
        elements: list[dict[str, Any]] = []
        for entity in all_elements:
            cls = str(entity.is_a())
            by_class[cls] = by_class.get(cls, 0) + 1

            container = None
            try:
                c = element_util.get_container(entity)
                if c:
                    container = {
                        "guid": getattr(c, "GlobalId", None),
                        "ifc_class": c.is_a(),
                        "name": getattr(c, "Name", None),
                    }
            except Exception:
                pass

            type_info = None
            try:
                t = element_util.get_type(entity)
                if t:
                    type_info = {
                        "guid": getattr(t, "GlobalId", None),
                        "ifc_class": t.is_a(),
                        "name": getattr(t, "Name", None),
                    }
            except Exception:
                pass

            materials: list[dict[str, Any]] = []
            try:
                for material in element_util.get_materials(entity)[:32]:
                    materials.append({
                        "ifc_class": material.is_a(),
                        "name": getattr(material, "Name", None),
                    })
            except Exception:
                pass

            psets: dict[str, Any] = {}
            try:
                raw = element_util.get_psets(entity, should_inherit=True)
                for pset_name, props in list(raw.items())[:64]:
                    if isinstance(props, dict):
                        props = {k: v for k, v in list(props.items())[:128] if k != "id"}
                    psets[str(pset_name)[:160]] = _json_safe(props)
            except Exception:
                pass

            placement = None
            try:
                obj_placement = getattr(entity, "ObjectPlacement", None)
                if obj_placement:
                    matrix = placement_util.get_local_placement(obj_placement)
                    placement = {
                        "x_m": float(matrix[0][3]) * unit_scale,
                        "y_m": float(matrix[1][3]) * unit_scale,
                        "z_m": float(matrix[2][3]) * unit_scale,
                    }
            except Exception:
                pass

            predefined = getattr(entity, "PredefinedType", None)
            item = {
                "guid": getattr(entity, "GlobalId", None),
                "step_id": int(entity.id()),
                "ifc_class": cls,
                "name": getattr(entity, "Name", None),
                "description": getattr(entity, "Description", None),
                "tag": getattr(entity, "Tag", None),
                "predefined_type": str(predefined) if predefined is not None else None,
                "container": container,
                "type": type_info,
                "materials": materials,
                "placement_m": placement,
                "property_sets": psets,
            }
            elements.append(_json_safe(item))

        statistics = {
            "element_count": len(elements),
            "spatial_count": len(spatial),
            "by_class": dict(sorted(by_class.items())),
        }
        scene = {
            "schema_version": "glip.arch.scene.v1",
            "units": "m",
            "semantic_source": {
                "format": "ifc",
                "source_sha256": source_sha256,
                "ifc_schema": schema,
                "engine": self.name,
                "engine_version": self.version,
                "unit_scale_to_m": unit_scale,
            },
            "spatial_structure": spatial,
            "elements": elements,
            "statistics": statistics,
            "geometry": {
                "status": "PENDING_GATE_3",
                "distribution_format": "glb/gltf",
                "semantic_source_of_truth": "ifc",
            },
        }
        scene["quantity_takeoff"] = extract_ifc_quantity_takeoff(scene)
        return SemanticExtractionResult(
            scene=scene,
            engine=self.name,
            engine_version=self.version,
            statistics=statistics,
        )
