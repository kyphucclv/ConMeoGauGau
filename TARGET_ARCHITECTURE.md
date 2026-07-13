# Target Data Architecture

Status: **Approved business design - implementation pending**

## Core relationship

```text
employees
  +-- employee_org_history
  +-- placements
  +-- cohort_memberships -- cohorts -- cohort_pic_assignments
  +-- run_enrollments -- course_runs -- courses
                           +-- meetings -- session_units -- attendance
  +-- evaluations (versioned)
```

## Grain contract

| Entity | Exactly one row means |
|---|---|
| Employee | One known company employee. |
| Employee org history | One observed BU/role period. |
| Cohort | One stable team/class code across courses. |
| Cohort membership | One continuous employee membership period in a cohort. |
| PIC assignment | One PIC assignment period for a cohort. |
| Course | One reusable course definition. |
| Course run | One cohort taking one course one time. |
| Run enrollment | One learner participating in one course run. |
| Meeting | One scheduled/actual gathering. |
| Session unit | One credited instructional unit within a meeting. |
| Attendance | One enrollment's result for one applicable session unit. |
| Placement | One learner's initial placement. |
| Evaluation version | One immutable version of a course-final result. |

## Business invariants

1. `emp_code` and `class_code` are stable identifiers; names are not keys.
2. A cohort can study many courses and can repeat a course using a new run.
3. A learner may join a run mid-course. Earlier units are not applicable.
4. A transfer closes the old enrollment and creates a target enrollment.
5. Attendance has only effective `Present`/`Absent`; make-up corrections are audited.
6. Cancelled meetings are excluded from attendance eligibility.
7. Exam eligibility is derived from an attendance ratio and can be overridden
   by an admin with a required reason.
8. Pass and next-course eligibility are teacher evaluation decisions.
9. Evaluation corrections create immutable versions.
10. Course completion is suggested by the system and confirmed by an admin.
11. Historic BU/role reporting uses enrollment snapshots.
12. Current level, highest level, and progress trajectory are separate metrics.

## Status ownership

| Status family | Owned by | Why |
|---|---|---|
| Employment | Employee | Whether the person still works for the company. |
| Cohort | Cohort | Team lifecycle independent of one course. |
| Membership | Cohort membership | Join/leave/transfer history. |
| Course run | Course run | Planned through completed course delivery. |
| Enrollment | Run enrollment | Individual outcome in a run. |
| Meeting | Meeting | Planned/completed/cancelled schedule. |

There is intentionally no single overloaded `student_status` field.

## Attendance eligibility

```text
applicable units = non-cancelled session units
                   on/after enrollment.start_session_number

attendance ratio = present applicable units / applicable units

exam eligible = attendance ratio >= run.attendance_threshold_ratio
                OR approved admin override
```

The exact threshold value remains configurable business data, not hard-coded
application logic.

## Progress model

Progress is an ordered event stream rather than one mutable value:

```text
placement -> final evaluation 1 -> final evaluation 2 -> ...
```

This supports linear trajectory reporting while retaining regressions. The
latest result answers current ability; the maximum result answers peak ability.

## Schedule model

PICs currently register schedules outside the system. After approval, an admin
enters meetings. A normal meeting may carry one or two session units. Final-test
duration is stored in minutes and does not automatically inflate teaching
session frequency.

## Legacy migration policy

1. Preserve every source row in staging/legacy tables with source sheet and row.
2. Import valid records into target tables.
3. Send ambiguous rows to `data_quality_issues`; never silently drop them.
4. Exclude unresolved structural anomalies from new schedule-dependent KPIs.
5. Keep original attendance order/date/status for manual resolution.

Known initial issues include three attendance rows without dates, seven EL052
enrollment rows without a course, attendance without enrollment matches, and
class/session/date combinations that do not describe one consistent schedule.

## Deferred scope

- True employee learning coverage is deferred until a complete HR roster is
  available as the denominator.
- PIC self-service schedule submission is deferred; admin entry is the first
  supported workflow.
- Advanced attendance states are deferred; effective status remains binary.

## Implementation gate

The existing `001_foundation_v2.sql` and `002_derived_student_state.sql` were
created before this discovery and do not implement this contract. Do not apply
them to production. Replace the draft migration chain only after confirming it
has not already been applied to the target database.

