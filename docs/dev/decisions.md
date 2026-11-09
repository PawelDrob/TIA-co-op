---
type: Rationale
title: Decisions
description: The decisions that shape the tools as they stand, one short entry each, with the reason.
tags: [dev, decisions]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-08T21:16:15-05:00 }
---

# Decisions

What holds today, and why. A decision with a long argument also has an [ADR](../adr/index.md). When one changes, change its entry here; git keeps the old one.

## Scope

- **Offline only.**
- **TIA Portal V20, WinCC Comfort and Advanced.**
- **The whole toolkit ships, every tool marked experimental.** The tools call each other, so one clone holds them all.

## The bridge

- **Its own stdio MCP server in Windows PowerShell 5.1, with no install and no build.** PowerShell 5.1 is on every machine that runs TIA and reaches Openness directly, so nothing needs compiling for the bridge itself. It covers PLC blocks, HMI screens and library types on V20.
- **One long-running process per client, not one per call.** Attaching takes seconds, and each new program meets TIA's access dialog.
- **One bridge per TIA.**
- **Bulk content goes through files, never through tool results.** The agent edits with its normal tools, and results stay small: paths, counts, states and messages. Every full result is in the project repo's `logs\`.
- **One git repo per project, and a repo belongs to one `.ap20` path.** A project at a new path is a question for the person (moved, or a different project), because an export committed to the wrong repo reads as a change.
- **Archive before the first write.** Writes are refused until the session's archive exists, and only the person can skip it. It is the way back from what a session saves.
- **With a session archive, a save goes through and says what it stores.** Uncompiled writes and known compile errors are named in `savedWith`, not refused, as a project that cannot compile as a whole could otherwise never save. A failed write still refuses. Without an archive the stricter rules hold ([save rules](tools/tia-bridge.md#save-rules)).
- **Only the user's own words lift a guard.** The agent never decides these itself. The list is in the bridge's MCP instructions (`TiaBridge\Guides.ps1`).
- **A save also stores the person's unsaved edits,** and the tool says so: Openness saves a project only as a whole.
- **A background session never touches a TIA with a window.** It runs in a TIA the bridge starts, and only when the person asks, as one holds several GB of memory.
- **Agents open and close projects only when told.** `project_open` when the person names the project, `project_close` when the person says to.
- **The hardware configuration is not exported.**
- **`.s7dcl` is the supported block format, SimaticML the experimental one.** OBs and know-how protected blocks exist only as SimaticML: the `.s7dcl` of an OB loses its event class.
- **A block, DB or UDT has one format in the repo.** A successful export removes the other format's files, so the next commit carries the removal and no stale file stays beside the new one.
- **Library releases wait for a person, type by type.** A change to one type reaches every type containing it, so each is reviewed against its released version and approved on its own.
- **The rules ship with the clone, and a session normally starts there.** One tracked skill, `tia-change`, holds the order of a change. A session elsewhere still works, as the MCP instructions carry absolute paths.
- **The bridge is registered per user** ([ADR 0002](../adr/0002-bridge-registered-per-user.md)), **the skills plugin comes from the official marketplace** ([ADR 0003](../adr/0003-skills-plugin-from-the-official-marketplace.md)) and **the skills' config lives in `docs\agents\`** ([ADR 0001](../adr/0001-skills-config-beside-the-guides.md)).

## Change reports

`CODING_STANDARDS.md`, Change reports, holds the rules a report is reviewed against: above all, hiding a real change is the worst failure, and a report reads exports only. Beside those:

- **What differs but cannot be shown gets a note,** not silence: "differs in something this report does not show".
- **By default only changes are shown.** A new or deleted block, tag table or library type is shown with its content, marked added or removed, as one change; on request by heading only, for a very large change.
- **The diff compares logic, not text.** Renumbered wires and reordered branches are no change; a changed order of rungs carries a tag.
- **One self-contained page,** so a report can be passed on and opened with nothing installed.

## HMI

- **Screens, templates and pop-ups are always exported full,** with defaults and read-only attributes. A full export imports back unchanged, and the preview and validator see what the document holds, with no table of TIA defaults to keep.
- **Every object is copied from an export or the catalogue's fixture, never invented.**
- **One validator for the generator, the preview and the import.** What the preview shows as an error, the bridge refuses.
- **An error is what TIA refuses, crashes on or silently loses.** A warning is what TIA accepts and probably looks wrong.
- **The preview draws the documents that will be imported.** There is no second model, and the report draws with the same code.
- **Every HMI import waits for the person's yes to its preview, and the bridge does not check it.** The yes is said in the conversation, which the bridge never sees. A flag on `import` would be set on every HMI call, so it would become a habit that tells nothing, unlike the guards for rare acts. A running preview server shows only that a page exists, not that the person looked at it. The stop is in `.claude\skills\tia-change\hmi.md`, and the text of the `import` tool points there.

## The other tools

- **The Archive Compare window is Python with tkinter.** No build step and no new dependency, and it never talks to TIA.
- **The status views read, but for one button.** They write no state file and never touch TIA themselves. The TIA dashboard's button starts a report run, its own process, which attaches to TIA, exports, commits and makes the change report; one attach at a time, so it refuses beside a bridge and a bridge refuses beside it ([ADR 0004](../adr/0004-the-tia-dashboard-starts-a-report-run.md)). They answer `127.0.0.1` only, as they have no login, and the button's request also carries the page's token and Origin.
- **The dashboards use the standard library.** Their icon goes through `ctypes`, for no dependency and no licence to list, and everything a page loads comes from the repo.
- **One Python environment,** pinned by `pyproject.toml` and `uv.lock`, called by absolute path, never `python` from `PATH`.
- **Tests need no TIA** (`CODING_STANDARDS.md`, Tests run headless), so every commit can be checked on any machine. How they run: [Testing](testing.md).
- **Docs are an OKF bundle with its checker in the repo,** so a contributor needs nothing else to check them ([conventions](conventions.md)).
