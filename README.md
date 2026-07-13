# English Class Management — PostgreSQL migration

> **Data model redesign in progress:** read `DATA_DICTIONARY.md` and
> `TARGET_ARCHITECTURE.md`. Do not apply the draft files in `migrations/` to a
> production database yet.

## Developer handoff

Read these documents in order before changing code or data:

1. `DATA_DICTIONARY.md` - field meaning and source of truth.
2. `TARGET_ARCHITECTURE.md` - entity grain and business invariants.
3. `PROJECT_RULES.md` - mandatory engineering and data-safety rules.
4. `IMPLEMENTATION_PLAN.md` - phased tasks, dependencies, tests, and gates.
5. `DEVELOPER_REVIEW_CHECKLIST.md` - evidence required for every phase/PR.

The current schema, ETL, views, app, setup guide, and draft migrations describe
an earlier model. They are reference material only until the implementation
plan replaces and re-verifies them.

## Legacy prototype baseline

The original prototype migrated `okok_FIXED_v2.xlsx` and reproduced several
spreadsheet dashboard totals. Later field-level review found that its
"zero silent data loss" claim was not a sufficient validation: source rows
include missing dates/courses and structurally ambiguous attendance. Treat the
old counts and views as comparison data, not v3 acceptance criteria.

## Files

- `schema.sql` — table definitions, primary/foreign keys, constraints, indexes.
- `views.sql` — reporting views that replace the spreadsheet's computed sheets.
- `admin_schema.sql` — application users and audit log tables for the admin app.
- `migrations/` + `migrate.py` — versioned, one-time upgrades for existing databases.
- `quality_checks.sql` — repeatable queries for known integrity gaps.
- `database_roles.sql` — restricted PostgreSQL role used by the web app.
- `backup.ps1` — timestamped PostgreSQL backup before upgrades.
- `etl.py` — one-time loader: reads the xlsx and populates the tables.
- `README.md` — this file.

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

## Legacy commands - do not run during redesign

```bash
psql "$DATABASE_URL" -f schema.sql
psql "$DATABASE_URL" -f views.sql
psql "$DATABASE_URL" -f admin_schema.sql
python3 -m pip install -r requirements.txt
python3 etl.py okok_FIXED_v2.xlsx "$DATABASE_URL"
python3 migrate.py "$DATABASE_URL"
```

For a database that already contains the imported data, create a backup and
run only `python migrate.py "$DATABASE_URL"`. Do not re-run the one-time ETL.
