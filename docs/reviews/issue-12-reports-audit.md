# Issue #12 Reports and Audit Evidence

Date: 2026-07-16
Status: approved

## Registered report boundary

The browser submits only a report key. The server resolves that key against the
static `REPORTS` registry and owns SQL, approved columns, metric definitions,
ordering, page size, and offset. Unknown keys, including SQL-like strings, use
the stable safe error contract and are never executed.

## Authorization and privacy

- Admin/editor/viewer can run registered reports with a maximum page size of 100.
- Only admin can access audit history; editor/viewer receive no event count or
  payload detail.
- Audit filters are parameterized and bounded. Password, secret, token, hash,
  session, connection, database URL, and SQL-shaped detail keys are recursively
  removed before serialization, while business `session_unit_ids` remain
  available as approved audit evidence.
- Metric definitions come from the canonical registered definition view and are
  displayed next to report output.

## Verification

- Three targeted HTTP integration tests cover catalog/result parity, pagination,
  invalid/injection-like keys, maximum limits, role isolation, filtering, and
  recursive sensitive-key removal.
- React tests verify viewer report access and admin-only audit navigation.
- Chrome browser evidence covers report selection/results, metric definitions,
  restricted audit filtering, and the viewer navigation contract.
- Phase 5 reporting gate passed after the report runner was made pageable; full
  regression completed with 91 Python tests, 13 React tests, all four
  Playwright journeys, and a production build.
- Manual desktop review passed for the report registry, metric cards, wide-table
  containment, audit details, and pagination; console was clean.

## Review decision

- [x] Approved
- [ ] Changes required
