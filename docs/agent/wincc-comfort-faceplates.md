---
type: Guide
title: "WinCC Comfort: faceplates"
description: What TIA Portal V20 Openness can and cannot do with WinCC Comfort faceplate types, and how a faceplate is built from a generated staging screen.
tags: [tia-portal, hmi, wincc-comfort, openness, faceplates, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T16:19:37-05:00 }
sources:
  - id: probe
    resource: ../../TiaBridge/Tools/Probe.ps1
    title: Reflection on and calls to the installed V20 Openness API
  - id: user
    resource: observations in the TIA editor
    title: Observed by the user in the TIA editor
---

# WinCC Comfort: faceplates

Part of the [WinCC Comfort guide](wincc-comfort-openness.md): section 6, read for a faceplate. A section keeps its number in the file that holds it; the guide's section 0 holds the confidence tags.

## 6. Faceplates `[PROBE]` `[USER]`

- `FaceplateLibraryTypeVersion.Export(file, options)` writes only the version
  metadata (author, version number, comment), not the contents.
- `ExportAsDocuments(dir, name, format, options)`: format `''` -> "Cannot
  export a version without specifying an export format or with an invalid
  export format"; `SimaticML`, `Xml`, `Documents`, `s7dcl` -> "The type
  version could not be exported". `GetSupportedExportFormats()` returns an
  empty list.
- The type folder has `CreateFromDocuments(...)`; without an export there is
  nothing to feed it.
- Route used instead: generate a **staging screen** with the faceplate's
  objects at their final positions (styles, texts, formats, text lists,
  animations, events, groups), import it into `zzStaging`, select the objects, create the
  faceplate in TIA, then connect the tags to the interface. Creating the
  faceplate clears the tag connections `[USER]`, so the staging screens carry
  none.
- A faceplate's look only shows on an instance; check it on a screen.
- Faceplate instances on generated screens: copy the exported shape (4.2)
  with the type name and version of the released type.
- **Putting a faceplate type in work through Openness crashes TIA**:
  `FaceplateLibraryTypeVersion.Edit(LibraryTypeInstanceInfo)` (through an
  instance on a screen) ended TIA V20 Update 7 with
  `NonRecoverableException` "Unexpected exception - no exception message
  available" `[PROBE]` (project B 2026-10-06 16:04). TiaBridge refuses it; the user
  edits and updates faceplate types in TIA.
- A faceplate type that contains a PLC data type (its interface) keeps its
  version when that data type gets a new one, and is then **not using the
  default version** of it: `Dependencies` of the faceplate version names the
  version it was built with (`faceplateStation20Operate` 0.0.2 ->
  `typeHmiBench30` 0.0.1 while 0.0.2 is the default) `[PROBE]`
  (project B 2026-10-06). `library_update_usages` does not put the faceplate in
  work; TiaBridge reports it (`library_review`, `list`), and it needs a new
  version made in TIA.
