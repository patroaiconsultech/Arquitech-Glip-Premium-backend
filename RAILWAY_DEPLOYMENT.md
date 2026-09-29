# GLIP Backend F01 — Railway Deployment Contract

## Runtime

Dockerfile listens on `0.0.0.0:${PORT:-8080}`.

Use the dedicated GLIP PostgreSQL service only.

## Migration gate

Pre-deploy command:

```text
alembic upgrade head
```

Expected migration head for F01:

```text
0010_glip_project_lifecycle
```

Migration `0010_glip_project_lifecycle` is additive and creates:
- `projects.archived_at`;
- `projects.archived_by`;
- durable `project_create_idempotency` records.

Before deploy, real PostgreSQL upgrade must pass in CI/staging.
SQLite migration smoke is not sufficient production evidence.

## Health

- `/health/live`
- `/health/ready`

Readiness must return HTTP 503 until database, authentication configuration and migration head are ready.

## Native human auth

Target:

```text
GLIP_AUTH_MODE=native_session
```

Required secrets:
- `GLIP_AUTH_SESSION_SECRET`
- `GLIP_AUTH_PASSWORD_PEPPER`

Never place secrets in GitHub, frontend variables, screenshots or logs.

## Password reset safety gate

The emergency reset script is not a normal pre-deploy action.

Before any F01 backend deploy, verify that Railway does **not** retain:
- `GLIP_RESET_CONFIRM`
- `GLIP_RESET_TENANT_ID`
- `GLIP_RESET_EMAIL`
- `GLIP_RESET_PASSWORD`

and verify the pre-deploy command is **not**:

```text
python scripts/reset_native_password.py
```

Do not rotate `GLIP_AUTH_PASSWORD_PEPPER` or the session secret as part of F01.

## F01 functional smoke after deploy

Prove with an authorized tenant user:
1. create project with `Idempotency-Key`;
2. replay same request/key returns the same project;
3. reuse same key with a different payload returns conflict;
4. edit project;
5. archive project;
6. active list excludes archived project;
7. archived list includes it;
8. restore project;
9. negative cross-tenant mutation remains inaccessible;
10. `/health/ready` is healthy at migration head `0010_glip_project_lifecycle`.

## Rollback

Code rollback and migration rollback are separate gates.

A structural downgrade to:

```text
0009_glip_pricing_authority_hardening
```

drops archive metadata and durable project-create idempotency records. It does not delete project rows, but it loses F01 archive/idempotency state.

If a full rollback is required:
1. stop or drain writes;
2. export/archive F01 lifecycle metadata if preservation is required;
3. while migration `0010` is still present, run:
   `alembic downgrade 0009_glip_pricing_authority_hardening`;
4. restore the pre-F01 backend source;
5. validate readiness and auth again.

Production is not approved by this document. Human approval remains required.
