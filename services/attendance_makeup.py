"""Attendance roster entry and linked make-up credit commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class AttendanceMakeupCommands:
    def attendance_roster(self, course_run_id: int, session_unit_id: int) -> CommandResult:
        """Return the event-time roster without inventing historical attendance."""
        def op(cur):
            unit, rows = self._attendance_roster_in_tx(cur, course_run_id, session_unit_id)
            return CommandResult("attendance_roster", session_unit_id, {
                "sequence_in_run": unit[0], "meeting_status": unit[1], "starts_at": unit[3], "rows": rows,
            })
        return self._run({"admin", "editor", "viewer"}, op)

    def save_attendance_roster(self, course_run_id: int, session_unit_id: int, records: Iterable[dict[str, Any]]) -> CommandResult:
        """Write exactly one selected session's full applicable roster in one transaction."""
        records = list(records)
        def op(cur):
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s FOR UPDATE", (course_run_id,))
            if not cur.fetchone(): raise CommandError("not_found", "course run not found")
            cur.execute("""SELECT su.sequence_in_run,m.status,m.meeting_id
                           FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.session_unit_id=%s AND su.course_run_id=%s
                           FOR UPDATE OF su,m""", (session_unit_id, course_run_id))
            unit = cur.fetchone()
            if not unit: raise CommandError("not_found", "session unit does not belong to the selected course run")
            if unit[1] == "cancelled": raise CommandError("invalid_state", "cancelled sessions cannot receive attendance")
            _, roster_rows = self._attendance_roster_in_tx(cur, course_run_id, session_unit_id, lock_enrollments=True)
            roster_ids = {row["run_enrollment_id"] for row in roster_rows}
            submitted_ids = [item.get("run_enrollment_id") for item in records]
            if len(submitted_ids) != len(set(submitted_ids)) or set(submitted_ids) != roster_ids:
                raise CommandError("invalid_state", "attendance save must include each applicable learner exactly once")
            before_by_enrollment = {row["run_enrollment_id"]: row for row in roster_rows}
            changes = []
            created_count = 0
            updated_count = 0
            for item in records:
                status = item.get("effective_status")
                if status not in {"Present", "Absent"}:
                    raise CommandError("invalid_input", "attendance status must be Present or Absent")
                before = before_by_enrollment[item["run_enrollment_id"]]
                cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,details)
                               VALUES(%s,%s,%s,%s,%s)
                               ON CONFLICT(run_enrollment_id,session_unit_id) DO UPDATE SET effective_status=EXCLUDED.effective_status,updated_at=NOW()
                               RETURNING attendance_id""",
                            (item["run_enrollment_id"], session_unit_id, status, item.get("original_status", status),
                             psycopg2.extras.Json(_json_safe(item.get("details", {})))))
                attendance_id = cur.fetchone()[0]
                if before["recorded_status"] != status:
                    changes.append({
                        "attendance_id": attendance_id,
                        "run_enrollment_id": item["run_enrollment_id"],
                        "emp_code": before["emp_code"],
                        "before": {"effective_status": before["recorded_status"]},
                        "after": {"effective_status": status},
                        "note": item.get("details", {}).get("note") if isinstance(item.get("details"), dict) else None,
                    })
                    if before["attendance_id"] is None:
                        created_count += 1
                    else:
                        updated_count += 1
            if unit[1] == "planned":
                cur.execute("UPDATE meetings SET status='completed' WHERE meeting_id=%s", (unit[2],))
            self._audit(cur, "attendance.roster.save", "session_unit", session_unit_id,
                        {"course_run_id": course_run_id, "roster_count": len(records),
                         "meeting_status_before": unit[1], "meeting_status_after": "completed",
                         "created_count": created_count, "updated_count": updated_count,
                         "unchanged_count": len(records) - len(changes), "changes": changes})
            return CommandResult("attendance", None, {
                "count": len(records), "session_unit_id": session_unit_id,
                "created_count": created_count, "updated_count": updated_count,
                "unchanged_count": len(records) - len(changes),
            })
        return self._run({"admin", "editor"}, op)

    @staticmethod
    def _attendance_roster_in_tx(cur, course_run_id: int, session_unit_id: int, *, lock_enrollments: bool = False):
        cur.execute("""SELECT su.sequence_in_run,m.status,m.meeting_id,m.starts_at,su.unit_type
                       FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                       WHERE su.session_unit_id=%s AND su.course_run_id=%s""", (session_unit_id, course_run_id))
        unit = cur.fetchone()
        if not unit:
            raise CommandError("not_found", "session unit does not belong to the selected course run")
        if unit[1] == "cancelled":
            raise CommandError("invalid_state", "cancelled sessions do not have an attendance roster")
        if unit[4] == "makeup":
            raise CommandError("invalid_state", "make-up sessions use the linked absence workflow")
        lock_clause = " FOR UPDATE OF re" if lock_enrollments else ""
        cur.execute("""SELECT re.run_enrollment_id,e.emp_code,e.full_name,re.start_session_number,
                              CASE WHEN a.attendance_id IS NOT NULL THEN a.effective_status
                                   WHEN %s='planned' THEN 'Present' END AS effective_status,
                              a.attendance_id
                       FROM run_enrollments re
                       JOIN employees e ON e.employee_id=re.employee_id
                       LEFT JOIN cohort_memberships cm ON cm.cohort_membership_id=re.cohort_membership_id
                       LEFT JOIN attendance a
                         ON a.run_enrollment_id=re.run_enrollment_id AND a.session_unit_id=%s
                       WHERE re.course_run_id=%s
                         AND re.start_session_number<=%s
                         AND (
                           a.attendance_id IS NOT NULL
                           OR (%s='planned' AND re.status='active')
                           OR (%s='completed'
                               AND cm.start_date<=%s::date
                               AND (cm.end_date IS NULL OR %s::date<=cm.end_date))
                         )
                       ORDER BY e.full_name,e.emp_code""" + lock_clause,
                    (unit[1], session_unit_id, course_run_id, unit[0], unit[1], unit[1], unit[3], unit[3]))
        columns = ["run_enrollment_id", "emp_code", "full_name", "start_session_number", "effective_status", "attendance_id"]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        for row in rows:
            row["recorded_status"] = row["effective_status"] if row["attendance_id"] is not None else None
        return unit, rows

    def bulk_record_attendance(self, records: Iterable[dict[str, Any]]) -> CommandResult:
        records=list(records)
        def op(cur):
            if not records: raise CommandError("invalid_input","at least one attendance record is required")
            ids=[]
            for item in records:
                status=item.get("effective_status")
                if status not in {"Present","Absent"}: raise CommandError("invalid_input","attendance status must be Present or Absent")
                cur.execute("SELECT unit_type FROM session_units WHERE session_unit_id=%s", (item["session_unit_id"],))
                unit = cur.fetchone()
                if not unit:
                    raise CommandError("not_found", "attendance session not found")
                if unit[0] == "makeup":
                    raise CommandError("invalid_state", "make-up sessions use the linked absence workflow")
                cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,details)
                             VALUES(%s,%s,%s,%s,%s)
                             ON CONFLICT(run_enrollment_id,session_unit_id) DO UPDATE SET effective_status=EXCLUDED.effective_status,
                               updated_at=NOW() RETURNING attendance_id""",(item["run_enrollment_id"],item["session_unit_id"],status,item.get("original_status",status),psycopg2.extras.Json(_json_safe(item.get("details",{})))))
                ids.append(cur.fetchone()[0])
            self._audit(cur,"attendance.bulk_record","attendance",None,{"count":len(ids),"attendance_ids":ids}); return CommandResult("attendance",None,{"count":len(ids),"attendance_ids":ids})
        return self._run({"admin","editor"},op)

    def correct_attendance_makeup(self, attendance_id: int, makeup_session_unit_id: int, reason: str) -> CommandResult:
        def op(cur):
            reason_value = _required(reason, "reason").strip()
            self._advisory_lock(cur, f"attendance_makeup:{attendance_id}")
            cur.execute("""SELECT a.run_enrollment_id,a.effective_status,a.is_makeup,
                                  re.course_run_id,re.start_session_number,
                                  su.sequence_in_run,m.status,m.starts_at
                           FROM attendance a
                           JOIN run_enrollments re ON re.run_enrollment_id=a.run_enrollment_id
                           JOIN session_units su ON su.session_unit_id=a.session_unit_id
                           JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE a.attendance_id=%s FOR UPDATE OF a""", (attendance_id,))
            original = cur.fetchone()
            if not original:
                raise CommandError("not_found", "attendance not found")
            if original[2] or original[1] != "Absent":
                raise CommandError("invalid_state", "make-up credit requires an original absence")
            if original[6] != "completed":
                raise CommandError("invalid_state", "the original session must be completed")
            cur.execute("""SELECT su.course_run_id,su.unit_type,su.sequence_in_run,
                                  m.meeting_id,m.status,m.starts_at
                           FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.session_unit_id=%s FOR UPDATE OF su,m""", (makeup_session_unit_id,))
            target = cur.fetchone()
            if not target:
                raise CommandError("not_found", "make-up session not found")
            if target[0] != original[3]:
                raise CommandError("invalid_input", "make-up session must belong to the same course run")
            if target[1] != "makeup":
                raise CommandError("invalid_input", "select a session configured for make-up attendance")
            if target[2] < original[4]:
                raise CommandError("invalid_input", "make-up session is before the enrollment start")
            if target[4] == "cancelled":
                raise CommandError("invalid_state", "cancelled sessions cannot provide make-up credit")
            if target[5] <= original[7]:
                raise CommandError("invalid_input", "make-up session must occur after the original absence")
            cur.execute("SELECT 1 FROM attendance WHERE makeup_for_attendance_id=%s", (attendance_id,))
            if cur.fetchone():
                raise CommandError("duplicate_makeup", "this absence already has make-up credit")
            cur.execute("""SELECT 1 FROM attendance
                           WHERE run_enrollment_id=%s AND session_unit_id=%s""",
                        (original[0], makeup_session_unit_id))
            if cur.fetchone():
                raise CommandError("invalid_state", "attendance already exists for this learner and make-up session")
            cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,is_makeup,makeup_for_attendance_id,details)
                         VALUES(%s,%s,'Present','Absent',TRUE,%s,%s) RETURNING attendance_id""",
                        (original[0], makeup_session_unit_id, attendance_id,
                         psycopg2.extras.Json({"correction_reason": reason_value})))
            new_id = cur.fetchone()[0]
            if target[4] == "planned":
                cur.execute("UPDATE meetings SET status='completed' WHERE meeting_id=%s", (target[3],))
            self._audit(cur, "attendance.makeup", "attendance", new_id, {
                "makeup_for": attendance_id,
                "makeup_session_unit_id": makeup_session_unit_id,
                "reason": reason_value,
                "before": {"original_status": "Absent", "credited_status": "Absent"},
                "after": {"original_status": "Absent", "credited_status": "Present"},
                "denominator_units_added": 0,
            })
            return CommandResult("attendance", new_id, {
                "makeup_for": attendance_id,
                "credited_status": "Present",
                "denominator_units_added": 0,
            })
        return self._run({"admin","editor"},op)
