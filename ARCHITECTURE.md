# GLIP Platform Backend v0.6 — Standalone Architecture

GLIP is an independent product and system of record for architecture/project operations.

```text
GLIP Frontend
    ↓
GLIP Backend
    ↓
GLIP PostgreSQL
    │
    └── ORKIO Integration Adapter → Efatà/ORKIO (optional intelligence)
```

## Boundaries
- GLIP has its own frontend, backend, database, migrations and deploy lifecycle.
- Efatà/ORKIO never reads or writes the GLIP database directly.
- GLIP never reads or writes the Efatà database directly.
- The browser never carries an M2M secret and never calls Efatà directly.
- Realtime, voice and avatar are optional external capabilities and do not block core GLIP readiness.

## Core domains
Projects, clients, providers, stages, tasks, milestones, schedule, budget, documents,
decisions, media/3D/BIM assets, communications, approvals, memory and audit/outbox.

## Auth
`native_session` is the production human-auth target.
Credentials, tenant membership and revocable sessions are GLIP-owned.
Login requires an explicit tenant + email + password. There is no OIDC account linking,
no public self-registration and no silent auto-provision.

## ORKIO modes
- `disabled`: zero ORKIO network requirement.
- `probe`: health/readiness/governance only; no GLIP project/client/document data.
- `capability_v1`: fail-closed and requires an explicit server-side M2M token + versioned execute path.
- `mock`: development/test only.

## External capability status
Realtime / voice / avatar may be `disabled`, `pending_external` or `enabled`.
`pending_external` is the expected state while the Efatà/Fatar implementation is being stabilized.

## Database baseline v0.8
Before the first official GLIP database deployment, development migration shortcuts were collapsed into a single explicit Alembic baseline: `0001_glip_baseline_v08`. ORM metadata is separated from engine creation so Alembic offline checks require no database connection.

## v0.9 staging hardening
Staging/production require PostgreSQL. Staging/production also require the readiness migration-head gate. Production CORS rejects HTTP/localhost. Optional Efatà capabilities remain outside core readiness.


## v1.0 RC1 — canonical ORKIO boundary

GLIP domain requests are never sent directly to Efatà/ORKIO.

```text
GLIP domain request
→ ORKIO Integration Adapter
→ ORKIO-CAPABILITY-REQUEST-1
→ Efatà/ORKIO
→ ORKIO-RESPONSE-1
→ strict adapter validation
→ GLIP domain response
```

The adapter sends a minimum context: tenant/org id, project id, actor id, context version,
purpose and explicitly authorized source refs. Client names, storage refs, document content and
the full internal ProjectContext are not exported implicitly.

`integration_executions` is GLIP-owned durable state for idempotency, canonical request identity,
upstream response evidence and domain replay. No Efatà table is accessed directly.


## RC2 premium integration state machine

```text
contextualized
→ calling (owner_token + bounded lease)
→ completed
  or
→ failed
```

A unique idempotency key elects the durable winner. A concurrent loser rolls back its
local transaction, rereads the winner and never masks unrelated `IntegrityError`.
Only one live lease owner may call ORKIO. An expired lease can be taken over; the old
owner cannot finalize after ownership loss.

HTTP retry classification is explicit and fail-closed:

- `401/403` → `AUTH_TERMINAL`
- `400/404/409/410/412/415/422` → `CONTRACT_TERMINAL`
- `408/429/502/503/504` → `RETRYABLE_TRANSIENT`
- every other HTTP error → `UPSTREAM_TERMINAL`

New/unknown statuses therefore do not silently become retryable.


## RC2.1 atomic finalization

RC2.1 removes the `SELECT owner → later commit` TOCTOU window.
Success and failure finalization use a single conditional SQL `UPDATE` with:

- execution id;
- tenant id;
- `status = calling`;
- exact `owner_token`;
- non-null lease;
- `lease_expires_at > database now()`.

A stale or expired owner gets rowcount 0 and the whole local transaction is rolled
back, including any pending Draft/DraftVersion mutations. The database clock is the
authority for lease validity.


## RC4 native authentication boundary

```text
Browser
→ same-origin GLIP frontend
→ POST /api/v1/auth/login
→ GLIP native credential
→ exact tenant Membership
→ server-side session
→ HttpOnly cookie
```

The password pepper and session secret exist only in backend secret management.
The browser never stores access/refresh/M2M tokens.
