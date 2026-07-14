# Phase 5 reporting and KPI validation review

## Change identity

- Task/phase: Phase 5 - Reporting views and KPI validation
- Developer: Codex
- Date: 2026-07-13
- Files changed: `migrations/006_reporting_views.sql`, `scripts/phase5_reporting_check.py`
- Data entities affected: canonical reporting views over employees, cohorts, course runs, enrollments, schedule, attendance, placements, evaluations, and quality issues

## Contract review

The reporting layer reads canonical v3 tables only.  Legacy spreadsheet report
tables remain untouched and are not used by these views.  Metrics that need
business semantics are documented in `v_reporting_metric_definitions`, so UI
surfaces can link displayed KPI names to numerator and denominator definitions.

The views preserve the target architecture rules:

- attendance denominators use non-cancelled session units on or after
  `run_enrollments.start_session_number`;
- admin eligibility override is separate from calculated attendance
  eligibility;
- sessions-per-month counts credited non-final-test session units in completed
  meetings, so final-test duration does not inflate teaching frequency;
- current level, highest level, trajectory, and regression are separate
  progress metrics;
- historical BU/role reporting reads enrollment snapshots;
- unresolved quality issues are exposed for exclusion/review instead of being
  hidden inside schedule-dependent KPIs.

## Implemented reporting surface

- `v_reporting_metric_definitions`
- `v_latest_evaluation_versions`
- `v_run_enrollment_attendance`
- `v_monthly_session_units`
- `v_historical_enrollment_snapshot`
- `v_current_employee_state`
- `v_progress_trajectory`
- `v_employee_progress_summary`
- `v_unresolved_quality_issues` presents one actionable queue row per source
  problem, preferring the
  lifecycle-managed quality issue over its matching ETL outcome trace.
- `v_cohort_course_run_dashboard`

## Test evidence

Commands executed:

```text
python -m py_compile services.py scripts\phase4_integration_check.py scripts\phase5_reporting_check.py
git diff --check
python scripts\phase5_reporting_check.py
python scripts\phase4_integration_check.py
```

Latest Phase 5 integration output:

```text
Applying: 001_canonical_schema_v3.sql
Applying: 002_raw_staging_and_profile.sql
Applying: 003_etl_source_row_outcomes.sql
Applying: 004_canonical_etl_batches.sql
Applying: 005_phase4_completion.sql
Applying: 006_reporting_views.sql
Database migrations are up to date.
Phase 5 reporting gate passed.
attendance_ratio: 0.7500
midrun_applicable_units: 3
credited_session_units: 3
final_test_units_not_inflated: 1
regression_flag: True
unresolved_quality_issues: 1
```

Phase 4 integration was also rerun after adding migration `006`; it still
passed with `concurrent_run_numbers: [1, 2]`.

## Manual KPI traces

Attendance ratio trace:

- Fixture enrollment has session units 1, 2, final-test unit 4, and make-up
  unit 5 applicable; cancelled unit 3 is excluded.
- Present units are unit 1, final-test unit 4, and make-up unit 5.
- `v_run_enrollment_attendance.attendance_ratio` is therefore `3 / 4 = 0.7500`.

Monthly sessions trace:

- January fixture run has completed normal units 1 and 2, completed make-up
  unit 5, one completed final-test unit, and one cancelled unit.
- `v_monthly_session_units.credited_session_units` is `3`; the final-test unit
  is reported separately as `final_test_units = 1` and its 180 minutes do not
  inflate the teaching-session count.

Progress/regression trace:

- Fixture learner placement is Entrance numeric `1.0`.
- Evaluation version 1 final level is Peak numeric `3.0`; version 2 correction
  is Middle numeric `2.0`.
- `v_employee_progress_summary` reports current level Middle, highest level
  Peak, and `regression_flag = true`.

## Residual risks / deferred work

- True company learning coverage remains deferred because there is no complete
  HR roster denominator.
- Performance tuning with materialized views is deferred until production-size
  query timings justify it.
- UI wiring and user-facing filters belong to Phase 7.

Reviewer decision: Approved for Phase 6 planning/implementation.
