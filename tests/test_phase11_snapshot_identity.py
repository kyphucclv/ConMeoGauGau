import json
import subprocess
import sys

from scripts.phase11_operational_issue_snapshot import issue_decision_key, issue_identity_digest, prior_decisions


def issue(*, entity_key: str, stable_identity: dict, details: dict) -> dict:
    return {
        "issue_code": "incomplete_attendance_roster",
        "severity": "high",
        "entity_type": "session_unit",
        "entity_key": entity_key,
        "workflow": "Attendance",
        "details": details,
        "stable_identity": stable_identity,
    }


def test_snapshot_identity_ignores_surrogate_ids_and_row_order():
    first_rebuild = [
        issue(
            entity_key="101",
            stable_identity={"class_code": "A1", "course_code": "ENG", "run_number": 1, "sequence_in_run": 2},
            details={"course_run_id": 41, "missing_enrollment_count": 2},
        ),
        issue(
            entity_key="102",
            stable_identity={"class_code": "A1", "course_code": "ENG", "run_number": 1, "sequence_in_run": 3},
            details={"course_run_id": 41, "missing_enrollment_count": 1},
        ),
    ]
    second_rebuild = [
        issue(
            entity_key="902",
            stable_identity={"class_code": "A1", "course_code": "ENG", "run_number": 1, "sequence_in_run": 3},
            details={"course_run_id": 88, "missing_enrollment_count": 1},
        ),
        issue(
            entity_key="901",
            stable_identity={"class_code": "A1", "course_code": "ENG", "run_number": 1, "sequence_in_run": 2},
            details={"course_run_id": 88, "missing_enrollment_count": 2},
        ),
    ]

    assert issue_identity_digest(first_rebuild) == issue_identity_digest(second_rebuild)


def test_prior_decisions_are_not_reused_for_a_different_identity_set(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "metadata": {"source_checksum": "same-workbook", "issue_snapshot_sha256": "old-identity"},
                "bulk_decisions": [{"issue_code": "missing_business_placement", "owner_decision": "approved"}],
                "issues": [
                    {
                        "issue_code": "missing_business_placement",
                        "severity": "high",
                        "entity_type": "employee",
                        "entity_key": "1",
                        "workflow": "Learners",
                        "stable_identity": {"emp_code": "E001"},
                        "owner_decision": "approved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    bulk, issues = prior_decisions(snapshot, "same-workbook", "new-identity")

    assert bulk == {}
    assert issues == {}


def test_prior_per_issue_decision_follows_stable_identity_across_rebuilds(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    prior_issue = {
        "issue_code": "missing_business_placement",
        "severity": "high",
        "entity_type": "employee",
        "entity_key": "1",
        "workflow": "Learners",
        "stable_identity": {"emp_code": "E001"},
        "owner_decision": "approve_unknown_placement_placeholder",
    }
    snapshot.write_text(
        json.dumps(
            {
                "metadata": {"source_checksum": "workbook", "issue_snapshot_sha256": "identity"},
                "bulk_decisions": [],
                "issues": [prior_issue],
            }
        ),
        encoding="utf-8",
    )
    rebuilt_issue = {**prior_issue, "entity_key": "999", "owner_decision": "pending"}

    _, decisions = prior_decisions(snapshot, "workbook", "identity")

    assert decisions[issue_decision_key(rebuilt_issue)]["owner_decision"] == "approve_unknown_placement_placeholder"


def test_changed_issue_membership_changes_identity_even_when_counts_match():
    common = {
        "entity_key": "irrelevant",
        "details": {"missing_enrollment_count": 2},
    }
    approved_membership = issue(
        **common,
        stable_identity={
            "class_code": "A1", "course_code": "ENG", "run_number": 1,
            "sequence_in_run": 2, "missing_emp_codes": ["E001", "E002"],
        },
    )
    changed_membership = issue(
        **common,
        stable_identity={
            "class_code": "A1", "course_code": "ENG", "run_number": 1,
            "sequence_in_run": 2, "missing_emp_codes": ["E001", "E003"],
        },
    )

    assert issue_identity_digest([approved_membership]) != issue_identity_digest([changed_membership])


def test_phase9_rehearsal_writes_snapshot_evidence_outside_tracked_reviews():
    from scripts.phase9_cutover_rehearsal import PHASE11_REHEARSAL_JSON, PHASE11_REHEARSAL_MARKDOWN

    assert PHASE11_REHEARSAL_JSON.parent.name == "backups"
    assert PHASE11_REHEARSAL_MARKDOWN.parent.name == "backups"


def test_snapshot_cli_requires_an_explicit_action():
    result = subprocess.run(
        [sys.executable, "scripts/phase11_operational_issue_snapshot.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "one of the arguments --generate" in result.stderr
