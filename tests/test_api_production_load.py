from concurrent.futures import ThreadPoolExecutor
import math
import socket
from threading import Barrier, Thread
import time
import uuid

import httpx
import psycopg2
import uvicorn

from api.main import Settings, create_app
from auth import hash_password
from db import create_pool, pooled_connection


CONCURRENCY = 20


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _wait_until_ready(origin: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(origin + "/api/health/ready", timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    raise AssertionError("production-style test server did not become ready")


def _seed_load_fixtures(database_url: str) -> list[tuple[str, int, int]]:
    suffix = uuid.uuid4().hex[:8]
    password_hash = hash_password("load-pass")
    fixtures: list[tuple[str, int, int]] = []
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                for index in range(CONCURRENCY):
                    username = f"load_{suffix}_{index}"
                    cursor.execute(
                        """INSERT INTO app_users(username,password_hash,full_name,role)
                           VALUES(%s,%s,%s,'editor')""",
                        (username, password_hash, f"Load User {index}"),
                    )
                    issue_ids = []
                    for scenario in ("burst", "measured"):
                        cursor.execute(
                            """INSERT INTO data_quality_issues(issue_code,entity_type,entity_key,details)
                               VALUES('issue13_load','employee',%s,'{}'::jsonb)
                               RETURNING issue_id""",
                            (f"{suffix}:{scenario}:{index}",),
                        )
                        issue_ids.append(cursor.fetchone()[0])
                    fixtures.append((username, issue_ids[0], issue_ids[1]))
    finally:
        connection.close()
    return fixtures


def test_twenty_session_http_load_meets_latency_and_returns_every_connection(database_url):
    fixtures = _seed_load_fixtures(database_url)
    pool = create_pool(database_url, application_name="issue13_load",)
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    app = create_app(Settings(database_url, origin, secure_cookie=False, serve_static=False), pool=pool)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_until_ready(origin)
        barrier = Barrier(CONCURRENCY)

        def burst_flow(fixture: tuple[str, int, int]) -> tuple[dict[str, str], str, float, float]:
            username, issue_id, _ = fixture
            with httpx.Client(base_url=origin, timeout=10) as client:
                barrier.wait()
                login = client.post(
                    "/api/auth/login",
                    headers={"Origin": origin},
                    json={"username": username, "password": "load-pass"},
                )
                assert login.status_code == 200
                started = time.perf_counter()
                dashboard = client.get("/api/dashboard")
                read_seconds = time.perf_counter() - started
                assert dashboard.status_code == 200
                assert client.get("/api/reports/not-registered").status_code == 422
                started = time.perf_counter()
                resolved = client.post(
                    f"/api/follow-ups/quality-issues/{issue_id}/resolution",
                    headers={"X-CSRF-Token": login.json()["csrf_token"]},
                    json={"status": "resolved", "note": "Issue 13 load verification"},
                )
                command_seconds = time.perf_counter() - started
                assert resolved.status_code == 200
                return dict(client.cookies), login.json()["csrf_token"], read_seconds, command_seconds

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            burst_results = list(executor.map(burst_flow, fixtures))

        burst_read_p95 = _p95([result[2] for result in burst_results])
        burst_command_p95 = _p95([result[3] for result in burst_results])
        print(
            f"issue13_burst sessions={CONCURRENCY} read_p95_ms={burst_read_p95 * 1000:.2f} "
            f"command_p95_ms={burst_command_p95 * 1000:.2f}"
        )

        measured_concurrency = 10
        measured_barrier = Barrier(measured_concurrency)

        def measured_flow(index: int) -> tuple[float, float]:
            cookies, csrf_token, _, _ = burst_results[index]
            issue_id = fixtures[index][2]
            with httpx.Client(base_url=origin, cookies=cookies, timeout=10) as client:
                measured_barrier.wait()
                started = time.perf_counter()
                dashboard = client.get("/api/dashboard")
                read_seconds = time.perf_counter() - started
                assert dashboard.status_code == 200
                started = time.perf_counter()
                resolved = client.post(
                    f"/api/follow-ups/quality-issues/{issue_id}/resolution",
                    headers={"X-CSRF-Token": csrf_token},
                    json={"status": "resolved", "note": "Issue 13 measured verification"},
                )
                command_seconds = time.perf_counter() - started
                assert resolved.status_code == 200
                return read_seconds, command_seconds

        with ThreadPoolExecutor(max_workers=measured_concurrency) as executor:
            measured_results = list(executor.map(measured_flow, range(measured_concurrency)))
        read_p95 = _p95([result[0] for result in measured_results])
        command_p95 = _p95([result[1] for result in measured_results])
        print(
            f"issue13_measured sessions={measured_concurrency} read_p95_ms={read_p95 * 1000:.2f} "
            f"command_p95_ms={command_p95 * 1000:.2f}"
        )
        assert read_p95 < 1.0
        assert command_p95 < 2.0

        try:
            with pooled_connection(pool):
                raise RuntimeError("exercise rollback and connection return")
        except RuntimeError:
            pass

        acquired = [pool.getconn() for _ in range(5)]
        try:
            assert all(connection.closed == 0 for connection in acquired)
        finally:
            for connection in acquired:
                connection.rollback()
                pool.putconn(connection)

        connection = psycopg2.connect(database_url)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM data_quality_issues WHERE issue_code='issue13_load' AND status='resolved'")
                assert cursor.fetchone()[0] == CONCURRENCY + measured_concurrency
                cursor.execute("SELECT count(*) FROM audit_events WHERE action='quality_issue.resolve' AND details->>'note'='Issue 13 load verification'")
                assert cursor.fetchone()[0] == CONCURRENCY
                cursor.execute("SELECT count(*) FROM audit_events WHERE action='quality_issue.resolve' AND details->>'note'='Issue 13 measured verification'")
                assert cursor.fetchone()[0] == measured_concurrency
        finally:
            connection.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        pool.closeall()
