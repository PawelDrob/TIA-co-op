---
name: coordinate
description: "Run ticket and audit sessions over a wayfinder map: start, watch, relay, close."
argument-hint: "<effort folder>"
disable-model-invocation: true
---

You work a map by running other sessions; you do not write the tickets' code. The map, its tickets, the dashboard and `git worktree list` hold the state, so keep it there: a decision goes in its ticket with a gist on the map, and only what they cannot hold goes in a handoff.

Starting, watching and closing a session: [the sessions file](SESSIONS.md).

## Steps

1. **Take stock.** Read the map, every ticket's `Status:`, the running sessions, `git worktree list` and unread answers on [review pages](../review-page/SKILL.md). Done when each open session, worktree and answer has its next action, and the maintainer has the open questions in one message, most important first.
2. **Sequence.** Take the frontier as [the tracker doc](../../../docs/agents/issue-tracker.md) defines it. Run tickets at once only when their files do not overlap; a ticket that touches everything runs alone. Done when each ticket you start is `claimed`, with its first prompt naming you, its worktree, its branch and the sessions beside it with their files.
3. **Watch and relay,** from the first session on, without waiting for the next message. On an event read that session's terminal, send findings on or start the next step, and tell the maintainer only what needs them. Record their answers in the ticket. Done when every session is working or waits on something you have named.
4. **Audit.** A ticket at `in-review` from its ticket session gets a fresh session in the same worktree, by `audit` in the sessions file. Findings go to the ticket session, then the same audit session audits again. A page waiting for a person's look: relay the answer to the audit session, which acts on it by step 5 of the [audit](../audit/SKILL.md) skill. When that session has ended, act on it yourself by the same step: a yes by its code-only pass; a no or a request to reword as its findings, sent to the ticket session, with a fresh audit once the ticket is back at `in-review`; either way take the page down. A pass, code-only or after the person's yes: relay the audit's report, then merge with `merge` of the sessions file, with `--keep-tree` while the ticket owes a real run. A stop on a rebase conflict or a failed hook goes back to the audit session; anything else, to the maintainer. Done when the ticket is `done`.
5. **Close.** `merge` closes a merged ticket's sessions with its tree and branch. Close any other session once its ticket is closed, its report is relayed and no question is open, without asking. Close a tree kept for a real run once the run is done. A follow-up goes to the same session while it is open, otherwise to a new one. Done when `git worktree list` holds only open work, and the pages of closed sessions are down.

Repeat from step 2 until the frontier is empty.

## Sessions that go cold or wrong

`wayfinder`, `handoff` and `retro` run only on a typed prompt: the Skill tool refuses them. Send the prompt into a session you run; in your own session, ask the maintainer to type it.

- **Charting:** `/mattpocock-skills:wayfinder` makes the map and resolves its decision tickets.
- **Cold,** a session too long to go on well: `/mattpocock-skills:handoff <what comes next>`. It writes to the OS temp folder, so put that path in the ticket's `## Comments`, or in the map's Notes for your own. Decisions go in the ticket, not the note.
- **Went wrong:** `/mattpocock-skills:retro <session>`, and turn what it finds into a check, a skill line or a coding standard.

## Throughout

- **What counts as an answer:** only the maintainer's own words. A session's suggested input line is a guess; never send it.
- **Permission prompts** in a session: a one-time yes at most, and say so. Leave "always allow" to the maintainer.
- **Pushing** waits for the maintainer's word, and each push takes its own.
- **TIA:** one bridge per TIA, yours; sessions write files and ask, and you import, compile and export. With another coordinator on this machine, tell it before you use a TIA and when you are done: in between, its bridge keeps off that TIA. After a merge that changes `TiaBridge\`, your bridge still runs the code it started with: ask the maintainer to reconnect it with `/mcp`, then `connect`.
- **After a PC restart:** start what is not running yet, the [development dashboard](../../../docs/user/development-dashboard.md#start-it), the [TIA dashboard](../tia-dashboard/SKILL.md) and the [TIA watcher](../../../TiaAgentStatus/README.md#how-to-use); then `list` and `watch` of the sessions file, whose "After a restart" says how sessions come back.
- **Notes and tickets** with Windows paths: change them with the Edit tool. Python string escapes have turned `\f`, `\b` and `\1` in paths into control characters; `check` in the sessions file finds them.
