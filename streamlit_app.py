"""Canonical Streamlit entry point for the English Class admin app."""

from __future__ import annotations

import os

import streamlit as st

from auth import AppUser, UserAdminService, active_user_by_id, authenticate, bootstrap_first_admin, list_users
from db import create_pool, fetch_all, verify_canonical_schema
from frontend_workflows import render_operations
from reporting import REPORTS, metric_definitions, report_by_label, run_report
from services import CommandError


st.set_page_config(page_title="English Class Admin", layout="wide")


def configured_database_url() -> str:
    try:
        secret_conn = st.secrets.get("database", {}).get("url", "")
    except (FileNotFoundError, KeyError):
        secret_conn = ""
    return os.getenv("APP_DATABASE_URL", "") or secret_conn or os.getenv("DATABASE_URL", "")


@st.cache_resource(max_entries=3)
def cached_pool(conn_str: str):
    return create_pool(conn_str)


def current_user(pool) -> AppUser | None:
    user = st.session_state.get("user")
    if not user:
        return None
    active_user = active_user_by_id(pool, user["user_id"])
    if not active_user:
        st.session_state.pop("user", None)
        return None
    save_user(active_user)
    return active_user


def save_user(user: AppUser) -> None:
    st.session_state["user"] = {
        "user_id": user.user_id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
    }


def render_bootstrap(pool) -> None:
    st.warning("No app users found. Create the first admin account to start using the system.")
    with st.form("bootstrap_admin"):
        full_name = st.text_input("Full name")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        password_confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create admin", icon=":material/admin_panel_settings:")
    if submitted:
        if not full_name.strip() or not username.strip() or not password:
            st.error("Fill in all fields.")
        elif password != password_confirm:
            st.error("Passwords do not match.")
        else:
            try:
                bootstrap_first_admin(pool, username, full_name, password)
            except CommandError as error:
                st.error(error.message)
            else:
                st.success("Admin account created. You can now sign in.")
                st.rerun()
    st.stop()


def render_login(pool) -> None:
    st.title("English Class Admin")
    st.caption("Canonical reporting and administration on PostgreSQL.")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", icon=":material/login:")
    if submitted:
        user = authenticate(pool, username, password)
        if not user:
            st.error("Invalid username or password.")
        else:
            save_user(user)
            st.rerun()
    st.stop()


def render_reports(pool) -> None:
    st.subheader("Reports")
    selected_label = st.selectbox("Report", [report.label for report in REPORTS])
    report = report_by_label(selected_label)
    try:
        rows = run_report(pool, report)
    except Exception:
        st.error("Unable to load this report.")
        return

    st.caption(f"{len(rows)} rows")
    if rows:
        st.dataframe(rows)
    else:
        st.info("No rows found.")

    definitions = metric_definitions(pool, report.metric_keys)
    if definitions:
        with st.expander("Metric definitions"):
            st.dataframe(definitions)


def render_users(pool, actor: AppUser) -> None:
    st.subheader("User management")
    if actor.role != "admin":
        st.info("Only admins can manage app users.")
        return

    st.dataframe(list_users(pool))
    service = UserAdminService(pool, actor)

    with st.container(border=True):
        st.markdown("Create app user")
        with st.form("create_user"):
            full_name = st.text_input("Full name", key="new_user_full_name")
            username = st.text_input("Username", key="new_user_username")
            password = st.text_input("Password", type="password", key="new_user_password")
            role = st.selectbox("Role", ["editor", "viewer", "admin"], key="new_user_role")
            submitted = st.form_submit_button("Create user", icon=":material/person_add:")
        if submitted:
            try:
                service.create_user(username, full_name, password, role)
            except CommandError as error:
                st.error(error.message)
            else:
                st.success("User created.")
                st.rerun()

    active_users = [row["username"] for row in list_users(pool) if row["is_active"] and row["username"] != actor.username]
    with st.container(border=True):
        st.markdown("Deactivate app user")
        if not active_users:
            st.info("No other active users.")
            return
        with st.form("deactivate_user"):
            username = st.selectbox("Active user", active_users)
            submitted = st.form_submit_button("Deactivate", icon=":material/person_cancel:")
        if submitted:
            try:
                service.deactivate_user(username)
            except CommandError as error:
                st.error(error.message)
            else:
                st.success("User deactivated.")
                st.rerun()


def render_audit(pool, actor: AppUser) -> None:
    st.subheader("Audit events")
    if actor.role != "admin":
        st.info("Only admins can view audit events.")
        return
    rows = fetch_all(
        pool,
        """
        SELECT created_at, actor_username, action, entity_type, entity_key, details
        FROM audit_events
        ORDER BY created_at DESC
        LIMIT 300
        """,
    )
    if rows:
        st.dataframe(rows)
    else:
        st.info("No audit events found.")


def render_app() -> None:
    st.title("English Class Admin")
    conn_str = configured_database_url()
    if not conn_str:
        st.error("Database credentials are not configured.")
        st.stop()

    try:
        pool = cached_pool(conn_str)
        verify_canonical_schema(pool)
    except Exception:
        st.error("The application could not connect to the canonical database.")
        st.stop()

    users = list_users(pool)
    if not users:
        render_bootstrap(pool)

    user = current_user(pool)
    if not user:
        render_login(pool)

    st.sidebar.success(f"{user.full_name} ({user.role})")
    if st.sidebar.button("Sign out", icon=":material/logout:"):
        st.session_state.pop("user", None)
        st.rerun()

    operations_tab, reports_tab, users_tab, audit_tab = st.tabs(["Operations", "Reports", "Users", "Audit"], on_change="rerun")
    if operations_tab.open:
        with operations_tab:
            render_operations(pool, user)
    if reports_tab.open:
        with reports_tab:
            render_reports(pool)
    if users_tab.open:
        with users_tab:
            render_users(pool, user)
    if audit_tab.open:
        with audit_tab:
            render_audit(pool, user)


render_app()
