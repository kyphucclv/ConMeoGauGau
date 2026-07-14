# Phase 10 owner checklist for okok_FIXED_v2.xlsx

Workbook being reviewed: `okok_FIXED_v2.xlsx`

Status: **Owner decisions captured and pattern remediation applied**

Reviewer: ____________________

Review date: ____________________

## Applied decision summary

- Session 13: confirmed as `2026-06-23 13:00:00` for rows 4118 and 4133.
- Session 7: inferred as `2026-04-21 13:00:00` from the weekly Tuesday cadence;
  the owner authorized a pattern-based fill.
- PIC: treated as a team label when no employee code exists; all 52 cohort PIC
  assignments now load, including nine labels.
- Placement `247082`: Foundation from row 353 replaces the earlier business
  placement; its date remains unknown and is retained as null.
- Repeated session orders on different dates: treated as valid delivered
  occurrences of one logical session, not course-run resets.
- Transfers: inferred only for same-course mid-run handoffs with no overlap and
  a gap of at most 30 days; eight links satisfy the rule.
- Result: 6,281 attendance rows loaded and zero open quality issues in the
  checksum-matched ETL verification.

## Safety first

- [ ] Keep `okok_FIXED_v2.xlsx` unchanged as the audit source.
- [ ] If making corrections, save them as `okok_FIXED_v3.xlsx`.
- [ ] Record the evidence used for each correction: calendar, trainer record,
  attendance form, HR directory, email, or owner confirmation.
- [ ] Do not guess missing employee codes, dates, run boundaries, or transfers.

## A. Required checks to unblock cutover

### A1. Missing EL034 attendance dates

Open `ATTENDANCE_LOG`. Column `F` is `Date`.

| Done | Cell | Employee | Class/course | Session | Confirmed date/time | Evidence |
|---|---|---|---|---:|---|---|
| [ ] | `F4118` | `227097` | EL034 / Business English | 13 |  |  |
| [ ] | `F4127` | `247088` | EL034 / Business English | 7 |  |  |
| [ ] | `F4133` | `247088` | EL034 / Business English | 13 |  |  |

Acceptance:

- [ ] Session 7 has one confirmed actual date/time.
- [ ] Session 13 has one confirmed actual date/time, or a documented reason
  why the two employees attended different meetings.

### A2. Missing PIC employee codes

Open `PIC`. Column `C` is `EMP Code`. Confirm against HR/email records; do not
copy learner codes from helper columns on the right.

| Done | Cell | Class | PIC name | Confirmed employee code | Evidence |
|---|---|---|---|---|---|
| [ ] | `C6` | EL005 | Duc Nguyen |  |  |
| [ ] | `C9` | EL008 | Hung Nguyen |  |  |
| [ ] | `C11` | EL010 | Huy Tran 1 |  |  |
| [ ] | `C12` | EL011 | Huy Tran 2 |  |  |
| [ ] | `C13` | EL012 | Huyen Vo |  |  |
| [ ] | `C24` | EL023 | Ky Luong |  |  |
| [ ] | `C37` | EL036 | Ky Phuc |  |  |
| [ ] | `C50` | EL049 | Phung Nguyen |  |  |
| [ ] | `C53` | EL052 | Duong Pham |  |  |

### A3. Placement decision for employee 247082

Open `Placement` and inspect row `353` together with the earlier placement for
employee `247082`.

Current records:

- Existing business placement: Beginner, `2024-12-11`.
- `C353` is blank and `D353` is Foundation.

Choose exactly one:

- [ ] Diagnostic/retest: retain row 353 and enter the confirmed date in `C353`.
- [ ] Replacement: retain Foundation as the canonical business placement and
  document why it replaces the 2024-12-11 result.
- [ ] Duplicate/error: exclude row 353.

Decision: ____________________

Evidence/note: ____________________________________________________________

### A4. Five class/course run-boundary reviews

In `ATTENDANCE_LOG`, use:

- Column `A`: Class Code
- Column `B`: Course Name
- Column `E`: Session Order
- Column `F`: Date

Filter one class/course at a time and sort by `F` ascending. For each group,
confirm whether it is one run with incorrect session numbers or multiple runs.

| Done | Class/course | Approx. source rows | Open rows | Number of actual runs | Evidence/note |
|---|---|---:|---:|---:|---|
| [ ] | EL004 / Communication 1 | 324-413 | 90 |  |  |
| [ ] | EL007 / Communication 2 | 708-827 | 120 |  |  |
| [ ] | EL026 / Communication 2 | 3073-3149 | 77 |  |  |
| [ ] | EL030 / Communication 1 | 3554-3623 | 70 |  |  |
| [ ] | EL046 / Communication 1 | 5696-5805 | 110 |  |  |

For every group above:

- [ ] Identify each actual run number.
- [ ] Record each run's first and last meeting date.
- [ ] Confirm the canonical session sequence for every meeting date.
- [ ] Confirm whether two session orders on one timestamp represent two valid
  credited units.
- [ ] Mark incorrect `Session Order` or `Date` cells for correction.
- [ ] Do not split a run using date gaps alone; use a schedule or owner record.

### A5. Other conflicting session structures

These groups have repeated session orders or inconsistent meeting timestamps,
but no separately confirmed run boundary yet.

| Done | Class/course | Affected rows | Result: date error / order error / valid repeat / separate run | Evidence |
|---|---|---:|---|---|
| [ ] | EL033 / Communication 2 | 45 |  |  |
| [ ] | EL012 / Communication 1 | 35 |  |  |
| [ ] | EL015 / Communication 1 | 24 |  |  |
| [ ] | EL020 / Communication 1 | 24 |  |  |
| [ ] | EL014 / Communication 1 | 20 |  |  |
| [ ] | EL005 / Communication 1 | 15 |  |  |
| [ ] | EL013 / Communication 1 | 12 |  |  |
| [ ] | EL029 / Communication 1 | 12 |  |  |
| [ ] | EL049 / Foundation | 10 |  |  |
| [ ] | EL002 / Communication 1 | 8 |  |  |
| [ ] | EL037 / Communication 1 | 8 |  |  |
| [ ] | EL039 / Communication 1 | 8 |  |  |
| [ ] | EL013 / Communication 3 | 6 |  |  |
| [ ] | EL035 / Communication 1 | 6 |  |  |
| [ ] | EL047 / Communication 1 | 6 |  |  |
| [ ] | EL003 / Communication 1 | 5 |  |  |
| [ ] | EL008 / Communication 1 | 5 |  |  |

### A6. Twenty-three suspicious transfer transitions

Open `sheet2` at the target row. For each transition, confirm `TRANSFER` or
`NOT TRANSFER`. If it is a transfer, provide the effective date and target
start session.

| Done | Row | Employee | From | To | Observed target start | Decision | Transfer date/evidence |
|---|---:|---|---|---|---:|---|---|
| [ ] | 193 | 247389 | EL007 / Communication 2 | EL020 / Communication 2 | 1 |  |  |
| [ ] | 194 | 227183 | EL007 / Communication 2 | EL020 / Communication 2 | 1 |  |  |
| [ ] | 195 | 247390 | EL007 / Communication 2 | EL020 / Communication 2 | 1 |  |  |
| [ ] | 196 | 213891 | EL007 / Communication 2 | EL020 / Communication 2 | 1 |  |  |
| [ ] | 227 | 227122 | EL001 / Communication 2 | EL022 / Communication 3 | 2 |  |  |
| [ ] | 431 | 237061 | EL026 / Communication 1 | EL039 / Communication 1 | 5 |  |  |
| [ ] | 432 | 247265 | EL003 / Communication 1 | EL039 / Communication 1 | 6 |  |  |
| [ ] | 433 | 227035 | EL023 / Communication 1 | EL039 / Communication 1 | 5 |  |  |
| [ ] | 434 | 247415 | EL003 / Communication 1 | EL039 / Communication 1 | 6 |  |  |
| [ ] | 436 | 213946 | EL035 / Communication 1 | EL039 / Communication 1 | 5 |  |  |
| [ ] | 437 | 237245 | EL026 / Communication 1 | EL039 / Communication 1 | 5 |  |  |
| [ ] | 438 | 227188 | EL026 / Communication 1 | EL039 / Communication 1 | 5 |  |  |
| [ ] | 461 | 227035 | EL039 / Communication 1 | EL042 / Communication 1 | 1 |  |  |
| [ ] | 471 | 213881 | EL037 / Foundation | EL043 / Foundation | 4 |  |  |
| [ ] | 473 | 213929 | EL027 / Communication 1 | EL043 / Foundation | 4 |  |  |
| [ ] | 474 | 227058 | EL027 / Communication 1 | EL043 / Foundation | 4 |  |  |
| [ ] | 475 | 247082 | EL044 / Communication 1 | EL043 / Foundation | 4 |  |  |
| [ ] | 484 | 213856 | EL015 / Communication 1 | EL045 / Communication 1 | 3 |  |  |
| [ ] | 501 | 193607 | EL041 / Communication 1 | EL047 / Communication 1 | 4 |  |  |
| [ ] | 508 | 237103 | EL049 / Foundation | EL048 / Communication 1 | 3 |  |  |
| [ ] | 519 | 193633 | EL014 / Communication 1 | EL050 / Communication 1 | 2 |  |  |
| [ ] | 521 | 247185 | EL015 / Communication 2 | EL050 / Communication 1 | 2 |  |  |
| [ ] | 523 | 227177 | EL015 / Communication 2 | EL050 / Communication 1 | 2 |  |  |

## B. Source cleanup already handled by ETL

These items no longer block the rehearsal, but correcting them in the next
workbook removes reliance on the remediation manifest.

### B1. EL052 missing course

Open `sheet2`; column `E` is `Course Name`.

- [ ] Confirm and enter `Foundation` in `E532:E538`.
- [ ] Confirm employee `267040` belongs to EL052 even though no attendance was
  observed in the current workbook.

### B2. Not Placement casing

Open `Placement`; column `D` is `1st session:`.

- [ ] Change `D238` from `not placement` to `Not Placement`.
- [ ] Change `D281:D286` from `not placement` to `Not Placement`.
- [ ] Change `D330` from `not placement` to `Not Placement`.
- [ ] Change `D334` from `not placement` to `Not Placement`.

### B3. Duplicate placements already decided

- [ ] Confirm row `336`, employee `247313`, is a diagnostic/retest dated
  `2025-06-05`, not a replacement business placement.
- [ ] Confirm row `354`, employee `227058`, is an invalid exact duplicate and
  should remain excluded.

## Completion package

Provide either:

- `okok_FIXED_v3.xlsx` containing confirmed corrections; or
- this completed checklist plus supporting schedule/HR exports.

Before handoff:

- [ ] Every edited value has evidence or a named owner confirmation.
- [ ] No formulas, helper columns, or unrelated rows were reformatted.
- [ ] The original `okok_FIXED_v2.xlsx` remains available unchanged.
- [ ] The corrected file name/version and reviewer are recorded.
