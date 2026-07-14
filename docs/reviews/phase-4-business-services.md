# Phase 4 business services review

## Change identity

- Task/phase: Phase 4 - Business commands and database services
- Developer: Codex
- Date: 2026-07-13
- Files changed: `migrations/005_phase4_completion.sql`, `services.py`
- Data entities affected: service commands over canonical v3 entities; completion suggestions

## Contract review

The implementation follows the approved grain in `DATA_DICTIONARY.md` and
`TARGET_ARCHITECTURE.md`.  Completion suggestion grain is one decision for one
run enrollment.  Evaluation versions remain append-only.  Transfers close the
old record and create a new record.  Attendance remains binary and make-up
records retain the original attendance reference.

The service layer has no Streamlit import.  Every public command performs role
authorization, validates input/state, writes its audit event before commit, and
returns `CommandResult` or raises `CommandError` with a stable code.

## Implemented command surface

- employee upsert and org observation;
- cohort creation and PIC assignment;
- membership add, close, and transfer;
- course-run creation with advisory-lock run numbering and lifecycle status;
- enrollment and enrollment transfer with mid-run start session;
- meeting/unit creation, update, and cancellation;
- bulk attendance and make-up correction;
- attendance-ratio eligibility calculation and admin override;
- evaluation creation/correction as immutable versions;
- completion suggestion and admin confirmation/rejection.

## Test evidence

Commands executed:

```text
python -m py_compile services.py scripts\phase4_integration_check.py
git diff --check
python scripts\phase4_integration_check.py
```

The Python compile and whitespace checks passed.  The integration gate creates
and recreates disposable database `english_class_p4_test`, applies migrations
`001` through `005`, seeds minimum reference data, and exercises the Phase 4
service commands against PostgreSQL.

Latest integration output:

```text
Applying: 001_canonical_schema_v3.sql
Applying: 002_raw_staging_and_profile.sql
Applying: 003_etl_source_row_outcomes.sql
Applying: 004_canonical_etl_batches.sql
Applying: 005_phase4_completion.sql
Database migrations are up to date.
Phase 4 integration gate passed.
audit_events: 34
confirmed_suggestions: 1
completed_enrollment_id: 1
transferred_enrollment_id: 3
transferred_membership_id: 2
concurrent_run_numbers: [1, 2]
```

The gate verifies happy paths across employee, cohort, PIC, membership,
course-run, enrollment, meeting, session-unit, attendance, make-up,
eligibility, evaluation, completion, membership transfer, and enrollment
transfer commands.  It also verifies invalid course-run transition handling,
concurrent run-number creation on two database connections, and rollback of an
employee upsert whose later org-history write fails.

## Residual risks / deferred work

- Role provisioning and credential policy belong to Phase 6; services assume
  `app_users` already exists.
- UI adapters and reporting queries belong to Phases 5 and 7.

Reviewer decision: Approved for Phase 5 planning/implementation, with Phase 6
credential hardening still deferred as planned.
