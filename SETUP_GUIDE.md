# Setup guide (Windows)

> **Blocked during the v3 redesign.** `DRAFT_MIGRATIONS.lock` intentionally
> prevents setup. Follow `IMPLEMENTATION_PLAN.md`; do not use the commands in
> this guide until Phase 9 re-verifies and unlocks them.

This package is self-contained: PostgreSQL schema + data loader + the source
spreadsheet. Follow this on the new machine.

## What's in this package

| File | Purpose |
|---|---|
| `setup.ps1` | Automated setup script — run this first. |
| `schema.sql` | Table definitions (PK/FK/constraints). |
| `views.sql` | Report views (replace DASHBOARD/PROGRESS/ATT_COUNT/sheet2). |
| `admin_schema.sql` | App users + audit log tables for the admin app. |
| `migrations/`, `migrate.py` | Safe versioned database upgrades. |
| `quality_checks.sql` | Checks for unresolved source-data issues. |
| `backup.ps1` | Creates a PostgreSQL backup. |
| `etl.py` | Loads `okok_FIXED_v2.xlsx` into the database. |
| `okok_FIXED_v2.xlsx` | Source data. |
| `README.md` | Schema design notes — how each spreadsheet sheet maps to a table/view, and known data-quality gaps. |
| `SETUP_GUIDE.md` | This file. |

## Option A — Automated (recommended)

1. Copy this whole folder to the new machine.
2. Right-click inside the folder → "Open in Terminal" (or open PowerShell and `cd` into the folder).
3. Run:
   ```powershell
   .\setup.ps1
   ```
4. If PostgreSQL or Python weren't installed, the script installs them via
   `winget` and asks you to **open a new PowerShell window** (so PATH picks
   up the new installs) and run `.\setup.ps1` again.
5. When prompted, enter the password you want for the PostgreSQL `postgres`
   superuser (this sets it on first install, or must match your existing
   password if PostgreSQL is already on the machine).
6. Choose a separate password for the `english_class_app` database user.
   The app uses this restricted account instead of the `postgres` superuser.
7. At the end it stores the app connection in `.streamlit/secrets.toml` and
   runs a check query — you
   should see:
   ```
   total_students | active_students | inactive_students | waiting_for_class
   308            | 102             | 195                | 11
   ```
   If those numbers match, the migration is correct.

If `winget` isn't available on the target machine (older Windows), install
manually:
- PostgreSQL: https://www.postgresql.org/download/windows/
- Python: https://www.python.org/downloads/windows/ (check "Add to PATH" during install)

Then re-run `.\setup.ps1`.

## Option B — Manual steps

```powershell
# 1. Create the database (enter your postgres password when prompted)
psql -U postgres -c "CREATE DATABASE english_class"

# 2. Apply schema + views + admin tables
psql -U postgres -d english_class -f schema.sql
psql -U postgres -d english_class -f views.sql
psql -U postgres -d english_class -f admin_schema.sql

# 3. Install Python deps
python -m pip install -r requirements.txt

# 4. Load data
python etl.py okok_FIXED_v2.xlsx "postgresql://postgres:YOUR_PASSWORD@localhost:5432/english_class"

# 5. Apply the normalized architecture migrations
python migrate.py "postgresql://postgres:YOUR_PASSWORD@localhost:5432/english_class"

# 6. Verify
psql -U postgres -d english_class -c "SELECT * FROM v_dashboard_overview;"
```

## Run the dashboard app

After you have loaded the data, start the web UI with:

```powershell
python -m streamlit run app.py
```

Then open the local URL shown in the terminal. Automated setup stores the
restricted app connection in `.streamlit/secrets.toml`, so no connection
string needs to be pasted into the browser.

On first login, if no app users exist yet, the app will ask you to create the
initial admin account.

## Updating an existing database

Do not drop the database and do not re-run the one-time ETL. Run:

```powershell
.\backup.ps1
python migrate.py "postgresql://postgres:YOUR_PASSWORD@localhost:5432/english_class"
```

`migrate.py` records applied versions in `schema_migrations`, skips completed
versions, and stops if an already-applied migration file was modified.

## Troubleshooting

- **`psql: command not found` after installing** — you're still in the old
  PowerShell session; open a new window.
- **`password authentication failed`** — the password you typed doesn't
  match the one set when PostgreSQL was installed. On Windows, the
  installer sets the `postgres` user's password during setup; if you don't
  know it, reinstall PostgreSQL or reset it via `pgAdmin`.
- **`FATAL: role "postgres" does not exist`** — some installs create a
  different default superuser name; check what the installer used (shown at
  the end of the PostgreSQL installer, or open pgAdmin to see the server's
  default login).
- **etl.py FK/constraint errors** — means the source spreadsheet changed
  shape since this package was built; re-check `README.md`'s "Known
  data-quality gaps" section and adjust `etl.py` accordingly.
