"""Load staged workbook rows into the canonical v3 schema conservatively."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg2
import psycopg2.extras


FORMULA_PREFIX = "="


@dataclass(frozen=True)
class RawRow:
    raw_row_id: int
    import_batch_id: int
    sheet_name: str
    source_row_number: int
    values: dict[str, Any]


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).strip().split())
    if not text or text.startswith(FORMULA_PREFIX):
        return None
    return text


def clean_code(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def clean_emp_code(value: Any) -> str | None:
    code = clean_code(value)
    if not code or not re.fullmatch(r"\d+", code):
        return None
    return code


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, dict):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None
    if number == number.to_integral_value():
        return int(number)
    return None


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, dict):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def detect_session_resets(rows: list[tuple[datetime, int]]) -> list[dict[str, Any]]:
    reset_candidates: list[dict[str, Any]] = []
    previous_date = None
    previous_session = None
    for starts_at, session_order in sorted(set(rows)):
        if (
            previous_date is not None
            and starts_at > previous_date
            and session_order < previous_session
        ):
            reset_candidates.append(
                {
                    "date": starts_at.isoformat(),
                    "session_order": session_order,
                    "previous_date": previous_date.isoformat(),
                    "previous_session_order": previous_session,
                }
            )
        if previous_date is None or starts_at > previous_date or session_order > previous_session:
            previous_date = starts_at
            previous_session = session_order
    return reset_candidates


class CanonicalLoader:
    def __init__(self, conn):
        self.conn = conn
        self.issues_seen: set[tuple[str, str, str | None, int | None, int | None]] = set()
        self.stats: Counter[str] = Counter()

    def outcome(
        self,
        row: RawRow,
        outcome_type: str,
        outcome_code: str,
        target_entity: str | None = None,
        target_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etl_source_row_outcomes (
                    import_batch_id, raw_row_id, source_sheet, source_row_number,
                    outcome_type, outcome_code, target_entity, target_key, details
                )
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM etl_source_row_outcomes
                    WHERE raw_row_id = %s
                      AND outcome_type = %s
                      AND outcome_code = %s
                      AND COALESCE(target_entity, '') = COALESCE(%s, '')
                      AND COALESCE(target_key, '') = COALESCE(%s, '')
                )
                """,
                (
                    row.import_batch_id,
                    row.raw_row_id,
                    row.sheet_name,
                    row.source_row_number,
                    outcome_type,
                    outcome_code,
                    target_entity,
                    target_key,
                    psycopg2.extras.Json(details or {}),
                    row.raw_row_id,
                    outcome_type,
                    outcome_code,
                    target_entity,
                    target_key,
                ),
            )
            self.stats[f"outcomes.{outcome_type}"] += cur.rowcount

    def ignored(self, row: RawRow, code: str, details: dict[str, Any] | None = None) -> None:
        self.outcome(row, "ignored", code, None, None, details)

    def rows(self, sheet_name: str) -> list[RawRow]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT raw_row_id, import_batch_id, sheet_name, source_row_number,
                       raw_payload->'values_by_header' AS values
                FROM raw_workbook_rows
                WHERE sheet_name = %s
                  AND source_row_number > 1
                ORDER BY source_row_number
                """,
                (sheet_name,),
            )
            return [
                RawRow(
                    raw_row_id=row["raw_row_id"],
                    import_batch_id=row["import_batch_id"],
                    sheet_name=row["sheet_name"],
                    source_row_number=row["source_row_number"],
                    values=row["values"],
                )
                for row in cur.fetchall()
            ]

    def issue(self, row: RawRow, code: str, entity_type: str, entity_key: str | None, details: dict[str, Any]) -> None:
        key = (code, entity_type, entity_key, row.import_batch_id, row.raw_row_id)
        if key in self.issues_seen:
            return
        self.issues_seen.add(key)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_quality_issues (
                    import_batch_id, issue_code, entity_type, entity_key,
                    source_sheet, source_row_number, details
                )
                SELECT %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM data_quality_issues
                    WHERE import_batch_id = %s
                      AND issue_code = %s
                      AND entity_type = %s
                      AND COALESCE(entity_key, '') = COALESCE(%s, '')
                      AND source_sheet = %s
                      AND source_row_number = %s
                )
                """,
                (
                    row.import_batch_id,
                    code,
                    entity_type,
                    entity_key,
                    row.sheet_name,
                    row.source_row_number,
                    psycopg2.extras.Json(details),
                    row.import_batch_id,
                    code,
                    entity_type,
                    entity_key,
                    row.sheet_name,
                    row.source_row_number,
                ),
            )
            self.stats[f"issues.{code}"] += cur.rowcount
        self.outcome(row, "issue", code, entity_type, entity_key, details)

    def scalar_id(self, sql: str, params: tuple[Any, ...]) -> int | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

    def load_levels(self) -> None:
        sequence = 1
        for row in self.rows("LEVEL_HELPER"):
            name = clean_text(row.values.get("Level Name"))
            numeric = parse_decimal(row.values.get("Numeric Value"))
            if not name or numeric is None:
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO levels (level_name, numeric_value, sequence_order)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (level_name) DO UPDATE
                    SET numeric_value = EXCLUDED.numeric_value,
                        sequence_order = EXCLUDED.sequence_order
                    """,
                    (name, numeric, sequence),
                )
            self.outcome(row, "loaded", "level_loaded", "levels", name)
            self.stats["levels.upserted"] += 1
            sequence += 1

    def load_courses(self) -> None:
        for row in self.rows("COURSE_PLAN"):
            name = clean_text(row.values.get("Course Name"))
            expected = parse_int(row.values.get("Expected Sessions"))
            if not name or not expected:
                continue
            code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:32]
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO courses (course_code, course_name, expected_units)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (course_name) DO UPDATE
                    SET expected_units = EXCLUDED.expected_units
                    """,
                    (code, name, expected),
                )
            self.outcome(row, "loaded", "course_loaded", "courses", name)
            self.stats["courses.upserted"] += 1

    def employee_id(self, emp_code: str) -> int | None:
        return self.scalar_id("SELECT employee_id FROM employees WHERE emp_code = %s", (emp_code,))

    def ensure_employee(self, emp_code: str | None, full_name: str | None, email: str | None = None, english_name: str | None = None) -> int | None:
        if not emp_code:
            return None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO employees (emp_code, full_name, email, english_name)
                VALUES (%s, COALESCE(%s, %s), %s, %s)
                ON CONFLICT (emp_code) DO UPDATE
                SET full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), employees.full_name),
                    email = COALESCE(EXCLUDED.email, employees.email),
                    english_name = COALESCE(EXCLUDED.english_name, employees.english_name)
                RETURNING employee_id
                """,
                (emp_code, full_name, emp_code, email, english_name),
            )
            self.stats["employees.upserted"] += 1
            return cur.fetchone()[0]

    def load_employees(self) -> None:
        for row in self.rows("STUDENTS"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            full_name = clean_text(row.values.get("Full Name"))
            if not emp_code:
                self.issue(row, "missing_emp_code", "employee", None, {"sheet": "STUDENTS"})
                continue
            self.ensure_employee(emp_code, full_name)
            self.outcome(row, "loaded", "employee_loaded", "employees", emp_code)

        for row in self.rows("PIC"):
            emp_code = clean_emp_code(row.values.get("EMP Code"))
            full_name = clean_text(row.values.get("PIC"))
            if emp_code:
                self.ensure_employee(emp_code, full_name, clean_text(row.values.get("Mail")), clean_text(row.values.get("English name")))
                self.outcome(row, "loaded", "pic_employee_loaded", "employees", emp_code)
            else:
                class_code = clean_code(row.values.get("Class Code"))
                pic_name = clean_text(row.values.get("PIC"))
                if not class_code and not pic_name:
                    self.ignored(row, "pic_helper_or_trailing_row")

        for row in self.rows("Placement"):
            emp_code = clean_emp_code(row.values.get("Emp. Code"))
            full_name = clean_text(row.values.get("Full name"))
            if emp_code:
                self.ensure_employee(emp_code, full_name)
                self.outcome(row, "loaded", "placement_employee_loaded", "employees", emp_code)
            else:
                marker_values = [
                    clean_text(row.values.get("Emp. Code")),
                    clean_text(row.values.get("Full name")),
                    clean_text(row.values.get("Entrance Test date")),
                    clean_text(row.values.get("1st session:")),
                ]
                if any(marker_values):
                    self.ignored(row, "placement_header_or_helper_row", {"markers": marker_values})
                else:
                    self.ignored(row, "placement_blank_helper_row")

    def ensure_named_ref(self, table: str, column: str, value: str | None) -> int | None:
        if not value:
            return None
        id_col = "business_unit_id" if table == "business_units" else "job_role_id"
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} ({column})
                VALUES (%s)
                ON CONFLICT ({column}) DO UPDATE SET {column} = EXCLUDED.{column}
                RETURNING {id_col}
                """,
                (value,),
            )
            return cur.fetchone()[0]

    def load_org_history(self) -> None:
        seen: set[str] = set()
        for row in self.rows("sheet2"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            if not emp_code or emp_code in seen:
                continue
            employee_id = self.employee_id(emp_code)
            if not employee_id:
                continue
            bu_id = self.ensure_named_ref("business_units", "business_unit_name", clean_text(row.values.get("BU")))
            role_id = self.ensure_named_ref("job_roles", "job_role_name", clean_text(row.values.get("Role")))
            if not bu_id and not role_id:
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO employee_org_history (
                        employee_id, business_unit_id, job_role_id, valid_from, observed_from
                    )
                    VALUES (%s, %s, %s, DATE '1900-01-01', 'sheet2')
                    ON CONFLICT (employee_id) WHERE is_current DO NOTHING
                    """,
                    (employee_id, bu_id, role_id),
                )
            self.outcome(row, "loaded", "org_history_loaded", "employee_org_history", emp_code)
            seen.add(emp_code)
            self.stats["org_history.inserted"] += 1

    def level_id(self, name: str | None) -> int | None:
        if not name:
            return None
        return self.scalar_id("SELECT level_id FROM levels WHERE level_name = %s", (name,))

    def course_id(self, name: str | None) -> int | None:
        if not name:
            return None
        return self.scalar_id("SELECT course_id FROM courses WHERE course_name = %s", (name,))

    def cohort_id(self, class_code: str | None) -> int | None:
        if not class_code:
            return None
        return self.scalar_id("SELECT cohort_id FROM cohorts WHERE class_code = %s", (class_code,))

    def load_placements(self) -> None:
        seen: set[str] = set()
        for row in self.rows("Placement"):
            emp_code = clean_emp_code(row.values.get("Emp. Code"))
            if not emp_code:
                continue
            employee_id = self.employee_id(emp_code)
            if not employee_id:
                self.issue(row, "missing_emp_code", "placement", emp_code, {"reason": "employee could not be created"})
                continue
            if emp_code in seen:
                self.issue(row, "duplicate_business_placement", "placement", emp_code, {"emp_code": emp_code})
                continue
            seen.add(emp_code)
            level_name = clean_text(row.values.get("1st session:"))
            level_id = self.level_id(level_name)
            if level_name and not level_id:
                self.issue(row, "unknown_level", "placement", emp_code, {"level": level_name})
            test_date = parse_date(row.values.get("Entrance Test date"))
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO placements (
                        employee_id, placement_kind, test_date, level_id,
                        grammar_feedback, vocabulary_feedback, pronunciation_feedback,
                        fluency_feedback, source_reference
                    )
                    VALUES (%s, 'business', %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (employee_id, placement_kind) DO NOTHING
                    """,
                    (
                        employee_id,
                        test_date,
                        level_id,
                        clean_text(row.values.get("column_5")),
                        clean_text(row.values.get("column_6")),
                        clean_text(row.values.get("column_7")),
                        clean_text(row.values.get("column_8")),
                        psycopg2.extras.Json({"sheet": row.sheet_name, "row": row.source_row_number}),
                    ),
                )
            self.outcome(row, "loaded", "placement_loaded", "placements", emp_code)
            self.stats["placements.inserted"] += 1

    def load_cohorts(self) -> None:
        class_codes: set[str] = set()
        for sheet, field in [("PIC", "Class Code"), ("CLASS_DATES", "Class Code"), ("sheet2", "Class Code"), ("ATTENDANCE_LOG", "Class Code")]:
            for row in self.rows(sheet):
                code = clean_code(row.values.get(field))
                if code:
                    class_codes.add(code)
        for class_code in sorted(class_codes):
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohorts (class_code, display_name, status)
                    VALUES (%s, %s, 'active')
                    ON CONFLICT (class_code) DO NOTHING
                    """,
                    (class_code, class_code),
                )
            self.stats["cohorts.inserted"] += 1

    def mark_cohort_source_outcomes(self) -> None:
        for sheet, field in [("PIC", "Class Code"), ("CLASS_DATES", "Class Code"), ("sheet2", "Class Code"), ("ATTENDANCE_LOG", "Class Code")]:
            for row in self.rows(sheet):
                class_code = clean_code(row.values.get(field))
                if class_code and self.cohort_id(class_code):
                    self.outcome(row, "loaded", "cohort_resolved", "cohorts", class_code)

    def load_pic_assignments(self) -> None:
        for row in self.rows("PIC"):
            class_code = clean_code(row.values.get("Class Code"))
            emp_code = clean_emp_code(row.values.get("EMP Code"))
            cohort_id = self.cohort_id(class_code)
            pic_employee_id = self.employee_id(emp_code) if emp_code else None
            if not class_code or not cohort_id:
                if not class_code and not emp_code and not clean_text(row.values.get("PIC")):
                    self.ignored(row, "pic_helper_or_trailing_row")
                    continue
                self.issue(row, "missing_class_code", "cohort_pic_assignment", class_code, {"class_code": class_code})
                continue
            if not pic_employee_id:
                self.issue(row, "unmapped_pic_employee", "cohort_pic_assignment", class_code, {"emp_code": emp_code, "pic": clean_text(row.values.get("PIC"))})
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohort_pic_assignments (cohort_id, pic_employee_id, start_date)
                    VALUES (%s, %s, DATE '1900-01-01')
                    ON CONFLICT (cohort_id) WHERE end_date IS NULL DO NOTHING
                    """,
                    (cohort_id, pic_employee_id),
                )
            self.outcome(row, "loaded", "pic_assignment_loaded", "cohort_pic_assignments", class_code)
            self.stats["pic_assignments.inserted"] += 1

    def load_course_runs(self) -> None:
        pairs: set[tuple[str, str]] = set()
        for sheet in ("CLASS_DATES", "sheet2", "ATTENDANCE_LOG"):
            for row in self.rows(sheet):
                class_code = clean_code(row.values.get("Class Code"))
                course_name = clean_text(row.values.get("Course Name"))
                if class_code and course_name:
                    pairs.add((class_code, course_name))
        for class_code, course_name in sorted(pairs):
            cohort_id = self.cohort_id(class_code)
            course_id = self.course_id(course_name)
            if not cohort_id or not course_id:
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO course_runs (
                        cohort_id, course_id, run_number, status,
                        expected_units_snapshot, attendance_threshold_ratio_snapshot
                    )
                    SELECT %s, c.course_id, 1, 'active', c.expected_units, c.attendance_threshold_ratio
                    FROM courses c
                    WHERE c.course_id = %s
                    ON CONFLICT (cohort_id, course_id, run_number) DO NOTHING
                    """,
                    (cohort_id, course_id),
                )
            self.stats["course_runs.inserted"] += 1

    def mark_course_run_source_outcomes(self) -> None:
        for sheet in ("CLASS_DATES", "sheet2", "ATTENDANCE_LOG"):
            for row in self.rows(sheet):
                class_code = clean_code(row.values.get("Class Code"))
                course_name = clean_text(row.values.get("Course Name"))
                if class_code and course_name and self.course_run_id(class_code, course_name):
                    self.outcome(
                        row,
                        "loaded",
                        "course_run_resolved",
                        "course_runs",
                        f"{class_code}:{course_name}:1",
                    )

    def course_run_id(self, class_code: str | None, course_name: str | None) -> int | None:
        if not class_code or not course_name:
            return None
        return self.scalar_id(
            """
            SELECT cr.course_run_id
            FROM course_runs cr
            JOIN cohorts c ON c.cohort_id = cr.cohort_id
            JOIN courses co ON co.course_id = cr.course_id
            WHERE c.class_code = %s AND co.course_name = %s AND cr.run_number = 1
            """,
            (class_code, course_name),
        )

    def membership_id(self, employee_id: int, cohort_id: int) -> int | None:
        return self.scalar_id(
            "SELECT cohort_membership_id FROM cohort_memberships WHERE employee_id = %s AND cohort_id = %s ORDER BY cohort_membership_id LIMIT 1",
            (employee_id, cohort_id),
        )

    def load_memberships_and_enrollments(self) -> None:
        for row in self.rows("sheet2"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            if not emp_code:
                self.issue(row, "missing_emp_code", "run_enrollment", None, {})
                continue
            if not class_code:
                self.issue(row, "missing_class_code", "run_enrollment", emp_code, {})
                continue
            if not course_name:
                self.issue(row, "missing_course", "run_enrollment", f"{emp_code}:{class_code}", {})
                continue
            employee_id = self.employee_id(emp_code)
            cohort_id = self.cohort_id(class_code)
            course_run_id = self.course_run_id(class_code, course_name)
            if not employee_id or not cohort_id or not course_run_id:
                self.issue(row, "unknown_course", "run_enrollment", f"{emp_code}:{class_code}:{course_name}", {"course_name": course_name})
                continue
            joined_at = parse_date(row.values.get("start date")) or date(1900, 1, 1)
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohort_memberships (cohort_id, employee_id, start_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (employee_id) WHERE status = 'active' DO NOTHING
                    """,
                    (cohort_id, employee_id, joined_at),
                )
            self.outcome(row, "loaded", "cohort_membership_resolved", "cohort_memberships", f"{emp_code}:{class_code}")
            membership_id = self.membership_id(employee_id, cohort_id)
            bu_id = self.ensure_named_ref("business_units", "business_unit_name", clean_text(row.values.get("BU")))
            role_id = self.ensure_named_ref("job_roles", "job_role_name", clean_text(row.values.get("Role")))
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_enrollments (
                        course_run_id, employee_id, cohort_membership_id,
                        business_unit_id_snapshot, job_role_id_snapshot
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (course_run_id, employee_id) DO NOTHING
                    RETURNING run_enrollment_id
                    """,
                    (course_run_id, employee_id, membership_id, bu_id, role_id),
                )
                inserted = cur.fetchone()
            if inserted:
                self.stats["run_enrollments.inserted"] += 1
            self.outcome(row, "loaded", "run_enrollment_loaded", "run_enrollments", f"{emp_code}:{class_code}:{course_name}")
            self.load_evaluation(row, course_run_id, employee_id)

    def run_enrollment_id(self, class_code: str | None, course_name: str | None, emp_code: str | None) -> int | None:
        if not class_code or not course_name or not emp_code:
            return None
        return self.scalar_id(
            """
            SELECT re.run_enrollment_id
            FROM run_enrollments re
            JOIN employees e ON e.employee_id = re.employee_id
            JOIN course_runs cr ON cr.course_run_id = re.course_run_id
            JOIN cohorts c ON c.cohort_id = cr.cohort_id
            JOIN courses co ON co.course_id = cr.course_id
            WHERE c.class_code = %s AND co.course_name = %s AND e.emp_code = %s
            """,
            (class_code, course_name, emp_code),
        )

    def load_evaluation(self, row: RawRow, course_run_id: int, employee_id: int) -> None:
        final_level_name = clean_text(row.values.get("Final Level"))
        if not final_level_name:
            return
        final_level_id = self.level_id(final_level_name)
        emp_code = clean_emp_code(row.values.get("Emp Code"))
        if not final_level_id:
            self.issue(row, "unknown_level", "evaluation", emp_code, {"level": final_level_name})
            return
        enrollment_id = self.scalar_id(
            "SELECT run_enrollment_id FROM run_enrollments WHERE course_run_id = %s AND employee_id = %s",
            (course_run_id, employee_id),
        )
        if not enrollment_id:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluations (run_enrollment_id)
                VALUES (%s)
                ON CONFLICT (run_enrollment_id) DO UPDATE SET run_enrollment_id = EXCLUDED.run_enrollment_id
                RETURNING evaluation_id
                """,
                (enrollment_id,),
            )
            evaluation_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO evaluation_versions (evaluation_id, version_number, final_level_id)
                VALUES (%s, 1, %s)
                ON CONFLICT (evaluation_id, version_number) DO NOTHING
                """,
                (evaluation_id, final_level_id),
            )
        self.outcome(row, "loaded", "evaluation_loaded", "evaluations", emp_code)
        self.stats["evaluations.upserted"] += 1

    def load_schedule_and_attendance(self) -> None:
        groups: dict[tuple[str, str, int], set[datetime]] = defaultdict(set)
        attendance_rows = self.rows("ATTENDANCE_LOG")
        for row in attendance_rows:
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            session_order = parse_int(row.values.get("Session Order"))
            starts_at = parse_datetime(row.values.get("Date"))
            if class_code and course_name and session_order and starts_at:
                groups[(class_code, course_name, session_order)].add(starts_at)

        conflicting = {key for key, dates in groups.items() if len(dates) > 1}
        pair_session_rows: dict[tuple[str, str], list[tuple[datetime, int]]] = defaultdict(list)
        for (class_code, course_name, session_order), dates in groups.items():
            for starts_at in dates:
                pair_session_rows[(class_code, course_name)].append((starts_at, session_order))
        run_boundary_resets = {
            pair: resets
            for pair, rows in pair_session_rows.items()
            if (resets := detect_session_resets(rows))
        }
        meeting_unit_numbers: dict[tuple[int, datetime, int], int] = {}
        sessions_by_meeting: dict[tuple[int, datetime], list[int]] = defaultdict(list)
        for (class_code, course_name, session_order), dates in groups.items():
            if (class_code, course_name, session_order) in conflicting or len(dates) != 1:
                continue
            if (class_code, course_name) in run_boundary_resets:
                continue
            course_run_id = self.course_run_id(class_code, course_name)
            if not course_run_id:
                continue
            starts_at = next(iter(dates))
            sessions_by_meeting[(course_run_id, starts_at)].append(session_order)

        overfull_meetings = {
            key for key, session_orders in sessions_by_meeting.items()
            if len(set(session_orders)) > 2
        }
        for key, session_orders in sessions_by_meeting.items():
            if key in overfull_meetings:
                continue
            for unit_number, session_order in enumerate(sorted(set(session_orders)), start=1):
                meeting_unit_numbers[(key[0], key[1], session_order)] = unit_number

        session_unit_by_key: dict[tuple[str, str, int, datetime], int] = {}
        for (class_code, course_name, session_order), dates in groups.items():
            if (class_code, course_name, session_order) in conflicting:
                continue
            if (class_code, course_name) in run_boundary_resets:
                continue
            starts_at = next(iter(dates))
            course_run_id = self.course_run_id(class_code, course_name)
            if not course_run_id:
                continue
            if (course_run_id, starts_at) in overfull_meetings:
                continue
            unit_number = meeting_unit_numbers.get((course_run_id, starts_at, session_order))
            if not unit_number:
                continue
            existing_session_unit_id = self.scalar_id(
                "SELECT session_unit_id FROM session_units WHERE course_run_id = %s AND sequence_in_run = %s",
                (course_run_id, session_order),
            )
            if existing_session_unit_id:
                session_unit_by_key[(class_code, course_name, session_order, starts_at)] = existing_session_unit_id
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings (course_run_id, starts_at, duration_minutes, status)
                    VALUES (%s, %s, 60, 'completed')
                    ON CONFLICT (course_run_id, starts_at) DO UPDATE SET starts_at = EXCLUDED.starts_at
                    RETURNING meeting_id
                    """,
                    (course_run_id, starts_at),
                )
                meeting_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO session_units (course_run_id, meeting_id, sequence_in_run, unit_number_in_meeting)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (course_run_id, sequence_in_run) DO UPDATE SET sequence_in_run = EXCLUDED.sequence_in_run
                    RETURNING session_unit_id
                    """,
                    (course_run_id, meeting_id, session_order, unit_number),
                )
                session_unit_id = cur.fetchone()[0]
            session_unit_by_key[(class_code, course_name, session_order, starts_at)] = session_unit_id

        for row in attendance_rows:
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            session_order = parse_int(row.values.get("Session Order"))
            starts_at = parse_datetime(row.values.get("Date"))
            status = clean_text(row.values.get("Status"))
            entity_key = ":".join(part for part in [emp_code, class_code, course_name, str(session_order) if session_order else None] if part)
            if not starts_at:
                self.issue(row, "malformed_date", "attendance", entity_key, {"date": row.values.get("Date")})
                continue
            if not course_name:
                self.issue(row, "missing_course", "attendance", entity_key, {})
                continue
            if not emp_code:
                self.issue(row, "missing_emp_code", "attendance", entity_key, {})
                continue
            if not class_code:
                self.issue(row, "missing_class_code", "attendance", entity_key, {})
                continue
            if not session_order or (class_code, course_name, session_order) in conflicting:
                self.issue(row, "conflicting_session_structure", "attendance", entity_key, {"session_order": session_order})
                continue
            if (class_code, course_name) in run_boundary_resets:
                self.issue(
                    row,
                    "run_boundary_unresolved",
                    "attendance",
                    entity_key,
                    {"reset_examples": run_boundary_resets[(class_code, course_name)][:5]},
                )
                continue
            if status not in {"Present", "Absent"}:
                self.issue(row, "invalid_attendance_status", "attendance", entity_key, {"status": status})
                continue
            enrollment_id = self.run_enrollment_id(class_code, course_name, emp_code)
            if not enrollment_id:
                self.issue(row, "attendance_without_enrollment", "attendance", entity_key, {})
                continue
            course_run_id = self.course_run_id(class_code, course_name)
            if course_run_id and (course_run_id, starts_at) in overfull_meetings:
                self.issue(row, "conflicting_session_structure", "attendance", entity_key, {"reason": "meeting has more than two normal units"})
                continue
            session_unit_id = session_unit_by_key.get((class_code, course_name, session_order, starts_at))
            if not session_unit_id:
                self.issue(row, "conflicting_session_structure", "attendance", entity_key, {"reason": "session unit not created"})
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO attendance (run_enrollment_id, session_unit_id, effective_status, original_status, details)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_enrollment_id, session_unit_id) DO NOTHING
                    """,
                    (
                        enrollment_id,
                        session_unit_id,
                        status,
                        status,
                        psycopg2.extras.Json({"sheet": row.sheet_name, "row": row.source_row_number}),
                    ),
                )
                self.stats["attendance.inserted"] += cur.rowcount
            self.outcome(row, "loaded", "attendance_loaded", "attendance", entity_key)

    def run(self) -> Counter[str]:
        self.load_levels()
        self.load_courses()
        self.load_employees()
        self.load_org_history()
        self.load_placements()
        self.load_cohorts()
        self.mark_cohort_source_outcomes()
        self.load_pic_assignments()
        self.load_course_runs()
        self.mark_course_run_source_outcomes()
        self.load_memberships_and_enrollments()
        self.load_schedule_and_attendance()
        return self.stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database_url")
    args = parser.parse_args()
    with psycopg2.connect(args.database_url) as conn:
        loader = CanonicalLoader(conn)
        stats = loader.run()
    print(json.dumps(dict(sorted(stats.items())), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
