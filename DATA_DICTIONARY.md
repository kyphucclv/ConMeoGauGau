# English Class Data Dictionary

Status: **Canonical v3 reconciled through migrations 001-019**

Last schema validation: 2026-07-14 against the applied `english_class`
database. Physical names and stored values in this document are canonical.
HR-facing labels may be friendlier, but must map to these values at the UI
boundary and must never be written as alternate database values.

## Naming contract

| Layer | Example | Rule |
|---|---|---|
| Physical schema | `run_enrollments.start_session_number` | Used by migrations, services, query modules, tests, and technical docs. |
| HR label | First applicable session | Used in the interface; maps to one physical field or derived value. |
| Derived read model | `attendance_ratio` | Calculated from canonical facts; never maintained as a parallel input. |

## Field classes

| Class | Meaning |
|---|---|
| `input` | Entered or confirmed by an authorized user. |
| `reference` | Controlled lookup value. |
| `snapshot` | Copied at event time and immutable afterward. |
| `derived` | Calculated from source records; never manually maintained. |
| `audit` | System-generated identity, actor, version, or timestamp. |

## Controlled values

Stored values are lower-case unless explicitly shown otherwise.

| Field | Canonical values | Suggested HR labels |
|---|---|---|
| `employees.employment_status` | `active`, `inactive`, `unknown` | Employed, Not active, Needs confirmation |
| `cohorts.status` | `planned`, `active`, `completed`, `archived` | Planned, Active, Completed, Archived |
| `cohort_memberships.status` | `active`, `completed`, `transferred`, `cancelled` | Active, Completed, Transferred, Cancelled |
| `course_runs.status` | `planned`, `active`, `completed`, `cancelled`, `archived` | Planned, Active, Completed, Cancelled, Archived |
| `run_enrollments.status` | `active`, `completed`, `transferred`, `dropped`, `cancelled` | Learning, Completed, Transferred, Withdrawn, Cancelled |
| `meetings.status` | `planned`, `completed`, `cancelled` | Planned, Delivered, Cancelled |
| `session_units.unit_type` | `normal`, `final_test`, `makeup`, `admin` | Class session, Final test, Make-up session, Admin unit |
| `attendance.effective_status` | `Present`, `Absent` | Present, Absent |
| `placements.placement_kind` | `business`, `diagnostic`, `other` | Entrance placement, Diagnostic, Other |

## employees

Grain: one row per known employee. A learner is an employee participating in
the learning lifecycle; learner identity is not duplicated elsewhere.

`employees` physical columns: `employee_id`, `emp_code`, `full_name`, `english_name`,
`email`, `employment_status`, `created_at`, `updated_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `employee_id` | audit | yes | Immutable internal key. |
| `emp_code` | input | yes | Unique company employee code and stable business identity. |
| `full_name` | input | yes | Current full name; never used as a key. |
| `english_name`, `email` | input | no | Optional current profile values. |
| `employment_status` | input | yes | Uses the canonical values above. Resignation is not a course exit reason. |
| `created_at`, `updated_at` | audit | yes | Row creation and last-update timestamps. |

## employee_org_history

Grain: one row per observed BU/role assignment period. At most one row per
employee is current. Saving the same BU and role does not create a new period.

`employee_org_history` physical columns: `employee_org_history_id`, `employee_id`,
`business_unit_id`, `job_role_id`, `valid_from`, `valid_to`, `is_current`,
`observed_from`, `created_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `employee_org_history_id` | audit | yes | Immutable period key. |
| `employee_id` | input | yes | Employee whose assignment was observed. |
| `business_unit_id`, `job_role_id` | reference | operationally yes | Controlled BU and role references; legacy unknown placeholders remain explicit references. |
| `valid_from`, `valid_to` | input | start yes | Assignment period. `valid_to` is null for the current row. |
| `is_current` | derived/system | yes | Exactly one current row where available. |
| `observed_from` | audit | no | Legacy source provenance; not an HR effective-date input. |
| `created_at` | audit | yes | Record creation timestamp. |

## cohorts and membership

`cohorts` grain: one stable learning team, such as `EL001`, which may study
multiple course runs. `cohort_memberships` grain: one employee membership
period in one cohort.

`cohorts` physical columns: `cohort_id`, `class_code`, `display_name`, `status`,
`created_at`, `updated_at`, `capacity`.

`cohort_memberships` physical columns: `cohort_membership_id`, `cohort_id`,
`employee_id`, `start_date`, `end_date`, `status`,
`transfer_to_membership_id`, `created_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `cohorts.class_code` | input/system | yes | Stable unique class code. |
| `cohorts.display_name` | input | yes | Administrative display name; not an identifier. |
| `cohorts.capacity` | input | no | Positive active-learner limit; exceeding it requires an audited override. |
| `cohort_memberships.start_date`, `end_date` | input | start yes | Event-time class applicability period. |
| `cohort_memberships.transfer_to_membership_id` | input/system | transferred only | Target membership for a transfer. |

## cohort_pic_assignments

Grain: one PIC assignment period for one cohort. The target is either an
employee reference or a normalized free-text team label.

`cohort_pic_assignments` physical columns: `cohort_pic_assignment_id`, `cohort_id`, `pic_employee_id`,
`start_date`, `end_date`, `created_at`, `pic_label`.

The current assignment has `end_date IS NULL`. At least one of
`pic_employee_id` or nonblank `pic_label` is required. PIC display is derived
from `pic_label` first, then the referenced employee name.

## courses and course_runs

`courses` grain: one reusable course definition. `course_runs` grain: one
numbered delivery of one course to one cohort.

`courses` physical columns: `course_id`, `course_code`, `course_name`,
`expected_units`, `attendance_threshold_ratio`, `is_active`, `created_at`.

`course_runs` physical columns: `course_run_id`, `cohort_id`, `course_id`,
`run_number`, `status`, `expected_units_snapshot`,
`attendance_threshold_ratio_snapshot`, `start_date`, `end_date`, `created_at`,
`updated_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `courses.expected_units` | reference | yes | Current planned logical units for new runs. |
| `courses.attendance_threshold_ratio` | reference | yes | Current eligibility threshold for new runs. |
| `course_runs.run_number` | input/system | yes | Positive sequence within cohort and course. |
| `course_runs.expected_units_snapshot` | snapshot | yes | Course expected units copied when the run is created. |
| `course_runs.attendance_threshold_ratio_snapshot` | snapshot | yes | Attendance policy copied when the run is created. |
| `course_runs.start_date`, `end_date` | input | no | Confirmed run boundaries. |

## run_enrollments

Grain: one employee enrolled in one course run. An employee may have at most
one `active` run enrollment across all runs.

`run_enrollments` physical columns: `run_enrollment_id`, `course_run_id`, `employee_id`,
`cohort_membership_id`, `status`, `start_session_number`,
`business_unit_id_snapshot`, `job_role_id_snapshot`,
`transfer_from_enrollment_id`, `created_at`, `updated_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `run_enrollment_id` | audit | yes | Immutable enrollment key. |
| `cohort_membership_id` | input/system | active yes | Matching active membership in the course run's cohort. |
| `start_session_number` | input/system | yes | First applicable logical sequence; earlier sessions are not applicable, not absent. |
| `business_unit_id_snapshot`, `job_role_id_snapshot` | snapshot | active yes | Organization copied at enrollment start and immutable afterward. |
| `transfer_from_enrollment_id` | input/system | transfer only | Previous enrollment in the learner transfer chain. |

## meetings and session_units

`meetings` grain: one scheduled or delivered occurrence. `session_units` grain:
one credited logical unit in an occurrence. Duration and credited units are
separate concepts, and one logical sequence may have multiple occurrences.

`meetings` physical columns: `meeting_id`, `course_run_id`, `starts_at`,
`duration_minutes`, `status`, `cancellation_reason`, `created_at`, `updated_at`.

`session_units` physical columns: `session_unit_id`, `course_run_id`,
`meeting_id`, `sequence_in_run`, `unit_number_in_meeting`, `unit_type`, `title`,
`created_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `meetings.starts_at`, `duration_minutes` | input | yes | Approved occurrence date/time and actual or planned duration. |
| `meetings.cancellation_reason` | input | cancelled only | Required when status is `cancelled`; cancellation retains schedule facts. |
| `session_units.sequence_in_run` | input/system | yes | Logical sequence used for applicability and attendance denominator. |
| `session_units.unit_number_in_meeting` | input/system | yes | Positive position inside the meeting. |
| `session_units.unit_type` | input | yes | Uses the canonical values above; at most two `normal` units per meeting. |

## attendance

Grain: one enrollment fact for one session unit. Direct facts use a non-make-up
unit. A make-up row records `Present` at a `makeup` unit and links to one
original direct `Absent` fact for the same enrollment.

`attendance` physical columns: `attendance_id`, `run_enrollment_id`, `session_unit_id`,
`effective_status`, `original_status`, `is_makeup`,
`makeup_for_attendance_id`, `details`, `created_at`, `updated_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `effective_status` | input | yes | Exactly `Present` or `Absent`; a make-up row must be `Present`. |
| `original_status` | snapshot | no | Source status retained when available. |
| `is_makeup` | input/system | yes | True only for linked replacement-credit attendance. |
| `makeup_for_attendance_id` | input/system | make-up only | Unique link to an original non-make-up absence for the same enrollment. |
| `details` | input/audit | yes | Structured source, note, or correction context. |

The original absence is never overwritten. A valid make-up credits that
logical sequence as present and adds zero denominator units. Make-up linkage,
attended unit type, and a credited original absence are immutable.

The attendance grid may propose `Present` for a new planned roster in the UI;
the database has no default attendance fact. Historical gaps remain unknown
until evidence is saved or a separately approved legacy exception exists.

## placements

Grain: one placement per employee and `placement_kind`; the current business
process permits exactly one `business` entrance placement.

`placements` physical columns: `placement_id`, `employee_id`, `placement_kind`, `test_date`,
`level_id`, `grammar_feedback`, `vocabulary_feedback`,
`pronunciation_feedback`, `fluency_feedback`, `source_reference`, `created_at`.

`source_reference` retains structured provenance. Corrections are audited; a
returning learner reuses the existing business placement rather than inserting
a second one.

## evaluations and evaluation_versions

`evaluations` grain: one stable evaluation identity per run enrollment.
`evaluations` physical columns: `evaluation_id`, `run_enrollment_id`, `created_at`.

`evaluation_versions` grain: one immutable version of that evaluation.
`evaluation_versions` physical columns: `evaluation_version_id`, `evaluation_id`, `version_number`,
`final_level_id`, `exam_eligible`, `exam_eligibility_override`,
`exam_eligibility_override_reason`, `passed`, `next_course_id`, `teacher_notes`,
`correction_reason`, `created_by_user_id`, `created_at`.

| Field | Class | Required | Meaning / rule |
|---|---|---|---|
| `version_number` | audit | yes | Increasing version unique within an evaluation. |
| `exam_eligible` | input | override only | Admin-selected eligibility value only when override is active. |
| `exam_eligibility_override` | input/system | yes | False means eligibility is derived from attendance policy. |
| `exam_eligibility_override_reason` | input | override only | Required for an admin override. |
| `passed`, `final_level_id`, `next_course_id`, `teacher_notes` | input | conditional | Final outcome and recommendation fields. |
| `correction_reason` | input | version 2+ | Explicit operator reason; generic generated reasons are prohibited. |
| `created_by_user_id`, `created_at` | audit | yes | Named actor and version timestamp. |

## levels

Grain: one controlled ordinal level.

`levels` physical columns: `level_id`, `level_name`, `numeric_value`, `sequence_order`,
`is_active`.

`numeric_value` supports progress calculation; `sequence_order` is the stable
display order. Unknown legacy entrance placement remains an explicit reference,
not a null silently interpreted as a level.

## Audited support records

`cohort_capacity_overrides` physical columns: `cohort_capacity_override_id`,
`cohort_id`, `employee_id`, `course_run_id`, `previous_capacity`,
`resulting_active_learner_count`, `reason`, `actor_user_id`, `created_at`.

`monthly_review_action_summary_versions` physical columns:
`monthly_review_action_summary_version_id`, `review_month`, `version_number`,
`highlights`, `risks`, `next_month_priorities`, `created_by_user_id`,
`created_at`.

`attendance_roster_legacy_exceptions` physical columns: `session_unit_id`,
`reason`, `approved_by_user_id`, `approved_at`.

`data_quality_issues` physical columns: `issue_id`, `import_batch_id`,
`issue_code`, `entity_type`, `entity_key`, `source_sheet`, `source_row_number`,
`details`, `status`, `created_at`, `resolved_at`, `resolved_by_user_id`,
`resolution_note`.

`audit_events` physical columns: `audit_event_id`, `actor_user_id`,
`actor_username`, `action`, `entity_type`, `entity_key`, `details`, `created_at`.

| Table | Grain and purpose |
|---|---|
| `cohort_capacity_overrides` | One approved admission above cohort capacity, including employee, run, previous capacity, resulting count, reason, actor, and timestamp. |
| `monthly_review_action_summary_versions` | One immutable HR-authored summary version for one calendar month. |
| `attendance_roster_legacy_exceptions` | One owner-approved acknowledgement that a historical session roster is unavailable; it creates no attendance fact. |
| `data_quality_issues` | One imported or manually logged issue with explicit open/resolved/ignored lifecycle. |
| `audit_events` | One named-actor application event with entity key and structured details. |

## Derived progress and reporting fields

These values belong to views or query modules and are never editable columns.

| Field | Definition |
|---|---|
| `entrance_level` | Level from the employee's `business` placement. |
| `current_level` | Final level from the latest evaluation version carrying a final level. |
| `highest_level` | Maximum final level reached across evaluation versions. |
| `current_progress` | Current numeric level minus entrance numeric level. |
| `peak_progress` | Highest numeric level minus entrance numeric level. |
| `regression_flag` | Latest final level is below the immediately preceding final level. |
| `last_active_at` | Latest completed meeting with direct or replacement-credit presence. |
| `attendance_ratio` | Present applicable logical sequences divided by applicable non-cancelled non-make-up logical sequences. |
| `effective_exam_eligible` | Latest admin override when active; otherwise attendance ratio compared with the run threshold snapshot. |
| `sessions_per_month` | Credited non-final-test units in completed meetings by calendar month. |

## Spreadsheet fields to deprecate

| Legacy field | Canonical treatment |
|---|---|
| `STUDENTS.Status` | Split into employment, membership, enrollment, and run statuses. |
| `STUDENTS.PIC` | Derive from the current `cohort_pic_assignments` row. |
| `Current Course`, `Latest Class Code` | Derive from active or latest run enrollment. |
| `Current Level` | Use clearly named derived current and highest levels. |
| `Last Active Date`, `Days Since Active` | Derive from attendance and meeting facts. |
| `Drop Flag` | Derive from enrollment state and policy; never store as a parallel truth. |
| Numeric, grouping, and progress helper columns | Derive from controlled levels and evaluation versions. |
| Spreadsheet name, PIC, role, and BU copies | Join employee/PIC records; retain only immutable enrollment BU/role snapshots. |
| Formula minimum start dates | Replace with confirmed `course_runs.start_date`. |
| `First Class Start Date`, pivot helpers, uniqueness helpers | Do not load into production canonical data. |
| `ATTENDANCE_LOG` copied names/PIC | Derive through enrollment and class relationships. |
| `CLASS_DATES` | Replace with `course_runs`, `meetings`, and `session_units`. |
