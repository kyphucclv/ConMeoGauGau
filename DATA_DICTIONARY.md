# English Class Data Dictionary

Status: **Canonical v3 implemented; Phase 11 additions identified**

This document defines the business meaning and source of truth for each field.
Fields marked `derived` must be calculated from source records and must not be
manually edited.

## Field classes

| Class | Meaning |
|---|---|
| `input` | Entered or confirmed by an admin. |
| `reference` | Controlled lookup value. |
| `snapshot` | Value copied at an event time for historical reporting. |
| `derived` | Calculated from source records. Never manually maintained. |
| `audit` | System-generated history metadata. |

## employees

One row per known employee. Learners belong here. A PIC may reference an
employee, but Phase 11 also permits a free-text team label without an employee
record.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `employee_id` | bigint | audit | yes | Internal immutable key. |
| `emp_code` | text | input | yes | Company employee code; unique and stable if the employee returns. |
| `full_name` | text | input | yes | Current employee name. Not used as an identifier. |
| `employment_status` | enum | input | yes | `Employed` or `Resigned`. Resign is not a course drop reason. |
| `created_at` | timestamptz | audit | yes | Creation timestamp. |
| `updated_at` | timestamptz | audit | yes | Last confirmed update timestamp. |

## employee_org_history

One row per observed BU/role assignment. Exact HR effective dates are not
available, so `recorded_at` means when the admin learned about the change.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `org_history_id` | bigint | audit | yes | Internal key. |
| `employee_id` | bigint FK | input | yes | Employee. |
| `business_unit` | text/FK | input | yes | BU observed at that time. |
| `job_role` | text/FK | input | yes | Employee role observed at that time. |
| `recorded_at` | timestamptz | audit | yes | Time the change was recorded. |
| `is_current` | boolean | derived | yes | Exactly one current row per employee. |

## cohorts

One row per stable learning team, such as `EL001`. A cohort can study several
courses sequentially and can repeat a course.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `cohort_id` | bigint | audit | yes | Internal key. |
| `class_code` | text | input/system | yes | Stable unique code, auto-generated but editable before use. |
| `status` | enum | input | yes | `Forming`, `Active`, `Paused`, `Completed`, `Archived`. |
| `capacity` | integer | input | Phase 11 | Expected maximum active learners; exceeding it requires an audited override. |
| `created_at` | timestamptz | audit | yes | Cohort creation time. |

Display names such as `EL001 - Anh Vu` are derived from `class_code` and the
current PIC. They are not stored as cohort identifiers.

## cohort_pic_assignments

One row per PIC assignment period. The current PIC is the assignment without
an end timestamp. A PIC may be an employee or a normalized free-text team
label.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `pic_assignment_id` | bigint | audit | yes | Internal key. |
| `cohort_id` | bigint FK | input | yes | Cohort being represented. |
| `employee_id` | bigint FK | input | conditional | PIC employee; null when a team label is used. |
| `pic_label` | text | input | conditional | PIC/team display label; required when `employee_id` is null. |
| `assigned_at` | timestamptz | input/audit | yes | Assignment start. |
| `ended_at` | timestamptz | input | no | Assignment end. |

Exactly one of employee identity or a nonblank PIC label must be supplied.
Labels are trimmed and compared case-insensitively for suggestions and duplicate
prevention while preserving display casing.

## cohort_memberships

One row per continuous membership period. Joining, leaving, and transferring
never overwrite old membership records.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `membership_id` | bigint | audit | yes | Internal key. |
| `cohort_id` | bigint FK | input | yes | Cohort. |
| `employee_id` | bigint FK | input | yes | Learner. |
| `joined_at` | date | input | yes | Date joined. |
| `left_at` | date | input | no | Date left/transferred. |
| `status` | enum | input | yes | `Active`, `Transferred`, `Left`, `Completed`. |
| `transfer_to_cohort_id` | bigint FK | input | no | Destination cohort when transferred. |

## courses

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `course_id` | bigint | audit | yes | Internal key. |
| `course_name` | text | reference | yes | Controlled course name. |
| `expected_session_units` | smallint | reference | yes | Expected credited one-hour units. |
| `attendance_threshold_ratio` | numeric | reference | yes | Required attendance ratio; configurable without schema changes. |
| `is_active` | boolean | reference | yes | Whether new runs can use the course. |
| `created_at` | timestamptz | audit | Phase 11 | Course creation time used by the monthly new-course KPI. |

## course_runs

One row per time a cohort studies a course. `EL001 / Communication 1 / Run 2`
is different from Run 1.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `course_run_id` | bigint | audit | yes | Internal key. |
| `cohort_id` | bigint FK | input | yes | Cohort. |
| `course_id` | bigint FK | input | yes | Course. |
| `run_number` | smallint | system | yes | Sequence for repeated cohort/course runs. |
| `start_date` | date | input | yes | Admin-confirmed run start, not MIN(attendance date). |
| `completed_at` | date | input | no | Completion/final-test date. |
| `status` | enum | input/system | yes | `Planned`, `Active`, `Final evaluation`, `Completed`, `Cancelled`. |
| `expected_session_units` | smallint | snapshot | yes | Course plan copied for this run. |
| `attendance_threshold_ratio` | numeric | snapshot | yes | Eligibility rule copied for this run. |

The system may suggest completion after evaluations are entered, but an admin
confirms the final transition.

## run_enrollments

One row per learner in one course run. BU/role are snapshotted here so historic
reports do not change when the employee later changes organization.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `enrollment_id` | bigint | audit | yes | Internal key. |
| `course_run_id` | bigint FK | input | yes | Course run. |
| `employee_id` | bigint FK | input | yes | Learner. |
| `membership_id` | bigint FK | input | yes | Cohort membership at enrollment. |
| `joined_at` | date | input | yes | Date joined this run. |
| `start_session_number` | smallint | input | yes | First applicable session in the target run. |
| `status` | enum | input/system | yes | See enrollment statuses below. |
| `bu_snapshot` | text/FK | snapshot | yes | BU when enrollment started. |
| `role_snapshot` | text/FK | snapshot | yes | Role when enrollment started. |
| `exit_reason` | text/FK | input | no | Course exit reason; never `Resign`. |
| `transferred_from_enrollment_id` | bigint FK | input | no | Previous enrollment when transferred. |

Sessions before `start_session_number` have no attendance record and are
`Not applicable`, not `Absent`.

An employee may have at most one active run enrollment across all courses. BU
and role snapshots are copied automatically from the current organization row
when enrollment starts. HR edits organization data only in employee history;
snapshots are not a parallel input.

Enrollment statuses: `Active`, `Completed`, `Completed - no continuation`,
`Transferred`, `Withdrawn`, `Not eligible for final test`, and
`Waiting for next course`.

## meetings

One row per scheduled/actual class meeting. Schedule changes update the current
meeting; the general audit log records actor, reason, and old/new values.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `meeting_id` | bigint | audit | yes | Internal key. |
| `course_run_id` | bigint FK | input | yes | Run. |
| `starts_at` | timestamp | input | yes | Approved date and time. |
| `duration_minutes` | smallint | input | yes | Actual/planned duration, including 2-3 hour final tests. |
| `meeting_type` | enum | input | yes | `Class` or `Final test`. |
| `status` | enum | input | yes | `Planned`, `Completed`, `Cancelled`. |

Cancelled meetings are excluded from attendance denominators.

## session_units

One row per credited one-hour unit. One meeting may contain at most two normal
session units. Duration and credited units are separate concepts.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `session_unit_id` | bigint | audit | yes | Internal key. |
| `course_run_id` | bigint FK | input | yes | Run. |
| `meeting_id` | bigint FK | input | yes | Meeting containing the unit. |
| `session_number` | smallint | input/system | yes | Sequence within the run. |
| `unit_type` | enum | input | yes | `Teaching` or `Final test`. |

## attendance

One row per enrollment and applicable session unit.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `attendance_id` | bigint | audit | yes | Internal key. |
| `enrollment_id` | bigint FK | input | yes | Learner/run enrollment. |
| `session_unit_id` | bigint FK | input | yes | Credited session. |
| `status` | enum | input | yes | Only `Present` or `Absent`. |
| `is_makeup` | boolean | input | yes | Present credit came from a make-up class. |
| `note` | text | input | no | Optional correction/make-up explanation. |
| `updated_by` | bigint FK | audit | yes | App user who last confirmed the result. |
| `updated_at` | timestamptz | audit | yes | Last update timestamp. |

A make-up changes the effective status to `Present`. The audit log preserves
the previous `Absent` value and the reason for transparency.

The Phase 11 attendance grid defaults every applicable roster row to `Present`;
this is a UI default, not a database default. Only an explicit bulk save writes
attendance rows.

## placements

Exactly one business placement per learner. Corrections are audited; a second
placement attempt is not part of the current process.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `placement_id` | bigint | audit | yes | Internal key. |
| `employee_id` | bigint FK | input | yes | Learner. |
| `test_date` | date | input | yes | Placement date. |
| `level_id` | bigint FK | input | yes | Entrance level. |
| `grammar_feedback` | text | input | no | Placement feedback. |
| `vocabulary_feedback` | text | input | no | Placement feedback. |
| `pronunciation_feedback` | text | input | no | Placement feedback. |
| `fluency_feedback` | text | input | no | Placement feedback. |

## evaluations and evaluation_versions

An evaluation is attached to an enrollment. Every edit creates a version;
old results are never overwritten.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `evaluation_id` | bigint | audit | yes | Stable evaluation identity. |
| `enrollment_id` | bigint FK | input | yes | Evaluated run enrollment. |
| `version_number` | integer | audit | yes | Increasing version. |
| `final_level_id` | bigint FK | input | no | Final level; null when not eligible. |
| `passed` | boolean | input | yes | Teacher's pass decision. |
| `eligible_for_next_course` | boolean | input | yes | Teacher recommendation. |
| `evaluated_at` | date | input/system | yes | Run completion date when no separate date exists. |
| `change_reason` | text | input | required on correction | Why an existing result changed. |
| `created_by` | bigint FK | audit | yes | App user. |
| `created_at` | timestamptz | audit | yes | Version creation time. |

## levels

The current spreadsheet scale is retained as a controlled ordinal scale:
`Not Placement = 0.0` through `Advanced = 6.5` in 0.5 increments.

| Field | Type | Class | Required | Meaning / rule |
|---|---|---|---|---|
| `level_id` | bigint | audit | yes | Internal key. |
| `level_name` | text | reference | yes | Unique label. |
| `numeric_value` | numeric(3,1) | reference | yes | Ordered comparison value. |
| `sequence` | smallint | reference | yes | Stable display/progression order. |
| `is_active` | boolean | reference | yes | Whether it can be newly selected. |

## Derived progress fields

These are views/queries, never editable columns:

| Field | Definition |
|---|---|
| `entrance_level` | The learner's single placement level. |
| `current_level` | Final level from the latest valid evaluation. |
| `highest_level` | Maximum final level reached across valid evaluation versions. |
| `current_progress` | Current numeric level minus placement numeric level. |
| `peak_progress` | Highest numeric level minus placement numeric level. |
| `regression_flag` | Latest final level is lower than the preceding final level. |
| `progress_trajectory` | Ordered placement + final evaluations over time. |
| `last_active_at` | Latest `Present` attendance meeting. |
| `attendance_ratio` | Applicable present units / applicable non-cancelled units. |
| `sessions_per_month` | Credited session units in completed meetings per calendar month. |

## Spreadsheet fields to deprecate

| Current field | Target treatment |
|---|---|
| `STUDENTS.Status` | Replace with employment, membership, enrollment, and run statuses. |
| `STUDENTS.PIC` | Derive from current cohort PIC assignment. |
| `Current Course` / `Latest Class Code` | Derive from active/latest enrollment. |
| `Current Level` | Replace with clearly named `current_level` and `highest_level`. |
| `Last Active Date` / `Days Since Active` | Derive from attendance and current date. |
| `Drop Flag` | Derive from enrollment status and attendance rules. |
| Numeric/group/progress helper columns | Derive from levels and evaluations. |
| `sheet2.Full Name`, `PIC`, `Role`, `BU` | Use employee joins; retain BU/Role enrollment snapshots only. |
| `sheet2.start date` | Replace formula MIN date with admin-confirmed run start date. |
| `First Class Start Date` | Remove; no current business use. |
| `Is_Unique_Row` and pivot/helper columns | Remove from production data. |
| `ATTENDANCE_LOG.Full Name`, `PIC` | Derive through relationships. |
| `CLASS_DATES` | Replace with course runs and meetings. |
