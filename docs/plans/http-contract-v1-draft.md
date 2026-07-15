# FastAPI HTTP Contract v1 Draft

Status: **Phase 0 contract draft; endpoint-level schemas are finalized inside
their tracer slice before implementation**

## Contract principles

1. Routes are adapters around existing application commands and read models.
2. A confirmed HR event invokes exactly one atomic `BusinessService` command.
3. Route identifiers follow canonical entity grain. Attendance roster addresses
   a credited session unit; learner lifecycle/result commands address a run
   enrollment.
4. The authenticated actor comes only from the server-side session.
5. OpenAPI is the source for generated TypeScript types/client.
6. Dates use `YYYY-MM-DD`; instants use timezone-aware ISO 8601; Decimal values
   are serialized as JSON strings unless a field contract explicitly proves a
   safe numeric representation.
7. List endpoints have stable ordering, filters, and pagination. Default page
   size is 50; maximum is 100.
8. `/api` is same-origin in production. CORS is a development adapter only.

## Common responses

### Error

```json
{
  "code": "invalid_input",
  "message": "Human-safe message",
  "field_errors": {},
  "request_id": "opaque-correlation-id"
}
```

| Condition | Status |
|---|---:|
| Missing, expired, or revoked session | 401 |
| Authenticated actor lacks role | 403 |
| Authorized resource does not exist | 404 |
| Pydantic/request validation | 422 |
| Duplicate, capacity, stale proposal, or lifecycle conflict | 409 |
| Unexpected application/database failure | 500 |

FastAPI validation and `CommandError` responses use the same envelope. A 500
response contains no raw exception or SQL detail.

### Paged list

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0,
  "sort": "stable_server_sort"
}
```

## Access matrix

Parity preserves current Streamlit visibility until an owner approves a change:

| Surface | Admin | Editor | Viewer |
|---|---:|---:|---:|
| Header/dashboard summary | read | read | read |
| HR workspaces | read/write | read/write | no access |
| Reports | read | read | read |
| Audit events | read | no access | no access |
| Owner-approved remediation | execute | no access | no access |

Routes still rely on service-level authorization for commands.

## Health and authentication

| Method and path | Contract |
|---|---|
| `GET /api/health/live` | No DB call; returns process status only. |
| `GET /api/health/ready` | Verifies restricted DB reachability and expected migration/schema state without leaking internals. |
| `POST /api/auth/login` | Validates origin and credentials, applies throttle, creates/rotates server session, sets cookie, returns actor plus CSRF token. |
| `GET /api/auth/me` | Revalidates session and active user; returns actor, allowed navigation, and CSRF token. |
| `POST /api/auth/logout` | Requires CSRF, revokes current session, expires cookie. |

Safe user representation:

```json
{
  "user_id": 1,
  "username": "named.user",
  "full_name": "Named User",
  "role": "editor"
}
```

## Dashboard and learners

| Method and path | Read/command seam | Notes |
|---|---|---|
| `GET /api/dashboard` | `application_snapshot` plus approved home summary | Role-safe summary only. |
| `GET /api/learners` | Endpoint-oriented learner directory query | `q`, lifecycle/status filter, page, page size, stable sort. |
| `GET /api/learners/{employee_id}` | Learner context, course history, authorized employee audit summary | Audit detail remains role-filtered. |
| `GET /api/learners/start-options` | Narrow courses/classes/levels/organization options | No broad all-workflow reference payload. |
| `PATCH /api/learners/{employee_id}/profile` | `create_or_update_employee` | Server confirms path employee matches canonical employee selected by employee code. |
| `POST /api/learners/start` | `onboard_learner` | Includes confirmed current start-session proposal and optional authorized capacity reason. |
| `POST /api/run-enrollments/{run_enrollment_id}/transfer` | `transfer_learner` | Includes destination run, transfer date, confirmed proposal, optional capacity reason. |

Issue #2 freezes the read-only subset as follows:

- `GET /api/dashboard` is available to every authenticated role. `summary`
  contains the six `application_snapshot` counts. `hr_home` contains the six
  `hr_home_snapshot` counts for admin/editor and is `null` for viewer.
- `GET /api/learners` is admin/editor only. Parameters are `q`,
  `learning_status=all|current|not_current`, `class_code`, `course`, `pic`,
  `business_unit`, `job_role`, `page` (default 1), and `page_size` (default 50,
  maximum 100). Blank optional filters are ignored.
- Directory order is always case-insensitive full name, then employee code,
  then `employee_id`. The response reports this as
  `full_name_asc_emp_code_asc`; clients cannot submit an arbitrary SQL sort.
- `GET /api/learners/{employee_id}` is admin/editor only and returns
  `learner`, `course_history`, and `audit_summary`. Audit summary exposes only
  `created_at`, `actor_username`, and `action`; the audit `details` JSON is not
  part of this contract.
- An empty directory query is `200` with an empty page, an unknown authorized
  employee is `404`, an invalid filter/page is `422`, and a viewer request to a
  learner route is `403` using the common error envelope.

FastAPI OpenAPI is exported to `web/openapi.json`; `openapi-typescript`
generates `web/src/api/schema.d.ts`. `npm run api:check` is the contract-drift
gate.

Issue #3 freezes the employee-profile subset as follows:

- `GET /api/learners/profile-options` is admin/editor only and returns only
  active `{id,name}` business-unit and job-role options in stable name order.
- `PATCH /api/learners/{employee_id}/profile` is admin/editor only and requires
  the session CSRF token. The request contains `emp_code` as immutable business
  identity confirmation, editable `full_name`, `employment_status`,
  `business_unit_id`, `job_role_id`, `organization_valid_from`, and the required
  nullable `expected_org_valid_from` stale precondition.
- The command locks the path employee and its current organization assignment.
  A path/body identity mismatch or changed organization version returns `409`
  and rolls back person, organization, and audit writes.
- Unknown organization references return `404`; invalid or extra input returns
  `422`; viewer and bad CSRF requests return `403`. Enrollment IDs/snapshots,
  attendance, derived fields, and audit attribution are forbidden extra input.
- Success returns only `employee_id` and `org_history_action`; React then
  refetches the selected learner detail and invalidates dashboard data without
  refetching the directory.

Issue #4 freezes the learner-start subset as follows:

- `GET /api/learners/start-options` is admin/editor only. It returns active
  organization and entrance-level references plus only planned/active course
  runs, with class/course labels, capacity, current active membership count,
  and the calculated first applicable session.
- `POST /api/learners/start` is admin/editor only and requires the session CSRF
  token. The request accepts a required nullable canonical employee
  precondition, employee/profile inputs, destination run, join date,
  confirmed start-session proposal, and an optional capacity-override
  reason. Enrollment IDs/snapshots, lifecycle, derived counts, and audit actor
  are forbidden input.
- The server recalculates the proposal while holding the destination lock. A
  changed proposal returns `409 stale_proposal`; active enrollment/membership,
  placement, lifecycle, and capacity conflicts use the stable command-error
  envelope and roll back the whole event.
- One successful confirmation invokes `onboard_learner` once. The command owns
  employee/org changes, placement reuse/creation, membership reuse/creation,
  immutable enrollment snapshots, any reasoned capacity override, and the
  named-user `learner.onboard` audit event in one transaction.
- Success returns the run-enrollment and employee IDs plus lifecycle,
  placement action, and membership action. React refetches the affected learner
  and invalidates dashboard data.

Start/transfer returns `409` when authoritative destination state or proposed
start session changed after the user loaded the form.

Issue #5 freezes the learner-transfer subset as follows:

- `GET /api/run-enrollments/{run_enrollment_id}/transfer-options` is
  admin/editor only and accepts only an active enrollment linked to its active
  source membership. It returns the canonical source employee/run/class plus
  planned/active destination runs from different cohorts, including capacity,
  active membership count, and calculated first applicable session.
- `POST /api/run-enrollments/{run_enrollment_id}/transfer` is admin/editor only
  and requires CSRF. The body accepts target run, transfer date, confirmed
  proposal, and optional capacity reason; employee IDs, snapshots, lifecycle,
  membership IDs, derived counts, and audit attribution are forbidden input.
- The command locks and revalidates target proposal and active source state.
  Changed proposal returns `409 stale_proposal`; inactive/retried source,
  same-class destination, closed destination, capacity, and duplicate-active
  conflicts use the stable safe error envelope.
- One successful confirmation closes and links the source enrollment/membership,
  creates the target membership/enrollment with current immutable organization
  snapshots, writes any reasoned capacity override, and records the named-user
  `learner.transfer` audit event in one transaction.
- Success returns only target/source enrollment identity, target membership,
  first session, and whether an override was applied. React refetches the
  affected learner and invalidates dashboard data.

## Attendance

| Method and path | Read/command seam | Notes |
|---|---|---|
| `GET /api/attendance/course-runs` | Narrow active/planned course-run options | Authorized workspace only. |
| `GET /api/course-runs/{course_run_id}/session-units` | Schedule/session-unit read | Includes meeting label/status but session unit is the roster identity. |
| `POST /api/course-runs/{course_run_id}/attendance-sessions` | `create_attendance_session` | One meeting plus one normal session unit atomically. |
| `GET /api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster` | `attendance_roster` | Returns event-time applicable roster. |
| `PUT /api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster` | `save_attendance_roster` | Full roster, exactly once per applicable enrollment. |
| `GET /api/attendance/makeup-options` | `available_makeup_absences` plus eligible makeup units | Narrow workflow response. |
| `POST /api/attendance/{attendance_id}/makeup-credit` | `correct_attendance_makeup` | Requires makeup session unit and reason. |

Roster request:

```json
{
  "records": [
    {
      "run_enrollment_id": 123,
      "effective_status": "Present",
      "note": null
    }
  ]
}
```

The server ignores client attempts to set audit fields, original historical
facts, applicability, employee identity, meeting completion, or denominator
semantics. An incomplete, duplicate, or newly stale roster returns `409`.

Issue #6 freezes the attendance-session and full-roster subset as follows:

- `GET /api/attendance/course-runs` returns only planned/active runs and the
  authoritative next non-cancelled logical sequence. `GET
  /api/course-runs/{course_run_id}/session-units` returns non-make-up units with
  meeting labels/status, but meeting identity is never a roster route key.
- `POST /api/course-runs/{course_run_id}/attendance-sessions` is
  admin/editor-only, requires CSRF, and accepts start time, duration, and the
  confirmed next sequence. The command locks the run and rejects a changed
  sequence as `409 stale_proposal` before creating one planned meeting and one
  normal session unit atomically.
- `GET /api/course-runs/{course_run_id}/session-units/{session_unit_id}/roster`
  returns the event-time applicable roster plus an opaque `roster_token`.
  Planned rows may propose Present; unknown historical facts remain `null`.
- `PUT` on the same roster path requires that token and exactly one
  Present/Absent record per authoritative enrollment. Employee identity,
  original facts, applicability, meeting status, derived counts, and audit
  attribution are forbidden input.
- Changed membership or attendance, retry/double-submit, and concurrent saves
  return `409 stale_roster`. Incomplete/duplicate rosters and cancelled sessions
  also fail without partial attendance writes or meeting completion.
- One successful save upserts the complete roster, marks a planned meeting
  completed, and records row-level before/after audit detail in one transaction.

## Final results

| Method and path | Read/command seam | Notes |
|---|---|---|
| `GET /api/evaluations/pending` | Evaluation outcome read model | Stable filtered list. |
| `GET /api/run-enrollments/{run_enrollment_id}/final-result` | Latest result plus calculated eligibility/history summary | Role-safe response. |
| `POST /api/run-enrollments/{run_enrollment_id}/final-result` | `record_evaluation` | Creates v1 or corrected v2+; v2+ requires correction reason. |
| `POST /api/run-enrollments/{run_enrollment_id}/exam-eligibility-override` | `override_exam_eligibility` | Admin only; requires eligible value and reason. |
| `POST /api/run-enrollments/{run_enrollment_id}/completion-confirmation` | `confirm_completion` | Reject action requires reason where service contract requires it. |

React never submits a trusted calculated eligibility or evaluation version
number. The service calculates and locks the next version.

## Monthly review, follow-ups, and remediation

| Method and path | Read/command seam | Notes |
|---|---|---|
| `GET /api/monthly-review?month=YYYY-MM` | Monthly data and summary | Month normalized server-side to first day. |
| `POST /api/monthly-review/action-summary` | `save_monthly_action_summary` | Admin/editor; immutable next version. |
| `GET /api/monthly-review/export?month=YYYY-MM` | Existing XLSX generator | Safe filename, correct MIME type, private/no-store response. |
| `GET /api/follow-ups` | Operational issues query | Severity/workflow/code filters plus pagination. |
| `GET /api/quality-issues` | Open quality issue query | Pagination and authorized detail. |
| `POST /api/quality-issues/{issue_id}/resolution` | `resolve_quality_issue` | Status and note; history retained. |
| `POST /api/remediation/unknown-org-profiles` | `backfill_unknown_org_profiles` | Admin only; explicit confirmation. |
| `POST /api/remediation/legacy-attendance-exceptions` | Single or approved bulk legacy exception command | Admin only; scope and reason required. |
| `POST /api/remediation/unknown-placements` | `backfill_unknown_business_placements` | Admin only; explicit confirmation. |

Generic `POST /follow-ups/{id}/resolve` is not used for derived operational
issues that require a domain-specific correction or owner-approved remediation.

## Classes and schedule

| Method and path | Read/command seam |
|---|---|
| `GET /api/classes` | Cohort rows, paginated |
| `GET /api/classes/setup-options` | Narrow course/PIC/organization options |
| `POST /api/classes/with-first-course-run` | `create_class_course_run` |
| `POST /api/classes` | `create_cohort` |
| `POST /api/classes/{cohort_id}/pic-assignments` | `assign_pic` |
| `GET /api/course-runs` | Course-run dashboard, paginated/filtered |
| `POST /api/course-runs` | `create_course_run` |
| `POST /api/course-runs/{course_run_id}/status-change` | `change_course_run_status` |
| `GET /api/schedule` | Schedule rows filtered by run/date |
| `POST /api/schedule/meetings-with-units` | `create_meeting_with_units` |
| `PATCH /api/schedule/meetings/{meeting_id}` | `save_meeting` correction/status contract |
| `POST /api/schedule/meetings/{meeting_id}/cancellation` | `cancel_meeting` |
| `POST /api/schedule/meetings/{meeting_id}/session-units` | `add_session_units` |

Distinct routes preserve the difference between a meeting and its one or two
credited session units.

## Reports and audit

| Method and path | Contract |
|---|---|
| `GET /api/reports` | Allow-listed report keys, labels, columns, and metric keys. |
| `GET /api/reports/{report_key}` | Runs only a server-registered report; paginates where semantics allow. |
| `GET /api/reports/{report_key}/metric-definitions` | Approved metric definitions only. |
| `GET /api/audit` | Admin only; page, actor, action, entity, and time filters with a hard maximum. |

## Concurrency contract

- React refetches authoritative context immediately before risky confirmation.
- Streamlit may change the same database during migration; cached React data is
  never treated as a precondition.
- Existing command locks and invariant checks remain authoritative.
- A slice adds a version/updated-at precondition only if its current service
  cannot distinguish a stale edit.
- Duplicate submissions either resolve to one valid outcome or a stable `409`;
  they never produce partial multi-record writes.

## Contract completion rule

Before implementing an endpoint, its slice must add concrete Pydantic request
and response examples, role tests, error cases, and OpenAPI-generated TypeScript
evidence. This draft deliberately does not freeze fields that the existing read
model still needs to narrow.
