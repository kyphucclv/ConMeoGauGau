"""Phase 6 security and application architecture integration gate."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import AppUser, UserAdminService, hash_password
from db import create_pool, fetch_one
from migrate import apply_migrations
from scripts.phase4_integration_check import _database_url, recreate_database
from services import BusinessService, CommandError


DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_TEST_DB = "english_class_p6_test"


@dataclass(frozen=True)
class DbRole:
    name: str
    password: str

    def url(self, db_name: str) -> str:
        return f"postgresql://{self.name}:{self.password}@localhost:5432/{db_name}"


def role_name(db_name: str, suffix: str) -> str:
    return f"{db_name}_{suffix}"


def create_roles(maintenance_url: str, db_name: str) -> dict[str, DbRole]:
    roles = {
        "migration": DbRole(role_name(db_name, "migration"), secrets.token_urlsafe(18)),
        "app": DbRole(role_name(db_name, "app"), secrets.token_urlsafe(18)),
        "readonly": DbRole(role_name(db_name, "readonly"), secrets.token_urlsafe(18)),
    }
    conn = psycopg2.connect(maintenance_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for role in roles.values():
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role.name,))
                if cur.fetchone():
                    cur.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(
                            sql.Identifier(role.name)
                        ),
                        (role.password,),
                    )
                else:
                    cur.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(
                            sql.Identifier(role.name)
                        ),
                        (role.password,),
                    )
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}, {}").format(
                    sql.Identifier(db_name),
                    sql.Identifier(roles["migration"].name),
                    sql.Identifier(roles["app"].name),
                    sql.Identifier(roles["readonly"].name),
                )
            )
    finally:
        conn.close()

    db_conn = psycopg2.connect(_database_url(db_name, maintenance_url))
    db_conn.autocommit = True
    try:
        with db_conn.cursor() as cur:
            migration = sql.Identifier(roles["migration"].name)
            app = sql.Identifier(roles["app"].name)
            readonly = sql.Identifier(roles["readonly"].name)
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}, {}").format(migration, app, readonly))
            cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(migration))
            cur.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}, {}").format(app, readonly))
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(migration, app)
            )
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                        "GRANT USAGE, SELECT ON SEQUENCES TO {}").format(migration, app)
            )
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}").format(
                    migration, readonly
                )
            )
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                        "GRANT USAGE, SELECT ON SEQUENCES TO {}").format(migration, readonly)
            )
            cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(app))
            cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(app))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(readonly))
            cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(readonly))
    finally:
        db_conn.close()
    return roles


def expect_db_error(fn) -> None:
    try:
        fn()
    except psycopg2.Error:
        return
    raise AssertionError("expected PostgreSQL permission error")


def expect_command_error(code: str, fn) -> None:
    try:
        fn()
    except CommandError as exc:
        if exc.code != code:
            raise AssertionError(f"expected {code}, got {exc.code}") from exc
        return
    raise AssertionError(f"expected CommandError {code}")


def try_sql(database_url: str, sql: str) -> None:
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    finally:
        conn.close()


def seed_app_users(database_url: str) -> dict[str, int]:
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_users(username, password_hash, full_name, role)
                    VALUES
                        ('phase6_admin', %s, 'Phase 6 Admin', 'admin'),
                        ('phase6_editor', %s, 'Phase 6 Editor', 'editor'),
                        ('phase6_viewer', %s, 'Phase 6 Viewer', 'viewer')
                    RETURNING user_id, username
                    """,
                    (hash_password("admin-pass"), hash_password("editor-pass"), hash_password("viewer-pass")),
                )
                return {username: user_id for user_id, username in cur.fetchall()}
    finally:
        conn.close()


def assert_no_runtime_secret_ui() -> None:
    streamlit_app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    forbidden = ["PostgreSQL connection string", "st.exception", "use_container_width"]
    for text in forbidden:
        if text in streamlit_app:
            raise AssertionError(f"forbidden runtime UI/source pattern found: {text}")


def run_gate(database_url: str, db_name: str, roles: dict[str, DbRole]) -> dict[str, object]:
    seed_ids = seed_app_users(database_url)

    app_url = roles["app"].url(db_name)
    readonly_url = roles["readonly"].url(db_name)
    migration_url = roles["migration"].url(db_name)

    try_sql(migration_url, "ALTER TABLE employees ADD COLUMN phase6_migration_probe integer")
    try_sql(migration_url, "ALTER TABLE employees DROP COLUMN phase6_migration_probe")

    expect_db_error(lambda: try_sql(app_url, "CREATE TABLE phase6_app_should_not_create(id int)"))
    expect_db_error(lambda: try_sql(app_url, "ALTER TABLE employees ADD COLUMN phase6_forbidden int"))
    expect_db_error(lambda: try_sql(app_url, "DROP TABLE employees"))
    expect_db_error(lambda: try_sql(readonly_url, "INSERT INTO app_users(username, password_hash, full_name, role) VALUES('nope','x','Nope','viewer')"))

    try_sql(app_url, "SELECT count(*) FROM v_current_employee_state")
    try_sql(app_url, "SELECT count(*) FROM v_operational_data_issues")
    try_sql(readonly_url, "SELECT count(*) FROM v_reporting_metric_definitions")
    try_sql(readonly_url, "SELECT count(*) FROM v_operational_data_issues")

    app_pool = create_pool(app_url, application_name="phase6_app_role_test")
    viewer_conn = psycopg2.connect(app_url)
    editor_conn = psycopg2.connect(app_url)
    try:
        viewer_service = BusinessService(viewer_conn, seed_ids["phase6_viewer"])
        expect_command_error("forbidden", lambda: viewer_service.create_cohort("P6-VIEW", "Viewer forbidden"))

        editor_service = BusinessService(editor_conn, seed_ids["phase6_editor"])
        expect_command_error("forbidden", lambda: editor_service.override_exam_eligibility(9999, True, "forbidden"))

        editor_actor = AppUser(seed_ids["phase6_editor"], "phase6_editor", "Phase 6 Editor", "editor")
        user_admin = UserAdminService(app_pool, editor_actor)
        expect_command_error("forbidden", lambda: user_admin.create_user("phase6_nope", "Nope", "x", "viewer"))

        admin_actor = AppUser(seed_ids["phase6_admin"], "phase6_admin", "Phase 6 Admin", "admin")
        admin_user_service = UserAdminService(app_pool, admin_actor)
        created_user_id = admin_user_service.create_user("phase6_created", "Created User", "created-pass", "viewer")
        audit = fetch_one(
            app_pool,
            "SELECT count(*) AS total FROM audit_events WHERE action = 'app_user.create' AND entity_key = 'phase6_created'",
        )
        assert audit["total"] == 1
    finally:
        viewer_conn.close()
        editor_conn.close()
        app_pool.closeall()

    assert_no_runtime_secret_ui()

    return {
        "app_role_ddl_denied": True,
        "migration_role_alter_allowed": True,
        "readonly_insert_denied": True,
        "viewer_service_mutation_denied": True,
        "editor_user_admin_denied": True,
        "editor_eligibility_override_denied": True,
        "admin_user_created": created_user_id,
    }


def main() -> None:
    db_name = os.getenv("PHASE6_TEST_DB", DEFAULT_TEST_DB)
    maintenance_url = os.getenv("PHASE6_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    database_url = os.getenv("PHASE6_DATABASE_URL", _database_url(db_name, maintenance_url))

    recreate_database(maintenance_url, db_name)
    roles = create_roles(maintenance_url, db_name)
    apply_migrations(roles["migration"].url(db_name))
    result = run_gate(database_url, db_name, roles)

    print("Phase 6 security gate passed.")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
