# Issue #8 Final-result Authorization Evidence

Date: 2026-07-15
Status: approved

## Contract and grain

One `evaluations` row is the stable final-result identity for one run
enrollment. Each `evaluation_versions` row is an immutable, increasing version
of that result. React addresses the run enrollment and never calculates or
submits trusted eligibility, actor identity, or version numbers.

The read interface returns the review queue plus authoritative enrollment,
eligibility, history, completion, and reference-option context. The write
interfaces record/correct a complete result, create an admin override, or apply
an explicit completion action.

## Authorization, transaction, and conflict behavior

- Admin and editor can read and record results; version 2+ requires a non-blank
  correction reason. The server locks and assigns the next version.
- Only admin can override eligibility. The override requires an explicit value
  and reason and carries current result fields into the new version.
- Admin and editor can suggest completion. Only admin can confirm or reject;
  rejection requires a reason and preserves the active enrollment.
- Successful writes retain named-user audit attribution. Unauthorized, forged,
  incomplete, duplicate, missing-CSRF, invalid-state, and concurrent writes
  roll back without partial versions or lifecycle changes.

## Journey and parity

- React presents pending outcomes first, then loads one coherent
  run-enrollment workspace with attendance-derived eligibility and history.
- The same workspace records or corrects the result, allows an admin override,
  and moves completion through suggestion and final authorization.
- Historical versions display their own calculated/override eligibility rather
  than projecting the current effective value backward.

## Verification

- Targeted backend: 15 evaluation and authorization tests passed, including
  role, CSRF, forged input, attendance-derived eligibility, immutable history,
  rollback, audit, lifecycle, and concurrent-first-write behavior.
- React: 8 tests passed; production TypeScript/Vite build passed.
- Playwright: 2 journeys passed; the admin journey records a result, creates an
  eligibility override, suggests completion, and confirms it without a page
  reload. The viewer journey confirms that final-result navigation is hidden.
- Manual browser review passed for admin sign-in, navigation, summary cards,
  correction/override/completion forms, and version-specific history layout.
- Full gate run passed: 74 Python tests, OpenAPI drift check, 8 React tests,
  production build, 2 Playwright journeys, Phase 13 dictionary validation,
  Phase 8 UAT, Phase 9 cutover rehearsal, Phase 10 sign-off, and Phase 11
  decision gate. Production-like reconciliation retained 365 employees, 552
  run enrollments, and 6,281 attendance rows from the approved snapshot.

## Review decision

- [x] Approved
- [ ] Changes required
