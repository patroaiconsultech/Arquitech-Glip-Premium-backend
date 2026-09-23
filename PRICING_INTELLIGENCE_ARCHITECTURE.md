# GLIP Pricing Intelligence — Architecture Foundation

## Purpose

GLIP needs two related but distinct pricing capabilities:

1. **Professional Fee Pricing** — how much the architecture practice should charge the client.
2. **Construction Cost Intelligence** — how much the designed work is expected to cost to execute.

They may share project context and quantities, but they do not share the same price authority.

## Non-negotiable rule

The language model is **not** the numeric authority for price.

LLM responsibilities may include:
- classifying scope;
- suggesting mappings;
- explaining an estimate;
- identifying missing inputs;
- comparing scenarios.

Authoritative numeric values must come from versioned price sources, explicit office parameters, approved supplier quotes, or historical GLIP records.

## Mode A — Professional Fee Pricing

Target inputs:
- project typology;
- built/intervention area;
- service scope and phases;
- BIM/CAD/detailing/render deliverables;
- number of revisions;
- deadline / urgency;
- complexity;
- travel/site visits;
- liability/risk;
- taxes and office overhead;
- target margin;
- local market;
- internal historical proposals and realized hours.

Initial reference authorities:
- CAU/BR / CAU/UF indicative professional fee methodology;
- CUB for applicable state/context where the CAU method requires construction-cost reference;
- GLIP internal historical proposals, win/loss and actual-hours records.

Outputs:
- reference fee;
- floor / target / premium scenario;
- estimated internal effort;
- expected gross margin;
- scope assumptions;
- exclusions;
- confidence and source provenance.

## Mode B — Construction Cost Intelligence

Target inputs:
- BIM IFC quantities (preferred);
- geometry-derived quantities with provenance;
- approved CAD layer mappings;
- materials/specifications;
- location / UF;
- date/competency;
- work standard and quality level;
- supplier quotations;
- construction method.

Initial Brazilian source hierarchy:
1. approved project-specific supplier quotations;
2. GLIP historical actual costs for sufficiently equivalent jobs;
3. SINAPI official compositions / inputs for UF and competency;
4. relevant CUB state reference for high-level checks/anchors;
5. SICRO when infrastructure/transport-related compositions are applicable;
6. manually approved custom office reference.

Every source record must preserve:
- provider/source;
- source code;
- description;
- unit;
- location;
- competency date;
- acquisition timestamp;
- raw source reference;
- version/hash;
- whether manually approved.

## Quantity contract

`glip.quantity-takeoff.v1`

Quantities must preserve provenance and confidence:

- `authoritative_ifc`: from standard IFC Qto property sets;
- `geometry_derived`: computed from authoritative geometry;
- `cad_mapped`: derived from an explicitly approved CAD layer/entity mapping;
- `cad_raw_unmapped`: not eligible for automatic pricing;
- `manual_approved`: human-entered/approved quantity.

A price estimate must fail closed when a required quantity has no eligible mapping or price authority.

## Pricing result contract

Future target: `glip.pricing-estimate.v1`

Each line should expose at least:
- canonical item ID;
- quantity and unit;
- quantity provenance;
- matched reference source;
- reference source code;
- unit price;
- competency date;
- location;
- base cost;
- waste/factor adjustments;
- BDI/overhead policy reference if applied;
- subtotal;
- confidence;
- mapping explanation;
- approval status.

## Auditability

Never emit a naked number as "market price".

Every numeric recommendation must be reconstructible from:
`quantity × selected source unit price × explicit factors`.

## Cost isolation

All pricing ingestion and provider usage belongs to GLIP:
- billing_scope=`glip`
- GLIP storage
- GLIP credentials
- GLIP source snapshots
- GLIP audit ledger

No Efata token or cost center is reused.

## Roadmap

- Gate 3: quantity takeoff foundation from IFC and CAD
- Gate P1: price-source snapshot models + SINAPI/CUB/SICRO/manual import adapters
- Gate P2: professional-fee engine using CAU methodology + office economics
- Gate P3: mapping engine and project estimate scenarios
- Gate P4: market learning from approved GLIP historicals with human governance

## RC8 authority hardening

Pricing authority is now explicitly separated from submission.

### Trust states

- `unverified`: caller-submitted evidence. It may be stored for review but has no executable monetary authority.
- `human_approved`: currently restricted to manually approvable `supplier_quote` snapshots after explicit `owner` approval.
- `server_verified`: reserved for server-controlled importers/internal sources. Official sources such as SINAPI/SICRO/Sinduscon/CAU references cannot be promoted through the public human-approval endpoint.

Caller-supplied values such as `validity_status`, `evidence_sha256`, `publisher`, or `manually_approved` never grant executable authority by themselves.

### Financial approval boundary

Current conservative RC8 policy:

- tenant `member`: may submit price evidence and proposed quantity-price mappings;
- tenant `owner`: may approve manually approvable source snapshots, approve quantity-price mappings, create persisted professional-fee estimates, create construction-cost estimates, and record `actual` cost entries;
- official/internal source verification: server-controlled only.

This is intentionally fail-closed until a richer permission model is formally introduced.

### Actual-cost evidence

`evidence_status=actual` requires a resolvable `document:<id>` that:

- belongs to the same tenant;
- belongs to the same project;
- is active;
- explicitly includes `cost_evidence` in `allowed_purposes`.

A non-empty arbitrary string is not evidence.

### Promotion invariant

An executable construction estimate requires all of:

1. owner-authorized execution;
2. an approved quantity-price mapping with server-derived `approved_by`;
3. a valid source snapshot;
4. an executable authority state (`server_verified` or permitted `human_approved`);
5. source-specific authority rules;
6. a detailed-cost role;
7. a positive monetary amount;
8. unit compatibility.

The arithmetic can be deterministic while the authority is invalid; both must pass.
