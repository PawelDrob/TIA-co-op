# TiaAgentStatus

Experimental.

Shows what happens to your TIA projects while agents work on them, without asking in chat.

## What it does

From the state files of [TiaBridge](../TiaBridge/README.md):

- **Dashboard:** a local page with what needs you and what to do, the projects worked on, what the agent is calling, its
  TIA, its HMI preview while one runs, its change reports and every call. For the preview it also reads the record each
  HMI preview keeps while it runs, in `%LOCALAPPDATA%\hmipreview\running\`, and asks that preview whether it answers.
  Its one button, **Make a change report of TIA now**, makes the change report of a project as your open TIA holds it,
  without an agent: through TiaBridge it exports the project, commits that and makes the report
  ([how](../docs/user/tia-agent-status.md#a-change-report-without-an-agent)).
- **Status line:** a TIA row in the Claude Code session that started the bridge.
- **Watcher:** a pane in [herdr](https://herdr.dev), a terminal workspace for agents, that adds the TIA state to each agent's
  tab label, sends notifications and shows all bridges as a table.

[What each view shows](../docs/user/tia-agent-status.md).

## What it does not

- Write the state files, or start or stop an HMI preview.
- Touch TIA, except through that button's report run, which saves nothing and changes nothing there, and waits while a
  bridge or another program is connected to that TIA.
- Answer other machines: `127.0.0.1` or `localhost` only, as it has no login; a proxy such as `tailscale serve` gets 403.
  Anyone on this machine can read it.
- See a message box of a TIA with a window as such: only as no CPU, after `--quiet-minutes`.

## How to use

Run [first setup](../docs/user/setup.md), or `uv sync` in the clone's folder for these alone. `<repo>` is that folder.

**Dashboard:**

```
<repo>\.venv\Scripts\pythonw.exe -X utf8 <repo>\TiaAgentStatus dashboard
```

Then open <http://127.0.0.1:8771/>. It runs with no console window, and the command returns at once. For a double-click, make
a shortcut with that line as its target. Options: `--port P` (default 8771), `--every S` (default 1 s: how often it reads
everything again; raise it on a slow PC), `--quiet-minutes M` (default 5), `--root DIR` (the projects root).

While it runs it has an icon in the notification area of the taskbar, a dark T on green, in the colours of Catppuccin Mocha. Its
tooltip says **Tia co-op: TIA dashboard** and its address. A left click on it opens the page in your default Windows browser. A
right click opens a menu: **Open Tia co-op: TIA dashboard** does the same, **Stop Tia co-op: TIA dashboard** ends the dashboard.
Windows 11 first puts a new icon behind the ^ button; drag it onto the taskbar to keep it in view. The
[development dashboard](../docs/user/development-dashboard.md) has an icon of its own, a dark D on mauve. A session with no
desktop gets no icon; the dashboard answers all the same. Ended by Task Manager, it leaves its icon behind until the mouse
passes over it.

Started a second time, it says in a box that the port is taken and ends; the first runs on with its one icon. A wrong option
comes up in a box too. To read what stops it from starting, run the same line with `python.exe`: it then stays in that
terminal, and Ctrl+C stops it.

It needs `tools\dashboard\`, which the clone holds, and Chrome or Edge 123, Firefox 120,
Safari 17.5 or later; an older browser shows it in its default colours.

**Status line:** first setup adds it to your Claude Code settings (`~\.claude\settings.json`, or the folder in
`CLAUDE_CONFIG_DIR`), with forward slashes, as Claude Code runs it through Git Bash on Windows:

```json
"statusLine": {
  "type": "command",
  "command": "\"<repo>/.venv/Scripts/python.exe\" -X utf8 \"<repo>/TiaAgentStatus\" statusline",
  "refreshInterval": 5
}
```

A running session picks the setting up. `refreshInterval` keeps the time and memory current during a long call; without it
the row changes only on new messages.

Setup never replaces a status line you have. To have both, make your own command also run the one above: it prints the
TIA row, or nothing when the session's bridge holds no TIA.

**Watcher:** in a herdr pane of its own, Ctrl+C stops it:

```
<repo>\.venv\Scripts\python.exe -X utf8 <repo>\TiaAgentStatus watch
```

Options: `--every S` (default 5 s), `--quiet-minutes M` (default 5), `--root DIR` (the projects root), `--once` (one round,
printed as plain text).

TiaBridge has to run for anything live; history and change reports show without one. herdr is needed only for the watcher:
the dashboard uses it when it is there, works without it, and renames and notifies nothing. git gives the commit subjects of
the change reports; without it a report links by its commit hash.
