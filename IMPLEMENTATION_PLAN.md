# Detailed Implementation Plan

Status: **In execution - Phase 3 in progress**

This plan implements `DATA_DICTIONARY.md` and `TARGET_ARCHITECTURE.md`. All
tasks are governed by `PROJECT_RULES.md` and must include evidence from
`DEVELOPER_REVIEW_CHECKLIST.md`.

## Delivery policy

- Execute phases in order unless a dependency is explicitly removed.
- One phase may contain several small pull requests, but one pull request must
  not mix unrelated schema, ETL, reporting, and UI changes.
- Keep `DRAFT_MIGRATIONS.lock` through Phase 8.
- Do not run draft migrations on the production/working database.
- At the end of every phase, hold a review gate. A failed gate sends the phase
  back to `in progress`.

## Execution state

- Phase 0 is approved in `docs/reviews/phase-0-baseline.md`.
- Phase 1 is approved in `docs/reviews/phase-1-canonical-schema.md`.
- Phase 2 is approved in `docs/reviews/phase-2-raw-staging-profile.md`.
- Phase 3 has an initial executable ETL pass in
  `docs/reviews/phase-3-canonical-etl-initial.md`, but the review gate remains
  open pending stricter source-row reconciliation and transfer/run inference.
- Phase 3 source-row outcome coverage now passes for the core workbook sheets
  through `migrations/003_etl_source_row_outcomes.sql`; the gate remains open
  for transfer/mid-run tracing and failure-state handling.
- Phase 3 course-run inference audit is captured in
  `docs/reviews/phase-3-course-run-inference-audit.json`; unresolved repeated
  run candidates are quarantined as `run_boundary_unresolved`.
- The target database had no `schema_migrations` table during Phase 0 audit, so
  the selected branch is a clean canonical v3 initial migration.
- `migrations/001_canonical_schema_v3.sql` replaced the un-applied draft
  migration chain.
- `migrations/002_raw_staging_and_profile.sql` adds auditable raw workbook
  staging and profiling metadata.
- The working `english_class` database has not been migrated to v3.
- Local PostgreSQL test access uses `%APPDATA%\postgresql\pgpass.conf` entries
  for `english_class`, `postgres`, and `english_class_p1_test`.
- Git is initialized on `master`, but no baseline commit has been created yet.

## Phase 0 - Baseline and migration-state audit

Goal: establish facts before changing any database.

### P0.1 Capture repository baseline

Tasks:

- Record current file checksums for `schema.sql`, migrations, ETL, views, and
  the source workbook.
- Record Python, PostgreSQL, and Streamlit versions.
- Confirm whether the folder is a valid Git worktree; if not, initialize the
  intended version-control workflow before implementation.
- Record all uncommitted/user changes without reverting them.

Outputs:

- `docs/reviews/phase-0-baseline.md` using the review checklist.
- Source workbook SHA-256 checksum.

### P0.2 Audit target database

Tasks:

- Connect read-only first.
- Query database name, server version, table inventory, row counts, constraints,
  and `schema_migrations` if present.
- Determine whether draft migrations `001` or `002` were applied.
- Capture current report/view outputs and app-user counts.
- Take a custom-format `pg_dump` backup before any mutation.
- Validate the backup with `pg_restore --list`.

Decision branch:

- If draft migrations were never applied, replace the draft chain with a clean
  v3 initial schema/migration.
- If they were applied, never edit them; create additive corrective migrations
  that preserve all existing rows.

Acceptance criteria:

- Database state is known and documented.
- Backup exists and its catalog can be read.
- No schema/data writes occurred before backup.

Review gate:

- A second review confirms the selected migration branch from captured output.

## Phase 1 - Canonical schema v3

Goal: implement target grain and constraints without loading legacy data.

### P1.1 Create shared infrastructure

Implement:

- migration metadata;
- import batches;
- data-quality issues and resolution metadata;
- audit events;
- app users/roles where not already present;
- lookup/reference tables for controlled values.

Required constraints:

- stable issue codes;
- valid issue statuses;
- actor/timestamp on resolutions;
- JSON details default to an empty object, never null.

### P1.2 Create people and organization model

Implement:

- `employees`;
- `business_units` and `job_roles` reference tables;
- `employee_org_history`;
- constraint/index guaranteeing at most one current org row per employee.

Tests:

- duplicate `emp_code` rejected;
- two current org rows rejected;
- changing current org closes/marks previous history in one transaction;
- enrollment snapshots remain unchanged after a later org update.

### P1.3 Create cohort model

Implement:

- `cohorts`;
- `cohort_memberships`;
- `cohort_pic_assignments`;
- safe class-code generation with admin validation/edit before first use.

Tests:

- PIC may be outside cohort;
- cohort display name changes when current PIC changes, code does not;
- transfer closes old membership and creates target membership atomically;
- overlapping active membership periods are handled by the approved rule.

### P1.4 Create course delivery model

Implement:

- `courses`;
- `course_runs`;
- `run_enrollments`;
- unique run number per cohort/course;
- run snapshots for expected units and attendance threshold.

Tests:

- same cohort can repeat the same course in Run 2;
- duplicate run number rejected;
- mid-run join stores `start_session_number`;
- transfer links old and new enrollment;
- BU/role snapshots are populated transactionally.

### P1.5 Create schedule and attendance model

Implement:

- `meetings`;
- `session_units`;
- `attendance`;
- cancelled-meeting rules;
- one or two normal units per meeting;
- duration independent from unit count;
- make-up metadata and effective Present/Absent state.

Tests:

- two units can share one meeting timestamp;
- a normal meeting cannot exceed two normal units;
- final-test duration may exceed two hours without creating teaching frequency;
- sessions before enrollment start are excluded from denominator;
- cancelled meetings are excluded;
- duplicate attendance for enrollment/unit rejected.

### P1.6 Create placement and evaluation model

Implement:

- `levels` with current 0.0-6.5 mapping and sequence;
- `placements` with one business placement per employee;
- stable `evaluations` identity;
- immutable `evaluation_versions`;
- pass and next-course eligibility fields.

Tests:

- second business placement rejected;
- evaluation correction creates a new version and requires reason;
- old evaluation version remains unchanged;
- final level may be null when not eligible;
- current/highest level definitions work with regression.

Phase acceptance criteria:

- Schema creates successfully on an empty disposable PostgreSQL database.
- All expected PK/FK/unique/check constraints are inspected from PostgreSQL.
- No legacy spreadsheet helper field exists in canonical tables.
- Database tests for P1.2-P1.6 pass.

Review gate:

- Developer manually inspects `\d+`/catalog output for every table.
- Reviewer traces one normal learner and one transfer scenario through all FKs.

## Phase 2 - Raw staging and source profiling

Goal: make the import auditable before canonical transformation.

### P2.1 Create staging design

Each raw row stores:

- `import_batch_id`;
- source checksum/name;
- sheet name;
- source row number;
- deterministic row hash;
- raw JSON payload;
- ingestion timestamp.

Use either one generic raw table with strict metadata or sheet-specific staging
tables plus a shared row ledger. Document the selected design and why it is
easy to reconcile.

### P2.2 Build workbook profiler

Profile at minimum:

- row counts and meaningful-data row counts;
- nulls by source field;
- duplicate candidate keys;
- value distributions for controlled fields;
- data types and malformed dates;
- formula/error cells such as `#REF!` and `#N/A`;
- cross-sheet key coverage.

### P2.3 Create mapping specification

For every relevant source field, document:

- target entity/field;
- normalization rule;
- source priority;
- issue code when invalid;
- whether the field is input, snapshot, derived, or deprecated.

Known mappings must include `STUDENTS`, `PIC`, `COURSE_PLAN`, `LEVEL_HELPER`,
`Placement`, `sheet2`, and `ATTENDANCE_LOG`.

Acceptance criteria:

- Re-importing the same workbook creates no duplicate raw rows.
- Raw payload can reconstruct every source row used by ETL.
- Profile output independently reproduces known anomalies.

Review gate:

- Manually compare at least five source rows per core sheet to staging.
- Confirm workbook totals against the source file, not README claims.

## Phase 3 - Canonical ETL and legacy issue queue

Goal: load valid canonical data while preserving all ambiguous rows.

### P3.1 Import reference and employee data

- Load levels and courses through controlled mappings.
- Load employees from learner and PIC sources without using names as keys.
- Load current BU/role observations, then snapshot them during enrollment load.
- Represent unmatched placement candidates as employees/people according to the
  approved mapping; do not null the source identity silently.

### P3.2 Import cohorts, PICs, and memberships

- Create one cohort per valid class code.
- Resolve numbered PIC labels such as one person managing several cohorts.
- Create PIC assignments referencing employees.
- Infer membership only where evidence is sufficient; otherwise issue a stable
  quality code.

### P3.3 Infer course runs conservatively

- Create distinct runs only when source evidence supports the boundary.
- Use explicit Run 1/Run 2 identities for repeated cohort/course histories.
- Do not treat global MIN attendance as a learner enrollment start.
- Quarantine structurally ambiguous patterns instead of inventing schedules.

### P3.4 Import enrollments and evaluations

- Create run enrollments at the correct target grain.
- Preserve BU/role snapshots.
- Convert source entrance/final levels through controlled mapping.
- Create initial evaluation version only when a final result exists.
- Preserve teacher pass/next-course fields when available; mark unavailable
  legacy values as unknown rather than guessing.

### P3.5 Import meetings, session units, and attendance

- Preserve original class, course, session order, timestamp, and status in raw
  provenance.
- Create meetings and units only for non-ambiguous source groups.
- Route the following to issues at minimum:
  - attendance rows without dates;
  - enrollment rows without course;
  - attendance without a resolvable enrollment;
  - inconsistent class/course/session/timestamp structures;
  - duplicate or conflicting effective attendance.
- Do not let unresolved structural rows contribute to schedule KPIs.

### P3.6 Idempotency and failure behavior

- Use batch/checksum state transitions: running, completed, failed.
- Roll back canonical writes when a batch fails.
- Preserve failure details and raw rows for investigation.
- Re-run a completed checksum as a no-op or explicit reviewed replay.

Acceptance criteria:

- Source reconciliation equation balances for every core sheet.
- No silent skip path exists.
- Same checksum re-run creates no duplicate canonical rows.
- Failed batch cannot leave partially committed canonical data.
- Known anomalies appear with expected stable issue codes and source references.

Review gate:

- Trace normal, transfer, missing-date, missing-course, and conflicting-session
  examples from workbook row to raw row to canonical record/issue.
- Developer reviews transformed values after ETL, not only ETL logs.

## Phase 4 - Business commands and database services

Goal: implement transactional operations independently of the UI.

Commands:

- create/update employee and org observation;
- create cohort and assign/change PIC;
- add/close/transfer cohort membership;
- create/start/complete/cancel course run;
- enroll mid-run and transfer enrollment;
- create/update/cancel meeting and units;
- bulk record attendance;
- correct attendance as make-up with audit;
- calculate/override exam eligibility;
- create/correct evaluation version;
- suggest and confirm course completion.

Requirements:

- validated command inputs;
- one transaction per business operation;
- role authorization in service layer;
- typed result/error objects suitable for UI display;
- no Streamlit imports in domain/repository modules.

Acceptance criteria:

- Unit and integration tests cover each command's happy path and invalid state
  transition.
- Concurrent class-code/run-number creation cannot duplicate values.
- Audit events are written in the same transaction as sensitive changes.

Review gate:

- Reviewer deliberately triggers a failure halfway through a multi-table
  command and verifies full rollback.

## Phase 5 - Reporting views and KPI validation

Goal: expose metrics with documented semantics.

Implement views/queries for:

- current employee/cohort/run state;
- attendance ratio and exam eligibility;
- sessions per month, excluding final-test duration inflation;
- placement/current/highest level;
- ordered progress trajectory and regression;
- historical reporting by enrollment BU/role snapshot;
- unresolved quality issue summary;
- cohort/course-run operational dashboard.

Do not implement true company coverage without an HR roster denominator.

Validation:

- Calculate representative KPI examples independently in test SQL/Python.
- Test mid-run joins, transfers, cancellations, make-up, regression, and revised
  evaluation versions.
- Label legacy-comparable metrics separately when semantics differ from the old
  spreadsheet dashboard.

Acceptance criteria:

- Every displayed KPI links to a written definition.
- Test fixtures prove numerator and denominator composition.
- Unresolved anomalies do not silently enter schedule-dependent metrics.

Review gate:

- Developer manually traces at least three KPI rows to base records.

## Phase 6 - Security and application architecture

Goal: prepare a maintainable app foundation.

Tasks:

- Create restricted migration, application, and read-only database roles.
- Split database/repository, service, reporting, auth, and Streamlit UI modules.
- Use a bounded connection pool with timeouts.
- Load credentials from environment/Streamlit secrets only.
- Remove schema DDL and arbitrary SQL execution from app runtime.
- Define admin/editor/viewer permissions per command.
- Add structured error handling that does not expose credentials or raw traces
  to normal users.

Acceptance criteria:

- App role cannot create/drop/alter schema objects.
- Viewer cannot mutate through direct service calls.
- Editor cannot manage users or bypass eligibility without permission.
- No secret appears in tracked files or rendered UI.

Review gate:

- Test permissions using each real PostgreSQL role, not UI hiding alone.

## Phase 7 - Admin frontend workflows

Goal: implement workflows only after services and rules are stable.

Build in this order:

1. Employee search/create/update and org-history observation.
2. Cohort creation, membership management, transfer, and PIC assignment.
3. Course-run creation and lifecycle.
4. Approved schedule entry with one/two units and cancellation.
5. Bulk attendance by meeting/unit, including mid-run applicability.
6. Eligibility review and reasoned admin override.
7. Final evaluation entry and transparent correction history.
8. Progress trajectory, monthly frequency, and data-quality review screens.

UX requirements:

- forms batch related writes;
- no free-form database identifiers when a validated selector is available;
- confirmations for state transitions;
- clear distinction between current, highest, and entrance level;
- quality warnings include a source reference and resolution action;
- hidden tabs must not execute every expensive query on each rerun.

Acceptance criteria:

- Each workflow is tested against its service command.
- Desktop and mobile layouts remain usable.
- User-facing errors explain the correction without exposing internals.

Review gate:

- Developer replays the real monthly admin workflow from cohort creation through
  evaluation and reviews resulting database rows after every major step.

## Phase 8 - Automated verification and UAT

Goal: prove the system is correct enough to replace the spreadsheet workflow.

Required automated suites:

- schema/constraint tests;
- migration tests on fresh and legacy snapshots;
- ETL unit/idempotency/reconciliation tests;
- service transaction and permission tests;
- reporting fixture tests;
- Streamlit smoke tests for critical forms.

Required UAT scenarios:

1. New employee, placement, cohort membership, and first run.
2. Mid-course join with prior units not applicable.
3. Transfer to a cohort currently at a different session number.
4. One meeting with two credited units.
5. Cancelled meeting excluded from eligibility.
6. Too many absences, then reasoned admin override.
7. Make-up changes effective attendance while preserving audit history.
8. Completed - no continuation outcome.
9. Evaluation correction retains both versions.
10. BU/role update does not rewrite historical enrollment reports.
11. Regression appears in trajectory while highest level remains unchanged.
12. Legacy anomaly remains traceable and excluded until resolved.

Acceptance criteria:

- User signs off UAT scenarios and KPI meanings.
- No critical/high defects remain.
- Backup and restore rehearsal succeeds.
- Production runbook is complete.

Review gate:

- Review actual restored data and app behavior, not only backup command exit code.

## Phase 9 - Cutover and setup unlock

Goal: switch safely and leave a supportable system.

Tasks:

- Freeze source workbook edits for the cutover window or record a final checksum.
- Take final backup.
- Run final staged import and reconciliation.
- Resolve or explicitly accept open critical issues.
- Apply production migration with captured output.
- Create restricted app credentials.
- Run smoke tests and KPI checks.
- Remove `DRAFT_MIGRATIONS.lock` only now.
- Update `README.md` and `SETUP_GUIDE.md` from draft warnings to verified steps.
- Document rollback trigger and restore command.

Acceptance criteria:

- Final source reconciliation is signed off.
- App uses canonical v3 tables only.
- Setup/run instructions were executed successfully on a clean environment.
- Monitoring, backup ownership, and issue ownership are assigned.

## Cross-phase review requirement

At the end of every phase, the developer must answer:

1. What output did we expect?
2. What output did we actually inspect?
3. Which source records or scenarios were traced manually?
4. What automated tests ran, and what important output did they produce?
5. What assumptions changed after reviewing the output?
6. What remains risky or unresolved?

Answers such as "tests passed" or "migration succeeded" without evidence are
not sufficient. Review the generated tables, rows, constraints, reports, and UI
state directly before requesting approval.
