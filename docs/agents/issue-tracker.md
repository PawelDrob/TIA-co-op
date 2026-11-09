---
type: Standard
title: Issue tracker for agent skills
description: Where the engineering skills keep issues, specs and wayfinder maps in this repo, as markdown files under .scratch/, the status values and ticket head those files use, and how a ticket asks the maintainer a question.
tags: [agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-08T19:48:57-05:00 }
sources:
  - id: dashboard
    resource: ../../tools/dashboard/board.py
    title: The development dashboard's ticket reader
---

# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`. The folder is gitignored: tickets stay on your machine, and a fresh clone has none until the first one is written. Every worktree of a clone uses the `.scratch/` of the main working tree, so write there from a worktree too.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Execution tickets are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file. Nothing else goes in `issues/`: the dashboard counts every `.md` there as a ticket, so a note shows as Not readable. Notes go in `research/`
- Take a ticket's number just before you write its file, the next one free in its `issues/`: other sessions file there too
- Files made for a [review page](../../.claude/skills/review-page/SKILL.md), renders and HTML, go in `.scratch/<feature-slug>/pages/`: out of the worktree, which `close` in [the sessions file](../../.claude/skills/coordinate/SESSIONS.md) removes only when it holds no stray files
- Triage state is recorded as a `Status:` line near the top of each issue file (see [triage-labels.md](triage-labels.md) for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

**PRs as a request surface: no.** _(`/triage` reads this flag; set it to `yes` if this repo starts treating external PRs as feature requests.)_

## Ticket head

The title and these lines open every ticket, within its first 16 lines. The [development dashboard](../user/development-dashboard.md) reads them, and shows a ticket it cannot read as "Not readable".

```
# 03 Read the old header

Type: task
Status: ready-for-agent
Blocked by: 01, other-effort/02
```

- `Status:` holds one value and nothing after it. Narrative, commit hashes, push state and human or scheduling gates go under `## Comments`.
- `Blocked by:` holds `none`, or comma-separated ticket numbers, `<effort>/NN` for a ticket of another effort. `to-tickets` offers titles and "None (can start immediately)": write the numbers and `none` instead. The dashboard reads that "None" as `none`; a title shows as Not readable.
- `Type:` is optional outside a map; keep one a ticket already has.
- `Category:` is optional: `bug` or `enhancement`, set by triage.
- `Review page:` is optional: the title of the [review page](../../.claude/skills/review-page/SKILL.md) about this ticket, as given to `--title`. While that page waits for answers, the ticket waits for the maintainer; while it is up, the ticket links to it.
- A blocker is satisfied once its ticket is closed: `done`, `resolved` or `wontfix`. An edge stays until the maintainer overrides it. A closed ticket with no recorded dependencies has `Blocked by: none`.

## Status values

| Ticket | Values |
|---|---|
| Execution ticket | A triage role, then `claimed` (work in progress), `in-review` (awaiting audit or acceptance), `done` (accepted and closed). `wontfix` also closes it. |
| Decision ticket (`research`, `prototype`, `grilling`) | `open`, `claimed`, `resolved`. No triage roles. |

`claimed`, `in-review` and `done` are this repo's lifecycle states, not extra triage roles. A ticket reaches `done` by acceptance, which a merge alone does not establish; the maintainer may assign remaining checks to a separate follow-up ticket.

## Asking the maintainer

A ticket shows under "Waits for you" on the [development dashboard](../user/development-dashboard.md) only when it is open, nothing blocks it and it asks the maintainer something, whatever its open status. A closed ticket asks nothing, and a blocked one asks nothing until its blockers are closed:

- **A question:** a `## Question for the maintainer` section before `## Comments`, holding the question, written to stand on its own; one in a code block does not count. Wayfinder's `## Question`, the body of every wayfinder ticket, is for whoever works on the ticket and asks the maintainer nothing. The ticket's page on the dashboard shows the question with an answer box. The answer goes in as the newest entry under `## Comments` (`- <name>, <date time>, answer on the dashboard: <answer>`), the heading becomes `## Question for the maintainer, answered <date time>`, which asks nothing more, and the coordinator's watch reports it (`answer to ticket ...`). One question per section; a second one waits until the first is answered.
- **A review page:** a `Review page:` line in the head, naming a page that waits for answers. The question stays on the page, answered there.
- **A wayfinder ticket for a person:** an open `grilling` or `prototype` ticket, once nothing blocks it: its body is the question, answered in its session with the agent that runs it. Its page on the dashboard has no answer box.

Nothing else asks: an `in-review` or `needs-info` ticket that does none of these is under "With the coordinator", a `ready-for-human` one under "Yours to start". To ask, write the section or the line; asking only in a report or a session's terminal leaves the dashboard silent.

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `open`/`claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every ticket it lists is closed.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins. An effort whose map Notes hold a line starting `Postponed` has no frontier until the maintainer resumes it.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
- **Research findings**: `.scratch/<effort>/research/`, with a context pointer from the ticket, in place of a research branch.
- **Execution in a map**: a map carries execution only when its Notes say so. Its `Type: task` tickets then use the execution ticket values above, and `ready-for-agent` counts as open for the frontier. Its decision tickets keep `open`, `claimed`, `resolved`.
