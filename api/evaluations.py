"""HTTP seam for final-result review, versioning, eligibility, and completion."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db import fetch_all, fetch_one, pooled_connection
from services import BusinessService


EnrollmentStatus = Literal["active", "completed", "transferred", "dropped", "cancelled"]


class EvaluationPendingItem(BaseModel):
    run_enrollment_id: int
    employee_id: int
    emp_code: str
    full_name: str
    class_code: str
    course_code: str
    course_name: str
    run_number: int
    enrollment_status: EnrollmentStatus
    attendance_ratio: float | None
    effective_exam_eligible: bool
    latest_version_number: int | None
    passed: bool | None
    completion_status: Literal["suggested", "confirmed", "rejected"] | None


class EvaluationPendingList(BaseModel):
    items: list[EvaluationPendingItem]


class EvaluationEnrollment(BaseModel):
    run_enrollment_id: int
    employee_id: int
    emp_code: str
    full_name: str
    course_run_id: int
    class_code: str
    course_code: str
    course_name: str
    run_number: int
    enrollment_status: EnrollmentStatus


class EvaluationEligibility(BaseModel):
    applicable_units: int
    present_units: int
    attendance_ratio: float
    calculated_exam_eligible: bool
    effective_exam_eligible: bool
    exam_eligibility_override: bool
    exam_eligibility_override_reason: str | None
    latest_evaluation_version: int | None


class EvaluationResultVersion(BaseModel):
    evaluation_version_id: int
    version_number: int
    final_level_id: int | None
    final_level_name: str | None
    exam_eligible: bool | None
    exam_eligibility_override: bool
    exam_eligibility_override_reason: str | None
    passed: bool | None
    next_course_id: int | None
    next_course_code: str | None
    teacher_notes: str | None
    correction_reason: str | None
    created_by_username: str | None
    created_at: datetime


class EvaluationCompletion(BaseModel):
    suggested: bool
    status: Literal["suggested", "confirmed", "rejected"]
    confirmed_by_username: str | None
    confirmed_at: datetime | None


class EvaluationLevelOption(BaseModel):
    level_id: int
    level_name: str


class EvaluationCourseOption(BaseModel):
    course_id: int
    course_code: str
    course_name: str


class EvaluationOptions(BaseModel):
    levels: list[EvaluationLevelOption]
    courses: list[EvaluationCourseOption]


class FinalResultDetail(BaseModel):
    enrollment: EvaluationEnrollment
    eligibility: EvaluationEligibility
    latest_result: EvaluationResultVersion | None
    history: list[EvaluationResultVersion]
    completion: EvaluationCompletion | None
    options: EvaluationOptions


class FinalResultBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_level_id: int = Field(gt=0)
    passed: bool
    next_course_id: int | None = Field(default=None, gt=0)
    teacher_notes: str | None = Field(default=None, max_length=5000)
    correction_reason: str | None = Field(default=None, max_length=1000)


class FinalResultResult(BaseModel):
    evaluation_version_id: int
    version_number: int
    effective_exam_eligible: bool
    exam_eligibility_override: bool


class EligibilityOverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    reason: str = Field(min_length=1, max_length=1000)


class EligibilityOverrideResult(BaseModel):
    evaluation_version_id: int
    version_number: int
    effective_exam_eligible: bool
    previous_effective_exam_eligible: bool


class CompletionActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["suggest", "confirm", "reject"]
    reason: str | None = Field(default=None, max_length=1000)


class CompletionActionResult(BaseModel):
    action: Literal["suggest", "confirm", "reject"]
    suggested: bool
    completion_status: Literal["suggested", "confirmed", "rejected"]
    enrollment_status: EnrollmentStatus


def pending_evaluations(pool) -> EvaluationPendingList:
    rows = fetch_all(
        pool,
        """SELECT re.run_enrollment_id,re.employee_id,e.emp_code,e.full_name,
                  cohort.class_code,course.course_code,course.course_name,cr.run_number,
                  re.status AS enrollment_status,attendance.attendance_ratio,
                  COALESCE(attendance.effective_exam_eligible,FALSE) AS effective_exam_eligible,
                  latest.version_number AS latest_version_number,latest.passed,
                  completion.status AS completion_status
           FROM run_enrollments re
           JOIN employees e ON e.employee_id=re.employee_id
           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
           JOIN cohorts cohort ON cohort.cohort_id=cr.cohort_id
           JOIN courses course ON course.course_id=cr.course_id
           LEFT JOIN v_run_enrollment_attendance attendance
             ON attendance.run_enrollment_id=re.run_enrollment_id
           LEFT JOIN v_latest_evaluation_versions latest
             ON latest.run_enrollment_id=re.run_enrollment_id
           LEFT JOIN course_completion_suggestions completion
             ON completion.run_enrollment_id=re.run_enrollment_id
           ORDER BY CASE WHEN latest.version_number IS NULL THEN 0 ELSE 1 END,
                    lower(cohort.class_code),lower(e.full_name),re.run_enrollment_id
           LIMIT 300""",
    )
    return EvaluationPendingList(
        items=[EvaluationPendingItem.model_validate(row) for row in rows]
    )


def final_result_detail(pool, actor_user_id: int, run_enrollment_id: int) -> FinalResultDetail | None:
    enrollment = fetch_one(
        pool,
        """SELECT re.run_enrollment_id,re.employee_id,e.emp_code,e.full_name,
                  re.course_run_id,cohort.class_code,course.course_code,
                  course.course_name,cr.run_number,re.status AS enrollment_status
           FROM run_enrollments re
           JOIN employees e ON e.employee_id=re.employee_id
           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
           JOIN cohorts cohort ON cohort.cohort_id=cr.cohort_id
           JOIN courses course ON course.course_id=cr.course_id
           WHERE re.run_enrollment_id=%s""",
        (run_enrollment_id,),
    )
    if enrollment is None:
        return None
    with pooled_connection(pool) as connection:
        eligibility = BusinessService(connection, actor_user_id).calculate_exam_eligibility(
            run_enrollment_id
        ).values
    history_rows = fetch_all(
        pool,
        """SELECT ev.evaluation_version_id,ev.version_number,ev.final_level_id,
                  level.level_name AS final_level_name,ev.exam_eligible,
                  ev.exam_eligibility_override,ev.exam_eligibility_override_reason,
                  ev.passed,ev.next_course_id,
                  next_course.course_code AS next_course_code,ev.teacher_notes,
                  ev.correction_reason,actor.username AS created_by_username,ev.created_at
           FROM evaluations evaluation
           JOIN evaluation_versions ev ON ev.evaluation_id=evaluation.evaluation_id
           LEFT JOIN levels level ON level.level_id=ev.final_level_id
           LEFT JOIN courses next_course ON next_course.course_id=ev.next_course_id
           LEFT JOIN app_users actor ON actor.user_id=ev.created_by_user_id
           WHERE evaluation.run_enrollment_id=%s
           ORDER BY ev.version_number DESC,ev.evaluation_version_id DESC""",
        (run_enrollment_id,),
    )
    history = [EvaluationResultVersion.model_validate(row) for row in history_rows]
    completion_row = fetch_one(
        pool,
        """SELECT completion.suggested,completion.status,
                  actor.username AS confirmed_by_username,completion.confirmed_at
           FROM course_completion_suggestions completion
           LEFT JOIN app_users actor ON actor.user_id=completion.confirmed_by_user_id
           WHERE completion.run_enrollment_id=%s""",
        (run_enrollment_id,),
    )
    levels = fetch_all(
        pool,
        "SELECT level_id,level_name FROM levels WHERE is_active ORDER BY sequence_order,level_id",
    )
    courses = fetch_all(
        pool,
        "SELECT course_id,course_code,course_name FROM courses WHERE is_active ORDER BY lower(course_name),course_id",
    )
    return FinalResultDetail(
        enrollment=EvaluationEnrollment.model_validate(enrollment),
        eligibility=EvaluationEligibility.model_validate(eligibility),
        latest_result=history[0] if history else None,
        history=history,
        completion=EvaluationCompletion.model_validate(completion_row) if completion_row else None,
        options=EvaluationOptions(
            levels=[EvaluationLevelOption.model_validate(row) for row in levels],
            courses=[EvaluationCourseOption.model_validate(row) for row in courses],
        ),
    )


def record_final_result(
    pool, actor_user_id: int, run_enrollment_id: int, body: FinalResultBody
) -> FinalResultResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).record_evaluation(
            run_enrollment_id,
            final_level_id=body.final_level_id,
            passed=body.passed,
            next_course_id=body.next_course_id,
            teacher_notes=body.teacher_notes,
            correction_reason=body.correction_reason,
        )
    return FinalResultResult(
        evaluation_version_id=result.entity_id,
        version_number=result.values["version_number"],
        effective_exam_eligible=result.values["exam_eligible"],
        exam_eligibility_override=result.values["exam_eligibility_override"],
    )


def override_eligibility(
    pool, actor_user_id: int, run_enrollment_id: int, body: EligibilityOverrideBody
) -> EligibilityOverrideResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).override_exam_eligibility(
            run_enrollment_id, body.eligible, body.reason
        )
    return EligibilityOverrideResult(
        evaluation_version_id=result.entity_id,
        version_number=result.values["version_number"],
        effective_exam_eligible=result.values["exam_eligible"],
        previous_effective_exam_eligible=result.values["previous"][
            "effective_exam_eligible"
        ],
    )


def apply_completion_action(
    pool, actor_user_id: int, run_enrollment_id: int, body: CompletionActionBody
) -> CompletionActionResult:
    with pooled_connection(pool) as connection:
        commands = BusinessService(connection, actor_user_id)
        if body.action == "suggest":
            commands.suggest_completion(run_enrollment_id)
        else:
            commands.confirm_completion(
                run_enrollment_id,
                body.action == "confirm",
                body.reason,
            )
    state = fetch_one(
        pool,
        """SELECT completion.suggested,completion.status AS completion_status,
                  enrollment.status AS enrollment_status
           FROM course_completion_suggestions completion
           JOIN run_enrollments enrollment
             ON enrollment.run_enrollment_id=completion.run_enrollment_id
           WHERE completion.run_enrollment_id=%s""",
        (run_enrollment_id,),
    )
    return CompletionActionResult(action=body.action, **state)
