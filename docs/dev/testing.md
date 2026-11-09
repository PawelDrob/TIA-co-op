---
type: Guide
title: Testing
description: What each test suite covers and what it fakes, what the commit hook runs across tools, and what only a real TIA can show.
tags: [dev, testing]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-09T00:05:00-05:00 }
---

# Testing

`CONTRIBUTING.md`, sections Tests and Integration runs, has the commands and scripts. The head of `.githooks\pre-commit` lists what runs when. This page says what each suite covers and where it stops.

## The suites

No suite the hook runs needs TIA, a window or a person, so anyone can run them and a commit stays fast.

| Suite | Covers | In place of the real thing |
|---|---|---|
| `TiaBridge\Tests\*.Tests.ps1` (Pester 3.4) | The tools' logic, the MCP loop over piped JSON, repo mapping, save rules, guards. `WriteGate.Tests.ps1` fails for a new tool until it is classified as write or read | Fake Openness objects, no TIA |
| `TiaBridge\Tests\parse.ps1` | Every script parses in PowerShell 5.1 and is ASCII | |
| `TiaChangeReports\tests\` | Readers, diff, layout and page. `verify.py` rebuilds the nets from the drawn lines and matches them to the parsed network | Real export formats with a made-up plant (`tests\fixtures\`) |
| `TiaHmiGenerator\Tests\` | Validator rules, generator runs, the preview server over HTTP, and drawing through headless Edge or Chrome, skipped with a reason when neither is found | A fixture project repo built on disk (`Tests\fixture.py`) |
| `TiaHmiGenerator\catalogue\build.py --check` | The catalogue and its generated page agree with their inputs | |
| `TiaArchiveCompare\runner\tests\` | A whole run, with the report step for real | `fake.FakeExporter` for TIA, `tests\fake_bridge.py` for the bridge |
| `TiaArchiveCompare\window\tests\` | The window's model, with no window and no process | |
| `TiaArchiveCompare\package\tests\` | Which tracked files the download holds, and its version against the tag and the bridge's | A made-up repo for the versions |
| `TiaAgentStatus\tests\` | Rows, orphans, labels, notifications, the page. One test starts a real bridge with no tools | A fake process table, a fake [herdr](https://herdr.dev) |
| `tools\*\tests\` | Dashboard, session tool, first setup, the commit hook, the check for pointers to files that are gone, OKF checker | Temp git repos, a fake `claude` |

## What the hook adds

`.githooks\pre-commit` picks suites by the paths a commit touches. Four suites run for a change elsewhere, because a contract crosses there:

- The report's test of its export folders against the bridge's, on a change to the bridge alone.
- The status suite, on a change to the bridge or `tools\dashboard\`: it reads the state files and runs on that core.
- The bridge's validator guard tests, on a change to the generator.
- The Archive Compare package tests, on a change to `TiaBridge\Mcp.ps1`: the download's version must equal the bridge's.

## By hand

**The Archive Compare window check** opens real windows, so it stays out of the hook. [Its README](../../TiaArchiveCompare/window/README.md) says how to run it.

**The check of the download** (`TiaArchiveCompare\package\check.py`) needs a built zip, which needs a download of Python, so it runs after each build and in the release workflow, not in the hook. [CONTRIBUTING.md](../../CONTRIBUTING.md#the-download-of-tia-archive-compare) has the commands.

**The integration scripts** run on a real TIA, and `CONTRIBUTING.md` lists them. The project's archive is the way back. Test objects are named `zz...` so they are easy to find and delete, and each script's head says what it leaves.

## Where the tests stop

- Unit tests pin what the code does against fake Openness objects, not how TIA answers. A behaviour found on TIA goes into `docs\agent\`, marked `[PROBE]`.
- A report test shows that the model and the drawing agree with each other. Whether they agree with TIA takes screenshots and a person's eye.
- [Known issues](known-issues.md) names what has not been run on real content.
