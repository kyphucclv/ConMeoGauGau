# FastAPI + React Migration: Phase 0 Baseline

Status: **Green; full verification battery passed**

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

### Green full-battery rerun

After an operator supplied the PostgreSQL maintenance credential in the local
PowerShell process, the verification battery was rerun from the repository root:

```powershell
python -m pytest tests/
.\scripts\run-all-gates.ps1
```

Result reported on 2026-07-15:

| Gate | Result | Duration |
|---|---|---:|
| pytest fast suite | Pass | 4s |
| Phase 13 dictionary check | Pass | 0s |
| Phase 8 automated UAT | Pass | 8s |
| Phase 9 cutover rehearsal | Pass | 71s |
| Phase 10 sign-off gate | Pass | 0s |
| Phase 11 decision gate | Pass | 0s |

Final runner result: `All gates passed.` No database credential was recorded in
the repository or this evidence file.

The full run regenerated the Phase 11 operational-issue snapshot in the working
tree. Those generated changes are intentionally not included in the migration
baseline documentation commit and require their own semantic review before any
later commit.

### Initial environment-blocked attempt

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

## Reproduction

An operator can reproduce the green baseline by configuring a maintenance URL
or process-scoped `PGPASSWORD` for disposable databases without committing the
secret, then running:

```powershell
$env:ENGLISH_CLASS_TEST_MAINTENANCE_URL = '<operator-supplied URL>'
python -m pytest tests/
.\scripts\run-all-gates.ps1
```

Expected gate: all tests and required heavyweight gates pass.

## Baseline conclusion

The Phase 0 verification prerequisite for Issue #1 is satisfied. Future
implementation still begins from a reviewed worktree: the two pre-existing
frontend changes and regenerated Phase 11 snapshot must be committed separately,
discarded by their owner, or otherwise isolated before migration code is added.
