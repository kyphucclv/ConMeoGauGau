"""Transactional Phase 4 business commands.

This module deliberately has no Streamlit dependency.  A command owns one
transaction, validates business state before writing, and records its audit
event before commit.  The UI can translate ``CommandResult`` and
``CommandError`` into user-facing messages without inspecting SQL exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

import psycopg2
import psycopg2.extras


@dataclass(frozen=True)
class CommandResult:
    entity_type: str
    entity_id: int | None
    values: dict[str, Any]


class CommandError(Exception):
    """Stable, safe-to-display command failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _required(value: Any, name: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise CommandError("invalid_input", f"{name} is required")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _normalize_label(value: str | None) -> str | None:
    """Collapse accidental PIC whitespace while retaining the chosen casing."""
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


class BusinessService:
    """Application service over an existing psycopg2 connection."""

    def __init__(self, connection, actor_user_id: int):
        self.connection = connection
        self.actor_user_id = _required(actor_user_id, "actor_user_id")

    def _actor(self, cur, roles: set[str]) -> tuple[int, str]:
        cur.execute("SELECT user_id, role FROM app_users WHERE user_id=%s AND is_active", (self.actor_user_id,))
        row = cur.fetchone()
        if not row:
            raise CommandError("unauthorized", "active application user is required")
        if row[1] not in roles:
            raise CommandError("forbidden", "user is not authorized for this operation")
        return row

    def _audit(self, cur, action: str, entity_type: str, entity_id: int | None, details: dict[str, Any] | None = None):
        cur.execute("""INSERT INTO audit_events(actor_user_id, actor_username, action, entity_type, entity_key, details)
                     SELECT user_id, username, %s, %s, %s, %s FROM app_users WHERE user_id=%s""",
                    (action, entity_type, str(entity_id) if entity_id is not None else None,
                     psycopg2.extras.Json(_json_safe(details or {})), self.actor_user_id))

    @staticmethod
    def _advisory_lock(cur, key: str) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))

    @staticmethod
    def _next_evaluation_version(cur, evaluation_id: int) -> int:
        BusinessService._advisory_lock(cur, f"evaluation_version:{evaluation_id}")
        cur.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM evaluation_versions WHERE evaluation_id=%s",
            (evaluation_id,),
        )
        return cur.fetchone()[0]

    def _run(self, roles: set[str], fn):
        with self.connection:
            with self.connection.cursor() as cur:
                self._actor(cur, roles)
                try:
                    return fn(cur)
                except psycopg2.errors.UniqueViolation as exc:
                    if exc.diag.constraint_name == "uq_run_enrollments_one_active_per_employee":
                        raise CommandError("active_enrollment_conflict", "employee already has an active course enrollment") from exc
                    raise CommandError("duplicate", "the requested business record already exists") from exc
                except psycopg2.errors.ForeignKeyViolation as exc:
                    raise CommandError("not_found", "a referenced business record does not exist") from exc
                except psycopg2.errors.CheckViolation as exc:
                    raise CommandError("invalid_state", "the requested state is not valid") from exc
                except psycopg2.errors.RaiseException as exc:
                    raise CommandError("invalid_state", "the requested state is not valid") from exc

    def create_or_update_employee(self, emp_code: str, full_name: str, *, english_name=None, email=None,
                                  employment_status="unknown", business_unit_id=None, job_role_id=None,
                                  valid_from: date | None = None) -> CommandResult:
        def op(cur):
            _required(emp_code, "emp_code"); _required(full_name, "full_name")
            if employment_status not in {"active", "inactive", "unknown"}:
                raise CommandError("invalid_input", "employment_status is invalid")
            cur.execute("""INSERT INTO employees(emp_code,full_name,english_name,email,employment_status)
                         VALUES(%s,%s,%s,%s,%s)
                         ON CONFLICT(emp_code) DO UPDATE SET full_name=EXCLUDED.full_name,
                           english_name=EXCLUDED.english_name,email=EXCLUDED.email,
                           employment_status=EXCLUDED.employment_status RETURNING employee_id""",
                        (emp_code.strip(), full_name.strip(), english_name, email, employment_status))
            employee_id = cur.fetchone()[0]
            if business_unit_id is not None or job_role_id is not None:
                vf = valid_from or date.today()
                cur.execute("UPDATE employee_org_history SET valid_to=%s,is_current=FALSE WHERE employee_id=%s AND is_current",
                            (vf, employee_id))
                cur.execute("""INSERT INTO employee_org_history(employee_id,business_unit_id,job_role_id,valid_from)
                             VALUES(%s,%s,%s,%s) RETURNING employee_org_history_id""",
                            (employee_id, business_unit_id, job_role_id, vf))
            self._audit(cur, "employee.upsert", "employee", employee_id)
            return CommandResult("employee", employee_id, {"emp_code": emp_code})
        return self._run({"admin", "editor"}, op)

    def create_cohort(self, class_code: str, display_name: str, *, status="planned", capacity: int | None = None) -> CommandResult:
        def op(cur):
            _required(class_code, "class_code"); _required(display_name, "display_name")
            if status not in {"planned", "active", "completed", "archived"}: raise CommandError("invalid_input", "invalid cohort status")
            if capacity is not None and capacity <= 0: raise CommandError("invalid_input", "capacity must be positive")
            cur.execute("INSERT INTO cohorts(class_code,display_name,status,capacity) VALUES(%s,%s,%s,%s) RETURNING cohort_id", (class_code, display_name, status, capacity))
            entity_id = cur.fetchone()[0]; self._audit(cur, "cohort.create", "cohort", entity_id)
            return CommandResult("cohort", entity_id, {})
        return self._run({"admin", "editor"}, op)

    def propose_next_class_code(self, *, prefix: str = "EL", width: int = 3) -> CommandResult:
        """Propose, but do not reserve, the next sequential stable class code."""
        def op(cur):
            prefix_value = _required(prefix, "prefix").strip().upper()
            if width < 1: raise CommandError("invalid_input", "width must be positive")
            self._advisory_lock(cur, f"class_code:{prefix_value}")
            cur.execute("""SELECT COALESCE(MAX((substring(class_code FROM %s))::integer), 0) + 1
                           FROM cohorts WHERE class_code ~ %s""",
                        (f"^{prefix_value}([0-9]+)$", f"^{prefix_value}[0-9]+$"))
            next_number = cur.fetchone()[0]
            return CommandResult("cohort", None, {"class_code": f"{prefix_value}{next_number:0{width}d}"})
        return self._run({"admin", "editor"}, op)

    def pic_label_suggestions(self, search: str = "") -> CommandResult:
        def op(cur):
            term = _normalize_label(search) or ""
            cur.execute("""SELECT DISTINCT ON (lower(pic_label)) pic_label
                           FROM cohort_pic_assignments
                           WHERE pic_label IS NOT NULL AND lower(pic_label) LIKE lower(%s)
                           ORDER BY lower(pic_label), cohort_pic_assignment_id DESC""", (f"%{term}%",))
            return CommandResult("pic_label", None, {"labels": [row[0] for row in cur.fetchall()]})
        return self._run({"admin", "editor", "viewer"}, op)

    def create_class_course_run(
        self,
        *,
        class_code: str,
        display_name: str,
        course_id: int,
        start_date: date,
        capacity: int,
        status: str = "active",
        pic_employee_id: int | None = None,
        pic_label: str | None = None,
    ) -> CommandResult:
        """Create a class, current PIC, and first course run in one transaction."""
        def op(cur):
            code = _required(class_code, "class_code").strip().upper()
            name = _required(display_name, "display_name").strip()
            if status not in {"planned", "active"}:
                raise CommandError("invalid_input", "initial class status must be planned or active")
            if capacity <= 0:
                raise CommandError("invalid_input", "capacity must be positive")
            normalized_label = _normalize_label(pic_label)
            if not pic_employee_id and not normalized_label:
                raise CommandError("invalid_input", "PIC employee or team label is required")
            cur.execute(
                "SELECT expected_units,attendance_threshold_ratio FROM courses WHERE course_id=%s AND is_active",
                (course_id,),
            )
            course = cur.fetchone()
            if not course:
                raise CommandError("not_found", "course not found")
            cur.execute(
                "INSERT INTO cohorts(class_code,display_name,status,capacity) VALUES(%s,%s,%s,%s) RETURNING cohort_id",
                (code, name, status, capacity),
            )
            cohort_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO cohort_pic_assignments(cohort_id,pic_employee_id,pic_label,start_date) VALUES(%s,%s,%s,%s) RETURNING cohort_pic_assignment_id",
                (cohort_id, pic_employee_id, normalized_label, start_date),
            )
            pic_assignment_id = cur.fetchone()[0]
            self._advisory_lock(cur, f"course_run:{cohort_id}:{course_id}")
            cur.execute("""INSERT INTO course_runs(
                               cohort_id,course_id,run_number,status,expected_units_snapshot,
                               attendance_threshold_ratio_snapshot,start_date
                           ) VALUES(%s,%s,1,%s,%s,%s,%s) RETURNING course_run_id""",
                        (cohort_id, course_id, status, course[0], course[1], start_date))
            course_run_id = cur.fetchone()[0]
            self._audit(cur, "cohort.create", "cohort", cohort_id, {"source": "class_course_run"})
            self._audit(cur, "cohort.pic.assign", "cohort_pic_assignment", pic_assignment_id, {"cohort_id": cohort_id})
            self._audit(cur, "course_run.create", "course_run", course_run_id, {"cohort_id": cohort_id, "run_number": 1})
            return CommandResult(
                "course_run",
                course_run_id,
                {"cohort_id": cohort_id, "pic_assignment_id": pic_assignment_id, "run_number": 1},
            )
        return self._run({"admin", "editor"}, op)

    def assign_pic(
        self,
        cohort_id: int,
        pic_employee_id: int | None,
        start_date: date,
        *,
        pic_label: str | None = None,
    ) -> CommandResult:
        def op(cur):
            normalized_label = _normalize_label(pic_label)
            if not pic_employee_id and not normalized_label:
                raise CommandError("invalid_input", "PIC employee or team label is required")
            cur.execute("SELECT 1 FROM cohorts WHERE cohort_id=%s", (cohort_id,))
            if not cur.fetchone(): raise CommandError("not_found", "cohort not found")
            cur.execute("UPDATE cohort_pic_assignments SET end_date=%s WHERE cohort_id=%s AND end_date IS NULL", (start_date, cohort_id))
            cur.execute(
                "INSERT INTO cohort_pic_assignments(cohort_id,pic_employee_id,pic_label,start_date) VALUES(%s,%s,%s,%s) RETURNING cohort_pic_assignment_id",
                (cohort_id, pic_employee_id, normalized_label, start_date),
            )
            entity_id=cur.fetchone()[0]; self._audit(cur,"cohort.pic.assign","cohort_pic_assignment",entity_id)
            return CommandResult(
                "cohort_pic_assignment",
                entity_id,
                {"assignment_type": "employee" if pic_employee_id else "label"},
            )
        return self._run({"admin", "editor"}, op)

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

    def create_course_run(self, cohort_id: int, course_id: int, *, start_date=None) -> CommandResult:
        def op(cur):
            # Advisory lock serializes run-number allocation for this business key;
            # MAX()+1 is safe only while this lock is held.
            self._advisory_lock(cur, f"course_run:{cohort_id}:{course_id}")
            cur.execute("SELECT COALESCE(MAX(run_number),0)+1 FROM course_runs WHERE cohort_id=%s AND course_id=%s", (cohort_id,course_id)); run_no=cur.fetchone()[0]
            cur.execute("SELECT expected_units,attendance_threshold_ratio FROM courses WHERE course_id=%s",(course_id,)); course=cur.fetchone()
            if not course: raise CommandError("not_found","course not found")
            cur.execute("""INSERT INTO course_runs(cohort_id,course_id,run_number,expected_units_snapshot,attendance_threshold_ratio_snapshot,start_date)
                         VALUES(%s,%s,%s,%s,%s,%s) RETURNING course_run_id""",(cohort_id,course_id,run_no,course[0],course[1],start_date))
            entity_id=cur.fetchone()[0]; self._audit(cur,"course_run.create","course_run",entity_id); return CommandResult("course_run",entity_id,{"run_number":run_no})
        return self._run({"admin", "editor"}, op)

    def change_course_run_status(self, course_run_id: int, status: str, *, end_date=None) -> CommandResult:
        allowed={"planned","active","completed","cancelled","archived"}
        transitions={"planned":{"active","cancelled"}, "active":{"completed","cancelled"},
                     "completed":{"archived"}, "cancelled":{"archived"}, "archived":set()}
        def op(cur):
            if status not in allowed: raise CommandError("invalid_input","invalid course run status")
            cur.execute("SELECT status FROM course_runs WHERE course_run_id=%s FOR UPDATE",(course_run_id,)); current=cur.fetchone()
            if not current: raise CommandError("not_found","course run not found")
            if status != current[0] and status not in transitions[current[0]]: raise CommandError("invalid_state",f"cannot change course run from {current[0]} to {status}")
            cur.execute("UPDATE course_runs SET status=%s,end_date=COALESCE(%s,end_date) WHERE course_run_id=%s RETURNING course_run_id",(status,end_date,course_run_id))
            cur.fetchone()
            self._audit(cur,"course_run.status","course_run",course_run_id,{"status":status}); return CommandResult("course_run",course_run_id,{"status":status})
        return self._run({"admin","editor"},op)

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
    ) -> CommandResult:
        """Atomically create/update the learner directory and start their run.

        Grain: this command creates one learner's business placement, continuous
        cohort membership, and course-run enrollment as one all-or-nothing event.
        """
        def op(cur):
            _required(emp_code, "emp_code"); _required(full_name, "full_name")
            if employment_status not in {"active", "inactive", "unknown"}:
                raise CommandError("invalid_input", "employment_status is invalid")
            if start_session_number < 1:
                raise CommandError("invalid_input", "start_session_number must be positive")
            cur.execute("""SELECT cr.cohort_id, c.capacity FROM course_runs cr
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           WHERE cr.course_run_id=%s FOR UPDATE""", (course_run_id,))
            target = cur.fetchone()
            if not target:
                raise CommandError("not_found", "course run not found")
            cohort_id, capacity = target
            proposed_start_session = self._propose_course_run_start_session_in_tx(cur, course_run_id)
            if start_session_number < proposed_start_session:
                raise CommandError(
                    "invalid_input",
                    f"first applicable session must be {proposed_start_session} or later for this run",
                )
            # Lock the employee row when it exists, so concurrent onboarding does
            # not create competing organization histories or active enrollments.
            cur.execute("SELECT employee_id FROM employees WHERE emp_code=%s FOR UPDATE", (emp_code.strip(),))
            row = cur.fetchone()
            if row:
                employee_id = row[0]
                cur.execute("UPDATE employees SET full_name=%s, employment_status=%s WHERE employee_id=%s",
                            (full_name.strip(), employment_status, employee_id))
            else:
                cur.execute("""INSERT INTO employees(emp_code,full_name,employment_status)
                               VALUES(%s,%s,%s) RETURNING employee_id""",
                            (emp_code.strip(), full_name.strip(), employment_status))
                employee_id = cur.fetchone()[0]
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

            cur.execute("SELECT count(*) FROM cohort_memberships WHERE cohort_id=%s AND status='active'", (cohort_id,))
            active_count = cur.fetchone()[0]
            resulting_count = active_count + 1
            if capacity is not None and resulting_count > capacity and not _normalize_label(capacity_override_reason):
                raise CommandError("capacity_exceeded", "cohort is at capacity; an HR override reason is required")

            cur.execute("""INSERT INTO placements(employee_id,placement_kind,test_date,level_id)
                           VALUES(%s,'business',%s,%s) RETURNING placement_id""",
                        (employee_id, joined_on, entrance_level_id))
            placement_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO cohort_memberships(cohort_id,employee_id,start_date)
                           VALUES(%s,%s,%s) RETURNING cohort_membership_id""", (cohort_id, employee_id, joined_on))
            membership_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO run_enrollments(
                               course_run_id,employee_id,cohort_membership_id,start_session_number,
                               business_unit_id_snapshot,job_role_id_snapshot
                           ) VALUES(%s,%s,%s,%s,%s,%s) RETURNING run_enrollment_id""",
                        (course_run_id, employee_id, membership_id, start_session_number, business_unit_id, job_role_id))
            enrollment_id = cur.fetchone()[0]
            if capacity is not None and resulting_count > capacity:
                reason = _normalize_label(capacity_override_reason)
                cur.execute("""INSERT INTO cohort_capacity_overrides(
                               cohort_id,employee_id,course_run_id,previous_capacity,resulting_active_learner_count,reason,actor_user_id
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING cohort_capacity_override_id""",
                            (cohort_id, employee_id, course_run_id, capacity, resulting_count, reason, self.actor_user_id))
                override_id = cur.fetchone()[0]
                self._audit(cur, "cohort.capacity.override", "cohort_capacity_override", override_id,
                            {"cohort_id": cohort_id, "previous_capacity": capacity, "resulting_active_learner_count": resulting_count, "reason": reason})
            self._audit(cur, "learner.onboard", "run_enrollment", enrollment_id,
                        {"employee_id": employee_id, "placement_id": placement_id, "membership_id": membership_id})
            return CommandResult("run_enrollment", enrollment_id, {"employee_id": employee_id, "placement_id": placement_id, "membership_id": membership_id})
        return self._run({"admin", "editor"}, op)

    def propose_onboarding_start_session(self, target_course_run_id: int) -> CommandResult:
        def op(cur):
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s", (target_course_run_id,))
            if not cur.fetchone(): raise CommandError("not_found", "target course run not found")
            return CommandResult("course_run", target_course_run_id, {
                "start_session_number": self._propose_course_run_start_session_in_tx(cur, target_course_run_id)
            })
        return self._run({"admin", "editor"}, op)

    def propose_transfer_start_session(self, target_course_run_id: int) -> CommandResult:
        def op(cur):
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s", (target_course_run_id,))
            if not cur.fetchone(): raise CommandError("not_found", "target course run not found")
            return CommandResult("course_run", target_course_run_id, {
                "start_session_number": self._propose_course_run_start_session_in_tx(cur, target_course_run_id)
            })
        return self._run({"admin", "editor"}, op)

    def transfer_learner(self, run_enrollment_id: int, target_course_run_id: int, transfer_date: date, *, confirmed_start_session_number: int) -> CommandResult:
        """Close source membership/enrollment and create target records atomically."""
        def op(cur):
            proposal = self._propose_transfer_start_session_in_tx(cur, target_course_run_id)
            if confirmed_start_session_number != proposal:
                raise CommandError("invalid_input", "confirmed start session must match the current transfer proposal")
            cur.execute("""SELECT re.employee_id,re.cohort_membership_id,cr.cohort_id,re.course_run_id
                           FROM run_enrollments re JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           WHERE re.run_enrollment_id=%s AND re.status='active' FOR UPDATE""", (run_enrollment_id,))
            source = cur.fetchone()
            if not source: raise CommandError("invalid_state", "enrollment is not active or does not exist")
            employee_id, source_membership_id, source_cohort_id, source_course_run_id = source
            if not source_membership_id:
                raise CommandError("invalid_state", "active enrollment must be linked to its cohort membership before transfer")
            cur.execute("SELECT cr.cohort_id,c.capacity FROM course_runs cr JOIN cohorts c ON c.cohort_id=cr.cohort_id WHERE cr.course_run_id=%s FOR UPDATE", (target_course_run_id,))
            target = cur.fetchone()
            if not target: raise CommandError("not_found", "target course run not found")
            target_cohort_id, capacity = target
            if target_course_run_id == source_course_run_id: raise CommandError("invalid_input", "target course run must differ from source")
            cur.execute("SELECT business_unit_id,job_role_id FROM employee_org_history WHERE employee_id=%s AND is_current", (employee_id,))
            org = cur.fetchone()
            if not org or org[0] is None or org[1] is None: raise CommandError("invalid_state", "current employee BU and role are required for transfer")
            cur.execute("SELECT count(*) FROM cohort_memberships WHERE cohort_id=%s AND status='active'", (target_cohort_id,))
            if capacity is not None and cur.fetchone()[0] >= capacity: raise CommandError("capacity_exceeded", "target cohort is at capacity")
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
            self._audit(cur, "learner.transfer", "run_enrollment", new_enrollment_id,
                        {"from_enrollment_id": run_enrollment_id, "from_cohort_id": source_cohort_id, "start_session_number": proposal})
            return CommandResult("run_enrollment", new_enrollment_id, {"from_enrollment_id": run_enrollment_id, "membership_id": target_membership_id, "start_session_number": proposal})
        return self._run({"admin", "editor"}, op)

    @staticmethod
    def _propose_course_run_start_session_in_tx(cur, target_course_run_id: int) -> int:
        cur.execute("""SELECT COALESCE(min(su.sequence_in_run) FILTER (WHERE m.status='planned'), max(su.sequence_in_run) FILTER (WHERE m.status='completed') + 1, 1)
                       FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id WHERE su.course_run_id=%s""", (target_course_run_id,))
        return cur.fetchone()[0]

    @staticmethod
    def _propose_transfer_start_session_in_tx(cur, target_course_run_id: int) -> int:
        return BusinessService._propose_course_run_start_session_in_tx(cur, target_course_run_id)

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

    def save_meeting(self, course_run_id: int, starts_at: datetime, duration_minutes: int, *, meeting_id=None, status="planned", cancellation_reason=None) -> CommandResult:
        def op(cur):
            if duration_minutes <= 0: raise CommandError("invalid_input", "duration_minutes must be positive")
            if status not in {"planned", "completed", "cancelled"}: raise CommandError("invalid_input", "invalid meeting status")
            if status == "cancelled" and not cancellation_reason: raise CommandError("invalid_input", "cancellation_reason is required")
            if meeting_id:
                cur.execute("""UPDATE meetings SET starts_at=%s,duration_minutes=%s,status=%s,cancellation_reason=%s
                             WHERE meeting_id=%s RETURNING meeting_id""",(starts_at,duration_minutes,status,cancellation_reason,meeting_id))
            else:
                cur.execute("""INSERT INTO meetings(course_run_id,starts_at,duration_minutes,status,cancellation_reason)
                             VALUES(%s,%s,%s,%s,%s) RETURNING meeting_id""",(course_run_id,starts_at,duration_minutes,status,cancellation_reason))
            row=cur.fetchone()
            if not row: raise CommandError("not_found","meeting not found")
            entity_id=row[0]; self._audit(cur,"meeting.save","meeting",entity_id,{"status":status,"cancellation_reason":cancellation_reason if status == "cancelled" else None}); return CommandResult("meeting",entity_id,{"status":status})
        return self._run({"admin","editor"},op)

    def cancel_meeting(self, meeting_id: int, reason: str) -> CommandResult:
        return self.save_meeting(0, datetime.now(), 1, meeting_id=meeting_id, status="cancelled", cancellation_reason=_required(reason, "reason"))

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
            cur.execute("SELECT 1 FROM course_runs WHERE course_run_id=%s FOR UPDATE", (course_run_id,))
            if not cur.fetchone():
                raise CommandError("not_found", "course run not found")
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

    def save_monthly_action_summary(self, review_month: date, *, highlights: str, risks: str, next_month_priorities: str) -> CommandResult:
        """Persist only an explicitly saved HR conclusion as an immutable version."""
        def op(cur):
            if review_month.day != 1:
                raise CommandError("invalid_input", "review month must be the first day of the month")
            self._advisory_lock(cur, f"monthly_review_action_summary:{review_month.isoformat()}")
            cur.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM monthly_review_action_summary_versions WHERE review_month=%s", (review_month,))
            version_number = cur.fetchone()[0]
            cur.execute("""INSERT INTO monthly_review_action_summary_versions(
                           review_month,version_number,highlights,risks,next_month_priorities,created_by_user_id
                         ) VALUES(%s,%s,%s,%s,%s,%s) RETURNING monthly_review_action_summary_version_id""",
                        (review_month, version_number, highlights.strip(), risks.strip(), next_month_priorities.strip(), self.actor_user_id))
            entity_id = cur.fetchone()[0]
            self._audit(cur, "monthly_review.action_summary.save", "monthly_review_action_summary", entity_id,
                        {"review_month": review_month.isoformat(), "version_number": version_number})
            return CommandResult("monthly_review_action_summary", entity_id, {"review_month": review_month, "version_number": version_number})
        return self._run({"admin", "editor"}, op)

    def attendance_roster(self, course_run_id: int, session_unit_id: int) -> CommandResult:
        """Return the applicable active roster; unsaved rows intentionally default Present."""
        def op(cur):
            cur.execute("""SELECT su.sequence_in_run, m.status
                           FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.session_unit_id=%s AND su.course_run_id=%s""", (session_unit_id, course_run_id))
            unit = cur.fetchone()
            if not unit: raise CommandError("not_found", "session unit does not belong to the selected course run")
            if unit[1] == "cancelled": raise CommandError("invalid_state", "cancelled sessions do not have an attendance roster")
            cur.execute("""SELECT re.run_enrollment_id,e.emp_code,e.full_name,re.start_session_number,
                                  COALESCE(a.effective_status,'Present') AS effective_status,
                                  a.attendance_id
                           FROM run_enrollments re JOIN employees e ON e.employee_id=re.employee_id
                           LEFT JOIN attendance a ON a.run_enrollment_id=re.run_enrollment_id AND a.session_unit_id=%s
                           WHERE re.course_run_id=%s AND re.status='active' AND re.start_session_number<=%s
                           ORDER BY e.full_name,e.emp_code""", (session_unit_id, course_run_id, unit[0]))
            rows = [dict(zip(["run_enrollment_id", "emp_code", "full_name", "start_session_number", "effective_status", "attendance_id"], row)) for row in cur.fetchall()]
            return CommandResult("attendance_roster", session_unit_id, {"sequence_in_run": unit[0], "rows": rows})
        return self._run({"admin", "editor", "viewer"}, op)

    def save_attendance_roster(self, course_run_id: int, session_unit_id: int, records: Iterable[dict[str, Any]]) -> CommandResult:
        """Write exactly one selected session's full applicable roster in one transaction."""
        records = list(records)
        def op(cur):
            cur.execute("""SELECT su.sequence_in_run,m.status,m.meeting_id
                           FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                           WHERE su.session_unit_id=%s AND su.course_run_id=%s
                           FOR UPDATE OF su,m""", (session_unit_id, course_run_id))
            unit = cur.fetchone()
            if not unit: raise CommandError("not_found", "session unit does not belong to the selected course run")
            if unit[1] == "cancelled": raise CommandError("invalid_state", "cancelled sessions cannot receive attendance")
            cur.execute("""SELECT run_enrollment_id FROM run_enrollments
                           WHERE course_run_id=%s AND status='active' AND start_session_number<=%s FOR UPDATE""",
                        (course_run_id, unit[0]))
            roster_ids = {row[0] for row in cur.fetchall()}
            submitted_ids = [item.get("run_enrollment_id") for item in records]
            if len(submitted_ids) != len(set(submitted_ids)) or set(submitted_ids) != roster_ids:
                raise CommandError("invalid_state", "attendance save must include each applicable learner exactly once")
            for item in records:
                status = item.get("effective_status")
                if status not in {"Present", "Absent"}:
                    raise CommandError("invalid_input", "attendance status must be Present or Absent")
                cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,details)
                               VALUES(%s,%s,%s,%s,%s)
                               ON CONFLICT(run_enrollment_id,session_unit_id) DO UPDATE SET effective_status=EXCLUDED.effective_status,updated_at=NOW()
                               RETURNING attendance_id""",
                            (item["run_enrollment_id"], session_unit_id, status, item.get("original_status", status),
                             psycopg2.extras.Json(_json_safe(item.get("details", {})))))
            if unit[1] == "planned":
                cur.execute("UPDATE meetings SET status='completed' WHERE meeting_id=%s", (unit[2],))
            self._audit(cur, "attendance.roster.save", "session_unit", session_unit_id,
                        {"course_run_id": course_run_id, "roster_count": len(records), "meeting_status": "completed"})
            return CommandResult("attendance", None, {"count": len(records), "session_unit_id": session_unit_id})
        return self._run({"admin", "editor"}, op)

    def bulk_record_attendance(self, records: Iterable[dict[str, Any]]) -> CommandResult:
        records=list(records)
        def op(cur):
            if not records: raise CommandError("invalid_input","at least one attendance record is required")
            ids=[]
            for item in records:
                status=item.get("effective_status")
                if status not in {"Present","Absent"}: raise CommandError("invalid_input","attendance status must be Present or Absent")
                cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,details)
                             VALUES(%s,%s,%s,%s,%s)
                             ON CONFLICT(run_enrollment_id,session_unit_id) DO UPDATE SET effective_status=EXCLUDED.effective_status,
                               updated_at=NOW() RETURNING attendance_id""",(item["run_enrollment_id"],item["session_unit_id"],status,item.get("original_status",status),psycopg2.extras.Json(_json_safe(item.get("details",{})))))
                ids.append(cur.fetchone()[0])
            self._audit(cur,"attendance.bulk_record","attendance",None,{"count":len(ids),"attendance_ids":ids}); return CommandResult("attendance",None,{"count":len(ids),"attendance_ids":ids})
        return self._run({"admin","editor"},op)

    def correct_attendance_makeup(self, attendance_id: int, makeup_session_unit_id: int, reason: str) -> CommandResult:
        def op(cur):
            _required(reason,"reason")
            cur.execute("SELECT run_enrollment_id,effective_status FROM attendance WHERE attendance_id=%s FOR UPDATE",(attendance_id,)); old=cur.fetchone()
            if not old: raise CommandError("not_found","attendance not found")
            cur.execute("""INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status,original_status,is_makeup,makeup_for_attendance_id,details)
                         VALUES(%s,%s,'Present',%s,TRUE,%s,%s) RETURNING attendance_id""",(old[0],makeup_session_unit_id,old[1],attendance_id,psycopg2.extras.Json({"correction_reason":reason})))
            new_id=cur.fetchone()[0]; self._audit(cur,"attendance.makeup","attendance",new_id,{"makeup_for":attendance_id,"reason":reason}); return CommandResult("attendance",new_id,{"makeup_for":attendance_id})
        return self._run({"admin","editor"},op)

    def calculate_exam_eligibility(self, run_enrollment_id: int) -> CommandResult:
        def op(cur):
            cur.execute("""SELECT re.course_run_id,re.start_session_number,cr.attendance_threshold_ratio_snapshot
                         FROM run_enrollments re JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                         WHERE re.run_enrollment_id=%s""",(run_enrollment_id,)); row=cur.fetchone()
            if not row: raise CommandError("not_found","enrollment not found")
            cur.execute("""SELECT COUNT(DISTINCT su.sequence_in_run), COUNT(DISTINCT su.sequence_in_run) FILTER (WHERE a.effective_status='Present')
                         FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id
                         LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id AND a.run_enrollment_id=%s
                         WHERE su.course_run_id=%s AND m.status<>'cancelled' AND su.sequence_in_run >= %s""",(run_enrollment_id,row[0],row[1]))
            total,present=cur.fetchone(); ratio=(Decimal(present)/Decimal(total)) if total else Decimal("0"); eligible=ratio >= row[2]
            return CommandResult("run_enrollment",run_enrollment_id,{"applicable_units":total,"present_units":present,"attendance_ratio":ratio,"exam_eligible":eligible})
        return self._run({"admin","editor","viewer"},op)

    def override_exam_eligibility(self, run_enrollment_id: int, eligible: bool, reason: str) -> CommandResult:
        def op(cur):
            _required(reason,"reason"); calc=self._eligibility_in_tx(cur,run_enrollment_id)
            cur.execute("""INSERT INTO evaluations(run_enrollment_id) VALUES(%s) ON CONFLICT(run_enrollment_id) DO UPDATE SET run_enrollment_id=EXCLUDED.run_enrollment_id RETURNING evaluation_id""",(run_enrollment_id,)); evaluation_id=cur.fetchone()[0]
            version = self._next_evaluation_version(cur, evaluation_id)
            cur.execute("""INSERT INTO evaluation_versions(evaluation_id,version_number,exam_eligible,exam_eligibility_override,exam_eligibility_override_reason,created_by_user_id,correction_reason)
                         VALUES(%s,%s,%s,TRUE,%s,%s,%s) RETURNING evaluation_version_id""",(evaluation_id,version,eligible,reason,self.actor_user_id,"eligibility override" if version>1 else None))
            entity_id=cur.fetchone()[0]; self._audit(cur,"eligibility.override","evaluation_version",entity_id,{"previous":calc,"eligible":eligible,"reason":reason}); return CommandResult("evaluation_version",entity_id,{"exam_eligible":eligible,"previous":calc})
        return self._run({"admin"},op)

    def _eligibility_in_tx(self, cur, enrollment_id):
        cur.execute("""SELECT re.course_run_id,re.start_session_number,cr.attendance_threshold_ratio_snapshot
                     FROM run_enrollments re JOIN course_runs cr ON cr.course_run_id=re.course_run_id WHERE re.run_enrollment_id=%s""",(enrollment_id,)); row=cur.fetchone()
        if not row: raise CommandError("not_found","enrollment not found")
        cur.execute("""SELECT COUNT(DISTINCT su.sequence_in_run),COUNT(DISTINCT su.sequence_in_run) FILTER (WHERE a.effective_status='Present') FROM session_units su
                     JOIN meetings m ON m.meeting_id=su.meeting_id LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id AND a.run_enrollment_id=%s
                     WHERE su.course_run_id=%s AND m.status<>'cancelled' AND su.sequence_in_run >= %s""",(enrollment_id,row[0],row[1])); total,present=cur.fetchone()
        ratio=(Decimal(present)/Decimal(total)) if total else Decimal("0"); return {"applicable_units":total,"present_units":present,"attendance_ratio":ratio,"exam_eligible":ratio>=row[2]}

    def record_evaluation(self, run_enrollment_id: int, *, final_level_id=None, passed=None, next_course_id=None,
                          exam_eligible=None, teacher_notes=None) -> CommandResult:
        def op(cur):
            cur.execute("INSERT INTO evaluations(run_enrollment_id) VALUES(%s) ON CONFLICT(run_enrollment_id) DO UPDATE SET run_enrollment_id=EXCLUDED.run_enrollment_id RETURNING evaluation_id",(run_enrollment_id,)); evaluation_id=cur.fetchone()[0]
            version = self._next_evaluation_version(cur, evaluation_id)
            correction=None if version==1 else "new evaluation version"
            cur.execute("""INSERT INTO evaluation_versions(evaluation_id,version_number,final_level_id,exam_eligible,passed,next_course_id,teacher_notes,correction_reason,created_by_user_id)
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING evaluation_version_id""",(evaluation_id,version,final_level_id,exam_eligible,passed,next_course_id,teacher_notes,correction,self.actor_user_id))
            entity_id=cur.fetchone()[0]; self._audit(cur,"evaluation.record" if version==1 else "evaluation.correct","evaluation_version",entity_id); return CommandResult("evaluation_version",entity_id,{"version_number":version})
        return self._run({"admin","editor"},op)

    def suggest_completion(self, run_enrollment_id: int) -> CommandResult:
        def op(cur):
            eligibility=self._eligibility_in_tx(cur,run_enrollment_id)
            cur.execute("""SELECT ev.passed,ev.next_course_id,ev.exam_eligible,ev.exam_eligibility_override
                         FROM evaluations e JOIN evaluation_versions ev ON ev.evaluation_id=e.evaluation_id
                         WHERE e.run_enrollment_id=%s ORDER BY ev.version_number DESC LIMIT 1""",(run_enrollment_id,)); evaluation=cur.fetchone()
            effective_eligible = bool(evaluation[2]) if evaluation and evaluation[2] is not None else eligibility["exam_eligible"]
            suggested=bool(evaluation and evaluation[0] is True and effective_eligible)
            cur.execute("""INSERT INTO course_completion_suggestions(run_enrollment_id,suggested,reason) VALUES(%s,%s,%s)
                         ON CONFLICT(run_enrollment_id) DO UPDATE SET suggested=EXCLUDED.suggested,reason=EXCLUDED.reason,status='suggested',confirmed_by_user_id=NULL,confirmed_at=NULL
                         RETURNING completion_suggestion_id""",(run_enrollment_id,suggested,psycopg2.extras.Json(_json_safe({"eligibility":eligibility,"effective_exam_eligible":effective_eligible,"evaluation_present":bool(evaluation)}))))
            entity_id=cur.fetchone()[0]; self._audit(cur,"completion.suggest","completion_suggestion",entity_id,{"suggested":suggested}); return CommandResult("completion_suggestion",entity_id,{"suggested":suggested,"reason":eligibility})
        return self._run({"admin","editor"},op)

    def confirm_completion(self, run_enrollment_id: int, confirmed: bool, reason: str | None = None) -> CommandResult:
        def op(cur):
            if not confirmed and not reason: raise CommandError("invalid_input","reason is required when rejecting completion")
            cur.execute("UPDATE course_completion_suggestions SET status=%s,confirmed_by_user_id=%s,confirmed_at=NOW() WHERE run_enrollment_id=%s RETURNING completion_suggestion_id",("confirmed" if confirmed else "rejected",self.actor_user_id,run_enrollment_id)); row=cur.fetchone()
            if not row: raise CommandError("invalid_state","completion must be suggested before confirmation")
            cur.execute("UPDATE run_enrollments SET status='completed' WHERE run_enrollment_id=%s AND %s",(run_enrollment_id,confirmed))
            self._audit(cur,"completion.confirm","completion_suggestion",row[0],{"confirmed":confirmed,"reason":reason}); return CommandResult("completion_suggestion",row[0],{"confirmed":confirmed})
        return self._run({"admin"},op)

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
