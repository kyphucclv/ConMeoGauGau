# Phase 3 canonical ETL initial review

## Change identity

- Task/phase: Phase 3 - Canonical ETL and legacy issue queue, initial implementation
- Developer: Codex
- Date: 2026-07-13
- Files changed: `scripts/canonical_etl_v3.py`
- Data entities affected: none in the working database; ETL was tested only on disposable database `english_class_p1_test`

## Contract review

- Canonical ETL reads from `raw_workbook_rows`; it does not read the workbook directly.
- Valid rows are loaded into canonical v3 tables.
- Ambiguous rows are routed to `data_quality_issues` with source sheet and source row number.
- The working `english_class` database was not migrated or loaded.

Row grain:

```text
One run_enrollments row represents exactly one employee participating in one course run.
One attendance row represents exactly one enrollment result for one applicable session unit.
One data_quality_issues row represents exactly one detected source-row problem requiring review.
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
- issue queue: `data_quality_issues`.

The loader is conservative:

- no global MIN attendance date is used as an admin-confirmed run start;
- class/course/session/date conflicts are quarantined as issues;
- attendance without matching enrollment is quarantined;
- missing course/date/class/employee identifiers are quarantined;
- repeated run inference remains limited to Run 1 until stronger evidence exists.

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
attendance.inserted: 5751
```

Important output from second ETL run:

```text
attendance.inserted: 0
issues.attendance_without_enrollment: 0
issues.conflicting_session_structure: 0
issues.duplicate_business_placement: 0
issues.malformed_date: 0
issues.missing_class_code: 0
issues.missing_course: 0
issues.unknown_level: 0
issues.unmapped_pic_employee: 0
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
| `meetings` | 893 |
| `session_units` | 896 |
| `attendance` | 5751 |
| `placements` | 316 |
| `evaluations` | 326 |
| `data_quality_issues` | 682 |

Issue counts:

| Issue code | Count |
|---|---:|
| `attendance_without_enrollment` | 114 |
| `conflicting_session_structure` | 413 |
| `duplicate_business_placement` | 3 |
| `malformed_date` | 3 |
| `missing_class_code` | 124 |
| `missing_course` | 7 |
| `unknown_level` | 9 |
| `unmapped_pic_employee` | 9 |

Representative traced canonical row:

```text
emp_code=237050, class_code=EL001, course_name=Business English,
sequence_in_run=1..5, effective_status=Present
```

Representative traced issues:

```text
attendance_without_enrollment: ATTENDANCE_LOG row 957, 237117:EL008:Business English:2
conflicting_session_structure: ATTENDANCE_LOG row 194, 247300:EL002:Communication 1:1
duplicate_business_placement: Placement row 336, 247313
malformed_date: ATTENDANCE_LOG row 4118, 227097:EL034:Business English:13
missing_course: sheet2 row 532, 267040:EL052
unknown_level: Placement row 238, 247193, level="not placement"
unmapped_pic_employee: PIC row 6, EL005, PIC="Duc Nguyen"
```

## Review gate

Decision: **Changes required / Phase 3 remains in progress.**

What passed:

- [x] Fresh disposable migration plus staging plus ETL runs successfully.
- [x] Same ETL rerun does not duplicate attendance or issue rows.
- [x] Known anomalies are surfaced in `data_quality_issues`.
- [x] Canonical attendance/enrollment/evaluation rows can be traced through FKs.

What is not yet approved:

- [ ] Full source reconciliation equation is not complete for every core sheet.
- [ ] Helper/header rows in `Placement` and trailing helper rows in `PIC` need an explicit loaded/issue/ignored outcome rule.
- [ ] Course-run inference currently creates only Run 1 per cohort/course and must be reviewed against repeated-course evidence.
- [ ] Transfer and mid-run join scenarios are not yet fully traced.
- [ ] Failure-state batch transitions are not yet implemented around canonical writes.

Residual risks / deferred work:

- The ETL is good enough as a first executable pass, but not yet a cutover-ready canonical import.
- Issue rows can overlap canonical rows for partially loadable rows, so reconciliation reporting needs a stricter per-source-row ledger in the next pass.
- `DRAFT_MIGRATIONS.lock` remains in place.

Reviewer decision:

- [ ] Approved
- [x] Changes required
