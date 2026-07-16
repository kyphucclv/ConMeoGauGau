"""HTTP read and command seam for operational and logged follow-ups."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from db import fetch_all, fetch_one, pooled_connection
from services import BusinessService


class OperationalIssue(BaseModel):
    severity: Literal["high", "warning"]
    issue_code: str
    entity_type: str
    entity_key: str
    title: str
    workflow: str
    details: dict[str, Any]


class OperationalIssuePage(BaseModel):
    items: list[OperationalIssue]
    page: int
    page_size: int
    total: int


class QualityIssue(BaseModel):
    issue_id: int
    issue_code: str
    entity_type: str | None
    entity_key: str | None
    source_sheet: str | None
    source_row_number: int | None
    details: dict[str, Any]
    status: Literal["open", "resolved", "ignored"]
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_username: str | None
    resolution_note: str | None


class QualityIssuePage(BaseModel):
    items: list[QualityIssue]
    page: int
    page_size: int
    total: int


class QualityIssueResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "ignored"]
    note: str = Field(min_length=1, max_length=2000)


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class ConfirmedReasonBody(ReasonBody):
    confirmed: Literal[True]


class LegacyAttendanceExceptionBody(ConfirmedReasonBody):
    session_unit_id: int = Field(gt=0)


class ScheduleConflictResolutionBody(ConfirmedReasonBody):
    meeting_id: int = Field(gt=0)


class RemediationResult(BaseModel):
    entity_type: str
    entity_id: int | None
    values: dict[str, Any]


def operational_issues(
    pool,
    *,
    severity: Literal["all", "high", "warning"] = "all",
    workflow: str | None = None,
    issue_code: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> OperationalIssuePage:
    conditions: list[str] = []
    params: list[Any] = []
    if severity != "all":
        conditions.append("severity=%s")
        params.append(severity)
    if workflow:
        conditions.append("workflow=%s")
        params.append(workflow)
    if issue_code:
        conditions.append("issue_code=%s")
        params.append(issue_code)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    count = fetch_one(pool, f"SELECT count(*) AS total FROM v_operational_data_issues{where}", params)
    rows = fetch_all(
        pool,
        f"""SELECT severity,issue_code,entity_type,entity_key,title,workflow,details
            FROM v_operational_data_issues{where}
            ORDER BY CASE severity WHEN 'high' THEN 0 ELSE 1 END,
                     issue_code,entity_type,entity_key
            LIMIT %s OFFSET %s""",
        [*params, page_size, (page - 1) * page_size],
    )
    return OperationalIssuePage(
        items=[OperationalIssue.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=count["total"],
    )


def quality_issues(
    pool,
    *,
    status: Literal["all", "open", "resolved", "ignored"] = "open",
    issue_code: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> QualityIssuePage:
    conditions: list[str] = []
    params: list[Any] = []
    if status != "all":
        conditions.append("dqi.status=%s")
        params.append(status)
    if issue_code:
        conditions.append("dqi.issue_code=%s")
        params.append(issue_code)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    count = fetch_one(pool, f"SELECT count(*) AS total FROM data_quality_issues dqi{where}", params)
    rows = fetch_all(
        pool,
        f"""SELECT dqi.issue_id,dqi.issue_code,dqi.entity_type,dqi.entity_key,
                   dqi.source_sheet,dqi.source_row_number,dqi.details,dqi.status,
                   dqi.created_at,dqi.resolved_at,actor.username AS resolved_by_username,
                   dqi.resolution_note
            FROM data_quality_issues dqi
            LEFT JOIN app_users actor ON actor.user_id=dqi.resolved_by_user_id
            {where}
            ORDER BY dqi.created_at DESC,dqi.issue_id DESC
            LIMIT %s OFFSET %s""",
        [*params, page_size, (page - 1) * page_size],
    )
    return QualityIssuePage(
        items=[QualityIssue.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=count["total"],
    )


def _result(result) -> RemediationResult:
    return RemediationResult(
        entity_type=result.entity_type,
        entity_id=result.entity_id,
        values=result.values,
    )


def resolve_quality_issue(pool, actor_user_id: int, issue_id: int, body: QualityIssueResolutionBody) -> RemediationResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).resolve_quality_issue(
            issue_id, body.status, body.note
        )
    return _result(result)


def backfill_unknown_organizations(pool, actor_user_id: int, body: ConfirmedReasonBody) -> RemediationResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).backfill_unknown_org_profiles(body.reason)
    return _result(result)


def approve_legacy_attendance_exception(pool, actor_user_id: int, body: LegacyAttendanceExceptionBody) -> RemediationResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).approve_legacy_attendance_exception(
            body.session_unit_id, body.reason
        )
    return _result(result)


def backfill_unknown_placements(pool, actor_user_id: int, body: ConfirmedReasonBody) -> RemediationResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).backfill_unknown_business_placements(body.reason)
    return _result(result)


def resolve_schedule_conflict(pool, actor_user_id: int, body: ScheduleConflictResolutionBody) -> RemediationResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).cancel_meeting(body.meeting_id, body.reason)
    return _result(result)
