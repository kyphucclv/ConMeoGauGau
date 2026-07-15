# Domain Documentation

This is a single-context repository.

## Before Exploring Or Changing The System

Read the relevant parts of:

1. `CONTEXT.md` at the repository root, when it exists.
2. `DATA_DICTIONARY.md` for confirmed field ownership and terminology.
3. `TARGET_ARCHITECTURE.md` for entity grain and business invariants.
4. `PROJECT_RULES.md` for mandatory engineering and verification rules.
5. Relevant records under `docs/adr/`, when they exist.

If `CONTEXT.md` or `docs/adr/` does not yet exist, proceed silently. Create
domain context or an ADR only when a real terminology or architectural decision
needs to be recorded.

## Layout

```text
/
├── CONTEXT.md
└── docs/
    └── adr/
```

Do not introduce `CONTEXT-MAP.md` or per-package domain contexts unless the
repository becomes a genuine multi-context system.

## Vocabulary And Decisions

- Use the canonical business terms defined by the data dictionary and target
  architecture in issue titles, tests, implementation, and documentation.
- Do not replace `course_run`, `session_unit`, `run_enrollment`, or other
  grain-bearing terms with convenient but ambiguous synonyms.
- If a proposal conflicts with an ADR or confirmed invariant, identify the
  conflict explicitly rather than silently overriding it.
