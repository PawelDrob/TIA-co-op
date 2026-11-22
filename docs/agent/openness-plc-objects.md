---
type: Guide
title: "TIA Openness V20 facts: watch and force tables, technology objects and folders"
description: "What TIA Portal Openness V20 does with PLC watch tables, force tables, technology objects and user folders."
tags: [openness, tia-v20, plc, agents]
generated: { by: antigravity/gemini-4-neon, at: 2026-11-21T19:58:00-05:00 }
---

# TIA Openness V20 facts: watch and force tables, technology objects and folders

Part of the [TIA Openness V20 facts for agents](openness-v20.md): section 1 (watch and force tables, technology objects and user folders). A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its Sources section holds the citations `[n]`.

## 1. PLC software: watch and force tables, technology objects and folders

Its other items: [blocks, OBs, F-blocks and compile](openness-plc-blocks.md), [project texts and settings](openness-settings.md), [export timing, dates and software units](openness-measurements.md) ("next paragraph" under User folders below refers to Software units and named value documents there).

| What | Behaviour | Source |
|---|---|---|
| Watch and force tables | SimaticML; an inconsistent table is refused: "The table is inconsistent and cannot be exported." `[PROBE]`. A watch table goes back through `PlcWatchTableComposition.Import` with `Override`: identical after the round trip, an edited row lands, a file of a new name makes a new table, and its full export (`WithReadOnly`) imports too; rows of a PLC tag, a DB member, an absolute address and a comment were tried. `ModifyIntention` in a file is refused as read-only. A row whose symbol the PLC does not have (`"Data".noSuchMember`, also a nested member written flat) makes the import answer OK and leaves the table not consistent with 0 rows, the good ones gone too, so its export is refused. In the same transaction `IsConsistent` of the returned table reads `False`, and a rollback brings the old table back with its rows; counting its `Entries` there ended TIA: *The following exception occurred while trying to enumerate the collection: "Unexpected exception - no exception message available."* TiaBridge reads `IsConsistent` only, and fails such an import, which rolls the call back `[PROBE]`. A force table goes back through `PlcForceTableComposition.Import` with `Override` over the PLC's one table only (`Force table`, in the system group `Watch and force tables`): identical after the round trip, added rows (`%Q0.0:P`, `%Q0.1:P`) and an edited one (`%Q0.1:P` to `%Q0.2:P`) land, and its empty export imported over rows empties it. A file of another name answers *'Create' is not supported by type 'Siemens.Engineering.SW.WatchAndForceTables.PlcForceTableComposition'.*, and the table has no `Delete()`. `ForceIntention` in a file is refused as read-only, so a file cannot arm a force: the import changes the offline table only. Whether a row marked for forcing in TIA keeps its mark through an import was not tried, as Openness cannot set the mark. A row whose symbol the PLC does not have (`"zz325NoSuchTag":P`, `"DEBUG".noSuchMember`) throws when it carries a `DisplayFormat`: *The attribute 'Siemens.Simatic.PlcLanguages.VatService.Openness.ForceTableEntry.DisplayFormat' cannot be set for 'Force table' because the assigned block is inconsistent.* Without one, the import answers OK and leaves the table not consistent, as a watch table. Either way a rollback brings the table back as it was. TiaBridge refuses another name before TIA sees it, and fails a table not consistent (2026-11-12) `[PROBE]` | [33] |
| Technology objects | By reflection `TechnologicalInstanceDB` derives from `InstanceDB`, yet none is among `BlockGroup.Blocks`: they live in `TechnologicalObjectGroup` only. TIA reports a `PID_Compact` 2.4 made with `Create` as know-how protected (`IsKnowHowProtected` true) although nobody protected it, and a `TO_ExternalEncoder` 6.0 as not protected `[PROBE]`. Why is not known; the protection of the system block behind the object is a guess `[INFERRED]`. On a CPU 1515-2 PN, firmware V2.9, `TechnologicalInstanceDBComposition.Create` makes `PID_Compact` 2.4, `PID_3Step` 2.3, `PID_Temp` 1.1, `TO_SpeedAxis`, `TO_PositioningAxis`, `TO_SynchronousAxis`, `TO_ExternalEncoder` 6.0, `High_Speed_Counter` (asked 5.0, reads 4.1) and `SSI_Absolute_Encoder` 3.0. Later motion versions, and `TO_MeasuringInput`, `TO_OutputCam`, `TO_CamTrack`, `TO_Cam`, `TO_Kinematics`, `TO_LeadingAxisProxy`, `TO_Interpreter` at any version, answer *The type or version of the library element "TO_SpeedAxis.9.0" does not exist or is not a valid technology object.* A new object reads not consistent, and its export is refused (*Inconsistent blocks and PLC data types (UDT) cannot be exported.*) until a compile of the PLC. An axis without a drive compiles once `VirtualAxis.Mode` is set to 1 through `Parameters`. The external encoder and the counter stay not consistent without hardware (*The input address of the encoder telegram is not set.*, *Please select the hardware*), and `SSI_Absolute_Encoder` does not export at all (*IMExport of this TO is not supported.*) `[PROBE]`. A compile of the PLC with such an encoder ends with 3 errors and the encoder not consistent; TiaBridge names it in `failed` and at the save, export only and in write mode (2026-11-12) `[PROBE]`. The import goes through `Import` with `Override`. Each of `PID_Compact` 2.4, `PID_3Step` 2.3, `PID_Temp` 1.1 and the three axes 6.0 (virtual) went in new from a file and round tripped identically, and the PLC compiled with 0 errors. The new object keeps the file's number. A number DB `DEBUG` had (3) went in too, and the compile gave the object a free one (9), DB 3 unchanged. An edited start value (`Config.InputUpperLimit` 99.5) lands. After any import, an override of the same file too, the object reads not consistent and refuses its export until the PLC is compiled. An FC reading it (`"PID".Output`) was seen not consistent after an import until the compile in an earlier probe; the probe of 2026-11-12 read that FC only after compiles, consistent. A document naming an element or version TIA does not have (`PID_Compact` 9.9, `PID_3Step` 2.4, `TO_SpeedAxis` 9.0) is refused: *Cannot create the 'SW.TechnologicalObjects.TechnologicalInstanceDB' object with Simatic ML ID '0' at line number 54 ...*, then the `Create` message above, and the transaction rolls back with TIA alive. One it has is taken as written, unchecked: a `PID_Compact` 2.4 export marked 2.3 went in, compiled and exported as 2.3 with the 2.4 interface. TiaBridge imports the kind, names each item's element and version and whether they were tried, imports over every technology object whether TIA reports it know-how protected or not, refuses an import over an object of another element or version (not tried), and refuses a new object of a name a block or DB has (2026-11-12) `[PROBE]` | [33] |

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
  `Documents`; PLC tag table folder `TagTables`, `Groups`; HMI folders their objects and `Folders`. A watch table folder
  (`PlcWatchAndForceTableUserGroup`, 2026-11-12) `ForceTables`, `Groups`, `WatchTables`, as the root
  `WatchAndForceTableGroup` does, and it has `Delete()`. `delete_folder` refused one holding a subfolder and one holding a
  watch table, and deleted both once empty.
- `Documents` is for named value data types. Into a folder of the PLC, `ImportFromDocuments` refuses: "The
  'ImportFromDocuments' method only supports the import of named value data types within software units." Into a folder of
  a software unit an earlier probe got "The file '...' does not exist" for every file name it tried; on
  2026-11-20 the name without its extension went in, the name with it gave that answer (next paragraph). An ordinary PLC data type goes
  to `Types`. The folders of a software unit are a tree of their own, which TiaBridge does not reach.
- No folder was found that looks empty and holds something: F-blocks are listed without the safety login, and
  `delete_folder` reads every collection the folder reports, not only those of its kind. Something Openness does not
  list at all cannot be ruled out this way.

("next paragraph" in the bullet on `Documents` above refers to **Software units and named value documents** in [openness-measurements.md](openness-measurements.md), section 1.)
