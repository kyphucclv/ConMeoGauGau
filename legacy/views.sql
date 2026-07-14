-- ============================================================================
-- Reporting views -- replace DASHBOARD, PROGRESS, ATT_COUNT, and sheet2's
-- denormalized report columns. Apply after schema.sql + data load.
-- These are plain views (always fresh); swap to MATERIALIZED VIEW + a
-- periodic REFRESH if the dataset grows large enough that recompute-on-read
-- gets slow.
-- ============================================================================

-- v_att_count  (replaces ATT_COUNT sheet)
-- Sessions attended / expected / completion ratio per student per class run.
CREATE OR REPLACE VIEW v_att_count AS
SELECT
    a.class_code,
    a.course_name,
    a.emp_code,
    count(*) FILTER (WHERE a.status = 'Present')                       AS sessions_attended,
    cp.expected_sessions,
    round(count(*) FILTER (WHERE a.status = 'Present')::numeric
          / NULLIF(cp.expected_sessions, 0), 4)                         AS completion_ratio,
    s.status                                                            AS student_status
FROM attendance_log a
JOIN course_plan cp ON cp.course_name = a.course_name
JOIN students s      ON s.emp_code = a.emp_code
GROUP BY a.class_code, a.course_name, a.emp_code, cp.expected_sessions, s.status;

-- v_enrollment_detail  (replaces sheet2)
-- One row per (student, class run) with levels resolved to numeric scale,
-- BU/role/PIC pulled live from students/class_pic instead of copy-pasted.
CREATE OR REPLACE VIEW v_enrollment_detail AS
SELECT
    e.emp_code,
    s.full_name,
    e.class_code,
    cpic.pic_name,
    e.course_name,
    e.entrance_level,
    lh_e.numeric_value AS entrance_numeric,
    e.final_level,
    lh_f.numeric_value AS final_numeric,
    e.start_date,
    e.first_class_start_date,
    s.role,
    s.bu
FROM enrollments e
JOIN students s            ON s.emp_code = e.emp_code
LEFT JOIN class_pic cpic    ON cpic.class_code = e.class_code
LEFT JOIN level_helper lh_e ON lh_e.level_name = e.entrance_level
LEFT JOIN level_helper lh_f ON lh_f.level_name = e.final_level;

-- v_progress_by_bu  (replaces PROGRESS sheet)
-- Buckets each student's entrance->current level jump by business unit.
CREATE OR REPLACE VIEW v_progress_by_bu AS
SELECT
    s.bu,
    count(*) FILTER (WHERE s.entrance_level IS NULL OR s.current_level IS NULL)                       AS not_tested_yet,
    count(*) FILTER (WHERE lh_c.numeric_value < lh_e.numeric_value)                                     AS regressed,
    count(*) FILTER (WHERE lh_c.numeric_value = lh_e.numeric_value)                                     AS no_progress,
    count(*) FILTER (WHERE lh_c.numeric_value > lh_e.numeric_value
                       AND lh_c.numeric_value - lh_e.numeric_value < 1)                                 AS minor_improvement,
    count(*) FILTER (WHERE lh_c.numeric_value - lh_e.numeric_value >= 1)                                AS level_up_or_more,
    count(*)                                                                                             AS total_emp
FROM students s
LEFT JOIN level_helper lh_e ON lh_e.level_name = s.entrance_level
LEFT JOIN level_helper lh_c ON lh_c.level_name = s.current_level
GROUP BY s.bu;

-- v_dashboard_overview  (replaces DASHBOARD Section 1)
CREATE OR REPLACE VIEW v_dashboard_overview AS
SELECT
    (SELECT count(*) FROM students)                                            AS total_students,
    (SELECT count(*) FROM students WHERE status = 'Active')                    AS active_students,
    (SELECT count(*) FROM students WHERE status = 'Inactive')                  AS inactive_students,
    (SELECT count(*) FROM students WHERE status = 'Waiting for class')         AS waiting_for_class,
    (SELECT round(
        count(*) FILTER (WHERE status = 'Present')::numeric / NULLIF(count(*), 0), 4)
     FROM attendance_log)                                                      AS overall_attendance_rate,
    (SELECT count(*) FROM attendance_log)                                      AS total_sessions_logged;

-- v_dashboard_by_course  (replaces DASHBOARD Section 2)
CREATE OR REPLACE VIEW v_dashboard_by_course AS
SELECT
    current_course                                         AS course_name,
    count(*) FILTER (WHERE status = 'Active')              AS active,
    count(*) FILTER (WHERE status = 'Inactive')             AS inactive,
    count(*) FILTER (WHERE status = 'Waiting for class')    AS waiting,
    count(*)                                                AS total
FROM students
WHERE current_course IS NOT NULL
GROUP BY current_course;
