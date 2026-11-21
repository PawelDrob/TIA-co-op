# PLC block, data type, DB

The guide: s7dcl-format.md, the core every PLC change reads. Its section 9 checklist runs before every import, and its table says which part holds the rule of each item. Read a part, beside it in `docs\agent\`, whole, when the change touches what it covers:

| The change touches | Read too |
|---|---|
| SCL networks only, and nothing of a row below | Nothing more |
| A LAD network, new or changed | s7dcl-lad.md |
| A comment or title, new or changed (`.s7res`) | s7dcl-resources.md |
| A DB's start values or retain, a data type, a member's attributes; a multi-instance of an FB imported in this session; a classic `.scl` or `.udt` source to bring in | s7dcl-data.md |
| A call of a library, communication, Technology or F instruction, in LAD or SCL; a LAD instruction named as on TIA's screen or in its help | s7dcl-instructions.md |
| An F-block (`safety: true`), the main safety block above all: its import needs a step of the user's after it | s7dcl-import.md |
| An import or an SD export that fails, or a log message to read | s7dcl-import.md |
| The first change after a TIA Portal update | s7dcl-import.md |

## An OB

SimaticML only. Edit it per openness-v20.md section 1, "Editing an OB's SimaticML": keep the declaration `encoding="utf-8"` and every namespace without a prefix, so no Python ElementTree round trip.

## The middle

1. Edit the exported file per the guide. A new block: write its files in the repo. Done when the section 9 checklist passes.
2. `import`; a new block with `target_folder`. Done when every item is ok.
3. `compile`; fix and repeat. Done when it has 0 errors and nothing of this session's stands in `failed`.
4. `export` again and diff against your edit. Done when every difference left is the exporter's normalization or a block attribute it leaves out (section 9, item 18).
