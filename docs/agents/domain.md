---
type: Standard
title: Domain docs for agent skills
description: How the engineering skills read GLOSSARY.md and docs/adr/ in this single-context repo, and the header an ADR needs here.
tags: [agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-03T15:43:12-05:00 }
---

# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- [`GLOSSARY.md`](../../GLOSSARY.md) at the repo root.
- [`docs/adr/`](../adr/index.md): read ADRs that touch the area you're about to work in.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── docs/adr/
│   └── 0001-<slug>.md
└── TiaBridge/, TiaChangeReports/, ...
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. A concept missing there is a gap to note for `/domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0002 (bridge registered per user), but worth reopening because…_

## A new ADR here

`docs/` is a checked documentation bundle, so an ADR needs what `/domain-modeling`'s format leaves out: a header with `type: Rationale`, `title`, `description` and `generated`, and a line in `docs/log.md`. The pre-commit hook refuses a commit without the header ([the bundle's rules](../../tools/okf/README.md)). `GLOSSARY.md` sits outside the bundle and has no header.
