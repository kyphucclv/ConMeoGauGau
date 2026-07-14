"""Task-oriented read models for the Streamlit application."""

from __future__ import annotations

from db import fetch_all


def application_snapshot(pool) -> dict:
    rows = fetch_all(
        pool,
        """
        SELECT
            (SELECT count(*) FROM employees WHERE employment_status='active') AS active_employees,
            (SELECT count(*) FROM run_enrollments WHERE status='active') AS active_learners,
            (SELECT count(*) FROM course_runs WHERE status IN ('planned','active')) AS open_course_runs,
            (SELECT count(*) FROM v_operational_data_issues) AS operational_issues,
            (SELECT count(*) FROM v_operational_data_issues WHERE severity='high') AS high_issues,
            (SELECT count(*) FROM data_quality_issues WHERE status='open') AS open_quality_issues
        """,
    )
    return rows[0] if rows else {
        "active_employees": 0,
        "active_learners": 0,
        "open_course_runs": 0,
        "operational_issues": 0,
        "high_issues": 0,
        "open_quality_issues": 0,
    }


def hr_home_snapshot(pool) -> dict:
    rows = fetch_all(
        pool,
        """
        SELECT
            (SELECT count(*) FROM employees WHERE employment_status='active') AS active_people,
            (SELECT count(*) FROM run_enrollments WHERE status='active') AS current_learners,
            (SELECT count(*) FROM course_runs WHERE status IN ('planned','active')) AS open_classes,
            (SELECT count(*) FROM v_operational_data_issues) AS review_items,
            (SELECT count(*) FROM v_operational_data_issues WHERE severity='high') AS urgent_items,
            (SELECT count(*) FROM data_quality_issues WHERE status='open') AS follow_ups
        """,
    )
    return rows[0] if rows else {
        "active_people": 0,
        "current_learners": 0,
        "open_classes": 0,
        "review_items": 0,
        "urgent_items": 0,
        "follow_ups": 0,
    }


def audit_event_rows(pool, limit: int = 300) -> list[dict]:
    return fetch_all(
        pool,
        """
        SELECT created_at, actor_username, action, entity_type, entity_key, details
        FROM audit_events
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def workflow_reference_data(pool) -> dict[str, list[dict]]:
    return {
        "business_units": fetch_all(pool, "SELECT business_unit_id, business_unit_name FROM business_units WHERE is_active ORDER BY business_unit_name"),
        "job_roles": fetch_all(pool, "SELECT job_role_id, job_role_name FROM job_roles WHERE is_active ORDER BY job_role_name"),
        "employees": fetch_all(pool, "SELECT employee_id, emp_code, full_name FROM employees ORDER BY full_name LIMIT 500"),
        "cohorts": fetch_all(pool, "SELECT cohort_id, class_code, display_name, status FROM cohorts ORDER BY class_code LIMIT 500"),
        "active_memberships": fetch_all(pool, """
            SELECT cm.cohort_membership_id, cm.employee_id, e.emp_code, e.full_name, c.class_code
            FROM cohort_memberships cm
            JOIN employees e ON e.employee_id=cm.employee_id
            JOIN cohorts c ON c.cohort_id=cm.cohort_id
            WHERE cm.status='active'
            ORDER BY c.class_code, e.full_name
            LIMIT 500
        """),
        "courses": fetch_all(pool, "SELECT course_id, course_code, course_name, expected_units FROM courses WHERE is_active ORDER BY course_name"),
        "pic_labels": fetch_all(pool, """
            SELECT DISTINCT ON (lower(pic_label)) pic_label
            FROM cohort_pic_assignments
            WHERE pic_label IS NOT NULL
            ORDER BY lower(pic_label), cohort_pic_assignment_id DESC
            LIMIT 200
        """),
        "course_runs": fetch_all(pool, """
            SELECT cr.course_run_id, c.class_code, co.course_code, co.course_name, cr.run_number, cr.status
            FROM course_runs cr
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_name, cr.run_number
            LIMIT 500
        """),
        "enrollments": fetch_all(pool, """
            SELECT re.run_enrollment_id, e.emp_code, e.full_name, c.class_code, co.course_code,
                   co.course_name, cr.run_number, re.status, re.start_session_number
            FROM run_enrollments re
            JOIN employees e ON e.employee_id=re.employee_id
            JOIN course_runs cr ON cr.course_run_id=re.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_name, cr.run_number, e.full_name
            LIMIT 500
        """),
        "meetings": fetch_all(pool, """
            SELECT m.meeting_id, m.course_run_id, c.class_code, co.course_code, cr.run_number,
                   m.starts_at, m.duration_minutes, m.status, m.cancellation_reason
            FROM meetings m
            JOIN course_runs cr ON cr.course_run_id=m.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY m.starts_at DESC
            LIMIT 500
        """),
        "session_units": fetch_all(pool, """
            SELECT su.session_unit_id, su.course_run_id, c.class_code, co.course_code, cr.run_number,
                   su.sequence_in_run, su.unit_type, m.starts_at, m.status AS meeting_status
            FROM session_units su
            JOIN meetings m ON m.meeting_id=su.meeting_id
            JOIN course_runs cr ON cr.course_run_id=su.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_code, cr.run_number, su.sequence_in_run
            LIMIT 700
        """),
        "levels": fetch_all(pool, "SELECT level_id, level_name FROM levels WHERE is_active ORDER BY sequence_order"),
    }


def learner_directory_rows(pool) -> list[dict]:
    """Return one row per employee with current learning state derived."""
    return fetch_all(pool, """
        SELECT e.employee_id, e.emp_code, e.full_name, e.employment_status,
               bu.business_unit_name, jr.job_role_name,
               c.class_code, co.course_name, co.course_code, re.run_enrollment_id,
               re.status AS enrollment_status, re.start_session_number,
               l.level_name AS entrance_level, attendance.attendance_ratio,
               COALESCE(cpa.pic_label, pic.full_name) AS pic
        FROM employees e
        LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
        LEFT JOIN business_units bu ON bu.business_unit_id=eoh.business_unit_id
        LEFT JOIN job_roles jr ON jr.job_role_id=eoh.job_role_id
        LEFT JOIN run_enrollments re ON re.employee_id=e.employee_id AND re.status='active'
        LEFT JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        LEFT JOIN cohorts c ON c.cohort_id=cr.cohort_id
        LEFT JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN cohort_pic_assignments cpa ON cpa.cohort_id=c.cohort_id AND cpa.end_date IS NULL
        LEFT JOIN employees pic ON pic.employee_id=cpa.pic_employee_id
        LEFT JOIN placements p ON p.employee_id=e.employee_id AND p.placement_kind='business'
        LEFT JOIN levels l ON l.level_id=p.level_id
        LEFT JOIN v_run_enrollment_attendance attendance ON attendance.run_enrollment_id=re.run_enrollment_id
        ORDER BY e.full_name, e.emp_code
        LIMIT 500
    """)


def course_run_capacity(pool, course_run_id: int) -> dict | None:
    rows = fetch_all(pool, """
        SELECT c.class_code, c.capacity,
               count(cm.cohort_membership_id) FILTER (WHERE cm.status='active') AS active_learners
        FROM course_runs cr
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        LEFT JOIN cohort_memberships cm ON cm.cohort_id=c.cohort_id
        WHERE cr.course_run_id=%s
        GROUP BY c.class_code,c.capacity
    """, (course_run_id,))
    return rows[0] if rows else None


def learner_course_history(pool, employee_id: int) -> list[dict]:
    return fetch_all(pool, """
        SELECT cr.start_date, c.class_code, co.course_name, re.status, re.start_session_number,
               rea.attendance_ratio, lev.final_level_id, ev.passed
        FROM run_enrollments re
        JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN v_latest_evaluation_versions ev ON ev.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN evaluation_versions lev ON lev.evaluation_version_id=ev.evaluation_version_id
        WHERE re.employee_id=%s
        ORDER BY re.created_at DESC
    """, (employee_id,))


def employee_audit_rows(pool, employee_id: int) -> list[dict]:
    key = str(employee_id)
    return fetch_all(pool, """
        SELECT created_at, actor_username, action, details
        FROM audit_events
        WHERE (entity_type='employee' AND entity_key=%s)
           OR details->>'employee_id'=%s
        ORDER BY created_at DESC
        LIMIT 100
    """, (key, key))


def employee_search_rows(pool, search: str) -> list[dict]:
    term = search.strip()
    return fetch_all(pool, """
        SELECT emp_code, full_name, employment_status, business_unit_name, job_role_name,
               class_code, course_name, enrollment_status
        FROM v_current_employee_state
        WHERE %s = '' OR emp_code ILIKE %s OR full_name ILIKE %s
        ORDER BY full_name
        LIMIT 100
    """, (term, f"%{term}%", f"%{term}%"))


def cohort_rows(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT c.class_code, c.display_name, c.status,
               COALESCE(cpa.pic_label, pe.full_name) AS current_pic,
               c.created_at
        FROM cohorts c
        LEFT JOIN cohort_pic_assignments cpa
          ON cpa.cohort_id = c.cohort_id AND cpa.end_date IS NULL
        LEFT JOIN employees pe ON pe.employee_id = cpa.pic_employee_id
        ORDER BY c.class_code
        LIMIT 200
    """)


def course_run_dashboard_rows(pool) -> list[dict]:
    return fetch_all(
        pool,
        "SELECT * FROM v_cohort_course_run_dashboard ORDER BY class_code, course_name, run_number LIMIT 200",
    )


def schedule_rows(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT c.class_code, co.course_code, cr.run_number, m.starts_at, m.duration_minutes,
               m.status, su.sequence_in_run, su.unit_type
        FROM meetings m
        JOIN course_runs cr ON cr.course_run_id=m.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN session_units su ON su.meeting_id=m.meeting_id
        ORDER BY m.starts_at DESC, su.sequence_in_run
        LIMIT 250
    """)


def available_makeup_absences(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT a.attendance_id, re.course_run_id, e.emp_code, e.full_name, c.class_code, co.course_code,
               su.sequence_in_run, a.effective_status
        FROM attendance a
        JOIN run_enrollments re ON re.run_enrollment_id=a.run_enrollment_id
        JOIN employees e ON e.employee_id=re.employee_id
        JOIN session_units su ON su.session_unit_id=a.session_unit_id
        JOIN course_runs cr ON cr.course_run_id=su.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        JOIN meetings m ON m.meeting_id=su.meeting_id
        WHERE a.effective_status='Absent'
          AND NOT a.is_makeup
          AND m.status='completed'
          AND NOT EXISTS (
              SELECT 1 FROM attendance makeup
              WHERE makeup.makeup_for_attendance_id=a.attendance_id
          )
        ORDER BY a.updated_at DESC
        LIMIT 300
    """)


def evaluation_outcome_rows(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT e.emp_code, e.full_name, c.class_code, co.course_code, cr.run_number,
               rea.attendance_ratio, rea.effective_exam_eligible, lev.version_number,
               l.level_name AS final_level, lev.passed, next_course.course_code AS next_course
        FROM run_enrollments re
        JOIN employees e ON e.employee_id=re.employee_id
        JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN v_latest_evaluation_versions lev ON lev.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN levels l ON l.level_id=lev.final_level_id
        LEFT JOIN courses next_course ON next_course.course_id=lev.next_course_id
        ORDER BY c.class_code, co.course_code, cr.run_number, e.full_name
        LIMIT 250
    """)


def progress_trajectory_rows(pool) -> list[dict]:
    return fetch_all(pool, "SELECT * FROM v_progress_trajectory ORDER BY emp_code, event_at NULLS FIRST LIMIT 300")


def employee_progress_rows(pool) -> list[dict]:
    return fetch_all(pool, "SELECT * FROM v_employee_progress_summary ORDER BY full_name LIMIT 300")


def monthly_session_rows(pool) -> list[dict]:
    return fetch_all(pool, "SELECT * FROM v_monthly_session_units ORDER BY session_month DESC, course_run_id LIMIT 300")


def open_quality_issue_rows(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT issue_id, issue_code, entity_type, entity_key, source_sheet,
               source_row_number, details, created_at
        FROM data_quality_issues
        WHERE status='open'
        ORDER BY created_at DESC
        LIMIT 300
    """)


def operational_issue_rows(pool) -> list[dict]:
    return fetch_all(pool, """
        SELECT severity, issue_code, entity_type, entity_key, title, workflow, details
        FROM v_operational_data_issues
        ORDER BY CASE severity WHEN 'high' THEN 0 ELSE 1 END, issue_code, entity_key
        LIMIT 500
    """)
