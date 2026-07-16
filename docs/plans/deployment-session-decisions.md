# FastAPI + React Deployment And Session Decisions

Status: **target-host service/TLS contract validated; LAN DNS/client trust, HR
UAT and stabilization remain pending**

These decisions define the deployment and security contract. The concrete TLS
gateway product remains replaceable; it must prove this contract on the actual
Windows/LAN host before production use.

## Deployment decisions

| Topic | Decision |
|---|---|
| Runtime host | Start on the current designated Windows internal application host; do not introduce cloud hosting in this migration. |
| User access | LAN users access one approved internal HTTPS hostname. Direct access to FastAPI, Vite, PostgreSQL, or Streamlit ports is not the production user path. |
| Origin | React static files and `/api/*` share one origin. Production CORS is disabled by default. |
| TLS | HTTPS is mandatory for LAN login. Certificate trust, installation, and renewal belong in the runbook and cutover rehearsal. |
| Frontend serving | Deploy a versioned Vite production build. The Vite development server is local-development-only. |
| FastAPI execution | Keep synchronous psycopg2 and use FastAPI `def` handlers. Do not perform blocking database/password work directly in `async def` handlers. |
| Initial process model | One FastAPI worker for the first production slice; increase only after connection-budget and load evidence. |
| Database pool | Retain a bounded 1-5 connection pool initially. Worker count multiplied by pool maximum must remain inside the PostgreSQL budget. |
| Secrets | Database URLs and session/security secrets use protected host environment/configuration, never repository files or frontend environment variables embedded at build time. |
| Network exposure | Bind only to the intended host interface; restrict backend/database ports with the host firewall. |
| Logs | Structured application logs include request ID, route, status, duration, and safe actor/session identifiers; never passwords, cookies, CSRF tokens, SQL text with user values, or connection strings. |
| Backup | Existing PostgreSQL backup/restore remains authoritative; frontend rollback normally does not restore data. |
| Fallback | Keep a tagged, schema-compatible Streamlit release and switch user routing back without dual-write or reverse migration. |

## Initial service targets

These are initial acceptance thresholds, not permanent capacity promises:

- Support 10 simultaneously active HR browser sessions on the target LAN host.
- No pool exhaustion or leaked connection during a 20-session test scenario.
- p95 non-export read response below 1 second on the representative local DB.
- p95 normal command response below 2 seconds, excluding user confirmation and
  intentionally expensive file exports.
- Authentication/session failure rate is zero in the scripted normal-flow test.
- Any threshold change must be recorded with the measured target-host evidence.

Server-paginated endpoints default to 50 rows and cap at 100. Attendance roster
is deliberately unpaginated because saving the complete applicable roster is one
atomic business event.

## Session decisions

| Topic | Decision |
|---|---|
| Session form | Opaque random bearer token in the browser; only a SHA-256 token hash is stored in PostgreSQL. |
| Entropy | Generate at least 256 bits using the operating system CSPRNG. |
| Durable record | One `app_sessions` row represents one revocable browser session. This requires an infrastructure migration with normal verification/restore evidence. |
| Cookie | `HttpOnly`, `Secure` in production, `SameSite=Lax`, host-only where possible, path `/`, explicit maximum age. |
| Absolute lifetime | 12 hours from login. |
| Idle lifetime | 60 minutes. |
| Activity writes | Refresh `last_seen_at` no more often than every 5 minutes to avoid a write on every request. |
| Multiple sessions | Allow at most 5 active sessions per user; successful login revokes the oldest session above the limit. |
| Login rotation | Always create a fresh token after successful authentication; never promote an anonymous identifier. |
| Logout | Revoke the current server-side row before expiring the cookie. |
| User deactivation | Revalidation of `app_users.is_active` rejects the next request; deactivation also revokes all active sessions in the same admin transaction when that command is introduced. |
| Password/security change | Revoke all existing sessions after an approved password reset/change. Current password-management expansion remains out of parity scope. |
| Expired records | Ignore immediately; purge records older than the retention period through an explicit maintenance command, not startup DDL. |

## CSRF and origin decisions

- Every authenticated unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) requires
  an `X-CSRF-Token` that matches the secret associated with the server-side
  session.
- React may hold the CSRF value in memory and recover it from `/api/auth/me` after
  refresh; it is not stored in local storage.
- The login endpoint validates `Origin`/`Referer` against the configured same
  origin and is rate-limited even though no authenticated CSRF session exists.
- Development allows only the exact Vite origin with credentials.
- Production does not accept wildcard origins.

## Authentication throttling

The first deployment uses one FastAPI worker, so a bounded in-process limiter is
acceptable for the initial internal slice:

- key by normalized username plus source address;
- do not reveal whether the username exists;
- return one generic retry response;
- log only safe aggregate failure information.

Before increasing worker count or exposing the application beyond the approved
LAN, replace this with a shared limiter or an approved gateway control.

## Remaining host validation

The target host now proves the Caddy/WinSW service topology, loopback backend,
restricted database role and budget, protected secrets, rotated service logs,
firewall rules, trusted server TLS, restart recovery and scheduled backup. Issue
#13 cannot claim final production readiness until it also proves:

- approved hostname resolution from HR workstations;
- Caddy internal root distribution to HR browsers and observed leaf renewal;
- named HR UAT for every parity workflow;
- stabilization without a high/critical defect or unexplained count mismatch;
- Streamlit routing fallback rehearsal from a client workstation.
