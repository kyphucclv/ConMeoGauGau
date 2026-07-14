# Phase 13 HR-first UX specification

Status: **Started after Phase 12 polish exposed non-technical usability risk**

Baseline commit: `712d6fb phase12 polish evaluation workflow`

Start date: 2026-07-14

Implementation evidence:

- P13.1 HR-first shell gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase8_automated_uat.py`, and
  `.\run_app.cmd -CheckOnly`.

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

1. P13.1 HR-first app shell and task start page.
2. P13.2 Learner journey wording and guided add/transfer flow.
3. P13.3 Attendance flow wording and session selection simplification.
4. P13.4 Monthly review as the default manager-facing review path.
5. P13.5 Data follow-up wording and owner-action simplification.

Each slice must run `python scripts\phase7_frontend_workflow_check.py`,
`python scripts\phase8_automated_uat.py` when workflow behavior is touched, and
`.\run_app.cmd -CheckOnly` before commit.

## P13.1 scope

- Rename the shell from an operations workspace to an HR workspace.
- Replace technical first-screen metrics with HR-facing status labels.
- Add a `Start here` task area with direct entry points for common HR work.
- Move setup/admin record maintenance behind `Class setup` and `Admin records`.
- Keep existing service calls, forms, and transaction behavior unchanged.

## Acceptance notes

- Phase 13 does not change database design or owner decisions.
- Technical records remain accessible for admin users.
- The running app remains available at `http://127.0.0.1:8501`.
