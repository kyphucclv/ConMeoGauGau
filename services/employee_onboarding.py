"""Employee identity and learner onboarding commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


_UNSET = object()


class EmployeeOnboardingCommands:
    def create_or_update_employee(self, emp_code: str, full_name: str, *, english_name=None, email=None,
                                  employment_status="unknown", business_unit_id=None, job_role_id=None,
                                  valid_from: date | None = None, expected_employee_id: int | None = None,
                                  expected_org_valid_from: date | None | object = _UNSET) -> CommandResult:
        def op(cur):
            _required(emp_code, "emp_code"); _required(full_name, "full_name")
            if employment_status not in {"active", "inactive", "unknown"}:
                raise CommandError("invalid_input", "employment_status is invalid")
            if expected_employee_id is not None:
                cur.execute(
                    "SELECT emp_code FROM employees WHERE employee_id=%s FOR UPDATE",
                    (expected_employee_id,),
                )
                current_employee = cur.fetchone()
                if not current_employee:
                    raise CommandError("not_found", "employee not found")
                if current_employee[0] != emp_code.strip():
                    raise CommandError("identity_conflict", "employee identity changed; reload before saving")
                cur.execute(
                    """UPDATE employees
                       SET full_name=%s,english_name=%s,email=%s,employment_status=%s
                       WHERE employee_id=%s RETURNING employee_id""",
                    (full_name.strip(), english_name, email, employment_status, expected_employee_id),
                )
            else:
                cur.execute("""INSERT INTO employees(emp_code,full_name,english_name,email,employment_status)
                             VALUES(%s,%s,%s,%s,%s)
                             ON CONFLICT(emp_code) DO UPDATE SET full_name=EXCLUDED.full_name,
                               english_name=EXCLUDED.english_name,email=EXCLUDED.email,
                               employment_status=EXCLUDED.employment_status RETURNING employee_id""",
                            (emp_code.strip(), full_name.strip(), english_name, email, employment_status))
            employee_id = cur.fetchone()[0]
            org_history_action = "not_requested"
            if business_unit_id is not None or job_role_id is not None:
                vf = valid_from or date.today()
                cur.execute(
                    """SELECT employee_org_history_id,business_unit_id,job_role_id,valid_from
                       FROM employee_org_history
                       WHERE employee_id=%s AND is_current
                       FOR UPDATE""",
                    (employee_id,),
                )
                current_org = cur.fetchone()
                if expected_org_valid_from is not _UNSET:
                    actual_org_valid_from = current_org[3] if current_org else None
                    if actual_org_valid_from != expected_org_valid_from:
                        raise CommandError("stale_profile", "organization profile changed; reload before saving")
                requested_org = (business_unit_id, job_role_id)
                if current_org and requested_org == (current_org[1], current_org[2]):
                    org_history_action = "unchanged"
                else:
                    if current_org and vf < current_org[3]:
                        raise CommandError(
                            "invalid_input",
                            "organization change date cannot precede the current assignment",
                        )
                    if current_org:
                        cur.execute(
                            """UPDATE employee_org_history
                               SET valid_to=%s,is_current=FALSE
                               WHERE employee_org_history_id=%s""",
                            (vf, current_org[0]),
                        )
                        org_history_action = "changed"
                    else:
                        org_history_action = "created"
                    cur.execute(
                        """INSERT INTO employee_org_history(
                               employee_id,business_unit_id,job_role_id,valid_from
                           ) VALUES(%s,%s,%s,%s)""",
                        (employee_id, business_unit_id, job_role_id, vf),
                    )
            details = {
                "emp_code": emp_code.strip(),
                "org_history_action": org_history_action,
            }
            self._audit(cur, "employee.upsert", "employee", employee_id, details)
            return CommandResult("employee", employee_id, details)
        return self._run({"admin", "editor"}, op)

    def enroll(self, course_run_id: int, employee_id: int, membership_id: int | None = None, start_session_number: int = 1) -> CommandResult:
        def op(cur):
            if start_session_number < 1: raise CommandError("invalid_input","start_session_number must be positive")
            if membership_id is None: raise CommandError("invalid_input","active cohort membership is required for enrollment")
            cur.execute("SELECT cohort_id FROM course_runs WHERE course_run_id=%s", (course_run_id,))
            run = cur.fetchone()
            if not run: raise CommandError("not_found","course run not found")
            cur.execute("SELECT employee_id,cohort_id,status FROM cohort_memberships WHERE cohort_membership_id=%s FOR UPDATE", (membership_id,))
            membership = cur.fetchone()
            if not membership: raise CommandError("not_found","cohort membership not found")
            if membership[0] != employee_id or membership[1] != run[0]:
                raise CommandError("invalid_input","cohort membership must belong to the employee and course run cohort")
            if membership[2] != "active":
                raise CommandError("invalid_state","cohort membership must be active")
            cur.execute("SELECT business_unit_id,job_role_id FROM employee_org_history WHERE employee_id=%s AND is_current", (employee_id,))
            org = cur.fetchone()
            if not org or org[0] is None or org[1] is None:
                raise CommandError("invalid_state","current employee BU and role are required for enrollment")
            cur.execute("""INSERT INTO run_enrollments(
                            course_run_id,employee_id,cohort_membership_id,start_session_number,
                            business_unit_id_snapshot,job_role_id_snapshot
                         )
                         VALUES(%s,%s,%s,%s,%s,%s)
                         RETURNING run_enrollment_id""",(course_run_id,employee_id,membership_id,start_session_number,org[0],org[1]))
            entity_id=cur.fetchone()[0]; self._audit(cur,"enrollment.create","run_enrollment",entity_id); return CommandResult("run_enrollment",entity_id,{})
        return self._run({"admin","editor"},op)

    def onboard_learner(
        self,
        *,
        emp_code: str,
        full_name: str,
        business_unit_id: int,
        job_role_id: int,
        entrance_level_id: int,
        course_run_id: int,
        joined_on: date,
        employment_status: str = "active",
        start_session_number: int = 1,
        capacity_override_reason: str | None = None,
        expected_start_session_number: int | None = None,
        expected_employee_id: int | None | object = _UNSET,
    ) -> CommandResult:
        """Atomically start first-time, returning, continuing, or rejoining learning."""
        def op(cur):
            _required(emp_code, "emp_code"); _required(full_name, "full_name")
            if employment_status not in {"active", "inactive", "unknown"}:
                raise CommandError("invalid_input", "employment_status is invalid")
            if start_session_number < 1:
                raise CommandError("invalid_input", "start_session_number must be positive")
            cur.execute("""SELECT cr.cohort_id, c.capacity, cr.status FROM course_runs cr
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           WHERE cr.course_run_id=%s FOR UPDATE""", (course_run_id,))
            target = cur.fetchone()
            if not target:
                raise CommandError("not_found", "course run not found")
            cohort_id, capacity, run_status = target
            if run_status not in {"planned", "active"}:
                raise CommandError("invalid_state", "learning can start only in a planned or active course run")
            proposed_start_session = self._propose_course_run_start_session_in_tx(cur, course_run_id)
            if expected_start_session_number is not None and expected_start_session_number != proposed_start_session:
                raise CommandError(
                    "stale_proposal",
                    "first applicable session changed; reload the destination before saving",
                )
            if start_session_number < proposed_start_session:
                raise CommandError(
                    "invalid_input",
                    f"first applicable session must be {proposed_start_session} or later for this run",
                )
            # Lock the employee row when it exists, so concurrent onboarding does
            # not create competing organization histories or active enrollments.
            cur.execute(
                """SELECT employee_id,full_name,employment_status
                   FROM employees WHERE emp_code=%s FOR UPDATE""",
                (emp_code.strip(),),
            )
            row = cur.fetchone()
            if expected_employee_id is not _UNSET:
                actual_employee_id = row[0] if row else None
                if actual_employee_id != expected_employee_id:
                    raise CommandError(
                        "identity_conflict",
                        "employee identity changed; select the canonical learner before saving",
                    )
            employee_created = row is None
            if row:
                employee_id = row[0]
                employee_action = "unchanged"
                if (row[1], row[2]) != (full_name.strip(), employment_status):
                    cur.execute(
                        "UPDATE employees SET full_name=%s, employment_status=%s WHERE employee_id=%s",
                        (full_name.strip(), employment_status, employee_id),
                    )
                    employee_action = "updated"
            else:
                cur.execute("""INSERT INTO employees(emp_code,full_name,employment_status)
                               VALUES(%s,%s,%s) RETURNING employee_id""",
                            (emp_code.strip(), full_name.strip(), employment_status))
                employee_id = cur.fetchone()[0]
                employee_action = "created"
            cur.execute("SELECT business_unit_id,job_role_id FROM employee_org_history WHERE employee_id=%s AND is_current FOR UPDATE", (employee_id,))
            current_org = cur.fetchone()
            if current_org != (business_unit_id, job_role_id):
                if current_org:
                    cur.execute("UPDATE employee_org_history SET valid_to=%s,is_current=FALSE WHERE employee_id=%s AND is_current", (joined_on, employee_id))
                cur.execute("""INSERT INTO employee_org_history(employee_id,business_unit_id,job_role_id,valid_from)
                               VALUES(%s,%s,%s,%s)""", (employee_id, business_unit_id, job_role_id, joined_on))

            cur.execute("SELECT 1 FROM run_enrollments WHERE employee_id=%s AND status='active' FOR UPDATE", (employee_id,))
            if cur.fetchone():
                raise CommandError("active_enrollment_conflict", "employee already has an active course enrollment")

            cur.execute("""SELECT placement_id,level_id FROM placements
                           WHERE employee_id=%s AND placement_kind='business' FOR UPDATE""", (employee_id,))
            placement = cur.fetchone()
            if placement and placement[1] != entrance_level_id:
                raise CommandError(
                    "placement_conflict",
                    "employee already has a different entrance placement; use the placement correction workflow",
                )
            if placement:
                placement_id = placement[0]
                placement_action = "reused"
            else:
                cur.execute("""INSERT INTO placements(employee_id,placement_kind,test_date,level_id)
                               VALUES(%s,'business',%s,%s) RETURNING placement_id""",
                            (employee_id, joined_on, entrance_level_id))
                placement_id = cur.fetchone()[0]
                placement_action = "created"

            cur.execute("""SELECT cohort_membership_id,cohort_id FROM cohort_memberships
                           WHERE employee_id=%s AND status='active' FOR UPDATE""", (employee_id,))
            active_membership = cur.fetchone()
            cur.execute("SELECT EXISTS(SELECT 1 FROM cohort_memberships WHERE employee_id=%s)", (employee_id,))
            had_membership = cur.fetchone()[0]
            if active_membership and active_membership[1] != cohort_id:
                raise CommandError(
                    "active_membership_conflict",
                    "employee belongs to another active class; use the transfer workflow",
                )
            if active_membership:
                membership_id = active_membership[0]
                membership_action = "reused"
                lifecycle = "continuation"
            else:
                cur.execute("""INSERT INTO cohort_memberships(cohort_id,employee_id,start_date)
                               VALUES(%s,%s,%s) RETURNING cohort_membership_id""", (cohort_id, employee_id, joined_on))
                membership_id = cur.fetchone()[0]
                membership_action = "created"
                if had_membership:
                    lifecycle = "rejoin"
                elif placement_action == "reused" and not employee_created:
                    lifecycle = "returning"
                else:
                    lifecycle = "first_time"

            cur.execute("SELECT count(*) FROM cohort_memberships WHERE cohort_id=%s AND status='active'", (cohort_id,))
            resulting_count = cur.fetchone()[0]
            increases_membership = membership_action == "created"
            if increases_membership and capacity is not None and resulting_count > capacity and not _normalize_label(capacity_override_reason):
                raise CommandError("capacity_exceeded", "cohort is at capacity; an HR override reason is required")
            cur.execute("""INSERT INTO run_enrollments(
                               course_run_id,employee_id,cohort_membership_id,start_session_number,
                               business_unit_id_snapshot,job_role_id_snapshot
                           ) VALUES(%s,%s,%s,%s,%s,%s) RETURNING run_enrollment_id""",
                        (course_run_id, employee_id, membership_id, start_session_number, business_unit_id, job_role_id))
            enrollment_id = cur.fetchone()[0]
            if increases_membership and capacity is not None and resulting_count > capacity:
                reason = _normalize_label(capacity_override_reason)
                cur.execute("""INSERT INTO cohort_capacity_overrides(
                               cohort_id,employee_id,course_run_id,previous_capacity,resulting_active_learner_count,reason,actor_user_id
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING cohort_capacity_override_id""",
                            (cohort_id, employee_id, course_run_id, capacity, resulting_count, reason, self.actor_user_id))
                override_id = cur.fetchone()[0]
                self._audit(cur, "cohort.capacity.override", "cohort_capacity_override", override_id,
                            {"cohort_id": cohort_id, "previous_capacity": capacity, "resulting_active_learner_count": resulting_count, "reason": reason})
            self._audit(cur, "learner.onboard", "run_enrollment", enrollment_id,
                        {"employee_id": employee_id, "placement_id": placement_id, "membership_id": membership_id,
                         "lifecycle": lifecycle, "placement_action": placement_action,
                         "membership_action": membership_action, "employee_action": employee_action})
            return CommandResult("run_enrollment", enrollment_id, {
                "employee_id": employee_id,
                "placement_id": placement_id,
                "membership_id": membership_id,
                "lifecycle": lifecycle,
                "placement_action": placement_action,
                "membership_action": membership_action,
                "employee_action": employee_action,
            })
        return self._run({"admin", "editor"}, op)

    def propose_onboarding_start_session(self, target_course_run_id: int) -> CommandResult:
        def op(cur):
            cur.execute("SELECT status FROM course_runs WHERE course_run_id=%s", (target_course_run_id,))
            target = cur.fetchone()
            if not target: raise CommandError("not_found", "target course run not found")
            if target[0] not in {"planned", "active"}:
                raise CommandError("invalid_state", "learning can start only in a planned or active course run")
            return CommandResult("course_run", target_course_run_id, {
                "start_session_number": self._propose_course_run_start_session_in_tx(cur, target_course_run_id)
            })
        return self._run({"admin", "editor"}, op)
