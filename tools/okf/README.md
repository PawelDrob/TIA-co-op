# OKF bundle checker

`docs\` is a documentation bundle in the Open Knowledge Format (OKF) v0.2
(https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md), with a few stricter rules (below).
This folder checks it and writes its generated files. Windows PowerShell 5.1, no install.

```
powershell -NoProfile -File tools\okf\Test-OkfBundle.ps1 -Path docs -WriteIndex
```

- `-WriteIndex` rewrites every `index.md` before the check. Without it the tool only checks. `-Quiet` prints errors
  only. Exit code 1 on errors.
- `-WriteViz` makes `docs\viz.html` when you want it, a graph viewer of the bundle to open in a browser. Git ignores
  it and the check does not read it. `-Name` is the name in its header (default: the repo folder).
- The pre-commit hook runs the check when a commit touches `docs\`, and the tests below when it touches this folder.
- Tests (Pester 3.4): `powershell -NoProfile -File tools\okf\tests\run.ps1`.

## Rules

OKF fixes the container: Markdown files with a YAML header, folders, `index.md` and `log.md`. On top of it:

- Every folder with documents has an `index.md`; the bundle root has `log.md`. No `README.md` inside the bundle.
- File names are kebab-case (`s7dcl-format.md`), no dates in names.
- Every document starts with a header between `---` lines: `type` (one of [types.md](types.md)), `title`,
  `description` (one sentence), `generated: { by: <actor>, at: <ISO 8601 date-time with offset> }`; optional `tags`,
  `status` (`draft`, `deprecated`; omit when stable), `verified`, `stale_after`, `sources`.
- The header is a YAML subset: maps, lists, `{ }` and `[ ]` on one line, plain or quoted values.
- Actors: `human:<name>`, `<producer>/<model>` for an agent (`claude-code/claude-opus-5-5`), `process:<id>`,
  `team:<id>` (source authors only). `generated` names who made the last content change; formatting-only changes
  leave it alone. Only a person adds their own `human:` entry to `verified`.
- Dates in prose are ISO (`2026-10-04`).
- Links are relative Markdown links to a file (not `/...`, no `[[wikilinks]]`); a folder is linked through its
  `index.md`. Broken links are errors.
- `index.md` files are generated (one section per type, then the folders); edit a document's header, not its index
  entry. Only the root `index.md` has a header: `okf_version: "0.2"`.
- `log.md`: `## YYYY-MM-DD` headings, newest first, one bullet per event, starting with a bold label
  (**Creation**, **Update**, **Move**, **Deprecation**, **Initialization**). Log what git does not show well.

## Files and license

- `Test-OkfBundle.ps1` (entry point), `OkfBundle.ps1` (check, indexes), `types.md` (the type vocabulary and its
  colors), `tests\`: part of this repository, under its license.
- `OkfViz.ps1` (viewer): derived from `reference_agent/viewer/generator.py` of Google's Open Knowledge Format
  reference implementation, Copyright 2026 Google LLC, Apache License 2.0 (`viz\LICENSE.txt`); its header lists
  what changed.
- `viz\viz.html`, `viz.js`, `viz.css`: the OKF bundle viewer of Google's Open Knowledge Format reference
  implementation, unchanged, Copyright 2026 Google LLC, Apache License 2.0 (`viz\LICENSE.txt`, `viz\NOTICE.txt`).
  The generated `docs\viz.html` embeds it and loads Cytoscape.js and marked (MIT) from cdn.jsdelivr.net.
