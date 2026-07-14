-- Phase 11 operational issue inbox.
-- Grain: one row is one currently actionable canonical-data condition.
-- Forward verification: query v_operational_data_issues after seeded issue fixtures.
-- Rollback: restore the pre-migration backup; this migration owns no source data.

CREATE OR REPLACE VIEW v_operational_data_issues AS
SELECT
    'incomplete_employee_profile'::text AS issue_code,
    'high'::text AS severity,
    'employee'::text AS entity_type,
    e.employee_id::text AS entity_key,
    'Employee identity or current organization is incomplete'::text AS title,
    'Learners'::text AS workflow,
    jsonb_build_object('emp_code', e.emp_code, 'full_name', e.full_name) AS details
FROM employees e
LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
WHERE NULLIF(BTRIM(e.full_name), '') IS NULL OR eoh.employee_org_history_id IS NULL
   OR eoh.business_unit_id IS NULL OR eoh.job_role_id IS NULL

UNION ALL
SELECT 'employee_code_case_conflict','high','employee',min(e.employee_id)::text,
       'Employee codes differ only by letter case','Learners',
       jsonb_build_object('normalized_emp_code', lower(e.emp_code), 'employee_ids', jsonb_agg(e.employee_id ORDER BY e.employee_id))
FROM employees e GROUP BY lower(e.emp_code) HAVING count(*) > 1

UNION ALL
SELECT 'active_enrollment_conflict','high','employee',re.employee_id::text,
       'Learner has multiple active course enrollments','Learners',
       jsonb_build_object('active_enrollment_ids', jsonb_agg(re.run_enrollment_id ORDER BY re.run_enrollment_id))
FROM run_enrollments re WHERE re.status='active' GROUP BY re.employee_id HAVING count(*) > 1

UNION ALL
SELECT 'missing_business_placement','high','employee',e.employee_id::text,
       'Learner has no business placement','Learners',jsonb_build_object('emp_code', e.emp_code, 'full_name', e.full_name)
FROM employees e LEFT JOIN placements p ON p.employee_id=e.employee_id AND p.placement_kind='business'
WHERE p.placement_id IS NULL

UNION ALL
SELECT 'session_datetime_conflict','high','cohort',c.cohort_id::text,
       'Class has concurrent scheduled session occurrences','Schedule',
       jsonb_build_object('starts_at', m.starts_at, 'meeting_ids', jsonb_agg(m.meeting_id ORDER BY m.meeting_id))
FROM meetings m JOIN course_runs cr ON cr.course_run_id=m.course_run_id JOIN cohorts c ON c.cohort_id=cr.cohort_id
WHERE m.status <> 'cancelled' GROUP BY c.cohort_id,m.starts_at HAVING count(*) > 1

UNION ALL
SELECT 'incomplete_attendance_roster','high','session_unit',su.session_unit_id::text,
       'Delivered session has applicable learners without a saved attendance result','Attendance',
       jsonb_build_object('course_run_id', su.course_run_id, 'sequence_in_run', su.sequence_in_run, 'missing_enrollment_count', count(re.run_enrollment_id))
FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id AND m.status='completed'
JOIN run_enrollments re ON re.course_run_id=su.course_run_id AND re.status='active' AND re.start_session_number<=su.sequence_in_run
LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id AND a.run_enrollment_id=re.run_enrollment_id
WHERE a.attendance_id IS NULL GROUP BY su.session_unit_id,su.course_run_id,su.sequence_in_run

UNION ALL
SELECT 'low_attendance_follow_up','warning','run_enrollment',rea.run_enrollment_id::text,
       'Active learner is below the course attendance threshold','Attendance',
       jsonb_build_object('attendance_ratio', rea.attendance_ratio, 'threshold', rea.attendance_threshold_ratio_snapshot)
FROM v_run_enrollment_attendance rea WHERE rea.enrollment_status='active'
  AND rea.applicable_units > 0 AND rea.attendance_ratio < rea.attendance_threshold_ratio_snapshot

UNION ALL
SELECT 'capacity_override_review','warning','cohort_capacity_override',cco.cohort_capacity_override_id::text,
       'Capacity override requires operational review','Learners',
       jsonb_build_object('cohort_id', cco.cohort_id, 'employee_id', cco.employee_id, 'reason', cco.reason, 'resulting_active_learner_count', cco.resulting_active_learner_count)
FROM cohort_capacity_overrides cco

UNION ALL
SELECT 'transfer_link_incomplete','high','cohort_membership',cm.cohort_membership_id::text,
       'Transferred membership has no target membership link','Learners',
       jsonb_build_object('employee_id', cm.employee_id, 'cohort_id', cm.cohort_id)
FROM cohort_memberships cm WHERE cm.status='transferred' AND cm.transfer_to_membership_id IS NULL;
