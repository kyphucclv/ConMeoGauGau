# Codebase summary

English Class Management — canonical v3. Local single-machine production:
Python 3.13 + Streamlit UI over PostgreSQL 17. HR users sign in with named
accounts; every write is one service transaction with an audit event.

## Layering (strict, enforced by the phase 7 gate)

```
streamlit_app.py            entry: auth, header, tabs
  └─ frontend_workflows/    task-area UI, NO SQL — calls services + read models
       └─ services/         one command = one transaction + audit (RBAC here)
       └─ frontend_queries.py  read models (SELECT-only, parameterized)
            └─ PostgreSQL   migrations/ 001..019: schema, triggers, views
```

- UI never embeds SQL; reads go through `frontend_queries.py`, writes through
  `services.BusinessService` (`safe_submit`/`submit_values` in
  `frontend_workflows/shared.py`).
- Roles: `admin`/`editor`/`viewer` re-checked inside every service command
  (`services/base.py:_run`), never trusted from the UI.
- Business invariants live in both the service layer and DB triggers
  (migrations 016–019): single active enrollment, immutable BU/role snapshots,
  make-up replacement credit (no denominator unit), immutable make-up links.

## Directory map

| Path | Purpose |
|---|---|
| `services/` | Business commands by concern: `base` (plumbing: CommandResult/Error, actor+RBAC, audit, advisory locks), `employee_onboarding`, `membership_transfer`, `class_schedule`, `meetings_units`, `attendance_makeup`, `evaluation_completion`, `admin_remediation`. `BusinessService` assembled in `__init__.py`. |
| `frontend_workflows/` | Streamlit task areas: `operations_entry` (dispatch), `learner_directory`, `learner_journeys` (onboard/transfer), `attendance`, `evaluation`, `monthly_review`, `data_issues`, `class_admin`, `schedule_admin`, `shared` (constants + submit helpers). Public API: `render_operations`. |
| `frontend_queries.py` | Task-oriented read models for the UI. |
| `reporting.py` | Monthly review data/summary/xlsx export + report registry. |
| `auth.py` | pbkdf2 (600k) hashing, authenticate, user admin, first-admin bootstrap. |
| `db.py` | Connection pool, fetch helpers, canonical schema verification. |
| `migrations/` + `migrate.py` | Versioned schema; checksum-guarded, idempotent. |
| `scripts/` | Staging loader, canonical ETL v3, phase gates 4–13, `run-all-gates.ps1`, `bootstrap_admin.py`. |
| `tests/` | Fast pytest suite on a disposable DB (`english_class_pytest`), migrations only, no workbook. |
| `config/phase10_remediation.json` | Checksum-bound owner-approved source overrides. |
| `docs/reviews/` | Phase evidence, specs, owner-decision snapshots. |
| `legacy/` | Archived pre-canonical prototype — do not run. |
| `backup.ps1`, `run_app.cmd/.ps1` | Verified daily backup (scheduled 12:00) and health-checked launcher. |

## Verification

- Fast: `python -m pytest tests/` (~3 s).
- Full: `.\scripts\run-all-gates.ps1` — pytest + dictionary check + phase
  8 UAT + phase 9 rehearsal + phase 10/11 owner-decision validators.
- Config: DB URLs from user-scoped `APP_DATABASE_URL` /
  `MIGRATION_DATABASE_URL` env vars (no secrets in the repo).

## Key domain rules (see TARGET_ARCHITECTURE.md for all 16)

- Attendance ratio = present applicable units / applicable non-cancelled,
  non-make-up units at/after the enrollment start session; a linked make-up
  credits the original absence without adding a denominator unit.
- Transfers close the source membership+enrollment and create linked targets
  atomically; one active enrollment per employee (DB unique constraint).
- Evaluations are immutable versions; corrections require a reason.
- Capacity overflow requires an audited HR override reason.
