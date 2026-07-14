# Phase 11 operational issue snapshot

Status: **Owner decisions approved for current high-severity legacy issues**

## Snapshot identity

- Database: `english_class`
- Source workbook: `okok_FIXED_v2.xlsx`
- Source checksum: `f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997`
- Operational issue snapshot SHA-256: `da4c78ce5ef58f15425cc5de2184654c8034ce89ed58a570705964efafd8bf12`
- Generated at: `2026-07-14T12:22:03+07:00`
- Total issues: **255**
- High severity issues: **173**
- Warning issues: **82**

Owner decisions are stored in the JSON file. Use `bulk_decisions` for
issue-code-level decisions, or set per-row `owner_decision` values for
exceptions.

## Summary

| Severity | Issue code | Workflow | Count | Owner options | Rollout disposition |
|---|---|---|---:|---|---|
| high | `incomplete_attendance_roster` | Attendance | 124 | `resolve_source`, `approve_legacy_attendance_exception` | Block rollout until original attendance is entered or an audited legacy exception is approved without inventing attendance facts. |
| high | `missing_business_placement` | Learners | 49 | `resolve_source`, `approve_unknown_placement_placeholder` | Block rollout until the owner supplies an entrance level or approves the Unknown Entrance Level placeholder. |
| warning | `low_attendance_follow_up` | Attendance | 82 | `review_operationally` | Warning only; review operationally and include in monthly follow-up. |

## Owner Decisions

| Issue code | Count | Decision | Owner | Date | Note |
|---|---:|---|---|---|---|
| `incomplete_attendance_roster` | 124 | `approve_legacy_attendance_exception` | Owner approval in chat | 2026-07-14 | Approved all 124 incomplete attendance roster issues as legacy exceptions; do not create invented Present/Absent attendance facts and exclude these legacy gaps from rollout blocking. |
| `missing_business_placement` | 49 | `approve_unknown_placement_placeholder` | Owner approval in chat | 2026-07-14 | Approved Unknown Entrance Level placeholder for 49 learners; HR will replace it with the confirmed placement later. |
| `low_attendance_follow_up` | 82 | `review_operationally` |  |  |  |

## High-Severity Examples

| Issue code | Entity | Entity key | Workflow | Details |
|---|---|---:|---|---|
| `incomplete_attendance_roster` | `session_unit` | 1014 | Attendance | `{"course_run_id": 84, "missing_enrollment_count": 1, "sequence_in_run": 2}` |
| `incomplete_attendance_roster` | `session_unit` | 1015 | Attendance | `{"course_run_id": 84, "missing_enrollment_count": 1, "sequence_in_run": 3}` |
| `incomplete_attendance_roster` | `session_unit` | 1016 | Attendance | `{"course_run_id": 84, "missing_enrollment_count": 1, "sequence_in_run": 4}` |
| `missing_business_placement` | `employee` | 148 | Learners | `{"emp_code": "203748"}` |
| `missing_business_placement` | `employee` | 149 | Learners | `{"emp_code": "257045"}` |
| `missing_business_placement` | `employee` | 150 | Learners | `{"emp_code": "133067"}` |

## Sign-Off Rule

Current high-severity legacy issues have owner-approved written
acceptance with owner, date, note, source checksum, and the exact
issue snapshot SHA-256 above. Warning issues remain operational
follow-up items.

Validation command:

```powershell
$env:PHASE11_DB='english_class'; python scripts\phase11_operational_issue_snapshot.py --validate-decisions
```
