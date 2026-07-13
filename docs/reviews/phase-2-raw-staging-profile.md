# Phase 2 raw staging and source profiling review

## Change identity

- Task/phase: Phase 2 - Raw staging and source profiling
- Developer: Codex
- Date: 2026-07-13
- Files changed:
  - `migrations/002_raw_staging_and_profile.sql`
  - `scripts/stage_workbook.py`
  - `docs/source-field-mapping.md`
  - `docs/reviews/phase-2-workbook-profile.json`
- Data entities affected: none in the working database; migration and staging were tested only on disposable database `english_class_p1_test`

## Contract review

- Re-read Phase 2 in `IMPLEMENTATION_PLAN.md`.
- Re-read raw preservation, ETL, mapping, and migration rules in `PROJECT_RULES.md`.
- Re-read `TARGET_ARCHITECTURE.md` legacy migration policy.
- Re-read `DATA_DICTIONARY.md` source deprecation and target grain notes.

Row grain:

```text
One raw_workbook_rows row represents exactly one meaningful source workbook row
from one sheet in one imported workbook checksum.
```

Invariants affected:

- Raw source rows are append-only/idempotent per import batch, sheet, and source row number.
- Raw payload stores cells, headers, typed serialized values, source sheet, source row number, and deterministic row hash.
- Canonical ETL remains deferred; no source row is silently classified as canonical/ignored in this phase.

## Implementation summary

Selected staging design:

- Generic raw table: `raw_workbook_rows`.
- Shared workbook identity: `source_workbooks`.
- Profile tables: `workbook_sheet_profiles`, `workbook_field_profiles`.
- Mapping registry table: `source_field_mappings`.

Why generic raw rows:

- The workbook has 18 sheets with helper/formula/pivot columns and changing widths.
- A generic raw payload can preserve every row without creating unstable sheet-specific staging DDL.
- Phase 3 ETL can map only reviewed core fields while retaining the full source row for reconciliation.

Profiler/loader:

- `scripts/stage_workbook.py` computes workbook SHA-256, row hashes, sheet/field stats, formula/error counts, top values, inferred types, malformed examples, and cross-sheet key coverage.
- It can write a compact JSON profile and load raw/profile records into PostgreSQL.
- Re-running the same source checksum is idempotent.

Mapping specification:

- `docs/source-field-mapping.md` covers `STUDENTS`, `PIC`, `COURSE_PLAN`, `LEVEL_HELPER`, `Placement`, `sheet2`, `ATTENDANCE_LOG`, and `CLASS_DATES`.
- Deprecated helper/formula fields are explicitly marked as raw-only.
- Stable issue codes are defined for Phase 3 ETL.

## Test evidence

Disposable database:

```text
english_class_p1_test
```

Commands executed:

```text
python .\scripts\stage_workbook.py .\okok_FIXED_v2.xlsx --profile-output .\docs\reviews\phase-2-workbook-profile.json
createdb -U postgres -h localhost -p 5432 -w english_class_p1_test
python .\migrate.py "postgresql://postgres@localhost:5432/english_class_p1_test"
python .\scripts\stage_workbook.py .\okok_FIXED_v2.xlsx --database-url postgresql://postgres@localhost:5432/english_class_p1_test --profile-output .\docs\reviews\phase-2-workbook-profile.json
python .\scripts\stage_workbook.py .\okok_FIXED_v2.xlsx --database-url postgresql://postgres@localhost:5432/english_class_p1_test --profile-output .\docs\reviews\phase-2-workbook-profile.json
psql ... -c "select count(*) as raw_rows from raw_workbook_rows;"
psql ... -c "select version, left(checksum, 12) from schema_migrations order by version;"
python -m py_compile .\scripts\stage_workbook.py
```

Important output:

```text
Applying: 001_canonical_schema_v3.sql
Applying: 002_raw_staging_and_profile.sql
Database migrations are up to date.
001_canonical_schema_v3: 8732e4848fa2
002_raw_staging_and_profile: 8de596a7ce78

source_checksum: b605d50a79b466cced02fd2fe75b676c933443d6b51cafef367f60fa1b07474d
sheet_count: 18
meaningful_rows: 9545
first staging run inserted_rows: 9545
second staging run inserted_rows: 0
raw_rows after second run: 9545
```

Profile highlights from `docs/reviews/phase-2-workbook-profile.json`:

| Sheet | Meaningful rows | Max columns | Formula cells | Error cells |
|---|---:|---:|---:|---:|
| `STUDENTS` | 309 | 30 | 3635 | 0 |
| `sheet2` | 538 | 90 | 7534 | 0 |
| `ATTENDANCE_LOG` | 6282 | 8 | 0 | 0 |
| `Placement` | 370 | 26 | 337 | 0 |
| `PIC` | 177 | 9 | 0 | 19 |
| `LEVEL_HELPER` | 15 | 6 | 0 | 0 |
| `CLASS_DATES` | 79 | 3 | 78 | 0 |
| `COURSE_PLAN` | 7 | 6 | 0 | 0 |

Cross-sheet coverage highlights after numeric-code normalization:

```text
Emp Code:
  STUDENTS distinct=308, sheet2 distinct=308, ATTENDANCE_LOG distinct=308
  Placement has 58 codes not in STUDENTS and misses 49 STUDENTS codes
  PIC has 37 distinct employee codes, all present in STUDENTS

Class Code:
  PIC distinct=52
  CLASS_DATES distinct=47, absent PIC classes include EL036, EL046, EL047, EL048, EL052
  sheet2 and ATTENDANCE_LOG each miss EL036 from PIC

Course Name:
  COURSE_PLAN, CLASS_DATES, sheet2, and ATTENDANCE_LOG each have the same 6 distinct course names

Level:
  LEVEL_HELPER distinct=14
  sheet2 has 13 referenced levels and no unknown level labels
  Placement has 3 level labels not in LEVEL_HELPER and misses 9 reference levels
```

Representative records manually traced:

- `ATTENDANCE_LOG` rows 1-5: header plus EL001/Business English attendance rows with date, status, employee, and PIC preserved in raw payload.
- `CLASS_DATES` rows 1-5: class/course rows preserve MINIFS formulas in `column_3`.
- `COURSE_PLAN` rows 1-5: course names and expected sessions are preserved as typed values.
- `LEVEL_HELPER` rows 1-5: level names and numeric values are preserved.
- `PIC` rows 1-5: class code, PIC name, employee code, mail, and extra helper columns are preserved.
- `Placement` rows 1-5: multi-row header/helper structure is preserved, not flattened away.
- `sheet2` rows 1-5: formulas and helper columns are preserved.
- `STUDENTS` rows 1-5: array formulas are serialized deterministically with formula text/ref, not Python object memory addresses.

## Reconciliation

| Dataset | Source meaningful rows | Raw staged rows | Difference |
|---|---:|---:|---:|
| all sheets | 9545 | 9545 | 0 |
| core sheets listed above | 7777 | 7777 | 0 |

- Re-importing the same workbook checksum inserted zero additional raw rows.
- Raw payload can reconstruct each staged source row because it stores sheet, source row number, headers, values-by-header, and cell list.
- No canonical rows were created in Phase 2.

## Review gate

Decision: **Approved for Phase 3 planning/implementation with constraints.**

Acceptance criteria status:

- [x] Re-importing the same workbook creates no duplicate raw rows.
- [x] Raw payload can reconstruct every meaningful source row used by ETL.
- [x] Profile output reproduces known anomalies, including `PIC` error cells and formula-heavy helper sheets.
- [x] Mapping specification exists for all required core sheets.
- [x] Workbook totals are confirmed against the source file, not README claims.

Residual risks / deferred work:

- Phase 3 must decide whether non-meaningful blank rows are intentionally ignored or retained with an approved ignored-row rule.
- `Placement` contains extra employee codes and level labels requiring issue routing.
- `STUDENTS` helper/formula columns are noisy and must not become canonical source of truth.
- App code still targets the legacy schema and remains deferred to later phases.
- `DRAFT_MIGRATIONS.lock` remains in place until the full chain is complete and approved.

Reviewer decision:

- [x] Approved
- [ ] Changes required
