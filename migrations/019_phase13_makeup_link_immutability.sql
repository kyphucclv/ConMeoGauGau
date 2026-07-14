-- Phase 13 make-up link immutability hardening.
-- Grain remains one linked make-up attendance row per original absence.
-- Once created, its semantic relationship fields are immutable. An original
-- absence with linked credit cannot be reassigned to another session.
-- Forward verification: Phase 8 rejects a direct semantic update to the linked
-- make-up row and all Phase 4/5/7/8 gates retain replacement-credit results.
-- Rollback: restore the pre-018 production backup; do not weaken immutable
-- attendance history in place after linked make-up writes exist.

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
    IF TG_OP = 'UPDATE' AND OLD.is_makeup THEN
        RAISE EXCEPTION 'linked make-up attendance relationship is immutable';
    END IF;

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
                  OR (
                      TG_OP = 'UPDATE'
                      AND NEW.session_unit_id IS DISTINCT FROM OLD.session_unit_id
                  )
              )
        ) THEN
            RAISE EXCEPTION 'an absence with make-up credit cannot be rewritten or reassigned';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
