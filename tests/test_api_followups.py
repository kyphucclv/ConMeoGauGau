from tests.test_api_auth import ORIGIN, client_for


def _login(client, username="pytest_editor", password="editor-pass"):
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def test_editor_filters_and_pages_operational_followups(database_url, factory):
    _, run_id = factory.cohort_run()
    factory.onboard(run_id, full_name="Follow-up Learner")
    _, unit_id = factory.meeting_unit(run_id, 1, status="completed")
    pool, client = client_for(database_url)
    try:
        with client:
            _login(client)
            response = client.get(
                "/api/follow-ups/operational?severity=high&workflow=Attendance&"
                "issue_code=incomplete_attendance_roster&page=1&page_size=1"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1 and body["page_size"] == 1
        assert body["total"] >= 1
        assert len(body["items"]) == 1
        assert body["items"][0]["issue_code"] == "incomplete_attendance_roster"
        assert body["items"][0]["entity_key"] == str(unit_id)
        assert "audit" not in body["items"][0]
    finally:
        pool.closeall()


def test_quality_issue_resolution_preserves_original_details_and_named_history(database_url, factory, conn):
    marker = f"followup-{factory.unique()}"
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO data_quality_issues(
                       issue_code,entity_type,entity_key,source_sheet,source_row_number,details
                   ) VALUES('pytest_followup','employee',%s,'TEST',17,%s::jsonb)
                   RETURNING issue_id""",
                (marker, '{"original":"retained"}'),
            )
            issue_id = cur.fetchone()[0]
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client)
            resolved = client.post(
                f"/api/follow-ups/quality-issues/{issue_id}/resolution",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={"status": "resolved", "note": "Owner verified the source row"},
            )
            ledger = client.get(
                "/api/follow-ups/quality-issues?status=resolved&issue_code=pytest_followup"
            )

        assert resolved.status_code == 200
        item = next(row for row in ledger.json()["items"] if row["issue_id"] == issue_id)
        assert item["details"] == {"original": "retained"}
        assert item["source_sheet"] == "TEST" and item["source_row_number"] == 17
        assert item["resolved_by_username"] == "pytest_editor"
        assert item["resolution_note"] == "Owner verified the source row"
        assert factory.one(
            "SELECT actor_username FROM audit_events WHERE action='quality_issue.resolve' AND entity_key=%s",
            (str(issue_id),),
        )[0] == "pytest_editor"
    finally:
        pool.closeall()


def test_followup_permissions_csrf_and_forged_fields_are_rejected(database_url, factory):
    pool, client = client_for(database_url)
    try:
        with client:
            viewer = _login(client, "pytest_viewer", "viewer-pass")
            viewer_read = client.get("/api/follow-ups/operational")
            viewer_action = client.post(
                "/api/follow-ups/actions/unknown-placement",
                headers={"X-CSRF-Token": viewer["csrf_token"]},
                json={"confirmed": True, "reason": "forbidden"},
            )
            client.post("/api/auth/logout", headers={"X-CSRF-Token": viewer["csrf_token"]})
            editor = _login(client)
            editor_admin_action = client.post(
                "/api/follow-ups/actions/unknown-placement",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={"confirmed": True, "reason": "forbidden"},
            )
            missing_csrf = client.post(
                "/api/follow-ups/quality-issues/999999/resolution",
                json={"status": "resolved", "note": "missing csrf"},
            )
            forged = client.post(
                "/api/follow-ups/quality-issues/999999/resolution",
                headers={"X-CSRF-Token": editor["csrf_token"]},
                json={
                    "status": "resolved",
                    "note": "attempted forgery",
                    "resolved_by_username": "forged",
                },
            )
            invalid_scope = client.get("/api/follow-ups/operational?severity=critical")

        assert viewer_read.status_code == 403
        assert viewer_action.status_code == 403
        assert editor_admin_action.status_code == 403
        assert missing_csrf.status_code == 403
        assert forged.status_code == 422 and forged.json()["code"] == "invalid_input"
        assert invalid_scope.status_code == 422 and invalid_scope.json()["code"] == "invalid_input"
    finally:
        pool.closeall()


def test_admin_approves_one_legacy_exception_without_inventing_attendance(database_url, factory, seed_ids):
    _, run_id = factory.cohort_run()
    factory.onboard(run_id, full_name="Legacy Missing Roster")
    _, unit_id = factory.meeting_unit(run_id, 1, status="completed")
    before = factory.one("SELECT count(*) FROM attendance")[0]
    pool, client = client_for(database_url)
    try:
        with client:
            auth = _login(client, "pytest_admin", "admin-pass")
            response = client.post(
                "/api/follow-ups/actions/legacy-attendance-exception",
                headers={"X-CSRF-Token": auth["csrf_token"]},
                json={
                    "session_unit_id": unit_id,
                    "confirmed": True,
                    "reason": "Owner confirmed the historical source is unavailable",
                },
            )

        assert response.status_code == 200
        assert factory.one("SELECT count(*) FROM attendance")[0] == before
        assert factory.one(
            """SELECT reason,approved_by_user_id FROM attendance_roster_legacy_exceptions
               WHERE session_unit_id=%s""",
            (unit_id,),
        ) == ("Owner confirmed the historical source is unavailable", seed_ids["admin"])
    finally:
        pool.closeall()
