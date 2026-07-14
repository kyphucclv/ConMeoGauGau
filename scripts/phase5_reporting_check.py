"""Phase 5 reporting/KPI integration gate."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import apply_migrations
from scripts.phase4_integration_check import _database_url, recreate_database
from services import BusinessService


DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_TEST_DB = "english_class_p5_test"


def seed(conn) -> dict[str, int]:
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_users(username, password_hash, full_name, role)
                VALUES ('phase5_admin', 'x', 'Phase 5 Admin', 'admin'),
                       ('phase5_editor', 'x', 'Phase 5 Editor', 'editor')
                RETURNING user_id, username
                """
            )
            ids = {username: user_id for user_id, username in cur.fetchall()}
            cur.execute("INSERT INTO business_units(business_unit_name) VALUES('Sales'), ('Ops') RETURNING business_unit_id, business_unit_name")
            ids.update({f"bu_{name.lower()}": row_id for row_id, name in cur.fetchall()})
            cur.execute("INSERT INTO job_roles(job_role_name) VALUES('Agent'), ('Lead') RETURNING job_role_id, job_role_name")
            ids.update({f"role_{name.lower()}": row_id for row_id, name in cur.fetchall()})
            cur.execute(
                """
                INSERT INTO courses(course_code, course_name, expected_units, attendance_threshold_ratio)
                VALUES ('RPT-A', 'Reporting Course A', 4, 0.750),
                       ('RPT-B', 'Reporting Course B', 3, 0.500)
                RETURNING course_id, course_code
                """
            )
            ids.update({f"course_{code[-1].lower()}": row_id for row_id, code in cur.fetchall()})
            cur.execute(
                """
                INSERT INTO levels(level_name, numeric_value, sequence_order)
                VALUES ('Entrance', 1.0, 1),
                       ('Middle', 2.0, 2),
                       ('Peak', 3.0, 3)
                RETURNING level_id, level_name
                """
            )
            ids.update({f"level_{name.lower()}": row_id for row_id, name in cur.fetchall()})
    return ids


def one(conn, sql: str, params: tuple = ()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def all_rows(conn, sql: str, params: tuple = ()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def run_fixture(database_url: str) -> dict[str, object]:
    conn = psycopg2.connect(database_url)
    try:
        ids = seed(conn)
        editor = BusinessService(conn, ids["phase5_editor"])
        admin = BusinessService(conn, ids["phase5_admin"])

        learner = editor.create_or_update_employee(
            "RPT-001",
            "Reporting Learner",
            employment_status="active",
            business_unit_id=ids["bu_sales"],
            job_role_id=ids["role_agent"],
            valid_from=date(2026, 1, 1),
        ).entity_id
        midrun = editor.create_or_update_employee(
            "RPT-002",
            "Midrun Learner",
            employment_status="active",
            business_unit_id=ids["bu_sales"],
            job_role_id=ids["role_agent"],
            valid_from=date(2026, 1, 1),
        ).entity_id
        transfer = editor.create_or_update_employee(
            "RPT-003",
            "Transfer Learner",
            employment_status="active",
            business_unit_id=ids["bu_sales"],
            job_role_id=ids["role_agent"],
            valid_from=date(2026, 1, 1),
        ).entity_id
        pic = editor.create_or_update_employee("RPT-PIC", "Reporting PIC", employment_status="active").entity_id

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO placements(employee_id, placement_kind, test_date, level_id) VALUES(%s, 'business', %s, %s)",
                    (learner, date(2026, 1, 1), ids["level_entrance"]),
                )

        cohort_a = editor.create_cohort("RPT-A", "Reporting Cohort A").entity_id
        cohort_b = editor.create_cohort("RPT-B", "Reporting Cohort B").entity_id
        editor.assign_pic(cohort_a, pic, date(2026, 1, 1))
        membership = editor.add_membership(cohort_a, learner, date(2026, 1, 1)).entity_id
        midrun_membership = editor.add_membership(cohort_a, midrun, date(2026, 1, 1)).entity_id
        transfer_membership = editor.add_membership(cohort_a, transfer, date(2026, 1, 1)).entity_id

        run_a = editor.create_course_run(cohort_a, ids["course_a"], start_date=date(2026, 1, 5)).entity_id
        run_b = editor.create_course_run(cohort_b, ids["course_b"], start_date=date(2026, 2, 1)).entity_id
        enrollment = editor.enroll(run_a, learner, membership, start_session_number=1).entity_id
        midrun_enrollment = editor.enroll(run_a, midrun, midrun_membership, start_session_number=2).entity_id
        transfer_enrollment = editor.enroll(run_a, transfer, transfer_membership, start_session_number=1).entity_id
        moved_enrollment = editor.transfer_learner(
            transfer_enrollment,
            run_b,
            date(2026, 2, 1),
            confirmed_start_session_number=1,
        ).entity_id

        meeting_1 = editor.save_meeting(run_a, datetime(2026, 1, 7, 9, 0, tzinfo=timezone.utc), 120, status="completed").entity_id
        meeting_cancelled = editor.save_meeting(run_a, datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc), 120).entity_id
        editor.cancel_meeting(meeting_cancelled, "cancelled fixture")
        meeting_final = editor.save_meeting(run_a, datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc), 180, status="completed").entity_id
        meeting_makeup = editor.save_meeting(run_a, datetime(2026, 1, 28, 9, 0, tzinfo=timezone.utc), 60, status="completed").entity_id

        unit_1 = editor.add_session_unit(run_a, meeting_1, 1, unit_number_in_meeting=1).entity_id
        unit_2 = editor.add_session_unit(run_a, meeting_1, 2, unit_number_in_meeting=2).entity_id
        alternate_meeting = editor.save_meeting(
            run_a,
            datetime(2026, 1, 8, 9, 0, tzinfo=timezone.utc),
            60,
            status="completed",
        ).entity_id
        editor.add_session_unit(run_a, alternate_meeting, 2, unit_number_in_meeting=1)
        cancelled_unit = editor.add_session_unit(run_a, meeting_cancelled, 3, unit_number_in_meeting=1).entity_id
        final_unit = editor.add_session_unit(run_a, meeting_final, 4, unit_number_in_meeting=1, unit_type="final_test").entity_id
        makeup_unit = editor.add_session_unit(run_a, meeting_makeup, 5, unit_number_in_meeting=1, unit_type="makeup").entity_id

        attendance = editor.bulk_record_attendance(
            [
                {"run_enrollment_id": enrollment, "session_unit_id": unit_1, "effective_status": "Present"},
                {"run_enrollment_id": enrollment, "session_unit_id": unit_2, "effective_status": "Absent"},
                {"run_enrollment_id": enrollment, "session_unit_id": cancelled_unit, "effective_status": "Absent"},
                {"run_enrollment_id": enrollment, "session_unit_id": final_unit, "effective_status": "Present"},
                {"run_enrollment_id": midrun_enrollment, "session_unit_id": unit_2, "effective_status": "Present"},
            ]
        )
        editor.correct_attendance_makeup(attendance.values["attendance_ids"][1], makeup_unit, "reported make-up")

        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO evaluations(run_enrollment_id) VALUES(%s) RETURNING evaluation_id", (enrollment,))
                evaluation_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO evaluation_versions(
                        evaluation_id, version_number, final_level_id, exam_eligible,
                        passed, next_course_id, teacher_notes, correction_reason,
                        created_by_user_id, created_at
                    )
                    VALUES
                        (%s, 1, %s, TRUE, TRUE, %s, 'initial peak', NULL, %s, %s),
                        (%s, 2, %s, TRUE, TRUE, %s, 'corrected lower', 'teacher correction', %s, %s)
                    """,
                    (
                        evaluation_id,
                        ids["level_peak"],
                        ids["course_b"],
                        ids["phase5_editor"],
                        datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
                        evaluation_id,
                        ids["level_middle"],
                        ids["course_b"],
                        ids["phase5_editor"],
                        datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc),
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO source_workbooks(source_name, source_checksum, file_size_bytes)
                    VALUES('phase5.xlsx', repeat('a', 64), 1)
                    RETURNING source_workbook_id
                    """,
                )
                source_workbook_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO import_batches(source_name, source_checksum, status, completed_at)
                    VALUES('phase5.xlsx', repeat('a', 64), 'completed', NOW())
                    RETURNING import_batch_id
                    """
                )
                import_batch_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO raw_workbook_rows(
                        import_batch_id, source_workbook_id, source_name, source_checksum,
                        sheet_name, source_row_number, row_hash, raw_payload
                    )
                    VALUES(%s, %s, 'phase5.xlsx', repeat('a', 64), 'ATTENDANCE_LOG', 42, repeat('b', 64), '{}'::jsonb)
                    RETURNING raw_row_id
                    """,
                    (import_batch_id, source_workbook_id),
                )
                raw_row_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO data_quality_issues(
                        import_batch_id, issue_code, entity_type, entity_key,
                        source_sheet, source_row_number, details
                    )
                    VALUES(%s, 'run_boundary_unresolved', 'course_run', 'RPT-A', 'ATTENDANCE_LOG', 42, %s)
                    """,
                    (import_batch_id, psycopg2.extras.Json({"fixture": True})),
                )
                cur.execute(
                    """
                    INSERT INTO etl_source_row_outcomes(
                        import_batch_id, raw_row_id, source_sheet, source_row_number,
                        outcome_type, outcome_code, target_entity, target_key, details
                    )
                    VALUES(%s, %s, 'ATTENDANCE_LOG', 42, 'issue',
                           'run_boundary_unresolved', 'course_run', 'RPT-A', %s)
                    """,
                    (import_batch_id, raw_row_id, psycopg2.extras.Json({"fixture": True})),
                )

        admin.suggest_completion(enrollment)

        attendance_row = one(conn, "SELECT * FROM v_run_enrollment_attendance WHERE run_enrollment_id = %s", (enrollment,))
        assert attendance_row["applicable_units"] == 3
        assert attendance_row["present_units"] == 3
        assert attendance_row["makeup_present_units"] == 1
        assert str(attendance_row["attendance_ratio"]) == "1.0000"
        assert attendance_row["effective_exam_eligible"] is True

        midrun_row = one(conn, "SELECT * FROM v_run_enrollment_attendance WHERE run_enrollment_id = %s", (midrun_enrollment,))
        assert midrun_row["applicable_units"] == 2
        assert midrun_row["present_units"] == 1
        assert midrun_row["effective_exam_eligible"] is False

        monthly = one(conn, "SELECT * FROM v_monthly_session_units WHERE course_run_id = %s", (run_a,))
        assert monthly["credited_session_units"] == 4
        assert monthly["final_test_units"] == 1
        assert monthly["final_test_duration_minutes"] == 180

        progress = one(conn, "SELECT * FROM v_employee_progress_summary WHERE employee_id = %s", (learner,))
        assert progress["current_level_name"] == "Middle"
        assert progress["highest_level_name"] == "Peak"
        assert progress["regression_flag"] is True

        snapshot = one(conn, "SELECT * FROM v_historical_enrollment_snapshot WHERE run_enrollment_id = %s", (moved_enrollment,))
        assert snapshot["transfer_from_enrollment_id"] == transfer_enrollment
        assert snapshot["enrollment_business_unit"] == "Sales"

        dashboard = one(conn, "SELECT * FROM v_cohort_course_run_dashboard WHERE course_run_id = %s", (run_a,))
        assert dashboard["enrollment_count"] == 3
        assert dashboard["cancelled_meetings"] == 1
        assert dashboard["non_cancelled_units"] == 4

        unresolved = all_rows(conn, "SELECT * FROM v_unresolved_quality_issues")
        assert len(unresolved) == 1
        assert unresolved[0]["issue_code"] == "run_boundary_unresolved"
        assert unresolved[0]["source"] == "data_quality_issue"

        definitions = all_rows(conn, "SELECT metric_key FROM v_reporting_metric_definitions")
        definition_keys = {row["metric_key"] for row in definitions}
        assert {"attendance_ratio", "sessions_per_month", "regression_flag"}.issubset(definition_keys)

        trace_rows = {
            "attendance_ratio_trace": dict(attendance_row),
            "monthly_session_trace": dict(monthly),
            "progress_trace": dict(progress),
        }
        return {
            "attendance_ratio": str(attendance_row["attendance_ratio"]),
            "midrun_applicable_units": midrun_row["applicable_units"],
            "credited_session_units": monthly["credited_session_units"],
            "final_test_units_not_inflated": monthly["final_test_units"],
            "regression_flag": progress["regression_flag"],
            "unresolved_quality_issues": len(unresolved),
            "trace_rows": trace_rows,
        }
    finally:
        conn.close()


def main() -> None:
    db_name = os.getenv("PHASE5_TEST_DB", DEFAULT_TEST_DB)
    maintenance_url = os.getenv("PHASE5_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    database_url = os.getenv("PHASE5_DATABASE_URL", _database_url(db_name, maintenance_url))

    recreate_database(maintenance_url, db_name)
    apply_migrations(database_url)
    result = run_fixture(database_url)
    print("Phase 5 reporting gate passed.")
    for key, value in result.items():
        if key != "trace_rows":
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
