---
type: Overview
title: Developer overview
description: What this repository is for, how its five tools and their helpers fit together, and where to read on when you change them.
tags: [dev, overview]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-06T14:04:29-05:00 }
---

# Developer overview

For people changing the tools. To use them, start at [the README](../../README.md) at the repo root; to set them up, at [Setup](../user/setup.md).

## The goal

An agent changes an offline TIA Portal V20 project through files, and a person sees exactly what it changed.

Two things make that work. The agent reaches TIA through an MCP server over Siemens' Openness API. Each project's exports live in a git repo, so every change is a commit, and a report draws what a commit changed as TIA would show it. Downloads and online work stay with the person.

## How the tools fit together

```
Agent (Claude Code)
  |  skill tia-change, guides in docs\agent\
  |  MCP over stdio
  v
TiaBridge ---------- Openness ----------> TIA Portal V20
  |   |   |
  |   |   +-- exports, logs, commits ---> project repo (git)
  |   |                                      |
  |   +-- validates HMI imports with         |  two revisions
  |   |                                      v
  |   |   TiaHmiGenerator --- preview     TiaChangeReports --- report page
  |   |                                      ^
  |   +-- state files                        |  two export folders
  |          |                               |
  |          v                               |
  |       TiaAgentStatus --- dashboard,      |
  |                          status line,    |
  |                          watcher         |
  |                                          |
  +<-- child over MCP, progress lines -- TiaArchiveCompare (window, runner)
```

| Tool | Language | What it calls | Page |
|---|---|---|---|
| TiaBridge | Windows PowerShell 5.1 | Openness, git, TiaChangeReports, hmipreview | [TiaBridge](tools/tia-bridge.md) |
| TiaChangeReports | Python | hmipreview, for the HMI part | [TiaChangeReports](tools/tia-change-reports.md) |
| TiaHmiGenerator | Python; plain JavaScript in the browser | Nothing of the others | [TiaHmiGenerator](tools/tia-hmi-generator.md) |
| TiaArchiveCompare | Python with tkinter | TiaBridge as a child, TiaChangeReports | [TiaArchiveCompare](tools/tia-archive-compare.md) |
| TiaAgentStatus | Python | Reads the bridge's files; `tools\dashboard\` for its page; TiaBridge as a child for a report run | [TiaAgentStatus](tools/tia-agent-status.md) |

One clone holds them all ([why](decisions.md#scope)). Every Python tool runs on the one `.venv` of the clone.

## Around the tools

- **`docs\agent\`** holds the file formats and Openness facts. An agent reads them while it works, and the bridge's MCP instructions name them by absolute path.
- **`.claude\skills\tia-change\`** holds the order of a change. The other skills there hold how this repo is changed.
- **`tools\`** holds first setup, the checks the commit hook runs, and the session and dashboard tools.
- **Project repos** live outside this repo, by default under `%USERPROFILE%\TIA-Projects`. [The bridge's page](tools/tia-bridge.md#the-project-repo) has their layout.

## Read on

- [Decisions](decisions.md): what is settled, one entry each; [the ADRs](../adr/index.md) for the long ones.
- [Known issues](known-issues.md): what Openness cannot do and what is not solved.
- [Testing](testing.md): what each suite covers. `CONTRIBUTING.md` has the commands.
- [Conventions](conventions.md): where a fact goes, and how a document stays true.
- [Roadmap](roadmap.md): what is planned.
