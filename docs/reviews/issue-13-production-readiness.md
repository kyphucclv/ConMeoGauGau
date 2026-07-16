# Issue 13 production readiness evidence

Date: 2026-07-16
Status: **changes required — LAN DNS/client trust, HR UAT and stabilization are pending**

Owner-approved production hostname: `english-class.cyberlogitec.local`.
Authorization to configure the HTTPS gateway and Windows service on the
designated host was provided on 2026-07-16. Host service/TLS proof is complete;
LAN DNS and HR-workstation trust remain pending.

## Change identity

- Task/phase: Issue #13, production readiness and React ownership cutover
- Developer: Codex
- Files changed: HTTP boundary/observability, bounded pool, dashboard read,
  production launcher/config/probe, load/accessibility/security tests, runbook
  and parity evidence
- Data entities affected: no schema or production-row mutation; disposable tests
  exercise `app_sessions`, `data_quality_issues` and `audit_events`

## Contract review

- [x] Relevant `DATA_DICTIONARY.md`, `TARGET_ARCHITECTURE.md`,
  `PROJECT_RULES.md` and deployment/session decisions were re-read.
- [x] Canonical entity grains, service transaction ownership, audit attribution
  and no-silent-data-loss rules are unchanged.

Row grain:

```text
One structured access event represents exactly one completed or failed HTTP
request at the route boundary. One load-test quality issue represents exactly
one durable issue resolved at most once by its named authenticated actor.
```

No derived business field became writable. The dashboard optimization reuses
the already-read application snapshot to construct the HR summary and does not
change metric definitions, filters or grain.

## Implemented readiness controls

- Loopback-only one-worker launcher with a fail-closed HTTPS/config/schema/role/
  connection-budget preflight.
- Bounded 1-5 connection pool that waits for short bursts, times out safely and
  returns every connection after success or rollback. Pool timeout has a stable
  sanitized HTTP 503 response.
- Allow-listed JSON access events with bounded request IDs and no query string,
  body, cookie, CSRF token, password, connection string or SQL values.
- Same-origin login, no CORS middleware, CSRF on authenticated unsafe methods,
  secure/HttpOnly/SameSite cookies, private no-store API responses, CSP,
  clickjacking/MIME/referrer/permissions headers and HSTS in secure mode.
- Production build metadata and keyboard-focusable scroll tables; automated axe
  WCAG A/AA coverage for sign-in, every admin workspace and viewer reports.
- Routing-only Streamlit fallback and explicit prohibition of dual-write,
  reverse migration or database restore for frontend rollback.

## Test evidence to date

```text
python -m pytest tests/test_api_auth.py -q
6 passed

python -m pytest tests/test_api_production_load.py -q -s
20-session burst: all flows succeeded, no pool exhaustion
latest 10-session measured: read p95 716.80 ms; command p95 602.51 ms
30 durable issues resolved; audit counts exactly 20 burst + 10 measured
all five pool connections reacquired after load and exception rollback

npx playwright test e2e/accessibility.spec.ts
2 passed (44.4 s)

.\scripts\run-all-gates.ps1
96 Python tests, OpenAPI drift check, 13 React tests, production build,
npm audit (0 vulnerabilities), schema dictionary 020, 6 Playwright journeys,
Phase 8 automated UAT, Phase 9 backup/restore cutover rehearsal, and Phase
10/11 decision gates all passed

.\run_react_app.ps1 -CheckOnly
restricted role/schema/build/one-worker/1-5 pool preflight passed; port 8000 free
(configuration-only probe with an example HTTPS origin, not TLS evidence)
```

The Phase 9 candidate has zero open `data_quality_issues`. Its 255 derived
operational conditions (including 173 high-priority legacy conditions) match the
checksum-bound Phase 11 snapshot and all have recorded owner decisions; they
are not unreviewed software defects. Any new high/critical product defect or
unexplained condition still blocks React cutover.

The first 20-session run exposed immediate `ThreadedConnectionPool` exhaustion.
After making acquisition bounded/blocking, the first measured read remained over
target because the dashboard performed the same six metrics twice. Reusing the
single snapshot removed that duplicate work and the representative 10-session
test passed both thresholds. These failures were fixed rather than waived.

## Target-host deployment evidence

The initial read-only inspection on 2026-07-16 found only PostgreSQL 17. The
approved deployment then installed Caddy 2.11.4 and WinSW 2.12 and produced this
sanitized evidence on the merged release:

- `EnglishClassReact` and `EnglishClassCaddy` are Running/Automatic and both
  recover through an explicit restart.
- Caddy listens on 80/443; FastAPI listens only on `127.0.0.1:8000` with one
  worker. Firewall allows 80/443 only from `10.0.50.0/24` and explicitly blocks
  inbound 8000/8501/5432.
- Full `issue13_host_check.py` passed against
  `https://english-class.cyberlogitec.local`: trusted TLS, live/ready 200,
  restricted `english_class_app`, schema `020_app_sessions`, static build and a
  1-5 pool with 90 connections available before app start.
- The response has HSTS, CSP, private/no-store and a request ID. HTTP redirects
  to HTTPS with status 308.
- Logs contain 21 structured access events, no connection URL or assigned
  password/CSRF/session-cookie/database-URL value, and use 10 MiB/14-file WinSW
  rotation for app and gateway output.
- `EnglishClassDbBackup` runs daily at 12:00 as SYSTEM with catch-up enabled. A
  forced run returned zero and created verified dump
  `english_class_20260716_132423.dump` (2,575,806 bytes); Phase 9 proves restore.
- The internal root is trusted on the server and exported with its elevated
  installer to `C:\Users\Public\Documents\EnglishClass` for HR clients.
- `10.0.50.119` is currently DHCP-assigned. A DHCP reservation for Wi-Fi MAC
  `00-93-37-64-12-F7` is required before LAN DNS/UAT approval.

The approved Caddy internal-CA design uses automatically renewed short-lived
certificates. The host checker therefore uses a one-hour emergency floor rather
than a 30-day public-certificate window; trust-root distribution and renewal
rehearsal remain separate mandatory evidence.

## Reconciliation

| Dataset | Expected | Observed | Difference |
|---|---:|---:|---:|
| Load issues resolved | 30 | 30 | 0 |
| `quality_issue.resolve` burst audits | 20 | 20 | 0 |
| `quality_issue.resolve` measured audits | 10 | 10 | 0 |
| Pool connections recoverable after test | 5 | 5 | 0 |

Production report/audit/key-count reconciliation remains pending and must be
captured immediately before and after traffic cutover. Disposable load rows are
never written to production.

## Final review

- [x] Complete tracked and untracked diff reviewed; generated OpenAPI remained
  unchanged.
- [x] Null/duplicate/invalid input, authorization, session, CSRF, CORS, safe
  exception, rollback and connection-return paths are covered by the full suite.
- [x] No migration, startup DDL, data rewrite, dual-write path, debug credential
  or unsafe admin bypass was added.
- [x] Backup/restore rehearsal inspected 365 employees, 20 migrations, 552 run
  enrollments, 6,281 attendance rows and zero open quality issues.
- [x] Reviewed again on the deployed release after host configuration and
  forced service restart/backup.
- [ ] Review again after named HR UAT and stabilization.

Potentially destructive behavior reviewed: the approved host installer creates
two Windows services, three scoped firewall rules, one hosts entry, one trusted
internal CA root and one scheduled backup task. It does not change schema or
production rows. All load writes target disposable `english_class_pytest`.

## Remaining acceptance evidence

- [x] Approved hostname: `english-class.cyberlogitec.local`
- [x] Gateway/service manager, service identities and host firewall proof
- [ ] DHCP reservation, LAN DNS record and HR-workstation connectivity proof
- [ ] HR-browser root trust distribution and observed short-lived leaf renewal
- [x] Protected secret injection, restart recovery, log rotation/retention/ACL
- [x] Current backup task and disposable restore proof
- [x] Full repository regression, disposable parity/load and backup/restore
  rehearsal on the release candidate
- [x] Target-host HTTPS/restart evidence on the deployed release commit
- [ ] HR-workstation LAN and representative production-session evidence
- [ ] Named HR UAT for every parity workflow
- [ ] Stabilization completed with no high/critical defect or unexplained report,
  audit or key-count mismatch
- [ ] Explicit owner approval of React as canonical frontend; Streamlit retained
  as fallback until separate Issue 14 retirement approval

## Reviewer decision

- [ ] Approved
- [x] Changes required

Do not close Issue 13 or start Issue 14 from this repository evidence alone.
