# TIA Portal with agents

Guides for PLC (S7DCL) and WinCC Comfort work in TIA Portal V20, the TiaBridge MCP server (`TiaBridge\`) and the tools around it.

This file is for changing this repo. To change a TIA project, follow skill `tia-change`; the bridge's instructions and tool texts carry its rules.

## First setup

Once per clone, in the main working tree. Run it again at any time: it is also the check, and changes only what is off.

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1
```

Done when it exits 0. A `Question:` line: ask the user, then run it with `--projects-root "<path>"`. `missing` lines name what is off. Its list "A person does these" goes to the user as it stands. When you ran it for a task that needs the bridge, end your turn on that list: its `claude --continue` brings this conversation back with the server.

## Workflow skills

`/ticket` works one ticket in a worktree, `/audit` is the gate into `main`, `/coordinate` runs sessions over a map; `review-page` fires by itself. An agent kind that does not read `.claude/skills/` reads `.claude/skills/<name>/SKILL.md`; before it starts on a ticket, check it reaches what the ticket needs.

A lesson about how this repo is worked on goes in a tracked skill, check or this file, not only in an agent's memory: a clone carries nothing else.

## Python

Every Python tool runs on one environment: `pyproject.toml` and `uv.lock` (pinned) -> `.venv` of the tree, made by first setup. A worktree has its own: `uv sync` there, about a second.

`<py>` is `<this tree>\.venv\Scripts\python.exe -X utf8`, by absolute path. A tool's usage line or message that says `python` means `<py>`. New dependency: `uv add <package>`, commit both files.

## Names

This repo is public: write for strangers, with the names [`CODING_STANDARDS.md`](CODING_STANDARDS.md) allows. It also holds what review reads for.

## Documentation

`docs\` is an OKF v0.2 bundle (rules and checker: `tools\okf\README.md`): `docs\agent\` the guides an agent reads while working on a TIA project, `docs\agents\` the engineering skills' config, `docs\adr\` the decision records, `docs\user\` what is too long for a tool's README (the README is the tool's how-to for users), `docs\dev\` how the tools are built. `docs\index.md` lists everything. Where a fact goes and how a document stays true: `docs\dev\conventions.md`.

- When you change a document's content, set `generated: { by: <agent>/<model id>, at: <now with offset> }`. Formatting-only changes leave it alone.
- A `human:` entry in `verified` is a person's own: ask the maintainer.
- After changing documents, in your tree: `powershell -NoProfile -File tools\okf\Test-OkfBundle.ps1 -Path docs -WriteIndex`. A document added, moved, removed or deprecated also takes a line in `docs\log.md`.

## Commits and tests

- **The hook** (`.githooks\pre-commit`) chooses the suites for what a commit touches; its head lists them.
- **`sh .githooks/pre-commit <ref>`** runs the same choice for a branch since `<ref>`. Use it after a cherry-pick, revert or rebase, which git runs no pre-commit hook for.
- **Test commands, and the integration runs on a real TIA:** [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Worktrees** go beside the clone, one per ticket; `/ticket` and [the sessions file](.claude/skills/coordinate/SESSIONS.md) make them.
- **`grep -i` in Git Bash:** without a UTF-8 locale (none set, or `C`), the grep that Git for Windows ships (GNU grep 3.0) aborts on `-i` with fixed strings (`-F`, `fgrep`, a `-f` list or several `-e` of plain words): no output, and a `grep.exe.stackdump` where it ran. `.claude/settings.json` sets `LANG` for a Claude Code session, and first setup checks it; in any other shell, or under `LC_ALL=C`: `LC_ALL=C.UTF-8 grep ...`, or the agent's own search tool.
- **Ending a process:** use a stop file, or the number Windows reports for it. Git Bash's process numbers are its own, and `taskkill` with one can end an unrelated process.

## Agent skills

### Issue tracker

Local markdown files with this repo's lifecycle states, execution tickets in a map. Public reports arrive as GitHub issues (`CONTRIBUTING.md`). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` plus `docs/adr/` (ADRs keep an OKF header). See `docs/agents/domain.md`.
