from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from tests.test_api_auth import ORIGIN, client_for


def _login(client, username: str = "pytest_editor", password: str = "editor-pass") -> dict:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def test_editor_credits_an_eligible_absence_through_the_makeup_http_interface(database_url, factory, admin_svc):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Make-up Learner")
    _, absence_unit_id = factory.meeting_unit(course_run_id, 1, status="completed")
    admin_svc.bulk_record_attendance([{
        "run_enrollment_id": enrollment.entity_id,
        "session_unit_id": absence_unit_id,
        "effective_status": "Absent",
    }])
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s AND session_unit_id=%s",
        (enrollment.entity_id, absence_unit_id),
    )[0]
    _, makeup_unit_id = factory.meeting_unit(
        course_run_id, 2, unit_type="makeup", day_offset=7
    )
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            options = client.get("/api/attendance/makeup-options")
            credited = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "makeup_session_unit_id": makeup_unit_id,
                    "reason": "Approved medical absence",
                },
            )
            refreshed = client.get("/api/attendance/makeup-options")

        assert options.status_code == 200
        absence = next(
            item for item in options.json()["items"]
            if item["attendance_id"] == attendance_id
        )
        assert absence["full_name"] == "Make-up Learner"
        assert [unit["session_unit_id"] for unit in absence["eligible_units"]] == [makeup_unit_id]
        assert credited.status_code == 200
        assert credited.json() == {
            "attendance_id": credited.json()["attendance_id"],
            "makeup_for_attendance_id": attendance_id,
            "credited_status": "Present",
            "denominator_units_added": 0,
        }
        assert attendance_id not in {
            item["attendance_id"] for item in refreshed.json()["items"]
        }
    finally:
        pool.closeall()


def test_makeup_http_credit_preserves_the_original_denominator_and_named_audit(database_url, factory, admin_svc):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Reconciled Make-up")
    _, absence_unit_id = factory.meeting_unit(course_run_id, 1, status="completed")
    admin_svc.bulk_record_attendance([{
        "run_enrollment_id": enrollment.entity_id,
        "session_unit_id": absence_unit_id,
        "effective_status": "Absent",
    }])
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s AND session_unit_id=%s",
        (enrollment.entity_id, absence_unit_id),
    )[0]
    _, makeup_unit_id = factory.meeting_unit(
        course_run_id, 2, unit_type="makeup", day_offset=7
    )
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            response = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "makeup_session_unit_id": makeup_unit_id,
                    "reason": "Manager-approved recovery class",
                },
            )

        assert response.status_code == 200
        assert factory.one(
            "SELECT effective_status,is_makeup FROM attendance WHERE attendance_id=%s",
            (attendance_id,),
        ) == ("Absent", False)
        assert factory.one(
            """SELECT applicable_units,present_units,makeup_present_units,attendance_ratio
               FROM v_run_enrollment_attendance WHERE run_enrollment_id=%s""",
            (enrollment.entity_id,),
        ) == (1, 1, 1, 1)
        audit = factory.one(
            """SELECT actor_username,details->>'reason',details->'before',details->'after',
                      (details->>'denominator_units_added')::int
               FROM audit_events WHERE action='attendance.makeup' AND entity_key=%s""",
            (str(response.json()["attendance_id"]),),
        )
        assert audit == (
            "pytest_editor",
            "Manager-approved recovery class",
            {"original_status": "Absent", "credited_status": "Absent"},
            {"original_status": "Absent", "credited_status": "Present"},
            0,
        )
    finally:
        pool.closeall()


def test_concurrent_makeup_http_credits_commit_once(database_url, factory, admin_svc):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Concurrent Make-up")
    _, absence_unit_id = factory.meeting_unit(course_run_id, 1, status="completed")
    admin_svc.bulk_record_attendance([{
        "run_enrollment_id": enrollment.entity_id,
        "session_unit_id": absence_unit_id,
        "effective_status": "Absent",
    }])
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s AND session_unit_id=%s",
        (enrollment.entity_id, absence_unit_id),
    )[0]
    _, makeup_unit_id = factory.meeting_unit(
        course_run_id, 2, unit_type="makeup", day_offset=7
    )
    pool_a, client_a = client_for(database_url)
    pool_b, client_b = client_for(database_url)
    barrier = Barrier(2)

    def submit(client, csrf_token: str):
        barrier.wait()
        return client.post(
            f"/api/attendance/{attendance_id}/makeup-credit",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "makeup_session_unit_id": makeup_unit_id,
                "reason": "Concurrent approved request",
            },
        )

    try:
        with client_a, client_b:
            auth_a = _login(client_a)
            auth_b = _login(client_b, "pytest_admin", "admin-pass")
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = [future.result(timeout=15) for future in [
                    executor.submit(submit, client_a, auth_a["csrf_token"]),
                    executor.submit(submit, client_b, auth_b["csrf_token"]),
                ]]

        assert sorted(response.status_code for response in responses) == [200, 409]
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()["code"] == "duplicate_makeup"
        assert factory.one(
            "SELECT count(*) FROM attendance WHERE makeup_for_attendance_id=%s",
            (attendance_id,),
        )[0] == 1
        assert factory.one(
            "SELECT count(*) FROM audit_events WHERE action='attendance.makeup' AND details->>'makeup_for'=%s",
            (str(attendance_id),),
        )[0] == 1
    finally:
        pool_a.closeall()
        pool_b.closeall()


def test_makeup_http_contract_filters_invalid_units_and_rejects_unauthorized_or_forged_writes(database_url, factory, admin_svc):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Protected Make-up")
    _, absence_unit_id = factory.meeting_unit(course_run_id, 1, status="completed")
    admin_svc.bulk_record_attendance([{
        "run_enrollment_id": enrollment.entity_id,
        "session_unit_id": absence_unit_id,
        "effective_status": "Absent",
    }])
    attendance_id = factory.one(
        "SELECT attendance_id FROM attendance WHERE run_enrollment_id=%s AND session_unit_id=%s",
        (enrollment.entity_id, absence_unit_id),
    )[0]
    _, normal_unit_id = factory.meeting_unit(course_run_id, 2, day_offset=7)
    cancelled_meeting_id, cancelled_unit_id = factory.meeting_unit(
        course_run_id, 3, unit_type="makeup", day_offset=8
    )
    admin_svc.cancel_meeting(cancelled_meeting_id, "cancelled make-up")
    _, valid_unit_id = factory.meeting_unit(
        course_run_id, 4, unit_type="makeup", day_offset=9
    )
    pool, client = client_for(database_url)
    try:
        with client:
            viewer = _login(client, "pytest_viewer", "viewer-pass")
            viewer_options = client.get("/api/attendance/makeup-options")
            viewer_write = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": viewer["csrf_token"]},
                json={"makeup_session_unit_id": valid_unit_id, "reason": "forbidden"},
            )
            client.post("/api/auth/logout", headers={"X-CSRF-Token": viewer["csrf_token"]})
            auth = _login(client, "pytest_admin", "admin-pass")
            options = client.get("/api/attendance/makeup-options")
            bad_csrf = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                json={"makeup_session_unit_id": valid_unit_id, "reason": "missing csrf"},
            )
            forged = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "makeup_session_unit_id": valid_unit_id,
                    "reason": "attempted forgery",
                    "actor_username": "forged",
                    "denominator_units_added": 1,
                },
            )
            blank_reason = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"makeup_session_unit_id": valid_unit_id, "reason": "   "},
            )
            normal_target = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"makeup_session_unit_id": normal_unit_id, "reason": "wrong target"},
            )
            cancelled_target = client.post(
                f"/api/attendance/{attendance_id}/makeup-credit",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"makeup_session_unit_id": cancelled_unit_id, "reason": "wrong target"},
            )

        assert viewer_options.status_code == 403
        assert viewer_write.status_code == 403
        option = next(item for item in options.json()["items"] if item["attendance_id"] == attendance_id)
        assert [unit["session_unit_id"] for unit in option["eligible_units"]] == [valid_unit_id]
        assert bad_csrf.status_code == 403 and bad_csrf.json()["code"] == "csrf_rejected"
        assert forged.status_code == 422 and forged.json()["code"] == "invalid_input"
        assert blank_reason.status_code == 422 and blank_reason.json()["code"] == "invalid_input"
        assert normal_target.status_code == 422 and normal_target.json()["code"] == "invalid_input"
        assert cancelled_target.status_code == 409 and cancelled_target.json()["code"] == "invalid_state"
        assert factory.one(
            "SELECT count(*) FROM attendance WHERE makeup_for_attendance_id=%s",
            (attendance_id,),
        )[0] == 0
    finally:
        pool.closeall()


def test_editor_creates_a_session_and_saves_its_complete_roster(database_url, factory):
    _, course_run_id = factory.cohort_run()
    first = factory.onboard(course_run_id, full_name="Attendance Alpha")
    second = factory.onboard(course_run_id, full_name="Attendance Beta")
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            runs = client.get("/api/attendance/course-runs")
            created = client.post(
                f"/api/course-runs/{course_run_id}/attendance-sessions",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "starts_at": "2026-08-10T09:00:00Z",
                    "duration_minutes": 60,
                    "confirmed_sequence_in_run": 1,
                },
            )
            session_unit_id = created.json()["session_unit_id"]
            units = client.get(f"/api/course-runs/{course_run_id}/session-units")
            roster = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            )
            saved = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "roster_token": roster.json()["roster_token"],
                    "records": [
                        {"run_enrollment_id": first.entity_id, "effective_status": "Present"},
                        {"run_enrollment_id": second.entity_id, "effective_status": "Absent"},
                    ],
                },
            )
            refreshed = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            )

        assert runs.status_code == 200
        run = next(item for item in runs.json()["items"] if item["course_run_id"] == course_run_id)
        assert run["next_sequence_in_run"] == 1
        assert created.status_code == 200
        assert created.json()["sequence_in_run"] == 1
        assert units.status_code == 200
        assert units.json()["items"][0]["session_unit_id"] == session_unit_id
        assert [row["full_name"] for row in roster.json()["rows"]] == ["Attendance Alpha", "Attendance Beta"]
        assert [row["effective_status"] for row in roster.json()["rows"]] == ["Present", "Present"]
        assert saved.status_code == 200
        assert saved.json() == {
            "session_unit_id": session_unit_id,
            "count": 2,
            "created_count": 2,
            "updated_count": 0,
            "unchanged_count": 0,
        }
        assert refreshed.json()["meeting_status"] == "completed"
        assert [row["effective_status"] for row in refreshed.json()["rows"]] == ["Present", "Absent"]
    finally:
        pool.closeall()


def test_changed_membership_rejects_the_stale_roster_without_partial_writes(database_url, factory):
    _, course_run_id = factory.cohort_run()
    first = factory.onboard(course_run_id, full_name="Roster First")
    _, session_unit_id = factory.meeting_unit(course_run_id, 1)
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            roster = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            ).json()
            factory.onboard(course_run_id, full_name="Roster Joined Later")
            response = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "roster_token": roster["roster_token"],
                    "records": [
                        {"run_enrollment_id": first.entity_id, "effective_status": "Absent"}
                    ],
                },
            )

        assert response.status_code == 409
        assert response.json()["code"] == "stale_roster"
        assert factory.one(
            "SELECT m.status,count(a.attendance_id) FROM meetings m JOIN session_units su ON su.meeting_id=m.meeting_id LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id WHERE su.session_unit_id=%s GROUP BY m.status",
            (session_unit_id,),
        ) == ("planned", 0)
    finally:
        pool.closeall()


def test_concurrent_roster_saves_commit_once_and_reject_the_stale_writer(database_url, factory):
    _, course_run_id = factory.cohort_run()
    learner = factory.onboard(course_run_id, full_name="Concurrent Attendance")
    _, session_unit_id = factory.meeting_unit(course_run_id, 1)
    pool_a, client_a = client_for(database_url)
    pool_b, client_b = client_for(database_url)
    barrier = Barrier(2)

    def submit(client, csrf_token: str, roster_token: str, status: str):
        barrier.wait()
        return client.put(
            f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "roster_token": roster_token,
                "records": [
                    {"run_enrollment_id": learner.entity_id, "effective_status": status}
                ],
            },
        )

    try:
        with client_a, client_b:
            auth_a = _login(client_a)
            auth_b = _login(client_b, "pytest_admin", "admin-pass")
            roster_token = client_a.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            ).json()["roster_token"]
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(submit, client_a, auth_a["csrf_token"], roster_token, "Present"),
                    executor.submit(submit, client_b, auth_b["csrf_token"], roster_token, "Absent"),
                ]
                responses = [future.result(timeout=15) for future in futures]

        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["code"] == "stale_roster"
        assert factory.one(
            "SELECT count(*) FROM attendance WHERE session_unit_id=%s",
            (session_unit_id,),
        )[0] == 1
        assert factory.one(
            "SELECT count(*) FROM audit_events WHERE action='attendance.roster.save' AND entity_key=%s",
            (str(session_unit_id),),
        )[0] == 1
    finally:
        pool_a.closeall()
        pool_b.closeall()


def test_completed_session_roster_preserves_later_transfer_and_completion(database_url, factory, admin_svc):
    _, source_run_id = factory.cohort_run()
    _, target_run_id = factory.cohort_run()
    transferred = factory.onboard(source_run_id, full_name="Historical Transfer")
    completed = factory.onboard(source_run_id, full_name="Historical Completion")
    _, session_unit_id = factory.meeting_unit(source_run_id, 1, status="completed")
    admin_svc.transfer_learner(
        transferred.entity_id,
        target_run_id,
        date(2026, 8, 15),
        confirmed_start_session_number=1,
    )
    admin_svc.suggest_completion(completed.entity_id)
    admin_svc.confirm_completion(completed.entity_id, True)

    pool, client = client_for(database_url)
    try:
        with client:
            _login(client)
            response = client.get(
                f"/api/course-runs/{source_run_id}/session-units/{session_unit_id}/roster"
            )

        assert response.status_code == 200
        assert [row["full_name"] for row in response.json()["rows"]] == [
            "Historical Completion",
            "Historical Transfer",
        ]
        assert [row["effective_status"] for row in response.json()["rows"]] == [None, None]
    finally:
        pool.closeall()


def test_roster_contract_rejects_forbidden_incomplete_duplicate_and_cancelled_writes(database_url, factory, admin_svc):
    _, course_run_id = factory.cohort_run()
    learner = factory.onboard(course_run_id, full_name="Protected Attendance")
    meeting_id, session_unit_id = factory.meeting_unit(course_run_id, 1)
    _, other_run_id = factory.cohort_run()
    pool, client = client_for(database_url)
    try:
        with client:
            viewer = _login(client, "pytest_viewer", "viewer-pass")
            viewer_read = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            )
            viewer_write = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                json={"roster_token": "x" * 64, "records": []},
            )
            client.post("/api/auth/logout", headers={"X-CSRF-Token": viewer["csrf_token"]})
            auth = _login(client, "pytest_admin", "admin-pass")
            roster = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            ).json()
            wrong_run = client.get(
                f"/api/course-runs/{other_run_id}/session-units/{session_unit_id}/roster"
            )
            bad_csrf = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                json={"roster_token": roster["roster_token"], "records": []},
            )
            forged = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "roster_token": roster["roster_token"],
                    "records": [{
                        "run_enrollment_id": learner.entity_id,
                        "effective_status": "Present",
                        "employee_id": 999,
                        "audit_actor": "forged",
                    }],
                },
            )
            incomplete = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"roster_token": roster["roster_token"], "records": []},
            )
            duplicate = client.put(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "roster_token": roster["roster_token"],
                    "records": [
                        {"run_enrollment_id": learner.entity_id, "effective_status": "Present"},
                        {"run_enrollment_id": learner.entity_id, "effective_status": "Absent"},
                    ],
                },
            )
            admin_svc.cancel_meeting(meeting_id, "weather closure")
            cancelled = client.get(
                f"/api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster"
            )

        assert viewer_read.status_code == 403
        assert viewer_write.status_code == 403
        assert wrong_run.status_code == 404
        assert bad_csrf.status_code == 403 and bad_csrf.json()["code"] == "csrf_rejected"
        assert forged.status_code == 422 and forged.json()["code"] == "invalid_input"
        assert incomplete.status_code == 409 and incomplete.json()["code"] == "invalid_state"
        assert duplicate.status_code == 409 and duplicate.json()["code"] == "invalid_state"
        assert cancelled.status_code == 409 and cancelled.json()["code"] == "invalid_state"
        assert factory.one(
            "SELECT count(*) FROM attendance WHERE session_unit_id=%s",
            (session_unit_id,),
        )[0] == 0
    finally:
        pool.closeall()


def test_concurrent_session_creation_uses_one_sequence_and_rejects_the_stale_proposal(database_url, factory):
    _, course_run_id = factory.cohort_run()
    pool_a, client_a = client_for(database_url)
    pool_b, client_b = client_for(database_url)
    barrier = Barrier(2)

    def submit(client, csrf_token: str, starts_at: str):
        barrier.wait()
        return client.post(
            f"/api/course-runs/{course_run_id}/attendance-sessions",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "starts_at": starts_at,
                "duration_minutes": 60,
                "confirmed_sequence_in_run": 1,
            },
        )

    try:
        with client_a, client_b:
            auth_a = _login(client_a)
            auth_b = _login(client_b, "pytest_admin", "admin-pass")
            naive_time = client_a.post(
                f"/api/course-runs/{course_run_id}/attendance-sessions",
                headers={"X-CSRF-Token": auth_a["csrf_token"]},
                json={
                    "starts_at": "2026-08-10T09:00:00",
                    "duration_minutes": 60,
                    "confirmed_sequence_in_run": 1,
                },
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(submit, client_a, auth_a["csrf_token"], "2026-08-10T09:00:00Z"),
                    executor.submit(submit, client_b, auth_b["csrf_token"], "2026-08-11T09:00:00Z"),
                ]
                responses = [future.result(timeout=15) for future in futures]

        assert naive_time.status_code == 422 and naive_time.json()["code"] == "invalid_input"
        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["code"] == "stale_proposal"
        assert factory.one(
            "SELECT count(DISTINCT m.meeting_id),count(su.session_unit_id) FROM meetings m JOIN session_units su ON su.meeting_id=m.meeting_id WHERE m.course_run_id=%s",
            (course_run_id,),
        ) == (1, 1)
    finally:
        pool_a.closeall()
        pool_b.closeall()
