---
type: Guide
title: SIMATIC SD (.s7dcl) authoring guide
description: How to write SIMATIC SD (.s7dcl) PLC blocks for TIA Portal V20 and V21 that import cleanly, with every statement tagged by its source; the core every PLC change reads, and which part holds LAD networks, comments, data, instructions and import diagnostics.
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T17:16:20-05:00 }
sources:
  - id: lad-doc
    resource: https://support.industry.siemens.com/cs/ww/en/view/109994073
    title: SIMATIC Source Documents - LADDER Format Description V1.0 (2025-09)
    author: team:siemens
  - id: readme
    resource: SIMATIC TIA Portal V20 Update 4 and 5 readmes (A5E54260417)
    title: TIA Portal V20 readmes
    author: team:siemens
  - id: iec
    resource: IEC 61131-3 programming languages standard
    title: IEC 61131-3
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD (.s7dcl) Authoring Guide for AI Agents

Target platform: Siemens TIA Portal V20 (Update 4 or later; projects are kept on the latest V20 update) / V21, SIMATIC Source Documents (SIMATIC SD) format.

**This guide in parts.** A section keeps its number in the file that holds it, so a section cited by number, here or elsewhere, is in the file this table names; 8.14b and 8.14c are parted at their items, each piece under the section's heading and a name. Read this file for every PLC change, and a part when the change needs it.

| File | Sections | Read for |
|---|---|---|
| `s7dcl-format.md`, this file | 0 to 7, 9, 12, 13 | Every PLC change: what a file is, encoding, block structure, interface, literals, networks, SCL networks, the checklist, the gaps, the workflow |
| [s7dcl-lad.md](s7dcl-lad.md) | 8, 8.1 to 8.13, 8.13b, 8.14a, 8.14b: LAD, 8.14c: branch shapes and LAD operands, 8.14, Appendices A and B | A LAD network written or changed |
| [s7dcl-resources.md](s7dcl-resources.md) | 8.14b: resource files, 8.14c: resource files | A comment or title, new or changed: the `.s7res` and its import failures |
| [s7dcl-data.md](s7dcl-data.md) | 8.14b: blocks, interfaces and data, 8.14d | A DB's body, start values or retain, a data type, a member's attributes, block headers as exported; a classic SCL source ported to SD |
| [s7dcl-instructions.md](s7dcl-instructions.md) | 8.13a | A call of a library, communication, Technology or F instruction; instruction names that differ from TIA's screen |
| [s7dcl-import.md](s7dcl-import.md) | 10, 11 | An import that fails, or does more than it was asked, and its log messages; the import of a main safety block; the platform notes: OBs, the add-in SimaticSdEnabler, a TIA update |

## 0. Source basis and confidence tags

This guide is compiled from verifiable sources only. Every statement carries one of these tags:

| Tag | Meaning |
|---|---|
| `[LAD-DOC]` | Verified from Siemens "SIMATIC Source Documents - LADDER Format Description", Entry ID 109994073, V1.0, 2025-09. Authoritative for LAD bodies and the general block/network scaffolding. |
| `[README]` | Verified from Siemens TIA Portal V20 Update 4/5 readmes (SIMATIC SD platform behavior, supported objects, limitations). |
| `[IEC]` | The LAD-DOC delegates this area to IEC 61131-3 syntax without restating it. Standard IEC syntax applies, but TIA-specific extensions are NOT covered. |
| `[INFERRED]` | Follows logically from a documented rule but is not shown verbatim in any source. Verify by round-trip import before relying on it. |
| `[GAP]` | Not specified in any available source. Do NOT guess. See section 12 for the unblocking procedure. |
| `[EXPORT]` | Verified from a TIA Portal V20 workspace export (project F, 2026-08) and, where stated, a successful re-import. Outranks `[INFERRED]`, but only for the exact shape seen. |
| `[PROBE]` | Tried on TIA Portal V20 Update 7 through Openness. Holds for the exact shape tried, as `[EXPORT]` does. |

**Hard rule for agents: when generating anything tagged `[GAP]`, stop and request a reference export from TIA Portal instead of inventing syntax.**

---

## 1. What a .s7dcl file is

- SIMATIC SD is the text-based, version-control-friendly source format for TIA Portal blocks, introduced with TIA Portal V20 (workspaces) and extended in V20 Update 4 and V21. `[README]`
- A block exports as a **pair of files**: `<BlockName>.s7dcl` (declaration + program code) and `<BlockName>.s7res` (resources: comments, titles, multilingual texts). `[README]`
- The `.s7dcl` deliberately contains **only the semantic content** of the block: no graphical positions, no UIDs, no multilingual comments. `[LAD-DOC §1.4]`
- Round-trip behavior: STEP 7 preserves user-chosen wire names and text on import/export; internal UIDs and grid positions are regenerated. Only real edits create textual diffs. `[LAD-DOC §3.5, §3.6]`
- Objects confirmed exportable in SD format: SCL blocks (V20 Upd4+), LAD blocks, UDTs, DBs (including F-DBs) via the version control interface / Openness / VCI. `[README]`
- On TIA Portal V20 **without updates** (build 20.0.9501, the TiaBridge test guest), Openness `ExportAsDocuments` refused the FC `Library_Notes` of Master_Template_X with *The export or import of blocks with mixed programming languages is not possible.* (2026-10-04); its language attribute said SCL. LAD blocks and UDTs exported. Most likely the missing Update 4 (SCL in SD, above), not a limit of SD itself: check again on V20 Update 7 before relying on it. Until then exchange such a block as SimaticML. `[EXPORT]`
- An error-free compile is NOT required for SCL export; interface templates with incomplete bodies are legal SD content. `[README]`

## 2. Encoding and lexical rules `[LAD-DOC §2]`

- **UTF-8**, preferably starting with the byte order mark `0xEF 0xBB 0xBF`. Files without BOM are interpreted with the OS code page; STEP 7 rewrites them as UTF-8 with BOM on save.
- Excluded code points: `16#D800..16#FFFF` (surrogates, private use planes, and above `16#E000`). Non-printable characters `16#0000..16#001F` and `16#007F..16#00A0` are excluded, except CR (000D), LF (000A), FF (000C), TAB (000B).
- Keywords, elementary data types, array/struct types, and block/section delimiters are **case-insensitive**. Variable-name matching between body and declaration is case-insensitive. STEP 7 is case-insensitive but **case-preserving** (also for pragmas).
- That holds on `import` `[PROBE]`: an FC, an FB, a DB and a UDT with every keyword and type in lower or mixed case (`function "x" : void`, `Function_Block`, `eNd_vAr`, `data_block`, `type`, `struct`, `bool`) imported and compiled, and their exports write the usual upper case. The exception seen is the first keyword of a **new library type**: `function`, `function_block` or `type` in lower case, and `Function`, `Function_Block` in mixed case, fail `CreateFromDocuments` with *The import failed. The instance name in the file is invalid.* With that keyword in upper case, an FC and a data type with the rest in lower case went in; other mixes were not tried. An import into a version in work took a lower-case `function` too.
- Mnemonic is always **international (English)**, regardless of project settings.
- Wire identifiers (and identifiers generally): start with a Unicode letter, followed by letters or digits.

## 3. Block structure `[LAD-DOC §2.1]`

Block types managed by STEP 7: **OB, FC/SFC, FB/SFB, DB/SDB, UDT/SDT, FBT**.

Every block consists of the following components, in this fixed order:

1. Start-of-block keyword (block-type specific)
2. Block attributes (optional)
3. Block header (interface declaration)
4. Block body (networks; start values in the case of data blocks)
5. End-of-block keyword

The only start/end keyword pair shown verbatim in the source is for function blocks:

```
FUNCTION_BLOCK <Name>
    ...interface...
    ...networks...
END_FUNCTION_BLOCK
```

- `FUNCTION_BLOCK ... END_FUNCTION_BLOCK` `[LAD-DOC Listing 2]`
- All five keyword pairs are seen in V20 exports `[EXPORT]` (project B, 2026-09): `FUNCTION_BLOCK "X"` / `END_FUNCTION_BLOCK`, `FUNCTION "X" : Void` / `END_FUNCTION` (LAD and SCL FCs), `ORGANIZATION_BLOCK "X"` / `END_ORGANIZATION_BLOCK`, `DATA_BLOCK` / `END_DATA_BLOCK`, `TYPE` / `END_TYPE`. `FUNCTION_BLOCK` and `FUNCTION` names are written quoted; `DATA_BLOCK` names quoted or not (`DATA_BLOCK "X" : "Y"`, `DATA_BLOCK X : Y`, `DATA_BLOCK X`). `TYPE` stands alone on its line, then an optional pragma block, then the name and `: STRUCT`: unquoted, except a name with a special character (`"Ns:Data" : STRUCT`) `[EXPORT]` (about 4900 exported documents, 2026-11-02; no OB among them).
- Block attributes are one pragma block in front of the keyword, of a `TYPE` after the keyword (an F-compliant UDT has `S7_Safety := "True"` there) `[EXPORT]` (8.14b): `S7_Author`, `S7_BlockComment`, `S7_BlockTitle`, `S7_EditorMode` or `S7_PreferredLanguage`, `S7_GenerateENOforSCL`, `S7_IECCheck`, `S7_Optimized`, `S7_Version`, optionally `S7_Family`, `S7_UserDefinedId`. The OB header carries no event class and no OB number, which is why a re-imported OB becomes a Program cycle OB (section 11).
- `S7_EditorMode` or `S7_PreferredLanguage` `[EXPORT]` (project A, V20 Update 7, 2026-10-29): a pure SCL block has `S7_EditorMode := "SCL"` and exactly one network (section 6); a block with networks, also SCL-only ones, has `S7_PreferredLanguage := "LAD"`. `S7_PreferredLanguage := "SCL"` is refused: *Line number 5: Value 'SCL' for attribute 'S7_PreferredLanguage' is invalid.*

## 4. Interface declarations

The LAD-DOC states: "For the interface of a block the syntax defined by the norm is used." `[LAD-DOC §2.3]` That means IEC 61131-3 declaration sections `[IEC]`:

| Section | Purpose | TIA prefix convention |
|---|---|---|
| `VAR_INPUT ... END_VAR` | Input parameters | in* (project convention) |
| `VAR_OUTPUT ... END_VAR` | Output parameters | out* (blocks before 09.2026: o*) |
| `VAR_IN_OUT ... END_VAR` | In/out parameters | io* |
| `VAR ... END_VAR` | Static variables (FB only) | stat*, inst* |
| `VAR_TEMP ... END_VAR` | Temporary variables | temp* |
| `VAR CONSTANT ... END_VAR` | Local constants | UPPER_CASE |

Declaration line form `[IEC]`:

```
name : Type
name : Type := initialValue
```

The single interface example in the source shows no trailing semicolon (`Input1 : INT`) `[LAD-DOC Listing 2]`; the V20 exporter writes a terminating `;` on every declaration `[EXPORT]`.

A `DATA_BLOCK` declaration takes no initial value `[EXPORT]` (project A, V20 Update 7, 2026-10-29): `speed : Int := 100;` fails the import with *Syntax Error : Syntax error ':=' expecting ;*. Start values go after `END_VAR` as `speed := 100;` (8.14b). FBs and UDTs keep `name : Type := value` as the default (`statDefault : Int := 1;` in an FB and `limit : Int := 10;` in a UDT imported).

Not representable / not supported in SIMATIC SD `[README]` and `[LAD-DOC §1.3]`:

- The `AT` overlay construct
- Data types `USTRING` and `UCHAR`
- Object-oriented IEC extensions
- Per-member attributes: grammar seen in exports `[EXPORT]`, see 8.14b (`S7_Access`, `S7_Visibility`, `S7_Setpoint`, `S7_MLC`); retain is a `VAR RETAIN` section of a DB or an FB, or `S7_StandardRetain` in the header of an instance DB, a DB of a UDT or a non-optimized DB (8.14b)

## 5. Literals and constants `[LAD-DOC §2.2]` `[IEC]`

"For literal constants the syntax defined by the norm is used." Standard IEC literal forms apply, as seen in the source's examples:

- Typed time literals: `T#500MS`, `t#5s`, `T#10s`
- Reals: `3.0`, `2.0`
- Integers: `42`, typed `Int#256`
- Based numbers: `16#100`, `W#16#100`
- BCD counter constants: `C#100`
- Booleans: `TRUE`, `FALSE`

## 6. The body: networks `[LAD-DOC §2.4]`

- A code block must have **at least one network**.
- A network is delimited by `NETWORK ... END_NETWORK`.
- Every network MUST be preceded by the mandatory language pragma, allowed only at network level:

```
{ S7_Language := "SCL" }
NETWORK
    ...
END_NETWORK
```

- Supported values: `"STL"`, `"LAD"`, `"FBD"`, `"SCL"`. A network without the pragma is invalid.
- Languages can be mixed freely within one block, network by network.
- Not in a block with `S7_EditorMode := "SCL"` `[EXPORT]` (project A, V20 Update 7, 2026-10-29): it takes one network only. Several fail the import with *ERROR: ResourceID 'MulitpleSCLNetworksErrorMessage' not found in resource of type Siemens.Simatic.Lang.Documents.DOL.FeedbackDocuments* (sic, the missing resource hides the real message). Titled SCL networks, alone or mixed with LAD, go in a block with `S7_PreferredLanguage := "LAD"`, as project A `PrepareTrolleyData` (8 SCL and 18 LAD networks).
- Networks are evaluated top to bottom. `[LAD-DOC §4.6.5]`

## 7. SCL networks

SCL statements go directly between `NETWORK` and `END_NETWORK`. Local variables (interface and temp) are referenced with the `#` prefix, exactly as in the SCL editor:

```
{ S7_Language := "SCL" }
NETWORK
    #oResult := #inValue1 + 10;
END_NETWORK
```

`[LAD-DOC Listing 2]`, confirmed by `[README]` ("the program code is located between the keywords NETWORK and END_NETWORK").

Notes:

- ST code per the norm is valid SCL apart from the unsupported features listed in section 4. `[LAD-DOC §1.3]`
- `GOTO` and a label in an SCL network are refused: *This instruction is not permitted in SCL networks.* They need a pure SCL block (`S7_EditorMode := "SCL"`, one network). `[EXPORT]`
- `REGION name` needs its statements on the next line; on one line: *Incomplete instruction.* `[EXPORT]`
- `%T11` and `%C11` compile in SCL, and TIA writes them back as a tag `"Tag_n"` in both export formats. `TypeOfDB(#x) = IEC_TIMER` compiles. `[EXPORT]`
- An unknown block or data type in an SCL network imports without an error; only the compile refuses it. `[EXPORT]`
- `{ S7_MLC := "MLC_x" }` in a body is a multilingual comment, `(/* text */)` in the editor; its text is in the `.s7res`. `[EXPORT]`
- Inline `//` code comments and `(* *)` block comments stay in the `.s7dcl` as written; they are not externalized to the `.s7res` `[EXPORT]`. Only interface, title and network comments become `MLC_` entries. An import brings comment lines below column 8 up to 8 (section 10).

---

## 9. Validation checklist (run against every generated file)

Where the rule of each item is, so a run reads only the parts its items need (the table at the head of this guide names the files):

| Items | Sections | File |
|---|---|---|
| 1, 11, 12, 20 | 2, 3, 4, 6 | this file |
| 10, 10a | 2, 5, 7; the line ends and the indent 10 | this file; the line ends and the indent `s7dcl-import.md` |
| 2 to 9, 16, 16a, 17a | 8.2 to 8.13; 8.4, with the shapes tried in 8.13b and 8.14c | `s7dcl-lad.md` |
| 13 to 15 | 8.14b, 8.14c | `s7dcl-resources.md` |
| 17, 18 | 10 | `s7dcl-import.md` |
| 19 | 3, 4, 6; a non-optimized DB 8.14b | this file; a non-optimized DB `s7dcl-data.md` |

1. Every network has exactly one `{ S7_Language := "..." }` pragma directly before `NETWORK`, value one of STL/LAD/FBD/SCL.
2. Every LAD rung starts with a wire operand (`RUNG wire#powerrail` or another wire) and, if compileable code is required, ends with a coil, box, jump, or return — never with a contact.
3. Box parameters: complete (every parameter listed), one per line, `:=` for in/in-out, `=>` for out, empty value for unconnected pins.
4. Operand-role parameters written inline without name; instance-role written as `instance.Instruction(...)`.
5. At most one jump or return coil per network; it is the last instruction of its rung. `JumpList`/`Switch` likewise terminate their rung.
6. `Label( name )` only as the first line after `NETWORK`; one per network; the label exists as a network label somewhere in the block.
7. Wire names `wire#`-prefixed, unique meaning per network only; no crossing wires, no feedback loops — split into networks instead.
8. `S7_Templates` / `S7_GenerateENO` / `S7_Expression` / `CASE<n>` pragmas sit immediately before the instruction they modify.
9. Timers, counters, flip-flops, FB calls have an instance; a bare FB block name imports but will not compile.
10. Local variables carry `#`; constants and literals use IEC syntax; identifiers restricted to the allowed Unicode set; file saved UTF-8 (+BOM preferred), with CRLF line ends (section 10; the TiaBridge import writes them).
10a. Keep your own indent at 8 or deeper. A body that has already gone deeper stays there (24 stays 24): take the surplus off by hand once, in the file, with the lines still at 8 or deeper (10, Line ends decide the indent of an SCL body).
11. No AT constructs, no USTRING/UCHAR, no OOP features.
12. Interface prefixes and naming per the project's own guidelines where it owns the code — the format itself does not enforce naming.
13. `.s7res` parses as YAML; MLC references in the `.s7dcl` and entries in the `.s7res` are equal as sets and in count (8.14b).
14. No MLC id occurs twice, in either file (8.14c). Run this on TIA exports too, not only on generated files.
15. Every `.s7res` entry has a language key with text, and no key of a language the project does not have (8.14c, where the list of languages is an assumption). Drop the reference and the entry for an empty comment (8.14c).
16. No LAD branch starts at a merge node and encloses a nested OR that ends at the same node, and none ends at a node inside a sibling branch from the same merge node (8.14c).
16a. In every LAD network, every rung that ends at a node comes before every rung that starts at that node (8.4; 8.14c says which shapes were tried). A new branch goes after the rungs that hold its start and its end node inside them, where TIA's export puts it (8.13b, 8.14c; tried for one shape), and after every rung that ends at its start node, and before every rung that starts at its end node. Where no place fits, move existing rungs until the order holds at every node.
17a. No LAD operand with a multi-dimensional array index (`a[i, j, k]`) in a network that goes through an SD import (8.14c): such a block goes through SimaticML (`format: xml`), or is edited in TIA.
17. Every block, UDT and tag a call references exists in the project in the form the call expects. A call to an FB whose new interface has not been imported yet fails the caller's import (10).
18. Every block attribute the export left out is written as FALSE before the import: `S7_GenerateENOforSCL := "FALSE";`, `S7_IECCheck := "FALSE";`. An import without them sets them TRUE (10, block attributes set by an import).
19. Language attribute: `S7_EditorMode := "SCL"` only on a block with one SCL network; any other block `S7_PreferredLanguage := "LAD"`, never `"SCL"` (3, 6). No `:= value` on a `DATA_BLOCK` declaration: start values after `END_VAR` (4). A non-optimized DB: `S7_StandardRetain := "TRUE"` with only `VAR RETAIN`, `"FALSE"` with only `VAR` (8.14b).
20. One object per document, as an export writes it, and the kind that fits it (3). `import` and `library_create_type` refuse a document declaring a second object, also a second type listed in one `TYPE`, a head whose object they cannot read (keep to comments and one pragma block in front of the keyword), and as a library type a DB, OB, tag table, watch table, force table, technology object or HMI document. `import` also refuses a DB under kind `block`, an FB, FC or OB under `db`, a data type under either, a block or DB under `type`, a block, DB or data type under `plc_tag_table`, `watch_table` or `force_table`, a tag table, watch table, force table, technology object or HMI document under `block`, `db` or `type`, a watch table, force table, technology object or HMI document under `plc_tag_table`, a tag table, force table, technology object or HMI document under `watch_table`, a tag table, watch table, technology object or HMI document under `force_table`, any other document under `technology_object`, and a new object of a name another of `block`, `db` and `technology_object` holds: those kinds list their own objects only, so the guards would not see the object. TIA itself refuses two FCs in one document (*The import failed. The source file contains multiple object definitions.*), but it takes a `TYPE` listing two data types and makes the first only, with no message: the second is gone `[PROBE]`. Keywords are case-insensitive (2), and the bridge reads them so: a document with a keyword in another case meets the guards under the name it declares.

## 12. Gaps — blocked without a reference export `[GAP]`

The following cannot be specified from available documentation. Generating them from imagination will produce import failures or silent corruption; obtain one reference export per item from a TIA Portal V20 Upd4+/V21 workspace and use it as the template.

| # | Item | Status |
|---|---|---|
| 1 | Header keywords + attribute grammar for FC, OB, DB, UDT | All seen `[EXPORT]` (section 3, 8.14b). OB files are not edited: the event class is not in the file |
| 2 | Block attribute block content | FB, DB and UDT seen `[EXPORT]` (8.14b) |
| 3 | DB bodies: start values, instance DB representation | Covered `[EXPORT]` with imports (8.14b): global DB start values (struct, array, UDT members, any depth), comments of inner members (`:= ();`), instance DB (empty body, also with multi-instances and retain members in the FB; with start values, also of multi-instance members), DB of a UDT (with start values and comments), `VAR RETAIN` in a global DB and an FB, `DB_SPECIFIC` sections, `S7_StandardRetain` (instance DB, DB of a UDT, non-optimized and optimized global DB) |
| 4 | UDT / Named value data type declaration syntax | UDT seen `[EXPORT]`; Named value type still blocked |
| 5 | Per-member interface attributes | `S7_Access`, `S7_Visibility`, `S7_Setpoint`, `S7_MLC` seen `[EXPORT]`; retain is a `VAR RETAIN` section and applies to a whole DB member (a member of a UDT cannot be retained on its own); the encoding of "not accessible at all" is still unseen |
| 6 | FBD textual format (a separate format description exists per the LAD document's cross references; not available here) | Blocked |
| 7 | STL network content format | Blocked for `.s7dcl`; a SimaticML export writes a `StatementList` of `StlStatement`s |
| 8 | `.s7res` schema | Seen `[EXPORT]` (8.14b), hand-written ids re-imported |
| 9 | Full inherent instruction list with parameter names | Basic, extended, Communication, Technology, Optional packages and F-LAD instructions seen `[EXPORT]`, all but those a CPU 1515F does not offer or take (8.13a has those whose names differ and how the library and F instructions go in) |
| 10 | GRAPH | Not supported as an `S7_Language` value at all |
| 11 | Timer/counter instance data types in the interface | `IEC_TIMER` seen `[EXPORT]`; counters still blocked |

## 13. Recommended agent workflow

1. Decide the target object. FB/FC with SCL and/or LAD networks, UDT, global DB: proceed with this guide, starting from an existing export of the same kind. OB: edit in TIA only (section 11). Anything still open in section 12: request a template export first.
2. Write the interface using IEC sections (section 4) and project naming conventions; keep every declaration also present wherever the body references it (case-insensitive match).
3. Write the body network by network; each network gets its language pragma. Prefer SCL networks for arithmetic/sequencing, LAD networks for Boolean interlocks — mixing is free.
4. Run the section 9 checklist mechanically.
5. Round-trip: import into a TIA workspace, compile, re-export, and diff the re-export against the generated file. Differences reveal formatting the exporter normalizes (semicolons, indentation, pragma spacing) — adopt the exporter's form as the canonical style from then on.
6. Keep `.s7dcl`/`.s7res` pairs together in version control. Hand edits to a `.s7res` are fine when they follow 8.14b/8.14c: YAML, one entry with text per reference, no duplicate ids, no key of a language the project does not have.
7. A new library type goes the same way, through `library_create_type` instead of `import`: the `.s7dcl` (with its `.s7res`) alone is enough, in a folder of its own, `library\types\<folder>\<name>\` where export will write it. A `.libinfo` beside it sets the first version; do not copy one from another type, its `Guid` is refused (openness-v20.md section 3). `[PROBE]`

---

Source documents: Siemens Entry ID 109994073 "SIMATIC Source Documents - LADDER Format Description" V1.0 2025-09; SIMATIC TIA Portal V20 Update 4/5 readmes (A5E54260417).
