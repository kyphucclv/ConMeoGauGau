"""Streamlit admin workflows backed by Phase 4 services."""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from auth import AppUser
from db import fetch_all, pooled_connection
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
    rows = fetch_all(pool, """
        SELECT
            (SELECT count(*) FROM employees WHERE employment_status='active') AS active_people,
            (SELECT count(*) FROM run_enrollments WHERE status='active') AS current_learners,
            (SELECT count(*) FROM course_runs WHERE status IN ('planned','active')) AS open_classes,
            (SELECT count(*) FROM v_operational_data_issues) AS review_items,
            (SELECT count(*) FROM v_operational_data_issues WHERE severity='high') AS urgent_items,
            (SELECT count(*) FROM data_quality_issues WHERE status='open') AS follow_ups
    """)
    summary = rows[0] if rows else {
        "active_people": 0,
        "current_learners": 0,
        "open_classes": 0,
        "review_items": 0,
        "urgent_items": 0,
        "follow_ups": 0,
    }
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
    return {
        "business_units": fetch_all(pool, "SELECT business_unit_id, business_unit_name FROM business_units WHERE is_active ORDER BY business_unit_name"),
        "job_roles": fetch_all(pool, "SELECT job_role_id, job_role_name FROM job_roles WHERE is_active ORDER BY job_role_name"),
        "employees": fetch_all(pool, "SELECT employee_id, emp_code, full_name FROM employees ORDER BY full_name LIMIT 500"),
        "cohorts": fetch_all(pool, "SELECT cohort_id, class_code, display_name, status FROM cohorts ORDER BY class_code LIMIT 500"),
        "active_memberships": fetch_all(pool, """
            SELECT cm.cohort_membership_id, cm.employee_id, e.emp_code, e.full_name, c.class_code
            FROM cohort_memberships cm
            JOIN employees e ON e.employee_id=cm.employee_id
            JOIN cohorts c ON c.cohort_id=cm.cohort_id
            WHERE cm.status='active'
            ORDER BY c.class_code, e.full_name
            LIMIT 500
        """),
        "courses": fetch_all(pool, "SELECT course_id, course_code, course_name, expected_units FROM courses WHERE is_active ORDER BY course_name"),
        "pic_labels": fetch_all(pool, """
            SELECT DISTINCT ON (lower(pic_label)) pic_label
            FROM cohort_pic_assignments
            WHERE pic_label IS NOT NULL
            ORDER BY lower(pic_label), cohort_pic_assignment_id DESC
            LIMIT 200
        """),
        "course_runs": fetch_all(pool, """
            SELECT cr.course_run_id, c.class_code, co.course_code, co.course_name, cr.run_number, cr.status
            FROM course_runs cr
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_name, cr.run_number
            LIMIT 500
        """),
        "enrollments": fetch_all(pool, """
            SELECT re.run_enrollment_id, e.emp_code, e.full_name, c.class_code, co.course_code,
                   co.course_name, cr.run_number, re.status, re.start_session_number
            FROM run_enrollments re
            JOIN employees e ON e.employee_id=re.employee_id
            JOIN course_runs cr ON cr.course_run_id=re.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_name, cr.run_number, e.full_name
            LIMIT 500
        """),
        "meetings": fetch_all(pool, """
            SELECT m.meeting_id, m.course_run_id, c.class_code, co.course_code, cr.run_number,
                   m.starts_at, m.duration_minutes, m.status, m.cancellation_reason
            FROM meetings m
            JOIN course_runs cr ON cr.course_run_id=m.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY m.starts_at DESC
            LIMIT 500
        """),
        "session_units": fetch_all(pool, """
            SELECT su.session_unit_id, su.course_run_id, c.class_code, co.course_code, cr.run_number,
                   su.sequence_in_run, su.unit_type, m.starts_at, m.status AS meeting_status
            FROM session_units su
            JOIN meetings m ON m.meeting_id=su.meeting_id
            JOIN course_runs cr ON cr.course_run_id=su.course_run_id
            JOIN cohorts c ON c.cohort_id=cr.cohort_id
            JOIN courses co ON co.course_id=cr.course_id
            ORDER BY c.class_code, co.course_code, cr.run_number, su.sequence_in_run
            LIMIT 700
        """),
        "levels": fetch_all(pool, "SELECT level_id, level_name FROM levels WHERE is_active ORDER BY sequence_order"),
    }


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
    return fetch_all(pool, """
        SELECT e.employee_id, e.emp_code, e.full_name, e.employment_status,
               bu.business_unit_name, jr.job_role_name,
               c.class_code, co.course_name, co.course_code, re.run_enrollment_id,
               re.status AS enrollment_status, re.start_session_number,
               l.level_name AS entrance_level, attendance.attendance_ratio,
               COALESCE(cpa.pic_label, pic.full_name) AS pic
        FROM employees e
        LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
        LEFT JOIN business_units bu ON bu.business_unit_id=eoh.business_unit_id
        LEFT JOIN job_roles jr ON jr.job_role_id=eoh.job_role_id
        LEFT JOIN run_enrollments re ON re.employee_id=e.employee_id AND re.status='active'
        LEFT JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        LEFT JOIN cohorts c ON c.cohort_id=cr.cohort_id
        LEFT JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN cohort_pic_assignments cpa ON cpa.cohort_id=c.cohort_id AND cpa.end_date IS NULL
        LEFT JOIN employees pic ON pic.employee_id=cpa.pic_employee_id
        LEFT JOIN placements p ON p.employee_id=e.employee_id AND p.placement_kind='business'
        LEFT JOIN levels l ON l.level_id=p.level_id
        LEFT JOIN v_run_enrollment_attendance attendance ON attendance.run_enrollment_id=re.run_enrollment_id
        ORDER BY e.full_name, e.emp_code
        LIMIT 500
    """)


def _capacity_context(pool, course_run_id: int | None) -> dict | None:
    if not course_run_id:
        return None
    rows = fetch_all(pool, """
        SELECT c.class_code, c.capacity, count(cm.cohort_membership_id) FILTER (WHERE cm.status='active') AS active_learners
        FROM course_runs cr JOIN cohorts c ON c.cohort_id=cr.cohort_id
        LEFT JOIN cohort_memberships cm ON cm.cohort_id=c.cohort_id
        WHERE cr.course_run_id=%s GROUP BY c.class_code,c.capacity
    """, (course_run_id,))
    return rows[0] if rows else None


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
    """Desktop-first learner search, onboarding, correction, and transfer workspace."""
    st.session_state.setdefault("learner_workspace_mode", "Find learner")
    mode = st.segmented_control(
        "Learner workflow",
        ["Find learner", "Add learner", "Create class"],
        key="learner_workspace_mode",
    )

    if mode == "Add learner":
        render_learner_onboarding(pool, actor, refs)
        return
    if mode == "Create class":
        render_class_course_run_creator(pool, actor, refs)
        return

    rows = _learner_rows(pool)
    bu_names = sorted({row["business_unit_name"] for row in rows if row["business_unit_name"]})
    role_names = sorted({row["job_role_name"] for row in rows if row["job_role_name"]})
    class_codes = sorted({row["class_code"] for row in rows if row["class_code"]})
    course_names = sorted({row["course_name"] for row in rows if row["course_name"]})
    pic_names = sorted({row["pic"] for row in rows if row["pic"]})

    with st.form("learner_filters", border=False):
        search = st.text_input("Search by employee code or name", value=st.session_state.get("learner_search", ""))
        filter_row = st.container(horizontal=True)
        with filter_row:
            class_filter = st.selectbox("Class", ["All"] + class_codes)
            course_filter = st.selectbox("Course", ["All"] + course_names)
            pic_filter = st.selectbox("PIC", ["All"] + pic_names)
            active_filter = st.segmented_control("Enrollment", ["All", "Active", "Inactive"], default="All")
        org_filter_row = st.container(horizontal=True)
        with org_filter_row:
            bu_filter = st.selectbox("Business unit", ["All"] + bu_names)
            role_filter = st.selectbox("Role", ["All"] + role_names)
            submitted = st.form_submit_button("Apply filters", icon=":material/search:")
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
            and (active_filter == "All" or (active_filter == "Active") == (row["enrollment_status"] == "active"))
        )

    filtered = [row for row in rows if matches(row)]
    active_count = sum(1 for row in filtered if row["enrollment_status"] == "active")
    missing_placement_count = sum(1 for row in filtered if not row["entrance_level"])
    with st.container(horizontal=True):
        st.metric("Results", len(filtered), border=True)
        st.metric("Active", active_count, border=True)
        st.metric("Missing placement", missing_placement_count, border=True)
    with st.container(horizontal=True):
        st.button("Add learner", icon=":material/person_add:", on_click=_set_learner_workspace_mode, args=("Add learner",))
        st.button("Create class", icon=":material/add_circle:", on_click=_set_learner_workspace_mode, args=("Create class",))
    event = st.dataframe(filtered, hide_index=True, key="learner_results", on_select="rerun", selection_mode="single-row", column_config={
        "employee_id": None, "run_enrollment_id": None,
        "attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent"),
        "start_session_number": st.column_config.NumberColumn("Start session"),
    })
    selected = filtered[event.selection.rows[0]] if event.selection.rows else None
    if selected:
        render_learner_detail(pool, actor, refs, selected)


def _set_learner_workspace_mode(mode: str) -> None:
    st.session_state["learner_workspace_mode"] = mode


def render_learner_detail(pool, actor: AppUser, refs: dict[str, list[dict]], learner: dict) -> None:
    st.subheader(f"{learner['full_name']} · {learner['emp_code']}")
    metrics = st.columns(4)
    metrics[0].metric("Current class", learner["class_code"] or "Not enrolled")
    metrics[1].metric("Course", learner["course_name"] or "—")
    metrics[2].metric("Entrance level", learner["entrance_level"] or "Not set")
    metrics[3].metric("Attendance", f"{learner['attendance_ratio']:.0%}" if learner["attendance_ratio"] is not None else "No sessions")

    bu = options(refs["business_units"], "business_unit_id", "business_unit_name")
    roles = options(refs["job_roles"], "job_role_id", "job_role_name")
    current_bu = next((label for label, item_id in bu.items() if item_id and label == learner["business_unit_name"]), "")
    current_role = next((label for label, item_id in roles.items() if item_id and label == learner["job_role_name"]), "")
    with st.form(f"learner_edit_{learner['employee_id']}"):
        st.markdown("Employee identity and current organization")
        st.text_input("Employee code", value=learner["emp_code"], disabled=True)
        full_name = st.text_input("Full name", value=learner["full_name"])
        status = st.selectbox("Employment status", ["active", "inactive", "unknown"], index=["active", "inactive", "unknown"].index(learner["employment_status"]))
        business_unit = st.selectbox("Business unit", [""] + list(bu), index=([""] + list(bu)).index(current_bu) if current_bu else 0)
        job_role = st.selectbox("Job role", [""] + list(roles), index=([""] + list(roles)).index(current_role) if current_role else 0)
        submitted = st.form_submit_button("Save employee changes", icon=":material/save:")
    if submitted:
        if safe_submit(pool, actor, lambda svc: svc.create_or_update_employee(
            learner["emp_code"], full_name, employment_status=status,
            business_unit_id=bu.get(business_unit), job_role_id=roles.get(job_role), valid_from=date.today(),
        )):
            st.rerun()

    history = fetch_all(pool, """
        SELECT cr.start_date, c.class_code, co.course_name, re.status, re.start_session_number,
               rea.attendance_ratio, lev.final_level_id, ev.passed
        FROM run_enrollments re JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN v_latest_evaluation_versions ev ON ev.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN evaluation_versions lev ON lev.evaluation_version_id=ev.evaluation_version_id
        WHERE re.employee_id=%s ORDER BY re.created_at DESC
    """, (learner["employee_id"],))
    st.markdown("Course history")
    st.dataframe(history, hide_index=True, column_config={"attendance_ratio": st.column_config.NumberColumn("Attendance", format="percent")})

    audit = fetch_all(pool, """SELECT created_at, actor_username, action, details FROM audit_events
                               WHERE (entity_type='employee' AND entity_key=%s)
                                  OR details->>'employee_id'=%s
                               ORDER BY created_at DESC LIMIT 100""", (str(learner["employee_id"]), str(learner["employee_id"])))
    with st.expander("Audit history"):
        st.dataframe(audit, hide_index=True)

    active_enrollment_id = learner["run_enrollment_id"]
    if active_enrollment_id:
        render_learner_transfer(pool, actor, refs, active_enrollment_id)


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
    st.subheader("Add learner")
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "course_name", "run_number", "status")
    bu = options(refs["business_units"], "business_unit_id", "business_unit_name")
    roles = options(refs["job_roles"], "job_role_id", "job_role_name")
    levels = options(refs["levels"], "level_id", "level_name")
    directory = {"Create a new employee": None}
    directory.update({f"{row['emp_code']} | {row['full_name']}": row for row in _learner_rows(pool)})
    known_label = st.selectbox("Employee directory lookup", list(directory), key="onboard_employee_lookup")
    known_employee = directory[known_label]
    run_label = st.selectbox("Class and course run", [""] + list(runs), key="onboard_run")
    course_run_id = runs.get(run_label)
    capacity = _capacity_context(pool, course_run_id)
    if capacity:
        limit = str(capacity["capacity"]) if capacity["capacity"] is not None else "Not set"
        st.info(f"{capacity['class_code']}: {capacity['active_learners']} active learner(s) / capacity {limit}")
    start_session_proposal = _onboarding_start_proposal(pool, actor, course_run_id)
    if start_session_proposal is not None:
        st.info(f"First applicable session starts at {start_session_proposal} for this run.")
    default_bu = known_employee["business_unit_name"] if known_employee else ""
    default_role = known_employee["job_role_name"] if known_employee else ""
    default_level = known_employee["entrance_level"] if known_employee else ""
    bu_labels = [""] + list(bu)
    role_labels = [""] + list(roles)
    level_labels = [""] + list(levels)
    if known_employee and known_employee["enrollment_status"] == "active":
        st.warning("This employee already has an active course. Use Transfer learner to move classes.")
    elif default_level:
        st.info(f"Existing entrance placement will be retained: {default_level}.")
    with st.form("learner_onboarding"):
        emp_code = st.text_input("Employee code", value=known_employee["emp_code"] if known_employee else "", disabled=bool(known_employee))
        full_name = st.text_input("Full name", value=known_employee["full_name"] if known_employee else "")
        business_unit = st.selectbox("Business unit", bu_labels, index=bu_labels.index(default_bu) if default_bu in bu_labels else 0)
        job_role = st.selectbox("Job role", role_labels, index=role_labels.index(default_role) if default_role in role_labels else 0)
        entrance_level = st.selectbox(
            "Entrance placement",
            level_labels,
            index=level_labels.index(default_level) if default_level in level_labels else 0,
        )
        joined_on = st.date_input("Joined on", value=date.today())
        start_session = st.number_input(
            "First applicable session",
            min_value=1,
            value=start_session_proposal or 1,
            step=1,
            key=f"onboard_start_session_{course_run_id or 'none'}",
        )
        allow_override = st.checkbox("Approve capacity override")
        override_reason = st.text_input("Override reason", disabled=not allow_override)
        submitted = st.form_submit_button("Add learner", type="primary", icon=":material/person_add:")
    if submitted:
        if not course_run_id:
            st.error("Select a class and course run.")
        elif not business_unit or not job_role or not entrance_level:
            st.error("Business unit, role, and entrance level are required.")
        elif safe_submit(pool, actor, lambda svc: svc.onboard_learner(
            emp_code=emp_code, full_name=full_name, business_unit_id=bu[business_unit], job_role_id=roles[job_role],
            entrance_level_id=levels[entrance_level], course_run_id=course_run_id, joined_on=joined_on,
            start_session_number=int(start_session), capacity_override_reason=override_reason if allow_override else None,
        )):
            st.rerun()


def render_learner_transfer(pool, actor: AppUser, refs: dict[str, list[dict]], enrollment_id: int) -> None:
    st.markdown("Transfer learner")
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "course_name", "run_number", "status")
    target_label = st.selectbox("Target class and course run", [""] + list(runs), key=f"transfer_target_{enrollment_id}")
    target_run_id = runs.get(target_label)
    proposal = _transfer_start_proposal(pool, actor, target_run_id)
    if proposal is not None:
        st.info(f"Attendance will start at target logical session {proposal}.")
    with st.form(f"learner_transfer_{enrollment_id}"):
        transfer_date = st.date_input("Transfer date", value=date.today())
        confirm = st.checkbox("I confirm the proposed target start session")
        submitted = st.form_submit_button("Transfer learner", icon=":material/swap_horiz:")
    if submitted:
        if not target_run_id or proposal is None:
            st.error("Select a target course run.")
        elif not confirm:
            st.error("Confirm the proposed start session before transferring.")
        elif safe_submit(pool, actor, lambda svc: svc.transfer_learner(
            enrollment_id, target_run_id, transfer_date, confirmed_start_session_number=proposal,
        )):
            st.rerun()


def render_employee_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    search = st.text_input("Search employees", key="employee_search")
    rows = fetch_all(
        pool,
        """
        SELECT emp_code, full_name, employment_status, business_unit_name, job_role_name,
               class_code, course_name, enrollment_status
        FROM v_current_employee_state
        WHERE %s = '' OR emp_code ILIKE %s OR full_name ILIKE %s
        ORDER BY full_name
        LIMIT 100
        """,
        (search.strip(), f"%{search.strip()}%", f"%{search.strip()}%"),
    )
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
    st.dataframe(fetch_all(pool, """
        SELECT c.class_code, c.display_name, c.status,
               COALESCE(cpa.pic_label, pe.full_name) AS current_pic,
               c.created_at
        FROM cohorts c
        LEFT JOIN cohort_pic_assignments cpa
          ON cpa.cohort_id = c.cohort_id AND cpa.end_date IS NULL
        LEFT JOIN employees pe ON pe.employee_id = cpa.pic_employee_id
        ORDER BY c.class_code
        LIMIT 200
    """))
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
    st.dataframe(fetch_all(pool, "SELECT * FROM v_cohort_course_run_dashboard ORDER BY class_code, course_name, run_number LIMIT 200"))
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
    st.dataframe(fetch_all(pool, """
        SELECT c.class_code, co.course_code, cr.run_number, m.starts_at, m.duration_minutes,
               m.status, su.sequence_in_run, su.unit_type
        FROM meetings m
        JOIN course_runs cr ON cr.course_run_id=m.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN session_units su ON su.meeting_id=m.meeting_id
        ORDER BY m.starts_at DESC, su.sequence_in_run
        LIMIT 250
    """))
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
    absences = fetch_all(pool, """
        SELECT a.attendance_id, re.course_run_id, e.emp_code, e.full_name, c.class_code, co.course_code,
               su.sequence_in_run, a.effective_status
        FROM attendance a
        JOIN run_enrollments re ON re.run_enrollment_id=a.run_enrollment_id
        JOIN employees e ON e.employee_id=re.employee_id
        JOIN session_units su ON su.session_unit_id=a.session_unit_id
        JOIN course_runs cr ON cr.course_run_id=su.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        JOIN meetings m ON m.meeting_id=su.meeting_id
        WHERE a.effective_status='Absent'
          AND NOT a.is_makeup
          AND m.status='completed'
          AND NOT EXISTS (
              SELECT 1 FROM attendance makeup
              WHERE makeup.makeup_for_attendance_id=a.attendance_id
          )
        ORDER BY a.updated_at DESC
        LIMIT 300
    """)
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
    rows = fetch_all(pool, """
        SELECT e.emp_code, e.full_name, c.class_code, co.course_code, cr.run_number,
               rea.attendance_ratio, rea.effective_exam_eligible, lev.version_number,
               l.level_name AS final_level, lev.passed, next_course.course_code AS next_course
        FROM run_enrollments re
        JOIN employees e ON e.employee_id=re.employee_id
        JOIN course_runs cr ON cr.course_run_id=re.course_run_id
        JOIN cohorts c ON c.cohort_id=cr.cohort_id
        JOIN courses co ON co.course_id=cr.course_id
        LEFT JOIN v_run_enrollment_attendance rea ON rea.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN v_latest_evaluation_versions lev ON lev.run_enrollment_id=re.run_enrollment_id
        LEFT JOIN levels l ON l.level_id=lev.final_level_id
        LEFT JOIN courses next_course ON next_course.course_id=lev.next_course_id
        ORDER BY c.class_code, co.course_code, cr.run_number, e.full_name
        LIMIT 250
    """)
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
        st.dataframe(fetch_all(pool, "SELECT * FROM v_progress_trajectory ORDER BY emp_code, event_at NULLS FIRST LIMIT 300"))
        st.dataframe(fetch_all(pool, "SELECT * FROM v_employee_progress_summary ORDER BY full_name LIMIT 300"))
    elif view == "Monthly review":
        render_monthly_review(pool, actor)
    elif view == "Monthly frequency":
        st.dataframe(fetch_all(pool, "SELECT * FROM v_monthly_session_units ORDER BY session_month DESC, course_run_id LIMIT 300"))
    else:
        rows = fetch_all(pool, """
            SELECT issue_id, issue_code, entity_type, entity_key, source_sheet,
                   source_row_number, details, created_at
            FROM data_quality_issues
            WHERE status='open'
            ORDER BY created_at DESC
            LIMIT 300
        """)
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
    return fetch_all(pool, """
        SELECT severity, issue_code, entity_type, entity_key, title, workflow, details
        FROM v_operational_data_issues
        ORDER BY CASE severity WHEN 'high' THEN 0 ELSE 1 END, issue_code, entity_key
        LIMIT 500
    """)


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
    ledger_rows = fetch_all(pool, """
        SELECT issue_id,issue_code,entity_type,entity_key,source_sheet,source_row_number,details,created_at
        FROM data_quality_issues WHERE status='open' ORDER BY created_at DESC LIMIT 300
    """)
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
