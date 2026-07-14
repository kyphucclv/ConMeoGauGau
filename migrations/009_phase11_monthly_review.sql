-- Phase 11 monthly-review support.
-- Grain: one row is one explicit HR-authored version of a month’s action summary.
-- Forward verification: run the P11 monthly-review integration gate on a fresh database.
-- Rollback: restore the pre-migration backup; review conclusions are audit records.

ALTER TABLE courses ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE monthly_review_action_summary_versions (
    monthly_review_action_summary_version_id BIGSERIAL PRIMARY KEY,
    review_month DATE NOT NULL,
    version_number SMALLINT NOT NULL CHECK (version_number > 0),
    highlights TEXT NOT NULL DEFAULT '',
    risks TEXT NOT NULL DEFAULT '',
    next_month_priorities TEXT NOT NULL DEFAULT '',
    created_by_user_id BIGINT NOT NULL REFERENCES app_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (review_month, version_number),
    CHECK (review_month = date_trunc('month', review_month::timestamp)::date)
);

CREATE INDEX idx_monthly_review_action_summary_month
    ON monthly_review_action_summary_versions(review_month, version_number DESC);
