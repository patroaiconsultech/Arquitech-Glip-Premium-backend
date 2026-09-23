
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
from typing import Any
import hashlib


class GeometryPreviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class GLBPreviewResult:
    data: bytes
    sha256: str
    engine: str
    engine_version: str
    statistics: dict[str,Any]


class TrimeshLinePreviewEngine:
    """Build a deterministic GLB linework preview from normalized scene paths.

    This is deliberately a CAD/BIM *preview* and not a fabricated 3D model.
    True architectural 3D geometry must come from IFC geometry or approved
    semantic/extrusion rules.
    """
    name="trimesh"

    def available(self)->bool:
        return util.find_spec("trimesh") is not None

    @property
    def version(self)->str:
        try:
            return metadata.version("trimesh")
        except Exception:
            return "unknown"

    def build(self, scene:dict[str,Any], *, max_paths:int=20_000, max_points:int=500_000)->GLBPreviewResult:
        if not self.available():
            raise GeometryPreviewError("GEOMETRY_ENGINE_UNAVAILABLE")
        try:
            import numpy as np
            import trimesh
            from trimesh.exchange.gltf import export_glb
        except Exception as exc:
            raise GeometryPreviewError("GEOMETRY_ENGINE_IMPORT_FAILED") from exc

        geometry=dict(scene.get("geometry") or {})
        paths=list(geometry.get("paths") or [])
        if len(paths)>max_paths:
            raise GeometryPreviewError("GEOMETRY_PATH_LIMIT_EXCEEDED")

        vertices=[]
        edges=[]
        point_count=0
        path_count=0
        for path in paths:
            points=path.get("points_m") if isinstance(path,dict) else None
            if not isinstance(points,list) or len(points)<2:
                continue
            if point_count+len(points)>max_points:
                raise GeometryPreviewError("GEOMETRY_POINT_LIMIT_EXCEEDED")
            start=len(vertices)
            clean=[]
            for p in points:
                if not isinstance(p,(list,tuple)) or len(p)<2:
                    continue
                try:
                    x=float(p[0]);y=float(p[1]);z=float(p[2] if len(p)>2 else 0.0)
                except Exception:
                    continue
                clean.append((x,y,z))
            if len(clean)<2:
                continue
            vertices.extend(clean)
            for idx in range(len(clean)-1):
                edges.append((start+idx,start+idx+1))
            if bool(path.get("closed")) and len(clean)>2:
                edges.append((start+len(clean)-1,start))
            point_count+=len(clean)
            path_count+=1

        if not vertices or not edges:
            raise GeometryPreviewError("GEOMETRY_NO_PREVIEW_PATHS")

        try:
            verts=np.asarray(vertices,dtype=float)
            entities=[trimesh.path.entities.Line([a,b]) for a,b in edges]
            path3d=trimesh.path.Path3D(entities=entities,vertices=verts,process=False)
            tm_scene=trimesh.Scene()
            tm_scene.add_geometry(path3d,node_name="GLIP_CAD_PREVIEW",geom_name="GLIP_CAD_PREVIEW")
            glb=export_glb(tm_scene,include_normals=False)
        except Exception as exc:
            raise GeometryPreviewError("GEOMETRY_GLB_EXPORT_FAILED") from exc
        if not isinstance(glb,(bytes,bytearray)) or len(glb)<20:
            raise GeometryPreviewError("GEOMETRY_GLB_INVALID")
        data=bytes(glb)
        return GLBPreviewResult(
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            engine=self.name,
            engine_version=self.version,
            statistics={
                "path_count":path_count,
                "point_count":point_count,
                "edge_count":len(edges),
                "bytes":len(data),
                "preview_only":True,
            },
        )
