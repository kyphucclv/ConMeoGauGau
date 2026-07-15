# Long-Term Migration Plan: Replace Streamlit With FastAPI + React

Status: **Revised architecture plan; implementation requires Phase 0 approval**

Phase 0 companion artifacts:

- [Baseline](phase-0-baseline.md)
- [Deployment and session decisions](deployment-session-decisions.md)
- [HTTP contract v1 draft](http-contract-v1-draft.md)
- [Workflow parity matrix](workflow-parity-matrix.md)
- [Published issue breakdown](fastapi-react-issues.md)

## 1. Objective

Replace the Streamlit presentation layer with a maintainable internal web
application while preserving the strongest parts of the current system:

- PostgreSQL canonical v3 remains the durable source of truth.
- Existing migrations, database constraints, reporting views, audit history,
  and business invariants remain authoritative.
- `services.BusinessService` remains the transaction and authorization seam for
  business commands.
- `frontend_queries.py` and `reporting.py` are reused initially, then deepened
  into endpoint-oriented read modules where pagination or narrower contracts are
  required.
- Streamlit remains available during migration, but it never becomes a second
  implementation of business rules.

The migration is successful only when the React application reaches verified
workflow parity, production operation is stable, and rollback to Streamlit has
been rehearsed without reversing database writes.

## 2. Default Decisions

- Frontend: **React + Vite + TypeScript**
- Backend: **FastAPI with synchronous handlers for existing psycopg2 code**
- UI library: **Mantine + TanStack Table**
- Server-state management: **TanStack Query**
- Browser automation: **Playwright**
- Deployment: **Local/LAN internal web application over HTTPS**
- Production topology: **same origin for React and `/api`**
- Migration style: **incremental vertical slices, side-by-side with Streamlit**
- Authentication: **opaque, server-side sessions in PostgreSQL**
- HTTP contract source: **FastAPI OpenAPI document with generated TypeScript
  types/client**

React + Vite is preferred over Next.js because this internal operations app does
not need SSR or SEO. An async database rewrite is explicitly out of scope for
the migration.

## 3. Goals And Non-Goals

### Goals

- Improve navigation, form interaction, table usability, and perceived latency.
- Support safe multi-user LAN access.
- Expose a stable HTTP interface around existing application use cases.
- Preserve transaction boundaries, audit attribution, RBAC, historical meaning,
  and reporting semantics.
- Migrate one complete workflow at a time with measurable parity.
- Make deployment, health checking, logging, and rollback explicit.

### Non-goals

- Redesign the canonical database.
- Rewrite business rules in React or FastAPI routes.
- Convert psycopg2 and all services to async.
- Introduce microservices, event sourcing, GraphQL, or a second data store.
- Add unrelated product features during parity migration.
- Run the Vite development server in production.
- Remove Streamlit before acceptance and rollback criteria are satisfied.

## 4. Target Architecture

### Application shape

```text
Browser
  -> HTTPS internal origin
    -> React static application
    -> /api/* -> FastAPI HTTP adapter
                  -> endpoint-oriented read modules
                  -> existing services.BusinessService
                    -> PostgreSQL canonical v3
```

During migration:

```text
Streamlit adapter ----------------------+
                                        |
React -> FastAPI adapter ---------------+-> shared Python services/read models
                                             -> one canonical PostgreSQL database
```

Rules:

1. PostgreSQL is the only committed source of truth.
2. React owns draft presentation state only.
3. Every confirmed HR business event calls exactly one atomic service command.
4. FastAPI routes validate transport data and translate results; they do not own
   business rules or SQL.
5. Reads may use dedicated read modules, but user-provided values remain
   parameterized and responses expose only authorized fields.
6. Streamlit and React never dual-write or synchronize through copied tables.
7. Schema changes remain backward-compatible with both frontends until
   Streamlit retirement.

## 5. Production And Development Topology

### Development only

```text
Streamlit: http://127.0.0.1:8501
FastAPI:   http://127.0.0.1:8000
Vite:      http://127.0.0.1:5173
```

Development CORS must use an exact allow-list, allow credentials only for the
known Vite origin, and never use `*` with credentialed requests.

### Production/LAN

```text
https://english-class.internal/
  /       -> versioned React static build
  /api/*  -> FastAPI
```

Production requirements:

- One HTTPS origin terminates TLS and routes `/api/*` to FastAPI.
- The Vite development server is not installed or exposed.
- CORS is disabled unless a separately approved origin requires it.
- The application binds only to the intended interface and is restricted by the
  host firewall.
- Database URLs and session secrets come from protected environment/configuration,
  never from the repository or frontend build.
- Startup, restart, log location, backup, restore, and certificate renewal are
  documented in a production runbook.
- Worker count and per-worker connection-pool size are chosen together so their
  maximum does not exceed the PostgreSQL connection budget.

Initial production should use the smallest worker count that meets the measured
LAN concurrency target. Existing synchronous psycopg2 calls must run in normal
FastAPI `def` handlers or an explicitly managed thread pool, never directly in
an async event-loop handler.

## 6. Backend Module Layout

Add an `api/` package without moving existing domain code during the foundation
phase:

```text
api/
  main.py                 app factory, middleware, lifecycle, router registration
  config.py               validated environment configuration
  deps.py                 pool, authenticated session, actor, command dependency
  errors.py               stable error envelope and exception mapping
  security.py             cookie, CSRF, session creation/revocation
  routers/
    auth.py
    dashboard.py
    learners.py
    attendance.py
    evaluations.py
    monthly_review.py
    follow_ups.py
    classes_schedule.py
    reports.py
    audit.py
  schemas/
    common.py
    auth.py
    learners.py
    attendance.py
    evaluations.py
    monthly_review.py
    classes_schedule.py
```

Avoid one growing `schemas.py` or generic repository layer. Schemas live near
their workflow contract, while `BusinessService` remains the public interface
for commands.

### Connection and transaction ownership

- The application creates one bounded pool during FastAPI startup and closes it
  during shutdown.
- Read dependencies borrow and return connections safely.
- A write dependency borrows one connection and constructs
  `BusinessService(connection, actor.user_id)`.
- The service command owns its transaction, authorization recheck, audit event,
  and rollback behavior.
- No route manually chains multiple committing commands for one HR event.
- Connections are always returned on success, validation error, command error,
  disconnect, or unexpected exception.

## 7. Authentication, Sessions, And Browser Security

### Session model

Add a small infrastructure migration for an `app_sessions` table. This is not a
domain-model change.

One row represents one revocable authenticated browser session and contains at
least:

- a cryptographically random token hash;
- `user_id`;
- creation, absolute expiry, last-seen, and revoked timestamps;
- optional minimal operational metadata if approved.

The raw token is stored only in a cookie. The database stores its hash.

Cookie requirements:

- `HttpOnly`;
- `Secure` in production;
- `SameSite=Lax` or stricter unless a documented integration requires otherwise;
- narrow path/domain;
- explicit lifetime.

Authentication flow:

```text
POST /api/auth/login
  -> rate-limit attempt
  -> authenticate with existing auth.authenticate
  -> rotate/create opaque server-side session
  -> return safe current-user metadata

Each protected request
  -> hash cookie token
  -> load non-expired, non-revoked session
  -> revalidate active app_users row
  -> construct AppUser actor

POST /api/auth/logout
  -> revoke session server-side
  -> expire cookie
```

Additional requirements:

- Mutating requests require CSRF protection in addition to SameSite cookies.
- Login is throttled without revealing whether a username exists.
- Session identifiers rotate after login and privilege-sensitive changes.
- Deactivated users immediately fail the next protected request.
- Bootstrap remains an explicit operator command and never runs at app startup.
- React never submits `actor_user_id` or role as trusted command input.
- Authorization remains enforced inside service commands as well as at route/UI
  level.
- Raw password hashes, session tokens, connection strings, SQL errors, and
  unauthorized audit details are never returned or logged.

## 8. HTTP Contract

### Common conventions

- Base path: `/api`.
- JSON fields use stable snake_case names for v1.
- Dates use `YYYY-MM-DD`.
- Instants use ISO 8601 with timezone; the server stores UTC and the UI displays
  the configured business timezone.
- Decimal values are serialized without binary floating-point ambiguity.
- List endpoints define filters, stable sort, page/page-size, and maximum size.
- Mutations return a typed receipt plus the minimum updated representation the
  caller needs.
- OpenAPI is the source for generated TypeScript types/client. CI fails when the
  generated contract is stale.
- Report keys are selected from the server registry; no client value becomes a
  SQL fragment.

### Error envelope

```json
{
  "code": "invalid_input",
  "message": "Human-safe message",
  "field_errors": {},
  "request_id": "opaque-correlation-id"
}
```

Mapping:

| Condition | HTTP status |
|---|---:|
| Missing/invalid session | 401 |
| Insufficient role | 403 |
| Missing authorized resource | 404 |
| Request/schema validation | 422 |
| Duplicate, stale state, capacity or lifecycle conflict | 409 |
| Unexpected server/database failure | 500 |

FastAPI validation errors are normalized to the same envelope. Unexpected
failures are logged with their request ID, while the browser receives only a
generic message.

### Health endpoints

```text
GET /api/health/live   process is running; no database query
GET /api/health/ready  restricted DB reachable and expected schema version valid
```

Health responses reveal no connection string, SQL, table contents, user data,
or internal exception text.

### Initial endpoint catalogue

```text
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout

GET  /api/dashboard

GET  /api/learners?q=&status=&page=&page_size=&sort=
GET  /api/learners/{employee_id}
GET  /api/learners/start-options
PATCH /api/learners/{employee_id}/profile
POST /api/learners/start
POST /api/run-enrollments/{run_enrollment_id}/transfer

GET  /api/attendance/course-runs
GET  /api/course-runs/{course_run_id}/session-units
GET  /api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster
PUT  /api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster
POST /api/attendance/{attendance_id}/makeup-credit

GET  /api/evaluations/pending
GET  /api/run-enrollments/{run_enrollment_id}/final-result
POST /api/run-enrollments/{run_enrollment_id}/final-result
POST /api/run-enrollments/{run_enrollment_id}/exam-eligibility-override
POST /api/run-enrollments/{run_enrollment_id}/completion-confirmation

GET  /api/monthly-review?month=YYYY-MM
POST /api/monthly-review/action-summary
GET  /api/monthly-review/export?month=YYYY-MM

GET  /api/follow-ups?severity=&workflow=&page=&page_size=
POST /api/follow-ups/{issue_id}/resolve

GET  /api/classes?page=&page_size=
GET  /api/classes/setup-options
POST /api/classes
GET  /api/schedule?course_run_id=&from=&to=
POST /api/schedule/meetings
PATCH /api/schedule/meetings/{meeting_id}
POST /api/schedule/meetings/{meeting_id}/cancellation

GET  /api/reports
GET  /api/reports/{report_key}?page=&page_size=
GET  /api/audit?page=&page_size=&actor=&action=&from=&to=
```

`session_unit_id` is required for attendance because one meeting may contain
multiple credited units. Evaluation, override, completion, and learner transfer
use `run_enrollment_id` because that is the aggregate selected and locked by the
existing atomic commands.

Broad `reference-data?scope=...` responses are avoided. Each workflow exposes a
narrow options/read endpoint containing only the labels, identifiers, and
derived context that workflow needs.

## 9. Concurrency And Cache Contract

TanStack Query improves responsiveness but never decides correctness.

- Use short, workflow-specific stale times.
- Refetch on browser focus and after authentication changes.
- Invalidate only affected query keys after a successful React mutation.
- During side-by-side operation, assume Streamlit can change data outside the
  React cache.
- Refetch authoritative context immediately before displaying final confirmation
  for transfers, capacity overrides, schedule corrections, and similar actions.
- Every service command reloads and locks the business state it validates.
- Stale proposals, changed rosters, duplicate submissions, and lifecycle races
  return `409` rather than silently overwriting newer state.
- Full-roster save includes every applicable enrollment exactly once and remains
  one transaction.
- Add version/updated-at preconditions only where existing locks and invariant
  checks cannot distinguish a stale edit; do not add generic optimistic locking
  without a demonstrated need.

## 10. Frontend Application

Add a `web/` Vite React application:

```text
web/
  src/
    app/                  router, providers, authenticated shell
    api/                  generated client and query-key helpers
    features/             workflow-oriented UI modules
      auth/
      dashboard/
      learners/
      attendance/
      evaluations/
      monthly-review/
      follow-ups/
      classes-schedule/
      reports/
      audit/
    shared/               truly cross-workflow presentation modules only
```

Navigation:

```text
Work
  Home
  Learners
  Attendance
  Final results

Review
  Monthly review
  Follow-ups
  Reports

Admin
  Classes and schedule
  Audit
```

User-management UI is not part of parity because the current Streamlit app does
not expose it. It remains an operator workflow during migration and may be added
later as a separately accepted feature.

Frontend rules:

- Protected routes wait for `/api/auth/me` before rendering sensitive data.
- Draft form state stays local; successful save responses are followed by
  targeted invalidation/refetch.
- Forms prevent accidental double submit but the backend still enforces
  idempotency/invariants.
- Risky actions show destination, calculated values, consequences, and required
  reasons before confirmation.
- UI uses HR language, not storage identifiers or internal entity terminology.
- Loading, empty, forbidden, validation, conflict, unexpected-error, and
  reconnect states are designed explicitly.
- Tables support keyboard operation, accessible labels, stable focus, and
  server-side pagination once the agreed client-side threshold is exceeded.
- Export endpoints return correct content type, safe filename, and streamed
  bytes without caching sensitive output publicly.

## 11. Migration Strategy

Use tracer-bullet vertical slices. A slice contains its HTTP contract, backend
adapter, React UI, automated tests, documentation, and UAT evidence.

The first slice is:

```text
Login -> Home dashboard -> Learner directory read-only -> Learner detail read-only
```

Then migrate commands in this order:

1. Learner profile/start/transfer.
2. Attendance roster and make-up.
3. Final results, correction, eligibility override, and completion.
4. Monthly review and export.
5. Follow-ups.
6. Class setup and schedule.
7. Reports and audit.

For each workflow, a parity matrix records:

- existing Streamlit entry point;
- corresponding endpoint(s) and React route;
- roles and field visibility;
- read filters and sort semantics;
- command and transaction invoked;
- expected audit action;
- empty/error/conflict cases;
- test evidence;
- HR owner acceptance;
- which frontend currently owns the production workflow.

Only one frontend is canonical for a migrated workflow at a time. The fallback
may remain reachable, but users are directed to the canonical path.

## 12. Implementation Phases

### Phase 0: Decision, Contract, And Baseline

Deliver:

- Record business reasons for migration and measurable targets for navigation,
  common task completion, concurrency, and deployment reliability.
- Inventory every Streamlit workflow in a parity matrix.
- Freeze entity/grain terminology from `TARGET_ARCHITECTURE.md` and
  `DATA_DICTIONARY.md`.
- Approve endpoint identifiers, error mapping, session/CSRF model, production
  topology, timezone contract, and connection budget.
- Capture baseline service, Streamlit smoke, reporting, and phase-gate results.
- Define the client-side table threshold and expected LAN concurrency.

Acceptance:

- No endpoint contract confuses meeting, session unit, employee, evaluation, or
  run enrollment identity.
- Security and deployment decisions have an owner and testable acceptance
  criteria.
- Every current workflow appears in the parity matrix.
- Rollout success and rollback triggers are measurable.

### Phase 1: FastAPI And Security Foundation

Deliver:

- Add production and development dependencies with bounded compatible versions.
- Add FastAPI app factory, validated configuration, pool lifecycle, request IDs,
  structured error handling, and health endpoints.
- Add the `app_sessions` migration with verification and restore/rollback notes.
- Implement login, current-user revalidation, logout/revocation, CSRF, cookie
  configuration, session expiry, and login throttling.
- Add OpenAPI generation and TypeScript contract generation/checking.
- Add tests for connection cleanup and generic handling of unexpected SQL errors.

Acceptance:

- Live and readiness checks behave independently.
- Login returns safe user metadata and rotates the session token.
- Refresh preserves a valid login.
- Logout invalidates the session server-side.
- Inactive users cannot continue using an existing session.
- Missing CSRF fails every protected mutation.
- Viewer/editor/admin behavior is verified on representative endpoints.
- No endpoint uses superuser credentials or exposes SQL/security internals.
- Streamlit and all existing verification gates still pass unchanged.

### Phase 2: Read-Only React Slice

Implementation status (2026-07-15): Issue #2 delivers the HR home and learner
read journey. React is canonical for these read-only surfaces; Streamlit remains
canonical for learner commands and reports until their later tracer slices.
Viewer report access therefore remains on Streamlit during side-by-side
operation and is not silently expanded into the HR workspace.

Deliver:

- Create the Vite React app and generated HTTP client.
- Add authenticated shell, navigation, protected routes, and session-expired flow.
- Implement dashboard, learner list, and learner detail.
- Add loading, empty, forbidden, server-error, and reconnect states.
- Produce a deployable static build served through the production-style same
  origin in a test environment.

Acceptance:

- HR can sign in, refresh, navigate, and sign out without data leakage or
  Streamlit-style full reruns.
- Dashboard and learner output match current read models on fixed fixtures and a
  representative workbook-loaded database.
- Search, filtering, stable sorting, and pagination/threshold behavior are
  documented and tested.
- Protected data is not rendered before authentication resolves.
- Playwright covers authentication and the complete read-only slice.

### Phase 3: Learner Commands

Implementation status (2026-07-15): Issue #3 delivers profile edit from learner
detail. Issue #4 delivers first-time, returning, continuation, and rejoin starts
through authoritative destination options, an exact start-session precondition,
one atomic onboarding command, reasoned capacity override, named-user audit,
and targeted learner/dashboard refresh. Issue #5 delivers cross-class transfer
addressed by active run enrollment, with authoritative destination capacity,
exact start-session confirmation, atomic history links, optional reasoned
override, named-user audit, and targeted learner/dashboard refresh.

Deliver:

- Implement profile, learner start, and run-enrollment transfer endpoints.
- Add forms, validation, live destination context, confirmation, and capacity
  override behavior.
- Reuse lifecycle-aware service commands without UI orchestration of writes.

Acceptance:

- First-time start, continuation, rejoin, and transfer match current service
  behavior.
- Changed start-session proposals and conflicting active enrollments return safe
  conflict responses.
- Capacity overflow requires an authorized reason.
- Silent placement or historical snapshot changes remain impossible.
- Every successful write has named-user audit attribution.
- Invalid input, forbidden role, concurrency conflict, rollback, and retry paths
  are tested.

### Phase 4: Attendance And Final Results

Implementation status (2026-07-15): Issue #6 delivers attendance course-run and
session-unit selection, atomic planned session creation with an exact sequence
precondition, event-time roster reads, and atomic full-roster save protected by
an opaque stale/concurrent token. Issue #7 adds server-filtered make-up options
and linked credit with required reason, named audit attribution, immutable
original absence, zero denominator effect, and safe concurrent rejection.
Issue #8 adds the final-result review queue, server-calculated eligibility,
immutable result corrections, admin-only override, and role-safe completion
suggest/confirm/reject actions as one coherent run-enrollment journey.

Deliver:

- Implement session-unit list, event-time roster, atomic full-roster save, and
  linked make-up credit.
- Implement final-result creation/correction, calculated eligibility, authorized
  override, and completion confirmation.

Acceptance:

- A roster is addressed by course run plus session unit, never meeting alone.
- Historical roster membership remains correct after transfer or completion.
- Full-roster save is one transaction and rejects incomplete/stale membership.
- Make-up preserves the original absence and adds no denominator unit.
- Evaluation version 2+ requires a correction reason.
- Eligibility override remains admin-only and audited.
- Two concurrent roster/evaluation submissions have defined, tested outcomes.

### Phase 5: Review, Follow-Ups, Classes, Reports, And Audit

Implementation status (2026-07-16): Issue #9 delivers normalized monthly
overview/detail reads, a clearly separated server proposal, immutable
named-actor HR conclusions, and authenticated private XLSX export through one
React journey. Workbook sheet/value parity and concurrent version allocation
are covered at the HTTP interface.

Deliver:

- Implement monthly review, saved action summary, and XLSX export.
- Implement operational follow-up inbox and approved resolution actions.
- Implement class/course-run creation, scheduling, revision, and cancellation.
- Implement allow-listed reports and paginated audit views.

Acceptance:

- Monthly figures and exports match current reporting for fixed and production-like
  fixtures.
- Follow-up resolution preserves original issue details and resolution history.
- Schedule revision/cancellation requires reasons where defined and records
  before/after audit detail.
- Viewer can read only allowed data and cannot mutate.
- Report and audit filters cannot expose unauthorized internal payloads.
- User management remains explicitly out of parity scope unless separately
  approved.

### Phase 6: Operational Hardening

Deliver:

- Run backend integration, frontend browser, accessibility, security, and load
  tests against the production-style topology.
- Add production runbook for install, launch, restart, TLS, secrets, logs,
  backup/restore, upgrade, rollback, and certificate renewal.
- Verify connection-pool behavior at the agreed concurrency and worker count.
- Add automated output comparisons for critical Streamlit and React read paths.
- Rehearse deployment and fallback on a disposable or restored production-like
  database.

Acceptance:

- Measured latency and concurrency targets from Phase 0 pass.
- No connection leak appears during success, error, disconnect, or load tests.
- Security review covers cookies, CSRF, CORS, TLS, authorization, logs, and
  secrets.
- Backup restore and frontend traffic rollback are demonstrated.
- All existing data dictionary, service, UAT, and cutover gates still pass.

### Phase 7: Controlled Cutover

Deliver:

- Run HR UAT from the completed parity matrix.
- Assign React ownership workflow by workflow.
- Freeze Streamlit feature development after full parity, allowing only critical
  fallback fixes.
- Deploy the versioned React build and FastAPI release with a documented rollback
  switch.
- Observe the agreed stabilization window.

Acceptance:

- HR owner signs the parity matrix and cutover checklist.
- No critical or high unresolved migration defect remains.
- Audit, reports, and key record counts reconcile after production use.
- Rollback can redirect users to the compatible Streamlit release without data
  restore or reverse migration.
- Production targets remain healthy for the explicitly dated stabilization
  period; â€œone release cycleâ€ alone is not an acceptance criterion.

### Phase 8: Streamlit Retirement

Deliver:

- Archive the final compatible Streamlit release/tag and its rollback runbook.
- Remove Streamlit runtime dependencies, launcher paths, UI-only helpers, and
  obsolete smoke tests only after signed retirement approval.
- Keep reusable services, read modules, reports, migrations, and historical
  evidence.
- Update architecture, setup, operations, and developer documentation.

Acceptance:

- No production route or operator procedure still depends on Streamlit.
- Replacement verification covers every removed Streamlit gate.
- A verified database backup and final compatible application artifact are
  retained according to the approved retention policy.
- The repository passes the full test and documentation review after deletion.

## 13. Test Strategy

### Existing regression net

- `python -m pytest tests/`
- Existing dictionary and phase gates.
- Existing Streamlit smoke paths until their replacement is verified.
- Manual UAT with the representative workbook-loaded local database.

### Backend

- Unit tests for schema validation, error mapping, session security, and helpers.
- Router integration tests against disposable PostgreSQL.
- Authentication, CSRF, session expiry/revocation, and role matrices.
- Exact service command invoked per mutation.
- Audit attribution and transaction rollback.
- Stale/concurrent mutation behavior.
- Pagination, filtering, timezone, Decimal, and unexpected-error serialization.
- Pool lifecycle and connection-return tests.
- OpenAPI snapshot/compatibility checks.

### Frontend

- Focused tests for complex form state and query-key behavior.
- Generated-client contract check.
- Accessibility checks for forms, tables, dialogs, navigation, focus, and error
  summaries.
- Playwright scenarios for:
  - login, refresh, expiry, and logout;
  - protected-route behavior;
  - dashboard and learner search/detail;
  - learner start and transfer, including conflict;
  - full attendance roster save and stale roster;
  - make-up credit;
  - final-result correction and admin override;
  - monthly review export;
  - forbidden mutation as viewer;
  - schedule correction/cancellation;
  - follow-up resolution;
  - reports and restricted audit visibility.

### Parity and reconciliation

- Compare API reads with current read-model/report output on fixed fixtures.
- Compare representative Streamlit and React screen totals, labels, filters, and
  empty-state semantics.
- Reconcile audit events after each migrated write scenario.
- Verify no migration changes entity grain, historical snapshots, attendance
  denominator rules, evaluation versioning, or source-row preservation.

## 14. Rollout And Rollback

### Rollout

- Version backend and frontend artifacts together.
- Deploy backward-compatible schema changes before code that requires them.
- Direct users to React one workflow at a time.
- Record production ownership of each workflow in the parity matrix.
- Monitor request errors, authentication failures, response latency, connection
  exhaustion, and business-command conflict rates without logging sensitive
  inputs.

### Rollback triggers

Define numeric/owner-approved thresholds in Phase 0. At minimum, rollback is
considered for:

- authentication/session failure affecting normal HR work;
- data integrity or audit attribution discrepancy;
- repeated transaction failures on a core workflow;
- report/KPI mismatch that cannot be explained by timing;
- unacceptable latency or connection exhaustion;
- a critical security defect.

### Rollback action

```text
Stop routing users to the affected React workflow
  -> restore access to the last compatible Streamlit release
  -> keep the same canonical database
  -> investigate using request IDs and audit evidence
```

Rollback does not undo valid canonical writes and does not dual-write. A database
restore is reserved for independently verified data corruption and follows the
existing backup/restore authority and runbook.

## 15. Principal Risks And Controls

| Risk | Control |
|---|---|
| HTTP contract targets the wrong entity grain | Phase 0 contract review; session-unit and enrollment identifiers |
| Session theft or unrevokable logout | Opaque DB-backed sessions, HTTPS, CSRF, expiry, revocation |
| Business logic duplicated in routes or React | Exactly one service command per HR event; service-level tests |
| Streamlit and React overwrite each other | Short cache lifetime, authoritative reload/locks, explicit 409 conflicts |
| Connection exhaustion | Bounded pool, worker budget, load test, lifecycle tests |
| TypeScript/Pydantic drift | Generated OpenAPI client and CI stale-contract check |
| Big-bang cutover | Workflow slices, parity matrix, route ownership, rehearsed fallback |
| Scope expansion delays parity | User admin and unrelated features remain separate |
| LAN credentials sent in clear text | Production HTTPS and secure cookies |
| UI parity hides semantic regression | Fixed-fixture comparison, audit reconciliation, owner UAT |

## 16. Final Go/No-Go Criteria

Proceed from planning to implementation only when:

- the migration business case and measurable targets are approved;
- session, CSRF, TLS, deployment, and secret-management decisions are explicit;
- endpoint identifiers match canonical entity grain and existing command inputs;
- the parity matrix covers all production workflows;
- the production connection budget and LAN concurrency target are known;
- Phase 0 baseline verification passes.

Cut over completely only when:

- all parity slices have automated and owner-accepted evidence;
- production-style security, load, backup, and rollback rehearsals pass;
- all required existing gates pass;
- the fallback release is compatible with the current schema;
- the dated stabilization window and retirement approval are complete.
