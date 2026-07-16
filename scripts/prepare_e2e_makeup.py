"""Add one deterministic make-up target to the disposable browser-test data."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import BusinessService


def main() -> None:
    # Browser fixtures must never follow APP_DATABASE_URL: that variable can
    # legitimately point at the local production database. Keep this script on
    # the dedicated disposable database unless an explicit E2E URL is supplied.
    database_url = os.getenv(
        "ENGLISH_CLASS_E2E_DATABASE_URL",
        "postgresql://postgres@localhost:5432/english_class_pytest",
    )
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT cr.course_run_id,COALESCE(MAX(su.sequence_in_run),0)+1
                   FROM course_runs cr
                   JOIN cohorts cohort ON cohort.cohort_id=cr.cohort_id
                   JOIN courses course ON course.course_id=cr.course_id
                   LEFT JOIN session_units su ON su.course_run_id=cr.course_run_id
                   WHERE cr.status IN ('planned','active')
                   GROUP BY cr.course_run_id,cohort.class_code,course.course_name,cr.run_number
                   ORDER BY lower(cohort.class_code),lower(course.course_name),cr.run_number,cr.course_run_id
                   LIMIT 1"""
            )
            target = cursor.fetchone()
            cursor.execute("SELECT user_id FROM app_users WHERE username='pytest_admin'")
            actor = cursor.fetchone()
        if not target or not actor:
            raise RuntimeError("browser-test course run or admin fixture is missing")
        BusinessService(connection, actor[0]).create_meeting_with_units(
            target[0],
            datetime(2030, 9, 8, 9, 0, tzinfo=timezone.utc),
            60,
            target[1],
            unit_type="makeup",
            status="planned",
        )
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO data_quality_issues(
                           issue_code,entity_type,entity_key,source_sheet,source_row_number,details
                       )
                       SELECT 'playwright_followup','employee','browser-fixture','E2E',1,
                              '{"source":"browser-fixture"}'::jsonb
                       WHERE NOT EXISTS (
                         SELECT 1 FROM data_quality_issues
                         WHERE issue_code='playwright_followup' AND status='open'
                       )"""
                )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
