"""Role enforcement at the service layer and evaluation versioning rules."""

from __future__ import annotations

import pytest

from services import BusinessService, CommandError


def test_viewer_cannot_write(factory, viewer_svc, seed_ids):
    with pytest.raises(CommandError) as excinfo:
        viewer_svc.create_cohort("PTVIEW", "Viewer Attempt")
    assert excinfo.value.code == "forbidden"


def test_inactive_or_unknown_actor_is_unauthorized(conn, factory):
    ghost = BusinessService(conn, 999999)
    with pytest.raises(CommandError) as excinfo:
        ghost.create_cohort("PTGHOST", "Ghost Attempt")
    assert excinfo.value.code == "unauthorized"


def test_editor_cannot_override_eligibility(factory, editor_svc):
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id
    with pytest.raises(CommandError) as excinfo:
        editor_svc.override_exam_eligibility(enrollment_id, True, "editor override attempt")
    assert excinfo.value.code == "forbidden"


def test_direct_exam_eligible_write_is_rejected(factory, admin_svc, seed_ids):
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id
    with pytest.raises(CommandError) as excinfo:
        admin_svc.record_evaluation(
            enrollment_id, final_level_id=seed_ids["final_level"], passed=True, exam_eligible=True
        )
    assert excinfo.value.code == "invalid_input"


def test_evaluation_correction_requires_reason_and_versions(factory, admin_svc, seed_ids):
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id

    first = admin_svc.record_evaluation(
        enrollment_id, final_level_id=seed_ids["final_level"], passed=True
    )
    assert first.values["version_number"] == 1

    with pytest.raises(CommandError) as excinfo:
        admin_svc.record_evaluation(enrollment_id, final_level_id=seed_ids["final_level"], passed=False)
    assert excinfo.value.code == "invalid_input"

    second = admin_svc.record_evaluation(
        enrollment_id,
        final_level_id=seed_ids["final_level"],
        passed=False,
        correction_reason="teacher corrected the result",
    )
    assert second.values["version_number"] == 2

    versions = factory.one(
        """SELECT count(*) FROM evaluation_versions ev
           JOIN evaluations e ON e.evaluation_id=ev.evaluation_id
           WHERE e.run_enrollment_id=%s""",
        (enrollment_id,),
    )
    assert versions[0] == 2, "corrections must append immutable versions, never overwrite"


def test_admin_override_wins_over_calculated_eligibility(factory, admin_svc):
    _, run_id = factory.cohort_run()
    enrollment_id = factory.onboard(run_id).entity_id
    # No delivered sessions yet: calculated eligibility is false (ratio 0 < 0.75).
    calculated = admin_svc.calculate_exam_eligibility(enrollment_id).values
    assert calculated["calculated_exam_eligible"] is False

    admin_svc.override_exam_eligibility(enrollment_id, True, "owner exception")
    effective = admin_svc.calculate_exam_eligibility(enrollment_id).values
    assert effective["effective_exam_eligible"] is True
    assert effective["exam_eligibility_override"] is True
    assert effective["exam_eligibility_override_reason"] == "owner exception"


def test_every_write_creates_audit_event(factory, admin_svc):
    before = factory.one("SELECT count(*) FROM audit_events")[0]
    _, run_id = factory.cohort_run()
    factory.onboard(run_id)
    after = factory.one("SELECT count(*) FROM audit_events")[0]
    assert after > before, "business writes must record audit events in the same transaction"
