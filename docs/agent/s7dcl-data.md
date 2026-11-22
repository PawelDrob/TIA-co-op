---
type: Guide
title: "SIMATIC SD guide: blocks, interfaces and data as exports write them"
description: "How TIA Portal V20 exports write SIMATIC SD block headers, interfaces, data types, DBs, start values and retain, and how a classic SCL source maps to SD."
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T19:16:55-05:00 }
sources:
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: blocks, interfaces and data as exports write them

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): sections 8.14b: blocks, interfaces and data, 8.14d, read for a DB, a data type, a classic SCL source; an SCL block, an SCL block calling a library, communication, Technology or F instruction, a LAD block, an F-block when it declares a multi-instance of an FB imported in this session; a comment or title when a member's comment is new, for its pragma; an import or SD export that fails when the log message's row names it. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

### 8.14b Shapes seen in exports `[EXPORT]`: blocks, interfaces and data

Its other items: [LAD](s7dcl-lad.md), [resource files](s7dcl-resources.md).

- Structured operands quoted where a member name is a keyword: `#ioPanel.command."sequence".cancel`.
- The export quotes member names that are keywords or look like them, wherever they occur (project A, V20 Update 7, 2026-10-29): written unquoted, imported, exported as `"a" : Bool;`, `"b"`, `"c"`, `"limit" : Int := 12;`, also in start values (`dev1."limit" := 7;`, `"limit" := 3;`). Both forms import; adopt the quoted one after a round trip.
- Global DB access from inside a block: `"GxxSlotStatus".fg[#tFg].bay[#tBay].ws.exist`.
- Interface pragma block per member: `{ S7_Access := "ReadOnly := External"; S7_Visibility := "Hidden := External" }`, optional `S7_MLC := "MLC_xxx"` for the comment id, `S7_Setpoint := "False"` on instances/timers. No `S7_Setpoint` is not false everywhere. Against the exports, TIA ticks the box on an FB instance, of a system FB or of the project, and on a UDT instance in a static of a standard FB; on a UDT instance in a global DB and in a UDT; on `TCON_Param` and `OPC_UA_SessionConnectInfo` in a global DB. It leaves it empty on elementary types and on `DB_WWW` and `PORT` in a global DB `[EXPORT]` (test project, seen in TIA, 2026-11-04). SimaticML of the same blocks writes false on `DTL` and an array of an elementary type, and on every instance in an F-FB `[EXPORT]`. Not seen in TIA: other system types in a DB, an array of a structured type (the one SimaticML seen with a setting on one says true: `CMD_buf` in `Write_Tagfield` `[EXPORT]`), an input or output of a UDT, and an F-block's instances. `DB_DYN`, `PIP` and `RTM` go as `DB_WWW` and `PORT` by their names only `[INFERRED]`. A released library type's export writes no `S7_Setpoint` at all, so there its absence says nothing `[EXPORT]`. A version just put in work writes none either; written as `"False"` into its document and imported, it comes back in the next export of that version `[PROBE]`. Whether a group-level pragma propagates to members is unverified; exports write it on every member.
- UDT file: `TYPE` / `typeName : STRUCT ... END_STRUCT;` / `END_TYPE`, members with the same pragma blocks, nested `_.typeOther` references.
- DB file: `{ S7_Optimized := "TRUE"; S7_StandardRetain := "FALSE"; S7_Version := "0.1" }` / `DATA_BLOCK name` / one or more `VAR` and `VAR RETAIN` sections / start values after the declarations as `name.member[1].x := 1.0;` lines / `END_DATA_BLOCK`.
- Global DB start value paths (projects A, B and C exports, 2026-10): a member of a `STRUCT` (`maxTime.timeout := T#600ms;`), an array element (`pos[1] := 6268;`), a member of a UDT member (`"left".homePos.xPos[3] := 410;`), an array of UDTs (`Index[0].Unit.Column := 0;`), any depth (`conn[3].connectionSetup.ConnPara.RemoteAddress.ADDR[1] := 192;`). Imported: `speed := 100;` and `dev1."limit" := 5;` (a UDT member) in `zzE2eGlobalDb` (project A, 2026-10-29).
- Comment of an inner member without a start value: the `S7_MLC` pragma, then the path with `:= ();`: `{ S7_MLC := "MLC_G5" }` / `dev2.flag := ();`. Seen in global DBs (projects B/C `StopDb`: `"Z00+RC01-QA500".q := ();`) and in a DB of a UDT (projects B/C `GxxFaultAndMode`: `fg[0].warning[40] := ();`). Imported: `StopDb` (projects B and C, 2026-10-21/22) and `zzE2eGlobalDb` `dev2.flag` (project A, 2026-10-29). Its id counts in the `.s7res` like any other.
- FB header: `S7_BlockTitle`, `S7_GenerateENOforSCL`, `S7_IECCheck`, `S7_Optimized`, `S7_PreferredLanguage`, `S7_Version` in the leading pragma block.
- Timer instance type in the interface: `IEC_TIMER`.
- FC header (V20 Upd7): `FUNCTION "PressureSwitchP1" : Void`, same pragma block as an FB; an SCL FC with only comments (`Customer_Description`) imports and exports. OB header: `ORGANIZATION_BLOCK "CyclicInterrupt"` with `S7_BlockTitle`, `S7_PreferredLanguage`, `S7_Version`; no event class, no number.
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
