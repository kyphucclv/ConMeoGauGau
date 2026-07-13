-- ============================================================================
-- English Class Management -- PostgreSQL schema
-- Migrated from Google Sheets "okok_FIXED_v2.xlsx"
--
-- Design notes:
--   * Sheets that were pure lookup/reference data become small dimension
--     tables (level_helper, course_plan).
--   * Sheets that were "wide" or denormalized (ATTENDANCE_INPUT, sheet2)
--     collapse into the base tables + views below -- no data is duplicated.
--   * Sheets that were purely computed reports/pivots (DASHBOARD, PROGRESS,
--     ATT_COUNT, Cross-check) are NOT tables here -- see views.sql. They are
--     recomputed on read from the base tables, so they can never drift out
--     of sync the way the spreadsheet formulas could.
--   * QC/scratch sheets (Log, DATE_ANOMALIES, Pivot Table 1, Trang tinh14,
--     "Ban sao cua Trang tinh8", Cross-check) are working notes, not part
--     of the production data model, and are intentionally left out.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Reference / lookup tables
-- ----------------------------------------------------------------------------

-- LEVEL_HELPER sheet -> lookup table mapping English level names to a
-- numeric scale (0 .. 6.5) used for progress comparisons.
CREATE TABLE level_helper (
    level_name     TEXT PRIMARY KEY,
    numeric_value  NUMERIC(3,1) NOT NULL
);

-- COURSE_PLAN sheet -> expected number of sessions per course.
CREATE TABLE course_plan (
    course_name        TEXT PRIMARY KEY,
    expected_sessions  SMALLINT NOT NULL CHECK (expected_sessions > 0)
);

-- ----------------------------------------------------------------------------
-- Core dimension tables
-- ----------------------------------------------------------------------------

-- STUDENTS sheet -> one row per employee/learner.
CREATE TABLE students (
    emp_code           TEXT PRIMARY KEY,
    full_name          TEXT NOT NULL,
    bu                 TEXT,
    role               TEXT,
    status             TEXT NOT NULL CHECK (status IN ('Active', 'Inactive', 'Waiting for class')),
    pic                TEXT,                     -- current PIC name (also see class_pic)
    current_course     TEXT REFERENCES course_plan(course_name),
    entrance_level     TEXT REFERENCES level_helper(level_name),
    current_level      TEXT REFERENCES level_helper(level_name),
    last_active_date   TIMESTAMP,
    drop_flag          TEXT,                     -- e.g. checkmark label from sheet
    drop_definition    TEXT,
    drop_reason        TEXT,
    remark             TEXT,
    latest_class_code  TEXT,                      -- FK added below once classes exists
    latest_course_name TEXT,
    progress_category  TEXT
);

-- PIC sheet -> one row per class code, who is responsible for it.
CREATE TABLE class_pic (
    class_code    TEXT PRIMARY KEY,
    pic_name      TEXT NOT NULL,
    pic_emp_code  TEXT REFERENCES students(emp_code),
    mail          TEXT,
    english_name  TEXT
);

-- CLASS_DATES sheet -> a "class" (class_code) runs one or more courses
-- sequentially over time (e.g. EL001 ran Business English, then
-- Communication 1, then Communication 2). Composite key matches the
-- sheet's grain exactly (78 rows, all unique class_code+course_name pairs).
CREATE TABLE class_offerings (
    class_code   TEXT NOT NULL REFERENCES class_pic(class_code),
    course_name  TEXT NOT NULL REFERENCES course_plan(course_name),
    start_date   TIMESTAMP,
    PRIMARY KEY (class_code, course_name)
);

ALTER TABLE students
    ADD CONSTRAINT fk_students_latest_class
    FOREIGN KEY (latest_class_code, latest_course_name)
    REFERENCES class_offerings(class_code, course_name);

-- ----------------------------------------------------------------------------
-- Fact tables
-- ----------------------------------------------------------------------------

-- Placement sheet -> entrance test results (one-time or repeat test),
-- independent of any specific class.
CREATE TABLE placements (
    placement_id            BIGSERIAL PRIMARY KEY,
    emp_code                 TEXT REFERENCES students(emp_code),
    full_name                TEXT,             -- kept as-supplied in case emp_code is later added manually
    test_date                DATE,
    level                     TEXT REFERENCES level_helper(level_name),
    grammar_feedback          TEXT,
    vocabulary_feedback       TEXT,
    pronunciation_feedback    TEXT,
    fluency_feedback          TEXT
);

-- sheet2 -> "enrollments": one row per student per class+course run,
-- recording the level the student entered and exited that run at.
-- This replaces sheet2's denormalized columns (BU/Role/PIC etc. are
-- looked up from students/class_pic instead of being copied here).
CREATE TABLE enrollments (
    emp_code                 TEXT NOT NULL REFERENCES students(emp_code),
    class_code               TEXT NOT NULL,
    course_name              TEXT NOT NULL,
    entrance_level           TEXT REFERENCES level_helper(level_name),
    final_level               TEXT REFERENCES level_helper(level_name),
    start_date                TIMESTAMP,
    first_class_start_date    TIMESTAMP,
    PRIMARY KEY (emp_code, class_code, course_name),
    FOREIGN KEY (class_code, course_name) REFERENCES class_offerings(class_code, course_name)
);

-- ATTENDANCE_LOG sheet -> the normalized session-by-session attendance log.
-- (ATTENDANCE_INPUT, the wide 16-columns-per-session version, is the raw
-- input this table was built from -- it is superseded by this table and not
-- migrated separately.)
CREATE TABLE attendance_log (
    attendance_id  BIGSERIAL PRIMARY KEY,
    class_code     TEXT NOT NULL,
    course_name    TEXT NOT NULL,
    emp_code       TEXT NOT NULL REFERENCES students(emp_code),
    session_order  SMALLINT NOT NULL,
    session_date   TIMESTAMP NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('Present', 'Absent')),
    FOREIGN KEY (class_code, course_name) REFERENCES class_offerings(class_code, course_name),
    UNIQUE (class_code, course_name, emp_code, session_order)
    -- NOTE: intentionally NOT FK'd to enrollments(emp_code, class_code, course_name).
    -- In the source data, 21 attendance rows exist for students who were never
    -- given a matching row in sheet2/enrollments (data entry gaps in the
    -- original spreadsheet). Attendance is the more authoritative log, so it
    -- is anchored to class_offerings + students only, not to enrollments.
);

-- ----------------------------------------------------------------------------
-- Indexes for the joins/filters the reports below rely on
-- ----------------------------------------------------------------------------

CREATE INDEX idx_students_status        ON students(status);
CREATE INDEX idx_students_bu            ON students(bu);
CREATE INDEX idx_enrollments_class      ON enrollments(class_code, course_name);
CREATE INDEX idx_attendance_class       ON attendance_log(class_code, course_name);
CREATE INDEX idx_attendance_emp         ON attendance_log(emp_code);
CREATE INDEX idx_placements_emp         ON placements(emp_code);

COMMIT;
