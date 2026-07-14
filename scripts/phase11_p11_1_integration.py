"""P11.1 integration gate: learner onboarding, constraints, and transfer."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import apply_migrations
from scripts.phase4_integration_check import _database_url, recreate_database
from services import BusinessService, CommandError


def expect_error(code, fn):
    try:
        fn()
    except CommandError as exc:
        assert exc.code == code, f"expected {code}; got {exc.code}"
        return
    raise AssertionError(f"expected CommandError {code}")


def scalar(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def seed(conn):
    with conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app_users(username,password_hash,full_name,role) VALUES('p11','x','P11 HR','editor') RETURNING user_id")
            user_id = cur.fetchone()[0]
            cur.execute("INSERT INTO business_units(business_unit_name) VALUES('P11 BU') RETURNING business_unit_id")
            bu_id = cur.fetchone()[0]
            cur.execute("INSERT INTO job_roles(job_role_name) VALUES('P11 Role') RETURNING job_role_id")
            role_id = cur.fetchone()[0]
            cur.execute("INSERT INTO levels(level_name,numeric_value,sequence_order) VALUES('P11 Entrance',1.0,1) RETURNING level_id")
            level_id = cur.fetchone()[0]
            cur.execute("INSERT INTO courses(course_code,course_name,expected_units,attendance_threshold_ratio) VALUES('P11', 'P11 Course', 4, .8) RETURNING course_id")
            course_id = cur.fetchone()[0]
    return user_id, bu_id, role_id, level_id, course_id


def run(database_url):
    conn = psycopg2.connect(database_url)
    try:
        user_id, bu_id, role_id, level_id, course_id = seed(conn)
        svc = BusinessService(conn, user_id)
        assert svc.propose_next_class_code().values['class_code'] == 'EL001'
        source_cohort = svc.create_cohort('EL001', 'Source', status='active', capacity=1).entity_id
        target_cohort = svc.create_cohort('EL002', 'Target', status='active', capacity=2).entity_id
        source_run = svc.create_course_run(source_cohort, course_id, start_date=date(2026, 7, 1)).entity_id
        target_run = svc.create_course_run(target_cohort, course_id, start_date=date(2026, 7, 1)).entity_id
        source_meeting = svc.save_meeting(source_run, datetime(2026, 7, 1, 9, tzinfo=timezone.utc), 60).entity_id
        source_unit = svc.add_session_unit(source_run, source_meeting, 1).entity_id

        learner = svc.onboard_learner(
            emp_code='P11-001', full_name='First Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=source_run, joined_on=date(2026, 7, 1),
        )
        assert learner.values['lifecycle'] == 'first_time'
        assert learner.values['placement_action'] == 'created'
        assert learner.values['membership_action'] == 'created'
        assert scalar(conn, 'SELECT count(*) FROM placements WHERE employee_id=%s', (learner.values['employee_id'],)) == 1
        assert scalar(conn, 'SELECT count(*) FROM run_enrollments WHERE run_enrollment_id=%s', (learner.entity_id,)) == 1
        assert scalar(conn, 'SELECT business_unit_id_snapshot FROM run_enrollments WHERE run_enrollment_id=%s', (learner.entity_id,)) == bu_id

        # Full cohort fails as one transaction: no directory row or placement leaks.
        expect_error('capacity_exceeded', lambda: svc.onboard_learner(
            emp_code='P11-ROLLBACK', full_name='Rollback Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=source_run, joined_on=date(2026, 7, 2),
        ))
        assert scalar(conn, "SELECT count(*) FROM employees WHERE emp_code='P11-ROLLBACK'") == 0

        override = svc.onboard_learner(
            emp_code='P11-002', full_name='Override Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=source_run, joined_on=date(2026, 7, 2),
            capacity_override_reason='Approved temporary seat',
        )
        assert scalar(conn, 'SELECT count(*) FROM cohort_capacity_overrides WHERE employee_id=%s', (override.values['employee_id'],)) == 1
        expect_error('active_enrollment_conflict', lambda: svc.onboard_learner(
            emp_code='P11-001', full_name='First Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=target_run, joined_on=date(2026, 7, 3),
        ))

        midrun_cohort = svc.create_cohort('EL003', 'Mid-run intake', status='active', capacity=5).entity_id
        midrun_run = svc.create_course_run(midrun_cohort, course_id, start_date=date(2026, 7, 1)).entity_id
        completed_units = []
        for seq in (1, 2):
            completed_meeting = svc.save_meeting(
                midrun_run,
                datetime(2026, 7, seq, 9, tzinfo=timezone.utc),
                60,
                status='completed',
            ).entity_id
            completed_units.append(svc.add_session_unit(midrun_run, completed_meeting, seq).entity_id)
        assert svc.propose_onboarding_start_session(midrun_run).values['start_session_number'] == 3
        expect_error('invalid_input', lambda: svc.onboard_learner(
            emp_code='P11-MIDRUN-BAD', full_name='Bad Midrun Start', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=midrun_run, joined_on=date(2026, 7, 3),
            start_session_number=1,
        ))
        midrun_learner = svc.onboard_learner(
            emp_code='P11-MIDRUN', full_name='Midrun Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=midrun_run, joined_on=date(2026, 7, 3),
            start_session_number=3,
        )
        assert scalar(
            conn,
            """SELECT count(*) FROM v_operational_data_issues
               WHERE issue_code='incomplete_attendance_roster' AND entity_key IN (%s,%s)""",
            tuple(str(unit_id) for unit_id in completed_units),
        ) == 0

        # The same active class membership and entrance placement carry into
        # the next course, while a later rejoin creates only a new membership.
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE run_enrollments SET status='completed' WHERE run_enrollment_id=%s", (midrun_learner.entity_id,))
        continuation_run = svc.create_course_run(midrun_cohort, course_id, start_date=date(2026, 7, 10)).entity_id
        continuation = svc.onboard_learner(
            emp_code='P11-MIDRUN', full_name='Midrun Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=continuation_run, joined_on=date(2026, 7, 10),
        )
        assert continuation.values['lifecycle'] == 'continuation'
        assert continuation.values['placement_id'] == midrun_learner.values['placement_id']
        assert continuation.values['membership_id'] == midrun_learner.values['membership_id']
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE run_enrollments SET status='completed' WHERE run_enrollment_id=%s", (continuation.entity_id,))
        svc.close_membership(continuation.values['membership_id'], date(2026, 7, 20))
        rejoin_run = svc.create_course_run(midrun_cohort, course_id, start_date=date(2026, 8, 1)).entity_id
        rejoin = svc.onboard_learner(
            emp_code='P11-MIDRUN', full_name='Midrun Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=rejoin_run, joined_on=date(2026, 8, 1),
        )
        assert rejoin.values['lifecycle'] == 'rejoin'
        assert rejoin.values['placement_id'] == midrun_learner.values['placement_id']
        assert rejoin.values['membership_id'] != midrun_learner.values['membership_id']

        target_meeting = svc.save_meeting(target_run, datetime(2026, 7, 8, 9, tzinfo=timezone.utc), 60).entity_id
        target_unit = svc.add_session_unit(target_run, target_meeting, 3).entity_id
        assert svc.propose_transfer_start_session(target_run).values['start_session_number'] == 3
        moved = svc.transfer_learner(learner.entity_id, target_run, date(2026, 7, 4), confirmed_start_session_number=3)
        assert moved.values['start_session_number'] == 3
        assert scalar(conn, "SELECT status FROM run_enrollments WHERE run_enrollment_id=%s", (learner.entity_id,)) == 'transferred'
        assert scalar(conn, "SELECT status FROM run_enrollments WHERE run_enrollment_id=%s", (moved.entity_id,)) == 'active'

        # A completed historical session reconstructs applicability from the
        # enrollment start and membership dates even after transfer. Missing
        # history remains unknown until HR explicitly enters evidence.
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE meetings SET status='completed' WHERE meeting_id=%s", (source_meeting,))
        historical = svc.attendance_roster(source_run, source_unit)
        assert [row['run_enrollment_id'] for row in historical.values['rows']] == [learner.entity_id]
        assert historical.values['rows'][0]['effective_status'] is None
        first_save = svc.save_attendance_roster(source_run, source_unit, [{
            'run_enrollment_id': learner.entity_id, 'effective_status': 'Present',
        }])
        assert first_save.values['created_count'] == 1
        second_save = svc.save_attendance_roster(source_run, source_unit, [{
            'run_enrollment_id': learner.entity_id, 'effective_status': 'Absent',
        }])
        assert second_save.values['updated_count'] == 1
        attendance_audit = scalar(
            conn,
            "SELECT details FROM audit_events WHERE action='attendance.roster.save' AND entity_key=%s ORDER BY audit_event_id DESC LIMIT 1",
            (str(source_unit),),
        )
        assert attendance_audit['changes'][0]['before']['effective_status'] == 'Present'
        assert attendance_audit['changes'][0]['after']['effective_status'] == 'Absent'

        # The attendance roster exposes only applicable learners and defaults
        # unsaved values to Present; a full-roster save is one transaction.
        roster = svc.attendance_roster(target_run, target_unit)
        assert len(roster.values['rows']) == 1
        assert roster.values['rows'][0]['effective_status'] == 'Present'
        svc.save_attendance_roster(target_run, roster.entity_id, [{
            'run_enrollment_id': moved.entity_id, 'effective_status': 'Absent',
        }])
        assert scalar(conn, 'SELECT effective_status FROM attendance WHERE run_enrollment_id=%s', (moved.entity_id,)) == 'Absent'
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE run_enrollments SET status='completed' WHERE run_enrollment_id=%s", (moved.entity_id,))
        completed_history = svc.attendance_roster(target_run, target_unit)
        assert [row['run_enrollment_id'] for row in completed_history.values['rows']] == [moved.entity_id]

        returning_employee = svc.create_or_update_employee(
            'P11-RETURN', 'Returning Learner', employment_status='active',
            business_unit_id=bu_id, job_role_id=role_id, valid_from=date(2026, 7, 9),
        ).entity_id
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO placements(employee_id,placement_kind,test_date,level_id) VALUES(%s,'business',%s,%s)",
                    (returning_employee, date(2026, 7, 9), level_id),
                )
        returning = svc.onboard_learner(
            emp_code='P11-RETURN', full_name='Returning Learner', business_unit_id=bu_id, job_role_id=role_id,
            entrance_level_id=level_id, course_run_id=target_run, joined_on=date(2026, 7, 9),
            start_session_number=4,
        )
        assert returning.values['lifecycle'] == 'returning'
        assert returning.values['placement_action'] == 'reused'
        assert returning.values['membership_action'] == 'created'
        assert scalar(conn, 'SELECT count(*) FROM placements WHERE employee_id=%s', (returning_employee,)) == 1
        expect_error('invalid_state', lambda: svc.save_attendance_roster(target_run, roster.entity_id, []))
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO attendance(run_enrollment_id,session_unit_id,effective_status)
                           VALUES(%s,%s,'Present')""",
                        (moved.entity_id, source_unit),
                    )
        except psycopg2.Error:
            pass
        else:
            raise AssertionError('attendance outside the enrollment course run should be rejected')

        # The database, not only the service, protects immutable event snapshots.
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('UPDATE run_enrollments SET business_unit_id_snapshot=NULL WHERE run_enrollment_id=%s', (moved.entity_id,))
        except psycopg2.Error:
            pass
        else:
            raise AssertionError('snapshot mutation should be rejected by database trigger')
        assert svc.assign_pic(target_cohort, None, date(2026, 7, 1), pic_label='  Learning   Team  ').entity_id
        assert svc.pic_label_suggestions('learning team').values['labels'] == ['Learning Team']
        return {'learner_enrollment_id': learner.entity_id, 'transfer_enrollment_id': moved.entity_id}
    finally:
        conn.close()


if __name__ == '__main__':
    maintenance_url = os.getenv('P11_MAINTENANCE_URL', 'postgresql://postgres@localhost:5432/postgres')
    database_url = _database_url('english_class_p11_test', maintenance_url)
    recreate_database(maintenance_url, 'english_class_p11_test')
    apply_migrations(database_url)
    print(run(database_url))
