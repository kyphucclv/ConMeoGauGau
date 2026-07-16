# Issue 13 React production cutover runbook

Status: **target host configured; LAN DNS/trust distribution, HR UAT and stabilization pending**

This runbook moves user traffic from Streamlit to the same-origin React/FastAPI
application without changing the canonical database. Streamlit remains the
schema-compatible fallback throughout stabilization. Rollback changes routing
only: do not dual-write, reverse migrations, or restore the database for a
frontend rollback.

## Owner decisions required before cutover

Record each decision in `docs/reviews/issue-13-production-readiness.md`.

| Decision | Required evidence | Current state |
|---|---|---|
| Approved internal hostname | DNS resolution from an HR workstation | Owner-approved: `english-class.cyberlogitec.local`; server hosts entry complete, LAN DNS proof pending |
| HTTPS gateway and Windows service manager | Product/version, service names, service identities, startup mode | Caddy 2.11.4 + WinSW 2.12; `EnglishClassCaddy` LocalService and `EnglishClassReact` LocalSystem, automatic delayed start |
| Certificate issuer and renewal owner | Trusted chain, expiry, renewal command/task and alert owner | Caddy internal CA with short-lived automatic leaf renewal; server trust complete, HR client distribution/renewal observation pending |
| Firewall owner | Inbound HTTPS allowed from approved LAN; ports 8000, 8501 and 5432 not exposed to users | Rules active for `10.0.50.0/24`; backend ports explicitly blocked |
| Secret owner | Protected service-account environment for `APP_DATABASE_URL`, `APP_ORIGIN`, `APP_COOKIE_SECURE=true` | Protected under `C:\ProgramData\EnglishClass`; SYSTEM/Administrators only |
| Log owner | Gateway/app log paths, ACLs, rotation size/age and retention | WinSW logs under `C:\ProgramData\EnglishClass\logs`; 10 MiB, 14-file rotation |
| Backup owner | Daily task identity, destination, retention and latest restore proof | `EnglishClassDbBackup` runs daily at 12:00 as SYSTEM; current verified dump and Phase 9 restore proof complete |
| HR UAT and cutover owner | Named approvers and signed workflow matrix | Pending |
| Stabilization window | Start/end, support contact and rollback authority | Pending |

Do not replace pending values with examples. The approved hostname must also be
the exact `APP_ORIGIN` and certificate name.

## Build and fail-closed preflight

Run from the versioned release checkout as the intended service identity:

```powershell
npm --prefix web ci
npm --prefix web run build
.\run_react_app.ps1 -CheckOnly
```

The launcher accepts exactly one worker, binds FastAPI to loopback, checks the
restricted application role, schema `020_app_sessions`, static build and the
PostgreSQL connection budget. It must fail if `APP_ORIGIN` is not HTTPS or
`APP_COOKIE_SECURE` is not `true`.

Never place a database URL in the repository, frontend build variables, service
command line, logs or evidence files. Inject it through the approved protected
service-account configuration and restrict read access to that identity and the
operator group.

## Service and gateway contract

The installed Windows service configuration has these fixed properties:

- working directory is the versioned release directory;
- command is `powershell -NoProfile -ExecutionPolicy Bypass -File run_react_app.ps1`;
- startup is automatic, recovery restarts are bounded, and only the named
  service identity can read secrets;
- FastAPI listens only on `127.0.0.1:8000`, uses one worker and the 1-5 blocking
  pool;
- stdout/stderr use `config/uvicorn-logging.json`; the service manager rotates
  logs according to the approved size, age and retention decision;
- the HTTPS gateway serves `APP_ORIGIN`, proxies all paths to
  `127.0.0.1:8000`, preserves the host, and supplies forwarded headers only
  from loopback;
- gateway request/body/time limits are documented, and health endpoints remain
  available at `/api/health/live` and `/api/health/ready`.

To prove restart rather than only initial launch:

```powershell
Restart-Service -Name EnglishClassReact
Restart-Service -Name EnglishClassCaddy
Get-Service -Name EnglishClassReact,EnglishClassCaddy
python scripts\issue13_host_check.py
```

The final host check must not use `--skip-origin-probe`. It verifies trusted TLS,
at least one certificate hour remaining, both health endpoints, the restricted
database role, schema head and connection budget without printing secrets.
The one-hour emergency window stays below Caddy's default renewal window for its
12-hour internal certificates; renewal and root distribution still require
explicit evidence.

The client trust bundle is at
`C:\Users\Public\Documents\EnglishClass`. After the network administrator adds
`english-class.cyberlogitec.local -> 10.0.50.119` to LAN DNS, each HR workstation
must receive `english-class-root.crt` through the approved trust policy (or run
the included elevated `install-root-ca.ps1`) before browser UAT.
The server address is currently DHCP-assigned; reserve `10.0.50.119` for Wi-Fi
MAC `00-93-37-64-12-F7` before relying on the DNS record.

## Firewall, certificate, logs and backup evidence

Capture sanitized command output showing:

1. the approved LAN clients can reach only the HTTPS gateway;
2. user workstations cannot reach FastAPI 8000, Streamlit 8501 or PostgreSQL
   5432;
3. the certificate chain is browser-trusted and its renewal rehearsal leaves at
   least one hour on the newly issued short-lived certificate;
4. an app restart preserves readiness and a gateway restart restores routing;
5. access logs contain request ID, route template, status, duration and safe
   actor ID, but no query, body, password, cookie, CSRF token, SQL value or URL;
6. forced rotation preserves the configured retention and ACLs;
7. `.\backup.ps1` creates a current dump and the Phase 9 restore rehearsal
   succeeds on a disposable database.

PostgreSQL budget acceptance is:

```text
workers * pool_max <= max_connections - superuser_reserved_connections - current_connections
1 * 5 <= available connections before app start
```

Increasing workers requires a new measured budget and shared login throttling.

## Pre-cutover verification

```powershell
.\scripts\run-all-gates.ps1
python scripts\issue13_host_check.py
python scripts\phase9_cutover_rehearsal.py
python scripts\phase10_quality_signoff.py --validate-decisions
python scripts\phase11_operational_issue_snapshot.py --validate-decisions
```

Stop if any gate fails, a high/critical defect is open, or reports, audit events
or key counts have an unexplained mismatch. Run HR UAT for sign-in/session,
learner profile/start/transfer, attendance and make-up, final results, monthly
review/export, follow-ups/remediation, classes/schedule, reports and restricted
audit. Record actor, time, result and issue reference for every row in the parity
matrix.

## Traffic cutover

1. Confirm a fresh verified backup and keep both frontends on the same canonical
   schema and service layer.
2. Start/restart the React/FastAPI service and HTTPS gateway.
3. Run the full host check and a named-user smoke test.
4. Change only the approved user-facing route/bookmark to React.
5. Record baseline counts for employees, run enrollments, attendance, open
   quality issues and audit events; compare them after smoke/UAT.
6. Announce the stabilization window. Do not retire or mutate Streamlit.

## Stabilization and routing rollback

Monitor health, HTTP 5xx/503 rate, authentication/session failures, p95 read and
command latency, pool wait/timeouts, disk/log growth, report counts, audit actor
attribution and open high/critical issues. Initial thresholds remain: 10 active
HR sessions, read p95 below 1 second, command p95 below 2 seconds, zero normal
auth/session failures, no pool exhaustion/leak in the 20-session scenario and no
unexplained report/audit/count mismatch.

Rollback immediately on a sustained readiness failure, unsafe data behavior,
unattributed mutation, unexplained mismatch, high/critical defect, repeated
session failure or threshold breach accepted by the rollback owner:

1. route the approved hostname/bookmark back to the tagged Streamlit release;
2. leave the canonical database and migrations unchanged;
3. stop user traffic to React while retaining sanitized logs/evidence;
4. run Streamlit health/smoke and reconciliation checks;
5. open an incident and obtain a new cutover approval after correction.

Database restore is reserved for a separately proven database incident, not UI
rollback. Streamlit retirement (Issue 14) requires completed stabilization and
an explicit owner approval recorded after Issue 13.
