"""HTTP seam for lifecycle-aware learner starts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db import fetch_all, pooled_connection
from services import BusinessService


class StartReferenceOption(BaseModel):
    id: int
    name: str


class StartCourseRunOption(BaseModel):
    course_run_id: int
    cohort_id: int
    class_code: str
    course_code: str
    course_name: str
    run_number: int
    run_status: Literal["planned", "active"]
    start_date: date | None = None
    capacity: int | None = None
    active_learners: int
    proposed_start_session_number: int


class LearnerStartOptions(BaseModel):
    business_units: list[StartReferenceOption]
    job_roles: list[StartReferenceOption]
    entrance_levels: list[StartReferenceOption]
    course_runs: list[StartCourseRunOption]


class LearnerStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(min_length=1, max_length=100)
    expected_employee_id: int | None
    full_name: str = Field(min_length=1, max_length=300)
    employment_status: Literal["active", "inactive", "unknown"] = "active"
    business_unit_id: int = Field(gt=0)
    job_role_id: int = Field(gt=0)
    entrance_level_id: int = Field(gt=0)
    course_run_id: int = Field(gt=0)
    joined_on: date
    confirmed_start_session_number: int = Field(gt=0)
    capacity_override_reason: str | None = Field(default=None, max_length=1000)


class LearnerStartResult(BaseModel):
    run_enrollment_id: int
    employee_id: int
    lifecycle: Literal["first_time", "returning", "continuation", "rejoin"]
    placement_action: Literal["created", "reused"]
    membership_action: Literal["created", "reused"]


def learner_start_options(pool) -> LearnerStartOptions:
    business_units = fetch_all(
        pool,
        """SELECT business_unit_id AS id, business_unit_name AS name
           FROM business_units WHERE is_active
           ORDER BY lower(business_unit_name), business_unit_id""",
    )
    job_roles = fetch_all(
        pool,
        """SELECT job_role_id AS id, job_role_name AS name
           FROM job_roles WHERE is_active
           ORDER BY lower(job_role_name), job_role_id""",
    )
    entrance_levels = fetch_all(
        pool,
        """SELECT level_id AS id, level_name AS name
           FROM levels WHERE is_active
           ORDER BY sequence_order, level_id""",
    )
    course_runs = fetch_all(
        pool,
        """SELECT cr.course_run_id, cr.cohort_id, c.class_code,
                  course.course_code, course.course_name, cr.run_number,
                  cr.status AS run_status, cr.start_date, c.capacity,
                  count(DISTINCT cm.cohort_membership_id)
                    FILTER (WHERE cm.status='active') AS active_learners,
                  COALESCE(
                    min(su.sequence_in_run) FILTER (WHERE m.status='planned'),
                    max(su.sequence_in_run) FILTER (WHERE m.status='completed') + 1,
                    1
                  ) AS proposed_start_session_number
           FROM course_runs cr
           JOIN cohorts c ON c.cohort_id=cr.cohort_id
           JOIN courses course ON course.course_id=cr.course_id
           LEFT JOIN cohort_memberships cm ON cm.cohort_id=c.cohort_id
           LEFT JOIN session_units su ON su.course_run_id=cr.course_run_id
           LEFT JOIN meetings m ON m.meeting_id=su.meeting_id
           WHERE cr.status IN ('planned','active')
           GROUP BY cr.course_run_id, cr.cohort_id, c.class_code,
                    course.course_code, course.course_name, cr.run_number,
                    cr.status, cr.start_date, c.capacity
           ORDER BY lower(c.class_code), lower(course.course_name), cr.run_number, cr.course_run_id""",
    )
    option = lambda row: StartReferenceOption.model_validate(row)
    return LearnerStartOptions(
        business_units=[option(row) for row in business_units],
        job_roles=[option(row) for row in job_roles],
        entrance_levels=[option(row) for row in entrance_levels],
        course_runs=[StartCourseRunOption.model_validate(row) for row in course_runs],
    )


def start_learner(pool, actor_user_id: int, body: LearnerStartBody) -> LearnerStartResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).onboard_learner(
            emp_code=body.emp_code,
            full_name=body.full_name,
            employment_status=body.employment_status,
            business_unit_id=body.business_unit_id,
            job_role_id=body.job_role_id,
            entrance_level_id=body.entrance_level_id,
            course_run_id=body.course_run_id,
            joined_on=body.joined_on,
            start_session_number=body.confirmed_start_session_number,
            expected_start_session_number=body.confirmed_start_session_number,
            expected_employee_id=body.expected_employee_id,
            capacity_override_reason=body.capacity_override_reason,
        )
    return LearnerStartResult(
        run_enrollment_id=result.entity_id,
        employee_id=result.values["employee_id"],
        lifecycle=result.values["lifecycle"],
        placement_action=result.values["placement_action"],
        membership_action=result.values["membership_action"],
    )
