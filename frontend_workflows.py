"""Streamlit admin workflows backed by Phase 4 services."""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from auth import AppUser
from db import pooled_connection
import frontend_queries as queries
from reporting import monthly_review_data, monthly_review_summary, monthly_review_xlsx, proposed_monthly_actions
from services import BusinessService, CommandError


HR_TASK_AREAS = [
    "Start here",
    "Learners",
    "Attendance",
    "Final results",
    "Monthly review",
    "Data follow-up",
    "Class setup",
    "Admin records",
]

EMPLOYMENT_OPTIONS = {
    "Employed": "active",
    "Not active": "inactive",
    "Needs confirmation": "unknown",
}

ENROLLMENT_STATUS_LABELS = {
    "active": "Learning",
    "completed": "Completed",
    "transferred": "Transferred",
    "dropped": "Withdrawn",
    "cancelled": "Cancelled",
}

LEARNER_CHANGE_LABELS = {
    "employee.upsert": "Profile saved",
    "learner.onboard": "Learning started",
    "learner.transfer": "Moved to another class",
    "enrollment.create": "Course started",
    "enrollment.transfer": "Course changed",
    "membership.create": "Joined class",
    "membership.close": "Left class",
    "membership.transfer": "Class changed",
}

LIFECYCLE_LABELS = {
    "active": ("Currently learning", "blue"),
    "continuation": ("Ready for next course", "green"),
    "rejoin": ("Returning to a class", "orange"),
    "returning": ("Returning learner", "orange"),
    "first_time": ("First learning record", "gray"),
}


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


def load_refs(pool) -> dict[str, list[dict]]:
    return queries.workflow_reference_data(pool)


def service(pool, actor: AppUser):
    conn_ctx = pooled_connection(pool)
    conn = conn_ctx.__enter__()
    return conn_ctx, BusinessService(conn, actor.user_id)


def options(rows, id_col: str, *label_cols: str) -> dict[str, int]:
    result = {}
    for row in rows:
        label = " | ".join(str(row[col]) for col in label_cols if row[col] is not None)
        result[label] = row[id_col]
    return result


def safe_submit(pool, actor: AppUser, fn) -> bool:
    conn_ctx, svc = service(pool, actor)
    try:
        fn(svc)
    except CommandError as error:
        st.error(error.message)
        return False
    except Exception:
        st.error("Unable to complete this operation.")
        return False
    finally:
        conn_ctx.__exit__(None, None, None)
    st.success("Saved.")
    return True


def submit_values(pool, actor: AppUser, fn) -> dict | None:
    """Run one command and return its receipt without exposing SQL errors."""
    conn_ctx, svc = service(pool, actor)
    try:
        return fn(svc).values
    except CommandError as error:
        st.error(error.message)
    except Exception:
        st.error("Unable to complete this operation.")
    finally:
        conn_ctx.__exit__(None, None, None)
    return None


def service_values(pool, actor: AppUser, fn) -> dict | None:
    try:
        with pooled_connection(pool) as conn:
            return fn(BusinessService(conn, actor.user_id)).values
    except CommandError as error:
        st.error(error.message)
    except Exception:
        st.error("Unable to load this operation.")
    return None


def selected_id(label: str, values: dict[str, int], *, key: str) -> int | None:
    if not values:
        st.info(f"No {label.lower()} available.")
        return None
    selected = st.selectbox(label, list(values.keys()), key=key)
    return values[selected]


def _learner_rows(pool) -> list[dict]:
    """One display row per employee; current assignment is intentionally derived."""
    return queries.learner_directory_rows(pool)


def _capacity_context(pool, course_run_id: int | None) -> dict | None:
    if not course_run_id:
        return None
    return queries.course_run_capacity(pool, course_run_id)


def _transfer_start_proposal(pool, actor: AppUser, target_course_run_id: int | None) -> int | None:
    if not target_course_run_id:
        return None
    values = service_values(pool, actor, lambda svc: svc.propose_transfer_start_session(target_course_run_id))
    return values["start_session_number"] if values else None


def _onboarding_start_proposal(pool, actor: AppUser, target_course_run_id: int | None) -> int | None:
    if not target_course_run_id:
        return None
    values = service_values(pool, actor, lambda svc: svc.propose_onboarding_start_session(target_course_run_id))
    return values["start_session_number"] if values else None


def _proposed_class_code(pool, actor: AppUser) -> str:
    values = service_values(pool, actor, lambda svc: svc.propose_next_class_code())
    return values["class_code"] if values else ""


def _next_attendance_sequence(pool, actor: AppUser, course_run_id: int | None) -> int:
    if not course_run_id:
        return 1
    values = service_values(pool, actor, lambda svc: svc.propose_next_attendance_session(course_run_id))
    return int(values["sequence_in_run"]) if values else 1


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
        st.markdown("Create cohort")
        class_code = st.text_input("Class code")
        display_name = st.text_input("Display name")
        status = st.selectbox("Status", ["planned", "active", "completed", "archived"])
        submitted = st.form_submit_button("Create cohort", icon=":material/groups:")
    if submitted and safe_submit(pool, actor, lambda svc: svc.create_cohort(class_code, display_name, status=status)):
        st.rerun()

    pic_mode = st.segmented_control("PIC type", ["Team label", "Employee"], default="Team label")
    with st.form(f"cohort_pic_{pic_mode}"):
        st.markdown("Assign PIC")
        cohort_id = selected_id("Cohort", cohorts, key="pic_cohort")
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
        st.markdown("Create course run")
        cohort_id = selected_id("Cohort", cohorts, key="run_cohort")
        course_id = selected_id("Course", courses, key="run_course")
        start_date = st.date_input("Run start date", value=date.today())
        submitted = st.form_submit_button("Create run", icon=":material/play_lesson:")
    if submitted and cohort_id and course_id:
        if safe_submit(pool, actor, lambda svc: svc.create_course_run(cohort_id, course_id, start_date=start_date)):
            st.rerun()

    with st.form("course_run_status"):
        st.markdown("Change course-run status")
        run_id = selected_id("Course run", runs, key="status_run")
        status = st.selectbox("New status", ["planned", "active", "completed", "cancelled", "archived"])
        end_date = st.date_input("End date", value=date.today())
        apply_end_date = st.checkbox("Apply end date")
        submitted = st.form_submit_button("Update status", icon=":material/published_with_changes:")
    if submitted and run_id:
        if safe_submit(pool, actor, lambda svc: svc.change_course_run_status(run_id, status, end_date=end_date if apply_end_date else None)):
            st.rerun()


def render_schedule_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    st.dataframe(queries.schedule_rows(pool))
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "run_number", "status")
    meetings = options(refs["meetings"], "meeting_id", "class_code", "course_code", "run_number", "starts_at", "status")
    open_meeting_ids = {row["meeting_id"] for row in refs["meetings"] if row["status"] != "cancelled"}
    open_meetings = {label: item_id for label, item_id in meetings.items() if item_id in open_meeting_ids}

    with st.form("meeting_create_with_units"):
        st.markdown("Create meeting and credited units")
        run_id = selected_id("Course run", runs, key="meeting_run")
        starts_on = st.date_input("Meeting date", value=date.today())
        starts_time = st.time_input("Start time", value=time(9, 0))
        duration = st.number_input("Duration minutes", min_value=1, value=120, step=15)
        status = st.selectbox("Meeting status", ["planned", "completed"])
        first_sequence = st.number_input("First session number", min_value=1, value=1, step=1)
        units_to_add = st.segmented_control("Credited units", [1, 2], default=1)
        unit_type = st.selectbox("Unit type", ["normal", "final_test", "makeup", "admin"])
        submitted = st.form_submit_button("Create meeting", icon=":material/event:")
    if submitted and run_id:
        starts_at = datetime.combine(starts_on, starts_time)
        if safe_submit(pool, actor, lambda svc: svc.create_meeting_with_units(
            run_id,
            starts_at,
            int(duration),
            int(first_sequence),
            unit_count=int(units_to_add),
            unit_type=unit_type,
            status=status,
        )):
            st.rerun()

    meeting_label = st.selectbox("Meeting to revise", [""] + list(open_meetings), key="schedule_meeting_to_revise")
    meeting_id = open_meetings.get(meeting_label)
    meeting_row = next((row for row in refs["meetings"] if row["meeting_id"] == meeting_id), None)
    if meeting_row:
        starts_at_value = meeting_row["starts_at"]
        with st.form(f"meeting_update_{meeting_id}"):
            st.markdown("Revise meeting")
            starts_on = st.date_input("Meeting date", value=starts_at_value.date())
            starts_time = st.time_input("Start time", value=starts_at_value.time().replace(tzinfo=None))
            duration = st.number_input(
                "Duration minutes",
                min_value=1,
                value=int(meeting_row["duration_minutes"]),
                step=15,
            )
            status = st.selectbox(
                "Meeting status",
                ["planned", "completed"],
                index=["planned", "completed"].index(meeting_row["status"])
                if meeting_row["status"] in {"planned", "completed"} else 0,
            )
            change_reason = st.text_input("Reason for schedule change")
            submitted = st.form_submit_button("Save meeting changes", icon=":material/edit_calendar:")
        if submitted:
            starts_at = datetime.combine(starts_on, starts_time)
            if safe_submit(pool, actor, lambda svc: svc.save_meeting(
                meeting_row["course_run_id"],
                starts_at,
                int(duration),
                meeting_id=meeting_id,
                status=status,
                change_reason=change_reason,
            )):
                st.rerun()

        with st.form(f"meeting_cancel_{meeting_id}"):
            cancellation_reason = st.text_input("Cancellation reason")
            cancel_submitted = st.form_submit_button("Cancel meeting", icon=":material/event_busy:")
        if cancel_submitted:
            if safe_submit(pool, actor, lambda svc: svc.cancel_meeting(meeting_id, cancellation_reason)):
                st.rerun()

    with st.form("session_units_add"):
        st.markdown("Add credited units to an existing meeting")
        run_id = selected_id("Course run", runs, key="unit_run")
        meeting_id = selected_id("Meeting", open_meetings, key="unit_meeting")
        first_sequence = st.number_input("First sequence in run", min_value=1, value=1, step=1)
        units_to_add = st.segmented_control("Units to add", [1, 2], default=1)
        unit_type = st.selectbox("Unit type", ["normal", "final_test", "makeup", "admin"])
        submitted = st.form_submit_button("Add units", icon=":material/add_circle:")
    if submitted and run_id and meeting_id:
        if safe_submit(pool, actor, lambda svc: svc.add_session_units(
            run_id,
            meeting_id,
            int(first_sequence),
            unit_count=int(units_to_add),
            unit_type=unit_type,
        )):
            st.rerun()


def render_attendance_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "course_name", "run_number", "status")
    st.session_state.setdefault("attendance_workspace_mode", "Record roster")
    mode = st.segmented_control(
        "Attendance workflow",
        ["Record roster", "Create session", "Correct absence"],
        key="attendance_workspace_mode",
    )

    if mode == "Create session":
        run_label = st.selectbox("Class and course run", [""] + list(runs), key="attendance_create_run")
        course_run_id = runs.get(run_label)
        st.subheader("Create session")
        with st.form("attendance_session_create", border=False):
            row = st.container(horizontal=True, vertical_alignment="bottom")
            with row:
                starts_on = st.date_input("Session date", value=date.today(), key="attendance_session_date")
                starts_time = st.time_input("Session time", value=time(9, 0), key="attendance_session_time")
                duration = st.number_input("Duration minutes", min_value=1, value=60, step=15, key="attendance_session_duration")
                sequence = st.number_input(
                    "Logical session number",
                    min_value=1,
                    value=_next_attendance_sequence(pool, actor, course_run_id),
                    step=1,
                    key=f"attendance_session_sequence_{course_run_id or 'none'}",
                )
                submitted = st.form_submit_button("Create session", icon=":material/add_circle:")
        if submitted:
            if not course_run_id:
                st.error("Select a class and course run first.")
            elif safe_submit(pool, actor, lambda svc: svc.create_attendance_session(
                course_run_id, datetime.combine(starts_on, starts_time), int(duration), int(sequence),
            )):
                st.rerun()
        return

    if mode == "Correct absence":
        render_attendance_makeup(pool, actor, refs)
        return

    with st.container(horizontal=True, vertical_alignment="bottom"):
        run_label = st.selectbox("Class and course run", [""] + list(runs), key="attendance_run")
        course_run_id = runs.get(run_label)
        run_units = [
            row for row in refs["session_units"]
            if row["course_run_id"] == course_run_id and row["unit_type"] != "makeup"
        ] if course_run_id else []
        units = options(run_units, "session_unit_id", "sequence_in_run", "unit_type", "starts_at", "meeting_status")
        unit_label = st.selectbox("Session", [""] + list(units), key="attendance_session")
        session_unit_id = units.get(unit_label)

    with st.container(horizontal=True):
        st.button("Create session", icon=":material/add_circle:", on_click=_set_attendance_workspace_mode, args=("Create session",))
        st.button("Correct absence", icon=":material/healing:", on_click=_set_attendance_workspace_mode, args=("Correct absence",))

    roster = None
    if course_run_id and session_unit_id:
        roster = service_values(pool, actor, lambda svc: svc.attendance_roster(course_run_id, session_unit_id))
    if course_run_id and not run_units:
        st.info("No sessions exist for the selected run.")
    elif not course_run_id or not session_unit_id:
        st.info("Select a class run and session.")
    if roster is not None:
        roster_rows = roster["rows"]
        saved_rows = sum(row["attendance_id"] is not None for row in roster_rows)
        present_rows = sum(row["effective_status"] == "Present" for row in roster_rows)
        absent_rows = sum(row["effective_status"] == "Absent" for row in roster_rows)
        missing_rows = sum(row["effective_status"] is None for row in roster_rows)
        with st.container(horizontal=True):
            st.metric("Session", roster["sequence_in_run"], border=True)
            st.metric("Status", roster["meeting_status"], border=True)
            st.metric("Learners", len(roster_rows), border=True)
            st.metric("Saved", saved_rows, border=True)
            st.metric("Present", present_rows, border=True)
            st.metric("Absent", absent_rows, border=True)
            if missing_rows:
                st.metric("Needs entry", missing_rows, border=True)
                st.warning("Historical gaps stay blank until attendance evidence is entered.")
        editor_rows = [
            {"run_enrollment_id": row["run_enrollment_id"], "employee": f"{row['emp_code']} | {row['full_name']}",
             "start_session_number": row["start_session_number"], "effective_status": row["effective_status"]}
            for row in roster_rows
        ]
        with st.form(f"attendance_roster_{session_unit_id}"):
            edited = st.data_editor(
                editor_rows,
                hide_index=True,
                disabled=["run_enrollment_id", "employee", "start_session_number"],
                column_config={
                    "run_enrollment_id": None,
                    "employee": st.column_config.TextColumn("Learner", pinned=True),
                    "start_session_number": st.column_config.NumberColumn("Starts at"),
                    "effective_status": st.column_config.SelectboxColumn("Attendance", options=["Present", "Absent"], required=True),
                },
                key=f"attendance_editor_{session_unit_id}",
            )
            submitted = st.form_submit_button("Save full roster", type="primary", icon=":material/checklist:")
        if submitted:
            records = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            if safe_submit(pool, actor, lambda svc: svc.save_attendance_roster(course_run_id, session_unit_id, records)):
                st.rerun()


def _set_attendance_workspace_mode(mode: str) -> None:
    st.session_state["attendance_workspace_mode"] = mode


def render_attendance_makeup(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    absences = queries.available_makeup_absences(pool)
    st.subheader("Record make-up attendance")
    absence_options = options(absences, "attendance_id", "class_code", "course_code", "sequence_in_run", "emp_code")
    attendance_id = selected_id("Original absence", absence_options, key="makeup_attendance")
    selected_absence = next((row for row in absences if row["attendance_id"] == attendance_id), None)
    eligible_units = [
        row for row in refs["session_units"]
        if selected_absence
        and row["course_run_id"] == selected_absence["course_run_id"]
        and row["unit_type"] == "makeup"
        and row["meeting_status"] != "cancelled"
    ]
    units = options(
        eligible_units,
        "session_unit_id",
        "class_code",
        "course_code",
        "starts_at",
        "meeting_status",
    )
    with st.form("attendance_makeup"):
        makeup_unit_id = selected_id("Make-up session", units, key="makeup_unit")
        reason = st.text_input("Reason")
        submitted = st.form_submit_button("Record make-up", icon=":material/healing:")
    if submitted and attendance_id and makeup_unit_id:
        if safe_submit(pool, actor, lambda svc: svc.correct_attendance_makeup(attendance_id, makeup_unit_id, reason)):
            st.rerun()


def render_evaluation_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    rows = queries.evaluation_outcome_rows(pool)
    enrollments = options(refs["enrollments"], "run_enrollment_id", "class_code", "course_code", "run_number", "emp_code", "status")
    levels = options(refs["levels"], "level_id", "level_name")
    courses = options(refs["courses"], "course_id", "course_code", "course_name")
    st.session_state.setdefault("evaluation_workspace_mode", "Review outcomes")
    mode = st.segmented_control(
        "Evaluation workflow",
        ["Review outcomes", "Eligibility override", "Record evaluation", "Completion"],
        key="evaluation_workspace_mode",
    )

    if mode == "Review outcomes":
        with st.container(horizontal=True):
            st.metric("Visible enrollments", len(rows), border=True)
            st.metric("Exam eligible", sum(1 for row in rows if row["effective_exam_eligible"]), border=True)
            st.metric("Evaluated", sum(1 for row in rows if row["version_number"] is not None), border=True)
            st.metric("Passed", sum(1 for row in rows if row["passed"]), border=True)
        st.dataframe(rows, hide_index=True, column_config={
            "attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent"),
            "effective_exam_eligible": st.column_config.CheckboxColumn("Exam eligible"),
            "passed": st.column_config.CheckboxColumn("Passed"),
        })
        return

    if mode == "Eligibility override":
        render_eligibility_override(pool, actor, enrollments)
        return
    if mode == "Record evaluation":
        render_evaluation_record(pool, actor, enrollments, levels, courses)
        return
    render_completion_action(pool, actor, enrollments)


def render_eligibility_override(pool, actor: AppUser, enrollments: dict[str, int]) -> None:
    with st.form("eligibility_override"):
        st.subheader("Override exam eligibility")
        enrollment_id = selected_id("Enrollment", enrollments, key="eligibility_enrollment")
        eligible = st.checkbox("Eligible for exam", value=True)
        reason = st.text_input("Override reason")
        submitted = st.form_submit_button("Save override", icon=":material/rule:")
    if submitted and enrollment_id:
        if actor.role != "admin":
            st.error("Only admins can override eligibility.")
        elif safe_submit(pool, actor, lambda svc: svc.override_exam_eligibility(enrollment_id, eligible, reason)):
            st.rerun()


def render_evaluation_record(pool, actor: AppUser, enrollments: dict[str, int], levels: dict[str, int], courses: dict[str, int]) -> None:
    enrollment_id = selected_id("Enrollment", enrollments, key="evaluation_enrollment")
    eligibility = service_values(
        pool,
        actor,
        lambda svc: svc.calculate_exam_eligibility(enrollment_id),
    ) if enrollment_id else None
    if eligibility:
        with st.container(horizontal=True):
            st.metric("Attendance", f"{eligibility['attendance_ratio']:.0%}", border=True)
            st.metric(
                "Exam eligibility",
                "Eligible" if eligibility["effective_exam_eligible"] else "Not eligible",
                border=True,
            )
            st.metric(
                "Eligibility source",
                "Admin override" if eligibility["exam_eligibility_override"] else "Attendance rule",
                border=True,
            )
    with st.form("evaluation_record"):
        st.subheader("Record or correct final evaluation")
        level_label = st.selectbox("Final level", [""] + list(levels.keys()))
        passed = st.checkbox("Passed", value=True)
        next_course_label = st.selectbox("Next course", [""] + list(courses.keys()))
        notes = st.text_area("Teacher notes")
        correction_reason = None
        if eligibility and eligibility["latest_evaluation_version"] is not None:
            correction_reason = st.text_input("Reason for changing this result")
        submitted = st.form_submit_button("Save evaluation", icon=":material/rate_review:")
    if submitted and enrollment_id:
        if safe_submit(pool, actor, lambda svc: svc.record_evaluation(
            enrollment_id,
            final_level_id=levels.get(level_label),
            passed=passed,
            next_course_id=courses.get(next_course_label),
            teacher_notes=notes.strip() or None,
            correction_reason=correction_reason,
        )):
            st.rerun()


def render_completion_action(pool, actor: AppUser, enrollments: dict[str, int]) -> None:
    with st.form("completion"):
        st.subheader("Suggest or confirm completion")
        enrollment_id = selected_id("Enrollment", enrollments, key="completion_enrollment")
        action = st.segmented_control("Action", ["Suggest", "Confirm", "Reject"], default="Suggest")
        rejection_reason = st.text_input("Rejection reason")
        submitted = st.form_submit_button("Apply completion action", icon=":material/task_alt:")
    if submitted and enrollment_id:
        def op(svc):
            if action == "Suggest":
                svc.suggest_completion(enrollment_id)
            elif action == "Confirm":
                svc.confirm_completion(enrollment_id, True)
            else:
                svc.confirm_completion(enrollment_id, False, rejection_reason)
        if action in {"Confirm", "Reject"} and actor.role != "admin":
            st.error("Only admins can confirm or reject completion.")
        elif safe_submit(pool, actor, op):
            st.rerun()


def render_review_workflow(pool, actor: AppUser) -> None:
    view = st.segmented_control("Review", ["Progress", "Monthly review", "Monthly frequency", "Data quality"], default="Progress")
    if view == "Progress":
        st.dataframe(queries.progress_trajectory_rows(pool))
        st.dataframe(queries.employee_progress_rows(pool))
    elif view == "Monthly review":
        render_monthly_review(pool, actor)
    elif view == "Monthly frequency":
        st.dataframe(queries.monthly_session_rows(pool))
    else:
        rows = queries.open_quality_issue_rows(pool)
        st.dataframe(rows)
        issue_options = options(rows, "issue_id", "issue_code", "entity_type", "entity_key", "source_sheet", "source_row_number")
        with st.form("quality_resolve"):
            issue_id = selected_id("Open quality issue", issue_options, key="quality_issue")
            status = st.selectbox("Resolution", ["resolved", "ignored"])
            note = st.text_input("Resolution note")
            submitted = st.form_submit_button("Resolve issue", icon=":material/fact_check:")
        if submitted and issue_id:
            if safe_submit(pool, actor, lambda svc: svc.resolve_quality_issue(issue_id, status, note)):
                st.rerun()


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
    st.subheader("Data issues")
    rows = _operational_issue_rows(pool)
    high_count = sum(1 for row in rows if row["severity"] == "high")
    warning_count = sum(1 for row in rows if row["severity"] == "warning")
    workflow_count = len({row["workflow"] for row in rows})
    with st.container(horizontal=True):
        st.metric("Total issues", len(rows), border=True)
        st.metric("High severity", high_count, border=True)
        st.metric("Warnings", warning_count, border=True)
        st.metric("Workflows", workflow_count, border=True)

    st.session_state.setdefault("data_issues_mode", "Issue inbox")
    mode = st.segmented_control(
        "Data issue workflow",
        ["Issue inbox", "Owner decisions", "Logged issues"],
        key="data_issues_mode",
    )
    if mode == "Owner decisions":
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
                        args=(selected_issue["workflow"],),
                    )
        else:
            st.info("No issues match the selected filters.")

        workflows = sorted({row["workflow"] for row in filtered_rows})
        with st.container(horizontal=True):
            for workflow in workflows:
                st.button(f"Open {workflow}", icon=":material/open_in_new:", key=f"issue_workflow_{workflow}",
                          on_click=_open_operation_section, args=(workflow,))
    else:
        st.success("No operational data issues are currently detected.")


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


def _open_operation_section(section: str) -> None:
    st.session_state["operations_section"] = section


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, delta: int) -> date:
    month_index = value.year * 12 + value.month - 1 + delta
    return date(month_index // 12, month_index % 12 + 1, 1)


def _shift_review_month(delta: int) -> None:
    current = st.session_state.get("monthly_review_month", date.today().replace(day=1))
    st.session_state["monthly_review_month"] = _shift_month(_month_start(current), delta)


def _percent(value) -> str:
    return f"{value:.0%}" if value is not None else "No data"


def render_monthly_review(pool, actor: AppUser) -> None:
    st.session_state.setdefault("monthly_review_month", date.today().replace(day=1))
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.button("Previous month", icon=":material/chevron_left:", on_click=_shift_review_month, args=(-1,))
        selected = st.date_input("Review month", key="monthly_review_month")
        st.button("Next month", icon=":material/chevron_right:", on_click=_shift_review_month, args=(1,))
    review_month = _month_start(selected)
    data = monthly_review_data(pool, review_month)
    summary = monthly_review_summary(data)
    st.session_state.setdefault("monthly_review_mode", "Overview")
    mode = st.segmented_control(
        "Monthly review workflow",
        ["Overview", "Detail tables", "Summary export"],
        key="monthly_review_mode",
    )
    with st.container(horizontal=True):
        st.metric("Active participants", summary["active"], border=True)
        st.metric("Repeated participants", summary["repeated"], border=True)
        st.metric("Planned / delivered sessions", f"{summary['planned']} / {summary['delivered']}", f"{summary['variance']:+d}", border=True)
        st.metric("Delivery rate", _percent(summary["delivery_rate"]), border=True)
        st.metric("Overall attendance", _percent(summary["attendance_ratio"]), border=True)
        st.metric("Below threshold", summary["low_count"], _percent(summary["low_rate"]), border=True, delta_color="inverse")
        st.metric("Improved latest test", f"{summary['improved_count']} / {summary['tested_count']}", _percent(summary["improved_rate"]), border=True)

    if mode == "Summary export":
        render_monthly_action_summary(pool, actor, review_month, data, summary)
        return
    if mode == "Detail tables":
        render_monthly_detail_tables(data, summary)
        return

    with st.container(border=True):
        st.subheader("Program status")
        if data["program"]:
            st.bar_chart(data["program"], x="class_code", y=["planned_sessions", "delivered_sessions"])
            st.dataframe(data["program"], hide_index=True)
        else:
            st.info("No program activity for this month.")
    with st.container(border=True):
        st.subheader("Participation")
        if data["course_participation"]:
            st.bar_chart(data["course_participation"], x="course_name", y="attendance_ratio")
        else:
            st.info("No participation activity for this month.")
    with st.container(border=True):
        st.subheader("Learning progress")
        if data["level_distribution"]:
            st.bar_chart(data["level_distribution"], x="course_name", y="learner_count", color="latest_level")
        else:
            st.info("No final evaluation activity for this month.")


def render_monthly_detail_tables(data: dict, summary: dict) -> None:
    with st.container(border=True):
        st.subheader("Program status")
        st.dataframe(data["program"], hide_index=True)
    with st.container(border=True):
        st.subheader("Participation")
        st.dataframe(data["course_participation"], hide_index=True, column_config={
            "attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent"),
        })
        st.dataframe(data["class_participation"], hide_index=True, column_config={
            "attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent"),
        })
        st.dataframe(data["participation"], hide_index=True, column_config={
            "attendance_threshold": st.column_config.NumberColumn("Threshold", format="percent"),
            "attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent"),
        })
    with st.container(border=True):
        st.subheader("Learning progress")
        st.dataframe(data["level_distribution"], hide_index=True)
        st.dataframe(data["progress"], hide_index=True)
        st.metric("Courses created", summary["new_course_count"], border=True)
        st.dataframe(data["new_courses"], hide_index=True)


def render_monthly_action_summary(pool, actor: AppUser, review_month: date, data: dict, summary: dict) -> None:
    proposed = proposed_monthly_actions(summary)
    saved = data["action_summary"]
    defaults = saved or proposed
    st.subheader("Action summary")
    if saved:
        st.badge("Saved summary", icon=":material/check_circle:", color="green")
    else:
        st.badge("Draft proposal", icon=":material/edit:", color="orange")
    with st.form("monthly_action_summary"):
        highlights = st.text_area("Highlights", value=defaults["highlights"])
        risks = st.text_area("Risks", value=defaults["risks"])
        priorities = st.text_area("Next-month priorities", value=defaults["next_month_priorities"])
        save_clicked = st.form_submit_button("Save action summary", icon=":material/save:")
        export_clicked = st.form_submit_button("Prepare Excel export", icon=":material/download:")
    if save_clicked:
        if safe_submit(pool, actor, lambda svc: svc.save_monthly_action_summary(
            review_month, highlights=highlights, risks=risks, next_month_priorities=priorities,
        )):
            st.rerun()
    if export_clicked:
        st.session_state["monthly_review_export"] = monthly_review_xlsx(
            review_month, data,
            {"highlights": highlights, "risks": risks, "next_month_priorities": priorities},
        )
        st.session_state["monthly_review_export_name"] = f"english-class-monthly-review-{review_month.isoformat()}.xlsx"
    if st.session_state.get("monthly_review_export"):
        st.download_button("Download Excel review", data=st.session_state["monthly_review_export"],
                           file_name=st.session_state["monthly_review_export_name"],
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           icon=":material/download:")
