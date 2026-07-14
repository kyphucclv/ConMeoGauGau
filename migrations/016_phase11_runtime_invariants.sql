-- Phase 11 runtime invariants.
-- Grain: one attendance row must belong to the selected learner's course run
-- and to a session that is applicable from the learner's start session.
-- Forward verification: run scripts/phase11_p11_1_integration.py and Phase 6
-- security role checks after applying this migration.
-- Rollback: restore the pre-migration backup; do not weaken attendance facts
-- in place after production writes have begun.

CREATE OR REPLACE FUNCTION enforce_attendance_run_relationships()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    enrollment_course_run_id BIGINT;
    enrollment_start_session SMALLINT;
    session_course_run_id BIGINT;
    session_sequence SMALLINT;
BEGIN
    SELECT course_run_id, start_session_number
    INTO enrollment_course_run_id, enrollment_start_session
    FROM run_enrollments
    WHERE run_enrollment_id = NEW.run_enrollment_id;

    IF enrollment_course_run_id IS NULL THEN
        RAISE EXCEPTION 'run enrollment % does not exist', NEW.run_enrollment_id;
    END IF;

    SELECT course_run_id, sequence_in_run
    INTO session_course_run_id, session_sequence
    FROM session_units
    WHERE session_unit_id = NEW.session_unit_id;

    IF session_course_run_id IS NULL THEN
        RAISE EXCEPTION 'session unit % does not exist', NEW.session_unit_id;
    END IF;

    IF session_course_run_id <> enrollment_course_run_id THEN
        RAISE EXCEPTION 'attendance session must belong to the enrollment course run';
    END IF;

    IF session_sequence < enrollment_start_session THEN
        RAISE EXCEPTION 'attendance session is before the enrollment start session';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_attendance_run_relationships ON attendance;
CREATE TRIGGER trg_attendance_run_relationships
BEFORE INSERT OR UPDATE OF run_enrollment_id, session_unit_id ON attendance
FOR EACH ROW EXECUTE FUNCTION enforce_attendance_run_relationships();
