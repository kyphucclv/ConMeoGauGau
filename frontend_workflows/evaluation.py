"""Final-result review, eligibility override, evaluation, completion.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

import streamlit as st

from auth import AppUser
import frontend_queries as queries
from frontend_workflows.shared import options, safe_submit, selected_id, service_values


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
