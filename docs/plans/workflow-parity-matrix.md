# Streamlit To React Workflow Parity Matrix

Status: **Issue 13 technical inventory complete; target-host proof, HR UAT and
stabilization approval pending**

Current visibility is preserved unless an owner approves a product change:

- admin/editor: HR workspace and reports;
- viewer: header summary and reports, no HR workspace;
- admin only: audit events and owner-approved remediation actions.

## Authentication and shell

| Workflow | Current entry/read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Named sign-in | `streamlit_app.render_sign_in`, `auth.authenticate` | Session-state assignment only | all active users | none | Secure sign-in foundation | Verified in Issue #1; opaque durable session, exact-origin login and bounded rate limit |
| Session revalidation | `active_user_by_id` on rerun | none | all active users | none | Secure sign-in foundation | Verified in Issue #1; active user/session revalidated server-side with absolute and idle expiry |
| Sign out | sidebar session-state removal | none | all | none | Secure sign-in foundation | Verified in Issue #1; server row revoked before secure cookie expiry and CSRF required |
| Header summary | `application_snapshot` | none | admin/editor/viewer | none | Read-only shell | Verified in Issue #2; viewer receives summary and `hr_home=null` |
| HR home | `hr_home_snapshot` | none | admin/editor | none | Read-only shell | Verified in Issue #2; React owns this read surface |

## Learners

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Directory/search | `learner_directory_rows` with client filtering | none | admin/editor | none | Read-only shell | Verified in Issue #2; React/API own read-only search, filters, sort, and paging |
| Learner detail/current journey | `learner_journey_context` | none | admin/editor | none | Read-only shell | Verified in Issue #2; fixed-fixture API/UI/Playwright coverage |
| Course history | `learner_course_history` | none | admin/editor | none | Read-only shell | Verified in Issue #2; stable newest-first order |
| Learner audit summary | `employee_audit_rows` | none | admin/editor | none | Read-only shell | Verified in Issue #2; only when/actor/action exposed, no details JSON |
| Create/update employee profile | Learner context, business-unit/job-role refs | `create_or_update_employee` | admin/editor | `employee.upsert` | Profile slice | Verified in Issue #3; React owns profile edit with identity/org stale preconditions |
| First-time/returning learner start | Journey/capacity/start-session context | `onboard_learner` | admin/editor | `learner.onboard` plus owned related events | Learner start slice | Verified in Issue #4; React confirms destination, capacity, and exact start-session proposal before one atomic command |
| Cross-class learner transfer | Journey/capacity/start-session context | `transfer_learner` | admin/editor | `learner.transfer`, capacity override when applicable | Transfer slice | Verified in Issue #5; React addresses active run enrollment and confirms cross-class capacity/start proposal before one atomic transfer |

## Attendance

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Propose/create attendance session | Workflow refs and `propose_next_attendance_session` | `create_attendance_session` | admin/editor | `attendance.session.create` | Attendance roster slice | Verified in Issue #6; React confirms the locked next sequence before one meeting/unit transaction |
| Event-time roster | `attendance_roster(course_run_id, session_unit_id)` | none | admin/editor through current UI | none | Attendance roster slice | Verified in Issue #6; course run plus session unit is identity and historical unknowns remain blank |
| Full-roster save | Event-time roster reload | `save_attendance_roster` | admin/editor | `attendance.roster.save` | Attendance roster slice | Verified in Issue #6; opaque roster precondition, exact membership, concurrent conflict, and atomic row-level audit covered |
| Make-up options | `available_makeup_absences` plus session refs | none | admin/editor | none | Make-up slice | Verified in Issue #7; each completed direct absence is returned with only later, same-run, non-cancelled and unoccupied make-up units |
| Link make-up credit | Selected absence and makeup session unit | `correct_attendance_makeup` | admin/editor | `attendance.makeup` | Make-up slice | Verified in Issue #7; original remains Absent, linked fact is Present, denominator adds zero, and concurrent duplicate commits once |

## Final results

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Pending/outcome list | `evaluation_outcome_rows` | none | admin/editor | none | Final-results slice | Verified in Issue #8; all run enrollments are reviewable with unevaluated outcomes first |
| Calculated eligibility | `calculate_exam_eligibility` | read command | admin/editor through current UI | none | Final-results slice | Verified in Issue #8; attendance-derived value and source are server-owned |
| Eligibility override | Latest calculation | `override_exam_eligibility` | admin only | `eligibility.override` | Final-results slice | Verified in Issue #8; explicit value and non-blank reason create a new immutable version |
| Record/correct final result | Outcome and reference data | `record_evaluation` | admin/editor | `evaluation.record` | Final-results slice | Verified in Issue #8; v1 is created once and version 2+ requires a correction reason |
| Suggest completion | Enrollment/result context | `suggest_completion` | admin/editor | completion audit action | Final-results slice | Verified in Issue #8; suggestion preserves enrollment lifecycle state |
| Confirm/reject completion | Suggested completion | `confirm_completion` | admin only | completion audit action | Final-results slice | Verified in Issue #8; confirmation completes and rejection requires a reason without completing |

## Monthly review and reports

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Monthly overview/detail | `monthly_review_data`, `monthly_review_summary` | none | admin/editor | none | Monthly-review slice | Verified in Issue #9; `YYYY-MM` is normalized server-side and summary/detail share one read model |
| Proposed monthly actions | `proposed_monthly_actions` | none | admin/editor | none | Monthly-review slice | Verified in Issue #9; server-derived proposal remains distinct from saved HR truth |
| Save action summary | Current monthly data | `save_monthly_action_summary` | admin/editor | `monthly_review.action_summary.save` | Monthly-review slice | Verified in Issue #9; named immutable versions remain safe under concurrent saves |
| Export XLSX | `monthly_review_xlsx` | none | admin/editor | none | Monthly-review slice | Verified in Issue #9; displayed month/conclusion, safe filename, private cache, MIME, sheets, and values match |
| Registered reports | `REPORTS`, `run_report`, metric definitions | none | admin/editor/viewer | none | Reports/audit slice | Verified in Issue #12; server registry owns SQL, approved columns, definitions, and bounded pagination |

## Follow-ups and remediation

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Operational inbox/filter/detail | `operational_issue_rows` | none | admin/editor | none | Follow-ups slice | Verified in Issue #10; derived rows are filtered/paged and remain separate from durable issue lifecycle |
| Logged quality issues | `open_quality_issue_rows` | none | admin/editor | none | Follow-ups slice | Verified in Issue #10; open/resolved/ignored history and original details remain inspectable |
| Resolve/ignore quality issue | Selected quality issue | `resolve_quality_issue` | admin/editor | quality issue resolution audit | Follow-ups slice | Verified in Issue #10; note, actor, time, source, and original details retained |
| Backfill unknown org profile | Operational issues | `backfill_unknown_org_profiles` | admin only | remediation audit | Follow-ups slice | Verified in Issue #10; separate confirmed endpoint with owner reason |
| Approve one/all legacy attendance exceptions | Operational issues | dedicated exception command | admin only | remediation audit | Follow-ups slice | Verified in Issue #10; one exception creates zero attendance facts |
| Backfill unknown placement | Operational issues | `backfill_unknown_business_placements` | admin only | remediation audit | Follow-ups slice | Verified in Issue #10; separate confirmed endpoint with owner reason |
| Resolve schedule conflict | Operational issue details | `cancel_meeting` | admin/editor in current schedule conflict form; remediation section itself admin-oriented | `meeting.cancel` | Follow-ups/class-schedule slices | Verified in Issues #10/#11; explicit duplicate choice and reason preserve the meeting schedule |

## Class and schedule administration

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Create class with first course run/PIC | Workflow refs and proposed code | `create_class_course_run` | admin/editor | class/run/PIC audit events | Classes/schedule slice | Verified in Issue #11; one atomic command and rollback test |
| Employee admin search/upsert | `employee_search_rows` | `create_or_update_employee` | admin/editor | `employee.upsert` | Profile or classes slice | Profile edit is canonical in learner detail; separate admin search UI remains deferred |
| List/create class record | `cohort_rows` | `create_cohort` | admin/editor | cohort creation audit | Classes/schedule slice | Superseded in target UI by Issue #11 atomic class + first run/PIC command; no separate partial-create React command |
| Assign PIC employee/team label | Workflow refs | `assign_pic` | admin/editor | PIC assignment audit | Classes/schedule slice | Verified in Issue #11; label remains non-identity |
| List/add course run | `course_run_dashboard_rows` | `create_course_run` | admin/editor | run creation audit | Classes/schedule slice | Verified in Issue #11; stable paging and concurrent run numbering |
| Change course-run status | Course-run dashboard | `change_course_run_status` | admin/editor | status audit | Classes/schedule slice | Verified in Issue #11; lifecycle conflict retained |
| List schedule | `schedule_rows` | none | admin/editor | none | Classes/schedule slice | Verified in Issue #11; meetings aggregate their separate unit identities |
| Create meeting with one/two units | Schedule and refs | `create_meeting_with_units` | admin/editor | `meeting.units.create` | Classes/schedule slice | Verified in Issue #11; one transaction and two-unit browser journey |
| Correct meeting | Schedule row | `save_meeting` | admin/editor | `meeting.correct`/status | Classes/schedule slice | Verified in Issue #11; reason and before/after retained |
| Cancel meeting | Schedule row | `cancel_meeting` | admin/editor | `meeting.cancel` | Classes/schedule slice | Verified in Issue #11; reason required and schedule preserved |
| Add session units | Schedule row | `add_session_units` | admin/editor | `meeting.units.add` | Classes/schedule slice | Verified in Issue #11; one/two-unit rules retained |

## Audit and out-of-scope surfaces

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Global audit events | `audit_event_rows(limit=300)` | none | admin only | none | Reports/audit slice | Verified in Issue #12; parameterized filters, bounded pages, and sanitized details |
| User creation/deactivation UI | No Streamlit UI; operator/service only | `UserAdminService` | admin/operator | user audit | Out of parity | Separate approved feature after cutover |
| First-admin bootstrap | Operator script | `bootstrap_first_admin` | operator | bootstrap audit | Foundation keeps script | Never application startup |

## Slice completion columns

For each row, replace `Inventoried` with links/references to:

1. approved HTTP/OpenAPI contract;
2. backend integration test;
3. React/Playwright evidence;
4. fixed-fixture or production-like parity comparison;
5. HR owner UAT result;
6. current canonical frontend ownership and fallback path.

## Issue 13 production ownership and fallback

All target workflows above have approved HTTP/OpenAPI, disposable database and
React/browser evidence in Issues #1-#12. The repository gates add production-
style load, accessibility, security and failure-path evidence in Issue #13.
Named HR UAT and target-host proof remain pending and must not be inferred from
automated tests.

| Workflow group | Canonical owner after approved cutover | Stabilization fallback | UAT/cutover state |
|---|---|---|---|
| Authentication and shell | React/FastAPI | Tagged schema-compatible Streamlit route | Pending named HR/host approval |
| Learners/profile/start/transfer | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Attendance and make-up | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Final results/completion | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Monthly review/export | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Follow-ups/remediation | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Classes and schedule | React/FastAPI services | Streamlit using the same services/database | Pending named HR approval |
| Registered reports/restricted audit | React/FastAPI | Streamlit using the same registered definitions/database | Pending named HR approval |
| User administration/bootstrap | Operator/service only; out of parity | Same operator path | Separate feature/approval |

Fallback switches routing only. Both frontends must remain on the same canonical
schema and transactional service layer; dual-write, reverse migration and UI-
rollback database restore are prohibited. Streamlit retirement requires a
separate explicit approval after the Issue #13 stabilization window.
