"""Shared pytest fixtures: disposable canonical database and seeded services.

The suite gives developers a fast, always-runnable regression net for
services.py business rules.  It creates one disposable database per test
session (migrations only, no workbook ETL), seeds minimal reference data,
and hands each test real BusinessService instances over real connections.
"""

from __future__ import annotations

import itertools
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import bootstrap_first_admin, hash_password
from db import create_pool
from migrate import apply_migrations
from scripts.phase4_integration_check import _database_url, recreate_database
from services import BusinessService

DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
TEST_DB = os.getenv("ENGLISH_CLASS_PYTEST_DB", "english_class_pytest")


def _ensure_pgpassword() -> None:
    """Scheduled shells may lack PGPASSWORD; fall back to the user registry."""
    if os.environ.get("PGPASSWORD") or sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            os.environ["PGPASSWORD"] = str(winreg.QueryValueEx(key, "PGPASSWORD")[0])
    except OSError:
        pass


@pytest.fixture(scope="session")
def database_url() -> str:
    _ensure_pgpassword()
    maintenance_url = os.getenv("ENGLISH_CLASS_TEST_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    recreate_database(maintenance_url, TEST_DB)
    url = _database_url(TEST_DB, maintenance_url)
    apply_migrations(url)
    return url


@pytest.fixture(scope="session")
def seed_ids(database_url: str) -> dict[str, int]:
    """Bootstrap app users and minimal reference rows once per session."""
    pool = create_pool(database_url, application_name="pytest_bootstrap")
    try:
        admin_id = bootstrap_first_admin(pool, "pytest_admin", "Pytest Admin", "admin-pass")
    finally:
        pool.closeall()
    ids: dict[str, int] = {"admin": admin_id}
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO app_users(username, password_hash, full_name, role)
                       VALUES ('pytest_editor', %s, 'Pytest Editor', 'editor'),
                              ('pytest_viewer', %s, 'Pytest Viewer', 'viewer')
                       RETURNING user_id, username""",
                    (hash_password("editor-pass"), hash_password("viewer-pass")),
                )
                for user_id, username in cur.fetchall():
                    ids[username.replace("pytest_", "")] = user_id
                cur.execute(
                    "INSERT INTO business_units(business_unit_name) VALUES('Pytest BU') RETURNING business_unit_id"
                )
                ids["bu"] = cur.fetchone()[0]
                cur.execute("INSERT INTO job_roles(job_role_name) VALUES('Pytest Role') RETURNING job_role_id")
                ids["role"] = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO courses(course_code, course_name, expected_units, attendance_threshold_ratio)
                       VALUES ('PT-A', 'Pytest Course A', 4, 0.750)
                       RETURNING course_id"""
                )
                ids["course"] = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO levels(level_name, numeric_value, sequence_order)
                       VALUES ('Pytest Entrance', 1.0, 1), ('Pytest Final', 2.0, 2)
                       RETURNING level_id, level_name"""
                )
                rows = cur.fetchall()
                ids["entrance_level"] = min(rows)[0]
                ids["final_level"] = max(rows)[0]
    finally:
        conn.close()
    return ids


@pytest.fixture
def conn(database_url: str):
    connection = psycopg2.connect(database_url)
    yield connection
    connection.close()


@pytest.fixture
def admin_svc(conn, seed_ids) -> BusinessService:
    return BusinessService(conn, seed_ids["admin"])


@pytest.fixture
def editor_svc(conn, seed_ids) -> BusinessService:
    return BusinessService(conn, seed_ids["editor"])


@pytest.fixture
def viewer_svc(conn, seed_ids) -> BusinessService:
    return BusinessService(conn, seed_ids["viewer"])


_unique = itertools.count(1)


@pytest.fixture
def factory(conn, seed_ids, admin_svc):
    """Builders for per-test cohorts, runs, meetings, and learners."""

    class Factory:
        BASE_START = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)

        def unique(self) -> int:
            return next(_unique)

        def cohort_run(self, *, capacity: int = 10) -> tuple[int, int]:
            n = self.unique()
            result = admin_svc.create_class_course_run(
                class_code=f"PT{n:03d}",
                display_name=f"Pytest Class {n}",
                course_id=seed_ids["course"],
                start_date=date(2026, 8, 1),
                capacity=capacity,
                pic_label="Pytest Team",
            )
            return result.values["cohort_id"], result.entity_id

        def meeting_unit(self, course_run_id: int, sequence: int, *, unit_type: str = "normal",
                         day_offset: int = 0, status: str = "planned") -> tuple[int, int]:
            result = admin_svc.create_meeting_with_units(
                course_run_id,
                self.BASE_START + timedelta(days=day_offset),
                60,
                sequence,
                unit_type=unit_type,
                status=status,
            )
            return result.entity_id, result.values["session_unit_ids"][0]

        def onboard(self, course_run_id: int, *, emp_code: str | None = None, **overrides):
            n = self.unique()
            params = dict(
                emp_code=emp_code or f"9{n:05d}",
                full_name=f"Pytest Learner {n}",
                business_unit_id=seed_ids["bu"],
                job_role_id=seed_ids["role"],
                entrance_level_id=seed_ids["entrance_level"],
                course_run_id=course_run_id,
                joined_on=date(2026, 8, 1),
            )
            params.update(overrides)
            return admin_svc.onboard_learner(**params)

        def one(self, sql: str, params: tuple = ()):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    return Factory()
