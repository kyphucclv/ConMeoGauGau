"""HTTP command seam for safe employee profile updates."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db import fetch_all, pooled_connection
from services import BusinessService


class ProfileUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=300)
    employment_status: Literal["active", "inactive", "unknown"]
    business_unit_id: int = Field(gt=0)
    job_role_id: int = Field(gt=0)
    organization_valid_from: date
    expected_org_valid_from: date | None


class ProfileUpdateResult(BaseModel):
    employee_id: int
    org_history_action: Literal["unchanged", "changed", "created"]


class ReferenceOption(BaseModel):
    id: int
    name: str


class ProfileOptions(BaseModel):
    business_units: list[ReferenceOption]
    job_roles: list[ReferenceOption]


def profile_options(pool) -> ProfileOptions:
    business_units = fetch_all(
        pool,
        """SELECT business_unit_id AS id, business_unit_name AS name
           FROM business_units WHERE is_active
           ORDER BY lower(business_unit_name), business_unit_id""",
    )
    job_roles = fetch_all(
        pool,
        """SELECT job_role_id AS id, job_role_name AS name
           FROM job_roles WHERE is_active
           ORDER BY lower(job_role_name), job_role_id""",
    )
    return ProfileOptions(
        business_units=[ReferenceOption.model_validate(row) for row in business_units],
        job_roles=[ReferenceOption.model_validate(row) for row in job_roles],
    )


def update_profile(pool, actor_user_id: int, employee_id: int, body: ProfileUpdateBody) -> ProfileUpdateResult:
    with pooled_connection(pool) as connection:
        result = BusinessService(connection, actor_user_id).create_or_update_employee(
            body.emp_code,
            body.full_name,
            employment_status=body.employment_status,
            business_unit_id=body.business_unit_id,
            job_role_id=body.job_role_id,
            valid_from=body.organization_valid_from,
            expected_employee_id=employee_id,
            expected_org_valid_from=body.expected_org_valid_from,
        )
    return ProfileUpdateResult(
        employee_id=result.entity_id,
        org_history_action=result.values["org_history_action"],
    )
