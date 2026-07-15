from datetime import date

from tests.test_api_auth import ORIGIN, client_for
from frontend_queries import learner_directory_rows


def _login(client, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def test_admin_searches_learners_with_stable_server_pagination(database_url, seed_ids, factory):
    _, first_run = factory.cohort_run()
    first = factory.onboard(first_run, full_name="Directory Alpha")
    _, second_run = factory.cohort_run()
    factory.onboard(second_run, full_name="Directory Beta")

    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_admin", "admin-pass")
            response = client.get("/api/learners", params={"q": "Directory", "page": 1, "page_size": 1})

        assert response.status_code == 200
        payload = response.json()
        assert payload["page"] == 1
        assert payload["page_size"] == 1
        assert payload["total"] == 2
        assert payload["sort"] == "full_name_asc_emp_code_asc"
        assert [item["full_name"] for item in payload["items"]] == ["Directory Alpha"]
        assert payload["items"][0]["employee_id"] == first.values["employee_id"]
    finally:
        pool.closeall()


def test_dashboard_keeps_viewer_out_of_hr_home(database_url, seed_ids):
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_viewer", "viewer-pass")
            viewer = client.get("/api/dashboard")
            forbidden = client.get("/api/learners")
            client.post("/api/auth/logout", headers={"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]})
            _login(client, "pytest_editor", "editor-pass")
            editor = client.get("/api/dashboard")

        assert viewer.status_code == 200
        assert viewer.json()["summary"]["active_employees"] >= 0
        assert viewer.json()["hr_home"] is None
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "forbidden"
        assert editor.status_code == 200
        assert editor.json()["hr_home"]["active_people"] >= 0
    finally:
        pool.closeall()


def test_editor_reads_learner_detail_history_and_safe_audit_summary(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Detail Learner")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_editor", "editor-pass")
            response = client.get(f"/api/learners/{employee_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["learner"]["employee_id"] == employee_id
        assert payload["learner"]["full_name"] == "Detail Learner"
        assert payload["learner"]["lifecycle"] == "active"
        assert len(payload["course_history"]) == 1
        assert payload["course_history"][0]["status"] == "active"
        assert payload["audit_summary"]
        assert {"created_at", "actor_username", "action"} == set(payload["audit_summary"][0])
        assert "details" not in response.text
    finally:
        pool.closeall()


def test_directory_filters_by_current_class(database_url, seed_ids, factory):
    first_cohort, first_run = factory.cohort_run()
    factory.onboard(first_run, full_name="Filtered One")
    _, second_run = factory.cohort_run()
    factory.onboard(second_run, full_name="Filtered Two")
    class_code = factory.one("SELECT class_code FROM cohorts WHERE cohort_id=%s", (first_cohort,))[0]

    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_admin", "admin-pass")
            response = client.get(
                "/api/learners",
                params={"q": "Filtered", "learning_status": "current", "class_code": class_code},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["full_name"] == "Filtered One"
    finally:
        pool.closeall()


def test_directory_item_matches_legacy_read_model(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Parity Learner")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        legacy = next(row for row in learner_directory_rows(pool) if row["employee_id"] == employee_id)
        with client:
            _login(client, "pytest_admin", "admin-pass")
            item = client.get("/api/learners", params={"q": "Parity Learner"}).json()["items"][0]

        for field in (
            "employee_id", "emp_code", "full_name", "employment_status",
            "business_unit_name", "job_role_name", "class_code", "course_name",
            "course_code", "enrollment_status", "entrance_level", "pic",
        ):
            assert item[field] == legacy[field]
    finally:
        pool.closeall()


def test_directory_empty_missing_and_invalid_states_are_stable(database_url, seed_ids):
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_admin", "admin-pass")
            empty = client.get("/api/learners", params={"q": "no-such-learner-987654"})
            missing = client.get("/api/learners/999999999")
            invalid = client.get("/api/learners", params={"page_size": 101, "learning_status": "maybe"})

        assert empty.status_code == 200 and empty.json()["items"] == [] and empty.json()["total"] == 0
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"
        assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_input"
        assert {"page_size", "learning_status"} <= set(invalid.json()["field_errors"])
    finally:
        pool.closeall()


def test_editor_updates_the_path_learner_profile_and_audit(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Profile Before")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            before = client.get(f"/api/learners/{employee_id}").json()["learner"]
            response = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": before["emp_code"],
                    "full_name": "Profile After",
                    "employment_status": "inactive",
                    "business_unit_id": before["business_unit_id"],
                    "job_role_id": before["job_role_id"],
                    "organization_valid_from": before["current_org_valid_from"],
                    "expected_org_valid_from": before["current_org_valid_from"],
                },
            )
            after = client.get(f"/api/learners/{employee_id}").json()

        assert response.status_code == 200
        assert response.json() == {"employee_id": employee_id, "org_history_action": "unchanged"}
        assert after["learner"]["full_name"] == "Profile After"
        assert after["learner"]["employment_status"] == "inactive"
        assert after["audit_summary"][0]["actor_username"] == "pytest_editor"
        assert after["audit_summary"][0]["action"] == "employee.upsert"
    finally:
        pool.closeall()


def test_profile_options_are_narrow_and_forbidden_to_viewer(database_url, seed_ids):
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_editor", "editor-pass")
            editor = client.get("/api/learners/profile-options")
            client.cookies.clear()
            _login(client, "pytest_viewer", "viewer-pass")
            viewer = client.get("/api/learners/profile-options")

        assert editor.status_code == 200
        assert set(editor.json()) == {"business_units", "job_roles"}
        assert editor.json()["business_units"] == sorted(
            editor.json()["business_units"], key=lambda item: item["name"].lower()
        )
        assert editor.json()["job_roles"] == sorted(
            editor.json()["job_roles"], key=lambda item: item["name"].lower()
        )
        assert viewer.status_code == 403 and viewer.json()["code"] == "forbidden"
    finally:
        pool.closeall()


def test_profile_update_rejects_non_editable_fields(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Protected Fields")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_admin", "admin-pass")
            learner = client.get(f"/api/learners/{employee_id}").json()["learner"]
            response = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": learner["emp_code"],
                    "full_name": "Should Not Save",
                    "employment_status": learner["employment_status"],
                    "business_unit_id": learner["business_unit_id"],
                    "job_role_id": learner["job_role_id"],
                    "organization_valid_from": learner["current_org_valid_from"],
                    "expected_org_valid_from": learner["current_org_valid_from"],
                    "active_enrollment_id": learner["active_enrollment_id"],
                    "audit_actor": "forged-user",
                },
            )
            after = client.get(f"/api/learners/{employee_id}").json()["learner"]

        assert response.status_code == 422 and response.json()["code"] == "invalid_input"
        assert {"active_enrollment_id", "audit_actor"} <= set(response.json()["field_errors"])
        assert after["full_name"] == "Protected Fields"
    finally:
        pool.closeall()


def test_stale_profile_update_rolls_back_all_fields(database_url, seed_ids, factory, conn, admin_svc):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Original Profile")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            stale = client.get(f"/api/learners/{employee_id}").json()["learner"]

            with conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO business_units(business_unit_name) VALUES('Concurrent BU') RETURNING business_unit_id")
                    concurrent_bu = cur.fetchone()[0]
                    cur.execute("INSERT INTO job_roles(job_role_name) VALUES('Concurrent Role') RETURNING job_role_id")
                    concurrent_role = cur.fetchone()[0]
            admin_svc.create_or_update_employee(
                stale["emp_code"],
                "Concurrent Profile",
                employment_status="active",
                business_unit_id=concurrent_bu,
                job_role_id=concurrent_role,
                valid_from=date(2026, 8, 2),
            )

            response = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": stale["emp_code"],
                    "full_name": "Stale Overwrite",
                    "employment_status": "inactive",
                    "business_unit_id": stale["business_unit_id"],
                    "job_role_id": stale["job_role_id"],
                    "organization_valid_from": stale["current_org_valid_from"],
                    "expected_org_valid_from": stale["current_org_valid_from"],
                },
            )
            after = client.get(f"/api/learners/{employee_id}").json()

        assert response.status_code == 409 and response.json()["code"] == "stale_profile"
        assert after["learner"]["full_name"] == "Concurrent Profile"
        assert after["learner"]["employment_status"] == "active"
        assert after["learner"]["business_unit_id"] == concurrent_bu
        assert [row["action"] for row in after["audit_summary"]].count("employee.upsert") == 1
    finally:
        pool.closeall()


def test_profile_path_cannot_overwrite_a_different_employee(database_url, seed_ids, factory):
    _, first_run = factory.cohort_run()
    first = factory.onboard(first_run, full_name="Identity One")
    _, second_run = factory.cohort_run()
    second = factory.onboard(second_run, full_name="Identity Two")

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_admin", "admin-pass")
            first_before = client.get(f"/api/learners/{first.values['employee_id']}").json()["learner"]
            second_before = client.get(f"/api/learners/{second.values['employee_id']}").json()["learner"]
            response = client.patch(
                f"/api/learners/{first.values['employee_id']}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": second_before["emp_code"],
                    "full_name": "Forged Overwrite",
                    "employment_status": first_before["employment_status"],
                    "business_unit_id": first_before["business_unit_id"],
                    "job_role_id": first_before["job_role_id"],
                    "organization_valid_from": first_before["current_org_valid_from"],
                    "expected_org_valid_from": first_before["current_org_valid_from"],
                },
            )
            first_after = client.get(f"/api/learners/{first.values['employee_id']}").json()["learner"]
            second_after = client.get(f"/api/learners/{second.values['employee_id']}").json()["learner"]

        assert response.status_code == 409 and response.json()["code"] == "identity_conflict"
        assert first_after["full_name"] == "Identity One"
        assert second_after["full_name"] == "Identity Two"
    finally:
        pool.closeall()


def test_missing_profile_reference_rolls_back_employee_update(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Reference Before")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            before = client.get(f"/api/learners/{employee_id}").json()["learner"]
            response = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": before["emp_code"],
                    "full_name": "Reference After",
                    "employment_status": "inactive",
                    "business_unit_id": 999999999,
                    "job_role_id": before["job_role_id"],
                    "organization_valid_from": before["current_org_valid_from"],
                    "expected_org_valid_from": before["current_org_valid_from"],
                },
            )
            after = client.get(f"/api/learners/{employee_id}").json()["learner"]

        assert response.status_code == 404 and response.json()["code"] == "not_found"
        assert after["full_name"] == "Reference Before"
        assert after["employment_status"] == "active"
    finally:
        pool.closeall()


def test_profile_update_requires_hr_role_and_csrf(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Protected Profile")
    employee_id = onboarded.values["employee_id"]

    pool, client = client_for(database_url)
    try:
        with client:
            admin_auth = _login(client, "pytest_admin", "admin-pass")
            learner = client.get(f"/api/learners/{employee_id}").json()["learner"]
            body = {
                "emp_code": learner["emp_code"],
                "full_name": learner["full_name"],
                "employment_status": learner["employment_status"],
                "business_unit_id": learner["business_unit_id"],
                "job_role_id": learner["job_role_id"],
                "organization_valid_from": learner["current_org_valid_from"],
                "expected_org_valid_from": learner["current_org_valid_from"],
            }
            no_csrf = client.patch(f"/api/learners/{employee_id}/profile", json=body)
            client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_auth["csrf_token"]})
            viewer_auth = _login(client, "pytest_viewer", "viewer-pass")
            viewer = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": viewer_auth["csrf_token"]},
                json=body,
            )

        assert no_csrf.status_code == 403 and no_csrf.json()["code"] == "csrf_rejected"
        assert viewer.status_code == 403 and viewer.json()["code"] == "forbidden"
    finally:
        pool.closeall()


def test_profile_org_change_preserves_enrollment_snapshots(database_url, seed_ids, factory, conn):
    _, course_run_id = factory.cohort_run()
    onboarded = factory.onboard(course_run_id, full_name="Organization Change")
    employee_id = onboarded.values["employee_id"]
    enrollment_id = onboarded.entity_id
    snapshot_before = factory.one(
        "SELECT business_unit_id_snapshot,job_role_id_snapshot FROM run_enrollments WHERE run_enrollment_id=%s",
        (enrollment_id,),
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO business_units(business_unit_name) VALUES('Profile New BU') RETURNING business_unit_id")
            new_bu = cur.fetchone()[0]
            cur.execute("INSERT INTO job_roles(job_role_name) VALUES('Profile New Role') RETURNING job_role_id")
            new_role = cur.fetchone()[0]

    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            before = client.get(f"/api/learners/{employee_id}").json()["learner"]
            response = client.patch(
                f"/api/learners/{employee_id}/profile",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": before["emp_code"],
                    "full_name": before["full_name"],
                    "employment_status": before["employment_status"],
                    "business_unit_id": new_bu,
                    "job_role_id": new_role,
                    "organization_valid_from": "2026-08-02",
                    "expected_org_valid_from": before["current_org_valid_from"],
                },
            )
            after = client.get(f"/api/learners/{employee_id}").json()

        assert response.status_code == 200 and response.json()["org_history_action"] == "changed"
        assert after["learner"]["business_unit_id"] == new_bu
        assert after["learner"]["job_role_id"] == new_role
        assert after["learner"]["current_org_valid_from"] == "2026-08-02"
        assert factory.one(
            "SELECT business_unit_id_snapshot,job_role_id_snapshot FROM run_enrollments WHERE run_enrollment_id=%s",
            (enrollment_id,),
        ) == snapshot_before
        assert after["audit_summary"][0]["actor_username"] == "pytest_editor"
        assert after["audit_summary"][0]["action"] == "employee.upsert"
    finally:
        pool.closeall()


def test_editor_starts_a_first_time_learner_from_authoritative_options(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run(capacity=3)
    factory.meeting_unit(course_run_id, 3, status="planned")
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            options = client.get("/api/learners/start-options")
            destination = next(item for item in options.json()["course_runs"] if item["course_run_id"] == course_run_id)
            response = client.post(
                "/api/learners/start",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": "API-START-001",
                    "expected_employee_id": None,
                    "full_name": "API First Learner",
                    "employment_status": "active",
                    "business_unit_id": seed_ids["bu"],
                    "job_role_id": seed_ids["role"],
                    "entrance_level_id": seed_ids["entrance_level"],
                    "course_run_id": course_run_id,
                    "joined_on": "2026-08-03",
                    "confirmed_start_session_number": destination["proposed_start_session_number"],
                },
            )
            detail = client.get(f"/api/learners/{response.json()['employee_id']}")
            duplicate_identity = client.post(
                "/api/learners/start",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": "API-START-001",
                    "expected_employee_id": None,
                    "full_name": "Wrong Existing Learner",
                    "business_unit_id": seed_ids["bu"],
                    "job_role_id": seed_ids["role"],
                    "entrance_level_id": seed_ids["entrance_level"],
                    "course_run_id": course_run_id,
                    "joined_on": "2026-08-03",
                    "confirmed_start_session_number": destination["proposed_start_session_number"],
                },
            )

        assert options.status_code == 200
        assert destination["proposed_start_session_number"] == 3
        assert destination["active_learners"] == 0
        assert response.status_code == 200
        assert response.json()["lifecycle"] == "first_time"
        assert response.json()["placement_action"] == "created"
        assert detail.json()["learner"]["active_course_run_id"] == course_run_id
        assert detail.json()["course_history"][0]["start_session_number"] == 3
        assert detail.json()["audit_summary"][0]["actor_username"] == "pytest_editor"
        assert detail.json()["audit_summary"][0]["action"] == "learner.onboard"
        assert duplicate_identity.status_code == 409
        assert duplicate_identity.json()["code"] == "identity_conflict"
        assert factory.one("SELECT full_name FROM employees WHERE emp_code='API-START-001'")[0] == "API First Learner"
    finally:
        pool.closeall()


def test_start_rejects_a_changed_session_proposal_and_rolls_back(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_admin", "admin-pass")
            options = client.get("/api/learners/start-options").json()
            stale = next(item for item in options["course_runs"] if item["course_run_id"] == course_run_id)
            factory.meeting_unit(course_run_id, 1, status="completed")
            response = client.post(
                "/api/learners/start",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "emp_code": "API-STALE-001",
                    "expected_employee_id": None,
                    "full_name": "Stale Proposal",
                    "business_unit_id": seed_ids["bu"],
                    "job_role_id": seed_ids["role"],
                    "entrance_level_id": seed_ids["entrance_level"],
                    "course_run_id": course_run_id,
                    "joined_on": "2026-08-03",
                    "confirmed_start_session_number": stale["proposed_start_session_number"],
                },
            )

        assert response.status_code == 409
        assert response.json()["code"] == "stale_proposal"
        assert factory.one("SELECT count(*) FROM employees WHERE emp_code='API-STALE-001'")[0] == 0
    finally:
        pool.closeall()


def test_start_requires_a_reasoned_capacity_override_and_audits_it(database_url, seed_ids, factory):
    cohort_id, course_run_id = factory.cohort_run(capacity=1)
    factory.onboard(course_run_id)
    pool, client = client_for(database_url)
    body = {
        "emp_code": "API-CAPACITY-001",
        "expected_employee_id": None,
        "full_name": "Capacity Learner",
        "business_unit_id": seed_ids["bu"],
        "job_role_id": seed_ids["role"],
        "entrance_level_id": seed_ids["entrance_level"],
        "course_run_id": course_run_id,
        "joined_on": "2026-08-03",
        "confirmed_start_session_number": 1,
    }
    try:
        with client:
            auth = _login(client, "pytest_editor", "editor-pass")
            rejected = client.post("/api/learners/start", headers={"X-CSRF-Token": auth["csrf_token"]}, json=body)
            approved = client.post(
                "/api/learners/start",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={**body, "capacity_override_reason": "HR approved overflow"},
            )

        assert rejected.status_code == 409
        assert rejected.json()["code"] == "capacity_exceeded"
        assert approved.status_code == 200
        override = factory.one(
            "SELECT reason, actor_user_id, resulting_active_learner_count FROM cohort_capacity_overrides WHERE cohort_id=%s",
            (cohort_id,),
        )
        assert override == ("HR approved overflow", seed_ids["editor"], 2)
    finally:
        pool.closeall()


def test_start_forbids_viewer_bad_csrf_and_non_input_fields(database_url, seed_ids, factory):
    _, course_run_id = factory.cohort_run()
    body = {
        "emp_code": "API-PROTECTED-START",
        "expected_employee_id": None,
        "full_name": "Protected Start",
        "business_unit_id": seed_ids["bu"],
        "job_role_id": seed_ids["role"],
        "entrance_level_id": seed_ids["entrance_level"],
        "course_run_id": course_run_id,
        "joined_on": "2026-08-03",
        "confirmed_start_session_number": 1,
    }
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client, "pytest_viewer", "viewer-pass")
            viewer_options = client.get("/api/learners/start-options")
            viewer_save = client.post("/api/learners/start", json=body)
            client.post("/api/auth/logout", headers={"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]})
            _login(client, "pytest_admin", "admin-pass")
            bad_csrf = client.post("/api/learners/start", json=body)
            protected = client.post(
                "/api/learners/start",
                headers={"X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"]},
                json={**body, "run_enrollment_id": 999, "audit_actor": "forged"},
            )

        assert viewer_options.status_code == 403
        assert viewer_save.status_code == 403
        assert bad_csrf.status_code == 403 and bad_csrf.json()["code"] == "csrf_rejected"
        assert protected.status_code == 422 and protected.json()["code"] == "invalid_input"
        assert factory.one("SELECT count(*) FROM employees WHERE emp_code='API-PROTECTED-START'")[0] == 0
    finally:
        pool.closeall()
