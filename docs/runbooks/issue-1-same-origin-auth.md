# Issue #1 same-origin authentication runbook

## Runtime topology

The production browser talks to one HTTPS origin. The TLS gateway forwards
that origin to one Uvicorn worker; FastAPI serves `/api/*` and the compiled
React assets from `web/dist`. Vite and its proxy are development-only.

Required environment:

```text
APP_DATABASE_URL=postgresql://english_class_app@db-host:5432/english_class
APP_ORIGIN=https://english-class.example.internal
APP_COOKIE_SECURE=true
```

Build and start:

```powershell
Push-Location web
npm ci
npm run build
Pop-Location
python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

The gateway must preserve `Host`, terminate HTTPS, redirect HTTP to HTTPS,
and must not expose Uvicorn directly. The database URL must use the restricted
`english_class_app` role created by `database_roles.sql`, not the migration
owner. Schema migrations run separately with the migration credential.

## Verification evidence

1. `GET /api/health/live` remains 200 without querying PostgreSQL.
2. `GET /api/health/ready` returns 200 only when PostgreSQL is reachable and
   migration 020 has created `app_sessions`.
3. Browser network requests for `/`, assets, and `/api/auth/*` show the same
   HTTPS origin; the session cookie is host-only, `Secure`, `HttpOnly`,
   `SameSite=Lax`, and `Path=/`.
4. Logout immediately makes `/api/auth/me` return 401. Deactivating a user has
   the same result on their next request.
5. Run `python -m pytest tests/test_api_auth.py tests/test_sessions.py -q`,
   `npm test`, and `npm run build` before the full repository gates.

Do not claim target-topology sign-off until these checks have been captured on
the operator-supplied HTTPS hostname.
