"""HTTP seam for attendance session creation and complete-roster saves."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db import fetch_all, pooled_connection
from services import BusinessService


class AttendanceCourseRun(BaseModel):
    course_run_id: int
    cohort_id: int
    class_code: str
    course_code: str
    course_name: str
    run_number: int
    run_status: Literal["planned", "active"]
    next_sequence_in_run: int


class AttendanceCourseRuns(BaseModel):
    items: list[AttendanceCourseRun]


class AttendanceSessionUnit(BaseModel):
    session_unit_id: int
    meeting_id: int
    sequence_in_run: int
    starts_at: datetime
    duration_minutes: int
    meeting_status: Literal["planned", "completed", "cancelled"]


class AttendanceSessionUnits(BaseModel):
    items: list[AttendanceSessionUnit]


class AttendanceSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    duration_minutes: int = Field(gt=0, le=1440)
    confirmed_sequence_in_run: int = Field(gt=0)

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone")
        return value


class AttendanceSessionResult(BaseModel):
    session_unit_id: int
    meeting_id: int
    sequence_in_run: int


class AttendanceRosterRow(BaseModel):
    run_enrollment_id: int
    emp_code: str
    full_name: str
    start_session_number: int
    effective_status: Literal["Present", "Absent"] | None
    attendance_id: int | None = None


class AttendanceRoster(BaseModel):
    course_run_id: int
    session_unit_id: int
    sequence_in_run: int
    meeting_status: Literal["planned", "completed"]
    starts_at: datetime
    roster_token: str
    rows: list[AttendanceRosterRow]


class AttendanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_enrollment_id: int = Field(gt=0)
    effective_status: Literal["Present", "Absent"]


class AttendanceRosterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roster_token: str = Field(min_length=64, max_length=64)
    records: list[AttendanceRecord]


class AttendanceRosterResult(BaseModel):
    session_unit_id: int
    count: int
    created_count: int
    updated_count: int
    unchanged_count: int


def attendance_course_runs(pool) -> AttendanceCourseRuns:
    rows = fetch_all(
        pool,
        """SELECT cr.course_run_id,cr.cohort_id,c.class_code,course.course_code,
                  course.course_name,cr.run_number,cr.status AS run_status,
                  COALESCE(MAX(su.sequence_in_run) FILTER (WHERE m.status<>'cancelled'),0)+1 AS next_sequence_in_run
           FROM course_runs cr
           JOIN cohorts c ON c.cohort_id=cr.cohort_id
           JOIN courses course ON course.course_id=cr.course_id
           LEFT JOIN session_units su ON su.course_run_id=cr.course_run_id
           LEFT JOIN meetings m ON m.meeting_id=su.meeting_id
           WHERE cr.status IN ('planned','active')
           GROUP BY cr.course_run_id,cr.cohort_id,c.class_code,course.course_code,
                    course.course_name,cr.run_number,cr.status
           ORDER BY lower(c.class_code),lower(course.course_name),cr.run_number,cr.course_run_id""",
    )
    return AttendanceCourseRuns(items=[AttendanceCourseRun.model_validate(row) for row in rows])


def attendance_session_units(pool, course_run_id: int) -> AttendanceSessionUnits:
    rows = fetch_all(
        pool,
        """SELECT su.session_unit_id,su.meeting_id,su.sequence_in_run,m.starts_at,
                  m.duration_minutes,m.status AS meeting_status
           FROM session_units su
           JOIN meetings m ON m.meeting_id=su.meeting_id
           WHERE su.course_run_id=%s AND su.unit_type<>'makeup'
           ORDER BY su.sequence_in_run,m.starts_at,su.session_unit_id""",
        (course_run_id,),
    )
    return AttendanceSessionUnits(items=[AttendanceSessionUnit.model_validate(row) for row in rows])


def create_attendance_session(pool, actor_user_id: int, course_run_id: int, body: AttendanceSessionBody) -> AttendanceSessionResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).create_attendance_session(
            course_run_id,
            body.starts_at,
            body.duration_minutes,
            body.confirmed_sequence_in_run,
        )
    return AttendanceSessionResult(
        session_unit_id=result.entity_id,
        meeting_id=result.values["meeting_id"],
        sequence_in_run=result.values["sequence_in_run"],
    )


def attendance_roster(pool, actor_user_id: int, course_run_id: int, session_unit_id: int) -> AttendanceRoster:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).attendance_roster(course_run_id, session_unit_id)
    return AttendanceRoster(
        course_run_id=course_run_id,
        session_unit_id=session_unit_id,
        sequence_in_run=result.values["sequence_in_run"],
        meeting_status=result.values["meeting_status"],
        starts_at=result.values["starts_at"],
        roster_token=result.values["roster_token"],
        rows=[AttendanceRosterRow.model_validate(row) for row in result.values["rows"]],
    )


def save_attendance_roster(pool, actor_user_id: int, course_run_id: int, session_unit_id: int, body: AttendanceRosterBody) -> AttendanceRosterResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).save_attendance_roster(
            course_run_id,
            session_unit_id,
            [record.model_dump() for record in body.records],
            roster_token=body.roster_token,
        )
    return AttendanceRosterResult.model_validate(result.values)
