"""Phase 9 cutover rehearsal on disposable databases.

This does not mutate production.  It proves the cutover sequence using the
current workbook, migrations, canonical ETL, restricted roles, app smoke, and a
backup/restore rehearsal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from psycopg2.extensions import parse_dsn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import apply_migrations
from scripts.canonical_etl_v3 import run_canonical_etl
from scripts.phase4_integration_check import _database_url, recreate_database
from scripts.phase6_security_check import create_roles
from scripts.phase8_automated_uat import PG_DUMP, PG_RESTORE
from scripts.phase11_operational_issue_snapshot import (
    DEFAULT_JSON as PHASE11_ISSUE_JSON,
    DEFAULT_MARKDOWN as PHASE11_ISSUE_MARKDOWN,
    generate as generate_phase11_operational_issue_snapshot,
)
from scripts.stage_workbook import load_profile, profile_for_json, profile_workbook


DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_TEST_DB = "english_class_p9_rehearsal"
WORKBOOK = ROOT / "okok_FIXED_v2.xlsx"
PROTECTED_DATABASES = {"english_class", "postgres", "template0", "template1"}


def validate_disposable_target(database_url: str, db_name: str) -> None:
    target_name = parse_dsn(database_url).get("dbname", "")
    normalized = db_name.lower()
    if target_name != db_name:
        raise RuntimeError(f"Phase 9 target mismatch: URL database is {target_name!r}, expected {db_name!r}")
    if normalized in PROTECTED_DATABASES or not any(marker in normalized for marker in ("test", "rehearsal")):
        raise RuntimeError(f"Phase 9 refuses non-disposable database name: {db_name!r}")


def one(conn, sql: str, params: tuple = ()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def stage_current_workbook(database_url: str) -> dict:
    profile = profile_workbook(WORKBOOK)
    profile_output = ROOT / "docs" / "reviews" / "phase-9-workbook-profile.json"
    profile_output.write_text(
        json.dumps(profile_for_json(profile), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with psycopg2.connect(database_url) as conn:
        load_result = load_profile(conn, profile)
    return {
        "source_name": profile["source_name"],
        "source_checksum": profile["source_checksum"],
        "sheet_count": len(profile["sheets"]),
        "meaningful_rows": sum(sheet["meaningful_rows"] for sheet in profile["sheets"]),
        "staged_rows": sum(len(sheet["rows"]) for sheet in profile["sheets"]),
        "load_result": load_result,
        "profile_output": str(profile_output.relative_to(ROOT)),
    }


def summarize_database(database_url: str) -> dict:
    with psycopg2.connect(database_url) as conn:
        schema_versions = one(conn, "SELECT count(*) AS total FROM schema_migrations")["total"]
        canonical_batches = one(conn, "SELECT count(*) AS total FROM canonical_etl_batches WHERE status='completed'")["total"]
        open_issues = one(conn, "SELECT count(*) AS total FROM data_quality_issues WHERE status='open'")["total"]
        issue_outcomes = one(conn, "SELECT count(*) AS total FROM etl_source_row_outcomes WHERE outcome_type='issue'")["total"]
        employees = one(conn, "SELECT count(*) AS total FROM employees")["total"]
        enrollments = one(conn, "SELECT count(*) AS total FROM run_enrollments")["total"]
        attendance = one(conn, "SELECT count(*) AS total FROM attendance")["total"]
        reporting_rows = one(conn, "SELECT count(*) AS total FROM v_cohort_course_run_dashboard")["total"]
        operational_issues = one(conn, "SELECT count(*) AS total FROM v_operational_data_issues")["total"]
    return {
        "schema_versions": schema_versions,
        "completed_canonical_batches": canonical_batches,
        "open_quality_issues": open_issues,
        "issue_outcomes": issue_outcomes,
        "employees": employees,
        "run_enrollments": enrollments,
        "attendance_rows": attendance,
        "cohort_dashboard_rows": reporting_rows,
        "operational_data_issues": operational_issues,
    }


def streamlit_smoke(database_url: str) -> dict:
    os.environ["APP_DATABASE_URL"] = database_url
    with psycopg2.connect(database_url) as conn:
        restricted_user = one(conn, "SELECT current_user AS username")["username"]
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=12)
    app.run(timeout=12)
    assert not app.exception
    assert any("English Class Admin" in item.value for item in app.title)
    assert [tab.label for tab in app.tabs] == ["Operations", "Reports", "Audit"]
    assert all(button.label != "Sign in" for button in app.button)
    return {
        "database_user": restricted_user,
        "tabs": len(app.tabs),
        "errors": len(app.error),
        "exceptions": len(app.exception),
    }


def backup_restore(database_url: str, restored_db: str, maintenance_url: str) -> dict:
    if not PG_DUMP.exists() or not PG_RESTORE.exists():
        raise RuntimeError("PostgreSQL backup tools are not installed at the expected path")
    backup_path = ROOT / "backups" / "phase9_cutover_rehearsal.dump"
    backup_path.parent.mkdir(exist_ok=True)
    if backup_path.exists():
        backup_path.unlink()
    subprocess.run([str(PG_DUMP), "--format=custom", "--file", str(backup_path), database_url], check=True)
    recreate_database(maintenance_url, restored_db)
    restored_url = _database_url(restored_db, maintenance_url)
    subprocess.run([str(PG_RESTORE), "--dbname", restored_url, str(backup_path)], check=True)

    source_summary = summarize_database(database_url)
    restored_summary = summarize_database(restored_url)
    assert restored_summary["employees"] == source_summary["employees"]
    assert restored_summary["schema_versions"] == source_summary["schema_versions"]
    return {
        "backup_path": str(backup_path.relative_to(ROOT)),
        "backup_bytes": backup_path.stat().st_size,
        "restored_employees": restored_summary["employees"],
        "restored_schema_versions": restored_summary["schema_versions"],
    }


def main() -> None:
    db_name = os.getenv("PHASE9_TEST_DB", DEFAULT_TEST_DB)
    restored_db = f"{db_name}_restore"
    maintenance_url = os.getenv("PHASE9_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    database_url = _database_url(db_name, maintenance_url)
    validate_disposable_target(database_url, db_name)

    recreate_database(maintenance_url, db_name)
    roles = create_roles(maintenance_url, db_name)
    apply_migrations(roles["migration"].url(db_name))
    staging = stage_current_workbook(database_url)
    etl = run_canonical_etl(database_url)
    idempotent = run_canonical_etl(database_url)
    smoke = streamlit_smoke(roles["app"].url(db_name))
    summary = summarize_database(database_url)
    phase11_snapshot = generate_phase11_operational_issue_snapshot(
        database_url, PHASE11_ISSUE_JSON, PHASE11_ISSUE_MARKDOWN
    )
    restore = backup_restore(database_url, restored_db, maintenance_url)

    result = {
        "database": db_name,
        "source_checksum": staging["source_checksum"],
        "staged_rows": staging["staged_rows"],
        "canonical_etl_status": etl["status"],
        "canonical_etl_idempotent_status": idempotent["status"],
        "schema_versions": summary["schema_versions"],
        "employees": summary["employees"],
        "run_enrollments": summary["run_enrollments"],
        "attendance_rows": summary["attendance_rows"],
        "open_quality_issues": summary["open_quality_issues"],
        "issue_outcomes": summary["issue_outcomes"],
        "operational_data_issues": summary["operational_data_issues"],
        "phase11_operational_issue_snapshot": phase11_snapshot,
        "restricted_roles": sorted(role.name for role in roles.values()),
        "streamlit_smoke": smoke,
        "backup_restore": restore,
        "profile_output": staging["profile_output"],
    }

    print("Phase 9 cutover rehearsal passed.")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
