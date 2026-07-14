"""Canonical Streamlit entry point for the English Class admin app."""

from __future__ import annotations

import os

import streamlit as st

from auth import AppUser, ensure_local_admin
from db import create_pool, fetch_all, verify_canonical_schema
from frontend_workflows import render_operations
from reporting import REPORTS, metric_definitions, report_by_label, run_report


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

    user = ensure_local_admin(pool)
    st.sidebar.success(f"{user.full_name} ({user.role})")

    operations_tab, reports_tab, audit_tab = st.tabs(["Operations", "Reports", "Audit"], on_change="rerun")
    if operations_tab.open:
        with operations_tab:
            render_operations(pool, user)
    if reports_tab.open:
        with reports_tab:
            render_reports(pool)
    if audit_tab.open:
        with audit_tab:
            render_audit(pool, user)


render_app()
