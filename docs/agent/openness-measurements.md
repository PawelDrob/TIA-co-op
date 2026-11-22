---
type: Guide
title: "TIA Openness V20 facts: measurements, dates, software units and comparisons"
description: "TIA Portal Openness V20 probe measurements: export timing with a window, object dates and GetAttributes, software units and named value documents, and fingerprints and offline comparisons."
tags: [openness, tia-v20, measurements, agents]
generated: { by: antigravity/gemini-4-neon, at: 2026-11-21T20:18:00-05:00 }
---

# TIA Openness V20 facts: measurements, dates, software units and comparisons

Part of the [TIA Openness V20 facts for agents](openness-v20.md): export timing, dates and software units of section 1, and section 6 (fingerprints and offline comparisons). A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its Sources section holds the citations `[n]`.

## 1. PLC software: export timing, dates and software units

Its other items: [blocks, OBs, F-blocks and compile](openness-plc-blocks.md), [watch and force tables, technology objects and folders](openness-plc-objects.md), [project texts and settings](openness-settings.md).

| What | Behaviour | Source |
|---|---|---|
| Export time with a window | On one PC, in a TIA with its window, `ExportAsDocuments` of a small object cost about 150 ms more than in a TIA without one. On a project of 550 blocks and types upgraded from V18: a data type of 205 bytes 153 ms against 4, an FB of 1.4 KB 159 against 5, an instance DB 162 against 11. On one of 2098 blocks and types, all last changed in V20: a data type 151 against 3, an FB 173 against 17. Six objects a project; on a DB that takes 5.7 s the difference is lost in its spread. In one session on the upgraded project, TIA used 141 to 147 ms of CPU time per call of 153 to 162 ms, and with TIA's main window minimized the same small objects took 13 to 17 ms. SimaticML `Export` of the small objects costs the same with and without the window, 5 to 20 ms. No effect on it: `ExclusiveAccess` around the calls, a handler on `Confirmation` and `Notification`. What it costs on another PC is not known. V20 Update 7, TIA started by Openness, its window on a hidden desktop, no other TIA running when each run started `[PROBE]` (2026-11-18). Through TiaBridge on the same PC, `full_export` with `full: true`, no other TIA running when each run started. With a window: TIA started on its project file with its window maximized on a hidden desktop, two runs a case, none the first run of its TIA; the benchmark project (473 objects, 248 `.s7dcl` calls) took 56 to 57 s with the window showing, 165 to 169 ms a `.s7dcl` call, and 17 to 18 s with TIA's main window minimized (`ShowWindowAsync`), 23 ms a call; a smaller project (68 objects, 21 `.s7dcl` calls) 6.8 to 7.3 s, 165 to 167 ms, and 3.3 to 4.6 s, 14 to 17 ms. Without a window: a background session (`background_open`), the second run of its TIA (the first took 25.8 s and 10.6 s); the benchmark project 13 s, 20 ms a call; the smaller one 2.2 s, 14 ms. A window maximized or in its normal size came back so after `SW_RESTORE`; one brought up during the export made the calls after it cost what they cost with the window showing (DBs median 185 ms against 23). V20 Update 7 `[PROBE]` (2026-11-19). TiaBridge: an export of 20 or more `.s7dcl` documents in a session with a window minimizes TIA's main window and puts it back after, unless the user touched it (`TiaBridge\Window.ps1`) | `[PROBE]` |
| What one `.s7dcl` call grows with | Measured without a window, V20 Update 7 (2026-11-18): not with the project. A data type of 100 to 240 bytes without comments takes 2.4 to 5.3 ms with 1000 data types, 300 global DBs, 6000 tags, 10 active languages with comments in each, a compile, a type used by 300 others, or last changed in V18; one with 8 comments in 10 languages (5.8 KB) 5.7 ms. With the object: nesting (a type 50 levels deep, 18 ms), a block's comments (an FB of 2000 statics, each with a comment: 2.5 s, 196 ms without the comments; SimaticML 34 ms), and DBs of some data types: one of 151 bytes takes 5.7 s, SimaticML 0.4 s `[PROBE]`; its data type holds arrays sized by constants, which another data type does whose DB takes 11 ms, so what in it costs is not known. The first `.s7dcl` call of a session, a data type, took 261 to 333 ms, and the first call on a block later in it 447 to 484 ms `[PROBE]` | `[PROBE]` |

**Dates.** The agent's own import moves every date of the object (`CreationDate` included), and its compile moves
them again. A block changed by a person after the agent's last import and compile shows a newer `ModifiedDate`
`[PROBE]`. `full_export` skips a block, DB or data type whose values below read as at the last export, and a tag table
whose export reads as its file ([TiaBridge's internals](../dev/tools/tia-bridge.md) say what else it checks); every
reason it skips rests on this table and the lists after it.

(The list **Texts edited through the project texts** is in [openness-settings.md](openness-settings.md), section 1.)

Probed on 2026-10-08 on a real project, V20 Update 7, with a person making the edits in TIA and a script reading the
values between the steps `[PROBE]`. The objects: an SCL FB, a LAD FB, a global DB, a data type, a PLC tag table, and an
FB made a project library type with its instance. Every date reads as a `DateTime` of `Kind` `Utc`; a read costs about
0.6 ms (one attribute of all 331 blocks of the project: 197 ms; the walk of the block tree: 1.1 s).

| Step | Dates that move | Also |
|---|---|---|
| `ExportAsDocuments` | none | |
| Compile with nothing changed | none, not even `CompileDate` | |
| A comment only (an interface member, a network title, a DB or data type member, a tag) | `ModifiedDate`; a tag table's `ModifiedTimeStamp` | a LAD network title makes the FB not consistent |
| Code: an SCL statement, a LAD contact, a DB start value | `ModifiedDate`, `CodeModifiedDate`; a tag table's `ModifiedTimeStamp` for a tag's address | not consistent |
| A data type member's default value | `ModifiedDate`, `InterfaceModifiedDate` | not consistent |
| An interface member added (FB, DB, data type), a tag added | `ModifiedDate`, `CodeModifiedDate`, `InterfaceModifiedDate`, `ParameterModified`, `StructureModified` | |
| Compile after a change | FB: `ModifiedDate`, `CodeModifiedDate`, `CompileDate` (code regenerated); DB: `CompileDate` only | consistent again |
| Rename | `ModifiedDate` | number and `CreationDate` kept; not consistent |
| Move to another group | none | not consistent |
| `ImportFromDocuments` with `Override`, of the unchanged export | every date, `CreationDate` too; `CompileDate` reads `0001-01-01` | the object made anew, number and group kept |
| Save, close and reopen | none: every date, `IsConsistent` and the library versions' `Guid`, `State` and `ModifiedDate` read the same to the millisecond | only `Project.LastModified` moves |

Library types: **Edit type** makes a new version, `InWork`, with its own `Guid` and `ModifiedDate` `0001-01-01`, and moves
the instance's `ModifiedDate`. **Release** gives the version a new `Guid`, sets its `ModifiedDate` to the release time,
compiles the instance and deletes the old version. Comfort HMI objects list only `Name` in `GetAttributeInfos` (an HMI tag
table also `IsSystemObject`): no signal short of an export. `PlcChecksumProvider.Software` is empty while any block is not
consistent and changes on every compile after a change: one value per PLC, which names no object `[PROBE]`.

A getter that throws reads `$null` in PowerShell, as an attribute the object does not have: TiaBridge reads these values
by reflection, so one TIA refuses counts as unread and its object is exported `[PROBE]` (2026-11-17, Windows PowerShell 5.1).

Probed again on 2026-11-17, V20 Update 7, on a copy of a test project without a window, through the calls an agent makes
and edits Openness makes in place; after each change the default `full_export` and `full: true` left the same files
`[PROBE]`:

- **Import, compile:** an `Override` import moves every date of the object, `InterfaceModifiedDate` too, also when only its
  code changed. The compile after an interface change rewrote both callers (each got the new input) and moved their
  `ModifiedDate`, `CodeModifiedDate` and `CompileDate`. Before it they read not consistent.
- **Data type:** a member added by import left every block and DB using it not consistent and changed only the type's file;
  the compile after it changed no other file. A member added to a global DB that 43 blocks use moved the dates of those the
  compile rewrote; a member renamed left the users it broke not consistent.
- **Rename in place** (`SetAttribute('Name')`): the block's key changes; no date of a caller moves and no caller's file
  changes until the compile, which rewrote both callers and moved their dates.
- **Number in place** (`AutoNumber` off, `Number`): `ModifiedDate` and `InterfaceModifiedDate` move, the callers turn not
  consistent, only the block's own file changes.
- **A tag renamed in place:** no date of its tag table moves, and the table's file changes. The block using the tag turns
  not consistent, its file stays, and the compile after it rewrote it and moved its dates. A tag's address or comment set
  in place moves the table's `ModifiedTimeStamp`.
- **Closed without saving** after an import and compile: the next session reads the dates from before the import.
- **Library type** edited and released: the version's `Guid`, `State` and `ModifiedDate` moved with its files.
- **Not settable through Openness** on an FB or FC: `HeaderAuthor`, `HeaderVersion`, `HeaderFamily`, `IsIECCheckEnabled`,
  `SetENOAutomatically` ("'set_HeaderVersion' is not supported by type 'Siemens.Engineering.SW.Blocks.FC'"); a block has no
  `Comment` attribute. Whether editing them in TIA's dialogs moves a date is not probed.
- **Read only through `GetAttribute`** `[PROBE]` (2026-11-18, V20 Update 7, a copy of another test project):
  `IsIECCheckEnabled` and `SetENOAutomatically` have no .NET property. `GetAttributeInfos` names both on an FB, an FC and
  an OB, only `IsIECCheckEnabled` on an F-FB, and neither on a global DB or a data type, where `GetAttribute` throws
  "... is not supported". For the five blocks written as `.s7dcl` (four FBs, an F-FB among them, and an FC) the values
  read match the file: `True` where it holds `S7_IECCheck` or `S7_GenerateENOforSCL` as `TRUE`, `False` where it leaves
  them out. The OB's SimaticML was not compared. The values TiaBridge reads for `full_export` hold both for an FB and an
  FC, only `IsIECCheckEnabled` for an F-FB, neither for a DB or a data type, and nothing unread.
- **`GetAttributes` of a list of names** `[PROBE]` (2026-11-19, V20 Update 7, copies of two test projects, 270 blocks, DBs,
  data types and tag tables): one call answers the list in its order. The text TiaBridge makes of each value is the same as
  from `GetAttribute` and the .NET properties for every object: the dates with their `Kind`, an enum as its name. The
  call throws `EngineeringNotSupportedException` ("'X' is not supported by type '...'") when the object lacks any one
  name, though the API documentation says it answers null for such a name. That happens on every global DB
  (`InstanceOfName`, `IsIECCheckEnabled`, `SetENOAutomatically`), instance DB (the last two), data type
  (`CodeModifiedDate` and nine more), F-block (`SetENOAutomatically`) and an STL FB (the last two). A name no object has
  is refused alone and among others. `GetAttributes(AttributeAccessOptions)` answers name and value pairs, but gives an
  enum as `Siemens.Engineering.Contract.EnumToClientRepresentation`. Not probed: what the call does for a name whose
  getter throws, as no object of the copies had one. On the copy of 246 blocks, DBs, data types and tag tables, in a
  session without a window, the values `full_export` compares took 1.6 s read in one call, after a refusal the names
  `GetAttributeInfos` lists in a second, against 3.6 s one by one. How TiaBridge reads them:
  [TiaBridge internals](../dev/tools/tia-bridge.md#the-project-repo).
- **Candidates for skipping:** system blocks have the dates of a block, but no step changed one; the force table has no date
  (`IsConsistent` only); no technology object or watch table was in the project. They are exported every time.

**Software units and named value documents** `[PROBE]` (V20 Update 7, 2026-11-20, on a copy of a test project with an
F-CPU, in a background session, not saved). TiaBridge reaches none of this: by their code `list`, `export` and
`full_export` walk the main program only (`TiaBridge\Tools\Plc.ps1`), and a `full_export` of a PLC with two units
exported nothing of them and named no unit.

- **Where they are:** `PlcSoftware.GetService<PlcUnitProvider>()`, then `UnitGroup.Units` and, apart, `UnitGroup.SafetyUnits`.
  A unit has its own `BlockGroup`, `TypeGroup`, `TagTableGroup`, `ExternalSourceGroup`, `PlcAlarmTextlistGroup` and
  `Relations`, and offers `ICompilable`, `PlcAlarmTextProvider`, `PlcAlarmTextListProvider` and `SupervisionProvider` of its own. Named value
  documents are in `TypeGroup.Documents` of a unit and of its type folders, apart from `Types`.
- **Making them:** `Units.Create(name)` makes a standard unit, with a tag table of its own whose number follows the
  PLC, as tag table names are unique there: the first unit got `Default tag table_1`, the second `Default tag table_2`.
  `GetCreationInfos` of `SafetyUnits` lists nothing. `Relations.Create(name, UnitRelationType.SoftwareUnit)` makes a
  relation. A block in a unit comes from a document (`ImportFromDocuments` of an `.s7dcl`), in nested folders too.
  `PlcBlockComposition.CreateFB` with SCL is refused: "The action "Create block" only supports the programming
  language 'ProDiag'.", in a unit and in the main program, although `GetCreationInfos` lists FB as creatable. Other
  languages were not tried.
- **Names:** a block, a PLC data type or a tag table of a name another unit's object holds is refused. The document of
  a block or a data type: "Import failed because an object with the name 'X' already exists in the plc."; so is a
  block of that name in the main program (a data type and a tag table there were not tried). A tag table:
  `Create` throws "An attempt was made to create an object that already exists." Setting the unit's `NamespacePreset`
  first changes none of the three. A document that wraps the block in `NAMESPACE <ns>` ...
  `END_NAMESPACE` goes in, and the export gives the same wrapping back: two blocks of one name in one PLC differ by their
  namespace (`Namespace` of the block). A data type and a tag table in a namespace were not tried. Named value documents
  are not held to this: two units hold documents of one name, no namespace (next item).
- **A named value document** goes in with `Documents.ImportFromDocuments(dir, name, options)`, `name` without `.nvt`
  (the parameter is `fileNameWithoutExtension`); with the extension TIA answers "The file '<name>.nvt' does not exist."
  Tried: `TYPE <name> : <base type> ( <NAME> := <value>, ... ) [:= <default>]; END_TYPE`, the syntax of the installed help,
  which also allows `NAMESPACE` and `{ PUBLISHED := 'TRUE' }` (both not tried). Two units may hold documents of one name. With two
  such documents each block of either unit compiled with two errors, "There is an ambiguous declarations in scope
  <name>", and read consistent afterwards. `PlcDocument.Name` carries the extension (`Colors.nvt`), so an export by
  `Name` writes `Colors.nvt.nvt`. Exported without it, a document is one `.nvt` file, the text as imported with a BOM
  added, and no `.s7res`.
- **Exports:** a unit's blocks and data types export with `ExportAsDocuments`, its tag tables with `Export`, as the main
  program's do. A unit block's document says `S7_UnitAccess := "Unpublished"` among its attributes.

## 6. Fingerprints and offline comparisons

Probed on 2026-11-20, V20 Update 7, without a window, on copies of a test project with one language (en-US) and a safety
program: changes of one object each (code, comments, interface, start values, block properties, a data type, a tag),
imported as `.s7dcl` or SimaticML. Fingerprints were read on the project before and after each change, `CompareTo`
compared the project after it with a retrieved archive of the state before `[PROBE]`. TiaBridge uses none of these calls.

**`FingerprintProvider.GetFingerprints()`** (service of a block or PLC data type) answers `Fingerprint` items, `Id` and
`Value`; every value read was 20 bytes in base64.

- **What moved:** `Code` and `ProgramCode` for a LAD, STL or SCL statement and an OB's LAD network; an FBD statement was
  not tried. `Code` only for an SCL comment: it did not move `Comments`. `Comments` for a block title, a block comment, an
  FBD network title, an FB interface member's and a data type member's comment. `Interface` for a member added, a start
  value of an FB member and of a global DB, and optimized access switched off (with `Properties`). `Properties` for the
  block version and author.
- **What did not move:** a second read, a compile by name, a `full_export`, a close and reopen. The same content imported
  again gave the same values, unlike the dates (section 1, Dates). A member added to a data type, its users compiled,
  left the fingerprints of the FB and the DBs using it as they were; an input added to an FB moved its instance DBs'
  `Interface`.
- **A setting none of them saw:** an instance DB's `S7_StandardRetain` set from FALSE to TRUE. The `.s7dcl` export writes
  it, and the export after the import read TRUE again. No fingerprint moved, nor `PlcSoftware.CompareTo`; of the
  attributes `GetAttributeInfos` lists on that DB only its dates moved.
- **Categories by kind:** `Interface` and `Properties` on every block, data type and system block. `Comments` on the
  blocks and data types, also on those whose `.s7dcl` export has no `.s7res`, but not on the F-OB, and on few system
  blocks. `Code` on code blocks, not on DBs, data types, system blocks or the F-OB; F-blocks have `Code` without
  `ProgramCode`. `Events` on OBs, `LibraryType` on instances of library types. A category an object lacks says nothing
  about a change.
- **Fails:** a block that is not consistent throws: *The block or PLC data type (UDT) '...' is inconsistent. Checksums can
  only be formed for consistent blocks.* A block left so by a change elsewhere loses its fingerprints with nothing of its
  own changed: a tag table imported in an older state left other blocks so. A tag table has no provider (`GetService`
  gives null). In a project opened as secondary every call throws: *The operation is not permitted in a read-only
  context.*
- **Cost:** milliseconds an object; seconds for every block, data type and system block of the test PLC, a few hundred objects.

**`PlcSoftware.CompareTo(ISoftwareCompareTarget)`**, tried with another PLC's software and with the project library. Two
offline PLCs: the second one opened as a secondary project in the same TIA, `Projects.Open(path, null,
ProjectOpenMode.Secondary)`, in under a second. An archive of the saved project (`Project.Archive`, its name given with
`.zap20`) retrieved as secondary, `Projects.Retrieve(..., null, ProjectOpenMode.Secondary)`, compared identical with the
state it was taken from every time.

- **Result:** a tree of `CompareResultElement`: the PLC, then Software units, Program blocks (System blocks too),
  Technology objects, PLC tags, PLC data types (System data types too); no watch or force tables. A changed object was one
  leaf `ObjectsDifferent` with *Objects are different.* and no elements below it: the call says which object differs, not
  what in it. In every compare of two PLCs, identical or not, the Program blocks folder's `DetailedInformation` held the
  collective F-signatures of the safety programs.
- **What it named:** the changed object of every change tried but the retain setting above, a tag's comment too (as the
  tag table). A member added to a data type, and a member comment, also marked the FB and the DBs using it; an input
  added to an FB also marked its instance DBs. That FB's caller, not consistent both in the archive and after the change,
  its own content unchanged, read identical.
- **Cost:** between two PLCs, tens of milliseconds the first call of a session and a few milliseconds each call after;
  seconds to read the whole tree of the test PLC. An archive of the test project took seconds, its retrieve under a
  second.
- **Against the project library** (`CompareTo(project.ProjectLibrary)`): instances of released type versions, and objects
  of the name of an object in a master copy, were compared with those: identical, or `ObjectsDifferent` where they
  differ. Released types without an instance read `LeftMissing`; plain objects and the instances of versions in work
  `RightMissing`. The Program blocks folder itself read `ObjectsDifferent`, with elements below it. A few milliseconds
  the call, seconds the tree.

**`LibraryTypeVersion.CompareTo(LibraryTypeVersion)`** of two versions in one project library answered seven properties:
`GUID of version object`, `Version Number`, `Is Default Version`, `Version author`, `Version comment`, `Modified Time`,
`Original Library` (`NotCompared`). Not the content: two versions differing by a member read different in GUID, number,
comment and time only. Milliseconds a pair. `LibraryType.CompareTo` and `LibraryTypeVersion.CompareTo` against a type in
a secondary project throw *The operation is not permitted in a read-only context.*

Not tried: a project with a second language (an OB's `Comments` with the project's languages changed), an OB's event,
GRAPH, alarms, supervisions, technology objects, software units, a library link or version changed on an instance (the
`LibraryType` category was never seen to move), another CPU, another TIA version or update, a global library or a master
copy as the target of `CompareTo`, and `CompareToOnline` and the station `FingerprintDataProvider`, which need a device.
