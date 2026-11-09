---
type: Guide
title: TiaArchiveCompare internals
description: The window and runner that export two TIA archives through background TIA sessions and write the change report, with their event contract, commands, steps, bridge seam and cache.
tags: [dev, archive-compare, tia-bridge]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-09T00:27:39-05:00 }
---

# TiaArchiveCompare internals

A person picks two versions of a project, presses one button, sees at every moment what the tool does, and gets the change report. What it does for a user, with its limits and measured times, is in [its README](../../../TiaArchiveCompare/README.md). This page is the contract between the parts.

| Part | What | Code |
|---|---|---|
| Window | Python with tkinter, no build. Starts the runner, shows its events, sends it commands. Never talks to TIA | `window\`; [its README](../../../TiaArchiveCompare/window/README.md) lists the files and the check by hand |
| Runner | One run: A, then B, then the report. Events on stdout, commands on stdin | `runner\run.py`, `events.py`, `inputs.py`, `checks.py`, `cache.py`, `errors.py` |
| Exporter | One TIA per input, behind `exporter.Exporter` | `runner\bridge.py` (TiaBridge as a child), `runner\fake.py` (no TIA) |
| Report | TiaChangeReports on two folders | [Its page](tia-change-reports.md) |
| Download | The zip on a GitHub release, to use with no clone | `package\`; [below](#download) |

An agent runs the same runner, with `--no-ask`: the bridge's MCP instructions hold that command line.

## Command line

From the repo folder, with the options in the head of `runner\__main__.py`:

```
.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.runner run --before A --after B [options]
```

Exit code 0 when the report is written, 1 when the run failed or was cancelled, 2 on a usage error. An `end` event says why in each case. An out root or data root under the project repos is a usage error: the tool never writes there.

`--git REPO` makes A and B two commits of that repo ([its README](../../../TiaArchiveCompare/README.md#two-commits-of-a-git-repo)): no TIA starts, the steps are `check` and `report`, and the report is that of TiaChangeReports `--git`, with the HMI whatever `--hmi` says. `--compile`, `--safety` and `--no-cache` are usage errors with it.

`--exporter fake` with `runner\samples\` plays every step without TIA ([samples](../../../TiaArchiveCompare/runner/samples/README.md)).

## Inputs

`inputs.classify` makes each input an **archive**, a **project** or **exports**, or gives a `problem` sentence, and the check step fails with it. Which inputs are taken: [its README](../../../TiaArchiveCompare/README.md#what-it-does-not), Other TIA versions, Several projects in a folder and Projects open in TIA.

With `--git` each input is a **commit** (`inputs.CommitSource`), and the check step fails with the sentence of `gitrepo.compare_problem`.

**Secrets** go from the window to the runner on stdin, and from the runner to the exporter in tool arguments on the child's stdin. They never appear on a command line, in an event, in `log.txt` or in `run.json`.

## Events

Runner stdout, one JSON object per line, `t` its kind. Diagnostics go to stderr and `log.txt`.

| `t` | Fields | Window |
|---|---|---|
| `plan` | `steps: [{id, text}]` | The step list, all pending |
| `step` | `id`, `state` (`running`, `done`, `failed`, `cancelled`, `skipped`), `ms`, `error?`, `last_ms?` | Icon, bold while running, time |
| `progress` | `id`, `done`, `total`, `item` | Bar and "<step>: 25 of 40 (<item>)". The export's: at most 10 a second, the last of a part always. `X.cache`: one per change of the MB count |
| `log` | `level` (`info`, `warn`, `error`), `text` | A log line |
| `tia` | `pid` | Kept for Stop now |
| `prompt` | `text`, `answer` | A TIA message the exporter answered: a warning |
| `ask` | `id`, `kind` (`safety_password`, `umc_login`), `project`, `hint?` | Asks the person, answers on stdin |
| `end` | `ok`, `report?`, `folder?`, `changed?`, `moved?`, `not_exported?`, `cancelled?`, `error?` | The result line, Open report, the "Not in the report" list |

`changed` counts the changed, new and deleted blocks, tag tables and, with `--hmi`, HMI objects; `moved` what only moved to another folder. A `why` in `not_exported` starts with the side it holds for ("A: ", "B: ", "A and B: "), or "the report could not read it: ".

## Commands

Runner stdin, one JSON object per line:

```
{"t":"cancel"}
{"t":"answer","id":...,"user":...,"password":...,"umc_global":true}
{"t":"answer","id":...,"skip":true}
```

**Cancel** ends the throwaway TIA at once, deletes the copy and the unfinished export, and closes the run with `end`. A closed stdout counts as a cancel, as the window is gone. End of stdin does not: an answer still missing counts as skipped. The window offers **Stop now** when no `end` came 120 s after the cancel: it ends the runner's process tree and the TIA of the last `tia` event. With `--no-ask`, a password or login TIA asks for counts as skipped at once.

## Steps

Per input, A then B:

| Step id | What |
|---|---|
| `check` (once) | TIA V20 and Openness, the Openness group, disk, memory. A problem fails an input's `start`, not the check, so cached inputs still compare |
| `X.cache` | Hash the source, look for an earlier export |
| `X.start`, `X.open` | Start TIA without a window, open the copy, upgrade if needed. The login loop runs here |
| `X.compile` | Only with `--compile`. Never saved |
| `X.export` | One `full_export` call per part, with progress per object |
| `X.close` | Also after a failure or cancel. A failed close ends TIA hard |
| `X.folder` | In place of the above, for an export folder |
| `report` (once) | Compare and write |

A cache hit marks `start` to `close` skipped. After a failure the rest is skipped. `end.error` is "<step text>: <plain sentence>" (`errors.plain`), and the Siemens text goes to the log.

**Parts** (`exporter.PARTS`, `HMI_PARTS`): `blocks`, `dbs`, `types`, `library_types`, and with `--hmi` the `hmi_*` parts per HMI device and `graphics` once. Without `--hmi` the report gets `--only plc`.

## The bridge seam

`bridge.BridgeExporter` starts `TiaBridge\TiaBridge.ps1 -SettingsPath <work>\settings.json` per input and talks MCP over stdio.

- **Settings:** `projectsRoot` is the parent of the export folder and `backgroundRoot` is `<work>\copy`. Nothing goes to the user's project repos.
- **Calls:** `background_open` (`plain: true`, an archive as a copy with a short name, a project as it is, a login if given), then `safety_login`, `compile`, `full_export` per part and `background_close`. Arguments are checked against `tools/list`: a missing `plain` is left out and the step goes on; a login the bridge cannot take fails the step, saying so.
- **Progress:** [the bridge's stderr lines](tia-bridge.md#progress-lines). Other stderr lines reach `log.txt` as `diag  bridge: ...` during a call. The runner keeps the last of them, during a call or between calls: when the bridge ends or stops answering, the last five go into the failure, written to `log.txt` as `TIA: ...; last lines: ...`.
- **Prompts:** in each result's `prompts`, which become `prompt` events.
- **Version:** `tiabridge-<hash of its scripts>-c<client version>`, part of the cache key, so a changed exporter exports again.

## Cache

`<data root>\exports\<key>\` holds `export\` and `meta.json`. The data root defaults to `%LOCALAPPDATA%\TIA Compare`.

- **Key:** SHA-256 of the source (an archive's bytes, or a project folder's names and bytes), the TIA version, the exporter version, the parts, and the compile mode actually used.
- **Write:** an entry is built in the work folder and renamed in when complete, so a cancel or crash leaves no half entry.
- **Keep:** the 10 entries used last, never this run's. `--no-cache` skips the lookup and replaces the entry.

## Folders

**Run folder:** `<out root>\<yyyy-MM-dd_HHmm> <A> vs <B>\`, by default under `Documents\TIA Compare`, holding `report.html`, `log.txt` and `run.json` (inputs, options, steps, not exported, prompts, result).

**Work folder:** `<data root>\work\<pid>\`, removed at the end of the run. A folder of a process no longer running goes at the next start. `<data root>\times.json` keeps the last time of each kind of step, for `last_ms`.

## Download

`package\build.py` makes `TIA-Archive-Compare-<version>.zip`, and `package\check.py` checks it. The commands and the release workflow: `CONTRIBUTING.md`, The download of TIA Archive Compare.

**The repo's layout, cut down.** The zip holds one folder, `TIA-Archive-Compare-<version>\`, laid out as the repo is, so every path the code finds by its own location holds unchanged. The runner finds TiaChangeReports beside `TiaArchiveCompare`, the report finds TiaHmiGenerator, and the bridge seam finds `TiaBridge\TiaBridge.ps1`. `package_files` takes the tracked files of `TiaArchiveCompare\runner`, `window`, TiaChangeReports, TiaHmiGenerator and TiaBridge, without their tests, plus `LICENSE` and `NOTICE`. Of the tests it keeps one folder, `TiaChangeReports\tests\fixtures\plant`, which `runner\fake.py` plays for the samples. Files come from git's index by name, with their content from the working tree, so an untracked `TiaBridge\settings.json` never goes in. The build names each tracked file that differs from `HEAD`.

**Python beside the window.** `TiaArchiveCompare\window\python\` holds uv's standalone CPython of `.python-version`, with the packages of `uv.lock` in its `Lib\site-packages`. The window and the shortcut already look there before the `.venv`, so the code has no download mode. Python's embeddable zip was not taken, as it has no tkinter. PyInstaller was not taken either: its frozen program is not a `python.exe` that the window can start the runner with, nor one the runner can start TiaChangeReports with (`sys.executable -m`). Its one-folder mode keeps the bridge's scripts as files too, but inside its own `_internal` folder, where the paths of the repo do not hold.

**The launcher.** `TIA Archive Compare.exe`, at the top of the folder, comes from `package\launcher.cs`, compiled by Windows PowerShell's `Add-Type`, so the build needs no SDK. It is a Windows program, as `pythonw.exe` is, so no console opens. It starts `pythonw.exe -X utf8 -m TiaArchiveCompare.window` from its own folder with its own command line passed on unchanged, so a file dropped on it stands in the Before box, as one dropped on the shortcut of a clone does. It takes `PYTHONHOME` and `PYTHONPATH` out of the environment and sets `PYTHONNOUSERSITE`, so a Python on the PC cannot reach into the download's. The window and the runner inherit that environment. The launcher waits for the window and returns its exit code. In a download, the shortcut of `window\shortcut.py` starts the launcher. The launcher is not signed, so SmartScreen warns once.

**Settings and cache** stay where a clone keeps them, as [the README](../../../TiaArchiveCompare/README.md#from-the-download) tells a user: nothing about them depends on where the code is. The [Folders](#folders) and [Cache](#cache) above hold for a download unchanged.

**The check** (`package\check.py`, whose head lists its steps) runs the download as a person gets it, so that nothing of the clone can stand in. Its path has a space and an umlaut, and its `PATH` leaves out the Windows folder, which may hold `py.exe`. The window starts by the launcher with no runner named, so the Python it finds and the title it shows are the download's own.
