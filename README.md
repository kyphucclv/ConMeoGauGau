# English Class Management — Canonical v3

Canonical v3 is deployed to the local production database and verified through
Phase 10. The checksum-matched cutover completed with zero open quality issues,
including restricted-role app smoke and backup/restore validation.

The current frontend includes the verified Phase 11 HR operations workflow
specified in `docs/reviews/phase-11-operations-workspace-spec.md`. Production
rollout validation is approved for the current workbook checksum and operational
issue snapshot after owner decisions for high-severity legacy data issues.

Phase 13.2 now provides HR-first learner start, continuation, rejoin, profile,
history, and transfer journeys while preserving the canonical service and audit
boundaries.

FastAPI + React is the only active frontend for the secure shell, learner,
attendance, final-result, monthly-review, follow-up/remediation, class/schedule,
registered-report, and restricted-audit journeys. The owner limited the final
scope to local testing on the designated machine and approved Streamlit
retirement on 2026-07-16.

The remaining pre-canonical database/ETL prototype files are archived under
`legacy/` and must not be run against the canonical database. The removed
Streamlit wrapper/setup remains available only in the final compatible tag. Use
the versioned migrations, staging loader, canonical ETL, and FastAPI/React app.

## Developer handoff

Read these documents in order before changing code or data:

1. `DATA_DICTIONARY.md` - field meaning and source of truth.
2. `TARGET_ARCHITECTURE.md` - entity grain and business invariants.
3. `PROJECT_RULES.md` - mandatory engineering and data-safety rules.
4. `IMPLEMENTATION_PLAN.md` - phased tasks, dependencies, tests, and gates.
5. `docs/reviews/phase-11-operations-workspace-spec.md` - approved HR workflow
   and UX acceptance criteria.
6. `DEVELOPER_REVIEW_CHECKLIST.md` - evidence required for every phase/PR.

## Verified canonical path

The current verified path is:

1. Create a PostgreSQL database.
2. Create restricted database roles and transfer canonical ownership with
   `database_roles.sql`.
3. Run `python migrate.py "<migration-role-database-url>"`.
4. Stage the workbook:
   `python scripts/stage_workbook.py okok_FIXED_v2.xlsx --database-url "<migration-role-database-url>" --profile-output docs/reviews/final-workbook-profile.json`
5. Run canonical ETL:
   `python scripts/canonical_etl_v3.py "<migration-role-database-url>"`.
6. Configure `APP_DATABASE_URL` or `DATABASE_URL` with the restricted app role
   URL outside the repository.
7. Create the first named app admin once:
   `python scripts/bootstrap_admin.py --username hr-admin --full-name "HR Admin"`.
8. Build the React frontend and start the checked FastAPI launcher:
   `npm --prefix web run build`, then `.\run_react_app.cmd`.

The launcher verifies Python packages, the restricted app database connection,
the canonical schema, the production build and the connection budget before
starting one loopback-only FastAPI worker behind the HTTPS gateway.

The app requires a named application username and password so every operational
change and audit event is attributed to the HR user who performed it.

## Verification and backups

Fast business-rule regression suite (seconds, disposable `english_class_pytest`
database, no workbook load):

```powershell
python -m pytest tests/
```

Full verification battery (fast suite + dictionary check + phase 8/9/10/11
gates) in one command:

```powershell
.\scripts\run-all-gates.ps1            # everything
.\scripts\run-all-gates.ps1 -SkipHeavy # fast suite + dictionary check only
.\scripts\run-all-gates.ps1 -TargetHost # also require live trusted HTTPS host proof
```

The production host runs the `EnglishClassDbBackup` scheduled task daily at
12:00 as SYSTEM with catch-up enabled, verified destinations and 30-day
retention. Issue #13 host verification runs the task and requires a new non-empty
dump with result code zero; Phase 9 supplies the disposable restore proof.
Manual run:

```powershell
.\backup.ps1
```

Database URLs are read from the user-scoped `APP_DATABASE_URL` and
`MIGRATION_DATABASE_URL` environment variables and never from repository files.

Phase 9 rehearsal command:

```powershell
python scripts\phase9_cutover_rehearsal.py
```

The rehearsal also regenerates the Phase 11 operational issue snapshot.

Generate and validate the owner-facing quality sign-off snapshot:

```powershell
python scripts\phase10_quality_signoff.py
python scripts\phase10_quality_signoff.py --validate-decisions
```

The latest checksum-matched verification passes with zero open quality issues.

Generate and validate the Phase 11 operational issue snapshot:

```powershell
python scripts\phase11_operational_issue_snapshot.py --generate
python scripts\phase11_operational_issue_snapshot.py --write-decision-template
python scripts\phase11_operational_issue_snapshot.py --apply-decision-template
python scripts\phase11_operational_issue_snapshot.py --validate-decisions
```

The validation command is expected to fail until the owner decisions in
`docs/reviews/phase-11-owner-decision-template.json` are completed and applied,
or the high-severity issues are resolved.

Latest rehearsal evidence is recorded in
`docs/reviews/phase-9-cutover-rehearsal.md`.

The current local production database is applied through
`020_app_sessions`. Migration 019 additionally enforces one linked
make-up per original absence and excludes make-up units from the attendance
denominator while preserving present replacement credit and immutable linkage.

## Files

- `migrations/` + `migrate.py` — canonical schema, staging, ETL batch, service,
  and reporting migrations.
- `scripts/stage_workbook.py` — auditable raw workbook staging.
- `scripts/canonical_etl_v3.py` — canonical v3 transformation.
- `config/phase10_remediation.json` — checksum-bound, owner-approved source
  overrides and unresolved confirmation inventory.
- `services/` — transactional business commands, one module per workflow
  concern (`base`, `employee_onboarding`, `membership_transfer`,
  `class_schedule`, `meetings_units`, `attendance_makeup`,
  `evaluation_completion`, `admin_remediation`).
- `api/` + `web/` — FastAPI HTTP boundary and the React application.
- `frontend_queries.py` — task-oriented canonical read models used by the API.
- `tests/` — fast disposable-database business-rule regression suite.
- `legacy/` — archived pre-canonical prototype; do not run.
- `run_react_app.cmd` / `run_react_app.ps1` — checked loopback-only FastAPI
  launcher used behind the HTTPS gateway.
- `database_roles.sql` — restricted migration/app/read-only role grants.
- `scripts/phase*_*.py` — disposable integration, UAT, and cutover rehearsal gates.
- `scripts/phase10_quality_signoff.py` — reproducible quality issue snapshot and
  owner-decision validation gate.
- `scripts/phase11_operational_issue_snapshot.py` — reproducible operational
  issue snapshot and Phase 11 owner-decision validation gate.
- `scripts/phase13_dictionary_check.py` — column-level dictionary validation
  against the applied canonical schema.
- `docs/reviews/phase-11-operations-workspace-spec.md` — owner-approved learner,
  attendance, monthly review, and data-issues workflow contract.
- `docs/reviews/` — phase evidence and review decisions.

## Cutover safety

Database cutover completed on 2026-07-13. The owner withdrew the HR/LAN rollout
and accepted local-only testing on 2026-07-16, so Issue #13 closed as not
planned. The final Streamlit-compatible source is retained at tag
`streamlit-final-compatible-2026-07-16`; the live repository has no Streamlit
runtime. See `docs/runbooks/issue-14-streamlit-retirement.md` for the retained
artifact and recovery evidence.

## Archived legacy notes

The sections below describe the original prototype and are kept only as
historical context.

## Legacy sheet mapping (superseded)

| Sheet | Becomes |
|---|---|
| STUDENTS | `students` table |
| PIC | `class_pic` table |
| CLASS_DATES | `class_offerings` table (+ rows recovered from sheet2/ATTENDANCE_LOG, see below) |
| COURSE_PLAN | `course_plan` table |
| LEVEL_HELPER | `level_helper` table |
| Placement | `placements` table |
| sheet2 | `enrollments` table + `v_enrollment_detail` view |
| ATTENDANCE_LOG | `attendance_log` table |
| ATTENDANCE_INPUT | not migrated — this was the raw wide-format input `ATTENDANCE_LOG` was built from; superseded by it |
| ATT_COUNT | `v_att_count` view (computed, not stored) |
| PROGRESS | `v_progress_by_bu` view |
| DASHBOARD | `v_dashboard_overview` + `v_dashboard_by_course` views |
| DATE_ANOMALIES, Log, Cross-check, Pivot Table 1, Trang tính14, Bản sao của Trang tính8 | QC/scratch notes — not part of the production data model |

## Legacy entity-relationship diagram (superseded)

```mermaid
erDiagram
    STUDENTS ||--o{ ENROLLMENTS : "enrolls in"
    STUDENTS ||--o{ PLACEMENTS : "takes"
    STUDENTS ||--o{ ATTENDANCE_LOG : "attends"
    STUDENTS ||--o{ CLASS_PIC : "may be PIC of"
    COURSE_PLAN ||--o{ CLASS_OFFERINGS : "offered as"
    CLASSES ||--o{ CLASS_OFFERINGS : "runs"
    CLASS_OFFERINGS ||--o{ ENROLLMENTS : "has"
    CLASS_OFFERINGS ||--o{ CLASS_SESSIONS : "schedules"
    CLASS_SESSIONS ||--o{ ATTENDANCE_LOG : "records"
    ENROLLMENTS ||--o{ ATTENDANCE_LOG : "links when available"
    LEVEL_HELPER ||--o{ STUDENTS : "entrance/current level"
    LEVEL_HELPER ||--o{ ENROLLMENTS : "entrance/final level"
    LEVEL_HELPER ||--o{ PLACEMENTS : "level"

    STUDENTS {
        text emp_code PK
        text full_name
        text bu
        text status
        text current_course FK
        text entrance_level FK
        text current_level FK
        text latest_class_code FK
    }
    CLASS_PIC {
        text class_code PK
        text pic_name
        text pic_emp_code FK
    }
    CLASS_OFFERINGS {
        text class_code PK_FK
        text course_name PK_FK
        timestamp start_date
    }
    COURSE_PLAN {
        text course_name PK
        smallint expected_sessions
    }
    LEVEL_HELPER {
        text level_name PK
        numeric numeric_value
    }
    ENROLLMENTS {
        text emp_code PK_FK
        text class_code PK_FK
        text course_name PK_FK
        text entrance_level FK
        text final_level FK
    }
    ATTENDANCE_LOG {
        bigint attendance_id PK
        text class_code FK
        text course_name FK
        text emp_code FK
        smallint session_order
        timestamp session_date
        text status
    }
    PLACEMENTS {
        bigint placement_id PK
        text emp_code FK
        date test_date
        text level FK
    }
```

## Known data-quality gaps (present in the original spreadsheet, handled not hidden)

- `emp_code` is stored as `float` in some sheets (e.g. PIC, Placement) and
  `string` in others (STUDENTS, ATTENDANCE_LOG) — the ETL normalizes all of
  these to `TEXT`.
- 6 (class_code, course_name) combinations appear in ATTENDANCE_LOG/sheet2
  but were missing a row in CLASS_DATES (e.g. `EL008` / `Business English`).
  The ETL adds them to `class_offerings` with a `NULL` start_date rather than
  dropping the attendance/enrollment data that depends on them.
- 21 attendance rows have no matching row in `enrollments` (sheet2) — real
  gaps in the source data entry. They are retained with a nullable
  `enrollment_id` and surfaced in `data_quality_issues` for correction.
- Session order and timestamp are both inconsistent in parts of the source.
  Some learners have the same order on different dates, and some timestamps
  carry multiple credited orders. The v3 model separates meetings from session
  units and routes ambiguous legacy groups to data-quality review.
- 57 Placement rows reference an `emp_code` not present in STUDENTS (likely
  candidates who never became active students) — kept, with `emp_code` set
  to `NULL` and `full_name` preserved as free text.
- Level labels like `"⏳ Chưa test"` / `"not placement"` (case mismatch with
  `"Not Placement"`) don't match `level_helper` and are stored as `NULL`.

## Legacy architecture (superseded)

`classes -> class_offerings -> class_sessions -> attendance_log` represents
the teaching schedule. `students -> enrollments -> attendance_log` represents
who joined it. `students.current_enrollment_id` explicitly selects the current
enrollment used by `v_student_current`; the old `students.current_*` columns
remain only as fallback data from the spreadsheet.

This architecture is retained only to explain the prototype. The target model
is defined in `TARGET_ARCHITECTURE.md`.

## Legacy commands - archived, do not run for canonical v3

The referenced files now live in `legacy/`.

```bash
psql "$DATABASE_URL" -f legacy/schema.sql
psql "$DATABASE_URL" -f legacy/views.sql
psql "$DATABASE_URL" -f legacy/admin_schema.sql
python3 -m pip install -r requirements.txt
python3 legacy/etl.py okok_FIXED_v2.xlsx "$DATABASE_URL"
python3 migrate.py "$DATABASE_URL"
```

For canonical v3, use the verified path at the top of this README and the
Phase 9 cutover runbook.
