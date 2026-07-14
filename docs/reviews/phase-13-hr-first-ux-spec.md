# Phase 13 HR-first UX specification

Status: **Architecture owner-approved; P13.0 integrity foundation in progress**

Baseline commit: `712d6fb phase12 polish evaluation workflow`

Start date: 2026-07-14

Owner architecture approval date: 2026-07-14

Owner make-up decision: replacement credit without denominator inflation.

Implementation evidence:

- P13.1 HR-first shell gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase8_automated_uat.py`, and
  `.\run_app.cmd -CheckOnly`.
- Architecture and transaction review completed on 2026-07-14 in
  `docs/reviews/phase-13-hr-first-architecture.md`.
- The P13.1 shell is treated as an exploratory baseline. No additional workflow
  implementation proceeds before P13.0 blockers are remediated.
- P13.0-A through P13.0-D and P13.0-H passed service, security, reporting,
  Streamlit UAT, launcher, and operational-decision gates on 2026-07-14. Named
  actor identity, atomic schedule writes, safe schedule
  cancellation/correction, derived exam eligibility, and explicit evaluation
  correction reasons are now enforced.

## Problem statement

The Phase 12 interface is operationally correct but still assumes the user knows
technical system concepts such as cohorts, course runs, schedule units, audit
events, and operational data issues. HR users need to start from familiar tasks,
not from database-adjacent nouns.

## Product principles

1. Put common HR tasks before admin record maintenance.
2. Use business language for top-level navigation.
3. Keep technical/admin screens available, but not as the first path.
4. Preserve all Phase 11 service, transaction, audit, and owner-decision gates.
5. Avoid long instructional text; make the next action visible through labels,
   buttons, and status.

## Delivery slices

1. P13.0 identity, transaction, audit, lifecycle, and data-contract foundation.
2. P13.1 HR-first app shell and task start page v2.
3. P13.2 First-time, returning, continuation, and transfer learner journeys.
4. P13.3 Event-time attendance, schedule, and correction journeys.
5. P13.4 Final-result, completion, and monthly-review journeys.
6. P13.5 Guided data follow-up and admin journeys.
7. P13.6 Scenario-based HR UAT and rollout.

Each slice must run `python scripts\phase7_frontend_workflow_check.py`,
`python scripts\phase8_automated_uat.py` when workflow behavior is touched, and
`.\run_app.cmd -CheckOnly` before commit.

P13.0 additionally requires disposable-database transaction and failure-
injection tests for each affected business event. UI smoke checks alone are not
an integrity gate.

## P13.1 scope

- Rename the shell from an operations workspace to an HR workspace.
- Replace technical first-screen metrics with HR-facing status labels.
- Add a `Start here` task area with direct entry points for common HR work.
- Move setup/admin record maintenance behind `Class setup` and `Admin records`.
- Keep existing service calls, forms, and transaction behavior unchanged.

## Acceptance notes

- Phase 13 preserves canonical grains and owner decisions. Targeted migrations
  may be proposed when needed for idempotency or complete correction history;
  each requires migration review and rollback evidence.
- Technical records remain accessible for admin users.
- The running app remains available at `http://127.0.0.1:8501`.
- The full architecture, transaction contract, workflows, blockers, and gates
  are defined in `docs/reviews/phase-13-hr-first-architecture.md`.
