"""Meeting schedule entry, revision, cancellation, and credited units.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import options, safe_submit, selected_id


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
