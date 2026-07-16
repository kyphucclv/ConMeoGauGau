# Issue #11 Classes and Schedule Evidence

Date: 2026-07-16
Status: approved

## Contract and grain

One cohort row is one stable class. One course-run row is one occurrence of one
course for that class. One meeting row is one gathering, while each session-unit
row is one credited logical session; one meeting may create one or two normal
units. The class, current PIC, and first course run are created by one existing
transactional command.

## Commands and concurrency

- Stable, bounded reads cover classes, course runs, and schedule rows with
  HR-facing labels and explicit identities.
- PIC assignment, course-run creation/lifecycle, meeting creation/correction/
  cancellation, and unit addition call the existing domain services.
- Course-run numbering remains advisory-lock protected. Concurrent API creation
  receives distinct run numbers.
- Schedule corrections require reasons when date/time/duration changes and
  retain before/after audit. Cancellation preserves the schedule and units.
- Invalid timezone, role, lifecycle, duplicate sequence, and partial class
  creation fail without partial business records.

## Verification

- Five targeted HTTP integration tests cover atomic creation/rollback, one/two
  units, later unit allocation, correction/cancellation audit, role/validation,
  and concurrent numbering.
- React component coverage creates a class-with-first-run and a two-unit meeting.
- Chrome browser evidence creates a class, creates/corrects/cancels a two-unit
  meeting, verifies the correction form preserves local wall-clock time, and
  confirms the resulting audit journey.
- Full regression: 91 Python tests, 13 React tests, and all four Playwright
  journeys passed; production build plus Phase 5 reporting, Phase 7 workflow,
  and Phase 13 dictionary gates passed.
- Manual desktop review passed for class/PIC forms, lifecycle tables, schedule
  forms, long lists, and horizontal table containment; console was clean.

## Review decision

- [x] Approved
- [ ] Changes required
