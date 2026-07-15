"""Authenticated monthly-review read, conclusion, and export seam."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db import pooled_connection
from reporting import monthly_review_data, monthly_review_summary, monthly_review_xlsx, proposed_monthly_actions
from services import BusinessService


class MonthlySummary(BaseModel):
    active: int
    repeated: int
    planned: int
    delivered: int
    variance: int
    attendance_ratio: float | None
    low_count: int
    improved_count: int
    tested_count: int
    delivery_rate: float | None
    low_rate: float | None
    improved_rate: float | None
    new_course_count: int


class MonthlyActionSummary(BaseModel):
    highlights: str
    risks: str
    next_month_priorities: str


class SavedMonthlyActionSummary(MonthlyActionSummary):
    version_number: int
    created_at: datetime
    created_by_username: str


class MonthlyReviewResponse(BaseModel):
    review_month: date
    summary: MonthlySummary
    program: list[dict[str, Any]]
    participation: list[dict[str, Any]]
    course_participation: list[dict[str, Any]]
    class_participation: list[dict[str, Any]]
    progress: list[dict[str, Any]]
    level_distribution: list[dict[str, Any]]
    new_courses: list[dict[str, Any]]
    action_summary: SavedMonthlyActionSummary | None
    proposed_action_summary: MonthlyActionSummary


class MonthlyActionSummaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    highlights: str = Field(max_length=5000)
    risks: str = Field(max_length=5000)
    next_month_priorities: str = Field(max_length=5000)


class MonthlyActionSummaryResult(BaseModel):
    review_month: date
    version_number: int


def parse_review_month(value: str) -> date:
    return date.fromisoformat(f"{value}-01")


def monthly_review(pool, review_month: date) -> MonthlyReviewResponse:
    data = monthly_review_data(pool, review_month)
    summary = monthly_review_summary(data)
    return MonthlyReviewResponse(
        review_month=review_month,
        summary=summary,
        program=data["program"],
        participation=data["participation"],
        course_participation=data["course_participation"],
        class_participation=data["class_participation"],
        progress=data["progress"],
        level_distribution=data["level_distribution"],
        new_courses=data["new_courses"],
        action_summary=data["action_summary"],
        proposed_action_summary=proposed_monthly_actions(summary),
    )


def save_action_summary(
    pool, actor_user_id: int, body: MonthlyActionSummaryBody
) -> MonthlyActionSummaryResult:
    review_month = parse_review_month(body.month)
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).save_monthly_action_summary(
            review_month,
            highlights=body.highlights,
            risks=body.risks,
            next_month_priorities=body.next_month_priorities,
        )
    return MonthlyActionSummaryResult(
        review_month=review_month,
        version_number=result.values["version_number"],
    )


def export_monthly_review(pool, review_month: date) -> bytes:
    data = monthly_review_data(pool, review_month)
    action_summary = data["action_summary"]
    if action_summary is None:
        action_summary = proposed_monthly_actions(monthly_review_summary(data))
    return monthly_review_xlsx(review_month, data, action_summary)
