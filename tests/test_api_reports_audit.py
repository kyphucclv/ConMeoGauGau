import json

from tests.test_api_auth import ORIGIN, client_for


def _login(client, username="pytest_viewer", password="viewer-pass"):
    response=client.post("/api/auth/login",headers={"Origin":ORIGIN},json={"username":username,"password":password})
    assert response.status_code==200
    return response.json()


def test_viewer_runs_only_registered_paginated_reports_with_metric_definitions(database_url, factory):
    factory.cohort_run()
    pool,client=client_for(database_url)
    try:
        with client:
            _login(client)
            catalog=client.get("/api/reports")
            report=client.get("/api/reports/cohort_dashboard?page=1&page_size=1")
        assert catalog.status_code==200
        registered={item["key"]:item for item in catalog.json()["reports"]}
        assert "cohort_dashboard" in registered
        assert "course_run_id" in registered["cohort_dashboard"]["columns"]
        assert "average_attendance_ratio" in registered["cohort_dashboard"]["columns"]
        assert {item["metric_key"] for item in registered["cohort_dashboard"]["metric_definitions"]}=={"attendance_ratio","effective_exam_eligible"}
        assert report.status_code==200
        assert report.json()["page_size"]==1 and len(report.json()["items"])==1
        assert report.json()["total"]>=1
        assert set(report.json()["items"][0])==set(report.json()["columns"])
        assert isinstance(report.json()["items"][0]["course_run_id"], int)
    finally: pool.closeall()


def test_report_key_is_not_sql_and_limits_are_bounded(database_url):
    pool,client=client_for(database_url)
    try:
        with client:
            _login(client)
            invalid=client.get("/api/reports/not-a-registered-report")
            injection=client.get("/api/reports/cohort_dashboard%20UNION%20SELECT%201")
            oversized=client.get("/api/reports/cohort_dashboard?page_size=101")
        assert invalid.status_code==422 and invalid.json()["code"]=="invalid_input"
        assert injection.status_code==422 and injection.json()["message"]=="report key is not registered"
        assert oversized.status_code==422 and oversized.json()["code"]=="invalid_input"
    finally: pool.closeall()


def test_audit_history_is_admin_only_filtered_and_removes_sensitive_payload_keys(database_url, conn, seed_ids):
    with conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO audit_events(actor_user_id,actor_username,action,entity_type,entity_key,details)
                           VALUES(%s,'pytest_admin','pytest.sensitive','employee','777',%s::jsonb)
                           RETURNING audit_event_id""",
                        (seed_ids["admin"],json.dumps({
                            "safe":"visible","password_hash":"hidden","raw_query":"SELECT secret",
                            "session_id":"hidden","session_unit_ids":[41,42],
                            "nested":{"session_token":"hidden","reason":"visible"},
                        })))
            event_id=cur.fetchone()[0]
    pool,client=client_for(database_url)
    try:
        with client:
            _login(client,"pytest_viewer","viewer-pass")
            viewer=client.get("/api/audit-events")
        # Use fresh clients so each role check has an independent browser session.
        editor_pool,editor_client=client_for(database_url)
        admin_pool,admin_client=client_for(database_url)
        try:
            with editor_client:
                _login(editor_client,"pytest_editor","editor-pass")
                editor=editor_client.get("/api/audit-events")
            with admin_client:
                _login(admin_client,"pytest_admin","admin-pass")
                admin=admin_client.get("/api/audit-events?action=pytest.sensitive&entity_type=employee&actor_username=pytest_admin&page_size=10")
                oversized=admin_client.get("/api/audit-events?page_size=101")
            assert viewer.status_code==403 and editor.status_code==403
            assert admin.status_code==200
            assert oversized.status_code==422 and oversized.json()["code"]=="invalid_input"
            item=next(row for row in admin.json()["items"] if row["audit_event_id"]==event_id)
            assert item["details"]=={
                "safe":"visible","session_unit_ids":[41,42],"nested":{"reason":"visible"},
            }
            serialized=json.dumps(admin.json()).lower()
            assert "password_hash" not in serialized and "session_token" not in serialized
            assert "session_id" not in serialized and "raw_query" not in serialized
        finally:
            editor_pool.closeall();admin_pool.closeall()
    finally: pool.closeall()
