# Domain Docs

This repository uses a single domain context.

## Before exploring or changing code

- Read the root `CONTEXT.md` and use its canonical terms rather than synonyms listed under `_Avoid_`.
- Read the ADRs under `docs/adr/` that touch the planned change.
- Surface any ADR conflict explicitly; never override one silently.

## Layout

```text
/
├── CONTEXT.md
└── docs/
    └── adr/
```

Do not create `CONTEXT-MAP.md` unless the repository is deliberately split into multiple bounded contexts.
