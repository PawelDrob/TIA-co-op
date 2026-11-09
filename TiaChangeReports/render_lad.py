"""Draw a LAD network as TIA Portal does, as inline SVG.

Layout (from TIA screenshots at 100%: an FB call, R_TRIG, SR, TON and branches ending on other nodes):
- power rail on the left, no right rail; one rung (text RUNG ... END_RUNG) = one horizontal line; an empty network
  (an empty rung) the rail and a line one cell long;
- a jump label: a gray box one cell wide over the rail, a black line inside its top and bottom edge, the name
  centered; the rail starts under it. A renamed, added or removed label: the box filled with the diff mark;
- every element takes a cell, wire nodes sit at the longest-path column, so elements after a node line up;
- a branch starts under its start node, its elements left-aligned, a line runs on to its end node; branches are
  stacked in the first free band below, vertical connectors at the node columns;
- coils right-aligned at the end of the network; boxes stay where they are in the rung;
- boxes: inputs on the left, outputs on the right, each side with its own row spacing (an output row sits just
  low enough for its operand text); an FB / FC call whose block is in the snapshot: pins in the declaration order
  of its interface, the in-outs on the left below the inputs, marked with a two-way arrow; a call of a system block no
  export holds: in the export's order, the in-outs the catalogue names marked below the inputs; otherwise as written;
  a call box shows the block number and the quoted name in its head, the instance above it and above that the
  instance's comment, else the called block's comment; an unassigned pin shows its default value in gray; the type
  of a box (SrcType, ...) bold in a cell of its own under the title; no add-pin star (the editor's handle, not for
  a report); the conversion mark at an input fed an operand of another elementary type; an open ENO (the rung ends
  at the box) runs on to the network's end in its top rung and ends in a short stub below it;
- as the LAD help draws them: P_TRIG / N_TRIG with CLK and Q on the rung, the edge memory below the box;
  IN_RANGE / OUT_RANGE with the rung through the box, no EN / ENO, pins MIN, VAL, MAX; two types each in a cell of their
  own, 'to' between them (CONV, ROUND, NORM_X, ...), '**' for EXPT; in the coil RET, above it the return value (RLO, TRUE,
  FALSE or its operand). A type in the export's case: TIA's screen writes Time where the help's drawing writes TIME;
- above an operand its comment (purple; a member inside a UDT or a global DB: from the UDT or DB when the snapshot
  holds it; a whole global DB: its number, teal) and its name; compare contacts show the relation and type between the bars, in1 above, in2 below (constant: value
  teal, comment purple, name blue; a literal blue). Names quoted only where TIA shows quotes.
- diff marks as the SCL line diff: square fills without outline, under every line (no wire is cut); an added,
  removed or moved element is filled whole, a changed one only where it changed (its operand, the variable at a pin
  of a box, the name of a pin without one or of one only this version has, the operand above an SR / RS, the name of a
  renamed called block, the head for other templates, the symbol of a contact, compare or coil for another relation,
  type or kind), red before and green after, as a changed SCL line. Each thing has its mark, whatever else changed with
  it. What is drawn otherwise though the element is the same (an operand's comment, a constant's value, a conversion
  mark, the title, number or comment of a call's box) is marked as changed; the network does not count as changed for
  it: the declaration it comes from tells that change.
"""
import re
from html import escape

from . import instructions
from .diff import Graph, RAIL, SINK, changed_params
from .s7dcl import CMP, Rung, _segments, type_name, wire_of

FONT = 11
LINE = 13
CELL = 200               # TIA's cell at 100%, in the units of FONT
X0 = 12                  # power rail
TOP = 8
GAP = 10                 # vertical gap between bands
MAXCMT = 4               # comment lines shown at most

C_WIRE = '#1a1a1a'
C_CMT = '#7b1e6b'
C_VAL = '#13866f'        # value of a constant
C_CST = '#2b6cb0'        # literal, name of a constant
C_DEF = '#8c8c8c'        # default value of an unassigned pin
C_NUM = '#16a0a0'        # block number in a call box head
C_OP = '#1a1a1a'
C_BOX = '#e6e8eb'
C_BOXHEAD = '#d3d7dc'
FILL = {'added': '#e3f4e6', 'removed': '#f9e3e7', 'changed': '#fff3c2', 'moved': '#dfe9f5'}   # as page.py's SCL
C_LABEL = '#dfe0e8'      # jump label box
LABEL_Y = 2              # its top; the rail starts at its bottom
LABEL_H = 30

# Arial advance widths per 1000 em
_W = {c: 556 for c in 'abdeghnopqu0123456789#_$'}
_W.update({c: 500 for c in 'cksvxyzJ'})
_W.update({c: 222 for c in 'ijl'})
_W.update({c: 278 for c in 'ft.,:;[] /\'!I|'})
_W.update({c: 333 for c in 'r()-{}`'})
_W.update({'m': 833, 'w': 722, 'M': 833, 'W': 944, '"': 355, '=': 584, '<': 584, '>': 584, '*': 389, '%': 889})
_W.update({c: 667 for c in 'ABEKPSVXY'})
_W.update({c: 722 for c in 'CDHNRUw'})
_W.update({c: 778 for c in 'GOQ'})
_W.update({c: 611 for c in 'FTZ'})
_W.update({'L': 556})


def tw(s, size=FONT, bold=False):
    return sum(_W.get(c, 556) for c in s) * size / 1000.0 * (1.06 if bold else 1.0)


def wrap(s, width, size=FONT, bold=False, maxlines=None):
    """Greedy wrap; prefers breaking after '.', ',', ' ' or between the words of a camel-case name (as TIA:
    'DisableError' / 'Handling'), else hard."""
    lines, cur = [], ''
    for ch in s:
        if tw(cur + ch, size, bold) <= width or not cur:
            cur += ch
            continue
        camel = [i - 1 for i in range(1, len(cur)) if cur[i].isupper() and cur[i - 1].islower()]
        cut = max([cur.rfind('.'), cur.rfind(' '), cur.rfind(',')] + camel)
        if cut >= len(cur) * 0.5:
            lines.append(cur[:cut + 1].rstrip())
            cur = cur[cut + 1:].lstrip() + ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    if maxlines and len(lines) > maxlines:
        lines = lines[:maxlines]
        lines[-1] = lines[-1][:-1] + '…'
    return lines


def _t(x, y, s, color=C_OP, anchor='middle', bold=False, size=FONT):
    w = ' font-weight="bold"' if bold else ''
    return '<text x="%.1f" y="%.1f" fill="%s" text-anchor="%s" font-size="%s"%s>%s</text>' % (
        x, y, color, anchor, size, w, escape(s))


def _ln(x1, y1, x2, y2, color=C_WIRE, w=1.2):
    return '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s"/>' % (x1, y1, x2, y2, color, w)


# ---------------------------------------------------------------- operand labels

_QUOTED = re.compile(r'(?<=[#.])"([A-Za-z_][A-Za-z0-9_]*)"')


def display_operand(op):
    """An operand as TIA shows it: a member name quoted in the export because it is a keyword (#"NULL",
    .Config."Type") without its quotes; names that need them ("x+y", global "DB") keep them."""
    return _QUOTED.sub(lambda m: m.group(1), op)


def plain_operand(v):
    """A pin's operand without the NOT the reader tells a negated pin with. TIA has no negated pin in LAD, only in FBD,
    though the schema allows one: should an export hold it, the drawing shows the operand and the pin is marked, as
    the comparison still sees it."""
    return re.sub(r'^NOT(\s+|$)', '', v.strip())


def operand_lines(op, itf, width, below=False, types=None):
    """[(text, color, bold)] for an operand, top to bottom. types: name -> Interface (compare.Callees), for the
    comments of members inside a UDT."""
    op = plain_operand(op)
    if not op:
        return [('...', C_DEF, False)]
    c = itf.constant(op)
    if c is not None:
        out = [(c.value or '?', C_VAL, False)]
        if c.comment:
            out += [(l, C_CMT, True) for l in wrap(c.comment, width, bold=True, maxlines=MAXCMT)]
        out += [(l, C_CST, False) for l in wrap(display_operand(op), width)]
        return out
    if not op.startswith('#') and not op.startswith('"'):
        return [(l, C_CST, False) for l in wrap(op, width)]                 # literal
    cmt = itf.comment_of(op, types)
    out = [(l, C_CMT, True) for l in wrap(cmt, width, bold=True, maxlines=MAXCMT)] if cmt else []
    db = types.db(op) if re.fullmatch(r'"[^"]+"', op) and getattr(types, 'db', None) else None
    if db and db.number:                                    # a whole global DB: its number, as TIA (%DB901)
        out.append(('%DB' + db.number, C_NUM, True))
    out += [(l, C_OP, False) for l in wrap(display_operand(op), width)]
    return out


def _stack_up(lines, x, ybottom, anchor='middle'):
    """Draw lines so that the last one sits on ybottom."""
    out = []
    for k, (s, c, b) in enumerate(reversed(lines)):
        out.append(_t(x, ybottom - k * LINE, s, c, anchor, b))
    return out


def _stack_down(lines, x, ytop, anchor='middle'):
    return [_t(x, ytop + k * LINE, s, c, anchor, b) for k, (s, c, b) in enumerate(lines)]


def _text_box(lines, x, ybottom, anchor='middle'):
    """(x, y, w, h) around lines drawn by _stack_up(lines, x, ybottom, anchor)."""
    w = max([tw(s, FONT, b) for s, _, b in lines] + [0])
    x1 = {'middle': x - w / 2, 'end': x - w, 'start': x}[anchor] - 2
    top = ybottom - (len(lines) - 1) * LINE - 10
    return (x1, top, w + 4, ybottom + 4 - top)


# ---------------------------------------------------------------- element views

TIMERS = ('TON', 'TOF', 'TP', 'TONR')
JUMP_BOXES = ('Switch', 'JumpList')     # no ENO: the first destination sits on the rung row
EDGE_BOXES = ('P_Trig', 'N_Trig')       # the edge memory below the box, as TIA
EDGE_MEMORY = (None, 'bit', 'operand')  # its parameter: unnamed in .s7dcl; a SimaticML export lists pins in wire order
_SRC_TO_DEST = ('SrcType', 'to', 'DestType')
# the two types of a box, each in a cell of its own: (first template, what stands between, second template)
TYPE_PAIRS = {'Round': _SRC_TO_DEST, 'Ceil': _SRC_TO_DEST, 'ceil': _SRC_TO_DEST, 'Floor': _SRC_TO_DEST, 'Trunc': _SRC_TO_DEST,
              'trunc': _SRC_TO_DEST, 'Expt': ('DestType', '**', 'SrcType')}
PIN_TYPES = {('JumpList', 'k'): 'UInt'}  # input types an instruction fixes; others: its SrcType
STUB = 50                               # TIA's open ENO of a box below the network's top rung
C_CONV = '#a9a9a9'                      # conversion mark: a gray square, its lower right half light
C_CONV_LIGHT = '#d3d3d3'
ELEMENTARY = {t.lower() for t in (
    'Bool Byte Word DWord LWord SInt Int DInt LInt USInt UInt UDInt ULInt Real LReal Time LTime S5Time Date TOD '
    'Time_Of_Day LTOD LTime_Of_Day DT Date_And_Time LDT DTL Char WChar String WString').split()}
ALIASES = {'tod': 'time_of_day', 'ltod': 'ltime_of_day', 'dt': 'date_and_time'}   # one type, two names
EXPR_ROW = 34                           # Calculate: the expression row between EN and IN1
PAIR_GAP = 5                            # between a type cell and the 'to' beside it
C_OFF = '#a0a0a0'                       # an ENO that is not generated
_ZERO = {'bool': 'false', 'time': 'T#0ms', 'ltime': 'LT#0ns', 'real': '0.0', 'lreal': '0.0', 'string': "''",
         'wstring': "WSTRING#''", 'byte': '16#00', 'word': '16#0000', 'dword': '16#0000_0000'}
_ZERO.update({t: '0' for t in ('sint', 'int', 'dint', 'lint', 'usint', 'uint', 'udint', 'ulint',
                                  'db_www', 'db_dyn', 'port', 'pip', 'rtm')})      # iface._ELEMENTARY says which are seen


def default_value(value, typ):
    """What TIA shows at an unassigned pin: the declared default value, else the zero of the elementary type; None
    for a structured type."""
    return value or _ZERO.get((typ or '').strip().lower())


def operand_type(itf, op, types=None):
    """Data type of a local or global operand as far as the interfaces declare it, an array element's for '#a[1]';
    None when the path is not declared to its end (a slice, a member of a type not in the snapshot)."""
    op = op.strip()
    if not op.startswith(('#', '"')):
        return None
    path = itf.lookup(op, types)
    segs = _segments(op[1:] if op.startswith('#') else op)
    if not path or len(path) != len(segs) - (0 if op.startswith('#') else 1):
        return None
    t = (path[-1].type or '').strip()
    if op.endswith(']'):
        t = re.sub(r'^Array\s*\[.*\]\s*of\s+', '', t, flags=re.I)
    return t


def converted(optype, pintype):
    """Whether TIA converts an operand of optype at a pin of pintype (both elementary, another type): its
    conversion mark (seen on JMP_LIST's K, a UInt, fed a USInt)."""
    a, b = ((t or '').strip().lower() for t in (optype, pintype))
    a, b = ALIASES.get(a, a), ALIASES.get(b, b)
    return a in ELEMENTARY and b in ELEMENTARY and a != b


def _sides(params, called):
    """Call parameters as (inputs, in-outs, outputs) [(name, value, member)], each in the declaration order of the
    called block's interface; a parameter it does not declare (member None) goes by its arrow (':=' input, '=>'
    output), after the rest."""
    decl = {}
    for k, m in enumerate(called.root.children.values()):
        if m.section in ('INPUT', 'IN_OUT', 'OUTPUT'):
            decl[m.name.lower()] = (m.section, k, m)
    out = {'INPUT': [], 'IN_OUT': [], 'OUTPUT': []}
    for pos, (n, d, v) in enumerate(params):
        sec, k, m = decl.get((n or '').lower(), ('OUTPUT' if d == '=>' else 'INPUT', len(decl) + pos, None))
        out[sec].append((k, n, v, m))
    return tuple([(n, v, m) for _, n, v, m in sorted(out[s], key=lambda t: t[0])]
                 for s in ('INPUT', 'IN_OUT', 'OUTPUT'))


NOT_FONT = 8


def undrawn_settings(el, partner, drawn):
    """['name: value'] of the type settings TIA's look leaves out (not in drawn) that differ from the other version of the
    element: on the box only then, so that nothing differs from TIA's screen unless the two versions do. A setting only this
    side holds is written; not one of a SimaticML export the other side lacks, as a .s7dcl does not write those."""
    if partner is None:
        return []
    mine, theirs = {**el.more, **el.templates}, {**partner.more, **partner.templates}
    out = []
    for k in sorted(mine):
        if k in drawn or re.match(r'CASE\d+$', k) or mine[k] == theirs.get(k) or (k not in theirs and k in el.more):
            continue
        out.append('%s: %s' % (k, mine[k]))
    return out


def _symbol(el):
    """(half width, half height) of what a contact or compare draws on its rung."""
    if el.instr == 'Not':                             # its text between the bars, as TIA
        return tw('NOT', NOT_FONT, True) / 2 + 3, 8
    if el.kind == 'contact' and instructions.contact_text(el.instr):     # its name between the bars, as TIA
        return tw(instructions.contact_text(el.instr), FONT, True) / 2 + 4, 8
    if el.kind != 'compare':
        return 6, 8
    return max(10, tw(next(iter(el.templates.values()), ''), 8, True) / 2 + 3), 13


def _pin_names(el):
    return {n.lower() for n, _, _ in el.params if n}


def _negated_pins(el):
    """The pins an export lists for their negation alone, with no operand."""
    return {n.lower() for n, _, v in el.params if n and v == 'NOT'}


def _side_rows(side):
    """Row offsets below the rung of one side of a box: a row sits just low enough for the operand text above it."""
    ys = [0]
    for _, L in side[1:]:
        ys.append(ys[-1] + max(18, len(L or []) * LINE + 5))
    return ys


# what a coil shows inside it, as TIA, where it is not the name before _Coil
COIL_TEXT = {'I_Coil': '/', 'JumpCoil': 'JMP', 'I_JumpCoil': 'JMPN', 'ReturnCoil': 'RET',
             'R_BitfieldCoil': 'RESET_BF', 'S_BitfieldCoil': 'SET_BF',
             'Return': 'RET', 'ReturnTrue': 'RET', 'ReturnFalse': 'RET'}
RETURN_VALUES = {'Return': 'RLO', 'ReturnTrue': 'TRUE', 'ReturnFalse': 'FALSE'}   # above the coil, no operand in the export
COIL_SIGNALS = ('operand', 'timer', 'counter')    # the operand above a coil, whatever the order in the export
SQUARE_COILS = ('RT_Coil',)                       # [ RT ], as TIA: square brackets, not arcs
IEC_TIMER_COIL = re.compile(r'(TP|TON|TOF|TONR)_Coil', re.I)     # one tall coil: the kind over the type, as TIA


def _coil_text(instr):
    """What a coil writes inside it; a kind the report does not know keeps its raw name."""
    m = re.fullmatch(r'(\w+)_Coil', instr)
    return COIL_TEXT.get(instr, m.group(1).upper() if m else '' if instr == 'Coil' else instr)


def _operands(el):
    """(key, value) of the operand a contact or coil shows above it, [the same] of those below it, as TIA: the edge
    memory of a P / N element, a timer coil's time. Keys as diff.changed_params. The signal is found by its name: a
    SimaticML export lists the pins in the order of their wires. A negated pin the rung runs through is no operand. A
    return coil without an operand: its return value, told by the instruction."""
    ops = [(n.lower() if n else '#%d' % k, v) for k, (n, _, v) in enumerate(el.params) if not (n and v == 'NOT')]
    if el.instr in RETURN_VALUES and not ops and not el.instance:
        return ('#instr', RETURN_VALUES[el.instr]), []
    if el.instance:                                   # #inst.TP_Coil( t#5s ): written on the instance
        return (None, el.instance), ops
    first = next((o for o in ops if o[0] in COIL_SIGNALS), ops[0] if ops else None)
    return first, [o for o in ops if o is not first]


class View:
    """Size of an element and its drawing at (x, y) where y is the rung wire."""

    def __init__(self, el, itf, callees=None, partner=None):
        self.el = el
        self.partner = partner                            # the other version of the element, when the two are compared
        self.itf = itf
        self.callees = callees
        self.wirepins = {}
        self.eno_stub = False                             # a box: set by Layout, an open ENO below the top rung
        k = el.kind
        self.tall = 0
        if k in ('contact', 'coil'):
            self.w = CELL
            first, rest = _operands(el)
            self.topkey = first[0] if first else None
            self.top = operand_lines(first[1], itf, CELL - 20, types=callees) if first else []
            self.botrows = [(key, operand_lines(v, itf, CELL - 20, below=True, types=callees)) for key, v in rest]
            notes = undrawn_settings(el, partner, {'time_type'} if k == 'coil' else ())
            if notes:
                self.botrows.append(('templates', [(s, C_DEF, False) for s in notes]))
            self.bot = [line for _, lines in self.botrows for line in lines]
            self.tall = 6 if k == 'coil' and len(self._coil_lines()) == 2 else 0     # room for the second line
            self.above = 14 + self.tall + len(self.top) * LINE
            self.below = 12 + self.tall + len(self.bot) * LINE
        elif k == 'compare':
            self.w = CELL
            p = dict((n, v) for n, _, v in el.params)
            self.top = operand_lines(p.get('in1', ''), itf, CELL - 20, types=callees)
            self.bot = operand_lines(p.get('in2', ''), itf, CELL - 20, below=True, types=callees)
            self.above = 20 + len(self.top) * LINE
            self.below = 20 + len(self.bot) * LINE
        else:
            self._box_geometry()

    # ---- boxes
    def _box_geometry(self):
        el = self.el
        sysbox = el.instr != 'CALL'
        spec = instructions.lookup(el.instr)
        rin, rout = spec.rung if spec else instructions.EN_ENO
        self.rungpins = {(p or '').lower() for p in (rin, rout)}   # drawn on the rung's row, listed in the export or not
        params = [(n, d, plain_operand(v)) for n, d, v in el.params      # the rung's own pins are drawn anyway
                  if not (v == 'NOT' and (n or '').upper() in (rin, rout))]
        self.inst = el.instance if el.instance else None
        self.number = ''
        self.dbcall = None                                # the block whose instance the DB of this call is: TIA draws the DB above the box, the block in the head
        edge = next((p for p in params if el.instr in EDGE_BOXES and (p[0] and p[0].lower()) in EDGE_MEMORY
                     and wire_of(p[2]) is None), None)    # logic on it stays a pin: its wire ends there
        params = [p for p in params if p is not edge]
        self.abovekey = spec.above.lower() if spec else ''
        if self.abovekey:                                # flip-flop, S5 timer or counter: its operand above the box
            op = next((v for n, d, v in params if (n or '').lower() == self.abovekey), '')
            params = [p for p in params if (p[0] or '').lower() != self.abovekey]
            self.inst = op or None
            self.title = spec.title
        elif sysbox:
            self.title = spec.title if spec else el.instr.upper()
        else:
            of = getattr(self.callees, 'instance_of', None)
            self.dbcall = (of(el.call) or None) if el.call and of else None
            if self.dbcall:
                self.inst = '"%s"' % el.call.strip('"')
            self.title = '"%s"' % (self.dbcall or el.call or self._fb_type(el.instance) or (el.instance or '').lstrip('#')).strip('"')
        types = dict(spec.fixed) if spec else {}          # what the instruction fixes, an export's own over it
        types.update(el.templates)
        self.second = types.get(spec.second, '') if spec and spec.second else ''
        if spec and spec.line is not None:                # TIA's line holds these, whatever else the export has
            types = {k: types[k] for k in spec.line if k in types}
        self.sub = ', '.join(v for k, v in types.items() if not re.match(r'CASE\d+$', k))
        self.subpair = None                               # (type, what stands between, type): TIA's two cells
        pair = (spec and spec.pair) or TYPE_PAIRS.get(el.instr)   # only those two: another template stays drawn in self.sub
        if pair and {k for k in types if not re.match(r'CASE\d+$', k)} == {pair[0], pair[2]}:
            self.subpair = (types[pair[0]], pair[1], types[pair[2]])
        self.notes = undrawn_settings(el, self.partner, set(types) | ({spec.second} if spec else set()))
        self.expr = 'OUT :=  ' + re.sub(r'\b(in\d+|out)\b', lambda m: m.group(1).upper(), el.expression.strip(),
                                        flags=re.I) if el.expression is not None else ''
        told = (spec.pin(n) for n, _, _ in params) if spec else (None for _ in params)
        sides = [(p.side if p else 'out' if d == '=>' else 'in' if d == ':=' or n is None else '', (n, v, None))
                 for p, (n, d, v) in zip(told, params)]
        ins, ios, outs = ([x for s, x in sides if s == side] for side in ('in', 'io', 'out'))
        if spec:                                          # each side in TIA's order, whatever the wires' order
            ins, ios, outs = (sorted(x, key=lambda t: spec.order(t[0])) for x in (ins, ios, outs))
        called = None if sysbox else self.callees and self.callees(el.call or self._fb_type(el.instance) or '')
        if called:
            ins, ios, outs = _sides(params, called)
        elif not sysbox:                                  # a system block: no export holds it, the catalogue its in-outs
            inout = instructions.call_in_outs(self.dbcall if self.dbcall and '"' not in self.dbcall else self._system_block(el.instance))
            ios = [x for x in ins if (x[0] or '').lower() in inout]
            ins = [x for x in ins if (x[0] or '').lower() not in inout]
        blk = getattr(called, 'block', None)
        if blk is not None and blk.props.get('S7_BlockNumber'):
            self.number = '%%%s%s' % ('FC' if blk.kind == 'FUNCTION' else 'FB', blk.props['S7_BlockNumber'])
        name = spec.label if spec else (lambda n: (n or '').upper()) if sysbox else (lambda n: n or '')
        lw = 220
        jump = el.instr in JUMP_BOXES and bool(outs)
        if jump:                                          # DEST0..n, then ELSE, as TIA (the export: else first)
            outs.sort(key=lambda o: (o[0] or '').lower() == 'else')
            name = lambda n: re.sub(r'^DST(?=\d)', 'DEST', (n or '').upper())

        def lines(n, v, m):
            if v.strip() and jump and re.match(r'(dst\d+|else)$', n or '', re.I):
                return [(v.strip(), C_OP, False)]              # a jump label, black as TIA shows it
            if v.strip():
                return operand_lines(v, self.itf, lw, types=self.callees)
            dv = default_value(m.value, m.type) if m is not None else None
            if el.instr in TIMERS and (n or '').lower() == 'et':
                dv = default_value(None, el.templates.get('time_type', 'Time'))
            return [(dv or '...', C_DEF, False)]
        def key(n, v):                                    # as diff.changed_params names a parameter
            if n:
                return n.lower()
            return '#%d' % next((k for k, (pn, _, pv) in enumerate(el.params) if pn is None and plain_operand(pv) == v), 0)
        self.underkey = key(edge[0], edge[2]) if edge else None
        self.under = operand_lines(edge[2], self.itf, CELL - 20, types=self.callees) if edge else []
        self.wirepins = {}                                # left row -> (pin name, wire node)
        self.inouts = set()                               # left rows of in-outs
        self.relrows = set()                              # left rows of Switch cases: the relation as pin name
        self.pinrow = {}                                  # parameter -> ('L' | 'R', row)
        self.conv = set()                                 # left rows with TIA's conversion mark
        self.lefts = [(rin, None)]
        for k, (n, v, m) in enumerate(ins + ios):
            if k >= len(ins):
                self.inouts.add(len(self.lefts))
            rel = re.match(r'case(\d+)$', n or '', re.I) if el.instr == 'Switch' else None
            if rel:
                self.relrows.add(len(self.lefts))
            label = el.templates.get('CASE' + rel.group(1), '?') if rel else name(n)
            self.pinrow[key(n, v)] = ('L', len(self.lefts))
            if wire_of(v) is not None:
                self.wirepins[len(self.lefts)] = (n, wire_of(v))
                self.lefts.append((label, []))
            else:
                if k < len(ins) and converted(operand_type(self.itf, v, self.callees), self._pin_type(n, m)):
                    self.conv.add(len(self.lefts))
                self.lefts.append((label, lines(n, v, m)))
        self.noeno = jump                                 # outputs from the rung row on
        self.pinrow.update((key(n, v), ('R', r + (0 if jump else 1))) for r, (n, v, m) in enumerate(outs))
        self.rights = ([] if jump else [(rout, None)]) + [(name(n), lines(n, v, m)) for n, v, m in outs]
        self.rowy = _side_rows(self.lefts)                # each side its own rows, as TIA
        self.rowy_r = _side_rows(self.rights)
        if self.expr:                                     # the expression row under EN / ENO
            self.rowy = self.rowy[:1] + [r + EXPR_ROW for r in self.rowy[1:]]
            self.rowy_r = self.rowy_r[:1] + [r + EXPR_ROW for r in self.rowy_r[1:]]
        self.gaps = [0] + [self.rowy[r] - self.rowy[r - 1] for r in range(1, len(self.rowy))]
        pinw = max([tw(self._label(r, n)) for r, (n, _) in enumerate(self.lefts)] + [0]) + \
            max([tw(n or '') for n, _ in self.rights] + [0]) + 24
        typew = self._pair_width() + 16 if self.subpair else max(tw(self.sub, FONT, True), tw(self.second, FONT, True)) + 24
        typew = max([typew] + [tw(s) + 24 for s in self.notes])
        self.bw = max(CELL - 30, tw(self.title, FONT, True) + 20, tw(self.number, FONT, True) + 20, typew, pinw)
        if self.expr:                                     # TIA's Calculate box: about two cells wide
            self.bw = max(self.bw, 2 * CELL - 30, tw(self.expr) + 40)
        self.lw = max([max([tw(s, FONT, b) for s, _, b in L] + [0]) for _, L in self.lefts if L] + [0]) + 12
        self.rw = max([max([tw(s, FONT, b) for s, _, b in L] + [0]) for _, L in self.rights if L] + [0]) + 12
        self.lw = max(self.lw, 24)
        self.rw = max(self.rw, 24)
        self.head = 20 + 14 * (bool(self.sub) + bool(self.second) + len(self.notes)) + (LINE if self.number else 0)
        self.w = max(CELL, self.lw + self.bw + self.rw)
        first = 0
        for side, ys in ((self.lefts, self.rowy), (self.rights, self.rowy_r)):
            if len(side) > 1:
                first = max(first, (len(side[1][1]) - 1) * LINE + 10 - ys[1])
        self.instlines = wrap(display_operand(self.inst), self.w - 10) if self.inst else []
        db = self.callees.db(self.inst) if (el.instr in TIMERS or self.dbcall) and re.fullmatch(r'"[^"]+"', self.inst or '') \
            and getattr(self.callees, 'db', None) else None     # TIA: %DB7 above "IEC_Timer_0_DB"
        self.instnum = [('%DB' + db.number, C_NUM, True)] if db and db.number else []
        cmt = self.itf.comment_of(self.inst, self.callees) if self.inst else None
        if not cmt and blk is not None:                   # TIA: else the called block's comment
            cmt = (blk.props.get('S7_BlockComment') or '').strip()
        self.cmtlines = [(l, C_CMT, True) for l in wrap(cmt, min(self.w, CELL) - 20, bold=True, maxlines=MAXCMT)] \
            if cmt else []
        self.above = self.head + 6 + LINE * (len(self.instnum) + len(self.instlines) + len(self.cmtlines)) + max(0, first)
        self.below = self._box_below()

    def _box_below(self):
        """How far the element reaches below the rung: the box's last row, the edge memory under the box."""
        return max(self.rowy[-1], self.rowy_r[-1]) + 12 + len(self.under) * LINE

    def _label(self, r, n):
        """Pin name; an in-out with TIA's two-way arrow."""
        return '\u21cc' + n if r in self.inouts and n else (n or '')

    def set_pin_offset(self, r, off):
        """Move left row r down to `off` below the rung (where the logic feeding it was placed); later rows keep
        their spacing."""
        if off > self.rowy[r]:
            self.rowy[r] = off
            for k in range(r + 1, len(self.rowy)):
                self.rowy[k] = max(self.rowy[k], self.rowy[k - 1] + self.gaps[k])
            self.below = self._box_below()

    def pin_x(self, x):
        """x where the wire of a left pin ends (start of the pin stub) for a box drawn at x."""
        return x + self.lw - 8

    def _pin_type(self, n, m):
        """Data type of an input: the called block's declaration, the type the instruction fixes, else its SrcType
        (Switch K and cases, IN<n>; not MUX / DEMUX K, an index); None when unknown."""
        if m is not None:
            return m.type
        n = (n or '').lower()
        t = PIN_TYPES.get((self.el.instr, n))
        if self.el.instr == 'Expt' and n == 'in1':        # the base: the type of the result, the exponent is SrcType
            return self.el.templates.get('DestType')
        if t is None and (re.match(r'(case\d+|in\d*)$', n) or n == 'k' and self.el.instr == 'Switch'):
            t = self.el.templates.get('SrcType')
        return t

    def _fb_type(self, inst):
        p = self.itf.lookup(inst or '')
        if p:
            return type_name(p[-1].type)
        return None

    def _system_block(self, inst):
        """The type of an instance when it is a system block, written without quotes; a block of the project has them."""
        p = self.itf.lookup(inst or '')
        typ = p[-1].type if p else ''
        return None if '"' in typ or '_.' in typ else type_name(typ)

    # ---- diff marks
    def operand_texts(self):
        """{parameter, as diff.changed_params names it, '#inst' the instance: what is drawn of its operand, unwrapped}; a
        wire draws nothing."""
        def lines(v):
            return operand_lines(v, self.itf, float('inf'), types=self.callees)
        out = {(n.lower() if n else '#%d' % k): lines(v)
               for k, (n, _, v) in enumerate(self.el.params) if 'wire#' not in v.lower()}
        if self.el.instance:
            out['#inst'] = lines(self.el.instance)
        return out

    def drawn_otherwise(self, partner):
        """What is drawn otherwise in the two versions of an element: the parameters both have whose operands differ
        (keys as operand_texts) or that only one draws a conversion mark at, a box's '#call' title, '#dbname' DB above
        it, '#number' block number, '#inst' comment or DB number above it."""
        mine, theirs = self.operand_texts(), partner.operand_texts()
        out = {k for k in mine if k in theirs and mine[k] != theirs[k]}
        if self.el.kind == 'box':
            def converted_pins(v):
                return {k for k, (side, r) in v.pinrow.items() if side == 'L' and r in v.conv}
            out |= (converted_pins(self) ^ converted_pins(partner)) & set(self.pinrow) & set(partner.pinrow)
            out |= {k for k, x, y in (('#call', self.title, partner.title), ('#dbname', self.dbcall and self.inst, partner.dbcall and partner.inst),
                                      ('#number', self.number, partner.number),
                                      ('#inst', (self.cmtlines, self.instnum), (partner.cmtlines, partner.instnum))) if x != y}
        return out

    def marks(self, x, y, st, keys=(), other=None):
        """[(layer, x, y, w, h)] of the diff marks of this element drawn at (x, y): layer 'under' goes below every
        line, 'box' on the box fill below its texts. st: added / removed / moved fill the element, changed only the
        parameters in keys (diff.changed_params); the element when none of them is drawn. other: the partner element, for
        the pins only one of the two has: this one's are marked whole, the other's need no mark here."""
        whole = [('under', x, y - self.above, self.w, self.above + self.below)]
        if st != 'changed':
            return whole
        k = self.el.kind
        out = [('under',) + self._symbol_box(x, y)] if k != 'box' and keys & {'#instr', 'templates'} else []
        top_changed = k in ('contact', 'coil') and self.top and self.topkey in keys     # '#instr': a return value
        keys = keys - {'#instr'}
        if k in ('contact', 'coil'):
            if top_changed:
                out.append(('under',) + _text_box(self.top, x + self.w / 2, y - (14 if k == 'coil' else 13) - self.tall))
            line = self._bot_y(y)
            for key, lines in self.botrows:
                line += (len(lines) - 1) * LINE
                if key in keys:
                    out.append(('under',) + _text_box(lines, x + self.w / 2, line))
                line += LINE
        elif k == 'compare':
            if 'in1' in keys:
                out.append(('under',) + _text_box(self.top, x + self.w / 2, y - 18))
            if 'in2' in keys:
                out.append(('under',) + _text_box(self.bot, x + self.w / 2, y + 25 + (len(self.bot) - 1) * LINE))
        else:
            bx = x + self.lw
            mine, theirs = _pin_names(self.el), _pin_names(other) if other else set()
            alone = mine - theirs if other else set()
            for key in sorted(keys):
                side, r = self.pinrow.get(key, (None, 0))
                if side == 'L':
                    py = y + self.rowy[r]
                    n, L = self.lefts[r]
                    if L:
                        out.append(('under',) + _text_box(L, bx - 10, py + 4, 'end'))
                    if not L or r in self.relrows or key in alone:   # no variable; a case's relation is in the pin
                        out.append(('box', bx + .5, py - 6, tw(self._label(r, n)) + 7, 13))
                elif side == 'R':
                    py = y + self.rowy_r[r]
                    n, L = self.rights[r]
                    ex = bx + self.bw
                    if L:
                        out.append(('under',) + _text_box(L, ex + 10, py + 4, 'start'))
                    if not L or key in alone:
                        out.append(('box', ex - tw(n or '') - 7.5, py - 6, tw(n or '') + 7, 13))
                elif key == self.underkey:                    # the edge memory under the box
                    n = len(self.under) - 1
                    out.append(('under',) + _text_box(self.under, bx + self.bw / 2, self._under_y(y) + n * LINE))
                elif key in ('operand', '#inst', self.abovekey) and (self.inst or self.cmtlines):   # what stands above the box
                    above, cx, yb = self._above(x, y)
                    out.append(('under',) + _text_box(above, cx, yb))
                elif key == 'expression' and self.expr:
                    out.append(('box',) + self._expr_box(bx, y))
                elif key == '#number' and self.number:        # the called block's number, over its name
                    w = tw(self.number, FONT, True) + 8
                    out.append(('box', bx + (self.bw - w) / 2, y - self.head + 2, w, 13))
                elif key == '#call':                          # the called block's name, in the box head
                    out.append(('box',) + self._title_box(bx, y))
                elif key == '#dbname' and self.dbcall:        # the DB of a call with one of its own, above the box
                    above, cx, yb = self._above(x, y)
                    out.append(('under',) + _text_box(above, cx, yb))
                elif key == 'eno' and not self.noeno and self.rights[0][0]:
                    n = self.rights[0][0]
                    out.append(('box', bx + self.bw - tw(n) - 7.5, y - 6, tw(n) + 7, 13))
            drawn = set(self.pinrow) | {'#call', self.underkey} | {'#dbname'} | ({'#number'} if self.number else set()) \
                | ({'operand', '#inst', self.abovekey} if self.inst or self.cmtlines else set()) \
                | ({'expression'} if self.expr else set()) | ({'eno'} if not self.noeno and self.rights[0][0] else set())
            missing = theirs - mine
            negated = self.rungpins & _negated_pins(other) if other else set()     # drawn here too: only the other lists them
            drawn_there = missing - negated                   # their marks stand on the side that draws them, none here
            if ('templates' in keys or keys - drawn - missing
                    or (not out and (not keys or keys - drawn_there))):     # the head: what has no place
                out.append(('box', bx + .5, y - self.head + .5, self.bw - 1, self.head - 6))
            return out
        return out or whole

    def _bot_y(self, y):
        """Baseline of the first line below a contact or coil."""
        return y + (21 if self.el.kind == 'coil' else 20) + self.tall

    def _above(self, x, y):
        """(lines, x, baseline of the last line) of the texts above a box: comment, instance or operand."""
        bx = x + self.lw
        above = self.cmtlines + self.instnum + [(l, C_OP, False) for l in self.instlines]
        if not above:
            return above, bx, y
        half = max(tw(s, FONT, b) for s, _, b in above) / 2      # centred over the box, inside the element's cell
        return above, min(max(bx + self.bw / 2, x + half + 2), x + self.w - half - 2), y - self.head - 4

    def _symbol_box(self, x, y):
        """(x, y, w, h) of the mark on what a contact, compare or coil draws on its rung, past its bars: a compare's type
        cell covers the bars' inside."""
        if self.el.kind == 'coil':
            g, h = max(13, self._coil_shape()[0] + 8), 11 + self.tall
        else:
            g, h = _symbol(self.el)
        return x + self.w / 2 - g - 4, y - h - 1, 2 * g + 8, 2 * h + 2

    def _coil_lines(self):
        """The lines inside a coil: its text, under it a timer coil's type as the export's S7_Templates has it."""
        text = _coil_text(self.el.instr)
        kind = self.el.templates.get('time_type') if IEC_TIMER_COIL.fullmatch(self.el.instr) else None
        return [text, kind] if kind else [text] if text else []

    def _coil_shape(self):
        """(half the distance of the arcs' ends, font size of the texts inside): a long text widens the coil, as TIA's
        RESET_BF."""
        lines = self._coil_lines()
        short = all(len(s) == 1 for s in lines)
        size = 10 if short else 7 if self.el.instr in COIL_TEXT and len(lines[0]) < 5 else 9
        bulge = 6 if self.tall else 4.7                   # how far an arc reaches past its ends, level with the text
        return max(5, max([tw(s, size, True) for s in lines] + [0]) / 2 + 2 - bulge), size

    # ---- drawing
    def draw(self, x, y, inbox=''):
        """inbox: svg drawn on the fill of a box, below its texts (the diff marks of its pins)."""
        k = self.el.kind
        out = []
        if k in ('contact', 'compare'):
            cx = x + self.w / 2
            typ = next(iter(self.el.templates.values()), '') if k == 'compare' else ''
            g, h = _symbol(self.el)
            out += [_ln(x, y, cx - g, y), _ln(cx + g, y, x + self.w, y),
                    _ln(cx - g, y - h, cx - g, y + h, w=1.6), _ln(cx + g, y - h, cx + g, y + h, w=1.6)]
            out += _stack_up(self.top, cx, y - h - 5)
            ins = self.el.instr
            if k == 'compare':
                out.append(_t(cx, y - 2, CMP[ins], C_OP, bold=True, size=9))
                if typ:
                    out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="9" fill="#d9dde2"/>'
                               % (cx - g + 1.5, y + 2, 2 * g - 3))
                    out.append(_t(cx, y + 9.5, typ, C_OP, bold=True, size=8))
                out += _stack_down(self.bot, cx, y + h + 12)
            elif instructions.contact_text(ins) and ins != 'Not':
                out.append(_t(cx, y + 4, instructions.contact_text(ins), bold=True))
            elif ins.startswith('I_'):
                out.append(_ln(cx - 5, y + 7, cx + 5, y - 7))
            elif ins in ('P_Contact', 'N_Contact'):
                out.append(_t(cx, y + 4, ins[0], bold=True, size=10))
            elif ins == 'Not':
                out.append(_t(cx, y + 4, 'NOT', bold=True, size=NOT_FONT))
            if k == 'contact':
                out += _stack_down(self.bot, cx, self._bot_y(y))
        elif k == 'coil':
            cx = x + self.w / 2
            g, size = self._coil_shape()
            h, r, reach = (15, 18, 7.4) if self.tall else (9, 11, 4)
            if self.el.instr in SQUARE_COILS:
                b = g + 6
                out += [_ln(x, y, cx - b, y), _ln(cx + b, y, x + self.w, y)]
                out += ['<path d="M%.1f %.1f H%.1f V%.1f H%.1f" fill="none" stroke="%s" stroke-width="1.6"/>'
                        % (cx + s * (b - 3), y - h, cx + s * b, y + h, cx + s * (b - 3), C_WIRE) for s in (-1, 1)]
            else:
                out += [_ln(x, y, cx - g - reach, y), _ln(cx + g + reach, y, x + self.w, y),
                        '<path d="M%.1f %.1f A %d %d 0 0 0 %.1f %.1f" fill="none" stroke="%s" stroke-width="1.6"/>'
                        % (cx - g, y - h, r, r, cx - g, y + h, C_WIRE),
                        '<path d="M%.1f %.1f A %d %d 0 0 1 %.1f %.1f" fill="none" stroke="%s" stroke-width="1.6"/>'
                        % (cx + g, y - h, r, r, cx + g, y + h, C_WIRE)]
            lines = self._coil_lines()
            for s, yt in zip(lines, (y - 2, y + 10) if self.tall else (y + 4,)):
                out.append(_t(cx, yt, s, bold=True, size=size))
            out += _stack_up(self.top, cx, y - 14 - self.tall)
            out += _stack_down(self.bot, cx, self._bot_y(y))
        else:
            out += self._draw_box(x, y, inbox)
        return out

    def _draw_box(self, x, y, inbox=''):
        out = []
        bx = x + self.lw
        bt = y - self.head
        bb = self._box_bottom(y)
        out.append(_ln(x, y, bx, y))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#9aa3ad"/>'
                   % (bx, bt, self.bw, bb - bt, C_BOX))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                   % (bx + .5, bt + .5, self.bw - 1, self.head - 6, C_BOXHEAD))
        if self.expr:
            out += self._draw_expression(bx, bt, y)
        for r in sorted(self.relrows):                    # a Switch case: its relation in a cell of its own
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="14" fill="%s" stroke="#b5bcc4"/>'
                       % (bx + .5, y + self.rowy[r] - 7, tw(self.lefts[r][0]) + 8, C_BOXHEAD))
        if inbox:
            out.append(inbox)
        ty = bt + 12
        if self.number:
            out.append(_t(bx + self.bw / 2, ty, self.number, C_NUM, bold=True))
            ty += LINE
        out.append(_t(bx + self.bw / 2, ty, self.title, C_OP, bold=True))
        if self.subpair:
            out += self._draw_pair(bx, ty, bt)
        elif self.sub or self.second:                     # the type: bold in a cell of its own, as TIA
            sw = max(tw(self.sub, FONT, True), tw(self.second, FONT, True)) + 8
            for k, s in enumerate(x for x in (self.sub, self.second) if x):
                top = ty + 3 + 14 * k
                h = 14 if self.second or self.notes else bt + self.head - 6 - ty - 3
                out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="%s"/>'
                           % (bx + (self.bw - sw) / 2, top, sw, h, C_BOXHEAD, C_BOX))
                out.append(_t(bx + self.bw / 2, top + 11, s, C_OP, bold=True))
        for k, s in enumerate(self.notes):                # a setting TIA's look leaves out, the two versions differ in
            out.append(_t(bx + self.bw / 2, ty + 14 + 14 * (bool(self.sub) + bool(self.second) + k), s))
        above, cx, yb = self._above(x, y)
        if above:
            out += _stack_up(above, cx, yb)
        if not self.noeno:                                # on to the cell's end, or TIA's short open end
            out.append(_ln(bx + self.bw, y, bx + self.bw + STUB if self.eno_stub else x + self.w, y))
        if self.expr:
            ex, ey, ew, eh = self._expr_box(bx, y)
            out.append(_t(ex + ew / 2, ey + 14, self.expr, C_OP))
        for r, (n, L) in enumerate(self.lefts):
            py = y + self.rowy[r]
            if n:
                out.append(_t(bx + 4, py + 4, self._label(r, n), C_OP, 'start'))
            if r:
                wired = r in self.wirepins
                out.append(_ln(bx - 8, py, bx, py, C_WIRE if wired else '#888', 1.2 if wired else 1))
                out += _stack_up(L, bx - 10, py + 4, 'end')
            if r in self.conv:
                out += _conversion(bx, py)
        for r, (n, L) in enumerate(self.rights):
            py = y + self.rowy_r[r]
            off = not r and not self.noeno and self.el.no_eno
            if n:
                out.append(_t(bx + self.bw - 4, py + 4, n, C_OFF if off else C_OP, 'end'))
            if off:                                       # ENO := EN, drawn through the box as TIA
                out.append(_ln(bx + tw(self.lefts[0][0]) + 9, y, bx + self.bw - tw(n) - 9, y, C_OFF, 1))
            if r or self.noeno:
                out.append(_ln(bx + self.bw, py, bx + self.bw + 8, py, '#888', 1))
                out += _stack_up(L, bx + self.bw + 10, py + 4, 'start')
        out += _stack_down(self.under, bx + self.bw / 2, self._under_y(y))
        return out

    def _box_bottom(self, y):
        return y + self.below - 6 - len(self.under) * LINE

    def _under_y(self, y):
        """Baseline of the first line under the box."""
        return self._box_bottom(y) + 12

    def _pair_width(self):
        """Width of the two type cells and what stands between them."""
        a, sep, b = self.subpair
        return tw(a, FONT, True) + tw(b, FONT, True) + tw(sep) + 2 * 8 + 2 * PAIR_GAP

    def _draw_pair(self, bx, ty, bt):
        """Two types in the head, each bold in a cell of its own, as TIA: Int to DInt."""
        a, sep, b = self.subpair
        x = bx + (self.bw - self._pair_width()) / 2
        out = []
        for k, s in enumerate((a, b)):
            w = tw(s, FONT, True) + 8
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="%s"/>'
                       % (x, ty + 3, w, 14 if self.notes else bt + self.head - 6 - ty - 3, C_BOXHEAD, C_BOX))
            out.append(_t(x + w / 2, ty + 14, s, C_OP, bold=True))
            x += w
            if not k:
                out.append(_t(x + PAIR_GAP + tw(sep) / 2, ty + 14, sep))
                x += 2 * PAIR_GAP + tw(sep)
        return out

    def _title_box(self, bx, y):
        """(x, y, w, h) of the mark on the box's title: below the block number, as _draw_box draws them."""
        w = tw(self.title, FONT, True) + 8
        return bx + (self.bw - w) / 2, y - self.head + 2 + (LINE if self.number else 0), w, 13

    def _expr_box(self, bx, y):
        """(x, y, w, h) of the expression row of a Calculate box drawn at bx on the rung y."""
        return (bx + 8, y + 16, self.bw - 16, 20)

    def _draw_expression(self, bx, bt, y):
        """The field of the expression row (its text comes above the diff marks) and the calculator icon in the
        head (TIA's button to edit the expression)."""
        ex, ey, ew, eh = self._expr_box(bx, y)
        ix, iy = bx + self.bw - 17, bt + 5
        return ['<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#eef0f2" stroke="#b5bcc4"/>'
                % (ex, ey, ew, eh),
                '<rect x="%.1f" y="%.1f" width="11" height="13" fill="#f4f5f6" stroke="#555"/>' % (ix, iy),
                '<rect x="%.1f" y="%.1f" width="7" height="3" fill="#555"/>' % (ix + 2, iy + 2)] + \
            ['<rect x="%.1f" y="%.1f" width="2" height="2" fill="#555"/>' % (ix + 2 + 2.5 * c, iy + 7 + 3 * r)
             for r in range(2) for c in range(3)]


def _conversion(bx, py):
    """TIA's conversion mark at an input: a gray square on the pin over the box edge, its lower right half light."""
    x1, y1 = bx - 7, py - 4
    return ['<rect x="%.1f" y="%.1f" width="10" height="9" fill="%s"/>' % (x1, y1, C_CONV),
            '<path d="M%.1f %.1fL%.1f %.1fL%.1f %.1fZ" fill="%s"/>' % (x1 + 2, y1 + 8, x1 + 9, y1 + 1, x1 + 9, y1 + 8,
                                                                     C_CONV_LIGHT)]


# ---------------------------------------------------------------- network layout

PIN_GAP = 8              # minimum run from the end of the logic feeding a box pin to the box


class Layout:
    """Positions of a LAD network.

    Columns: every node at the longest path from the rail (element widths); a box with inputs fed by logic sits right
    of that logic. Rows: one per rung, placed first-fit below the rows they attach to, without overlapping text or
    crossing lines where possible; the rung feeding a box pin sets the height of that pin row (the box grows).
    wiring() returns the drawn lines and the element terminals; svg() draws exactly those, verify.py reads the logic
    back from them. callees: name -> Interface of a called FB / FC (compare.Callees); without it a call box shows its
    pins as written. label: the network's jump label, drawn over it, filled with FILL[mark] unless mark is 'same'
    (compare.NetPair.label_state); wiring() and marks() stay in the coordinates below it. other: {element id: the other version's
    element} (diff.NetDiff.other), for the type settings the two differ in."""

    def __init__(self, rungs, itf, callees=None, label='', mark='same', other=None):
        rungs = rungs or [Rung(RAIL, [], None)]           # SimaticML's empty network: no rung at all
        self.rungs = rungs
        self.label, self.mark = label, mark
        self.itf = itf
        self.g = g = Graph(rungs)
        self.views = {}
        for r in rungs:
            for it in r.items:
                if not isinstance(it, tuple):
                    self.views[it.eid] = View(it, itf, callees, (other or {}).get(it.eid))
        self.src = {e.eid: g.find(s) for e, s, d in g.edges if e}
        self.pinof = {}                                   # pin node -> (box eid, left row)
        for eid, v in self.views.items():
            if v.el.kind == 'box':
                for r, (_, wn) in sorted(v.wirepins.items()):
                    self.pinof.setdefault(g.find(wn), (eid, r))
        self._columns()
        self._rows()
        if label:
            self.width = max(self.width, X0 + CELL + 30)

    def _columns(self):
        g = self.g
        x = {g.find(RAIL): X0}
        edges = []
        for e, s, d in g.edges:
            if e is not None and self.views[e.eid].wirepins:       # box right of the logic feeding its pins
                b = ('box', e.eid)
                edges += [(g.find(s), b, 0), (b, g.find(d), self.views[e.eid].w)]
            else:
                edges.append((g.find(s), g.find(d), self.views[e.eid].w if e else 0))
        edges += [(n, ('box', eid), PIN_GAP) for n, (eid, _) in self.pinof.items()]
        for _ in range(len(edges) + 2):
            moved = False
            for s, d, w in edges:
                if s in x and x[s] + w > x.get(d, -1e9):
                    x[d] = x[s] + w
                    moved = True
            if not moved:
                break
        self.x = x

    # ---------------------------------------------------------------- rows
    def _rows(self):
        g, x = self.g, self.x
        sink, rail = g.find(SINK), g.find(RAIL)
        info = []
        for r in self.rungs:
            s = g.find(r.start)
            placed, inline = [], []
            cx = x.get(s, X0)
            for it in r.items:
                if isinstance(it, tuple):
                    n = g.find(it[1])
                    placed.append(('node', n))
                    inline.append(n)
                    cx = max(cx, x.get(n, cx))
                else:
                    ex = max(cx, x.get(('box', it.eid), x.get(self.src[it.eid], cx)))
                    placed.append((it, ex))
                    cx = ex + self.views[it.eid].w
            e = g.find(r.end) if r.end else None
            if e == sink:
                e = None
            boxes = [p[0].eid for p in placed if not isinstance(p[0], str) and self.views[p[0].eid].wirepins]
            last = placed[-1] if placed and e is None and not isinstance(placed[-1][0], str) else None
            eno = last if last and last[0].kind == 'box' and not self.views[last[0].eid].noeno else None
            info.append(dict(s=s, e=e, placed=placed, inline=inline, end=cx, boxes=boxes, eno=eno))
        self.info = info
        box_rung = {eid: k for k, i in enumerate(info) for eid in i['boxes']}
        right = max([i['end'] for i in info] + [v for n, v in x.items() if n != sink and not isinstance(n, tuple)]
                    + [X0 + CELL] + [ex + self.views[el.eid].lw + self.views[el.eid].bw + STUB
                                     for el, ex in (i['eno'] for i in info if i['eno'])])
        for i in info:
            if i['e'] is None and not i['placed']:        # an empty rung (an empty network): across, as in TIA
                i['end'] = right
            if i['e'] is None:                            # trailing coils right-aligned at the network end
                k = len(i['placed'])
                while k and not isinstance(i['placed'][k - 1][0], str) and i['placed'][k - 1][0].kind == 'coil':
                    k -= 1
                if k < len(i['placed']):
                    pos = right - sum(self.views[p[0].eid].w for p in i['placed'][k:])
                    for j in range(k, len(i['placed'])):
                        el = i['placed'][j][0]
                        i['placed'][j] = (el, pos)
                        pos += self.views[el.eid].w
                    i['end'] = right
        self.right = right

        home = {}                                         # node -> rung that defines its row
        for k, i in enumerate(info):
            for n in i['inline']:
                home.setdefault(n, k)
            for eid in i['boxes']:
                for n, (b, _) in self.pinof.items():
                    if b == eid:
                        home.setdefault(n, k)             # until the first rung feeding the pin is placed
        fed = set()
        feeding = {i['e'] for i in info if i['e'] in self.pinof}
        bands = []                                        # (x1, x2, top, bottom, tag)
        elband = {}
        ys = {}

        def deps(k):
            i = info[k]
            return [n for n in (i['s'], i['e']) if n and n != rail and n in home and home[n] != k]

        def pin_turn(k):
            """Rows of a box are set top-down: the logic feeding a pin waits until every earlier pin of the box
            has its feeding rung (export order is drawing order otherwise)."""
            e = info[k]['e']
            if e not in self.pinof or e in fed:
                return True
            eid, r = self.pinof[e]
            return all(n in fed or n not in feeding for n, (b, r2) in self.pinof.items() if b == eid and r2 < r)

        def free(cands, ymin, i, k, verts, own_box, strict):
            for c in sorted(set(cands)):
                if c < ymin:
                    continue
                if all(not _hit(bd, i, k, c, verts, own_box, strict) for bd in bands):
                    return c
            return None

        def _hit(bd, i, k, c, verts, own_box, strict):
            bx1, bx2, bt, bb, tag = bd
            for (x1, x2, t, b, kind) in self._row_boxes(i, c):
                if kind == 'line':
                    if tag is not None and tag[0] == 'v' and tag[1] in (i['s'], i['e']):
                        continue
                    if tag is not None and tag[0] == 'el' and tag[1] == own_box:
                        continue
                    if tag is not None and tag[0] == 'el':        # up to an element's cell, as TIA, not into it
                        across = bx1 < x2 and x1 < bx2
                    else:                                         # near another line: it would read as a junction
                        across = bx1 <= x2 + 2 and x1 <= bx2 + 2
                    if across and t < bb and bt < b:
                        return True
                else:
                    if tag is not None and tag[0] == 'el' and tag[1] == own_box:
                        continue
                    if tag is not None and tag[0] == 'v' and tag[1] in (i['s'], i['e']):
                        continue                          # its own node's connector runs along the cell's edge

                    if bx1 < x2 and x1 < bx2 and t < bb and bt < b:
                        return True
            if strict:                                    # its vertical connectors: no false junction, no text hit
                for n, vx, y0 in verts:
                    t, b = min(y0, c), max(y0, c)
                    if tag is not None and ((tag[0] == 'v' and tag[1] == n) or (tag[0] == 'line' and n in tag[2])):
                        continue
                    inside = (bx1 < vx < bx2) if (tag is not None and tag[0] == 'el') else (bx1 <= vx <= bx2)
                    if inside and t < bb - 1 and bt + 1 < b:
                        return True
            return False

        todo = list(range(len(info)))
        bottom = TOP
        while todo:
            pick = next((k for k in todo if all(home[n] in ys for n in deps(k)) and pin_turn(k)), None)
            if pick is None:
                pick = todo[0]
            todo.remove(pick)
            k = pick
            i = info[k]
            els = [self.views[p[0].eid] for p in i['placed'] if not isinstance(p[0], str)]
            above = max([v.above for v in els] + [10])
            pin = self.pinof.get(i['e']) if i['e'] else None
            own_box = pin[0] if pin else None
            first_feed = pin is not None and i['e'] not in fed
            ymin = max([ys[home[n]] for n in deps(k) if home[n] in ys] + [TOP + above - 1]) + 1
            if first_feed:
                bk = home[i['e']]
                ymin = max(ymin, ys[bk] + self.views[pin[0]].rowy[pin[1]])
                i['to_pin'] = self.views[pin[0]].pin_x(self._elx(pin[0]))
            verts = []
            for n in (i['s'], i['e']):
                if n and n != rail and n in home and home[n] in ys and home[n] != k and not (first_feed and n == i['e']):
                    verts.append((n, x[n], ys[home[n]]))
            if i['eno']:                                  # an open ENO: TIA runs the top rung on to the network's
                if not bands:                             # end, the others end in a short stub
                    i['end'] = max(i['end'], right)
                else:
                    self.views[i['eno'][0].eid].eno_stub = True
            if not bands:
                y = TOP + above
            elif i['s'] == rail and i['e'] is None:
                y = bottom + GAP + above                  # another rung of the network: below everything
            else:
                cands = [ymin] + [bd[3] + GAP + above for bd in bands] + [bd[3] + 6 for bd in bands]
                y = free(cands, ymin, i, k, verts, own_box, True)
                if y is None:
                    y = free(cands, ymin, i, k, verts, own_box, False)
                if y is None:
                    y = max(ymin, bottom + GAP + above)
            ys[k] = y
            for (x1, x2, t, b, kind) in self._row_boxes(i, y):
                if kind == 'line':
                    tag = ('line', i['s'], set([i['s'], i['e']] + i['inline'] + ([i['e']] if pin else [])))
                    bands.append((x1, x2, t, b, tag))
                else:
                    elband[kind] = len(bands)
                    bands.append((x1, x2, t, b, ('el', kind)))
            for n, vx, y0 in verts:
                bands.append((vx - 1, vx + 1, min(y0, y), max(y0, y), ('v', n)))
            for n in (i['s'], i['e']):
                if n and n != rail and n not in home:
                    home[n] = k
            if first_feed:
                fed.add(i['e'])
                home[i['e']] = k
                v = self.views[pin[0]]
                yb = ys[box_rung[pin[0]]]
                v.set_pin_offset(pin[1], y - yb)
                bi = elband[pin[0]]
                b = bands[bi]
                bands[bi] = (b[0], b[1], b[2], yb + v.below, b[4])
            bottom = max([bd[3] for bd in bands] + [bottom])

        self.info, self.ys, self.home = info, ys, home
        self.height = max([bd[3] for bd in bands] + [TOP]) + TOP
        self.width = max([i['end'] for i in info] + [right] +
                         [self._elx(eid) + v.w for eid, v in self.views.items()]) + 30

    def _elx(self, eid):
        for i in self.info:
            for p in i['placed']:
                if not isinstance(p[0], str) and p[0].eid == eid:
                    return p[1]
        return X0

    def _row_boxes(self, i, y):
        """Occupied rectangles of a rung drawn at y: its wire line and each element (with its texts)."""
        x1 = self.x.get(i['s'], X0)
        x2 = i.get('to_pin') or (self.x.get(i['e'], i['end']) if i['e'] else i['end'])
        out = [(x1, x2, y - 4, y + 4, 'line')]
        for p in i['placed']:
            if not isinstance(p[0], str):
                v = self.views[p[0].eid]
                out.append((p[1], p[1] + v.w, y - v.above, y + v.below, p[0].eid))
        return out

    # ---------------------------------------------------------------- wiring
    def wiring(self):
        """(segments [(x1, y1, x2, y2)], terminals [(kind, eid, pin, x, y)]): every drawn wire line, and where each
        element connects (kind in / out / pin)."""
        g, x, ys = self.g, self.x, self.ys
        rail = g.find(RAIL)
        segs, terms = [(X0, 2, X0, self.height - 2)], []
        vert = {}
        boxrow = {}
        for k, i in enumerate(self.info):
            y = ys[k]
            for p in i['placed']:
                if not isinstance(p[0], str):
                    boxrow[p[0].eid] = (p[1], y)
        for k, i in enumerate(self.info):
            y = ys[k]
            for n in [i['s'], i['e']] + i['inline']:
                if n and n != rail:
                    vert.setdefault(n, set()).add(y)
            cur = x.get(i['s'], X0)
            for p in i['placed']:
                if isinstance(p[0], str):
                    nx = x.get(p[1], cur)
                    if nx > cur:
                        segs.append((cur, y, nx, y))
                    cur = max(cur, nx)
                    continue
                el, ex = p
                v = self.views[el.eid]
                if ex > cur:
                    segs.append((cur, y, ex, y))
                terms.append(('in', el.eid, None, ex, y))
                terms.append(('out', el.eid, None, ex + v.w, y))
                for r, (pn, wn) in v.wirepins.items():
                    terms.append(('pin', el.eid, pn, v.pin_x(ex), y + v.rowy[r]))
                cur = ex + v.w
            if i['e'] is not None:
                ex = x.get(i['e'], cur)
                if ex > cur:
                    segs.append((cur, y, ex, y))
                if i.get('to_pin'):
                    segs.append((ex, y, i['to_pin'], y))
            elif i['end'] > cur:                          # an empty rung, the top rung after an open ENO
                segs.append((cur, y, i['end'], y))
        for n, yl in vert.items():
            if len(yl) > 1 and n in x:
                segs.append((x[n], min(yl), x[n], max(yl)))
        return segs, terms

    # ---------------------------------------------------------------- svg
    def _placed(self):
        """(element, x, y) of every element drawn."""
        for k, i in enumerate(self.info):
            for p in i['placed']:
                if not isinstance(p[0], str):
                    yield p[0], p[1], self.ys[k]

    def marks(self, status, other, side=None, partner=None):
        """[(eid, status, layer, x, y, w, h)]: the diff marks (View.marks) of the elements that are not 'same', and of
        those whose operand partner, the other version's Layout, draws otherwise. side: 'removed' on the before pane,
        'added' on the after pane: the status (the colour) of what changed."""
        out = []
        for el, ex, y in self._placed():
            st = status.get(el.eid, 'same')
            o = other.get(el.eid)
            keys = changed_params(el, o) if st == 'changed' and o is not None else set()
            v = self.views[el.eid]
            if st in ('same', 'changed') and o is not None and partner is not None and o.eid in partner.views:
                pv = partner.views[o.eid]
                if getattr(v, 'dbcall', None) or getattr(pv, 'dbcall', None):
                    keys -= {'#call'}                     # it compares the names of the DBs: what each version draws tells head from DB
                keys |= v.drawn_otherwise(pv)
                st = 'changed' if keys else st
            elif '#call' in keys and getattr(v, 'dbcall', None):
                keys.add('#dbname')                       # the other version not at hand: both, rather than one that did not change
            if st == 'same':
                continue
            fill = side if st == 'changed' and side else st
            out += [(el.eid, fill) + m for m in self.views[el.eid].marks(ex, y, st, keys, o)]
        return out

    def svg(self, status=None, other=None, scale=1.0, side=None, partner=None):
        status = status or {}
        other = other or {}
        segs, _ = self.wiring()
        inbox = {}
        body = []
        for eid, st, layer, x, y, w, h in self.marks(status, other, side, partner):
            r = '<rect class="hl %s" x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (
                st, x, y, w, h, FILL[st])
            if layer == 'under':
                body.append(r)                            # below every line: no wire is cut
            else:
                inbox[eid] = inbox.get(eid, '') + r
        body += [_ln(*segs[0], color=C_WIRE, w=2.2)] + [_ln(*sg) for sg in segs[1:]]
        for el, ex, y in self._placed():
            st = status.get(el.eid, 'same')
            body.append('<g class="el"><title>%s</title>' % escape(_tip(el, other.get(el.eid), st)))
            body += self.views[el.eid].draw(ex, y, inbox.get(el.eid, ''))
            body.append('</g>')
        w, h = self.width, self.height
        if self.label:
            dy = LABEL_Y + LABEL_H - 2                    # the rail (from y 2) starts at the label's bottom
            body = [self._label_svg(side), '<g transform="translate(0,%d)">' % dy] + body + ['</g>']
            h += dy
        return ('<svg xmlns="http://www.w3.org/2000/svg" class="lad" viewBox="0 0 %d %d" width="%d" height="%d" '
                'font-family="Arial, Helvetica, sans-serif">%s</svg>' % (w, h, w * scale, h * scale, ''.join(body)))

    def _label_svg(self, side=None):
        """The jump label box (module doc); side: as marks, for a renamed label."""
        fill = FILL.get(side if self.mark == 'changed' and side else self.mark, C_LABEL)
        x, y = X0 - 1, LABEL_Y
        tip = {'changed': 'Jump label renamed', 'added': 'Jump label added', 'removed': 'Jump label removed'}
        return ('<g class="jl"><title>%s</title><rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>%s%s'
                '<text x="%.1f" y="%d" fill="%s" text-anchor="middle" font-size="%d">%s</text></g>'
                % (escape(tip.get(self.mark, 'Jump label')), x, y, CELL, LABEL_H, fill,
                   _ln(x, y + 4, x + CELL, y + 4, color='#000', w=2),
                   _ln(x, y + LABEL_H - 4, x + CELL, y + LABEL_H - 4, color='#000', w=2),
                   x + CELL / 2.0, y + 20, C_OP, FONT, escape(self.label)))


def _tip(el, other, st):
    def show(e):
        if e.kind in ('contact', 'coil'):
            return '%s %s' % (e.instr, plain_operand(e.operand()))
        return '%s(%s)' % (e.instr if e.instr != 'CALL' else (e.call or e.instance),
                           ', '.join('%s%s%s' % (n or '', (' %s ' % d) if d else '', plain_operand(v)) for n, d, v in e.params))
    t = show(el)
    if st == 'changed' and other is not None:
        t += '\n↔ ' + show(other)
    elif st == 'moved':
        t += '\nmoved'
    return t

