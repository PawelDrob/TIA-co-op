"""The system instructions the report knows: per instruction its raw names in the two export formats, and what TIA's LAD
editor draws for it: form, title, rung pins, pins in their order and on their side, in-out marks, type line.

Evidence: one network per instruction on a CPU 1515F in TIA Portal V20 Update 7, exported as SimaticML and as .s7dcl,
against TIA's own screen; the help only where the screen leaves it open, as a type no export holds. TIA's screen wins over
both the exports and the help. Mixed case follows TIA (Ret_Val on some boxes, RET_VAL on others).

The boxes of the extended instructions are generated from their exports (instructions_extended), those of Communication too
(instructions_communication). A type line is a fact per box, in no export: boxes with the same templates differ (RD_REC Variant,
WR_REC none). It comes from TIA's screen, else the help's drawings; a box neither shows keeps what the general box draws. An in-out
mark of the extended boxes comes from the same; of Communication, Technology and the Optional packages from the instance's sections
in SimaticML, which agree with TIA's screen wherever a screen shows the pin; an FC has no sections, so its in-outs from the screen.

An instruction that exports as a call of a block no project export holds (PID_Compact) draws as a call: its title in quotes, its
pins as the export writes them, its in-outs from CALL_IN_OUTS, for an instance of that type written without quotes.

An F-box shares the entry of its standard box where TIA draws them alike (TON, CTU, SR); the F-library boxes are generated too (instructions_safety). Their .s7dcl writes only
the cards of an F-box, not the type it imports with: F_TYPES holds what TIA's screen draws.

A name is exact: the legacy SCALE is another instruction than Scale. An instruction not here is drawn as the general box:
its name and pins in capitals, EN and ENO, its sides from what its export says.
"""
from dataclasses import dataclass, field
from typing import Optional

from .instructions_communication import CALL_IN_OUTS, COMMUNICATION
from .instructions_extended import EXTENDED
from .instructions_safety import SAFETY, UNSHOWN_LINES as UNSHOWN_F

EN_ENO = ('EN', 'ENO')
UNNAMED = '#'                    # the alias of a pin .s7dcl writes without a name: 'Inc( x )'


@dataclass(frozen=True)
class Pin:
    tia: str                     # as TIA's screen writes it
    side: str                    # 'in', 'io' (TIA's two-way arrow, on the left), 'out'
    aliases: tuple = ()          # raw names in the exports other than tia; the first the .s7dcl's, UNNAMED for none


@dataclass(frozen=True)
class Instruction:
    title: str
    form: str = 'box'            # 'box', 'contact', 'coil'
    rung: tuple = EN_ENO         # the pins on the rung as TIA writes them; '' for none
    pins: tuple = ()             # the pins whose name, side or place is a fact to tell; others: upper case, in export order, a rung pin first
    sd: str = ''                 # the .s7dcl's name, where the SimaticML part has another
    above: str = ''              # the pin whose operand TIA writes above the box
    types: tuple = ()            # SimaticML templates that make its type line (the others TIA does not draw)
    pair: Optional[tuple] = None  # the type line in two cells: (template, what stands between, template)
    fixed: dict = field(default_factory=dict)  # a type the export may leave out and the instruction fixes: {template: type}
    line: Optional[tuple] = None  # the only templates its type line shows, () none; None: every one the export has
    second: str = ''             # a template TIA writes in a cell of its own under the type (T_COMP's relation)

    def pin(self, name):
        """The Pin of a raw name (any case; None: the unnamed one), None when it is no fact here."""
        raw = UNNAMED if name is None else name.lower()
        return next((p for p in self.pins if raw == p.tia.lower() or raw in (a.lower() for a in p.aliases)), None)

    def label(self, name):
        """A pin's name as TIA writes it."""
        p = self.pin(name)
        return p.tia if p else (name or '').upper()

    def order(self, name):
        """Where a pin stands on its side: a rung pin not told first, those told in their order, the others after them."""
        p = self.pin(name)
        if p:
            return self.pins.index(p)
        return -1 if (name or '').lower() in (r.lower() for r in self.rung if r) else len(self.pins)

    def reads(self, template):
        """Whether a SimaticML template is what the type line is made of."""
        return template in self.types or template in (self.line or ()) or template == self.second

    def rung_pin(self, end, wired):
        """The name in `wired` (raw names) of the rung-in (end 0) or rung-out (end 1) pin, None when none of them is it."""
        want = self.rung[end].lower()
        return next((n for n in wired if want and n.lower() == want), None)


def _pins(ins='', ios='', outs=''):
    """'SRC_ARRAY=srcArray POS' -> Pins: TIA's name, '=' the raw names it has beside it, ',' between them."""
    out = []
    for side, text in (('in', ins), ('io', ios), ('out', outs)):
        for spec in text.split():
            tia, _, aliases = spec.partition('=')
            out.append(Pin(tia, side, tuple(a for a in aliases.split(',') if a)))
    return tuple(out)


def _seq(prefix, first, last):
    return ' '.join('%s%d' % (prefix, k) for k in range(first, last + 1))


def _boxes(names, **kw):
    """Boxes whose title is their name in capitals: EN / ENO, pins upper case."""
    return {n: Instruction(n.upper(), **kw) for n in names.split()}


CATALOGUE = {}
CATALOGUE.update(_boxes(
    'Add Sub Mul Div Mod Neg Abs MIN MAX Sqr Sqrt Ln Exp Sin Cos Tan Asin Acos Atan Frac Expt Move Swap Lower_Bound '
    'Upper_Bound Round Ceil ceil Floor Trunc trunc And Or Xor Inv Mux Demux Shr Shl Ror Rol SEG RE_TRIGR STP WAIT '
    'LEAD_LAG BCDCPL R_TRIG F_TRIG Calculate'))
# Logic on a pin gets no place from SimaticML's wires, so these and the counters, BO_W and W_BO below hold the order of their .s7dcl exports.
# Not Mux, Demux, Move, FILL_BLK, UFILL_BLK: the networks made for this did not go through import and compile on V20 Update 7, so they have no such order.
# On a CPU 1515F, Mux, Demux and Move refuse the type Bool; FILL_BLK and UFILL_BLK take it on operands and refuse logic on IN (s7dcl guide 8.13b). Other CPU families and the editor were not tried.
CATALOGUE.update({
    'SEL': Instruction('SEL', pins=_pins('G IN0 IN1', outs='OUT')),
    'DCAT': Instruction('DCAT', pins=_pins('CMD O_FB C_FB', outs='Q OA CA')),
    'MCAT': Instruction('MCAT', pins=_pins('O_CMD C_CMD S_CMD O_FB C_FB', outs='OO CO OA CA Q')),
})
CATALOGUE.update({
    # conversion: two types, each in a cell of its own
    'Convert': Instruction('CONV', pair=('SrcType', 'to', 'DestType')),
    'Normalize': Instruction('NORM_X', pair=('SrcType', 'to', 'DestType')),
    'Scale': Instruction('SCALE_X', pair=('SrcType', 'to', 'DestType')),
    'DECO': Instruction('DECO', types=('value_type', 'return_type'), pair=('value_type', 'to', 'return_type'),
                        fixed={'value_type': 'UInt'}),     # .s7dcl: the target alone; IN is UInt (help)
    'ENCO': Instruction('ENCO', types=('src_type',)),
    # jumps
    'JumpList': Instruction('JMP_LIST', rung=('EN', '')),
    'Switch': Instruction('SWITCH', rung=('EN', '')),
    # the rung through the box
    'InRange': Instruction('IN_RANGE', rung=('', ''), pins=_pins('MIN VAL=in MAX')),
    'OutRange': Instruction('OUT_RANGE', rung=('', ''), pins=_pins('MIN VAL=in MAX')),
    'P_Trig': Instruction('P_TRIG', rung=('CLK', 'Q')),
    'N_Trig': Instruction('N_TRIG', rung=('CLK', 'Q')),
    'S_SR': Instruction('SR', rung=('S', 'Q'), above='operand'),
    'S_RS': Instruction('RS', rung=('R', 'Q'), above='operand'),
    # IEC timers and counters
    'TP': Instruction('TP', rung=('IN', 'Q')),
    'TON': Instruction('TON', rung=('IN', 'Q')),
    'TOF': Instruction('TOF', rung=('IN', 'Q')),
    'TONR': Instruction('TONR', rung=('IN', 'Q')),
    'CTU': Instruction('CTU', rung=('CU', 'Q'), pins=_pins('CU R PV', outs='Q CV')),
    'CTD': Instruction('CTD', rung=('CD', 'Q'), pins=_pins('CD LD PV', outs='Q CV')),
    'CTUD': Instruction('CTUD', rung=('CU', 'QU'), pins=_pins('CU CD R LD PV', outs='QU QD CV')),
    # math
    'Inc': Instruction('INC', pins=_pins(ios='IN/OUT=#,operand')),
    'Dec': Instruction('DEC', pins=_pins(ios='IN/OUT=#,operand')),
    'Limit': Instruction('LIMIT', pins=_pins('MN=min IN MX=max')),
    # move
    'MoveBlockI': Instruction('MOVE_BLK'),
    'MoveBlockU': Instruction('UMOVE_BLK'),
    'FillBlockI': Instruction('FILL_BLK'),
    'FillBlockU': Instruction('UFILL_BLK'),
    'Deserialize': Instruction('Deserialize', pins=_pins('SRC_ARRAY=srcArray', 'POS', 'Ret_Val DEST_VARIABLE=dstVariable')),
    'Serialize': Instruction('Serialize', pins=_pins('SRC_VARIABLE=srcVariable', 'POS', 'Ret_Val DEST_ARRAY=dstArray')),
    'MoveBlockVariant': Instruction('MOVE_BLK_VARIANT', pins=_pins('SRC COUNT SRC_INDEX=srcIndex DEST_INDEX=dstIndex',
                                                                   outs='Ret_Val DEST=dst')),
    'AssignAttempt': Instruction('?=', types=('src_type',)),
    'SCATTER': Instruction('SCATTER', types=('src_type',)),
    'GATHER': Instruction('GATHER', types=('dest_type',)),
    'ScatterBlock': Instruction('SCATTER_BLK', pins=_pins('IN COUNT_IN=countIn', outs='OUT'), types=('src_type', 'count_type'),
                                pair=('src_type', 'count:', 'count_type')),
    'GatherBlock': Instruction('GATHER_BLK', pins=_pins('IN COUNT_OUT=countOut', outs='OUT'), types=('dest_type', 'count_type'),
                               pair=('dest_type', 'count:', 'count_type')),
    'ReadFromArrayDB': Instruction('ReadFromArrayDB', pins=_pins('db index', outs='Ret_Val value')),
    'WriteToArrayDB': Instruction('WriteToArrayDB', pins=_pins('db index value', outs='Ret_Val')),
    'ReadFromArrayDBL': Instruction('ReadFromArrayDBL', pins=_pins('req db index', 'value', 'busy done error')),
    'WriteToArrayDBL': Instruction('WriteToArrayDBL', pins=_pins('req db index value', outs='busy done error')),
    'VariantGet': Instruction('VariantGet'),
    'VariantPut': Instruction('VariantPut'),
    'CountOfElements': Instruction('CountOfElements', pins=_pins('IN', outs='RET_VAL')),
    'FieldRead': Instruction('FieldRead'),
    'FieldWrite': Instruction('FieldWrite'),
    'S_BlockMove': Instruction('BLKMOV', pins=_pins('SRCBLK=srcBlock', outs='RET_VAL DSTBLK=dstBlock'), types=('blk_type',),
                               fixed={'blk_type': 'Variant'}),
    'SU_BlockMove': Instruction('UBLKMOV', pins=_pins('SRCBLK=srcBlock', outs='RET_VAL DSTBLK=dstBlock'), types=('ptr_type',),
                                fixed={'ptr_type': 'Variant'}),
    'S_Fill': Instruction('FILL', pins=_pins('BVAL', outs='RET_VAL BLK'), types=('ptr_type',), fixed={'ptr_type': 'Variant'}),
    'S_Scale': Instruction('SCALE', pins=_pins('IN HI_LIM=hiLim LO_LIM=loLim BIPOLAR', outs='RET_VAL OUT')),
    'S_Normalize': Instruction('UNSCALE', pins=_pins('IN HI_LIM=hiLim LO_LIM=loLim BIPOLAR', outs='RET_VAL OUT')),
    # program control
    'GetError': Instruction('GET_ERROR'),
    'GetErrorID': Instruction('GET_ERR_ID', pins=_pins(outs='ID=error')),
    'INIT_RD': Instruction('INIT_RD', pins=_pins('REQ', outs='Ret_Val')),
    'Runtime': Instruction('RUNTIME', pins=_pins(ios='MEM', outs='Ret_Val')),
    'ENDIS_PW': Instruction('ENDIS_PW', pins=_pins('REQ F_PWD FULL_PWD R_PWD HMI_PWD',
                                                   outs='Ret_Val F_PWD_ON FULL_PWD_ON R_PWD_ON HMI_PWD_ON')),
    # legacy
    'DRUM': Instruction('DRUM', pins=_pins('RESET JOG DRUM_EN LST_STEP ' + _seq('EVENT', 1, 16),
                                           outs=_seq('OUT', 1, 16) + ' Q OUT_WORD ERR_CODE')),
    'IMC': Instruction('IMC', pins=_pins(_seq('IN_BIT', 0, 15) + ' CMP_STEP', outs='OUT ERR_CODE')),
    'SMC': Instruction('SMC', pins=_pins(_seq('IN_BIT', 0, 15), outs='OUT OUT_STEP ERR_CODE')),
    'BITSUM': Instruction('BITSUM', pins=_pins('IN', outs='Ret_Val')),
    # contacts that write their name: the operand above, the second one below
    'OK': Instruction('OK', 'contact', ('', '')),
    'NOK': Instruction('NOT_OK', 'contact', ('', '')),
    'IS_NULL': Instruction('IS_NULL', 'contact', ('', '')),
    'NOT_NULL': Instruction('NOT_NULL', 'contact', ('', '')),
    'IS_ARRAY': Instruction('IS_ARRAY', 'contact', ('', '')),
    'EQ_TypeContact': Instruction('EQ_Type', 'contact', ('', '')),
    'NE_TypeContact': Instruction('NE_Type', 'contact', ('', '')),
    'EQ_ElemTypeContact': Instruction('EQ_ElemType', 'contact', ('', '')),
    'NE_ElemTypeContact': Instruction('NE_ElemType', 'contact', ('', '')),
    'EQ_TypeOfDBContact': Instruction('EQ_TypeOfDB', 'contact', ('', '')),
    'NE_TypeOfDBContact': Instruction('NE_TypeOfDB', 'contact', ('', '')),
})

_S5_TIMER = _pins('TV R', outs='BI=RT BCD=RTBCD')
for _sd, _title in (('Sp', 'S_PULSE'), ('Se', 'S_PEXT'), ('Sd', 'S_ODT'), ('Ss', 'S_ODTS'), ('Sf', 'S_OFFDT')):
    CATALOGUE[_sd] = Instruction(_title, rung=('S', 'Q'), pins=_S5_TIMER, above='Top')
for _sd, _title, _rung, _ins in (('Cu', 'S_CU', 'CU', 'S PV R'), ('Cd', 'S_CD', 'CD', 'S PV R'), ('Cud', 'S_CUD', 'CU', 'CD S PV R')):
    CATALOGUE[_sd] = Instruction(_title, rung=(_rung, 'Q'), pins=_pins(_ins, outs='CV CV_BCD=CVBCD'), above='Top')

# The type lines of the extended and Communication boxes, from TIA's screen, else the help's drawings: {title: (line, pair, second, fixed)}. A type
# the .s7dcl leaves out is fixed. Any other extended box has none.
_TO = ('src_type', 'TO', 'dest_type')
_PTR = ('ptr_type',)
_VARIANT = {'ptr_type': 'Variant'}
_DATE = ('date_type',)
_STR = ('str_type',)
EXTENDED_TYPES = {
    'T_COMP': (_DATE, None, 'relation', {}), 'S_COMP': (('src_type',), None, 'relation', {}),
    'T_CONV': (None, _TO, '', {}), 'S_CONV': (None, _TO, '', {}), 'STRG_VAL': (None, _TO, '', {}),
    'VAL_STRG': (None, ('value_type', 'TO', 'str_type'), '', {}),
    'T_ADD': (None, ('date_type', 'PLUS', 'time_type'), '', {}), 'T_SUB': (None, ('date_type', 'MINUS', 'time_type'), '', {}),
    'T_DIFF': (None, ('date_type', 'TO', 'time_type'), '', {}), 'T_COMBINE': (None, ('time_type', 'TO', 'date_type'), '', {}),
    'WR_SYS_T': (_DATE, None, '', {}), 'RD_SYS_T': (_DATE, None, '', {}), 'RD_LOC_T': (_DATE, None, '', {}),
    'WR_LOC_T': (('loctime_type',), None, '', {}), 'Strg_TO_Chars': (('strg_type',), None, '', {}),
    'Chars_TO_Strg': (_STR, None, '', {}), 'MAX_LEN': (('SrcType',), None, '', {}), 'MID': (('value_type',), None, '', {}),
    'LEN': (_STR, None, '', {}), 'CONCAT': (_STR, None, '', {}), 'LEFT': (_STR, None, '', {}), 'RIGHT': (_STR, None, '', {}),
    'DELETE': (_STR, None, '', {}), 'INSERT': (_STR, None, '', {}), 'REPLACE': (_STR, None, '', {}), 'FIND': (_STR, None, '', {}),
    'READ_DBL': (('src_type',), None, '', {'src_type': 'Variant'}), 'WRIT_DBL': (('src_type',), None, '', {'src_type': 'Variant'}),
    'S_MOVE': (None, ('src_type', 'to', 'dest_type'), '', {}),
    'RDREC': (_PTR, None, '', _VARIANT), 'WRREC': (_PTR, None, '', _VARIANT), 'RD_REC': (_PTR, None, '', _VARIANT),
    'RD_DPAR': (_PTR, None, '', _VARIANT), 'RD_DPARA': (_PTR, None, '', _VARIANT),
    'RD_DPARM': (('record_type',), None, '', {'record_type': 'Variant'}),
    'USEND': (_PTR, None, '', _VARIANT), 'URCV': (_PTR, None, '', _VARIANT),
    'BSEND': (_PTR, None, '', _VARIANT), 'BRCV': (_PTR, None, '', _VARIANT),
    'GET': (None, ('remote_type', '-', 'local_type'), '', {'remote_type': 'Remote', 'local_type': 'Variant'}),
    'PUT': (None, ('remote_type', '-', 'local_type'), '', {'remote_type': 'Remote', 'local_type': 'Variant'}),
    'SCALE': (('value_type',), None, '', {}),
}
_EXTENDED_XML = {}
for _title, _xml, _sd, _ins, _ios, _outs in EXTENDED + COMMUNICATION + SAFETY:
    _line, _pair, _second, _fixed = EXTENDED_TYPES.get(_title, (None if _title in UNSHOWN_F else (), None, '', {}))
    _spec = Instruction(_title, pins=_pins(_ins, _ios, _outs), pair=_pair, second=_second, fixed=_fixed,
                        line=(_pair[0], _pair[2]) if _pair else _line)
    CATALOGUE[_sd] = _spec
    if _xml != _sd:
        _EXTENDED_XML[_xml] = _sd

# SimaticML part -> the .s7dcl's name, where they differ; pins it writes under another name than the .s7dcl {pin: pin}
XML_NAMES = {
    'Eq': 'EQ_Contact', 'Ne': 'NE_Contact', 'Lt': 'LT_Contact', 'Gt': 'GT_Contact', 'Le': 'LE_Contact', 'Ge': 'GE_Contact',
    'SCoil': 'S_Coil', 'RCoil': 'R_Coil', 'PBox': 'P_Trig', 'NBox': 'N_Trig', 'Sr': 'S_SR', 'Rs': 'S_RS',
    'ResetIECTimerCoil': 'RT_Coil', 'PContact': 'P_Contact', 'NContact': 'N_Contact', 'PCoil': 'P_Coil', 'NCoil': 'N_Coil',
    'Calc': 'Calculate', 'JmpList': 'JumpList', 'PtCoil': 'PT_Coil', 'ScCoil': 'SC_Coil', 'CuCoil': 'CU_Coil',
    'CdCoil': 'CD_Coil', 'RBitfield': 'R_BitfieldCoil', 'SBitfield': 'S_BitfieldCoil',
    'EQ_Type': 'EQ_TypeContact', 'NE_Type': 'NE_TypeContact', 'EQ_ElemType': 'EQ_ElemTypeContact',
    'NE_ElemType': 'NE_ElemTypeContact', 'EQ_TypeOfDB': 'EQ_TypeOfDBContact', 'NE_TypeOfDB': 'NE_TypeOfDBContact',
    'CoilTP': 'TP_Coil', 'CoilTON': 'TON_Coil', 'CoilTOF': 'TOF_Coil', 'CoilTONR': 'TONR_Coil',
    'SpCoil': 'SP_Coil', 'SeCoil': 'SE_Coil', 'SdCoil': 'SD_Coil', 'SsCoil': 'SS_Coil', 'SfCoil': 'SF_Coil',
    'Jump': 'JumpCoil', 'JumpNot': 'I_JumpCoil', 'ReturnValue': 'ReturnCoil',
    'Scale_X': 'Scale', 'Rr': 'Ror', 'Rl': 'Rol', 'LIMIT': 'Limit', '?=': 'AssignAttempt', 'MOVE_BLK_VARIANT': 'MoveBlockVariant',
    'SCATTER_BLK': 'ScatterBlock', 'GATHER_BLK': 'GatherBlock', 'BLKMOV': 'S_BlockMove', 'UBLKMOV': 'SU_BlockMove',
    'FILL': 'S_Fill', 'SCALE': 'S_Scale', 'UNSCALE': 'S_Normalize',
}
XML_NAMES.update(_EXTENDED_XML)
# Two types in cells of their own, as on TIA's screen; a .s7dcl holds only the cards: F_TYPES
for _title, _box_pins in (('BO_W', _pins(_seq('IN', 0, 15), outs='OUT')), ('W_BO', _pins('IN', outs=_seq('OUT', 0, 15)))):
    CATALOGUE[_title] = Instruction(_title, pair=('src_type', 'to', 'dest_type'), line=('src_type', 'dest_type'), pins=_box_pins)
CATALOGUE.update(Ctu=CATALOGUE['CTU'], Ctd=CATALOGUE['CTD'], Ctud=CATALOGUE['CTUD'])     # one instruction each, two spellings
CATALOGUE['S_Move'] = CATALOGUE['S_MOVE']     # one instruction: older .s7dcl exports write S_Move and no template, so no type line
_TIMER_COIL = {'operand': 'timer', 'value': 'pt'}
XML_PINS = {'SP_Coil': _TIMER_COIL, 'SE_Coil': _TIMER_COIL, 'SD_Coil': _TIMER_COIL, 'SS_Coil': _TIMER_COIL, 'SF_Coil': _TIMER_COIL,
            'TP_Coil': _TIMER_COIL, 'TON_Coil': _TIMER_COIL, 'TOF_Coil': _TIMER_COIL, 'TONR_Coil': _TIMER_COIL,
            'PT_Coil': {'operand': 'timer', 'pt': 'PT'}, 'SC_Coil': {'operand': 'counter', 'value': 'pv'}}
XML_PINS.update({n: {'timer': 'Top'} for n in ('Sp', 'Se', 'Sd', 'Ss', 'Sf')})
XML_PINS.update({n: {'counter': 'Top'} for n in ('Cu', 'Cd', 'Cud')})

# The type of an F-box, on TIA's screen. SimaticML holds it, an F-box's .s7dcl does not. It is the only one: TIA's compile refuses another on CTU, TON, SHR (DInt, LTime, DWord:
# the formal parameter stays Int, Time, Word), so their families are taken as the same; the help has one type for each. SCALE: on the screen, not tried in TIA.
F_TYPES = {'TP': {'time_type': 'Time'}, 'TON': {'time_type': 'Time'}, 'TOF': {'time_type': 'Time'}, 'CTU': {'value_type': 'Int'}, 'CTD': {'value_type': 'Int'},
           'CTUD': {'value_type': 'Int'}, 'SHR': {'value_type': 'Word'}, 'SHL': {'value_type': 'Word'}, 'SCALE': {'value_type': 'Int'},
           'BO_W': {'src_type': 'Bool', 'dest_type': 'Word'}, 'W_BO': {'src_type': 'Word', 'dest_type': 'Bool'}}


def f_templates(instr, pragmas):
    """What the type template of an F-box is when nothing else says: the pragma in front of it (a .s7dcl names only an F-box's cards there), else the table; {} for
    any other element. The caller fills only what is empty."""
    if instr not in F_TYPES or not any(k.startswith('f_') and k.endswith('_card') for k in pragmas):
        return {}
    return {template: pragmas.get(template, typ) for template, typ in F_TYPES[instr].items()}


# What a contact shows by a symbol or not at all, what a coil shows inside it by its own table: no name to write.
SYMBOL_CONTACTS = ('Contact', 'I_Contact', 'P_Contact', 'N_Contact', 'Not')


def lookup(instr):
    """The Instruction of an element's name (exact), None when the report does not know it."""
    return CATALOGUE.get(instr)


def call_in_outs(block):
    """The in-out pins, lower case, of a call of this system block; empty for any other."""
    return {p.lower() for p in CALL_IN_OUTS.get(block, ())}


def form(instr):
    """'box', 'contact' or 'coil' when known, else None."""
    spec = CATALOGUE.get(instr)
    return spec.form if spec else None


def sd_name(part):
    """The .s7dcl's name of a SimaticML part."""
    return XML_NAMES.get(part, part)


def sd_pin(instr, pin):
    """The .s7dcl's name of a pin of a SimaticML part (instr: its .s7dcl name)."""
    known = XML_PINS.get(instr, {}).get(pin.lower())
    if known:
        return known
    spec = CATALOGUE.get(instr)
    p = spec.pin(pin) if spec else None
    return p.aliases[0] if p and p.aliases and p.aliases[0] != UNNAMED else pin


def unnamed_pin(instr, pin):
    """A pin of a SimaticML part the .s7dcl writes without a name."""
    spec = CATALOGUE.get(instr)
    p = spec.pin(pin) if spec else None
    return bool(p and p.aliases and p.aliases[0] == UNNAMED)


def contact_text(instr):
    """What a contact writes between its bars, '' for one drawn by its symbol: an instruction the report does not know
    keeps its raw name, so a check never reads as a bit."""
    if instr in SYMBOL_CONTACTS:
        return ''
    spec = CATALOGUE.get(instr)
    return spec.title if spec else instr
