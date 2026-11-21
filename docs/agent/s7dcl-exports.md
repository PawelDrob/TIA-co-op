---
type: Guide
title: "SIMATIC SD guide: what exports showed"
description: "What TIA Portal V20 exports of SIMATIC SD (.s7dcl, .s7res) files showed: instruction names, library and F-LAD instructions, DB, UDT and member shapes, the .s7res, and the import failures found in exported files."
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-21T16:19:37-05:00 }
sources:
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: what exports showed

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): sections 8.13a, 8.14b, 8.14c and 8.14d, the catalogues taken from exports. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

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
