---
type: Guide
title: Block viewer internals
description: How the block viewer draws one .s7dcl with the change report's code, opens it in the default browser with no console, registers for a double-click and for Open with on .xml, and what its tests cover.
tags: [dev, change-reports, plc]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-19T18:18:27-05:00 }
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

**An instance DB, and a DB of a UDT:** its `.s7dcl` holds no members, only its type, the start values it sets and `S7_StandardRetain`. `iface.db_type` decides the type, for the line above the table and for the table alike: the block of the file that `blk.callees` finds for that name, as for a call's interface, when it is an FB or a UDT; the file of an FC counts as not found, one of a global DB or an OB is passed over for the next file of that name. That lookup goes by the file alone: an export named as the type (its file-safe name, in any case) anywhere the project's exports are read (in a project repo under `plc/`, a PLC's `blocks`, `systemblocks`, `types` and `technology` alike, `project/` and the library's `types`, `faceplates`, `mastercopies` and `global`, not `library/changes/`; else all of the folder but a dot folder at its top), with several PLCs not another PLC's; of several such files the project's before a library type's (for a DB under `library/`, the library's first, of its own version), in work before released, then by path. A block, a system FB and a library type are read alike when the project holds their file, and none of them when it does not. The report takes whatever the name finds. `iface.html(..., whole=True, db=...)` (db: the retain the DB sets itself; None on any other page) then lists every member of the FB's Input, Output, InOut and Static sections, or of the UDT (`iface._instance`), as `Inner` rows with the type, comment, default and attributes of that file. The DB's start values land on them, nested ones too (`a.b := 1`). Retain is the FB's; where the FB leaves it to the instance ("Set in IDB"), and on a DB of a UDT, it is the DB's own (`iface.set_by_db` says which members, `view.own_retain` reads the value). A UDT member opens as above, and so does a multi-instance of an FB of the project (`iface._unfold` with `fbs`), onto that FB's Input, Output, InOut and Static, a multi-instance inside it too; never its Temp and constants. An FB that would hold itself by a chain (Ping holds Pong, Pong holds Ping) opens once: its instance inside stays closed, with no arrow, as does an instance of an FB the project holds no file of, such as `TON_TIME`. In an FB's own interface a multi-instance stays closed, as above. A line above the table names the file the members come from; when no file of an FB or UDT of that name is found, the line says that its members could not be read, above the start values the DB sets. A SimaticML export of such a DB holds the whole interface, but not the FB's defaults, so it is drawn the same way: the reader leaves its start values out, and `view.block_of` reads them with `simaticml.parse_interface`, as for a global DB, and the retain from its members' `Remanence`. On such a DB's page a Bool value is written `true` or `false` whichever way the file spells it (`.s7dcl` `TRUE`, SimaticML `true`; `iface._bools`), so that both formats give one table; on a row of no type (its FB not found, or a member the FB no longer has) a value `TRUE` or `FALSE` is read so too. Every other page, an FB's or a global DB's, and the report keep the file's spelling. Both formats of one DB give one table (`test_viewer.InstanceDb`).

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
- That id among `.xml\OpenWithProgids`, and nothing else of `.xml`: Explorer lists it in Open with for `.xml` files, under its `FriendlyAppName` (Block viewer), and `.xml`'s default and its `UserChoice` stay. On Windows 11, asked through `SHAssocEnumHandlers` from a new process, the shell lists such an id at once, with no `SHChangeNotify` and no sign-out; the menu of an Explorer already running, which caches, was not looked at.

`--unregister` takes all of it back and removes `.s7dcl`'s key when nothing else is in it; of `.xml` it removes only that value, and leaves the key and the other programs' values. A choice made in Open with (`FileExts\.s7dcl\UserChoice`) beats the default and is hashed by Windows so that no program writes it: register names it and leaves it. Both tell Explorer through `SHChangeNotify`.

## Tests

In the report's suite, so a change to the drawing runs them:

- `test_viewer.py`: the drawing against the report, a UDT member's members from the UDT's file (and the report's table without them), an instance DB's and a DB of a UDT's members from both formats, the source and the files it cannot draw, the opening with a stand-in for `os.startfile`, and the registration in a key of the test's own under `HKEY_CURRENT_USER`, removed after; a key opened to write anywhere else fails the test before it is written.
- `test_interface_fold.py`: the interface fold of the viewer and of the report, one section or member at a time and all at once by Collapse all, Expand all, C and E, in headless Edge or Chrome, skipped without one.

No test opens a window or the default browser.
