# Phase 12 UX/UI polish specification

Status: **Started from Phase 11 release-ready baseline**

Baseline tag: `phase-11-ready`

Start date: 2026-07-14

Implementation evidence:

- P12.1 app shell gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase8_automated_uat.py`, and
  `.\run_app.cmd -CheckOnly`.
- P12.2 learner workspace gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase8_automated_uat.py`, and
  `.\run_app.cmd -CheckOnly`.

## Objective

Refine the Streamlit application into a calmer desktop operations workspace for
HR users without changing the approved Phase 11 database model, transactions, or
rollout decisions.

Phase 12 is a usability pass. Schema, ETL, and service-layer behavior may only
change when a UI walkthrough exposes a concrete business bug, and every such fix
must include a focused regression gate.

## Product principles

1. Keep the first screen operational, not explanatory.
2. Prefer visible status, searchable grids, and direct workflow actions.
3. Reduce heavy instructional text; keep only labels, state, and actionable
   validation.
4. Keep desktop density high enough for repeated HR use.
5. Preserve all Phase 11 audit, transaction, and snapshot guarantees.

## Delivery slices

1. P12.1 application shell and operational status bar.
2. P12.2 learner workspace layout polish and action grouping.
3. P12.3 attendance roster ergonomics and exception review polish.
4. P12.4 data issues remediation layout and audit confidence.
5. P12.5 monthly review export flow and report readability.

Each slice must run `python scripts\phase7_frontend_workflow_check.py`,
`python scripts\phase8_automated_uat.py` when workflow behavior is touched, and
`.\run_app.cmd -CheckOnly` before commit.

## P12.1 scope

- Add an app-level status bar for active employees, active learners, open course
  runs, operational issues, high-severity issues, and open quality issues.
- Replace the heavy sidebar success callout with lightweight user/baseline
  metadata.
- Add Material Symbol icons to top-level navigation tabs.
- Keep reports and audit tables index-free for cleaner scanning.

## P12.2 scope

- Split the learner workspace into explicit modes: find learner, add learner,
  and create class.
- Keep the find mode focused on search, filters, result counts, and selected
  learner detail.
- Add quick action buttons from search results into add/create modes.
- Remove heavy dividers and always-visible secondary forms from the learner
  search flow.

## Acceptance notes

- Phase 12 does not approve or close legacy operational findings.
- The production operational issue snapshot remains governed by
  `docs/reviews/phase-11-owner-decision-template.json`.
- Owner visual review can continue in the running app at
  `http://127.0.0.1:8501`.
