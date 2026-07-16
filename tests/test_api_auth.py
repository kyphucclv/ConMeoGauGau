import json
import logging

from fastapi.testclient import TestClient
from psycopg2.pool import PoolError

from api.main import Settings, create_app
from auth import AppUser, UserAdminService
from db import create_pool


ORIGIN = "http://testserver"


def client_for(database_url):
    pool = create_pool(database_url, application_name="pytest_api")
    app = create_app(Settings(database_url, ORIGIN, secure_cookie=False, serve_static=False), pool=pool)
    return pool, TestClient(app, raise_server_exceptions=False)


def test_health_login_refresh_csrf_and_logout(database_url, seed_ids):
    pool, client = client_for(database_url)
    try:
        with client:
            assert client.get("/api/health/live").status_code == 200
            assert client.get("/api/health/ready").status_code == 200
            assert client.get("/api/auth/me").status_code == 401
            login = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"username": "pytest_viewer", "password": "viewer-pass"})
            assert login.status_code == 200
            assert "HttpOnly" in login.headers["set-cookie"] and "SameSite=lax" in login.headers["set-cookie"]
            assert client.get("/api/auth/me").json()["user"]["role"] == "viewer"
            assert client.post("/api/auth/logout").status_code == 403
            assert client.post("/api/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]}).status_code == 204
            assert client.get("/api/auth/me").status_code == 401
    finally:
        pool.closeall()


def test_deactivated_user_loses_existing_session(database_url, seed_ids):
    pool, client = client_for(database_url)
    try:
        admin = AppUser(seed_ids["admin"], "pytest_admin", "Pytest Admin", "admin")
        username = "api_deactivate_user"
        UserAdminService(pool, admin).create_user(username, "API User", "api-pass", "viewer")
        with client:
            assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"username": username, "password": "api-pass"}).status_code == 200
            UserAdminService(pool, admin).deactivate_user(username)
            assert client.get("/api/auth/me").status_code == 401
            conn = pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT revocation_reason FROM app_sessions s JOIN app_users u ON u.user_id=s.user_id WHERE u.username=%s ORDER BY app_session_id DESC LIMIT 1", (username,))
                    assert cur.fetchone()[0] == "user_inactive"
            finally:
                conn.rollback()
                pool.putconn(conn)
    finally:
        pool.closeall()


def test_errors_are_stable_and_hide_exceptions(database_url):
    pool, client = client_for(database_url)
    try:
        @client.app.get("/api/test/boom")
        def boom():
            raise RuntimeError("database password must never leak")
        @client.app.get("/api/test/busy")
        def busy():
            raise PoolError("database URL must never leak")
        with client:
            bad = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={})
            assert bad.status_code == 422 and bad.json()["code"] == "invalid_input"
            response = client.get("/api/test/boom")
            assert response.status_code == 500
            assert "password" not in response.text
            assert response.json()["request_id"]
            busy_response = client.get("/api/test/busy")
            assert busy_response.status_code == 503
            assert busy_response.json()["code"] == "database_busy"
            assert "database url" not in busy_response.text.lower()
    finally:
        pool.closeall()


def test_login_is_same_origin_and_rate_limited(database_url):
    pool, client = client_for(database_url)
    try:
        with client:
            assert client.post("/api/auth/login", json={"username":"nobody","password":"wrong"}).status_code == 403
            for _ in range(5):
                assert client.post("/api/auth/login", headers={"Origin":ORIGIN}, json={"username":"nobody","password":"wrong"}).status_code == 401
            response = client.post("/api/auth/login", headers={"Origin":ORIGIN}, json={"username":"nobody","password":"wrong"})
            assert response.status_code == 429 and response.json()["code"] == "rate_limited"
    finally:
        pool.closeall()


def test_security_headers_and_cross_origin_preflight_are_fail_closed(database_url):
    pool = create_pool(database_url, application_name="pytest_api_security")
    app = create_app(Settings(database_url, "https://english-class.test", secure_cookie=True, serve_static=False), pool=pool)
    try:
        with TestClient(app) as client:
            response = client.get("/api/health/live")
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert response.headers["strict-transport-security"].startswith("max-age=31536000")

            preflight = client.options(
                "/api/auth/login",
                headers={
                    "Origin": "https://attacker.test",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert preflight.status_code == 405
            assert "access-control-allow-origin" not in preflight.headers
    finally:
        pool.closeall()


def test_access_log_is_structured_bounded_and_contains_no_request_secrets(database_url, caplog):
    pool, client = client_for(database_url)
    try:
        with caplog.at_level(logging.INFO, logger="english_class.access"):
            with client:
                login = client.post(
                    "/api/auth/login",
                    headers={"Origin": ORIGIN, "X-Request-ID": "invalid request id"},
                    json={"username": "pytest_viewer", "password": "viewer-pass"},
                )
                dashboard = client.get(
                    "/api/dashboard?do_not_log=this-query",
                    headers={"X-Request-ID": "production-check-1"},
                )
        assert login.status_code == 200 and dashboard.status_code == 200
        events = [json.loads(record.message) for record in caplog.records if record.name == "english_class.access"]
        dashboard_event = next(event for event in events if event["route"] == "/api/dashboard")
        assert dashboard_event["request_id"] == "production-check-1"
        assert dashboard_event["authenticated"] is True
        assert isinstance(dashboard_event["actor_user_id"], int)
        serialized = json.dumps(events).lower()
        assert "do_not_log" not in serialized
        assert "viewer-pass" not in serialized
        assert login.json()["csrf_token"].lower() not in serialized
        assert "english_class_session" not in serialized
    finally:
        pool.closeall()
