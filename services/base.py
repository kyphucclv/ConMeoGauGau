"""Transactional Phase 4 business commands.

This module deliberately has no UI-framework dependency.  A command owns one
transaction, validates business state before writing, and records its audit
event before commit.  The UI can translate ``CommandResult`` and
``CommandError`` into user-facing messages without inspecting SQL exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

import psycopg2
import psycopg2.extras


@dataclass(frozen=True)
class CommandResult:
    entity_type: str
    entity_id: int | None
    values: dict[str, Any]


class CommandError(Exception):
    """Stable, safe-to-display command failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _required(value: Any, name: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise CommandError("invalid_input", f"{name} is required")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _normalize_label(value: str | None) -> str | None:
    """Collapse accidental PIC whitespace while retaining the chosen casing."""
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


class ServiceCore:
    """Application service over an existing psycopg2 connection."""

    def __init__(self, connection, actor_user_id: int):
        self.connection = connection
        self.actor_user_id = _required(actor_user_id, "actor_user_id")

    def _actor(self, cur, roles: set[str]) -> tuple[int, str]:
        cur.execute("SELECT user_id, role FROM app_users WHERE user_id=%s AND is_active", (self.actor_user_id,))
        row = cur.fetchone()
        if not row:
            raise CommandError("unauthorized", "active application user is required")
        if row[1] not in roles:
            raise CommandError("forbidden", "user is not authorized for this operation")
        return row

    def _audit(self, cur, action: str, entity_type: str, entity_id: int | None, details: dict[str, Any] | None = None):
        cur.execute("""INSERT INTO audit_events(actor_user_id, actor_username, action, entity_type, entity_key, details)
                     SELECT user_id, username, %s, %s, %s, %s FROM app_users WHERE user_id=%s""",
                    (action, entity_type, str(entity_id) if entity_id is not None else None,
                     psycopg2.extras.Json(_json_safe(details or {})), self.actor_user_id))

    @staticmethod
    def _advisory_lock(cur, key: str) -> None:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))

    @staticmethod
    def _next_evaluation_version(cur, evaluation_id: int) -> int:
        ServiceCore._advisory_lock(cur, f"evaluation_version:{evaluation_id}")
        cur.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM evaluation_versions WHERE evaluation_id=%s",
            (evaluation_id,),
        )
        return cur.fetchone()[0]

    def _run(self, roles: set[str], fn):
        with self.connection:
            with self.connection.cursor() as cur:
                self._actor(cur, roles)
                try:
                    return fn(cur)
                except psycopg2.errors.UniqueViolation as exc:
                    if exc.diag.constraint_name == "uq_run_enrollments_one_active_per_employee":
                        raise CommandError("active_enrollment_conflict", "employee already has an active course enrollment") from exc
                    raise CommandError("duplicate", "the requested business record already exists") from exc
                except psycopg2.errors.ForeignKeyViolation as exc:
                    raise CommandError("not_found", "a referenced business record does not exist") from exc
                except psycopg2.errors.CheckViolation as exc:
                    raise CommandError("invalid_state", "the requested state is not valid") from exc
                except psycopg2.errors.RaiseException as exc:
                    raise CommandError("invalid_state", "the requested state is not valid") from exc

    @staticmethod
    def _propose_course_run_start_session_in_tx(cur, target_course_run_id: int) -> int:
        cur.execute("""SELECT COALESCE(min(su.sequence_in_run) FILTER (WHERE m.status='planned'), max(su.sequence_in_run) FILTER (WHERE m.status='completed') + 1, 1)
                       FROM session_units su JOIN meetings m ON m.meeting_id=su.meeting_id WHERE su.course_run_id=%s""", (target_course_run_id,))
        return cur.fetchone()[0]

    @staticmethod
    def _propose_transfer_start_session_in_tx(cur, target_course_run_id: int) -> int:
        return ServiceCore._propose_course_run_start_session_in_tx(cur, target_course_run_id)
