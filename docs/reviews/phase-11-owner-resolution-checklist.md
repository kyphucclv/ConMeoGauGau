# Phase 11 owner resolution checklist

Status: **Owner decisions approved for production rollout validation**

Generated from the production rollout validation snapshot on 2026-07-14.

Source workbook: `okok_FIXED_v2.xlsx`

Source checksum:
`f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997`

Validated database: `english_class`

Operational issue snapshot SHA-256:
`da4c78ce5ef58f15425cc5de2184654c8034ce89ed58a570705964efafd8bf12`

Full machine-readable issue snapshot:
`docs/reviews/phase-11-operational-issue-snapshot.json`

Owner decision template:
`docs/reviews/phase-11-owner-decision-template.json`

Human-readable issue snapshot:
`docs/reviews/phase-11-operational-issue-snapshot.md`

Production validation command:

```powershell
$env:PHASE11_DB='english_class'; python scripts\phase11_operational_issue_snapshot.py --validate-decisions
```

Rehearsal verification command:

```powershell
python scripts\phase9_cutover_rehearsal.py
```

Supporting UAT command:

```powershell
python scripts\phase8_automated_uat.py
```

Issue snapshot command:

```powershell
python scripts\phase11_operational_issue_snapshot.py
```

`python scripts\phase9_cutover_rehearsal.py` also regenerates this snapshot as
part of the production-shaped rehearsal.

Owner decision validation command:

```powershell
$env:PHASE11_DB='english_class'; python scripts\phase11_operational_issue_snapshot.py --validate-decisions
```

Generate the smaller owner-editable decision template:

```powershell
python scripts\phase11_operational_issue_snapshot.py --write-decision-template
```

After the owner edits `docs/reviews/phase-11-owner-decision-template.json`,
merge it back into the snapshot:

```powershell
python scripts\phase11_operational_issue_snapshot.py --apply-decision-template
```

## Production rollout summary

| Check | Result |
|---|---:|
| Schema migrations applied | 16 |
| Staged workbook rows | 9,545 |
| Employees | 365 |
| Run enrollments | 552 |
| Attendance rows | 6,281 |
| Open ETL quality issues | 0 |
| Operational data issues | 255 |
| Backup restore check | Passed |
| Restricted app smoke | Passed |
| Automated UAT gate | Passed |

## Automated UAT evidence

The 2026-07-14 UAT run passed the migration chain, service constraints,
Streamlit smoke path, backup/restore rehearsal, and Phase 11 workflow fixtures.

| Fixture | Result |
|---|---:|
| Transfer start-session proposal | 3 |
| Monthly repeated participant fixture | 1 |
| Two-latest-test improvement fixture | 1 |
| Monthly Excel export | Passed |
| Legacy attendance exception fixture | Passed |
| Bulk legacy attendance exception fixture | Passed |
| Unknown placement backfill fixture | Passed |
| Deactivated session rejection smoke | Passed |

## Rollout decisions

| Issue code | Severity | Count | Owner decision | Required evidence before rollout |
|---|---|---:|---|---|
| `incomplete_attendance_roster` | High | 124 | Approved audited legacy exception with no invented attendance facts. | Accepted by `python scripts\phase11_operational_issue_snapshot.py --validate-decisions`. |
| `missing_business_placement` | High | 49 | Approved `Unknown Entrance Level` placeholder only where no business placement exists. | Accepted by `python scripts\phase11_operational_issue_snapshot.py --validate-decisions`. |

Warnings do not block rollout by themselves:

| Issue code | Severity | Count | Operational handling |
|---|---|---:|---|
| `low_attendance_follow_up` | Warning | 82 | Review in monthly operations and follow up with HR/PIC as needed. |

## Representative high-severity examples

These examples identify the shape of each issue without serving as the full
worklist. The live worklist is `v_operational_data_issues` in the rehearsal or
production database.

| Issue code | Entity | Entity key | Workflow | Details |
|---|---|---:|---|---|
| `incomplete_attendance_roster` | `session_unit` | 1014 | Attendance | Course run 84, logical session 2, 1 missing learner. |
| `incomplete_attendance_roster` | `session_unit` | 1015 | Attendance | Course run 84, logical session 3, 1 missing learner. |
| `incomplete_attendance_roster` | `session_unit` | 1016 | Attendance | Course run 84, logical session 4, 1 missing learner. |
| `missing_business_placement` | `employee` | 148 | Learners | Employee code `203748` has no business placement. |
| `missing_business_placement` | `employee` | 149 | Learners | Employee code `257045` has no business placement. |
| `missing_business_placement` | `employee` | 150 | Learners | Employee code `133067` has no business placement. |

## Owner sign-off table

| Decision area | Decision | Owner | Date | Notes |
|---|---|---|---|---|
| Incomplete attendance rosters | Approved legacy exception | Owner approval in chat | 2026-07-14 | Do not create invented `Present` or `Absent` facts; exclude the legacy gaps from rollout blocking. |
| Missing business placements | Approved placeholder | Owner approval in chat | 2026-07-14 | HR will replace `Unknown Entrance Level` with confirmed placement later. |
| Schedule conflicts | Resolved from source year | Owner approval in chat | 2026-07-14 | `EL024 / Communication 1` dates are remediated from 2025 to 2024; Foundation 2025 remains unchanged. |
| Low attendance warnings | Review operationally | Operations follow-up | 2026-07-14 | Warning-only items remain in monthly operations follow-up and do not block rollout validation. |
| Production rollout validation | Approved | Owner approval in chat | 2026-07-14 | `--validate-decisions` passes for the current snapshot. |

## Execution notes

- Use the Data issues workspace to see the live list and jump to the corrective
  workflow.
- Legacy attendance exceptions must not create `Present` or `Absent` records.
- Unknown placement backfill must not overwrite an observed entrance level.
- Schedule conflict remediation must remain scoped to the owner-confirmed
  `EL024 / Communication 1` 2024 source-year correction.
- Re-run `python scripts\phase9_cutover_rehearsal.py` after decision-affecting
  changes to confirm rehearsal counts remain stable.
- Re-run `$env:PHASE11_DB='english_class'; python
  scripts\phase11_operational_issue_snapshot.py --validate-decisions` after
  owner decisions are entered in the JSON snapshot; it must pass before rollout
  approval.
- Owners may edit the smaller
  `docs/reviews/phase-11-owner-decision-template.json` instead of the full
  255-row snapshot, then use `--apply-decision-template` before validation.
