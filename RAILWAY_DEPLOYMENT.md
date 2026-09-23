# GLIP Backend RC4 Native Auth — Railway

Recommended service name: `glip-backend`.

## Runtime
Dockerfile listens on `0.0.0.0:${PORT:-8080}`.

## Database
Use the dedicated GLIP PostgreSQL service only.

Pre-deploy:
`alembic upgrade head`

Expected head:
`0004_glip_native_auth_rc4`

Health:
- `/health/live`
- `/health/ready`

Readiness returns HTTP 503 until database, auth configuration and migration head are ready.

## Native human auth
Production target:
`GLIP_AUTH_MODE=native_session`

Required secrets:
- `GLIP_AUTH_SESSION_SECRET`
- `GLIP_AUTH_PASSWORD_PEPPER`

Use different high-entropy values. Never place either in GitHub or browser variables.

The first owner is created only with:
`scripts/bootstrap_membership.py`

There is no public self-registration and no OIDC/JWKS/client-secret human login flow.

## First deployment
Keep:
`GLIP_ORKIO_MODE=disabled`

Validate GLIP frontend + backend + PostgreSQL + native auth first.
Enable ORKIO probe/capability only in a later governed gate.

## Residual production security gates
Before broad/admin production approval:
- AO-01 must assess absence of MFA/passkeys;
- public edge/rate-limit behavior must be measured/configured;
- real PostgreSQL migration/runtime must be proven;
- rollback must be rehearsed on a disposable/staging copy.
