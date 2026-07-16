"""HTTP read and command seam for class, course-run, PIC, and schedule administration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db import fetch_all, fetch_one, pooled_connection
from services import BusinessService


class AdminOption(BaseModel):
    id: int
    label: str


class AdministrationOptions(BaseModel):
    proposed_class_code: str
    courses: list[AdminOption]
    employees: list[AdminOption]
    cohorts: list[AdminOption]
    course_runs: list[AdminOption]
    pic_labels: list[str]


class ClassRow(BaseModel):
    cohort_id: int
    class_code: str
    display_name: str
    status: str
    capacity: int | None
    current_pic: str | None
    course_run_count: int


class ClassPage(BaseModel):
    items: list[ClassRow]
    page: int
    page_size: int
    total: int


class CourseRunRow(BaseModel):
    course_run_id: int
    cohort_id: int
    class_code: str
    course_id: int
    course_code: str
    course_name: str
    run_number: int
    status: str
    start_date: date | None
    end_date: date | None
    expected_units: int
    next_sequence_in_run: int


class CourseRunPage(BaseModel):
    items: list[CourseRunRow]
    page: int
    page_size: int
    total: int


class ScheduleRow(BaseModel):
    meeting_id: int
    course_run_id: int
    class_code: str
    course_code: str
    course_name: str
    run_number: int
    starts_at: datetime
    duration_minutes: int
    status: str
    cancellation_reason: str | None
    units: list[dict[str, Any]]


class SchedulePage(BaseModel):
    items: list[ScheduleRow]
    page: int
    page_size: int
    total: int


class ClassWithRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_code: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=300)
    course_id: int = Field(gt=0)
    start_date: date
    capacity: int = Field(gt=0)
    status: Literal["planned", "active"] = "active"
    pic_employee_id: int | None = Field(default=None, gt=0)
    pic_label: str | None = Field(default=None, max_length=300)


class PicAssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pic_employee_id: int | None = Field(default=None, gt=0)
    pic_label: str | None = Field(default=None, max_length=300)
    start_date: date


class CourseRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: int = Field(gt=0)
    start_date: date


class CourseRunStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["planned", "active", "completed", "cancelled", "archived"]
    end_date: date | None = None


class MeetingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    duration_minutes: int = Field(gt=0, le=1440)
    first_sequence_in_run: int = Field(gt=0)
    unit_count: Literal[1, 2]
    unit_type: Literal["normal", "final_test", "makeup", "admin"]
    status: Literal["planned", "completed"] = "planned"

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return value


class MeetingCorrectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_run_id: int = Field(gt=0)
    starts_at: datetime
    duration_minutes: int = Field(gt=0, le=1440)
    status: Literal["planned", "completed"]
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return value


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class SessionUnitsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_run_id: int = Field(gt=0)
    first_sequence_in_run: int = Field(gt=0)
    unit_count: Literal[1, 2]
    unit_type: Literal["normal", "final_test", "makeup", "admin"]


class AdministrationCommandResult(BaseModel):
    entity_type: str
    entity_id: int | None
    values: dict[str, Any]


def _result(result) -> AdministrationCommandResult:
    return AdministrationCommandResult(
        entity_type=result.entity_type,
        entity_id=result.entity_id,
        values=result.values,
    )


def administration_options(pool, actor_user_id: int) -> AdministrationOptions:
    with pooled_connection(pool) as connection:
        service = BusinessService(connection, actor_user_id)
        proposed = service.propose_next_class_code().values["class_code"]
        labels = service.pic_label_suggestions().values["labels"]
    courses = fetch_all(pool, """SELECT course_id AS id,course_code||' · '||course_name AS label
                                  FROM courses WHERE is_active ORDER BY lower(course_name),course_id LIMIT 500""")
    employees = fetch_all(pool, """SELECT employee_id AS id,emp_code||' · '||full_name AS label
                                    FROM employees WHERE employment_status='active'
                                    ORDER BY lower(full_name),employee_id LIMIT 500""")
    cohorts = fetch_all(pool, """SELECT cohort_id AS id,class_code||' · '||display_name AS label
                                  FROM cohorts WHERE status IN ('planned','active')
                                  ORDER BY lower(class_code),cohort_id LIMIT 500""")
    runs = fetch_all(pool, """SELECT cr.course_run_id AS id,c.class_code||' · '||co.course_code||
                                      ' · run '||cr.run_number AS label
                               FROM course_runs cr JOIN cohorts c ON c.cohort_id=cr.cohort_id
                               JOIN courses co ON co.course_id=cr.course_id
                               WHERE cr.status IN ('planned','active')
                               ORDER BY lower(c.class_code),lower(co.course_code),cr.run_number LIMIT 500""")
    return AdministrationOptions(
        proposed_class_code=proposed,
        courses=[AdminOption.model_validate(row) for row in courses],
        employees=[AdminOption.model_validate(row) for row in employees],
        cohorts=[AdminOption.model_validate(row) for row in cohorts],
        course_runs=[AdminOption.model_validate(row) for row in runs],
        pic_labels=labels,
    )


def classes(pool, *, q: str = "", status: str = "all", page: int = 1, page_size: int = 50) -> ClassPage:
    conditions = ["(%s='' OR c.class_code ILIKE %s OR c.display_name ILIKE %s)"]
    term = q.strip()
    params: list[Any] = [term, f"%{term}%", f"%{term}%"]
    if status != "all":
        conditions.append("c.status=%s")
        params.append(status)
    where = " WHERE " + " AND ".join(conditions)
    count = fetch_one(pool, f"SELECT count(*) AS total FROM cohorts c{where}", params)
    rows = fetch_all(pool, f"""SELECT c.cohort_id,c.class_code,c.display_name,c.status,c.capacity,
                         COALESCE(pic.full_name,cpa.pic_label) AS current_pic,
                         count(DISTINCT cr.course_run_id)::int AS course_run_count
                  FROM cohorts c
                  LEFT JOIN cohort_pic_assignments cpa ON cpa.cohort_id=c.cohort_id AND cpa.end_date IS NULL
                  LEFT JOIN employees pic ON pic.employee_id=cpa.pic_employee_id
                  LEFT JOIN course_runs cr ON cr.cohort_id=c.cohort_id
                  {where}
                  GROUP BY c.cohort_id,pic.full_name,cpa.pic_label
                  ORDER BY lower(c.class_code),c.cohort_id LIMIT %s OFFSET %s""",
                 [*params,page_size,(page-1)*page_size])
    return ClassPage(items=[ClassRow.model_validate(row) for row in rows],page=page,page_size=page_size,total=count["total"])


def course_runs(pool, *, status: str = "all", page: int = 1, page_size: int = 50) -> CourseRunPage:
    where = " WHERE cr.status=%s" if status != "all" else ""
    params: list[Any] = [status] if status != "all" else []
    count = fetch_one(pool, f"SELECT count(*) AS total FROM course_runs cr{where}",params)
    rows = fetch_all(pool,f"""SELECT cr.course_run_id,cr.cohort_id,c.class_code,cr.course_id,
                         co.course_code,co.course_name,cr.run_number,cr.status,cr.start_date,
                         cr.end_date,cr.expected_units_snapshot AS expected_units,
                         COALESCE(max(su.sequence_in_run) FILTER (WHERE m.status<>'cancelled'),0)::int+1 AS next_sequence_in_run
                  FROM course_runs cr JOIN cohorts c ON c.cohort_id=cr.cohort_id
                  JOIN courses co ON co.course_id=cr.course_id
                  LEFT JOIN session_units su ON su.course_run_id=cr.course_run_id
                  LEFT JOIN meetings m ON m.meeting_id=su.meeting_id
                  {where}
                  GROUP BY cr.course_run_id,c.class_code,co.course_code,co.course_name
                  ORDER BY lower(c.class_code),lower(co.course_name),cr.run_number,cr.course_run_id
                  LIMIT %s OFFSET %s""",[*params,page_size,(page-1)*page_size])
    return CourseRunPage(items=[CourseRunRow.model_validate(row) for row in rows],page=page,page_size=page_size,total=count["total"])


def schedule(pool, *, course_run_id: int | None = None, status: str = "all", page: int = 1, page_size: int = 50) -> SchedulePage:
    conditions=[];params:list[Any]=[]
    if course_run_id is not None: conditions.append("m.course_run_id=%s");params.append(course_run_id)
    if status != "all": conditions.append("m.status=%s");params.append(status)
    where=" WHERE "+" AND ".join(conditions) if conditions else ""
    count=fetch_one(pool,f"SELECT count(*) AS total FROM meetings m{where}",params)
    rows=fetch_all(pool,f"""SELECT m.meeting_id,m.course_run_id,c.class_code,co.course_code,
                       co.course_name,cr.run_number,m.starts_at,m.duration_minutes,m.status,
                       m.cancellation_reason,
                       COALESCE(jsonb_agg(jsonb_build_object(
                         'session_unit_id',su.session_unit_id,'sequence_in_run',su.sequence_in_run,
                         'unit_number_in_meeting',su.unit_number_in_meeting,'unit_type',su.unit_type)
                         ORDER BY su.unit_number_in_meeting) FILTER (WHERE su.session_unit_id IS NOT NULL),'[]') AS units
                FROM meetings m JOIN course_runs cr ON cr.course_run_id=m.course_run_id
                JOIN cohorts c ON c.cohort_id=cr.cohort_id JOIN courses co ON co.course_id=cr.course_id
                LEFT JOIN session_units su ON su.meeting_id=m.meeting_id
                {where}
                GROUP BY m.meeting_id,c.class_code,co.course_code,co.course_name,cr.run_number
                ORDER BY m.starts_at DESC,m.meeting_id DESC LIMIT %s OFFSET %s""",[*params,page_size,(page-1)*page_size])
    return SchedulePage(items=[ScheduleRow.model_validate(row) for row in rows],page=page,page_size=page_size,total=count["total"])


def create_class_with_run(pool,actor_user_id:int,body:ClassWithRunBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).create_class_course_run(
            class_code=body.class_code,display_name=body.display_name,course_id=body.course_id,
            start_date=body.start_date,capacity=body.capacity,status=body.status,
            pic_employee_id=body.pic_employee_id,pic_label=body.pic_label)
    return _result(result)


def assign_pic(pool,actor_user_id:int,cohort_id:int,body:PicAssignmentBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).assign_pic(
            cohort_id,body.pic_employee_id,body.start_date,pic_label=body.pic_label)
    return _result(result)


def create_course_run(pool,actor_user_id:int,cohort_id:int,body:CourseRunBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).create_course_run(
            cohort_id,body.course_id,start_date=body.start_date)
    return _result(result)


def change_course_run_status(pool,actor_user_id:int,course_run_id:int,body:CourseRunStatusBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).change_course_run_status(
            course_run_id,body.status,end_date=body.end_date)
    return _result(result)


def create_meeting(pool,actor_user_id:int,course_run_id:int,body:MeetingBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).create_meeting_with_units(
            course_run_id,body.starts_at,body.duration_minutes,body.first_sequence_in_run,
            unit_count=body.unit_count,unit_type=body.unit_type,status=body.status)
    return _result(result)


def correct_meeting(pool,actor_user_id:int,meeting_id:int,body:MeetingCorrectionBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).save_meeting(
            body.course_run_id,body.starts_at,body.duration_minutes,meeting_id=meeting_id,
            status=body.status,change_reason=body.reason)
    return _result(result)


def cancel_meeting(pool,actor_user_id:int,meeting_id:int,body:ReasonBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).cancel_meeting(meeting_id,body.reason)
    return _result(result)


def add_session_units(pool,actor_user_id:int,meeting_id:int,body:SessionUnitsBody):
    with pooled_connection(pool) as connection:
        result=BusinessService(connection,actor_user_id).add_session_units(
            body.course_run_id,meeting_id,body.first_sequence_in_run,
            unit_count=body.unit_count,unit_type=body.unit_type)
    return _result(result)
