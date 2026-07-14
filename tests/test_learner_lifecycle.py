"""Learner lifecycle rules: single active enrollment, capacity, transfer chain."""

from __future__ import annotations

from datetime import date

import pytest

from services import CommandError


def test_first_time_onboarding_creates_active_enrollment(factory):
    _, run_id = factory.cohort_run()
    result = factory.onboard(run_id)
    assert result.values["lifecycle"] == "first_time"
    row = factory.one(
        "SELECT status, business_unit_id_snapshot, job_role_id_snapshot FROM run_enrollments WHERE run_enrollment_id=%s",
        (result.entity_id,),
    )
    assert row[0] == "active"
    assert row[1] is not None and row[2] is not None


def test_second_active_enrollment_is_rejected(factory):
    _, run_a = factory.cohort_run()
    _, run_b = factory.cohort_run()
    enrolled = factory.onboard(run_a)
    emp_code = factory.one(
        "SELECT e.emp_code FROM employees e JOIN run_enrollments re ON re.employee_id=e.employee_id WHERE re.run_enrollment_id=%s",
        (enrolled.entity_id,),
    )[0]
    with pytest.raises(CommandError) as excinfo:
        factory.onboard(run_b, emp_code=emp_code)
    assert excinfo.value.code in {"active_enrollment_conflict", "active_membership_conflict"}


def test_capacity_requires_audited_override(factory):
    cohort_id, run_id = factory.cohort_run(capacity=1)
    factory.onboard(run_id)
    with pytest.raises(CommandError) as excinfo:
        factory.onboard(run_id)
    assert excinfo.value.code == "capacity_exceeded"

    result = factory.onboard(run_id, capacity_override_reason="owner approved overflow")
    override = factory.one(
        "SELECT reason, resulting_active_learner_count FROM cohort_capacity_overrides WHERE cohort_id=%s",
        (cohort_id,),
    )
    assert override[0] == "owner approved overflow"
    assert override[1] == 2
    assert result.values["lifecycle"] == "first_time"


def test_transfer_closes_source_and_links_chain(factory, admin_svc):
    _, run_a = factory.cohort_run()
    _, run_b = factory.cohort_run()
    enrolled = factory.onboard(run_a)

    proposal = admin_svc.propose_transfer_start_session(run_b).values["start_session_number"]
    transferred = admin_svc.transfer_learner(
        enrolled.entity_id,
        run_b,
        date(2026, 8, 15),
        confirmed_start_session_number=proposal,
    )

    source = factory.one(
        "SELECT status, cohort_membership_id FROM run_enrollments WHERE run_enrollment_id=%s",
        (enrolled.entity_id,),
    )
    assert source[0] == "transferred"
    target = factory.one(
        "SELECT status, transfer_from_enrollment_id FROM run_enrollments WHERE run_enrollment_id=%s",
        (transferred.entity_id,),
    )
    assert target[0] == "active"
    assert target[1] == enrolled.entity_id
    membership_chain = factory.one(
        "SELECT status, transfer_to_membership_id FROM cohort_memberships WHERE cohort_membership_id=%s",
        (source[1],),
    )
    assert membership_chain[0] == "transferred"
    assert membership_chain[1] == transferred.values["membership_id"]


def test_transfer_to_same_cohort_is_rejected(factory, admin_svc):
    cohort_id, run_a = factory.cohort_run()
    enrolled = factory.onboard(run_a)
    with pytest.raises(CommandError) as excinfo:
        admin_svc.transfer_learner(
            enrolled.entity_id, run_a, date(2026, 8, 15), confirmed_start_session_number=1
        )
    assert excinfo.value.code == "invalid_input"
