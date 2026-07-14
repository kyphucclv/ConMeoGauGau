"""Authentication helpers and user administration commands."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

import psycopg2.errors

from db import execute_one, fetch_all, fetch_one, pooled_connection
from services import CommandError


@dataclass(frozen=True)
class AppUser:
    user_id: int
    username: str
    full_name: str
    role: str


def hash_password(password: str) -> str:
    iterations = 150000
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def authenticate(pool, username: str, password: str) -> AppUser | None:
    row = fetch_one(
        pool,
        """
        SELECT user_id, username, full_name, role, password_hash, is_active
        FROM app_users
        WHERE username = %s
        """,
        (username.strip(),),
    )
    if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
        return None
    return AppUser(row["user_id"], row["username"], row["full_name"], row["role"])


def active_user_by_id(pool, user_id: int) -> AppUser | None:
    row = fetch_one(
        pool,
        """
        SELECT user_id, username, full_name, role
        FROM app_users
        WHERE user_id = %s AND is_active
        """,
        (user_id,),
    )
    if not row:
        return None
    return AppUser(row["user_id"], row["username"], row["full_name"], row["role"])


def list_users(pool):
    return fetch_all(
        pool,
        "SELECT username, full_name, role, is_active, created_at FROM app_users ORDER BY username",
    )


class UserAdminService:
    def __init__(self, pool, actor: AppUser):
        self.pool = pool
        self.actor = actor

    def _require_admin(self) -> None:
        if self.actor.role != "admin":
            raise CommandError("forbidden", "admin role is required")

    def create_user(self, username: str, full_name: str, password: str, role: str) -> int:
        self._require_admin()
        if role not in {"admin", "editor", "viewer"}:
            raise CommandError("invalid_input", "role is invalid")
        if not username.strip() or not full_name.strip() or not password:
            raise CommandError("invalid_input", "username, full_name, and password are required")
        try:
            with pooled_connection(self.pool) as conn:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO app_users(username, password_hash, full_name, role)
                            VALUES (%s, %s, %s, %s)
                            RETURNING user_id
                            """,
                            (username.strip(), hash_password(password), full_name.strip(), role),
                        )
                        user_id = cur.fetchone()[0]
                        self._audit_in_tx(cur, "app_user.create", username.strip(), {"role": role})
        except psycopg2.errors.UniqueViolation as exc:
            raise CommandError("duplicate", "username already exists") from exc
        return user_id

    def deactivate_user(self, username: str) -> None:
        self._require_admin()
        if username == self.actor.username:
            raise CommandError("invalid_state", "an admin cannot deactivate their own account")
        with pooled_connection(self.pool) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE app_users
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE username = %s AND is_active
                        RETURNING user_id
                        """,
                        (username,),
                    )
                    if not cur.fetchone():
                        raise CommandError("not_found", "active user not found")
                    self._audit_in_tx(cur, "app_user.deactivate", username, {})

    def _audit_in_tx(self, cur, action: str, username: str, details: dict) -> None:
        cur.execute(
            """
            INSERT INTO audit_events(actor_user_id, actor_username, action, entity_type, entity_key, details)
            VALUES (%s, %s, %s, 'app_user', %s, %s::jsonb)
            """,
            (self.actor.user_id, self.actor.username, action, username, __import__("json").dumps(details)),
        )


def bootstrap_first_admin(pool, username: str, full_name: str, password: str) -> int:
    user_count = fetch_one(pool, "SELECT count(*) AS total FROM app_users")["total"]
    if user_count:
        raise CommandError("invalid_state", "bootstrap is only allowed before users exist")
    row = execute_one(
        pool,
        """
        INSERT INTO app_users(username, password_hash, full_name, role)
        VALUES (%s, %s, %s, 'admin')
        RETURNING user_id
        """,
        (username.strip(), hash_password(password), full_name.strip()),
    )
    execute_one(
        pool,
        """
        INSERT INTO audit_events(actor_user_id, actor_username, action, entity_type, entity_key, details)
        VALUES (%s, %s, 'app_user.bootstrap_admin', 'app_user', %s, '{}'::jsonb)
        RETURNING audit_event_id
        """,
        (row["user_id"], username.strip(), username.strip()),
    )
    return row["user_id"]
