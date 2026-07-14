"""Cohort, PIC assignment, and course-run administration commands.

Split verbatim from the original services.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg2
import psycopg2.extras

from services.base import CommandError, CommandResult, _json_safe, _normalize_label, _required


class ClassScheduleCommands:
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
