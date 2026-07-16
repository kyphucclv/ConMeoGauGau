"""Role-safe dashboard composition for the migration shell."""

from pydantic import BaseModel

from frontend_queries import application_snapshot


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
    snapshot = application_snapshot(pool)
    return DashboardResponse(
        summary=ApplicationSummary.model_validate(snapshot),
        hr_home=(
            HrHomeSummary(
                active_people=snapshot["active_employees"],
                current_learners=snapshot["active_learners"],
                open_classes=snapshot["open_course_runs"],
                review_items=snapshot["operational_issues"],
                urgent_items=snapshot["high_issues"],
                follow_ups=snapshot["open_quality_issues"],
            )
            if role in {"admin", "editor"}
            else None
        ),
    )
