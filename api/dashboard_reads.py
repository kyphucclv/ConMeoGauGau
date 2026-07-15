"""Role-safe dashboard composition for the migration shell."""

from pydantic import BaseModel

from frontend_queries import application_snapshot, hr_home_snapshot


class ApplicationSummary(BaseModel):
    active_employees: int
    active_learners: int
    open_course_runs: int
    operational_issues: int
    high_issues: int
    open_quality_issues: int


class HrHomeSummary(BaseModel):
    active_people: int
    current_learners: int
    open_classes: int
    review_items: int
    urgent_items: int
    follow_ups: int


class DashboardResponse(BaseModel):
    summary: ApplicationSummary
    hr_home: HrHomeSummary | None


def dashboard_for(pool, role: str) -> DashboardResponse:
    return DashboardResponse(
        summary=ApplicationSummary.model_validate(application_snapshot(pool)),
        hr_home=(
            HrHomeSummary.model_validate(hr_home_snapshot(pool))
            if role in {"admin", "editor"}
            else None
        ),
    )
