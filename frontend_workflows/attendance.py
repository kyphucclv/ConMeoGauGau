"""Attendance roster entry, session creation, and make-up correction.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import (
    _next_attendance_sequence,
    options,
    safe_submit,
    selected_id,
    service_values,
)


def render_attendance_workflow(pool, actor: AppUser, refs: dict[str, list[dict]]) -> None:
    runs = options(refs["course_runs"], "course_run_id", "class_code", "course_code", "course_name", "run_number", "status")
    st.session_state.setdefault("attendance_workspace_mode", "Mark attendance")
    mode = st.segmented_control(
        "Attendance workflow",
        ["Mark attendance", "Create session", "Record make-up"],
        key="attendance_workspace_mode",
    )

    if mode == "Create session":
        run_label = st.selectbox("Class and course", [""] + list(runs), key="attendance_create_run")
        course_run_id = runs.get(run_label)
        st.subheader("Create session")
        with st.form("attendance_session_create", border=False):
            row = st.container(horizontal=True, vertical_alignment="bottom")
            with row:
                starts_on = st.date_input("Session date", value=date.today(), key="attendance_session_date")
                starts_time = st.time_input("Session time", value=time(9, 0), key="attendance_session_time")
                duration = st.number_input("Duration minutes", min_value=1, value=60, step=15, key="attendance_session_duration")
                sequence = st.number_input(
                    "Session number",
                    min_value=1,
                    value=_next_attendance_sequence(pool, actor, course_run_id),
                    step=1,
                    help="Position of this session in the course, starting at 1.",
                    key=f"attendance_session_sequence_{course_run_id or 'none'}",
                )
                submitted = st.form_submit_button("Create session", icon=":material/add_circle:")
        if submitted:
            if not course_run_id:
                st.error("Select a class and course first.")
            elif safe_submit(pool, actor, lambda svc: svc.create_attendance_session(
                course_run_id, datetime.combine(starts_on, starts_time), int(duration), int(sequence),
            )):
                st.rerun()
        return

    if mode == "Record make-up":
        render_attendance_makeup(pool, actor, refs)
        return

    with st.container(horizontal=True, vertical_alignment="bottom"):
        run_label = st.selectbox("Class and course", [""] + list(runs), key="attendance_run")
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
        st.button("Record make-up", icon=":material/healing:", on_click=_set_attendance_workspace_mode, args=("Record make-up",))

    roster = None
    if course_run_id and session_unit_id:
        roster = service_values(pool, actor, lambda svc: svc.attendance_roster(course_run_id, session_unit_id))
    if course_run_id and not run_units:
        st.info("This class has no sessions yet. Use 'Create session' first.")
    elif not course_run_id or not session_unit_id:
        st.info("Select a class and a session to mark attendance.")
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
                    "start_session_number": st.column_config.NumberColumn(
                        "Joined at session", help="The learner's first applicable session in this course."
                    ),
                    "effective_status": st.column_config.SelectboxColumn("Attendance", options=["Present", "Absent"], required=True),
                },
                key=f"attendance_editor_{session_unit_id}",
            )
            submitted = st.form_submit_button("Save attendance", type="primary", icon=":material/checklist:")
        if submitted:
            records = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            if safe_submit(pool, actor, lambda svc: svc.save_attendance_roster(
                course_run_id, session_unit_id, records, roster_token=roster["roster_token"],
            )):
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
