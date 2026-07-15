# FastAPI + React Migration: Published Issue Breakdown

Status: **Approved and published to GitHub Issues on 2026-07-15**

The breakdown follows tracer-bullet vertical slices. Each issue is independently
demoable and crosses the necessary schema, HTTP, UI, test, and operational seams.

## Proposed slices

1. **Prove secure same-origin sign-in on the target topology**
   - Blocked by: green database-backed baseline and target-host access.
   - Covers: health/readiness, pool lifecycle, `app_sessions`, login/me/logout,
     CSRF, minimal React protected shell, same-origin test deployment, and
     end-to-end authentication evidence.

2. **Deliver the read-only HR home and learner directory journey**
   - Blocked by: 1.
   - Covers: dashboard, learner search/pagination, learner detail/history,
     viewer-vs-editor navigation, generated client, parity comparison, and
     Playwright read journey.

3. **Edit an employee profile safely from learner detail**
   - Blocked by: 2.
   - Covers: profile options/read context, profile form, one
     `create_or_update_employee` command, validation/conflict response, audit,
     query invalidation, and end-to-end evidence.

4. **Start a first-time or returning learner in a class**
   - Blocked by: 2.
   - Covers: narrow start options, current capacity/start-session proposal,
     confirmation, `onboard_learner`, capacity override, stale proposal conflict,
     audit, rollback, and lifecycle variants.

5. **Transfer an active run enrollment between classes**
   - Blocked by: 4.
   - Covers: run-enrollment identity, destination proposal, transfer confirmation,
     `transfer_learner`, capacity conflict/override, historical chain, audit, and
     concurrent transfer behavior.

6. **Create an attendance session and save its full event-time roster**
   - Blocked by: 1.
   - Covers: course-run/session-unit selection, session creation, event-time
     roster, atomic complete-roster save, stale membership conflict, audit,
     historical roster parity, and browser workflow.

7. **Credit one original absence through a later make-up session**
   - Blocked by: 6.
   - Covers: absence/make-up options, reasoned `correct_attendance_makeup`, original
     absence preservation, zero denominator addition, duplicate/concurrency
     rejection, audit, and end-to-end evidence.

8. **Record, correct, and authorize a learner's final result**
   - Blocked by: 6.
   - Covers: pending results, calculated eligibility, versioned result command,
     admin override, completion confirmation, reasons, role matrix, audit, and
     concurrent version behavior.

9. **Review a month, save conclusions, and export the workbook**
   - Blocked by: 1.
   - Covers: monthly read/summary parity, immutable action-summary command,
     generated XLSX download, authorization, audit, and fixed-fixture output
     comparison.

10. **Resolve operational and logged data follow-ups through approved actions**
    - Blocked by: 1.
    - Covers: filtered/paginated inbox, quality-issue resolution, admin-only
      remediation actions, explicit confirmations, preserved issue history,
      audit, and forbidden-role tests.

11. **Administer classes, course runs, PIC assignments, and schedule events**
    - Blocked by: 1.
    - Covers: class/run lists and options, atomic class-with-run creation, PIC,
      run lifecycle, meeting/unit creation, correction/cancellation, reasons,
      audit, concurrency, and meeting-vs-session-unit contract tests.

12. **Serve registered reports and restricted audit history**
    - Blocked by: 1.
    - Covers: allow-listed report registry, metric definitions, pagination,
      viewer report access, admin-only audit filters, payload privacy, parity, and
      browser evidence.

13. **Prove production readiness and perform controlled workflow cutover**
    - Blocked by: 2-12.
    - Covers: full parity matrix, accessibility/security/load tests, connection
      budget, TLS/service/runbook, backup/restore check, fallback rehearsal,
      HR UAT, dated stabilization window, and ownership switch.

14. **Retire Streamlit after the stabilization gate**
    - Blocked by: 13 and explicit owner retirement approval.
    - Covers: archived compatible release, removal of Streamlit runtime/UI-only
      paths, replacement verification, documentation update, retained rollback
      artifacts, and clean full-gate evidence.

## Proposed dependency shape

```text
1 secure foundation
├── 2 read-only home/learners ──┬── 3 profile
│                               ├── 4 learner start ── 5 transfer
├── 6 attendance roster ────────┬── 7 make-up
│                               └── 8 final results
├── 9 monthly review
├── 10 follow-ups
├── 11 classes/schedule
└── 12 reports/audit

2-12 -> 13 production cutover -> 14 Streamlit retirement
```

Issues 2, 6, 9, 10, 11, and 12 may proceed in parallel after issue 1 if separate
owners are available. Issue 13 waits for every parity slice, not merely the
nominal feature screens.

## Published issues

All issues are classified as `enhancement` and use the human-led triage state
`ready-for-human`. No `ready-for-agent` label was created or applied.

| Issue | Slice |
|---|---|
| [#1](https://github.com/kyphucclv/ConMeoGauGau/issues/1) | Prove secure same-origin sign-in on the target topology |
| [#2](https://github.com/kyphucclv/ConMeoGauGau/issues/2) | Deliver the read-only HR home and learner directory journey |
| [#3](https://github.com/kyphucclv/ConMeoGauGau/issues/3) | Edit an employee profile safely from learner detail |
| [#4](https://github.com/kyphucclv/ConMeoGauGau/issues/4) | Start a first-time or returning learner in a class |
| [#5](https://github.com/kyphucclv/ConMeoGauGau/issues/5) | Transfer an active run enrollment between classes |
| [#6](https://github.com/kyphucclv/ConMeoGauGau/issues/6) | Create an attendance session and save its full event-time roster |
| [#7](https://github.com/kyphucclv/ConMeoGauGau/issues/7) | Credit one original absence through a later make-up session |
| [#8](https://github.com/kyphucclv/ConMeoGauGau/issues/8) | Record, correct, and authorize a learner final result |
| [#9](https://github.com/kyphucclv/ConMeoGauGau/issues/9) | Review a month, save conclusions, and export the workbook |
| [#10](https://github.com/kyphucclv/ConMeoGauGau/issues/10) | Resolve operational and logged data follow-ups through approved actions |
| [#11](https://github.com/kyphucclv/ConMeoGauGau/issues/11) | Administer classes, course runs, PIC assignments, and schedule events |
| [#12](https://github.com/kyphucclv/ConMeoGauGau/issues/12) | Serve registered reports and restricted audit history |
| [#13](https://github.com/kyphucclv/ConMeoGauGau/issues/13) | Prove production readiness and perform controlled workflow cutover |
| [#14](https://github.com/kyphucclv/ConMeoGauGau/issues/14) | Retire Streamlit after the stabilization gate |
