"""Safe structured access events for the production HTTP boundary."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any


ACCESS_LOGGER = logging.getLogger("english_class.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def request_id_or_new(value: str | None) -> str:
    """Accept a bounded opaque correlation ID or replace it with a safe value."""
    return value if value and _REQUEST_ID.fullmatch(value) else uuid.uuid4().hex


def access_event(request, *, status: int, duration_ms: float) -> dict[str, Any]:
    """Build an allow-listed event without query strings, cookies, or bodies."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or request.url.path
    event: dict[str, Any] = {
        "event": "http_request",
        "request_id": request.state.request_id,
        "method": request.method,
        "route": route_path,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "authenticated": bool(getattr(request.state, "actor_user_id", None)),
    }
    actor_user_id = getattr(request.state, "actor_user_id", None)
    if actor_user_id is not None:
        event["actor_user_id"] = actor_user_id
    return event


def log_access(request, *, status: int, duration_ms: float) -> None:
    ACCESS_LOGGER.info(
        json.dumps(access_event(request, status=status, duration_ms=duration_ms), separators=(",", ":"))
    )
