# Phase 3 canonical ETL initial review

## Change identity

- Task/phase: Phase 3 - Canonical ETL and legacy issue queue, initial implementation
- Developer: Codex
- Date: 2026-07-13
- Files changed:
  - `migrations/003_etl_source_row_outcomes.sql`
  - `migrations/004_canonical_etl_batches.sql`
  - `scripts/canonical_etl_v3.py`
  - `scripts/audit_course_run_inference.py`
  - `scripts/audit_transfer_midrun.py`
  - `docs/reviews/phase-3-course-run-inference-audit.json`
  - `docs/reviews/phase-3-transfer-midrun-audit.json`
- Data entities affected: none in the working database; ETL was tested only on disposable database `english_class_p1_test`

## Contract review

- Canonical ETL reads from `raw_workbook_rows`; it does not read the workbook directly.
- Valid rows are loaded into canonical v3 tables.
- Ambiguous rows are routed to `data_quality_issues` with source sheet and source row number.
- Every core source row receives at least one `etl_source_row_outcomes` ledger entry.
- Canonical ETL writes are wrapped in a canonical batch transaction with
  `running`, `completed`, and `failed` states.
- The working `english_class` database was not migrated or loaded.

Row grain:

```text
One run_enrollments row represents exactly one employee participating in one course run.
One attendance row represents exactly one enrollment result for one applicable session unit.
One data_quality_issues row represents exactly one detected source-row problem requiring review.
One etl_source_row_outcomes row represents exactly one loaded, issue, or ignored outcome for one raw source row.
One canonical_etl_batches row represents exactly one canonical transform attempt
against one completed staging import batch.
```

## Implementation summary

`scripts/canonical_etl_v3.py` currently loads:

- references: `levels`, `courses`, `business_units`, `job_roles`;
- people/org: `employees`, `employee_org_history`;
- placement candidates: `placements`;
- cohorts and PICs: `cohorts`, `cohort_pic_assignments`;
- course delivery: `course_runs`, `cohort_memberships`, `run_enrollments`;
- evaluations: `evaluations`, `evaluation_versions`;
- schedule/attendance: `meetings`, `session_units`, `attendance`;
- issue queue: `data_quality_issues`;
- reconciliation ledger: `etl_source_row_outcomes`;
- canonical ETL batch state: `canonical_etl_batches`.

The loader is conservative:

- no global MIN attendance date is used as an admin-confirmed run start;
- class/course/session/date conflicts are quarantined as issues;
- attendance without matching enrollment is quarantined;
- missing course/date/class/employee identifiers are quarantined;
- repeated run inference remains limited to Run 1 until stronger evidence exists.
- possible repeated-run/run-boundary evidence is quarantined as
  `run_boundary_unresolved` instead of being forced into Run 1.
- mid-run joins set `run_enrollments.start_session_number` from the first
  observed attendance session when that session is greater than 1.
- multi-class employee histories are quarantined as
  `transfer_membership_unresolved` until a human confirms transfer boundaries.

## Test evidence

Disposable database:

```text
english_class_p1_test
```

Commands executed:

```text
createdb -U postgres -h localhost -p 5432 -w english_class_p1_test
python .\migrate.py postgresql://postgres@localhost:5432/english_class_p1_test
python .\scripts\stage_workbook.py .\okok_FIXED_v2.xlsx --database-url postgresql://postgres@localhost:5432/english_class_p1_test --profile-output .\docs\reviews\phase-2-workbook-profile.json
python .\scripts\canonical_etl_v3.py postgresql://postgres@localhost:5432/english_class_p1_test
python .\scripts\canonical_etl_v3.py postgresql://postgres@localhost:5432/english_class_p1_test
psql ... table counts
psql ... issue counts
python .\scripts\audit_course_run_inference.py .\okok_FIXED_v2.xlsx --output .\docs\reviews\phase-3-course-run-inference-audit.json
python .\scripts\audit_transfer_midrun.py .\okok_FIXED_v2.xlsx --output .\docs\reviews\phase-3-transfer-midrun-audit.json
python .\scripts\canonical_etl_v3.py ... --fail-after-step placements
python .\scripts\canonical_etl_v3.py ...
python .\scripts\canonical_etl_v3.py ...
```

Important output from first ETL run:

```text
levels.upserted: 14
courses.upserted: 6
employees.upserted: 670
cohorts.inserted: 52
course_runs.inserted: 84
run_enrollments.inserted: 530
placements.inserted: 316
evaluations.upserted: 326
attendance.inserted: 5458
issues.run_boundary_unresolved: 303
issues.transfer_membership_unresolved: 143
outcomes.loaded: 22031
outcomes.issue: 994
outcomes.ignored: 174
canonical_etl_batch status: completed
```

Important output from second ETL run:

```text
attendance.inserted: 0
issues.attendance_without_enrollment: 0
issues.conflicting_session_structure: 0
issues.duplicate_business_placement: 0
issues.malformed_date: 0
issues.missing_course: 0
issues.unknown_level: 0
issues.unmapped_pic_employee: 0
outcomes.loaded: 0
outcomes.issue: 0
outcomes.ignored: 0
canonical_etl result: already_completed
```

Forced failure test:

```text
python .\scripts\canonical_etl_v3.py ... --fail-after-step placements
canonical_etl_batches: failed=1
employees=0
placements=0
data_quality_issues=0
etl_source_row_outcomes=0
```

Success after failure:

```text
canonical_etl_batches: completed=1, failed=1
completed batch stats attendance.inserted=5458
completed batch stats outcomes.issue=994
```

Final table counts:

| Table | Count |
|---|---:|
| `employees` | 365 |
| `levels` | 14 |
| `courses` | 6 |
| `cohorts` | 52 |
| `course_runs` | 84 |
| `run_enrollments` | 530 |
| `meetings` | 852 |
| `session_units` | 854 |
| `attendance` | 5458 |
| `placements` | 316 |
| `evaluations` | 326 |
| `data_quality_issues` | 994 |
| `etl_source_row_outcomes` | 23199 |
| `canonical_etl_batches` | 2 |

Issue counts:

| Issue code | Count |
|---|---:|
| `attendance_without_enrollment` | 114 |
| `conflicting_session_structure` | 413 |
| `duplicate_business_placement` | 3 |
| `malformed_date` | 3 |
| `missing_course` | 7 |
| `run_boundary_unresolved` | 303 |
| `transfer_membership_unresolved` | 143 |
| `unknown_level` | 9 |
| `unmapped_pic_employee` | 9 |

Course-run inference audit:

```text
pair_count: 84
repeated_run_candidate_count: 5
ambiguous_pair_count: 22
```

Repeated-run candidates requiring human review:

| Class | Course | Attendance rows | Reset candidates |
|---|---|---:|---:|
| `EL004` | `Communication 1` | 90 | 3 |
| `EL007` | `Communication 2` | 120 | 3 |
| `EL026` | `Communication 2` | 77 | 1 |
| `EL030` | `Communication 1` | 70 | 1 |
| `EL046` | `Communication 1` | 110 | 2 |

Decision: keep one `course_run` per `class_code + course_name` as Run 1 for now, but exclude attendance rows from the five unresolved run-boundary candidates from canonical attendance until reviewed.

Transfer and mid-run audit:

```text
enrollment_rows: 530
enrollments_without_attendance: 3
midrun_candidate_count: 54
multi_class_employee_count: 62
transfer_candidate_count: 68
```

Mid-run import result:

| `start_session_number` | Enrollment count |
|---:|---:|
| 1 | 476 |
| 2 | 32 |
| 3 | 8 |
| 4 | 6 |
| 5 | 6 |
| 6 | 2 |

Decision: set `start_session_number` from first observed attendance session when the first observed session is greater than 1. Do not create absent rows for earlier sessions. Multi-class histories remain unresolved transfer candidates until reviewed.

Ignored outcome counts:

| Ignored outcome code | Count |
|---|---:|
| `pic_helper_or_trailing_row` | 124 |
| `placement_blank_helper_row` | 47 |
| `placement_header_or_helper_row` | 3 |

Core source-row outcome coverage:

| Sheet | Source rows | Rows with outcome | Rows without outcome |
|---|---:|---:|---:|
| `ATTENDANCE_LOG` | 6281 | 6281 | 0 |
| `CLASS_DATES` | 78 | 78 | 0 |
| `COURSE_PLAN` | 6 | 6 | 0 |
| `LEVEL_HELPER` | 14 | 14 | 0 |
| `PIC` | 176 | 176 | 0 |
| `Placement` | 369 | 369 | 0 |
| `sheet2` | 537 | 537 | 0 |
| `STUDENTS` | 308 | 308 | 0 |

Representative traced canonical row:

```text
emp_code=237050, class_code=EL001, course_name=Business English,
sequence_in_run=1..5, effective_status=Present
```

Representative traced issues:

```text
attendance_without_enrollment: ATTENDANCE_LOG row 957, 237117:EL008:Business English:2
conflicting_session_structure: ATTENDANCE_LOG row 194, 247300:EL002:Communication 1:1
run_boundary_unresolved: ATTENDANCE_LOG row 324, 193479:EL004:Communication 1:1
transfer_membership_unresolved: sheet2 row 3, 173230:EL001:Communication 1
duplicate_business_placement: Placement row 336, 247313
malformed_date: ATTENDANCE_LOG row 4118, 227097:EL034:Business English:13
missing_course: sheet2 row 532, 267040:EL052
unknown_level: Placement row 238, 247193, level="not placement"
unmapped_pic_employee: PIC row 6, EL005, PIC="Duc Nguyen"
```

## Review gate

Decision: **Approved for Phase 4 planning/implementation with constraints.**

What passed:

- [x] Fresh disposable migration plus staging plus ETL runs successfully.
- [x] Same ETL rerun does not duplicate attendance or issue rows.
- [x] Known anomalies are surfaced in `data_quality_issues`.
- [x] Canonical attendance/enrollment/evaluation rows can be traced through FKs.
- [x] Every source row in each Phase 3 core sheet has at least one loaded, issue, or ignored outcome.
- [x] Helper/header rows in `Placement` and trailing/helper rows in `PIC` have explicit ignored outcomes.
- [x] Course-run inference was audited against workbook evidence.
- [x] Possible run-boundary rows are quarantined instead of silently entering Run 1.
- [x] Mid-run join candidates were audited and loaded with `start_session_number`.
- [x] Multi-class employee histories are issue-routed instead of silently rewiring memberships.
- [x] Failure-state batch transitions are implemented and tested around canonical writes.
- [x] Forced mid-ETL failure rolls back canonical writes and records a failed batch.

What is not yet approved:

- [x] Full source-row outcome coverage exists for every core sheet.
- [x] Helper/header rows in `Placement` and trailing helper rows in `PIC` have an explicit loaded/issue/ignored outcome rule.
- [x] Course-run inference has been reviewed against repeated-course evidence; unresolved candidates are issues.
- [x] Transfer and mid-run join scenarios are traced; transfer boundaries remain issues pending human confirmation.
- [x] Failure-state batch transitions are implemented around canonical writes.

Residual risks / deferred work:

- The ETL is approved for the next phase, but not yet a cutover-ready production import.
- Issue rows can overlap canonical rows for partially loadable rows; the source-row outcome ledger now makes that overlap explicit for review.
- `run_boundary_unresolved` and `transfer_membership_unresolved` issues require business review before cutover.
- `DRAFT_MIGRATIONS.lock` remains in place.

Reviewer decision:

- [x] Approved
- [ ] Changes required
