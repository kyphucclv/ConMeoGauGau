"""Monthly review dashboards, detail tables, and action summary export.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from auth import AppUser
from reporting import monthly_review_data, monthly_review_summary, monthly_review_xlsx, proposed_monthly_actions
from frontend_workflows.shared import safe_submit


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
