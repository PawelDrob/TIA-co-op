# TIA Portal with agents

This glossary fixes the words for working on TIA projects with these tools and for how this repo is changed.

## Working on a TIA project

**Bridge**:
The MCP server through which an agent reads and changes a TIA project.
_Avoid_: plugin, connector

**Project repo**:
The git repo that holds the files of one TIA project, apart from this repo.
_Avoid_: export folder, project folder

**Change report**:
One page of what changed between two exports of a project, drawn as TIA shows it. Not the library change report.
_Avoid_: diff page, comparison

**Session archive**:
The project archive made before a session writes, the way back from what that session saves.
_Avoid_: backup, snapshot

**Session record**:
The file in the project repo that holds what a window session wrote and what the save rules still hold against it, read back when a new bridge process binds to the project.
_Avoid_: session file, state file

**Window session**:
Work in a TIA that a person has open, through the bridge attached to it.
_Avoid_: live session, online session

**Background session**:
Work in a TIA without user interface that the bridge starts, on a copy or on a project file closed in TIA.
_Avoid_: headless mode, offline session

**TIA dashboard**:
The local page of what agents do to a person's TIA projects.
_Avoid_: status page, "the dashboard" alone (there are two)

## Library types

**Reviewed change**:
A change to a library type together with every type that contains it, approved type by type by a person and open until nothing of it is in work unreleased.
_Avoid_: update, transaction

**Library change report**:
The file `library\changes\<id>.md` in the project repo that the bridge writes for one reviewed change: its types, the review's verdicts and a box per type to approve.
_Avoid_: "change report" alone, change record

**Type left behind**:
A library type with no instance in the project, which stays on old versions of what it contains because no update moves it.
_Avoid_: orphan, stale type

## HMI screens

**Reference export**:
A screen, template or pop-up built in TIA and exported in full, the only source of element shapes.
_Avoid_: sample, example screen

**Generated screen**:
A screen, template or pop-up written by a project's generator, kept apart from the TIA exports until it is imported.
_Avoid_: mockup

**Staging screen**:
A generated screen after its import into the `zzStaging` folder of the TIA project.
_Avoid_: test screen

**Hand-built object**:
A screen object that exists only in TIA because Openness does not carry it, such as an alarm view.
_Avoid_: control, missing object

**HMI preview**:
The browser view of a project's generated screens, clicked through before import.
_Avoid_: prototype, simulator

## Changing this repo

**Effort**:
A body of work too big for one session, with its own folder of a map and tickets.
_Avoid_: project, epic

**Decision ticket**:
A ticket whose resolution is a decision: research, prototype or grilling.
_Avoid_: question, spike

**Execution ticket**:
A ticket whose resolution is delivered work, accepted by audit.
_Avoid_: implementation issue, job

**Coordinator**:
The session or person that runs ticket and audit sessions over a map and relays between them and the maintainer.
_Avoid_: lead, orchestrator

**Ticket session**:
One session working one execution ticket in its own worktree, up to the audit.
_Avoid_: implementer tab, worker

**Audit session**:
A session that wrote nothing of a finished ticket branch and judges it; its pass lets the branch enter `main`.
_Avoid_: reviewer, QA pass

**Development dashboard**:
The local page of the tickets and review pages of work on this repo.
_Avoid_: board, "the dashboard" alone (there are two)

**Review page**:
A page on the development dashboard where a person looks at what an agent shows and answers its questions.
_Avoid_: report, preview

**Agent guide**:
A document an agent reads while working on a TIA project, in `docs/agent/`.
_Avoid_: agent doc, manual

**Skills config**:
What tells the engineering skills how this repo works, in `docs/agents/`.
_Avoid_: agent doc, agent settings
