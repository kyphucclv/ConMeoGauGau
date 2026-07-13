-- Raw staging and source profiling support.
-- Every source workbook row can be reconstructed from raw_workbook_rows.raw_payload.

CREATE TABLE source_workbooks (
    source_workbook_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_checksum TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    workbook_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_name, source_checksum)
);

CREATE TABLE raw_workbook_rows (
    raw_row_id BIGSERIAL PRIMARY KEY,
    import_batch_id BIGINT NOT NULL REFERENCES import_batches(import_batch_id),
    source_workbook_id BIGINT NOT NULL REFERENCES source_workbooks(source_workbook_id),
    source_name TEXT NOT NULL,
    source_checksum TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    row_hash TEXT NOT NULL CHECK (length(row_hash) = 64),
    raw_payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (import_batch_id, sheet_name, source_row_number),
    UNIQUE (import_batch_id, sheet_name, row_hash)
);

CREATE INDEX idx_raw_rows_source
    ON raw_workbook_rows(source_checksum, sheet_name, source_row_number);

CREATE INDEX idx_raw_rows_hash
    ON raw_workbook_rows(source_checksum, row_hash);

CREATE TABLE workbook_sheet_profiles (
    sheet_profile_id BIGSERIAL PRIMARY KEY,
    source_workbook_id BIGINT NOT NULL REFERENCES source_workbooks(source_workbook_id),
    sheet_name TEXT NOT NULL,
    physical_rows INTEGER NOT NULL CHECK (physical_rows >= 0),
    meaningful_rows INTEGER NOT NULL CHECK (meaningful_rows >= 0),
    max_columns INTEGER NOT NULL CHECK (max_columns >= 0),
    formula_cells INTEGER NOT NULL DEFAULT 0 CHECK (formula_cells >= 0),
    error_cells INTEGER NOT NULL DEFAULT 0 CHECK (error_cells >= 0),
    duplicate_row_hashes INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_row_hashes >= 0),
    profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    profiled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_workbook_id, sheet_name)
);

CREATE TABLE workbook_field_profiles (
    field_profile_id BIGSERIAL PRIMARY KEY,
    sheet_profile_id BIGINT NOT NULL REFERENCES workbook_sheet_profiles(sheet_profile_id),
    field_name TEXT NOT NULL,
    column_index INTEGER NOT NULL CHECK (column_index > 0),
    non_null_count INTEGER NOT NULL DEFAULT 0 CHECK (non_null_count >= 0),
    null_count INTEGER NOT NULL DEFAULT 0 CHECK (null_count >= 0),
    distinct_count INTEGER NOT NULL DEFAULT 0 CHECK (distinct_count >= 0),
    duplicate_non_null_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_non_null_count >= 0),
    inferred_types JSONB NOT NULL DEFAULT '{}'::jsonb,
    top_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    malformed_examples JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (sheet_profile_id, column_index)
);

CREATE TABLE source_field_mappings (
    source_field_mapping_id BIGSERIAL PRIMARY KEY,
    source_sheet TEXT NOT NULL,
    source_field TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    target_field TEXT NOT NULL,
    field_class TEXT NOT NULL
        CHECK (field_class IN ('input', 'reference', 'snapshot', 'derived', 'audit', 'deprecated')),
    normalization_rule TEXT NOT NULL,
    source_priority TEXT NOT NULL DEFAULT 'primary',
    invalid_issue_code TEXT,
    notes TEXT,
    UNIQUE (source_sheet, source_field, target_entity, target_field)
);

CREATE INDEX idx_source_field_mappings_target
    ON source_field_mappings(target_entity, target_field);
