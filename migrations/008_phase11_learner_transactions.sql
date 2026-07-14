-- Phase 11 learner transaction invariants.
-- Grain: one cohort capacity override records one approved admission above the
-- cohort's configured active-learner capacity.
-- Forward verification: inspect pg_constraint/pg_indexes for the named rules
-- and run scripts/phase11_p11_1_integration.py on a disposable database.
-- Rollback: restore the database backup taken before applying this migration;
-- production override and enrollment history must not be discarded by DDL.

ALTER TABLE cohorts ADD COLUMN capacity INTEGER;
ALTER TABLE cohorts ADD CONSTRAINT ck_cohorts_capacity_positive
    CHECK (capacity IS NULL OR capacity > 0);

CREATE UNIQUE INDEX uq_run_enrollments_one_active_per_employee
    ON run_enrollments(employee_id) WHERE status = 'active';

CREATE TABLE cohort_capacity_overrides (
    cohort_capacity_override_id BIGSERIAL PRIMARY KEY,
    cohort_id BIGINT NOT NULL REFERENCES cohorts(cohort_id),
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    course_run_id BIGINT NOT NULL REFERENCES course_runs(course_run_id),
    previous_capacity INTEGER NOT NULL CHECK (previous_capacity > 0),
    resulting_active_learner_count INTEGER NOT NULL CHECK (resulting_active_learner_count > previous_capacity),
    reason TEXT NOT NULL CHECK (NULLIF(BTRIM(reason), '') IS NOT NULL),
    actor_user_id BIGINT NOT NULL REFERENCES app_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_capacity_overrides_cohort ON cohort_capacity_overrides(cohort_id);

UPDATE cohort_pic_assignments
SET pic_label = regexp_replace(BTRIM(pic_label), '\s+', ' ', 'g')
WHERE pic_label IS NOT NULL;
ALTER TABLE cohort_pic_assignments ADD CONSTRAINT ck_cohort_pic_assignment_label_normalized
    CHECK (pic_label IS NULL OR pic_label = regexp_replace(BTRIM(pic_label), '\s+', ' ', 'g'));

CREATE OR REPLACE FUNCTION enforce_run_enrollment_relationships()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE membership_employee_id BIGINT; membership_cohort_id BIGINT; run_cohort_id BIGINT;
BEGIN
    SELECT cohort_id INTO run_cohort_id FROM course_runs WHERE course_run_id = NEW.course_run_id;
    IF run_cohort_id IS NULL THEN RAISE EXCEPTION 'course run % does not exist', NEW.course_run_id; END IF;
    IF NEW.cohort_membership_id IS NOT NULL THEN
        SELECT employee_id, cohort_id INTO membership_employee_id, membership_cohort_id
        FROM cohort_memberships WHERE cohort_membership_id = NEW.cohort_membership_id;
        IF membership_employee_id <> NEW.employee_id OR membership_cohort_id <> run_cohort_id THEN
            RAISE EXCEPTION 'enrollment membership must belong to the employee and course run cohort';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_run_enrollment_relationships
BEFORE INSERT OR UPDATE OF course_run_id, employee_id, cohort_membership_id ON run_enrollments
FOR EACH ROW EXECUTE FUNCTION enforce_run_enrollment_relationships();

CREATE OR REPLACE FUNCTION protect_run_enrollment_snapshots()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.business_unit_id_snapshot IS DISTINCT FROM OLD.business_unit_id_snapshot
       OR NEW.job_role_id_snapshot IS DISTINCT FROM OLD.job_role_id_snapshot THEN
        RAISE EXCEPTION 'enrollment organization snapshots are immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_run_enrollment_snapshots_immutable
BEFORE UPDATE OF business_unit_id_snapshot, job_role_id_snapshot ON run_enrollments
FOR EACH ROW EXECUTE FUNCTION protect_run_enrollment_snapshots();
