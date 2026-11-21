---
type: Guide
title: "SIMATIC SD guide: comments and titles in the .s7res"
description: "How TIA Portal V20 writes the comments and titles of a SIMATIC SD block in its .s7res, and the import failures a resource file gave."
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T17:14:22-05:00 }
sources:
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: comments and titles in the .s7res

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): the resource file items of 8.14b and of 8.14c, read for a comment or title new or changed. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

### 8.14b Shapes seen in exports `[EXPORT]`: resource files

Its other items: [LAD](s7dcl-lad.md), [blocks, interfaces and data](s7dcl-data.md).

- `.s7res`: YAML, `MultiLingualTexts:` list of `- id: MLC_xxx` / `    en-US: text`. A key of a language the project does not have fails the import (8.14c). Multi-line text uses `|-`. Values containing `:` are single-quoted: an unquoted `: ` in a text is not YAML, and the import fails with *"The resource file contains corrupted data or format might be invalid."* (project C `Main_Safety_X1`, 2026-10-22). Ids are free strings: hand-picked ids (`MLC_N001`) imported without complaint. `[EXPORT]` (import failure 2026-08-25, LAD FB): the importer enforces a STRICT 1:1 COUNT between MLC references in the `.s7dcl` and entries in the `.s7res` — "Import failed because the Mlc ids present in resource file ... does not match the count of Mlc ids present in source file". Consequences: every `S7_MLC`, `S7_NetworkTitle`, `S7_NetworkComment` and `S7_BlockTitle` reference needs its OWN entry; one id must NOT be shared by several members (eight members sharing one id = seven missing entries); unused entries are NOT harmless — they fail the count the other way. When generating, count `MLC_` occurrences in the `.s7dcl` and entries in the `.s7res` and require equality before handing the pair to TIA.
- Comment ids belong to the project `[EXPORT]` (projects B and C, 2026-10): every TIA export of a block repeats the `S7_MLC` id of each comment, also after its text changed (926 commented members over the repos' histories); an id written into an import is kept and exported again (an agent's `MLC_N001` comes back as `MLC_N001`). A member renamed in TIA's editor keeps its comment's id (a UDT of project E, 2026-10-31). Two copies of one project do not share them (project A's original and latest copies differ in 4248 of 4248 ids), and a SimaticML import gives every comment a new id (an FB of project E exported as SimaticML and imported back: 16 of 16 new, also of members not edited). So an id identifies a comment only within one copy and until such an import: no evidence that two exports' members are one (TiaChangeReports does not use them).
- `.s7res` normalization on export (2026-09-28): TIA drops the single quotes of a value that does not need them and adds them where it does, and writes a text that starts with a space as `|2-` block scalar. Semantically the same YAML; diff exports by parsed value, not by bytes, when checking a round trip.

### 8.14c Import failures from resource files and branch shapes `[EXPORT]`: resource files

Its other part: [branch shapes and LAD operands](s7dcl-lad.md).

Verified by four failed syncs and their fixes (project B, 2026-09-23, TIA Portal V20). Every defect of those four was in a file **written by TIA's own export** (possibly after the ID add-in had run), not by hand; a file that exported cleanly is not proof that it re-imports.

**Duplicate MLC ids.** Two entries with the same id in one `.s7res` (and the id referenced twice in the `.s7dcl`) fail the import with *"Error when calling method 'ImportFromDocuments' ... The resource file contains corrupted data or format might be invalid."* The count check of 8.14b passes, because references and entries are both one too many. Seen in `StationPassThrough10` (two empty separator networks sharing `MLC_54t`) and `CyclicInterrupt` (F10 and F11 CALL networks sharing `MLC_3mw` / `MLC_3uE`). Both came from copying a network in the TIA editor; the copy keeps the text ids of the original, and the export writes them out twice. Fix: give the copy a new id in both files. In the project, retyping the copied network's title and comment should make TIA assign new ids at the next export.

**Entries without text.** An entry that has only an id and no language key:

```yaml
  - id: MLC_002
```

fails the import with *"0 errors, 0 warnings : Import of block(s) failed. please check the s7dcl file"* and no other message. Seen in `G05Units` for six empty network comments (`MLC_002` … `MLC_012`; the sequential numbering suggests the ID add-in rather than the exporter, unconfirmed). Fix: delete the `S7_NetworkComment := "MLC_0xx"` line in the `.s7dcl` and the entry in the `.s7res`; a network without a comment needs no reference at all. The same file with every network title and comment removed imported, which is how this was isolated.

**A text in a language the project does not have** (a line added by hand, not an export; a test project with en-US only, TIA Portal V20 Update 7, 2026-11-04). One more key in an entry:

```yaml
  - id: MLC_C
    en-US: A comment
    de-DE: Ein Kommentar
```

fails the import with `Siemens.Engineering.EngineeringTargetInvocationException`: *"Error when calling method 'ImportFromDocuments' of type 'Siemens.Engineering.SW.Blocks.PlcBlockComposition'. ERROR: ResourceID 'MultiLingualTextWithInvalidDocumentOption' not found in resource of type Siemens.Simatic.Lang.Documents.DOL.FeedbackDocuments"*. The import is rolled back. The text speaks of a resource TIA itself is missing; it does not name the language, the entry or the file. Through SimaticML (`format: xml`), a de-DE text on a project with en-US only says what it is: *the specified culture does not exist within the current project* (2026-11-02). Fix: take the key out of the entry. The same document without that line imported, compiled and saved. On the first text, compare the language keys of every `.s7res` of the import with the project's languages: `probe("project", "LanguageSettings.ActiveLanguages")` lists them under `items` `[PROBE]`. On a copy of another project a de-DE text of one comment went in, and its report showed the state changed (2026-11-02). The record does not name the route, SD or SimaticML, and that repo no longer exists, so an SD import in a language the project has is not shown. That `ActiveLanguages` is the list TIA checks against is an assumption `[INFERRED]`.
