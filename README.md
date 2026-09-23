# GLIP Platform Backend RC4 — Native Auth Production Candidate

Domínio GLIP independente com Client, Project, Stage, Provider, Task, Milestone, Document, Project Context v2, três capabilities iniciais, Draft Store e Approval Center.

## Invariantes
- tenant vem do principal autenticado;
- membership local é obrigatório;
- `project_id` é autorizado no GLIP, não inflado no runtime ORKIO;
- `draft_message` sempre retorna `external_write_allowed=false`;
- editar cria nova versão e invalida aprovações abertas;
- aprovação é vinculada ao SHA-256 exato;
- não existe rota `/send` ou `/publish`.

## Local
```bash
cp .env.example .env
docker compose up -d db
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
alembic upgrade head
python scripts/bootstrap_dev.py --apply
uvicorn glip.main:app --reload --port 8081
```

Headers dev: `X-GLIP-Tenant-ID: tenant-demo`, `X-GLIP-User-ID: user-demo`.
Produção deve usar `GLIP_AUTH_MODE=native_session`.


## V5 additions
Knowledge/Memory Plane, ApprovedVersion, MemoryCandidate, ScheduleItem, BudgetSnapshot, ExternalDelivery placeholder, OutboxEvent, audit events and resilient ORKIO adapter.


## RC2 premium hardening

This offline candidate closes AO-01 findings around HTTP retry classification,
concurrent durable idempotency, processing ownership/lease and release provenance.

The GLIP backend remains an independent domain backend. Efatà/ORKIO is consumed only
through the versioned `src/glip/integrations/orkio` adapter.

RC2 does **not** prove real Efatà M2M, Railway networking, real PostgreSQL runtime,
staging or production.


## RC4 native authentication

Human login is GLIP-native. OIDC/JWKS/account-linking are not part of this candidate.

```text
tenant + email + password
→ GLIP backend
→ scrypt(salt + server pepper)
→ exact local membership
→ server-side revocable session
→ HttpOnly/Secure/SameSite=Strict cookie
```

There is no public registration endpoint. The first owner is created with
`scripts/bootstrap_membership.py`; controlled password reset uses
`scripts/reset_native_password.py`.

MFA/passkeys remain a declared residual security item for AO-01 review.
