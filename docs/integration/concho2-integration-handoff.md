# ConCho2 integration handoff

This is the start page for a developer integrating the English Class domain
into [FinanceBullkk/ConCho2](https://github.com/FinanceBullkk/ConCho2). It
explains what must be preserved, where the working code lives, how the two
models relate, and how to migrate without losing history.

## Outcome

Keep ConCho2 as the single LTMS product and application shell. Rebuild the
English Class business behavior inside ConCho2 using this repository's model
and tests as the reference. Do not combine the databases first and try to fix
the meaning later.

The intended end state is:

```text
ConCho2 React UI
  -> ConCho2 auth/policy and HTTP boundary
    -> English Training command Interface
      -> English domain Module (rules + one transaction + audit)
        -> ConCho2 PostgreSQL canonical English tables

ConCho2 calendar/email/certificates/reports
  <- events and projections from committed English domain state
```

This is an integration recommendation based on the repositories as inspected
on 2026-07-16. Proposed target names below are not claims that those entities
already exist in ConCho2.

## Read in this order

1. [Domain glossary](../../CONTEXT.md) for exact shared language.
2. [ADR 0001](../adr/0001-english-domain-authority-for-concho2-integration.md)
   for the ownership decision.
3. [Data dictionary](../../DATA_DICTIONARY.md) for canonical fields, controlled
   values, and field ownership.
4. [Target architecture](../../TARGET_ARCHITECTURE.md) for entity grain and all
   invariants.
5. [Project rules](../../PROJECT_RULES.md) for mandatory transaction, audit,
   migration, and no-silent-loss rules.
6. [Codebase summary](../codebase-summary.md) for the implementation map.
7. [HTTP contract](../plans/http-contract-v1-draft.md) for current request,
   response, role, conflict, and concurrency behavior.
8. [Workflow parity matrix](../plans/workflow-parity-matrix.md) and issue
   evidence under [`docs/reviews/`](../reviews/) for proof of each workflow.

If these sources conflict, follow the authority order in `PROJECT_RULES.md`:
confirmed data dictionary decisions, target grain/invariants, implementation
plan, production behavior, then legacy sources.

## Current repository state

- Runtime: React + FastAPI + PostgreSQL, local single-machine testing only.
- Streamlit is retired. Its final compatible source is retained by tag; see
  [the retirement record](../runbooks/issue-14-streamlit-retirement.md).
- PostgreSQL migrations `001` through `020` form the canonical application
  schema. Files under `legacy/` are historical evidence and must not run
  against the canonical database.
- The workbook is a migration source, not a target model.
- Database contents, backups, passwords, environment files, private keys, and
  local certificates are deliberately absent from Git. A clone contains the
  code and reproducible schema, not production data or credentials.

Before using any revision as the integration baseline, select an explicit
commit or tag and require a clean test run; never infer the baseline from a
developer's working directory.

## Codebase map

| Area | What a ConCho2 developer should learn from it |
|---|---|
| `services/` | Reference business commands. `BusinessService` composes workflow modules; each command owns one transaction, authorization, locking, and audit. |
| `api/` | Safe HTTP boundary, validated input, CSRF/session enforcement, stable `409` conflicts, and no SQL leakage. |
| `frontend_queries.py` | Task-oriented read models; use this pattern instead of exposing generic table CRUD. |
| `web/` | Current HR journeys and generated OpenAPI TypeScript contract. It is behavior evidence, not UI that must be copied pixel-for-pixel. |
| `migrations/` | PostgreSQL constraints, triggers, views, session tables, and canonical physical model. Applied migrations are immutable. |
| `scripts/canonical_etl_v3.py` | Deterministic, staged, auditable legacy transformation. |
| `tests/` | Fast business and API regression suite on a disposable database. These scenarios should become target contract tests. |
| `docs/reviews/` | Per-slice acceptance evidence, edge cases, and owner decisions. |

The layer rule is `UI -> HTTP -> business command/read model -> repository/DB`.
UI components never own SQL or domain transitions.

## Business mechanisms that must survive

### Identity, groups, and repeated learning

- An Employee is identified by employee code, not name and not ConCho2 login
  ID alone.
- A Cohort is a stable learning group across Courses.
- One delivery is a Course Run. The same Cohort can take many Courses and can
  repeat the same Course through a new numbered Course Run.
- Cohort Membership history and Run Enrollment history are different facts and
  must remain different.

Example: `EL001` completes Elementary and later repeats Elementary. That is one
Cohort, two Course Runs, and separate Run Enrollments. Reusing a record keyed by
`EL001 + Elementary` destroys the first history.

### Joining and transferring

- Starting a learner is one atomic event: employee/profile confirmation,
  organization history, placement, membership, run enrollment, immutable
  organization snapshots, capacity decision, and audit either all commit or
  all roll back.
- `start_session_number` is the first applicable logical unit. Earlier units
  are not absences and never enter the denominator.
- A transfer closes and links the source membership and enrollment, then
  creates the target records with current organization snapshots in the same
  transaction. History is never moved or rewritten.
- One Employee cannot have two active Run Enrollments.

### Schedule and attendance

- A Meeting is a calendar occurrence; a Session Unit is a credited unit.
  Duration and credit are not interchangeable.
- Attendance grain is one Run Enrollment plus one Session Unit.
- A roster is calculated from event-time applicability. Saving is a complete,
  atomic roster operation protected by a stale-state token; an incomplete,
  duplicate, or changed roster returns a conflict without partial writes.
- Cancelled Meetings and make-up units do not add denominator units.
- A make-up creates a later Present fact linked to one original direct Absent
  fact. It does not overwrite the absence and does not inflate the denominator.

Example: a learner is Absent at logical unit 5 and later Present at a make-up
unit. Unit 5 becomes credited in the derived result, but the original absence
and make-up link remain auditable and the denominator still contains one unit.

### Evaluation, eligibility, and completion

- Exam eligibility is derived from applicable attendance. Only admin can
  override it, with the old result, actor, reason, and timestamp retained.
- Pass and next-Course decisions come from the teacher's Evaluation, not from
  attendance alone.
- Evaluation corrections append immutable Evaluation Versions. The client
  never chooses the next version number.
- Current level means the latest valid Evaluation. Highest historical level is
  a different metric.
- Completion is suggested, then explicitly confirmed or rejected. Recording a
  result does not silently perform an irreversible completion.

### History, audit, and migration

- Current employee organization and enrollment organization snapshots have
  different owners. Updating HR data never rewrites historical snapshots.
- Every sensitive business command is attributed to a named server-verified
  actor and writes its audit record inside the same transaction.
- Every imported source row has exactly one recorded outcome. Unknown or
  ambiguous data is retained in staging or a durable quality issue; it is not
  silently dropped or invented.

## The integration Seam

Create one deep English Training **Module** in ConCho2. Its small command
**Interface** is the primary **Seam**; HTTP controllers, jobs, and ConCho2
features use **Adapters** rather than writing English tables directly.

| Business command | Current reference | Required target behavior |
|---|---|---|
| Start learner | `BusinessService.onboard_learner` | Lock destination and proposal; atomically own profile/org, placement, membership, enrollment snapshots, capacity override, and audit. |
| Transfer learner | `transfer_learner` | Close/link source and create target membership/enrollment atomically; reject stale or repeated source. |
| Create course delivery | `create_class_course_run`, `create_course_run` | Preserve stable Cohort versus numbered Course Run and snapshot policy values. |
| Create meeting and credits | `create_meeting_with_units`, `create_attendance_session` | Keep occurrence and credited units separate; lock the proposed sequence. |
| Save roster | `save_attendance_roster` | Require one result per authoritative applicable enrollment and a stale precondition; commit roster, meeting state, and audit together. |
| Credit make-up | `correct_attendance_makeup` | Create one linked Present, retain original Absent, add zero denominator units, audit reason. |
| Record/correct result | `record_evaluation` | Append an immutable server-numbered version; require a correction reason after v1. |
| Override eligibility | `override_exam_eligibility` | Admin only; append override context instead of mutating derived attendance. |
| Suggest completion | `suggest_completion` | Perform a reversible, audited lifecycle proposal. |
| Confirm/reject completion | `confirm_completion` | Enforce role and reason rules; commit lifecycle and audit together. |

The target Interface does not need these Python method names, but it must keep
their input ownership and outcomes. Prefer intent-shaped commands over generic
`create/update` endpoints. Each write accepts only user decisions; identifiers,
snapshots, derived values, version numbers, actor identity, and audit fields are
server-owned.

Concurrency is part of the contract: lock authoritative rows, recalculate
proposals inside the transaction, use unique constraints as final guards, and
return a stable conflict so the UI refetches. A retry must produce one valid
outcome, never two partial events.

## ConCho2 model mapping

The inspected ConCho2 model uses `User`, `LearningProgram`, `Class`, `Team`,
`Enrollment`, `Schedule`, `Attendance`, and evaluation/assessment concepts.
Its own overview says `Class` is currently presented as a Cohort DTO and `Team`
to LearningGroup is not yet migrated. Therefore the following is a target
design proposal, not a mechanical rename.

| English Class authority | ConCho2 today | Recommended target interpretation |
|---|---|---|
| Employee | `User` | Link by unique normalized `empCode`; keep account/auth identity separate from employee business identity if users without accounts are valid. |
| Course | `LearningProgram` | Reuse when one Program really is one reusable course definition and policy snapshots can be created per run. |
| Cohort | `Class` / `Team` overlap | Introduce or clarify `LearningGroup`: one stable group across course deliveries. Do not force it into a one-delivery Class row. |
| Cohort Membership | team/class membership or Enrollment overlap | `GroupMembership` with start/end/status and transfer link, separate from program participation. |
| Course Run | `Class` | Prefer explicit `ProgramRun`: one group taking one program one time, including repeat number and policy snapshots. |
| Run Enrollment | `Enrollment` | `ProgramEnrollment`: employee in one ProgramRun, first applicable unit, org snapshots, lifecycle, transfer link. |
| Meeting | `Schedule` | Session occurrence/calendar booking. Keep ConCho2 scheduling modes as policy for who creates it. |
| Session Unit | no proven equivalent | Add a credited-unit child of Schedule/Meeting; roster identity and applicability use this key. |
| Attendance fact | `Attendance(scheduleId,userId)` | Change/extend grain to ProgramEnrollment + SessionUnit; retain original status and linked make-up fact. |
| Evaluation Version | Evaluation/Assessment concepts | Keep course-final business result separate from quiz attempts; append immutable result versions. |

ConCho2's `leader_booking`, `admin_scheduled`, `self_enroll`, and `nomination`
modes answer who may schedule or join. They are orthogonal to Course Run,
Enrollment, Session Unit, attendance denominator, and make-up semantics. Keep
the policies, but do not let a scheduling mode change historical grain.

Keep ConCho2's broader strengths: account/MFA and authorization policy,
application shell and UX, Google Calendar and email adapters, assessments,
feedback, learning paths, reports, certificates, compliance, and other LTMS
capabilities. These consume committed English state or call the command
Interface; they do not bypass it.

Relevant ConCho2 sources:

- [System overview](https://github.com/FinanceBullkk/ConCho2/blob/main/docs/system-overview.md)
- [Core PostgreSQL training schema](https://github.com/FinanceBullkk/ConCho2/blob/main/server/db/pg/migrations/001_core_training_schema.js)
- [Scheduling-mode policy](https://github.com/FinanceBullkk/ConCho2/blob/main/server/domains/schedule/scheduling-mode-policy.js)
- [Scheduling and booking specification](https://github.com/FinanceBullkk/ConCho2/blob/main/docs/specs/scheduling-and-booking/spec.md)
- [Domain-model migration rule](https://github.com/FinanceBullkk/ConCho2/blob/main/.claude/rules/domain-model-and-migration.md)

## Migration and cutover plan

### 0. Freeze the contract and baseline

- Choose exact source and ConCho2 commits; record both SHAs.
- Back up both databases and test restoring them.
- Confirm the target PostgreSQL migration ledger before adding migrations.
- Turn the business mechanisms above into target contract tests.

### 1. Add the target model behind a feature flag

- Add explicit target entities and constraints at their stated grains.
- Add the command Interface and task-oriented reads.
- Port one vertical workflow at a time: start, transfer, schedule/roster,
  make-up, result/completion.
- Keep ConCho2 auth and policy as the caller boundary; recheck authorization in
  the domain service.

### 2. Prove a small pilot

Use roughly ten Employees and one Cohort with multiple Course Runs. Include a
repeat Course, mid-run join, transfer, cancelled Meeting, two-unit Meeting,
linked make-up, evaluation correction, capacity override, and completion
rejection/confirmation. Compare target outputs to this reference implementation
and manually inspect audit events.

### 3. Migrate history through staging

- Load immutable raw rows with batch, checksum, source row, raw payload, and
  ingestion time.
- Create stable crosswalks from source surrogate IDs to target IDs.
- Transform deterministically into canonical target grains.
- Record one source-row outcome and durable issue code for every row.
- Never invent missing dates, levels, identities, or run boundaries.

For every source sheet or extract, prove at the same row grain:

```text
source data rows
= canonical rows represented
+ unresolved issue rows
+ approved ignored rows
```

Also reconcile business facts independently: Employees, Cohorts, Course Runs,
active Enrollments, Meetings, denominator Session Units, direct Attendance,
linked make-ups, Evaluations and versions, completion states, and audit events.

### 4. Switch ConCho2 English workflows

- Enable the new Interface for a controlled role/cohort first.
- Stop old English writes before final delta migration; do not dual-write.
- Verify UI journeys, permissions, conflicts, reports, notifications, calendar
  events, and certificates against the new state.
- Roll back by feature flag and database restore if reconciliation or a
  critical invariant fails.

### 5. Accept and retire the old runtime

Cut over only when tests pass, migration equations balance, representative
records match, no unexplained high-severity issue remains, and the business
owner signs off. Retain the source commit/tag, migration batches, crosswalks,
quality issues, reconciliation output, and restore instructions.

## Acceptance gates

- Database constraints prove unique employee code, one active Run Enrollment,
  repeatable Course Runs, attendance fact uniqueness, one make-up per original
  absence, and immutable history where practical.
- Every command test covers success, permission denial, invalid input, stale or
  duplicate submission, rollback, and actor-attributed audit.
- Derived attendance reproduces mid-run applicability, cancellation exclusion,
  and replacement-credit behavior without denominator inflation.
- Evaluation correction and eligibility override retain every version and
  reason.
- Source-row and entity-level reconciliation balances exactly or has an
  explicitly approved residual issue.
- ConCho2 cross-cutting integrations act only after the English transaction is
  committed and are idempotent or safely retryable.

## Decisions the integration team must make

Do not hide these choices inside implementation:

1. Does this canonical mechanism govern only English programs, or become the
   shared model for every structured instructor-led program in ConCho2?
2. How do ConCho2 attendance values such as Late or Excused Late map to the
   English canonical effective Present/Absent result and retained details?
3. Which system is authoritative for Employee and organization history, and
   how are effective dates received?
4. Does ConCho2 retain text IDs, adopt surrogate IDs for canonical English
   entities, or keep an explicit crosswalk? IDs may change; grain may not.
5. Which target environment, access owner, maintenance window, and rollback
   authority are approved for the real cutover?
6. Which ConCho2 scheduling modes are permitted for English programs? This
   choice changes who can initiate a Meeting, not attendance or enrollment
   meaning.

## Explicit non-goals

- No permanent database-to-database sync or bidirectional replication.
- No shared schema in which both applications write the same tables.
- No UI or controller writing canonical tables directly.
- No flattening to `class_code + course_name`, employee name, meeting, or
  today's membership as a convenient key.
- No copying Python code verbatim as a goal; semantic parity is the goal.
- No committing database dumps, source workbook data, passwords, tokens,
  private certificates, or local environment configuration.

## Developer setup and verification

Follow the full local setup in [README](../../README.md). A fast reference
verification run is:

```powershell
python -m pytest tests/
npm --prefix web test
npm --prefix web run build
```

For schema, ETL, and cutover work use `scripts/run-all-gates.ps1` and the review
checklist; these need the documented disposable databases and environment
variables. Never aim migration or destructive test commands at an unknown
database.

Useful evidence by behavior:

- [Start](../reviews/issue-4-learner-start.md) and
  [transfer](../reviews/issue-5-learner-transfer.md)
- [Roster](../reviews/issue-6-attendance-roster.md) and
  [linked make-up](../reviews/issue-7-makeup-credit.md)
- [Final results](../reviews/issue-8-final-results.md)
- [Classes and schedule](../reviews/issue-11-classes-schedule.md)
- [Reports and audit](../reviews/issue-12-reports-audit.md)
- [Production/local-only decision](../reviews/issue-13-production-readiness.md)
- [Streamlit retirement](../reviews/issue-14-streamlit-retirement.md)

## Handoff checklist

- [ ] Source and target commit SHAs recorded.
- [ ] The integration team has read the glossary, ADR, data dictionary, target
      architecture, and project rules.
- [ ] Six open decisions above have named owners and recorded outcomes.
- [ ] Target entity grains and constraints are reviewed before migrations.
- [ ] Command Interface contract tests exist before target implementation.
- [ ] Pilot edge cases pass with audit and rollback evidence.
- [ ] Raw staging, crosswalk, row outcomes, and reconciliation are reproducible.
- [ ] Security, privacy, secrets, and least-privilege roles are reviewed.
- [ ] Cutover, rollback, and ownership are approved; no dual-write window exists.
- [ ] Old runtime is retired only after target acceptance.
