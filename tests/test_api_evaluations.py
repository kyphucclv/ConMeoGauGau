from concurrent.futures import ThreadPoolExecutor
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


def test_editor_records_the_first_final_result_through_the_run_enrollment_interface(
    database_url, factory, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Final Result Alpha")
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            pending = client.get("/api/evaluations/pending")
            before = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )
            recorded = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "final_level_id": seed_ids["final_level"],
                    "passed": True,
                    "next_course_id": seed_ids["course"],
                    "teacher_notes": "Ready for the next course",
                    "correction_reason": None,
                },
            )
            after = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )

        assert pending.status_code == 200
        assert enrollment.entity_id in {
            item["run_enrollment_id"] for item in pending.json()["items"]
        }
        assert before.status_code == 200
        assert before.json()["enrollment"]["full_name"] == "Final Result Alpha"
        assert before.json()["eligibility"]["effective_exam_eligible"] is False
        assert before.json()["latest_result"] is None
        assert recorded.status_code == 200
        assert recorded.json() == {
            "evaluation_version_id": recorded.json()["evaluation_version_id"],
            "version_number": 1,
            "effective_exam_eligible": False,
            "exam_eligibility_override": False,
        }
        assert after.json()["latest_result"] == {
            "evaluation_version_id": recorded.json()["evaluation_version_id"],
            "version_number": 1,
            "final_level_id": seed_ids["final_level"],
            "final_level_name": "Pytest Final",
            "exam_eligible": False,
            "exam_eligibility_override": False,
            "exam_eligibility_override_reason": None,
            "passed": True,
            "next_course_id": seed_ids["course"],
            "next_course_code": "PT-A",
            "teacher_notes": "Ready for the next course",
            "correction_reason": None,
            "created_by_username": "pytest_editor",
            "created_at": after.json()["latest_result"]["created_at"],
        }
        assert len(after.json()["history"]) == 1
    finally:
        pool.closeall()


def test_final_result_correction_requires_reason_and_appends_history(
    database_url, factory, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Corrected Result")
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            first = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )
            missing_reason = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"final_level_id": seed_ids["entrance_level"], "passed": False},
            )
            corrected = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "final_level_id": seed_ids["entrance_level"],
                    "passed": False,
                    "correction_reason": "Teacher corrected the assessment",
                },
            )
            detail = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )

        assert first.status_code == 200 and first.json()["version_number"] == 1
        assert missing_reason.status_code == 422
        assert missing_reason.json()["code"] == "invalid_input"
        assert corrected.status_code == 200 and corrected.json()["version_number"] == 2
        assert [item["version_number"] for item in detail.json()["history"]] == [2, 1]
        assert detail.json()["history"][0]["correction_reason"] == (
            "Teacher corrected the assessment"
        )
        assert detail.json()["history"][1]["passed"] is True
        assert factory.one(
            """SELECT actor_username,details->>'correction_reason'
               FROM audit_events WHERE action='evaluation.correct'""",
        ) == ("pytest_editor", "Teacher corrected the assessment")
    finally:
        pool.closeall()


def test_only_admin_can_override_eligibility_without_erasing_the_latest_result(
    database_url, factory, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Eligibility Override")
    pool, client = client_for(database_url)
    try:
        with client:
            editor = _login(client)
            recorded = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )
            forbidden = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/exam-eligibility-override",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"eligible": True, "reason": "editor cannot decide"},
            )
            client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": editor["csrf_token"]},
            )
            admin = _login(client, "pytest_admin", "admin-pass")
            overridden = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/exam-eligibility-override",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"eligible": True, "reason": "Approved exam exception"},
            )
            detail = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )

        assert recorded.status_code == 200
        assert forbidden.status_code == 403 and forbidden.json()["code"] == "forbidden"
        assert overridden.status_code == 200
        assert overridden.json() == {
            "evaluation_version_id": overridden.json()["evaluation_version_id"],
            "version_number": 2,
            "effective_exam_eligible": True,
            "previous_effective_exam_eligible": False,
        }
        assert detail.json()["eligibility"]["calculated_exam_eligible"] is False
        assert detail.json()["eligibility"]["effective_exam_eligible"] is True
        assert detail.json()["eligibility"]["exam_eligibility_override_reason"] == (
            "Approved exam exception"
        )
        assert detail.json()["latest_result"]["final_level_id"] == seed_ids["final_level"]
        assert detail.json()["latest_result"]["passed"] is True
        assert factory.one(
            """SELECT actor_username,details->>'reason'
               FROM audit_events WHERE action='eligibility.override'""",
        ) == ("pytest_admin", "Approved exam exception")
    finally:
        pool.closeall()


def test_final_result_uses_attendance_derived_eligibility(database_url, factory, admin_svc, seed_ids):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Attendance Eligible")
    for sequence, status in enumerate(["Present", "Present", "Present", "Absent"], start=1):
        _, unit_id = factory.meeting_unit(
            course_run_id, sequence, day_offset=sequence - 1
        )
        roster = admin_svc.attendance_roster(course_run_id, unit_id)
        admin_svc.save_attendance_roster(
            course_run_id,
            unit_id,
            [{"run_enrollment_id": enrollment.entity_id, "effective_status": status}],
            roster_token=roster.values["roster_token"],
        )
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            detail = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )
            recorded = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )

        assert detail.json()["eligibility"] == {
            "applicable_units": 4,
            "present_units": 3,
            "attendance_ratio": 0.75,
            "calculated_exam_eligible": True,
            "effective_exam_eligible": True,
            "exam_eligibility_override": False,
            "exam_eligibility_override_reason": None,
            "latest_evaluation_version": None,
        }
        assert recorded.json()["effective_exam_eligible"] is True
    finally:
        pool.closeall()


def test_editor_suggests_completion_and_only_admin_confirms_it(
    database_url, factory, admin_svc, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Completion Confirmed")
    _, unit_id = factory.meeting_unit(course_run_id, 1)
    roster = admin_svc.attendance_roster(course_run_id, unit_id)
    admin_svc.save_attendance_roster(
        course_run_id,
        unit_id,
        [{"run_enrollment_id": enrollment.entity_id, "effective_status": "Present"}],
        roster_token=roster.values["roster_token"],
    )
    pool, client = client_for(database_url)
    try:
        with client:
            editor = _login(client)
            client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )
            suggested = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"action": "suggest", "reason": None},
            )
            forbidden = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"action": "confirm", "reason": None},
            )
            client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": editor["csrf_token"]},
            )
            admin = _login(client, "pytest_admin", "admin-pass")
            confirmed = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"action": "confirm", "reason": None},
            )
            detail = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )

        assert suggested.status_code == 200
        assert suggested.json()["suggested"] is True
        assert suggested.json()["completion_status"] == "suggested"
        assert suggested.json()["enrollment_status"] == "active"
        assert forbidden.status_code == 403 and forbidden.json()["code"] == "forbidden"
        assert confirmed.status_code == 200
        assert confirmed.json()["completion_status"] == "confirmed"
        assert confirmed.json()["enrollment_status"] == "completed"
        assert detail.json()["completion"]["confirmed_by_username"] == "pytest_admin"
        assert detail.json()["enrollment"]["enrollment_status"] == "completed"
        assert factory.one(
            """SELECT actor_username,(details->>'confirmed')::boolean
               FROM audit_events WHERE action='completion.confirm'""",
        ) == ("pytest_admin", True)
    finally:
        pool.closeall()


def test_completion_rejection_requires_reason_and_preserves_active_enrollment(
    database_url, factory
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Completion Rejected")
    pool, client = client_for(database_url)
    try:
        with client:
            admin = _login(client, "pytest_admin", "admin-pass")
            suggested = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"action": "suggest", "reason": None},
            )
            missing_reason = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"action": "reject", "reason": None},
            )
            after_failed_reject = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )
            rejected = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"action": "reject", "reason": "Result needs another review"},
            )
            detail = client.get(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result"
            )

        assert suggested.status_code == 200
        assert missing_reason.status_code == 422
        assert missing_reason.json()["code"] == "invalid_input"
        assert after_failed_reject.json()["completion"]["status"] == "suggested"
        assert rejected.status_code == 200
        assert rejected.json()["completion_status"] == "rejected"
        assert rejected.json()["enrollment_status"] == "active"
        assert detail.json()["enrollment"]["enrollment_status"] == "active"
    finally:
        pool.closeall()


def test_concurrent_first_result_submissions_commit_once_and_conflict_safely(
    database_url, factory, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Concurrent Result")
    pool_a, client_a = client_for(database_url)
    pool_b, client_b = client_for(database_url)
    barrier = Barrier(2)

    def submit(client, csrf_token: str):
        barrier.wait()
        return client.post(
            f"/api/run-enrollments/{enrollment.entity_id}/final-result",
            headers={"X-CSRF-Token": csrf_token},
            json={"final_level_id": seed_ids["final_level"], "passed": True},
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

        assert sorted(response.status_code for response in responses) == [200, 422]
        conflict = next(response for response in responses if response.status_code == 422)
        assert conflict.json()["code"] == "invalid_input"
        assert factory.one(
            """SELECT count(*) FROM evaluation_versions version
               JOIN evaluations evaluation ON evaluation.evaluation_id=version.evaluation_id
               WHERE evaluation.run_enrollment_id=%s""",
            (enrollment.entity_id,),
        )[0] == 1
        assert factory.one(
            """SELECT count(*) FROM audit_events audit
               JOIN evaluation_versions version
                 ON audit.entity_key=version.evaluation_version_id::text
               JOIN evaluations evaluation ON evaluation.evaluation_id=version.evaluation_id
               WHERE audit.action='evaluation.record' AND evaluation.run_enrollment_id=%s""",
            (enrollment.entity_id,),
        )[0] == 1
    finally:
        pool_a.closeall()
        pool_b.closeall()


def test_final_result_contract_rejects_viewer_csrf_forged_and_invalid_state_writes(
    database_url, factory, seed_ids
):
    _, course_run_id = factory.cohort_run()
    enrollment = factory.onboard(course_run_id, full_name="Protected Result")
    pool, client = client_for(database_url)
    try:
        with client:
            viewer = _login(client, "pytest_viewer", "viewer-pass")
            viewer_list = client.get("/api/evaluations/pending")
            viewer_write = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": viewer["csrf_token"]},
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )
            client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": viewer["csrf_token"]},
            )
            editor = _login(client)
            bad_csrf = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                json={"final_level_id": seed_ids["final_level"], "passed": True},
            )
            forged = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={
                    "final_level_id": seed_ids["final_level"],
                    "passed": True,
                    "exam_eligible": True,
                    "version_number": 9,
                    "created_by_user_id": 999,
                },
            )
            incomplete = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/final-result",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"passed": True},
            )
            missing = client.get("/api/run-enrollments/999999/final-result")
            confirm_without_suggestion = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"action": "confirm", "reason": None},
            )
            client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": editor["csrf_token"]},
            )
            admin = _login(client, "pytest_admin", "admin-pass")
            missing_suggestion = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/completion-confirmation",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"action": "confirm", "reason": None},
            )
            blank_override = client.post(
                f"/api/run-enrollments/{enrollment.entity_id}/exam-eligibility-override",
                headers={"X-CSRF-Token": admin["csrf_token"]},
                json={"eligible": True, "reason": "   "},
            )

        assert viewer_list.status_code == 403
        assert viewer_write.status_code == 403
        assert bad_csrf.status_code == 403 and bad_csrf.json()["code"] == "csrf_rejected"
        assert forged.status_code == 422 and forged.json()["code"] == "invalid_input"
        assert incomplete.status_code == 422 and incomplete.json()["code"] == "invalid_input"
        assert missing.status_code == 404
        assert confirm_without_suggestion.status_code == 403
        assert missing_suggestion.status_code == 409
        assert missing_suggestion.json()["code"] == "invalid_state"
        assert blank_override.status_code == 422
        assert factory.one(
            """SELECT count(*) FROM evaluation_versions version
               JOIN evaluations evaluation ON evaluation.evaluation_id=version.evaluation_id
               WHERE evaluation.run_enrollment_id=%s""",
            (enrollment.entity_id,),
        )[0] == 0
    finally:
        pool.closeall()
