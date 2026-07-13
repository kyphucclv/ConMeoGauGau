# Source field mapping specification

Status: Phase 2 draft for ETL implementation.

This document maps workbook fields to the canonical v3 model. Fields marked
`deprecated` stay available in `raw_workbook_rows.raw_payload` but are not
loaded into canonical tables.

## Issue code conventions

| Issue code | Meaning |
|---|---|
| `missing_emp_code` | Source row does not identify an employee code where one is required. |
| `missing_class_code` | Source row does not identify a cohort/class code where one is required. |
| `unknown_level` | Source level label is not present in `levels`. |
| `unknown_course` | Source course label is not present in `courses`. |
| `missing_course` | Enrollment or attendance row does not identify a course. |
| `malformed_date` | Date field cannot be parsed into the target date/timestamp type. |
| `duplicate_business_placement` | More than one business placement candidate exists for one employee. |
| `attendance_without_enrollment` | Attendance row cannot be matched to a run enrollment. |
| `conflicting_session_structure` | Class/course/session/date values do not form one consistent schedule. |
| `run_boundary_unresolved` | Source suggests a possible repeated run or session reset, but no stable run identifier exists. |
| `unmapped_pic_employee` | PIC name/class exists but no employee code can be resolved. |

## `LEVEL_HELPER`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Level Name` | `levels.level_name` | reference | Trim whitespace; preserve label casing from source. | `unknown_level` when referenced but absent |
| `Numeric Value` | `levels.numeric_value` | reference | Parse numeric(3,1); sequence by numeric order with source order as tiebreaker. | `unknown_level` |

## `COURSE_PLAN`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Course Name` | `courses.course_name` | reference | Trim whitespace; preserve source label. | `unknown_course` |
| `Expected Sessions` | `courses.expected_units` | reference | Parse positive integer session-unit count. | `unknown_course` |

## `STUDENTS`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Emp Code` | `employees.emp_code` | input | Trim; uppercase only if source codes prove case-insensitive. | `missing_emp_code` |
| `Full Name` | `employees.full_name` | input | Trim and collapse internal whitespace. | `missing_emp_code` |
| `BU` | `business_units.business_unit_name`, `employee_org_history.business_unit_id` | input | Trim; create controlled reference candidate. |  |
| `ROLE` | `job_roles.job_role_name`, `employee_org_history.job_role_id` | input | Trim; create controlled reference candidate. |  |
| `Status` | `employees.employment_status` plus later membership/enrollment inference | input | Map employment-only meaning conservatively; do not overload as course status. |  |
| `PIC` | derived through cohort PIC/current enrollment | deprecated | Preserve raw only; do not load as employee identifier. | `unmapped_pic_employee` if needed later |
| `Current Course` | derived through latest active/completed enrollment | deprecated | Preserve raw only; used as reconciliation hint. | `unknown_course` |
| `Entrance Level` | `placements.level_id` | input | Resolve through `levels.level_name`. | `unknown_level` |
| `Current Level` | derived from latest evaluation version | deprecated | Preserve raw only; used as reconciliation hint. | `unknown_level` |
| `Last Active Date` | derived from attendance | deprecated | Preserve raw only. | `malformed_date` if used for reconciliation |
| `Days Since Active` | derived | deprecated | Do not load. |  |
| `Drop Flag (<30 days is safe)` | derived from enrollment/attendance rules | deprecated | Do not load. |  |
| `Define of drop (not inc. resign)` | `run_enrollments.status`/issue candidate | input | Use only in Phase 3 with explicit mapping. |  |
| `Drop reason` | `run_enrollments.status`/issue candidate | input | Resign remains employment status, not course drop reason. |  |
| `Remark` | issue/details candidate | input | Preserve in raw; load only if a reviewed target note exists. |  |
| `Latest Class Code` | `cohorts.class_code` / latest enrollment hint | input/derived | Trim; use to infer current/latest run only when supported by enrollment evidence. | `missing_class_code` |
| `Latest Course Name` | latest enrollment hint | input/derived | Resolve through courses; do not create run by itself. | `unknown_course` |
| numeric/group/progress helper columns | reporting views | deprecated | Do not load; recompute from levels/evaluations. |  |

## `PIC`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Class Code` | `cohorts.class_code` | input | Trim; stable cohort business key. | `missing_class_code` |
| `PIC` | `employees.full_name` candidate | input | Name is not a key; resolve through `EMP Code` where available. | `unmapped_pic_employee` |
| `EMP Code` | `employees.emp_code`, `cohort_pic_assignments.pic_employee_id` | input | Trim; create employee if not already present. | `missing_emp_code` |
| `Mail` | `employees.email` | input | Trim; validate email format only as warning in Phase 3. |  |
| `English name` | `employees.english_name` | input | Trim. |  |

## `CLASS_DATES`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Class Code` | `cohorts.class_code` | input | Trim; class/cohort identifier. | `missing_class_code` |
| `Course Name` | `course_runs.course_id` candidate | input | Resolve through `courses`; repeated cohort/course needs run-number inference. | `unknown_course` |
| `column_3` | `course_runs.start_date` candidate | input | Parse as date if populated; do not substitute attendance MIN date. | `malformed_date` |

## `sheet2`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Emp Code` | `run_enrollments.employee_id` | input | Resolve to employee. | `missing_emp_code` |
| `Full Name` | derived through employee | deprecated | Preserve raw only; names are not keys. |  |
| `Class Code` | `cohorts.class_code` / `course_runs.cohort_id` | input | Resolve to cohort. | `missing_class_code` |
| `PIC` | derived through cohort PIC assignment | deprecated | Preserve raw only. | `unmapped_pic_employee` |
| `Course Name` | `course_runs.course_id` | input | Resolve through courses. | `missing_course` / `unknown_course` |
| `Entrance Level` | placement/enrollment context | input | Resolve through levels; source priority below `Placement` for business placement. | `unknown_level` |
| `Final Level` | `evaluation_versions.final_level_id` | input | Resolve through levels; null allowed when not eligible/unavailable. | `unknown_level` |
| `start date` | `course_runs.start_date` or `run_enrollments.joined_at` candidate | input | Parse date; use only with supporting class/course evidence. | `malformed_date` |
| `First Class Start Date` | none | deprecated | No current business use. |  |
| `Role` | `run_enrollments.job_role_id_snapshot` | snapshot | Resolve/create job role at enrollment load time. |  |
| `BU` | `run_enrollments.business_unit_id_snapshot` | snapshot | Resolve/create BU at enrollment load time. |  |
| `Is_Unique_Row` and pivot/helper columns | none | deprecated | Do not load. |  |
| numeric/group/progress helper columns | reporting views | deprecated | Do not load; recompute. |  |

## `ATTENDANCE_LOG`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Class Code` | `cohorts.class_code` / `course_runs.cohort_id` | input | Resolve to cohort. | `missing_class_code` |
| `Course Name` | `course_runs.course_id` | input | Resolve through courses. | `missing_course` / `unknown_course` |
| `Emp Code` | `attendance.run_enrollment_id` via employee/enrollment | input | Resolve through employee and enrollment. | `missing_emp_code` / `attendance_without_enrollment` |
| `Full Name` | derived through employee | deprecated | Preserve raw only. |  |
| `Session Order` | `session_units.sequence_in_run` | input | Parse positive integer; conflicts across date/course/class become issues. | `conflicting_session_structure` |
| `Date` | `meetings.starts_at` | input | Parse timestamp/date; missing/malformed rows become issues. | `malformed_date` |
| `Status` | `attendance.effective_status` | input | Only `Present` or `Absent`; other values become issues. |  |
| `PIC` | derived through cohort PIC assignment | deprecated | Preserve raw only. |  |

## `Placement`

| Source field | Target entity.field | Class | Normalization rule | Issue code |
|---|---|---|---|---|
| `Emp. Code` | `placements.employee_id` | input | Resolve to employee. | `missing_emp_code` |
| `Full name` | derived through employee | deprecated | Preserve raw only. |  |
| `Entrance Test date` | `placements.test_date` | input | Parse date. | `malformed_date` |
| `1st session:` | `placements.level_id` | input | Resolve through levels. | `unknown_level` |
| placement feedback columns | `placements.*_feedback` | input | Map feedback columns only after header review; otherwise preserve raw. |  |
| duplicate/helper columns | none | deprecated | Use for profiling only, not canonical load. | `duplicate_business_placement` |
