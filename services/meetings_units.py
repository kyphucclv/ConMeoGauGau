"""Meeting schedule and credited session-unit commands."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class MeetingsUnitsCommands:
    def save_meeting(
        self,
        course_run_id: int,
        starts_at: datetime,
        duration_minutes: int,
        *,
        meeting_id=None,
        status="planned",
        cancellation_reason=None,
        change_reason: str | None = None,
    ) -> CommandResult:
        def op(cur):
            if duration_minutes <= 0: raise CommandError("invalid_input", "duration_minutes must be positive")
            if status not in {"planned", "completed", "cancelled"}: raise CommandError("invalid_input", "invalid meeting status")
            if status == "cancelled" and not cancellation_reason: raise CommandError("invalid_input", "cancellation_reason is required")
            if meeting_id:
                if status == "cancelled":
                    raise CommandError("invalid_input", "use the dedicated cancellation command")
                cur.execute(
                    """SELECT course_run_id,starts_at,duration_minutes,status,cancellation_reason
                       FROM meetings WHERE meeting_id=%s FOR UPDATE""",
                    (meeting_id,),
                )
                previous = cur.fetchone()
                if not previous:
                    raise CommandError("not_found", "meeting not found")
                if previous[0] != course_run_id:
                    raise CommandError("invalid_input", "meeting does not belong to the selected course run")
                if previous[3] == "cancelled":
                    raise CommandError("invalid_state", "cancelled meetings require a dedicated correction workflow")
                if previous[3] == "completed" and status == "planned":
                    raise CommandError("invalid_state", "completed meetings cannot return to planned status")
                cur.execute("SELECT %s::timestamptz", (starts_at,))
                normalized_starts_at = cur.fetchone()[0]
                schedule_changed = previous[1] != normalized_starts_at or previous[2] != duration_minutes
                reason = _normalize_label(change_reason)
                if schedule_changed and not reason:
                    raise CommandError("invalid_input", "change reason is required for a schedule correction")
                cur.execute("""UPDATE meetings SET starts_at=%s,duration_minutes=%s,status=%s,cancellation_reason=%s
                             WHERE meeting_id=%s RETURNING meeting_id""",(starts_at,duration_minutes,status,cancellation_reason,meeting_id))
                entity_id = cur.fetchone()[0]
                before = {
                    "course_run_id": previous[0], "starts_at": previous[1],
                    "duration_minutes": previous[2], "status": previous[3],
                    "cancellation_reason": previous[4],
                }
                after = {
                    "course_run_id": course_run_id, "starts_at": normalized_starts_at,
                    "duration_minutes": duration_minutes, "status": status,
                    "cancellation_reason": None,
                }
                self._audit(
                    cur,
                    "meeting.correct" if schedule_changed else "meeting.status",
                    "meeting",
                    entity_id,
                    {"reason": reason, "before": before, "after": after},
                )
            else:
                cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s FOR UPDATE", (course_run_id,))
                if not cur.fetchone():
                    raise CommandError("not_found", "course run not found")
                cur.execute("""INSERT INTO meetings(course_run_id,starts_at,duration_minutes,status,cancellation_reason)
                             VALUES(%s,%s,%s,%s,%s) RETURNING meeting_id""",(course_run_id,starts_at,duration_minutes,status,cancellation_reason))
                entity_id = cur.fetchone()[0]
                self._audit(cur, "meeting.create", "meeting", entity_id, {
                    "after": {
                        "course_run_id": course_run_id, "starts_at": starts_at,
                        "duration_minutes": duration_minutes, "status": status,
                        "cancellation_reason": cancellation_reason if status == "cancelled" else None,
                    }
                })
            return CommandResult("meeting",entity_id,{"status":status})
        return self._run({"admin","editor"},op)

    def cancel_meeting(self, meeting_id: int, reason: str) -> CommandResult:
        def op(cur):
            clean_reason = _normalize_label(_required(reason, "reason"))
            cur.execute(
                """SELECT course_run_id,starts_at,duration_minutes,status,cancellation_reason
                   FROM meetings WHERE meeting_id=%s FOR UPDATE""",
                (meeting_id,),
            )
            previous = cur.fetchone()
            if not previous:
                raise CommandError("not_found", "meeting not found")
            if previous[3] == "cancelled":
                raise CommandError("invalid_state", "meeting is already cancelled")
            cur.execute(
                """UPDATE meetings SET status='cancelled',cancellation_reason=%s
                   WHERE meeting_id=%s RETURNING meeting_id""",
                (clean_reason, meeting_id),
            )
            entity_id = cur.fetchone()[0]
            before = {
                "course_run_id": previous[0], "starts_at": previous[1],
                "duration_minutes": previous[2], "status": previous[3],
                "cancellation_reason": previous[4],
            }
            after = dict(before)
            after.update({"status": "cancelled", "cancellation_reason": clean_reason})
            self._audit(cur, "meeting.cancel", "meeting", entity_id, {
                "reason": clean_reason, "before": before, "after": after,
            })
            return CommandResult("meeting", entity_id, {"status": "cancelled"})
        return self._run({"admin", "editor"}, op)

    def create_meeting_with_units(
        self,
        course_run_id: int,
        starts_at: datetime,
        duration_minutes: int,
        first_sequence_in_run: int,
        *,
        unit_count: int = 1,
        unit_type: str = "normal",
        status: str = "planned",
    ) -> CommandResult:
        """Create one meeting and all credited units in one transaction."""
        def op(cur):
            if duration_minutes <= 0 or first_sequence_in_run < 1:
                raise CommandError("invalid_input", "duration and first session number must be positive")
            if unit_count not in {1, 2}:
                raise CommandError("invalid_input", "a meeting must create one or two credited units")
            if unit_type not in {"normal", "final_test", "makeup", "admin"}:
                raise CommandError("invalid_input", "invalid unit type")
            if unit_type != "normal" and unit_count != 1:
                raise CommandError("invalid_input", "only normal meetings may create two credited units")
            if status not in {"planned", "completed"}:
                raise CommandError("invalid_input", "new meeting status must be planned or completed")
            self._advisory_lock(cur, f"meeting_units:{course_run_id}")
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s FOR UPDATE", (course_run_id,))
            if not cur.fetchone():
                raise CommandError("not_found", "course run not found")
            cur.execute(
                """INSERT INTO meetings(course_run_id,starts_at,duration_minutes,status)
                   VALUES(%s,%s,%s,%s) RETURNING meeting_id""",
                (course_run_id, starts_at, duration_minutes, status),
            )
            meeting_id = cur.fetchone()[0]
            unit_ids = []
            for offset in range(unit_count):
                cur.execute(
                    """INSERT INTO session_units(
                           course_run_id,meeting_id,sequence_in_run,unit_number_in_meeting,unit_type
                       ) VALUES(%s,%s,%s,%s,%s) RETURNING session_unit_id""",
                    (course_run_id, meeting_id, first_sequence_in_run + offset, offset + 1, unit_type),
                )
                unit_ids.append(cur.fetchone()[0])
            self._audit(cur, "meeting.units.create", "meeting", meeting_id, {
                "course_run_id": course_run_id,
                "starts_at": starts_at,
                "duration_minutes": duration_minutes,
                "status": status,
                "unit_type": unit_type,
                "session_unit_ids": unit_ids,
                "sequence_numbers": [first_sequence_in_run + offset for offset in range(unit_count)],
            })
            return CommandResult("meeting", meeting_id, {"session_unit_ids": unit_ids})
        return self._run({"admin", "editor"}, op)

    def add_session_units(
        self,
        course_run_id: int,
        meeting_id: int,
        first_sequence_in_run: int,
        *,
        unit_count: int = 1,
        unit_type: str = "normal",
    ) -> CommandResult:
        """Add one or two units to an existing meeting without partial commit."""
        def op(cur):
            if first_sequence_in_run < 1 or unit_count not in {1, 2}:
                raise CommandError("invalid_input", "first session number and unit count are invalid")
            if unit_type not in {"normal", "final_test", "makeup", "admin"}:
                raise CommandError("invalid_input", "invalid unit type")
            if unit_type != "normal" and unit_count != 1:
                raise CommandError("invalid_input", "only normal meetings may create two credited units")
            self._advisory_lock(cur, f"meeting_units:{course_run_id}")
            cur.execute(
                "SELECT status FROM meetings WHERE meeting_id=%s AND course_run_id=%s FOR UPDATE",
                (meeting_id, course_run_id),
            )
            meeting = cur.fetchone()
            if not meeting:
                raise CommandError("not_found", "meeting does not belong to the selected course run")
            if meeting[0] == "cancelled":
                raise CommandError("invalid_state", "cancelled meetings cannot receive credited units")
            unit_ids = []
            for offset in range(unit_count):
                cur.execute(
                    """INSERT INTO session_units(
                           course_run_id,meeting_id,sequence_in_run,unit_number_in_meeting,unit_type
                       ) VALUES(%s,%s,%s,%s,%s) RETURNING session_unit_id""",
                    (course_run_id, meeting_id, first_sequence_in_run + offset, offset + 1, unit_type),
                )
                unit_ids.append(cur.fetchone()[0])
            self._audit(cur, "meeting.units.add", "meeting", meeting_id, {
                "session_unit_ids": unit_ids,
                "sequence_numbers": [first_sequence_in_run + offset for offset in range(unit_count)],
                "unit_type": unit_type,
            })
            return CommandResult("session_unit", None, {"session_unit_ids": unit_ids})
        return self._run({"admin", "editor"}, op)

    def add_session_unit(self, course_run_id: int, meeting_id: int, sequence_in_run: int, *, unit_number_in_meeting=1, unit_type="normal", title=None) -> CommandResult:
        def op(cur):
            if unit_type not in {"normal","final_test","makeup","admin"}: raise CommandError("invalid_input","invalid unit type")
            cur.execute("""INSERT INTO session_units(course_run_id,meeting_id,sequence_in_run,unit_number_in_meeting,unit_type,title)
                         VALUES(%s,%s,%s,%s,%s,%s) RETURNING session_unit_id""",(course_run_id,meeting_id,sequence_in_run,unit_number_in_meeting,unit_type,title))
            entity_id=cur.fetchone()[0]; self._audit(cur,"session_unit.create","session_unit",entity_id); return CommandResult("session_unit",entity_id,{})
        return self._run({"admin","editor"},op)

    def create_attendance_session(self, course_run_id: int, starts_at: datetime, duration_minutes: int, sequence_in_run: int) -> CommandResult:
        """Create one planned meeting and its credited attendance unit atomically."""
        def op(cur):
            if duration_minutes <= 0 or sequence_in_run < 1:
                raise CommandError("invalid_input", "duration and session number must be positive")
            self._advisory_lock(cur, f"attendance_session:{course_run_id}")
            cur.execute("SELECT status FROM course_runs WHERE course_run_id=%s FOR UPDATE", (course_run_id,))
            run = cur.fetchone()
            if not run:
                raise CommandError("not_found", "course run not found")
            if run[0] not in {"planned", "active"}:
                raise CommandError("invalid_state", "attendance sessions require a planned or active course run")
            cur.execute("""SELECT COALESCE(MAX(su.sequence_in_run), 0) + 1
                           FROM session_units su
                           JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.course_run_id=%s AND m.status <> 'cancelled'""", (course_run_id,))
            if cur.fetchone()[0] != sequence_in_run:
                raise CommandError("stale_proposal", "next session number changed; reload the course run before saving")
            cur.execute("""INSERT INTO meetings(course_run_id,starts_at,duration_minutes,status)
                           VALUES(%s,%s,%s,'planned') RETURNING meeting_id""", (course_run_id, starts_at, duration_minutes))
            meeting_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO session_units(course_run_id,meeting_id,sequence_in_run,unit_number_in_meeting,unit_type)
                           VALUES(%s,%s,%s,1,'normal') RETURNING session_unit_id""", (course_run_id, meeting_id, sequence_in_run))
            session_unit_id = cur.fetchone()[0]
            self._audit(cur, "attendance.session.create", "session_unit", session_unit_id,
                        {"course_run_id": course_run_id, "meeting_id": meeting_id, "sequence_in_run": sequence_in_run})
            return CommandResult("session_unit", session_unit_id, {"meeting_id": meeting_id, "sequence_in_run": sequence_in_run})
        return self._run({"admin", "editor"}, op)

    def propose_next_attendance_session(self, course_run_id: int) -> CommandResult:
        """Return the next logical session number for attendance entry."""
        def op(cur):
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s", (course_run_id,))
            if not cur.fetchone():
                raise CommandError("not_found", "course run not found")
            cur.execute("""SELECT COALESCE(MAX(su.sequence_in_run), 0) + 1
                           FROM session_units su
                           JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.course_run_id=%s AND m.status <> 'cancelled'""", (course_run_id,))
            return CommandResult("course_run", course_run_id, {"sequence_in_run": cur.fetchone()[0]})
        return self._run({"admin", "editor", "viewer"}, op)
