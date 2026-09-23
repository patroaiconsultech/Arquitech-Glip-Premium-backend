
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
from typing import Any, Protocol
import math

from glip.pricing.quantities import extract_cad_raw_quantities


class CADSemanticError(RuntimeError):
    pass


@dataclass(frozen=True)
class CADSemanticResult:
    scene: dict[str, Any]
    engine: str
    engine_version: str
    statistics: dict[str, Any]


class CADSemanticEngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def extract(self, path: Path, *, source_sha256: str, max_entities: int) -> CADSemanticResult: ...


def _finite(v: Any) -> float | None:
    try:
        x=float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def _polyline_length(points: list[tuple[float,float,float]]) -> float:
    total=0.0
    for a,b in zip(points,points[1:]):
        total += math.dist(a,b)
    return total


def _polygon_area_xy(points: list[tuple[float,float,float]]) -> float:
    if len(points)<3:
        return 0.0
    xy=[(p[0],p[1]) for p in points]
    if xy[0] != xy[-1]:
        xy.append(xy[0])
    return abs(sum(x1*y2-x2*y1 for (x1,y1),(x2,y2) in zip(xy,xy[1:]))) / 2.0


class EzdxfSemanticEngine:
    name="ezdxf"

    def available(self) -> bool:
        return util.find_spec("ezdxf") is not None

    @property
    def version(self) -> str:
        try:
            return metadata.version("ezdxf")
        except Exception:
            return "unknown"

    def extract(self, path: Path, *, source_sha256: str, max_entities: int) -> CADSemanticResult:
        if not self.available():
            raise CADSemanticError("CAD_ENGINE_UNAVAILABLE")
        try:
            import ezdxf
            from ezdxf import units
            from ezdxf.path import make_path
        except Exception as exc:
            raise CADSemanticError("CAD_ENGINE_IMPORT_FAILED") from exc

        try:
            doc=ezdxf.readfile(str(path))
        except Exception as exc:
            raise CADSemanticError("DXF_OPEN_FAILED") from exc

        try:
            insunits=int(doc.header.get("$INSUNITS",0) or 0)
            if insunits:
                unit_scale=float(units.conversion_factor(insunits,units.M))
                unit_name=str(units.unit_name(insunits) or "unknown")
            else:
                unit_scale=1.0
                unit_name="unitless_assumed_m"
        except Exception:
            unit_scale=1.0
            unit_name="unknown_assumed_m"

        modelspace=doc.modelspace()
        entities=list(modelspace)
        if len(entities)>max_entities:
            raise CADSemanticError("CAD_ENTITY_LIMIT_EXCEEDED")

        by_type: dict[str,int]={}
        layer_stats: dict[str,dict[str,Any]]={}
        entity_rows: list[dict[str,Any]]=[]
        preview_paths: list[dict[str,Any]]=[]
        max_preview_paths=min(max_entities,20_000)

        def layer_row(layer: str) -> dict[str,Any]:
            return layer_stats.setdefault(layer,{
                "name":layer,
                "entity_count":0,
                "length_m":0.0,
                "area_m2":0.0,
                "blocks":{},
            })

        for ent in entities:
            typ=str(ent.dxftype())
            layer=str(getattr(ent.dxf,"layer","0") or "0")
            by_type[typ]=by_type.get(typ,0)+1
            ls=layer_row(layer)
            ls["entity_count"]+=1
            handle=str(getattr(ent.dxf,"handle","") or "")

            row: dict[str,Any]={"handle":handle,"type":typ,"layer":layer}
            points: list[tuple[float,float,float]]=[]
            closed=False
            length_native=0.0
            area_native=0.0

            try:
                if typ=="LINE":
                    a=ent.dxf.start; b=ent.dxf.end
                    points=[(float(a.x),float(a.y),float(a.z)),(float(b.x),float(b.y),float(b.z))]
                    length_native=_polyline_length(points)
                elif typ in {"LWPOLYLINE","POLYLINE","ARC","SPLINE","ELLIPSE"}:
                    pth=make_path(ent)
                    pts=[(float(v.x),float(v.y),float(v.z)) for v in pth.flattening(distance=0.01)]
                    points=pts
                    if len(points)>=2:
                        length_native=_polyline_length(points)
                    closed=bool(getattr(ent,"closed",False) or getattr(pth,"is_closed",False))
                    if closed and len(points)>=3:
                        area_native=_polygon_area_xy(points)
                elif typ=="CIRCLE":
                    c=ent.dxf.center; r=float(ent.dxf.radius)
                    row["center"]=[float(c.x)*unit_scale,float(c.y)*unit_scale,float(c.z)*unit_scale]
                    row["radius_m"]=r*unit_scale
                    length_native=2*math.pi*r
                    area_native=math.pi*r*r
                elif typ=="INSERT":
                    name=str(getattr(ent.dxf,"name","") or "")
                    row["block_name"]=name
                    ins=getattr(ent.dxf,"insert",None)
                    if ins is not None:
                        row["insert_m"]=[float(ins.x)*unit_scale,float(ins.y)*unit_scale,float(ins.z)*unit_scale]
                    ls["blocks"][name]=int(ls["blocks"].get(name,0))+1
                elif typ in {"TEXT","MTEXT"}:
                    text=getattr(ent,"text",None) or getattr(ent,"plain_text",lambda:"")()
                    row["text"]=str(text)[:500]
            except Exception:
                # A malformed individual entity does not invalidate the whole DXF,
                # but it is left unmeasured and remains visible in entity counts.
                row["measurement_status"]="unavailable"

            if length_native>0:
                row["length_m"]=round(length_native*unit_scale,9)
                ls["length_m"]+=length_native*unit_scale
            if area_native>0:
                row["area_m2"]=round(area_native*(unit_scale**2),9)
                ls["area_m2"]+=area_native*(unit_scale**2)
            if points and len(preview_paths)<max_preview_paths:
                preview_paths.append({
                    "handle":handle,
                    "layer":layer,
                    "type":typ,
                    "closed":closed,
                    "points_m":[
                        [round(x*unit_scale,9),round(y*unit_scale,9),round(z*unit_scale,9)]
                        for x,y,z in points[:10_000]
                    ],
                })
            entity_rows.append(row)

        layers=[]
        for name in sorted(layer_stats):
            row=layer_stats[name]
            row["length_m"]=round(float(row["length_m"]),9)
            row["area_m2"]=round(float(row["area_m2"]),9)
            row["blocks"]=dict(sorted(row["blocks"].items()))
            layers.append(row)

        statistics={
            "entity_count":len(entity_rows),
            "layer_count":len(layers),
            "by_type":dict(sorted(by_type.items())),
            "preview_path_count":len(preview_paths),
        }
        scene={
            "schema_version":"glip.arch.scene.v1",
            "units":"m",
            "semantic_source":{
                "format":"dxf",
                "source_sha256":source_sha256,
                "engine":self.name,
                "engine_version":self.version,
                "dxf_version":str(getattr(doc,"dxfversion","UNKNOWN")),
                "drawing_units":unit_name,
                "unit_scale_to_m":unit_scale,
            },
            "spatial_structure":[],
            "layers":layers,
            "elements":entity_rows,
            "statistics":statistics,
            "geometry":{
                "status":"CAD_PREVIEW_READY",
                "authority":"2d_cad_source",
                "preview_kind":"linework",
                "paths":preview_paths,
                "distribution_format":"glb/gltf",
                "three_d_semantics_status":"MAPPING_REQUIRED",
            },
        }
        scene["quantity_takeoff"]=extract_cad_raw_quantities(scene)
        return CADSemanticResult(
            scene=scene,
            engine=self.name,
            engine_version=self.version,
            statistics=statistics,
        )
