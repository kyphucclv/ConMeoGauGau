# Issue #6 Attendance Roster Evidence

Date: 2026-07-15
Status: approved

## Contract and grain

One `meetings` row is one scheduled/delivered occurrence. One `session_units`
row is one credited logical unit within that occurrence. One `attendance` row
is one run enrollment's fact for one session unit. Roster routes therefore use
both course-run and session-unit identity and never accept meeting identity as
the roster grain.

The browser may submit only session time/duration/confirmed sequence, or an
opaque roster token plus enrollment/status pairs. Employee identity, historical
original status, applicability, meeting completion, derived counts, and audit
actor are server-owned.

## Transaction and conflict behavior

- Session creation locks the course run, recalculates the next non-cancelled
  logical sequence, and creates one planned meeting plus one normal unit in one
  transaction. Concurrent/stale proposals cannot create a second sequence.
- Roster reads use enrollment start sequence and event-time membership dates.
  Later transfer/completion does not remove historical applicable learners;
  unknown completed-session facts remain null rather than becoming Present.
- Full save locks the run, unit/meeting, and authoritative enrollments. The
  token covers session status plus roster/recorded facts. Changed membership,
  another attendance save, retry, or double-submit produces `stale_roster`.
- Every applicable enrollment must appear exactly once with Present/Absent.
  Cancelled, incomplete, duplicate, forged, or unauthorized submissions roll
  back without partial facts or meeting completion.
- Success saves all facts, completes a planned meeting, and retains named actor
  plus row-level before/after audit details in the same transaction.

## React journey

- Admin/editor navigation exposes Attendance; viewer navigation and routes do
  not.
- HR selects class/course and credited session, or confirms the server-proposed
  next session before creation.
- New planned rosters propose Present, show live present/absent/missing counts,
  and keep Save disabled while any historical unknown remains unresolved.
- Success refetches the canonical roster/session list and invalidates dashboard
  data without a page reload.

## Verification

- `python -m pytest tests/test_api_attendance.py -q`: 6 tests passed,
  covering success, stale-membership rollback, concurrent save, event-time
  transfer/completion history, protected/invalid inputs, and concurrent session
  creation.
- Full Python suite: 61 tests passed.
- Phase 7 frontend-workflow and Phase 11 learner/attendance integration checks
  passed after making the roster token mandatory for every command caller,
  including the side-by-side Streamlit workflow.
- OpenAPI generation/drift check, 6 React tests, and production build passed.
- Playwright: 2 journeys passed, including session creation and full-roster save.
- Manual Chrome review passed for desktop layout, proposal clarity, historical
  roster, live counts, accessible row labels, and cancel-without-write behavior.
- Phase 8 UAT, Phase 9 cutover rehearsal, Phase 10 quality sign-off, Phase 11
  decision gate, and Phase 13 dictionary check all passed. Production-like
  reconciliation retained 365 employees, 552 run enrollments, and 6,281
  attendance rows from the fixed source snapshot.

## Review decision

- [x] Approved
- [ ] Changes required
