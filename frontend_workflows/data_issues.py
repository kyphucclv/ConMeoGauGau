"""Operational data-issue inbox, owner decisions, and logged issues.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import (
    ISSUE_WORKFLOW_AREAS,
    _open_operation_section,
    options,
    safe_submit,
    selected_id,
)


def _operational_issue_rows(pool) -> list[dict]:
    return queries.operational_issue_rows(pool)


def _issue_filter_options(rows: list[dict], key: str) -> list[str]:
    return ["All"] + sorted({row[key] for row in rows if row.get(key)})


def _filtered_operational_issues(rows: list[dict], severity: str, workflow: str, issue_code: str) -> list[dict]:
    return [
        row for row in rows
        if (severity == "All" or row["severity"] == severity.lower())
        and (workflow == "All" or row["workflow"] == workflow)
        and (issue_code == "All" or row["issue_code"] == issue_code)
    ]


def render_data_issues_workspace(pool, actor: AppUser) -> None:
    st.subheader("Follow-ups")
    st.caption("Data the app flagged for an HR check. Nothing here blocks daily work.")
    rows = _operational_issue_rows(pool)
    high_count = sum(1 for row in rows if row["severity"] == "high")
    warning_count = sum(1 for row in rows if row["severity"] == "warning")
    workflow_count = len({row["workflow"] for row in rows})
    with st.container(horizontal=True):
        st.metric("Total items", len(rows), border=True)
        st.metric("Urgent", high_count, border=True)
        st.metric("Warnings", warning_count, border=True)
        st.metric("Areas involved", workflow_count, border=True)

    st.session_state.setdefault("data_issues_mode", "To check")
    mode = st.segmented_control(
        "Data issue workflow",
        ["To check", "Bulk fixes (admin)", "Logged issues"],
        key="data_issues_mode",
    )
    if mode == "Bulk fixes (admin)":
        render_operational_decision_actions(pool, actor, rows)
        return
    if mode == "Logged issues":
        render_logged_quality_issues(pool, actor)
        return

    if rows:
        with st.container(horizontal=True, vertical_alignment="bottom"):
            severity_filter = st.segmented_control(
                "Severity",
                ["All", "High", "Warning"],
                default="All",
                key="issue_severity_filter",
            )
            workflow_filter = st.selectbox("Workflow", _issue_filter_options(rows, "workflow"), key="issue_workflow_filter")
            code_filter = st.selectbox("Issue code", _issue_filter_options(rows, "issue_code"), key="issue_code_filter")
        filtered_rows = _filtered_operational_issues(rows, severity_filter, workflow_filter, code_filter)
        if filtered_rows:
            event = st.dataframe(
                filtered_rows,
                key="operational_issue_grid",
                on_select="rerun",
                selection_mode="single-row",
                hide_index=True,
                column_config={
                    "severity": st.column_config.TextColumn("Severity", pinned=True),
                    "title": st.column_config.TextColumn("Title", width="large"),
                    "details": st.column_config.JsonColumn("Details"),
                },
            )
            if event.selection.rows:
                selected_issue = filtered_rows[event.selection.rows[0]]
                with st.container(border=True):
                    st.markdown(f"**{selected_issue['title']}**")
                    with st.container(horizontal=True):
                        st.metric("Severity", selected_issue["severity"], border=True)
                        st.metric("Workflow", selected_issue["workflow"], border=True)
                        st.metric("Entity", f"{selected_issue['entity_type']} {selected_issue['entity_key']}", border=True)
                    st.code(selected_issue["issue_code"])
                    st.json(selected_issue["details"] or {})
                    st.button(
                        f"Open {selected_issue['workflow']}",
                        icon=":material/open_in_new:",
                        key=f"selected_issue_workflow_{selected_issue['workflow']}_{selected_issue['entity_type']}_{selected_issue['entity_key']}",
                        on_click=_open_operation_section,
                        args=(ISSUE_WORKFLOW_AREAS.get(selected_issue["workflow"], selected_issue["workflow"]),),
                    )
        else:
            st.info("No issues match the selected filters.")

        workflows = sorted({row["workflow"] for row in filtered_rows})
        with st.container(horizontal=True):
            for workflow in workflows:
                st.button(f"Open {workflow}", icon=":material/open_in_new:", key=f"issue_workflow_{workflow}",
                          on_click=_open_operation_section,
                          args=(ISSUE_WORKFLOW_AREAS.get(workflow, workflow),))
    else:
        st.success("Nothing to check right now.")


def render_operational_decision_actions(pool, actor: AppUser, rows: list[dict]) -> None:
    if actor.role != "admin":
        st.info("Only admins can apply owner-approved remediation actions.")
        return

    actionable_count = sum(
        1 for row in rows
        if row["issue_code"] in {
            "incomplete_employee_profile",
            "incomplete_attendance_roster",
            "missing_business_placement",
            "session_datetime_conflict",
        }
    )
    with st.container(horizontal=True):
        st.metric("Actionable rows", actionable_count, border=True)
        st.metric("Current inbox rows", len(rows), border=True)

    if actor.role == "admin" and any(row["issue_code"] == "incomplete_employee_profile" for row in rows):
        with st.form("unknown_org_backfill"):
            approved = st.checkbox("Apply approved Unknown BU and Unknown Role placeholders only where current organization is missing")
            submitted = st.form_submit_button("Backfill missing organization profiles", icon=":material/manage_history:")
        if submitted:
            if not approved:
                st.error("Confirm the approved placeholder policy before continuing.")
            elif safe_submit(pool, actor, lambda svc: svc.backfill_unknown_org_profiles()):
                st.rerun()

    attendance_exceptions = [row for row in rows if row["issue_code"] == "incomplete_attendance_roster"]
    if actor.role == "admin" and attendance_exceptions:
        exception_options = {
            f"Session {row['entity_key']} · run {row['details']['course_run_id']} · unit {row['details']['sequence_in_run']} · {row['details']['missing_enrollment_count']} missing": int(row["entity_key"])
            for row in attendance_exceptions
        }
        st.markdown("Legacy attendance exceptions")
        st.caption("Use only when the historical attendance source is unavailable. This approval creates no Present or Absent records.")
        with st.form("legacy_attendance_exception"):
            chosen_label = st.selectbox("Delivered session", list(exception_options))
            exception_reason = st.text_area("Approval reason", placeholder="State why the original attendance source cannot be recovered.")
            approved = st.checkbox("I approve this legacy exception without inferring learner attendance")
            submitted = st.form_submit_button("Approve legacy attendance exception", icon=":material/gavel:")
        if submitted:
            if not approved:
                st.error("Confirm that this exception does not create attendance facts.")
            elif safe_submit(pool, actor, lambda svc: svc.approve_legacy_attendance_exception(exception_options[chosen_label], exception_reason)):
                st.rerun()
        with st.form("bulk_legacy_attendance_exceptions"):
            bulk_reason = st.text_area("Shared approval reason", placeholder="State why the historical attendance source is unavailable for these sessions.")
            approved_all = st.checkbox(f"I approve legacy exceptions for all {len(attendance_exceptions)} currently listed sessions without inferring attendance")
            submitted_all = st.form_submit_button("Approve all listed legacy attendance exceptions", icon=":material/gavel:")
        if submitted_all:
            if not approved_all:
                st.error("Confirm the full scope before approving all listed sessions.")
            elif safe_submit(pool, actor, lambda svc: svc.approve_all_legacy_attendance_exceptions(bulk_reason)):
                st.rerun()

    if actor.role == "admin" and any(row["issue_code"] == "missing_business_placement" for row in rows):
        with st.form("unknown_placement_backfill"):
            approved = st.checkbox("Apply Unknown Entrance Level only where a learner has no business placement")
            submitted = st.form_submit_button("Backfill missing business placements", icon=":material/manage_history:")
        if submitted:
            if not approved:
                st.error("Confirm the approved Unknown Entrance Level policy before continuing.")
            elif safe_submit(pool, actor, lambda svc: svc.backfill_unknown_business_placements()):
                st.rerun()

    schedule_conflicts = [row for row in rows if row["issue_code"] == "session_datetime_conflict"]
    if schedule_conflicts:
        conflict_options = {
            f"Class {row['entity_key']} · {row['details']['starts_at']} · meetings {', '.join(map(str, row['details']['meeting_ids']))}": row
            for row in schedule_conflicts
        }
        st.markdown("Schedule conflict resolution")
        st.caption("Confirm the valid occurrence with the owner, then cancel only the duplicate meeting. Cancellation is audited and requires a reason.")
        with st.form("schedule_conflict_cancel"):
            conflict_label = st.selectbox("Concurrent session", list(conflict_options))
            conflict = conflict_options[conflict_label]
            meeting_id = st.selectbox("Duplicate meeting to cancel", [int(item) for item in conflict["details"]["meeting_ids"]])
            cancellation_reason = st.text_area("Cancellation reason", placeholder="State which occurrence is valid and why this one is a duplicate.")
            confirmed = st.checkbox("I confirmed this meeting is the duplicate occurrence")
            submitted = st.form_submit_button("Cancel duplicate meeting", icon=":material/event_busy:")
        if submitted:
            if not confirmed:
                st.error("Confirm the selected meeting is the duplicate occurrence.")
            elif safe_submit(pool, actor, lambda svc: svc.cancel_meeting(meeting_id, cancellation_reason)):
                st.rerun()


def render_logged_quality_issues(pool, actor: AppUser) -> None:
    st.subheader("Imported or manually logged quality issues")
    ledger_rows = queries.open_quality_issue_rows(pool)
    st.dataframe(ledger_rows, hide_index=True)
    issue_options = options(ledger_rows, "issue_id", "issue_code", "entity_type", "entity_key", "source_sheet", "source_row_number")
    with st.form("operational_issue_resolve"):
        issue_id = selected_id("Logged issue", issue_options, key="operational_issue_id")
        status = st.selectbox("Resolution", ["resolved", "ignored"])
        note = st.text_input("Resolution note")
        submitted = st.form_submit_button("Resolve logged issue", icon=":material/fact_check:")
    if submitted and issue_id:
        if safe_submit(pool, actor, lambda svc: svc.resolve_quality_issue(issue_id, status, note)):
            st.rerun()
