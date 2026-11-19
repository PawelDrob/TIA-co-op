---
type: Guide
title: First setup internals
description: How first setup's steps look before they change, so that the command and the setup window run the same checks and changes; what the window keeps; how it tells a dashboard on a port from another program.
tags: [dev, setup, dashboard]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-19T10:23:17-05:00 }
sources:
  - id: setup
    resource: ../../../tools/setup/
    title: First setup and its window
---

# First setup internals

Two ways in, one engine. `tools\setup\setup.ps1` is the command agents run; `Setup.wsf` at the clone's top starts the
window a person double-clicks ([Setup](../../user/setup.md)). Both run the steps of `tools\setup\setup.py`.

## Steps and findings

A step is a function that looks and returns a list of `Finding`s: `ok`, `done`, `warning`, `missing`, `note` (a line
under the one before), `question`, or `change`. A `change` is one not made yet: its text says what it would change and
in which file, and its `make()` makes it, reading the files again first, and returns the findings of the outcome. A
step changes nothing until `make()` is called.

- The command calls each step in setup's order (`steps()`), prints each finding, and calls `make()` of a change at
  once. `tools\setup\tests\test_setup.py` holds what it prints and its exit codes, run as a person or an agent runs it.
- The window calls the same steps to read, and `make()` when a person presses the change's button. It shows a finding's
  words for the window, not the line the command prints, which may speak of the command (`--projects-root`) or name only
  its topic: `shown`, sentences with short paths (`short()`: under the clone from its folder, under the user's folder
  from `~`); `commands`, one a line, drawn in a fixed-width field that never wraps; `details`, what changes with full
  paths, behind "Show what changes". `window_last_steps()` is `last_steps()` in the same form.
- `topic` groups the findings into the window's rows. `person_step` is a line of "A person does these".

The window adds no rule of its own about what is set up. What is registered is read fresh on each read and on Refresh;
the window keeps only which clones finished the first run, in `%LOCALAPPDATA%\TIA-co-op\setup-window.json`. The block
viewer's registration goes through `TiaChangeReports\viewer\register.py` (`state()`, `register()`, `unregister()`), the
commands `--register` and `--unregister` run.

## Dashboards on their ports

Both dashboards answer `GET /api/about` with `{"app": "development-dashboard" | "tia-dashboard", "clone": "<folder>"}`
(`tools\dashboard\live.py`, `send_about`). The window counts a dashboard as running only when its port answers so, and
names the clone it runs from. A dashboard started before it had that page is told by its `<h1>`, as the skill
`tia-dashboard` tells it. Anything else on the port is another program, named by its process number from `netstat`.
Start runs the dashboard's own command with `pythonw.exe` and `CREATE_NO_WINDOW`; stopping stays with its icon's menu.

## No console

`Setup.wsf` runs under `wscript.exe` and starts `pythonw.exe`, neither of which has a console. Every program the window
starts (git, claude, whoami, netstat, tasklist, a dashboard) starts with `CREATE_NO_WINDOW`; `run()` of `setup.py` does
so for the command too, where it changes nothing as the output is captured. The one console is `uv sync` on the first
double-click, before the `.venv` exists.

## Tests

[Testing](../testing.md) and the [window's README](../../../tools/setup/window/README.md) say what runs in the hook and
what by hand.
