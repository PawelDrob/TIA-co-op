---
type: Guide
title: Block viewer internals
description: How the block viewer draws one .s7dcl with the change report's code, opens it as a browser app window with no console, registers for a double-click, and how its tests and window check run.
tags: [dev, change-reports, plc]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-18T09:10:10-05:00 }
---

# Block viewer internals

One block export in, one page in a window out. What it does for a user is in [its README](../../../TiaChangeReports/viewer/README.md). It lives in `TiaChangeReports\viewer\` and imports the report, so that a change to the report's drawing changes both: [TiaChangeReports internals](tia-change-reports.md) has the readers and the drawing.

## The page

`view.page(path)` reads the file with the report's readers (`source.from_file`, `s7dcl.parse_block`), gives the block the report's call lookup (`compare.Callees`) over the project the file is in, and writes one self-contained page:

| Part | Drawn by |
|---|---|
| Header, properties | The report's block header; every property the file holds (`iface.props_rows`) |
| Interface | `iface.html(blk, blk, whole=True)`: the block compared with itself, every member open |
| A LAD network | `render_lad.Layout(...).svg()`, unchanged and unmarked, with the frame style `page._lad_pane` gives it |
| An SCL network | `s7dcl.scl_lines`, one side of the report's text table |
| Style and script | `page.CSS` and `page.JS`: fold, zoom, pan and minimap as in the report |

`.panes`, `.nwt` and `.nwc` are the report's grids with one column. `test_viewer.Drawing` holds every LAD network of a made-up project to the bytes of the SVG the report draws for it with `--all`.

**The project** (`view.project_root`): the nearest folder above the file with `plc`, `hmi` and `library`, a TiaBridge repo; else the nearest git repo's top; else the file's folder. The lookup lists that folder only when a call or type is asked for.

**A file it cannot draw:** any error of the readers becomes one line above the source, the path cut from it, and the Drawing button is disabled.

## The window

`window.py` writes the page to `%TEMP%\TiaChangeReports-viewer\` and starts the browser with `--app=<file URL>`: an app window, with no tabs and no address bar. The browser is the report's PNG browser (`hmipreview.edge.edge_path`): Edge, else Chrome. Pages older than a day go at the next start.

Why a browser app window: Edge comes with Windows 11 (Chrome where it was removed) and needs nothing installed, and the page is already the report's HTML. A package that hosts WebView2 would add a dependency with native parts for the same window.

**No console:** the registered command runs `.venv\Scripts\pythonw.exe`, a program of the Windows subsystem. With no console, `__main__.py` says what went wrong in a message box: no browser, or an error of the viewer itself.

The browser runs with the person's profile, so a running Edge opens the window in its own process. `--profile <folder>` (hidden from `--help`) starts a browser of its own: the window check needs one on its hidden desktop.

## Double-click

`register.py`, for `HKEY_CURRENT_USER\Software\Classes` only:

- The program id `TiaChangeReports.BlockViewer`, with its open command.
- `.s7dcl`'s default set to that id, keeping the id that was there before on the program id's key, to restore.
- That id among `.s7dcl\OpenWithProgids`.

`--unregister` takes all of it back and removes `.s7dcl`'s key when nothing else is in it. A choice made in Open with (`FileExts\.s7dcl\UserChoice`) beats the default and is hashed by Windows so that no program writes it: register names it and leaves it. Both tell Explorer through `SHChangeNotify`.

## Tests and the window check

`TiaChangeReports\tests\test_viewer.py`, in the report's suite: the drawing against the report, the source and unreadable files, the window's command with a stand-in for the browser, and registration in a key of the test's own under `HKEY_CURRENT_USER`. No test opens a window.

`<py> TiaChangeReports\viewer\check_window.py [--out <folder>]` runs by hand. It makes a hidden desktop and registers in a key of its own. It runs the registered command from there, plus `--profile`, on a LAD block and on a file it cannot draw. It checks for one browser window per file and no console on either desktop, and saves a PNG of each window (`PrintWindow`).

## Freezing it

One `.exe` would bundle Python, the report and the HMI preview's `rail` and `edge` modules: PyInstaller or the embedded Python the archive compare download already ships (`TiaArchiveCompare\package\`), with `pythonw` as the entry. The page and the browser window stay as they are.
