-- Canonical ETL batch state.
-- Staging import_batches identify raw workbook loads; this table records
-- canonical transformation attempts against one staged import batch.

CREATE TABLE canonical_etl_batches (
    canonical_etl_batch_id BIGSERIAL PRIMARY KEY,
    import_batch_id BIGINT NOT NULL REFERENCES import_batches(import_batch_id),
    source_checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    failure_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    CHECK (
        (status = 'completed' AND completed_at IS NOT NULL AND failed_at IS NULL)
        OR (status = 'failed' AND failed_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'running' AND completed_at IS NULL AND failed_at IS NULL)
    )
);

CREATE UNIQUE INDEX uq_canonical_etl_completed_checksum
    ON canonical_etl_batches(source_checksum)
    WHERE status = 'completed';

CREATE INDEX idx_canonical_etl_batches_import_batch
    ON canonical_etl_batches(import_batch_id, status);
