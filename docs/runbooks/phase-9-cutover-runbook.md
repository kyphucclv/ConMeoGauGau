# Phase 9 cutover runbook

Status: Production cutover completed and verified on 2026-07-13.

## Preconditions

- Workbook edit freeze is announced, or the final workbook checksum is accepted
  as the cutover source.
- Phase 8 review is approved.
- `python scripts\phase9_cutover_rehearsal.py` passes on this machine.
- Open quality issues are either resolved or explicitly accepted by the data
  owner through `docs/reviews/phase-10-quality-signoff.json`. The latest
  full Phase 9 rehearsal from the checksum-matched workbook has zero open
  issues.
- `python scripts\phase10_quality_signoff.py --validate-decisions` passes
  against the final candidate database and checksum.
- For Phase 11 rollout, `python scripts\phase11_operational_issue_snapshot.py`
  has been regenerated against the final candidate database. The Phase 9
  rehearsal also emits this snapshot. Then
  `python scripts\phase11_operational_issue_snapshot.py --validate-decisions`
  passes after owner decisions are entered.
- Production database backup owner, app owner, and issue owner are named.
- Rollback trigger is agreed before the first production mutation.

## Rollback trigger

Rollback if any of these happen during production cutover:

- backup cannot be restored to a disposable database;
- migrations fail or leave the database without all expected schema versions;
- staging row count or source checksum differs from the signed-off workbook;
- canonical ETL fails;
- critical source reconciliation is not accepted by the owner;
- app smoke test cannot reach login or canonical reporting views.

## Production cutover sequence

1. Record final workbook checksum:

   ```powershell
   python -c "from pathlib import Path; import hashlib; p=Path('okok_FIXED_v2.xlsx'); h=hashlib.sha256(p.read_bytes()).hexdigest(); print(h)"
   ```

2. Take final production backup:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" --format=custom --file backups\english_class_cutover_YYYYMMDD_HHMM.dump "postgresql://postgres@localhost:5432/english_class"
   ```

3. Restore the backup to a disposable database and inspect actual rows:

   ```powershell
   dropdb -U postgres -h localhost -p 5432 -w --if-exists --force english_class_restore_check
   createdb -U postgres -h localhost -p 5432 -w english_class_restore_check
   & "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --dbname "postgresql://postgres@localhost:5432/english_class_restore_check" backups\english_class_cutover_YYYYMMDD_HHMM.dump
   ```

   Required inspection:

   ```sql
   SELECT count(*) FROM employees;
   SELECT count(*) FROM schema_migrations;
   ```

4. Create restricted credentials and transfer canonical object ownership using
   operator-owned passwords:

   ```powershell
   psql "postgresql://postgres@localhost:5432/english_class" -v migration_user=english_class_migration -v migration_password="$env:MIGRATION_PASSWORD" -v app_user=english_class_app -v app_password="$env:APP_PASSWORD" -v readonly_user=english_class_readonly -v readonly_password="$env:READONLY_PASSWORD" -f database_roles.sql
   ```

5. Apply canonical migrations with the migration role:

   ```powershell
   python migrate.py "$env:MIGRATION_DATABASE_URL"
   ```

6. Stage final workbook and save profile:

   ```powershell
   python scripts/stage_workbook.py okok_FIXED_v2.xlsx --database-url "$env:MIGRATION_DATABASE_URL" --profile-output docs/reviews/final-workbook-profile.json
   ```

7. Run canonical ETL:

   ```powershell
   python scripts/canonical_etl_v3.py "$env:MIGRATION_DATABASE_URL"
   ```

8. Inspect reconciliation:

   ```sql
   SELECT version FROM schema_migrations ORDER BY version;
   SELECT status, count(*) FROM canonical_etl_batches GROUP BY status;
   SELECT outcome_type, count(*) FROM etl_source_row_outcomes GROUP BY outcome_type ORDER BY outcome_type;
   SELECT status, count(*) FROM data_quality_issues GROUP BY status ORDER BY status;
   SELECT count(*) FROM employees;
   SELECT count(*) FROM run_enrollments;
   SELECT count(*) FROM attendance;
   SELECT count(*) FROM v_cohort_course_run_dashboard;
   ```

9. Configure app secret:

   ```toml
   # .streamlit/secrets.toml
   [database]
   url = "postgresql://english_class_app:APP_PASSWORD@localhost:5432/english_class"
   ```

10. Smoke test:

    ```powershell
    python -m streamlit run streamlit_app.py
    ```

    Confirm the server is using `english_class_app`, then inspect login,
    Operations, Reports, Users, and Audit. Phase 8 UAT remains a disposable-DB
    precondition and is not a production smoke command.

11. Unlock setup only after sign-off:

    - remove `DRAFT_MIGRATIONS.lock`;
    - record sign-off in `docs/reviews/phase-9-cutover-rehearsal.md`;
    - update the final checksum and backup filename in the review;
    - retain the approved Phase 10 JSON and its issue snapshot SHA-256 as
      cutover evidence.

12. For Phase 11 rollout, generate and validate the operational issue snapshot:

    ```powershell
    python scripts\phase11_operational_issue_snapshot.py --database-url "$env:MIGRATION_DATABASE_URL"
    python scripts\phase11_operational_issue_snapshot.py --write-decision-template
    python scripts\phase11_operational_issue_snapshot.py --apply-decision-template
    python scripts\phase11_operational_issue_snapshot.py --database-url "$env:MIGRATION_DATABASE_URL" --validate-decisions
    ```

    If validation fails with pending high-severity issues, stop rollout until
    those issues are corrected or the owner signs the exact snapshot SHA-256 in
    `docs/reviews/phase-11-operational-issue-snapshot.json`.

## Restore command

To roll back to the final backup:

```powershell
dropdb -U postgres -h localhost -p 5432 -w english_class
createdb -U postgres -h localhost -p 5432 -w english_class
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --dbname "postgresql://postgres@localhost:5432/english_class" backups\english_class_cutover_YYYYMMDD_HHMM.dump
```

After restore, inspect representative rows and app behavior before reopening
the workflow to users.

## Ownership checklist

| Item | Owner | Status |
|---|---|---|
| Workbook freeze/checksum | Project owner | Complete: `f1d88362...5997` |
| Final backup file | Cutover operator | Complete: `english_class_canonical_20260713_154723.dump` |
| Restore validation | Cutover operator | Complete: `15 / 365 / 552 / 6281 / 0` in rehearsal |
| Open quality issue acceptance (`phase-10-quality-signoff.json`) | Project owner | Complete: approved, zero issues |
| Phase 11 owner decision gate | Project owner | Complete: `046c4fe3...79b6`, validation approved |
| Restricted app credentials | Cutover operator | Complete: migration/app/read-only roles |
| App smoke sign-off | Project owner / cutover operator | Complete: app role, zero errors |
| Rollback decision owner | Project owner | Complete: legacy database and dumps retained |
