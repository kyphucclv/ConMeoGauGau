# Issue #1 secure same-origin sign-in review

Status: **implementation complete; target HTTPS observation pending**

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

## Remaining acceptance evidence

Do not close Issue #1 until the operator has captured the checks in
`docs/runbooks/issue-1-same-origin-auth.md` on the real HTTPS hostname. Local
tests prove the topology and cookie configuration, but cannot prove the TLS
gateway, redirect, or externally observed cookie behavior.
