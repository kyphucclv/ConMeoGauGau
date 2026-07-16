# Issue 14 Streamlit retirement evidence

Date: 2026-07-16
Status: **implementation verified — draft PR review pending**

## Owner decision and scope

The owner explicitly confirmed: withdraw HR/LAN rollout, keep local testing on
the designated machine, close Issue #13 as not planned, and retire Streamlit
without a live fallback. GitHub Issue #13 records that scope change.

No canonical table, row grain, field meaning, transaction owner, audit rule or
production business row changes in this task. One application row and one audit
event retain exactly the same meaning before and after frontend retirement.

## Preserved evidence

- Tag `streamlit-final-compatible-2026-07-16` points to merged commit
  `eae9ef18c1fe98dca7865a214cb995f795aa4f34`.
- Backup `english_class_20260716_151523.dump` is 2,576,160 bytes and has 463
  readable `pg_restore` TOC entries.
- A secondary backup copy exists under `C:\Backups\english_class`.
- `services/`, read models, reports, migrations, ETL, audit history and
  historical review documents are retained.

## Retirement review

- Streamlit runtime dependency, entrypoint, UI-only package, launchers,
  configuration templates and obsolete legacy wrappers are removed.
- Phase 6 keeps a frontend secret-exposure check against React source.
- Phase 7 keeps the complete service workflow and read-model contract.
- Phase 8 keeps business UAT and disposable backup/restore.
- Phase 9 keeps ETL idempotency, reconciliation and disposable restore.
- API pytest, React unit/build and Playwright journeys replace UI smoke coverage.

## Post-removal verification

```text
python -m compileall -q api scripts services tests auth.py db.py
  frontend_queries.py reporting.py session_store.py
passed

python scripts/phase6_security_check.py
passed: restricted role/DDL/RBAC checks and React secret-source scan

python scripts/phase7_frontend_workflow_check.py
passed: complete business workflow and retained read-model contract

.\scripts\run-all-gates.ps1 -TargetHost
97 Python tests
OpenAPI drift check
13 React tests
React production build
npm audit: 0 vulnerabilities
schema dictionary through 020_app_sessions
trusted target HTTPS/live/ready/role/connection-budget proof
6 Playwright journeys including axe accessibility
Phase 8 business UAT and backup/restore
Phase 9 ETL idempotency/reconciliation and backup/restore
Phase 10/11 owner-decision gates
all passed
```

Phase 9 reconciled 9,545 staged rows, 365 employees, 552 run enrollments,
6,281 attendance rows, zero open quality issues and 20 schema migrations. Its
restored database retained 365 employees and all 20 migrations.

The elevated post-removal host verifier restarted `EnglishClassReact` and
`EnglishClassCaddy`; both returned Running/Automatic and HTTPS readiness
recovered. FastAPI listened only on `127.0.0.1:8000`, the backend-port block
remained active, logs contained 310 structured access events with no forbidden
secret-shaped value, and the forced SYSTEM backup created
`english_class_20260716_153409.dump` (2,576,160 bytes) with result zero.

One deliberately parallel validation run competed with React build/tests and
measured read p95 at 1.043 seconds against the 1-second target. The isolated
load rerun passed at 978.58 ms, and the final sequential full gate passed all 97
tests. This contention sensitivity is retained as a local-only capacity risk,
not hidden or waived as production evidence.

## Final review

- [x] Full tracked/untracked diff reviewed after generation
- [x] No Streamlit import, dependency or active launcher remains
- [x] No schema, migration or production business-row change
- [x] No service, read model, report, ETL or audit history removed
- [x] Invalid authorization/DDL paths remain covered by Phase 6 and pytest
- [x] Historical source and recovery path retained by immutable Git tag
- [x] Fresh production backup and disposable restore evidence retained
- [x] Documentation states the local-only scope and lack of active fallback

## Residual risk

The owner accepted no active Streamlit fallback and no HR/LAN production claim.
The measured latency sensitivity reinforces that limitation. Future multi-user
deployment requires a new production-readiness decision.
