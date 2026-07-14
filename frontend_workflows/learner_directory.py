"""Learner search list and the selected learner detail panel.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.learner_journeys import render_learner_onboarding, render_learner_transfer
from frontend_workflows.shared import (
    EMPLOYMENT_OPTIONS,
    ENROLLMENT_STATUS_LABELS,
    LEARNER_CHANGE_LABELS,
    LIFECYCLE_LABELS,
    _learner_rows,
    _open_operation_section,
    options,
    submit_values,
)


def render_learner_workspace(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    """HR-first learner search and lifecycle journeys."""
    if st.session_state.pop("learner_redirect_to_list", False):
        st.session_state["learner_workspace_mode"] = "Learner list"
    if st.session_state.get("learner_workspace_mode") not in {"Learner list", "Start learning"}:
        st.session_state["learner_workspace_mode"] = "Learner list"
    notice = st.session_state.pop("learner_notice", None)
    if notice:
        st.success(notice)
    mode = st.segmented_control(
        "Learner task",
        ["Learner list", "Start learning"],
        key="learner_workspace_mode",
    )

    if mode == "Start learning":
        render_learner_onboarding(pool, actor, refs)
        return

    rows = _learner_rows(pool)
    bu_names = sorted({row["business_unit_name"] for row in rows if row["business_unit_name"]})
    role_names = sorted({row["job_role_name"] for row in rows if row["job_role_name"]})
    class_codes = sorted({row["class_code"] for row in rows if row["class_code"]})
    course_names = sorted({row["course_name"] for row in rows if row["course_name"]})
    pic_names = sorted({row["pic"] for row in rows if row["pic"]})

    with st.form("learner_filters", border=False):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            search = st.text_input(
                "Search by employee code or name",
                value=st.session_state.get("learner_search", ""),
                placeholder="Employee code or name",
            )
            submitted = st.form_submit_button("Search", icon=":material/search:")
        with st.expander("More filters"):
            filter_row = st.container(horizontal=True)
            with filter_row:
                class_filter = st.selectbox("Class", ["All"] + class_codes)
                course_filter = st.selectbox("Course", ["All"] + course_names)
                pic_filter = st.selectbox("PIC", ["All"] + pic_names)
                active_filter = st.segmented_control(
                    "Learning status",
                    ["All", "Currently learning", "Not currently learning"],
                    default="All",
                )
            org_filter_row = st.container(horizontal=True)
            with org_filter_row:
                bu_filter = st.selectbox("Business unit", ["All"] + bu_names)
                role_filter = st.selectbox("Role", ["All"] + role_names)
    if submitted:
        st.session_state["learner_search"] = search

    def matches(row: dict) -> bool:
        text = search.strip().lower()
        return (
            (not text or text in row["emp_code"].lower() or text in row["full_name"].lower())
            and (class_filter == "All" or row["class_code"] == class_filter)
            and (course_filter == "All" or row["course_name"] == course_filter)
            and (pic_filter == "All" or row["pic"] == pic_filter)
            and (bu_filter == "All" or row["business_unit_name"] == bu_filter)
            and (role_filter == "All" or row["job_role_name"] == role_filter)
            and (
                active_filter == "All"
                or (active_filter == "Currently learning") == (row["enrollment_status"] == "active")
            )
        )

    filtered = [row for row in rows if matches(row)]
    active_count = sum(1 for row in filtered if row["enrollment_status"] == "active")
    missing_placement_count = sum(1 for row in filtered if not row["entrance_level"])
    with st.container(horizontal=True):
        st.metric("Results", len(filtered), border=True)
        st.metric("Currently learning", active_count, border=True)
        st.metric("Missing placement", missing_placement_count, border=True)
    with st.container(horizontal=True):
        st.button(
            "Start learning",
            type="primary",
            icon=":material/person_add:",
            on_click=_set_learner_workspace_mode,
            args=("Start learning", None),
        )
        st.button(
            "Create class",
            icon=":material/group_add:",
            on_click=_open_operation_section,
            args=("Class setup",),
        )

    display_rows = [
        {
            "Employee code": row["emp_code"],
            "Name": row["full_name"],
            "Learning status": "Currently learning" if row["enrollment_status"] == "active" else "Not currently learning",
            "Class": row["class_code"],
            "Course": row["course_name"],
            "Attendance": row["attendance_ratio"],
            "Business unit": row["business_unit_name"],
            "Role": row["job_role_name"],
            "PIC": row["pic"],
        }
        for row in filtered
    ]
    event = st.dataframe(
        display_rows,
        hide_index=True,
        key="learner_results_v2",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Attendance": st.column_config.NumberColumn("Attendance", format="percent"),
        },
    )
    selected = filtered[event.selection.rows[0]] if event.selection.rows else None
    if selected:
        render_learner_detail(pool, actor, refs, selected)


def _set_learner_workspace_mode(mode: str, employee_id: int | None = None) -> None:
    st.session_state["learner_workspace_mode"] = mode
    st.session_state["learner_start_employee_id"] = employee_id
    st.session_state["learner_start_requested"] = True


def _open_learner_transfer(enrollment_id: int) -> None:
    st.session_state["learner_transfer_enrollment_id"] = enrollment_id


def render_learner_detail(pool, actor: AppUser, refs: dict[str, list[dict]], learner: dict) -> None:
    context = queries.learner_journey_context(pool, learner["employee_id"])
    if not context:
        st.error("This employee record is no longer available.")
        return
    st.subheader(f"{learner['full_name']} | {learner['emp_code']}")
    lifecycle_label, lifecycle_color = LIFECYCLE_LABELS[context["lifecycle"]]
    st.badge(lifecycle_label, icon=":material/school:", color=lifecycle_color)
    with st.container(horizontal=True):
        st.metric("Current class", learner["class_code"] or "Not currently learning", border=True)
        st.metric("Course", learner["course_name"] or context["latest_course_name"] or "No course", border=True)
        st.metric("Entrance level", learner["entrance_level"] or "Not set", border=True)
        st.metric(
            "Attendance",
            f"{learner['attendance_ratio']:.0%}" if learner["attendance_ratio"] is not None else "No sessions",
            border=True,
        )

    with st.container(horizontal=True):
        if context["active_enrollment_id"]:
            st.button(
                "Move learner",
                type="primary",
                icon=":material/swap_horiz:",
                on_click=_open_learner_transfer,
                args=(context["active_enrollment_id"],),
            )
        else:
            action_label = "Continue learning" if context["lifecycle"] == "continuation" else "Start learning"
            st.button(
                action_label,
                type="primary",
                icon=":material/play_circle:",
                on_click=_set_learner_workspace_mode,
                args=("Start learning", learner["employee_id"]),
            )

    if st.session_state.get("learner_transfer_enrollment_id") == context["active_enrollment_id"]:
        render_learner_transfer(pool, actor, refs, context)

    bu = options(refs["business_units"], "business_unit_id", "business_unit_name")
    roles = options(refs["job_roles"], "job_role_id", "job_role_name")
    current_bu = next((label for label, item_id in bu.items() if item_id and label == learner["business_unit_name"]), "")
    current_role = next((label for label, item_id in roles.items() if item_id and label == learner["job_role_name"]), "")
    with st.expander("Profile and organization"):
        with st.form(f"learner_edit_{learner['employee_id']}"):
            st.text_input("Employee code", value=learner["emp_code"], disabled=True)
            full_name = st.text_input("Full name", value=learner["full_name"])
            employment_labels = list(EMPLOYMENT_OPTIONS)
            current_employment_label = next(
                label for label, value in EMPLOYMENT_OPTIONS.items() if value == learner["employment_status"]
            )
            employment_label = st.selectbox(
                "Employment status",
                employment_labels,
                index=employment_labels.index(current_employment_label),
            )
            business_unit = st.selectbox(
                "Business unit",
                [""] + list(bu),
                index=([""] + list(bu)).index(current_bu) if current_bu else 0,
            )
            job_role = st.selectbox(
                "Role",
                [""] + list(roles),
                index=([""] + list(roles)).index(current_role) if current_role else 0,
            )
            submitted = st.form_submit_button("Save profile", icon=":material/save:")
        if submitted:
            if not business_unit or not job_role:
                st.error("Business unit and role are required.")
            else:
                result = submit_values(pool, actor, lambda svc: svc.create_or_update_employee(
                    learner["emp_code"],
                    full_name,
                    employment_status=EMPLOYMENT_OPTIONS[employment_label],
                    business_unit_id=bu[business_unit],
                    job_role_id=roles[job_role],
                    valid_from=date.today(),
                ))
                if result is not None:
                    st.session_state["learner_notice"] = "Learner profile saved."
                    st.rerun()

    history = queries.learner_course_history(pool, learner["employee_id"])
    st.markdown("Course history")
    history_rows = [
        {
            "Started": row["start_date"],
            "Class": row["class_code"],
            "Course": row["course_name"],
            "Status": ENROLLMENT_STATUS_LABELS[row["status"]],
            "First session": row["start_session_number"],
            "Attendance": row["attendance_ratio"],
            "Final level": row["final_level"],
            "Passed": row["passed"],
        }
        for row in history
    ]
    st.dataframe(
        history_rows,
        hide_index=True,
        column_config={
            "Attendance": st.column_config.NumberColumn("Attendance", format="percent"),
            "Passed": st.column_config.CheckboxColumn("Passed"),
        },
    )

    audit = queries.employee_audit_rows(pool, learner["employee_id"])
    with st.expander("Change history"):
        st.dataframe(
            [
                {
                    "When": row["created_at"],
                    "Changed by": row["actor_username"],
                    "Change": LEARNER_CHANGE_LABELS.get(
                        row["action"],
                        row["action"].replace(".", " ").replace("_", " ").title(),
                    ),
                }
                for row in audit
            ],
            hide_index=True,
        )
