---
type: How-To
title: Setup
description: How to set up this repository on a Windows PC, with the setup window a person double-clicks or one command for agents, and what the window shows after the first run.
tags: [setup, tia-portal]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-19T19:18:10-05:00 }
sources:
  - id: setup
    resource: ../../tools/setup/
    title: The first setup command
---

# Setup

## First setup

To work with agents on TIA projects or on this repository. You need Windows, [uv](https://docs.astral.sh/uv/),
[git](https://git-scm.com/downloads/win) and TIA Portal V20 with the TIA Openness option. It was tested with
[Claude Code](https://code.claude.com/docs) only, which is not a requirement. Claude Code can run all of this for you.

Clone this repository. Then either double-click **Setup** in the clone's folder ([The setup window](#the-setup-window)),
or run this there:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1
```

Both do the same: the window runs the steps of the command, and its buttons make the changes the command makes. The command creates the Python environment and turns on the commit checks. With Claude Code installed, it also registers the MCP
server `tia` for your Windows user and installs the plugin `mattpocock-skills@claude-plugins-official`. It adds the TIA row
to the status line of Claude Code in your settings (`~\.claude\settings.json`), unless you already have a status line: that
one stays, and setup says how to add the row to it ([Status line](../../TiaAgentStatus/README.md#how-to-use)). It then
names anything that is missing: TIA Portal V20, membership of the Windows group **Siemens TIA Openness**, git or uv. Fix
what it names and run it again.

With no `claude` on the PATH, setup does the rest, and that alone is no failure: exit code 0. It registers no server and no
plugin, says so in its list of what you do yourself, and gives the command that starts the bridge. No other agent has been
tried. To try one, give it that command:

```
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "<clone>\TiaBridge\TiaBridge.ps1"
```

The first run asks where your project repositories should live, and offers `%USERPROFILE%\TIA-Projects`. Give your answer
with `--projects-root`:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1 --projects-root "C:\TIA-Projects"
```

The folder goes in `TiaBridge\settings.json`. Setup does not create it: the bridge creates `_bridge\sessions` in it each time
it starts; with Claude Code, every new session and `claude mcp get tia` start it. Setup also adds allow rules for that folder to your Claude Code settings
(`~\.claude\settings.json`): read, edit and git. The git rules match `git -C "C:/TIA-Projects/<repo>"`, with forward
slashes. A git command with backslashes, or with a `cd` first, still asks for permission. The rules match the start of the
command, so `git -C "C:/TIA-Projects/../other"` also passes. TIA refuses an archive path over 143 characters, so setup warns
you when the folder leaves little room for a project name.

Every project repo has a `standards` folder for your own rules, a style guide or a checklist, in any file format. Agents read
what fits the work before they edit, and follow it in what they write. To start each new repo with the same files, add
`standardsTemplate` to `TiaBridge\settings.json`: `{ "standardsTemplate": "C:\\Standards" }`. That folder is copied when a repo
is created, and never over a file. An existing repo stays as it is, so copy files there yourself. A single file that points to
shared standards is enough.

Then you do these yourself, once:

1. With Claude Code, if a session in the clone's folder ran setup for you, end it and run `claude --continue` there: it
   comes back with that conversation and its task, now with the server, so you tell it to go on. Otherwise start a new
   session in the clone's folder. Accept its trust prompt, and approve the plugin if it asks.
2. At the first connect, TIA asks whether to allow access. Answer **Yes**.

Run the command again at any time: it shows the stored folder, names what is missing and changes nothing that is already
right. To move to another folder, run it with a new `--projects-root`. Setup then replaces the setting and the rules, and
moves no repository: those in the old folder stay there. Restart any bridge that is running, because it keeps the old
value until then.

The settings of the bridge are in [TiaBridge](../../TiaBridge/README.md#settings).

**`claude plugin list` shows the plugin many times.** Claude Code has been seen to add an entry of project scope for clones
and worktrees where sessions ran, and to keep it after the folder is gone. Leave these entries: no harm has been seen from
them, and removing one also changes the tracked `.claude/settings.json`.

## The setup window

`Setup.wsf` at the top of the clone. Windows runs it with Windows Script Host, so no console window opens. Where your
company has turned Windows Script Host off, Windows says so in a box: use the command above instead.

**The first double-click** needs only uv. Without uv, a box says so and offers to open uv's install page. With uv and no
Python environment yet, a console window runs `uv sync` so that you see it work (the first one downloads Python). It closes
by itself when it is done, or stays open with uv's message when it fails. Then the window opens on its first page.

**The pages.** Each has a short title and a line saying what it is. Each row says what it is about, is marked optional
when you can do without it, and, when something is missing, says how to get it. A row that changes something says what and
in which file, shows the commands it runs on lines of their own, and changes nothing until you press its button. **Show
what changes** lists each change in full, such as every allow rule with its whole path.

| Page | What it holds |
|---|---|
| Installed | uv, git, Claude Code, TIA Portal V20 with TIA Openness, the Windows group **Siemens TIA Openness**. Nothing missing stops the pages |
| Repository settings | The commit checks, and the Claude Code settings of this repository |
| Bridge | The folder of your project repos (the stored one, or `%USERPROFILE%\TIA-Projects` to start with; type it or pick it with Browse), the server `tia`, the plugin, the status line, the bridge's other settings |
| Block viewer | Two rows, each on its own, for your Windows user only. Block viewer (.s7dcl): Register, and a double-click on an `.s7dcl` file opens it in the viewer of this clone; Unregister takes it back. These are the viewer's `--register` and `--unregister`. Block viewer in "Open with" (.xml): Register, and a right-click on an `.xml` file, Open with, offers Block viewer, while what a double-click on one opens stays; Unregister takes it back. These are `--register-xml` and `--unregister-xml` |
| Dashboards | The [development dashboard](development-dashboard.md) and the [TIA dashboard](../../TiaAgentStatus/README.md): Start (no console window) or, while one runs, Open. Nothing starts with Windows; its icon's menu in the notification area stops it |
| By hand | What only you can do |

The first double-click walks them with Back and Next, and Finish ends it. Next without pressing a button skips that step. A
change that fails shows the tool's own message under its row. Claude Code reads servers and plugins when a session starts:
end a session that was running and run `claude --continue`.

**After Finish** the same double-click opens a menu: one entry a page, with what it holds now ("All set", or how many are
not done, a step you skipped too, and how many are missing). Open goes to the page, read fresh, as is everything on
Refresh. A dashboard shows as running only when its port answers as that dashboard; a dashboard of another clone says so,
and another program
on its port is named with its process number. Which clones finished the first run is kept in
`%LOCALAPPDATA%\TIA-co-op\setup-window.json`: delete it, and the pages come again.

In a worktree the window says what the command says: a worktree needs only `uv sync`, and its settings belong to the main
tree.
