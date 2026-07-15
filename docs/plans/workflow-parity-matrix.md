# Streamlit To React Workflow Parity Matrix

Status: **Phase 0 inventory; acceptance/evidence columns are completed per
tracer slice**

Current visibility is preserved unless an owner approves a product change:

- admin/editor: HR workspace and reports;
- viewer: header summary and reports, no HR workspace;
- admin only: audit events and owner-approved remediation actions.

## Authentication and shell

| Workflow | Current entry/read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Named sign-in | `streamlit_app.render_sign_in`, `auth.authenticate` | Session-state assignment only | all active users | none | Secure sign-in foundation | Inventoried |
| Session revalidation | `active_user_by_id` on rerun | none | all active users | none | Secure sign-in foundation | Inventoried |
| Sign out | sidebar session-state removal | none | all | none | Secure sign-in foundation | Inventoried |
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
| Cross-class learner transfer | Journey/capacity/start-session context | `transfer_learner` | admin/editor | `learner.transfer`, capacity override when applicable | Transfer slice | Inventoried |

## Attendance

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Propose/create attendance session | Workflow refs and `propose_next_attendance_session` | `create_attendance_session` | admin/editor | `attendance.session.create` | Attendance roster slice | Inventoried |
| Event-time roster | `attendance_roster(course_run_id, session_unit_id)` | none | admin/editor through current UI | none | Attendance roster slice | Session unit, not meeting, is identity |
| Full-roster save | Event-time roster reload | `save_attendance_roster` | admin/editor | `attendance.roster.save` | Attendance roster slice | Must remain one transaction |
| Make-up options | `available_makeup_absences` plus session refs | none | admin/editor | none | Make-up slice | Inventoried |
| Link make-up credit | Selected absence and makeup session unit | `correct_attendance_makeup` | admin/editor | `attendance.makeup` | Make-up slice | Original absence/denominator invariant required |

## Final results

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Pending/outcome list | `evaluation_outcome_rows` | none | admin/editor | none | Final-results slice | Inventoried |
| Calculated eligibility | `calculate_exam_eligibility` | read command | admin/editor through current UI | none | Final-results slice | Server calculated |
| Eligibility override | Latest calculation | `override_exam_eligibility` | admin only | `eligibility.override` | Final-results slice | Reason required |
| Record/correct final result | Outcome and reference data | `record_evaluation` | admin/editor | `evaluation.record` | Final-results slice | Version 2+ correction reason |
| Suggest completion | Enrollment/result context | `suggest_completion` | admin/editor | none unless service changes state | Final-results slice | Preserve service behavior |
| Confirm/reject completion | Suggested completion | `confirm_completion` | admin/editor | completion audit action | Final-results slice | Rejection reason behavior retained |

## Monthly review and reports

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Monthly overview/detail | `monthly_review_data`, `monthly_review_summary` | none | admin/editor | none | Monthly-review slice | Numbers must reconcile |
| Proposed monthly actions | `proposed_monthly_actions` | none | admin/editor | none | Monthly-review slice | Derived, not committed truth |
| Save action summary | Current monthly data | `save_monthly_action_summary` | admin/editor | `monthly_review.action_summary.save` | Monthly-review slice | Immutable versions |
| Export XLSX | `monthly_review_xlsx` | none | admin/editor | none | Monthly-review slice | Filename/content parity |
| Registered reports | `REPORTS`, `run_report`, metric definitions | none | admin/editor/viewer | none | Reports/audit slice | Allow-listed keys only |

## Follow-ups and remediation

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Operational inbox/filter/detail | `operational_issue_rows` | none | admin/editor | none | Follow-ups slice | Preserve derived issue detail/navigation |
| Logged quality issues | `open_quality_issue_rows` | none | admin/editor | none | Follow-ups slice | Inventoried |
| Resolve/ignore quality issue | Selected quality issue | `resolve_quality_issue` | admin/editor | quality issue resolution audit | Follow-ups slice | Original issue retained |
| Backfill unknown org profile | Operational issues | `backfill_unknown_org_profiles` | admin only | remediation audit | Follow-ups slice | Owner-approved confirmation |
| Approve one/all legacy attendance exceptions | Operational issues | dedicated exception command | admin only | remediation audit | Follow-ups slice | Never infer attendance |
| Backfill unknown placement | Operational issues | `backfill_unknown_business_placements` | admin only | remediation audit | Follow-ups slice | Owner-approved confirmation |
| Resolve schedule conflict | Operational issue details | `cancel_meeting` | admin/editor in current schedule conflict form; remediation section itself admin-oriented | `meeting.cancel` | Follow-ups/class-schedule slices | Role contract requires explicit owner review |

## Class and schedule administration

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Create class with first course run/PIC | Workflow refs and proposed code | `create_class_course_run` | admin/editor | class/run/PIC audit events | Classes/schedule slice | One atomic event |
| Employee admin search/upsert | `employee_search_rows` | `create_or_update_employee` | admin/editor | `employee.upsert` | Profile or classes slice | Profile edit is canonical in learner detail; separate admin search UI remains deferred |
| List/create class record | `cohort_rows` | `create_cohort` | admin/editor | cohort creation audit | Classes/schedule slice | Inventoried |
| Assign PIC employee/team label | Workflow refs | `assign_pic` | admin/editor | PIC assignment audit | Classes/schedule slice | Label remains non-identity |
| List/add course run | `course_run_dashboard_rows` | `create_course_run` | admin/editor | run creation audit | Classes/schedule slice | Inventoried |
| Change course-run status | Course-run dashboard | `change_course_run_status` | admin/editor | status audit | Classes/schedule slice | Lifecycle conflict tested |
| List schedule | `schedule_rows` | none | admin/editor | none | Classes/schedule slice | Meeting/unit distinction retained |
| Create meeting with one/two units | Schedule and refs | `create_meeting_with_units` | admin/editor | `meeting.units.create` | Classes/schedule slice | One transaction |
| Correct meeting | Schedule row | `save_meeting` | admin/editor | `meeting.correct`/status | Classes/schedule slice | Change reason required where applicable |
| Cancel meeting | Schedule row | `cancel_meeting` | admin/editor | `meeting.cancel` | Classes/schedule slice | Reason required |
| Add session units | Schedule row | `add_session_units` | admin/editor | `meeting.units.add` | Classes/schedule slice | One/two-unit rules retained |

## Audit and out-of-scope surfaces

| Workflow | Current read | Current command | Roles | Expected audit | Target slice | Evidence/status |
|---|---|---|---|---|---|---|
| Global audit events | `audit_event_rows(limit=300)` | none | admin only | none | Reports/audit slice | Add server pagination/hard maximum |
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
