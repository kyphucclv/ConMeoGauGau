"""Start-learning onboarding and move-learner transfer journeys.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import (
    LIFECYCLE_LABELS,
    _capacity_context,
    _learner_rows,
    _onboarding_start_proposal,
    _open_operation_section,
    _transfer_start_proposal,
    options,
    submit_values,
)


def render_learner_onboarding(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.subheader("Start learning")
    available_run_rows = [row for row in refs["course_runs"] if row["status"] in {"planned", "active"}]
    runs = options(
        available_run_rows,
        "course_run_id",
        "class_code",
        "course_name",
        "run_number",
        "status",
    )
    bu = options(refs["business_units"], "business_unit_id", "business_unit_name")
    roles = options(refs["job_roles"], "job_role_id", "job_role_name")
    levels = options(refs["levels"], "level_id", "level_name")
    directory_rows = _learner_rows(pool)
    directory = {f"{row['emp_code']} | {row['full_name']}": row for row in directory_rows}

    requested = st.session_state.pop("learner_start_requested", False)
    requested_employee_id = st.session_state.get("learner_start_employee_id")
    if requested:
        st.session_state["start_learning_person_mode"] = (
            "Existing employee" if requested_employee_id is not None else "New employee"
        )
        if requested_employee_id is not None:
            requested_label = next(
                (label for label, row in directory.items() if row["employee_id"] == requested_employee_id),
                None,
            )
            if requested_label:
                st.session_state["start_learning_employee_lookup"] = requested_label

    person_mode = st.segmented_control(
        "Employee",
        ["Existing employee", "New employee"],
        key="start_learning_person_mode",
    )
    known_employee = None
    context = None
    if person_mode == "Existing employee":
        if not directory:
            st.info("No employees are available.")
            return
        known_label = st.selectbox(
            "Find employee",
            list(directory),
            key="start_learning_employee_lookup",
        )
        known_employee = directory[known_label]
        context = queries.learner_journey_context(pool, known_employee["employee_id"])
        if not context:
            st.error("This employee record is no longer available.")
            return
        lifecycle_label, lifecycle_color = LIFECYCLE_LABELS[context["lifecycle"]]
        st.badge(lifecycle_label, icon=":material/badge:", color=lifecycle_color)
        if context["active_enrollment_id"]:
            with st.container(horizontal=True):
                st.metric("Current class", context["active_class_code"], border=True)
                st.metric("Current course", context["active_course_name"], border=True)
            render_learner_transfer(pool, actor, refs, context)
            return

    if not runs:
        st.info("No planned or active course runs are available.")
        st.button(
            "Create class",
            icon=":material/group_add:",
            on_click=_open_operation_section,
            args=("Class setup",),
        )
        return

    run_label = st.selectbox(
        "Destination class and course",
        [""] + list(runs),
        key="start_learning_run",
    )
    course_run_id = runs.get(run_label)
    target_run = next(
        (row for row in available_run_rows if row["course_run_id"] == course_run_id),
        None,
    )
    capacity = _capacity_context(pool, course_run_id)
    start_session_proposal = _onboarding_start_proposal(pool, actor, course_run_id)
    default_bu = context["business_unit_name"] if context else ""
    default_role = context["job_role_name"] if context else ""
    default_level = context["entrance_level"] if context else ""
    bu_labels = [""] + list(bu)
    role_labels = [""] + list(roles)
    level_labels = [""] + list(levels)

    projected_count = None
    needs_override = False
    if capacity and target_run:
        reuses_membership = bool(
            context
            and context["active_membership_id"]
            and context["membership_cohort_id"] == target_run["cohort_id"]
        )
        projected_count = capacity["active_learners"] + (0 if reuses_membership else 1)
        needs_override = capacity["capacity"] is not None and projected_count > capacity["capacity"]

    with st.form("learner_onboarding", border=False):
        emp_code = st.text_input(
            "Employee code",
            value=known_employee["emp_code"] if known_employee else "",
            disabled=bool(known_employee),
        )
        full_name = st.text_input(
            "Full name",
            value=known_employee["full_name"] if known_employee else "",
        )
        business_unit = st.selectbox("Business unit", bu_labels, index=bu_labels.index(default_bu) if default_bu in bu_labels else 0)
        job_role = st.selectbox("Role", role_labels, index=role_labels.index(default_role) if default_role in role_labels else 0)
        if context and context["placement_id"]:
            st.text_input("Entrance placement", value=default_level, disabled=True)
            entrance_level_id = context["entrance_level_id"]
        else:
            entrance_level = st.selectbox("Entrance placement", level_labels)
            entrance_level_id = levels.get(entrance_level)
        joined_on = st.date_input("Start date", value=date.today())

        if target_run and start_session_proposal is not None:
            with st.container(horizontal=True):
                st.metric("Class", target_run["class_code"], border=True)
                st.metric("Course", target_run["course_name"], border=True)
                st.metric("First session", start_session_proposal, border=True)
                if capacity:
                    capacity_label = capacity["capacity"] if capacity["capacity"] is not None else "Not set"
                    st.metric("Class size", f"{projected_count} / {capacity_label}", border=True)

        approve_override = False
        override_reason = ""
        if needs_override:
            st.warning("This start exceeds the class capacity.")
            approve_override = st.checkbox("Approve capacity exception")
            override_reason = st.text_input("Exception reason", disabled=not approve_override)
        confirmed = st.checkbox("I confirm this learner, class, course, and first session")
        if context and context["lifecycle"] == "continuation":
            submit_label = "Continue learning"
        elif context:
            submit_label = "Restart learning"
        else:
            submit_label = "Add and start learning"
        submitted = st.form_submit_button(
            submit_label,
            type="primary",
            icon=":material/play_circle:",
        )
    if submitted:
        if not course_run_id:
            st.error("Select a destination class and course.")
        elif not emp_code.strip() or not full_name.strip():
            st.error("Employee code and full name are required.")
        elif not business_unit or not job_role or not entrance_level_id:
            st.error("Business unit, role, and entrance level are required.")
        elif start_session_proposal is None:
            st.error("The first session could not be calculated.")
        elif needs_override and (not approve_override or not override_reason.strip()):
            st.error("Confirm the capacity exception and enter a reason.")
        elif not confirmed:
            st.error("Confirm the summary before starting learning.")
        else:
            result = submit_values(pool, actor, lambda svc: svc.onboard_learner(
                emp_code=emp_code,
                full_name=full_name,
                business_unit_id=bu[business_unit],
                job_role_id=roles[job_role],
                entrance_level_id=entrance_level_id,
                course_run_id=course_run_id,
                joined_on=joined_on,
                start_session_number=int(start_session_proposal),
                capacity_override_reason=override_reason if needs_override else None,
            ))
            if result is not None:
                completion_messages = {
                    "first_time": "Learner added and learning started.",
                    "returning": "Returning learner started learning.",
                    "continuation": "Learner continued to the next course.",
                    "rejoin": "Learner rejoined and started learning.",
                }
                st.session_state["learner_notice"] = completion_messages[result["lifecycle"]]
                st.session_state["learner_search"] = emp_code.strip()
                st.session_state["learner_redirect_to_list"] = True
                st.rerun()


def render_learner_transfer(pool, actor: AppUser, refs: dict[str, list[dict]], context: dict) -> None:
    st.markdown("Move learner")
    enrollment_id = context["active_enrollment_id"]
    available_run_rows = [
        row for row in refs["course_runs"]
        if row["status"] in {"planned", "active"}
        and row["course_run_id"] != context["active_course_run_id"]
        and row["cohort_id"] != context["active_cohort_id"]
    ]
    runs = options(
        available_run_rows,
        "course_run_id",
        "class_code",
        "course_name",
        "run_number",
        "status",
    )
    if not runs:
        st.info("No other planned or active course runs are available.")
        return
    target_label = st.selectbox(
        "Destination class and course",
        [""] + list(runs),
        key=f"transfer_target_{enrollment_id}",
    )
    target_run_id = runs.get(target_label)
    target_run = next(
        (row for row in available_run_rows if row["course_run_id"] == target_run_id),
        None,
    )
    proposal = _transfer_start_proposal(pool, actor, target_run_id)
    capacity = _capacity_context(pool, target_run_id)
    projected_count = None
    needs_override = False
    if capacity and target_run:
        projected_count = capacity["active_learners"] + 1
        needs_override = (
            capacity["capacity"] is not None
            and projected_count > capacity["capacity"]
        )
    with st.form(f"learner_transfer_{enrollment_id}", border=False):
        transfer_date = st.date_input("Transfer date", value=date.today())
        if target_run and proposal is not None:
            with st.container(horizontal=True):
                st.metric("From", context["active_class_code"], border=True)
                st.metric("To", target_run["class_code"], border=True)
                st.metric("Course", target_run["course_name"], border=True)
            with st.container(horizontal=True):
                st.metric("First session", proposal, border=True)
                if capacity:
                    capacity_label = capacity["capacity"] if capacity["capacity"] is not None else "Not set"
                    st.metric("Class size", f"{projected_count} / {capacity_label}", border=True)
        approve_override = False
        override_reason = ""
        if needs_override:
            st.warning("This move exceeds the destination class capacity.")
            approve_override = st.checkbox("Approve capacity exception")
            override_reason = st.text_input("Exception reason", disabled=not approve_override)
        confirm = st.checkbox("I confirm the destination and first session")
        submitted = st.form_submit_button(
            "Move learner",
            type="primary",
            icon=":material/swap_horiz:",
        )
    if submitted:
        if not target_run_id or proposal is None:
            st.error("Select a destination class and course.")
        elif needs_override and (not approve_override or not override_reason.strip()):
            st.error("Confirm the capacity exception and enter a reason.")
        elif not confirm:
            st.error("Confirm the destination before moving the learner.")
        else:
            result = submit_values(pool, actor, lambda svc: svc.transfer_learner(
                enrollment_id,
                target_run_id,
                transfer_date,
                confirmed_start_session_number=proposal,
                capacity_override_reason=override_reason if needs_override else None,
            ))
            if result is not None:
                st.session_state["learner_notice"] = "Learner moved to the destination class."
                st.session_state["learner_search"] = context["emp_code"]
                st.session_state["learner_transfer_enrollment_id"] = None
                st.session_state["learner_redirect_to_list"] = True
                st.rerun()
