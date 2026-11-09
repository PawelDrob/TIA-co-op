---
name: ticket
description: Work one ticket of this repo in its own worktree, up to the audit.
argument-hint: "<ticket file> [worktree, branch, coordinator, sessions beside you, notes]"
disable-model-invocation: true
---

One ticket, one session, one worktree. Your work ends at `in-review`: an audit session (`/audit`) passes it, and the coordinator merges it. What the prompt adds holds on top of this.

## Steps

1. **Stand in the worktree.** The prompt names it. In the main working tree with none named, make one by `start` with `--terminal print` in [the sessions file](../coordinate/SESSIONS.md) and end your turn asking for a session there with what it prints. Done when `git rev-parse --git-dir` differs from `git rev-parse --git-common-dir` and `git branch --show-current` is the ticket's branch.
2. **Set up.** `uv sync` here; `<py>` in `AGENTS.md` means this worktree's `.venv`. Done when `uv sync` has finished in this folder without an error.
3. **Claim.** The ticket lives in the main working tree's `.scratch\`; its format is in [the tracker doc](../../../docs/agents/issue-tracker.md). Read it and the tickets it names, and set `Status: claimed`. Then end your turn with: "Ready: send `/mattpocock-skills:implement <ticket file>`". That skill runs only on a typed prompt, the Skill tool refuses it. Done when the status is saved and you can state the ticket's done condition in that message.
4. **Implement,** on that prompt. Where it says `code-review`, call the Skill tool with `mattpocock-skills:code-review` (plain `code-review` can reach another skill), fixed point `main`, and the ticket's absolute path as the spec: a worktree has no `.scratch\`. Run this review though an audit follows: it saves a round through the coordinator. Done when the ticket's done condition from step 3 is met, every commit passed the hook, and every finding is fixed or named in your report.
5. **Hand over.** First check every command and path you wrote, and every file that repeats a text you changed: each command against the options of its tool, each path on disk, each repeat against your change. Then set `Status: in-review`; commits and what is open go under `## Comments`. Report what changed, what is open and the commits, leaving out restated code and rare side cases. Done when each of those is checked, the ticket reads `in-review` and the report is your last message.
6. **Findings round,** when an audit sends findings back; they are the newest entry under `## Comments`. Set `Status: claimed`, fix each one, commit, and add a line under `## Comments` naming what was fixed and the commits: that saved file is what a watch sees. Then step 5 again. Done when every finding of that entry is fixed, or you have asked about it in your report, and the ticket reads `in-review`.

## Throughout

- **Branch only.** Commit on the ticket's branch. The merge belongs to the coordinator after the audit, and a push to the maintainer's word.
- **Stage by path,** each file you meant, and read `git diff --cached` before the commit, for stray files and for names by `CODING_STANDARDS.md`.
- **A commit denied with no reason:** the guard on pushing matches the word `push` anywhere in a command. Write the message to a file and use `git commit -F <file>`.
- **Your files.** Keep to the ticket's files. When you need one that a session beside you holds (the prompt names them), say so before you touch it.
- **Questions end the turn.** End it with the question, standing on its own: whoever reads your terminal relays it, and a dialog would stall the session.
- **Pictures and decisions** for a person: call the Skill tool with `review-page`. Its files go in the main working tree's `.scratch\<effort>\pages\`, not in this worktree.
- **No TIA.** Use no `tia` tool: another session's bridge may be attached, and a second one on a TIA has hung it. Write what you need exported or imported and why, and ask. A ticket may grant a background session on a named copy, with the maintainer's go.
- **MCP servers.** A session from `session.py` has only the servers it was started with, none by default. When the ticket needs one you lack, a browser or the bridge, do not get it another way: end your turn saying which and why. The coordinator starts the session again with it.
- **Project repos** the prompt adds are read-only: no git command that writes there.
