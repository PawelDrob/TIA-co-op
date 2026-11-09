---
type: Standard
title: Conventions
description: The documentation convention of this repo, where a fact goes and how a document stays true, with pointers for code and names.
tags: [dev, conventions]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-05T13:52:28-05:00 }
---

# Conventions

## Documents

**Each fact has one home, by who reads it.** Others link to it.

| Reader | Home |
|---|---|
| Someone using a tool | The tool's `README.md`, longer how-tos in [`docs\user\`](../user/index.md) |
| An agent working on a TIA project | [`docs\agent\`](../agent/index.md), `.claude\skills\tia-change\`, the bridge's tool descriptions |
| Someone changing a tool | `docs\dev\`, this folder |
| Someone sending a change | `CONTRIBUTING.md`, for commands and how a change gets in |
| An agent changing this repo | `AGENTS.md`, the other skills |
| Review | `CODING_STANDARDS.md` |
| Anyone unsure of a word | `GLOSSARY.md` |
| Why something hard to reverse is so | [`docs\adr\`](../adr/index.md), with one entry in [Decisions](decisions.md) |

**A dev page:**

- says what is true now, in the present tense. History is in git.
- holds no ticket numbers, session dates or names of people, as a reader outside has none of them.
- holds what the code does not say quickly: how the parts meet, the contracts between them, and why. A tool's options stay in its `--help` or head comment.
- links to `docs\user\` and `docs\agent\` rather than repeating them, and names code by path.

**When the code and a document disagree, the code wins:** fix the document.

**Private notes stay private.** Nothing tracked links to `.scratch\`, the folder of local notes git ignores.

**The format** is OKF v0.2. [The checker's README](../../tools/okf/README.md) holds its rules: a document's header, file names, links, `index.md` and `log.md`. `AGENTS.md`, section Documentation, says when to run it, and the hook checks every commit that touches `docs\`.

## Code

`CODING_STANDARDS.md` is what review reads for. Two rules shape how a tool is written:

- **PowerShell scripts stay ASCII:** `CONTRIBUTING.md`, Tests, says why.
- **Stdout is the protocol:** `CODING_STANDARDS.md`, Bridge output. The Archive Compare runner holds to it too: its stdout is its events.

## Names

Made-up samples only: `CODING_STANDARDS.md`, Names. `GLOSSARY.md` fixes the words, including the ones to avoid.
