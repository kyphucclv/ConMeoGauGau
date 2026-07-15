# Triage Labels

This repository uses human-led issue implementation. The canonical triage roles
map to GitHub labels as follows:

| Canonical role | GitHub label | Meaning |
|---|---|---|
| `needs-triage` | `needs-triage` | A maintainer needs to evaluate the issue. |
| `needs-info` | `needs-info` | Work is waiting on reporter/owner information. |
| `ready-for-agent` | Disabled — do not create or apply | AFK agent implementation is not authorized for this repository. |
| `ready-for-human` | `ready-for-human` | Specification is complete and awaits human implementation. |
| `wontfix` | `wontfix` | The issue will not be actioned. |

Rules:

- Fully specified migration issues receive `ready-for-human`, never
  `ready-for-agent`.
- Do not reinterpret `ready-for-human` as permission for unattended agent work.
- Keep exactly one active triage-state label on an issue when moving it through
  the state machine.
- Existing classification labels such as `bug`, `documentation`, and
  `enhancement` are independent of triage state.
