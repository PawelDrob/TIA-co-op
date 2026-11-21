# PLC block, data type, DB

The guide: s7dcl-format.md, the core every PLC change reads. Its section 9 checklist runs before every import, and its table says which part holds the rule of each item. Read a part, beside it in `docs\agent\`, when the change touches what it covers:

| The change touches | Read too |
|---|---|
| SCL networks only | Nothing more |
| A LAD network, new or changed | s7dcl-lad.md |
| A DB's start values or retain, a data type, a member's attributes or comment (`.s7res`) | s7dcl-exports.md, 8.14b |
| A LAD instruction named as on TIA's screen or in its help; a library, Technology or F-LAD box | s7dcl-exports.md, 8.13a |
| A LAD branch from a merge node; a LAD operand with several indices | s7dcl-exports.md, 8.14c |
| A classic `.scl` or `.udt` source to bring in | s7dcl-exports.md, 8.14d |
| An import that fails, or a log message to read | s7dcl-import.md, section 10 and its table of messages |

## An OB

SimaticML only. Edit it per openness-v20.md section 1, "Editing an OB's SimaticML": keep the declaration `encoding="utf-8"` and every namespace without a prefix, so no Python ElementTree round trip.

## The middle

1. Edit the exported file per the guide. A new block: write its files in the repo. Done when the section 9 checklist passes.
2. `import`; a new block with `target_folder`. Done when every item is ok.
3. `compile`; fix and repeat. Done when it has 0 errors and nothing of this session's stands in `failed`.
4. `export` again and diff against your edit. Done when every difference left is the exporter's normalization or a block attribute it leaves out (section 9, item 18).
