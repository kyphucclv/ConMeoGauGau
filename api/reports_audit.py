"""Allow-listed reports and restricted, sanitized audit-history reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from db import fetch_all, fetch_one
from reporting import REPORTS, metric_definitions, report_by_key, run_report_page
from services.base import CommandError


class MetricDefinition(BaseModel):
    metric_key: str
    metric_name: str
    definition: str
    numerator_definition: str | None
    denominator_definition: str | None


class RegisteredReport(BaseModel):
    key: str
    label: str
    columns: list[str]
    metric_definitions: list[MetricDefinition]


class ReportCatalog(BaseModel):
    reports: list[RegisteredReport]


class ReportPage(BaseModel):
    key: str
    label: str
    columns: list[str]
    metric_definitions: list[MetricDefinition]
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class AuditEvent(BaseModel):
    audit_event_id: int
    actor_username: str
    action: str
    entity_type: str
    entity_key: str | None
    details: dict[str, Any]
    created_at: datetime


class AuditEventPage(BaseModel):
    items: list[AuditEvent]
    page: int
    page_size: int
    total: int


def _definitions(pool, keys) -> list[MetricDefinition]:
    return [MetricDefinition.model_validate(row) for row in metric_definitions(pool, keys)]


def report_catalog(pool) -> ReportCatalog:
    return ReportCatalog(reports=[
        RegisteredReport(
            key=report.key,
            label=report.label,
            columns=list(report.columns),
            metric_definitions=_definitions(pool, report.metric_keys),
        )
        for report in REPORTS
    ])


def registered_report(pool, key: str, *, page: int, page_size: int) -> ReportPage:
    try:
        report = report_by_key(key)
    except KeyError as exc:
        raise CommandError("invalid_input", "report key is not registered") from exc
    result = run_report_page(pool, report, page=page, page_size=page_size)
    return ReportPage(
        key=report.key,
        label=report.label,
        columns=list(report.columns),
        metric_definitions=_definitions(pool, report.metric_keys),
        **result,
    )


_SENSITIVE_KEY_PARTS = (
    "password", "secret", "token", "hash", "connection", "database_url",
    "sql", "query", "dsn", "error", "exception", "trace", "credential",
)
_SENSITIVE_KEYS = (
    "session", "session_id", "session_cookie", "session_data",
)


def _safe_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_details(item)
            for key, item in value.items()
            if key.lower() not in _SENSITIVE_KEYS
            and not any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_safe_details(item) for item in value]
    return value


def audit_events(
    pool,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    actor_username: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> AuditEventPage:
    conditions: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("action", action),
        ("entity_type", entity_type),
        ("actor_username", actor_username),
    ):
        if value:
            conditions.append(f"{column}=%s")
            params.append(value)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    count = fetch_one(pool, f"SELECT count(*) AS total FROM audit_events{where}", params)
    rows = fetch_all(
        pool,
        f"""SELECT audit_event_id,actor_username,action,entity_type,entity_key,details,created_at
            FROM audit_events{where}
            ORDER BY created_at DESC,audit_event_id DESC
            LIMIT %s OFFSET %s""",
        [*params, page_size, (page - 1) * page_size],
    )
    return AuditEventPage(
        items=[AuditEvent.model_validate({**row, "details": _safe_details(row["details"])}) for row in rows],
        page=page,
        page_size=page_size,
        total=count["total"],
    )
