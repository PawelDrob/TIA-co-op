# Block viewer

Experimental.

Opens one PLC block export in a window of its own, drawn as the [change report](../README.md) draws it, without TIA.

## What it does

- Draws one `.s7dcl` file: its properties, its interface and every network, LAD as TIA draws it, SCL as text. The
  drawing is the change report's own, so the two always look the same.
- Reads the titles and comments from the `.s7res` beside the file, and a call's pins and the types it uses from the
  other exports of the project the file is in (the folder that holds `plc`, `hmi` and `library`, else the git repo,
  else the file's own folder).
- Shows the file's text, and its `.s7res`, on the Source switch (or the keys D and S).
- Opens the SimaticML `.xml` of a block when you name it, as the report reads it: experimental.
- A file it cannot draw opens on its text, with the reason above it.

## What it does not

- Edit anything, or show a project tree, search across blocks or HMI objects.
- Register itself: double-click opens `.s7dcl` files in it only after you run the register command below. It never
  registers `.xml`, which would take every XML file.

## How to use

From the clone's folder, after [first setup](../../docs/user/setup.md):

```
.venv\Scripts\python.exe -X utf8 TiaChangeReports\viewer <file>.s7dcl
```

`--html <out.html>` writes the page instead of opening a window. `--help` lists the rest.

**Double-click.** To open `.s7dcl` files in the viewer by a double-click, for your Windows user only:

```
.venv\Scripts\python.exe -X utf8 TiaChangeReports\viewer --register
```

To take that back, which restores the program `.s7dcl` files opened with before:

```
.venv\Scripts\python.exe -X utf8 TiaChangeReports\viewer --unregister
```

Run both in the clone you keep: the registered command holds that clone's path. If you once chose another program for
`.s7dcl` files in "Open with", Windows keeps that choice, and `--register` says so. Then right-click a `.s7dcl` file,
choose Open with, Choose another app, Block viewer, and Always.

The window is Microsoft Edge, or Google Chrome where Edge is missing, opened as an app window: no tabs and no address
bar. A double-click starts no console.
