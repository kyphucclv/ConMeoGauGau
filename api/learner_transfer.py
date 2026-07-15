"""HTTP seam for active run-enrollment transfers."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db import fetch_all, fetch_one, pooled_connection
from services import BusinessService
from services.base import CommandError


class TransferSource(BaseModel):
    run_enrollment_id: int
    employee_id: int
    emp_code: str
    full_name: str
    course_run_id: int
    cohort_id: int
    class_code: str
    course_code: str
    course_name: str
    start_session_number: int


class TransferDestination(BaseModel):
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


class LearnerTransferOptions(BaseModel):
    source: TransferSource
    destinations: list[TransferDestination]


class LearnerTransferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_course_run_id: int = Field(gt=0)
    transfer_date: date
    confirmed_start_session_number: int = Field(gt=0)
    capacity_override_reason: str | None = Field(default=None, max_length=1000)


class LearnerTransferResult(BaseModel):
    run_enrollment_id: int
    from_enrollment_id: int
    membership_id: int
    start_session_number: int
    capacity_override_applied: bool


def learner_transfer_options(pool, run_enrollment_id: int) -> LearnerTransferOptions:
    source = fetch_one(
        pool,
        """SELECT re.run_enrollment_id,re.employee_id,e.emp_code,e.full_name,
                  re.course_run_id,cr.cohort_id,c.class_code,
                  course.course_code,course.course_name,re.start_session_number
           FROM run_enrollments re
           JOIN employees e ON e.employee_id=re.employee_id
           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
           JOIN cohorts c ON c.cohort_id=cr.cohort_id
           JOIN courses course ON course.course_id=cr.course_id
           JOIN cohort_memberships cm ON cm.cohort_membership_id=re.cohort_membership_id
           WHERE re.run_enrollment_id=%s AND re.status='active'
             AND cm.status='active' AND cm.cohort_id=cr.cohort_id""",
        (run_enrollment_id,),
    )
    if not source:
        raise CommandError("invalid_state", "enrollment is not active or does not exist")
    destinations = fetch_all(
        pool,
        """SELECT cr.course_run_id,cr.cohort_id,c.class_code,
                  course.course_code,course.course_name,cr.run_number,
                  cr.status AS run_status,cr.start_date,c.capacity,
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
           WHERE cr.status IN ('planned','active') AND cr.cohort_id<>%s
           GROUP BY cr.course_run_id,cr.cohort_id,c.class_code,
                    course.course_code,course.course_name,cr.run_number,
                    cr.status,cr.start_date,c.capacity
           ORDER BY lower(c.class_code),lower(course.course_name),cr.run_number,cr.course_run_id""",
        (source["cohort_id"],),
    )
    return LearnerTransferOptions(
        source=TransferSource.model_validate(source),
        destinations=[TransferDestination.model_validate(row) for row in destinations],
    )


def transfer_learner(pool, actor_user_id: int, run_enrollment_id: int, body: LearnerTransferBody) -> LearnerTransferResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).transfer_learner(
            run_enrollment_id,
            body.target_course_run_id,
            body.transfer_date,
            confirmed_start_session_number=body.confirmed_start_session_number,
            capacity_override_reason=body.capacity_override_reason,
        )
    return LearnerTransferResult(
        run_enrollment_id=result.entity_id,
        from_enrollment_id=result.values["from_enrollment_id"],
        membership_id=result.values["membership_id"],
        start_session_number=result.values["start_session_number"],
        capacity_override_applied=result.values["capacity_override_id"] is not None,
    )
