"""Canonical Streamlit entry point for the English Class admin app."""

from __future__ import annotations

import os

import streamlit as st

from auth import AppUser, active_user_by_id, authenticate
from db import create_pool, verify_canonical_schema
import frontend_queries as queries
from frontend_workflows import render_operations
from reporting import REPORTS, metric_definitions, report_by_label, run_report


st.set_page_config(page_title="English class HR workspace", page_icon=":material/school:", layout="wide")


def configured_database_url() -> str:
    try:
        secret_conn = st.secrets.get("database", {}).get("url", "")
    except (FileNotFoundError, KeyError):
        secret_conn = ""
    return os.getenv("APP_DATABASE_URL", "") or secret_conn or os.getenv("DATABASE_URL", "")


@st.cache_resource(max_entries=3)
def cached_pool(conn_str: str):
    return create_pool(conn_str)


def operations_snapshot(pool) -> dict:
    return queries.application_snapshot(pool)


def render_app_header(pool, user: AppUser) -> None:
    with st.sidebar:
        st.badge(user.role.title(), icon=":material/verified_user:", color="blue")
        st.caption(user.full_name)
        if st.button("Sign out", icon=":material/logout:"):
            st.session_state.pop("actor_user_id", None)
            st.rerun()

    st.title("English class HR workspace")

    snapshot = operations_snapshot(pool)
    with st.container(horizontal=True):
        st.metric("Employees", snapshot["active_employees"], border=True)
        st.metric("Currently learning", snapshot["active_learners"], border=True)
        st.metric("Open classes", snapshot["open_course_runs"], border=True)
        st.metric("Items to check", snapshot["operational_issues"], border=True,
                  help="Data that needs an HR look — open the Follow-ups area.")
        st.metric("Urgent", snapshot["high_issues"], border=True, delta_color="inverse",
                  help="High-priority items inside 'Items to check'.")
        st.metric("Logged issues", snapshot["open_quality_issues"], border=True,
                  help="Imported or manually logged data-quality issues still open.")


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
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No rows found.")

    definitions = metric_definitions(pool, report.metric_keys)
    if definitions:
        with st.expander("Metric definitions"):
            st.dataframe(definitions, hide_index=True)


def render_audit(pool, actor: AppUser) -> None:
    st.subheader("Audit events")
    if actor.role != "admin":
        st.info("Only admins can view audit events.")
        return
    rows = queries.audit_event_rows(pool)
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No audit events found.")


def render_sign_in(pool) -> None:
    st.title("English class HR workspace")
    st.subheader("Sign in")
    with st.form("sign_in", border=True):
        username = st.text_input("Username", key="auth_username")
        password = st.text_input("Password", type="password", key="auth_password")
        submitted = st.form_submit_button(
            "Sign in",
            type="primary",
            icon=":material/login:",
        )
    if submitted:
        user = authenticate(pool, username, password)
        if user is None:
            st.error("Username or password is incorrect.")
        else:
            st.session_state["actor_user_id"] = user.user_id
            st.rerun()


def render_app() -> None:
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

    actor_user_id = st.session_state.get("actor_user_id")
    user = active_user_by_id(pool, actor_user_id) if actor_user_id else None
    if user is None:
        st.session_state.pop("actor_user_id", None)
        render_sign_in(pool)
        return
    render_app_header(pool, user)

    workspace_tab, reports_tab, audit_tab = st.tabs(
        [":material/home_work: HR workspace", ":material/table_chart: Reports", ":material/history: Audit"],
        on_change="rerun",
    )
    if workspace_tab.open:
        with workspace_tab:
            render_operations(pool, user)
    if reports_tab.open:
        with reports_tab:
            render_reports(pool)
    if audit_tab.open:
        with audit_tab:
            render_audit(pool, user)


render_app()
