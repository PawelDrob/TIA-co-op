---
type: Guide
title: Testing
description: What each test suite covers and what it fakes, what the commit hook runs across tools, and what only a real TIA can show.
tags: [dev, testing]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-24T22:18:00-05:00 }
---

# Testing

`CONTRIBUTING.md`, sections Tests and Integration runs, has the commands and scripts. The head of `.githooks\pre-commit` lists what runs when. This page says what each suite covers and where it stops.

## The suites

No suite the hook runs needs TIA, a window or a person, so anyone can run them and a commit stays fast.

| Suite | Covers | In place of the real thing |
|---|---|---|
| `TiaBridge\Tests\*.Tests.ps1` (Pester 3.4) | The tools' logic, the MCP loop over piped JSON, repo mapping, save rules, guards. `WriteGate.Tests.ps1` fails for a new tool until it is classified as write or read | Fake Openness objects, no TIA; for the user's own theme file, a path that is not there, set in `TIA_CR_USER_THEME` (`Report.Tests.ps1`) |
| `TiaBridge\Tests\parse.ps1` | Every script parses in PowerShell 5.1 and is ASCII | |
| `TiaChangeReports\tests\` | Readers, diff, layout and page. `verify.py` rebuilds the nets from the drawn lines and matches them to the parsed network. The block viewer too: its drawing against the report's, and its registration for a double-click, written to a key of the test's own under `HKEY_CURRENT_USER` and removed after. Page scripts, as the folds, in headless Edge or Chrome, skipped without one; there too the themes (`test_theme.py`): the forms of colour a theme takes and the form the page writes, held to the browser's own reading, and a trial palette that every element follows but an HMI screen. A VS Code color theme read onto the palette (`test_vscode_theme.py`): the file, its kind, the table against the dev doc, and every pair to keep readable over fixture themes of each kind, failing with a rule taken out. The two formats against each other (`twoformats.py`) on three commits. The SCL colours (`test_scl_colours.py`) over every SCL network of the fixtures; over the project repos the environment variable `TIA_CR_SCL_REPOS` names (paths apart by `;`), such as the benchmark project's, only when it is set | Real export formats with a made-up plant (`tests\fixtures\`); a stand-in for the default browser; for the two formats, real files of the two-format benchmark run (`tests\fixtures\twoformats\`); for the SCL colours, a real export of the benchmark project in both formats (`tests\fixtures\scl-colours\`); for the themes, VS Code color themes written for the tests (`tests\fixtures\themes\`); for the user's own theme file, a path that is not there, set in `TIA_CR_USER_THEME` |
| `TiaHmiGenerator\Tests\` | Validator rules, generator runs, the preview server over HTTP, and drawing through headless Edge or Chrome, skipped with a reason when neither is found | A fixture project repo built on disk (`Tests\fixture.py`) |
| `TiaHmiGenerator\catalogue\build.py --check` | The catalogue and its generated page agree with their inputs | |
| `TiaArchiveCompare\runner\tests\` | A whole run, with the report step for real | `fake.FakeExporter` for TIA, `tests\fake_bridge.py` for the bridge; for the user's own theme file, a path that is not there, set in `TIA_CR_USER_THEME` |
| `TiaArchiveCompare\window\tests\` | The window's model, with no window and no process | |
| `TiaArchiveCompare\package\tests\` | Which tracked files the download holds, and its version against the tag and the bridge's | A made-up repo for the versions |
| `TiaAgentStatus\tests\` | Rows, orphans, labels, notifications, the page. One test starts a real bridge with no tools | A fake process table, a fake [herdr](https://herdr.dev) |
| `tools\*\tests\` | Dashboard, session tool, first setup, the commit hook, the check for pointers to files that are gone, OKF checker | Temp git repos, a fake `claude` |

## What the hook adds

`.githooks\pre-commit` picks suites by the paths a commit touches. Some run for a change elsewhere, because a contract crosses there; the hook's head names, step by step, every path that starts each suite. Among them:

- The report's test of its export folders against the bridge's, on a change to the bridge alone.
- The status suite, on a change to the bridge or `tools\dashboard\`: it reads the state files and runs on that core.
- The bridge's validator guard tests, on a change to the generator.
- The generator's suite, on a change to `docs\agent\wincc-comfort-openness.md`: a test holds its list of the generator's calls (5.1) to the code and runs its worked screen (5.2).
- The Archive Compare package tests, on a change to `TiaBridge\Mcp.ps1`: the download's version must equal the bridge's.

A suite's tests run in worker processes at once: a Python suite's through `tools\hooks\run_tests.py`, each test on its own or a class with `setUpClass` whole, and the bridge's test files through `TiaBridge\Tests\run.ps1`. So a test shares the PC with the others of its suite. It keeps what it writes in a temp folder of its own, reads a file another process writes only once that file is whole, and waits for another process with a bound, so that a test that fails ends.

## By hand

**The Archive Compare window check** opens real windows, so it stays out of the hook. [Its README](../../TiaArchiveCompare/window/README.md) says how to run it.

**The setup window check** (`tools\setup\tests\check_window.py`) opens the window, so it stays out of the hook. It runs on a desktop of its own and may run on a PC in use: a fresh clone in a temp folder with a temp home, the first and second double-click on `Setup.wsf`, every button pressed, pictures of every page, and a watch for console windows. [The window's README](../../tools/setup/window/README.md) has the command.

**The check of the dashboards' icons** (`tools\dashboard\tests\tray_check.py`) shows real icons and moves the mouse, so it runs on a PC nobody is using. With `--hidden` it runs only its part on a desktop of its own, which shows nothing and may run on a PC in use: each dashboard where no taskbar is, and its end on Ctrl+C under `python.exe`. Its head says what each run covers.

**The check of the download** (`TiaArchiveCompare\package\check.py`) needs a built zip, which needs a download of Python, so it runs after each build and in the release workflow, not in the hook. [CONTRIBUTING.md](../../CONTRIBUTING.md#the-download-of-tia-archive-compare) has the commands.

**The integration scripts** run on a real TIA, and `CONTRIBUTING.md` lists them. The project's archive is the way back. Test objects are named `zz...` so they are easy to find and delete, and each script's head says what it leaves.

## Where the tests stop

- Unit tests pin what the code does against fake Openness objects, not how TIA answers. A behaviour found on TIA goes into `docs\agent\`, marked `[PROBE]`.
- A report test shows that the model and the drawing agree with each other. Whether they agree with TIA takes screenshots and a person's eye.
- [Known issues](known-issues.md) names what has not been run on real content.
