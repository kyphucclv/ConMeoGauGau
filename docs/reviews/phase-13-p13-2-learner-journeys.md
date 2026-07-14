# Phase 13.2 learner journeys

Status: **Implemented and verified**

Date: 2026-07-14

## Scope

P13.2 replaces the database-shaped learner workflow with HR tasks while
retaining the canonical transaction boundary established in P13.0.

- `Learner list` provides employee search, optional business filters, current
  learning state, and a single selected-person detail view.
- `Start learning` begins from either an existing employee or a new employee.
- Existing employees are classified as currently learning, ready to continue,
  returning, rejoining, or first-time before a destination is selected.
- Active learners are routed to `Move learner`; inactive learners are routed to
  the correct start, restart, or continuation action.
- Profile correction, course history, and named-actor change history stay in
  the selected learner record.

## Confirmation flow

Start and move journeys show the destination class, course, calculated first
session, and projected class size before the command is enabled. HR confirms
one summary. Capacity exception controls appear only when the selected action
would increase membership above the configured capacity.

The interface lists only `planned` and `active` course runs. The service also
rejects other run states so direct callers cannot bypass this rule.

## Transaction behavior

`BusinessService.onboard_learner` remains the single atomic command for
first-time, returning, continuation, and rejoin paths.

- unchanged employee name/status does not update the employee row;
- unchanged BU/role does not append organization history;
- existing entrance placement and applicable active membership are reused;
- continuation in an already-full class does not create a capacity override;
- a new above-capacity membership requires one reasoned override.

`BusinessService.transfer_learner` now applies the same capacity policy. A
failed unapproved move leaves the source enrollment and membership active. An
approved move closes and links the source, creates the target membership and
enrollment snapshots, writes the capacity override when needed, and records
the learner transfer in one transaction. Move destinations must belong to a
different class; same-class next-course work uses the continuation journey.

## Read boundary

`frontend_queries.learner_journey_context` is the task read model for lifecycle
classification. Streamlit modules still contain no read SQL and all writes
still cross `BusinessService`.

## Verification

- `python scripts\phase4_integration_check.py`
- `python scripts\phase5_reporting_check.py`
- `python scripts\phase6_security_check.py`
- `python scripts\phase7_frontend_workflow_check.py`
- `python scripts\phase8_automated_uat.py`
- `python scripts\phase11_p11_1_integration.py`
- `python scripts\phase13_dictionary_check.py`
- `python scripts\phase11_operational_issue_snapshot.py --validate-decisions --database-url postgresql://postgres@localhost:5432/english_class`
- `.\run_app.cmd -CheckOnly`

Phase 7 validates lifecycle read models and the UI/query boundary. Phase 8
navigates both learner views with Streamlit AppTest. Phase 11 validates
continuation reuse, no-op employee/profile behavior, transfer rollback,
reasoned capacity override, and rejection of closed destination runs.

## Production impact

P13.2 requires no schema migration and performs no production data
remediation. Production validation is read-only; the approved operational issue
snapshot remains the release baseline.
