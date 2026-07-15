# Issue #1 secure same-origin sign-in review

Status: **complete; target HTTPS behavior observed**

## Delivered

- Migration `020_app_sessions`; grain is one revocable authenticated browser
  session. Raw bearer tokens exist only in host-only cookies; PostgreSQL stores
  SHA-256 digests.
- Absolute 12-hour and idle 60-minute expiry, five-session cap, five-minute
  activity write throttling, logout revocation, and same-transaction revocation
  when an administrator deactivates a user.
- FastAPI liveness/readiness, same-origin login validation, one-worker login
  limiter, stable error envelope/request IDs, current-user revalidation, CSRF,
  and generic error redaction.
- React session bootstrap, protected-content holdback, login, refresh
  revalidation, and CSRF-protected logout. FastAPI serves the production build
  from the same origin.

## Migration evidence

- Pre-change head captured: `019_phase13_makeup_link_immutability` (19 rows).
- Pre-020 custom backup: `backups/pre-issue1-020-20260715-133619.dump`,
  2,570,150 bytes.
- Migration was applied by `english_class_migration`, not the superuser.
- Post-change head: `020_app_sessions`; initial session row count: zero.
- Phase 9 verified restricted roles, Streamlit smoke, and backup/restore with 20
  migrations.

## Verification

- Python: 26 tests passed.
- React: 2 tests passed; production TypeScript/Vite build passed.
- Phase 13 dictionary: 21 tables, baseline `020_app_sessions`.
- Phase 8 automated UAT, Phase 9 cutover rehearsal, Phase 10 sign-off, and
  Phase 11 decision gate all passed.
- `npm audit`: zero known vulnerabilities at install time.

The Python suite emits one upstream Starlette deprecation warning about its
TestClient HTTP transport; it does not affect runtime behavior and should be
removed when FastAPI's supported test transport changes.

## Target HTTPS evidence

The operator verified `https://english-class.example.internal` in Chrome:

- successful sign-in rendered protected content only after authentication;
- refresh revalidated and retained the server-side session;
- sign-out returned to the login shell, and the database recorded
  `revocation_reason=logout`;
- the browser cookie was `HttpOnly`, `Secure`, `SameSite=Lax`, and `Path=/`;
- the application does not set a `Domain` attribute, so the cookie is
  host-only.

The evidence screenshot accidentally displayed the raw cookie value. The
operator response revoked every active session for `hr-admin`, recorded
`app_session.revoke_exposed`, and verified zero active sessions. The exposed
token is therefore no longer usable; the account password was not exposed.
