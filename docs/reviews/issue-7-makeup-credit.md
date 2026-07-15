# Issue #7 Linked Make-up Credit Evidence

Date: 2026-07-15
Status: approved

## Contract and grain

One `attendance` row is one run enrollment's fact for one session unit. A
make-up row is Present at one `makeup` unit and links to exactly one completed
direct Absent row for the same enrollment. The original row remains Absent and
the linked row adds zero denominator units.

The read interface returns each actionable absence with only its eligible
targets. The write interface accepts only target session-unit identity and a
required reason. Employee identity, actor, before/after status, meeting state,
and denominator meaning remain server-owned.

## Transaction and conflict behavior

- The existing command locks by original attendance, then locks the original
  and target rows before validating original state, same course run, enrollment
  start, unit type, time ordering, meeting state, prior credit, and occupied
  target.
- Success creates one linked Present row, completes a planned target meeting,
  and writes `attendance.makeup` audit detail in the same transaction.
- Duplicate, invalid, cancelled, occupied, forged, unauthorized, missing-CSRF,
  and concurrent submissions leave no partial credit. Two concurrent writers
  produce one success, one `duplicate_makeup`, one linked row, and one audit.

## Reconciliation and journey

- Representative reporting changed from 0/1 present to 1/1 present while
  `applicable_units` stayed 1 and `makeup_present_units` became 1.
- React displays the selected absence and only server-approved target units,
  requires a reason, and explicitly confirms that the original remains Absent
  and denominator impact is zero.
- Success reloads the options and dashboard without a page reload. The
  completed absence disappears from actionable options.

## Verification

- Targeted backend: 16 attendance/make-up tests passed, including HTTP success,
  authorization/CSRF/forged input, cancelled and normal target rejection,
  existing-target collision, audit reconciliation, and concurrent duplicate.
- React: 7 tests passed; production TypeScript/Vite build passed.
- Playwright: 2 journeys passed; the admin journey creates an absence, records
  linked make-up credit, and verifies the post-credit empty state.
- Manual Chrome review passed for navigation, empty state, layout, accessible
  controls, and zero console warning/error output.
- Full gate run passed: 66 Python tests, OpenAPI drift check, 7 React tests,
  production build, 2 Playwright journeys, Phase 13 dictionary validation,
  Phase 8 UAT, Phase 9 cutover rehearsal, Phase 10 sign-off, and Phase 11
  decision gate. Production-like reconciliation retained 365 employees, 552
  run enrollments, and 6,281 attendance rows from the fixed source snapshot.

## Review decision

- [x] Approved
- [ ] Changes required
