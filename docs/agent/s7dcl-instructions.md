---
type: Guide
title: "SIMATIC SD guide: instructions as exports write them"
description: "How TIA Portal V20 writes instructions in SIMATIC SD (.s7dcl) and SimaticML where the names differ from its screen, and how extended, communication, Technology, Optional packages and F-LAD instructions go in."
tags: [tia-portal, plc, s7dcl, agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-22T02:42:50-05:00 }
sources:
  - id: export
    resource: TIA Portal V20 workspace exports of project F (2026-08), project B (2026-09), project C (2026-10) and project A (2026-10), with re-imports where stated; a test program with every basic LAD and SCL, every extended, Communication, Technology, Optional packages and F-LAD instruction this CPU takes, on a CPU 1515F, V20 Update 7 (2026-11)
    title: TIA Portal V20 exports
---

# SIMATIC SD guide: instructions as exports write them

Part of the [SIMATIC SD (.s7dcl) authoring guide](s7dcl-format.md): section 8.13a, read for an SCL block calling a library, communication, Technology or F instruction, a LAD block, an F-block; a DB when an instance DB of a library, Technology or F box; any other change of an OB when the change adds or changes a coil of an IEC or S5 timer, a jump or return coil, a type-test contact, or any box but a call of an FB or FC of the program. A section keeps its number in the file that holds it; the table at the head of the guide names the file of a section cited by number, and its section 0 the confidence tags.

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
