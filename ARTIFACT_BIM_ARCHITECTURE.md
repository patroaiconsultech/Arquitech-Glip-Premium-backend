# GLIP Artifact + CAD/BIM Architecture — RC7 Geometry & Quantity Foundation

## Implemented through RC7

### Document artifacts
- DOCX, PDF, PPTX, XLSX
- semantic reopen/validation
- SHA-256 integrity
- GLIP-isolated local/S3-compatible storage
- GLIP-only billing scope/provider profile

### Architectural sources
- first-class IFC
- DXF
- DWG upload registry (decode remains external adapter)
- PDF
- IFCZIP / IFCXML upload registry
- GLB / glTF derived/source registry
- tenant/project versioned source provenance

### BIM semantics — RC6
- isolated IfcOpenShell worker contract
- IFC GUID/class/spatial containment/type/material/property extraction
- IFC remains semantic source-of-truth
- real IfcOpenShell runtime with production-like IFC remains a staging gate

### CAD semantics — RC7
- isolated DXF worker
- `ezdxf` adapter
- units normalized to meters
- layers / entity counts / block counts
- measurable line/path length
- closed path/circle areas where deterministically available
- raw CAD quantities marked **not automatically pricing eligible**
- DWG decoding is not performed in FastAPI; Autodesk APS/ODA remains external

### Quantity foundation — RC7
- `glip.quantity-takeoff.v1`
- recognized standard IFC `Qto_*` quantities normalized to m / m² / m³ / count
- custom numeric properties are not silently promoted to quantities
- IFC Qto provenance marked `authoritative_ifc`
- CAD raw measurements marked `cad_raw_unmapped`
- `llm_numeric_authority=false`

### Geometry preview — RC7
- deterministic GLB linework preview using Trimesh
- GLB stored as GLIP-owned `ArtifactAsset(kind=model3d)`
- preview explicitly labeled `preview_only=true`
- source SHA, scene version and engine version preserved
- **no claim of inferred architectural 3D**
- authoritative IFC mesh extraction remains a next gate

## BIM policy

IFC is not replaced by GLB/glTF.

```text
IFC source
  → semantic scene
  → quantities
  → authoritative geometry (future IFC geom gate)
  → derived GLB/glTF
```

Any GLB is a derived visualization artifact and retains source/scene provenance.

## Pricing policy

Pricing Intelligence is a separate plane.

Two modes are planned:

1. professional architecture fees;
2. construction/project execution costs.

LLM may classify scope and explain mappings, but price numbers must come from
versioned sources or explicit office/project data.

Planned authorities include:
- CAU professional-fee methodology for fee references;
- SINAPI;
- state CUB references;
- SICRO where applicable;
- project supplier quotations;
- GLIP-approved historical proposals/actual costs.

See `PRICING_INTELLIGENCE_ARCHITECTURE.md`.

## Feature flags

All new surfaces remain disabled by default:

```text
GLIP_ARTIFACTS_ENABLED=false
GLIP_ARCHITECTURE_UPLOADS_ENABLED=false
GLIP_BIM_SEMANTIC_ENABLED=false
GLIP_CAD_SEMANTIC_ENABLED=false
GLIP_GEOMETRY_BUILD_ENABLED=false
GLIP_PRICING_INTELLIGENCE_ENABLED=false
```

## Current deployment boundary

Local code validation does not prove:
- real PostgreSQL migration/concurrency;
- real S3 object storage;
- production IfcOpenShell worker;
- fresh Docker geometry-worker build;
- Autodesk APS;
- authoritative IFC mesh → GLB;
- browser 3D viewer;
- Blender/GPU render;
- market price ingestion;
- staging/production.

Those remain explicit gates.
