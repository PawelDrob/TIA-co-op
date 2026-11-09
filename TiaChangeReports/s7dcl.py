"""Parse a SIMATIC SD block (.s7dcl + .s7res) into interface + networks; LAD networks into rungs and elements.

Grammar: docs/agent/s7dcl-format.md section 8. Only what the renderer and the diff need.
"""
import itertools
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from . import instructions
from .names import decl_name, object_name

LANG = 'en-US'
SET_IN_IDB = 'Set in IDB'      # the retain of a DB_SPECIFIC section's members (SimaticML: Remanence="SetInIDB")


# ---------------------------------------------------------------- resources

def all_texts(text):
    """MLC id -> every language's text, in one order."""
    data = (yaml.safe_load(text) if text else None) or {}
    return {e['id']: sorted((k, str(v)) for k, v in e.items() if k != 'id')
            for e in data.get('MultiLingualTexts') or [] if isinstance(e, dict) and 'id' in e}


def text_entries(text, lang=None):
    """[(the text in the report's language, ((language, text), ...) in the others)] of an .s7res, the entries with a text
    in another language."""
    lang = lang or LANG
    out = []
    for texts in all_texts(text).values():
        others = tuple((k, v) for k, v in texts if k != lang and v.strip())
        if others:
            out.append((next((v for k, v in texts if k == lang), ''), others))
    return out


def parse_res(text, lang=None):
    """MLC id -> text in `lang` (default LANG; else the first language of the entry)."""
    lang = lang or LANG
    if not text:
        return {}
    data = yaml.safe_load(text) or {}
    out = {}
    for e in data.get('MultiLingualTexts') or []:
        if not isinstance(e, dict) or 'id' not in e:
            continue
        txt = e.get(lang)
        if txt is None:
            txt = next((v for k, v in e.items() if k != 'id'), None)
        if txt is not None:
            out[e['id']] = str(txt)
    return out


def _pragmas(text):
    """'{ A := "x"; B := TRUE }' body -> {A: 'x', B: 'TRUE'}."""
    out = {}
    for part in re.split(r';\s*(?=[A-Za-z_]\w*\s*(?::=|$))', text.strip().strip('{}').strip()):
        m = re.match(r'\s*([A-Za-z_]\w*)\s*(?::=\s*(.*))?$', part.strip(), re.S)
        if m:
            v = (m.group(2) or '').strip().rstrip(';').strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            out[m.group(1)] = v
    return out


# ---------------------------------------------------------------- interface

@dataclass
class Member:
    name: str
    type: str = ''
    comment: Optional[str] = None
    value: Optional[str] = None          # default value (constants: the value)
    section: str = ''                    # INPUT OUTPUT IN_OUT STAT TEMP CONSTANT UDT
    children: dict = field(default_factory=dict)
    attrs: dict = field(default_factory=dict)    # pragmas other than the comment id (S7_Access, S7_SetPoint, ...)
    retain: object = False               # True, False or SET_IN_IDB


class Interface:
    def __init__(self):
        self.root = Member('')
        self.start = {}                  # DB start values after the declarations: path -> (value, comment)

    def lookup(self, operand, types=None):
        """Members along the path of a local operand '#a.b[1].c' (as far as the interface declares them). types:
        name -> Interface of a UDT or FB (compare.Callees): the path goes on into the members of a member's type;
        with types.db also a global DB operand '"DB".a.b' (members of the DB, or of its UDT or FB)."""
        if operand.startswith('#'):
            node, segs = self.root, _segments(operand[1:])
        elif operand.startswith('"') and getattr(types, 'db', None):
            segs = _segments(operand)
            db = types.db(segs[0]) if len(segs) > 1 else None
            if db is None or db.interface is None:
                return []
            node, segs = db.interface.root, segs[1:]
        else:
            return []
        path = []
        for seg in segs:
            nxt = node.children.get(seg)
            if nxt is None and path and types:
                itf = types(type_name(node.type))
                nxt = itf.root.children.get(seg) if itf else None
            if nxt is None:
                break
            node = nxt
            path.append(node)
        return path

    def comment_of(self, operand, types=None):
        """Comment of the deepest member along the path that has one (TIA falls back to the enclosing member);
        with types also inside UDTs (and multi-instances)."""
        for m in reversed(self.lookup(operand, types)):
            if m.comment:
                return m.comment
        return None

    def constant(self, operand):
        p = self.lookup(operand)
        if len(p) == 1 and p[0].section == 'CONSTANT':
            return p[0]
        return None


def type_name(t):
    """Name of the UDT or FB a data type refers to: '_.X', '"X"', 'Array[0..3] of _.X' -> 'X'."""
    t = re.sub(r'^Array\s*\[.*\]\s*of\s+', '', (t or '').strip(), flags=re.I)
    if t.startswith('_.'):
        t = t[2:]
    return t.replace('$"', '').strip('"')


def _segments(path):
    """'a."b"[1, #x].c' -> ['a', 'b', 'c'] (indices dropped)."""
    out, cur, depth, quote = [], '', 0, False
    for ch in path:
        if quote:
            if ch == '"':
                quote = False
            else:
                cur += ch
        elif ch == '"':
            quote = True
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        elif depth:
            pass
        elif ch == '.':
            out.append(cur)
            cur = ''
        else:
            cur += ch
    out.append(cur)
    return [s.strip() for s in out if s.strip()]


def _open(text):
    """The brackets ( [ that text leaves open (outside quotes)."""
    depth, quote = 0, None
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in '\'"':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
    return depth


class _Init:
    """A structured initializer as TIA writes it over several lines: '[ ... ]' the elements of an array ('n(x)': n
    elements x), '( name := x, ... )' the members of a struct or UDT instance, '()' the default; a pragma in front of
    an element or member holds its comment -> ('list', [(n, mlc, x)]), ('struct', [(name, mlc, x)]), ('default',),
    ('scalar', text)."""
    _REPEAT = re.compile(r'\s*(\d+)\(')
    _FIELD = re.compile(r'\s*("[^"]*"|[A-Za-z_]\w*)\s*:=')

    def __init__(self, text):
        self.s, self.i = text, 0

    def peek(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1
        return self.s[self.i:self.i + 1]

    def eat(self, ch):
        if self.peek() != ch:
            raise ValueError('%r expected at %d' % (ch, self.i))
        self.i += 1

    def mlc(self):
        if self.peek() != '{':
            return None
        j = self.s.index('}', self.i)
        p, self.i = _pragmas(self.s[self.i:j + 1]), j + 1
        return p.get('S7_MLC')

    def value(self):
        c = self.peek()
        if c == '[':
            self.i += 1
            items = []
            while self.peek() != ']':
                mlc = self.mlc()
                m = self._REPEAT.match(self.s, self.i)
                if m:
                    self.i = m.end()
                    x = self.value()
                    self.eat(')')
                    items.append((int(m.group(1)), mlc, x))
                else:
                    items.append((1, mlc, self.value()))
                if self.peek() == ',':
                    self.i += 1
            self.i += 1
            return ('list', items)
        if c == '(':
            self.i += 1
            if self.peek() == ')':
                self.i += 1
                return ('default',)
            if not self._FIELD.match(self.s, self.i) and self.peek() != '{':
                x = self.value()
                self.eat(')')
                return x
            fields = []
            while self.peek() != ')':
                mlc = self.mlc()
                m = self._FIELD.match(self.s, self.i)
                if not m:
                    raise ValueError('member expected at %d' % self.i)
                self.i = m.end()
                fields.append((m.group(1).strip('"'), mlc, self.value()))
                if self.peek() == ',':
                    self.i += 1
            self.i += 1
            return ('struct', fields)
        j, quote = self.i, None
        while j < len(self.s) and (quote or self.s[j] not in ',)]'):
            if quote:
                quote = None if self.s[j] == quote else quote
            elif self.s[j] in '\'"':
                quote = self.s[j]
            j += 1
        x, self.i = self.s[self.i:j].strip(), j
        return ('scalar', x)


def _seg(name):
    return name if re.match(r'^[A-Za-z_]\w*$', name) else '"%s"' % name


def _index(typ, k):
    """The index of an array's k-th element in its initializer ('[2]', '[1,0]', row by row), None when the bounds
    are not known here (a constant; the first element only when its lower bounds are; not an array)."""
    m = re.match(r'Array\s*\[(.*?)\]\s*of\s', typ or '', re.I)
    if not m:
        return None
    dims = [[x.strip() for x in d.split('..')] for d in m.group(1).split(',')]
    low = [re.sub(r'^_\."?([^"]*)"?$', r'"\1"', d[0]) for d in dims]
    if k == 0:
        return '[%s]' % ','.join(low)
    if not all(re.match(r'^-?\d+$', d[0]) for d in dims) or \
            not all(len(d) == 2 and re.match(r'^-?\d+$', d[1]) for d in dims[1:]):
        return None
    out = []
    for d in reversed(dims[1:]):
        size = int(d[1]) - int(d[0]) + 1
        out.append(int(d[0]) + k % size)
        k //= size
    return '[%s]' % ','.join(str(x) for x in [int(dims[0][0]) + k] + out[::-1])


def _entries(x, path, decl, res, out, mlc=None):
    """path -> (value, comment) of the elements and members that an initializer gives a value or a comment; decl:
    the member it initializes, whose array bounds and struct members name the elements below it."""
    if mlc or x[0] == 'scalar':
        out[path] = (x[1] if x[0] == 'scalar' else '()', res.get(mlc) if mlc else None)
    if x[0] == 'struct':
        for name, c, y in x[1]:
            _entries(y, '%s.%s' % (path, _seg(name)), decl.children.get(name) if decl else None, res, out, c)
    elif x[0] == 'list':
        k = 0
        for n, c, y in x[1]:
            for _ in range(n):
                idx = _index(decl.type if decl else '', k)
                if idx is not None:
                    _entries(y, path + idx, decl, res, out, c)
                k += 1


def _initializer(value, lines, i, decl, path, res, start):
    """A structured initializer (TIA writes it over several lines; the lines it takes): its elements and members
    into the start values, as a DB's start values. The lines index after it."""
    while _open(value) > 0 and i < len(lines):
        value += '\n' + lines[i]
        i += 1
    try:
        _entries(_Init(value.strip().rstrip(';')).value(), path, decl, res, start)
    except (ValueError, IndexError):
        pass
    return i


def parse_interface(text, res, db=False):
    """Declarations (VAR sections, or the STRUCT of a TYPE) as a member tree; DB start values after them. db: a
    DATA_BLOCK, whose start values may stand without a VAR section (an instance DB, a DB of a UDT)."""
    itf = Interface()
    stack = [itf.root]
    section = ''
    retain = False
    pending = {}
    after_vars = db
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        t = lines[i].strip()
        i += 1
        if not t:
            continue
        if t.startswith('{'):
            body = t
            while '}' not in body and i < len(lines):
                body += chr(10) + lines[i]
                i += 1
            pending = _pragmas(body[:body.index('}') + 1])
            continue
        m = re.match(r'^VAR(?:_(INPUT|OUTPUT|IN_OUT|TEMP))?(?:\s+(CONSTANT|RETAIN|NON_RETAIN|DB_SPECIFIC))?\s*$', t)
        if m:
            section = 'CONSTANT' if m.group(2) == 'CONSTANT' else (m.group(1) or 'STAT')
            retain = {'RETAIN': True, 'DB_SPECIFIC': SET_IN_IDB}.get(m.group(2), False)
            stack = [itf.root]
            pending = {}
            continue
        if re.match(r'^TYPE\b', t):
            section, stack, pending = 'UDT', [itf.root], {}
            continue
        if t.startswith('END_VAR'):
            section = ''
            after_vars = True
            continue
        if t.startswith('END_STRUCT'):
            if ':=' in t and len(stack) > 1:                 # an array of struct's initializer
                i = _initializer(t.split(':=', 1)[1].strip(), lines, i, stack[-1],
                                 '.'.join(_seg(s.name) for s in stack[1:]), res, itf.start)
            if len(stack) > 1:
                stack.pop()
            pending = {}
            continue
        if not section:
            m = re.match(r'^(.+?)\s*:=\s*(.*?);$', t)
            if after_vars and m:                          # DB start value
                mlc = pending.get('S7_MLC')
                itf.start[m.group(1).strip()] = (m.group(2).strip(), res.get(mlc) if mlc else None)
            pending = {}
            continue
        m = re.match(r'^("[^"]+"|[A-Za-z_]\w*)\s*:\s*(.*?)\s*;?\s*$', t)
        if not m:
            pending = {}
            continue
        name = m.group(1).strip('"')
        rest = m.group(2)
        value = None
        if ':=' in rest:
            rest, value = [x.strip() for x in rest.split(':=', 1)]
            value = value.rstrip(';').strip()
        mlc = pending.get('S7_MLC')
        attrs = {k: v for k, v in pending.items() if k != 'S7_MLC'}
        mem = Member(name, rest.rstrip(';').strip(), res.get(mlc) if mlc else None, value, section,
                     attrs=attrs, retain=retain)
        stack[-1].children[name] = mem
        if value and value[0] in '([':
            i = _initializer(value, lines, i, mem, '.'.join(_seg(s.name) for s in stack[1:] + [mem]), res, itf.start)
            mem.value = None
        if rest.upper().rstrip(';').strip().endswith('STRUCT'):
            stack.append(mem)
        pending = {}
    if len(itf.root.children) == 1:                       # a TYPE: show the members of its STRUCT
        only = next(iter(itf.root.children.values()))
        if only.section == 'UDT' and only.children:
            itf.root.children = only.children
            top = _seg(only.name) + '.'
            itf.start = {k[len(top):] if k.startswith(top) else k: v for k, v in itf.start.items()}
    return itf


_KIND = re.compile(r'^(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\b[ \t]*([^\n]*)', re.M)
_TYPE_NAME = re.compile(r'\s*(?:\{[^}]*\}\s*)?([^\n]*)')     # TYPE alone on its line: a pragma block, then the name


def declared_name(text):
    """The name an .s7dcl declares its object under, '' when it declares none."""
    m = _KIND.search(text)
    return decl_name(m.group(2).strip() or _TYPE_NAME.match(text, m.end()).group(1)) if m else ''


def parse_header(text, res):
    """(kind, rest of the declaration line, properties) from the pragma block in front of the declaration;
    title and comment ids resolved to their texts."""
    m = _KIND.search(text)
    kind, line = (m.group(1), m.group(2).strip()) if m else ('', '')
    head = text[:m.start()] if m else ''
    props = {}
    if '{' in head:
        props = _pragmas(head[head.index('{'):head.rindex('}') + 1])
    for k in ('S7_BlockTitle', 'S7_BlockComment'):
        if k in props:
            props[k] = res.get(props[k], props[k])
    return kind, line, props


# ---------------------------------------------------------------- LAD

@dataclass
class Element:
    eid: str
    instr: str                    # Contact, I_Contact, EQ_Contact, S_Coil, Move, TON, <call>
    instance: Optional[str]       # #inst for timers / FB calls
    params: list                  # [(name|None, ':=' | '=>' | None, value)]
    templates: dict               # S7_Templates values; a Switch also its relations ('CASE0': '==')
    call: Optional[str] = None    # FB / FC name for calls
    expression: Optional[str] = None   # Calculate: S7_Expression
    no_eno: bool = False          # ENO not generated (ENO := EN): TIA draws it gray
    more: dict = field(default_factory=dict)     # SimaticML: the other type templates, no part of the instruction's text

    @property
    def kind(self):
        i = self.instr
        if i in CMP:
            return 'compare'
        known = instructions.form(i)
        if known:
            return known
        if i.endswith('Contact') or i == 'Not':
            return 'contact'
        if i.endswith('Coil') or i in ('Return', 'ReturnTrue', 'ReturnFalse'):
            return 'coil'
        return 'box'

    def operand(self):
        """The inline operand of a contact / coil (first parameter value)."""
        return self.params[0][2] if self.params else ''

    def sig(self):
        ps = tuple((n or '', d or '', _norm(v)) for n, d, v in self.params)
        return (self.instr, self.instance or '', self.call or '', ps, tuple(sorted(self.templates.items())),
                norm_expression(self.expression), self.no_eno)


CMP = {'EQ_Contact': '==', 'NE_Contact': '<>', 'LT_Contact': '<', 'GT_Contact': '>',
       'LE_Contact': '<=', 'GE_Contact': '>='}

# relation of a Switch case: the SimaticML export's operation -> the .s7dcl export's pragma value, as TIA shows it
RELATIONS = {'EQ': '==', 'NE': '<>', 'LT': '<', 'GT': '>', 'LE': '<=', 'GE': '>='}


def norm_expression(e):
    """A Calculate expression as compared: without blanks, in upper case (both exports write IN1; the s7dcl guide's
    example in1)."""
    return re.sub(r'\s+', '', e or '').upper()

# Instruction names that appear on an instance ('#inst.TON(') rather than being an FB called by instance name.
INSTANCE_INSTR = {'TON', 'TOF', 'TP', 'TONR', 'R_TRIG', 'F_TRIG', 'Ctu', 'Ctd', 'Ctud', 'CTU', 'CTD', 'CTUD',
                  'S_RS', 'S_SR', 'RS', 'SR'}


def wire_of(v):
    """The wire feeding a parameter ('wire#w1', on a negated pin 'NOT wire#w1'), None when an operand or nothing does."""
    m = re.match(r'(?:NOT\s+)?wire#(.*)', v.strip(), re.I)
    return m.group(1).lower() if m else None


def _norm(v):
    v = re.sub(r'\s+', ' ', v.strip())
    if wire_of(v) is None:
        return v
    return 'NOT wire#' if v.startswith('NOT ') else 'wire#'     # wire names are renumbered by the exporter


@dataclass
class Rung:
    start: str                    # node name ('powerrail' or wN)
    items: list                   # Element | ('node', name)
    end: Optional[str]            # node name or None (rung ends in its last element)


def parse_lad(body, prefix, itf=None):
    rungs = []
    cur = None
    pend = {}
    lines = body.splitlines()
    i = 0
    n = 0
    while i < len(lines):
        t = lines[i].strip()
        i += 1
        if not t or t.startswith('//'):
            continue
        if t.startswith('{'):
            blk = t
            while '}' not in blk and i < len(lines):
                blk += '\n' + lines[i]
                i += 1
            pend.update(_pragmas(blk[:blk.index('}') + 1]))
            continue
        m = re.match(r'^RUNG\s+wire#(\w+)', t, re.I)
        if m:
            cur = Rung(m.group(1).lower(), [], None)
            continue
        m = re.match(r'^END_RUNG(?:\s+wire#(\w+))?', t, re.I)
        if m:
            cur.end = m.group(1).lower() if m.group(1) else None
            rungs.append(cur)
            cur = None
            continue
        m = re.match(r'^wire#(\w+)$', t, re.I)
        if m:
            cur.items.append(('node', m.group(1).lower()))
            continue
        m = re.match(r'^(.*?)\((.*)$', t)
        if not m or cur is None:                  # Label(x) before the first rung: Network.label (_LABEL)
            continue
        head, rest = m.group(1).strip(), m.group(2)
        params = []
        if rest.strip() and rest.rstrip().endswith(')'):
            inner = rest.rstrip()[:-1].strip()
            if inner:
                params = _param_list([inner]) if (':=' in inner or '=>' in inner) else [(None, None, inner)]
        else:
            plines = []
            while i < len(lines):
                pt = lines[i].strip()
                i += 1
                if pt == ')' or pt == ');':
                    break
                if pt:
                    plines.append(pt)
            params = _param_list(plines)
        templates = {}
        if 'S7_Templates' in pend:
            for part in pend['S7_Templates'].strip('[] ').split(','):
                if ':=' in part:
                    k, v = part.split(':=', 1)
                    templates[k.strip()] = v.strip()
        templates.update((k, v) for k, v in pend.items() if re.match(r'CASE\d+$', k))   # Switch: CASE0 := "=="
        if 'S7_Relation' in pend:                         # T_COMP, S_COMP: S7_Relation := "EQ"
            templates['relation'] = pend['S7_Relation']
        n += 1
        el = _element('%s%d' % (prefix, n), head, params, templates, itf)
        _fill_f_type(el, pend, itf)
        el.expression = pend.get('S7_Expression')
        eno = pend.get('S7_GenerateENO', '').upper()      # Calculate: ENO off unless generated [INFERRED], 8.6
        el.no_eno = eno == 'FALSE' or (head == 'Calculate' and eno != 'TRUE')
        pend = {}
        cur.items.append(el)
    return rungs


def _param_list(plines):
    out = []
    for pt in plines:
        pt = pt.rstrip().rstrip(',').rstrip()
        m = re.match(r'^("[^"]+"|[A-Za-z_]\w*)\s*(:=|=>)\s*(.*)$', pt)        # a quoted name: "iSq01/05"
        if m:
            out.append((m.group(1).strip('"'), m.group(2), m.group(3).strip()))
        elif pt:
            out.append((None, None, pt))
    return out


def _element(eid, head, params, templates, itf=None):
    if head.startswith('#'):
        base, _, last = head.rpartition('.')
        if base and (last in INSTANCE_INSTR or last.endswith('_Coil') or last.endswith('Coil')
                     or _instance_of(itf, base, last)):
            return Element(eid, last, base, params, templates)
        return Element(eid, 'CALL', head, params, templates, call=None)     # multi-instance FB call
    m = re.match(r'^("[^"]+")\.(\w+)$', head)
    if m:                                                                    # "DB".ESTOP1: single-instance DB
        return Element(eid, m.group(2), m.group(1), params, templates)
    if head.startswith('"'):
        return Element(eid, 'CALL', None, params, templates, call=head.strip('"'))
    if '.' in head and not head.startswith('#'):
        base, _, last = head.rpartition('.')                                 # single-instance DB.TON etc.
        return Element(eid, last, base, params, templates)
    return Element(eid, head, None, params, templates)


def _fill_f_type(el, pragmas, itf):
    """The type an F-box's .s7dcl leaves out, only where nothing says another: a type already read wins, and an instance has to be of the box's own type, written
    without quotes, as on TIA's screen (TON, not IEC_LTIMER, not a DB of its own whose type this file does not hold). A box without an instance: SHR."""
    fill = instructions.f_templates(el.instr, pragmas)
    if not fill or el.instance and not _plain_instance(itf, el):
        return
    for template, typ in fill.items():
        el.templates.setdefault(template, typ)


def _plain_instance(itf, el):
    p = itf.lookup(el.instance) if itf and el.instance.startswith('#') else []
    return _instance_of(itf, el.instance, el.instr) and '"' not in p[-1].type and '_.' not in p[-1].type


def _instance_of(itf, base, instr):
    """#inst.ESTOP1: the instance is declared with that instruction as its type (a system FB such as ESTOP1)."""
    p = itf.lookup(base) if itf else []
    return bool(p) and len(p) == len(_segments(base[1:])) and type_name(p[-1].type).lower() == instr.lower()


# ---------------------------------------------------------------- block

@dataclass
class Network:
    index: int                    # 1-based, as TIA numbers them
    lang: str
    title: str
    comment: str
    body: str
    rungs: Optional[list] = None  # LAD
    label: str = ''               # its jump label (LAD, FBD: TIA's box over the network)
    source: object = None         # its part of the file, to compare with what the report read
    raw: object = field(default=None, repr=False, compare=False)    # that part as read, to read again (beside.py)


@dataclass
class Block:
    name: str                    # as TIA names it (names.object_name), not its file's name
    label: str
    interface: Interface
    networks: list
    kind: str = ''               # FUNCTION_BLOCK FUNCTION ORGANIZATION_BLOCK DATA_BLOCK TYPE
    decl: str = ''               # rest of the declaration line ('"Filler"', ': Void', 'X : typeX')
    props: dict = field(default_factory=dict)
    auto_number: Optional[str] = None  # TIA's number under automatic numbering (XML only): drawn, not compared
    callees: Optional[object] = None  # name -> Interface of a block it calls, from its snapshot (compare.Callees)


_NET = re.compile(r'\{([^{}]*?S7_Language[^{}]*)\}\s*\n\s*NETWORK[ \t]*\n(.*?)\n[ \t]*END_NETWORK\b', re.S)


_blocks = itertools.count(1)

# A network's jump label: `Label(name)` on the line after NETWORK, before its first RUNG (V20 Update 7)
_LABEL = re.compile(r'\s*Label\(\s*([^()\s]+)\s*\)[ \t]*$', re.M)


def parse_block(src, lang=None):
    if getattr(src, 'xml', None) is not None:                 # a SimaticML export (an OB): the same model
        from .simaticml import parse_block as parse_xml
        return parse_xml(src, lang)
    text = src.s7dcl
    m = _KIND.search(text)
    if not m or not re.search(r'^\s*END_%s\b' % m.group(1), text[m.end():], re.M):   # empty, another file
        raise ValueError('%s: not a SIMATIC SD block export: %s' % (src.label, 'no END_' + m.group(1) if m else
                                                                    'empty' if not text.strip() else 'no block'))
    tag = next(_blocks)              # element ids unique across parsed blocks: before and after never collide
    res = parse_res(src.s7res, lang)
    kind, decl, props = parse_header(text, res)
    first = _NET.search(text)
    body = text[m.end():first.start()] if first else text[m.end():]
    if kind == 'TYPE':
        body = text[m.start():]
    itf = parse_interface(body, res, db=kind == 'DATA_BLOCK')
    nets = [network(k, m.group(1), m.group(2), res, itf, tag) for k, m in enumerate(_NET.finditer(text), 1)]
    return Block(object_name(src.name, declared_name(text)), src.label, itf, nets, kind, decl, props)


def network(k, pragma, body, res, itf, tag):
    """The k-th network of a block from its pragma block's settings and its lines; tag: the block's number, which keeps
    the element ids apart."""
    pr = _pragmas('{' + pragma + '}')
    lang_ = pr.get('S7_Language', '')
    nbody = _mlc_texts(body, res) if lang_ != 'LAD' else body
    net = Network(k, lang_, res.get(pr.get('S7_NetworkTitle', ''), ''), res.get(pr.get('S7_NetworkComment', ''), ''), nbody,
                  source=_network_source(pragma, body, res, lang_), raw=('sd', pragma, body, res, itf))
    lm = _LABEL.match(nbody)
    net.label = lm.group(1) if lm else ''
    if lang_ == 'LAD':
        net.rungs = parse_lad(nbody, 'b%dn%d_' % (tag, k), itf)
    return net


def numbered(network):
    """A network's text with its wires numbered by first appearance, the power rail as it is; a wire's name in any case
    (STEP 7 is not case-sensitive)."""
    wires = {'powerrail': 'powerrail'}
    return re.sub(r'\bwire#(\w+)', lambda m: 'wire#%s' % wires.setdefault(m.group(1).lower(), len(wires)), network, flags=re.I)


def lad_lines(body):
    """A LAD network's text as compared: wires numbered, without what the two export formats write differently (the
    indentation, the trailing comma an XML export writes after the last parameter, a space after an empty output)."""
    lines = (l.strip() for l in numbered(body).splitlines())
    return [re.sub(r'\s*,$', '', l) for l in lines if l]


def texts_for_keys(s, res):
    """An .s7dcl's text with each quoted key of its .s7res (res: parse_res) as that text: TIA numbers the keys per copy."""
    return re.sub(r'"([^"\n]*)"', lambda m: '"%s"' % res.get(m.group(1), m.group(1)), s)


def _network_source(pragma, body, res, lang):
    """A network's part of an .s7dcl as compared: its settings and lines in the report's language, the keys in its texts
    (TIA numbers them per copy) and the layout left out; language, title and comment are read and compared as such."""
    def text(s):
        return texts_for_keys(s, res)
    settings = sorted(x.strip() for x in text(pragma).split(';')
                      if x.strip() and not re.match(r'\s*S7_(Language|NetworkTitle|NetworkComment)\b', x))
    return 'sd', settings, lad_lines(text(body)) if lang == 'LAD' else scl_lines(text(body))


_MLC = re.compile(r'\{\s*S7_MLC\s*:=\s*"([^"]*)"\s*\}')


def _mlc_texts(body, res):
    """`{ S7_MLC := "MLC_4Xw" }` in an SCL body as what it is, a multilingual comment as the palette and a SimaticML export
    of it have it: `(/* text */)`, with the text instead of the key, which TIA renumbers per project copy; the
    lines of a text after its first at the pragma's indentation. An id the `.s7res` does not hold stays."""
    def text(m):
        t = res.get(m.group(1))
        if t is None:
            return m.group(0)
        line = body[body.rfind('\n', 0, m.start()) + 1:m.start()]
        ind = line[:len(line) - len(line.lstrip())]
        return '(/*%s*/)' % t.replace('\n', '\n' + ind)
    return _MLC.sub(text, body)


def scl_lines(body):
    """Body lines of an SCL network, common indentation removed, trailing blanks dropped."""
    lines = [l.rstrip() for l in body.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    ind = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return [l[ind:] for l in lines]
