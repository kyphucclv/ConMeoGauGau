# Phase 10 quality sign-off pack

Status: **Quality remediation complete; final cutover authorization pending**

## Snapshot identity

- Database: `english_class_p9_rehearsal`
- Source workbook: `okok_FIXED_v2.xlsx`
- Source checksum: `f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997`
- Issue snapshot SHA-256: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
- Generated at: `2026-07-14T19:29:55+07:00`
- Open unique issues: **0**
- P1 rows excluded from canonical enrollment/attendance facts: **0**
- P2 lineage/reference issues requiring acceptance: **0**

The detailed issue rows and editable decision fields are stored in
`docs/reviews/phase-10-quality-signoff.json`. A valid sign-off must refer
to both the source checksum and issue snapshot SHA-256 above.
Owners may complete the `bulk_decisions` entries or override individual
issue decisions. Every accepted decision requires owner, note, and date.

## Decision options

- `resolve_source`: correct the source/canonical mapping and rerun the rehearsal; this remains blocking while the issue is open.
- `accept_exclusion`: accept that the quarantined row is excluded from canonical facts and KPIs.
- `accept_limitation`: accept incomplete lineage/reference data while retaining loaded canonical facts.
- `reject_cutover`: block production cutover until the issue is resolved.
- `pending`: no owner decision yet.

## Issue summary

| Priority | Issue code | Source sheet | Count | Data effect | Recommended action |
|---|---|---|---:|---|---|

## Owner decisions

| Issue code | Count | Decision | Owner | Date | Note |
|---|---:|---|---|---|---|

## Sign-off gate

Cutover remains blocked while any detailed issue has `decision: pending`,
`resolve_source`, or `reject_cutover`. Bulk acceptance is valid only when the owner
records the issue codes, accepted counts, rationale, source checksum, and
issue snapshot SHA-256.

Validation command:

```powershell
python scripts\phase10_quality_signoff.py --validate-decisions
```

| Sign-off item | Owner | Decision/status | Date |
|---|---|---|---|
| P1 exclusion/resolution decision | TBD | Pending | TBD |
| P2 limitation/resolution decision | TBD | Pending | TBD |
| Final workbook checksum | TBD | Pending | TBD |
| Cutover authorization | TBD | Pending | TBD |

Reviewer decision: **Quality gate approved; production cutover still requires explicit final authorization.**
