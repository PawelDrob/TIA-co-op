# Sessions

Start, watch and close sessions with one tool. `<session>` below is `<main tree>\.venv\Scripts\python.exe -X utf8 <main tree>\tools\session\session.py`, run from the main working tree, the first line of `git worktree list`: `close` refuses to remove a tree its folder, Python or script lie in. `<session> <command> --help` has the options.

## Start

```
<session> start <ticket file> --coordinator <who> --beside "<sessions and their files>" -- --permission-mode auto
```

It makes the worktree and branch beside the clone, opens the session, sends `/ticket`, waits for the turn to end with the ticket `claimed`, and sends `/mattpocock-skills:implement`. That can take minutes, so run it in the background. Exit code 3 means the session is not ready, and it prints what the session said: answer with `prompt`, then `<session> prompt <name> --implement`. Done when the command exits 0 and `<session> list` shows the session.

- **Where it runs:** a herdr tab from inside a herdr pane, otherwise headless, one detached `claude -p` per turn. `--terminal print` is for a person with their own terminals: it makes the worktree and prints what to run and type. Their session still reports to `watch`. They accept a trust prompt for the worktree only, the home folder never. This route has not been tried with a person typing: the commands it prints were checked in Git Bash, nothing more.
- **`--worktree`** takes an absolute path outside the clone: a relative one has landed inside `.scratch\`.
- **After `--`** goes to claude. A session nobody watches stops at each permission prompt, so add the mode you accept for that. Add `--add-dir` with the folder of project repos when the ticket reads them.
- **Guards it sets:** questions end the turn, no second bridge on a TIA, no pushing.
- **MCP servers:** none unless asked for, as each one is a process per session, used or not. `--strict-mcp-config` keeps out those of the user, of a plugin and of claude.ai, `--no-chrome` Claude in Chrome; a plain `claude` in the clone still has them all. `--allow-tia` starts this clone's bridge, only for a ticket that grants a background session on a named copy. `--allow-browser` starts Playwright, for a ticket that needs a browser; its tools read `mcp__playwright__*`. Another server: `-- --mcp-config <file>`, which adds to these. An audit gets neither option from its ticket session, so give it the option; a `--mcp-config` after `--` does carry over, as all of that does. A session that needs one it did not get ends its turn saying so. Then `<session> close <name> --session-only`, and `start` again with the option, or for `audit<name>`, `audit <name>`: a fresh session in the same tree and branch, which reads the ticket's state from its file.
- **After a restart:** left to itself herdr brings a session back as `claude --resume <id>`, with no guards and no hooks. So the session's hook tells herdr its whole command when it starts, after `/clear` with its new id, and on every prompt and turn end, and herdr uses that instead. A session started before this existed, or whose command herdr refuses (an apostrophe or a control character in an argument, more than 64 arguments or 8 KiB), still comes back bare. `start` and `audit` name a refused command as they open the session, which runs on. After a restart, `list` and `watch` say so: `runs without its guards`. `its arguments could not be read` accuses nobody: herdr did not say what they are. Put it back by hand, once its turn has ended: `herdr agent prompt <pane> /exit`, then the command `<session> list --resume` prints under it, which gives it a name that lasts through a restart. From Git Bash, set `MSYS_NO_PATHCONV=1` for the `/exit`: without it the session gets the prompt `C:/Program Files/Git/exit`. Its start, or for an older session its first prompt, then reports the command again, if its record holds `args`. `list --resume` builds each command from the session's record and the id its hook last wrote down, so it needs no herdr. A session whose hooks never wrote one, as one started before `list --resume` existed that then came back bare, gets `<id>` and where to read it: for herdr `agent_session.value` of `herdr pane get <pane>`, for a person's own terminal the name of its transcript, `<id>.jsonl` under `~\.claude\projects\`. `list --resume` quotes each argument, for PowerShell and Git Bash alike: unquoted, PowerShell runs `(git push:*)` as a command and the session starts without those deny rules, and as its `--settings` is there, no sign says so. It uses single quotes, and double quotes for an argument with an apostrophe, which single quotes cannot hold. `COMES BACK WITHOUT ITS GUARDS` under a session marks one of two things. An older session's record holds no arguments: start it with the command it was started with. Or herdr will not keep the command for the next restart, and names why. A session whose pane herdr did not bring back: `<session> close <name> --session-only`, then `start` again with the options it was started with, `--coordinator`, `--beside`, `--name`, `--branch`, `--worktree`, `--allow-tia`, `--allow-browser` and the arguments after `--`, or for `audit<name>`, `audit <name>` with its own `--allow-*` options: a fresh session in the same tree and branch, which reads the ticket's state from its file. Its `session.json` holds the tree, the branch and, as `extra`, the arguments after `--`. A headless session needs nothing typed; one in a person's own terminal gets `cd` to its tree and its `claude` command. For a session started with `-- --permission-mode auto` it prints:

  ```
  herdr agent start <name> --kind claude --pane <pane> -- --resume <id> '--add-dir' '<main tree>' '--strict-mcp-config' '--no-chrome' '--settings' '<main tree>\.scratch\sessions\<name>\settings.json' '--disallowedTools' 'AskUserQuestion' 'mcp__tia__*' 'Bash(git push:*)' 'Bash(git * push *)' 'Bash(git * push)' 'PowerShell(git push:*)' 'PowerShell(git * push *)' 'PowerShell(git * push)' '--permission-mode' 'auto'
  ```
- **The guard on pushing** matches a command's text, so `git stash push`, `git log --grep push` and `git commit -m "... push ..."` are denied too, with no reason given. Commit such a message from a file, as `git commit -F <file>` runs, and set work aside with a temporary commit. It is a guard, not a wall: a script or an alias that pushes gets past it, so the rule itself still stands.
- **An agent that does not read `.claude/skills/`** gets "Read `.claude/skills/ticket/SKILL.md` and follow it" in the same worktree under the same rules. Check first that it reaches what the ticket needs.

After `in-review`: `<session> audit <name>` opens a fresh session `audit<name>` in the same worktree, with the ticket session's arguments after `--` unless you give it its own, and sends `/audit`. Done when `<session> read audit<name>` shows its answer.

## Watch

From the first session on, keep this running, with Claude Code's Monitor or any background runner:

```
<session> watch --effort <folder>
```

One line per event: a ticket file changed (the whole file, as a findings round sets `in-review` over `in-review`), a review answer, an answer given on a ticket's page of the dashboard (to any ticket, `answer to ticket <effort>/issues/<file>`), a turn ended with its last line (a question saves no file, so this is its signal), a session asking permission, a turn failed, a session gone, a session running without its guards, a terminal that does not answer or is down (with what herdr said), a control character in a watched ticket. `--first` exits after the first events, `--timeout` after that many seconds. Re-arming loses nothing: what happened in between comes on the next look.

On a wake, read the ticket's `Status:` with the newest entry under `## Comments`: at `claimed` its session is at work on that entry, so there is nothing to relay. `<session> read <name>` shows its terminal and last message; `<session> list` shows all of them. A session that asks permission waits for a person at its terminal, or in herdr for `herdr agent send-keys`: `prompt` does not answer that dialog. A headless session never asks, its tool is denied. Done when `watch` has printed `watching:` and lists every running session.

## Prompt

`<session> prompt <name> <text>` sends only to an open session of exactly that name. Use `--file <file>` for text with double quotes in PowerShell 5.1 or a leading `/` in Git Bash, which both change it before the tool sees it. A headless session takes its next prompt after its turn has ended; one that ended with background tasks running takes up again by itself when they end, so send it then. Done when it prints `sent to <name>`.

## Merge

`<session> merge <name>`, once the audit passed and, for a visible change or public text, the person said yes. `<name>` is the ticket session. In order:

1. It rebases the branch onto `main` in its tree, and runs `uv sync` there when the rebase brought a change to `uv.lock` or `pyproject.toml`.
2. It runs the hook for the branch, `sh .githooks/pre-commit main`. The audit's pass left a stamp, so the suites run again only when the branch moved since, as a rebase onto a newer `main` moves it.
3. It fast-forwards `main` in the main working tree. When `main` moved meanwhile, it rebases and runs the hook once more.
4. It sets `Status: done` in the ticket, and adds the commit `main` points at as the newest entry under `## Comments`.
5. It takes down the review page the ticket's `Review page:` line names, and any page titled with the name of one of its sessions.
6. It closes the ticket's sessions in the tree, `audit<name>` among them, as `close` does: the last one takes the tree and the branch.

Before step 1 it refuses unless the ticket is `in-review`, the main working tree is on `main`, the tree holds no uncommitted change and the command does not run from the tree. It cannot tell an audit's pass from a ticket waiting for its audit: run it only after the pass. It forces nothing and never pushes. At the first step that fails it stops with `merge <name> stopped: ...` and leaves tree, branch, sessions and ticket as they are. A rebase that conflicts is undone, and the files are named: the audit session rebases by its step 2. A failed hook shows its last lines and keeps its output in the session's folder. A step after the merge that fails says what was done and lists what is left to do, as commands to run from the main working tree: a second `merge` refuses, as the ticket is `done`. A page comes down with its answers, which `--done` keeps beside it. `--keep-tree` ends the sessions with `--session-only`, for a ticket that still owes a real run. Done when it prints `merged <name>: <commit> on main` and `git worktree list` no longer shows the tree, or the command has said why it stays.

## Close

`<session> close <name>` ends a session, then removes the worktree and the branch with the last session in them. `merge` runs it for a merged ticket's sessions; run it yourself for a session `merge` did not close.

It refuses before ending anything when the branch or the tree's `HEAD` is not merged, the tree holds uncommitted changes or ignored files, other than `.venv`, `__pycache__`, an ignored `*.stackdump` (a Git Bash program that crashed) and what a session's tools leave, or a process other than its own session stands in the tree, and it never forces. What its tools leave, a browser's `.playwright-mcp\` and the window's old build, `bin\` in `TiaArchiveCompare\window\`, it deletes itself before it removes the tree, and nothing else. A process that shows only after the session has ended leaves the tree whole and the session ended; close again once it has gone. A close that says what is left can be run again to finish. Standing in the tree means what Windows shows: a process started there, holding a file there or running a program from there, such as the tree's `.venv`. A Git Bash shell that went there with `cd`, or a PowerShell with `Set-Location`, holds nothing, so the tree goes whole from under it. A process this user may not read, such as an elevated one, can go unseen: the remove then stops half way and says what is left. `--session-only` ends the session and keeps both, for a ticket that still owes a real run. A tree or branch `start` did not make stays, and it says so, unless you add `--remove-tree`. A `ticket ... in-review` event can come before the turn ended, and close stops a running turn: wait for `turn ended`.

Done when `git worktree list` no longer shows the tree, or the command has said why it stays.

## Check

`<session> check [file ...]` lists control characters in `.scratch\**\*.md`, by file and line, with the path each should be when it can tell. It only reports: fix them with the Edit tool. A real line break from `\n` leaves no mark to find. Done when it prints `no control characters`.

## Names

`Sessions: <prefix>` in the map's Notes names sessions `<prefix><NN>` and `audit<prefix><NN>`, which puts their tickets under Running now on [the dashboard](../../../docs/user/development-dashboard.md) when they run in herdr, unless the ticket needs a person: the dashboard's how-to says which stay. With no such line they take the effort's name. Done when `<session> list` shows each session under its name.
