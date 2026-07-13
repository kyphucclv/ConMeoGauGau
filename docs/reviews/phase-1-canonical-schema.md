# Phase 1 canonical schema review

## Change identity

- Task/phase: Phase 1 - Canonical schema v3
- Developer: Codex
- Date: 2026-07-13
- Files changed: `migrations/001_canonical_schema_v3.sql`
- Files removed/replaced: draft `migrations/001_foundation_v2.sql`, draft `migrations/002_derived_student_state.sql`
- Data entities affected: none in the working database; migration was tested only on disposable/test targets

## Contract review

- Phase 0 confirmed the target database has no `schema_migrations` table, so the plan's clean v3 migration branch applies.
- `DRAFT_MIGRATIONS.lock` remains present.
- No draft migration was applied to the working `english_class` database.
- A Phase 0 backup exists and was validated before this phase.

Row grain implemented:

```text
employees
  -> employee_org_history
  -> cohort_memberships -> cohorts -> cohort_pic_assignments
  -> run_enrollments -> course_runs -> courses
                    -> meetings -> session_units -> attendance
  -> placements
  -> evaluations -> evaluation_versions
```

## Implementation summary

Created clean canonical v3 migration:

- shared infrastructure: `schema_migrations` via `migrate.py`, `import_batches`, `data_quality_issues`, `audit_events`, `app_users`;
- reference tables: `levels`, `courses`, `business_units`, `job_roles`;
- people/org model: `employees`, `employee_org_history`;
- cohort model: `cohorts`, `cohort_memberships`, `cohort_pic_assignments`;
- delivery model: `course_runs`, `run_enrollments`;
- schedule/attendance model: `meetings`, `session_units`, `attendance`;
- placement/evaluation model: `placements`, `evaluations`, `evaluation_versions`;
- triggers for `updated_at` and the session-unit meeting rule.

## Test evidence

Disposable database:

```text
english_class_p1_test
```

Commands executed:

```text
createdb -U postgres -h localhost -p 5432 -w english_class_p1_test
python .\migrate.py "postgresql://postgres@localhost:5432/english_class_p1_test"
psql ... -c "select count(*) as table_count ..."
psql ... -c "select count(*) as constraint_count ..."
psql ... -c "select version, left(checksum, 12) ..."
psql ... -c "insert seed data through employees -> attendance"
psql ... -c "negative invariant tests"
dropdb -U postgres -h localhost -p 5432 -w english_class_p1_test
```

Important output:

```text
Applying: 001_canonical_schema_v3.sql
Database migrations are up to date.
table_count: 22
constraint_count: 235
schema_migrations: 001_canonical_schema_v3 / 8732e4848fa2
seed_counts: employees=2, course_runs=1, attendance=1
PASS_REJECTED=duplicate_emp_code
PASS_REJECTED=two_current_org_rows
PASS_REJECTED=duplicate_run_number
PASS_REJECTED=third_normal_unit
PASS_REJECTED=duplicate_attendance
DROPPED english_class_p1_test
```

## Review gate

Decision: **Approved for Phase 2 planning/implementation with constraints.**

Acceptance criteria status:

- [x] Schema creates successfully on an empty disposable PostgreSQL database.
- [x] Expected PK/FK/unique/check constraints exist in PostgreSQL.
- [x] No legacy spreadsheet helper field exists in canonical tables.
- [x] Focused database tests for P1.2-P1.6 invariants passed.

Residual risks / deferred work:

- This phase defines the canonical empty schema only. It does not migrate existing `english_class` data.
- Phase 2 must add auditable staging/profiling before canonical ETL.
- App code still targets the legacy schema and will need later phase updates.
- `DRAFT_MIGRATIONS.lock` remains in place until the full migration chain is complete and approved.

Reviewer decision:

- [x] Approved
- [ ] Changes required
