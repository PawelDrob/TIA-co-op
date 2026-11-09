---
type: Guide
title: TIA agent status
description: What the dashboard, the status line and the herdr watcher of TiaAgentStatus show, with an example of each and the limits of what they show, and how the dashboard's button makes a change report without an agent.
tags: [tia-bridge, agents, herdr, status-line, dashboard, change-report]
status: draft
generated: { by: claude-code/claude-fable-5-2, at: 2026-11-09T17:43:10-05:00 }
sources:
  - id: code
    resource: ../../TiaAgentStatus/
    title: TiaAgentStatus (dashboard, status line, watcher)
---

# TIA agent status

What each view of [TiaAgentStatus](../../TiaAgentStatus/README.md) shows. How to start them is in its README.

The dashboard starts in the light or dark mode of your system. The icon at the top right switches it; your browser remembers
the choice, also for the [development dashboard](development-dashboard.md) on this machine; a tab already open takes it when
you come back to it.

## What the dashboard shows

- **What needs you** stands above everything, so nothing you have chosen can hide it: how many, and for each its project,
  what is wrong and what to do. Amber for what waits for you, red for what failed. A name opens that project.
  - TIA shows a box during a call and the bridge left it open: answer it in TIA. With no window no one can: it may hang, ask
    the agent or end that TIA. A box the bridge closed needs nothing: it shows under the TIA, as the last thing it asked.
    "Answer it in TIA" stays amber until the call ends, as the bridge's state does not change when a box closes.
  - TIA does nothing for `--quiet-minutes` during a call: look for a message box, or, with no window, it may hang.
  - A TIA without a window is left running without its agent: close it, the process number is given.
  - The last call of an agent failed, until its next call: ask the agent what it will do about it.
  - TIA closed or crashed while its agent runs: ask the agent to connect again.
- **Projects**, on the left: the folders of the projects root with tool logs or change reports, or with an agent or a
  running HMI preview on them. A row holds the name, when the last call was, and what happens now; what needs you comes
  first. The page sees bridges, not agents: between calls, while the agent reads, edits or thinks, its bridge is idle and
  the row says `Bridge idle`; with no bridge on the project it says `No bridge connected`. Two bridges on a project add
  `(2 bridges)`.
- **The chosen project**, on the right, stays chosen while the page updates and when you reload it, and its address can be
  shared (`#<project>`). It has these parts:
  - **Agent is calling**: the call with its time, else since when it calls nothing: the end of its last call, or when its
    bridge started. Also when the agent waits for an answer, is gone, or has ended and left a TIA. Two agents on a
    project have a line each.
  - **TIA**: with or without a window, memory, CPU over the last minute (100% = one core busy), the last thing it asked and
    how the bridge answered, and the project open in it when its name differs from the folder. It knows only the TIA a
    bridge holds.
  - **HMI preview**, only while an agent's HMI preview runs for the project: a link per HMI device, which opens the
    preview of that device in a new tab, with since when it runs. Once the preview stops answering, its link goes. A
    preview started with `--host 0.0.0.0` for another machine is linked on `127.0.0.1`, this machine; one bound to a
    single address of this machine is linked on that address.
  - **Change reports**: one list, newest made first. The commit subject opens the report in a new tab, with what was
    compared to what, the size, and the date and time the report was made, to the minute. Above it the button **Make a
    change report of TIA now** ([a change report without an agent](#a-change-report-without-an-agent)), and how its last
    run ended.
  - **History**: every call, newest first, in its own scrolling area, with its time and duration and, for a failed one,
    why. Which agent made a call does not show.
- **Bridges with no project** have their own section under the list while there is one, each its own line with since
  when it is idle, and below them any **TIA with no bridge**, in grey and needing nothing: your own, or one with a window
  that lost its agent, which may hold work not saved.

On a narrow screen the chosen project takes the place of the list; **All projects** goes back. What needs you stays on top.

## A change report without an agent

You changed the project in TIA yourself and want the report of it. Keep the project open in TIA and press **Make a change
report of TIA now** on its part of the dashboard. A report run then does what an agent does through
[TiaBridge](../../TiaBridge/README.md): it attaches to that TIA, exports the whole project into its repo (`full_export`),
commits that as `TIA dashboard: <project> as TIA holds it`, and makes the change report of that commit, which joins the list.
The next report, yours or an agent's, starts from that commit.

- **What the report shows:** the project as TIA holds it, saved or not. With unsaved edits, the commit and the line under
  the button say `unsaved edits included`. The run saves nothing and changes nothing in TIA.
- **While it runs** the line under the button shows the call, its part and n of m, and the time. An export takes minutes
  per thousand objects. Leave TIA alone until it ends: an edit made during the export may land in it half. On the first
  attach of a program TIA asks whether to allow access: answer it in TIA.
- **When it ends** the line says how, with the time: the commit, or TIA's own words when it failed. If the export did not
  reach every object, nothing is committed and the repo is as it was: a change no export reached would read as no change.
  The same when the run fails before its commit, at the connect or the export.
  If TIA holds what the last commit holds, there is nothing to report.
- **It waits, and says why,** while a bridge is connected to that TIA or that repo, or another program is attached to that
  TIA (two programs on one TIA have hung it), while another report run goes on, and while the repo has files not committed
  (the report would hold them). An agent's bridge in turn does not connect to that TIA or repo while the run goes on.
- The run goes on when you close the dashboard, and the page shows it again when you open it. Its record and the bridge's
  output are in `<projects root>\_bridge\report-runs\`.

## What the status line and the watcher show

- **Status line**: the project; `no window` for a TIA without window; the call that runs, with its part or step and n/m,
  and the time since it started, else `idle`; the memory of the TIA process (`TIA gone` when it has ended); the last
  question TIA asked while the call that caused it runs. Nothing when the session has no bridge, or its bridge holds no
  TIA and runs no call.
- **Tab labels**: each agent's tab gets ` · TIA <call and n/m>` or ` · TIA idle` after its own label, removed when the
  bridge holds no TIA or ends.
- **Notifications**: a TIA without window started or ended; a bridge ended without cleanup or left a TIA without
  window running (it says whether that TIA still runs); TIA asked something (caption, text and the bridge's answer);
  the TIA process is gone while its bridge runs; a call runs but TIA used almost no CPU for `--quiet-minutes` (it
  may hang: look at it).
- **Its pane**: one row per bridge, then the TIA processes left running by bridges that are gone, then the last
  notifications. `CPU%` is the TIA's CPU time over the last minute: a working TIA uses at least one core, a hung one
  none. In a narrow pane columns and rows give way; nothing wraps.

## Example

The dashboard with one project chosen (the text of the page, made-up projects). It reads everything again every second
(`--every`) and updates by itself when something changed; **Live, updated** gives the time it last did:

```
TIA-CO-OP DASHBOARD                                          Live, updated 14:02:59

2 need you
Filler  ● TIA asks: Import: Overwrite the block? Answer it in TIA.
Packer  ! compile failed: PLC_1: 2 errors, 0 warnings. Ask the agent what it will do about it.

Project          Last call    Press line
Filler               08:30
● TIA asks a question         AGENT IS CALLING              TIA
Packer               08:00    export blocks 31/115 2:15     Without a window
! compile failed                                            3.1 GB memory, 104% CPU
Press line           14:02
▸ export blocks 31/115 2:15   CHANGE REPORTS
Mixer           2026-10-20    2026-11-03 14:02  Pump: longer start delay      41 KB
! Last call failed: save                        b39bf4a to b764f2c
                              2026-10-29 16:40  Valve: new interlock          38 KB
BRIDGES WITH NO PROJECT                         6d0e1a2 to b39bf4a
○ Bridge idle since 13:40
Holds no TIA.                 HISTORY
                              2026-11-03
TIA WITH NO BRIDGE            14:02:54  change_report b39bf4a to b764f2c      5.3 s
Yours, or left by an agent    09:15:30  save                                  2.1 s
that ended.                   09:15:09  compile PLC_1: 0 errors, 2 warnings  14.8 s
Process 6000, 2.4 GB memory   09:15:00  import Pump, Valve                    2.3 s
```

The status line:

```
TIA: Plant copy · no window · export blocks 31/115 · 2:10 · 3.1 GB
TIA: Plant · idle · 2.4 GB
TIA: Plant · no window · import · 0:42 · 2.6 GB · asked: Overwrite object
```

The watcher's pane:

```
10:00:15  2 bridges, 1 orphaned TIA
Agent          Project       Win  Call                      Time    Mem  CPU%  Last prompt
-------------  ------------  ---  ------------------------  ----  -----  ----  ----------------------------
Lead           Plant copy    no   export blocks 31/115      2:15  3.1GB   90%
01 TIA status  Line          yes  idle                            900MB    0%  09:59 Import: Overwrite? -> No
-              Old           no   orphan (bridge 220 gone)        2.4GB    0%

Last notifications
10:00:05  TIA Old: bridge 220 ended without cleanup, TIA 6000 without window still running
```

## Limits of what they show

- After one press of the icon there is no way back to following the system setting, short of clearing the `dashboard-theme`
  cookie; it lasts a year.
- A report link serves report pages directly in `changes\reports\` of a known project repo, nothing else. A change report keeps its own light look: the icon does not reach it.
- TIA asks is not sure to show. The bridge writes a prompt only on a progress event or at the end of the call, and when
  the same prompt comes again it keeps the time of the first, which can lie before the call that runs.
- History shows the newest 100 calls per project and says how many there are; the rest are in the repo's `logs\`.
  Calls made with no project open are not in it.
- A TIA without a window whose agent ended cleanly before the dashboard started has nothing left to say whose it was: it
  shows as a TIA with no bridge, and does not count as needing you.
- The button works on a project an agent has connected to once: its repo records where the project file is. The commit
  is made with your git name.
