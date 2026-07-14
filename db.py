"""Database access helpers for the Streamlit app and service tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

import psycopg2
import psycopg2.extras
import psycopg2.pool


def normalize_conn_str(conn_str: str) -> str:
    if conn_str.startswith("postgres://"):
        return conn_str.replace("postgres://", "postgresql://", 1)
    return conn_str


def create_pool(conn_str: str, *, application_name: str = "english_class_app"):
    return psycopg2.pool.ThreadedConnectionPool(
        1,
        5,
        dsn=normalize_conn_str(conn_str),
        connect_timeout=5,
        application_name=application_name,
        options="-c statement_timeout=15000 -c idle_in_transaction_session_timeout=15000",
    )


@contextmanager
def pooled_connection(pool):
    conn = pool.getconn()
    close_conn = False
    try:
        yield conn
    except Exception:
        conn.rollback()
        close_conn = conn.closed != 0
        raise
    finally:
        pool.putconn(conn, close=close_conn)


def fetch_one(pool, query: str, params: Iterable[Any] | None = None):
    with pooled_connection(pool) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or [])
            return cur.fetchone()


def fetch_all(pool, query: str, params: Iterable[Any] | None = None):
    with pooled_connection(pool) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or [])
            return cur.fetchall()


def execute_one(pool, query: str, params: Iterable[Any] | None = None):
    with pooled_connection(pool) as conn:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params or [])
                return cur.fetchone()


def verify_canonical_schema(pool) -> None:
    required = [
        "app_users",
        "audit_events",
        "schema_migrations",
        "v_reporting_metric_definitions",
        "v_current_employee_state",
        "v_cohort_course_run_dashboard",
    ]
    placeholders = ", ".join(["%s"] * len(required))
    rows = fetch_all(
        pool,
        f"SELECT name, to_regclass(name) AS regclass FROM unnest(ARRAY[{placeholders}]) AS name",
        required,
    )
    missing = [row["name"] for row in rows if row["regclass"] is None]
    if missing:
        raise RuntimeError("Database setup is incomplete for canonical app runtime.")
