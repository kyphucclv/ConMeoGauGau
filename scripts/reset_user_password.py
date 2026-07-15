"""Securely reset one active application user's password."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import reset_user_password
from db import create_pool
from scripts.bootstrap_admin import configured_database_url
from services import CommandError


def load_windows_user_database_url() -> None:
    if os.getenv("APP_DATABASE_URL") or sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            os.environ["APP_DATABASE_URL"] = str(winreg.QueryValueEx(key, "APP_DATABASE_URL")[0])
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    load_windows_user_database_url()
    database_url = configured_database_url(args.database_url)
    if not database_url:
        raise SystemExit("Database URL is not configured")
    password = getpass.getpass("New password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    pool = create_pool(database_url, application_name="english_class_password_reset")
    try:
        reset_user_password(pool, args.username, password)
    except CommandError as error:
        raise SystemExit(error.message) from error
    finally:
        pool.closeall()
    print(f"Password reset completed for {args.username}. Existing sessions were revoked.")


if __name__ == "__main__":
    main()
