"""Attendance and make-up credit rules (invariants 5 and 6).

A linked make-up preserves the original absence, credits the logical unit as
present, adds no denominator unit, and is protected against rewrites.
Cancelled meetings never count toward the attendance denominator.
"""

from __future__ import annotations

import psycopg2
import pytest

from services import CommandError


def _save_roster(admin_svc, run_id: int, unit_id: int, enrollment_id: int, status: str):
    return admin_svc.save_attendance_roster(
        run_id, unit_id, [{"run_enrollment_id": enrollment_id, "effective_status": status}]
    )


def _view_rollup(factory, enrollment_id: int):
    return factory.one(
        """SELECT applicable_units, present_units, makeup_present_units, attendance_ratio
           FROM v_run_enrollment_attendance WHERE run_enrollment_id=%s""",
        (enrollment_id,),
    )


@pytest.fixture
def absence(factory, admin_svc):
    """One learner with a saved absence on session 1; returns the working set."""
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id
    _, unit_id = factory.meeting_unit(run_id, 1)
    _save_roster(admin_svc, run_id, unit_id, enrollment_id, "Absent")
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s AND session_unit_id=%s",
        (enrollment_id, unit_id),
    )[0]
    return {"run_id": run_id, "enrollment_id": enrollment_id, "attendance_id": attendance_id}


def test_makeup_credits_without_denominator_unit(factory, admin_svc, absence):
    before = _view_rollup(factory, absence["enrollment_id"])
    assert (before[0], before[1]) == (1, 0)

    _, makeup_unit = factory.meeting_unit(absence["run_id"], 2, unit_type="makeup", day_offset=7)
    admin_svc.correct_attendance_makeup(absence["attendance_id"], makeup_unit, "doctor note")

    after = _view_rollup(factory, absence["enrollment_id"])
    assert after[0] == 1, "make-up unit must not enter the denominator"
    assert after[1] == 1, "linked make-up must credit the original sequence as present"
    assert after[2] == 1
    assert float(after[3]) == 1.0

    original = factory.one(
        "SELECT effective_status FROM attendance WHERE attendance_id=%s", (absence["attendance_id"],)
    )
    assert original[0] == "Absent", "original absence row must remain unchanged"


def test_second_makeup_for_same_absence_is_rejected(factory, admin_svc, absence):
    _, first_unit = factory.meeting_unit(absence["run_id"], 2, unit_type="makeup", day_offset=7)
    admin_svc.correct_attendance_makeup(absence["attendance_id"], first_unit, "doctor note")

    _, second_unit = factory.meeting_unit(absence["run_id"], 3, unit_type="makeup", day_offset=14)
    with pytest.raises(CommandError) as excinfo:
        admin_svc.correct_attendance_makeup(absence["attendance_id"], second_unit, "second try")
    assert excinfo.value.code == "duplicate_makeup"


def test_absence_with_makeup_credit_cannot_be_rewritten(factory, admin_svc, conn, absence):
    _, makeup_unit = factory.meeting_unit(absence["run_id"], 2, unit_type="makeup", day_offset=7)
    admin_svc.correct_attendance_makeup(absence["attendance_id"], makeup_unit, "doctor note")

    with pytest.raises(psycopg2.Error):
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE attendance SET effective_status='Present' WHERE attendance_id=%s",
                    (absence["attendance_id"],),
                )


def test_makeup_requires_original_absence(factory, admin_svc):
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id
    _, unit_id = factory.meeting_unit(run_id, 1)
    _save_roster(admin_svc, run_id, unit_id, enrollment_id, "Present")
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s", (enrollment_id,)
    )[0]
    _, makeup_unit = factory.meeting_unit(run_id, 2, unit_type="makeup", day_offset=7)
    with pytest.raises(CommandError) as excinfo:
        admin_svc.correct_attendance_makeup(attendance_id, makeup_unit, "not needed")
    assert excinfo.value.code == "invalid_state"


def test_cancelled_meeting_excluded_from_denominator(factory, admin_svc, absence):
    meeting_id, _ = factory.meeting_unit(absence["run_id"], 3, day_offset=3)
    admin_svc.cancel_meeting(meeting_id, "teacher unavailable")
    rollup = _view_rollup(factory, absence["enrollment_id"])
    assert rollup[0] == 1, "cancelled meetings must not add applicable units"
