# Block viewer

Experimental.

Opens one PLC block export in your default browser, drawn as the [change report](../README.md) draws it, without TIA.

## What it does

- Draws one `.s7dcl` file: its properties, its interface and every network, LAD as TIA draws it, SCL as text. The
  drawing is the change report's own, so the two always look the same. A network, an interface section (Static,
  Input, ...) and a member with members fold on a click; Collapse all and Expand all (or the keys C and E) fold or
  open all of them. A member of a UDT type opens onto the UDT's members, read from the UDT's file in the project;
  one whose UDT the project does not hold has nothing to open and no arrow. An array of a UDT, an FB instance and a
  system type such as `TON_TIME` stay closed, with no arrow. The change report opens them only where a DB's start
  values name their members.
- Draws an instance DB, or a DB of a UDT, with the members of its FB or UDT, read from that block's file in the
  project: each with its type, comment, start value and retain. A start value the DB sets itself is black, the FB's
  default grey. A multi-instance of an FB of the project opens there onto that FB's members; one of a system FB
  such as `TON_TIME` stays closed. A line above them names the file they come from. When the project holds no file of
  that FB or UDT (a library block, a system FB, a block not exported), the page says that its members could not be
  read.
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

The page opens in your default browser. `--html <out.html>` writes the page instead of opening it. `--help` lists the
rest.

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

A double-click starts no console, only the page in your default browser.
