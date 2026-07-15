# Issue #3 Employee Profile Edit Evidence

Date: 2026-07-15
Status: implemented and verified

## Delivered boundary

- Admin/editor can open a profile editor from React learner detail, load only
  active business-unit/job-role options, and edit full name, employment status,
  organization, and organization effective date.
- Employee code is displayed but disabled. The request repeats it only as an
  immutable business-identity confirmation tied to the path `employee_id`.
- Viewer has no HR navigation and receives `403` from both options and mutation
  routes. Every profile mutation requires the session CSRF token.
- React refetches the selected learner after save, invalidates dashboard data,
  and does not refetch the learner directory.

## Transaction and conflict behavior

- `create_or_update_employee` retains its existing public interface and now
  accepts optional path-identity and current-org preconditions for HTTP callers.
- The command locks the canonical employee and current organization row before
  validating identity/version. Identity mismatch returns `identity_conflict`;
  changed organization state returns `stale_profile`.
- A stale request that attempted to change name, status, and organization left
  the concurrent profile untouched and created no audit event.
- Missing business-unit/job-role references return `404` and roll back the
  earlier employee update in the same transaction.
- A successful organization change creates the new current history row while
  preserving existing run-enrollment BU/role snapshots.

## Input and audit safety

- The generated request schema forbids extra fields. Tests prove submitted
  enrollment identity and forged audit actor fields return `422` with no write.
- Only the named server-session actor can create the `employee.upsert` audit
  event. The response exposes no trusted client audit fields.
- The response is intentionally narrow: employee ID and whether organization
  history was unchanged, changed, or created.

## Verification

- `python -m pytest tests/ -q`: 46 tests passed.
- `npm test`: 3 tests passed, including exact targeted-refetch assertions.
- `npm run build`: production Vite/TypeScript build passed.
- `npm run test:e2e`: 2 Chrome tests passed; the admin journey now includes
  edit, save, refreshed heading, success state, and named audit action.
- Manual connected-Chrome verification confirmed the responsive form layout,
  disabled employee code, selected reference values, effective date, and Cancel
  behavior. The temporary browser tab and server were closed afterward.
