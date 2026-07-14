# Phase 9 cutover and setup unlock review

## Change identity

- Task/phase: Phase 9 - Cutover and setup unlock
- Developer: Codex
- Date: 2026-07-13
- Files changed: `scripts/phase9_cutover_rehearsal.py`, `docs/runbooks/phase-9-cutover-runbook.md`, `README.md`, `SETUP_GUIDE.md`
- Data entities affected: disposable cutover rehearsal database, canonical staging, canonical ETL, roles, app smoke, backup/restore

## Decision

Cutover rehearsal, the five-finding hardening pass, and production cutover are
approved. The final workbook checksum, zero-issue quality snapshot,
backup/restore validation, restricted-role app smoke, and rollback path were
verified before the setup lock was removed.

## Rehearsal scope

The rehearsal created disposable database `english_class_p9_rehearsal`, applied
all canonical migrations, staged the current workbook, ran canonical ETL,
verified ETL idempotency, created restricted roles, smoke-tested the app, took a
custom-format PostgreSQL backup, restored it to a disposable database, and
queried restored data.

The rehearsal generated workbook profile:

- `docs/reviews/phase-9-workbook-profile.json`

## Test evidence

Commands executed:

```text
python -m py_compile scripts\phase9_cutover_rehearsal.py scripts\phase8_automated_uat.py services.py streamlit_app.py frontend_workflows.py
git diff --check
python scripts\phase9_cutover_rehearsal.py
```

Latest rehearsal output:

```text
Phase 9 cutover rehearsal passed.
{
  "database": "english_class_p9_rehearsal",
  "source_checksum": "f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997",
  "staged_rows": 9545,
  "canonical_etl_status": "completed",
  "canonical_etl_idempotent_status": "already_completed",
  "schema_versions": 7,
  "employees": 365,
  "run_enrollments": 552,
  "attendance_rows": 6281,
  "open_quality_issues": 0,
  "issue_outcomes": 0,
  "restricted_roles": [
    "english_class_p9_rehearsal_app",
    "english_class_p9_rehearsal_migration",
    "english_class_p9_rehearsal_readonly"
  ],
  "streamlit_smoke": {
    "database_user": "english_class_p9_rehearsal_app",
    "login_titles": 1,
    "errors": 0,
    "exceptions": 0
  },
  "backup_restore": {
    "backup_path": "backups\\phase9_cutover_rehearsal.dump",
    "backup_bytes": 2534635,
    "restored_employees": 365,
    "restored_schema_versions": 7
  },
  "profile_output": "docs\\reviews\\phase-9-workbook-profile.json"
}
```

## Actual output inspected

- Staged row count: `9545`.
- Source checksum:
  `f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997`.
- The checksum differs from the earlier workbook package after an Excel save,
  but a row-by-row comparison found zero changed values across all 9,545 staged
  rows.
- Canonical ETL completed once and returned `already_completed` on rerun.
- Canonical entity counts included `365` employees, `552` run enrollments, and
  `6281` attendance rows.
- Open quality issue count matched issue outcomes at `0`.
- Checksum-bound remediation loaded all attendance, supported PIC team labels,
  retained delivered occurrences for repeated logical sessions, applied the
  placement decisions, and inferred eight conservative transfer links.
- Restricted migration/app/read-only roles were created in the disposable DB.
- All public canonical relations are owned by the restricted migration role,
  and the Phase 6 gate proved that it can apply an `ALTER TABLE`.
- Streamlit smoke connected as `english_class_p9_rehearsal_app` and rendered
  login without errors or exceptions.
- Restored backup contained `365` employees and `7` schema migrations.

## Post-remediation ETL verification

The owner confirmed the missing session-13 date, PIC-as-team semantics, the
Foundation placement, and valid repeated session sequences, then delegated the
remaining pattern decisions. The full rehearsal staged all 9,545 rows from the
current workbook and applied migration
`007_session_occurrences_and_pic_labels`.

Inspected output:

- schema migrations: `7`;
- run enrollments: `552`;
- attendance rows loaded: `6281`;
- logical session keys: `956`;
- delivered session occurrences: `1016`;
- PIC employee links: `43`;
- PIC team labels: `9`;
- inferred transfer links: `8`;
- open quality issues and issue outcomes: `0`;
- Phase 10 snapshot: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

The same results were then reproduced by the full Phase 9 command directly from
the unlocked workbook, including profile generation, restricted app-role smoke,
backup, restore, and restored-row inspection.

## Production cutover

Production cutover completed on 2026-07-13 after explicit owner authorization.
The legacy database was retained as `english_class_legacy_20260713_154313`, and
the canonical schema was deployed to `english_class` using restricted migration,
application, and read-only roles.

- final source checksum: `f1d88362fdfc7d595843271361a8a59cffbc2c599cb3ae84ae7284b95b105997`;
- pre-cutover dump: `backups/english_class_cutover_20260713_153818.dump`;
- post-cutover dump: `backups/english_class_canonical_20260713_154723.dump`;
- restored canonical counts: `7` migrations, `365` employees, `552` run
  enrollments, `6281` attendance rows, and `0` open quality issues;
- existing admin credential preserved and active;
- Streamlit smoke connected as `english_class_app` with zero errors and zero
  exceptions.

## Hardening verification

- Rehearsal rejects production and any database name without `test` or
  `rehearsal` before the first mutation.
- `PHASE9_DATABASE_URL` can no longer redirect rehearsal mutations.
- App sessions revalidate active status and role on every rerun; Phase 8 proved
  that a deactivated session is returned to login.
- `v_unresolved_quality_issues` suppresses the ETL outcome duplicate when a
  matching quality issue ledger row exists.

## Phase 11 rehearsal addendum

On 2026-07-14, `python scripts\phase9_cutover_rehearsal.py` was rerun after
the Phase 11 operations workflow and operational issue snapshot gate were
added. That rehearsal applied all 15 migrations available at the time and
emitted the Phase 11 snapshot as part of the same production-shaped run.

A follow-up hardening migration, `016_phase11_runtime_invariants`, now extends
the current chain with database enforcement for attendance/enrollment
course-run consistency.

Inspected output:

- schema migrations: `15`;
- staged workbook rows: `9545`;
- employees: `365`;
- run enrollments: `552`;
- attendance rows: `6281`;
- open quality issues: `0`;
- operational data issues: `255`;
- Phase 11 high-severity operational issues: `173`;
- Phase 11 warning operational issues: `82`;
- Phase 11 snapshot:
  `da4c78ce5ef58f15425cc5de2184654c8034ce89ed58a570705964efafd8bf12`.

`python scripts\phase11_operational_issue_snapshot.py --validate-decisions`
passes with accepted decisions for `124` legacy attendance exceptions, `49`
unknown placement placeholders, and `82` operational low-attendance warnings.

## Assumptions and risks

- The current workbook checksum is the signed production source.
- Production has zero open quality issues; rollback assets must be retained
  until the owner closes the initial operating window.
- The runbook uses PostgreSQL 18 binaries at
  `C:\Program Files\PostgreSQL\18\bin`; adjust paths if production uses a
  different install location.
- `setup.ps1` remains legacy and locked; canonical setup instructions are now
  in `README.md`, `SETUP_GUIDE.md`, and the cutover runbook.

Reviewer decision: Production cutover and setup unlock approved.
