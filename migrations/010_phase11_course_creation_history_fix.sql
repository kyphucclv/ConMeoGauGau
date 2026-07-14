-- Preserve unknown historical course creation times instead of treating the
-- Phase 11 deployment timestamp as a business creation event.
-- Forward verification: legacy courses have NULL created_at; later courses retain their timestamp.
-- Rollback: restore the backup taken before the Phase 11 migration chain.

UPDATE courses
SET created_at = NULL
WHERE created_at <= (
    SELECT applied_at FROM schema_migrations WHERE version = '009_phase11_monthly_review'
);

ALTER TABLE courses ALTER COLUMN created_at DROP NOT NULL;
