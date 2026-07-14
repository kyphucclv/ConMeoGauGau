"""Shared UI constants, service-call helpers, and lookup builders.

Split verbatim from the original frontend_workflows.py; behavior unchanged.
"""

from __future__ import annotations

import streamlit as st

from auth import AppUser
from db import pooled_connection
import frontend_queries as queries
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


def _open_operation_section(section: str) -> None:
    st.session_state["operations_section"] = section
