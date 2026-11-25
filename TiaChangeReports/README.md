# TiaChangeReports

Experimental.

One HTML page of what changed in a TIA project.

## What it does

- Shows changed, new and deleted PLC blocks, DBs, UDTs and library types: interface and properties apart, LAD drawn as TIA
  does, SCL as a line diff in the colours of TIA's SCL editor.
- Shows PLC tag tables, and HMI screens, templates, pop-ups, tag tables and text lists before and after.
- Compares two files, two folders or two git revisions.
- Reads PLC blocks as `.s7dcl`, the supported format, and as SimaticML (xml), experimental.

## What it does not

- Export anything or touch TIA: it reads exports.
- Show every difference. Where the files differ in something it does not display, the block or network carries a note
  saying so: compare those two versions in TIA. No note comes when the same network is already marked as changed for
  another reason, or when another attribute of the same member has also changed.
- Compare the files of a block exported as XML on one side and as `.s7dcl` on the other. It compares what it reads of
  both, and the page names such blocks: a field it does not read, or one that only one of the two formats writes, is not
  compared there. Compare those in TIA where that matters.
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

**Colours of your own.** The report draws in TIA's colours. For others, take a VS Code color theme: write
`%LOCALAPPDATA%\tia-co-op\theme.json` as `{ "include": "C:/path/to/the-theme.json" }` (in JSON a path takes `/` or
`\\`), the theme's file where its extension keeps it. A theme extension's files are under
`%USERPROFILE%\.vscode\extensions\`, VS Code's own themes under its folder's `resources\app\extensions\`. Every report
and the block viewer then draw in the theme, also the reports the agent and Archive Compare make; a page says under its
title, the viewer in its bar, which theme it is drawn in. What a VS Code theme has no colour for, a LAD box or a change
mark, the report makes from the theme's own colours, and it moves what it makes and takes until every text is at
least as easy to read as in TIA's colours, up to WCAG's 4.5 to 1. To set one of the report's colours yourself, add
`"tia.<name>"` to `"colors"` in your `theme.json`, as `"tia.wire": "#0057b8"`; the names are in
[the developer notes](../docs/dev/tools/tia-change-reports.md#from-a-vs-code-theme-to-the-palette). A colour you set
so, and the theme's page, are drawn as written: where one leaves a text under that bound, the
report prints a warning that names it.
`--theme <file>` takes another theme for one report, `--theme tia` TIA's colours. A faulty file stops the report and
names its line, or says why it cannot be read.
