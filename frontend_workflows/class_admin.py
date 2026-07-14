"""Class/course-run creation and employee/cohort admin records.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import _proposed_class_code, options, safe_submit, selected_id


def render_class_course_run_creator(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.subheader("Create class and course run")
    courses = options(refs["courses"], "course_id", "course_code", "course_name", "expected_units")
    employees = options(refs["employees"], "employee_id", "emp_code", "full_name")
    pic_labels = [row["pic_label"] for row in refs.get("pic_labels", []) if row["pic_label"]]
    if "class_create_code" not in st.session_state:
        st.session_state["class_create_code"] = _proposed_class_code(pool, actor)

    with st.form("class_course_run_create"):
        class_code = st.text_input("Class code", key="class_create_code")
        display_name = st.text_input("Display name")
        course_label = st.selectbox("Course", [""] + list(courses), key="class_run_course")
        start_date = st.date_input("Start date", value=date.today(), key="class_run_start")
        capacity = st.number_input("Capacity", min_value=1, value=12, step=1)
        status = st.segmented_control("Initial status", ["planned", "active"], default="active")
        pic_mode = st.segmented_control("PIC type", ["Team label", "Employee"], default="Team label", key="class_run_pic_mode")
        pic_employee_id = None
        pic_label = None
        if pic_mode == "Employee":
            pic_employee_id = selected_id("PIC employee", employees, key="class_run_pic_employee")
        else:
            pic_label = st.selectbox(
                "PIC team label",
                [""] + pic_labels,
                accept_new_options=True,
                placeholder="Select or type a team label",
                key="class_run_pic_label",
            )
        submitted = st.form_submit_button("Create class", type="primary", icon=":material/add_circle:")
    if submitted:
        course_id = courses.get(course_label)
        if not course_id:
            st.error("Select a course.")
        elif pic_mode == "Team label" and not (pic_label or "").strip():
            st.error("PIC team label is required.")
        elif safe_submit(pool, actor, lambda svc: svc.create_class_course_run(
            class_code=class_code,
            display_name=display_name,
            course_id=course_id,
            start_date=start_date,
            capacity=int(capacity),
            status=status,
            pic_employee_id=pic_employee_id,
            pic_label=pic_label if pic_mode == "Team label" else None,
        )):
            st.session_state.pop("class_create_code", None)
            st.rerun()


def render_employee_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    search = st.text_input("Search employees", key="employee_search")
    rows = queries.employee_search_rows(pool, search)
    st.dataframe(rows)

    bu = options(refs["business_units"], "business_unit_id", "business_unit_name")
    roles = options(refs["job_roles"], "job_role_id", "job_role_name")
    with st.form("employee_upsert"):
        st.markdown("Create or update employee")
        emp_code = st.text_input("Emp code")
        full_name = st.text_input("Full name")
        english_name = st.text_input("English name")
        email = st.text_input("Email")
        status = st.selectbox("Employment status", ["active", "inactive", "unknown"])
        bu_label = st.selectbox("Business unit", [""] + list(bu.keys()))
        role_label = st.selectbox("Job role", [""] + list(roles.keys()))
        valid_from = st.date_input("Observed from", value=date.today())
        submitted = st.form_submit_button("Save employee", icon=":material/person:")
    if submitted:
        def op(svc):
            svc.create_or_update_employee(
                emp_code,
                full_name,
                english_name=english_name.strip() or None,
                email=email.strip() or None,
                employment_status=status,
                business_unit_id=bu.get(bu_label),
                job_role_id=roles.get(role_label),
                valid_from=valid_from,
            )
        if safe_submit(pool, actor, op):
            st.rerun()


def render_cohort_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.dataframe(queries.cohort_rows(pool))
    cohorts = options(refs["cohorts"], "cohort_id", "class_code", "display_name")
    employees = options(refs["employees"], "employee_id", "emp_code", "full_name")

    with st.form("cohort_create"):
        st.markdown("Create class record only (no course)")
        class_code = st.text_input("Class code")
        display_name = st.text_input("Display name")
        status = st.selectbox("Status", ["planned", "active", "completed", "archived"])
        submitted = st.form_submit_button("Create class record", icon=":material/groups:")
    if submitted and safe_submit(pool, actor, lambda svc: svc.create_cohort(class_code, display_name, status=status)):
        st.rerun()

    pic_mode = st.segmented_control("PIC type", ["Team label", "Employee"], default="Team label")
    with st.form(f"cohort_pic_{pic_mode}"):
        st.markdown("Assign PIC")
        cohort_id = selected_id("Class", cohorts, key="pic_cohort")
        pic_employee_id = None
        pic_label = None
        if pic_mode == "Employee":
            pic_employee_id = selected_id("PIC employee", employees, key="pic_employee")
        else:
            pic_label = st.text_input("Team label")
        start_date = st.date_input("PIC start date", value=date.today())
        submitted = st.form_submit_button("Assign PIC", icon=":material/supervisor_account:")
    if submitted and cohort_id:
        if safe_submit(
            pool,
            actor,
            lambda svc: svc.assign_pic(cohort_id, pic_employee_id, start_date, pic_label=pic_label),
        ):
            st.rerun()


def render_course_run_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.dataframe(queries.course_run_dashboard_rows(pool))
    cohorts = options(refs["cohorts"], "cohort_id", "class_code", "display_name")
    courses = options(refs["courses"], "course_id", "course_code", "course_name")
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "run_number", "status")

    with st.form("course_run_create"):
        st.markdown("Add a course to an existing class")
        cohort_id = selected_id("Class", cohorts, key="run_cohort")
        course_id = selected_id("Course", courses, key="run_course")
        start_date = st.date_input("Course start date", value=date.today())
        submitted = st.form_submit_button("Add course", icon=":material/play_lesson:")
    if submitted and cohort_id and course_id:
        if safe_submit(pool, actor, lambda svc: svc.create_course_run(cohort_id, course_id, start_date=start_date)):
            st.rerun()

    with st.form("course_run_status"):
        st.markdown("Change course status")
        run_id = selected_id("Class and course", runs, key="status_run")
        status = st.selectbox("New status", ["planned", "active", "completed", "cancelled", "archived"])
        end_date = st.date_input("End date", value=date.today())
        apply_end_date = st.checkbox("Apply end date")
        submitted = st.form_submit_button("Update status", icon=":material/published_with_changes:")
    if submitted and run_id:
        if safe_submit(pool, actor, lambda svc: svc.change_course_run_status(run_id, status, end_date=end_date if apply_end_date else None)):
            st.rerun()
