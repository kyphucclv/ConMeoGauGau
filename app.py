import base64
import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from datetime import date, datetime

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

st.set_page_config(page_title="English Class Admin", layout="wide")

DEFAULT_CONN = os.getenv(
    "DATABASE_URL",
    "",
)

REPORT_QUERIES = {
    "Dashboard overview": "SELECT * FROM v_dashboard_overview;",
    "Dashboard by course": "SELECT * FROM v_dashboard_by_course;",
    "Attendance counts": "SELECT * FROM v_att_count LIMIT 300;",
    "Progress by business unit": "SELECT * FROM v_progress_by_bu;",
    "Data quality summary": "SELECT * FROM v_data_quality_summary ORDER BY status, issue_type;",
    "Enrollment detail": "SELECT * FROM v_enrollment_detail LIMIT 300;",
    "Students": "SELECT * FROM students ORDER BY full_name LIMIT 300;",
    "Enrollments": "SELECT * FROM enrollments ORDER BY start_date DESC NULLS LAST LIMIT 300;",
    "Attendance log": "SELECT * FROM attendance_log ORDER BY session_date DESC, attendance_id DESC LIMIT 300;",
    "Open data quality issues": "SELECT issue_type, entity_type, entity_key, details, created_at FROM data_quality_issues WHERE status = 'open' ORDER BY created_at DESC LIMIT 300;",
}


def normalize_conn_str(conn_str: str) -> str:
    if conn_str.startswith("postgres://"):
        return conn_str.replace("postgres://", "postgresql://", 1)
    return conn_str


@st.cache_resource(max_entries=5)
def get_pool(conn_str: str):
    return psycopg2.pool.ThreadedConnectionPool(
        1,
        5,
        dsn=normalize_conn_str(conn_str),
        connect_timeout=5,
        application_name="english_class_admin",
    )


@contextmanager
def get_conn(conn_str: str):
    pool = get_pool(conn_str)
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


def ensure_app_schema(conn_str: str) -> None:
    with get_conn(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT to_regclass('app_users'),
                       to_regclass('schema_migrations'),
                       to_regclass('class_sessions'),
                       to_regclass('data_quality_issues')
                """
            )
            if any(value is None for value in cur.fetchone()):
                raise RuntimeError(
                    "Database setup is incomplete. Run setup.ps1 for a new database "
                    "or python migrate.py <connection-uri> for an existing database."
                )


def hash_password(password: str) -> str:
    iterations = 150000
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def fetch_one(conn_str: str, query: str, params=None):
    with get_conn(conn_str) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or [])
            return cur.fetchone()


def fetch_all(conn_str: str, query: str, params=None):
    with get_conn(conn_str) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or [])
            return cur.fetchall()


def execute_write(conn_str: str, query: str, params=None, audit=None):
    with get_conn(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or [])
            if audit:
                cur.execute(
                    """
                    INSERT INTO audit_log (actor_username, action, entity_type, entity_key, details)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        audit["actor_username"],
                        audit["action"],
                        audit["entity_type"],
                        audit["entity_key"],
                        json.dumps(audit["details"]),
                    ),
                )


def get_reference_data(conn_str: str):
    return {
        "levels": fetch_all(conn_str, "SELECT level_name FROM level_helper ORDER BY numeric_value, level_name"),
        "courses": fetch_all(conn_str, "SELECT course_name FROM course_plan ORDER BY course_name"),
        "classes": fetch_all(conn_str, "SELECT class_code, course_name FROM class_offerings ORDER BY class_code, course_name"),
        "students": fetch_all(conn_str, "SELECT emp_code, full_name FROM students ORDER BY full_name"),
    }


def current_user():
    return st.session_state.get("user")


def has_role(*roles):
    user = current_user()
    return bool(user and user["role"] in roles)


def render_data_table(rows):
    if rows:
        st.dataframe(rows, width="stretch")
    else:
        st.info("No data found.")


def bootstrap_first_admin(conn_str: str):
    user_count = fetch_one(conn_str, "SELECT COUNT(*) AS total FROM app_users")
    if user_count["total"] > 0:
        return

    st.warning("No app users found. Create the first admin account to start using the system.")
    with st.form("bootstrap_admin"):
        full_name = st.text_input("Full name")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        password_confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create admin")
    if submitted:
        if not full_name or not username or not password:
            st.error("Fill in all fields.")
        elif password != password_confirm:
            st.error("Passwords do not match.")
        else:
            execute_write(
                conn_str,
                """
                INSERT INTO app_users (username, password_hash, full_name, role)
                VALUES (%s, %s, %s, 'admin')
                """,
                (username.strip(), hash_password(password), full_name.strip()),
                audit={
                    "actor_username": username.strip(),
                    "action": "bootstrap_admin",
                    "entity_type": "app_user",
                    "entity_key": username.strip(),
                    "details": {"role": "admin"},
                },
            )
            st.success("Admin account created. You can now sign in.")
            st.rerun()
    st.stop()


def login_panel(conn_str: str):
    st.title("English Class Admin")
    st.write("Long-term admin app for data management, input, and reporting on top of PostgreSQL.")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        user = fetch_one(
            conn_str,
            """
            SELECT username, full_name, role, password_hash, is_active
            FROM app_users
            WHERE username = %s
            """,
            (username.strip(),),
        )
        if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
            st.error("Invalid username or password.")
        else:
            st.session_state["user"] = {
                "username": user["username"],
                "full_name": user["full_name"],
                "role": user["role"],
            }
            st.rerun()


def render_reports(conn_str: str, role: str):
    st.subheader("Reports")
    report_name = st.selectbox("Choose report", list(REPORT_QUERIES.keys()))
    show_sql = st.checkbox("Show SQL", value=False)
    selected_query = REPORT_QUERIES[report_name]
    if show_sql:
        st.code(selected_query)
    try:
        rows = fetch_all(conn_str, selected_query)
        st.caption(f"{len(rows)} rows")
        render_data_table(rows)
    except Exception as error:
        st.error("Unable to run query.")
        st.exception(error)


def render_students(conn_str: str, refs):
    st.subheader("Students")
    search = st.text_input("Search by name or emp_code")
    query = """
        SELECT emp_code, full_name, bu, role, status,
               derived_current_course AS current_course,
               entrance_level,
               derived_current_level AS current_level,
               derived_latest_class_code AS latest_class_code,
               derived_progress_category AS progress_category
        FROM v_student_current
    """
    params = []
    if search.strip():
        query += " WHERE emp_code ILIKE %s OR full_name ILIKE %s"
        like_text = f"%{search.strip()}%"
        params.extend([like_text, like_text])
    query += " ORDER BY full_name LIMIT 300"
    render_data_table(fetch_all(conn_str, query, params))

    if not has_role("admin", "editor"):
        st.info("Viewer role can browse students but cannot edit them.")
        return

    with st.expander("Add student"):
        with st.form("add_student"):
            emp_code = st.text_input("Emp code")
            full_name = st.text_input("Full name")
            bu = st.text_input("BU")
            job_role = st.text_input("Role")
            status = st.selectbox("Status", ["Active", "Inactive", "Waiting for class"])
            entrance_level = st.selectbox("Entrance level", [""] + [row["level_name"] for row in refs["levels"]])
            current_level = st.selectbox("Current level", [""] + [row["level_name"] for row in refs["levels"]])
            remark = st.text_area("Remark")
            submitted = st.form_submit_button("Create student")
        if submitted:
            execute_write(
                conn_str,
                """
                INSERT INTO students
                (emp_code, full_name, bu, role, status, entrance_level, current_level, remark)
                VALUES (%s, %s, %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), %s)
                """,
                (emp_code.strip(), full_name.strip(), bu.strip() or None, job_role.strip() or None, status, entrance_level, current_level, remark.strip() or None),
                audit={
                    "actor_username": current_user()["username"],
                    "action": "create",
                    "entity_type": "student",
                    "entity_key": emp_code.strip(),
                    "details": {"full_name": full_name.strip(), "status": status},
                },
            )
            st.success("Student created.")
            st.rerun()

    with st.expander("Update student status"):
        student_labels = [f'{row["emp_code"]} | {row["full_name"]}' for row in refs["students"]]
        if not student_labels:
            st.info("No students available.")
            return
        with st.form("update_student"):
            selected = st.selectbox("Student", student_labels)
            status = st.selectbox("New status", ["Active", "Inactive", "Waiting for class"], key="status_update")
            remark = st.text_area("Remark update")
            submitted = st.form_submit_button("Update student")
        if submitted:
            emp_code = selected.split(" | ", 1)[0]
            execute_write(
                conn_str,
                """
                UPDATE students
                SET status = %s,
                    remark = %s
                WHERE emp_code = %s
                """,
                (status, remark.strip() or None, emp_code),
                audit={
                    "actor_username": current_user()["username"],
                    "action": "update",
                    "entity_type": "student",
                    "entity_key": emp_code,
                    "details": {"status": status},
                },
            )
            st.success("Student updated.")
            st.rerun()


def render_enrollments(conn_str: str, refs):
    st.subheader("Enrollments")
    class_filter = st.selectbox(
        "Filter by class/course",
        ["All"] + [f'{row["class_code"]} | {row["course_name"]}' for row in refs["classes"]],
    )
    query = """
        SELECT emp_code, class_code, course_name, entrance_level, final_level, start_date, first_class_start_date
        FROM enrollments
    """
    params = []
    if class_filter != "All":
        class_code, course_name = class_filter.split(" | ", 1)
        query += " WHERE class_code = %s AND course_name = %s"
        params.extend([class_code, course_name])
    query += " ORDER BY start_date DESC NULLS LAST, class_code, emp_code LIMIT 300"
    render_data_table(fetch_all(conn_str, query, params))

    if not has_role("admin", "editor"):
        st.info("Viewer role can browse enrollments but cannot edit them.")
        return

    with st.expander("Add enrollment"):
        with st.form("add_enrollment"):
            student_label = st.selectbox("Student", [f'{row["emp_code"]} | {row["full_name"]}' for row in refs["students"]])
            class_label = st.selectbox("Class/course", [f'{row["class_code"]} | {row["course_name"]}' for row in refs["classes"]])
            entrance_level = st.selectbox("Entrance level", [""] + [row["level_name"] for row in refs["levels"]])
            final_level = st.selectbox("Final level", [""] + [row["level_name"] for row in refs["levels"]])
            use_dates = st.checkbox("Set dates now", value=False)
            start_date = st.date_input("Start date", value=date.today(), disabled=not use_dates)
            first_class_start_date = st.date_input("First class start date", value=date.today(), disabled=not use_dates)
            set_as_current = st.checkbox("Set as current enrollment", value=True)
            submitted = st.form_submit_button("Create enrollment")
        if submitted:
            emp_code = student_label.split(" | ", 1)[0]
            class_code, course_name = class_label.split(" | ", 1)
            values = (
                emp_code,
                class_code,
                course_name,
                entrance_level,
                final_level,
                start_date if use_dates else None,
                first_class_start_date if use_dates else None,
            )
            with get_conn(conn_str) as conn:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO enrollments
                                (emp_code, class_code, course_name, entrance_level,
                                 final_level, start_date, first_class_start_date)
                            VALUES (%s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), %s, %s)
                            RETURNING enrollment_id
                            """,
                            values,
                        )
                        enrollment_id = cur.fetchone()[0]
                        if set_as_current:
                            cur.execute(
                                """
                                UPDATE students
                                SET current_enrollment_id = %s,
                                    current_course = %s,
                                    latest_class_code = %s,
                                    latest_course_name = %s
                                WHERE emp_code = %s
                                """,
                                (enrollment_id, course_name, class_code, course_name, emp_code),
                            )
                        cur.execute(
                            """
                            INSERT INTO audit_log
                                (actor_username, action, entity_type, entity_key, details)
                            VALUES (%s, 'create', 'enrollment', %s, %s::jsonb)
                            """,
                            (
                                current_user()["username"],
                                f"{emp_code}:{class_code}:{course_name}",
                                json.dumps({
                                    "class_code": class_code,
                                    "course_name": course_name,
                                    "set_as_current": set_as_current,
                                }),
                            ),
                        )
            st.success("Enrollment created.")
            st.rerun()


def render_attendance(conn_str: str, refs):
    st.subheader("Attendance")
    student_search = st.text_input("Filter by emp_code")
    query = """
        SELECT attendance_id, class_code, course_name, emp_code, session_order, session_date, status
        FROM attendance_log
    """
    params = []
    if student_search.strip():
        query += " WHERE emp_code ILIKE %s"
        params.append(f"%{student_search.strip()}%")
    query += " ORDER BY session_date DESC, attendance_id DESC LIMIT 300"
    render_data_table(fetch_all(conn_str, query, params))

    if not has_role("admin", "editor"):
        st.info("Viewer role can browse attendance but cannot add new records.")
        return

    with st.expander("Add attendance record"):
        with st.form("add_attendance"):
            student_label = st.selectbox("Student", [f'{row["emp_code"]} | {row["full_name"]}' for row in refs["students"]], key="attendance_student")
            class_label = st.selectbox("Class/course", [f'{row["class_code"]} | {row["course_name"]}' for row in refs["classes"]], key="attendance_class")
            session_order = st.number_input("Session order", min_value=1, step=1)
            session_date = st.datetime_input("Session date and time", value=datetime.now())
            status = st.selectbox("Status", ["Present", "Absent"])
            submitted = st.form_submit_button("Create attendance")
        if submitted:
            emp_code = student_label.split(" | ", 1)[0]
            class_code, course_name = class_label.split(" | ", 1)
            with get_conn(conn_str) as conn:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO class_sessions
                                (class_code, course_name, starts_at, session_order)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (class_code, course_name, starts_at)
                            DO UPDATE SET session_order = COALESCE(
                                class_sessions.session_order,
                                EXCLUDED.session_order
                            )
                            RETURNING session_id
                            """,
                            (class_code, course_name, session_date, int(session_order)),
                        )
                        session_id = cur.fetchone()[0]
                        cur.execute(
                            """
                            SELECT enrollment_id
                            FROM enrollments
                            WHERE emp_code = %s AND class_code = %s AND course_name = %s
                            """,
                            (emp_code, class_code, course_name),
                        )
                        enrollment = cur.fetchone()
                        enrollment_id = enrollment[0] if enrollment else None
                        cur.execute(
                            """
                            INSERT INTO attendance_log
                                (session_id, enrollment_id, class_code, course_name,
                                 emp_code, session_order, session_date, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (class_code, course_name, emp_code, session_order)
                            DO UPDATE SET
                                session_id = EXCLUDED.session_id,
                                enrollment_id = EXCLUDED.enrollment_id,
                                session_date = EXCLUDED.session_date,
                                status = EXCLUDED.status
                            """,
                            (
                                session_id,
                                enrollment_id,
                                class_code,
                                course_name,
                                emp_code,
                                int(session_order),
                                session_date,
                                status,
                            ),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log
                                (actor_username, action, entity_type, entity_key, details)
                            VALUES (%s, 'upsert', 'attendance', %s, %s::jsonb)
                            """,
                            (
                                current_user()["username"],
                                f"{emp_code}:{class_code}:{course_name}:{int(session_order)}",
                                json.dumps({
                                    "status": status,
                                    "session_date": str(session_date),
                                    "has_enrollment": enrollment_id is not None,
                                }),
                            ),
                        )
            st.success("Attendance created.")
            st.rerun()


def render_users(conn_str: str):
    if not has_role("admin"):
        st.info("Only admins can manage app users.")
        return

    st.subheader("User management")
    render_data_table(fetch_all(conn_str, "SELECT username, full_name, role, is_active, created_at FROM app_users ORDER BY username"))

    with st.expander("Create app user"):
        with st.form("create_user"):
            full_name = st.text_input("Full name", key="new_user_full_name")
            username = st.text_input("Username", key="new_user_username")
            password = st.text_input("Password", type="password", key="new_user_password")
            role = st.selectbox("Role", ["editor", "viewer", "admin"], key="new_user_role")
            submitted = st.form_submit_button("Create user")
        if submitted:
            execute_write(
                conn_str,
                """
                INSERT INTO app_users (username, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s)
                """,
                (username.strip(), hash_password(password), full_name.strip(), role),
                audit={
                    "actor_username": current_user()["username"],
                    "action": "create",
                    "entity_type": "app_user",
                    "entity_key": username.strip(),
                    "details": {"role": role},
                },
            )
            st.success("User created.")
            st.rerun()

    with st.expander("Deactivate user"):
        users = fetch_all(conn_str, "SELECT username FROM app_users WHERE is_active = TRUE ORDER BY username")
        with st.form("deactivate_user"):
            username = st.selectbox("Active user", [row["username"] for row in users])
            submitted = st.form_submit_button("Deactivate")
        if submitted:
            execute_write(
                conn_str,
                "UPDATE app_users SET is_active = FALSE, updated_at = NOW() WHERE username = %s",
                (username,),
                audit={
                    "actor_username": current_user()["username"],
                    "action": "deactivate",
                    "entity_type": "app_user",
                    "entity_key": username,
                    "details": {},
                },
            )
            st.success("User deactivated.")
            st.rerun()


def render_audit(conn_str: str):
    if not has_role("admin"):
        st.info("Only admins can view the audit log.")
        return

    st.subheader("Audit log")
    rows = fetch_all(
        conn_str,
        """
        SELECT created_at, actor_username, action, entity_type, entity_key, details
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT 300
        """,
    )
    render_data_table(rows)


def main():
    st.title("English Class Admin")
    st.write("Manage data, input records, and reporting for the PostgreSQL-based English class system.")

    try:
        secret_conn = st.secrets.get("database", {}).get("url", "")
    except (FileNotFoundError, KeyError):
        secret_conn = ""
    configured_conn = DEFAULT_CONN or secret_conn
    conn_string = configured_conn or st.sidebar.text_input(
        "PostgreSQL connection string",
        type="password",
        help="Prefer DATABASE_URL or .streamlit/secrets.toml for long-term use.",
    )
    if not conn_string:
        st.error("Enter a PostgreSQL connection string in the sidebar.")
        return

    try:
        ensure_app_schema(conn_string)
        bootstrap_first_admin(conn_string)
    except Exception as error:
        st.error("Unable to connect or initialize app tables.")
        st.exception(error)
        return

    user = current_user()
    if not user:
        login_panel(conn_string)
        return

    st.sidebar.success(f'{user["full_name"]} ({user["role"]})')
    if st.sidebar.button("Sign out"):
        st.session_state.pop("user", None)
        st.rerun()

    refs = get_reference_data(conn_string)
    tabs = st.tabs(
        ["Reports", "Students", "Enrollments", "Attendance", "Users", "Audit"],
        on_change="rerun",
    )
    renderers = (
        lambda: render_reports(conn_string, user["role"]),
        lambda: render_students(conn_string, refs),
        lambda: render_enrollments(conn_string, refs),
        lambda: render_attendance(conn_string, refs),
        lambda: render_users(conn_string),
        lambda: render_audit(conn_string),
    )
    for tab, render in zip(tabs, renderers):
        if tab.open:
            with tab:
                render()


if __name__ == "__main__":
    main()
