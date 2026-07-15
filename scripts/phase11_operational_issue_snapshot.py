"""Generate a reproducible Phase 11 operational issue snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase4_integration_check import _database_url


DEFAULT_DB = "english_class_p9_rehearsal"
DEFAULT_MAINTENANCE_URL = "postgresql://postgres@localhost:5432/postgres"
DEFAULT_JSON = ROOT / "docs" / "reviews" / "phase-11-operational-issue-snapshot.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "reviews" / "phase-11-operational-issue-snapshot.md"
DEFAULT_DECISION_TEMPLATE = ROOT / "docs" / "reviews" / "phase-11-owner-decision-template.json"

ISSUE_POLICY = {
    "incomplete_employee_profile": {
        "rollout_disposition": "Block rollout until current employee identity and organization data exists or the approved Unknown BU/Unknown Role policy is applied.",
        "owner_decision_options": ["resolve_source", "approve_unknown_org_placeholder"],
    },
    "employee_code_case_conflict": {
        "rollout_disposition": "Block rollout until the owner identifies the valid employee code casing and duplicate candidate handling.",
        "owner_decision_options": ["resolve_source", "reject_rollout"],
    },
    "active_enrollment_conflict": {
        "rollout_disposition": "Block rollout until only one active course-run enrollment remains for the employee.",
        "owner_decision_options": ["resolve_source", "reject_rollout"],
    },
    "active_enrollment_membership_link_missing": {
        "rollout_disposition": "Block rollout until each active enrollment is linked to its active cohort membership or re-created through the learner workflow.",
        "owner_decision_options": ["resolve_source", "reject_rollout"],
    },
    "active_enrollment_snapshot_incomplete": {
        "rollout_disposition": "Block rollout until each active enrollment has immutable BU and role snapshots from approved employee organization data.",
        "owner_decision_options": ["resolve_source", "reject_rollout"],
    },
    "missing_business_placement": {
        "rollout_disposition": "Block rollout until the owner supplies an entrance level or approves the Unknown Entrance Level placeholder.",
        "owner_decision_options": ["resolve_source", "approve_unknown_placement_placeholder"],
    },
    "session_datetime_conflict": {
        "rollout_disposition": "Block rollout until the owner confirms the valid occurrence and the duplicate meeting is cancelled with audit.",
        "owner_decision_options": ["resolve_source", "cancel_duplicate_meeting"],
    },
    "incomplete_attendance_roster": {
        "rollout_disposition": "Block rollout until original attendance is entered or an audited legacy exception is approved without inventing attendance facts.",
        "owner_decision_options": ["resolve_source", "approve_legacy_attendance_exception"],
    },
    "low_attendance_follow_up": {
        "rollout_disposition": "Warning only; review operationally and include in monthly follow-up.",
        "owner_decision_options": ["review_operationally"],
    },
    "capacity_override_review": {
        "rollout_disposition": "Warning only when the override is audited; review operationally.",
        "owner_decision_options": ["review_operationally"],
    },
    "transfer_link_incomplete": {
        "rollout_disposition": "Block rollout until transferred membership has a target membership link or owner accepts incomplete legacy lineage.",
        "owner_decision_options": ["resolve_source", "accept_legacy_lineage_limitation"],
    },
}

# Stable business grain used for owner-approval identity. Surrogate keys remain
# in display details for diagnostics but never participate in snapshot hashes.
ISSUE_IDENTITY_GRAIN = {
    "incomplete_employee_profile": "employee emp_code plus exact missing profile fields",
    "employee_code_case_conflict": "normalized emp_code plus conflicting emp_codes",
    "active_enrollment_conflict": "employee emp_code plus active class/course/run set",
    "active_enrollment_membership_link_missing": "employee emp_code plus class/course/run",
    "active_enrollment_snapshot_incomplete": "employee emp_code plus class/course/run and missing snapshot fields",
    "missing_business_placement": "employee emp_code",
    "session_datetime_conflict": "class_code plus starts_at and conflicting class/course/run set",
    "incomplete_attendance_roster": "class/course/run plus sequence and missing emp_code set",
    "low_attendance_follow_up": "employee emp_code plus class/course/run",
    "capacity_override_review": "employee emp_code plus class/course/run and override event time",
    "transfer_link_incomplete": "employee emp_code plus class_code and membership start date",
}

DECISION_FIELDS = ("owner_decision", "decision_owner", "decision_note", "decided_at")
ACCEPTED_EXISTING_HIGH_DECISIONS = {
    "approve_unknown_org_placeholder",
    "approve_unknown_placement_placeholder",
    "approve_legacy_attendance_exception",
    "accept_legacy_lineage_limitation",
}


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def issue_identity_digest(rows: list[dict[str, Any]]) -> str:
    identity_rows = [
        {
            "issue_code": row["issue_code"],
            "severity": row["severity"],
            "entity_type": row["entity_type"],
            "workflow": row["workflow"],
            "stable_identity": row["stable_identity"],
        }
        for row in rows
    ]
    identity_rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=json_safe))
    identity_json = json.dumps(identity_rows, sort_keys=True, separators=(",", ":"), default=json_safe)
    return hashlib.sha256(identity_json.encode("utf-8")).hexdigest()


def issue_decision_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    return (
        issue["issue_code"],
        issue["severity"],
        issue["entity_type"],
        issue["workflow"],
        json.dumps(issue["stable_identity"], sort_keys=True, separators=(",", ":"), default=json_safe),
    )


def prior_decisions(
    json_output: Path, source_checksum: str | None, issue_snapshot_sha256: str
) -> tuple[dict[str, dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]]]:
    if not json_output.exists():
        return {}, {}
    prior = json.loads(json_output.read_text(encoding="utf-8"))
    if prior.get("metadata", {}).get("source_checksum") != source_checksum:
        return {}, {}
    if prior.get("metadata", {}).get("issue_snapshot_sha256") != issue_snapshot_sha256:
        return {}, {}
    bulk = {row["issue_code"]: row for row in prior.get("bulk_decisions", [])}
    issues = {issue_decision_key(row): row for row in prior.get("issues", [])}
    return bulk, issues


def fetch_snapshot(database_url: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with psycopg2.connect(database_url) as conn:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS database_name")
            database_name = cur.fetchone()["database_name"]
            cur.execute(
                """
                SELECT source_name, source_checksum
                FROM import_batches
                WHERE status='completed'
                ORDER BY completed_at DESC NULLS LAST, import_batch_id DESC
                LIMIT 1
                """
            )
            source = dict(cur.fetchone() or {})
            cur.execute(
                """
                SELECT v.severity, v.issue_code, v.entity_type, v.entity_key,
                       v.title, v.workflow, v.details,
                       CASE v.issue_code
                         WHEN 'incomplete_employee_profile' THEN (
                           SELECT jsonb_build_object(
                             'emp_code', e.emp_code,
                             'full_name_missing', NULLIF(BTRIM(e.full_name), '') IS NULL,
                             'current_org_missing', eoh.employee_org_history_id IS NULL,
                             'business_unit_missing', eoh.business_unit_id IS NULL,
                             'job_role_missing', eoh.job_role_id IS NULL
                           )
                           FROM employees e
                           LEFT JOIN employee_org_history eoh ON eoh.employee_id=e.employee_id AND eoh.is_current
                           WHERE e.employee_id = v.entity_key::bigint
                         )
                         WHEN 'employee_code_case_conflict' THEN jsonb_build_object(
                           'normalized_emp_code', v.details->'normalized_emp_code',
                           'emp_codes', (
                             SELECT jsonb_agg(e.emp_code ORDER BY e.emp_code)
                             FROM employees e
                             WHERE lower(e.emp_code) = v.details->>'normalized_emp_code'
                           )
                         )
                         WHEN 'active_enrollment_conflict' THEN (
                           SELECT jsonb_build_object(
                             'emp_code', e.emp_code,
                             'active_runs', jsonb_agg(
                               jsonb_build_array(c.class_code, course.course_code, cr.run_number)
                               ORDER BY c.class_code, course.course_code, cr.run_number
                             )
                           )
                           FROM employees e
                           JOIN run_enrollments re ON re.employee_id=e.employee_id AND re.status='active'
                           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE e.employee_id=v.entity_key::bigint
                           GROUP BY e.emp_code
                         )
                         WHEN 'active_enrollment_membership_link_missing' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code, 'class_code', c.class_code,
                             'course_code', course.course_code, 'run_number', cr.run_number)
                           FROM run_enrollments re
                           JOIN employees e ON e.employee_id=re.employee_id
                           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE re.run_enrollment_id=v.entity_key::bigint
                         )
                         WHEN 'active_enrollment_snapshot_incomplete' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code, 'class_code', c.class_code,
                             'course_code', course.course_code, 'run_number', cr.run_number,
                             'business_unit_missing', re.business_unit_id_snapshot IS NULL,
                             'job_role_missing', re.job_role_id_snapshot IS NULL)
                           FROM run_enrollments re
                           JOIN employees e ON e.employee_id=re.employee_id
                           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE re.run_enrollment_id=v.entity_key::bigint
                         )
                         WHEN 'missing_business_placement' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code)
                           FROM employees e WHERE e.employee_id=v.entity_key::bigint
                         )
                         WHEN 'session_datetime_conflict' THEN (
                           SELECT jsonb_build_object(
                             'class_code', c.class_code,
                             'starts_at', v.details->'starts_at',
                             'conflicting_runs', (
                               SELECT jsonb_agg(
                                 jsonb_build_array(c2.class_code, course.course_code, cr.run_number)
                                 ORDER BY c2.class_code, course.course_code, cr.run_number
                               )
                               FROM meetings m
                               JOIN course_runs cr ON cr.course_run_id=m.course_run_id
                               JOIN cohorts c2 ON c2.cohort_id=cr.cohort_id
                               JOIN courses course ON course.course_id=cr.course_id
                               WHERE c2.cohort_id=c.cohort_id AND m.starts_at=(v.details->>'starts_at')::timestamptz
                                 AND m.status <> 'cancelled'
                             )
                           )
                           FROM cohorts c WHERE c.cohort_id=v.entity_key::bigint
                         )
                         WHEN 'incomplete_attendance_roster' THEN (
                           SELECT jsonb_build_object(
                             'class_code', c.class_code, 'course_code', course.course_code,
                             'run_number', cr.run_number, 'sequence_in_run', su.sequence_in_run,
                             'missing_emp_codes', (
                               SELECT jsonb_agg(e.emp_code ORDER BY e.emp_code)
                               FROM run_enrollments re
                               JOIN employees e ON e.employee_id=re.employee_id
                               LEFT JOIN attendance a ON a.session_unit_id=su.session_unit_id
                                 AND a.run_enrollment_id=re.run_enrollment_id
                               WHERE re.course_run_id=su.course_run_id AND re.status='active'
                                 AND re.start_session_number<=su.sequence_in_run AND a.attendance_id IS NULL
                             )
                           )
                           FROM session_units su
                           JOIN course_runs cr ON cr.course_run_id=su.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE su.session_unit_id=v.entity_key::bigint
                         )
                         WHEN 'low_attendance_follow_up' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code, 'class_code', c.class_code,
                             'course_code', course.course_code, 'run_number', cr.run_number)
                           FROM run_enrollments re
                           JOIN employees e ON e.employee_id=re.employee_id
                           JOIN course_runs cr ON cr.course_run_id=re.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE re.run_enrollment_id=v.entity_key::bigint
                         )
                         WHEN 'capacity_override_review' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code, 'class_code', c.class_code,
                             'course_code', course.course_code, 'run_number', cr.run_number,
                             'override_created_at', cco.created_at)
                           FROM cohort_capacity_overrides cco
                           JOIN employees e ON e.employee_id=cco.employee_id
                           JOIN course_runs cr ON cr.course_run_id=cco.course_run_id
                           JOIN cohorts c ON c.cohort_id=cr.cohort_id
                           JOIN courses course ON course.course_id=cr.course_id
                           WHERE cco.cohort_capacity_override_id=v.entity_key::bigint
                         )
                         WHEN 'transfer_link_incomplete' THEN (
                           SELECT jsonb_build_object('emp_code', e.emp_code, 'class_code', c.class_code,
                             'membership_start_date', cm.start_date)
                           FROM cohort_memberships cm
                           JOIN employees e ON e.employee_id=cm.employee_id
                           JOIN cohorts c ON c.cohort_id=cm.cohort_id
                           WHERE cm.cohort_membership_id=v.entity_key::bigint
                         )
                       END AS stable_identity
                FROM v_operational_data_issues v
                ORDER BY
                    CASE v.severity WHEN 'high' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                    v.issue_code, v.entity_type, v.entity_key
                """
            )
            rows = [dict(row) for row in cur.fetchall()]

    unknown_codes = sorted({row["issue_code"] for row in rows} - ISSUE_POLICY.keys())
    if unknown_codes:
        raise RuntimeError(f"operational issue policy is missing issue codes: {unknown_codes}")
    if set(ISSUE_IDENTITY_GRAIN) != set(ISSUE_POLICY):
        raise RuntimeError("stable identity grain is not documented for every operational issue code")
    missing_identity = [row["issue_code"] for row in rows if row.get("stable_identity") is None]
    if missing_identity:
        raise RuntimeError(f"stable business identity is missing for issue codes: {sorted(set(missing_identity))}")

    metadata = {
        "database_name": database_name,
        "source_name": source.get("source_name"),
        "source_checksum": source.get("source_checksum"),
        "issue_snapshot_sha256": issue_identity_digest(rows),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    enriched = [
        {
            **row,
            **ISSUE_POLICY[row["issue_code"]],
            "owner_decision": "pending",
            "decision_owner": "",
            "decision_note": "",
            "decided_at": None,
        }
        for row in rows
    ]
    return metadata, enriched


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((row["severity"], row["issue_code"], row["workflow"]) for row in rows)
    return [
        {
            "severity": severity,
            "issue_code": issue_code,
            "workflow": workflow,
            "count": count,
            "rollout_disposition": ISSUE_POLICY[issue_code]["rollout_disposition"],
            "owner_decision_options": ISSUE_POLICY[issue_code]["owner_decision_options"],
        }
        for (severity, issue_code, workflow), count in sorted(
            counts.items(), key=lambda item: (0 if item[0][0] == "high" else 1, item[0][1], item[0][2])
        )
    ]


def markdown_report(
    metadata: dict[str, Any],
    summary: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    bulk_decisions: list[dict[str, Any]],
) -> str:
    severity_counts = Counter(row["severity"] for row in rows)
    bulk_by_code = {row["issue_code"]: row for row in bulk_decisions}
    high_decisions_approved = True
    for row in summary:
        if row["severity"] != "high":
            continue
        decision_row = bulk_by_code.get(row["issue_code"], {})
        decision = decision_row.get("owner_decision")
        if decision not in ACCEPTED_EXISTING_HIGH_DECISIONS:
            high_decisions_approved = False
            break
        if not decision_row.get("decision_owner") or not decision_row.get("decision_note") or not decision_row.get("decided_at"):
            high_decisions_approved = False
            break
    status = (
        "Status: **Owner decisions approved for current high-severity legacy issues**"
        if high_decisions_approved
        else "Status: **Snapshot generated; owner decisions required for high-severity issues**"
    )
    examples = []
    seen = Counter()
    for row in rows:
        if row["severity"] != "high" or seen[row["issue_code"]] >= 3:
            continue
        seen[row["issue_code"]] += 1
        examples.append(row)

    lines = [
        "# Phase 11 operational issue snapshot",
        "",
        status,
        "",
        "## Snapshot identity",
        "",
        f"- Database: `{metadata['database_name']}`",
        f"- Source workbook: `{metadata.get('source_name')}`",
        f"- Source checksum: `{metadata.get('source_checksum')}`",
        f"- Operational issue snapshot SHA-256: `{metadata['issue_snapshot_sha256']}`",
        f"- Generated at: `{metadata['generated_at']}`",
        f"- Total issues: **{len(rows)}**",
        f"- High severity issues: **{severity_counts['high']}**",
        f"- Warning issues: **{severity_counts['warning']}**",
        "",
        "Owner decisions are stored in the JSON file. Use `bulk_decisions` for",
        "issue-code-level decisions, or set per-row `owner_decision` values for",
        "exceptions.",
        "",
        "## Summary",
        "",
        "| Severity | Issue code | Workflow | Count | Owner options | Rollout disposition |",
        "|---|---|---|---:|---|---|",
    ]
    for row in summary:
        options = ", ".join(f"`{option}`" for option in row["owner_decision_options"])
        lines.append(
            f"| {row['severity']} | `{row['issue_code']}` | {row['workflow']} | {row['count']} | "
            f"{options} | {row['rollout_disposition']} |"
        )
    lines.extend(
        [
            "",
            "## Owner Decisions",
            "",
            "| Issue code | Count | Decision | Owner | Date | Note |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for row in bulk_decisions:
        note = str(row.get("decision_note") or "").replace("|", "\\|")
        lines.append(
            f"| `{row['issue_code']}` | {row['expected_count']} | `{row['owner_decision']}` | "
            f"{row.get('decision_owner') or ''} | {row.get('decided_at') or ''} | {note} |"
        )
    lines.extend(
        [
            "",
            "## High-Severity Examples",
            "",
            "| Issue code | Entity | Entity key | Workflow | Details |",
            "|---|---|---:|---|---|",
        ]
    )
    for row in examples:
        details = dict(row["details"] or {})
        if row["issue_code"] == "missing_business_placement":
            details.pop("full_name", None)
        details = json.dumps(details, ensure_ascii=False, sort_keys=True, default=json_safe).replace("|", "\\|")
        lines.append(f"| `{row['issue_code']}` | `{row['entity_type']}` | {row['entity_key']} | {row['workflow']} | `{details}` |")
    if high_decisions_approved:
        signoff_lines = [
            "Current high-severity legacy issues have owner-approved written",
            "acceptance with owner, date, note, source checksum, and the exact",
            "issue snapshot SHA-256 above. Warning issues remain operational",
            "follow-up items.",
        ]
    else:
        signoff_lines = [
            "Production rollout is not approved while any high-severity issue is",
            "`pending`, `resolve_source`, `cancel_duplicate_meeting`, or",
            "`reject_rollout` in this snapshot. Written acceptance must include",
            "owner, date, note, source checksum, and the exact issue snapshot",
            "SHA-256 above. Warning issues remain operational follow-up items.",
        ]
    lines.extend(
        [
            "",
            "## Sign-Off Rule",
            "",
            *signoff_lines,
            "",
            "Validation command:",
            "",
            "```powershell",
            "$env:PHASE11_DB='english_class'; python scripts\\phase11_operational_issue_snapshot.py --validate-decisions",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def generate(database_url: str, json_output: Path, markdown_output: Path) -> dict[str, Any]:
    metadata, rows = fetch_snapshot(database_url)
    prior_bulk, prior_issues = prior_decisions(
        json_output, metadata.get("source_checksum"), metadata["issue_snapshot_sha256"]
    )
    for row in rows:
        previous = prior_issues.get(issue_decision_key(row))
        if previous and previous.get("owner_decision") != "pending":
            row.update({field: previous.get(field) for field in DECISION_FIELDS})
    summary = summarize(rows)
    bulk_decisions = []
    for row in summary:
        decision = {
            "issue_code": row["issue_code"],
            "severity": row["severity"],
            "expected_count": row["count"],
            "owner_decision": "pending",
            "decision_owner": "",
            "decision_note": "",
            "decided_at": None,
        }
        previous = prior_bulk.get(row["issue_code"])
        if previous and previous.get("owner_decision") != "pending":
            decision.update({field: previous.get(field) for field in DECISION_FIELDS})
        bulk_decisions.append(decision)
    payload = {
        "metadata": metadata,
        "allowed_decisions": sorted(
            {option for policy in ISSUE_POLICY.values() for option in policy["owner_decision_options"]} | {"pending"}
        ),
        "bulk_decisions": bulk_decisions,
        "summary": summary,
        "issues": rows,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_safe) + "\n", encoding="utf-8")
    markdown_output.write_text(markdown_report(metadata, summary, rows, bulk_decisions), encoding="utf-8")
    return {
        "issues": len(rows),
        "high": sum(row["severity"] == "high" for row in rows),
        "warning": sum(row["severity"] == "warning" for row in rows),
        "snapshot_sha256": metadata["issue_snapshot_sha256"],
        "json_output": str(json_output.relative_to(ROOT)),
        "markdown_output": str(markdown_output.relative_to(ROOT)),
    }


def write_decision_template(snapshot_input: Path, template_output: Path) -> dict[str, Any]:
    payload = json.loads(snapshot_input.read_text(encoding="utf-8"))
    template = {
        "metadata": {
            "source_checksum": payload["metadata"]["source_checksum"],
            "issue_snapshot_sha256": payload["metadata"]["issue_snapshot_sha256"],
            "generated_from": str(snapshot_input.relative_to(ROOT)) if snapshot_input.is_relative_to(ROOT) else str(snapshot_input),
        },
        "instructions": [
            "Fill owner_decision, decision_owner, decision_note, and decided_at.",
            "Use decided_at as YYYY-MM-DD.",
            "High-severity resolve_source/cancel_duplicate_meeting decisions mean the issue must be corrected and disappear before validation can pass.",
            "Schedule conflicts must be corrected; they cannot be accepted while still present.",
        ],
        "allowed_decisions": payload["allowed_decisions"],
        "decisions": payload["bulk_decisions"],
    }
    template_output.parent.mkdir(parents=True, exist_ok=True)
    template_output.write_text(json.dumps(template, ensure_ascii=False, indent=2, default=json_safe) + "\n", encoding="utf-8")
    return {
        "decision_template": str(template_output.relative_to(ROOT)) if template_output.is_relative_to(ROOT) else str(template_output),
        "decision_rows": len(template["decisions"]),
        "source_checksum": template["metadata"]["source_checksum"],
        "snapshot_sha256": template["metadata"]["issue_snapshot_sha256"],
    }


def apply_decision_template(snapshot_input: Path, template_input: Path) -> dict[str, Any]:
    payload = json.loads(snapshot_input.read_text(encoding="utf-8"))
    template = json.loads(template_input.read_text(encoding="utf-8"))
    if template.get("metadata", {}).get("source_checksum") != payload["metadata"]["source_checksum"]:
        raise RuntimeError("decision template source checksum does not match the snapshot")
    if template.get("metadata", {}).get("issue_snapshot_sha256") != payload["metadata"]["issue_snapshot_sha256"]:
        raise RuntimeError("decision template snapshot SHA-256 does not match the snapshot")
    decisions = {row["issue_code"]: row for row in template.get("decisions", [])}
    if set(decisions) != {row["issue_code"] for row in payload.get("bulk_decisions", [])}:
        raise RuntimeError("decision template issue codes do not match the snapshot")
    for row in payload["bulk_decisions"]:
        incoming = decisions[row["issue_code"]]
        if incoming.get("expected_count") != row["expected_count"]:
            raise RuntimeError(f"decision template count mismatch for {row['issue_code']}")
        for field in DECISION_FIELDS:
            row[field] = incoming.get(field)
    snapshot_input.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_safe) + "\n", encoding="utf-8")
    return {
        "updated_snapshot": str(snapshot_input.relative_to(ROOT)) if snapshot_input.is_relative_to(ROOT) else str(snapshot_input),
        "applied_decisions": len(decisions),
        "source_checksum": payload["metadata"]["source_checksum"],
        "snapshot_sha256": payload["metadata"]["issue_snapshot_sha256"],
    }


def validate_decisions(database_url: str, json_input: Path) -> dict[str, Any]:
    payload = json.loads(json_input.read_text(encoding="utf-8"))
    metadata, current_rows = fetch_snapshot(database_url)
    recorded = payload["metadata"]
    if issue_identity_digest(payload["issues"]) != recorded["issue_snapshot_sha256"]:
        raise RuntimeError("issue rows do not match their recorded snapshot SHA-256")
    if recorded["source_checksum"] != metadata["source_checksum"]:
        raise RuntimeError("source workbook checksum changed; regenerate the Phase 11 issue snapshot")
    if recorded["issue_snapshot_sha256"] != metadata["issue_snapshot_sha256"]:
        raise RuntimeError("operational issue snapshot changed; regenerate the Phase 11 issue snapshot")

    current_counts = Counter(row["issue_code"] for row in current_rows)
    bulk = {row["issue_code"]: row for row in payload.get("bulk_decisions", [])}
    if set(bulk) != set(current_counts):
        raise RuntimeError("bulk decision issue codes do not match the current snapshot")
    for code, count in current_counts.items():
        if bulk[code]["expected_count"] != count:
            raise RuntimeError(f"bulk decision count mismatch for {code}: expected {count}")

    allowed_by_code = {code: set(policy["owner_decision_options"]) | {"pending"} for code, policy in ISSUE_POLICY.items()}
    blocking = Counter()
    accepted = Counter()
    for issue in payload["issues"]:
        decision_row = issue if issue.get("owner_decision") != "pending" else bulk[issue["issue_code"]]
        decision = decision_row["owner_decision"]
        if decision not in allowed_by_code[issue["issue_code"]]:
            blocking[f"invalid:{decision}"] += 1
            continue
        if issue["severity"] == "warning":
            if decision not in {"pending", "review_operationally"}:
                blocking[decision] += 1
            else:
                accepted[decision] += 1
            continue
        if decision not in ACCEPTED_EXISTING_HIGH_DECISIONS:
            blocking[decision] += 1
            continue
        if not decision_row.get("decision_owner") or not decision_row.get("decision_note") or not decision_row.get("decided_at"):
            blocking["missing_signoff_fields"] += 1
            continue
        accepted[decision] += 1

    if blocking:
        raise RuntimeError(f"Phase 11 rollout decisions are not approved: {dict(blocking)}")
    return {
        "status": "approved",
        "issues": len(payload["issues"]),
        "accepted": dict(accepted),
        "source_checksum": metadata["source_checksum"],
        "snapshot_sha256": metadata["issue_snapshot_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--generate", action="store_true")
    actions.add_argument("--validate-decisions", action="store_true")
    actions.add_argument("--write-decision-template", action="store_true")
    parser.add_argument("--decision-template", type=Path, default=DEFAULT_DECISION_TEMPLATE)
    actions.add_argument("--apply-decision-template", action="store_true")
    args = parser.parse_args()

    maintenance_url = os.getenv("PHASE11_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    db_name = os.getenv("PHASE11_DB", DEFAULT_DB)
    database_url = args.database_url or os.getenv("PHASE11_DATABASE_URL") or _database_url(db_name, maintenance_url)
    if args.write_decision_template:
        result = write_decision_template(args.json_output.resolve(), args.decision_template.resolve())
        print("Phase 11 owner decision template generated.")
    elif args.apply_decision_template:
        try:
            result = apply_decision_template(args.json_output.resolve(), args.decision_template.resolve())
        except RuntimeError as exc:
            print(f"Phase 11 owner decision template was not applied: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print("Phase 11 owner decision template applied.")
    elif args.validate_decisions:
        try:
            result = validate_decisions(database_url, args.json_output.resolve())
        except RuntimeError as exc:
            print(f"Phase 11 operational issue decisions are not approved: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print("Phase 11 operational issue decisions approved.")
    elif args.generate:
        result = generate(database_url, args.json_output.resolve(), args.markdown_output.resolve())
        print("Phase 11 operational issue snapshot generated.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
