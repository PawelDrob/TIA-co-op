---
type: Guide
title: Block viewer internals
description: How the block viewer draws one .s7dcl with the change report's code, opens it in the default browser with no console, registers for a double-click, and what its tests cover.
tags: [dev, change-reports, plc]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-19T15:23:07-05:00 }
---

# Block viewer internals

One block export in, one page in the default browser out. What it does for a user is in [its README](../../../TiaChangeReports/viewer/README.md). It lives in `TiaChangeReports\viewer\` and imports the report, so that a change to the report's drawing changes both: [TiaChangeReports internals](tia-change-reports.md) has the readers and the drawing.

## The page

`view.page(path)` reads the file with the report's readers (`source.from_file`, `s7dcl.parse_block`), gives the block the report's call lookup (`compare.Callees`) over the project the file is in, and writes one self-contained page:

| Part | Drawn by |
|---|---|
| Header, properties | The report's block header; every property the file holds (`iface.props_rows`) |
| Interface | `iface.html(blk, blk, whole=True)`: the block compared with itself, every member open, and every member of a UDT type opened onto the UDT's members (`iface._unfold`); an arrow only where something opens |
| A LAD network | `render_lad.Layout` in the report's frame (`page._lad_pane`), with no diff: nothing marked |
| An SCL network | `s7dcl.scl_lines`, one side of the report's text table |
| Style and script | `page.CSS` and `page.JS`: the folds of networks, sections and members, Collapse all and Expand all, zoom, pan and minimap as in the report |

The title bar, the comment field and the text table are written in `view.py`: the report's classes, with one side where the report writes two. `.panes`, `.nwt` and `.nwc` are the report's grids with one column. A change to that markup in `page.py` does not reach the viewer; a change to the drawing does. `test_viewer.Drawing` holds every LAD network of a made-up project to the bytes of the SVG the report draws for it with `--all`.

**The project** (`view.project_root`): the nearest folder above the file with `plc`, `hmi` and `library`, a TiaBridge repo; else the nearest git repo's top; else the file's folder. The lookup lists that folder only when a call or type is asked for.

**A UDT member's members:** the export lists them only where a DB's start values name them, which is all the report opens. The viewer reads the UDT's own file through `blk.callees`, nested UDTs and the UDT's structs too, each in its parent's section, as `iface.Inner` rows (the lighter grey of an opened member, its comment and default value from the UDT; in Temp and Return no default and no boxes, under an in-out every box empty, as their parent's). An array of a UDT, an array inside an opened UDT, an FB instance and a UDT the project lacks stay closed, with no arrow; an array of struct declared in the block opens onto its first element, as in the report.

**An instance DB, and a DB of a UDT:** its `.s7dcl` holds no members, only its type, the start values it sets and `S7_StandardRetain`. `view.type_of` finds the FB or UDT through `blk.callees`, as a call's interface (by name in any case; the project's block before a library type). `iface.html(..., whole=True, db_retain=...)` then lists every member of the FB's Input, Output, InOut and Static sections, or of the UDT (`iface._instance`), as `Inner` rows with the type, comment, default and attributes of that file. The DB's start values land on them, nested ones too (`a.b := 1`). Retain is the FB's; where the FB leaves it to the instance ("Set in IDB"), and on a DB of a UDT, it is the DB's own (`view.db_retain`). A UDT member opens as above, and so does a multi-instance of an FB of the project (`iface._unfold` with `fbs`), onto that FB's Input, Output, InOut and Static, a multi-instance inside it too; never its Temp and constants. An FB that would hold itself by a chain (Ping holds Pong, Pong holds Ping) opens once: its instance inside stays closed, with no arrow, as does an instance of a system FB such as `TON_TIME` (no file in the project). In an FB's own interface a multi-instance stays closed, as above. A line above the table names the file the members come from; when no FB or UDT of that name is found, the line says that its members could not be read, above the start values the DB sets. A SimaticML export of such a DB holds the whole interface, but not the FB's defaults, so it is drawn the same way: the reader leaves its start values out, and `view.block_of` reads them with `simaticml.parse_interface`, as for a global DB, and the retain from its members' `Remanence`. Both formats of one DB give one table (`test_viewer.InstanceDb`).

**A SimaticML export** is read in any case of its extension: `source.from_file` takes a lower-case `.xml` only, so `view.block_of` passes an upper-case one's text to the reader as SimaticML.

**A file it cannot draw:** any error of the readers becomes one line above the source, without the file's path; an error of the system gives its text alone ("No such file or directory"). The Drawing button is disabled.

**The switch:** a file opens on its drawing. Showing the source sets `#source` in the address, so a reload stays there.

## Opening the page

`browser.py` writes the page to `%TEMP%\TiaChangeReports-viewer\` and opens it as Windows opens an `.html` file (`os.startfile`): the default browser. Pages older than a day go at the next start.

**No console:** the registered command runs `.venv\Scripts\pythonw.exe`, a program of the Windows subsystem. With no console, `__main__.py` says what went wrong in a message box: a page Windows cannot open, or an error of the viewer itself.

## Double-click

`register.py`, for `HKEY_CURRENT_USER\Software\Classes` only:

- The program id `TiaChangeReports.BlockViewer`, with its open command.
- `.s7dcl`'s default set to that id, keeping the id that was there last on the program id's key, to restore.
- That id among `.s7dcl\OpenWithProgids`.

`--unregister` takes all of it back and removes `.s7dcl`'s key when nothing else is in it. A choice made in Open with (`FileExts\.s7dcl\UserChoice`) beats the default and is hashed by Windows so that no program writes it: register names it and leaves it. Both tell Explorer through `SHChangeNotify`.

## Tests

In the report's suite, so a change to the drawing runs them:

- `test_viewer.py`: the drawing against the report, a UDT member's members from the UDT's file (and the report's table without them), an instance DB's and a DB of a UDT's members from both formats, the source and the files it cannot draw, the opening with a stand-in for `os.startfile`, and the registration in a key of the test's own under `HKEY_CURRENT_USER`, removed after.
- `test_interface_fold.py`: the interface fold of the viewer and of the report, one section or member at a time and all at once by Collapse all, Expand all, C and E, in headless Edge or Chrome, skipped without one.

No test opens a window or the default browser.
