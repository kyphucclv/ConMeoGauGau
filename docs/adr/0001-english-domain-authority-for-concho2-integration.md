# ADR 0001: English domain authority in the ConCho2 integration

- Status: Accepted
- Date: 2026-07-16
- Decision owners: Product owner and maintainers of English Class and ConCho2

## Context

ConCho2 is the broader LTMS and already provides the stronger platform shell:
authentication, authorization, UI, scheduling modes, notifications, reporting,
certificates, and other cross-cutting capabilities. This repository has the
more complete English Class business model for learner history, repeated
courses, transfers, event-time attendance, linked make-up credit, versioned
evaluations, completion, audit, and lossless migration.

Matching tables by similarly named columns would collapse different entity
grains. In particular, a stable Cohort is not the same thing as one Course Run,
a Meeting is not a credited Session Unit, and `class_code + course_name` cannot
identify repeated deliveries.

## Decision

ConCho2 remains the host platform. For English training, the canonical terms,
entity grain, invariants, and transaction semantics in this repository are the
business authority.

The integration will place a small business-command **Interface** at the
English domain boundary. The English domain is a deep **Module**: ConCho2 calls
commands and reads task-oriented projections through this **Seam**, while the
module owns validation, transactions, concurrency control, history, and audit.
ConCho2-specific authentication, UI, calendar, mail, and reporting code talks
to that Interface through **Adapters**.

This is a model-and-behavior migration into ConCho2, not a permanent Python
microservice requirement. The target implementation may be Node/PostgreSQL as
long as it proves semantic parity. There will be no direct UI table writes,
shared-table shortcuts, permanent database-to-database synchronization, or
dual writes. Historical data moves through a staged, outcome-tracked,
reconciled migration followed by a controlled cutover.

## Consequences

- ConCho2 keeps its account, policy, scheduling-mode, communication, reporting,
  certificate, and application-shell capabilities.
- The target schema needs explicit equivalents for Cohort, Cohort Membership,
  Course Run, Run Enrollment, Meeting, Session Unit, linked make-up Attendance,
  and immutable Evaluation Version before English workflows switch over.
- Existing ConCho2 `Class`, `Team`, `Schedule`, `Enrollment`, `Attendance`, and
  `Evaluation` records cannot be reused by name alone; each mapping must prove
  grain and history preservation.
- Each English business event is one atomic transaction with server-derived
  actor attribution and a committed audit event.
- The current application remains a reference implementation and migration
  source until target parity, reconciliation, and cutover acceptance pass.

## Alternatives considered

### Keep both applications and synchronize their databases

Rejected because ownership becomes ambiguous, partial failures create drift,
and two systems can make incompatible decisions about the same learner.

### Copy current tables directly into ConCho2 tables

Rejected because similarly named tables have different row meanings and would
lose repeated-run, transfer, applicability, make-up, and version history.

### Make the current Python application a permanent microservice

Not required. It can be a temporary reference or transition boundary, but the
long-term goal is one ConCho2 platform with the same proven domain behavior.

## References

- [Integration handoff](../integration/concho2-integration-handoff.md)
- [Domain glossary](../../CONTEXT.md)
- [Canonical data dictionary](../../DATA_DICTIONARY.md)
- [Target architecture](../../TARGET_ARCHITECTURE.md)
- [ConCho2 system overview](https://github.com/FinanceBullkk/ConCho2/blob/main/docs/system-overview.md)
