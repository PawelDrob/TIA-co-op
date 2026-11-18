# TiaChangeReports

Experimental.

One HTML page of what changed in a TIA project.

## What it does

- Shows changed, new and deleted PLC blocks, DBs, UDTs and library types: interface and properties apart, LAD drawn as TIA
  does, SCL as a line diff.
- Shows PLC tag tables, and HMI screens, templates, pop-ups, tag tables and text lists before and after.
- Compares two files, two folders or two git revisions.
- Reads PLC blocks as `.s7dcl`, the supported format, and as SimaticML (xml), experimental.

## What it does not

- Export anything or touch TIA: it reads exports.
- Show every difference. Where the files differ in something it does not display, the block or network carries a note
  saying so: compare those two versions in TIA. No note comes when the same network is already marked as changed for
  another reason, when another attribute of the same member has also changed, or between XML and `.s7dcl` when the block
  has other changes.
- Show changes to other translations: it reads one language, English unless `--lang` names another, else the first
  language with a text.
- Stop at a block it cannot read in a folder or revision: it skips that file, names it and writes the rest. A file you
  name as before or after that it cannot read, and an HMI file it cannot read, stop the report: exit code 2, nothing written.

## How to use

Ask the agent, in a session with [TiaBridge](../TiaBridge/README.md):

> Show me what changed in the last commit of Line1.

Yourself, from the clone's folder, after [first setup](../docs/user/setup.md):

```
.venv\Scripts\python.exe -X utf8 TiaChangeReports --git <project repo> HEAD~1 HEAD -o report.html
```

`--help` lists the rest. It needs `TiaHmiGenerator` beside it, which the clone holds, and Edge or Chrome only for `--png`.

## Checking the two formats against each other

For whoever works on the report: does it say the same from `.s7dcl` as from SimaticML? The check runs on a repo where
each commit holds both: `.s7dcl` under `plc\` and `library\`, and SimaticML of the same objects under `simaticml\`. It
reads the repo's commits and changes nothing in it.

```
.venv\Scripts\python.exe -X utf8 -m TiaChangeReports.twoformats <repo> [--since REV] [--until REV] [--check nothing|same|both] [--json out.json]
```

- **Nothing changed:** per commit, the report from its `.s7dcl` to its SimaticML. Each object and network the report
  lists is a difference. It prints the counts at the first commit, the last and the one with the most.
- **The same change:** per commit, the report of the commit from `.s7dcl` and from SimaticML. Each object whose two
  reports differ is a difference.

Each difference gets its causes, and each cause its kind: a reader that reads a format otherwise, a field only one
format writes, the note, the drawing, the diff, or an object in one format only. A cause the tool cannot name prints
as `unknown: ...`. Numbers per cause: objects and networks (and how many networks have no other cause), or commits and
objects. `--json` writes every difference with its causes, and for the second check the facts each report alone holds.
Both checks over 530 commits take about half an hour. Run from the clone's folder, which `-m` needs.
