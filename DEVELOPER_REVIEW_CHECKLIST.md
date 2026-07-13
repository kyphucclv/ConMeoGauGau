# Developer Review Checklist

Copy this checklist into each phase review or pull request. Complete it after
implementation and tests, not from memory before the work is run.

## Change identity

- Task/phase:
- Developer:
- Date:
- Files changed:
- Data entities affected:

## Contract review

- [ ] I re-read the relevant sections of `DATA_DICTIONARY.md`.
- [ ] I re-read the relevant invariants in `TARGET_ARCHITECTURE.md`.
- [ ] I wrote the exact row grain below.

Row grain:

```text
One row represents exactly ...
```

Invariants affected:

-

## Output review

- [ ] I reviewed the complete diff, including generated SQL and docs.
- [ ] I inspected actual output records, not only aggregate counts.
- [ ] I checked null behavior, duplicate behavior, and invalid status values.
- [ ] I checked that derived fields are not manually writable.
- [ ] I checked that history is appended/versioned rather than overwritten.
- [ ] I checked transaction boundaries and failure rollback.
- [ ] I checked authorization and secret handling.

Potentially destructive behavior reviewed:

-

## Test evidence

Commands executed:

```text

```

Important output:

```text

```

- [ ] Happy path passed.
- [ ] Invalid-input case passed.
- [ ] Duplicate/idempotency case passed.
- [ ] Historical/transfer/correction case passed where applicable.
- [ ] Fresh-database migration passed where applicable.
- [ ] Legacy-database migration passed where applicable.

## Reconciliation

| Dataset | Source | Canonical | Issues | Ignored | Difference |
|---|---:|---:|---:|---:|---:|
| | | | | | |

Representative records manually traced:

- Normal record:
- Edge case:
- Known anomaly:

- [ ] Every source row has an auditable outcome.
- [ ] KPI/view output was compared with independently calculated examples.

## Final review

- [ ] I reviewed output again after the final test run.
- [ ] Documentation matches implemented behavior.
- [ ] No debug credentials, temporary bypasses, or unsafe admin features remain.
- [ ] Residual risks are listed below.

Residual risks / deferred work:

-

Reviewer decision:

- [ ] Approved
- [ ] Changes required

