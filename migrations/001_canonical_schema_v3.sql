-- Canonical v3 schema for the English Class Management system.
-- This migration is intended for an empty/disposable database first. Legacy
-- workbook rows are loaded later through auditable staging and ETL phases.

CREATE TABLE app_users (
    user_id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_events (
    audit_event_id BIGSERIAL PRIMARY KEY,
    actor_user_id BIGINT REFERENCES app_users(user_id),
    actor_username TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_key TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE import_batches (
    import_batch_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_name, source_checksum),
    CHECK (
        (status = 'completed' AND completed_at IS NOT NULL AND failed_at IS NULL)
        OR (status = 'failed' AND failed_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'running' AND completed_at IS NULL AND failed_at IS NULL)
    )
);

CREATE TABLE data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    import_batch_id BIGINT REFERENCES import_batches(import_batch_id),
    issue_code TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_key TEXT,
    source_sheet TEXT,
    source_row_number INTEGER CHECK (source_row_number IS NULL OR source_row_number > 0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by_user_id BIGINT REFERENCES app_users(user_id),
    resolution_note TEXT,
    CHECK (
        (status = 'open' AND resolved_at IS NULL AND resolved_by_user_id IS NULL)
        OR (status IN ('resolved', 'ignored') AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)
    )
);

CREATE TABLE levels (
    level_id BIGSERIAL PRIMARY KEY,
    level_name TEXT NOT NULL UNIQUE,
    numeric_value NUMERIC(3,1) NOT NULL UNIQUE CHECK (numeric_value >= 0.0 AND numeric_value <= 6.5),
    sequence_order SMALLINT NOT NULL UNIQUE CHECK (sequence_order > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE courses (
    course_id BIGSERIAL PRIMARY KEY,
    course_code TEXT NOT NULL UNIQUE,
    course_name TEXT NOT NULL UNIQUE,
    expected_units SMALLINT NOT NULL CHECK (expected_units > 0),
    attendance_threshold_ratio NUMERIC(4,3) NOT NULL DEFAULT 0.800
        CHECK (attendance_threshold_ratio >= 0.000 AND attendance_threshold_ratio <= 1.000),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE business_units (
    business_unit_id BIGSERIAL PRIMARY KEY,
    business_unit_name TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE job_roles (
    job_role_id BIGSERIAL PRIMARY KEY,
    job_role_name TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE employees (
    employee_id BIGSERIAL PRIMARY KEY,
    emp_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    english_name TEXT,
    email TEXT,
    employment_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (employment_status IN ('active', 'inactive', 'unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE employee_org_history (
    employee_org_history_id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    business_unit_id BIGINT REFERENCES business_units(business_unit_id),
    job_role_id BIGINT REFERENCES job_roles(job_role_id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    observed_from TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK ((is_current AND valid_to IS NULL) OR NOT is_current)
);

CREATE UNIQUE INDEX uq_employee_one_current_org
    ON employee_org_history(employee_id)
    WHERE is_current;

CREATE TABLE cohorts (
    cohort_id BIGSERIAL PRIMARY KEY,
    class_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'active', 'completed', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE cohort_memberships (
    cohort_membership_id BIGSERIAL PRIMARY KEY,
    cohort_id BIGINT NOT NULL REFERENCES cohorts(cohort_id),
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    start_date DATE NOT NULL,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'transferred', 'cancelled')),
    transfer_to_membership_id BIGINT REFERENCES cohort_memberships(cohort_membership_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK ((status = 'active' AND end_date IS NULL) OR status <> 'active')
);

CREATE UNIQUE INDEX uq_employee_one_active_cohort_membership
    ON cohort_memberships(employee_id)
    WHERE status = 'active';

CREATE UNIQUE INDEX uq_employee_cohort_membership_start
    ON cohort_memberships(employee_id, cohort_id, start_date);

CREATE TABLE cohort_pic_assignments (
    cohort_pic_assignment_id BIGSERIAL PRIMARY KEY,
    cohort_id BIGINT NOT NULL REFERENCES cohorts(cohort_id),
    pic_employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    start_date DATE NOT NULL,
    end_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE UNIQUE INDEX uq_cohort_one_current_pic
    ON cohort_pic_assignments(cohort_id)
    WHERE end_date IS NULL;

CREATE TABLE course_runs (
    course_run_id BIGSERIAL PRIMARY KEY,
    cohort_id BIGINT NOT NULL REFERENCES cohorts(cohort_id),
    course_id BIGINT NOT NULL REFERENCES courses(course_id),
    run_number SMALLINT NOT NULL CHECK (run_number > 0),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'active', 'completed', 'cancelled', 'archived')),
    expected_units_snapshot SMALLINT NOT NULL CHECK (expected_units_snapshot > 0),
    attendance_threshold_ratio_snapshot NUMERIC(4,3) NOT NULL
        CHECK (attendance_threshold_ratio_snapshot >= 0.000 AND attendance_threshold_ratio_snapshot <= 1.000),
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cohort_id, course_id, run_number),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE run_enrollments (
    run_enrollment_id BIGSERIAL PRIMARY KEY,
    course_run_id BIGINT NOT NULL REFERENCES course_runs(course_run_id),
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    cohort_membership_id BIGINT REFERENCES cohort_memberships(cohort_membership_id),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'transferred', 'dropped', 'cancelled')),
    start_session_number SMALLINT NOT NULL DEFAULT 1 CHECK (start_session_number > 0),
    business_unit_id_snapshot BIGINT REFERENCES business_units(business_unit_id),
    job_role_id_snapshot BIGINT REFERENCES job_roles(job_role_id),
    transfer_from_enrollment_id BIGINT REFERENCES run_enrollments(run_enrollment_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (course_run_id, employee_id)
);

CREATE TABLE meetings (
    meeting_id BIGSERIAL PRIMARY KEY,
    course_run_id BIGINT NOT NULL REFERENCES course_runs(course_run_id),
    starts_at TIMESTAMPTZ NOT NULL,
    duration_minutes SMALLINT NOT NULL CHECK (duration_minutes > 0),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'completed', 'cancelled')),
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (course_run_id, starts_at),
    CHECK ((status = 'cancelled' AND cancellation_reason IS NOT NULL) OR status <> 'cancelled')
);

CREATE TABLE session_units (
    session_unit_id BIGSERIAL PRIMARY KEY,
    course_run_id BIGINT NOT NULL REFERENCES course_runs(course_run_id),
    meeting_id BIGINT NOT NULL REFERENCES meetings(meeting_id),
    sequence_in_run SMALLINT NOT NULL CHECK (sequence_in_run > 0),
    unit_number_in_meeting SMALLINT NOT NULL CHECK (unit_number_in_meeting > 0),
    unit_type TEXT NOT NULL DEFAULT 'normal'
        CHECK (unit_type IN ('normal', 'final_test', 'makeup', 'admin')),
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (course_run_id, sequence_in_run),
    UNIQUE (meeting_id, unit_number_in_meeting)
);

CREATE OR REPLACE FUNCTION enforce_session_unit_meeting_rules()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    normal_units INTEGER;
    meeting_run_id BIGINT;
BEGIN
    SELECT course_run_id INTO meeting_run_id
    FROM meetings
    WHERE meeting_id = NEW.meeting_id;

    IF meeting_run_id IS NULL THEN
        RAISE EXCEPTION 'meeting % does not exist', NEW.meeting_id;
    END IF;

    IF meeting_run_id <> NEW.course_run_id THEN
        RAISE EXCEPTION 'session unit course_run_id must match its meeting';
    END IF;

    IF NEW.unit_type = 'normal' THEN
        SELECT count(*) INTO normal_units
        FROM session_units
        WHERE meeting_id = NEW.meeting_id
          AND unit_type = 'normal'
          AND session_unit_id <> COALESCE(NEW.session_unit_id, -1);

        IF normal_units >= 2 THEN
            RAISE EXCEPTION 'a meeting cannot have more than two normal session units';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_session_unit_meeting_rules
BEFORE INSERT OR UPDATE ON session_units
FOR EACH ROW EXECUTE FUNCTION enforce_session_unit_meeting_rules();

CREATE TABLE attendance (
    attendance_id BIGSERIAL PRIMARY KEY,
    run_enrollment_id BIGINT NOT NULL REFERENCES run_enrollments(run_enrollment_id),
    session_unit_id BIGINT NOT NULL REFERENCES session_units(session_unit_id),
    effective_status TEXT NOT NULL CHECK (effective_status IN ('Present', 'Absent')),
    original_status TEXT,
    is_makeup BOOLEAN NOT NULL DEFAULT FALSE,
    makeup_for_attendance_id BIGINT REFERENCES attendance(attendance_id),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_enrollment_id, session_unit_id)
);

CREATE TABLE placements (
    placement_id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(employee_id),
    placement_kind TEXT NOT NULL DEFAULT 'business'
        CHECK (placement_kind IN ('business', 'diagnostic', 'other')),
    test_date DATE,
    level_id BIGINT REFERENCES levels(level_id),
    grammar_feedback TEXT,
    vocabulary_feedback TEXT,
    pronunciation_feedback TEXT,
    fluency_feedback TEXT,
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (employee_id, placement_kind)
);

CREATE TABLE evaluations (
    evaluation_id BIGSERIAL PRIMARY KEY,
    run_enrollment_id BIGINT NOT NULL UNIQUE REFERENCES run_enrollments(run_enrollment_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE evaluation_versions (
    evaluation_version_id BIGSERIAL PRIMARY KEY,
    evaluation_id BIGINT NOT NULL REFERENCES evaluations(evaluation_id),
    version_number SMALLINT NOT NULL CHECK (version_number > 0),
    final_level_id BIGINT REFERENCES levels(level_id),
    exam_eligible BOOLEAN,
    exam_eligibility_override BOOLEAN NOT NULL DEFAULT FALSE,
    exam_eligibility_override_reason TEXT,
    passed BOOLEAN,
    next_course_id BIGINT REFERENCES courses(course_id),
    teacher_notes TEXT,
    correction_reason TEXT,
    created_by_user_id BIGINT REFERENCES app_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (evaluation_id, version_number),
    CHECK (
        NOT exam_eligibility_override
        OR exam_eligibility_override_reason IS NOT NULL
    ),
    CHECK (version_number = 1 OR correction_reason IS NOT NULL)
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_app_users_updated_at
BEFORE UPDATE ON app_users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_employees_updated_at
BEFORE UPDATE ON employees
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_cohorts_updated_at
BEFORE UPDATE ON cohorts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_course_runs_updated_at
BEFORE UPDATE ON course_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_run_enrollments_updated_at
BEFORE UPDATE ON run_enrollments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_meetings_updated_at
BEFORE UPDATE ON meetings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_attendance_updated_at
BEFORE UPDATE ON attendance
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_audit_events_entity ON audit_events(entity_type, entity_key);
CREATE INDEX idx_audit_events_created_at ON audit_events(created_at DESC);
CREATE INDEX idx_quality_open ON data_quality_issues(status, issue_code)
    WHERE status = 'open';
CREATE INDEX idx_employee_org_employee ON employee_org_history(employee_id);
CREATE INDEX idx_cohort_memberships_employee ON cohort_memberships(employee_id);
CREATE INDEX idx_pic_assignments_employee ON cohort_pic_assignments(pic_employee_id);
CREATE INDEX idx_course_runs_course ON course_runs(course_id);
CREATE INDEX idx_run_enrollments_employee ON run_enrollments(employee_id);
CREATE INDEX idx_meetings_run_date ON meetings(course_run_id, starts_at);
CREATE INDEX idx_session_units_run_sequence ON session_units(course_run_id, sequence_in_run);
CREATE INDEX idx_attendance_unit ON attendance(session_unit_id);
CREATE INDEX idx_placements_employee ON placements(employee_id);
CREATE INDEX idx_evaluation_versions_eval ON evaluation_versions(evaluation_id, version_number DESC);
