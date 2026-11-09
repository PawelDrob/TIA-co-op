# Log

## 2026-11-06
* **Creation**: [ADR 0004](adr/0004-the-tia-dashboard-starts-a-report-run.md): the TIA dashboard's button starts a report run, which works through the bridge in a report-run mode.
* **Update**: [TIA agent status](user/tia-agent-status.md): a change report without an agent, from the dashboard's button.

## 2026-11-05
* **Creation**: [Developer pages](dev/overview.md): how the tools are built, written fresh from the code: overview, one page per tool, decisions, known issues, testing, conventions, roadmap. [Conventions](dev/conventions.md) is the documentation convention of the repo from now on.
* **Update**: [Setup](user/setup.md): the keys of the bridge settings, moved out of the always-loaded rules.
* **Move**: The TIA Archive Compare user guide is now `TiaArchiveCompare/README.md`, its setup part with it; [Setup](user/setup.md) holds first setup only.
* **Update**: [TIA agent status](user/tia-agent-status.md) holds what each view shows; how to start them is in `TiaAgentStatus/README.md`.

## 2026-11-04
* **Deprecation**: `viz.html` is out of git and no longer checked: generated, nothing read it, and it conflicted on rebases. `-WriteViz` makes it when wanted; git ignores it.

## 2026-11-03
* **Update**: [Setup](user/setup.md): first setup of a clone, one command that is also the check.
* **Creation**: [Agent skills](agents/index.md): the config of the engineering skills for changing this repo (issue tracker, triage labels, domain docs), where `setup-matt-pocock-skills` looks for it.
* **Creation**: [ADRs](adr/index.md): the public decision records, written new and short; `GLOSSARY.md` at the repo root likewise.
* **Creation**: [Development dashboard](user/development-dashboard.md): the dashboard of tickets and review pages for people changing this repo, its tickets format, taking a page down, remote use through `tailscale serve`.

## 2026-11-02
* **Creation**: [Setup](user/setup.md): how to set up the tools on a Windows PC; so far TIA Archive Compare.
* **Update**: TIA Archive Compare user guide rewritten in the reader's order: what it does, an example report of a made-up project (`user/assets/`), download and setup, requirements, limitations. Build steps, the command line, options, cache and work folders left the page.

## 2026-11-01
* **Move**: The bundle is split by reader: [agent](agent/index.md) holds the guides an agent reads while working (SIMATIC SD, WinCC Comfort, WinCC Comfort screen objects), [user](user/index.md) the how-tos for users (TIA Archive Compare, moved from `guides\`). The designs, ADRs, research note, retro, templates, the agent skill documents and the glossary left the repo; they are kept privately until public developer documents are written. The catalogue generator writes [WinCC Comfort screen objects](agent/wincc-screen-objects.md) to its new place.
* **Creation**: [TIA Openness V20 facts for agents](agent/openness-v20.md): what Openness does with PLC blocks, HMI objects and library types and how it fails, taken from the research note on the Openness V20 capabilities.
* **Creation**: [TIA agent status](user/tia-agent-status.md): how to set up the status line and the herdr watcher and what they show, taken from the TIA agent status design.
* **Update**: The bundle checker is part of the repo (`tools\okf\`); the pre-commit hook and `CLAUDE.md` call it.
* **Creation**: TIA Archive Compare user guide (draft, preview): what the tool does, what it needs, build and start, inputs, options (compile, safety, HMI, UMC login), where results, cache and work copies land, "Not in the report", cancel and Stop now, limits.
* **Move**: The HMI generator folder `WinCCOpenness\` is now `TiaHmiGenerator\` (`hmixml.py`, `hmipreview\`, `catalogue\`), named like the other tools; paths in `CLAUDE.md`, the [WinCC Comfort guide](agent/wincc-comfort-openness.md) and [WinCC Comfort screen objects](agent/wincc-screen-objects.md) follow. The WinCC guide keeps its name.

## 2026-10-31
* **Creation**: [WinCC Comfort screen objects](agent/wincc-screen-objects.md): the screen object catalogue, every object of the WinCC Comfort toolbox with every option (TIA display name and group, export name, default in WinCC Dark, confirmed and documented values, greyed conditions, what the HMI preview draws), generated from `WinCCOpenness/catalogue/catalogue.json`. The [WinCC Comfort guide](agent/wincc-comfort-openness.md) now says the user view goes through Openness and names the 14 controls that do not.

## 2026-10-06
* **Update**: [WinCC Comfort guide](agent/wincc-comfort-openness.md) sections 2, 3, 5 and 8 follow the HMI preview (browser view, validator, TiaBridge import guard); `render.py` retired.

## 2026-10-04
* **Update**: Added `viz.html`, the OKF graph viewer of this bundle, generated with `-WriteViz` (open it in a browser).
* **Initialization**: The guides and designs moved from the repo root and `docs\` into this OKF v0.2 bundle. Files renamed to kebab-case, every document has a header, dates in prose are ISO. `generated` holds each file's last modification time before the move.
