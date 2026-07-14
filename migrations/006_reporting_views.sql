-- Phase 5 canonical reporting views and metric definitions.
-- These views intentionally report from canonical v3 tables only.

CREATE OR REPLACE VIEW v_reporting_metric_definitions AS
SELECT *
FROM (VALUES
    ('attendance_ratio', 'Attendance ratio', 'Present applicable attendance rows divided by applicable non-cancelled session units on or after enrollment.start_session_number.', 'attendance.effective_status = Present', 'non-cancelled session_units joined to meetings, sequence_in_run >= run_enrollments.start_session_number'),
    ('effective_exam_eligible', 'Effective exam eligibility', 'Admin override from the latest evaluation version when present; otherwise calculated attendance ratio >= course_run attendance threshold.', 'latest evaluation override or calculated eligibility', 'one run_enrollment'),
    ('sessions_per_month', 'Sessions per month', 'Credited non-final-test session units in completed meetings by calendar month. Final-test duration minutes do not inflate this count.', 'completed non-cancelled session_units where unit_type is not final_test', 'calendar month'),
    ('current_level', 'Current level', 'Final level from the latest evaluation version with a final level for the employee.', 'latest final_level_id by evaluation version creation order', 'one employee'),
    ('highest_level', 'Highest level', 'Maximum final level numeric value reached across all evaluation versions for the employee.', 'max(level.numeric_value)', 'one employee'),
    ('current_progress', 'Current progress', 'Current level numeric value minus business placement numeric value.', 'latest final level numeric - placement numeric', 'one employee with placement and current level'),
    ('peak_progress', 'Peak progress', 'Highest level numeric value minus business placement numeric value.', 'highest final level numeric - placement numeric', 'one employee with placement and highest level'),
    ('regression_flag', 'Regression flag', 'True when the latest final level is lower than the immediately preceding final level.', 'latest final level numeric < previous final level numeric', 'employee with at least two final-level evaluation versions'),
    ('unresolved_quality_issues', 'Unresolved quality issues', 'Open canonical data quality issues and issue-type ETL row outcomes that should not silently enter schedule-dependent KPIs.', 'open issues or issue outcomes', 'quality issue ledger')
) AS d(metric_key, metric_name, definition, numerator_definition, denominator_definition);

CREATE OR REPLACE VIEW v_latest_evaluation_versions AS
SELECT
    ranked.evaluation_id,
    ranked.run_enrollment_id,
    ranked.evaluation_version_id,
    ranked.version_number,
    ranked.final_level_id,
    ranked.exam_eligible,
    ranked.exam_eligibility_override,
    ranked.exam_eligibility_override_reason,
    ranked.passed,
    ranked.next_course_id,
    ranked.teacher_notes,
    ranked.correction_reason,
    ranked.created_by_user_id,
    ranked.created_at
FROM (
    SELECT
        e.run_enrollment_id,
        ev.*,
        row_number() OVER (
            PARTITION BY ev.evaluation_id
            ORDER BY ev.version_number DESC, ev.evaluation_version_id DESC
        ) AS rn
    FROM evaluations e
    JOIN evaluation_versions ev ON ev.evaluation_id = e.evaluation_id
) ranked
WHERE ranked.rn = 1;

CREATE OR REPLACE VIEW v_run_enrollment_attendance AS
WITH applicable_units AS (
    SELECT
        re.run_enrollment_id,
        su.session_unit_id,
        su.unit_type
    FROM run_enrollments re
    JOIN session_units su
        ON su.course_run_id = re.course_run_id
       AND su.sequence_in_run >= re.start_session_number
    JOIN meetings m
        ON m.meeting_id = su.meeting_id
       AND m.status <> 'cancelled'
),
rollup AS (
    SELECT
        re.run_enrollment_id,
        count(au.session_unit_id) AS applicable_units,
        count(a.attendance_id) FILTER (WHERE a.effective_status = 'Present') AS present_units,
        count(a.attendance_id) FILTER (WHERE a.effective_status = 'Absent') AS absent_units,
        count(a.attendance_id) FILTER (WHERE a.is_makeup) AS makeup_present_units
    FROM run_enrollments re
    LEFT JOIN applicable_units au ON au.run_enrollment_id = re.run_enrollment_id
    LEFT JOIN attendance a
        ON a.run_enrollment_id = re.run_enrollment_id
       AND a.session_unit_id = au.session_unit_id
    GROUP BY re.run_enrollment_id
)
SELECT
    re.run_enrollment_id,
    re.course_run_id,
    re.employee_id,
    re.status AS enrollment_status,
    re.start_session_number,
    cr.attendance_threshold_ratio_snapshot,
    rollup.applicable_units,
    rollup.present_units,
    rollup.absent_units,
    rollup.makeup_present_units,
    round(rollup.present_units::numeric / NULLIF(rollup.applicable_units, 0), 4) AS attendance_ratio,
    COALESCE(round(rollup.present_units::numeric / NULLIF(rollup.applicable_units, 0), 4), 0) >= cr.attendance_threshold_ratio_snapshot AS calculated_exam_eligible,
    CASE
        WHEN lev.exam_eligibility_override THEN lev.exam_eligible
        ELSE COALESCE(round(rollup.present_units::numeric / NULLIF(rollup.applicable_units, 0), 4), 0) >= cr.attendance_threshold_ratio_snapshot
    END AS effective_exam_eligible,
    lev.exam_eligibility_override,
    lev.exam_eligibility_override_reason,
    lev.evaluation_version_id AS latest_evaluation_version_id
FROM run_enrollments re
JOIN course_runs cr ON cr.course_run_id = re.course_run_id
JOIN rollup ON rollup.run_enrollment_id = re.run_enrollment_id
LEFT JOIN v_latest_evaluation_versions lev ON lev.run_enrollment_id = re.run_enrollment_id;

CREATE OR REPLACE VIEW v_monthly_session_units AS
SELECT
    date_trunc('month', m.starts_at)::date AS session_month,
    cr.course_run_id,
    cr.cohort_id,
    cr.course_id,
    count(*) FILTER (WHERE su.unit_type <> 'final_test') AS credited_session_units,
    count(*) FILTER (WHERE su.unit_type = 'final_test') AS final_test_units,
    sum(m.duration_minutes) FILTER (WHERE su.unit_type = 'final_test') AS final_test_duration_minutes
FROM session_units su
JOIN meetings m ON m.meeting_id = su.meeting_id
JOIN course_runs cr ON cr.course_run_id = su.course_run_id
WHERE m.status = 'completed'
GROUP BY date_trunc('month', m.starts_at)::date, cr.course_run_id, cr.cohort_id, cr.course_id;

CREATE OR REPLACE VIEW v_historical_enrollment_snapshot AS
SELECT
    re.run_enrollment_id,
    re.employee_id,
    e.emp_code,
    e.full_name,
    re.course_run_id,
    c.class_code,
    co.course_code,
    co.course_name,
    re.status AS enrollment_status,
    re.start_session_number,
    bu.business_unit_name AS enrollment_business_unit,
    jr.job_role_name AS enrollment_job_role,
    re.transfer_from_enrollment_id,
    re.created_at AS enrollment_created_at
FROM run_enrollments re
JOIN employees e ON e.employee_id = re.employee_id
JOIN course_runs cr ON cr.course_run_id = re.course_run_id
JOIN cohorts c ON c.cohort_id = cr.cohort_id
JOIN courses co ON co.course_id = cr.course_id
LEFT JOIN business_units bu ON bu.business_unit_id = re.business_unit_id_snapshot
LEFT JOIN job_roles jr ON jr.job_role_id = re.job_role_id_snapshot;

CREATE OR REPLACE VIEW v_current_employee_state AS
WITH current_org AS (
    SELECT
        eoh.employee_id,
        bu.business_unit_name,
        jr.job_role_name
    FROM employee_org_history eoh
    LEFT JOIN business_units bu ON bu.business_unit_id = eoh.business_unit_id
    LEFT JOIN job_roles jr ON jr.job_role_id = eoh.job_role_id
    WHERE eoh.is_current
),
active_membership AS (
    SELECT DISTINCT ON (cm.employee_id)
        cm.employee_id,
        cm.cohort_membership_id,
        cm.status AS membership_status,
        c.cohort_id,
        c.class_code,
        c.status AS cohort_status
    FROM cohort_memberships cm
    JOIN cohorts c ON c.cohort_id = cm.cohort_id
    WHERE cm.status = 'active'
    ORDER BY cm.employee_id, cm.start_date DESC, cm.cohort_membership_id DESC
),
current_enrollment AS (
    SELECT DISTINCT ON (re.employee_id)
        re.employee_id,
        re.run_enrollment_id,
        re.status AS enrollment_status,
        cr.course_run_id,
        cr.status AS course_run_status,
        co.course_code,
        co.course_name
    FROM run_enrollments re
    JOIN course_runs cr ON cr.course_run_id = re.course_run_id
    JOIN courses co ON co.course_id = cr.course_id
    ORDER BY
        re.employee_id,
        CASE WHEN re.status = 'active' THEN 0 ELSE 1 END,
        re.created_at DESC,
        re.run_enrollment_id DESC
)
SELECT
    e.employee_id,
    e.emp_code,
    e.full_name,
    e.employment_status,
    current_org.business_unit_name,
    current_org.job_role_name,
    active_membership.cohort_membership_id,
    active_membership.class_code,
    active_membership.membership_status,
    active_membership.cohort_status,
    current_enrollment.run_enrollment_id,
    current_enrollment.course_run_id,
    current_enrollment.course_code,
    current_enrollment.course_name,
    current_enrollment.enrollment_status,
    current_enrollment.course_run_status
FROM employees e
LEFT JOIN current_org ON current_org.employee_id = e.employee_id
LEFT JOIN active_membership ON active_membership.employee_id = e.employee_id
LEFT JOIN current_enrollment ON current_enrollment.employee_id = e.employee_id;

CREATE OR REPLACE VIEW v_progress_trajectory AS
SELECT
    p.employee_id,
    e.emp_code,
    'placement'::text AS event_type,
    p.placement_id AS source_id,
    p.test_date::timestamptz AS event_at,
    NULL::bigint AS run_enrollment_id,
    p.level_id,
    l.level_name,
    l.numeric_value,
    NULL::smallint AS evaluation_version_number,
    NULL::boolean AS passed
FROM placements p
JOIN employees e ON e.employee_id = p.employee_id
LEFT JOIN levels l ON l.level_id = p.level_id
UNION ALL
SELECT
    re.employee_id,
    e.emp_code,
    'evaluation'::text AS event_type,
    ev.evaluation_version_id AS source_id,
    ev.created_at AS event_at,
    re.run_enrollment_id,
    ev.final_level_id AS level_id,
    l.level_name,
    l.numeric_value,
    ev.version_number AS evaluation_version_number,
    ev.passed
FROM evaluation_versions ev
JOIN evaluations eval ON eval.evaluation_id = ev.evaluation_id
JOIN run_enrollments re ON re.run_enrollment_id = eval.run_enrollment_id
JOIN employees e ON e.employee_id = re.employee_id
LEFT JOIN levels l ON l.level_id = ev.final_level_id
WHERE ev.final_level_id IS NOT NULL;

CREATE OR REPLACE VIEW v_employee_progress_summary AS
WITH business_placement AS (
    SELECT DISTINCT ON (p.employee_id)
        p.employee_id,
        p.level_id AS entrance_level_id,
        l.level_name AS entrance_level_name,
        l.numeric_value AS entrance_numeric
    FROM placements p
    LEFT JOIN levels l ON l.level_id = p.level_id
    WHERE p.placement_kind = 'business'
    ORDER BY p.employee_id, p.test_date NULLS LAST, p.placement_id DESC
),
eval_levels AS (
    SELECT
        re.employee_id,
        ev.evaluation_version_id,
        ev.created_at,
        ev.version_number,
        ev.final_level_id,
        l.level_name,
        l.numeric_value,
        row_number() OVER (
            PARTITION BY re.employee_id
            ORDER BY ev.created_at DESC, ev.evaluation_version_id DESC
        ) AS latest_rank,
        lag(l.numeric_value) OVER (
            PARTITION BY re.employee_id
            ORDER BY ev.created_at, ev.evaluation_version_id
        ) AS previous_numeric
    FROM evaluation_versions ev
    JOIN evaluations eval ON eval.evaluation_id = ev.evaluation_id
    JOIN run_enrollments re ON re.run_enrollment_id = eval.run_enrollment_id
    LEFT JOIN levels l ON l.level_id = ev.final_level_id
    WHERE ev.final_level_id IS NOT NULL
),
current_eval AS (
    SELECT *
    FROM eval_levels
    WHERE latest_rank = 1
),
highest_eval AS (
    SELECT DISTINCT ON (employee_id)
        employee_id,
        final_level_id AS highest_level_id,
        level_name AS highest_level_name,
        numeric_value AS highest_numeric
    FROM eval_levels
    ORDER BY employee_id, numeric_value DESC NULLS LAST, created_at DESC, evaluation_version_id DESC
)
SELECT
    e.employee_id,
    e.emp_code,
    e.full_name,
    bp.entrance_level_id,
    bp.entrance_level_name,
    bp.entrance_numeric,
    ce.final_level_id AS current_level_id,
    ce.level_name AS current_level_name,
    ce.numeric_value AS current_numeric,
    he.highest_level_id,
    he.highest_level_name,
    he.highest_numeric,
    ce.numeric_value - bp.entrance_numeric AS current_progress,
    he.highest_numeric - bp.entrance_numeric AS peak_progress,
    COALESCE(ce.numeric_value < ce.previous_numeric, FALSE) AS regression_flag
FROM employees e
LEFT JOIN business_placement bp ON bp.employee_id = e.employee_id
LEFT JOIN current_eval ce ON ce.employee_id = e.employee_id
LEFT JOIN highest_eval he ON he.employee_id = e.employee_id;

CREATE OR REPLACE VIEW v_unresolved_quality_issues AS
SELECT
    'data_quality_issue'::text AS source,
    dqi.issue_id::text AS issue_key,
    dqi.issue_code,
    dqi.entity_type,
    dqi.entity_key,
    dqi.source_sheet,
    dqi.source_row_number,
    dqi.details,
    dqi.created_at
FROM data_quality_issues dqi
WHERE dqi.status = 'open'
UNION ALL
SELECT
    'etl_source_row_outcome'::text AS source,
    esro.source_row_outcome_id::text AS issue_key,
    esro.outcome_code AS issue_code,
    COALESCE(esro.target_entity, 'source_row') AS entity_type,
    esro.target_key AS entity_key,
    esro.source_sheet,
    esro.source_row_number,
    esro.details,
    esro.created_at
FROM etl_source_row_outcomes esro
WHERE esro.outcome_type = 'issue'
  AND NOT EXISTS (
      SELECT 1
      FROM data_quality_issues dqi
      WHERE dqi.import_batch_id = esro.import_batch_id
        AND dqi.issue_code = esro.outcome_code
        AND dqi.entity_type = COALESCE(esro.target_entity, 'source_row')
        AND COALESCE(dqi.entity_key, '') = COALESCE(esro.target_key, '')
        AND dqi.source_sheet = esro.source_sheet
        AND dqi.source_row_number = esro.source_row_number
  );

CREATE OR REPLACE VIEW v_cohort_course_run_dashboard AS
SELECT
    c.cohort_id,
    c.class_code,
    c.status AS cohort_status,
    cr.course_run_id,
    co.course_code,
    co.course_name,
    cr.run_number,
    cr.status AS course_run_status,
    cr.start_date,
    cr.end_date,
    count(DISTINCT re.run_enrollment_id) AS enrollment_count,
    count(DISTINCT re.run_enrollment_id) FILTER (WHERE re.status = 'active') AS active_enrollments,
    count(DISTINCT re.run_enrollment_id) FILTER (WHERE re.status = 'completed') AS completed_enrollments,
    count(DISTINCT m.meeting_id) FILTER (WHERE m.status = 'completed') AS completed_meetings,
    count(DISTINCT m.meeting_id) FILTER (WHERE m.status = 'cancelled') AS cancelled_meetings,
    count(DISTINCT su.session_unit_id) FILTER (WHERE m.status <> 'cancelled') AS non_cancelled_units,
    count(DISTINCT su.session_unit_id) FILTER (WHERE m.status <> 'cancelled' AND su.unit_type = 'final_test') AS final_test_units,
    round(avg(rea.attendance_ratio), 4) AS average_attendance_ratio,
    count(DISTINCT re.run_enrollment_id) FILTER (WHERE rea.effective_exam_eligible) AS exam_eligible_enrollments
FROM cohorts c
LEFT JOIN course_runs cr ON cr.cohort_id = c.cohort_id
LEFT JOIN courses co ON co.course_id = cr.course_id
LEFT JOIN run_enrollments re ON re.course_run_id = cr.course_run_id
LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id = re.run_enrollment_id
LEFT JOIN meetings m ON m.course_run_id = cr.course_run_id
LEFT JOIN session_units su ON su.meeting_id = m.meeting_id
GROUP BY c.cohort_id, c.class_code, c.status, cr.course_run_id, co.course_code, co.course_name, cr.run_number, cr.status, cr.start_date, cr.end_date;
