"""Transactional business commands (public API of the services package).


``BusinessService`` keeps its original surface: one command owns one
transaction, validates business state, and records its audit event
before commit. Implementation is split by workflow concern.
"""

from __future__ import annotations

from services.base import CommandError, CommandResult, ServiceCore, _json_safe, _normalize_label, _required
from services.employee_onboarding import EmployeeOnboardingCommands
from services.membership_transfer import MembershipTransferCommands
from services.class_schedule import ClassScheduleCommands
from services.meetings_units import MeetingsUnitsCommands
from services.attendance_makeup import AttendanceMakeupCommands
from services.evaluation_completion import EvaluationCompletionCommands
from services.admin_remediation import AdminRemediationCommands


class BusinessService(
    EmployeeOnboardingCommands,
    MembershipTransferCommands,
    ClassScheduleCommands,
    MeetingsUnitsCommands,
    AttendanceMakeupCommands,
    EvaluationCompletionCommands,
    AdminRemediationCommands,
    ServiceCore,
):
    """Application service over an existing psycopg2 connection."""


__all__ = ["BusinessService", "CommandError", "CommandResult"]
