# Phase 0 baseline and migration-state audit

## Change identity

- Task/phase: Phase 0 - Baseline and migration-state audit
- Developer: Codex
- Date: 2026-07-13
- Files changed: `docs/reviews/phase-0-baseline.md`
- Data entities affected: None; read-only audit only

## Contract review

- [x] Read `DATA_DICTIONARY.md`, `TARGET_ARCHITECTURE.md`, `PROJECT_RULES.md`, and `IMPLEMENTATION_PLAN.md`.
- [x] No database mutation was attempted.

Row grain:

```text
One baseline record represents exactly one inspected repository artifact,
source workbook sheet, runtime capability, or database-audit result.
```

Invariants affected:

- None. Phase 0 is an evidence-gathering phase.

## Repository baseline

- Working directory: `C:\Users\lnkph\OneDrive\Documents\english_class_postgres_package`
- Git status: initialized on branch `master`; no commits yet.
- All project files are currently untracked pending the first baseline commit.
- Existing files were not reverted or overwritten.
- `DRAFT_MIGRATIONS.lock` is present; draft migrations remain locked.

### Runtime/tool availability

- Python: `3.14.6` (64-bit Windows 11)
- Streamlit CLI: unavailable on PATH; the installed Python package was discovered by the Streamlit skill.
- PostgreSQL 18 Windows service `postgresql-x64-18`: running. Client tools are installed under `C:\Program Files\PostgreSQL\18\bin`.
- User environment now contains `DATABASE_URL=postgresql://postgres@localhost:5432/english_class`; the running Codex process still required explicit in-process assignment because it was started before the environment change.
- Password authentication succeeds through the local libpq password file.

### SHA-256 checksums

| Artifact | SHA-256 |
|---|---|
| `okok_FIXED_v2.xlsx` | `b605d50a79b466cced02fd2fe75b676c933443d6b51cafef367f60fa1b07474d` |
| `schema.sql` | `6D1232A4AB39BE2AB83791FC2A4381826D256D874AB8430CEBA0E97575795229` |
| `views.sql` | `26D0EC77D521D3B367CCB49A10237DC94CF9E5A2927C34E76001D5D4DF6F2D50` |
| `etl.py` | `BA0ADAE11CC9BBF18848D7005786595811ADC55D7D94E2494EF402B8DD329EE3` |
| `app.py` | `95709C562EEF0C184737A8CF13C98D63092363A16379FDA85E27826069527956` |
| `admin_schema.sql` | `1FCD268B7924C0E80DC06266F7643FE06BF122BFD0FE79A3AA021D96AD340C77` |
| `quality_checks.sql` | `C5FA8521E66785A77E3CB85CD07A4CA50FAE072BA61FF13A6551C7E733F4A78B` |
| `database_roles.sql` | `C2E97152D37FC5BC775DC9AB9A961D4A9332D90D8B001CF83651CF5BFF597C03` |
| `migrations/001_foundation_v2.sql` | `236BB559EBDF0B393F707940C5B32C4CB1CD46CBC1CD6F223E9C66BB6078B121` |
| `migrations/002_derived_student_state.sql` | `60BD1678A62DBFF14AEF1D479FEB2DEDD60B65A40C5B5A5B753466E6133F7B1A` |

## Source workbook profile

Profiled with `openpyxl`, formula values preserved. Meaningful rows count rows containing at least one non-null cell.

| Sheet | Physical rows | Meaningful rows | Max columns |
|---|---:|---:|---:|
| `STUDENTS` | 1005 | 309 | 30 |
| `sheet2` | 1593 | 538 | 90 |
| `ATTENDANCE_LOG` | 6282 | 6282 | 8 |
| `Placement` | 1346 | 370 | 26 |
| `PIC` | 1000 | 177 | 9 |
| `LEVEL_HELPER` | 1003 | 15 | 6 |
| `CLASS_DATES` | 79 | 79 | 3 |
| `COURSE_PLAN` | 1000 | 7 | 6 |

Other sheets were retained in the source file and profiled: `DASHBOARD`, `DATE_ANOMALIES`, `Log`, `ATTENDANCE_INPUT`, `ATT_COUNT`, `Pivot Table 1`, `PROGRESS`, `Trang tính14`, `Bản sao của Trang tính8`, and `Cross-check`.

Observed formula/error evidence:

- `ATTENDANCE_LOG`: one formula containing `#N/A`/`FILTER` fallback text.
- `PIC`: 19 `#N/A` cells were observed.

## Target database audit

Completed against the local target:

| Field | Value |
|---|---|
| Database | `english_class` |
| User | `postgres` |
| Server | PostgreSQL 18.4 on x86_64-windows |
| Database size | 10 MB |

Non-template databases:

| Database | Size |
|---|---:|
| `english_class` | 10 MB |
| `postgres` | 8014 kB |

Table inventory:

| Relation | Type | Rows |
|---|---|---:|
| `app_users` | table | 1 |
| `attendance_log` | table | 6278 |
| `audit_log` | table | 1 |
| `class_offerings` | table | 84 |
| `class_pic` | table | 52 |
| `course_plan` | table | 6 |
| `enrollments` | table | 530 |
| `level_helper` | table | 14 |
| `placements` | table | 319 |
| `students` | table | 308 |
| `v_att_count` | view | 548 |
| `v_dashboard_by_course` | view | 6 |
| `v_dashboard_overview` | view | 1 |
| `v_enrollment_detail` | view | 530 |
| `v_progress_by_bu` | view | 8 |

Migration/admin-state evidence:

| Check | Result |
|---|---|
| `to_regclass('public.schema_migrations')` | missing |
| `to_regclass('public.class_sessions')` | missing |
| `to_regclass('public.data_quality_issues')` | missing |
| `to_regclass('public.app_users')` | present |
| `english_class_app` role | missing |
| `postgres` role | present, login/superuser/createdb |

Constraints:

- 66 constraints were found across the existing public tables.
- Existing tables include primary keys, foreign keys, checks, and uniqueness constraints.
- The current database resembles a loaded base/admin state, but not a migrated Phase 1+ state because migration tracking and derived tables are absent.

Backup:

| Field | Value |
|---|---|
| Backup file | `backups/english_class_phase0_20260713_093949.dump` |
| Format | PostgreSQL custom archive |
| Compression | gzip |
| Dumped from/by | PostgreSQL 18.4 / pg_dump 18.4 |
| TOC entries | 81 |
| `pg_restore --list` validation | passed |

## Test evidence

Commands executed:

```text
python --version
python <Streamlit skill>/scripts/discover.py --project-dir <repo>
git status --short --branch
git status --short --branch
Get-FileHash ... -Algorithm SHA256
python -c "load workbook and count non-empty rows/errors"
psql --version
pg_dump --version
pg_restore --version
psql "$DATABASE_URL" -w -c "select current_database(), current_user, version();"
psql "$DATABASE_URL" -w -c "<table/view/role/migration audit queries>"
pg_dump -U postgres -h localhost -p 5432 -d english_class -w -Fc -f backups/english_class_phase0_20260713_093949.dump
pg_restore -l backups/english_class_phase0_20260713_093949.dump
```

Important output:

```text
Python 3.14.6
Streamlit skill discovery succeeded; local reference skill located.
git status: `## No commits yet on master`, all project files untracked
psql/pg_dump/pg_restore: PostgreSQL 18.4 client tools found under `C:\Program Files\PostgreSQL\18\bin`
current_database/current_user/version: `english_class` / `postgres` / PostgreSQL 18.4
schema_migrations/class_sessions/data_quality_issues: missing
backup: `backups/english_class_phase0_20260713_093949.dump`; restore catalog listed successfully
```

- [x] Source checksum and workbook profile completed.
- [x] No-write-before-backup rule respected; DB work before backup was read-only audit only.
- [x] Database audit completed.
- [x] Backup and restore catalog validation completed.

## Reconciliation

| Dataset | Source | Canonical | Issues | Ignored | Difference |
|---|---:|---:|---:|---:|---:|
| `STUDENTS` | 309 meaningful rows | 308 `students` rows | Not yet audited | likely 1 header row | 0 after header assumption |
| `sheet2` | 538 meaningful rows | 530 `enrollments` rows / 84 `class_offerings` rows | Not yet audited | mixed sheet/header/derived rows likely | needs Phase 2 reconciliation |
| `ATTENDANCE_LOG` | 6282 meaningful rows | 6278 `attendance_log` rows | Not yet audited | likely header/formula/filter rows | needs Phase 2 reconciliation |
| `Placement` | 370 meaningful rows | 319 `placements` rows | Not yet audited | blank/error/duplicate/non-canonical rows likely | needs Phase 2 reconciliation |

Representative records manually traced:

- Normal record: not yet; requires staging/DB target in Phase 2.
- Edge case: workbook error cells observed and recorded above.
- Known anomaly: legacy README reports missing dates/courses and ambiguous attendance; not reclassified without target DB audit.

## Review gate

Decision: **Approved for Phase 1 planning/implementation with constraints.**

Expected output was a repository/source baseline, database migration-state evidence, and validated backup. Actual inspection produced all three. The target database is backed up and ready for a Phase 1 migration-state design pass.

Residual risks / deferred work:

- The database has data but no `schema_migrations`, `class_sessions`, `data_quality_issues`, or `english_class_app` role. Phase 1 must treat this as an existing loaded database without migration tracking, not as an empty database.
- `DRAFT_MIGRATIONS.lock` remains present. Do not run `setup.ps1`, `migrate.py`, legacy ETL, or draft migrations until the lock/plan explicitly authorizes the next operation.
- Git workflow is available, but no baseline commit exists yet.

Reviewer decision:

- [x] Approved
- [ ] Changes required
