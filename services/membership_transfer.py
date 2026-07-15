"""Cohort membership lifecycle and learner/enrollment transfer commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class MembershipTransferCommands:
    def add_membership(self, cohort_id: int, employee_id: int, start_date: date) -> CommandResult:
        def op(cur):
            cur.execute("INSERT INTO cohort_memberships(cohort_id,employee_id,start_date) VALUES(%s,%s,%s) RETURNING cohort_membership_id", (cohort_id,employee_id,start_date))
            entity_id=cur.fetchone()[0]; self._audit(cur,"membership.add","cohort_membership",entity_id)
            return CommandResult("cohort_membership",entity_id,{})
        return self._run({"admin", "editor"}, op)

    def close_membership(self, membership_id: int, end_date: date, status="completed") -> CommandResult:
        def op(cur):
            if status not in {"completed", "cancelled"}: raise CommandError("invalid_input", "membership close status is invalid")
            cur.execute("UPDATE cohort_memberships SET end_date=%s,status=%s WHERE cohort_membership_id=%s AND status='active' RETURNING cohort_membership_id", (end_date,status,membership_id))
            if not cur.fetchone(): raise CommandError("invalid_state", "membership is not active or does not exist")
            self._audit(cur,"membership.close","cohort_membership",membership_id); return CommandResult("cohort_membership",membership_id,{"status":status})
        return self._run({"admin", "editor"}, op)

    def transfer_membership(self, membership_id: int, target_cohort_id: int, transfer_date: date) -> CommandResult:
        def op(cur):
            cur.execute("SELECT employee_id,start_date FROM cohort_memberships WHERE cohort_membership_id=%s AND status='active' FOR UPDATE", (membership_id,)); old=cur.fetchone()
            if not old: raise CommandError("invalid_state", "membership is not active or does not exist")
            cur.execute("UPDATE cohort_memberships SET end_date=%s,status='transferred' WHERE cohort_membership_id=%s", (transfer_date,membership_id))
            cur.execute("INSERT INTO cohort_memberships(cohort_id,employee_id,start_date,status) VALUES(%s,%s,%s,'active') RETURNING cohort_membership_id", (target_cohort_id,old[0],transfer_date)); new_id=cur.fetchone()[0]
            cur.execute("UPDATE cohort_memberships SET transfer_to_membership_id=%s WHERE cohort_membership_id=%s", (new_id,membership_id))
            self._audit(cur,"membership.transfer","cohort_membership",new_id,{"from_membership_id":membership_id}); return CommandResult("cohort_membership",new_id,{"from_membership_id":membership_id})
        return self._run({"admin", "editor"}, op)

    def propose_transfer_start_session(self, target_course_run_id: int) -> CommandResult:
        def op(cur):
            cur.execute("SELECT status FROM course_runs WHERE course_run_id=%s", (target_course_run_id,))
            target = cur.fetchone()
            if not target: raise CommandError("not_found", "target course run not found")
            if target[0] not in {"planned", "active"}:
                raise CommandError("invalid_state", "transfer target must be a planned or active course run")
            return CommandResult("course_run", target_course_run_id, {
                "start_session_number": self._propose_course_run_start_session_in_tx(cur, target_course_run_id)
            })
        return self._run({"admin", "editor"}, op)

    def transfer_learner(
        self,
        run_enrollment_id: int,
        target_course_run_id: int,
        transfer_date: date,
        *,
        confirmed_start_session_number: int,
        capacity_override_reason: str | None = None,
    ) -> CommandResult:
        """Close source membership/enrollment and create target records atomically."""
        def op(cur):
            cur.execute("""SELECT cr.cohort_id,c.capacity,cr.status
                           FROM course_runs cr
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           WHERE cr.course_run_id=%s FOR UPDATE""", (target_course_run_id,))
            target = cur.fetchone()
            if not target: raise CommandError("not_found", "target course run not found")
            target_cohort_id, capacity, target_status = target
            if target_status not in {"planned", "active"}:
                raise CommandError("invalid_state", "transfer target must be a planned or active course run")
            proposal = self._propose_transfer_start_session_in_tx(cur, target_course_run_id)
            if confirmed_start_session_number != proposal:
                raise CommandError("stale_proposal", "first applicable session changed; reload the destination before saving")
            cur.execute("""SELECT re.employee_id,re.cohort_membership_id,cr.cohort_id,re.course_run_id,
                                  cm.status,cm.cohort_id
                           FROM run_enrollments re
                           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           JOIN cohort_memberships cm ON cm.cohort_membership_id=re.cohort_membership_id
                           WHERE re.run_enrollment_id=%s AND re.status='active'
                           FOR UPDATE OF re,cm""", (run_enrollment_id,))
            source = cur.fetchone()
            if not source: raise CommandError("invalid_state", "enrollment is not active or does not exist")
            employee_id, source_membership_id, source_cohort_id, source_course_run_id, membership_status, membership_cohort_id = source
            if not source_membership_id or membership_status != "active" or membership_cohort_id != source_cohort_id:
                raise CommandError("invalid_state", "active enrollment must be linked to its active class membership")
            if target_course_run_id == source_course_run_id: raise CommandError("invalid_input", "target course run must differ from source")
            if target_cohort_id == source_cohort_id:
                raise CommandError("invalid_input", "move learner requires a different class; use continuation after course completion")
            cur.execute("SELECT business_unit_id,job_role_id FROM employee_org_history WHERE employee_id=%s AND is_current", (employee_id,))
            org = cur.fetchone()
            if not org or org[0] is None or org[1] is None: raise CommandError("invalid_state", "current employee BU and role are required for transfer")
            cur.execute("SELECT count(*) FROM cohort_memberships WHERE cohort_id=%s AND status='active'", (target_cohort_id,))
            target_active_count = cur.fetchone()[0]
            resulting_count = target_active_count + 1
            override_reason = _normalize_label(capacity_override_reason)
            needs_override = capacity is not None and resulting_count > capacity
            if needs_override and not override_reason:
                raise CommandError("capacity_exceeded", "target cohort is at capacity; an HR override reason is required")
            cur.execute("UPDATE run_enrollments SET status='transferred' WHERE run_enrollment_id=%s", (run_enrollment_id,))
            cur.execute("UPDATE cohort_memberships SET end_date=%s,status='transferred' WHERE cohort_membership_id=%s", (transfer_date, source_membership_id))
            cur.execute("""INSERT INTO cohort_memberships(cohort_id,employee_id,start_date,status)
                           VALUES(%s,%s,%s,'active') RETURNING cohort_membership_id""", (target_cohort_id, employee_id, transfer_date))
            target_membership_id = cur.fetchone()[0]
            cur.execute("UPDATE cohort_memberships SET transfer_to_membership_id=%s WHERE cohort_membership_id=%s", (target_membership_id, source_membership_id))
            cur.execute("""INSERT INTO run_enrollments(course_run_id,employee_id,cohort_membership_id,start_session_number,business_unit_id_snapshot,job_role_id_snapshot,transfer_from_enrollment_id)
                           VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING run_enrollment_id""",
                        (target_course_run_id, employee_id, target_membership_id, proposal, org[0], org[1], run_enrollment_id))
            new_enrollment_id = cur.fetchone()[0]
            override_id = None
            if needs_override:
                cur.execute("""INSERT INTO cohort_capacity_overrides(
                                   cohort_id,employee_id,course_run_id,previous_capacity,
                                   resulting_active_learner_count,reason,actor_user_id
                               ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                               RETURNING cohort_capacity_override_id""",
                            (target_cohort_id, employee_id, target_course_run_id, capacity,
                             resulting_count, override_reason, self.actor_user_id))
                override_id = cur.fetchone()[0]
                self._audit(cur, "cohort.capacity.override", "cohort_capacity_override", override_id, {
                    "employee_id": employee_id,
                    "cohort_id": target_cohort_id,
                    "previous_capacity": capacity,
                    "resulting_active_learner_count": resulting_count,
                    "reason": override_reason,
                })
            self._audit(cur, "learner.transfer", "run_enrollment", new_enrollment_id,
                        {"employee_id": employee_id, "from_enrollment_id": run_enrollment_id, "from_cohort_id": source_cohort_id,
                         "to_cohort_id": target_cohort_id, "start_session_number": proposal,
                         "capacity_override_id": override_id})
            return CommandResult("run_enrollment", new_enrollment_id, {
                "from_enrollment_id": run_enrollment_id,
                "membership_id": target_membership_id,
                "start_session_number": proposal,
                "capacity_override_id": override_id,
            })
        return self._run({"admin", "editor"}, op)

    def transfer_enrollment(self, run_enrollment_id: int, target_course_run_id: int, transfer_date: date, start_session_number: int = 1) -> CommandResult:
        def op(cur):
            if start_session_number < 1: raise CommandError("invalid_input","start_session_number must be positive")
            cur.execute("""SELECT re.employee_id,re.cohort_membership_id,re.business_unit_id_snapshot,re.job_role_id_snapshot,cr.cohort_id
                           FROM run_enrollments re JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           WHERE re.run_enrollment_id=%s AND re.status='active' FOR UPDATE""",(run_enrollment_id,)); old=cur.fetchone()
            if not old: raise CommandError("invalid_state","enrollment is not active or does not exist")
            if not old[1]: raise CommandError("invalid_state","active enrollment must be linked to its cohort membership before transfer")
            if old[2] is None or old[3] is None: raise CommandError("invalid_state","enrollment organization snapshots are required before transfer")
            cur.execute("SELECT cohort_id FROM course_runs WHERE course_run_id=%s", (target_course_run_id,))
            target = cur.fetchone()
            if not target: raise CommandError("not_found","target course run not found")
            if target[0] != old[4]:
                raise CommandError("invalid_input","use learner transfer for cross-cohort transfers")
            cur.execute("UPDATE run_enrollments SET status='transferred' WHERE run_enrollment_id=%s",(run_enrollment_id,))
            cur.execute("""INSERT INTO run_enrollments(course_run_id,employee_id,cohort_membership_id,start_session_number,business_unit_id_snapshot,job_role_id_snapshot,transfer_from_enrollment_id)
                         VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING run_enrollment_id""",(target_course_run_id,old[0],old[1],start_session_number,old[2],old[3],run_enrollment_id)); new_id=cur.fetchone()[0]
            self._audit(cur,"enrollment.transfer","run_enrollment",new_id,{"from_enrollment_id":run_enrollment_id,"transfer_date":str(transfer_date)}); return CommandResult("run_enrollment",new_id,{"from_enrollment_id":run_enrollment_id})
        return self._run({"admin","editor"},op)
