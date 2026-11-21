---
type: Guide
title: "TIA Openness V20 facts: project texts and settings"
description: "What TIA Portal Openness V20 does when importing project texts, alarm classes, system diagnostics settings and ProDiag supervisions."
tags: [openness, tia-v20, settings, agents]
generated: { by: antigravity/gemini, at: 2026-11-21T19:40:00-05:00 }
---

# TIA Openness V20 facts: project texts and settings

Part of the [TIA Openness V20 facts for agents](openness-v20.md): section 1 (texts edited through project texts and settings parts through import). A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its Sources section holds the citations `[n]`.

## 1. PLC software: project texts and settings

**Texts edited through the project texts** `[PROBE]` (2026-11-18, V20 Update 7, without a window, on a copy of a test
project given a second language: reference en-US, de-DE added). `Project.ImportProjectTexts(FileInfo path, bool
updateSourceLanguage)` took back the `.xlsx` that `ExportProjectTexts` wrote, with one cell changed; its result reads `State`
`Info` and names a log TIA writes under the project's `Logs`. Each edit moved the object's `ModifiedDate`:

- a translation added where there was none: an FB's title, an FB interface member's comment, a data type member's comment, a
  DB member's comment, an FB's network title;
- a translation changed: an OB's title;
- the reference language's text (`updateSourceLanguage` true): an FC's title.

A block's title and a network title also turned the block not consistent; the data type's and the DB's member comments
left them consistent (the FB's member comment was edited while the FB was not consistent already). The `.s7res` of the
FB, FC, DB and data type changed with each edit. The OB is written as SimaticML: after its edit that export failed, in both
runs alike, so no file of it changed; no compile was tried. After each edit, saved and read in a new session, the default
`full_export` left the same files as `full: true`.

**Settings parts through import** `[PROBE]` (2026-11-12 by script and 2026-11-19 through TiaBridge, V20 Update 7, without a
window, on copies of a test project with one language, en-US, and no PLC alarm texts). The files `full_export` writes go
back over the project's own:

| Part | Call | In a transaction | Tried |
|---|---|---|---|
| project texts (`.xlsx`) | `Project.ImportProjectTexts(FileInfo, true)`, result `State` `Info` | refused: *The operation is not permitted within a transaction.* | round trip identical; a block title edited in the sheet landed; the earlier export imported again put that title back |
| alarm classes (`.dat`) | `AlarmClassDataProvider.Import(FileInfo)`, `Success` | refused, the same | round trip identical but `CreationDate`; the earlier export imported again undid an edit that had added a second `DisplayName` without `Culture`. See the list below for an `.xml` packed into a `.dat` and the display name |
| system diagnostics settings (`.dat`) | `SystemdiagnosticsSettingsDataProvider.Import(FileInfo)`, `Success` | allowed | round trip identical but `CreationDate`; a category's `Activation` edited in its XML landed |
| ProDiag supervisions (`.xlsx`) | `SupervisionProvider.ImportSupervisionsFromXlsx(FileInfo, ImportOptions.Override)`, `Success` | allowed | round trip identical, of a sheet with headers only; no edit tried |

- **A `.dat` is a zip of one XML file** whose entry has the `.dat`'s own name, written in UTF-8 with a byte order mark. An
  edited XML packed the same way imported (2026-11-19).
- **An alarm class's display name is a project text.** A `DisplayName` edited with `Culture="en-US"` landed as that text,
  and the export then wrote an empty `<DisplayName />` beside it, which round trips. Edited without `Culture`, as the
  export writes it, it went in as a second `DisplayName`, and the text stayed.
- **The first supervisions import set up ProDiag.** On the project without ProDiag settings, importing its headers-only
  sheet initialised them: their export, refused before, then worked, and the project texts gained 230 rows of ProDiag
  categories (both dates). The same import rolled back in its transaction took both back: the settings' export still
  answered that they are not initialized, and the project texts kept the 215 rows they had, with none of the 230 added (2026-11-19).
- **After these imports** a compile of the PLC and of the HMI had 0 errors (2026-11-19). Whether a part needs a compile
  was not tried; a block title edited through the project texts turned the block not consistent in the paragraph above
  (2026-11-18).
- **Not tried:** an import of supervision settings and of PLC alarm text lists and texts; a new alarm class; project texts
  of a second language through TiaBridge (the paragraph above tried them by script).

How TiaBridge imports them: [TiaBridge internals](../dev/tools/tia-bridge.md#the-rules).
