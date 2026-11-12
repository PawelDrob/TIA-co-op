---
type: Guide
title: TIA Openness V20 facts for agents
description: What TIA Portal Openness V20 can and cannot do for the PLC blocks, HMI objects and library types an agent changes through TiaBridge, and how its failures look, cited to the Siemens manual and to probes on V20 Update 7.
tags: [openness, tia-v20, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-12T14:54:56-05:00 }
---

# TIA Openness V20 facts for agents

What an agent needs to know about the Openness API behind TiaBridge's tools: what goes through it, what does not, and
how it fails. The file formats are in the [SIMATIC SD guide](s7dcl-format.md) and the
[WinCC Comfort guide](wincc-comfort-openness.md); the screen objects in [WinCC Comfort screen objects](wincc-screen-objects.md).

Target: TIA Portal V20 Update 7 (`PublicAPI\V20`, file version 2000.7.201.2). Citations `[n]` are the Siemens pages
and files at the end. Markers: `[PROBE]` found by calling or reflecting on the installed API, `[EXPORT]` / `[IMPORT]`
seen in an export / import, `[INFERRED]` follows from those, not verified by a round trip.

## 1. PLC software

| What | Behaviour | Source |
|---|---|---|
| Formats | SimaticML (every language, OBs, DBs, UDTs, tag tables, technology object DBs) and, new in V20, SIMATIC SD documents (`.s7dcl` + `.s7res`) for blocks, DBs and UDTs | [12][14][17] |
| OBs | The SD export loses the event class: the OB comes back as a program cycle OB. Exchange OBs as SimaticML | `[EXPORT]` |
| Export | Only consistent (compiled) blocks export; compile first [14]. An export refuses to overwrite a file: delete it first `[PROBE]`. References outside the exported objects are written as open references and relinked on import when an object of that name exists at the same place [12] | [12][14] |
| SimaticML import | Read-only and informative attributes are ignored; missing instance DBs are not created; a file without a number gets an automatic number; the result may not compile [15]. Instance-specific attributes such as start values can be lost (readme) [8] | [8][15] |
| SD import | `Override` replaces an existing object. Update 7 returns `State = Failure` with line-precise messages for a broken file (base V20 threw) `[PROBE]` | [18] |
| Know-how protected, system blocks | Export, do not import. An `Override` import replaces an existing know-how protected block **unprotected**, with no password and no message: an FC protected through `PlcBlockProtectionProvider.Protect`, by `.s7dcl` and by SimaticML, and an instance DB of a single-instance library box by `.s7dcl`, all read `IsKnowHowProtected` false afterwards, and the FC exported with the new interface `[PROBE]`. So TiaBridge refuses it. A PLC data type has no such provider: its protection cannot be set through Openness, so that case was not tried `[PROBE]`. `Protect` wants a password of at least 8 characters with a number, a special character, a lower-case and an upper-case letter `[PROBE]`. Their code does not export, so the repo cannot restore a deleted one: TiaBridge refuses `delete` and `master_copy_to_project` with Replace (of a same-named block or DB; of a folder when the PLC has any such block) without `knowhow: true`, set only when the user asked for that delete or replace | [12] |
| F-blocks | Export and import as F-blocks [16], import as `.s7dcl` (the row F-LAD); after the safety login TIA lets every later call change them like any block, so TiaBridge refuses `import` and `delete` of them without `safety: true`, set only when the user asked for that safety change. `import` also refuses the document of an F-compliant PLC data type (`S7_Safety := "True"` after `TYPE`; in SimaticML `IsFailsafeCompliant`, of which only `false` has been seen in an export); a data type is known by its document only, so `delete` of one and an import over one with the mark taken out are not refused. A `PlcStruct` has `IsFailsafeCompliant` in `GetAttributeInfos`, read-only, no .NET property, and it reads `False` on a plain type `[PROBE]`; that it reads `True` on an F-compliant one is not tried, and until it is, the guard cannot rest on it. Refused without the flag `[PROBE]`: the SimaticML of an F-FB, an F-DB and an F-instance DB, over the existing object and as a new one under another name, the mark being `F_LAD` or `F_DB`; and a document with no mark declaring the F-FB's name in lower case, by the object. `library_update_usages`, `library_release_chain` and `master_copy_to_project` (of blocks, DBs, PLC data types) cannot name the blocks they will change, so they need the same flag on a PLC whose `SafetyAdministration` shows TIA would let them through (logged on, or no password). F-system blocks (`F_TON`, `F_SystemInfo_DB`, ...) do not export: "The export of block '...' is not permitted." `[PROBE]`. The F-OB of an F-runtime group does not export either, also after the safety login: `ExportAsDocuments` answers "The block is know-how-protected and cannot be exported.", `Export` "The export of block '...' is not permitted." `[PROBE]` | [16] |
| Library instructions | PtP, USS, Modbus RTU, ET 200S, Technology and Optional packages boxes go in as `.s7dcl` calls and become calls of a block with a number; a SimaticML `<Part>` of them is refused or its templates can only be guessed. `GET`, `PUT` go in with all four areas wired, as a SimaticML `<Part>` and as TIA's own `.s7dcl` taken back, `#inst.GET(...)`; a `.s7dcl` with fewer areas is refused; a box TIA allows as a single instance only (`SSI_Absolute_Encoder`, `DQ4_CAM`) goes in with its DB. A pin of a technology object type wired to an in-out of the FB compiles without the object. A compile says nothing about hardware. The s7dcl guide, 8.13a `[EXPORT]` | `[EXPORT]` |
| Export after a batch | A block that compiled in a batch may still refuse its export: compile 0 errors, a second compile *No block was compiled. All blocks are up-to-date.*, export *Inconsistent blocks and PLC data types (UDT) cannot be exported.* Seen on eleven blocks of the test project, ten of them calling library instructions, on a copy of a project that did not hold them: after a compile by name `IsConsistent` stays false, 0 errors, and a save goes through. Not every block not consistent refuses: an FC just imported and not compiled, and one whose compile failed on its name, read not consistent and their `.s7dcl` exported with no message `[PROBE]`. Compiled by name again, twice, and imported and compiled by name again with the instructions then in the project: the same eleven. A compile of the PLC done before the import does not prevent it. A compile of the PLC as a whole with them in it clears them, in 4 s with no `safety_login` on the test project, and later imports and compiles by name of the same documents left none. Which step inside TIA does it is not known. A different case: `MB_RED_CLIENT`, `MB_RED_SERVER` compile with 0 errors and stay not consistent after a compile of the whole PLC too: their SimaticML export is refused. TiaBridge asks TIA after every compile of a PLC: `failed` names what is not consistent on the whole PLC, a save names it (`savedWith`), and without a session archive refuses over what the session wrote or named `[EXPORT]` | `[EXPORT]` |
| F-LAD | F-blocks go in as `.s7dcl`, also on a PC with no STEP 7 Safety license `[IMPORT]`; why that route does not ask is not known. Imported as SimaticML an F-block answers *No safety license available.* because the PC has no such license (the maintainer's word, 2026-11-03). On a PC with no license, seen; with one, not tried. Seen with three, `zzFSafety`, `zzFTimer` with boxes of the safety library and `zzFBitLogic` without, TIA's own exports taken back, one of them in a TIA with a window `[IMPORT]`. The export itself works. What a user with a license may see: the s7dcl guide, 8.13a. `SENDDP`, `RCVDP` do not go in on the PC with no license: single-instance DB only, and that DB needs the box's F-system block first. A `.s7dcl` export leaves out the type an F-box was imported with. The s7dcl guide, 8.13a `[EXPORT]` | `[EXPORT]` |
| SimaticML calls | Adding output pins to a call without wiring them fails the import: "The connection with the name '8' is not connected to the object with the UID '31'". Leave them out; the compile adds them `[PROBE]` | `[PROBE]` |
| Watch and force tables | SimaticML; an inconsistent table is refused: "The table is inconsistent and cannot be exported." `[PROBE]`. A watch table goes back through `PlcWatchTableComposition.Import` with `Override`: identical after the round trip, an edited row lands, a file of a new name makes a new table, and its full export (`WithReadOnly`) imports too; rows of a PLC tag, a DB member, an absolute address and a comment were tried. `ModifyIntention` in a file is refused as read-only. A row whose symbol the PLC does not have (`"Data".noSuchMember`, also a nested member written flat) makes the import answer OK and leaves the table not consistent with 0 rows, the good ones gone too, so its export is refused. In the same transaction `IsConsistent` of the returned table reads `False`, and a rollback brings the old table back with its rows; counting its `Entries` there ended TIA: *The following exception occurred while trying to enumerate the collection: "Unexpected exception - no exception message available."* TiaBridge reads `IsConsistent` only, and fails such an import, which rolls the call back `[PROBE]` | [33] |
| PLC alarm texts | `.xlsx` only. Without text lists the text list export throws `TextListNotFoundException`; without program alarms the alarm text export throws "There is no exportable alarm." `[PROBE]` | [33] |
| SimaticML version | An export carries the installed TIA version; the format is "internal and valid exclusively for the current version of TIA Portal Openness" [12]; from V19 an API imports SimaticML of the three previous versions [13] | [12][13] |

**Compile** (`ICompilable`): on a device, PLC software, a block, a type or a group. It is not allowed inside a
transaction [6]. A password-protected safety program needs the safety login first, or the compile fails at once:
"permission to modify the safety program is missing either on F-CPU or project level" `[PROBE]` [19]. The result is a
tree (`State`, `ErrorCount`, `WarningCount`, `Messages` with `Path` and `Description`) [19].

**Editing an OB's SimaticML.** An OB goes in as SimaticML only (the row OBs). Edit its export as text, or with an XML
library that writes the namespaces back as it read them. Two writes TIA V20 refused, and rolled back (2026-11-05)
`[IMPORT]`:

- An OB rewritten by Python's ElementTree, which writes every namespace with a prefix (`<ns0:Sections>`, `xmlns:ns0`
  declared on `Document`): "Cannot create the 'SW.Blocks.CompileUnit' object ... error in network ''", no inner exception.
- A tag table declaring `encoding="utf-8-sig"`, as Python names UTF-8 with a byte order mark: "System does not support
  'utf-8-sig' encoding. Line 1, position 31."

So keep the export's `<?xml version="1.0" encoding="utf-8"?>`, and each namespace as the default of the element that
holds it, `<Sections xmlns="...">`, `<FlgNet xmlns="...">`, with no prefix. ElementTree cannot write several default
namespaces. TiaBridge refuses both before TIA sees the file, naming the line: a declared encoding other than utf-8 in any
SimaticML, a namespace prefix in a block's. Whether TIA takes prefixes in other SimaticML was not tried.

**Dates.** The agent's own import moves every date of the object (`CreationDate` included), and its compile moves
them again. A block changed by a person after the agent's last import and compile shows a newer `ModifiedDate`
`[PROBE]`.

**User folders** `[PROBE]` (V20 Update 7, 2026-11-02, on a copy: block, PLC data type and PLC tag table folders of a PLC;
screen, template, pop-up and HMI tag folders of a Comfort panel):

- Only a user folder has `Delete()`; the root folders (`PlcBlockSystemGroup`, `ScreenSystemFolder`, ...) have none.
- `Delete()` of a folder takes everything in it, objects and subfolders, with no exception and no question. The one
  message seen was a notification, for a folder holding an F-OB: "The F-OB "..." is deleted. By deleting the block, its
  associated runtime group "..." becomes invalid." TiaBridge's `delete_folder` therefore reads the folder first and
  refuses unless it is empty.
- On an empty folder: no message, with or without a transaction. A rollback brings the folder back, and with it what it
  held, and the object from before still works. The undo in TIA's window was not tried (no window in a background session).
- No block or PLC data type changes `IsConsistent` by it, so `delete_folder` asks for no compile. HMI objects have no
  such flag; a compile of the panel afterwards reported only its missing start screen.
- `Groups.Find` and `Folders.Find` ignore case: `delete_folder` compares the names itself.
- What a folder holds, from `GetCompositionInfos`: block folder `Blocks`, `Groups`; PLC data type folder `Types`, `Groups`,
  `Documents`; PLC tag table folder `TagTables`, `Groups`; HMI folders their objects and `Folders`.
- `Documents` is for named value data types. Into a folder of the PLC, `ImportFromDocuments` refuses: "The
  'ImportFromDocuments' method only supports the import of named value data types within software units." Into a folder of
  a software unit it answered "The file '...' does not exist" for every file name tried, so a filled `Documents` was not
  seen. An ordinary PLC data type goes to `Types`. The folders of a software unit are a tree of their own, which TiaBridge does
  not reach.
- No folder was found that looks empty and holds something: F-blocks are listed without the safety login, and
  `delete_folder` reads every collection the folder reports, not only those of its kind. Something Openness does not
  list at all cannot be ruled out this way.

## 2. HMI (WinCC Comfort)

| What | Behaviour | Source |
|---|---|---|
| Objects | Screens, templates, global screen, pop-ups, slide-ins, tag tables, text and graphic lists, VB scripts, cycles, connections, as SimaticML | [12] |
| Not exportable | Among others: alarm view, alarm indicator, alarm window, trend views, table and value views, recipe view, system diagnostics view/window, screen window, HTML browser, media player, camera, PDF view, status/force, editable text field, list/combo box, check box, option buttons, scroll bar, connector, pipes. The export leaves them out without a message, so an `Override` import of that screen deletes them `[EXPORT]` `[INFERRED]` | [21] |
| Screen attributes | A screen offers only `Name` through the object model: number and template come from the export `[PROBE]` | [33] |
| Import order | With function keys: global screen, then templates, then screens (readme) | [8] |
| Faceplate instances | Import and export inside the screen; object name and type name are mandatory; an unknown type, event or interface attribute aborts the import [22]. A type version missing from the project library crashed TIA `[IMPORT]`; grouped instances are refused `[IMPORT]` | [22] |
| Faceplate types | Contents do not export or import: `Export` writes version metadata only, `ExportAsDocuments` refuses every format `[PROBE]`. Putting one in work with `Edit(LibraryTypeInstanceInfo)` ended TIA (`NonRecoverableException`) `[PROBE]`. A person builds the type in TIA | |
| SimaticML written by a script | TIA refused a tag table declaring `encoding="utf-8-sig"` `[IMPORT]`; TiaBridge refuses any declared encoding other than `utf-8`, in every SimaticML. Section 1, Editing an OB's SimaticML | |
| HMI tag tables | `Override` on an existing table deletes it first; it closed TIA once `[IMPORT]`, so TiaBridge refuses it. Broken tags block the export `[EXPORT]` | |
| Alarms, recipes, logs, user administration | No objects in the V20 API (enums only): nothing to create, export or import [33] | [33] |
| Styles | Objects with a style export the values stored before the style was switched on; toggle `UseDesignColorSchema` (off, export, on, export) to get the style values (readme) | [8] |

## 3. Libraries

| What | Behaviour | Source |
|---|---|---|
| Edit, release, discard, export and create from documents | New in V20; project library only, not in a global library [23][25][26]. A type of a global library exports its version metadata only: bring it into the project library to work on it `[PROBE]` | [23][25][26] |
| Put in work | `Edit(LibraryTypeInstanceInfo)` for a PLC type; it throws when a version is already in work or the library is write-protected [23]. `Edit()` without the instance fails on a PLC type without a message `[PROBE]`. Importing over the instance of a type in work opens a modal TIA message and blocks the call `[PROBE]` | [23] |
| Release | Does **not** check compile errors: compile before releasing `[PROBE]`. It gives the version a new `Guid`; in the probe it also deleted the previous version `[PROBE]` | [24] |
| In work before an update | After a `Release` and a compile by name, with no `UpdateProject` yet, a data type and a code block type containing the released type stood in work `[PROBE]`, 2026-11-04. Which of the two steps did it was not read. `library_release_type` and `compile` read what stands in work and name what is new (`alsoInWork`), and the record of an open change takes it | `[PROBE]` |
| Update usages | `UpdateProject` puts the containing data types in work, but not the code block types or faceplate types that contain the changed type `[PROBE]` | [33] |
| An update removes instances nothing uses | It is TIA's behaviour. Any `UpdateProject` takes out of the PLC every instance of a released type that nothing uses, and then what only those used: FB, FC, UDT, a test instance or one made by `CreateFrom`. One in work stays, and one a plain block calls; an update does not touch plain blocks, and the types and their versions stay in the library. The help, *Updating the project to the latest versions*: *"By default, when the project is updated to the latest type instances, unused type instances are deleted from the project."* and *"If a CPU does not include block instances that are called in the user program, the block instances are removed from the CPU. The types still exist in the library and can be used in the project again as needed."* TIA's own window did the same in a test with all nine types selected, in its log: *zzLibD [zzLibD V 0.0.3 default] is no longer referenced and has therefore been deleted.* Through Openness it also takes instances of types not selected; in the window that is not tried. `DeleteUnusedVersionsMode` and the dialog's *Delete unused type versions* are about versions in the library, not this: with `DoNotDelete` the instances go too. The help names a setting against it, General > Library settings, *Do not remove unused type version instances when updating the project from the library*; Openness's `SettingsFolders` does not show it, and whether it holds for Openness is not tried. An update also moves an instance by making a new object: *'x_1 [x V 0.0.2 default]' was instantiated.*, the old one deleted, *'x_1' has been renamed as 'x'.* TiaBridge lets TIA remove them and compares the blocks and PLC data types around the update (HMI objects are not compared): `instancesRemoved` names object, type, version, folder, number; the session archive is the way back. `[PROBE]` | `[PROBE]`, help |
| A type with no instance | `Edit` needs an instance, so a type TIA has cleared stays on the versions it was built with, `DefaultVersionInconsistent`, and no update moves it. Every result of `library_update_usages`, `library_release_chain`, `library_release_type` and `library_discard_type` in a change and `library_review` names it in `typesLeftBehind`, with what it still uses; a read that fails holds the change. A change that ends with such types is `left-behind`, not `done`, and the user answers through `library_left_behind` (next row). `library_edit_type` makes an instance from its default version and puts it in work, in one transaction; when an older version has an instance it refuses instead, as that would be a second one. That version was built on older versions of what it contains, so `CreateFrom` also brings those as copies, `x_1` on the old version, when the project holds newer ones, which gives `MultipleVersionsInstantiationInSameDevice`: `copiesMade`. After a compile, any update moves the type in work to the new versions and removes the copies, as nothing uses them then. Until that update an export of the type reads the copies, `temp : _.x_1;`, so export after it. An import into the type brings the copies back on the old versions, from any document, also one that reads `_.x`, and TIA says nothing; TiaBridge compares the blocks and PLC data types around it, `copiesBack`, and the next update removes them. Unit test only for that compare. `library_release_type` and `library_release_chain` refuse a version on old versions of what it contains, `onOldVersions`: a version in work lists no dependencies, so they look after the release and roll back. The chain's guard is by unit test only. Released, it stands `Consistent` on the new versions; if nothing uses it, the next update removes its instance again. Without `UpdatePathsMode.KeepExistingPathsInTarget`, an object in a folder other than its library folder answers with no message `[PROBE]` | `[PROBE]` |
| Create from documents | One supported file per name, plus the JSON meta file; `CreateOptions.Override` replaces the version in work [25]. Works on Update 7 for edited SD documents `[PROBE]` | [25] |
| Create a new type | `LibraryTypeComposition.CreateFromDocuments(dir, name, target, options)` on the `Types` of the library's type folder or of a user folder. The target is required in practice: the PLC's `TypeGroup` for a UDT, its `BlockGroup` for an FB or FC, or a user group of either, and the test instance lands there. No target, the `PlcSoftware` or the device answer *The import failed. The selected target is invalid.* A UDT document with the block group, or an FC with the type group, answers *Import failed. Block type UDT is not supported under ProgramBlocksFolder.* In a transaction, 50 ms to 3 s. TiaBridge: `library_create_type` `[PROBE]` | `[PROBE]` |
| Documents of a new type | `.s7dcl` with or without `.s7res`, or SimaticML. No meta file is needed: version 0.0.1. A `.libinfo` is read: its `VersionNumber` becomes the version and its type `Guid` the type's, so one copied from an existing type answers *Creating a type from a document failed. A type with the same GUID already exists.* Its `Author` is not taken, nor the version `Guid` of a `.libint`; a `.libint` with wrong hashes goes through. The name the document declares names the type, not the file name, also with a `:` (`Ns:Block` in `Ns_Block.s7dcl`). A type on a data type that does not exist yet is created with state `Warning` and *Interface: Data type x is unknown.*, and compiles once it exists `[PROBE]` | `[PROBE]` |
| State of a new type | The only version is `InWork`, `IsDefault` false, type `Status` `NonDefaultVersionInstantiation`; its test instance is in the PLC, not consistent until compiled. A compile by name makes it consistent. It has no released version, so a reviewed change starts after a first release. An F-FB is created, but its release failed three times: *The object 'x (FB232)' from which you want to create a type is inconsistent. The type cannot be released.*, with `IsConsistent` true after compiles by name and of the whole PLC, cause not known `[PROBE]` | `[PROBE]` |
| Dependencies | A version in work lists none, also after a compile: `Dependencies` and `Dependents` read empty, and fill at its release (`zzB 0.0.1` lists `zzA 0.0.1`, `zzA 0.0.1` lists `zzB 0.0.1` as dependent). So the levels of a chain of new types are known only as they are released. A new type may use a type in work or a plain UDT of the PLC; the release of a type on a plain UDT is not tried. Released with `AutomaticallyCreateOrReleaseDependenciesIfRequired`, a new type takes a contained type in work with it; with `DoNotAutomaticallyCreateOrReleaseDependencies` the same release answers *Error when calling method 'Release'* and nothing else, so `library_release_chain` uses the first mode for a type never released. The same bare answer comes for a type released on a contained type in work outside the release, which the chain then names, `heldBy`, by unit test. That mode takes a contained type along also when nobody listed it, and makes a library type of a plain block or data type the type uses, and says neither. TiaBridge compares the library around the release: a type made is refused in `library_release_chain` and `library_release_type`, rolled back, `wouldMakeTypes`, and the plain object stays plain; a type in work outside the list is refused in the chain, `wouldAlsoRelease`, and named by `library_release_type`, `alsoReleased` `[PROBE]` | `[PROBE]` |
| Several types with no instance | One temporary folder takes them all, in this order. Contained types first, each `CreateFrom` while none of them is in work, then `Edit` of each: three levels and a data type came up in one update and one chain, on the new versions, `Consistent`. The other orders do not: a type made before what it contains brings that along under its own name in its library folder, not the one asked for; a type made after what it contains is in work brings that as a copy, `x_1` on the old version. Copies of what the project holds on newer versions land in the library's folder path, which TIA makes in the PLC if it is missing; they leave the folder empty when the update removes them. A copy name that is taken gets the next number (`x_2`), and the object holding it stays as it was. A plain block with the type's name gets the instance `x_1`, and that name goes into the document of the next version (*FUNCTION "x_1"*), so `library_left_behind` refuses it. A type whose instance was made and whose `Edit` failed has an instance, so it leaves the list, and the update moves or removes it. A block named as the folder it goes into: *An instance with the same name already exists.* The instance needs no use until it is released: TIA removes it at the update after the release. `Edit` of a type that has a version in work ended TIA once: *Error when calling method 'Edit'*, `NonRecoverableException`, on a know-how protected FC; not tried on another `[PROBE]` | `[PROBE]` |
| The number of a new instance | `CreateFrom` keeps the number the type's block had, also when a plain block holds it, and the next compile settles that by moving one of them, the user's too, with new dates. On a new instance `Number` can be set, refused while `AutoNumber` is on: set it off, set the number, set it back, before the compile. `library_left_behind` and `library_edit_type` do so: 204 plain blocks kept number and dates through a whole yes. A know-how protected instance answers *'set_AutoNumber' is not supported*, so it cannot move; both refuse it as know-how protected, by unit test. With `AutoNumber` left off the document says `S7_BlockNumber` and a review flags it. The released version keeps the number its instance had, so the next `CreateFrom` starts from that one `[PROBE]` | `[PROBE]` |
| A released version that moves by itself | A type with no instance on one whose new version has the same interface: after the update its released version reads the new one in `Dependencies`, with no new version of its own, `Consistent` (`zzY` 0.0.1 on `zzX` 0.0.2). So it drops off `typesLeftBehind` by itself. With a change to the interface it stays on the old one `[PROBE]` | `[PROBE]` |
| Consistency around a release | A type's own instance reads not consistent right after its release, also a first one; the next compile by name clears it. Nothing else changes by it. After an import into a type in work, what contains it reads not consistent until the usages are updated and compiled. A chain of four levels, released from the bottom with a compile by name after each, ended with nothing not consistent `[PROBE]` | `[PROBE]` |
| Name taken | A type or an instance of that name, also a plain block or UDT of the PLC that is no type: *The import failed. An instance with the same name already exists.* The call fails, the object stays `[PROBE]` | `[PROBE]` |
| Instance of a version in work | `CreateFrom(version)` of `PlcTypeComposition` or `PlcBlockComposition` answers *Instantiation of an in-work/in-test version is not allowed.*, with or without the test instance. From a released version it works, for an FB, FC and UDT, in a transaction too; the instance reads not consistent until compiled. With no mode and the object in a folder other than its library folder it answers *Error when calling method 'CreateFrom'* and nothing else: `UpdatePathsMode.KeepExistingPathsInTarget` works. Its number comes from automatic numbering, and `Number` is refused while `AutoNumber` is on `[PROBE]` | `[PROBE]` |
| Failed update | What a call has committed is logged at once and stays in its result, whatever fails later (`instancesRemoved`, `released`). A refused commit keeps nothing: `library_update_usages` refuses, `library_release_chain` keeps what it released, answers not ok with `updateRefused`, and its change stays open until an update goes through `[PROBE]` | `[PROBE]` |
| Discard a version in work | `Discard()` of the only version removes the type and its test instance; with a released version the instance goes back to it, not consistent until compiled. It does not ask what uses the version: a type in work on it stays and stops compiling. A type that only joined a change leaves it and the change reads what is left, `status`, `stale`, `typesLeftBehind`, by unit test; a change of the discarded changed type ends as abandoned. `LibraryType.Delete()` answers *Failed to delete the type.: x cannot be deleted because the following versions are 'in test'/'in work': 0.0.1.*, `LibraryTypeVersion.Delete()` *Failed to delete library version.: x (0.0.1) cannot be deleted because it is currently being edited.* `Delete()` of the test instance fails and TIA sends a notification, *The test environment of the library cannot be deleted or replaced.* Seen in a background session only. TiaBridge: `library_discard_type` `[PROBE]` | `[PROBE]` |
| Name of the documents | The name given to `ExportAsDocuments` names the files; a name that does not fit a file name goes in file-safe form (`Ns_Block.s7dcl`, the document declares `Ns:Block`). A type's document can declare the name of its project instance instead of the type's: one imported on Update 7 and landed in the type (2026-10-24). TIA's export does write it: with the only instance named otherwise, by `SetAttribute('Name', ...)` on the released instance, the documents of `zzCol:Blk` declare `zzCol:Blk_1` and those of `zzPlain7` declare `zzPlain7_1`; they went back with no prompt, the edit landed in the version in work of the type, and no other type or block came `[PROBE]`. TiaBridge takes the type's name or an instance's and refuses any other. `CreateFromDocuments` with a `:` in the declared name works `[PROBE]`: a new type and instance `zzCol:Blk` from `zzCol_Blk.s7dcl`; then, on the version in work of that new type, on one put in work by `library_edit_type` after a release, and from SimaticML (its `Name` reads `zzCol:Blk`), the edit stands in the next export, and the library holds no `zzCol_Blk` | [25], `[PROBE]` |
| Case of a new type's document | `CreateFromDocuments` of a new FC or data type with its first keyword in lower case, `function` or `type`, answers *The import failed. The instance name in the file is invalid.* and makes nothing. The same document with that keyword in upper case and the others in lower case goes through (`void`, `var_input`, `network`, `end_function`; `struct`, `end_struct`, `end_type`). A new FB with `function_block` or `Function_Block`, and an FC with `Function`, answer the same. A data type in mixed case and an FB with the first keyword in upper case and the rest in lower case were not tried. An import of `function` into the version in work of an FC goes through, and `ImportFromDocuments` of a project block, DB or data type takes keywords in another case (the s7dcl guide, section 2) `[PROBE]` | `[PROBE]` |
| A version in work and `S7_Setpoint` | The export of a version just put in work writes no `S7_Setpoint`, as a released one writes none, also on a data type's member of a data type, where TIA ticks the box. Written into its document as `"False"`, it stands in the next export of that version. The release was not followed further `[PROBE]` | `[PROBE]` |
| Master copies | Single objects (blocks, types, tag tables, HMI screens, tag tables, ...) [28]; on a name conflict the one-argument call renames `[PROBE]`. A user folder: the PLC's block, data type and tag table folders and the HMI user folders are all sources of `MasterCopies.Create` (`IMasterCopySource`), and the root folders are not; `CreateFrom(MasterCopy)` to place one exists on the PLC's folder compositions, with a mode, and not on the HMI ones `[PROBE]`, by reflection on the types only. That a folder goes through and comes back is `[INFERRED]`, not tried on a project. So TiaBridge makes (`source_folder`) and places the PLC's, and refuses the HMI's | [28], `[PROBE]`, `[INFERRED]` |
| Global libraries | A user library opens read-only or read-write, not both; older versions open read-only [27]; open and close are not allowed inside a transaction [6]; the path is at most 143 characters `[PROBE]` | [6][27] |

## 4. Failures

- **Exceptions.** `EngineeringException` and its subtypes are recoverable (`EngineeringTargetInvocationException`,
  `EngineeringNotSupportedException`, `EngineeringSecurityException`, `EngineeringObjectDisposedException`, ...);
  the message and its detail texts say what TIA refused. `NonRecoverableException` means TIA is gone [7]. After a TIA
  crash or a closed project every object throws `EngineeringObjectDisposedException` [7]. Quote them as the bridge
  gives them.
- **Result objects** can fail without an exception: document imports, library exports and compiles report through
  `State` [18][26].
- **Transactions.** A write runs in one transaction: one undo entry in TIA, and after a failed import TIA refuses the
  commit, so a batch is all or nothing `[PROBE]` [6]. Compile, save and opening or closing a library are not allowed
  inside one [6]; the bridge archives outside it too.
- **Online.** With a device online TIA refuses the transaction: *The operation is not permitted in online mode* (seen
  2026-11-05). Without a transaction nothing rolls a failed batch back, so the bridge refuses the write: "TIA is
  online: go offline first", nothing written. It refuses too when the transaction fails in other words, or the
  settings turn transactions off, and a device reads online; save and compile run online. `connect` and `tia_status`
  give each device's `online`: the `OnlineProvider` state of the device item that holds its software, in lower case,
  or `unknown` where none can be read. Which device items have one, an HMI's among them, is not probed `[INFERRED]`.
- **Modal dialogs.** A failing call can wait on a TIA message box for many minutes: when a write takes more than a
  minute, someone has to look at TIA `[PROBE]`. A TIA without window has none; the bridge answers its prompts.
  `full_export` waited 590 s behind an "Export Completed (0032:000002)" box in a TIA with a window. Without window that
  box arrives as a `Notification` and the part stays under 60 s `[PROBE]`. So in a TIA with a window `full_export`
  acknowledges, for the length of the call, the notifications with the icon `Success` or `Information`; `Warning` and
  `Error` boxes and every question stay with the person at TIA. All notifications are listed with their icon
  (`prompts`). With a window not probed: whether handling closes the box, what icon it carries, and whether a box of the
  person's own work during the call reaches the guard (the event is the portal's, not the call's).
- **Another name.** An import can land under another name with no message: a tag table deleted and imported straight
  after came back as `<name>_1`, and a second delete and import gave the right name `[PROBE]`. That was an HMI tag table, each
  time on three tries. A PLC tag table, import, delete, import in one session, kept its name `[PROBE]`; the HMI one was not tried again. TiaBridge compares the
  names TIA returns with the name the document declares: the result is not ok, with `importedAs` and `namedOtherwise`.
- **What TIA takes in a name** `[PROBE]`: `ImportFromDocuments` made a block of each of these names, and gave the name back as
  written: a blank inside, `.`, `-`, `_`, `:`, `/`, `\`, `*`, `?`, `<`, `>`, `|`, `#`, `%`, `&`, `(`, `)`, `[`, `]`, `{`, `}`,
  `~`, `+`, `=`, `,`, `;`, `'`, `$"` together (each alone was not tried; `$` may be the escape of the `"`), a dot or a blank at the end, a blank
  in front, two dots at the end. So nothing stops two such names from giving one file. `CreateFromDocuments` took a library type with a blank,
  `.`, `-`, `/`, `*`, `$"` too, and a dot at the end; a blank at the end was dropped: `zzT ` became the type `zzT`, with no message. An FC named with a `:` compiles with 0 errors; compiling
  the others was not tried, nor a letter outside ASCII.
- **Device names, control characters, case in a name** `[PROBE]`, FCs by `ImportFromDocuments`. `NUL`, `CON`, `COM1`, `LPT1`: made, their documents read `NUL_.s7dcl` and so on,
  and `NUL_.s7dcl` goes back; `NUL`, `CON` compile with 0 errors. A tab and U+0001 in a name: made, exported as `zz_Tab.s7dcl`, and the compile answers
  *Name: The name may only contain the characters "A-z", "0-9" or the underscore. Starting with a digit or ending with an underscore is not permitted.*
  Names differing only in case: `zzCaseABC` with `zzCaseAbc` in the project leaves one block, spelled `zzCaseABC`, with no message. Other kinds were not tried.
- **A property of a dead object raises nothing** `[PROBE]`. After `Project.Close()`, in Windows PowerShell 5.1 under `$ErrorActionPreference = 'Stop'`, reading `Name` or `Path`
  of the project or `Name` of a block returns `$null`, and no `catch` fires. The method `GetAttribute('Name')` throws: *Access to a disposed object of type
  'Siemens.Engineering.SW.Blocks.FC' is not possible. The object is no longer available.* So reading a property does not show that an object is alive. A getter that throws for another reason was not tried.
- **Names and files.** TiaBridge makes a name file-safe: the nine characters Windows forbids and control characters
  become `_`, so does a dot or space at the end, and a Windows device name gets `_` behind it (`NUL` -> `NUL_`). Names
  that give one file (`Ns:Block` and `Ns_Block`, or `Abc` and `ABC`) are refused by `export` and `full_export`: neither
  is exported and the files there stay. Rename one in TIA. Devices or global libraries whose names give one folder each
  get a folder with a mark of the exact name (`PLC_1~1a2b3c4d`), and the result says so; the HMI tools take that folder
  as the device. A device holding two software items of one kind (each has the device's name) is refused by `export`
  and `full_export`: nothing of it is exported and its files stay. Whether TIA can produce that is not probed. TIA goes by the
  declared name: with `zzNs:Plain` in the project, a document declaring `zzNs_Plain` made a second block beside it and replaced
  nothing, whatever the file was called, and `export` and `full_export` then refused both `[PROBE]`. With `zzCh:Six` and `zzCh_Six` both in the project, `zzCh_Six.s7dcl` declaring
  `zzCh:Six` replaced `zzCh:Six` and left `zzCh_Six` as it was; with `zzCh:Six` alone, a SimaticML file of that name did the same and no `zzCh_Six` came `[PROBE]`. So a guard reading the
  declared name looks at the right block.
- **Archive** refuses a project with unsaved changes `[PROBE]`. TIA can mark a project modified on opening, with no
  write made (seen without user interface, 2026-11-01), so it may need a save before its first archive `[PROBE]`.
- **UMC.** Without user interface, opening a UMC-protected project without a login fails after about 20 s ("The
  project is protected. You are not authorized to open the project in write mode."), without a prompt `[PROBE]`.
- **Safety.** A wrong safety password fails with "Wrong Safety Administration Editor password was supplied."
  `[PROBE]`.

## 5. Starting TIA, opening and closing a project

On copies of a test project, 2026-11-04 `[PROBE]`; the bridge's tools are `project_open` and `project_close`.

- **A TIA with a window outlives what started it.** Started through Openness (`new TiaPortal(WithUserInterface)`), or as the
  program, it stays open with its project when the starter is killed, when it exits with no `Dispose`, and after `Dispose`,
  which does end a TIA without window. Each `Dispose` of an attach leaves TIA as it is.
- **The TIA program with a path:** `Siemens.Automation.Portal.exe "<path>"`. The process started shows the project in its title
  and holds it in `GetProcesses` at about 15 s. It then has a child process of the same name, with no window; that one is not
  in `GetProcesses`, and its command line names no project (`-Name=SearchReplaceBackgroundProcess ...`). Behind a box there is
  no child yet. The started process keeps the path on its command line, which is how `project_open` finds one waiting, also
  after a bridge restart (2026-11-05).
- **A box at opening** stands in front of a process started that way, with no time limit: *Log on* for a protected project;
  *Open reference project (0100:000295)* for a project open in another TIA; *Open project (0025:000012)*, "Project not found",
  for a file that does not exist. Until it is answered the process is not in `GetProcesses`, though it runs and responds, so
  only the title of the box tells them apart (UI Automation). After the login the process holds the project and an attach
  reads it as any other. *Log on* closed with no login: the process stays, unlisted, behind *Open project (4600:000103)*
  (2026-11-05).
- **One project per process.** `Projects.Open` in a TIA that holds one is refused at once: "Unable to open project '...'.
  Another project is already open.", with no box. The program with another path starts a second TIA process and leaves the
  first as it was.
- **`Project.Close()` through an attach** works: 1 s, and TIA stays open with its window and no project, still in `GetProcesses`
  with an empty path. `Projects.Open` through an attach then opens one in 2 s. It asks nothing: **with unsaved changes it
  closes in the same way and they are gone**, with no event. In PowerShell the old `Project` object answers afterwards: `Name`
  reads empty, with no exception.
- **A person's close with a script attached and idle** goes through, with no hang and no message. An older note has TIA unable
  to close a project with a bridge attached; neither a plain attach nor TiaBridge attached and idle shows that. A close
  through a second program does hang beside an idle STA client (next point); why a close in TIA's window does not is not known.
- **The access dialog** shows at the first attach of a program, until someone answers "Yes to all" for that program. An attach
  then takes about a second.
- **TIA waits on a client attached from an STA thread** `[PROBE]` (2026-11-12: stacks of TIA and the client at the hang, and
  `Siemens.Engineering.dll` read). When a list changes in TIA (a project closes, a block or a group is added), TIA calls back
  into every Openness session that has read that list (`PageEnumerator.EnumeratorInvalidated`), and its UI thread waits for the
  answer. A session attached from an STA thread keeps such call-backs in a queue that only its own next call empties, and
  nothing empties it on dispose; from an MTA thread a call-back runs at once. So beside an STA session that read the list, TIA
  waits for that session's next call, and for a disposed one until its process ends. Hangs on demand, each from STA and none
  from MTA: attach, read `Projects`, dispose, attach again, `Close()` (*Closing project...*); two live sessions, `Close()` through
  the second; block groups read in one session, a group created through the other. A session that reads nothing does not take
  part. A garbage collection does not release what a session read.
- **TiaBridge attaches from an MTA thread** of its own since then. The bridge of release 0.1.0 ran on the STA thread of `powershell.exe -STA`
  and hung TIA so, from 2026-10-19 on: after a switch to a project in a second TIA process and back (`connect` disposes the
  session it leaves), a `project_close` in *Closing project...* or an import with only the exclusive-access box; with the bridge
  idle; beside a second, stale bridge. Another program attached from an STA thread, a bridge of release 0.1.0 among them, still hangs
  TIA so. Stopping it frees TIA, mostly within seconds; once it did not within 30 s. `tia_status` names other bridges on the
  same TIA. From an MTA thread call-backs run while the bridge's own calls run, so TIA can change a list while the bridge
  reads it: the client's enumerator then throws `InvalidOperationException` "Collection was modified; enumeration operation
  may not execute." from `MoveNext`, a text of its own, not translated. Read again, at most three times in all: the objects
  of each kind, folder trees, the devices and their items, the projects and the global libraries. Not read again: other
  lists, such as the versions of a library type and their dependencies.
- **Not explained:** an import of OB `Main` (2026-11-08) that never returned, with one bridge attached once and no other program
  known; TIA ended when the bridge was stopped. No stack was taken.

## Sources

Siemens system manual V20, "TIA Portal Openness: API for automation of engineering workflows", 01/2025, at
`https://docs.tia.siemens.cloud/r/en-us/v20/` (`...` = `tia-portal-openness-api-for-automation-of-engineering-workflows`;
read 2026-10-08):

6. Transaction handling: `.../tia-portal-openness-api/general-functions/transaction-handling`
7. Handling exceptions: `.../tia-portal-openness-api/exceptions/handling-exceptions`
8. Readme TIA Portal Openness V20, notes on use: `readme-tia-portal-openness/readme`
12. Basic principles of importing/exporting: `.../export/import/overview/basic-principles-of-importing/exporting`
13. Version Specific Simatic ML Import: `.../export/import/overview/version-specific-simatic-ml-import`
14. Exporting blocks: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-blocks`
15. Importing block: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/importing-block`
16. Exporting failsafe blocks: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-failsafe-blocks`
17. Exporting program block as document: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/exporting-program-block-as-document`
18. Importing program block from document: `.../export/import/importing/exporting-data-of-a-plc-device/blocks/importing-program-block-from-document`
19. Compiling a project: `.../tia-portal-openness-api/functions-for-projects-and-project-data/compiling-a-project`
21. Overview of exportable screen objects: `.../export/import/importing/exporting-data-of-an-hmi-device/screens/overview-of-exportable-screen-objects`
22. Importing a screen with a faceplate instance: `.../export/import/importing/exporting-data-of-an-hmi-device/screens/importing-a-screen-with-a-faceplate-instance`
23. Editing library type version: `.../tia-portal-openness-api/functions-on-libraries/editing-library-type-version`
24. Releasing library type version: `.../tia-portal-openness-api/functions-on-libraries/releasing-library-type-version`
25. Updating type from document: `.../tia-portal-openness-api/functions-on-libraries/updating-type-from-document`
26. Exporting library type version as document: `.../tia-portal-openness-api/functions-on-libraries/exporting-library-type-version-as-document`
27. Accessing global libraries: `.../tia-portal-openness-api/functions-on-libraries/accessing-global-libraries`
28. Create an object from a master copy: `.../tia-portal-openness-api/functions-on-libraries/create-an-object-from-a-master-copy`

Installed with TIA Portal V20:

33. `PublicAPI\V20\Siemens.Engineering.xml`, the XML documentation of the V20 assembly (file version 2000.7.201.2).
