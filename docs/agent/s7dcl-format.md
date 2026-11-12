---
type: Guide
title: SIMATIC SD (.s7dcl) authoring guide
description: How to write SIMATIC SD (.s7dcl) PLC blocks for TIA Portal V20 and V21 that import cleanly, with every statement tagged by its source.
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-12T18:35:00-05:00 }
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

## 8. LAD networks (fully specified) `[LAD-DOC §3, §4]`

This is the area the source document specifies completely. Everything in this section is `[LAD-DOC]` unless marked otherwise.

### 8.1 Data model

- A LAD network is a **graph**: parts (instruction uses) connected by wires.
- **Gate = instruction** (inherent library, ~230 instructions, or a code block call). A **part** is a gate used in a network.
- A **pin** is the graphical form of an instruction parameter. Pins carry roles that control the textual form:
  - `rung-in` / `rung-out` (Bool): never listed in text; expressed by instruction order inside a rung.
  - `operand` (text role): written inline without parameter name, e.g. `Contact( motorStart )`.
  - `instance` (text role): written as `instanceName.Instruction( ... )` (timers, counters, flip-flop memory bit, FB calls).
  - `top` / `bottom` (graphical roles): no influence on the text.
- A **wire** is a set of pins. All connected output pins are OR-ed; all connected input pins read the result.
- A **rung** is an ordered list of instructions and wires. Order = data flow. A LAD network is a list of rungs.
- Data flow is left to right; local variables use the `#` prefix (e.g. `Contact( #isEnabled )`, `Move( in := #inValue, out => #statValue )`), plain names address global tags.

### 8.2 Line grammar (complete)

Every line of a LAD network matches one of these shapes:

```
NETWORK                                     begin of a network
END_NETWORK                                 end of a network
RUNG wire#name                              begin of a rung (operand = starting wire)
END_RUNG wire#name                          end of a rung (trailing wire optional)
wire#name                                   wire node inside a rung
Instruction()                               instruction, no remaining parameter
Instruction( value )                        instruction, exactly one remaining parameter
Instruction(                                instruction, several parameters:
    paramname := value,                       input / in-out parameter
    paramname => value,                       output parameter
)                                             end of parameter list
{ Pragmaname }                              single pragma without value
{ Pragmaname := pragmavalue }               single pragma with value
{                                           pragma list:
    Pragmaname;
    Pragmaname := pragmavalue;
}
```

Pragma values can be: `true` / `false`, integer, `"symbol"`, `"[ symbol, ... ]"`, `"name := value"`, `"[ name := value, ... ]"`, `"name := [ value, ... ]"`.

One instruction per line, one parameter per line — this is deliberate, for clean version-control diffs.

### 8.3 Wires

- Wire identifiers are prefixed `wire#`; the scope is **local to one network**. Every network may reuse `wire#w1` as a different wire.
- `wire#powerrail` is predefined and always TRUE. All well-formed rungs start at it (directly or via another wire). `wire#leftrail` and `wire#rightrail` are accepted but unused by STEP 7.
- The STEP 7 editor auto-names new wires `wire#w<N>`, but any legal identifier is kept over round-trips.
- STEP 7 does not support crossing wires or feedback by wiring (the textual format itself would allow both). Split logic into several networks instead.

### 8.4 Rungs and parallel logic

Series contacts = AND:

```
{ S7_Language := "LAD" }
NETWORK
    RUNG wire#powerrail
        Contact( #isEnabledA )
        Contact( #isEnabledB )
        Coil( #oResult )
    END_RUNG
END_NETWORK
```

Parallel branches = additional rungs that start at the power rail and end in the shared wire:

```
NETWORK
    RUNG wire#powerrail
        Contact( #isStartRequested )
        wire#w1
        I_Contact( #isStopRequested )
        Coil( #statRunLatch )
    END_RUNG
    RUNG wire#powerrail
        Contact( #statRunLatch )
    END_RUNG wire#w1
END_NETWORK
```

Here `wire#w1` ORs the rung-outs of the start contact and the latch contact (a standard seal-in). Semantics: `statRunLatch := (isStartRequested OR statRunLatch) AND NOT isStopRequested`.

The order of the rungs matters too: a rung that ends at a node goes before every rung that starts at that node, and a branch goes after the rungs that hold its start and its end node. TIA refuses the network otherwise: 8.14c says which shapes were tried `[PROBE]`; the rest is `[INFERRED]`. The seal-in above is fine: no rung starts at `wire#w1`.

Order inside a rung matters. An instruction placed after the final coil is dead logic; the STEP 7 compiler rejects such a network ("rung should end with a coil or box").

### 8.5 Parameter listing rules

- Rung-in/rung-out pins are never written.
- Inputs and in-outs use `:=`, outputs use `=>`.
- For boxes, **all parameters must be listed**; a missing parameter line fails the import. Unconnected parameters are written empty:

```
Add(
    in1 := #inValueA,
    in2 := 4,
    in3 := ,
    in4 := #inValueB,
    out => #tempSum
)
```

- Most boxes number their inputs from 1 (the select box starts at 0).
- Whether referenced symbols exist does not matter for the import (unresolved names produce red boxes, see section 10).

### 8.6 Pragmas used inside LAD networks

| Pragma | Purpose |
|---|---|
| `{ S7_Templates := "name := value" }` | Specializes the following instruction (data type selection). List form: `"[ inType := Int, outType := Real ]"`. Only exported when the value differs from the default; automatic type selection (`Auto`) is never exported. |
| `{ S7_GenerateENO := TRUE }` | The following box computes a real ENO. Default for some math instructions is off (ENO := EN), in which case no pragma appears. |
| `{ S7_Expression := "..." }` | Stores the expression of a `Calculate` box, using the formal names; the export writes them `IN1`, `IN2`, ... (8.14) |
| `{ CASE0 := "==" }` | The relation of a `Switch` case, one per case, beside its `S7_Templates` (8.13) `[EXPORT]` |

Combined pragma list (semicolon-separated), placed immediately before the instruction it affects:

```
{
    S7_Templates := "SrcType := SInt";
    S7_GenerateENO := TRUE
}
Add(
    in1 := #ioSpeed,
    in2 := 42,
    out => #tempSpeed
)
```

### 8.7 Contacts

A contact is a Boolean AND of its rung-in and its operand. There are no AND/OR boxes in LAD; series = AND, parallel = OR.

| Textual form | Meaning |
|---|---|
| `Contact( op )` | Normally open: `out := in AND operand` |
| `I_Contact( op )` | Normally closed: `out := in AND NOT operand` |
| `P_Contact( operand := x, bit := mem )` | Rising edge; `bit` is the edge-memory in-out |
| `N_Contact( operand := x, bit := mem )` | Falling edge |
| `OK( x )` / `NOK( x )` | Float validity test (NaN/Inf); TIA writes `OK`, `NOT_OK` in the contact `[EXPORT]` |
| `IS_ARRAY( x )` | Variant array test `[EXPORT]` |
| `IS_NULL( x )` / `NOT_NULL( x )` | Reference null test `[EXPORT]` |

The LADDER Format Description's `IsValidContact`, `IsNotValidContact`, `IsArrayContact`, `IsNotArrayContact`, `IsNullContact`, `IsNotNullContact` are not what TIA exports, and it has no export of a negated array test; whether TIA imports them is untested. Write the exported form.

Compare contacts (relations EQ, NE, LT, GT, LE, GE) take two operands and a data-type template:

```
{ S7_Templates := "[ SrcType := DInt ]" }
GE_Contact(
    in1 := #statCounter,
    in2 := #MAX_COUNT
)
```

Type-test contacts without template, with `in1 :=` and `in2 :=`: `EQ_TypeContact`, `NE_TypeContact`, `EQ_ElemTypeContact`, `NE_ElemTypeContact`, `EQ_TypeOfDBContact`, `NE_TypeOfDBContact`; TIA writes `EQ_Type`, `NE_Type`, ... in the contact. `EQ_TypeOfDBContact( in1 := #x, in2 := IEC_TIMER )` imports, and then the compile refuses it: *Syntax error: The specified value "IEC_TIMER" is invalid.* and *Data type ??? is not permitted here.* The same networks imported as SimaticML compile with 0 errors, though TIA marks them with a red cross. `[EXPORT]`

Legacy status-word flag contacts (`BR_FlagContact()` etc.) exist only for AS300/AS400 targets — irrelevant for S7-1200/1500 work.

### 8.8 Coils

For all coils, the rung-in is copied to the rung-out (a coil does not break the rung).

| Textual form | Meaning |
|---|---|
| `Coil( op )` | `operand := in` |
| `I_Coil( op )` | `operand := NOT in` (rung-out stays = in) |
| `S_Coil( op )` | Set if in |
| `R_Coil( op )` | Reset if in |
| `P_Coil( operand => x, bit := mem )` | Rising-edge one-shot coil `[EXPORT]` |
| `N_Coil( operand => x, bit := mem )` | Falling-edge one-shot coil `[EXPORT]` |

Additional one-operand coils: `CU_Coil( counter )`, `CD_Coil( counter )`, `RT_Coil( timer )`, `JumpCoil( label )`, `I_JumpCoil( label )`, `ReturnCoil( operand )`, `CallCoil( operand )`, `OpenDBCoil` / `OpenDICoil` (AS300/400 only).

Two-operand coils (timer/counter control): `TP_Coil`, `TON_Coil`, `TOF_Coil`, `TONR_Coil`, `SP_Coil`, `SE_Coil`, `SD_Coil`, `SS_Coil`, `SF_Coil` (all `timer =>`, `pt :=`), `PT_Coil( timer =>, PT := )`, `SC_Coil( counter =>, pv := )`, `R_BitfieldCoil( operand =>, n := )`, `S_BitfieldCoil( operand =>, n := )`. `[EXPORT]`

A timer in a global DB is written with both parameters, as above. A timer of the interface has the instance role, so the coil is written on the instance with only the remaining parameter inline:

```
#instPulse.TP_Coil( t#5s )
```

No-operand coils (AS300/400 only): `McrOpenCoil`, `McrCloseCoil`, `McrActivateCoil`, `McrDeactivateCoil`, `SaveCoil`.

### 8.9 Negation

LAD has exactly three negation instructions: `I_Contact` (negates the operand), `I_Coil` (negates the assigned value), and the standalone `Not()` which inverts the rung: `out := NOT in`.

### 8.10 ENO boxes and math

- `EN`/`ENO` are the rung pins of ENO boxes and are never written in text.
- If EN is false, the box is not executed and connected outputs are untouched; ENO goes false.
- ENO generation is off by default for some math instructions (ENO := EN); switch it on with `{ S7_GenerateENO := TRUE }` (see 8.6).
- The overflow-guard idiom (Add into a temp, Move copies only on ENO true) is expressed as two consecutive boxes in one rung.
- Implicit data-type conversions inserted by the compiler have **no** textual representation.
- Auto data type: never exported; a selected data type appears as an `S7_Templates` pragma.

### 8.11 Calls (FC and FB)

- FC call: `BlockName( param lines )` or `BlockName()`. The called block's ENO drives the rung-out.
- FB call: the **instance name** replaces the block name:

```
InstConveyor(
    in1 := #inValueA,
    io1 := #ioState,
    out1 => #tempResult
)
```

- If no instance is assigned (incomplete program), the FB's block name is written instead; such a file imports but does not compile.
- ENO handling cannot be switched off for calls.

### 8.12 Q-boxes: flip-flops, timers, counters

Q-boxes have no EN/ENO; their Boolean `q` output is the rung-out.

**Flip-flops** (Simatic S_RS / S_SR; the second input is dominant). The storing operand has the instance role; the first input is the rung-in; the remaining second input is written inline (variable or wire):

```
NETWORK
    RUNG wire#powerrail
        Contact( #isResetRequested )
        #statMemory.S_RS( wire#w1 )
        Coil( #oIndicator )
    END_RUNG
    RUNG wire#powerrail
        Contact( #isSetRequested )
    END_RUNG wire#w1
END_NETWORK
```

The IEC-norm SR/RS boxes are explicitly NOT supported by STEP 7.

**IEC timers** (TP, TON, TOF, TONR; resolution via template `time_type := Time` or `LTime`). The timer parameter has the instance role; rung-in `in`, rung-out `q`:

```
{ S7_Templates := "time_type := Time" }
#instStartDelay.TP(
    pt := T#10s,
    et => #tempElapsed
)
```

An accumulating timer (TONR-style relic) exists on S7-1200/1500 and is reset with `RT_Coil`. The other pins of `TONR`: `r :=`, `pt :=`, `et =>`.

**S5 timers** `[EXPORT]`: `Sp` (TIA's `S_PULSE`), `Se` (`S_PEXT`), `Sd` (`S_ODT`), `Ss` (`S_ODTS`), `Sf` (`S_OFFDT`); started alternatively via the SP/SE/SD/SS/SF coils. The rung runs in at S and out at Q. The names of the pins are not the ones TIA shows: `Top` is the timer TIA draws above the box, `RT` is `BI`, `RTBCD` is `BCD`:

```
Sp(
    Top := "Data".timer,
    TV := "Data".time,
    R := "Data".reset,
    RT => "Data".value,
    RTBCD => "Data".valueBcd
)
```

On an absolute address (`Top := %T1`) this imports, and then the compile refuses it: *A constant not permitted here.* A symbol was not tried. The SimaticML part has the same name, its pins `s`, `tv`, `r`, `rt`, `rtbcd`, `timer`, `q`.

**IEC counters** (template `value_type := <integer type>`) `[EXPORT]`; rung-in `cu` (CTU, CTUD) or `cd` (CTD, with `ld :=`, `pv :=`, `cv =>`); rung-out `q` (`qu` for CTUD); no coils exist for IEC counters:

```
{ S7_Templates := "value_type := DInt" }
#instCounter.CTU(
    r := #isResetRequested,
    pv := #PRESET_COUNT,
    cv => #statCurrentCount
)
```

```
{ S7_Templates := "value_type := DInt" }
#instUpDown.CTUD(
    cd := #isCountDown,
    r := #isResetRequested,
    ld := #isLoadRequested,
    pv := #PRESET_COUNT,
    qd => ,
    cv => #statCurrentCount
)
```

S5 counters `Cu` (TIA's `S_CU`), `Cd` (`S_CD`), `Cud` (`S_CUD`) `[EXPORT]`: the rung runs in at the count input and out at Q; `Top :=` is the counter TIA draws above the box, then `S :=`, `PV :=`, `R :=`, `CV =>`, `CVBCD =>` (TIA's `CV_BCD`), with `Cud` first `CD :=`. On `%C1` the compile refuses them as the timers. They use BCD presets (`C#0..C#999`); their `q` is `cv > 0`, so they are not interchangeable with IEC counters. Coils `CU_Coil`/`CD_Coil`/`SC_Coil` mirror the box inputs.

### 8.13 Program control: labels, jumps, returns, JumpList, Switch

- **Label**: `Label( name )` on the line **directly after** `NETWORK`, nowhere else. One label per network. Labels have their own scope (no `label#` prefix needed).
- **Jump coils**: `JumpCoil( label )` (jump if rung-in true), `I_JumpCoil( label )` (jump if false). Jumps target networks, never instructions.
- **Return coils**: `ReturnCoil( x )` (ENO := x), `ReturnFalse()`, `ReturnTrue()`, `Return()` (ENO := rung-in). Without any return coil the compiler generates an implicit `return true` at block end.
- Jump and return coils have no rung-out and therefore must be the **last instruction of their rung**.
- **Only one jump OR return coil per network.** Split state machines into small networks accordingly. Networks are evaluated top to bottom.
- **JumpList** (calculated jump; EN but no ENO; k beyond the last destination falls through to the next network). As the V20 Update 7 export writes it (FB, 2026-10-30) `[EXPORT]`: the destinations are `dst0`, `dst1`, ..., the labels without prefix:

```
NETWORK
    RUNG wire#powerrail
        JumpList(
            k := #statStepIndex,
            dst0 => stepIdle,
            dst1 => stepRun
        )
    END_RUNG
END_NETWORK
```

- **Switch** (first true relation wins; the fallback is `else`). Same export `[EXPORT]`: the data type and the relation of every case are pragmas in front of the box, the relation as the symbol TIA shows (`CASE0 := "=="`); the parameters are `k`, the compared values `case0`, `case1`, ..., then `else`, then the destinations `dst0`, `dst1`, ...:

```
NETWORK
    RUNG wire#powerrail
        {
            S7_Templates := "SrcType := USInt";
            CASE0 := "==";
            CASE1 := "=="
        }
        Switch(
            k := #statStepIndex,
            case0 := #STEP_IDLE,
            case1 := #STEP_RUN,
            else => stepFault,
            dst0 => stepIdle,
            dst1 => stepRun
        )
    END_RUNG
END_NETWORK
```

**The export ends this pragma block with `;` before `}`, and TIA refuses its own export:** *Syntax Error during import of TextLad file, Message: "no viable alternative at input ...* Without that last `;` it imports, so take it out of a reference export `[EXPORT]`. The symbols of the other relations (`<>`, `<`, `>`, `<=`, `>=`, as TIA shows them) are not yet seen in an export `[INFERRED]`. The LADDER Format Description's forms (`dest0 => ...`; case lines `EQ #v => label`, no template pragma) are not what TIA exports; whether TIA imports them is untested. Write the exported form.

SimaticML export of the same networks in an OB `[EXPORT]`: the Switch part carries `<TemplateValue Name="SrcType" Type="Type">USInt</TemplateValue>` and per case `<TemplateValue Name="CASE0" Type="Operation">EQ</TemplateValue>`, the count as `Card`; its pins are `en`, `k`, `case0..n`, `dest0..n` (not `dst`), `else`. The JumpList part (`JmpList`, `Card` only) has `en`, `k`, `dest0..n`. A destination is a wire to an access `Scope="Label"` holding `<Label Name="..."/>`; the target network declares it in `<Labels><LabelDeclaration>`, where the SD export writes `Label(name)` (no blanks) on the line after `NETWORK`. Neither part has an `eno` pin: TIA draws both boxes with EN and no ENO, `DEST0` on the EN row, `ELSE` after the last destination, each case input with its relation (`==`) in place of a pin name.

### 8.13a Where the names differ `[EXPORT]`

One network per instruction through TIA V20 Update 7 on a CPU 1515F, both export formats against TIA's screen. The instructions below go by another name in the `.s7dcl`, in the SimaticML part or on the screen; the others keep one name, on the screen in capitals, but for the titles in mixed case below.

| TIA's screen | `.s7dcl` | SimaticML part | Pins: screen = `.s7dcl` |
|---|---|---|---|
| `CONV` | `Convert` | `Convert` | |
| `SCALE_X` | `Scale` | `Scale_X` | |
| `NORM_X` | `Normalize` | `Normalize` | |
| `ROR`, `ROL` | `Ror`, `Rol` | `Rr`, `Rl` | |
| `MOVE_BLK`, `UMOVE_BLK` | `MoveBlockI`, `MoveBlockU` | the same | |
| `FILL_BLK`, `UFILL_BLK` | `FillBlockI`, `FillBlockU` | the same | |
| `?=` | `AssignAttempt` | `?=` | |
| `MOVE_BLK_VARIANT` | `MoveBlockVariant` | `MOVE_BLK_VARIANT` | `SRC_INDEX` = `srcIndex`, `DEST_INDEX` = `dstIndex`, `DEST` = `dst` |
| `SCATTER_BLK` | `ScatterBlock` | `SCATTER_BLK` | `COUNT_IN` = `countIn` |
| `GATHER_BLK` | `GatherBlock` | `GATHER_BLK` | `COUNT_OUT` = `countOut` |
| `Deserialize` | `Deserialize` | `Deserialize` | `SRC_ARRAY` = `srcArray`, `DEST_VARIABLE` = `dstVariable` |
| `Serialize` | `Serialize` | `Serialize` | `SRC_VARIABLE` = `srcVariable`, `DEST_ARRAY` = `dstArray` |
| `BLKMOV` | `S_BlockMove` | `BLKMOV` | `SRCBLK` = `srcBlock`, `DSTBLK` = `dstBlock` |
| `UBLKMOV` | `SU_BlockMove` | `UBLKMOV` | as `BLKMOV` |
| `FILL` | `S_Fill` | `FILL` | |
| `SCALE` | `S_Scale` | `SCALE` | `HI_LIM` = `hiLim`, `LO_LIM` = `loLim` |
| `UNSCALE` | `S_Normalize` | `UNSCALE` | as `SCALE` |
| `LIMIT` | `Limit` | `LIMIT` | `MN` = `min`, `MX` = `max` |
| `IN_RANGE`, `OUT_RANGE` | `InRange`, `OutRange` | the same | `VAL` = `in` |
| `GET_ERROR` | `GetError` | `GetError` | |
| `GET_ERR_ID` | `GetErrorID` | `GetErrorID` | `ID` = `error` |
| `RUNTIME` | `Runtime` | `Runtime` | |
| `INC`, `DEC` | `Inc( x )`, `Dec( x )` | `Inc`, `Dec` | `IN/OUT` is unnamed, SimaticML `operand` |
| timer coils | `TP_Coil`, `TON_Coil`, `TOF_Coil`, `TONR_Coil` | `CoilTP`, `CoilTON`, `CoilTOF`, `CoilTONR` | SimaticML `operand`, `value` = `timer`, `pt` |
| S5 coils | `SP_Coil`, `SE_Coil`, `SD_Coil`, `SS_Coil`, `SF_Coil` | `SpCoil`, `SeCoil`, `SdCoil`, `SsCoil`, `SfCoil` | as the timer coils |
| `--(JMP)`, `--(JMPN)`, `--(RET)` | `JumpCoil`, `I_JumpCoil`, `ReturnCoil` | `Jump`, `JumpNot`, `ReturnValue` | |
| type tests | `EQ_TypeContact`, ... | `EQ_Type`, ... | |
| `STRG_VAL`, `VAL_STRG` | `StringToValue`, `ValueToString` | `STRG_VAL`, `VAL_STRG` | |
| `MAX_LEN` | `MaxLen` | `MAX_LEN` | `IN`, `OUT` on the help's picture; both exports `in`, `out` |
| `JOIN`, `SPLIT` | `Join`, `Split` | `JOIN`, `SPLIT` | |
| `ATH`, `HTA` | `AsciiToHex`, `HexToAscii` | `ATH`, `HTA` | |

Extended instructions, `.s7dcl`: it writes `in1`, `out`, `ret_val` in lower case where SimaticML and TIA have `IN1`, `OUT`, `Ret_Val`: take the case from a SimaticML export. On their type line TIA writes the type alone (`LEN`, `CONCAT`, `RD_SYS_T`, ... from `str_type`, `date_type`), two types with a word (`T_CONV`, `S_CONV`, `STRG_VAL`, `VAL_STRG`, `T_DIFF`, `T_COMBINE` `TO`; `T_ADD` `PLUS`; `T_SUB` `MINUS`), or the type over a relation (`T_COMP`, `S_COMP`: `{ S7_Templates := "date_type := Date"; S7_Relation := "EQ" }`, SimaticML `<TemplateValue Name="relation" Type="Operation">EQ</TemplateValue>`). `S_MOVE`: `String to String`, with a small `to`; real exports also write it `S_Move`, without a template. `READ_DBL`, `WRIT_DBL`: TIA writes `Variant`, the `.s7dcl` has no template. A type line is a fact per box, no rule from the templates: with the same templates `RD_REC`, `RD_DPAR`, `RD_DPARA`, `RDREC`, `WRREC` have `Variant`, `WR_REC`, `DPRD_DAT`, `DPWR_DAT`, `DPNRM_DG`, `GETIO`, `SETIO` none; `UPDAT_PI`, `UPDAT_PO` hold a template and draw no line. An in-out is in no export: both write it as an input (`RECORD` of `RDREC`, `Activate`, `VALID`, `DATA_ERRORRSP` of the `PE_..._RSP`); the help's table is right on most, but it marks `P` of `STRG_VAL`, `VAL_STRG`, which TIA's screen does not. SCL names: `T_CONV` is `TIME_TO_DINT`, `T_COMBINE` is `CONCAT_DATE_TOD`, `S_CONV` is `STRING_TO_INT`; the bare names are refused: *Tag 'T_CONV' is not declared.*

The help's parameter tables against the exports: `JOIN` `DstArray`, `SPLIT` `DstStruct` (help `DestArray`, `DestStruct`); `PE_CMD` `CMD_DSID_RQ` (help `CMD_DATA_STRUCTURE_IDENTIFIER_RQ`); `PE_DS3_Write_ET200S` `Slot_No_1` to `8`, `Func_1` to `8` (help `SLOT_NO_X`, `FUNC_X`). `DPSYC_FR`: its `LADDR` template takes `HW_DPMASTER`, not the `HW_INTERFACE` of the help.

Mixed case on the screen: the titles `Deserialize`, `Serialize`, `ReadFromArrayDB`, `WriteToArrayDB`, `ReadFromArrayDBL`, `WriteToArrayDBL`, `VariantGet`, `VariantPut`, `CountOfElements`, `FieldRead`, `FieldWrite`; `Ret_Val` on `BITSUM`, `INIT_RD`, `RUNTIME`, `ENDIS_PW`, `Deserialize`, `Serialize`, `MOVE_BLK_VARIANT`, `ReadFromArrayDB`, `WriteToArrayDB`; `RET_VAL` on `SCALE`, `UNSCALE`, `BLKMOV`, `UBLKMOV`, `FILL`, `CountOfElements`; `db`, `index`, `value`, `req`, `busy`, `done`, `error` on the array DB boxes. The two-way arrow of an in-out: `IN/OUT` of `INC`, `DEC`, `POS` of `Serialize`, `Deserialize`, `MEM` of `RUNTIME`, `value` of `ReadFromArrayDBL`.

**The help is not TIA's screen:** it writes capitals where the screen does not (`RET_VAL` everywhere, the array DB pins, `TIME` for `Time`), and it draws `DRUM` with one row for its 16 `EVENT` and 16 `OUT` pins. Where they differ, take the names from an export.

**Library instructions go in as `.s7dcl` calls** `[EXPORT]`**:** PtP, USS, Modbus RTU and ET 200S (`Port_Config`, `USS_Port_Scan`, `Modbus_Master`, `S_RCV`, ...) and all 75 boxes of Technology and the Optional packages: an instance `inst : PID_Compact;`, without quotes, and `#inst( ... )`. They export as a `<Call>` of a block with a number. TIA draws them as one, the title in quotes and `%FB610` above it, in the case of the export's `CallInfo`: `"MC_POWER"`, where the palette and the help have `MC_Power`. A SimaticML `<Part>` of them was refused, or its templates could only be guessed; the same instruction as a part is plain on the screen (`Signal_Get`), so the form decides the look. A library FC (`USS_Read_Param`, `S_USST`) stays a part: `USS_Read_Param( ... )`.

**In-out pins** `[EXPORT]`**:** the instance member of a box holds them in SimaticML: `<Member Name="instRead" Datatype="Read"><Sections>` with `Input`, `Output`, `InOut`. They agree with TIA's two-way arrows wherever a screen shows the pin; `.s7dcl` has only `instRead : Read;` and `:=`. The help does not always: on TIA's screen `OPC_UA_Connect` has no in-out (help `ServerEndpointUrl`, `SessionConnectInfo`), `OPC_UA_NodeGetHandleList` only `NodeStatusList`, `NodeHdls` (help also `NodeIDs`, `NamespaceIndexes`). Take them from an export. An FC has no instance, so no sections and no fact in an export: `USS_DB` of `USS_Read_Param`, `USS_Write_Param`, `USS_Read_Param_31`, `USS_Write_Param_31` is an in-out on the screen.

**A type line is on the screen or it is not** `[EXPORT]`**:** `TRCV`, `TUSEND`, `TURCV` draw none, though their SimaticML has `value_type` UDInt; `USS_Read_Param`, `USS_Write_Param` none with their four templates; `WWW` none with `value_type`; `SYNC_PI`, `SYNC_PO` none, like `UPDAT_PI`, `UPDAT_PO`, though SimaticML has `PIP`. `USEND`, `URCV`, `BSEND`, `BRCV` draw `Variant` from `ptr_type`, of their three templates; their `.s7dcl` holds none.

**Technology instructions compile without a technology object** `[EXPORT]`**:** a pin of type `TO_Axis`, `TO_SpeedAxis`, `TO_PositioningAxis`, `TO_SynchronousAxis`, `TO_MeasuringInput`, `TO_OutputCam`, `TO_CamTrack`, `TO_IDENT`, `TO_TAGLAYOUT` wired to an in-out parameter of the FB of that type (`#ioTO_Axis`). A compile says nothing about hardware or connections: no row was refused for a missing CM, CP or axis. `TO_BasicPos` written as a type becomes `BasicPosControl` in both exports.

**`GET`, `PUT`** `[EXPORT]` go in as LAD as a SimaticML `<Part Name="GET" Version="1.3">` with the templates `remote_type` REMOTE, `local_type` Variant and all four areas wired (`ADDR_1` to `4`, `RD_1` to `4` or `SD_1` to `4`); a pointer constant `P#DB1.DBX0.0 BYTE 1` as a `LiteralConstant` compiles, so does an in-out parameter of the FB of type `Remote`; a DB member of that type does not (*Data type Remote is not allowed here.*). As `.s7dcl` too, as the export writes it: `#instGET.GET(...)` with the four areas, TIA's own taken back imports and compiles with 0 errors. With fewer: *Instruction 'GET' : Pin 'ADDR_2' connection is missing.* `#inst(...)` without `.GET` reads as a call with the wrong formal types. On TIA's screen the type line is `Remote - Variant`, `ADDR_1` to `4` and the data areas in-out.

**Boxes TIA allows as a single instance only** `[EXPORT]`**:** `SSI_Absolute_Encoder`, `DQ4_CAM`: *The data type 'DQ4_CAM' is not supported as a multiple instance.* The DB as `.s7dcl`, `DATA_BLOCK zzDb : DQ4_CAM` with an empty body, needs the block in the project (*Dependent object ... not found*): importing a block that declares it, no compile, brings it; that block can then be deleted. The call is `"zzDb"( ... )`. TIA draws such a call with the DB above the box and the block in the head, `%DB10`, `"zzDb"`, `%FB1151`, `"DQ4_CAM"`. TiaBridge refuses an import over such a DB: it reads as know-how protected.

**Pins no list holds** `[EXPORT]`**:** a call with no operands compiles on many boxes, and TIA's SimaticML of the block then holds the instance's sections: that is where to read the pins from. Not on every box: an in-out of a system type may have to be wired, or the compile answers *The operand required at the input or output is missing or has an incorrect data type.* The list's names can be wrong: `Advanced_CMD` is `AdvancedCmd`; `EnS_EEm_Calc` has `measConfiguration`, `measOperation`, the help `measValueConfiguration`, `measValueOperation`. `BasicPosControl`: the sections name `OverAcc`, `OverDec` and a LAD box takes them; an SCL call answers *The formal parameter 'OverAcc' is invalid.* An S5 timer address in an SCL call becomes a PLC tag `Tag_n` in the default table, and every network on that address then exports the tag's name, LAD on its next import too.

**On this CPU, firmware V2.9** `[EXPORT]`, the reason where it says so `[INFERRED]`**:** `MB_RED_CLIENT`, `MB_RED_SERVER` compile as `.s7dcl` with 0 errors, stay not consistent after a compile of the whole PLC, and refuse their SimaticML export; as SimaticML *The 'MB_CLIENT V6.0' data type is not supported on this CPU or by the current library version.* The rows whose library version in TIA's file is newer than the tree's V6.0 or V5.2, which is why, inferred, no newer CPU tried: `MC_HaltSuperimposed`, `MC_SaveAbsoluteEncoderData`, `MC_GearInVelocity`, `MC_MotionInSuperimposed`, `MC_GetCamFollowingValueCyclic`, `MC_LoadProgram`, `MC_RunProgram`, `MC_StopProgram`, `CommConfig` answer *Data type MC_LoadProgram is unknown.*, as do `TIO_IOLink_IN`, `TIO_IOLink_OUT`.

**`"PORT"` in SCL** `[EXPORT]`**:** TIA and its `.s7dcl` write a parameter `PORT` in quotes, `"PORT" := ...`; SimaticML has `<Parameter Name="PORT">`. In LAD it has none.

The help against the exports, these instructions: `USEND`, `URCV` `SD_1` to `4`, `RD_1` to `4` (help `SD_i`, `RD_i`); `OPC_UA_ReadList_C`, `OPC_UA_WriteList_C` `Variable`, `NodeIDs` (help `Tag`, `NodeIds`); `Port_Config` `WAITTIME` (help `WAITIME`); `Send_P2P`, `Receive_P2P` have no `UNIVERSAL` on this CPU's version; `COM_RST` is no parameter of the CM instructions on these versions. The motion pages list pins the tree's V6.0 lacks: `ErrorInfo` on `MC_Power`, `MC_Reset`, `MC_Home`, `MC_Halt`, `MC_MoveAbsolute`, `MC_MoveRelative`, `MC_MoveVelocity`, `MC_MoveJog`; `HomingMode`, `Sensor` on `MC_Home`; `Mode` on `MC_Halt`; `Active`, `BufferMode` on `MC_MoveAbsolute`, `MC_MoveRelative`. `TIO_SYNC` has no `SendClock`, `TIO_DI_ONCE` no `Initialized`. `Inventory` `LEN_DATA` is a DInt.

**F-LAD goes in as `.s7dcl`** `[EXPORT]`**:** `{ S7_Safety := "TRUE" }` on the block. Plain elements as in a standard block. A box of the safety library as TIA exports it: `instX : X;`, `#instX.X( ... )` with all its pins named, an unwired one as `DIAG =>  `, and in front of it a pragma of its own, not `S7_Templates`: `{ f_user_card := "1"; f_image_card := "0" }`. Which cards and types a box wants differs; TIA's message names them (*Allowed Template Names: 'value_type, f_user_card, f_image_card, f_imageplus_card'*), and a wrong set can import and then fail: *The reference information is inconsistent.* Timers and counters take the rung at their first input: `Contact( ... )`, the box, `Coil( ... )`. An F-interface refuses `DWord`, `Byte`, `CTU_INT`, `IEC_TIMER`: those pins stay unwired, the instances have the plain type `TON`, `CTU`.

**The type of an F-box is in SimaticML only** `[EXPORT]`**:** the import takes `value_type := "Int"`, `time_type := "Time"` in that pragma, and the `.s7dcl` export leaves them out and keeps the cards. TIA's screen draws `Time` on `TP`, `TON`, `TOF`, `Int` on `CTU`, `CTD`, `CTUD`, `Word` on `SHR`, `SHL`, `Int` on `SCALE`, `Bool to Word` on `BO_W`, `Word to Bool` on `W_BO`, none on `SCALE_D`. Write the type on import, do not expect it back. There is no other: `value_type := "DInt"` on `CTU` imports, and the compile answers *The data type DInt of the actual parameter does not match the data type Int of the formal parameter.*; the same for `time_type := "LTime"` on `TON` (`Time`) and `value_type := "DWord"` on `SHR` (`Word`). `TP`, `TOF`, `CTD`, `CTUD`, `SHL`, `SCALE` were not tried themselves.

**F-LAD on the screen** `[EXPORT]`**:** an F-box has `EN` on the rail and `ENO` at the top like any box, and `CTU`, `CTD`, `CTUD` the output on the rung first. The help's drawings have `EN` unwired, `ENO` last, say they cannot be connected, and have `CV` before `Q`: take the screen. Titles in mixed case: `EV1oo2DI`, `F_FB_KTP_Mobile`. In-outs: `MP_STAT` of `F_FB_MP`, `MP1_STAT` and on of `F_FB_RNG_4`, `F_FB_RNG_16`. `.s7dcl` writes `hiLim`, `loLim` on the F-`SCALE`, as on the standard one, its sections `HI_LIM`, `LO_LIM`. TIA paints the F program yellow; no export holds that.

**F-boxes that do not go in** `[EXPORT]`**:** imported as SimaticML an F-block answers *No safety license available.* because the PC has no STEP 7 Safety license (the maintainer's word, 2026-11-03). On a PC with no license, seen; with one, not tried. Seen with TIA's own exports taken back, `zzFSafety`, `zzFTimer` with boxes of the safety library, `zzFBitLogic` without. As `.s7dcl` the same blocks import without the license; why that route does not ask is not known. With a license this answer should not come: the SimaticML import should go through, or stop on an answer of its own; this same answer on a PC with a license would mean this cause does not hold there `[INFERRED]`. If it comes, quote it. `SENDDP`, `RCVDP` have no way in by Openness on the PC with no license: *The type SENDDP is not permitted in the fail-safe block interface.* as a multi-instance, *Missing instance DB.* without a DB, *Dependent object 'SENDDP'not found in the Project.* for the DB as `.s7dcl`: a dialog of TIA makes it on inserting the box. The same in a TIA with a window, in LAD: all pins with the DB named at the call imports, then *Missing instance DB.*, and no dialog comes up.

**SimaticML import messages:** apart from `AutomaticTyped`, *is invalid* means a template name the part does not have, *has an invalid value* a wrong value; a missing output pin has to be wired (*is not connected*). What an import needs that no list holds: type templates per box (TIA names each that is missing); `DisabledENO="false"` on the string boxes; `card` 0 on `RD_REC`, `WR_REC`, `WR_DPARM`, `SETIO`; all of `SD_1` to `SD_10` wired on `Program_Alarm`, `Range` and `Subrange` on `GetChecksum`, though an SCL call leaves them out.

### 8.13b Logic on the pins of generic boxes `[PROBE]`

`Mux`, `Demux`, `Move`, `FillBlockI`, `FillBlockU` in LAD, an FB with Bool locals, V20 Update 7, on a CPU 1515F, through import and compile. What an instruction takes is a question per CPU family, and no other family was tried. In `.s7dcl`, and as SimaticML where the table says:

| Box | Pins with Bool operands | The pin on logic |
|---|---|---|
| `Mux`, `SrcType := Bool` | compile: *Data type Bool is not permitted here.* SimaticML import: *The element with UId ... causes the following error message: Data type Bool is not permitted here.* | `IN0`. Compile: the same, and *Only inputs and outputs of the data type bool are connectable.* SimaticML import: *The power rail (UId=...) contains an invalid connection to (UId=...) at pin "in0".* |
| `Demux`, `SrcType := Bool` | the same two | `OUT0` on a coil. SimaticML import: *... invalid connection ... at pin "out0".* |
| `Move`, with or without `SrcType := Bool` | compile: *Data type Bool is not permitted here.*, once per pin; the SimaticML imports and the compile answers the same | `OUT1` on a coil. SimaticML import: *... invalid connection ... at pin "out1".* |
| `FillBlockI`, `FillBlockU` | compile with 0 errors, on an element of an array of Bool | `IN`. Compile: *The data types are not compatible.* and *Only inputs and outputs of the data type bool are connectable.* SimaticML import: *... invalid connection ... at pin "in".* |

So none of these networks went through, one pin per box, and the boxes need no order for it. A pin that is Bool by itself takes logic: `R` of `CTU` as `.s7dcl`, `G` of `SEL` as SimaticML, each imported and compiled. What a person can draw in the editor was not tried: these runs were in a TIA without a window.

The form of a Bool input on logic: the box's rung first, `r := wire#f0`, and after it the rung that ends in that wire, as TIA exports it. That rung written **before** the box's fails the import: *Creation of OR gate failed with END_RUNG 'Wire#f0'.*

A box output on a coil, other than the output on the rung: no form tried goes in. `qd => wire#x` of `CTUD` with a rung `RUNG wire#x` after the box's: *Creation of OR gate failed with RUNG 'Wire#x'.* The same message for `out0 =>` of `Demux` and `out1 =>` of `Move`, with that rung before or after. As SimaticML, `QD` on a coil, with `QU` free or on a coil of its own: *... invalid connection ... at pin "QD".*

**Two shapes that import and do not compile.** A coil tapped from a node inside a leg of an OR, in the main rung's leg or the branch's, and a branch from a node in mid-rung onto a box pin (`r := wire#f0`, `RUNG wire#w1 ... END_RUNG wire#f0`), right in front of the box or a contact before it. Each imports, and the compile answers *The network does not comply with the rules for LAD.* The same networks without the tap, or with the branch from the power rail, compile with 0 errors.

### 8.14a Rung starts and edge boxes `[EXPORT]`

Verified by an import failure and its fix (2026-08):

- A rung that starts at a wire node (`RUNG wire#w1`) must begin with an element that has a rung-in and reads it: a contact or a box with `EN`/`in`. `P_Trig` / `N_Trig` as the first element of such a rung fails the import with `Instruction 'PBox' : Pin 'in' connection is missing`. The same is expected for `Coil` as a first element. Put the edge box on a rung that begins at `wire#powerrail` with a contact in front of it, e.g. read a coil written earlier in the same network:

```
NETWORK
    RUNG wire#powerrail
        Contact( #inButtonA )
        wire#w1
        Coil( #statRequested )
    END_RUNG
    RUNG wire#powerrail
        Contact( #inButtonB )
    END_RUNG wire#w1
    RUNG wire#powerrail
        Contact( #statRequested )
        P_Trig( #statEdgeMemory )
        Coil( #statRisingEdge )
    END_RUNG
END_NETWORK
```

- A branch rung that ends in a wire (`END_RUNG wire#w1`) and starts at a wire (`RUNG wire#w1 ... END_RUNG wire#w2`) is fine as long as its first element is a contact.

### 8.14b Shapes seen in exports `[EXPORT]`

- Timers: instance role, template pragma is `{ S7_Templates := "time_type := Time" }` (not `timeType`); unconnected `et` written as `et =>  ` with trailing spaces: `#statTimer.x.TON( pt := #CONST, et =>  )`.
- Comparators: `EQ_Contact`, `NE_Contact`, `LT_Contact`, `GT_Contact`, `GE_Contact` with `{ S7_Templates := "SrcType := DInt" }` (or `Time`, `LReal`) and `in1 :=`, `in2 :=`.
- Flip-flop: `S_SR( operand := #statLatch, r1 := wire#w3 )` with the rung-in as set; `S_RS` mirrored.
- `Move( in := ..., out1 => ..., out2 => ... )`, `Add( in1 :=, in2 :=, out => )`.
- Empty separator network: `RUNG wire#powerrail` / `END_RUNG` with nothing in between imports.
- Structured operands quoted where a member name is a keyword: `#ioPanel.command."sequence".cancel`.
- The export quotes member names that are keywords or look like them, wherever they occur (project A, V20 Update 7, 2026-10-29): written unquoted, imported, exported as `"a" : Bool;`, `"b"`, `"c"`, `"limit" : Int := 12;`, also in start values (`dev1."limit" := 7;`, `"limit" := 3;`). Both forms import; adopt the quoted one after a round trip.
- Call boxes come back with their parameters in the order inputs, in-outs, outputs, whatever order the import had (`inEnable`, `inValue`, `outActive`, `outValue`, `ioState` written; `ioState` exported before `outActive`).
- Global DB access from inside a block: `"GxxSlotStatus".fg[#tFg].bay[#tBay].ws.exist`.
- Interface pragma block per member: `{ S7_Access := "ReadOnly := External"; S7_Visibility := "Hidden := External" }`, optional `S7_MLC := "MLC_xxx"` for the comment id, `S7_Setpoint := "False"` on instances/timers. No `S7_Setpoint` is not false everywhere. Against the exports, TIA ticks the box on an FB instance, of a system FB or of the project, and on a UDT instance in a static of a standard FB; on a UDT instance in a global DB and in a UDT; on `TCON_Param` and `OPC_UA_SessionConnectInfo` in a global DB. It leaves it empty on elementary types and on `DB_WWW` and `PORT` in a global DB `[EXPORT]` (test project, seen in TIA, 2026-11-04). SimaticML of the same blocks writes false on `DTL` and an array of an elementary type, and on every instance in an F-FB `[EXPORT]`. Not seen in TIA: other system types in a DB, an array of a structured type (the one SimaticML seen with a setting on one says true: `CMD_buf` in `Write_Tagfield` `[EXPORT]`), an input or output of a UDT, and an F-block's instances. `DB_DYN`, `PIP` and `RTM` go as `DB_WWW` and `PORT` by their names only `[INFERRED]`. A released library type's export writes no `S7_Setpoint` at all, so there its absence says nothing `[EXPORT]`. A version just put in work writes none either; written as `"False"` into its document and imported, it comes back in the next export of that version `[PROBE]`. Whether a group-level pragma propagates to members is unverified; exports write it on every member.
- UDT file: `TYPE` / `typeName : STRUCT ... END_STRUCT;` / `END_TYPE`, members with the same pragma blocks, nested `_.typeOther` references.
- DB file: `{ S7_Optimized := "TRUE"; S7_StandardRetain := "FALSE"; S7_Version := "0.1" }` / `DATA_BLOCK name` / one or more `VAR` and `VAR RETAIN` sections / start values after the declarations as `name.member[1].x := 1.0;` lines / `END_DATA_BLOCK`.
- Global DB start value paths (projects A, B and C exports, 2026-10): a member of a `STRUCT` (`maxTime.timeout := T#600ms;`), an array element (`pos[1] := 6268;`), a member of a UDT member (`"left".homePos.xPos[3] := 410;`), an array of UDTs (`Index[0].Unit.Column := 0;`), any depth (`conn[3].connectionSetup.ConnPara.RemoteAddress.ADDR[1] := 192;`). Imported: `speed := 100;` and `dev1."limit" := 5;` (a UDT member) in `zzE2eGlobalDb` (project A, 2026-10-29).
- Comment of an inner member without a start value: the `S7_MLC` pragma, then the path with `:= ();`: `{ S7_MLC := "MLC_G5" }` / `dev2.flag := ();`. Seen in global DBs (projects B/C `StopDb`: `"Z00+RC01-QA500".q := ();`) and in a DB of a UDT (projects B/C `GxxFaultAndMode`: `fg[0].warning[40] := ();`). Imported: `StopDb` (projects B and C, 2026-10-21/22) and `zzE2eGlobalDb` `dev2.flag` (project A, 2026-10-29). Its id counts in the `.s7res` like any other.
- FB header: `S7_BlockTitle`, `S7_GenerateENOforSCL`, `S7_IECCheck`, `S7_Optimized`, `S7_PreferredLanguage`, `S7_Version` in the leading pragma block.
- `.s7res`: YAML, `MultiLingualTexts:` list of `- id: MLC_xxx` / `    en-US: text`. A key of a language the project does not have fails the import (8.14c). Multi-line text uses `|-`. Values containing `:` are single-quoted: an unquoted `: ` in a text is not YAML, and the import fails with *"The resource file contains corrupted data or format might be invalid."* (project C `Main_Safety_X1`, 2026-10-22). Ids are free strings: hand-picked ids (`MLC_N001`) imported without complaint. `[EXPORT]` (import failure 2026-08-25, LAD FB): the importer enforces a STRICT 1:1 COUNT between MLC references in the `.s7dcl` and entries in the `.s7res` — "Import failed because the Mlc ids present in resource file ... does not match the count of Mlc ids present in source file". Consequences: every `S7_MLC`, `S7_NetworkTitle`, `S7_NetworkComment` and `S7_BlockTitle` reference needs its OWN entry; one id must NOT be shared by several members (eight members sharing one id = seven missing entries); unused entries are NOT harmless — they fail the count the other way. When generating, count `MLC_` occurrences in the `.s7dcl` and entries in the `.s7res` and require equality before handing the pair to TIA.
- Comment ids belong to the project `[EXPORT]` (projects B and C, 2026-10): every TIA export of a block repeats the `S7_MLC` id of each comment, also after its text changed (926 commented members over the repos' histories); an id written into an import is kept and exported again (an agent's `MLC_N001` comes back as `MLC_N001`). A member renamed in TIA's editor keeps its comment's id (a UDT of project E, 2026-10-31). Two copies of one project do not share them (project A's original and latest copies differ in 4248 of 4248 ids), and a SimaticML import gives every comment a new id (an FB of project E exported as SimaticML and imported back: 16 of 16 new, also of members not edited). So an id identifies a comment only within one copy and until such an import: no evidence that two exports' members are one (TiaChangeReports does not use them).
- Timer instance type in the interface: `IEC_TIMER`.
- FC header (V20 Upd7): `FUNCTION "PressureSwitchP1" : Void`, same pragma block as an FB; an SCL FC with only comments (`Customer_Description`) imports and exports. OB header: `ORGANIZATION_BLOCK "CyclicInterrupt"` with `S7_BlockTitle`, `S7_PreferredLanguage`, `S7_Version`; no event class, no number.
- `.s7res` normalization on export (2026-09-28): TIA drops the single quotes of a value that does not need them and adds them where it does, and writes a text that starts with a space as `|2-` block scalar. Semantically the same YAML; diff exports by parsed value, not by bytes, when checking a round trip.
- Instance DB file: header pragma block, then `DATA_BLOCK G05UnitsDb : G05Units` / `END_DATA_BLOCK` with no body. No `.s7res`. Multi-instances and retain members of the FB do not show in it: all 203 instance DBs and DBs of a UDT in project A have no body, 189 of them of FBs with multi-instances, 4 of FBs with a `VAR RETAIN` section. Own start values and the retain of "Set in IDB" members are the only things an instance DB adds (next items).
- Start values of an instance DB and of a DB of a UDT (project A, V20 Update 7, 2026-10-29): one line per value between the header and `END_DATA_BLOCK`, no `VAR` section: `DATA_BLOCK zzE2eSubFb_DB : zzE2eSubFb` / `inValue := 5;`, `DATA_BLOCK zzE2eUdtDb : zzE2eData_UDT` / `limit := 3;`. Both imported, and the export writes them back (`"limit" := 3;`, quoted as above). The empty body above is an instance DB without own start values. A member of a multi-instance takes its path (project A, V20 Update 7, 2026-10-30): `DATA_BLOCK zzE2eMultiFb_DB : zzE2eMultiFb` / `statState := 4;` / `instSub.inValue := 7;` (an FB multi-instance) / `instTon.PT := T#3s;` (a `TON_TIME`) imported, compiled, and the export wrote the three lines back unchanged; the SimaticML export of the same DB holds them as `StartValue` of `inValue` and `PT` inside the multi-instances.
- A member of a data type renamed by an import of the type drops the start values that DBs hold of it `[PROBE]` (a copy of project E, V20, 2026-11-05): the global DB `zzIfaceDb` held `d2New : _.zzIface_UDT` with `d2New.m3 := 4;`. `zzIface_UDT` was imported from SD with `m3` renamed `m3Renamed` and compiled; the DB was not imported (the compile took it with the type). Its next export had no start value line for the member, only `d1New := 3;`. Before such a rename, note the start values of the member in the DBs of the type, and write them back under the new name with an import of each DB (not tried).
- Retain: a `VAR RETAIN` section in a global DB and in an FB (project A `SiloEmptyCheck`: `statReadyFlag`). An FB can have `VAR_INPUT DB_SPECIFIC`, `VAR_OUTPUT DB_SPECIFIC` and `VAR DB_SPECIFIC` sections (project A `DriveTelegram_PPO2/4`): TIA's retain "Set in IDB". An FB with all three, a `VAR RETAIN` and a plain `VAR` section imported and compiled (`zzE2eRetFb`, project A, V20 Update 7, 2026-10-30).
- `S7_StandardRetain` in the DB header is the retain of everything the DB decides as a whole (same session, each case imported from SD, compiled, exported as SD and as SimaticML):
  - Instance DB: all "Set in IDB" members together. `"TRUE"` makes every `DB_SPECIFIC` member Retain in the SimaticML; `VAR RETAIN` members of the FB stay Retain and plain `VAR` members NonRetain either way. The members cannot differ: a SimaticML import of the instance DB with one of them Retain and another NonRetain was refused with *zzE2eRetFb_DB.inB: The Openness import failed: The attribute 'Remanence' cannot be set.*; with all of them Retain it imported, and the SD export wrote `S7_StandardRetain := "TRUE"` and still no body.
  - DB of a UDT: all members. `"TRUE"` (`zzE2eStdRetUdtDb`, like the project A DBs of `HmiAlarm_UDT`) gives every member Remanence Retain, `"FALSE"` NonRetain. A member of a UDT cannot be retained on its own.
  - Non-optimized global DB (`S7_Optimized := "FALSE"`): the whole DB, and it must match the section: `"TRUE"` with only `VAR RETAIN`, `"FALSE"` with only `VAR`. Either mismatch is refused with *Import failed because non optimized block contains both Retain and non Retain variables.*
  - Optimized global DB: no effect. `VAR RETAIN` / `VAR` decide per member; `"TRUE"` and `"FALSE"` give the same SimaticML export and the same attributes (`probe` `[PROBE]`: the same attributes; the only retain-related one, `IsRetainMemResEnabled`, False on both). TIA keeps the imported value and the SD export writes it back; a SimaticML import (which does not carry it) resets it to `"FALSE"`. So the mix in project A (`SiloData` `"FALSE"`, `GxxSlotDataBackUp` `"TRUE"`, both only `VAR RETAIN`) means nothing; keep the exported value.
- Multi-instance of a freshly imported FB (V20 Upd7, 2026-09-25): the export of `ControlStationPump20` wrote `instControlPowerPack20 : "$"ControlPowerPack20$"";` instead of `_.ControlPowerPack20`, while `_.ComputeTableHeight` and `_.DriveVerticalAxis` in the same file exported normally. Cause unknown; whether that form re-imports is unverified. It was written back as `_.ControlPowerPack20` (the form that had imported). Check exports for `"$"` in type references.

### 8.14c Import failures from resource files and branch shapes `[EXPORT]`

Verified by four failed syncs and their fixes (project B, 2026-09-23, TIA Portal V20). Every defect of those four was in a file **written by TIA's own export** (possibly after the ID add-in had run), not by hand; a file that exported cleanly is not proof that it re-imports.

**Duplicate MLC ids.** Two entries with the same id in one `.s7res` (and the id referenced twice in the `.s7dcl`) fail the import with *"Error when calling method 'ImportFromDocuments' ... The resource file contains corrupted data or format might be invalid."* The count check of 8.14b passes, because references and entries are both one too many. Seen in `StationPassThrough10` (two empty separator networks sharing `MLC_54t`) and `CyclicInterrupt` (F10 and F11 CALL networks sharing `MLC_3mw` / `MLC_3uE`). Both came from copying a network in the TIA editor; the copy keeps the text ids of the original, and the export writes them out twice. Fix: give the copy a new id in both files. In the project, retyping the copied network's title and comment should make TIA assign new ids at the next export.

**Entries without text.** An entry that has only an id and no language key:

```yaml
  - id: MLC_002
```

fails the import with *"0 errors, 0 warnings : Import of block(s) failed. please check the s7dcl file"* and no other message. Seen in `G05Units` for six empty network comments (`MLC_002` … `MLC_012`; the sequential numbering suggests the ID add-in rather than the exporter, unconfirmed). Fix: delete the `S7_NetworkComment := "MLC_0xx"` line in the `.s7dcl` and the entry in the `.s7res`; a network without a comment needs no reference at all. The same file with every network title and comment removed imported, which is how this was isolated.

**A text in a language the project does not have** (a line added by hand, not an export; a test project with en-US only, TIA Portal V20 Update 7, 2026-11-04). One more key in an entry:

```yaml
  - id: MLC_C
    en-US: A comment
    de-DE: Ein Kommentar
```

fails the import with `Siemens.Engineering.EngineeringTargetInvocationException`: *"Error when calling method 'ImportFromDocuments' of type 'Siemens.Engineering.SW.Blocks.PlcBlockComposition'. ERROR: ResourceID 'MultiLingualTextWithInvalidDocumentOption' not found in resource of type Siemens.Simatic.Lang.Documents.DOL.FeedbackDocuments"*. The import is rolled back. The text speaks of a resource TIA itself is missing; it does not name the language, the entry or the file. Through SimaticML (`format: xml`), a de-DE text on a project with en-US only says what it is: *the specified culture does not exist within the current project* (2026-11-02). Fix: take the key out of the entry. The same document without that line imported, compiled and saved. On the first text, compare the language keys of every `.s7res` of the import with the project's languages: `probe("project", "LanguageSettings.ActiveLanguages")` lists them under `items` `[PROBE]`. On a copy of another project a de-DE text of one comment went in, and its report showed the state changed (2026-11-02). The record does not name the route, SD or SimaticML, and that repo no longer exists, so an SD import in a language the project has is not shown. That `ActiveLanguages` is the list TIA checks against is an assumption `[INFERRED]`.

**Branch that starts at a merge node and encloses a nested OR ending at the same node.** Fails with *"Syntax Error during import of TextLad file, Message: Creation of OR gate failed with RUNG 'Wire#w3' and END_RUNG 'Wire#w5'"*. The failing shape, from the *Command - Lower table* network, exported by TIA:

```
RUNG wire#powerrail
    Contact( #req )
    wire#w1
    ...
    wire#w2
    Contact( #sensorClear )
    wire#w3                               // closes the w2-w3 OR ...
    Contact( #auto )
    wire#w4
    EQ_Contact( ...STEP_A )
    wire#w5
    Coil( #out )
END_RUNG
RUNG wire#w2  Contact( #aboveLimit )  END_RUNG wire#w3
RUNG wire#w4  EQ_Contact( ...STEP_B ) END_RUNG wire#w5   // inner OR, ends at w5
RUNG wire#w3  Contact( #manual )      END_RUNG wire#w5   // ... and opens one that encloses it
RUNG wire#w1  Contact( #maint )       END_RUNG wire#w5
```

Fix, same logic: flatten the nested OR into sibling branches with the same start and end node, repeating the shared contact:

```
    wire#w3
    Contact( #auto )
    EQ_Contact( ...STEP_A )
    wire#w4
    Coil( #out )
END_RUNG
RUNG wire#w2  Contact( #aboveLimit )               END_RUNG wire#w3
RUNG wire#w3  Contact( #auto )  EQ_Contact( ...STEP_B )  END_RUNG wire#w4
RUNG wire#w3  Contact( #manual )                   END_RUNG wire#w4
RUNG wire#w1  Contact( #maint )                    END_RUNG wire#w4
```

**Branch from a merge node that ends inside a sibling branch from the same node** (repo A `Trolley` NW49/NW50, TIA's own export, V20 Update 7, 2026-10-24). Fails with *"Error during import of TextLad file, Message: Instruction 'Contact' : Pin 'in' connection is missing."*. `wire#w1` is a merge node (the main rung and another branch end there), and two branches start at it, the second ending at a node inside the first:

```
RUNG wire#w1
    I_Contact( #statHead.AtNeck )
    wire#w9
    Move( in := #FLOW_OFF, out1 => #statFlow.Pump )
END_RUNG
RUNG wire#w1
    I_Contact( #tmpModeSelect )
END_RUNG wire#w9
```

Fix, same result: give each branch its own `Move` and drop `wire#w9`. Found by bisecting test blocks down to single rungs: the network without these two rungs imported. Lint rule: no branch that starts at a merge node may end at a node inlined in a sibling branch that starts at the same merge node.

**A branch that ends at a node, written after a rung that starts at that node** `[PROBE]` (a network of a test block, TIA Portal V20 through TiaBridge, 2026-11-06, the Update not recorded; the text below without its two comments, as an FC of its own with Bool inputs, V20 Update 7, 2026-11-07). Fails with the message of the `Trolley` entry (Branch from a merge node that ends inside a sibling branch from the same node); here the message goes on with the network: *Error during import of TextLad file, Message: "Instruction 'Contact' : Pin 'in' connection is missing. Error in Network: ..."*, then *1 errors, 0 warnings : Import of block(s) failed. please check the s7dcl file.* The batch is rolled back. A new branch from the rail into `wire#w1`, beside the first contact, written last:

```
RUNG wire#powerrail
    Contact( #a )
    wire#w1
    Contact( #b )
    wire#w2
    Contact( #c )
    wire#w3
    Coil( #q )
END_RUNG
RUNG wire#w2
    Contact( #d )
END_RUNG wire#w3
RUNG wire#w1                  // starts at w1 ...
    Contact( #e )
END_RUNG wire#w3
RUNG wire#powerrail           // ... and the new branch, after it, ends at w1
    Contact( #f )
    I_Contact( #g )
END_RUNG wire#w1
```

Fix, same logic: write the new branch after the main rung and before `RUNG wire#w1`. Right after the main rung (both runs), and between `RUNG wire#w2` and `RUNG wire#w1` (2026-11-07), the same rungs imported and compiled with 0 errors, and TIA's export wrote the new branch right after the main rung in both.

The rule, for every node: a rung that ends at a node goes before every rung that starts at that node. Tried for two shapes `[PROBE]`: at `wire#w1` a branch from the power rail (above), at `wire#w2` a branch from `wire#w1` (below); other nodes and shapes `[INFERRED]`. At `wire#w2`, with the same main rung and `RUNG wire#w2 Contact( #d ) END_RUNG wire#w3`, a branch `RUNG wire#w1 Contact( #f ) I_Contact( #g ) END_RUNG wire#w2` written after that rung fails with another text: *Error during import of TextLad file, Message: " The output pin connecting to the instruction 'Contact' is missing.. Error in Network: ..."*, then the same *1 errors, 0 warnings*. Written before it, the branch imported and compiled with 0 errors. A branch also goes after the rungs that hold its start and its end node, tried for one shape `[PROBE]`, a branch with both nodes in the main rung: `RUNG wire#w2 Contact( #d ) END_RUNG wire#w3` written before the main rung fails with *Syntax Error during import of TextLad file, Message: "Creation of OR gate failed with RUNG 'Wire#w2'. Error in Network: ..."*, the text 8.13b gives for a box output on a wire. Its nodes in two rungs: `[INFERRED]`. These tries ran on 2026-11-07, V20 Update 7, each network as an FC of its own.

The rule does not explain the shape of the `Trolley` entry, where no rung starts at `wire#w9`. On *Pin 'in' connection is missing*, check a file for both causes.

**Multi-dimensional array index in LAD operands** (repo A, `ImportFromDocuments` into the version in work of the library types `Trolley` and `ChargeStation`, V20 Update 7, 2026-10-24). The import succeeds, but every LAD operand with a multi-dimensional index keeps only its last index: `#ioTrolleyData[#iLevel, #iColumn, #iLine].Status.Mode` comes back from the next export as `#ioTrolleyData[#iLine].Status.Mode`. The compile then fails with *Tag #ioTrolleyData[#iLine].Status.Mode not defined.* (151 errors). `ChargeStation` was imported unchanged, and none of its three-index accesses survived; in SCL networks they did. Do not round-trip a LAD network that uses multi-dimensional array operands through SIMATIC SD. SimaticML keeps them (`Trolley` on a copy of project A, 2026-10-29: SimaticML export of the version in work, edit, `CreateFromDocuments` with Override, compile 0 errors, all 114 three-index operands intact, the project instance still linked; side effects: new text ids, trailing spaces of two comments dropped). With TiaBridge: `export` kind `library_type` with `format: xml` once (later exports keep it; the SD export of such a type says so in its note), edit the `.xml`, `import` it (bridge run on a project A copy the same day: import 14 s, compile 0 errors, all 300 three-index references unchanged). Whether a plain project block (not a library type document) loses its indices the same way is unverified; exchange it as SimaticML too (`export` kind `block` with `format: xml`).

What does import: a branch starting at a merge node when nothing nested inside it closes at the same end (`w2→w3`, `w3→w4`, `w1→w4`, the *Conveyor east* network); several branches closing at one node when they are nested only by start (`w2→w3`, `w1→w3`); several sibling branches with identical start and end. Lint rule: for every branch `(s, e)` where `s` is also the end of another branch, no other branch may start strictly between `s` and `e` on the main rung and also end at `e`.

### 8.14d Classic SCL source attributes → SIMATIC SD `[EXPORT]`

For porting a block written as a classic `.scl` / `.udt` source into an SD pair:

| Classic source | SIMATIC SD |
|---|---|
| `{ ExternalWritable := 'False'}` | `S7_Access := "ReadOnly := External"` |
| member hidden from HMI engineering | add `S7_Visibility := "Hidden := External"` |
| `{ S7_SetPoint := 'False'}` | `S7_Setpoint := "False"` |
| member comment `// text` | `S7_MLC := "MLC_xxx"` + entry in the `.s7res` |
| type header comment | `{ S7_BlockComment := "MLC_xxx" }` after `TYPE` |
| reference to another UDT `"typeName"` | `_.typeName` |
| `VERSION : 0.1` | `S7_Version := "0.1"` in the header pragma block |
| `TON_TIME` / `TOF_TIME` instance | `IEC_TIMER` member called as `.TON(...)` / `.TOF(...)` (changes the instance layout) |

### 8.14 Calculate box

Extensible expression box; the expression lives in the `S7_Expression` pragma and uses the formal parameter names:

```
RUNG wire#powerrail
    Contact( #isEnabled )
    {
        S7_Templates := "SrcType := Real";
        S7_Expression := "sqr( sin( in1 )) + sqr( cos( in2 ))"
    }
    Calculate(
        in1 := #inAngleA,
        in2 := #inAngleB,
        out => #oResult
    )
END_RUNG
```

There is no `out :=` inside the expression; the output binding is fixed.

Export of an FB (V20 Update 7, 2026-10-30) `[EXPORT]`: `{ S7_Templates := "SrcType := DInt"; S7_Expression := "(IN1 + IN2) * (IN1 - IN2)" }` before `Calculate( in1 := ..., in2 := ..., in3 := ..., out => ... )`: the export writes the formal names in the expression in upper case, as the editor shows them (`OUT := (IN1 + IN2) * (IN1 - IN2)`). The SimaticML export of the same network in an OB: the part `Calc` with `<Equation>(IN1 + IN2) * (IN1 - IN2)</Equation>`, `Card` (the number of inputs) and `SrcType`; pins `en`, `in1..n`, `out`.

ENO: the Calculate as placed in the editor has `DisabledENO="true"` in the SimaticML export (ENO not generated: TIA draws it gray, with a line from EN through the box), and its `.s7dcl` export has no `S7_GenerateENO` pragma `[EXPORT]`. So no pragma = the gray ENO. That `S7_GenerateENO := TRUE` is written when ENO is generated (8.6) is not yet seen for a Calculate `[INFERRED]`.

---

## 9. Validation checklist (run against every generated file)

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

## 10. Import behavior and diagnostics `[LAD-DOC §5]`

When STEP 7 imports, each `identifier(` is resolved in this order: keywords → local variables → inherent instruction library → opened system and user libraries → user program (global namespace). Outcomes:

- Inherent instruction → contact/coil/box rendered normally.
- Local variable that is an FB/SFB instance → box with type name inside, instance on top.
- FC/SFC name → box with block name.
- FB/SFB name without instance → red box with three red question marks (missing instance).
- Anything else / unknown → red box with the identifier inside.
- Missing closing `)` → syntax error, **import aborts**.
- Parameter list does not match the resolved object → red box, import **continues**.

That is the behaviour of the LAD format description. Through the Version Control Interface sync it is stricter `[EXPORT]`: a bad resource file or an unresolvable reference fails the whole block, often with no detail in the log. Section 9 is the minimum bar before any import; compile-cleanliness is the real target.

**How the VCI sync imports** `[EXPORT]`:

- Each workspace folder imports as **one batch** to its matching project group. One bad file fails the folder, and the log names the folder (`"..._Customer" could not be imported to the target "_Customer"`) with the reason on a sub-line, sometimes naming the file, sometimes not.
- Folders import in their own order (G05 before the root folder was observed). A block in one folder that calls a changed FB in another fails on the first sync and imports on the second. Sync twice before investigating a dependent block.
- Only files that changed since the last sync are imported. A TIA-exported file with a latent defect (8.14c) sits harmlessly until someone edits it, then fails.
- TIA stops at the first error in a block; fixing one can reveal the next.
- **Line ends decide the indent of an SCL body** (test FCs, TIA Portal V20 Update 7, background session, 2026-11-02) `[EXPORT]`: an export writes every body line 8 spaces deeper than TIA holds it, and an import takes up to 8 off again, but only from a line that follows a CRLF. A line after a lone LF keeps them, so with LF the body goes 8 deeper on every round trip. Measured, one trip:

  | Line in the file, code or comment | File with CRLF | File with LF |
  |---|---|---|
  | First line of the body | 8 stays 8, 12 stays 12 | 8 stays 8 |
  | Any other line at 8 or deeper | stays (8, 12, 14), and a second trip gives the same body | 8 deeper (8 to 16, 12 to 20) |
  | Any other line below 8 | comes back at 8 (0, 2, 4 to 8), so relative indent below 8 is lost | 8 deeper (0 to 8, 4 to 12) |

  A file with both line ends behaves line by line: only the lines after a lone LF go deeper. Whether the body starts with a statement or a `REGION` makes no difference. A `(* ... *)` comment follows the same rule, so its continuation lines keep their relative indent from column 8 on.
  - The TiaBridge `import` (blocks, DBs, types, library types) rewrites a `.s7dcl` with a lone LF as CRLF in place before TIA reads it, changes no other byte, and says so in the item's `note`. Through the VCI sync, write CRLF yourself.
  - Keep your own indent at 8 or deeper. A body that has already gone deeper stays there (24 stays 24): take the surplus off by hand once, in the file, with the lines still at 8 or deeper.
  - SCL has no multi-line string: such a block imports and then fails to compile (*Invalid expression*).
  - Windowed TIA: imports stayed as above on project B (2026-10-06 to 2026-10-20, three FCs): two known to be CRLF (one written by a generator with CRLF, one an export re-imported), the third inferred from how it behaved, since git holds no line ends here (`core.autocrlf`). LF in a window was not measured `[unverified]`.
  - The documentation add-in renders a comment that came back at 8 correctly (checked on four generations, project B, 2026-09-28).
- **Block attributes set by an import** (project A, TiaBridge without user interface, 2026-10-29) `[EXPORT]`: the export of the SCL FC `CopyTrolleyDriveStatus` carried neither `S7_GenerateENOforSCL` nor `S7_IECCheck`: both are FALSE in TIA, and the export writes them only when TRUE. Importing that file with one comment line added set both to TRUE, and the re-export carried them as `"TRUE"`. Written as `"FALSE"`, they stay FALSE and the re-export leaves them out again. So this part of the exporter's normalization is not adopted: add the missing ones as FALSE before every import (section 9, item 18). Probably TIA applies the project's defaults for new blocks `[unverified]`; window mode not checked, same import call.
- **Locked files** (project B, 2026-09-26): while a block is open in the TIA editor, its `.s7dcl` in the workspace is locked (a write is refused as "open in another app"); the `.s7res` is not. Close the block, or hold both files of the pair until it is closed, so no pair is half written.
- **Library types after an export** (project B, 2026-09-28): `<type>.libinfo` shows `VersionNumber` and `InWork` / `IsDefault`; `<type>.libint` lists `DependsOn` with the versions of the contained types. Any change to a library type, a comment-only `.s7res` change included, leaves it "in work" until it is released in TIA; the containing types then need an update and a release (next item). Check both files after every export before calling a library change done.
- **Duplicate types with a `_1` suffix** (project B, 2026-09-28): the project held a second copy of several library types (`..._1`, an older version). The program and the documentation add-in used the old version (pages showed V0.0.3 with texts from before 2026-09-26). Remove the duplicates in TIA, update the project to the default versions, export again.
- **Changed library type used inside another library type** (project B, 2026-09-26): the changed type file (`typeDriveVerticalAxisConfig`, with `.libinfo` / `.libint` / `.liblink` next to it) imports, but the types that contain it keep pointing to the released version without the new members. A data block that sets start values for the new members then fails with *The member "..." is not present in the source block of IDB*. Fix in TIA: open the containing type (`typeHmiDriveVerticalAxis`), update it to the new version of the changed type, release, then sync again. Plan this step whenever a library-linked type gets new members.
- **A block that no longer exports while a copy of it does** (project B, 2026-09-25): cause unknown. The original block object was in a state TIA would not export, and a copy of it was not. Did not help: compile, rebuild all blocks, regenerating the text ids (SimaticSdEnabler), the VCI checkbox, disconnecting the block from the workspace, deleting its workspace files. What worked: copy the block, delete the original, rename the copy to the original name, export. Callers bind by name and pick up the copy, but their instance data is reinitialised on the next download (retained values included), so note the values first. Better, with TiaBridge (project B, 2026-10-08, 31 FG blocks refused with *SIMATIC SD export failed due to project modifications made with a TIA Portal version earlier than V20 Update 4*, also after SimaticSdEnabler): `export` the block as SimaticML (`format: xml`, still allowed), `import` that file over the block (override, no delete), `compile`. The XML export afterwards differed only in the export time, the instance DBs stayed consistent, and every block exported as `.s7dcl` again (that export deletes the `.xml` from the project repo). The import gives the block new internal text ids, which is most likely what the copy did too.

- **Main safety block after an import** (project B, TiaBridge, 2026-10-20 and 2026-10-22): importing the `.s7dcl` of the
  F-runtime group's main safety block (`Main_Safety_X1`) over itself succeeds, but the F-runtime group loses its main
  safety block, and the next compile fails with *The F-runtime group "F-runtime group 1" does not have a valid main
  safety block.* Openness through TiaBridge cannot set it: the user sets it again in TIA (Safety Administration, F-runtime
  group, main safety block), then compile and save. Plan this step for every import of a main safety block (`safety: true`, like every F-block; only when the user asked for the safety change). Importing
  a PLC tag table that holds F-I/O tags does not touch the safety program (export dates of the main safety block
  unchanged, 2026-10-22).

**Log message → cause** `[EXPORT]`:

| Log message | Cause | Section |
|---|---|---|
| *Mlc ids present in resource file ... does not match the count* | Reference and entry counts differ | 8.14b |
| *The resource file contains corrupted data or format might be invalid* (ImportFromDocuments) | Duplicate MLC id | 8.14c |
| *0 errors, 0 warnings : Import of block(s) failed. please check the s7dcl file* | Entry without text; or a referenced FB/UDT not yet in the project with the expected interface | 8.14c, 9.17 |
| *ResourceID 'MultiLingualTextWithInvalidDocumentOption' not found* (ImportFromDocuments) | An `.s7res` text in a language the project does not have (the one cause seen) | 8.14c, 9.15 |
| *the specified culture does not exist within the current project* (SimaticML) | A text in a language the project does not have | 8.14c |
| *Creation of OR gate failed with RUNG 'Wire#wX' and END_RUNG 'Wire#wY'* | Nested-OR branch shape | 8.14c |
| *Creation of OR gate failed with END_RUNG 'Wire#x'* | The rung feeding a box pin written before the box's rung | 8.13b |
| *Creation of OR gate failed with RUNG 'Wire#x'* | A box output on a wire (`=> wire#x`), other than the output on the rung: no form tried goes in; or a branch written before the rungs that hold its start and its end node | 8.4, 8.13b, 8.14c, 9.16a |
| *The import failed. The source file contains multiple object definitions.* | Two FCs in one document, the one case tried; an FB, a DB and a library type were not. Two data types in one `TYPE` get no such answer: the first is made, the second is gone | 9.20 |
| *The import failed. The instance name in the file is invalid.* (`CreateFromDocuments`) | The first keyword of a new library type's document in lower or mixed case | 2 |
| *Data type Bool is not permitted here.* (compile, or SimaticML import) | `Mux`, `Demux`, `Move` with the type Bool, on a CPU 1515F | 8.13b |
| *Only inputs and outputs of the data type bool are connectable.* (compile) | Logic on a pin of a generic type | 8.13b |
| *The power rail (UId=...) contains an invalid connection to (UId=...) at pin "..."* (SimaticML) | Logic on that pin; a box output on a coil that is not the rung's | 8.13b |
| *The network does not comply with the rules for LAD.* (compile) | A coil tapped inside an OR leg; a branch from mid-rung onto a box pin | 8.13b |
| *Value 'SCL' for attribute 'S7_PreferredLanguage' is invalid* | `S7_PreferredLanguage := "SCL"`; an SCL block has `S7_EditorMode := "SCL"` | 3, 9.19 |
| *ResourceID 'MulitpleSCLNetworksErrorMessage' not found* | Several networks in a block with `S7_EditorMode := "SCL"` | 6, 9.19 |
| *Syntax error ':=' expecting ;* (data block) | Initial value on a `DATA_BLOCK` declaration | 4, 9.19 |
| *Import failed because non optimized block contains both Retain and non Retain variables.* | Non-optimized DB whose `S7_StandardRetain` does not match its section (`VAR RETAIN` / `VAR`) | 8.14b, 9.19 |
| *The Openness import failed: The attribute 'Remanence' cannot be set.* (SimaticML, instance DB) | "Set in IDB" members with different Remanence; they are retained all or none | 8.14b |
| *Instruction 'PBox' : Pin 'in' connection is missing* | Edge box first on a wire-start rung | 8.14a |
| *Instruction 'Contact' : Pin 'in' connection is missing* | A rung written after a rung that starts at its end node (seen for a branch from the power rail); or a branch from a merge node ending inside a sibling branch from the same node | 8.4, 8.14c, 9.16, 9.16a |
| *The output pin connecting to the instruction 'Contact' is missing.* | A rung written after a rung that starts at its end node (seen for a branch from `wire#w1` to `wire#w2`) | 8.4, 8.14c, 9.16a |
| *Tag #x[#c].y not defined* after an import that succeeded (LAD) | Multi-dimensional index cut to its last index by the SD import | 8.14c |
| *Error when calling method 'CreateFromDocuments' of type 'Siemens.Engineering.Library.Types.LibraryTypeVersionComposition'. The creation of a new instance of the document has failed.* (library type, no detail) | Any import error in the document. Import the same text as a test project block (`zz...`) to get the real message, then bisect | 10 |
| *The member "x.y" is not present in the source block of IDB* (data block start value) | The member's type is library-linked and the containing library type still uses the old version | 10 |
| *The F-runtime group "..." does not have a valid main safety block* (compile after an import) | The main safety block was imported; set it again in the F-runtime group | 10 |

**Bisecting a silent failure.** When the log says only "0 errors ... failed", write the block's networks as separate test FBs (`<Block>Test1..n`) into the same workspace folder, each with the full `VAR` section and a slice of the networks, with network titles and comments stripped so no `.s7res` is needed. One sync reports each test separately. If every slice imports, the fault is in the `.s7res` or in the block's existing state in the project, not in the code. Delete the test blocks from the project and the workspace afterwards.

## 11. Platform notes verified from Siemens readmes `[README]`

- SIMATIC SD pair: `.s7dcl` + `.s7res`. Exchange both files together; the `.s7res` carries comments/titles/multilingual texts.
- SCL block export/import since TIA Portal V20 Update 4; blocks written in other languages can be converted to SCL SD via Openness/VCI; export does not require an error-free compile.
- LAD, UDT and DB documents (including F-DBs) export/import via the version control interface.
- **OBs are exported without type information**: any OB re-imported from SD becomes a "Program cycle OB" regardless of its original event class. For OB30-class cyclic interrupt blocks (project F architecture), the OB type must be fixed manually in TIA after import — plan block generation accordingly (keep OB bodies trivial, put logic in FBs). `[EXPORT]` Confirmed on V20 Update 7 (project B, 2026-09-25): an edited `CyclicInterrupt` (OB30) came back as a Program cycle OB with the number 124. TIA cannot change an OB's event class, so the OB had to be recreated. Do not edit or re-import OB files as `.s7dcl`. As SimaticML an OB keeps them: `ProgrammingError` (OB121) exported, imported unchanged and exported again kept number 121 and the event class `ProgrammingError`, only the export time differs (TiaBridge, project B 2026-10-06); TiaBridge exports OBs as SimaticML for this reason.
- Not exported: know-how-protected blocks, read-only blocks, PLC supervisions/alarms, SiVArc definitions.
- SIMATIC SD export can fail when multilingual comment (MLC) ids in the project are inconsistent. Fix: install and run the TIA Portal add-in **SimaticSdEnabler** before exporting. To avoid recurring inconsistencies, edit the project only with V20 Update 4 or later (V20 Upd4 readme). Update 5 contains no SIMATIC SD changes.
- V21 (2025-11) extends SIMATIC SD to FBD, SCL and mixed-language blocks and lists all block types, OBs included, as exportable. Migration from V20 is one way. Whether V21 keeps an OB's event class on import, or removes the need for the add-in, is unverified.
- After updating TIA Portal: update every installation that touches the project (including a VM that runs the workspace sync), run SimaticSdEnabler once, compile, do a full export, and check the whole workspace against section 9 items 13–16 before editing continues.

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

## Appendix A: complete example block

A minimal but structurally complete FB mixing LAD and SCL, in the form the V20 exporter writes (without the pragma blocks and `.s7res`).

```
FUNCTION_BLOCK "ControlConveyorStart"
VAR_INPUT
    isStartRequested : Bool;
    isStopRequested : Bool;
    startDelayTime : Time;
END_VAR
VAR_OUTPUT
    isMotorCommanded : Bool;
    isReadyForStart : Bool;
END_VAR
VAR
    statRunLatch : Bool;
    instStartDelay : IEC_TIMER;
END_VAR

{ S7_Language := "LAD" }
NETWORK
    RUNG wire#powerrail
        Contact( #isStartRequested )
        wire#w1
        I_Contact( #isStopRequested )
        Coil( #statRunLatch )
    END_RUNG
    RUNG wire#powerrail
        Contact( #statRunLatch )
    END_RUNG wire#w1
END_NETWORK

{ S7_Language := "LAD" }
NETWORK
    RUNG wire#powerrail
        Contact( #statRunLatch )
        { S7_Templates := "time_type := Time" }
        #instStartDelay.TON(
            pt := #startDelayTime,
            et =>  
        )
        Coil( #isMotorCommanded )
    END_RUNG
END_NETWORK

{ S7_Language := "SCL" }
NETWORK
    #isReadyForStart := NOT #statRunLatch AND NOT #isStopRequested;
END_NETWORK
END_FUNCTION_BLOCK
```

Semantics: network 1 is a seal-in latch, network 2 delays the motor command by `startDelayTime` (TON: rung-out true after the delay), network 3 computes the ready flag in SCL.

Seen in exports: trailing semicolons in the interface, `IEC_TIMER` as the instance type, `.TON(...)` with `time_type` (not the `timeType` of the LAD document) and `et =>` followed by two spaces when unconnected (8.14b).

## Appendix B: quick reference — documented instruction set

Contacts: `Contact`, `I_Contact`, `P_Contact`, `N_Contact`, `OK`, `NOK`, `IS_ARRAY`, `IS_NULL`, `NOT_NULL`, `EQ/NE/LT/GT/LE/GE_Contact`, `EQ/NE_TypeContact`, `EQ/NE_ElemTypeContact`, `EQ/NE_TypeOfDBContact`.

Coils: `Coil`, `I_Coil`, `S_Coil`, `R_Coil`, `P_Coil`, `N_Coil`, `CU_Coil`, `CD_Coil`, `RT_Coil`, `JumpCoil`, `I_JumpCoil`, `ReturnCoil`, `CallCoil`, `TP_Coil`, `TON_Coil`, `TOF_Coil`, `TONR_Coil`, `SP_Coil`, `SE_Coil`, `SD_Coil`, `SS_Coil`, `SF_Coil`, `PT_Coil`, `SC_Coil`, `R_BitfieldCoil`, `S_BitfieldCoil`.

Boxes and others: `Not`, math ENO boxes (`Add`, `Mul`, `Move`, `Convert`, ...), `Calculate`, FC/FB calls, flip-flops `S_RS`/`S_SR` (instance form), IEC timers `TP`/`TON`/`TOF`/`TONR` (instance form), S5 timers `Sp`/`Se`/`Sd`/`Ss`/`Sf`, IEC counters `CTU`/`CTD`/`CTUD` (instance form), S5 counters `Cu`/`Cd`/`Cud`, `Label`, `JumpList`, `Switch`, `Return`/`ReturnTrue`/`ReturnFalse`.

Templates in the exports: `SrcType`, `DestType`, `time_type`, `value_type`, `count_type`, `src_type`, `dest_type`, `return_type`. The LADDER Format Description's `valueType`, `timeType`, `countType`, `inType`/`outType` are not what TIA exports.

---

Source documents: Siemens Entry ID 109994073 "SIMATIC Source Documents - LADDER Format Description" V1.0 2025-09; SIMATIC TIA Portal V20 Update 4/5 readmes (A5E54260417).
