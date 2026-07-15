# Issue #4 Learner Start Evidence

Date: 2026-07-15
Status: implemented and verified

## Contract and grain

One `run_enrollments` row represents exactly one employee enrolled in one
course run. One `cohort_memberships` row represents one employee membership
period in one cohort. One business placement represents the employee's reusable
entrance placement; one capacity override represents one approved admission
above cohort capacity.

The HTTP interface exposes one narrow options read and one confirmed business
event. It never accepts enrollment snapshots, lifecycle classification,
projected counts, or audit attribution from the browser.

## Transaction and conflict behavior

- `onboard_learner` remains the deep module and sole transaction owner for
  first-time, returning, continuation, and rejoin cases.
- The destination run is locked before recalculating the first applicable
  session. HTTP confirmations require an exact match; changed proposals fail
  with `stale_proposal` before any employee or learner write.
- A required nullable employee precondition distinguishes a confirmed new
  employee from a selected canonical employee and rejects code/ID drift.
- Existing active-enrollment, active-membership, placement, lifecycle, and
  capacity rules remain server-owned. Failed confirmations roll back employee,
  organization, placement, membership, enrollment, override, and audit writes.
- Above-capacity membership creation requires a normalized reason and records
  both the capacity override and named-actor audit. Continuation that reuses a
  membership does not invent an override.

## React journey

- HR can start a new learner from the directory or start/continue an inactive
  existing learner from detail. Active learners do not receive the start action.
- The confirmation shows class, course, calculated first session, and projected
  class size. The capacity reason appears only when the selected start would
  create an above-capacity membership.
- Success refetches the affected learner, displays the resulting journey and
  audit event, and invalidates dashboard data.

## Verification

- `python -m pytest tests/ -q`: 50 tests passed. The new HTTP integration cases
  cover save/refetch, canonical identity, stale proposal rollback, reasoned
  capacity override, named actor, authorization, CSRF, and forbidden fields.
- `npm test`: 4 tests passed, including the complete confirmation and refetch.
- `npm run build`: production Vite/TypeScript build passed.
- `npm run test:e2e`: 2 Chrome tests passed; the admin journey edits a profile,
  starts a new learner, sees the refreshed detail and named audit action, while
  viewer navigation remains restricted.
- Manual connected-Chrome review confirmed the desktop form, active reference
  options, destination summary, exact first session, projected class size,
  conditional capacity-reason field, enabled confirmation, and safe Cancel.
- `scripts/run-all-gates.ps1`: every OpenAPI, React, Playwright, dictionary,
  UAT, cutover, sign-off, and decision gate passed. Phase 9 reconciled 365
  employees, 552 run enrollments, and 6,281 attendance rows with zero open
  quality issues; stable operational snapshot `d79985c7...` was preserved.

## Review decision

- [x] Approved
- [ ] Changes required
