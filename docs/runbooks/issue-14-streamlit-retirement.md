# Issue 14 Streamlit retirement and recovery record

Status: **retirement approved for local-only testing on 2026-07-16**

The owner withdrew the HR/LAN production rollout, accepted the designated
machine as the final test scope, and explicitly approved removal of the live
Streamlit adapter without a stabilization fallback. React/FastAPI is the only
active frontend. This decision changes no database schema, business rule,
transaction boundary or audit attribution.

## Retained recovery artifacts

- Final compatible source tag: `streamlit-final-compatible-2026-07-16`
- Tagged commit: `eae9ef18c1fe98dca7865a214cb995f795aa4f34`
- Final backup: `english_class_20260716_151523.dump`
- Backup size: 2,576,160 bytes
- Archive validation: `pg_restore -l` reported 463 TOC entries
- Secondary backup: `C:\Backups\english_class\english_class_20260716_151523.dump`

Backups remain outside Git. The tag contains the final Streamlit dependency,
launcher, configuration template, UI adapter and smoke paths.

## Removed live surfaces

- `streamlit_app.py` and `frontend_workflows/`
- `run_app.cmd`, `run_app.ps1` and `.streamlit/` templates
- Streamlit from `requirements.txt`
- legacy Streamlit wrapper/setup launch paths
- Streamlit-only Phase 6-9 source and smoke assertions

Reusable `services/`, `frontend_queries.py`, `reporting.py`, migrations, audit
history, ETL and historical review evidence remain.

## Replacement verification map

| Retired check | Active replacement |
|---|---|
| Sign-in, session shell and sign-out smoke | API auth/session pytest, React unit tests and Playwright journeys |
| Learner and operational workspace smoke | Workflow API integration tests, React feature tests and Playwright journeys |
| Static Streamlit UI/service-boundary scan | React production build, frontend secret scan, API/service tests and retained read-model contract |
| Phase 8 Streamlit `AppTest` | Phase 8 business UAT plus full API/React/Playwright gates |
| Phase 9 Streamlit `AppTest` | Phase 9 ETL/reconciliation/backup-restore plus live React/FastAPI host check |

## Active launch path

The Windows services remain `EnglishClassReact` and `EnglishClassCaddy`.
FastAPI binds only to `127.0.0.1:8000`; Caddy serves the local HTTPS origin.
Manual preflight remains:

```powershell
npm --prefix web run build
.\run_react_app.ps1 -CheckOnly
python scripts\issue13_host_check.py
```

## Source recovery procedure

The retired UI is not a live fallback. If source-level inspection or an
owner-approved emergency recovery is required, materialize the tag separately:

```powershell
git worktree add ..\ConMeoGauGau-streamlit streamlit-final-compatible-2026-07-16
Set-Location ..\ConMeoGauGau-streamlit
python -m pip install -r requirements.txt
.\run_app.ps1 -CheckOnly
```

Use the existing restricted `APP_DATABASE_URL`. Do not dual-write, reverse
migrations or restore the database merely to switch frontend code. A database
restore is reserved for a separately proven database incident.

## Residual risk

There is no active UI fallback and no HR-workstation production proof. The
application is approved only for testing on the designated machine. Expanding
to LAN/HR use requires a new issue with DNS, client trust, named UAT, capacity,
stabilization and rollback acceptance.
