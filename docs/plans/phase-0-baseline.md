# FastAPI + React Migration: Phase 0 Baseline

Status: **Environment-blocked; code baseline not yet green**

Captured: 2026-07-15 (Asia/Bangkok)

## Source revision

- Commit: `baf18755cd27396030c340d67f0b22b622c7822b`
- Subject: `feat(ui): plain-language relabel and simpler navigation for HR users`
- Two pre-existing, unstaged user changes were present and excluded from the
  migration documentation commit:
  - `frontend_workflows/learner_directory.py`
  - `frontend_workflows/operations_entry.py`

## Toolchain

| Tool | Observed version |
|---|---|
| Python | 3.13.13 |
| Streamlit | 1.59.2 |
| psycopg2 | 2.9.12 |
| openpyxl | 3.1.5 |
| Node.js | 24.17.0 |
| npm | 11.17.0 |
| PostgreSQL client | `psql` not available on `PATH` |

The PostgreSQL server version could not be queried because no maintenance or
application database URL was configured in the current process/user environment.

## Verification results

### Fast pytest suite

Command:

```powershell
python -m pytest tests/
```

Result: **environment error** in 1.36 seconds.

- 20 tests collected.
- 3 password-hashing tests passed.
- 17 database-backed tests stopped during session fixture setup.
- Root cause: `postgresql://postgres@localhost:5432/postgres` required a
  password, but `PGPASSWORD` and `ENGLISH_CLASS_TEST_MAINTENANCE_URL` were not
  configured.
- No business assertion failed; the disposable test database was never created.

### Safe gate subset

Command:

```powershell
.\scripts\run-all-gates.ps1 -SkipHeavy
```

Result:

| Gate | Result | Evidence |
|---|---|---|
| pytest fast suite | Environment-blocked | Same missing PostgreSQL maintenance credential |
| Phase 13 dictionary check | Pass | 20 tables, 10 legacy aliases, schema baseline `019_phase13_makeup_link_immutability` |

The heavyweight Phase 8-11 gates were not run because they require the same
missing database credentials. This avoids misrepresenting an environment
failure as a code regression and avoids any accidental production connection.

## Required rerun

Before Phase 1 implementation begins, an operator must configure a maintenance
URL for disposable databases without committing the secret, then rerun:

```powershell
$env:ENGLISH_CLASS_TEST_MAINTENANCE_URL = '<operator-supplied URL>'
python -m pytest tests/
.\scripts\run-all-gates.ps1
```

Expected gate: all tests and required heavyweight gates pass. Record the new
result here or in a dated successor baseline before changing dependencies,
migrations, services, or runtime entrypoints.

## Baseline conclusion

Documentation and contract work may continue. Phase 1 code and the
`app_sessions` migration must not begin until the database-backed baseline is
green or an owner explicitly accepts a documented pre-existing failure.
