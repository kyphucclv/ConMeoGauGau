# Phase 13 HR-first application architecture

Status: **Owner approved; P13.0 integrity foundation authorized**

Date: 2026-07-14

Owner approval date: 2026-07-14

Owner-approved make-up policy: **Replacement credit**. The original absence
remains historically visible and one linked make-up event changes effective
attendance credit without increasing the denominator.

Baseline commit reviewed: `9d0db4b phase13 start hr-first workspace`

Related contracts:

- `TARGET_ARCHITECTURE.md`
- `DATA_DICTIONARY.md`
- `docs/reviews/phase-11-operations-workspace-spec.md`
- `docs/reviews/phase-11-operational-issue-snapshot.md`
- `docs/reviews/phase-13-hr-first-ux-spec.md`

## 1. Outcome

Phase 13 must produce a desktop application that an HR operator can use from
familiar business tasks without learning database terms. User friendliness must
not move business rules into Streamlit or weaken the canonical PostgreSQL
model.

The architecture therefore uses two simultaneous contracts:

1. The HR contract: every page exposes a recognizable task, a clear current
   state, one primary next action, and business-language errors.
2. The data contract: every confirmed business event is validated and written
   once by one application use case in one database transaction.

Phase 13 is not permitted to continue with page-by-page cosmetic work until the
P13.0 integrity foundation in section 12 is complete.

## 2. Non-negotiable rules

1. PostgreSQL remains the durable source of truth. Streamlit session state is
   temporary UI state only.
2. Streamlit pages never execute INSERT, UPDATE, or DELETE statements.
3. One public application command represents one HR business event and owns
   exactly one transaction.
4. A page must not compose multiple committing service calls to simulate one
   save.
5. Database IDs may be carried internally but are never required knowledge for
   HR.
6. All writes use a named application user. Shared `local_admin` attribution is
   not acceptable for production operation.
7. High-risk corrections and overrides retain actor, timestamp, reason, and
   before/after values.
8. Historical facts are selected using event-time applicability, not only the
   entity's current status.
9. Derived values such as attendance rate and exam eligibility are read-only in
   normal forms. A separate authorized override command is required.
10. Accepted legacy exceptions remain explicit exceptions. The application
    must never convert an unknown legacy value into an invented fact.

## 3. Target application shape

```text
Streamlit presentation
  app shell, navigation, forms, grids, feedback, temporary drafts
                         |
                         v
Application use cases
  named commands, authorization, validation, transaction ownership,
  idempotency, audit payloads
                         |
               +---------+---------+
               |                   |
               v                   v
Domain policies                 Read queries
  lifecycle rules, roster         task-specific read models,
  applicability, eligibility,     operational issue projections,
  capacity, correction rules      reporting views
               |                   |
               +---------+---------+
                         v
PostgreSQL canonical model
  keys, foreign keys, checks, unique indexes, relationship triggers,
  immutable snapshots, versions, audit events
```

This is a modular monolith. A separate API or microservice is not justified for
two desktop HR users. The service boundary still remains explicit so a future
API can reuse the same use cases.

## 4. Proposed code ownership

```text
streamlit_app.py                 app bootstrap, actor, shared state, navigation
app_pages/
  home.py                       work queue and common task entry points
  learners.py                   learner search and learner journeys
  attendance.py                 session and roster journeys
  results.py                    eligibility, evaluation, completion
  monthly_review.py             read-only monthly review and saved conclusions
  follow_ups.py                 corrective work queue
  admin.py                      class setup, users, audit, reference records
ui/
  components.py                 shared display components only
  copy.py                       centralized HR labels and error messages
application/
  learners.py                   learner use cases
  attendance.py                 attendance and schedule use cases
  results.py                    evaluation and completion use cases
  classes.py                    class and course-run use cases
  follow_ups.py                 issue-resolution orchestration
domain/
  policies.py                   pure, testable business rules
queries/
  learners.py                   parameterized learner read models
  attendance.py                 event-time roster and session queries
  reviews.py                    monthly and follow-up read models
infrastructure/
  database.py                   pool, transaction helpers, schema verification
```

Migration can be incremental. Existing public service calls remain available
only while callers are moved to the new use-case modules. Deprecated low-level
write methods must not remain reachable from normal HR pages.

## 5. HR information architecture

Use persistent sidebar navigation with role-based sections. A large in-page
segmented control must not be the primary application navigation.

| Section | Page | HR question answered | Primary action |
|---|---|---|---|
| Work | Home | What needs my attention today? | Open a common task |
| Work | Learners | Who is learning and what class are they in? | Add or move a learner |
| Work | Attendance | Which class session needs attendance? | Save the full roster |
| Work | Final results | Who is ready for a result or completion decision? | Record a result |
| Review | Monthly review | What happened this month? | Save/export the review |
| Review | Follow-ups | Which records need an HR decision? | Open the corrective flow |
| Admin | Classes and schedule | Which classes and sessions are configured? | Set up or revise a class |
| Admin | Users and audit | Who can use the app and what changed? | Review access/history |

Daily pages show business labels such as learner, class, course, session, and
final result. Terms such as cohort, course run, session unit, enrollment ID,
and audit entity key remain internal or appear only in admin diagnostics.

The first screen is a work queue, not a KPI dashboard. Counts are useful only
when each count opens the exact records that need action.

## 6. Identity and permissions

Phase 11's owner decision that both HR operators have full application access
is preserved. Phase 13 adds named attribution, not a new permission decision.

| Actor | Normal access | Additional controls |
|---|---|---|
| Named HR user | Learners, attendance, final results, reviews, follow-ups, class setup | Confirmation and reason on risky actions |
| Admin user | Same daily work | User management, eligibility override, final completion confirmation, legacy decisions, audit |
| Viewer | Reports and history | No mutation commands |

Production startup must never create, reactivate, promote, or reset a user.
Bootstrap is a separate one-time operator command. The authenticated actor ID is
required by every write use case and every audit event.

## 7. Source-of-truth matrix

| Business fact | Canonical owner | HR may edit | Required history behavior |
|---|---|---|---|
| Employee code and name | `employees` | Name/status through employee profile; code through dedicated correction only | Audit before/after |
| Current and historic BU/role | `employee_org_history` | Through one organization-change command | Add a new period only when values change |
| Stable class identity | `cohorts` | Class setup | Code immutable after operational use |
| Current PIC | `cohort_pic_assignments` | Class setup | Close old assignment, add new assignment |
| Continuous class membership | `cohort_memberships` | Through join, transfer, or leave use cases | Never overwrite prior membership |
| One delivery of one course | `course_runs` | Class setup and lifecycle actions | Snapshot course rules at creation |
| Learner participation in a run | `run_enrollments` | Through start, continue, transfer, leave, completion | Keep immutable BU/role snapshots |
| Scheduled occurrence | `meetings` | Schedule flow | Preserve old/new schedule values on edits/cancel |
| Credited instructional unit | `session_units` | Created with its meeting use case | Unique sequence and meeting relationship |
| Attendance result | `attendance` plus audit/change history | Full-roster save or explicit correction | Record per-row before/after and actor |
| Entrance placement | `placements` | First placement or audited correction | One business placement, no duplicate inserts |
| Final result | `evaluation_versions` | New immutable version | Correction reason required after version 1 |
| Exam eligibility | Derived attendance policy | Read-only; admin override only | Override version includes reason and actor |
| Monthly conclusion | `monthly_review_action_summary_versions` | Explicit save | Immutable versions |
| Operational follow-up | Projection plus resolution event | Through the linked corrective use case | Cannot be hidden without correction or accepted exception |

## 8. Transaction contract

Every write use case follows the same sequence:

```text
receive typed command + actor + request token
  -> authorize actor
  -> validate required input
  -> acquire row/advisory locks in a stable order
  -> reload current canonical state inside the transaction
  -> validate lifecycle, relationships, capacity, and concurrency token
  -> write all related records
  -> write audit event/version in the same transaction
  -> commit once
  -> return a business receipt
```

The transaction rolls back on any failed validation or database constraint.
The UI receives a stable error code mapped to HR-facing copy.

### Idempotency

Create, transfer, full-roster save, schedule change, evaluation, completion, and
override commands receive a per-submit request token. A unique command receipt
prevents a browser rerun or double click from creating a second business event.

### Concurrency

- Learner start and transfer lock the employee, source enrollment/membership,
  and target class capacity before counting or writing.
- Attendance save locks the selected meeting/session and reloads the applicable
  roster inside the transaction.
- Schedule and employee edits carry the last observed `updated_at`; a stale form
  receives a refresh-required result instead of overwriting a newer change.
- Evaluation and monthly versions use an advisory lock before assigning the
  next version number.

### Audit payload

High-risk events include:

```json
{
  "request_id": "...",
  "reason": "...",
  "before": {},
  "after": {},
  "related_entity_ids": {}
}
```

Audit content must be sufficient to explain the change without reconstructing
the old state from mutable tables.

## 9. HR workflow contracts

### 9.1 Add learner to a class

```text
Find employee
  -> confirm/create employee profile
  -> system classifies first-time or returning learner
  -> select target class/course
  -> confirm placement or audited placement correction
  -> review capacity and proposed first applicable session
  -> confirm one summary
  -> one atomic start-learning command
  -> learner appears in the applicable attendance roster
```

The application command must support both first-time and returning learners:

- create the employee only when absent;
- update name/status only when HR changed them;
- create organization history only when BU/role changed;
- create a business placement only when absent, otherwise retain it or run an
  explicit correction;
- reuse an applicable active class membership or create a new membership;
- reject any competing active course-run enrollment;
- create the run enrollment and immutable organization snapshots;
- record a capacity override only when required and explicitly confirmed.

### 9.2 Continue to the next course

This is a separate HR task from first-time onboarding.

```text
Open completed learner result
  -> choose the next course run for the same class
  -> reuse active class membership
  -> calculate first applicable session
  -> create one new active run enrollment
```

No new employee, placement, or cohort membership is inserted. This flow closes
the gap between a completed enrollment and the cohort's next course.

### 9.3 Transfer learner

```text
Open active learner
  -> select destination class/course
  -> server calculates capacity and next applicable session
  -> HR confirms destination summary
  -> one atomic transfer command
```

The command marks the source enrollment transferred, closes and links the
source membership, creates the target membership and enrollment, copies current
organization snapshots, and writes one audit event. Capacity override behavior
must be explicit and consistent with learner onboarding.

### 9.4 Create or revise a class session

```text
Select class/course
  -> enter date, time, duration, and one/two credited units
  -> validate duplicate time and sequence
  -> one atomic create-session command
```

Creating a meeting and its credited units is one transaction. Editing or
cancelling a meeting preserves its identity, date, duration, and attached
attendance unless HR explicitly changes those fields. Cancellation changes only
status and reason and records the previous schedule in audit details.

### 9.5 Record attendance

```text
Select class/course
  -> select a planned or completed session
  -> server builds event-time applicable roster
  -> HR marks exceptions from the default
  -> review present/absent/unchanged counts
  -> one atomic full-roster save
  -> session becomes completed and metrics refresh
```

Roster applicability uses enrollment start session and membership dates. A
learner who transferred or completed later must still appear when correcting a
session that occurred while the learner was applicable.

Default `Present` is allowed only for a new unsaved operational roster. A
historical legacy gap remains `Unknown` until HR enters source evidence or an
approved legacy exception applies.

The save rejects missing, extra, duplicate, cross-run, pre-start, or stale
roster rows. Per-row changes retain old status, new status, actor, timestamp,
and optional note.

### 9.6 Record make-up attendance

The owner approved replacement credit. The original absence remains
historically visible, while one linked make-up event changes effective
attendance credit to present without adding another denominator unit. Migration
018 enforces one linked make-up per original absence, matching enrollment and
unit type, event order, and immutable linkage. Service eligibility, canonical
reporting, monthly review, and the HR form use the same replacement semantics.

### 9.7 Record final result and completion

```text
Select class/course
  -> select learner
  -> show calculated attendance and exam eligibility as read-only
  -> admin override only through a separate reasoned action
  -> record teacher result and next-course recommendation
  -> create immutable evaluation version
  -> system suggests completion
  -> admin confirms completion
```

Version 2 and later require HR to enter a correction reason. `exam_eligible`
cannot be directly edited in the ordinary evaluation form. Completion and the
class-membership next state must be explicit: continue in the same class, leave
the class, or transfer.

### 9.8 Resolve a follow-up

```text
Open issue
  -> application opens the owning corrective flow
  -> HR corrects the canonical record or records an authorized exception
  -> system re-runs the issue rule
  -> issue closes only when the rule no longer matches or exception is valid
```

A generic `Resolved` button must not hide a still-invalid canonical record.
The approved Phase 11 legacy decisions and source/snapshot checksums remain
attached to their exceptions.

## 10. Lifecycle rules visible to HR

| Entity | Allowed forward transitions |
|---|---|
| Class | `planned -> active -> completed -> archived` |
| Course run | `planned -> active -> completed -> archived`; cancellation is explicit |
| Enrollment | `active -> completed`, `transferred`, `dropped`, or `cancelled` |
| Membership | `active -> completed`, `transferred`, or `cancelled` |
| Meeting | `planned -> completed` or `cancelled` |
| Evaluation | no mutable status; append version 1, 2, 3, ... |

Employment status remains independent from course enrollment and class
membership. Resignation is not silently translated into a learning outcome.

Reverse transitions require a dedicated correction command with reason and
before/after audit. General-purpose status dropdowns should not expose invalid
state combinations.

## 11. Streamlit state and interaction rules

- `streamlit_app.py` initializes only actor identity and shared navigation
  context. Page-specific keys use a page prefix.
- Session state may hold selected employee, class, month, filters, draft form
  values, and request tokens. It never represents a committed business fact.
- Related inputs use `st.form`; changing a selectbox must not write data.
- After a successful command, clear the submitted draft, invalidate affected
  read caches, and rerun the page from canonical data.
- Operational reads should normally be uncached or use a very short bounded
  TTL. Shared database pools use resource caching.
- Pages use native Streamlit navigation and Material icons. Technical admin
  pages are conditional on role.
- Validation is shown at the field or summary that HR can act on. Raw SQL,
  constraint names, and internal IDs are not shown.

## 12. P13.0 integrity foundation

The repository review found the following blockers. These are architecture
findings, not permission to change production data.

| ID | Severity | Current risk | Required remediation |
|---|---|---|---|
| P13.0-A | critical | `streamlit_app.py` calls `ensure_local_admin`, which creates/reactivates/promotes a shared actor and prevents named HR attribution | Implement named sign-in/session actor; restrict bootstrap to an explicit operator path |
| P13.0-B | critical | A page can call several `BusinessService` methods, each committing independently; adding two session units can partially succeed | Add one atomic use case per multi-record HR event; remove UI orchestration of committing commands |
| P13.0-C | critical | `cancel_meeting` delegates placeholder date/duration values to `save_meeting`, so cancellation can overwrite the real schedule; schedule audit lacks before/after values | Implement dedicated cancel and schedule-correction commands with row lock and full audit payload |
| P13.0-D | critical | The normal evaluation form lets an editor write `exam_eligible` directly, bypassing the derived-policy/admin-override boundary | Make calculated eligibility read-only; accept changes only through the admin override command |
| P13.0-E | high | Attendance roster queries filter current `active` enrollments, so later transfer/completion can remove a learner from historical correction rosters | Build event-time roster applicability and test transfer/completion history |
| P13.0-F | high | Attendance updates overwrite effective status while the audit event records only roster count, not row-level before/after values | Add row-level change history or complete audit details in the same transaction |
| P13.0-G | high | Learner onboarding always inserts placement and membership, so a returning learner is not a supported lifecycle | Split first-time start, continuation, transfer, and rejoin behavior inside lifecycle-aware use cases |
| P13.0-H | high | Evaluation corrections use a generic generated reason instead of the operator's reason | Require and store an explicit reason for version 2+ |
| P13.0-I | high | Make-up attendance semantics and denominator behavior are not consistently defined | Implement the owner-approved replacement-credit policy in service, reporting, and database constraints |
| P13.0-J | medium | Saving an employee with unchanged BU/role can create an unnecessary organization-history period | Compare locked current values and append history only for a real change |
| P13.0-K | medium | UI modules contain extensive read SQL and database terminology, coupling copy, screens, and schema | Move reads into task-specific query modules before major page restructuring |
| P13.0-L | medium | `DATA_DICTIONARY.md` contains status/field language that has drifted from the applied canonical schema | Reconcile the dictionary against migrations before using it as UI terminology input |

P13.0-A through P13.0-H must be tested before P13.2 learner-page implementation.
P13.0-I now has an owner decision and must be implemented before the
make-up workflow is released. P13.0-J through P13.0-L must be completed before
Phase 13 sign-off.

### P13.0 implementation status

Completed on 2026-07-14:

- **P13.0-A**: runtime auto-admin creation was removed; named sign-in, sign-out,
  active-user revalidation, and one-time audited admin bootstrap are in place.
- **P13.0-B**: meeting plus credited-unit creation and one/two-unit additions
  now use atomic service commands. Failure on a later unit rolls back earlier
  units.
- **P13.0-C**: cancellation preserves schedule fields and writes reasoned
  before/after audit. Schedule correction locks the row, requires a reason when
  date/time/duration changes, and rejects invalid reverse transitions.
- **P13.0-D**: the final-result form no longer accepts exam eligibility.
  Eligibility is derived in the service, and only the admin override command
  can change its effective result.
- **P13.0-H**: evaluation version 2 and later require the HR operator's explicit
  correction reason; the service no longer generates a generic reason.
- **P13.0-E**: completed-session rosters now use enrollment start session and
  membership dates. Existing attendance remains correctable after transfer or
  completion, while planned rosters still include only active enrollments.
- **P13.0-F**: full-roster saves now retain per-enrollment before/after status,
  employee code, attendance identity, actor, timestamp, and optional note in the
  same-transaction audit event. New default-Present rows are audited from a null
  persisted state rather than treated as unchanged.
- **P13.0-G**: onboarding now classifies first-time, returning, continuation,
  and rejoin paths. It reuses an existing entrance placement and applicable
  active class membership, rejects silent placement changes and cross-class
  membership conflicts, and creates only the missing lifecycle records.
- **P13.0-I**: migrations 018-019 implement owner-approved replacement credit. The
  original absence remains `Absent`; one later completed make-up session grants
  present credit to its logical unit, adds zero denominator units, and writes a
  reasoned before/after audit event. Database constraints reject malformed,
  cross-purpose, duplicate, and rewritten links.

Verification evidence:

- `python scripts\phase4_integration_check.py`
- `python scripts\phase5_reporting_check.py`
- `python scripts\phase6_security_check.py`
- `python scripts\phase7_frontend_workflow_check.py`
- `python scripts\phase8_automated_uat.py`
- `python scripts\phase11_p11_1_integration.py`
- `python scripts\phase11_operational_issue_snapshot.py --validate-decisions --database-url postgresql://postgres@localhost:5432/english_class`
- `.\run_app.cmd -CheckOnly`

Production migration evidence on 2026-07-14:

- custom-format pre-018 backup catalog verified with 445 entries;
- migrations 018-019 applied with the restricted migration role in separate
  versioned transactions;
- production retained 6,281 attendance rows and zero pre-existing make-up rows;
- operational issue count and source/snapshot checksums remained unchanged;
- the restricted app role passed the launcher database health check.

P13.0-A through P13.0-I are complete. P13.0-J through P13.0-L remain open and
still gate Phase 13 sign-off.

## 13. Verification strategy

### Domain tests

- lifecycle transition matrix;
- event-time roster applicability before and after transfer/completion;
- attendance and exam-eligibility policy;
- first-time, returning, continuation, transfer, and rejoin classification;
- capacity and override policy;
- make-up policy after owner approval.

### Transaction integration tests

- each use case commits all records and its audit event together;
- injected failure at each write step leaves zero partial records;
- duplicate request token returns the existing receipt;
- concurrent onboarding cannot exceed capacity without one audited override;
- concurrent evaluation corrections receive unique sequential versions;
- stale schedule/profile edits are rejected;
- cancelled meetings retain original date, time, duration, units, and attendance;
- historical rosters remain reproducible after transfer and completion.

Integration tests run on disposable databases only.

### Database invariant checks

- no employee has multiple active run enrollments;
- active enrollments have an active matching membership and complete immutable
  organization snapshots;
- session unit and attendance rows belong to the same course run as their
  parent records;
- attendance never precedes enrollment applicability;
- one current organization and PIC assignment exist where required;
- no duplicate class code, run sequence, meeting time, attendance fact, or
  evaluation version exists;
- accepted legacy exception counts and checksums remain reproducible.

### UI acceptance

- an HR user completes each common journey without seeing or entering an
  internal database ID;
- each page has one obvious primary action and returns to fresh canonical data
  after success;
- risky actions show a concise confirmation summary and require a reason when
  policy requires one;
- errors identify the business correction, not the SQL failure;
- keyboard use, search, and full-roster entry are practical on desktop;
- viewer/admin visibility follows the authenticated actor.

## 14. Delivery order

1. **P13.0 integrity foundation**: identity, atomic commands, schedule,
   attendance history, evaluation boundary, learner lifecycle, and dictionary
   reconciliation.
2. **P13.1 application shell v2**: named actor, native page navigation, role
   sections, centralized copy, and work queue.
3. **P13.2 learner journeys**: first-time start, continuation, transfer, profile
   correction, and history.
4. **P13.3 attendance journeys**: session creation, event-time roster, bulk
   save, correction, and approved make-up behavior.
5. **P13.4 final results and monthly review**: eligibility, versioned result,
   completion, manager review, and export.
6. **P13.5 follow-ups and admin**: guided correction routes, accepted legacy
   exceptions, class maintenance, user management, and audit.
7. **P13.6 HR UAT and rollout**: two named HR users complete scenario-based UAT
   against production-shaped fixtures before production access.

## 15. Architecture gate

Phase 13 implementation may resume only when:

- this architecture is owner-approved;
- the replacement-credit make-up attendance policy is implemented and tested;
- each P13.0 blocker has an implementation/test owner;
- schema changes, if any, have forward verification and backup/rollback notes;
- the Phase 11 operational snapshot and owner decisions still validate;
- no UI workflow writes around the application use-case boundary.
