# Phase 8 automated verification and UAT review

## Change identity

- Task/phase: Phase 8 - Automated verification and UAT
- Developer: Codex
- Date: 2026-07-13
- Files changed: `scripts/phase8_automated_uat.py`, `services.py`
- Data entities affected: canonical schema, services, reports, Streamlit app smoke, backup/restore rehearsal

## Contract review

Phase 8 adds a single automated gate that proves the canonical path on a fresh
disposable database.  It applies migrations, checks schema migration state,
exercises service constraints and authorization behavior, replays all required
UAT scenarios, smoke-tests the Streamlit app with `streamlit.testing.v1`, and
performs a PostgreSQL custom-format backup/restore rehearsal with actual
restored row checks.

Two service hardening fixes were made while building the gate:

- new enrollments now snapshot the employee's current BU/role;
- PostgreSQL trigger `RAISE EXCEPTION` errors are mapped to safe
  `CommandError("invalid_state")` UI errors.

## Automated suites covered

- Schema/constraint tests:
  duplicate active membership and more-than-two-normal-units trigger are tested.
- Migration tests:
  fresh database applies migrations `001` through `006` and validates
  `schema_migrations`.
- Service transaction and permission tests:
  viewer mutation is denied; service error mapping is checked.
- Reporting fixture tests:
  attendance denominator, mid-run applicability, final-test monthly handling,
  historical snapshots, regression, and unresolved quality issue visibility are
  checked through reporting views.
- Streamlit smoke tests:
  login render and authenticated tab render are tested with `AppTest`.
- Backup/restore rehearsal:
  `pg_dump -Fc` and `pg_restore` run against disposable databases, then restored
  data and migration rows are queried.

## UAT scenario coverage

1. New employee, placement, cohort membership, and first run: covered.
2. Mid-course join with prior units not applicable: `midrun_applicable_units: 3`.
3. Transfer to a cohort currently at a different session number:
   `transfer_start_session_number: 3`.
4. One meeting with two credited units: covered by schema and UAT schedule.
5. Cancelled meeting excluded from eligibility: denominator excludes cancelled unit.
6. Too many absences, then reasoned admin override: calculated ineligible, then
   override makes effective eligibility true.
7. Make-up changes effective attendance while preserving audit history:
   `attendance.makeup` audit is checked.
8. Completed - no continuation outcome: evaluation with `next_course_id IS NULL`
   is recorded for a completed learner.
9. Evaluation correction retains versions: `evaluation_versions: 3`.
10. BU/role update does not rewrite historical enrollment reports:
    `historical_bu_snapshot: Original BU`.
11. Regression appears while highest remains unchanged: `regression_flag: True`.
12. Legacy anomaly remains traceable and excluded until resolved:
    unresolved quality issue is visible and does not change schedule counts.

## Test evidence

Commands executed:

```text
python -m py_compile db.py auth.py reporting.py services.py frontend_workflows.py streamlit_app.py app.py scripts\phase8_automated_uat.py scripts\phase7_frontend_workflow_check.py scripts\phase6_security_check.py scripts\phase5_reporting_check.py scripts\phase4_integration_check.py
git diff --check
python scripts\phase8_automated_uat.py
python scripts\phase4_integration_check.py
python scripts\phase5_reporting_check.py
python scripts\phase6_security_check.py
python scripts\phase7_frontend_workflow_check.py
```

Latest Phase 8 output:

```text
Phase 8 automated verification and UAT gate passed.
migrations: 7
attendance_ratio: 0.5000
midrun_applicable_units: 3
transfer_start_session_number: 3
credited_session_units: 3
final_test_units: 1
evaluation_versions: 3
historical_bu_snapshot: Original BU
regression_flag: True
quality_issue_traced: True
login_titles: 2
authenticated_tabs: 4
restored_employees: 5
restored_migrations: 7
```

Phase 4, Phase 5, and Phase 7 gates were rerun after the session-occurrence and
PIC-label changes and still passed. The Phase 8 gate also restored all seven
migrations successfully.

## Residual risks / deferred work

- User sign-off on KPI meanings and UAT scenarios is still a human approval
  step before production cutover.
- Production backup/restore must be rehearsed with the actual production backup
  during Phase 9; Phase 8 proves the mechanism on disposable data.
- Active app sessions are revalidated against `app_users`; deactivation was
  verified to return an existing session to login on the next rerun.
- Legacy snapshot migration testing remains represented by canonical staging
  and ETL phase evidence plus the unresolved anomaly trace in this gate.

Reviewer decision: Approved for Phase 9 cutover planning.
