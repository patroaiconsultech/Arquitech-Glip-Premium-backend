from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from pathlib import PurePosixPath
from sqlalchemy import select
from sqlalchemy.orm import Session

from .artifacts.storage import BlobStorage, BlobStorageError, build_blob_storage
from .models import ArchitecturalSource, ArtifactUsageEvent

SOURCE_FORMATS={
    ".dwg":"dwg",
    ".dxf":"dxf",
    ".pdf":"pdf",
    ".ifc":"ifc",
    ".ifczip":"ifczip",
    ".ifcxml":"ifcxml",
    ".glb":"glb",
    ".gltf":"gltf",
}
MIME_BY_FORMAT={
    "dwg":"application/acad",
    "dxf":"application/dxf",
    "pdf":"application/pdf",
    "ifc":"application/x-step",
    "ifczip":"application/zip",
    "ifcxml":"application/xml",
    "glb":"model/gltf-binary",
    "gltf":"model/gltf+json",
}

class ArchitecturalSourceError(RuntimeError): pass

def safe_source_filename(value:str)->str:
    name=PurePosixPath((value or "").replace("\\","/")).name.strip()
    if not name or name in {".",".."}: raise ArchitecturalSourceError("ARCH_SOURCE_FILENAME_INVALID")
    clean=re.sub(r"[^A-Za-z0-9._ -]+","_",name).strip(" .")
    if not clean: raise ArchitecturalSourceError("ARCH_SOURCE_FILENAME_INVALID")
    return clean[:180]

def source_format_for(filename:str)->str:
    suffix=PurePosixPath(filename.lower()).suffix
    if suffix not in SOURCE_FORMATS:
        raise ArchitecturalSourceError("ARCH_SOURCE_FORMAT_UNSUPPORTED")
    return SOURCE_FORMATS[suffix]

def detect_ifc_schema(prefix:bytes)->str|None:
    try:
        text=prefix.decode("utf-8","ignore")
    except Exception:
        return None
    match=re.search(r"FILE_SCHEMA\s*\(\s*\(\s*['\"]([^'\"]+)['\"]",text,re.I)
    return match.group(1).upper()[:64] if match else None

async def ingest_architectural_source(
    db:Session,*,settings,tenant_id:str,project_id:str,actor_id:str,
    upload,classification:str="project_internal",storage:BlobStorage|None=None,
)->tuple[ArchitecturalSource,bool]:
    if not getattr(settings,"architecture_uploads_enabled",False):
        raise ArchitecturalSourceError("ARCHITECTURE_UPLOADS_DISABLED")
    filename=safe_source_filename(upload.filename or "")
    fmt=source_format_for(filename)
    limit=int(getattr(settings,"max_architectural_source_bytes",250_000_000))
    h=hashlib.sha256(); size=0; prefix=b""
    with tempfile.NamedTemporaryFile(prefix="glip-arch-",suffix=".upload",delete=False) as tmp:
        temp_path=tmp.name
        try:
            while True:
                chunk=await upload.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>limit: raise ArchitecturalSourceError("ARCH_SOURCE_TOO_LARGE")
                if len(prefix)<1024*1024:
                    prefix += chunk[:1024*1024-len(prefix)]
                h.update(chunk); tmp.write(chunk)
        except Exception:
            from pathlib import Path
            Path(temp_path).unlink(missing_ok=True)
            raise
    from pathlib import Path
    path=Path(temp_path)
    try:
        if size<=0: raise ArchitecturalSourceError("ARCH_SOURCE_EMPTY")
        digest=h.hexdigest()
        existing=db.scalar(select(ArchitecturalSource).where(
            ArchitecturalSource.tenant_id==tenant_id,
            ArchitecturalSource.project_id==project_id,
            ArchitecturalSource.sha256==digest,
        ))
        if existing: return existing,True
        source_id=str(uuid.uuid4())
        key=f"{tenant_id}/{project_id}/architecture/sources/{source_id}-{filename}"
        storage=storage or build_blob_storage(settings)
        try:
            created=storage.put_file_if_absent(
                key,path,content_type=(upload.content_type or MIME_BY_FORMAT.get(fmt,"application/octet-stream"))
            )
            if not created: raise ArchitecturalSourceError("ARCH_SOURCE_STORAGE_COLLISION")
        except BlobStorageError as exc:
            raise ArchitecturalSourceError(str(exc)) from exc
        row=ArchitecturalSource(
            id=source_id,tenant_id=tenant_id,project_id=project_id,source_format=fmt,
            original_filename=filename,mime_type=upload.content_type or MIME_BY_FORMAT.get(fmt),
            storage_key=key,sha256=digest,size_bytes=size,classification=classification,
            ifc_schema=detect_ifc_schema(prefix) if fmt=="ifc" else None,
            status="uploaded",version=1,created_by=actor_id,
        )
        db.add(row)
        db.add(ArtifactUsageEvent(
            tenant_id=tenant_id,project_id=project_id,billing_scope="glip",
            usage_type="architectural_source_upload",provider="glip_storage",
            provider_profile_ref=getattr(settings,"artifact_provider_profile_ref","glip-local"),
            units_json={"format":fmt,"bytes":size},cost_microusd=None,
        ))
        db.flush()
        return row,False
    finally:
        path.unlink(missing_ok=True)

def architecture_capability_manifest(settings)->dict:
    return {
        "schema_version":"glip.arch-capabilities.v1",
        "uploads_enabled":bool(getattr(settings,"architecture_uploads_enabled",False)),
        "source_formats":["dwg","dxf","pdf","ifc","ifczip","ifcxml","glb","gltf"],
        "bim":{
            "ifc_first_class":True,
            "ifc_target":"IFC4.3 ADD2 / ISO 16739-1:2024",
            "ifc_backward_compatibility":["IFC4","IFC2x3"],
            "semantic_parser_status":"ADAPTER_READY" if bool(getattr(settings,"bim_semantic_enabled",False)) else "PENDING_GATE_2",
            "bcf_status":"PLANNED",
        },
        "cad":{
            "dwg_first_class":True,
            "dxf_first_class":True,
            "dxf_semantic_parser_status":"ADAPTER_READY" if bool(getattr(settings,"cad_semantic_enabled",False)) else "DISABLED",
            "autodesk_aps_status":"PLANNED_GATE_4",
            "dwg_decoder_status":"EXTERNAL_ADAPTER_REQUIRED",
        },
        "scene":{
            "schema":"glip.arch.scene.v1",
            "distribution_format":"glb/gltf",
            "quantity_schema":"glip.quantity-takeoff.v1",
            "geometry_preview_status":"ADAPTER_READY" if bool(getattr(settings,"geometry_build_enabled",False)) else "DISABLED",
            "authoritative_3d_status":"IFC_GEOMETRY_PENDING",
        },
        "pricing":{
            "quantity_takeoff_status":"FOUNDATION_READY",
            "market_price_ingestion_status":"PLANNED",
            "professional_fee_mode":"PLANNED",
            "construction_cost_mode":"PLANNED",
            "llm_numeric_authority":False,
        },
        "render":{
            "technical_engine":"blender",
            "status":"PENDING_GATE_4",
            "ai_enhancement_status":"PENDING_GATE_5",
        },
    }
