-- Phase 10 owner decisions: a logical session may have multiple delivered
-- occurrences, and legacy PIC values may identify a team label rather than an
-- employee record.

ALTER TABLE session_units
    DROP CONSTRAINT session_units_course_run_id_sequence_in_run_key;

ALTER TABLE session_units
    ADD CONSTRAINT uq_session_units_run_sequence_meeting
    UNIQUE (course_run_id, sequence_in_run, meeting_id);

ALTER TABLE cohort_pic_assignments
    ALTER COLUMN pic_employee_id DROP NOT NULL,
    ADD COLUMN pic_label TEXT,
    ADD CONSTRAINT ck_cohort_pic_assignment_target
        CHECK (pic_employee_id IS NOT NULL OR NULLIF(BTRIM(pic_label), '') IS NOT NULL);

CREATE OR REPLACE VIEW v_run_enrollment_attendance AS
WITH applicable_sequences AS (
    SELECT DISTINCT
        re.run_enrollment_id,
        su.sequence_in_run
    FROM run_enrollments re
    JOIN session_units su
        ON su.course_run_id = re.course_run_id
       AND su.sequence_in_run >= re.start_session_number
    JOIN meetings m
        ON m.meeting_id = su.meeting_id
       AND m.status <> 'cancelled'
),
attendance_by_sequence AS (
    SELECT
        a.run_enrollment_id,
        su.sequence_in_run,
        bool_or(a.effective_status = 'Present') AS is_present,
        bool_or(a.effective_status = 'Absent') AS is_absent,
        bool_or(a.is_makeup AND a.effective_status = 'Present') AS is_makeup_present
    FROM attendance a
    JOIN session_units su ON su.session_unit_id = a.session_unit_id
    JOIN meetings m ON m.meeting_id = su.meeting_id AND m.status <> 'cancelled'
    GROUP BY a.run_enrollment_id, su.sequence_in_run
),
rollup AS (
    SELECT
        re.run_enrollment_id,
        count(app.sequence_in_run) AS applicable_units,
        count(app.sequence_in_run) FILTER (WHERE abs.is_present) AS present_units,
        count(app.sequence_in_run) FILTER (WHERE abs.is_absent AND NOT abs.is_present) AS absent_units,
        count(app.sequence_in_run) FILTER (WHERE abs.is_makeup_present) AS makeup_present_units
    FROM run_enrollments re
    LEFT JOIN applicable_sequences app ON app.run_enrollment_id = re.run_enrollment_id
    LEFT JOIN attendance_by_sequence abs
        ON abs.run_enrollment_id = re.run_enrollment_id
       AND abs.sequence_in_run = app.sequence_in_run
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
    count(DISTINCT su.sequence_in_run) FILTER (WHERE m.status <> 'cancelled') AS non_cancelled_units,
    count(DISTINCT su.sequence_in_run) FILTER (WHERE m.status <> 'cancelled' AND su.unit_type = 'final_test') AS final_test_units,
    round(avg(rea.attendance_ratio), 4) AS average_attendance_ratio,
    count(DISTINCT re.run_enrollment_id) FILTER (WHERE rea.effective_exam_eligible) AS exam_eligible_enrollments
FROM cohorts c
LEFT JOIN course_runs cr ON cr.cohort_id = c.cohort_id
LEFT JOIN courses co ON co.course_id = cr.course_id
LEFT JOIN run_enrollments re ON re.course_run_id = cr.course_run_id
LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id = re.run_enrollment_id
LEFT JOIN meetings m ON m.course_run_id = cr.course_run_id
LEFT JOIN session_units su ON su.meeting_id = m.meeting_id
GROUP BY c.cohort_id, c.class_code, c.status, cr.course_run_id, co.course_code,
         co.course_name, cr.run_number, cr.status, cr.start_date, cr.end_date;
