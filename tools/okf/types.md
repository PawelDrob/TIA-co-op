---
type: Standard
title: Document types
description: The type values documents use, one per kind of document.
tags: [okf, conventions]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-05T09:14:45-05:00 }
types: [Overview, Standard, Guide, How-To, Rationale, Design, Project, Template]
colors:
  Overview: "#8b5cf6"
  Standard: "#3b82f6"
  Guide: "#10b981"
  How-To: "#f59e0b"
  Rationale: "#ec4899"
  Design: "#06b6d4"
  Project: "#ef4444"
  Template: "#94a3b8"
---

# Document types

Every document has exactly one `type` ([README.md](README.md)). OKF lets each producer choose its own types; these
are the ones the checker knows. The `types` field above is the list the checker uses, and its order is the section
order in generated `index.md` files and the node order in `viz.html`. `colors` gives each type its node color in
`viz.html`.

| Type | What it is | Examples |
|---|---|---|
| `Overview` | An introduction and entry point to a topic or tool | an overview of the repo's tools |
| `Standard` | Rules to follow. Says *what* | a coding style guide, these conventions |
| `Guide` | A reference for a file format, API or tool, used while doing the work | `docs/agent/s7dcl-format.md` |
| `How-To` | Steps for one task, in order | `docs/user/setup.md` |
| `Rationale` | Why the rules are what they are: lessons, trade-offs, rejected options | lessons learned |
| `Design` | The design of a piece of work, or the request it answers | a tool design |
| `Project` | The working notes of one project: current state, backlog, decisions | `docs/project.md` in a TIA project repo |
| `Template` | A starting point for new documents; the checker skips its other fields | a concept template |

A type outside this list is a warning, not an error: OKF readers accept any type. Add a type here (table and `types`
field) before using it.
