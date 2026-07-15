-- Issue #1 session storage.
-- Grain: one row is one revocable authenticated browser session.
-- The raw bearer token exists only in the browser cookie; PostgreSQL stores
-- its SHA-256 digest. The CSRF secret is not a bearer credential and is
-- returned only after the bearer cookie has been validated.
-- Forward verification:
--   SELECT count(*) FROM app_sessions WHERE token_hash !~ '^[0-9a-f]{64}$';
-- must return zero, and duplicate token_hash inserts must fail.
-- Rollback: before real sessions exist, DROP TABLE app_sessions. After use,
-- restore the pre-020 backup rather than weakening or rewriting auth history.

CREATE TABLE app_sessions (
    app_session_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_users(user_id),
    token_hash CHAR(64) NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT,
    CONSTRAINT app_sessions_token_hash_format CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT app_sessions_expiry_after_creation CHECK (expires_at > created_at),
    CONSTRAINT app_sessions_revocation_pair CHECK (
        (revoked_at IS NULL AND revocation_reason IS NULL)
        OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)
    )
);

CREATE INDEX idx_app_sessions_user_active
    ON app_sessions(user_id, created_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX idx_app_sessions_expiry
    ON app_sessions(expires_at)
    WHERE revoked_at IS NULL;
