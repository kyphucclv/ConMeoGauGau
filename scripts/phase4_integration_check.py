"""Phase 4 PostgreSQL integration gate.

This script creates a disposable database, applies all migrations, seeds the
minimum reference data, exercises the Phase 4 service commands, and verifies a
forced command failure rolls back earlier writes in the same transaction.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from queue import Queue
from urllib.parse import quote, urlparse, urlunparse

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import apply_migrations
from services import BusinessService, CommandError


DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_TEST_DB = "english_class_p4_test"


def _pgpass_password(host: str, port: str, database: str, user: str) -> str | None:
    pgpass = Path(os.environ.get("PGPASSFILE", Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"))
    if not pgpass.exists():
        return None
    for line in pgpass.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 5:
            continue
        entry_host, entry_port, entry_database, entry_user = parts[:4]
        password = ":".join(parts[4:])
        if (
            entry_host in {"*", host}
            and entry_port in {"*", port}
            and entry_database in {"*", database}
            and entry_user in {"*", user}
        ):
            return password
    return None


def _database_url(db_name: str, maintenance_url: str) -> str:
    parsed = urlparse(maintenance_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or _pgpass_password(host, port, parsed.path.lstrip("/") or "postgres", user)
    auth = quote(user)
    if password:
        auth = f"{auth}:{quote(password)}"
    return urlunparse((parsed.scheme or "postgresql", f"{auth}@{host}:{port}", f"/{db_name}", "", "", ""))


def recreate_database(maintenance_url: str, db_name: str) -> None:
    conn = psycopg2.connect(maintenance_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
            cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
            cur.execute(f"CREATE DATABASE {db_name}")
    finally:
        conn.close()


def seed_reference_data(conn) -> dict[str, int]:
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_users(username, password_hash, full_name, role)
                VALUES
                    ('phase4_admin', 'x', 'Phase 4 Admin', 'admin'),
                    ('phase4_editor', 'x', 'Phase 4 Editor', 'editor'),
                    ('phase4_viewer', 'x', 'Phase 4 Viewer', 'viewer')
                RETURNING user_id, username
                """
            )
            users = {username: user_id for user_id, username in cur.fetchall()}
            cur.execute(
                "INSERT INTO business_units(business_unit_name) VALUES('Phase 4 BU') RETURNING business_unit_id"
            )
            business_unit_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO job_roles(job_role_name) VALUES('Phase 4 Role') RETURNING job_role_id"
            )
            job_role_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO courses(course_code, course_name, expected_units, attendance_threshold_ratio)
                VALUES
                    ('P4-A', 'Phase 4 Course A', 2, 0.500),
                    ('P4-B', 'Phase 4 Course B', 2, 0.500)
                RETURNING course_id, course_code
                """
            )
            courses = {code: course_id for course_id, code in cur.fetchall()}
            cur.execute(
                """
                INSERT INTO levels(level_name, numeric_value, sequence_order)
                VALUES('Phase 4 Level', 3.0, 1)
                RETURNING level_id
                """
            )
            level_id = cur.fetchone()[0]
    return {
        **users,
        "business_unit_id": business_unit_id,
        "job_role_id": job_role_id,
        "course_a_id": courses["P4-A"],
        "course_b_id": courses["P4-B"],
        "level_id": level_id,
    }


def expect_command_error(code: str, fn) -> None:
    try:
        fn()
    except CommandError as exc:
        if exc.code != code:
            raise AssertionError(f"expected CommandError {code}, got {exc.code}") from exc
        return
    raise AssertionError(f"expected CommandError {code}")


def count_rows(conn, table: str, where: str, params: tuple) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where}", params)
        return cur.fetchone()[0]


def run_gate(database_url: str) -> dict[str, object]:
    conn = psycopg2.connect(database_url)
    try:
        ids = seed_reference_data(conn)
        admin = BusinessService(conn, ids["phase4_admin"])
        editor = BusinessService(conn, ids["phase4_editor"])
        viewer = BusinessService(conn, ids["phase4_viewer"])

        pic = editor.create_or_update_employee(
            "P4-PIC",
            "Phase Four PIC",
            employment_status="active",
            business_unit_id=ids["business_unit_id"],
            job_role_id=ids["job_role_id"],
            valid_from=date(2026, 1, 1),
        ).entity_id
        student = editor.create_or_update_employee(
            "P4-STUDENT",
            "Phase Four Student",
            employment_status="active",
            business_unit_id=ids["business_unit_id"],
            job_role_id=ids["job_role_id"],
            valid_from=date(2026, 1, 1),
        ).entity_id
        transfer_student = editor.create_or_update_employee(
            "P4-TRANSFER",
            "Phase Four Transfer",
            employment_status="active",
            business_unit_id=ids["business_unit_id"],
            job_role_id=ids["job_role_id"],
            valid_from=date(2026, 1, 1),
        ).entity_id

        cohort = editor.create_cohort("P4-COHORT", "Phase 4 Cohort").entity_id
        target_cohort = editor.create_cohort("P4-TARGET", "Phase 4 Target").entity_id
        editor.assign_pic(cohort, pic, date(2026, 1, 1))
        membership = editor.add_membership(cohort, student, date(2026, 1, 1)).entity_id
        transfer_membership = editor.add_membership(cohort, transfer_student, date(2026, 1, 1)).entity_id

        run = editor.create_course_run(cohort, ids["course_a_id"], start_date=date(2026, 1, 2))
        assert run.values["run_number"] == 1
        second_run = editor.create_course_run(cohort, ids["course_a_id"], start_date=date(2026, 2, 1))
        assert second_run.values["run_number"] == 2
        target_run = editor.create_course_run(target_cohort, ids["course_a_id"], start_date=date(2026, 3, 1))
        editor.change_course_run_status(run.entity_id, "active")
        expect_command_error("invalid_state", lambda: editor.change_course_run_status(run.entity_id, "planned"))
        concurrent_run_numbers = run_concurrent_course_run_check(database_url, ids["phase4_editor"], ids["course_b_id"])

        enrollment = editor.enroll(run.entity_id, student, membership).entity_id
        transfer_enrollment = editor.enroll(run.entity_id, transfer_student, transfer_membership, start_session_number=2).entity_id
        moved_enrollment = editor.transfer_learner(
            transfer_enrollment,
            target_run.entity_id,
            date(2026, 3, 15),
            confirmed_start_session_number=1,
        ).entity_id
        assert moved_enrollment != transfer_enrollment

        meeting = editor.save_meeting(
            run.entity_id,
            datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            120,
            status="completed",
        ).entity_id
        cancelled_meeting = editor.save_meeting(
            run.entity_id,
            datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc),
            120,
        ).entity_id
        editor.save_meeting(
            run.entity_id,
            datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc),
            90,
            meeting_id=cancelled_meeting,
        )
        editor.cancel_meeting(cancelled_meeting, "teacher unavailable")

        unit_1 = editor.add_session_unit(run.entity_id, meeting, 1, unit_number_in_meeting=1).entity_id
        unit_2 = editor.add_session_unit(run.entity_id, meeting, 2, unit_number_in_meeting=2).entity_id
        alternate_meeting = editor.save_meeting(
            run.entity_id,
            datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc),
            60,
            status="completed",
        ).entity_id
        editor.add_session_unit(run.entity_id, alternate_meeting, 1, unit_number_in_meeting=1)
        makeup_unit = editor.add_session_unit(
            run.entity_id,
            meeting,
            3,
            unit_number_in_meeting=3,
            unit_type="makeup",
        ).entity_id
        attendance = editor.bulk_record_attendance(
            [
                {"run_enrollment_id": enrollment, "session_unit_id": unit_1, "effective_status": "Present"},
                {"run_enrollment_id": enrollment, "session_unit_id": unit_2, "effective_status": "Absent"},
            ]
        )

        eligibility = viewer.calculate_exam_eligibility(enrollment)
        assert eligibility.values["applicable_units"] == 3
        assert eligibility.values["present_units"] == 1
        assert eligibility.values["exam_eligible"] is False
        editor.correct_attendance_makeup(attendance.values["attendance_ids"][1], makeup_unit, "valid make-up")
        admin.override_exam_eligibility(enrollment, True, "admin verification")

        evaluation = editor.record_evaluation(
            enrollment,
            final_level_id=ids["level_id"],
            passed=True,
            next_course_id=ids["course_b_id"],
            exam_eligible=True,
            teacher_notes="ready",
        )
        assert evaluation.values["version_number"] >= 1
        suggestion = editor.suggest_completion(enrollment)
        assert suggestion.values["suggested"] is True
        admin.confirm_completion(enrollment, True)

        transferred_membership = editor.transfer_membership(membership, target_cohort, date(2026, 4, 1))
        assert transferred_membership.values["from_membership_id"] == membership
        close_employee = editor.create_or_update_employee("P4-CLOSE", "Phase Four Close").entity_id
        close_membership = editor.add_membership(cohort, close_employee, date(2026, 5, 1)).entity_id
        closed = editor.close_membership(close_membership, date(2026, 5, 31))
        assert closed.values["status"] == "completed"

        expect_command_error(
            "not_found",
            lambda: editor.create_or_update_employee("P4-STUDENT", "Duplicate Student", business_unit_id=999999),
        )
        assert count_rows(conn, "employee_org_history", "business_unit_id = %s", (999999,)) == 0
        with conn.cursor() as cur:
            cur.execute("SELECT full_name FROM employees WHERE emp_code = 'P4-STUDENT'")
            assert cur.fetchone()[0] == "Phase Four Student"

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_events")
            audit_count = cur.fetchone()[0]
            cur.execute("SELECT status FROM run_enrollments WHERE run_enrollment_id = %s", (enrollment,))
            completed_status = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM course_completion_suggestions WHERE status = 'confirmed'")
            confirmed_suggestions = cur.fetchone()[0]

        assert audit_count >= 20
        assert completed_status == "completed"
        assert confirmed_suggestions == 1

        return {
            "audit_events": audit_count,
            "confirmed_suggestions": confirmed_suggestions,
            "completed_enrollment_id": enrollment,
            "transferred_enrollment_id": moved_enrollment,
            "transferred_membership_id": transferred_membership.entity_id,
            "concurrent_run_numbers": concurrent_run_numbers,
        }
    finally:
        conn.close()


def run_concurrent_course_run_check(database_url: str, actor_user_id: int, course_id: int) -> list[int]:
    setup_conn = psycopg2.connect(database_url)
    try:
        setup_service = BusinessService(setup_conn, actor_user_id)
        cohort_id = setup_service.create_cohort("P4-CONCURRENT", "Phase 4 Concurrent").entity_id
    finally:
        setup_conn.close()

    barrier = threading.Barrier(2)
    results: Queue[tuple[str, int | BaseException]] = Queue()

    def worker() -> None:
        worker_conn = psycopg2.connect(database_url)
        try:
            service = BusinessService(worker_conn, actor_user_id)
            barrier.wait()
            result = service.create_course_run(cohort_id, course_id, start_date=date(2026, 6, 1))
            results.put(("ok", result.values["run_number"]))
        except BaseException as exc:
            results.put(("error", exc))
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    run_numbers = []
    while not results.empty():
        status, value = results.get()
        if status == "error":
            raise AssertionError("concurrent course-run creation failed") from value
        run_numbers.append(value)

    assert sorted(run_numbers) == [1, 2]
    return sorted(run_numbers)


def main() -> None:
    db_name = os.getenv("PHASE4_TEST_DB", DEFAULT_TEST_DB)
    maintenance_url = os.getenv("PHASE4_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    database_url = os.getenv("PHASE4_DATABASE_URL", _database_url(db_name, maintenance_url))

    recreate_database(maintenance_url, db_name)
    apply_migrations(database_url)
    result = run_gate(database_url)
    print("Phase 4 integration gate passed.")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
