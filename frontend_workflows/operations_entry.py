"""Top-level HR workspace dispatch across task areas.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.attendance import render_attendance_workflow
from frontend_workflows.class_admin import (
    render_class_course_run_creator,
    render_cohort_workflow,
    render_course_run_workflow,
    render_employee_workflow,
)
from frontend_workflows.data_issues import render_data_issues_workspace
from frontend_workflows.evaluation import render_evaluation_workflow
from frontend_workflows.learner_directory import render_learner_workspace
from frontend_workflows.monthly_review import render_monthly_review
from frontend_workflows.schedule_admin import render_schedule_workflow
from frontend_workflows.shared import HR_TASK_AREAS, _open_operation_section, load_refs


def render_operations(pool, actor: AppUser) -> None:
    st.subheader("HR workspace")
    if actor.role not in {"admin", "editor"}:
        st.info("Viewer role can review reports but cannot change records.")
        return

    if st.session_state.get("operations_section") not in HR_TASK_AREAS:
        st.session_state["operations_section"] = "Start here"
    section = st.segmented_control(
        "Task area",
        HR_TASK_AREAS,
        key="operations_section",
    )

    refs = load_refs(pool)
    if section == "Start here":
        render_hr_start(pool)
    elif section == "Learners":
        render_learner_workspace(pool, actor, refs)
    elif section == "Attendance":
        render_attendance_workflow(pool, actor, refs)
    elif section == "Final results":
        render_evaluation_workflow(pool, actor, refs)
    elif section == "Monthly review":
        render_monthly_review(pool, actor)
    elif section == "Data follow-up":
        render_data_issues_workspace(pool, actor)
    elif section == "Class setup":
        render_class_setup_workspace(pool, actor, refs)
    elif section == "Admin records":
        render_admin_records_workspace(pool, actor, refs)


def render_hr_start(pool) -> None:
    summary = queries.hr_home_snapshot(pool)
    with st.container(horizontal=True):
        st.metric("Current learners", summary["current_learners"], border=True)
        st.metric("Open classes", summary["open_classes"], border=True)
        st.metric("Needs review", summary["review_items"], border=True)
        st.metric("Urgent", summary["urgent_items"], border=True, delta_color="inverse")
        st.metric("Follow-ups", summary["follow_ups"], border=True)

    st.subheader("Common HR tasks")
    with st.container(horizontal=True):
        st.button("Find or add learner", icon=":material/person_search:", on_click=_open_operation_section, args=("Learners",))
        st.button("Mark attendance", icon=":material/checklist:", on_click=_open_operation_section, args=("Attendance",))
        st.button("Record final result", icon=":material/rate_review:", on_click=_open_operation_section, args=("Final results",))
        st.button("Review this month", icon=":material/calendar_month:", on_click=_open_operation_section, args=("Monthly review",))
        st.button("Resolve follow-ups", icon=":material/task_alt:", on_click=_open_operation_section, args=("Data follow-up",))

    st.subheader("Setup and admin")
    with st.container(horizontal=True):
        st.button("Set up class", icon=":material/group_add:", on_click=_open_operation_section, args=("Class setup",))
        st.button("Admin records", icon=":material/database:", on_click=_open_operation_section, args=("Admin records",))


def render_class_setup_workspace(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.session_state.setdefault("class_setup_mode", "Create class")
    mode = st.segmented_control(
        "Class setup",
        ["Create class", "Classes", "Course runs", "Sessions"],
        key="class_setup_mode",
    )
    if mode == "Create class":
        render_class_course_run_creator(pool, actor, refs)
    elif mode == "Classes":
        render_cohort_workflow(pool, actor, refs)
    elif mode == "Course runs":
        render_course_run_workflow(pool, actor, refs)
    else:
        render_schedule_workflow(pool, actor, refs)


def render_admin_records_workspace(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    mode = st.segmented_control(
        "Admin record type",
        ["Employees", "Classes", "Course runs", "Sessions"],
        default="Employees",
        key="admin_records_mode",
    )
    if mode == "Employees":
        render_employee_workflow(pool, actor, refs)
    elif mode == "Classes":
        render_cohort_workflow(pool, actor, refs)
    elif mode == "Course runs":
        render_course_run_workflow(pool, actor, refs)
    else:
        render_schedule_workflow(pool, actor, refs)
