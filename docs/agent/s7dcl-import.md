---
type: Guide
title: "SIMATIC SD guide: import behavior and platform notes"
description: How TIA Portal V20 imports SIMATIC SD (.s7dcl) files, what its log messages mean and how to find a silent failure, and the platform notes of the Siemens readmes.
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T19:16:55-05:00 }
sources:
  - id: lad-doc
    resource: https://support.industry.siemens.com/cs/ww/en/view/109994073
    title: SIMATIC Source Documents - LADDER Format Description V1.0 (2025-09)
    author: team:siemens
  - id: readme
    resource: SIMATIC TIA Portal V20 Update 4 and 5 readmes (A5E54260417)
    title: TIA Portal V20 readmes
    author: team:siemens
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: import behavior and platform notes

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): sections 10, 11, read for an F-block, an OB, a library type's document, an import or SD export that fails, the first change after a TIA Portal update; a DB when its type is or holds a library type changed in this session. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

## 10. Import behavior and diagnostics `[LAD-DOC §5]`

When STEP 7 imports, each `identifier(` is resolved in this order: keywords → local variables → inherent instruction library → opened system and user libraries → user program (global namespace). Outcomes:

- Inherent instruction → contact/coil/box rendered normally.
- Local variable that is an FB/SFB instance → box with type name inside, instance on top.
- FC/SFC name → box with block name.
- FB/SFB name without instance → red box with three red question marks (missing instance).
- Anything else / unknown → red box with the identifier inside.
- Missing closing `)` → syntax error, **import aborts**.
- Parameter list does not match the resolved object → red box, import **continues**.

That is the behaviour of the LAD format description. Through the Version Control Interface sync it is stricter `[EXPORT]`: a bad resource file or an unresolvable reference fails the whole block, often with no detail in the log. Section 9 is the minimum bar before any import; compile-cleanliness is the real target.

**How the VCI sync imports** `[EXPORT]`:

- Each workspace folder imports as **one batch** to its matching project group. One bad file fails the folder, and the log names the folder (`"..._Customer" could not be imported to the target "_Customer"`) with the reason on a sub-line, sometimes naming the file, sometimes not.
- Folders import in their own order (G05 before the root folder was observed). A block in one folder that calls a changed FB in another fails on the first sync and imports on the second. Sync twice before investigating a dependent block.
- Only files that changed since the last sync are imported. A TIA-exported file with a latent defect (8.14c) sits harmlessly until someone edits it, then fails.
- TIA stops at the first error in a block; fixing one can reveal the next.
- **Line ends decide the indent of an SCL body** (test FCs, TIA Portal V20 Update 7, background session, 2026-11-02) `[EXPORT]`: an export writes every body line 8 spaces deeper than TIA holds it, and an import takes up to 8 off again, but only from a line that follows a CRLF. A line after a lone LF keeps them, so with LF the body goes 8 deeper on every round trip. Measured, one trip:

  | Line in the file, code or comment | File with CRLF | File with LF |
  |---|---|---|
  | First line of the body | 8 stays 8, 12 stays 12 | 8 stays 8 |
  | Any other line at 8 or deeper | stays (8, 12, 14), and a second trip gives the same body | 8 deeper (8 to 16, 12 to 20) |
  | Any other line below 8 | comes back at 8 (0, 2, 4 to 8), so relative indent below 8 is lost | 8 deeper (0 to 8, 4 to 12) |

  A file with both line ends behaves line by line: only the lines after a lone LF go deeper. Whether the body starts with a statement or a `REGION` makes no difference. A `(* ... *)` comment follows the same rule, so its continuation lines keep their relative indent from column 8 on.
  - The TiaBridge `import` (blocks, DBs, types, library types) rewrites a `.s7dcl` with a lone LF as CRLF in place before TIA reads it, changes no other byte, and says so in the item's `note`. Through the VCI sync, write CRLF yourself.
  - Keep your own indent at 8 or deeper. A body that has already gone deeper stays there (24 stays 24): take the surplus off by hand once, in the file, with the lines still at 8 or deeper.
  - SCL has no multi-line string: such a block imports and then fails to compile (*Invalid expression*).
  - Windowed TIA: imports stayed as above on project B (2026-10-06 to 2026-10-20, three FCs): two known to be CRLF (one written by a generator with CRLF, one an export re-imported), the third inferred from how it behaved, since git holds no line ends here (`core.autocrlf`). LF in a window was not measured `[unverified]`.
  - The documentation add-in renders a comment that came back at 8 correctly (checked on four generations, project B, 2026-09-28).
- **Block attributes set by an import** (project A, TiaBridge without user interface, 2026-10-29) `[EXPORT]`: the export of the SCL FC `CopyTrolleyDriveStatus` carried neither `S7_GenerateENOforSCL` nor `S7_IECCheck`: both are FALSE in TIA, and the export writes them only when TRUE. Importing that file with one comment line added set both to TRUE, and the re-export carried them as `"TRUE"`. Written as `"FALSE"`, they stay FALSE and the re-export leaves them out again. So this part of the exporter's normalization is not adopted: add the missing ones as FALSE before every import (section 9, item 18). Probably TIA applies the project's defaults for new blocks `[unverified]`; window mode not checked, same import call.
- **Locked files** (project B, 2026-09-26): while a block is open in the TIA editor, its `.s7dcl` in the workspace is locked (a write is refused as "open in another app"); the `.s7res` is not. Close the block, or hold both files of the pair until it is closed, so no pair is half written.
- **Library types after an export** (project B, 2026-09-28): `<type>.libinfo` shows `VersionNumber` and `InWork` / `IsDefault`; `<type>.libint` lists `DependsOn` with the versions of the contained types. Any change to a library type, a comment-only `.s7res` change included, leaves it "in work" until it is released in TIA; the containing types then need an update and a release (next item). Check both files after every export before calling a library change done.
- **Duplicate types with a `_1` suffix** (project B, 2026-09-28): the project held a second copy of several library types (`..._1`, an older version). The program and the documentation add-in used the old version (pages showed V0.0.3 with texts from before 2026-09-26). Remove the duplicates in TIA, update the project to the default versions, export again.
- **Changed library type used inside another library type** (project B, 2026-09-26): the changed type file (`typeDriveVerticalAxisConfig`, with `.libinfo` / `.libint` / `.liblink` next to it) imports, but the types that contain it keep pointing to the released version without the new members. A data block that sets start values for the new members then fails with *The member "..." is not present in the source block of IDB*. Fix in TIA: open the containing type (`typeHmiDriveVerticalAxis`), update it to the new version of the changed type, release, then sync again. Plan this step whenever a library-linked type gets new members.
- **A block that no longer exports while a copy of it does** (project B, 2026-09-25): cause unknown. The original block object was in a state TIA would not export, and a copy of it was not. Did not help: compile, rebuild all blocks, regenerating the text ids (SimaticSdEnabler), the VCI checkbox, disconnecting the block from the workspace, deleting its workspace files. What worked: copy the block, delete the original, rename the copy to the original name, export. Callers bind by name and pick up the copy, but their instance data is reinitialised on the next download (retained values included), so note the values first. Better, with TiaBridge (project B, 2026-10-08, 31 FG blocks refused with *SIMATIC SD export failed due to project modifications made with a TIA Portal version earlier than V20 Update 4*, also after SimaticSdEnabler): `export` the block as SimaticML (`format: xml`, still allowed), `import` that file over the block (override, no delete), `compile`. The XML export afterwards differed only in the export time, the instance DBs stayed consistent, and every block exported as `.s7dcl` again (that export deletes the `.xml` from the project repo). The import gives the block new internal text ids, which is most likely what the copy did too.

- **Main safety block after an import** (project B, TiaBridge, 2026-10-20 and 2026-10-22): importing the `.s7dcl` of the
  F-runtime group's main safety block (`Main_Safety_X1`) over itself succeeds, but the F-runtime group loses its main
  safety block, and the next compile fails with *The F-runtime group "F-runtime group 1" does not have a valid main
  safety block.* Openness through TiaBridge cannot set it: the user sets it again in TIA (Safety Administration, F-runtime
  group, main safety block), then compile and save. Plan this step for every import of a main safety block (`safety: true`, like every F-block; only when the user asked for the safety change). Importing
  a PLC tag table that holds F-I/O tags does not touch the safety program (export dates of the main safety block
  unchanged, 2026-10-22).

**Log message → cause** `[EXPORT]`:

| Log message | Cause | Section |
|---|---|---|
| *Mlc ids present in resource file ... does not match the count* | Reference and entry counts differ | 8.14b |
| *The resource file contains corrupted data or format might be invalid* (ImportFromDocuments) | Duplicate MLC id | 8.14c |
| *0 errors, 0 warnings : Import of block(s) failed. please check the s7dcl file* | Entry without text; or a referenced FB/UDT not yet in the project with the expected interface | 8.14c, 9.17 |
| *ResourceID 'MultiLingualTextWithInvalidDocumentOption' not found* (ImportFromDocuments) | An `.s7res` text in a language the project does not have (the one cause seen) | 8.14c, 9.15 |
| *the specified culture does not exist within the current project* (SimaticML) | A text in a language the project does not have | 8.14c |
| *Creation of OR gate failed with RUNG 'Wire#wX' and END_RUNG 'Wire#wY'* | Nested-OR branch shape | 8.14c |
| *Creation of OR gate failed with END_RUNG 'Wire#x'* | The rung feeding a box pin written before the box's rung | 8.13b |
| *Creation of OR gate failed with RUNG 'Wire#x'* | A box output on a wire (`=> wire#x`), other than the output on the rung: no form tried goes in; or a branch written before the rungs that hold its start and its end node | 8.4, 8.13b, 8.14c, 9.16a |
| *The import failed. The source file contains multiple object definitions.* | Two FCs in one document, the one case tried; an FB, a DB and a library type were not. Two data types in one `TYPE` get no such answer: the first is made, the second is gone | 9.20 |
| *The import failed. The instance name in the file is invalid.* (`CreateFromDocuments`) | The first keyword of a new library type's document in lower or mixed case | 2 |
| *Data type Bool is not permitted here.* (compile, or SimaticML import) | `Mux`, `Demux`, `Move` with the type Bool, on a CPU 1515F | 8.13b |
| *Only inputs and outputs of the data type bool are connectable.* (compile) | Logic on a pin of a generic type | 8.13b |
| *The power rail (UId=...) contains an invalid connection to (UId=...) at pin "..."* (SimaticML) | Logic on that pin; a box output on a coil that is not the rung's | 8.13b |
| *The network does not comply with the rules for LAD.* (compile) | A coil tapped inside an OR leg; a branch from mid-rung onto a box pin | 8.13b |
| *Value 'SCL' for attribute 'S7_PreferredLanguage' is invalid* | `S7_PreferredLanguage := "SCL"`; an SCL block has `S7_EditorMode := "SCL"` | 3, 9.19 |
| *ResourceID 'MulitpleSCLNetworksErrorMessage' not found* | Several networks in a block with `S7_EditorMode := "SCL"` | 6, 9.19 |
| *Syntax error ':=' expecting ;* (data block) | Initial value on a `DATA_BLOCK` declaration | 4, 9.19 |
| *Import failed because non optimized block contains both Retain and non Retain variables.* | Non-optimized DB whose `S7_StandardRetain` does not match its section (`VAR RETAIN` / `VAR`) | 8.14b, 9.19 |
| *The Openness import failed: The attribute 'Remanence' cannot be set.* (SimaticML, instance DB) | "Set in IDB" members with different Remanence; they are retained all or none | 8.14b |
| *Instruction 'PBox' : Pin 'in' connection is missing* | Edge box first on a wire-start rung | 8.14a |
| *Instruction 'Contact' : Pin 'in' connection is missing* | A rung written after a rung that starts at its end node (seen for a branch from the power rail); or a branch from a merge node ending inside a sibling branch from the same node | 8.4, 8.14c, 9.16, 9.16a |
| *The output pin connecting to the instruction 'Contact' is missing.* | A rung written after a rung that starts at its end node (seen for a branch from `wire#w1` to `wire#w2`) | 8.4, 8.14c, 9.16a |
| *Tag #x[#c].y not defined* after an import that succeeded (LAD) | Multi-dimensional index cut to its last index by the SD import | 8.14c |
| *Error when calling method 'CreateFromDocuments' of type 'Siemens.Engineering.Library.Types.LibraryTypeVersionComposition'. The creation of a new instance of the document has failed.* (library type, no detail) | Any import error in the document. Import the same text as a test project block (`zz...`) to get the real message, then bisect | 10 |
| *The member "x.y" is not present in the source block of IDB* (data block start value) | The member's type is library-linked and the containing library type still uses the old version | 10 |
| *The F-runtime group "..." does not have a valid main safety block* (compile after an import) | The main safety block was imported; set it again in the F-runtime group | 10 |

**Bisecting a silent failure.** When the log says only "0 errors ... failed", write the block's networks as separate test FBs (`<Block>Test1..n`) into the same workspace folder, each with the full `VAR` section and a slice of the networks, with network titles and comments stripped so no `.s7res` is needed. One sync reports each test separately. If every slice imports, the fault is in the `.s7res` or in the block's existing state in the project, not in the code. Delete the test blocks from the project and the workspace afterwards.

## 11. Platform notes verified from Siemens readmes `[README]`

- SIMATIC SD pair: `.s7dcl` + `.s7res`. Exchange both files together; the `.s7res` carries comments/titles/multilingual texts.
- SCL block export/import since TIA Portal V20 Update 4; blocks written in other languages can be converted to SCL SD via Openness/VCI; export does not require an error-free compile.
- LAD, UDT and DB documents (including F-DBs) export/import via the version control interface.
- **OBs are exported without type information**: any OB re-imported from SD becomes a "Program cycle OB" regardless of its original event class. For OB30-class cyclic interrupt blocks (project F architecture), the OB type must be fixed manually in TIA after import — plan block generation accordingly (keep OB bodies trivial, put logic in FBs). `[EXPORT]` Confirmed on V20 Update 7 (project B, 2026-09-25): an edited `CyclicInterrupt` (OB30) came back as a Program cycle OB with the number 124. TIA cannot change an OB's event class, so the OB had to be recreated. Do not edit or re-import OB files as `.s7dcl`. As SimaticML an OB keeps them: `ProgrammingError` (OB121) exported, imported unchanged and exported again kept number 121 and the event class `ProgrammingError`, only the export time differs (TiaBridge, project B 2026-10-06); TiaBridge exports OBs as SimaticML for this reason.
- Not exported: know-how-protected blocks, read-only blocks, PLC supervisions/alarms, SiVArc definitions.
- SIMATIC SD export can fail when multilingual comment (MLC) ids in the project are inconsistent. Fix: install and run the TIA Portal add-in **SimaticSdEnabler** before exporting. To avoid recurring inconsistencies, edit the project only with V20 Update 4 or later (V20 Upd4 readme). Update 5 contains no SIMATIC SD changes.
- V21 (2025-11) extends SIMATIC SD to FBD, SCL and mixed-language blocks and lists all block types, OBs included, as exportable. Migration from V20 is one way. Whether V21 keeps an OB's event class on import, or removes the need for the add-in, is unverified.
- After updating TIA Portal: update every installation that touches the project (including a VM that runs the workspace sync), run SimaticSdEnabler once, compile, do a full export, and check the whole workspace against section 9 items 13–16 before editing continues.
