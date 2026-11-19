---
type: Guide
title: TiaBridge internals
description: How the MCP server is built, its files and tools, the rules it enforces (archive gate, save rules, guards), its error contract and the project repo it writes.
tags: [dev, tia-bridge, openness]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-19T10:40:00-05:00 }
---

# TiaBridge internals

The MCP server `tia`: an agent changes an offline TIA Portal V20 project through Openness and through files in a git repo. What it does for a user is in [its README](../../../TiaBridge/README.md), its settings in [Setup](../../user/setup.md), and how Openness behaves in [the Openness facts](../../agent/openness-v20.md).

## How it runs

```
Claude Code -- stdio JSON-RPC, UTF-8 --> powershell.exe -STA -File TiaBridge\TiaBridge.ps1
                                           stdout: MCP, one message per line
                                           stderr: diagnostics and progress lines
                                           state file for observers
```

Started `-STA`, as first setup registers it, `TiaBridge.ps1` runs itself again on an MTA thread of its own: Openness answers TIA's call-backs at once only for a client attached from an MTA thread, and TIA waits for each ([the Openness facts](../../agent/openness-v20.md)). The safety password window runs on an STA thread of its own (`Invoke-OnStaThread`).

It is one process per client, attached to one TIA at a time: a `connect` to a project in another TIA attaches there, and `background_open` to a TIA of its own. Windows PowerShell 5.1 with Pester 3.4 for tests: nothing to compile.

Tools return paths, counts, states and messages. Bulk content goes through files in the project repo, which the agent edits with its normal tools.

## Files

| File | What |
|---|---|
| `TiaBridge.ps1` | Entry point: loads the scripts, registers the tools, runs the loop |
| `Mcp.ps1` | The protocol loop and tool registry (`Register-McpTool`), `Write-BridgeLog`, `Write-BridgeProgress` |
| `Bridge.ps1` | Context, and the dispatch every call passes: which tools may run, the error contract, secrets, the log, the size of the response |
| `Tia.ps1` | Loads `PublicAPI\V20\Siemens.Engineering.dll`, attaches, finds objects, unwraps errors |
| `Repo.ps1` | Settings, the project repo, git, the check for Python |
| `Rules.ps1` | The session record: the archive gate and the save rules |
| `Guards.ps1` | Checks made before TIA is called |
| `Guides.ps1` | The MCP instructions, with guide paths from the bridge's own location |
| `State.ps1` | The state file ([its fields](tia-agent-status.md#the-state-file)) |
| `Tools\Session.ps1` | `tia_status`, `connect`, `project_open`, `project_close`, `archive`, `save` |
| `Tools\Objects.ps1`, `Plc.ps1`, `Hmi.ps1` | `list`, `export`, `import`, `delete`, `delete_folder`, `compile` and the kinds behind them |
| `Tools\Library.ps1` | Global libraries, library types, master copies |
| `Tools\LibraryChange.ps1` | The reviewed change |
| `Tools\Background.ps1` | `background_open`, `background_close` |
| `Tools\FullExport.ps1` | `full_export` |
| `Tools\ExportRecord.ps1` | What `full_export` skips: the record of the last export, and why it exports an object |
| `Times.ps1` | Where the time of a `full_export` goes: the steps of each part, and its slowest objects |
| `Tools\Safety.ps1`, `Probe.ps1`, `Report.ps1` | `safety_login`, `probe`, `change_report` |
| `Tests\` | [Testing](../testing.md) |

## Tools

The description in each tool's `Register-McpTool` call is the contract an agent reads, so it holds the details: what is refused and what a result names.

| Group | Tools |
|---|---|
| Session | `tia_status`, `connect`, `project_open`, `project_close`, `archive`, `save` |
| Objects | `list`, `export`, `import`, `delete`, `delete_folder`, `compile` |
| Whole project | `full_export` |
| Library types | `library_create_type`, `library_edit_type`, `library_discard_type`, `library_release_type`, `library_update_usages`, `library_review`, `library_approve`, `library_release_chain`, `library_left_behind` |
| Other library | `library_open`, `master_copy_to_project`, `master_copy_from_project` |
| Background | `background_open`, `background_close` |
| Other | `safety_login`, `probe`, `change_report` |

**Adding a tool.** Put its name in `$script:WriteTools` or `$script:ReadTools` in `Bridge.ps1`: `Tests\WriteGate.Tests.ps1` fails until it is in one. A background session for export refuses it unless it is also in `$script:BackgroundTools`; write mode takes every write tool.

## The rules

**Archive gate.** The first `connect` to a project in a session archives it. Until that archive exists, the write tools are refused before their handler runs. `archive(skip=true, reason)` skips it, on the person's word, and is recorded. A session belongs to a project's path, so a copy elsewhere has its own archive to make. The newest archives are kept (`archivesKept`).

### Save rules

`save` is refused while:

- the session record cannot be read, or lacks the result of a write (the bridge stopped during it);
- a write failed and was not redone. An import the bridge refused before TIA was asked holds nothing.

With an archive of this session, a save goes through over writes not compiled since and known compile errors. `savedWith` names them per device, and the agent quotes it to the person. What stays not consistent is read from TIA's blocks, PLC data types and technology objects. With the archive skipped, a save is also refused while, since the last save, a write was not followed by a compile of its scope on its device, that compile had errors, or what this session wrote or named is left not consistent.

The rules count per device. The record lives in `.tiabridge-session.json` in the project repo, so it survives a bridge restart. A `connect` to a project with no unsaved changes clears it. A background session keeps its record in memory.

**Guards.** Most are in `Guards.ps1`, some where they are needed (`Tools\Hmi.ps1`, `Tools\Objects.ps1`, `Repo.ps1`), and each tool's description names what it refuses. The ones that matter most:

- **An `.s7dcl` of an OB is refused** ([why](../decisions.md#the-bridge)).
- **A document under the wrong kind is refused,** as is one declaring a second object, or a keyword whose object cannot be read: every guard goes by the object a document declares.
- **An import runs in one transaction per call, so it is all or nothing.** Where TIA refuses a transaction, or `useTransactions` is off, the files before a failure stay imported, and the result says so. A name TIA answers differently than the document declares is not ok.
- **HMI screens, templates and pop-ups import only from `hmi\[<device>\]generated\<kind>`,** after `hmipreview validate --import`. Errors, open planned items and a newer TIA export refuse them. `override` passed as true lets a newer export be replaced; the screens' default does not. A validator that cannot run refuses the whole call.
- **Faceplate type versions a screen names must be in the project library,** as a mismatch has crashed TIA.
- **A screen whose number another screen of the device has is refused,** new or over another screen, naming that screen: it ended TIA. Openness gives a screen no number, so the precheck of `hmi_screen` exports each screen of the device once per call, without defaults (a missing number is 1). The call's documents then count in order, as TIA imports them: an override frees the number it had, and a document without a number takes the lowest free one. A screen that cannot be exported or read refuses the call, and so does a document whose number is no whole number.
- **A watch or force table TIA leaves not consistent fails its import,** and the call rolls back. TIA answers OK to a row naming a symbol the PLC does not have and written without `DisplayFormat`, and drops every row of a watch table; such a row of a force table with `DisplayFormat` makes TIA throw instead. Without a transaction the table stays as TIA left it, not consistent or partly imported, and either way the save is refused until it is imported good.
- **HMI cycles import only from `hmi\[<device>\]cycles`, their export, and only as a full export.** The validator's `cycle.not-full` refuses a document that is no full export or lacks `StartAtStartingPoint`, as TIA imports a minimal one with that false. The bridge exports cycles full whatever `options.full` says. An older repo holds minimal ones: its next export changes every cycle file, which the change report folds as export differences. `delete` refuses the kind (`noDelete`): a delete was not tried.
- **Slide-ins and the global screens import only from their export, `hmi\[<device>\]slideins` and `hmi\[<device>\]global`, over the device's own only.** The importGuard runs the validator as for cycles; its rules for these documents are `rules\slideinglobal.py` (`slidein.not-slidein`, `global.not-global`, `global.screen-item`: a screen item in the global elements, as a text field there ended TIA) and, for an import only, `rules\handbuilt.py` (`handbuilt.override`: one named in `handbuilt.json`, a slide-in by its edge). The screen rules do not read them. `whoseFile` names a slide-in by its `SlideinType` and the others by their object (`ScreenGlobalElements`, `ScreenOverview`); the precheck (`Test-HmiFixedScreen`) refuses one the device does not have, as a new one was not tried. The global ones go in through `HmiTarget.ImportScreenGlobalElements` and `ImportScreenOverview`. `afterImport` puts `overrideLoses` on the result: an Override drops what the export cannot carry. What TIA does with them: [Openness V20](../../agent/openness-v20.md), Slide-ins and global screens. `delete` refuses both (`noDelete`): a delete was not tried.
- **A force table imports over the PLC's own only.** TIA makes no other, so a file of another name is refused before TIA sees it, and `delete` refuses the table. The result's `online` says that nothing reaches the CPU, that no file sets a force mark, and that whether a mark set in TIA survives an import was not tried.
- **Technology objects import as SimaticML, and each item says whether its system library element and version were tried on a real TIA.** The precheck reads the document's `OfSystemLibElement` and `OfSystemLibVersion`; the result's `technology` names those tried and those not, which go in. An import over an object of another element or version is refused in the precheck: it was not tried. `next` names the compile of the PLC (the kind's `compileWhy`). A new object of a name a block or DB has is refused, and the other way round (`sharesNamesWith`). The kind's `systemKnowHow` leaves technology objects out of the know-how guard: TIA reports some of them as know-how protected although nobody protected them, and the guard would refuse every import over such an object. What TIA does with the kind: [Openness V20](../../agent/openness-v20.md), Technology objects. `delete` refuses the kind (`noDelete`): a delete was not tried.
- **A project graphic imports with its image folder, and a graphic list only with graphics the project has.** The precheck of `graphic` reads every image the document names (`external="path"`, relative to the `.xml`, `<name> files\` in an export) and refuses one that is not there, or a document naming none, which TIA would take as a graphic with no image. A graphic belongs to the project, not to a device: its kind's `usedBy` makes its import a write on every HMI device, so `next` names the compile of the HMI. The write is recorded as `graphic:<name>`, apart from a block, screen or pop-up of that name, whose record a failed new graphic therefore neither holds nor clears. The precheck of `hmi_graphiclist` reads the project's graphics once per call and refuses an entry whose `Picture` link names another, matched without case as TIA links it: TIA would take the entry, and the HMI compile then fails. The HMI validator reads a `PictureList` link (a graphic I/O field's graphic list) against the graphic list exports in `hmi\[<device>\]graphiclists\` (`hmipreview\links.py`), and the change report counts it as a use of the list. Both refuse a document of another class (`Read-HmiDocumentObject`), and `delete` refuses both (`noDelete`): a delete was not tried.
- **A VB script goes in with whatever code it holds.** `hmi_vbscript` imports from any path, a new script into the folder its path under `hmi\[<device>\]scripts\` mirrors, and refuses only a document of another class (`Read-HmiDocumentObject`). What TIA does with the kind, a syntax error included: [Openness V20](../../agent/openness-v20.md), VB scripts. `next` names the HMI compile, where an error in a script a screen calls shows. `delete` refuses it (`noDelete`): a delete was not tried.
- **F-blocks and F-compliant data types need `safety: true`.** Know-how protected blocks need `knowhow: true` to delete and cannot be imported over; technology objects can (above). An import over a `hmi_tag_table` is refused, as it has crashed TIA.
- **`export` refuses two objects whose names give one file,** and leaves the files there.
- **A repo records one `.ap20` path.** Another path is refused until the person says `moved` or names another `repo`.

## Background sessions

A TIA with no window that the bridge starts, only when the person asks. A project open in any TIA of this Windows session is refused before TIA starts.

| Mode | Opens | Allows |
|---|---|---|
| Export only | A copy of the `.ap20` or `.zap20` under `<projectsRoot>\_bridge\background\`, or `backgroundRoot`, older versions upgraded in the copy | `$script:BackgroundTools`: reading, `compile` of the copy, `safety_login`. The copy is never saved |
| `write: true` | The `.ap20` itself, or a `.zap20` retrieved once to `_bridge\retrieved\<name>` | The writes of a `connect` session, with the same archive gate and save rules. Not `connect` or a writable `library_open` |
| `plain: true` | As export only, into a plain folder with no git | For tools such as TIA Archive Compare. Only here may a caller pass a safety password or UMC login |

Nobody can see a message box of such a TIA, so a compiled C# guard answers each prompt with the first of Cancel, Abort, No, NoToAll or Ok, and the result lists it (`prompts`). `background_close` never saves. In write mode, with unsaved changes, it needs `discard: true`, and a bridge whose stdin closes discards by itself: nobody is left to save.

## Report runs

`TiaBridge.ps1 -ReportRun` is the bridge a report run of the TIA dashboard starts (`TiaAgentStatus\reportrun.py`, [ADR 0004](../../adr/0004-the-tia-dashboard-starts-a-report-run.md)). It allows `$script:ReportRunTools` only: `tia_status`, `connect`, `full_export`, `change_report`. Its `connect` makes no session archive, and refuses a TIA that lists another program attached to it (`AttachedSessions`, read with no attach). Its state file says `client: report-run`.

An agent's `connect` refuses a TIA or repo that a running report run names in `<projectsRoot>\_bridge\report-runs\<repo>.json`. It first writes the TIA it is about to attach to into its state file, and only then reads the records. The run does the same the other way round, so two that start at once both refuse.

## The error contract

Every tool, through `Invoke-BridgeTool`:

- The Siemens error comes unwrapped: .NET type, message, every detail text, the inner chain.
- Results that fail with no exception (compile, document import) come as a full message tree.
- A batch reports per item, so one bad file does not hide the others.
- `tiaEnded`: TIA ended its own process, as it does after a `NonRecoverableException`. The bridge detaches and refuses TIA calls until `connect`, or `background_close` and `background_open`.
- Whether TIA is alive (`Test-TiaAlive`: the project's name and TIA's process): `Get-TiaProject` asks once a call, at its first read of the project, and reconnects a window session there. A yes holds for the rest of the call, so the paths of an object do not ask again; a no is never kept. Code whose next step depends on the answer calls `Test-TiaAlive`, which asks each time. Two of those places took over from the ask each path made before: after an item failed (`Set-ItemError`), and after each part of `full_export`.
- Every result goes untruncated to `logs\<yyyyMMdd_HHmmss>_<tool>.json`. The response may be shortened (`maxResponseChars`) and then names the log.
- `password`, `umc_password` and `umc_user` are hidden in the result, the log and stderr.

```json
{ "ok": false, "project": "Plant", "repo": "C:\\Users\\me\\TIA-Projects\\Plant",
  "items": [ { "name": "Filler", "ok": false,
               "error": { "type": "Siemens.Engineering.EngineeringTargetInvocationException",
                          "message": "...", "details": ["..."], "inner": [ { "type": "...", "message": "..." } ] },
               "messages": [ { "path": "...", "state": "Error", "description": "..." } ] } ],
  "log": "logs\\20261004_101500_import.json" }
```

## Progress lines

For a client that shows a long call. Beside the human lines, stderr carries one line per event, ASCII only:

```
[tiabridge 14:02:11] progress {"event":"object","part":"blocks","kind":"block","n":25,"of":115,"name":"Filler","ok":true}
```

| `event` | Fields | When |
|---|---|---|
| `tia` | `pid` | The background TIA's process id, as soon as it starts |
| `step` | `step`, `state`, `ms`, `pid`, `upgrade` | Background session: around each long call, and after each tool call |
| `part` | `part`, `device`, `state`, `exported`, `count`, `failed`, `ms` | `full_export`, around each part and device |
| `object` | `part`, `device`, `kind`, `n`, `of`, `name`, `ok`, `skipped` | `export` and `full_export`, after each object; `skipped` when `full_export` left it |

A reader takes the JSON after `progress ` and ignores fields it does not know.

## The project repo

One per project, under `projectsRoot`, made by `connect`:

```
<project>\
  tiabridge.json         project path, PLC and HMI devices, last connect, hmiTypeIdentifier
  docs\                  OKF bundle; project.md holds the notes an agent reads first
  standards\             the person's own standards, copied from standardsTemplate on creation
  plc\                   blocks\, types\, tags\; from full_export also systemblocks\, technology\,
                         watchtables\, forcetables\, alarms\, supervisions\
  hmi\                   screens\, templates\, popups\, tags\, textlists\; from full_export also slideins\,
                         global\, graphiclists\, scripts\, cycles\, connections\
  hmi\generated\         generated documents, planned.json, generated.json
  hmi\panel.json         the declared panel; hmi\handbuilt.json the hand-built objects
  project\               from full_export: texts\, graphics\, alarmclasses\, supervision\, diagnostics\
  library\               types\, faceplates\, mastercopies\, global\<library>\; changes\ the reviewed changes
  gen\                   the project's own generators
  changes\reports\       change report pages (ignored by git)
  logs\                  one JSON per tool call (committed: they pair with the change)
  archives\              .zap20 files (ignored by git)
  .tiabridge-session.json   the session record (ignored by git)
  .tiabridge-export.json    the record of the last full_export (ignored by git)
```

- **Several devices.** With several PLC or HMI devices, each has its own `plc\<device>\` or `hmi\<device>\`, generated documents and panel included. One-device repos keep the layout above.
- **Folders mirror the TIA tree.**
- **`full_export` mirrors the project.** Committed files in a folder the export writes, which no part wrote this time, are removed and listed in `removed`, but only when every part writing that folder ran and listed its objects. Uncommitted files stay, and so does everything when git cannot tell. Never touched: `hmi\[<device>\]generated\`, `handbuilt.json`, `panel.json`, `gen\`, `standards\`, `library\changes\`, `changes\`, `logs\`, `archives\`, `docs\`, `tiabridge.json`.
- **A failed export leaves the old file.** An `export` call, and each kind part of `full_export`, exports its objects into one work folder beside the kind's folder, `<folder>.<8 hex>.partial`. The TIA folders are below it as in the repo (`Repo.ps1`, the work folder of an export). At its end, also when it stopped, the files of the objects that exported go in place together, and the work folder goes. An object whose file does not go in place fails and keeps its old files. A library type is exported into a folder of its own, which replaces the type's folder.
- **`full_export` skips what TIA has not changed** (`full: true` exports everything). Before any export it reads the dates and other values of every block, DB, data type and tag table of each PLC (`$script:ExportStateAttributes`), and compares them for unequal with `.tiabridge-export.json`, which holds them per object with the SHA-256 of each file its export left. The facts it rests on are the `[PROBE]` table under Dates in [the Openness facts](../../agent/openness-v20.md), with the lists after it: a text edited through the project texts, in either language, moves the object's `ModifiedDate`. A comment edited in TIA's editors and a move to another folder rest on the person's probe there. Block properties edited in TIA's dialogs were not tried; those Openness reads are compared as values (`$script:BlockHeaderAttributes`); the IEC check and ENO have no .NET property, only an attribute.
  - **An object's values are one call into TIA** (`Read-TiaAttributeValues`, `GetAttributes` of the names). TIA refuses the whole call when the object lacks one of them, as every DB and data type does: then `GetAttributeInfos` says which it offers and those are read in a second call. The next object of the kind starts with `GetAttributeInfos`, until one offers every name. Every name the call gives no value for is read on its own, as a .NET property or, where it has none, through `GetAttribute`: a name it did not answer (the object does not offer it, which then gives nothing), a name it answered null, and every name when the calls fail. So a value whose getter throws is named (`unread`) and the object exported, whether TIA refuses the call for it or answers null; which of the two TIA does is not probed. Facts: [the Openness facts](../../agent/openness-v20.md), `GetAttributes`.
  - **TIA's tree is listed once a call.** The parts of the four kinds take the plan's lists, for their objects and for the names that give one file (`Get-ExportCollisions`). That rests on nothing changing the project during the call. A background session holds it: no window, and only the bridge reaches that TIA, one tool call at a time. Under `connect` it does not hold, as `full_export` takes no `ExclusiveAccess`, so the user can edit in TIA during the call. A list kept from the plan then gives the following, read from the code and not tried; the next call puts each right, as it compares TIA with the record again.
    - An object deleted after the plan: its export fails, and its files stay.
    - An object added: it is not exported in this call. The next call sees it added and exports the PLC whole.
    - An object renamed: it is exported under its old file name. The next call exports the PLC whole and removes that file.
    - The plan's values of an object edited later are recorded, so the next call exports it.
  - **Everything is exported** when the record is missing or does not read, or its head differs: the project (in a background session the source it copied), TIA's version (`Siemens.Engineering.dll`), the project's languages, the PLC devices, or a hash of the bridge's own `*.ps1`. The result names the reason (`exportedAll`).
  - **Every object of a PLC** when an object of it was added, deleted or renamed, a data type changed, or a tag table exports differently: other blocks name them or hold a type's members, and a rename moves no date of a block naming it until the compile rewrites that block (`exportedAllOf`). A tag table's dates are not its signal: a tag renamed through Openness moved none, so the plan exports each table to a temporary file and compares it with its file in the repo (`Get-TagTableDifference`).
  - **One object** when a value differs, it moved to another folder, it is not consistent, its last export failed, it reads no date or a value that does not read, a file of it differs from the record or one of another format lies beside it, or it is an instance DB of an FB that is exported. `details` counts the reasons per part (`why`).
  - **A block or DB changed in TIA**, its interface too: the blocks that call or use it export by their own values, as TIA holds them not consistent until the compile, and the compile that rewrites them moves their dates. Every object last written as SimaticML exports with it (`Get-SimaticMlReason`): such a file holds the parameters and members of what it calls, and whether it follows them before its own compile was not tried.
  - A skipped object's files count as written, so the mirror removes what a full export removes. A PLC's entries are one snapshot: a run that listed all four kinds of it replaces them, any other leaves them, and a run that stopped writes nothing.
- **`full_export` says where its time goes,** in `times` of its log (`Times.ps1`); the answer has one line in its place (`Invoke-BridgeToolCall`). One stopwatch gives its ticks to one step at a time, and a step entered inside another takes its time from the outer one, so the steps of a part add up to the part's `ms`. The code enters a step through the class `TiaBridgeTimes`, compiled once at load (`[TiaBridgeTimes]::Enter('move')`, `::Exit` in a `finally`): a step costs about 2 µs and no call into TIA (`stepChanges` counts them).
  - `plan`: what TIA says of the objects before any part (`Get-ExportPlan`). `parts`: one entry per part and device, with `objects` (median, 90th percentile, slowest) and `slowest`, the ten objects that took longest, with their time in Openness and the size of their files. `once`: the rest, the session, the mirror, git, the count of unchanged files, the record and the result. `logMs`: the making of the log's text, written in by `Write-ToolLog`.
  - Steps named `tia_*` are calls into Openness: `tia_list` (the walk of TIA's tree), `tia_properties` (an object's class and know-how protection; a library type's formats and versions), `tia_state` (the values the plan compares) and `tia_attribute` (inside it: `GetAttributeInfos` after a refused call, or a name read on its own), `tia_export_s7dcl`, `tia_export_xml`, `tia_export_retry` (the SimaticML export after a refused SD export), `tia_export_tag_table` (the plan's compare), `tia_export_file` (an export call of a file part), `tia_alive` (`Test-TiaAlive`'s read of the project's name; when it is asked: [the error contract](#the-error-contract)).
  - The bridge's own: `result` (TIA's result made into the bridge's), `collisions` (names that give one file), `paths` (an object's folder, `Get-KindDir`), `process_lookup` (`Test-TiaAlive`'s look for TIA's process), `work_folder`, `compare` (with the file in place), `move`, `remove` (old files no export wrote again), `file_part` (a file part's own export around its calls into TIA: a `.dat` unpacked, a list written), `record`, `record_read`, `record_compare`, `record_files`, `record_save`, `progress` (the progress lines), `mirror`, `git`, `unchanged_count`, `summary`, and `other`, what no step names.

## The reviewed change

A change to one library type reaches every type containing it. `library_edit_type` starts a change for a type with dependents and writes its report to `library\changes\` (`.json` and `.md`), a tree of dependents by level. `library_update_usages` also puts in work the library blocks TIA leaves out. `library_review` compares each type with its released version, into the verdicts `unchanged`, `reference-only`, `flagged` or `not-compared`. Approvals are the ticks in the report (`library_approve`, or by hand), and `library_release_chain` releases only what is approved and not waiting for a contained type. The steps an agent takes are in `.claude\skills\tia-change\library.md`.
