# Setup guide (Windows, canonical v3)

Canonical v3 passed the disposable rehearsal and production cutover on
2026-07-13. The production database uses the restricted canonical setup below.

This package is self-contained: PostgreSQL schema + data loader + the source
spreadsheet. Follow this on the new machine.

## What's in this package

| File | Purpose |
|---|---|
| `setup.ps1` | Legacy helper; do not use for the canonical application. |
| `migrations/`, `migrate.py` | Canonical v3 schema and reporting migrations. |
| `scripts/stage_workbook.py` | Raw workbook staging and profiling. |
| `scripts/canonical_etl_v3.py` | Canonical v3 ETL. |
| `scripts/phase9_cutover_rehearsal.py` | Disposable cutover rehearsal. |
| `scripts/phase11_operational_issue_snapshot.py` | Phase 11 operational issue snapshot and owner-decision gate. |
| `database_roles.sql` | Restricted migration/app/read-only DB roles. |
| `streamlit_app.py` | Canonical Streamlit app entrypoint. |
| `okok_FIXED_v2.xlsx` | Source data. |
| `README.md` | Canonical path and archived legacy context. |
| `SETUP_GUIDE.md` | This file. |

## Option A — Cutover rehearsal

Run the verified rehearsal before production cutover:

```powershell
python scripts\phase9_cutover_rehearsal.py
```

This creates disposable databases, applies migrations, stages the workbook,
runs canonical ETL, checks idempotency, creates restricted roles, smoke-tests
the app, and proves backup/restore.

If `winget` isn't available on the target machine (older Windows), install
manually:
- PostgreSQL: https://www.postgresql.org/download/windows/
- Python: https://www.python.org/downloads/windows/ (check "Add to PATH" during install)

Then re-run the rehearsal command.

## Option B — Manual canonical setup

```powershell
# 1. Create the database.
createdb -U postgres -h localhost -p 5432 -w english_class

# 2. Create restricted roles and transfer schema ownership. Supply passwords
# through operator-owned environment variables.
psql "postgresql://postgres@localhost:5432/english_class" -v migration_user=english_class_migration -v migration_password="$env:MIGRATION_PASSWORD" -v app_user=english_class_app -v app_password="$env:APP_PASSWORD" -v readonly_user=english_class_readonly -v readonly_password="$env:READONLY_PASSWORD" -f database_roles.sql

# 3. Apply canonical migrations with the migration role.
python migrate.py "$env:MIGRATION_DATABASE_URL"

# 4. Install Python deps
python -m pip install -r requirements.txt

# 5. Stage the workbook.
python scripts/stage_workbook.py okok_FIXED_v2.xlsx --database-url "$env:MIGRATION_DATABASE_URL" --profile-output docs/reviews/final-workbook-profile.json

# 6. Run canonical ETL.
python scripts/canonical_etl_v3.py "$env:MIGRATION_DATABASE_URL"

# 7. Verify on disposable databases.
python scripts/phase8_automated_uat.py
python scripts/phase9_cutover_rehearsal.py
python scripts/phase11_operational_issue_snapshot.py
```

Generate the smaller owner decision template, apply it after the owner fills it
in, then validate the Phase 11 rollout gate:

```powershell
python scripts/phase11_operational_issue_snapshot.py --write-decision-template
python scripts/phase11_operational_issue_snapshot.py --apply-decision-template
python scripts/phase11_operational_issue_snapshot.py --validate-decisions
```

This command exits zero only when high-severity operational issues are resolved
or covered by owner-approved legacy decisions for the exact current snapshot.

## Run the dashboard app

After you have loaded the data, start the web UI with:

```powershell
python -m streamlit run streamlit_app.py
```

Then open the local URL shown in the terminal. Store the restricted app
connection in `.streamlit/secrets.toml` or set `DATABASE_URL`; no connection
string is pasted into the browser.

On first login, if no app users exist yet, the app will ask you to create the
initial admin account.

## Updating an existing database

Do not drop the database and do not re-run canonical ETL for a completed source
checksum unless the cutover runbook says to force a new load. Back up first,
then run:

```powershell
.\backup.ps1
python migrate.py "$env:MIGRATION_DATABASE_URL"
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
