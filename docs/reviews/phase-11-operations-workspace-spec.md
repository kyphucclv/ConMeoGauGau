# Phase 11 operations workspace specification

Status: **Owner approved - implementation verified; production rollout gated by legacy data issue resolution**

Owner approval date: 2026-07-13

Implementation evidence:

- P11.1 learner transaction gate passed on 2026-07-14 through
  `python scripts\phase11_p11_1_integration.py`.
- P11.2 learner workspace gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py` and
  `python scripts\phase8_automated_uat.py`.
- P11.3 attendance roster gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase11_p11_1_integration.py`, and
  `python scripts\phase8_automated_uat.py`.
- P11.4 monthly review gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py` and
  `python scripts\phase8_automated_uat.py`.
- P11.5 data issues workspace gate passed on 2026-07-14 through
  `python scripts\phase7_frontend_workflow_check.py`,
  `python scripts\phase8_automated_uat.py`, and
  `$env:PHASE11_DB='english_class'; python scripts\phase11_operational_issue_snapshot.py --validate-decisions`.
- End-to-end UAT and rollout evidence is tracked in
  `docs/reviews/phase-11-uat-and-rollout.md`.

## Product outcome

Replace the three-sheet, script-assisted operating workflow with one desktop
application where HR records each business event once. The canonical database
remains the source of truth; the UI must be organized around HR tasks rather
than database tables.

The current Phase 7 UI proves the service and reporting paths but is not the
accepted spreadsheet-replacement experience. Phase 11 is the product workflow
and usability pass.

## Users and access

- Two HR users operate the application on desktop computers.
- Both HR users have full application permissions.
- Database migration and read-only roles remain separate from application
  permissions.
- Manager access is initially delivered through a monthly report, not a
  separate manager account.

## Product principles

1. Record one business event once; derived and related records update in one
   transaction.
2. Prefer searchable grids, bulk actions, and inline validation over isolated
   one-record forms.
3. Never require HR to know a database identifier or run an ETL script for
   normal operations.
4. Preserve history for transfers, organization changes, schedule edits, and
   attendance corrections.
5. Prevent inconsistency through one editable source of truth, not formulas
   copied across screens.
6. Keep Excel export available, but make direct application entry the primary
   workflow.

## Navigation

Build four task-oriented workspaces in this order:

1. **Learners** - employee lookup, inline employee creation, placement,
   enrollment, transfer, and learner history.
2. **Attendance** - class/session selection, roster entry, correction, and
   immediate attendance metrics.
3. **Monthly review** - manager KPIs, charts, highlights, risks, and priorities.
4. **Data issues** - missing, conflicting, duplicate, and override-required
   operational records.

## Learner workspace

### Search and overview

HR can search by employee code or name and filter by class code, course, PIC,
BU, role, and active status. The result grid shows the employee's current class,
course, PIC, entrance level, attendance rate, and enrollment status.

Selecting a learner opens one unframed detail workspace with current assignment,
placement, attendance summary, course history, evaluations, and audit history.

### Add learner transaction

1. HR enters an employee code or name.
2. The system searches the employee directory.
3. When found, the system fills current name, BU, and role.
4. When not found, HR can create the employee inline by entering employee code,
   name, BU, and role.
5. HR selects or enters PIC, class code, course, and entrance level.
6. The system validates capacity and verifies that the employee has no other
   active course enrollment.
7. One save creates or updates the employee directory record, organization
   history, placement, cohort membership, and run enrollment as applicable.
8. Any failure rolls back the full operation.

The learner appears in the attendance roster immediately. There is no separate
attendance-input registration step.

### Employee source of truth

- `employees` owns employee code and current name.
- `employee_org_history` owns BU and role over time.
- HR edits employee identity and organization data in one place only.
- Enrollment BU/role snapshots are system-created, immutable event-time values;
  they are never a second HR input.
- Employee code is stable after creation. A correction requires a dedicated,
  audited command rather than an ordinary inline edit.

### PIC behavior

- PIC may be a free-text team label and does not have to be an employee.
- The input provides autocomplete from previously used PIC labels.
- Leading/trailing and repeated whitespace is normalized.
- Duplicate checks are case-insensitive while the chosen display casing is
  retained.

### Capacity override

- The class capacity and current active learner count are visible before save.
- At capacity, save is blocked until HR explicitly selects override and enters
  a reason.
- The override, actor, reason, previous capacity, and resulting count are
  audited.

### Transfer

- A transfer closes the prior membership/enrollment and preserves all history.
- The target enrollment starts at the target class's next not-yet-delivered
  session.
- If no future session is scheduled, the proposal is one greater than the last
  delivered logical session.
- HR sees and confirms the proposed start session before saving.
- Attendance applicability begins at the confirmed target session; earlier
  target sessions are not absent.

## Class and course behavior

- Class codes are stable cohort identifiers such as `EL034`.
- The application proposes the next sequential class code; HR can edit it
  before first use.
- One class may take several courses sequentially under the same class code.
- Each class/course occurrence is a separate course run with its own schedule,
  enrollments, attendance, evaluations, and lifecycle.
- One learner cannot have two active course-run enrollments at the same time.
- Creating a class requires class code, course, PIC, start date, expected
  sessions, and capacity.
- A class can be created before its detailed meeting schedule is known.

## Attendance workspace

### Entry workflow

1. HR selects class and active course run.
2. HR selects an existing session or creates the next session.
3. HR confirms one date and time shared by the full roster.
4. Every applicable learner defaults to `Present`.
5. HR changes absent learners to `Absent`.
6. One bulk save validates and writes the full roster transactionally.
7. Updated attendance counts and rates appear immediately.

Only `Present` and `Absent` are supported. A person who is not on the applicable
roster cannot receive attendance.

### Schedule correction

- HR may directly edit the date/time of a scheduled or delivered session.
- Editing a session with attendance requires confirmation.
- Existing attendance remains attached to the session occurrence.
- Old and new schedule values, actor, time, and reason are retained in audit.
- Duplicate class/run/session/date combinations are rejected.

### Attendance correction

- Historical attendance remains editable by both HR users.
- The previous value, new value, actor, timestamp, and optional note are audited.
- Low attendance defaults to below `80%` and remains configurable per course
  run later.

## Monthly review

The report uses one selected calendar month with previous/next month controls.

### Program status

- active classes by course;
- unique active participants;
- repeated participants;
- planned sessions;
- delivered sessions;
- planned-to-delivered variance.

An active participant has an active enrollment in a course run that has not
ended. A repeated participant has at least two lifetime course-run enrollments
and is currently active.

Planned sessions are configured expectations. Delivered sessions are distinct
logical sessions with actual delivery evidence. They are never combined into
one ambiguous metric.

### Participation

- overall attendance rate;
- attendance rate by course;
- attendance rate by class and course;
- percentage and count of active learners below the applicable attendance
  threshold.

### Learning progress

- level distribution by course;
- participant progress distribution;
- percentage of learners whose latest test improved over their preceding test;
- courses created during the selected month.

Improvement compares the two latest valid tests, not placement versus final.
Course creation time must therefore be retained as reportable data.

### Action summary

The system proposes rule-based highlights, risks, and next-month priorities from
the visible KPIs. HR reviews and edits the text before export. Initial output is
an on-screen dashboard plus Excel export; PDF can follow after the monthly
layout is accepted.

## Data issues workspace

Show actionable operational issues rather than raw database errors:

- incomplete employee identity or organization data;
- duplicate employee code candidates;
- conflicting active enrollment;
- missing placement or entrance level;
- session date/time conflict;
- incomplete attendance roster;
- low attendance requiring follow-up;
- capacity override;
- transfer awaiting confirmation.

Each issue links directly to the corrective workflow and records resolution.

## UX acceptance criteria

- Adding a learner requires one save and no duplicate entry in another screen.
- A full class roster can be recorded from one grid without running a script.
- Employee and attendance search is available by the fields HR actually uses.
- Common bulk workflows use sensible defaults and remain keyboard-efficient.
- Validation appears before commit and identifies the exact row/field to fix.
- Every override and historical correction is attributable to an HR user.
- The monthly report is reproducible from canonical data for any selected month.
- All core workflows are optimized for desktop; mobile support is not required
  for Phase 11.

## Delivery slices

1. P11.1 learner service commands and source-of-truth constraints.
2. P11.2 learner search, add, edit, capacity override, and transfer workspace.
3. P11.3 attendance roster service and grid workspace.
4. P11.4 monthly KPI definitions, views, charts, and editable action summary.
5. P11.5 data issues inbox, workflow UAT, and production rollout.

Each slice requires a migration review when schema changes are needed,
transaction/service tests, Streamlit workflow tests, and direct inspection of
production-shaped fixture data before rollout.
