-- Phase 4 business-command support.
-- One row represents exactly one completion decision for one run enrollment.
CREATE TABLE course_completion_suggestions (
    completion_suggestion_id BIGSERIAL PRIMARY KEY,
    run_enrollment_id BIGINT NOT NULL UNIQUE REFERENCES run_enrollments(run_enrollment_id),
    suggested BOOLEAN NOT NULL,
    reason JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'suggested'
        CHECK (status IN ('suggested', 'confirmed', 'rejected')),
    confirmed_by_user_id BIGINT REFERENCES app_users(user_id),
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((status = 'suggested' AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL)
        OR (status IN ('confirmed', 'rejected') AND confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE INDEX idx_completion_suggestions_status
    ON course_completion_suggestions(status, suggested);
