"""Validate documented canonical columns against the applied PostgreSQL schema."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://postgres@localhost:5432/english_class"
TABLES = (
    "attendance",
    "attendance_roster_legacy_exceptions",
    "audit_events",
    "app_sessions",
    "cohort_capacity_overrides",
    "cohort_memberships",
    "cohort_pic_assignments",
    "cohorts",
    "course_runs",
    "courses",
    "employee_org_history",
    "employees",
    "evaluation_versions",
    "evaluations",
    "levels",
    "meetings",
    "monthly_review_action_summary_versions",
    "placements",
    "run_enrollments",
    "session_units",
    "data_quality_issues",
)
LEGACY_FIELD_ALIASES = (
    "enrollment_id",
    "membership_id",
    "joined_at",
    "expected_session_units",
    "eligible_for_next_course",
    "evaluated_at",
    "change_reason",
    "created_by",
    "session_number",
    "sequence",
)


def documented_columns(text: str, table: str) -> list[str]:
    match = re.search(
        rf"`{re.escape(table)}` physical columns:\s*(.+?)\.",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing physical-column inventory for {table}")
    return re.findall(r"`([a-z][a-z0-9_]*)`", match.group(1))


def applied_columns(conn) -> dict[str, list[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, array_agg(column_name::text ORDER BY ordinal_position)
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name = ANY(%s)
            GROUP BY table_name
            """,
            (list(TABLES),),
        )
        return {table: columns for table, columns in cur.fetchall()}


def run_check(database_url: str) -> dict[str, int | str]:
    text = (ROOT / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    conn = psycopg2.connect(database_url)
    try:
        actual = applied_columns(conn)
        for table in TABLES:
            if table not in actual:
                raise AssertionError(f"applied schema is missing {table}")
            documented = documented_columns(text, table)
            if documented != actual[table]:
                raise AssertionError(
                    f"{table} dictionary drift: documented={documented}, applied={actual[table]}"
                )

        for alias in LEGACY_FIELD_ALIASES:
            if re.search(rf"`{re.escape(alias)}`", text):
                raise AssertionError(f"legacy physical field alias remains documented: {alias}")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=%s)",
                ("020_app_sessions",),
            )
            if not cur.fetchone()[0]:
                raise AssertionError("applied database has not reached migration 020")
        return {
            "tables_checked": len(TABLES),
            "legacy_aliases_checked": len(LEGACY_FIELD_ALIASES),
            "schema_baseline": "020_app_sessions",
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("MIGRATION_DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args()
    result = run_check(args.database_url)
    print("Phase 13 data dictionary check passed.")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
