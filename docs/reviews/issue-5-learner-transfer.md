# Issue #5 Learner Transfer Evidence

Date: 2026-07-15
Status: approved

## Contract and grain

One source `run_enrollments` row remains the historical enrollment in its
course run. One new target enrollment links back through
`transfer_from_enrollment_id`. The source cohort-membership period closes and
links to one new target membership period. Existing attendance stays addressed
to the historical source enrollment; target BU/role snapshots are copied once
from current organization state.

The HTTP path is the active `run_enrollment_id`, never employee name or employee
ID alone. The browser cannot submit employee, membership, snapshot, lifecycle,
projected-count, or audit fields.

## Transaction and conflict behavior

- `transfer_learner` remains the sole transaction owner. It locks the target
  run, validates lifecycle, recalculates the first applicable session, and then
  locks/revalidates the active source enrollment and membership.
- Same-class moves are rejected and stay owned by continuation. Inactive source,
  changed proposal, closed target, capacity without reason, and safe retry all
  fail without partially closing source history.
- Success closes and links source records, creates target records, copies
  current organization snapshots, and records `learner.transfer` with the
  canonical employee and named session actor.
- Above-capacity transfer creates exactly one reasoned override and its audit
  event. A retry after success is a deterministic conflict and cannot create a
  second target enrollment or override.

## React journey

- Active learner detail exposes `Transfer learner`; inactive learners retain
  the separate start/continue journey.
- The transfer form shows canonical source class/course and only cross-class
  planned/active destinations. Confirmation shows target class/course,
  calculated first session, and projected size; capacity reason is conditional.
- Success refetches the affected learner, preserves both history rows, displays
  named audit history, and invalidates dashboard data.

## Verification

- `python -m compileall api services tests -q`: passed.
- `python -m pytest tests/test_api_learner_transfer.py -q`: 5 tests passed,
  covering success/reconciliation, stale-proposal rollback, reasoned capacity
  override and safe retry, authorization/CSRF/field protection, and concurrent
  transfer serialization.
- Full Python suite: 55 tests passed.
- `npm test`: 5 tests passed, including transfer confirmation and targeted
  learner refetch.
- `npm run build`: production Vite/TypeScript build passed.
- OpenAPI generation and drift check passed.
- Playwright: 2 journeys passed, including start followed by transfer and named
  audit-history reconciliation.
- Manual Chrome review passed for source/destination clarity, calculated first
  session, projected capacity, disabled/enabled confirmation, desktop layout,
  and cancel-without-write behavior.
- Phase 8 UAT, Phase 9 cutover rehearsal, Phase 10 quality sign-off, Phase 11
  decision gate, and Phase 13 dictionary check all passed.

## Review decision

- [x] Approved
- [ ] Changes required
