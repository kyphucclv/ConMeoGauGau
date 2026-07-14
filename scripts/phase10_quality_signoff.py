"""Generate the owner-facing quality sign-off snapshot from canonical issues."""

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
DEFAULT_JSON = ROOT / "docs" / "reviews" / "phase-10-quality-signoff.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "reviews" / "phase-10-quality-signoff.md"


ISSUE_POLICY = {
    "conflicting_session_structure": {
        "priority": "P1",
        "data_effect": "Attendance row was quarantined; schedule-dependent attendance KPIs may be understated.",
        "recommended_action": "Correct session order/date structure or explicitly accept exclusion from attendance KPIs.",
    },
    "run_boundary_unresolved": {
        "priority": "P1",
        "data_effect": "Attendance row was quarantined because the source may combine multiple course runs.",
        "recommended_action": "Confirm run boundaries and remap the row, or accept exclusion from the affected run KPIs.",
    },
    "attendance_without_enrollment": {
        "priority": "P1",
        "data_effect": "Attendance row was quarantined because no canonical enrollment could be identified.",
        "recommended_action": "Create or identify the enrollment, then reload; otherwise accept the missing attendance history.",
    },
    "missing_course": {
        "priority": "P1",
        "data_effect": "Enrollment row was quarantined because its course is missing.",
        "recommended_action": "Supply the course and reload, or confirm that the source row is not a valid enrollment.",
    },
    "malformed_date": {
        "priority": "P1",
        "data_effect": "Attendance row was quarantined because its date cannot be parsed.",
        "recommended_action": "Correct the source date and reload, or accept exclusion of the attendance row.",
    },
    "transfer_membership_unresolved": {
        "priority": "P2",
        "data_effect": "Enrollment was loaded, but transfer and cohort-membership lineage remains ambiguous.",
        "recommended_action": "Confirm transfer lineage or accept the enrollment without an inferred transfer link.",
    },
    "unknown_level": {
        "priority": "P2",
        "data_effect": "Placement was retained with a null canonical level, reducing progress-report completeness.",
        "recommended_action": "Map the source label to a canonical level or accept a null level.",
    },
    "unmapped_pic_employee": {
        "priority": "P2",
        "data_effect": "PIC assignment was quarantined because the employee could not be identified.",
        "recommended_action": "Supply the PIC employee code or accept the cohort without this historical assignment.",
    },
    "duplicate_business_placement": {
        "priority": "P2",
        "data_effect": "Duplicate placement row was quarantined; the first business placement was retained.",
        "recommended_action": "Confirm the retained placement or identify which row should be canonical.",
    },
}


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def issue_identity_digest(issues: list[dict[str, Any]]) -> str:
    identity_rows = [
        {
            "issue_id": issue["issue_id"],
            "issue_code": issue["issue_code"],
            "entity_type": issue["entity_type"],
            "entity_key": issue["entity_key"],
            "source_sheet": issue["source_sheet"],
            "source_row_number": issue["source_row_number"],
            "details": issue["details"],
        }
        for issue in issues
    ]
    identity_json = json.dumps(identity_rows, sort_keys=True, separators=(",", ":"), default=json_safe)
    return hashlib.sha256(identity_json.encode("utf-8")).hexdigest()


DECISION_FIELDS = ("decision", "decision_owner", "decision_note", "decided_at")


def issue_decision_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    return (
        issue["issue_code"],
        issue["entity_type"],
        issue["entity_key"],
        issue["source_sheet"],
        issue["source_row_number"],
    )


def prior_decisions(
    json_output: Path, source_checksum: str | None
) -> tuple[dict[str, dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]]]:
    if not json_output.exists():
        return {}, {}
    prior = json.loads(json_output.read_text(encoding="utf-8"))
    if prior.get("metadata", {}).get("source_checksum") != source_checksum:
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
                WHERE status = 'completed'
                ORDER BY completed_at DESC NULLS LAST, import_batch_id DESC
                LIMIT 1
                """
            )
            source = dict(cur.fetchone() or {})
            cur.execute(
                """
                SELECT issue_id, import_batch_id, issue_code, entity_type,
                       entity_key, source_sheet, source_row_number, details,
                       status, created_at
                FROM data_quality_issues
                WHERE status = 'open'
                ORDER BY issue_code, source_sheet, source_row_number, issue_id
                """
            )
            rows = [dict(row) for row in cur.fetchall()]

    unknown_codes = sorted({row["issue_code"] for row in rows} - ISSUE_POLICY.keys())
    if unknown_codes:
        raise RuntimeError(f"quality sign-off policy is missing issue codes: {unknown_codes}")

    issues = []
    for row in rows:
        policy = ISSUE_POLICY[row["issue_code"]]
        issues.append(
            {
                **row,
                **policy,
                "decision": "pending",
                "decision_owner": "",
                "decision_note": "",
                "decided_at": None,
            }
        )

    metadata = {
        "database_name": database_name,
        "source_name": source.get("source_name"),
        "source_checksum": source.get("source_checksum"),
        "issue_snapshot_sha256": issue_identity_digest(issues),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return metadata, issues


def summarize(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((issue["priority"], issue["issue_code"], issue["source_sheet"]) for issue in issues)
    return [
        {
            "priority": priority,
            "issue_code": code,
            "source_sheet": sheet,
            "count": count,
            "data_effect": ISSUE_POLICY[code]["data_effect"],
            "recommended_action": ISSUE_POLICY[code]["recommended_action"],
        }
        for (priority, code, sheet), count in sorted(counts.items())
    ]


def markdown_report(
    metadata: dict[str, Any],
    issues: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    bulk_decisions: list[dict[str, Any]],
) -> str:
    priority_counts = Counter(issue["priority"] for issue in issues)
    bulk = {row["issue_code"]: row for row in bulk_decisions}
    effective = Counter(
        (issue if issue["decision"] != "pending" else bulk[issue["issue_code"]])["decision"]
        for issue in issues
    )
    if not issues:
        status = "Quality remediation complete; final cutover authorization pending"
    elif effective["pending"]:
        status = "Pending data-owner decisions"
    else:
        status = "Owner decisions captured; remediation required before cutover"
    reviewer_decision = (
        "Quality gate approved; production cutover still requires explicit final authorization."
        if not issues
        else "Not approved for production cutover until owner sign-off is complete."
    )
    lines = [
        "# Phase 10 quality sign-off pack",
        "",
        f"Status: **{status}**",
        "",
        "## Snapshot identity",
        "",
        f"- Database: `{metadata['database_name']}`",
        f"- Source workbook: `{metadata['source_name']}`",
        f"- Source checksum: `{metadata['source_checksum']}`",
        f"- Issue snapshot SHA-256: `{metadata['issue_snapshot_sha256']}`",
        f"- Generated at: `{metadata['generated_at']}`",
        f"- Open unique issues: **{len(issues)}**",
        f"- P1 rows excluded from canonical enrollment/attendance facts: **{priority_counts['P1']}**",
        f"- P2 lineage/reference issues requiring acceptance: **{priority_counts['P2']}**",
        "",
        "The detailed issue rows and editable decision fields are stored in",
        "`docs/reviews/phase-10-quality-signoff.json`. A valid sign-off must refer",
        "to both the source checksum and issue snapshot SHA-256 above.",
        "Owners may complete the `bulk_decisions` entries or override individual",
        "issue decisions. Every accepted decision requires owner, note, and date.",
        "",
        "## Decision options",
        "",
        "- `resolve_source`: correct the source/canonical mapping and rerun the rehearsal; this remains blocking while the issue is open.",
        "- `accept_exclusion`: accept that the quarantined row is excluded from canonical facts and KPIs.",
        "- `accept_limitation`: accept incomplete lineage/reference data while retaining loaded canonical facts.",
        "- `reject_cutover`: block production cutover until the issue is resolved.",
        "- `pending`: no owner decision yet.",
        "",
        "## Issue summary",
        "",
        "| Priority | Issue code | Source sheet | Count | Data effect | Recommended action |",
        "|---|---|---|---:|---|---|",
    ]
    for row in summary:
        lines.append(
            f"| {row['priority']} | `{row['issue_code']}` | `{row['source_sheet']}` | "
            f"{row['count']} | {row['data_effect']} | {row['recommended_action']} |"
        )
    lines.extend(
        [
            "",
            "## Owner decisions",
            "",
            "| Issue code | Count | Decision | Owner | Date | Note |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for row in bulk_decisions:
        display = dict(row)
        detailed = [issue for issue in issues if issue["issue_code"] == row["issue_code"]]
        detailed_decisions = {issue["decision"] for issue in detailed if issue["decision"] != "pending"}
        if row["decision"] == "pending" and len(detailed_decisions) == 1 and all(
            issue["decision"] != "pending" for issue in detailed
        ):
            display["decision"] = f"per-row: {next(iter(detailed_decisions))}"
            display["decision_owner"] = ", ".join(sorted({issue["decision_owner"] for issue in detailed}))
            display["decided_at"] = ", ".join(sorted({str(issue["decided_at"]) for issue in detailed}))
            display["decision_note"] = "See the detailed issue decision in the JSON sign-off pack."
        note = str(display.get("decision_note") or "").replace("|", "\\|")
        lines.append(
            f"| `{display['issue_code']}` | {display['expected_count']} | `{display['decision']}` | "
            f"{display.get('decision_owner') or ''} | {display.get('decided_at') or ''} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Sign-off gate",
            "",
            "Cutover remains blocked while any detailed issue has `decision: pending`,",
            "`resolve_source`, or `reject_cutover`. Bulk acceptance is valid only when the owner",
            "records the issue codes, accepted counts, rationale, source checksum, and",
            "issue snapshot SHA-256.",
            "",
            "Validation command:",
            "",
            "```powershell",
            "python scripts\\phase10_quality_signoff.py --validate-decisions",
            "```",
            "",
            "| Sign-off item | Owner | Decision/status | Date |",
            "|---|---|---|---|",
            "| P1 exclusion/resolution decision | TBD | Pending | TBD |",
            "| P2 limitation/resolution decision | TBD | Pending | TBD |",
            "| Final workbook checksum | TBD | Pending | TBD |",
            "| Cutover authorization | TBD | Pending | TBD |",
            "",
            f"Reviewer decision: **{reviewer_decision}**",
            "",
        ]
    )
    return "\n".join(lines)


def generate(database_url: str, json_output: Path, markdown_output: Path) -> dict[str, Any]:
    metadata, issues = fetch_snapshot(database_url)
    prior_bulk, prior_issues = prior_decisions(json_output, metadata.get("source_checksum"))
    for issue in issues:
        previous = prior_issues.get(issue_decision_key(issue))
        if previous and previous.get("decision") != "pending":
            issue.update({field: previous.get(field) for field in DECISION_FIELDS})
    summary = summarize(issues)
    bulk_decisions = []
    for code, count in sorted(Counter(issue["issue_code"] for issue in issues).items()):
        row = {
            "issue_code": code,
            "expected_count": count,
            "decision": "pending",
            "decision_owner": "",
            "decision_note": "",
            "decided_at": None,
        }
        previous = prior_bulk.get(code)
        if previous and previous.get("decision") != "pending":
            row.update({field: previous.get(field) for field in DECISION_FIELDS})
        bulk_decisions.append(row)
    payload = {
        "metadata": metadata,
        "allowed_decisions": [
            "pending",
            "resolve_source",
            "accept_exclusion",
            "accept_limitation",
            "reject_cutover",
        ],
        "bulk_decisions": bulk_decisions,
        "summary": summary,
        "issues": issues,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_safe) + "\n", encoding="utf-8")
    markdown_output.write_text(markdown_report(metadata, issues, summary, bulk_decisions), encoding="utf-8")
    return {
        "issues": len(issues),
        "p1": sum(issue["priority"] == "P1" for issue in issues),
        "p2": sum(issue["priority"] == "P2" for issue in issues),
        "snapshot_sha256": metadata["issue_snapshot_sha256"],
        "json_output": str(json_output.relative_to(ROOT)),
        "markdown_output": str(markdown_output.relative_to(ROOT)),
    }


def validate_decisions(database_url: str, json_input: Path) -> dict[str, Any]:
    payload = json.loads(json_input.read_text(encoding="utf-8"))
    metadata, current_issues = fetch_snapshot(database_url)
    recorded = payload["metadata"]
    if issue_identity_digest(payload["issues"]) != recorded["issue_snapshot_sha256"]:
        raise RuntimeError("sign-off issue rows do not match their recorded snapshot SHA-256")
    if recorded["source_checksum"] != metadata["source_checksum"]:
        raise RuntimeError("source workbook checksum changed; regenerate the sign-off pack")
    if recorded["issue_snapshot_sha256"] != metadata["issue_snapshot_sha256"]:
        raise RuntimeError("open issue snapshot changed; regenerate the sign-off pack")

    current_counts = Counter(issue["issue_code"] for issue in current_issues)
    bulk = {row["issue_code"]: row for row in payload.get("bulk_decisions", [])}
    if set(bulk) != set(current_counts):
        raise RuntimeError("bulk decision issue codes do not match the current snapshot")
    for code, count in current_counts.items():
        if bulk[code]["expected_count"] != count:
            raise RuntimeError(f"bulk decision count mismatch for {code}: expected {count}")

    blocking = Counter()
    accepted = Counter()
    for issue in payload["issues"]:
        decision_row = issue if issue["decision"] != "pending" else bulk[issue["issue_code"]]
        decision = decision_row["decision"]
        priority = ISSUE_POLICY[issue["issue_code"]]["priority"]
        expected_acceptance = "accept_exclusion" if priority == "P1" else "accept_limitation"
        if decision != expected_acceptance:
            blocking[decision] += 1
            continue
        if not decision_row.get("decision_owner") or not decision_row.get("decision_note") or not decision_row.get("decided_at"):
            blocking["missing_signoff_fields"] += 1
            continue
        accepted[decision] += 1

    if blocking:
        raise RuntimeError(f"quality sign-off is not approved: {dict(blocking)}")
    return {
        "status": "approved",
        "issues": len(payload["issues"]),
        "accepted_exclusions": accepted["accept_exclusion"],
        "accepted_limitations": accepted["accept_limitation"],
        "source_checksum": metadata["source_checksum"],
        "snapshot_sha256": metadata["issue_snapshot_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--validate-decisions", action="store_true")
    args = parser.parse_args()

    maintenance_url = os.getenv("PHASE10_MAINTENANCE_URL", DEFAULT_MAINTENANCE_URL)
    db_name = os.getenv("PHASE10_DB", DEFAULT_DB)
    database_url = args.database_url or os.getenv("PHASE10_DATABASE_URL") or _database_url(db_name, maintenance_url)
    if args.validate_decisions:
        result = validate_decisions(database_url, args.json_output.resolve())
        print("Phase 10 quality sign-off decisions approved.")
    else:
        result = generate(database_url, args.json_output.resolve(), args.markdown_output.resolve())
        print("Phase 10 quality sign-off pack generated.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
