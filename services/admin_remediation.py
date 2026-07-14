"""Quality-issue resolution and owner-approved legacy remediation commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class AdminRemediationCommands:
    def resolve_quality_issue(self, issue_id: int, status: str, note: str) -> CommandResult:
        def op(cur):
            if status not in {"resolved", "ignored"}:
                raise CommandError("invalid_input", "quality issue status is invalid")
            _required(note, "note")
            cur.execute("""UPDATE data_quality_issues
                         SET status=%s,resolved_at=NOW(),resolved_by_user_id=%s,resolution_note=%s
                         WHERE issue_id=%s AND status='open'
                         RETURNING issue_id""", (status, self.actor_user_id, note, issue_id))
            row = cur.fetchone()
            if not row:
                raise CommandError("invalid_state", "quality issue is not open or does not exist")
            self._audit(cur, "quality_issue.resolve", "data_quality_issue", issue_id, {"status": status, "note": note})
            return CommandResult("data_quality_issue", issue_id, {"status": status})
        return self._run({"admin", "editor"}, op)

    def backfill_unknown_org_profiles(self) -> CommandResult:
        """Apply the owner-approved legacy BU/role placeholder without overwriting known values."""
        def op(cur):
            cur.execute("SELECT business_unit_id FROM business_units WHERE business_unit_name='Unknown BU'")
            unknown_bu = cur.fetchone()
            cur.execute("SELECT job_role_id FROM job_roles WHERE job_role_name='Unknown Role'")
            unknown_role = cur.fetchone()
            if not unknown_bu or not unknown_role:
                raise CommandError("invalid_state", "Unknown BU and Unknown Role references are not installed")
            unknown_bu_id, unknown_role_id = unknown_bu[0], unknown_role[0]
            cur.execute("""SELECT e.employee_id,eoh.employee_org_history_id,eoh.business_unit_id,eoh.job_role_id
                           FROM employees e LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
                           WHERE eoh.employee_org_history_id IS NULL OR eoh.business_unit_id IS NULL OR eoh.job_role_id IS NULL
                           FOR UPDATE OF e""")
            rows = cur.fetchall()
            for employee_id, history_id, bu_id, role_id in rows:
                if history_id is None:
                    cur.execute("""INSERT INTO employee_org_history(employee_id,business_unit_id,job_role_id,valid_from,observed_from)
                                   VALUES(%s,%s,%s,DATE '1900-01-01','phase11_unknown_placeholder')""",
                                (employee_id, unknown_bu_id, unknown_role_id))
                else:
                    cur.execute("""UPDATE employee_org_history SET business_unit_id=COALESCE(business_unit_id,%s),
                                   job_role_id=COALESCE(job_role_id,%s),observed_from=COALESCE(observed_from,'phase11_unknown_placeholder')
                                   WHERE employee_org_history_id=%s""", (unknown_bu_id, unknown_role_id, history_id))
            self._audit(cur, "employee_org.unknown_backfill", "employee_org_history", None,
                        {"employee_count": len(rows), "placeholder_business_unit": "Unknown BU", "placeholder_job_role": "Unknown Role"})
            return CommandResult("employee_org_history", None, {"employee_count": len(rows)})
        return self._run({"admin"}, op)

    def approve_legacy_attendance_exception(self, session_unit_id: int, reason: str) -> CommandResult:
        """Approve unavailable historical roster data without inventing attendance facts."""
        def op(cur):
            approved_reason = _required(reason, "reason")
            cur.execute("""SELECT su.session_unit_id
                           FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.session_unit_id=%s AND m.status='completed' FOR UPDATE OF su""", (session_unit_id,))
            if not cur.fetchone():
                raise CommandError("invalid_state", "only a delivered session can receive a legacy attendance exception")
            cur.execute("""SELECT EXISTS(
                             SELECT 1 FROM run_enrollments re
                             LEFT JOIN attendance a ON a.session_unit_id=%s AND a.run_enrollment_id=re.run_enrollment_id
                             WHERE re.course_run_id=(SELECT course_run_id FROM session_units WHERE session_unit_id=%s)
                               AND re.status='active'
                               AND re.start_session_number<=(SELECT sequence_in_run FROM session_units WHERE session_unit_id=%s)
                               AND a.attendance_id IS NULL
                         )""", (session_unit_id, session_unit_id, session_unit_id))
            if not cur.fetchone()[0]:
                raise CommandError("invalid_state", "this session has no missing applicable attendance results")
            cur.execute("""INSERT INTO attendance_roster_legacy_exceptions(session_unit_id,reason,approved_by_user_id)
                           VALUES(%s,%s,%s) RETURNING session_unit_id""",
                        (session_unit_id, approved_reason, self.actor_user_id))
            if not cur.fetchone():
                raise CommandError("invalid_state", "legacy attendance exception already exists for this session")
            self._audit(cur, "attendance.legacy_exception.approve", "session_unit", session_unit_id,
                        {"reason": approved_reason, "attendance_facts_created": 0})
            return CommandResult("attendance_roster_legacy_exception", session_unit_id, {"session_unit_id": session_unit_id})
        return self._run({"admin"}, op)

    def approve_all_legacy_attendance_exceptions(self, reason: str) -> CommandResult:
        """Approve every currently actionable historical roster exception with separate audit rows."""
        def op(cur):
            approved_reason = _required(reason, "reason")
            cur.execute("""SELECT su.session_unit_id
                           FROM session_units su
                           JOIN meetings m ON m.meeting_id=su.meeting_id AND m.status='completed'
                           LEFT JOIN attendance_roster_legacy_exceptions arex ON arex.session_unit_id=su.session_unit_id
                           WHERE arex.session_unit_id IS NULL
                             AND EXISTS (
                                 SELECT 1 FROM run_enrollments re
                                 LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id AND a.run_enrollment_id=re.run_enrollment_id
                                 WHERE re.course_run_id=su.course_run_id AND re.status='active'
                                   AND re.start_session_number<=su.sequence_in_run AND a.attendance_id IS NULL
                             )
                           FOR UPDATE OF su""")
            session_unit_ids = [row[0] for row in cur.fetchall()]
            if not session_unit_ids:
                raise CommandError("invalid_state", "there are no remaining legacy attendance exceptions to approve")
            for session_unit_id in session_unit_ids:
                cur.execute("""INSERT INTO attendance_roster_legacy_exceptions(session_unit_id,reason,approved_by_user_id)
                               VALUES(%s,%s,%s)""", (session_unit_id, approved_reason, self.actor_user_id))
                self._audit(cur, "attendance.legacy_exception.approve", "session_unit", session_unit_id,
                            {"reason": approved_reason, "attendance_facts_created": 0, "bulk_approval": True})
            return CommandResult("attendance_roster_legacy_exception", None, {"session_count": len(session_unit_ids)})
        return self._run({"admin"}, op)

    def backfill_unknown_business_placements(self) -> CommandResult:
        """Apply the approved legacy placement placeholder without replacing an observed placement."""
        def op(cur):
            cur.execute("SELECT level_id FROM levels WHERE level_name='Unknown Entrance Level'")
            unknown_level = cur.fetchone()
            if not unknown_level:
                raise CommandError("invalid_state", "Unknown Entrance Level reference is not installed")
            cur.execute("""SELECT e.employee_id FROM employees e
                           LEFT JOIN placements p ON p.employee_id=e.employee_id AND p.placement_kind='business'
                           WHERE p.placement_id IS NULL FOR UPDATE OF e""")
            employee_ids = [row[0] for row in cur.fetchall()]
            for employee_id in employee_ids:
                cur.execute("""INSERT INTO placements(employee_id,placement_kind,level_id,source_reference)
                               VALUES(%s,'business',%s,%s)""",
                            (employee_id, unknown_level[0], psycopg2.extras.Json({"source": "phase11_unknown_placement_placeholder"})))
            self._audit(cur, "placement.unknown_backfill", "placement", None,
                        {"employee_count": len(employee_ids), "placeholder_level": "Unknown Entrance Level"})
            return CommandResult("placement", None, {"employee_count": len(employee_ids)})
        return self._run({"admin"}, op)
