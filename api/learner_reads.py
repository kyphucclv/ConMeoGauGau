"""Endpoint-oriented learner read models.

This module owns filtering, stable ordering, and pagination so HTTP and UI
adapters cannot accidentally load and filter the legacy 500-row snapshot.
"""

from __future__ import annotations

from datetime import date, datetime

from typing import Literal

from pydantic import BaseModel

from db import fetch_all, fetch_one
from frontend_queries import employee_audit_rows, learner_course_history, learner_journey_context


class LearnerListItem(BaseModel):
    employee_id: int
    emp_code: str
    full_name: str
    employment_status: str
    business_unit_name: str | None = None
    job_role_name: str | None = None
    class_code: str | None = None
    course_name: str | None = None
    course_code: str | None = None
    enrollment_status: str | None = None
    attendance_ratio: float | None = None
    entrance_level: str | None = None
    pic: str | None = None


class LearnerPage(BaseModel):
    items: list[LearnerListItem]
    page: int
    page_size: int
    total: int
    sort: str = "full_name_asc_emp_code_asc"


class LearnerJourney(BaseModel):
    employee_id: int
    emp_code: str
    full_name: str
    employment_status: str
    business_unit_id: int | None = None
    business_unit_name: str | None = None
    job_role_id: int | None = None
    job_role_name: str | None = None
    current_org_valid_from: date | None = None
    placement_id: int | None = None
    entrance_level_id: int | None = None
    entrance_level: str | None = None
    active_enrollment_id: int | None = None
    active_course_run_id: int | None = None
    active_cohort_id: int | None = None
    active_class_code: str | None = None
    active_course_name: str | None = None
    active_membership_id: int | None = None
    membership_cohort_id: int | None = None
    membership_class_code: str | None = None
    latest_enrollment_status: str | None = None
    latest_class_code: str | None = None
    latest_course_name: str | None = None
    membership_count: int
    lifecycle: str


class CourseHistoryItem(BaseModel):
    start_date: date | None
    class_code: str
    course_name: str
    status: str
    start_session_number: int
    attendance_ratio: float | None = None
    final_level: str | None = None
    passed: bool | None = None


class LearnerAuditItem(BaseModel):
    created_at: datetime
    actor_username: str
    action: str


class LearnerDetail(BaseModel):
    learner: LearnerJourney
    course_history: list[CourseHistoryItem]
    audit_summary: list[LearnerAuditItem]


class LearnerReadService:
    def __init__(self, pool):
        self._pool = pool

    def search(
        self,
        *,
        q: str,
        learning_status: Literal["all", "current", "not_current"],
        class_code: str | None,
        course: str | None,
        pic: str | None,
        business_unit: str | None,
        job_role: str | None,
        page: int,
        page_size: int,
    ) -> LearnerPage:
        term = q.strip()
        match = f"%{term}%"
        clauses = ["(%s = '' OR e.emp_code ILIKE %s OR e.full_name ILIKE %s)"]
        params: list[object] = [term, match, match]
        if learning_status == "current":
            clauses.append("re.run_enrollment_id IS NOT NULL")
        elif learning_status == "not_current":
            clauses.append("re.run_enrollment_id IS NULL")
        for value, column in (
            (class_code, "c.class_code"),
            (course, "co.course_name"),
            (pic, "COALESCE(cpa.pic_label, pic.full_name)"),
            (business_unit, "bu.business_unit_name"),
            (job_role, "jr.job_role_name"),
        ):
            if value:
                clauses.append(f"{column} = %s")
                params.append(value)
        where = " AND ".join(clauses)
        joins = """
            FROM employees e
            LEFT JOIN employee_org_history eoh
              ON eoh.employee_id=e.employee_id AND eoh.is_current
            LEFT JOIN business_units bu ON bu.business_unit_id=eoh.business_unit_id
            LEFT JOIN job_roles jr ON jr.job_role_id=eoh.job_role_id
            LEFT JOIN run_enrollments re
              ON re.employee_id=e.employee_id AND re.status='active'
            LEFT JOIN course_runs cr ON cr.course_run_id=re.course_run_id
            LEFT JOIN cohorts c ON c.cohort_id=cr.cohort_id
            LEFT JOIN courses co ON co.course_id=cr.course_id
            LEFT JOIN cohort_pic_assignments cpa
              ON cpa.cohort_id=c.cohort_id AND cpa.end_date IS NULL
            LEFT JOIN employees pic ON pic.employee_id=cpa.pic_employee_id
            LEFT JOIN placements p
              ON p.employee_id=e.employee_id AND p.placement_kind='business'
            LEFT JOIN levels level ON level.level_id=p.level_id
            LEFT JOIN v_run_enrollment_attendance attendance
              ON attendance.run_enrollment_id=re.run_enrollment_id
        """
        total_row = fetch_one(
            self._pool,
            f"SELECT count(*) AS total {joins} WHERE {where}",
            params,
        )
        rows = fetch_all(
            self._pool,
            f"""
            SELECT e.employee_id, e.emp_code, e.full_name, e.employment_status,
                   bu.business_unit_name, jr.job_role_name,
                   c.class_code, co.course_name, co.course_code,
                   re.status AS enrollment_status,
                   attendance.attendance_ratio,
                   level.level_name AS entrance_level,
                   COALESCE(cpa.pic_label, pic.full_name) AS pic
            {joins}
            WHERE {where}
            ORDER BY lower(e.full_name), lower(e.emp_code), e.employee_id
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        return LearnerPage(
            items=[LearnerListItem.model_validate(row) for row in rows],
            page=page,
            page_size=page_size,
            total=int(total_row["total"] if total_row else 0),
        )

    def detail(self, employee_id: int) -> LearnerDetail | None:
        context = learner_journey_context(self._pool, employee_id)
        if context is None:
            return None
        return LearnerDetail(
            learner=LearnerJourney.model_validate(context),
            course_history=[
                CourseHistoryItem.model_validate(row)
                for row in learner_course_history(self._pool, employee_id)
            ],
            audit_summary=[
                LearnerAuditItem.model_validate(row)
                for row in employee_audit_rows(self._pool, employee_id)
            ],
        )
