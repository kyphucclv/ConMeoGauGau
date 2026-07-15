"""Database-backed, revocable browser sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from auth import AppUser
from db import pooled_connection


@dataclass(frozen=True)
class NewSession:
    token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedSession:
    session_id: int
    user: AppUser
    csrf_token: str


class SessionStore:
    def __init__(self, pool, *, absolute_lifetime=timedelta(hours=12), idle_lifetime=timedelta(hours=1), max_sessions=5):
        self.pool = pool
        self.absolute_lifetime = absolute_lifetime
        self.idle_lifetime = idle_lifetime
        self.max_sessions = max_sessions

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, user_id: int) -> NewSession:
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + self.absolute_lifetime
        with pooled_connection(self.pool) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM app_users WHERE user_id = %s AND is_active FOR UPDATE", (user_id,))
                    if not cur.fetchone():
                        raise ValueError("active user is required")
                    cur.execute(
                        """INSERT INTO app_sessions(user_id, token_hash, csrf_token, expires_at)
                           VALUES (%s, %s, %s, %s)""",
                        (user_id, self._digest(token), csrf_token, expires_at),
                    )
                    cur.execute(
                        """UPDATE app_sessions SET revoked_at = NOW(), revocation_reason = 'session_limit'
                           WHERE app_session_id IN (
                             SELECT app_session_id FROM app_sessions
                             WHERE user_id = %s AND revoked_at IS NULL
                             ORDER BY created_at DESC, app_session_id DESC
                             OFFSET %s
                           )""",
                        (user_id, self.max_sessions),
                    )
        return NewSession(token, csrf_token, expires_at)

    def authenticate(self, token: str | None) -> AuthenticatedSession | None:
        if not token:
            return None
        with pooled_connection(self.pool) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT s.app_session_id, s.csrf_token, s.expires_at, s.last_seen_at,
                                  s.revoked_at, u.user_id, u.username, u.full_name, u.role, u.is_active
                           FROM app_sessions s JOIN app_users u ON u.user_id = s.user_id
                           WHERE s.token_hash = %s FOR UPDATE OF s""",
                        (self._digest(token),),
                    )
                    row = cur.fetchone()
                    if not row or row[4] is not None:
                        return None
                    now = datetime.now(timezone.utc)
                    if not row[9] or row[2] <= now or row[3] <= now - self.idle_lifetime:
                        cur.execute(
                            "UPDATE app_sessions SET revoked_at = NOW(), revocation_reason = %s WHERE app_session_id = %s",
                            ("user_inactive" if not row[9] else "expired", row[0]),
                        )
                        return None
                    if row[3] <= now - timedelta(minutes=5):
                        cur.execute("UPDATE app_sessions SET last_seen_at = NOW() WHERE app_session_id = %s", (row[0],))
                    return AuthenticatedSession(row[0], AppUser(row[5], row[6], row[7], row[8]), row[1])

    def revoke(self, token: str | None, reason: str = "logout") -> None:
        if not token:
            return
        with pooled_connection(self.pool) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE app_sessions SET revoked_at = NOW(), revocation_reason = %s
                           WHERE token_hash = %s AND revoked_at IS NULL""",
                        (reason, self._digest(token)),
                    )

    @staticmethod
    def csrf_matches(session: AuthenticatedSession, supplied: str | None) -> bool:
        return bool(supplied) and hmac.compare_digest(session.csrf_token, supplied)
