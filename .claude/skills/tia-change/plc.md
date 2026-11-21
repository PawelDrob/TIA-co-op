# PLC block, data type, DB

The guide: s7dcl-format.md, the core every PLC change reads. Its section 9 checklist runs before every import, and its table says which part holds the rule of each item. Read a part, beside it in `docs\agent\`, whole, when the change touches what it covers:

| The change touches | Read too |
|---|---|
| An SCL block, new or changed, with no comment or title new or changed and no call of a library, communication, Technology or F instruction (an extended one, `T_CONV` and its like, is checklist item 21) | s7dcl-data.md when it declares a multi-instance of an FB imported in this session |
| An SCL block calling a library, communication, Technology or F instruction | s7dcl-instructions.md; s7dcl-data.md when it declares a multi-instance of an FB imported in this session |
| A LAD block, its networks new or changed | s7dcl-lad.md; s7dcl-instructions.md when a box whose name differs from TIA's screen, as CONV, SCALE_X, MOVE_BLK; s7dcl-data.md when it declares a multi-instance of an FB imported in this session |
| A LAD block with an extended, library, communication, Technology or F box | s7dcl-lad.md, s7dcl-instructions.md; s7dcl-data.md when it declares a multi-instance of an FB imported in this session |
| A comment or title, new or changed (`.s7res`), in any block, DB or data type | s7dcl-resources.md; s7dcl-data.md when a member's comment is new, for its pragma |
| A DB, new or changed: global, instance or of a data type; its start values or retain | s7dcl-data.md; s7dcl-instructions.md when an instance DB of a library, Technology or F box; s7dcl-import.md when its type is a library type changed in this session |
| A data type, new or changed; a member's attributes | s7dcl-data.md |
| A classic `.scl` or `.udt` source to bring in | s7dcl-data.md |
| An F-block (`safety: true`), the main safety block above all: its import needs a step of the user's after it | s7dcl-lad.md, s7dcl-instructions.md, s7dcl-import.md; s7dcl-data.md when it declares a multi-instance of an FB imported in this session |
| An OB | s7dcl-instructions.md, s7dcl-import.md; s7dcl-lad.md when its networks are LAD; SimaticML only: see An OB below |
| An FBD, STL or GRAPH network | Nothing more: the core's section 12 says what is blocked, and why |
| A PLC tag table, watch or force table, technology object | Nothing more: a SimaticML document: openness-v20.md, section 1, its rows Formats, Watch and force tables and Technology objects, and the tag table in Editing an OB's SimaticML; the core's checklist item 20 names the kind it goes under |
| A library type's document | s7dcl-import.md; library.md, and the rows above for what the document holds |
| An import or an SD export that fails, or a log message to read | s7dcl-import.md; s7dcl-lad.md, s7dcl-instructions.md, s7dcl-resources.md, s7dcl-data.md when the log message's row names it |
| The first change after a TIA Portal update | s7dcl-import.md |

## An OB

SimaticML only. Edit it per openness-v20.md section 1, "Editing an OB's SimaticML": keep the declaration `encoding="utf-8"` and every namespace without a prefix, so no Python ElementTree round trip.

## The middle

1. Edit the exported file per the guide. A new block: write its files in the repo. Done when the section 9 checklist passes.
2. `import`; a new block with `target_folder`. Done when every item is ok.
3. `compile`; fix and repeat. Done when it has 0 errors and nothing of this session's stands in `failed`.
4. `export` again and diff against your edit. Done when every difference left is the exporter's normalization or a block attribute it leaves out (section 9, item 18).
