# Issue #10 Follow-up and Remediation Evidence

Date: 2026-07-16
Status: approved

## Contract and grain

One operational item is one currently true, derived condition in
`v_operational_data_issues`; it has no mutable resolution lifecycle. One
`data_quality_issues` row is one durable imported or manually logged issue and
retains its source, original details, status, resolution note, actor, and time.
Domain-specific conditions are corrected through their existing service
commands rather than a generic derived-issue resolver.

## Authorization and safety

- Admin/editor can filter and page operational and logged issue reads.
- Admin/editor can resolve or ignore a logged quality issue with CSRF and a
  non-blank note; original details and source provenance remain unchanged.
- Unknown organization, legacy attendance exception, unknown placement, and
  schedule-conflict actions have separate request models and service calls.
- Owner-approved remediation is admin-only. Legacy attendance exceptions write
  acknowledgement and audit records but zero attendance facts.
- Client-supplied actor or resolution-history fields are forbidden.

## Verification

- Four targeted HTTP integration tests cover filtered paging, durable history,
  named attribution, role/CSRF/forged fields, and zero invented attendance.
- React component tests invoke every approved action family and the logged-issue
  resolution journey through its dedicated endpoint.
- Chrome browser evidence covers inbox navigation, logged resolution, and all
  four approved-action forms.
- Full regression: 91 Python tests, 13 React tests, and all four Playwright
  journeys passed; production build plus Phase 5 reporting, Phase 7 workflow,
  and Phase 13 dictionary gates passed.
- Manual desktop review passed for filters, priority badges, details disclosure,
  paging, ledger layout, and confirmation cards; browser console was clean.

## Review decision

- [x] Approved
- [ ] Changes required
