from tests.test_api_auth import ORIGIN, client_for
from frontend_queries import learner_directory_rows


def _login(client, username: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


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
