from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tests.test_api_auth import ORIGIN, client_for


def _login(client, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def _body(target_course_run_id: int, proposal: int = 1, **overrides) -> dict:
    body = {
        "target_course_run_id": target_course_run_id,
        "transfer_date": "2026-08-15",
        "confirmed_start_session_number": proposal,
    }
    body.update(overrides)
    return body


def test_editor_transfers_the_active_enrollment_and_reconciles_history(database_url, seed_ids, factory):
    source_cohort_id, source_run_id = factory.cohort_run()
    target_cohort_id, target_run_id = factory.cohort_run()
    source = factory.onboard(source_run_id, full_name="HTTP Transfer Learner")
    factory.meeting_unit(target_run_id, 3, status="planned")
    source_snapshot = factory.one(
        "SELECT business_unit_id_snapshot,job_role_id_snapshot,cohort_membership_id FROM run_enrollments WHERE run_enrollment_id=%s",
        (source.entity_id,),
    )

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            options = client.get(f"/api/run-enrollments/{source.entity_id}/transfer-options")
            destination = next(item for item in options.json()["destinations"] if item["course_run_id"] == target_run_id)
            response = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(target_run_id, destination["proposed_start_session_number"]),
            )
            detail = client.get(f"/api/learners/{source.values['employee_id']}")

        assert options.status_code == 200
        assert options.json()["source"]["run_enrollment_id"] == source.entity_id
        assert options.json()["source"]["cohort_id"] == source_cohort_id
        assert all(item["cohort_id"] != source_cohort_id for item in options.json()["destinations"])
        assert destination["cohort_id"] == target_cohort_id
        assert destination["proposed_start_session_number"] == 3
        assert response.status_code == 200
        target_enrollment_id = response.json()["run_enrollment_id"]
        assert response.json()["from_enrollment_id"] == source.entity_id
        assert response.json()["start_session_number"] == 3
        assert response.json()["capacity_override_applied"] is False
        assert factory.one(
            "SELECT status,transfer_from_enrollment_id,business_unit_id_snapshot,job_role_id_snapshot FROM run_enrollments WHERE run_enrollment_id=%s",
            (target_enrollment_id,),
        ) == ("active", source.entity_id, source_snapshot[0], source_snapshot[1])
        assert factory.one(
            "SELECT status,transfer_to_membership_id FROM cohort_memberships WHERE cohort_membership_id=%s",
            (source_snapshot[2],),
        ) == ("transferred", response.json()["membership_id"])
        assert detail.json()["learner"]["active_course_run_id"] == target_run_id
        assert [row["status"] for row in detail.json()["course_history"][:2]] == ["active", "transferred"]
        assert detail.json()["audit_summary"][0] == {
            "created_at": detail.json()["audit_summary"][0]["created_at"],
            "actor_username": "pytest_editor",
            "action": "learner.transfer",
        }
    finally:
        pool.closeall()


def test_transfer_rejects_a_changed_proposal_and_rolls_back(database_url, factory):
    _, source_run_id = factory.cohort_run()
    _, target_run_id = factory.cohort_run()
    source = factory.onboard(source_run_id, full_name="Stale Transfer")
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_admin", "admin-pass")
            options = client.get(f"/api/run-enrollments/{source.entity_id}/transfer-options").json()
            stale = next(item for item in options["destinations"] if item["course_run_id"] == target_run_id)
            factory.meeting_unit(target_run_id, 1, status="completed")
            response = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(target_run_id, stale["proposed_start_session_number"]),
            )

        assert response.status_code == 409
        assert response.json()["code"] == "stale_proposal"
        assert factory.one("SELECT status FROM run_enrollments WHERE run_enrollment_id=%s", (source.entity_id,))[0] == "active"
        assert factory.one(
            "SELECT status FROM cohort_memberships WHERE cohort_membership_id=%s",
            (source.values["membership_id"],),
        )[0] == "active"
        assert factory.one(
            "SELECT count(*) FROM run_enrollments WHERE transfer_from_enrollment_id=%s",
            (source.entity_id,),
        )[0] == 0
    finally:
        pool.closeall()


def test_transfer_capacity_requires_reason_and_retry_is_a_safe_conflict(database_url, seed_ids, factory):
    _, source_run_id = factory.cohort_run()
    target_cohort_id, target_run_id = factory.cohort_run(capacity=1)
    source = factory.onboard(source_run_id, full_name="Capacity Transfer")
    factory.onboard(target_run_id)
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            rejected = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(target_run_id),
            )
            approved = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(target_run_id, capacity_override_reason="HR approved transfer seat"),
            )
            retry = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(target_run_id, capacity_override_reason="HR approved transfer seat"),
            )

        assert rejected.status_code == 409 and rejected.json()["code"] == "capacity_exceeded"
        assert approved.status_code == 200 and approved.json()["capacity_override_applied"] is True
        assert retry.status_code == 409 and retry.json()["code"] == "invalid_state"
        assert factory.one(
            "SELECT reason,actor_user_id,resulting_active_learner_count FROM cohort_capacity_overrides WHERE cohort_id=%s",
            (target_cohort_id,),
        ) == ("HR approved transfer seat", seed_ids["editor"], 2)
        assert factory.one(
            "SELECT count(*) FROM run_enrollments WHERE transfer_from_enrollment_id=%s",
            (source.entity_id,),
        )[0] == 1
    finally:
        pool.closeall()


def test_transfer_rejects_same_class_viewer_bad_csrf_and_extra_fields(database_url, seed_ids, factory, admin_svc):
    source_cohort_id, source_run_id = factory.cohort_run()
    source = factory.onboard(source_run_id, full_name="Protected Transfer")
    same_class_run_id = admin_svc.create_course_run(
        source_cohort_id,
        seed_ids["course"],
        start_date=date(2026, 8, 15),
    ).entity_id
    _, other_run_id = factory.cohort_run()
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_viewer", "viewer-pass")
            viewer_options = client.get(f"/api/run-enrollments/{source.entity_id}/transfer-options")
            viewer_save = client.post(f"/api/run-enrollments/{source.entity_id}/transfer", json=_body(other_run_id))
            viewer_csrf = client.get("/api/auth/me").json()["csrf_token"]
            client.post("/api/auth/logout", headers={"X-CSRF-Token": viewer_csrf})
            auth = _login(client, "pytest_admin", "admin-pass")
            bad_csrf = client.post(f"/api/run-enrollments/{source.entity_id}/transfer", json=_body(other_run_id))
            protected = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={**_body(other_run_id), "employee_id": 999, "audit_actor": "forged"},
            )
            same_class = client.post(
                f"/api/run-enrollments/{source.entity_id}/transfer",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json=_body(same_class_run_id),
            )

        assert viewer_options.status_code == 403
        assert viewer_save.status_code == 403
        assert bad_csrf.status_code == 403 and bad_csrf.json()["code"] == "csrf_rejected"
        assert protected.status_code == 422 and protected.json()["code"] == "invalid_input"
        assert same_class.status_code == 422 and same_class.json()["code"] == "invalid_input"
        assert factory.one("SELECT status FROM run_enrollments WHERE run_enrollment_id=%s", (source.entity_id,))[0] == "active"
    finally:
        pool.closeall()


def test_concurrent_transfers_create_one_deterministic_target(database_url, factory):
    _, source_run_id = factory.cohort_run()
    _, target_a_run_id = factory.cohort_run()
    _, target_b_run_id = factory.cohort_run()
    source = factory.onboard(source_run_id, full_name="Concurrent Transfer")
    pool_a, client_a = client_for(database_url)
    pool_b, client_b = client_for(database_url)
    barrier = Barrier(2)

    def submit(client, csrf_token: str, target_run_id: int):
        barrier.wait()
        return client.post(
            f"/api/run-enrollments/{source.entity_id}/transfer",
            headers={"X-CSRF-Token": csrf_token},
            json=_body(target_run_id),
        )

    try:
        with client_a, client_b:
            auth_a = _login(client_a, "pytest_editor", "editor-pass")
            auth_b = _login(client_b, "pytest_admin", "admin-pass")
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = [
                    executor.submit(submit, client_a, auth_a["csrf_token"], target_a_run_id),
                    executor.submit(submit, client_b, auth_b["csrf_token"], target_b_run_id),
                ]
                results = [future.result(timeout=15) for future in responses]

        assert sorted(response.status_code for response in results) == [200, 409]
        conflict = next(response for response in results if response.status_code == 409)
        assert conflict.json()["code"] == "invalid_state"
        assert factory.one(
            "SELECT count(*) FROM run_enrollments WHERE transfer_from_enrollment_id=%s",
            (source.entity_id,),
        )[0] == 1
        assert factory.one(
            "SELECT count(*) FROM run_enrollments WHERE employee_id=%s AND status='active'",
            (source.values["employee_id"],),
        )[0] == 1
        assert factory.one(
            "SELECT count(*) FROM audit_events WHERE action='learner.transfer' AND details->>'employee_id'=%s",
            (str(source.values["employee_id"]),),
        )[0] == 1
    finally:
        pool_a.closeall()
        pool_b.closeall()
