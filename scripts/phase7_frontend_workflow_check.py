"""Phase 7 admin workflow gate.

The UI calls these same service commands; this script replays the monthly admin
workflow against PostgreSQL and validates the database rows that the UI should
surface after each major step.
"""

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

from auth import hash_password
from migrate import apply_migrations
from scripts.phase4_integration_check import _database_url, recreate_database
from services import BusinessService, CommandError


DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_TEST_DB = "english_class_p7_test"


def one(conn, sql: str, params: tuple = ()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def expect_command_error(code: str, fn) -> None:
    try:
        fn()
    except CommandError as exc:
        if exc.code != code:
            raise AssertionError(f"expected CommandError {code}, got {exc.code}") from exc
        return
    raise AssertionError(f"expected CommandError {code}")


def seed(conn) -> dict[str, int]:
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_users(username, password_hash, full_name, role)
                VALUES ('phase7_admin', %s, 'Phase 7 Admin', 'admin'),
                       ('phase7_editor', %s, 'Phase 7 Editor', 'editor')
                RETURNING user_id, username
                """,
                (hash_password("admin-pass"), hash_password("editor-pass")),
            )
            ids = {username: user_id for user_id, username in cur.fetchall()}
            cur.execute("INSERT INTO business_units(business_unit_name) VALUES('Phase 7 BU') RETURNING business_unit_id")
            ids["business_unit_id"] = cur.fetchone()[0]
            cur.execute("INSERT INTO job_roles(job_role_name) VALUES('Phase 7 Role') RETURNING job_role_id")
            ids["job_role_id"] = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO courses(course_code, course_name, expected_units, attendance_threshold_ratio)
                VALUES ('P7-A', 'Phase 7 Course A', 4, 0.750),
                       ('P7-B', 'Phase 7 Course B', 4, 0.750)
                RETURNING course_id, course_code
                """
            )
            ids.update({f"course_{code[-1].lower()}": course_id for course_id, code in cur.fetchall()})
            cur.execute(
                """
                INSERT INTO levels(level_name, numeric_value, sequence_order)
                VALUES ('P7 Entrance', 1.0, 1), ('P7 Current', 2.0, 2), ('P7 Highest', 3.0, 3)
                RETURNING level_id, level_name
                """
            )
            ids.update({name.lower().replace(" ", "_"): level_id for level_id, name in cur.fetchall()})
    return ids


def assert_static_ui_contract() -> None:
    files = ["streamlit_app.py", "frontend_workflows.py"]
    forbidden = ["st.exception", "Show SQL", "PostgreSQL connection string", "use_container_width"]
    for filename in files:
        text = (ROOT / filename).read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                raise AssertionError(f"{filename} contains forbidden UI pattern: {pattern}")
    if "BusinessService" not in (ROOT / "frontend_workflows.py").read_text(encoding="utf-8"):
        raise AssertionError("frontend workflows must call the service layer")
    workflow_text = (ROOT / "frontend_workflows.py").read_text(encoding="utf-8")
    required_patterns = [
        "on_select=\"rerun\"",
        "selection_mode=\"single-row\"",
        "create_class_course_run",
        "accept_new_options=True",
        "propose_next_attendance_session",
        "save_attendance_roster",
        "_attendance_session_summary",
        "_shift_review_month",
        "course_participation",
        "class_participation",
        "Delivery rate",
        "_operational_issue_rows",
        "issue_severity_filter",
        "operational_issue_grid",
        "JsonColumn",
    ]
    for pattern in required_patterns:
        if pattern not in workflow_text:
            raise AssertionError(f"frontend workflows missing P11.2 pattern: {pattern}")


def run_gate(database_url: str) -> dict[str, object]:
    conn = psycopg2.connect(database_url)
    try:
        ids = seed(conn)
        editor = BusinessService(conn, ids["phase7_editor"])
        admin = BusinessService(conn, ids["phase7_admin"])

        employee = editor.create_or_update_employee(
            "P7-001",
            "Phase Seven Learner",
            employment_status="active",
            business_unit_id=ids["business_unit_id"],
            job_role_id=ids["job_role_id"],
            valid_from=date(2026, 7, 1),
        ).entity_id
        pic = editor.create_or_update_employee("P7-PIC", "Phase Seven PIC", employment_status="active").entity_id
        employee_state = one(conn, "SELECT * FROM v_current_employee_state WHERE employee_id=%s", (employee,))
        assert employee_state["business_unit_name"] == "Phase 7 BU"

        cohort = editor.create_cohort("P7-COHORT", "Phase 7 Cohort", status="active").entity_id
        editor.assign_pic(cohort, pic, date(2026, 7, 1))
        label_assignment = editor.assign_pic(
            cohort,
            None,
            date(2026, 7, 2),
            pic_label="Phase Seven Team",
        )
        assert label_assignment.values["assignment_type"] == "label"
        pic_row = one(
            conn,
            "SELECT pic_employee_id, pic_label FROM cohort_pic_assignments WHERE cohort_id=%s AND end_date IS NULL",
            (cohort,),
        )
        assert pic_row["pic_employee_id"] is None
        assert pic_row["pic_label"] == "Phase Seven Team"
        proposed_code = editor.propose_next_class_code().values["class_code"]
        assert proposed_code == "EL001"
        created_run = editor.create_class_course_run(
            class_code=proposed_code,
            display_name="Phase 7 Created Class",
            course_id=ids["course_b"],
            start_date=date(2026, 7, 5),
            capacity=8,
            status="active",
            pic_label=" Phase   Seven   Team ",
        )
        created_class = one(
            conn,
            """
            SELECT c.class_code,c.capacity,c.status,cr.run_number,cr.status AS run_status,cpa.pic_label
            FROM course_runs cr
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN cohort_pic_assignments cpa ON cpa.cohort_id=c.cohort_id AND cpa.end_date IS NULL
            WHERE cr.course_run_id=%s
            """,
            (created_run.entity_id,),
        )
        assert created_class["class_code"] == "EL001"
        assert created_class["capacity"] == 8
        assert created_class["status"] == "active"
        assert created_class["run_number"] == 1
        assert created_class["run_status"] == "active"
        assert created_class["pic_label"] == "Phase Seven Team"
        assert "Phase Seven Team" in editor.pic_label_suggestions("seven").values["labels"]
        attendance_learner = editor.onboard_learner(
            emp_code="P7-ATT",
            full_name="Phase Seven Attendance",
            business_unit_id=ids["business_unit_id"],
            job_role_id=ids["job_role_id"],
            entrance_level_id=ids["p7_entrance"],
            course_run_id=created_run.entity_id,
            joined_on=date(2026, 7, 5),
        )
        next_session = editor.propose_next_attendance_session(created_run.entity_id).values["sequence_in_run"]
        assert next_session == 1
        attendance_session = editor.create_attendance_session(
            created_run.entity_id,
            datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
            60,
            next_session,
        )
        roster = editor.attendance_roster(created_run.entity_id, attendance_session.entity_id).values
        assert len(roster["rows"]) == 1
        assert roster["rows"][0]["effective_status"] == "Present"
        editor.save_attendance_roster(
            created_run.entity_id,
            attendance_session.entity_id,
            [{"run_enrollment_id": attendance_learner.entity_id, "effective_status": "Absent"}],
        )
        completed_session = one(
            conn,
            """SELECT m.status,a.effective_status
               FROM session_units su
               JOIN meetings m ON m.meeting_id=su.meeting_id
               JOIN attendance a ON a.session_unit_id=su.session_unit_id
               WHERE su.session_unit_id=%s""",
            (attendance_session.entity_id,),
        )
        assert completed_session["status"] == "completed"
        assert completed_session["effective_status"] == "Absent"
        expect_command_error(
            "invalid_state",
            lambda: editor.save_attendance_roster(created_run.entity_id, attendance_session.entity_id, []),
        )
        membership = editor.add_membership(cohort, employee, date(2026, 7, 1)).entity_id
        membership_row = one(conn, "SELECT status FROM cohort_memberships WHERE cohort_membership_id=%s", (membership,))
        assert membership_row["status"] == "active"

        run = editor.create_course_run(cohort, ids["course_a"], start_date=date(2026, 7, 2)).entity_id
        editor.change_course_run_status(run, "active")
        enrollment = editor.enroll(run, employee, membership, start_session_number=1).entity_id
        run_row = one(conn, "SELECT status FROM course_runs WHERE course_run_id=%s", (run,))
        assert run_row["status"] == "active"

        meeting = editor.save_meeting(
            run,
            datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),
            120,
            status="completed",
        ).entity_id
        cancelled = editor.save_meeting(run, datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc), 120).entity_id
        editor.cancel_meeting(cancelled, "admin workflow cancellation")
        unit_1 = editor.add_session_unit(run, meeting, 1, unit_number_in_meeting=1).entity_id
        unit_2 = editor.add_session_unit(run, meeting, 2, unit_number_in_meeting=2).entity_id
        cancelled_unit = editor.add_session_unit(run, cancelled, 3, unit_number_in_meeting=1).entity_id
        schedule_row = one(conn, "SELECT completed_meetings, cancelled_meetings, non_cancelled_units FROM v_cohort_course_run_dashboard WHERE course_run_id=%s", (run,))
        assert schedule_row["completed_meetings"] == 1
        assert schedule_row["cancelled_meetings"] == 1
        assert schedule_row["non_cancelled_units"] == 2

        attendance = editor.bulk_record_attendance(
            [
                {"run_enrollment_id": enrollment, "session_unit_id": unit_1, "effective_status": "Present"},
                {"run_enrollment_id": enrollment, "session_unit_id": unit_2, "effective_status": "Absent"},
                {"run_enrollment_id": enrollment, "session_unit_id": cancelled_unit, "effective_status": "Absent"},
            ]
        )
        makeup_meeting = editor.save_meeting(run, datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc), 60, status="completed").entity_id
        makeup_unit = editor.add_session_unit(run, makeup_meeting, 4, unit_number_in_meeting=1, unit_type="makeup").entity_id
        editor.correct_attendance_makeup(attendance.values["attendance_ids"][1], makeup_unit, "monthly workflow make-up")
        attendance_row = one(conn, "SELECT * FROM v_run_enrollment_attendance WHERE run_enrollment_id=%s", (enrollment,))
        assert attendance_row["applicable_units"] == 3
        assert attendance_row["present_units"] == 2
        assert attendance_row["calculated_exam_eligible"] is False

        admin.override_exam_eligibility(enrollment, True, "monthly workflow override")
        eligibility_row = one(conn, "SELECT effective_exam_eligible FROM v_run_enrollment_attendance WHERE run_enrollment_id=%s", (enrollment,))
        assert eligibility_row["effective_exam_eligible"] is True

        editor.record_evaluation(
            enrollment,
            final_level_id=ids["p7_current"],
            exam_eligible=True,
            passed=True,
            next_course_id=ids["course_b"],
            teacher_notes="monthly workflow evaluation",
        )
        editor.record_evaluation(
            enrollment,
            final_level_id=ids["p7_highest"],
            exam_eligible=True,
            passed=True,
            next_course_id=ids["course_b"],
            teacher_notes="transparent correction",
        )
        eval_history = one(conn, "SELECT count(*) AS total FROM evaluation_versions ev JOIN evaluations e ON e.evaluation_id=ev.evaluation_id WHERE e.run_enrollment_id=%s", (enrollment,))
        assert eval_history["total"] == 3

        suggestion = editor.suggest_completion(enrollment)
        assert suggestion.values["suggested"] is True
        admin.confirm_completion(enrollment, True)
        completed = one(conn, "SELECT status FROM run_enrollments WHERE run_enrollment_id=%s", (enrollment,))
        assert completed["status"] == "completed"

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO data_quality_issues(issue_code, entity_type, entity_key, source_sheet, source_row_number, details)
                    VALUES('phase7_manual_review', 'attendance', 'P7-001', 'ATTENDANCE_LOG', 77, '{}'::jsonb)
                    RETURNING issue_id
                    """
                )
                issue_id = cur.fetchone()[0]
        editor.resolve_quality_issue(issue_id, "resolved", "reviewed during Phase 7 workflow")
        issue = one(conn, "SELECT status, resolution_note FROM data_quality_issues WHERE issue_id=%s", (issue_id,))
        assert issue["status"] == "resolved"

        progress = one(conn, "SELECT * FROM v_employee_progress_summary WHERE employee_id=%s", (employee,))
        assert progress["current_level_name"] == "P7 Highest"

        assert_static_ui_contract()

        return {
            "employee_id": employee,
            "cohort_id": cohort,
            "course_run_id": run,
            "run_enrollment_id": enrollment,
            "attendance_ratio": str(attendance_row["attendance_ratio"]),
            "evaluation_versions": eval_history["total"],
            "completion_status": completed["status"],
            "quality_issue_status": issue["status"],
        }
    finally:
        conn.close()


def main() -> None:
    db_name = os.getenv("PHASE7_TEST_DB", DEFAULT_TEST_DB)
    maintenance_url = os.getenv("PHASE7_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    database_url = os.getenv("PHASE7_DATABASE_URL", _database_url(db_name, maintenance_url))

    recreate_database(maintenance_url, db_name)
    apply_migrations(database_url)
    result = run_gate(database_url)
    print("Phase 7 frontend workflow gate passed.")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
