---
type: Rationale
title: "WinCC Comfort: history of the first runs"
description: The first WinCC Comfort generation and import runs on project B, 2026-10-01 to 2026-10-06, in order, with what each changed.
tags: [tia-portal, hmi, wincc-comfort, history, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T16:34:52-05:00 }
---

# WinCC Comfort: history of the first runs

Part of the [WinCC Comfort guide](wincc-comfort-openness.md): section 9, the history of the first runs; the rules they found are in the guide. A section keeps its number in the file that holds it; the guide's section 0 holds the confidence tags.

## 9. History

- 2026-10-01: first export / import round trip (project B): 11 staging screens
  for the configuration and operation faceplates and 8 text lists generated;
  text lists and the first staging screen imported without errors, then all
  11 staging screens in one run (`import_log.txt` 13:19, no errors).
  Audit of the whole HMI from the exports (`B\HmiProjectAudit_2026-10-01.md`);
  `HmiExport.ps1` extended for PLC types / blocks and HMI tag tables.
- 2026-10-01, later: full redesign imported in one run (third try), first
  compile: all safety element links failed until the UDT elements were made
  accessible from the HMI (7.2). Screen titles removed from the redesign.
- 2026-10-01, run 3 prepared: 49 tab screens with generated faceplate
  instances, restyled pop-ups (Override), jog buttons rebuilt from presets.
- 2026-10-02, run 4 prepared: help in one text style, tab screens renamed
  with numbers in per-station folders, mode button feedback, G00 system on.

- 2026-10-02, run 6 prepared: internal tag for button feedback, group
  overviews with the Modes row as group bar.
- 2026-10-02, run 7 prepared: feedback back on the button bit, safety device
  symbols from rectangles, circles and lines (Line: StartLeft / StartTop /
  EndLeft / EndTop; height 0 for a horizontal line, `[INFERRED]` until
  imported) as the source for faceplate types (staging screen), graphic
  view at the graphic's own size (a scaled 128 px PNG pixelates).
- 2026-10-02, run 8 prepared: range appearance animations on Rectangle and
  Circle (BackColor = fill, ForeColor taken as the border colour
  `[INFERRED]` until imported) and on a transparent text field for a red
  text (BackColor of the range unused); status symbols grey while OK.
- 2026-10-02, run 9 prepared: invisible link buttons on the Modes rows;
  user name through a scheduled task on "User change".
- 2026-10-02, run 10 prepared: GetUserName removed from the generated screen
  events and the User pop-up (generator filters it out of copied screen
  events); the scheduled task is the only writer of the user name tag.
- 2026-10-02: faceplate type version mismatch crashed TIA during an import
  (pitfall above).
- 2026-10-02: project B catch-up run imported (tag table, three pop-ups with
  Override, 65 screens in two passes, nested folders); authorizations set
  per object in the generator; ImportStaging.ps1 continues after a failed
  screen (`$StopOnError = $false`, `$ScreenSkip`, failure list at the end).
- 2026-10-06: HMI preview built (validator, preview server, browser app,
  diff, PNGs through headless Edge); `render.py` retired; the generator
  writes to `hmi\generated\` and validates; TiaBridge `import` refuses on
  validator errors. Not yet run on project B.
- 2026-10-06: full exports only (2.3): TiaBridge exports screens, templates
  and pop-ups full into `hmi\<kind dir>`; the HMI preview's default sizes,
  fallback margins and colours removed, `document.incomplete` /
  `document.not-full` added; renders of 040, 1005, 5051, 5052 and the
  template from the full exports show no incomplete object.
- 2026-10-06: probes on project B through TiaBridge: HMI
  `TypeIdentifier` from the hardware side (section 5), screen size in the
  minimal export (section 4), `FaceplateTypeName` folders = library folder
  path (7.2). The preview's faceplate link check dropped the `_Library` root
  and was fixed (`links.py`); `list` kind `hmi_screen` reported `infoError`
  for every screen and was fixed (`Objects.ps1`). Still `[INFERRED]`:
  text-fit font size in pixels, absent margins as 0, `Culture` inside
  `FontItem`, the `//Portrait` suffix.
