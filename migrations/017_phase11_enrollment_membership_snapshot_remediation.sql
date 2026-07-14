-- Phase 11 enrollment integrity remediation.
-- Grain: active run enrollments must be linked to their active cohort
-- membership and must carry immutable BU/role snapshots.
-- Forward verification: v_operational_data_issues should report zero rows for
-- active_enrollment_membership_link_missing and
-- active_enrollment_snapshot_incomplete after this migration is applied.
-- Rollback: restore the database backup taken before applying this migration;
-- this file performs controlled historical remediation and adds guards.

UPDATE run_enrollments re
SET cohort_membership_id = cm.cohort_membership_id
FROM course_runs cr
JOIN cohort_memberships cm
  ON cm.cohort_id = cr.cohort_id
 AND cm.status = 'active'
WHERE re.course_run_id = cr.course_run_id
  AND cm.employee_id = re.employee_id
  AND re.status = 'active'
  AND re.cohort_membership_id IS NULL;

-- The Phase 11 snapshot immutability trigger protects app writes.  This
-- migration temporarily disables it only to fill missing active-row snapshots
-- from the already-approved current organization profile.
ALTER TABLE run_enrollments DISABLE TRIGGER trg_run_enrollment_snapshots_immutable;

UPDATE run_enrollments re
SET business_unit_id_snapshot = COALESCE(re.business_unit_id_snapshot, eoh.business_unit_id),
    job_role_id_snapshot = COALESCE(re.job_role_id_snapshot, eoh.job_role_id)
FROM employee_org_history eoh
WHERE eoh.employee_id = re.employee_id
  AND eoh.is_current
  AND re.status = 'active'
  AND (re.business_unit_id_snapshot IS NULL OR re.job_role_id_snapshot IS NULL)
  AND eoh.business_unit_id IS NOT NULL
  AND eoh.job_role_id IS NOT NULL;

ALTER TABLE run_enrollments ENABLE TRIGGER trg_run_enrollment_snapshots_immutable;

CREATE OR REPLACE FUNCTION enforce_active_run_enrollment_completeness()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE membership_status TEXT;
BEGIN
    IF NEW.status = 'active' THEN
        IF NEW.cohort_membership_id IS NULL THEN
            RAISE EXCEPTION 'active enrollment must reference an active cohort membership';
        END IF;
        IF NEW.business_unit_id_snapshot IS NULL OR NEW.job_role_id_snapshot IS NULL THEN
            RAISE EXCEPTION 'active enrollment must include BU and role snapshots';
        END IF;
        SELECT status INTO membership_status
        FROM cohort_memberships
        WHERE cohort_membership_id = NEW.cohort_membership_id;
        IF membership_status IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION 'active enrollment must reference an active cohort membership';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_active_run_enrollment_completeness ON run_enrollments;
CREATE TRIGGER trg_active_run_enrollment_completeness
BEFORE INSERT OR UPDATE OF status, cohort_membership_id, business_unit_id_snapshot, job_role_id_snapshot
ON run_enrollments
FOR EACH ROW EXECUTE FUNCTION enforce_active_run_enrollment_completeness();

CREATE OR REPLACE FUNCTION prevent_inactive_membership_with_active_enrollment()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'active' AND NEW.status <> 'active' THEN
        IF EXISTS (
            SELECT 1
            FROM run_enrollments re
            WHERE re.cohort_membership_id = OLD.cohort_membership_id
              AND re.status = 'active'
        ) THEN
            RAISE EXCEPTION 'cannot close or transfer a cohort membership while an active enrollment references it';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_membership_active_enrollment_guard ON cohort_memberships;
CREATE TRIGGER trg_membership_active_enrollment_guard
BEFORE UPDATE OF status ON cohort_memberships
FOR EACH ROW EXECUTE FUNCTION prevent_inactive_membership_with_active_enrollment();

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
SELECT 'active_enrollment_membership_link_missing','high','run_enrollment',re.run_enrollment_id::text,
       'Active enrollment is not linked to an active cohort membership','Learners',
       jsonb_build_object('emp_code', e.emp_code, 'full_name', e.full_name, 'class_code', c.class_code, 'course_run_id', re.course_run_id)
FROM run_enrollments re
JOIN employees e ON e.employee_id=re.employee_id
JOIN course_runs cr ON cr.course_run_id=re.course_run_id
JOIN cohorts c ON c.cohort_id=cr.cohort_id
LEFT JOIN cohort_memberships cm
  ON cm.cohort_membership_id=re.cohort_membership_id
 AND cm.status='active'
WHERE re.status='active' AND cm.cohort_membership_id IS NULL

UNION ALL
SELECT 'active_enrollment_snapshot_incomplete','high','run_enrollment',re.run_enrollment_id::text,
       'Active enrollment is missing immutable BU or role snapshot','Learners',
       jsonb_build_object('emp_code', e.emp_code, 'full_name', e.full_name, 'business_unit_id_snapshot', re.business_unit_id_snapshot, 'job_role_id_snapshot', re.job_role_id_snapshot)
FROM run_enrollments re
JOIN employees e ON e.employee_id=re.employee_id
WHERE re.status='active'
  AND (re.business_unit_id_snapshot IS NULL OR re.job_role_id_snapshot IS NULL)

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
LEFT JOIN attendance_roster_legacy_exceptions arex ON arex.session_unit_id=su.session_unit_id
WHERE a.attendance_id IS NULL AND arex.session_unit_id IS NULL
GROUP BY su.session_unit_id,su.course_run_id,su.sequence_in_run

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
