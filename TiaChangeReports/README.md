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

**Colours of your own.** The report draws in TIA's colours. For your own, write `%LOCALAPPDATA%\tia-co-op\theme.css`
with the `--theme-format` line and only the lines you change; the names and TIA's values are in
`TiaHmiGenerator\hmipreview\static\tia-theme.css`:

```css
.ldiff {
  --theme-format: 1;
  --wire: #0057b8;
}
```

A name you leave out keeps TIA's value, also when that value changes in a later version. Every report and the block
viewer then draw in your colours, also the reports the agent and Archive Compare make.
`--theme <file>` takes another theme for one report, `--theme tia` TIA's colours. A faulty file stops the report and
names its line.
