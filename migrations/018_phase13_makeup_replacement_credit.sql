-- Phase 13 make-up replacement-credit policy.
-- Grain: one make-up attendance row represents one learner present at one
-- make-up session and links to exactly one original absence for that enrollment.
-- The linked absence remains unchanged; reporting credits its logical sequence
-- as present and excludes the make-up unit from the attendance denominator.
-- Forward verification: run Phase 4, Phase 5, Phase 7, and Phase 8 gates, then
-- inspect v_run_enrollment_attendance for a linked make-up fixture.
-- Rollback: restore the pre-migration database backup. Do not drop these guards
-- after replacement-credit attendance has been written in production.

ALTER TABLE attendance
    ADD CONSTRAINT ck_attendance_makeup_link_shape
    CHECK (
        (is_makeup AND makeup_for_attendance_id IS NOT NULL AND effective_status = 'Present')
        OR
        (NOT is_makeup AND makeup_for_attendance_id IS NULL)
    );

CREATE UNIQUE INDEX uq_attendance_one_makeup_per_original
    ON attendance(makeup_for_attendance_id)
    WHERE makeup_for_attendance_id IS NOT NULL;

CREATE OR REPLACE FUNCTION enforce_attendance_makeup_relationships()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_unit_type TEXT;
    target_starts_at TIMESTAMPTZ;
    target_meeting_status TEXT;
    original_enrollment_id BIGINT;
    original_status TEXT;
    original_is_makeup BOOLEAN;
    original_starts_at TIMESTAMPTZ;
    original_meeting_status TEXT;
BEGIN
    SELECT su.unit_type, m.starts_at, m.status
    INTO target_unit_type, target_starts_at, target_meeting_status
    FROM session_units su
    JOIN meetings m ON m.meeting_id = su.meeting_id
    WHERE su.session_unit_id = NEW.session_unit_id;

    IF NEW.is_makeup THEN
        IF target_unit_type IS DISTINCT FROM 'makeup' THEN
            RAISE EXCEPTION 'make-up attendance must use a make-up session unit';
        END IF;

        SELECT original.run_enrollment_id, original.effective_status,
               original.is_makeup, original_meeting.starts_at,
               original_meeting.status
        INTO original_enrollment_id, original_status, original_is_makeup,
             original_starts_at, original_meeting_status
        FROM attendance original
        JOIN session_units original_unit
          ON original_unit.session_unit_id = original.session_unit_id
        JOIN meetings original_meeting
          ON original_meeting.meeting_id = original_unit.meeting_id
        WHERE original.attendance_id = NEW.makeup_for_attendance_id;

        IF original_enrollment_id IS NULL THEN
            RAISE EXCEPTION 'original attendance does not exist';
        END IF;
        IF original_is_makeup OR original_status <> 'Absent' THEN
            RAISE EXCEPTION 'make-up credit requires an original non-make-up absence';
        END IF;
        IF original_enrollment_id <> NEW.run_enrollment_id THEN
            RAISE EXCEPTION 'make-up credit must belong to the original enrollment';
        END IF;
        IF original_meeting_status <> 'completed' THEN
            RAISE EXCEPTION 'make-up credit requires a completed original session';
        END IF;
        IF target_meeting_status = 'cancelled' THEN
            RAISE EXCEPTION 'cancelled sessions cannot provide make-up credit';
        END IF;
        IF target_starts_at <= original_starts_at THEN
            RAISE EXCEPTION 'make-up session must occur after the original absence';
        END IF;
    ELSE
        IF target_unit_type = 'makeup' THEN
            RAISE EXCEPTION 'make-up session attendance must link to an original absence';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM attendance linked
            WHERE linked.makeup_for_attendance_id = NEW.attendance_id
              AND (
                  NEW.effective_status <> 'Absent'
                  OR NEW.is_makeup
                  OR linked.run_enrollment_id <> NEW.run_enrollment_id
              )
        ) THEN
            RAISE EXCEPTION 'an absence with make-up credit cannot be rewritten or reassigned';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_attendance_makeup_relationships ON attendance;
CREATE TRIGGER trg_attendance_makeup_relationships
BEFORE INSERT OR UPDATE OF run_enrollment_id, session_unit_id, effective_status,
    is_makeup, makeup_for_attendance_id
ON attendance
FOR EACH ROW EXECUTE FUNCTION enforce_attendance_makeup_relationships();

CREATE OR REPLACE FUNCTION protect_attended_session_unit_type()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.unit_type IS DISTINCT FROM OLD.unit_type
       AND EXISTS (
           SELECT 1 FROM attendance WHERE session_unit_id = OLD.session_unit_id
       ) THEN
        RAISE EXCEPTION 'session unit type is immutable after attendance exists';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_attended_session_unit_type_immutable ON session_units;
CREATE TRIGGER trg_attended_session_unit_type_immutable
BEFORE UPDATE OF unit_type ON session_units
FOR EACH ROW EXECUTE FUNCTION protect_attended_session_unit_type();

CREATE OR REPLACE VIEW v_reporting_metric_definitions AS
SELECT *
FROM (VALUES
    ('attendance_ratio', 'Attendance ratio', 'Present applicable logical sessions divided by applicable non-cancelled non-make-up logical sessions on or after enrollment.start_session_number. A linked make-up credits its original absence without adding a denominator unit.', 'direct Present or valid linked make-up replacement credit', 'distinct non-cancelled non-make-up session sequence in the enrollment range'),
    ('effective_exam_eligible', 'Effective exam eligibility', 'Admin override from the latest evaluation version when present; otherwise calculated attendance ratio >= course_run attendance threshold.', 'latest evaluation override or calculated eligibility', 'one run_enrollment'),
    ('sessions_per_month', 'Sessions per month', 'Credited non-final-test session units in completed meetings by calendar month. Final-test duration minutes do not inflate this count.', 'completed non-cancelled session_units where unit_type is not final_test', 'calendar month'),
    ('current_level', 'Current level', 'Final level from the latest evaluation version with a final level for the employee.', 'latest final_level_id by evaluation version creation order', 'one employee'),
    ('highest_level', 'Highest level', 'Maximum final level numeric value reached across all evaluation versions for the employee.', 'max(level.numeric_value)', 'one employee'),
    ('current_progress', 'Current progress', 'Current level numeric value minus business placement numeric value.', 'latest final level numeric - placement numeric', 'one employee with placement and current level'),
    ('peak_progress', 'Peak progress', 'Highest level numeric value minus business placement numeric value.', 'highest final level numeric - placement numeric', 'one employee with placement and highest level'),
    ('regression_flag', 'Regression flag', 'True when the latest final level is lower than the immediately preceding final level.', 'latest final level numeric < previous final level numeric', 'employee with at least two final-level evaluation versions'),
    ('unresolved_quality_issues', 'Unresolved quality issues', 'Open canonical data quality issues and issue-type ETL row outcomes that should not silently enter schedule-dependent KPIs.', 'open issues or issue outcomes', 'quality issue ledger')
) AS d(metric_key, metric_name, definition, numerator_definition, denominator_definition);

CREATE OR REPLACE VIEW v_run_enrollment_attendance AS
WITH applicable_sequences AS (
    SELECT DISTINCT
        re.run_enrollment_id,
        su.sequence_in_run
    FROM run_enrollments re
    JOIN session_units su
        ON su.course_run_id = re.course_run_id
       AND su.sequence_in_run >= re.start_session_number
       AND su.unit_type <> 'makeup'
    JOIN meetings m
        ON m.meeting_id = su.meeting_id
       AND m.status <> 'cancelled'
),
attendance_by_sequence AS (
    SELECT
        original.run_enrollment_id,
        original_unit.sequence_in_run,
        bool_or(
            original.effective_status = 'Present'
            OR makeup_meeting.meeting_id IS NOT NULL
        ) AS is_present,
        bool_or(original.effective_status = 'Absent') AS is_absent,
        bool_or(makeup_meeting.meeting_id IS NOT NULL) AS is_makeup_present
    FROM attendance original
    JOIN session_units original_unit
      ON original_unit.session_unit_id = original.session_unit_id
     AND original_unit.unit_type <> 'makeup'
    JOIN meetings original_meeting
      ON original_meeting.meeting_id = original_unit.meeting_id
     AND original_meeting.status <> 'cancelled'
    LEFT JOIN attendance credited_makeup
      ON credited_makeup.makeup_for_attendance_id = original.attendance_id
     AND credited_makeup.is_makeup
     AND credited_makeup.effective_status = 'Present'
    LEFT JOIN session_units makeup_unit
      ON makeup_unit.session_unit_id = credited_makeup.session_unit_id
     AND makeup_unit.unit_type = 'makeup'
    LEFT JOIN meetings makeup_meeting
      ON makeup_meeting.meeting_id = makeup_unit.meeting_id
     AND makeup_meeting.status = 'completed'
    GROUP BY original.run_enrollment_id, original_unit.sequence_in_run
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
