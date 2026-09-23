# GLIP Security Baseline — RC4 Native Auth

Production human authentication target:

`GLIP_AUTH_MODE=native_session`

Controls:
- credentials and sessions belong to the GLIP database;
- password KDF: scrypt with per-credential random salt plus a server-side pepper;
- session token is high-entropy and only its HMAC digest is persisted;
- browser cookie is HttpOnly, Secure in staging/production and SameSite=Strict;
- explicit tenant is required at login;
- credential is bound to exactly one GLIP Membership;
- no account linking by email;
- no public self-registration route;
- bootstrap is CLI-only and explicitly confirmed;
- password reset is CLI-only and revokes active sessions;
- absolute and idle session expiration are enforced;
- failed login response is uniform (`invalid_credentials`);
- sanitized auth audit stores only an identity fingerprint, never password/session token;
- cookie-authenticated unsafe writes enforce an allowed Origin in staging/production;
- `dev_headers` is forbidden outside development/test.

Residual production security item:
- MFA/passkeys are not implemented in RC4. This must be assessed explicitly by AO-01 before
  a broad/admin production rollout. Do not represent MFA as present.

Tenant isolation:
- tenant identity comes from the authenticated session/membership;
- every domain operation remains tenant-scoped.

Secrets must never be committed:
- `GLIP_AUTH_SESSION_SECRET`;
- `GLIP_AUTH_PASSWORD_PEPPER`;
- database credentials;
- ORKIO M2M credentials.


## RC4.1 concurrent lockout hardening

`authenticate_native()` locks the exact `(tenant_id, email_normalized)` credential row with
`SELECT ... FOR UPDATE` and `populate_existing=True` before evaluating lock status, password
result, failed-attempt increment or successful-session transition.

This serializes competing attempts for the same existing credential on PostgreSQL and ensures a
waiter observes the state committed by the previous lock owner instead of a stale Session object.

Real multi-process PostgreSQL concurrency remains a runtime qualification gate.
