"""Apply versioned PostgreSQL migrations exactly once."""

import hashlib
import os
import sys
from pathlib import Path

import psycopg2


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def apply_migrations(connection_uri: str) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    with psycopg2.connect(connection_uri) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("english_class_migrations",))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("SELECT version, checksum FROM schema_migrations")
            applied = dict(cur.fetchall())

            for path in migration_files:
                version = path.stem
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if version in applied:
                    if applied[version] != checksum:
                        raise RuntimeError(f"Applied migration was modified: {path.name}")
                    print(f"Already applied: {path.name}")
                    continue

                print(f"Applying: {path.name}")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )

    print("Database migrations are up to date.")


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATABASE_URL")
    if not uri:
        raise SystemExit("Usage: python migrate.py <postgres-connection-uri>")
    apply_migrations(uri)

