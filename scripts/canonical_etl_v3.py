"""Load staged workbook rows into the canonical v3 schema conservatively."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras


FORMULA_PREFIX = "="
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMEDIATION_PATH = ROOT / "config" / "phase10_remediation.json"


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


class CanonicalLoader:
    def __init__(
        self,
        conn,
        active_import_batch_id: int,
        fail_after_step: str | None = None,
        remediation: dict[str, Any] | None = None,
    ):
        self.conn = conn
        self.active_import_batch_id = active_import_batch_id
        self.issues_seen: set[tuple[str, str, str | None, int | None, int | None]] = set()
        self.stats: Counter[str] = Counter()
        self.fail_after_step = fail_after_step
        self.remediation = remediation or {}

    def maybe_fail(self, step: str) -> None:
        if self.fail_after_step == step:
            raise RuntimeError(f"Forced failure after step: {step}")

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
                  AND import_batch_id = %s
                  AND source_row_number > 1
                ORDER BY source_row_number
                """,
                (sheet_name, self.active_import_batch_id),
            )
            rows = [
                RawRow(
                    raw_row_id=row["raw_row_id"],
                    import_batch_id=row["import_batch_id"],
                    sheet_name=row["sheet_name"],
                    source_row_number=row["source_row_number"],
                    values=dict(row["values"]),
                )
                for row in cur.fetchall()
            ]
        overrides = self.remediation.get("row_overrides", {})
        return [
            RawRow(
                raw_row_id=row.raw_row_id,
                import_batch_id=row.import_batch_id,
                sheet_name=row.sheet_name,
                source_row_number=row.source_row_number,
                values=self.apply_row_remediation(
                    row.sheet_name,
                    row.source_row_number,
                    {**row.values, **overrides.get(f"{row.sheet_name}:{row.source_row_number}", {})},
                ),
            )
            for row in rows
        ]

    def apply_row_remediation(self, sheet_name: str, source_row_number: int, values: dict[str, Any]) -> dict[str, Any]:
        remediated = dict(values)
        for rule in self.remediation.get("date_year_overrides", []):
            if rule.get("sheet_name") != sheet_name:
                continue
            if clean_code(remediated.get("Class Code")) != rule.get("class_code"):
                continue
            if clean_text(remediated.get("Course Name")) != rule.get("course_name"):
                continue
            field = rule.get("field", "Date")
            observed_at = parse_datetime(remediated.get(field))
            if not observed_at or observed_at.year != int(rule.get("from_year", 0)):
                continue
            remediated[field] = observed_at.replace(year=int(rule["to_year"])).isoformat()
            self.stats["remediation.date_year_overrides"] += 1
        return remediated

    def remediation_action(self, action_group: str, row: RawRow) -> str | None:
        actions = self.remediation.get(action_group, {})
        return actions.get(f"{row.sheet_name}:{row.source_row_number}")

    def normalize_level_name(self, name: str | None) -> str | None:
        if not name:
            return None
        aliases = {
            str(source).casefold(): str(target)
            for source, target in self.remediation.get("level_aliases", {}).items()
        }
        return aliases.get(name.casefold(), name)

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
            bu_id = self.ensure_named_ref("business_units", "business_unit_name", clean_text(row.values.get("BU")) or "Unknown BU")
            role_id = self.ensure_named_ref("job_roles", "job_role_name", clean_text(row.values.get("Role")) or "Unknown Role")
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
        unknown_bu_id = self.ensure_named_ref("business_units", "business_unit_name", "Unknown BU")
        unknown_role_id = self.ensure_named_ref("job_roles", "job_role_name", "Unknown Role")
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO employee_org_history(employee_id,business_unit_id,job_role_id,valid_from,observed_from)
                           SELECT e.employee_id,%s,%s,DATE '1900-01-01','etl_unknown_placeholder'
                           FROM employees e LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
                           WHERE eoh.employee_org_history_id IS NULL""", (unknown_bu_id, unknown_role_id))
            self.stats["org_history.unknown_backfilled"] += cur.rowcount

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
            placement_kind = "business"
            if emp_code in seen:
                action = self.remediation_action("placement_duplicate_actions", row)
                if action == "exclude":
                    self.ignored(row, "accepted_duplicate_business_placement", {"emp_code": emp_code})
                    continue
                if action == "diagnostic":
                    placement_kind = "diagnostic"
                elif action == "replace_business":
                    placement_kind = "business"
                else:
                    self.issue(row, "duplicate_business_placement", "placement", emp_code, {"emp_code": emp_code})
                    continue
            else:
                seen.add(emp_code)
            level_name = self.normalize_level_name(clean_text(row.values.get("1st session:")))
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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (employee_id, placement_kind) DO UPDATE
                    SET test_date = EXCLUDED.test_date,
                        level_id = EXCLUDED.level_id,
                        grammar_feedback = EXCLUDED.grammar_feedback,
                        vocabulary_feedback = EXCLUDED.vocabulary_feedback,
                        pronunciation_feedback = EXCLUDED.pronunciation_feedback,
                        fluency_feedback = EXCLUDED.fluency_feedback,
                        source_reference = EXCLUDED.source_reference
                    """,
                    (
                        employee_id,
                        placement_kind,
                        test_date,
                        level_id,
                        clean_text(row.values.get("column_5")),
                        clean_text(row.values.get("column_6")),
                        clean_text(row.values.get("column_7")),
                        clean_text(row.values.get("column_8")),
                        psycopg2.extras.Json({"sheet": row.sheet_name, "row": row.source_row_number}),
                    ),
                )
            self.outcome(
                row,
                "loaded",
                "placement_loaded",
                "placements",
                f"{emp_code}:{placement_kind}",
                {"placement_kind": placement_kind},
            )
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
            pic_label = clean_text(row.values.get("PIC"))
            cohort_id = self.cohort_id(class_code)
            pic_employee_id = self.employee_id(emp_code) if emp_code else None
            if not class_code or not cohort_id:
                if not class_code and not emp_code and not clean_text(row.values.get("PIC")):
                    self.ignored(row, "pic_helper_or_trailing_row")
                    continue
                self.issue(row, "missing_class_code", "cohort_pic_assignment", class_code, {"class_code": class_code})
                continue
            if not pic_employee_id and not pic_label:
                self.issue(row, "unmapped_pic_employee", "cohort_pic_assignment", class_code, {"emp_code": emp_code, "pic": clean_text(row.values.get("PIC"))})
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohort_pic_assignments (cohort_id, pic_employee_id, pic_label, start_date)
                    VALUES (%s, %s, %s, DATE '1900-01-01')
                    ON CONFLICT (cohort_id) WHERE end_date IS NULL DO NOTHING
                    """,
                    (cohort_id, pic_employee_id, pic_label),
                )
            self.outcome(
                row,
                "loaded",
                "pic_assignment_loaded",
                "cohort_pic_assignments",
                class_code,
                {"assignment_type": "employee" if pic_employee_id else "label", "pic_label": pic_label},
            )
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

    def attendance_first_session_map(self) -> dict[tuple[str, str, str], int]:
        first_sessions: dict[tuple[str, str, str], int] = {}
        for row in self.rows("ATTENDANCE_LOG"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            session_order = parse_int(row.values.get("Session Order"))
            if not emp_code or not class_code or not course_name or not session_order:
                continue
            key = (emp_code, class_code, course_name)
            first_sessions[key] = min(first_sessions.get(key, session_order), session_order)
        return first_sessions

    def transfer_review_by_row(self) -> dict[int, dict[str, Any]]:
        attendance: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in self.rows("ATTENDANCE_LOG"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            session_order = parse_int(row.values.get("Session Order"))
            starts_at = parse_datetime(row.values.get("Date"))
            if not emp_code or not class_code or not course_name:
                continue
            key = (emp_code, class_code, course_name)
            summary = attendance.setdefault(key, {"first_date": None, "last_date": None, "first_session": None})
            if starts_at:
                summary["first_date"] = min(filter(None, (summary["first_date"], starts_at)))
                summary["last_date"] = max(filter(None, (summary["last_date"], starts_at)))
            if session_order:
                summary["first_session"] = min(filter(None, (summary["first_session"], session_order)))

        by_employee: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.rows("sheet2"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            if not emp_code or not class_code or not course_name:
                continue
            summary = attendance.get((emp_code, class_code, course_name), {})
            by_employee[emp_code].append(
                {
                    "row": row,
                    "class_code": class_code,
                    "course_name": course_name,
                    "first_date": summary.get("first_date"),
                    "last_date": summary.get("last_date"),
                    "first_session": summary.get("first_session"),
                    "start_date": parse_datetime(row.values.get("start date")),
                }
            )

        review: dict[int, dict[str, Any]] = {}
        for rows in by_employee.values():
            ordered = sorted(
                rows,
                key=lambda item: (
                    item["first_date"] or item["start_date"] or datetime.max,
                    item["class_code"],
                    item["course_name"],
                ),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if previous["class_code"] == current["class_code"]:
                    continue
                same_course = previous["course_name"] == current["course_name"]
                midrun = bool(current["first_session"] and current["first_session"] > 1)
                if not same_course and not midrun:
                    continue
                gap_days = None
                if previous["last_date"] and current["first_date"]:
                    gap_days = (current["first_date"].date() - previous["last_date"].date()).days
                max_gap = int(self.remediation.get("infer_transfer_max_gap_days", 0))
                inferred_transfer = bool(
                    same_course and midrun and gap_days is not None and 0 <= gap_days <= max_gap
                )
                review[current["row"].raw_row_id] = {
                    "from_class": previous["class_code"],
                    "from_course": previous["course_name"],
                    "from_last_attendance": previous["last_date"].isoformat() if previous["last_date"] else None,
                    "to_class": current["class_code"],
                    "to_course": current["course_name"],
                    "to_first_attendance": current["first_date"].isoformat() if current["first_date"] else None,
                    "to_first_session": current["first_session"],
                    "same_course": same_course,
                    "midrun": midrun,
                    "gap_days": gap_days,
                    "inferred_transfer": inferred_transfer,
                }
        return review

    def load_memberships_and_enrollments(self) -> None:
        first_sessions = self.attendance_first_session_map()
        transfer_review = self.transfer_review_by_row()
        # The workbook has no explicit current-enrollment flag.  Preserve every
        # historic enrollment, but make only the latest observed row per learner
        # active.  This is required by the P11 source-of-truth invariant and is
        # deterministic from attendance/start-date evidence rather than row order.
        first_dates: dict[tuple[str, str, str], datetime] = {}
        for attendance_row in self.rows("sheet1"):
            key = (
                clean_emp_code(attendance_row.values.get("Emp Code")),
                clean_code(attendance_row.values.get("Class Code")),
                clean_text(attendance_row.values.get("Course Name")),
            )
            observed_at = parse_datetime(attendance_row.values.get("Date"))
            if all(key) and observed_at:
                first_dates[key] = max(first_dates.get(key, observed_at), observed_at)
        latest_by_employee: dict[str, tuple[datetime, int]] = {}
        for enrollment_row in self.rows("sheet2"):
            emp_code = clean_emp_code(enrollment_row.values.get("Emp Code"))
            class_code = clean_code(enrollment_row.values.get("Class Code"))
            course_name = clean_text(enrollment_row.values.get("Course Name"))
            if not emp_code or not class_code or not course_name:
                continue
            observed_at = first_dates.get((emp_code, class_code, course_name)) or parse_datetime(enrollment_row.values.get("start date")) or datetime.min
            candidate = (observed_at, enrollment_row.raw_row_id)
            if emp_code not in latest_by_employee or candidate > latest_by_employee[emp_code]:
                latest_by_employee[emp_code] = candidate
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
            start_session_number = first_sessions.get((emp_code, class_code, course_name), 1)
            is_current = latest_by_employee.get(emp_code, (None, None))[1] == row.raw_row_id
            membership_status = "active" if is_current else "completed"
            enrollment_status = "active" if is_current else "completed"
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohort_memberships (cohort_id, employee_id, start_date, status)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (employee_id, cohort_id, start_date) DO UPDATE
                    SET status = CASE WHEN EXCLUDED.status = 'active' THEN 'active' ELSE cohort_memberships.status END
                    """,
                    (cohort_id, employee_id, joined_at, membership_status),
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
                        business_unit_id_snapshot, job_role_id_snapshot,
                        start_session_number, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (course_run_id, employee_id) DO NOTHING
                    RETURNING run_enrollment_id
                    """,
                    (course_run_id, employee_id, membership_id, bu_id, role_id, start_session_number, enrollment_status),
                )
                inserted = cur.fetchone()
            if inserted:
                self.stats["run_enrollments.inserted"] += 1
            self.outcome(row, "loaded", "run_enrollment_loaded", "run_enrollments", f"{emp_code}:{class_code}:{course_name}")
            transfer = transfer_review.get(row.raw_row_id)
            if transfer:
                if transfer["inferred_transfer"]:
                    from_enrollment_id = self.run_enrollment_id(
                        transfer["from_class"], transfer["from_course"], emp_code
                    )
                    to_enrollment_id = self.run_enrollment_id(class_code, course_name, emp_code)
                    if from_enrollment_id and to_enrollment_id:
                        with self.conn.cursor() as cur:
                            cur.execute(
                                "UPDATE run_enrollments SET transfer_from_enrollment_id = %s WHERE run_enrollment_id = %s",
                                (from_enrollment_id, to_enrollment_id),
                            )
                        self.outcome(
                            row,
                            "loaded",
                            "transfer_inferred_from_timeline",
                            "run_enrollments",
                            f"{emp_code}:{class_code}:{course_name}",
                            transfer,
                        )
                        self.stats["transfers.inferred"] += 1
                else:
                    self.ignored(row, "transfer_not_inferred_from_timeline", transfer)
            self.load_evaluation(row, course_run_id, employee_id)

    def load_attendance_derived_enrollments(self) -> None:
        if not self.remediation.get("derive_enrollments_from_attendance"):
            return
        candidates: dict[tuple[str, str, str], list[RawRow]] = defaultdict(list)
        first_session: dict[tuple[str, str, str], int] = {}
        for row in self.rows("ATTENDANCE_LOG"):
            emp_code = clean_emp_code(row.values.get("Emp Code"))
            class_code = clean_code(row.values.get("Class Code"))
            course_name = clean_text(row.values.get("Course Name"))
            session_order = parse_int(row.values.get("Session Order"))
            status = clean_text(row.values.get("Status"))
            if not emp_code or not class_code or not course_name or not session_order or status not in {"Present", "Absent"}:
                continue
            key = (emp_code, class_code, course_name)
            candidates[key].append(row)
            first_session[key] = min(first_session.get(key, session_order), session_order)

        for (emp_code, class_code, course_name), source_rows in sorted(candidates.items()):
            if self.run_enrollment_id(class_code, course_name, emp_code):
                continue
            employee_id = self.employee_id(emp_code)
            cohort_id = self.cohort_id(class_code)
            course_run_id = self.course_run_id(class_code, course_name)
            if not employee_id or not cohort_id or not course_run_id:
                continue
            membership_id = self.membership_id(employee_id, cohort_id)
            # Attendance-only candidates have no enrollment source row from
            # which to infer current status.  If another source-backed active
            # enrollment exists, retain this as historic rather than violating
            # the one-active-course invariant.
            active_exists = self.scalar_id(
                "SELECT run_enrollment_id FROM run_enrollments WHERE employee_id=%s AND status='active' LIMIT 1",
                (employee_id,),
            )
            enrollment_status = "completed" if active_exists else "active"
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_enrollments (
                        course_run_id, employee_id, cohort_membership_id, start_session_number, status
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (course_run_id, employee_id) DO NOTHING
                    RETURNING run_enrollment_id
                    """,
                    (course_run_id, employee_id, membership_id, first_session[(emp_code, class_code, course_name)], enrollment_status),
                )
                inserted = cur.fetchone()
            if not inserted:
                continue
            self.stats["run_enrollments.attendance_derived"] += 1
            self.stats["run_enrollments.inserted"] += 1
            for row in source_rows:
                self.outcome(
                    row,
                    "loaded",
                    "attendance_derived_enrollment",
                    "run_enrollments",
                    f"{emp_code}:{class_code}:{course_name}",
                    {"start_session_number": first_session[(emp_code, class_code, course_name)], "enrollment_status": enrollment_status},
                )

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

        meeting_unit_numbers: dict[tuple[int, datetime, int], int] = {}
        sessions_by_meeting: dict[tuple[int, datetime], list[int]] = defaultdict(list)
        for (class_code, course_name, session_order), dates in groups.items():
            course_run_id = self.course_run_id(class_code, course_name)
            if not course_run_id:
                continue
            for starts_at in dates:
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
            course_run_id = self.course_run_id(class_code, course_name)
            if not course_run_id:
                continue
            for starts_at in dates:
                if (course_run_id, starts_at) in overfull_meetings:
                    continue
                unit_number = meeting_unit_numbers.get((course_run_id, starts_at, session_order))
                if not unit_number:
                    continue
                existing_session_unit_id = self.scalar_id(
                    """
                    SELECT su.session_unit_id
                    FROM session_units su
                    JOIN meetings m ON m.meeting_id = su.meeting_id
                    WHERE su.course_run_id = %s
                      AND su.sequence_in_run = %s
                      AND m.starts_at = %s
                    """,
                    (course_run_id, session_order, starts_at),
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
                        ON CONFLICT (course_run_id, sequence_in_run, meeting_id)
                        DO UPDATE SET unit_number_in_meeting = EXCLUDED.unit_number_in_meeting
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
            if not session_order:
                self.issue(row, "conflicting_session_structure", "attendance", entity_key, {"session_order": session_order})
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
        self.maybe_fail("levels")
        self.load_courses()
        self.maybe_fail("courses")
        self.load_employees()
        self.maybe_fail("employees")
        self.load_org_history()
        self.maybe_fail("org_history")
        self.load_placements()
        self.maybe_fail("placements")
        self.load_cohorts()
        self.mark_cohort_source_outcomes()
        self.load_pic_assignments()
        self.maybe_fail("cohorts")
        self.load_course_runs()
        self.mark_course_run_source_outcomes()
        self.maybe_fail("course_runs")
        self.load_memberships_and_enrollments()
        self.load_attendance_derived_enrollments()
        self.maybe_fail("enrollments")
        self.load_schedule_and_attendance()
        self.maybe_fail("attendance")
        return self.stats


def get_staging_batch(conn) -> tuple[int, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT import_batch_id, source_checksum
            FROM import_batches
            WHERE status = 'completed'
            ORDER BY completed_at DESC, import_batch_id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("No completed staging import batch found. Run stage_workbook.py first.")
        return row[0], row[1]


def load_remediation(source_checksum: str, path: Path = DEFAULT_REMEDIATION_PATH) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    raw = path.read_bytes()
    remediation = json.loads(raw.decode("utf-8"))
    configured_checksum = remediation.get("source_checksum")
    if not configured_checksum:
        raise RuntimeError("Remediation manifest must declare source_checksum")
    if configured_checksum != source_checksum:
        return {}, None
    return remediation, hashlib.sha256(raw).hexdigest()


def completed_batch_stats(conn, source_checksum: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT canonical_etl_batch_id, stats
            FROM canonical_etl_batches
            WHERE source_checksum = %s AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (source_checksum,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_running_batch(conn, import_batch_id: int, source_checksum: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO canonical_etl_batches (import_batch_id, source_checksum, status)
            VALUES (%s, %s, 'running')
            RETURNING canonical_etl_batch_id
            """,
            (import_batch_id, source_checksum),
        )
        return cur.fetchone()[0]


def mark_batch_completed(conn, batch_id: int, stats: Counter[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE canonical_etl_batches
            SET status = 'completed',
                stats = %s,
                completed_at = NOW()
            WHERE canonical_etl_batch_id = %s
            """,
            (psycopg2.extras.Json(dict(sorted(stats.items()))), batch_id),
        )


def record_failed_batch(database_url: str, import_batch_id: int, source_checksum: str, error: BaseException) -> None:
    details = {
        "error_type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc(limit=12),
    }
    with psycopg2.connect(database_url) as failure_conn:
        with failure_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO canonical_etl_batches (
                    import_batch_id, source_checksum, status, failure_details, failed_at
                )
                VALUES (%s, %s, 'failed', %s, NOW())
                """,
                (import_batch_id, source_checksum, psycopg2.extras.Json(details)),
            )


def run_canonical_etl(database_url: str, fail_after_step: str | None = None, force: bool = False) -> dict[str, Any]:
    with psycopg2.connect(database_url) as conn:
        import_batch_id, source_checksum = get_staging_batch(conn)
        remediation, remediation_checksum = load_remediation(source_checksum)
        existing = completed_batch_stats(conn, source_checksum)
        if existing and not force and not fail_after_step:
            return {
                "status": "already_completed",
                "canonical_etl_batch_id": existing["canonical_etl_batch_id"],
                "stats": existing["stats"],
            }

    try:
        with psycopg2.connect(database_url) as conn:
            batch_id = create_running_batch(conn, import_batch_id, source_checksum)
            loader = CanonicalLoader(
                conn,
                active_import_batch_id=import_batch_id,
                fail_after_step=fail_after_step,
                remediation=remediation,
            )
            stats = loader.run()
            if remediation_checksum:
                stats["remediation.manifest_applied"] = 1
            mark_batch_completed(conn, batch_id, stats)
            return {
                "status": "completed",
                "canonical_etl_batch_id": batch_id,
                "stats": dict(sorted(stats.items())),
                "remediation_checksum": remediation_checksum,
            }
    except BaseException as error:
        record_failed_batch(database_url, import_batch_id, source_checksum, error)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database_url")
    parser.add_argument("--force", action="store_true", help="Run again even if this checksum already has a completed canonical ETL batch.")
    parser.add_argument("--fail-after-step", choices=[
        "levels",
        "courses",
        "employees",
        "org_history",
        "placements",
        "cohorts",
        "course_runs",
        "enrollments",
        "attendance",
    ])
    args = parser.parse_args()
    result = run_canonical_etl(args.database_url, fail_after_step=args.fail_after_step, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
