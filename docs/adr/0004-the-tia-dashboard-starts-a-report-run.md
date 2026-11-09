---
type: Rationale
title: "ADR 0004: The TIA dashboard starts a report run; the run does the work through the bridge"
description: The TIA dashboard's one button starts a separate process that runs TiaBridge in a report-run mode to export, commit and report, so the page stays a reader, the export is the bridge's own, and an agent's bridge and the run keep off each other's TIA.
tags: [adr, dashboard, bridge, change-report]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-06T14:04:29-05:00 }
---

# ADR 0004: The TIA dashboard starts a report run; the run does the work through the bridge

The TIA dashboard was a reader: it read state files, logs, reports and git, and never touched TIA. Its button **Make a change report of TIA now** has to attach to the user's open TIA, export the project, commit and run the change report. The page does none of that itself. The button only starts a report run (`TiaAgentStatus\reportrun.py`), a process of its own that outlives the page, and the page reads the run's record in `<projects root>\_bridge\report-runs\` as it reads the rest. The run starts TiaBridge in a report-run mode (`TiaBridge.ps1 -ReportRun`) and calls `tia_status`, `connect`, `full_export` and `change_report` on it as an agent does. So it uses the bridge's own export, logs and state file, and no second exporter has to stay in step with the bridge. In that mode the bridge refuses every other tool, and its `connect` makes no session archive, as the run writes nothing to TIA.

Two programs attached to one TIA have hung it, so the two keep apart. The run refuses a TIA or repo that a live bridge names in its state file, and in its `connect` a TIA that lists another program attached to it. An agent's bridge refuses in `connect` a TIA or repo that a running report run names in its record. Each first writes down the TIA it is about to attach to, the bridge in its state file and the run in its record, and only then looks for the other, so two that start at once both refuse rather than both attach.

The run commits only what the export wrote, with the logs of its own calls, and only when the export reached every object. Otherwise it puts the repo back to its last commit, so a change the export missed never reads as no change in a report. The maintainer chose this over committing and naming the objects left out (2026-11-06).

The one request that writes must come from the dashboard's own page. A page of any site in the user's browser can send requests to `127.0.0.1`, so the request has to be JSON, carry a token that only the dashboard's page holds, and name that page as its `Origin`. The existing check of `Host` stays in front of it.
