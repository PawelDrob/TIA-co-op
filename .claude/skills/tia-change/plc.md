# PLC block, data type, DB

The guide: s7dcl-format.md. Its section 9 checklist runs before every import.

## The middle

1. Edit the exported file per the guide. A new block: write its files in the repo. Done when the section 9 checklist passes.
2. `import`; a new block with `target_folder`. Done when every item is ok.
3. `compile`; fix and repeat. Done when it has 0 errors and nothing of this session's stands in `failed`.
4. `export` again and diff against your edit. Done when every difference left is the exporter's normalization or a block attribute it leaves out (section 9, item 18).
