---
type: How-To
title: Development dashboard
description: How to see what waits for you while agents change this repo, answer their questions on review pages and on a ticket's page, take a page down, and reach the dashboard from another machine through tailscale serve.
tags: [dashboard, agents, tickets, review-pages]
status: draft
generated: { by: claude-code/claude-fable-5-2, at: 2026-11-09T17:43:00-05:00 }
sources:
  - id: code
    resource: ../../tools/dashboard/
    title: Development dashboard (server, review pages, tickets)
---

# Development dashboard

For people changing this repo with agents. One local page shows what waits for you: the agents' questions, which you answer
on a review page or on the ticket's own page, and the tickets of every effort under `.scratch\`, with a list of topics that stays in view. It updates by itself. Pages and answers stay on your machine:
everything a page loads comes from the repo, and nothing is fetched from the internet.

Pages start in the light or dark mode of your system. The icon at the top right of a page switches it; your browser remembers the
choice, also for the [TIA dashboard](../../TiaAgentStatus/README.md) on this machine; a tab already open takes it when you come back to it.

## Example

A start page with one question open and one effort (the text of the page, made-up tickets):

```
DEVELOPMENT DASHBOARD                                     Live, updated 14:02:11

1 review and 1 ticket wait for you.

Reviews  ● 1  1 open
Parser   ● 2  6 open
No map        2 open

REVIEWS
● WAITING FOR YOUR ANSWERS (1)
  Parser audit                                                        2 questions

PARSER TICKETS
Files in the old format open without an error.
● WAITS FOR YOU (2)
  03  Audit the reader review page                              review page waits
  06  Version of the old header                                          question
▸ BEING WORKED ON (1)
  04  Read the old header
… WITH THE COORDINATOR (1)
  07  Error messages                                                    in-review
◇ YOURS TO START (1)
  08  Try it on a real file                                       ready-for-human
× BLOCKED (1)
  05  Write the old header                                           waits for 04
✓ CLOSED (2)

NO MAP
Folders with tickets and no map.md.
old-reader
○ READY FOR AN AGENT (2)
  ...
```

The list of topics starts with Reviews and has an entry per effort. Each entry jumps to its topic and shows how many of its tickets
wait for you and how many are open. On a wide screen it is a column on the left that stays in view; on a narrow one, a compact list
under the headline.

A fresh clone shows "Nothing waits for you." and says what to add.

## Start it

Once per clone, in the repo folder: `uv sync` ([uv](https://docs.astral.sh/uv/)). Then:

```
.venv\Scripts\pythonw.exe -X utf8 tools\dashboard\review_server.py
```

and open <http://127.0.0.1:8770/>. It runs with no console window, and the command returns at once. For a double-click, make a
shortcut with that line as its target, with full paths. `--port` picks another port, `--root` another `.scratch` folder. By default it
reads the `.scratch` of the main working tree, also when started from a worktree: worktrees share it. Building a review page starts the
server when it is not running, also with no console. After changing the server's Python, stop it and start it again.

While it runs it has an icon in the notification area of the taskbar, a dark D on mauve, in the colours of Catppuccin Mocha. Its tooltip
says **TIA-co-op: development dashboard** and its address. A left click on it opens the start page in your default Windows browser. A
right click opens a menu: **Open TIA-co-op: development dashboard** does the same, **Stop TIA-co-op: development dashboard** ends the
server. A review page built later starts it again. Windows 11 first puts a new icon behind
the ^ button; drag it onto the taskbar to keep it in view. The [TIA dashboard](../../TiaAgentStatus/README.md) has an icon of its own, a dark T on green.

Started a second time, it says in a box that the port is taken and ends; the first runs on with its one icon. To read what stops it
from starting, run the same line with `python.exe`: it then stays in that terminal, and Ctrl+C stops it.

## Tickets

Any folder under `.scratch\` with a `map.md` is an effort and a topic of its own. Its tickets are `issues\NN-<slug>.md` in the format of
the issue tracker, with `**Status:**` as `to-tickets` writes it or plain `Status:`.

A folder with tickets in `issues\` and no `map.md` shows under the one topic No map, by its folder name, those with something open
first. What waits there counts in the headline like any other ticket. An `issues\` folder with no tickets in it does not show.
Every `.md` file in `issues\` counts as a ticket, so a note kept there shows under Not readable, for having no `Status:`: nothing tells
it from a ticket that lost that line, and that one must not go silent. Keep notes in the effort's `research\` folder.

| In the ticket's head | What the page does with it |
|---|---|
| first `#` line | the title, which opens the ticket's file |
| `Status:` | the section: see below |
| `Blocked by:` | `none` or ticket numbers (`03, 07`, `other-effort/03`); Blocked while one is not closed. `None (can start immediately)`, as `to-tickets` writes it, reads as `none`; a ticket's title goes under Not readable, saying to write numbers |
| `Type:` | an open `grilling` or `prototype` waits for you once nothing blocks it |
| `Review page:` | the title of the review page about the ticket: while it waits for your answers, so does the ticket; while it is up, the ticket's row and page link to it |
| `Doc:` | a small link to a document under `docs\` or in the effort's folder (for a folder with no map, directly in it or in `issues\`) |

A ticket waits for you only when it is open, nothing blocks it and it asks you something: it has an open `## Question for the
maintainer` section, or its review page waits for your answers, or it is an open `grilling` or `prototype`. A question or a review
page holds whatever the open status; a closed ticket asks nothing, and a blocked one stays under Blocked until its blockers are
closed. Wayfinder's own `## Question`, which every wayfinder ticket has, asks you nothing. A ticket that waits only for its review
page counts once in the headline, as that review. A ticket that asks nothing goes by its status:

| Status | Section |
|---|---|
| any open status, nothing blocking, with a question or a review page waiting | Waits for you |
| `claimed` | Being worked on |
| `in-review`, `needs-info` | With the coordinator: an audit, acceptance or someone else's answer, nothing of yours |
| `ready-for-human` | Yours to start: work for a person, when you want; nothing asks |
| `ready-for-agent`, `open` | Ready for an agent |
| `needs-triage` | Needs triage |
| `done`, `resolved`, `wontfix` | Closed |
| anything else, a `Blocked by:` it cannot read, or a number an open ticket shares with another ticket | Not readable |

In `map.md`:

- `## Destination` is shown under the effort's heading.
- A line under `## Notes` that starts `This effort has been postponed` (or `Postponed`) folds the effort into one line and leaves
  it out of what waits for you: the list of topics and the headline count none of its tickets as waiting. It comes last on the page.
- `Sessions: <prefix>` is the name of the effort's agent sessions in herdr, when you use it: a ticket with a
  session `<prefix><number>` or `audit<prefix><number>` moves to Running now. Without the line the prefix is the folder name.
  Without herdr the section stays away. What needs a person stays where it is, and its row names the session: a ticket under Waits
  for you or Not readable, session or not. A ticket With the coordinator stays there while its session is only open, and moves while
  an agent works on it, an audit mostly.

## Answer a ticket

A ticket with a question opens on a page with the question at the top, an answer box and **Send answer**. Your answer goes into the
ticket as the newest comment, with your git `user.name`, date and time: `- <name>, 2026-11-05 14:30, answer on the dashboard: ...`.
The question's heading then says when it was answered, and the ticket leaves Waits for you. The coordinator's watch
(`tools\session\session.py watch`) reports the answer, for any ticket, with a session or not.

Only a ticket under Waits for you takes an answer: a blocked or closed ticket shows its question in its text, with no answer box.

If the ticket's question changed while the page was open, the answer is not sent: copy it, reload and answer the new question. A
ticket that changes while you type says so on the page instead of reloading.

A ticket whose review page waits says so at the top of its page, with a link: answer there, on the review page.

An open `grilling` or `prototype` under Waits for you has no answer box: you answer it in its session, with the agent that runs it.
Its page says so at the top, naming the session when herdr runs one.

## Review pages

An agent, or you, builds a page of things to look at and questions to answer:

```
.venv\Scripts\python.exe -X utf8 tools\dashboard\review_page.py --title "Parser audit" --ask "Keep the old name?" --note "Context" report.html::The report shot.png
```

Images are embedded, HTML files are shown in a frame. Building a page opens no browser: the start page lists it by itself, and its tab
title counts what waits. The command prints the page's address.

`--open "Parser audit"` opens the page in the default browser; to use another one for this option, set the environment variable `DASHBOARD_BROWSER`
to its path.

The page gets an answer box under each question. Answers land in `.scratch\reviews\answers\<title>.json`, where the agent reads them.
A page waits until its answers hold an answer to every question on it, so a page rebuilt with a new question waits again. A blank
box is no answer: the page names the blank questions and sends only when asked again, and then keeps waiting for those. With nothing
written at all it does not send. A page with no
questions is listed under To read and does not count as waiting; a comment sent on it moves it to Answered. A page or answer file that cannot be read is listed under Not readable.

A title used again shows its round on the start page and on the page ("round 2"), so that a new round does not look like the old
review coming back. A new round starts after `--done`, or when a page is built again after answers came in; a rebuild with none since
the last build stays in its round. Answers stay with a page built again, so a question asked in the same words stays answered: to ask it anew, take
the page down first.

Take a page down when its answers are acted on, or it stays on the start page:

```
.venv\Scripts\python.exe -X utf8 tools\dashboard\review_page.py --done "Parser audit"
```

The page, its files and its answers move to `.scratch\reviews\done\<title>\`. A tab still open on the page says it was taken down.
This is the only way to move answers: an answer file moved by hand while the page stays makes it wait again with its old questions.

## From another machine

The server only listens on 127.0.0.1. To reach it from your other machines, use [Tailscale](https://tailscale.com/kb/1247/funnel-serve-use-cases):

```
tailscale serve 8770
```

Open the `https://` address it prints; Ctrl+C ends it. With `--bg` it keeps running: `tailscale serve status` shows it,
`tailscale serve reset` removes every serve of this machine.

The server answers only requests whose `Host` names it, so that a web site in your browser cannot reach it: `127.0.0.1` or
`localhost` with its port, or an address ending in `.ts.net`, which is what `tailscale serve` hands on and needs no setting.
Any other proxy gets 403 unless it sends `Host: 127.0.0.1:<port>` to the server.

Everyone in your tailnet who can reach this machine can then send answers, and an answer goes straight to an agent. They can also
read more than the start page shows:

- every review page with its files and answers, also those taken down;
- the Markdown under `docs\`;
- the Markdown of each effort with a map, its whole folder at any depth, so keep what is private out of those;
- of a folder with tickets and no map, only `issues\` and the files directly in the folder, nothing deeper.

Other folders of `.scratch\` and the rest of the repo stay out. Do not use `tailscale funnel` for this: it opens the address to the internet. The dashboard has no login of its own.

## Requirements

- Python through `uv sync`; no other package.
- Chrome or Edge 123, Firefox 120, Safari 17.5 or later. An older browser shows the pages in its default colours.
- git, to find the main working tree. Without it, the `.scratch` beside the repo's `tools\` folder is read.
- Optional: herdr, Tailscale.

## Limitations

- Tested on Windows. The icon is Windows only.
- Not supported where nobody sees the screen: a session with no desktop, a hidden desktop, a service, or a scheduled task with no one logged on. On a hidden desktop it gets no icon and the server answers all the same; started with the line under [Start it](#start-it), what stops it, such as a taken port, shows there in a box that nobody closes, and the process keeps running. A service and a scheduled task with no one logged on are not measured, for the icon or for the box.
- The icon after a restart of Explorer is not measured.
- A server ended by Task Manager leaves its icon behind until the mouse passes over it.
- One server per port: a second one on the same port is refused. Two clones need two ports; pass `--port` to `review_page.py` too.
- A browser holds about six connections per site. The start page keeps one; other pages drop theirs while their tab is hidden.
- The fonts hold Latin letters; other characters come from a system font. A review page opened from disk uses system fonts only.
- A review page opened from disk or taken down has no icon to switch the mode: it follows the system setting.
- After one press there is no way back to following the system setting, short of clearing the `dashboard-theme` cookie; it lasts a year.
- The chosen mode is kept per address: `127.0.0.1`, `localhost` and a `tailscale serve` address each have their own. Where the browser blocks cookies the icon switches the page you are on until it next loads, and nothing is remembered.
