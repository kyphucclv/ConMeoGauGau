# Issue #15 deterministic operational snapshot review

Status: **complete**

## Root cause

The Phase 11 snapshot hash and per-row decision key included volatile surrogate
IDs (`employee_id`, `run_enrollment_id`, `session_unit_id`, and related IDs in
details). Fresh databases assigned different values to the same business
records. Phase 9 also generated its disposable snapshot directly into the
tracked owner-signoff files.

## Stable identity grain

| Issue family | Stable business identity |
|---|---|
| `incomplete_employee_profile` | Employee code and exact missing profile fields |
| `employee_code_case_conflict` | Normalized employee code and conflicting employee-code set |
| `active_enrollment_conflict` | Employee code and active class/course/run set |
| `active_enrollment_membership_link_missing` | Employee code and class/course/run |
| `active_enrollment_snapshot_incomplete` | Employee code, class/course/run, and which snapshots are missing |
| `missing_business_placement` | Employee code |
| `session_datetime_conflict` | Class code, start time, and conflicting class/course/run set |
| `incomplete_attendance_roster` | Class/course/run, session sequence, and missing employee-code set |
| `low_attendance_follow_up` | Employee code and class/course/run |
| `capacity_override_review` | Employee code, class/course/run, and override event time |
| `transfer_link_incomplete` | Employee code, class code, and membership start date |

Surrogate IDs remain in display details for diagnosis but do not participate in
the approval identity. Identity rows are canonicalized and sorted before
hashing, so database allocation and query order cannot change the hash.

## Decision safety

- Decisions are carried forward only when source checksum **and exact stable
  snapshot hash** both match.
- Per-row decisions are keyed by stable business identity, not `entity_key`.
- A changed issue member changes the hash even when issue-code counts stay the
  same; attendance identity includes the exact missing employee-code set.
- Generation requires explicit `--generate`; validation, template writing, and
  template application are mutually exclusive explicit actions.
- Phase 9 writes disposable snapshot evidence under `backups/` and cannot
  overwrite tracked owner-signoff evidence.

## Evidence

- Two fresh Phase 9 databases produced the same hash:
  `d79985c7133e3cd8ef2758a2d4e83e194d9919488abac088b63784b780b8ca69`.
- Both rebuilds contained 255 unique stable identities: 124 incomplete-roster,
  49 missing-placement, and 82 low-attendance issues.
- The owner explicitly re-approved this exact hash on 2026-07-15.
- The focused regression suite covers surrogate-ID/order stability, changed
  membership with equal counts, decision carry-forward acceptance/rejection,
  explicit CLI action, and untracked rehearsal output.
- Full repository gates passed: 32 Python tests, React tests/build, Phase 13
  dictionary, Phase 8 UAT, Phase 9 rehearsal/restore, Phase 10 sign-off, and
  Phase 11 decision validation.

## Prevention

Snapshot approval identity is now a deep module behind
`issue_identity_digest(rows)`. Callers no longer need to know which database
fields are volatile, and every supported issue family must have a documented
stable grain before snapshot generation succeeds.
