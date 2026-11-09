---
type: Guide
title: TiaAgentStatus internals
description: The bridge's state files and how the dashboard, the status line and the herdr watcher read them, tell live bridges from orphans, and judge a TIA as hung; and the report run the dashboard's button starts.
tags: [dev, tia-bridge, herdr, status-line, dashboard]
status: draft
generated: { by: claude-code/claude-fable-5-2, at: 2026-11-09T18:29:00-05:00 }
---

# TiaAgentStatus internals

Shows what happens to TIA projects while agents work on them. Everything it shows comes from what the bridge leaves behind, and it never writes back. The one exception is the dashboard's button, which starts a [report run](#report-run). What each view shows is in [TIA agent status](../../user/tia-agent-status.md), how to start them in [its README](../../../TiaAgentStatus/README.md).

| File | What |
|---|---|
| `__main__.py` | Command line: `statusline`, `watch`, `dashboard`, `report-run` |
| `state.py` | Reads the state files; live or orphan; which bridge belongs to which Claude process |
| `procs.py` | Process data through `kernel32` with `ctypes` |
| `statusline.py` | The TIA row of a Claude Code status line |
| `watch.py`, `table.py` | The herdr watcher, its pane |
| `dashboard.py` | The local page, on the core in `tools\dashboard\` (`live.py`, `tray.py`) |
| `reportrun.py` | A report run: the bridge in its report-run mode, the commit, the run's record |

Python's standard library only: a status line runs often, and Python starts far faster than Windows PowerShell.

## The state file

Every bridge process keeps `<projectsRoot>\_bridge\sessions\<bridge pid>.json` (`TiaBridge\State.ps1`). It is written at the start, at the start and end of every tool call and on progress events (object events at most once a second), as a temp file and a rename. A failed write goes to stderr and never fails a call. The bridge removes the file when it ends.

| Field | Content |
|---|---|
| `v` | Contract version, 1. Fields may be added; readers ignore what they do not know |
| `pid`, `client`, `started`, `updated` | The bridge process, `mcp` (`report-run` for the bridge of a report run), its start, the time of this write |
| `session`, `claude.pid`, `claude.from` | The Claude session and process: `CLAUDE_PID` (`env`), else the nearest ancestor named claude or node (`ancestor`), else the parent |
| `herdr.tab`, `herdr.pane` | `HERDR_TAB_ID`, `HERDR_PANE_ID`, when the bridge runs in herdr |
| `project`, `repo`, `boundSince` | The bound project |
| `tia.pid`, `tia.window` | The TIA process, and whether it has a window |
| `operation` | The call that runs: `name`, `since`, and from progress `step`, `part`, `device`, `kind`, `n`, `of`. Null when idle |
| `lastOperation`, `lastPrompt` | The last call (`name`, `ok`, `ended`, `ms`), and the last prompt of a background TIA (`at`, `kind`, `caption`, `text`, `answer`) |

**The bridge cannot write during one blocking Openness call.** So a reader computes elapsed time, memory and CPU itself, from `operation.since` and `tia.pid`.

**Orphans.** A file whose pid is dead, or whose pid started after `started` (a reused pid), is an orphan. Readers skip it as a live bridge, and the next bridge start deletes it. The watcher remembers an orphan's TIA while it runs, by pid and process start time.

## Status line

`statusline.py` walks up its own process tree to the nearest Claude process (`CLAUDE_PID` first when set) and shows the newest live bridge with that Claude process. It prints nothing without one, and on any error but one: bridge settings it cannot read are the row, with the file named, as the bridge's folder is unknown then. `state.bridge_settings` reads `TiaBridge\settings.json` as strict JSON, finds a name in any case, as the bridge does, and raises `SettingsUnreadable` for text only the bridge can read (single quotes, names without quotes) and for names the bridge refuses. `watch` and `dashboard` stop on it when no `--root` gives the folder. The row only stays current when Claude Code runs it again, so its how-to in [the README](../../../TiaAgentStatus/README.md#how-to-use) sets `refreshInterval`.

## Watcher

Every `--every` seconds, through the CLI of [herdr](https://herdr.dev), a terminal workspace for agents:

- **Tab label:** the tab's own label plus ` · TIA <call>` or ` · TIA idle`, read anew each round so a rename stays. The tab comes from `herdr.tab`, else the pane whose foreground process is the bridge's Claude process. Several live bridges on one tab: the newest shows.
- **Notifications:** a TIA without a window started or ended, a bridge ended without cleanup or holding such a TIA, a new `lastPrompt`, a TIA gone while its bridge runs, and a quiet TIA. A TIA without a window and a prompt already there at the watcher's start are not announced; a TIA already gone while its bridge runs is.
- **Its own pane:** a table of the bridges and orphans, then the last notifications. On a console it redraws in place and never wraps; with `--once`, or when stdout is not a console, it prints plain ASCII.

**A quiet TIA.** During a call, a TIA that used under 2 s of CPU within `--quiet-minutes` is reported, once per quiet spell. The threshold comes from a measured upgrade, not a real hang. An idle TIA is not reported.

A failing herdr call goes to the pane and the round goes on.

## Dashboard

`dashboard.py` serves a local page on `127.0.0.1`. It reads the state files through the watcher, with a herdr that renames and notifies nothing, or none at all. It also reads tool logs and change reports from the project repos, and commit subjects from git. A request from another host is refused ([why](../decisions.md#the-other-tools)).

`tools\dashboard\` is the core it shares with the [development dashboard](../../user/development-dashboard.md): `live.py` for the server, the live updates and the page's head, `tray.py` for serving with the notification area icon, and `tray_icon.py` for the icon itself. It knows nothing of what a page shows.

## Report run

The dashboard's button posts `/api/report-run`. That request must be JSON, carry the token the page holds (`X-Report-Token`), and name the page itself as `Origin`. The dashboard then starts `python -m TiaAgentStatus report-run --repo <repo>` as a detached process, and from then on reads the run's record like any other file ([ADR 0004](../../adr/0004-the-tia-dashboard-starts-a-report-run.md)).

`reportrun.py` writes `<projectsRoot>\_bridge\report-runs\<repo folder>.json`: `pid`, `started`, `project`, `repo`, `projectPath`, `tia`, `bridge`, `step`, then `ended`, `outcome` (`done`, `same`, `failed`, `refused`), `text`, `commit`, `page`, `unsaved`. A record counts as running until it has ended, while its process lives and did not start after the record, or its bridge lives and started after it: a run that is killed leaves its bridge in the call it is in. One run goes at a time: a run writes its record before it looks for another's, so two that start at once both refuse. Two runs of one repo, from two dashboards at the same moment, would write the same record: a run first takes `<repo folder>.lock` beside it, locked by Windows until the run's process ends, and a second one refuses while it is held.

The run checks, in order:
- the repo records a project path;
- no live bridge names the repo;
- the repo has nothing uncommitted outside `logs\`.

It then starts `TiaBridge.ps1 -ReportRun` with its own copy of the bridge settings, pointing at the same projects root under the name as the file spells it (settings it cannot read end the run with `Not run:` and the reason), and talks MCP to it over stdin and stdout; the bridge's stderr goes to `<repo folder>.log`. From the bridge:
- `tia_status` gives the TIA process that holds the project's path, which must have a window. The record then takes that process, and the run checks again that no bridge names that TIA.
- `connect` follows, then `full_export`.

What `connect` writes of its own goes back as committed before the export (the time of the connect in `tiabridge.json`; not `.gitignore`), so the commit is the export's, and a TIA with no change commits nothing. An export that is not whole is not committed: failed objects, a stop, a git or mirror error, repos or uncommitted files left in the export folders, or a bridge that ended during it. Nor is a run that failed at `connect`, which may have written to the repo by then (`tiabridge.json`, the docs it makes when missing). The repo goes back with `reset --hard` and `clean`, keeping `logs\`: it held nothing else before the run. A whole export is committed with `add -A`, and `change_report` runs on that commit, with the commit's subject as the page's title, which says when TIA had unsaved edits.
