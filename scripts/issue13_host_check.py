"""Fail-closed target-host readiness probe for the React/FastAPI cutover."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psycopg2
import psycopg2.extras


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SCHEMA_VERSION = "020_app_sessions"


def validate_origin(origin: str) -> tuple[str, int]:
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("APP_ORIGIN must be an absolute HTTPS origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("APP_ORIGIN must not contain credentials, a path, query, or fragment")
    return parsed.hostname, parsed.port or 443


def connection_budget(*, max_connections: int, reserved_connections: int,
                      current_connections: int, workers: int, pool_max: int) -> dict[str, int | bool]:
    configured = workers * pool_max
    available = max_connections - reserved_connections - current_connections
    return {
        "max_connections": max_connections,
        "reserved_connections": reserved_connections,
        "current_connections": current_connections,
        "configured_app_max": configured,
        "available_before_start": available,
        "passes": configured <= available,
    }


def database_evidence(database_url: str, *, workers: int, pool_max: int) -> dict[str, object]:
    connection = psycopg2.connect(database_url, connect_timeout=5, application_name="issue13_host_check")
    try:
        with connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT current_user AS db_user,current_database() AS db_name,
                              role.rolsuper,role.rolcreatedb,role.rolcreaterole,
                              has_schema_privilege(current_user,'public','CREATE') AS can_create_schema,
                              current_setting('max_connections')::int AS max_connections,
                              current_setting('superuser_reserved_connections')::int AS reserved_connections,
                              (SELECT count(*)::int FROM pg_stat_activity) AS current_connections
                       FROM pg_roles role WHERE role.rolname=current_user"""
                )
                row = cursor.fetchone()
                cursor.execute("SELECT version FROM schema_migrations ORDER BY applied_at DESC,version DESC LIMIT 1")
                schema = cursor.fetchone()
                cursor.execute("SELECT to_regclass('app_sessions') IS NOT NULL AS sessions_table")
                sessions = cursor.fetchone()
        restricted = not row["rolsuper"] and not row["rolcreatedb"] and not row["rolcreaterole"] and not row["can_create_schema"]
        budget = connection_budget(
            max_connections=row["max_connections"],
            reserved_connections=row["reserved_connections"],
            current_connections=row["current_connections"],
            workers=workers,
            pool_max=pool_max,
        )
        return {
            "database": row["db_name"],
            "role": row["db_user"],
            "restricted_role": restricted,
            "schema_version": schema["version"] if schema else None,
            "sessions_table": bool(sessions["sessions_table"]),
            "connection_budget": budget,
        }
    finally:
        connection.close()


def origin_evidence(origin: str, *, minimum_certificate_days: int) -> dict[str, object]:
    host, port = validate_origin(origin)
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=5) as raw_socket:
        with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
            certificate = tls_socket.getpeercert()
            expires = datetime.strptime(certificate["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_remaining = (expires - datetime.now(timezone.utc)).days
    statuses: dict[str, int] = {}
    for path in ("/api/health/live", "/api/health/ready"):
        request = Request(origin.rstrip("/") + path, headers={"User-Agent": "english-class-readiness/1"})
        with urlopen(request, timeout=10, context=context) as response:
            statuses[path] = response.status
    return {
        "host": host,
        "port": port,
        "certificate_expires_at": expires.isoformat(),
        "certificate_days_remaining": days_remaining,
        "certificate_window_passes": days_remaining >= minimum_certificate_days,
        "health_statuses": statuses,
    }


def readiness(*, skip_origin_probe: bool, workers: int, pool_max: int,
              minimum_certificate_days: int) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    origin = os.getenv("APP_ORIGIN", "")
    database_url = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
    try:
        host, port = validate_origin(origin)
        origin_contract: dict[str, object] = {"origin": origin, "host": host, "port": port}
    except ValueError as exc:
        origin_contract = {"origin": origin or None}
        failures.append(str(exc))
    secure_cookie = os.getenv("APP_COOKIE_SECURE", "").lower() == "true"
    if not secure_cookie:
        failures.append("APP_COOKIE_SECURE must be true")
    static_build = (ROOT / "web" / "dist" / "index.html").is_file()
    if not static_build:
        failures.append("web/dist production build is missing")
    database: dict[str, object] | None = None
    if not database_url:
        failures.append("APP_DATABASE_URL is required")
    else:
        try:
            database = database_evidence(database_url, workers=workers, pool_max=pool_max)
            if not database["restricted_role"]:
                failures.append("application database role is privileged")
            if database["schema_version"] != REQUIRED_SCHEMA_VERSION or not database["sessions_table"]:
                failures.append("database schema is not at the required application version")
            if not database["connection_budget"]["passes"]:
                failures.append("PostgreSQL connection budget is insufficient")
        except Exception as exc:
            failures.append(f"database readiness probe failed ({type(exc).__name__})")
    tls: dict[str, object] | None = None
    if not skip_origin_probe and "host" in origin_contract:
        try:
            tls = origin_evidence(origin, minimum_certificate_days=minimum_certificate_days)
            if not tls["certificate_window_passes"]:
                failures.append("TLS certificate renewal window is too short")
            if set(tls["health_statuses"].values()) != {200}:
                failures.append("target health endpoints did not both return 200")
        except Exception as exc:
            failures.append(f"HTTPS origin probe failed ({type(exc).__name__})")
    evidence = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "origin_contract": origin_contract,
        "secure_cookie": secure_cookie,
        "static_build": static_build,
        "workers": workers,
        "pool_max_per_worker": pool_max,
        "database": database,
        "tls": tls,
        "origin_probe_skipped": skip_origin_probe,
        "status": "pass" if not failures else "fail",
        "failures": failures,
    }
    return evidence, failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-origin-probe", action="store_true", help="Validate configuration and DB only; never use as final TLS evidence.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--pool-max", type=int, default=5)
    parser.add_argument("--minimum-certificate-days", type=int, default=30)
    args = parser.parse_args()
    if args.workers < 1 or args.pool_max < 1 or args.minimum_certificate_days < 1:
        raise SystemExit("workers, pool maximum, and certificate days must be positive")
    evidence, failures = readiness(
        skip_origin_probe=args.skip_origin_probe,
        workers=args.workers,
        pool_max=args.pool_max,
        minimum_certificate_days=args.minimum_certificate_days,
    )
    print(json.dumps(evidence, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
