# Phase 6 security and application architecture review

## Change identity

- Task/phase: Phase 6 - Security and application architecture
- Developer: Codex
- Date: 2026-07-13
- Files changed: `app.py`, `streamlit_app.py`, `db.py`, `auth.py`, `reporting.py`, `database_roles.sql`, `scripts/phase6_security_check.py`
- Data entities affected: app users, audit events, canonical reporting views, PostgreSQL roles and grants

## Contract review

The runtime app is now split into small modules:

- `streamlit_app.py` contains Streamlit UI only;
- `db.py` owns connection pooling, timeouts, and canonical schema verification;
- `auth.py` owns password hashing, login, bootstrap admin, and admin-only user management;
- `reporting.py` exposes a whitelist of canonical report queries;
- `services.py` remains the business-command service layer.

The app no longer renders a connection-string input, raw SQL text, or raw
tracebacks.  Runtime credentials come only from `DATABASE_URL` or
`st.secrets["database"]["url"]`; `.streamlit/secrets.toml` is already ignored
by git.  The app uses canonical Phase 5 reporting views and no longer executes
legacy `students`, `attendance_log`, `enrollments`, `class_sessions`, or
`audit_log` SQL.

Sensitive app-user changes write `audit_events` in the same transaction as the
user mutation.  Viewer/editor mutation restrictions are enforced in the service
layer and user-admin service.

## Implemented security surface

- Restricted role provisioning script in `database_roles.sql`; migration,
  app, and readonly roles are separate login roles.
- Canonical relations are owned by the migration role so future schema changes
  do not require the PostgreSQL superuser.
- App/read-only roles receive no schema `CREATE` privilege.
- Read-only role receives `SELECT` only.
- App role receives DML privileges for runtime operations, but schema DDL is
  denied by PostgreSQL ownership/privilege checks.
- Streamlit app uses a bounded connection pool with statement and idle
  transaction timeouts.
- Reporting access is query-whitelisted via `reporting.py`.
- User management is admin-only through `UserAdminService`.

## Test evidence

Commands executed:

```text
python -m py_compile db.py auth.py reporting.py services.py streamlit_app.py app.py scripts\phase6_security_check.py scripts\phase5_reporting_check.py scripts\phase4_integration_check.py
git diff --check
python scripts\phase6_security_check.py
python scripts\phase4_integration_check.py
python scripts\phase5_reporting_check.py
```

Latest Phase 6 integration output:

```text
Applying: 001_canonical_schema_v3.sql
Applying: 002_raw_staging_and_profile.sql
Applying: 003_etl_source_row_outcomes.sql
Applying: 004_canonical_etl_batches.sql
Applying: 005_phase4_completion.sql
Applying: 006_reporting_views.sql
Database migrations are up to date.
Phase 6 security gate passed.
app_role_ddl_denied: True
readonly_insert_denied: True
viewer_service_mutation_denied: True
editor_user_admin_denied: True
editor_eligibility_override_denied: True
admin_user_created: 4
```

Phase 4 and Phase 5 gates were rerun after the architecture changes and still
passed.

## Permission traces

- App database role attempted `CREATE TABLE`, `ALTER TABLE employees`, and
  `DROP TABLE employees`; PostgreSQL denied each operation.
- Read-only database role attempted an `INSERT` into `app_users`; PostgreSQL
  denied the write while allowing `SELECT` from reporting views.
- Viewer app user attempted a direct service mutation; `BusinessService`
  returned `forbidden`.
- Editor app user attempted user creation and eligibility override;
  `UserAdminService` and `BusinessService` returned `forbidden`.
- Admin app user created a viewer account; one matching `audit_events` row was
  written.

## Residual risks / deferred work

- Full CRUD workflows remain deferred to Phase 7 and should call service-layer
  commands rather than ad hoc SQL.
- Database role script uses psql variables for passwords; operators must supply
  secrets outside source control.
- Fine-grained PostgreSQL row-level security is not implemented; application
  authorization remains service-layer based for Phase 6.

Reviewer decision: Approved for Phase 7 planning/implementation.
