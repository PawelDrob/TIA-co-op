---
type: Guide
title: "SIMATIC SD guide: LAD networks"
description: "How LAD networks are written in SIMATIC SD (.s7dcl) files for TIA Portal V20: rungs, wires, contacts, coils, boxes, calls, program control and the Calculate box, with a complete example block and the instruction set."
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-22T02:42:50-05:00 }
sources:
  - id: lad-doc
    resource: https://support.industry.siemens.com/cs/ww/en/view/109994073
    title: SIMATIC Source Documents - LADDER Format Description V1.0 (2025-09)
    author: team:siemens
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: LAD networks

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): sections 8, 8.1 to 8.13, 8.13b, 8.14a, 8.14b: LAD, 8.14c: branch shapes and LAD operands, 8.14, Appendix A, Appendix B, read for a LAD block, an F-block; any other change of an OB when the change adds or changes a `MUX`, `DEMUX` or `MOVE` box with Bool operands, logic on a box pin other than its input on the rung, or a coil on a box output other than the output on the rung; an import or SD export that fails when the log message's row names it. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

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
| `{ S7_GenerateENO := "TRUE" }` | The following box computes a real ENO. On a box with TIA's ENO setting (8.10) the export writes it where ENO is generated and writes nothing where it is not (ENO := EN) `[EXPORT]`. |
| `{ S7_Expression := "..." }` | Stores the expression of a `Calculate` box, using the formal names; the export writes them `IN1`, `IN2`, ... (8.14) |
| `{ CASE0 := "==" }` | The relation of a `Switch` case, one per case, beside its `S7_Templates` (8.13) `[EXPORT]` |

Combined pragma list (semicolon-separated), placed immediately before the instruction it affects:

```
{
    S7_Templates := "SrcType := SInt";
    S7_GenerateENO := "TRUE"
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
- ENO generation is a setting of some boxes: math, move, conversion, string, word logic, shift and rotate, `Calculate` (the list: `ENO_SETTING` in `TiaChangeReports\instructions.py`). Off, ENO := EN, and TIA draws ENO gray, with a line from EN through the box. The export writes `{ S7_GenerateENO := "TRUE" }` on such a box where it is on and nothing where it is off `[EXPORT]`; its SimaticML, and the boxes that carry neither the pragma nor `DisabledENO`: [openness-plc-blocks.md](openness-plc-blocks.md), section 1, Boxes in an OB's SimaticML. The change report draws the ENO of those boxes black, and reads the pragma written on one of them or taken away as a change. Switch it on with `{ S7_GenerateENO := "TRUE" }` (see 8.6).
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

On an absolute address (`Top := %T1`) this imports, and then the compile refuses it: *A constant not permitted here.* A symbol was not tried. Its SimaticML: [openness-plc-blocks.md](openness-plc-blocks.md), section 1, Boxes in an OB's SimaticML.

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

The SD export writes `Label(name)` (no blanks) on the line after `NETWORK`. The SimaticML export of the same networks in an OB: [openness-plc-blocks.md](openness-plc-blocks.md), section 1, Boxes in an OB's SimaticML.

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

### 8.14b Shapes seen in exports `[EXPORT]`: LAD

Its other items: [resource files](s7dcl-resources.md), [blocks, interfaces and data](s7dcl-data.md).

- Timers: instance role, template pragma is `{ S7_Templates := "time_type := Time" }` (not `timeType`); unconnected `et` written as `et =>  ` with trailing spaces: `#statTimer.x.TON( pt := #CONST, et =>  )`.
- Comparators: `EQ_Contact`, `NE_Contact`, `LT_Contact`, `GT_Contact`, `GE_Contact` with `{ S7_Templates := "SrcType := DInt" }` (or `Time`, `LReal`) and `in1 :=`, `in2 :=`.
- Flip-flop: `S_SR( operand := #statLatch, r1 := wire#w3 )` with the rung-in as set; `S_RS` mirrored.
- `Move( in := ..., out1 => ..., out2 => ... )`, `Add( in1 :=, in2 :=, out => )`.
- Empty separator network: `RUNG wire#powerrail` / `END_RUNG` with nothing in between imports.
- Call boxes come back with their parameters in the order inputs, in-outs, outputs, whatever order the import had (`inEnable`, `inValue`, `outActive`, `outValue`, `ioState` written; `ioState` exported before `outActive`).

### 8.14c Import failures from resource files and branch shapes `[EXPORT]`: branch shapes and LAD operands

Its other part: [resource files](s7dcl-resources.md). The section's first paragraph, the source of both parts, stands in both.

Verified by four failed syncs and their fixes (project B, 2026-09-23, TIA Portal V20). Every defect of those four was in a file **written by TIA's own export** (possibly after the ID add-in had run), not by hand; a file that exported cleanly is not proof that it re-imports.

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

Export of an FB (V20 Update 7, 2026-10-30) `[EXPORT]`: `{ S7_Templates := "SrcType := DInt"; S7_Expression := "(IN1 + IN2) * (IN1 - IN2)" }` before `Calculate( in1 := ..., in2 := ..., in3 := ..., out => ... )`: the export writes the formal names in the expression in upper case, as the editor shows them (`OUT := (IN1 + IN2) * (IN1 - IN2)`). The SimaticML export of the same network in an OB: [openness-plc-blocks.md](openness-plc-blocks.md), section 1, Boxes in an OB's SimaticML.

ENO: the Calculate as placed in the editor has ENO not generated (TIA draws it gray, with a line from EN through the box), and its `.s7dcl` export has no `S7_GenerateENO` pragma `[EXPORT]`. So no pragma = the gray ENO. With ENO generated the export writes `S7_GenerateENO := "TRUE"`, as on any box with the setting (8.10) `[EXPORT]`. Its SimaticML: [openness-plc-blocks.md](openness-plc-blocks.md), section 1, Boxes in an OB's SimaticML.

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
