"""Create the first named application administrator once."""

from __future__ import annotations

import argparse
import getpass
import os

from auth import bootstrap_first_admin
from db import create_pool
from services import CommandError


def configured_database_url(explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url
    env_url = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    args = parser.parse_args()

    database_url = configured_database_url(args.database_url)
    if not database_url:
        raise SystemExit("Database URL is not configured")
    password = getpass.getpass("New admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    pool = create_pool(database_url, application_name="english_class_admin_bootstrap")
    try:
        user_id = bootstrap_first_admin(pool, args.username, args.full_name, password)
    except CommandError as error:
        raise SystemExit(error.message) from error
    finally:
        pool.closeall()
    print(f"Named admin created with user ID {user_id}.")


if __name__ == "__main__":
    main()
