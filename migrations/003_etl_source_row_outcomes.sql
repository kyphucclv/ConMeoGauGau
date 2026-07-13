-- Per-source-row ETL outcome ledger.
-- This supports reconciliation without overloading data_quality_issues.

CREATE TABLE etl_source_row_outcomes (
    source_row_outcome_id BIGSERIAL PRIMARY KEY,
    import_batch_id BIGINT NOT NULL REFERENCES import_batches(import_batch_id),
    raw_row_id BIGINT NOT NULL REFERENCES raw_workbook_rows(raw_row_id),
    source_sheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    outcome_type TEXT NOT NULL CHECK (outcome_type IN ('loaded', 'issue', 'ignored')),
    outcome_code TEXT NOT NULL,
    target_entity TEXT,
    target_key TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_etl_source_row_outcomes_identity
    ON etl_source_row_outcomes (
        raw_row_id,
        outcome_type,
        outcome_code,
        COALESCE(target_entity, ''),
        COALESCE(target_key, '')
    );

CREATE INDEX idx_etl_outcomes_source
    ON etl_source_row_outcomes(import_batch_id, source_sheet, source_row_number);

CREATE INDEX idx_etl_outcomes_type_code
    ON etl_source_row_outcomes(outcome_type, outcome_code);
