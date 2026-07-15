from fastapi.testclient import TestClient

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
        with client:
            bad = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={})
            assert bad.status_code == 422 and bad.json()["code"] == "invalid_input"
            response = client.get("/api/test/boom")
            assert response.status_code == 500
            assert "password" not in response.text
            assert response.json()["request_id"]
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
