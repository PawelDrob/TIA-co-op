"""Interface diff of two block versions: members by path (a member moved to another section is 'moved'),
compared on section, data type (as TIA names it), default value, comment, retain and attributes (S7_Access,
S7_SetPoint, ...); block properties (version, title, comment, number, ...). DB start values are members of the tree
too: a start value of a member inside a UDT, struct or array goes under that member (an array element as 'x[2]'),
as TIA's DB editor shows it. Such a member named on one side only, but in the type on both, is 'changed'
(its comment or start value set or cleared), not 'added' / 'removed'. Such inner rows show TIA's
disabled boxes from the UDT and their parent, and the type's other members go under the instance. Every
row shows TIA's disabled cells gray and its disabled boxes as disabled boxes, not as blanks.

Renames: a removed and an added member of the same parent and section are one renamed member by
their comment or by their place among unchanged neighbours (_pairs); a member moved into or out of a struct keeps
its name or is removed and added. Members that left the common order of their siblings are 'moved' (order), as are
members moved to another section or struct.

rows(before, after) -> [Row]: every member of both versions in the order of the after version, removed ones after
their former predecessor. html(...) shows them as TIA's interface editor does (sections as tree rows, members under
their parent, TIA's attribute columns): the changed rows with their parents, the unchanged ones folded in place."""
import copy
import re
from dataclasses import dataclass, field
from html import escape, unescape
from types import SimpleNamespace
from typing import Optional

from .names import decl_name, decl_type
from .render_lad import default_value
from .s7dcl import Interface, Member, SET_IN_IDB, type_name

SECTIONS = [('INPUT', 'Input'), ('OUTPUT', 'Output'), ('IN_OUT', 'InOut'), ('STAT', 'Static'), ('TEMP', 'Temp'),
            ('CONSTANT', 'Constant'), ('RETURN', 'Return'), ('UDT', 'Members')]
NO_BOXES = ('TEMP', 'CONSTANT', 'RETURN')
FIELDS = ('section', 'type', 'value', 'comment', 'retain', 'attrs')
PROPS = [('S7_BlockTitle', 'Title'), ('S7_BlockComment', 'Comment'), ('S7_Version', 'Version'),
         ('S7_BlockNumber', 'Number'), ('S7_Optimized', 'Optimized access'), ('S7_IECCheck', 'IEC check'),
         ('S7_PreferredLanguage', 'Language'), ('S7_GenerateENOforSCL', 'ENO for SCL'),
         ('S7_StandardRetain', 'Retain'), ('S7_Safety', 'Safety')]


@dataclass
class Row:
    path: tuple
    b: Optional[Member]
    a: Optional[Member]
    changes: set = field(default_factory=set)      # FIELDS, 'name' (renamed), 'order', 'parent'
    bpath: Optional[tuple] = None                  # the path in the before version
    order: Optional[tuple] = None                  # (was, now): 'first', 'last' or 'after <sibling>'

    @property
    def state(self):
        if self.b is None:
            return 'added'
        if self.a is None:
            return 'removed'
        if self.changes and self.changes <= {'order', 'section', 'parent'}:
            return 'moved'
        return 'changed' if self.changes else 'same'

    @property
    def m(self):
        return self.a or self.b


@dataclass
class Inner(Member):
    """A member inside a UDT, struct or array of a DB that only a start value line names; type, comment and default
    value (inherited, shown gray) and attributes from the UDT when the input holds it; up: the accessible,
    writable and visible of its parent, which limit its own; decl: the member as the UDT declares it, whose
    children are the members of a struct (or of an array element's struct) in the UDT."""
    inherited: Optional[str] = None
    dflt: Optional[str] = None
    up: tuple = (True, True, True)
    decl: Optional[Member] = None


def tia_type(t):
    """A data type as TIA shows it: '_.X' / '_."X"' -> '"X"' (also in array bounds), STRUCT -> Struct."""
    t = re.sub(r'"\$"(.*?)\$""', r'"\1"', t or '')
    t = re.sub(r'(?<![\w"])_\.(?:"([^"]*)"|([\w/+\-]+))', lambda m: '"%s"' % (m.group(1) or m.group(2)), t)
    return re.sub(r'\bSTRUCT\b', 'Struct', t)


# DB_WWW and PORT: TIA keeps them as numbers, a start value 0 and an empty Setpoint box (a shot of a global
# DB). DB_DYN, PIP and RTM the same by their names only, on no shot.
_ELEMENTARY = re.compile(r'^(bool|byte|word|dword|lword|sint|int|dint|lint|usint|uint|udint|ulint|real|lreal|s5time|'
                         r'time|ltime|date|tod|time_of_day|ltod|ltime_of_day|dt|date_and_time|ldt|char|wchar|'
                         r'w?string(\s*\[.*\])?|variant|pointer|any|db_any|db_www|db_dyn|port|pip|rtm|hw_\w+|conn_\w+|event_\w+|ob_\w+|'
                         r'ref_to\b.*)$', re.I)


def structured(t):
    """A UDT, struct, array or FB instance (TIA can unfold it)."""
    return bool(t) and not _ELEMENTARY.match(t.strip())


def setpoint_default(t, section, safety=False):
    """TIA's Setpoint box of a member without a setting. On shots of 2026-11-04 against the exports: ticked
    on an FB or UDT instance in a static of a standard FB, a UDT instance in a global DB or a UDT, a structured system
    type in a global DB; empty on an elementary type. By SimaticML alone, false: a DTL, an array of an elementary type,
    an instance in an F-FB; no setting: an in-out. Drawn so, not seen in TIA: other system types in a DB and an instance
    in a struct, ticked; an array of a structured type, an input or output of a UDT, an F-block's instances, empty.
    Replaces an earlier rule, empty for every type, from shots of a project no longer here (A_1)."""
    t = (t or '').strip()
    return (section in ('STAT', 'UDT') and not safety and structured(t)
            and not _no_sp(t) and t.upper() != 'DTL' and not t.lower().startswith('array'))


def _start_keys(path):
    """'"e".q' -> ['e', 'q']; 'a.b[1].c' -> ['a', 'b', 'b[1]', 'c'] (an array element is a member of its array)."""
    out, name, idx, depth, quote = [], '', '', 0, False
    for ch in path:
        if depth:
            idx += ch
            depth += {'[': 1, ']': -1}.get(ch, 0)
            if not depth:
                out.append(out[-1] + idx)
        elif quote:
            if ch == '"':
                quote = False
            else:
                name += ch
        elif ch == '"':
            quote = True
        elif ch in '.[':
            if name.strip():
                out.append(name.strip())
            name = ''
            if ch == '[':
                depth, idx = 1, '['
        else:
            name += ch
    if name.strip():
        out.append(name.strip())
    return out


def _inner(parent, key, types, base):
    """(type, inherited comment, default value, attributes, declaration) of a member that a start value names below
    parent: an array element has the element type, the array's comment and its Setpoint, and the members of an array
    of struct; a member of a UDT (or of the DB's own type, base, or a struct in the UDT) the UDT's."""
    if key.endswith(']'):
        sp = {k: v for k, v in parent.attrs.items() if k in ('S7_Setpoint', 'S7_SetPoint')} or {'S7_Setpoint': 'False'}
        typ = re.sub(r'^Array\s*\[.*\]\s*of\s+', '', parent.type, flags=re.I)
        kids = {k: m for k, m in (getattr(parent, 'decl', None) or parent).children.items() if not k.endswith(']')}
        return (typ, parent.comment or getattr(parent, 'inherited', None), None, sp,
                Member(key, typ, children=kids) if kids else None)
    owner = _owner(parent, types, base)
    m = owner.root.children.get(key) if owner else None
    return (m.type, m.comment, m.value, dict(m.attrs), m) if m else ('', None, None, {}, None)


def _eff(m):
    """(accessible, writable, visible) of a member as TIA shows them: its own settings, limited by its parent's
    for a member inside a UDT or array (Inner)."""
    vis, acc_ = m.attrs.get('S7_Visibility', ''), m.attrs.get('S7_Access', '')
    up = getattr(m, 'up', (True, True, True))
    acc = up[0] and 'Hidden' not in vis
    return acc, acc and up[1] and 'ReadOnly' not in acc_, acc and up[2] and 'Unlisted' not in vis


def _new_inner(parent, key, types, base, old=None):
    """A top-level member of an instance DB is in the section the FB declares it in."""
    typ, inh, dflt, own, decl = _inner(parent, key, types, base)
    sec = parent.section or 'STAT'
    if not parent.section and base is not None and key in base.root.children:
        sec = base.root.children[key].section
    if not typ and old is not None:                      # the type not in the input: as the other side has it
        typ, inh, dflt, own, sec, decl = old.type, old.inherited, old.dflt, old.attrs, old.section, old.decl
    return Inner(key, typ, None, None, sec if sec in ('INPUT', 'OUTPUT', 'IN_OUT', 'STAT') else 'STAT',
                 retain=parent.retain, attrs=own, inherited=inh, dflt=dflt, up=_eff(parent), decl=decl)


def _owner(parent, types, base):
    """The interface of the UDT or FB a member is of (base: the DB's own type; a struct in a UDT: its members as the
    UDT declares them), None when the input lacks it."""
    if base is not None:
        return base
    decl = getattr(parent, 'decl', None)
    if decl is not None and decl.children:
        return SimpleNamespace(root=decl)
    return types(type_name(parent.type)) if types and parent.type else None


def _first(m):
    """The first element of an array as TIA names it: 'a[0,1]', 'a[*]', 'a["first"]' (a constant bound)."""
    dims = re.match(r'Array\s*\[(.*?)\]\s*of\s', m.type, re.I).group(1).split(',')
    return '%s[%s]' % (m.name, ','.join(tia_type(d.split('..')[0].strip()) for d in dims))


def _elements(node, types):
    """An array of struct declared here shows its first element with the struct's members under it, not the members
    under the array; decl: the members as declared, for the elements that start values name."""
    for m in node.children.values():
        if re.match(r'Array\s*\[', m.type or '', re.I) and m.children \
                and not any(k.endswith(']') for k in m.children):
            m.decl = Member(m.name, m.type, children=copy.deepcopy(m.children))
            key = _first(m)
            el = _new_inner(m, key, types, None)
            el.section, el.children, m.children = m.section, m.children, {key: el}   # also a UDT's or Temp
        _elements(m, types)


def _tree(itf, types=None, base=None):
    """The member tree with the DB start values in it (a copy; the parsed interface stays as it is)."""
    root = copy.deepcopy(itf.root)
    _elements(root, types)
    for key, (value, comment) in itf.start.items():
        node = root
        for k in _start_keys(key):
            nxt = node.children.get(k)
            if nxt is None:
                nxt = _new_inner(node, k, types, base if node is root else None)
                node.children[k] = nxt
            node = nxt
        if value != '()':
            node.value = value
        if comment:
            node.comment = comment
    for m in root.children.values():
        _fill(m, types)
    return root


def _fill(node, types):
    """A UDT or FB instance that start values unfold gets the other members of its type too, in the type's order,
    as TIA lists them under it (unchanged, so folded); so does an element of an array of struct that only
    its own comment or start value names. Not the elements of an array."""
    if any(isinstance(m, Inner) and not k.endswith(']') for k, m in node.children.items()) or (
            isinstance(node, Inner) and node.name.endswith(']') and node.decl is not None and node.decl.children):
        owner = _owner(node, types, None)
        if owner is not None:
            kids = {k: node.children.get(k) or _new_inner(node, k, types, None) for k in owner.root.children}
            node.children = dict(kids, **{k: m for k, m in node.children.items() if k not in kids})
    for m in node.children.values():
        _fill(m, types)


def _has(parent, other, key, types, base):
    """Has parent (one side) the member key that only a start value of the other side (below other) names? From
    parent's type when the input holds it, else when both are of the same type."""
    if key.endswith(']'):
        return bool(re.match(r'Array\s*\[', parent.type or '', re.I)) and tia_type(parent.type) == tia_type(other.type)
    owner = _owner(parent, types, base)
    if owner is not None:
        return key in owner.root.children
    return tia_type(parent.type) == tia_type(other.type)


def _complete(tb, ta, types, bases):
    """A member inside a UDT, FB instance or array that a start value names on one side only (its start value or
    comment set or cleared) gets its row on the other side too, from the type, when that side has it: 'changed',
    not 'added' / 'removed'. A member added to the UDT, or an instance added, stays as it is."""
    def walk(x, y, top):
        for src, dst, side in ((x, y, 1), (y, x, 0)):
            prev = None
            for k, m in list(src.children.items()):
                if k not in dst.children and isinstance(m, Inner) and _has(dst, src, k, types[side],
                                                                            bases[side] if top else None):
                    new = _new_inner(dst, k, types[side], bases[side] if top else None, m)
                    items = list(dst.children.items())
                    at = [n for n, _ in items].index(prev) + 1 if prev in dst.children else 0
                    dst.children = dict(items[:at] + [(k, new)] + items[at:])
                if k in dst.children:
                    prev = k
        for k, m in x.children.items():
            if k in y.children:
                walk(m, y.children[k], False)
    walk(tb, ta, True)


def _flat(root, path=()):
    out = []
    for name, m in root.children.items():
        out.append((path + (name,), m))
        out += _flat(m, path + (name,))
    return out


def _value(m, f):
    if f == 'type':
        return tia_type(m.type)
    return getattr(m, f)


def _key(m):
    """A member's type for pairing by place: a struct or an array of struct with its members' types, so a struct
    filled with other members does not line up."""
    t = tia_type(m.type)
    if t.strip().upper() == 'STRUCT' or re.search(r'\bof\s+Struct\s*$', t, re.I):
        return '%s(%s)' % (t, ','.join(_key(c) for c in m.children.values()))
    return t


def _own(path):
    """The last key of a path without its array's name for an array element ('arr', 'arr[1]' -> '[1]')."""
    k = path[-1]
    return k[len(path[-2]):] if len(path) > 1 and k.startswith(path[-2] + '[') else k


def _child(q, p):
    """The after path of before member p under q, the after path of its parent: an element of a renamed array
    keeps its index ('arr[1]' under 'list' -> 'list[1]')."""
    k = _own(p)
    return q + ((q[-1] + k) if k.startswith('[') else k,)


def _unique(rs, as_, same):
    """(r, a) for each r of rs with exactly one a of as_ for which same(r, a), that a having no other r."""
    cand = {r: [a for a in as_ if same(r, a)] for r in rs}
    return [(r, qs[0]) for r, qs in cand.items() if len(qs) == 1 and sum(qs[0] in c for c in cand.values()) == 1]


def _gaps(bs, as_, to_a):
    """The removed and the added members (lists of paths) between each two neighbours that keep their order."""
    x = [to_a[p] for p in bs if to_a.get(p) in set(as_)]
    keep = _common(x, [q for q in as_ if q in set(x)])
    taken = set(to_a.values())
    out, rem, add, j = [], [], [], 0
    for p in bs + [None]:
        if p is not None and p not in to_a:
            rem.append(p)
            continue
        if p is not None and to_a[p] not in keep:
            continue                                      # a moved member bounds no gap
        stop = to_a[p] if p is not None else None
        while j < len(as_) and as_[j] != stop:
            if as_[j] not in taken:
                add.append(as_[j])
            j += 1
        j += 1
        out.append((rem, add))
        rem, add = [], []
    return out


def _pairs(fb, fa):
    """before path -> after path of every member in both versions, level by level: the same name under the
    (possibly renamed) parent; else, among the same parent and section, a rename: the same data type and the same
    comment (not empty), each the other's only candidate; then, in each gap between the same two neighbours, the
    same comment whatever the type, each the other's only candidate; then by place: a gap with as many removed as
    added members pairs them in order where their types (_key) are the same (a gap with more on one side pairs
    none). An element of a renamed array keeps its index. Last, a member left on each side with the same name, each
    the other's only one, moved into or out of a struct (moved when not renamed), and then its members."""
    db, da = dict(fb), dict(fa)
    to_a = {(): ()}
    while True:
        _levels(fb, fa, db, da, to_a)
        taken = set(to_a.values())
        moved = _unique([p for p, _ in fb if p not in to_a and p[:-1] in to_a],
                        [q for q, _ in fa if q not in taken and q[:-1] in taken], lambda p, q: p[-1] == q[-1])
        if not moved:
            break
        to_a.update(moved)
    del to_a[()]
    return to_a


def _levels(fb, fa, db, da, to_a):
    """The pairs of _pairs within a parent, level by level, added to to_a."""
    for depth in range(1, max((len(p) for p, _ in fb), default=0) + 1):
        gone = []
        for p, _ in fb:
            if len(p) == depth and p[:-1] in to_a and p not in to_a:
                q = _child(to_a[p[:-1]], p)
                if q in da:
                    to_a[p] = q
                else:
                    gone.append(p)
        taken = set(to_a.values())
        new = [q for q, _ in fa if len(q) == depth and q not in taken]
        for p, q in _unique(gone, new, lambda p, q: to_a[p[:-1]] == q[:-1] and db[p].section == da[q].section
                            and tia_type(db[p].type) == tia_type(da[q].type) and db[p].comment
                            and db[p].comment == da[q].comment):
            to_a[p] = q
        groups = {}
        for p, m in fb:
            if len(p) == depth and p[:-1] in to_a:
                groups.setdefault((to_a[p[:-1]], m.section), ([], []))[0].append(p)
        for q, m in fa:
            if len(q) == depth and (q[:-1], m.section) in groups:
                groups[(q[:-1], m.section)][1].append(q)
        for bs, as_ in groups.values():
            for rem, add in _gaps(bs, as_, to_a):
                for p, q in _unique(rem, add, lambda p, q: db[p].comment and db[p].comment == da[q].comment):
                    to_a[p] = q
                    rem.remove(p)
                    add.remove(q)
                if len(rem) == len(add):
                    to_a.update((p, q) for p, q in zip(rem, add) if _key(db[p]) == _key(da[q]))


def _common(x, y):
    """The items of a longest common subsequence of x and y."""
    n, m = len(x), len(y)
    ln = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            ln[i][j] = ln[i + 1][j + 1] + 1 if x[i] == y[j] else max(ln[i + 1][j], ln[i][j + 1])
    out, i, j = set(), 0, 0
    while i < n and j < m:
        if x[i] == y[j]:
            out.add(x[i])
            i, j = i + 1, j + 1
        elif ln[i + 1][j] >= ln[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def _place(sibs, k):
    return 'first' if k == 0 else 'last' if k == len(sibs) - 1 else 'after %s' % sibs[k - 1][-1]


def _moves(fb, fa, to_a):
    """after path -> (was, now) for the members that left the common order of their siblings (same parent and
    section)."""
    gb, ga = {}, {}
    for p, m in fb:
        if p[:-1] in to_a or len(p) == 1:
            gb.setdefault((to_a.get(p[:-1], ()), m.section), []).append(p)
    for q, m in fa:
        ga.setdefault((q[:-1], m.section), []).append(q)
    out = {}
    for key, bs in gb.items():
        as_ = ga.get(key, [])
        both = set(as_)
        x = [to_a[p] for p in bs if to_a.get(p) in both]
        y = [q for q in as_ if q in set(x)]
        keep = _common(x, y)
        for p in bs:
            q = to_a.get(p)
            if q in both and q not in keep:
                out[q] = (_place(bs, bs.index(p)), _place(as_, as_.index(q)))
    return out


def rows(bitf, aitf, types=(None, None), bases=(None, None)):
    """types: (before, after) name -> Interface of a UDT (compare.Callees); bases: the interface of a DB's own
    type (a DB of a UDT, an instance DB); both for the members that only DB start values name."""
    tb = _tree(bitf, types[0], bases[0]) if bitf else None
    ta = _tree(aitf, types[1], bases[1]) if aitf else None
    if tb is not None and ta is not None:
        _complete(tb, ta, types, bases)
    fb = _flat(tb) if tb is not None else []
    fa = _flat(ta) if ta is not None else []
    db, da = dict(fb), dict(fa)
    to_a = _pairs(fb, fa)
    to_b = {q: p for p, q in to_a.items()}
    moves = _moves(fb, fa, to_a)
    order = [('a', q) for q, _ in fa]
    pos = {e: k for k, e in enumerate(order)}
    prev = None
    for p, _ in fb:                                   # removed members after their former predecessor
        if p not in to_a:
            at = pos[prev] + 1 if prev in pos else 0
            while at < len(order) and prev is not None and order[at][1][:len(prev[1])] == prev[1]:
                at += 1                               # behind the predecessor's own members
            order.insert(at, ('b', p))
            pos = {e: k for k, e in enumerate(order)}
        prev = ('a', to_a[p]) if p in to_a else ('b', p)
    out = []
    for side, p in order:
        if side == 'b':
            out.append(Row(p, db[p], None, bpath=p))
            continue
        pb = to_b.get(p)
        b, a = db.get(pb), da[p]
        ch = set()
        if b is not None:
            fields = ('value', 'comment') if isinstance(a, Inner) and isinstance(b, Inner) else FIELDS
            ch = {f for f in fields if _value(b, f) != _value(a, f)}
            if len(p) > 1:                               # retain is the top-level member's, its row shows it
                ch.discard('retain')
            if _own(pb) != _own(p):
                ch.add('name')
            if to_a.get(pb[:-1], ()) != p[:-1]:
                ch.add('parent')
            if p in moves:
                ch.add('order')
        out.append(Row(p, b, a, ch, pb, moves.get(p)))
    return out


def _base(blk):
    """A DB of a UDT or an instance DB: the interface of its type."""
    cal = getattr(blk, 'callees', None)
    if blk is None or blk.kind != 'DATA_BLOCK' or not decl_type(blk.decl) or not cal:
        return None
    return cal(decl_type(blk.decl))


def _returns(blk):
    """A function's interface with its return value as TIA's Return section shows it: one member named as the
    block, of the return type (none for Void; before, a changed return type was no change)."""
    itf = blk.interface
    typ = decl_type(blk.decl) if blk.kind == 'FUNCTION' else ''
    if not typ or typ.lower() == 'void':
        return itf
    name = decl_name(blk.decl)
    out = Interface()
    out.start = itf.start
    out.root = Member('', children=dict(itf.root.children, **{name: Member(name, typ, section='RETURN')}))
    return out


def block_rows(bblock, ablock):
    bs = (bblock, ablock)
    return rows(*(_returns(b) if b else None for b in bs), types=tuple(getattr(b, 'callees', None) for b in bs),
                bases=tuple(_base(b) for b in bs))


def props_rows(bprops, aprops):
    out = []
    names = dict(PROPS)
    keys = [k for k, _ in PROPS] + sorted((set(bprops) | set(aprops)) - set(names))
    for k in keys:
        b, a = bprops.get(k), aprops.get(k)
        if b != a and (b is not None or a is not None):
            out.append((names.get(k, k), b, a))
    return out


def changed(bblock, ablock):
    """Any change of the declaration (start values included)? The block properties are apart."""
    return any(r.state != 'same' for r in block_rows(bblock, ablock))


def props_changed(bblock, ablock):
    """Any block property changed (the version TIA raises on every edit), both versions there."""
    return bool(bblock and ablock and props_rows(bblock.props, ablock.props))


# ---------------------------------------------------------------- html

LABELS = dict(SECTIONS)
ATTR_HEADS = ('Accessible from HMI/OPC UA', 'Writable from HMI/OPC UA', 'Visible in HMI engineering', 'Setpoint')
KNOWN_ATTRS = ('S7_Access', 'S7_Visibility', 'S7_Setpoint', 'S7_SetPoint')


def take_setpoints(released, other):
    """A released library type's .s7dcl writes no Setpoint, where its version in work and the project block write
    one: its no setting says nothing of the box, so a release must draw no box changed, and whether one did the two
    exports cannot tell. Its members take the other version's setting; True when one did, for the block to
    say that its file differs in what the report does not show."""
    took = False

    def walk(r, o):
        nonlocal took
        for key, m in r.children.items():
            x = o.children.get(key)
            if x is not None:
                if _setpoint(x) is not None and _setpoint(m) is None:
                    m.attrs['S7_Setpoint'] = _setpoint(x)
                    took = True
                walk(m, x)
    walk(released.interface.root, other.interface.root)
    return took


def _attrs(d):
    return '; '.join('%s: %s' % (k.replace('S7_', ''), v) for k, v in sorted(d.items())) or '–'


def _box(on, disabled=False):
    return '<span class="cb%s%s"></span>' % (' on' if on else '', ' dis' if disabled else '')


BOX_CELLS = ('acc', 'wr', 'vis', 'sp')


def _setpoint(m):
    return m.attrs.get('S7_Setpoint', m.attrs.get('S7_SetPoint'))


def _no_sp(t):
    """A struct has no Setpoint (an array has one, as seen on an array of a UDT in a global DB)."""
    return (t or '').strip().upper() == 'STRUCT'


def _off(m, kind='', safety=False):
    """The cells of a member's row that TIA disables (draws gray): 'name', 'type', 'value', 'retain' and
    BOX_CELLS. Seen in a standard FB, an F-FB, a global DB, an F-DB and an instance DB (TIA screenshots):
    the default / start value of a UDT, struct, array or FB instance; in-outs of such a type: retain,
    value and every box; writable, visible and setpoint when the member is not accessible; the setpoint of a struct;
    retain in an F-DB and an F-FB; a member inside a UDT instance or array, or of an instance DB (Inner): all but its
    start value (gray too when structured) and comment. Temp, constants and Return: none (not seen)."""
    if isinstance(m, Inner):
        return {'name', 'type', 'retain'} | set(BOX_CELLS) | ({'value'} if structured(m.type) else set())
    if m.section in NO_BOXES:
        return set()
    off = set()
    if structured(m.type):
        off.add('value')
        if m.section == 'IN_OUT':
            off |= {'retain'} | set(BOX_CELLS)
    if not _eff(m)[0]:
        off |= {'wr', 'vis', 'sp'}
    if _no_sp(m.type):
        off.add('sp')
    if safety:
        off.add('retain')
    return off


def _boxes(m, safety=False):
    """TIA's checkboxes (accessible, writable, visible, setpoint) of a member, disabled where TIA disables them
    (_off: a disabled box, not a blank), all empty for an in-out of a structured type; '' for temp,
    constants and Return. Setpoint without a setting: setpoint_default, never for a struct. A member inside a UDT
    instance or array that a DB start value names (Inner): ticked from the UDT's settings (an array element: the
    array's) as far as its parent allows."""
    if m.section in NO_BOXES and not isinstance(m, Inner):
        return ('',) * 4
    t = (m.type or '').strip()
    if m.section == 'IN_OUT' and structured(t) and not isinstance(m, Inner):
        return (_box(False, True),) * 4                  # empty in TIA, whatever the export sets
    sp = _setpoint(m)
    sp = not _no_sp(t) and (setpoint_default(t, m.section, safety) if sp is None else sp.lower() == 'true')
    off = _off(m)
    return tuple(_box(on, c in off) for on, c in zip(_eff(m) + (sp,), BOX_CELLS))


def _retain(m, depth, kind, safety=False):
    """FB: 'Retain' / 'Non-retain' / 'Set in IDB' on the top-level members (not temp, constants, structured in-outs;
    in an F-FB not a structured static either: an FB instance there shows none); DB: a box, disabled in an F-DB and on a
    member inside a UDT instance or array (Inner, with the retain of its top-level member)."""
    if isinstance(m, Inner):
        return _box(m.retain, True) if kind == 'DATA_BLOCK' else ''
    if depth != 1:
        return ''
    if m.retain == SET_IN_IDB:
        return SET_IN_IDB
    if kind == 'DATA_BLOCK':
        return _box(m.retain, 'retain' in _off(m, kind, safety))
    if safety and m.section == 'STAT' and structured(m.type):
        return ''
    if m.section in ('INPUT', 'OUTPUT', 'STAT') or (m.section == 'IN_OUT' and not structured(m.type)):
        return 'Retain' if m.retain else 'Non-retain'
    return ''


def _value_html(m):
    if m.value:
        return escape(m.value)
    z = getattr(m, 'dflt', None) or (default_value(None, m.type) if m.section not in ('TEMP', 'RETURN') else None)
    return '<span class="dflt">%s</span>' % escape(z) if z else ''


def _comment_html(m):
    if m.comment:
        return escape(m.comment)
    inh = getattr(m, 'inherited', None)
    return '<span class="inh">%s</span>' % escape(inh) if inh else ''


def _both(b, a, sep=' '):
    """Content that differs (HTML), as a changed network title: the before content in a light red
    field, the after content in a light green one, the changed words of a plain text stronger; a side without
    content left out."""
    if '<' not in b + a:
        from .page import _inline
        b, a = _inline(unescape(b), unescape(a))
    return sep.join(x for x in ('<span class="tx del">%s</span>' % b if b else '',
                                '<span class="tx ins">%s</span>' % a if a else '') if x)


def _cell(r, show, changed=True):
    if r.state == 'changed' and changed:
        b, a = show(r.b), show(r.a)
        if b != a:
            return _both(b, a, '') if 'class="cb' in b + a else _both(b or '–', a or '–')
    return show(r.m)


def _columns(kind):
    """(title of the value column, Retain column?, attribute columns?) of TIA's editor for a block kind."""
    return ('Start value' if kind == 'DATA_BLOCK' else 'Default value', kind in ('FUNCTION_BLOCK', 'DATA_BLOCK'),
            kind in ('FUNCTION_BLOCK', 'DATA_BLOCK', 'TYPE'))


def _skip(n, ncols, depth):
    return ('<tr class="skip"><td colspan="%d" style="padding-left:%dpx">⋯ %d unchanged member%s<span class="hint"> '
            '(click to show all)</span></td></tr>' % (ncols, 8 + 16 * depth, n, '' if n == 1 else 's'))


def props_html(bblock, ablock):
    """The changed block properties, as TIA's property list (apart from the interface)."""
    return '<table class="itf"><tr class="sec"><td colspan="4">Block properties</td></tr>%s</table>' % ''.join(
        '<tr class="chg"><td class="nm">%s</td><td colspan="3">%s</td></tr>'
        % (escape(n), _both(escape(b or '–'), escape(a or '–'))) for n, b, a in props_rows(bblock.props, ablock.props))


def block_texts_html(blk, removed=False):
    """A new block's title and comment as added, a deleted one's (removed) as removed (TIA shows them above the first
    network); '' without either. Not its other properties: nothing changed in them that a reader looks for on such a
    block."""
    rows = [(n, blk.props[k]) for k, n in PROPS if k in ('S7_BlockTitle', 'S7_BlockComment') and blk.props.get(k)]
    cls, side = ('del', lambda t: _both(t, '')) if removed else ('ins', lambda t: _both('', t))
    return '<table class="itf"><tr class="sec"><td colspan="4">Block properties</td></tr>%s</table>' % ''.join(
        '<tr class="%s"><td class="nm">%s</td><td colspan="3">%s</td></tr>'
        % (cls, escape(n), side(escape(a))) for n, a in rows) if rows else ''


def declaration_html(before, after):
    """A block's kind and declaration, old and new (a DB of another type, an FC become an FB)."""
    return ('<table class="itf"><tr class="chg"><td class="nm">Declaration</td><td colspan="3">%s</td></tr></table>'
            % _both(escape(before), escape(after)))


def html(bblock, ablock):
    rs = block_rows(bblock, ablock)
    blk = ablock or bblock
    kind = blk.kind if blk else ''
    vhead, has_retain, has_attrs = _columns(kind)
    safety = kind != 'TYPE' and blk.props.get('S7_Safety', '').lower() == 'true'      # an F-DB or F-FB
    ncols = 4 + has_retain + 4 * has_attrs
    keep = set()
    for r in rs:
        if r.state != 'same':
            keep.update(r.path[:k] for k in range(1, len(r.path) + 1))    # the row and its parents
    parents = {r.path[:-1] for r in rs}
    parts = []
    if keep:
        body = ['<tr class="hd"><td>Name</td><td>Data type</td><td>%s</td>%s%s<td>Comment</td></tr>'
                % (vhead, '<td>Retain</td>' if has_retain else '',
                   ''.join('<td class="c">%s</td>' % h for h in ATTR_HEADS) if has_attrs else '')]
        top = 0 if kind == 'TYPE' else 1                            # a UDT has no section rows
        for sec, label in SECTIONS:
            srows = [r for r in rs if r.m.section == sec]          # a moved member shows in its new section
            if not any(r.path in keep for r in srows):
                continue
            if top:
                body.append(_sec_row('Static' if sec == 'UDT' else label, ncols, kind, has_retain, has_attrs))
            k = 0
            while k < len(srows):
                r = srows[k]
                if r.path not in keep:                                 # a run of unchanged rows, folded in place
                    j = k
                    while j < len(srows) and srows[j].path not in keep:
                        j += 1
                    body.append(_skip(j - k, ncols, top + len(r.path) - 1))
                    body += [_row(x, 'ctx', top, parents, kind, has_retain, has_attrs, safety) for x in srows[k:j]]
                    k = j
                    continue
                body.append(_row(r, '', top, parents, kind, has_retain, has_attrs, safety))
                k += 1
        parts.append('<table class="itf">%s</table>' % ''.join(body))
    return ''.join(parts)


def _sec_row(label, ncols, kind, has_retain, has_attrs):
    """A section as a tree row; with TIA's attribute columns, their boxes disabled and empty as TIA draws them (a DB
    also Retain)."""
    name = '<span class="tw">▼</span>%s' % label
    if not has_attrs:
        return '<tr class="sec"><td colspan="%d">%s</td></tr>' % (ncols, name)
    cells = [name, '', ''] + ([_box(False, True) if kind == 'DATA_BLOCK' else ''] if has_retain else [])
    cells += [_box(False, True)] * 4 + ['']
    return '<tr class="sec">%s</tr>' % ''.join('<td%s>%s</td>' % (' class="nm"' if i == 0 else
                                                                  ' class="c"' if 'class="cb' in c else '', c)
                                               for i, c in enumerate(cells))


def _td(html, off, cls=''):
    cls = ' '.join(x for x in (cls, 'dis' if off else '') if x)
    return '<td%s>%s</td>' % (' class="%s"' % cls if cls else '', html)


def _row(r, ctx, top, parents, kind, has_retain, has_attrs, safety=False):
    cls = ' '.join(x for x in ({'added': 'ins', 'removed': 'del', 'changed': 'chg', 'moved': 'mov',
                                'same': ''}[r.state], ctx) if x)
    depth = len(r.path)
    name = escape(r.path[-1])
    if 'name' in r.changes:
        name = _both(escape(r.bpath[-1]), name)
    tw = '▼' if r.path in parents else ('▶' if structured(r.m.type) else '')
    extra = []
    if 'order' in r.changes:
        extra.append('order: was %s, now %s' % tuple(escape(x) for x in r.order))
    if 'section' in r.changes:
        extra.append('moved: %s → %s' % (LABELS[r.b.section], LABELS[r.a.section]))
    if 'parent' in r.changes:
        extra.append('moved: %s → %s' % (escape('.'.join(r.bpath)), escape('.'.join(r.path))))
    if 'attrs' in r.changes:
        other = [{k: v for k, v in m.attrs.items() if k not in KNOWN_ATTRS or not has_attrs} for m in (r.b, r.a)]
        if other[0] != other[1]:
            extra.append('attributes: ' + _both(escape(_attrs(other[0])), escape(_attrs(other[1]))))
    if 'retain' in r.changes and not has_retain:
        extra.append('retain: %s → %s' % (r.b.retain, r.a.retain))
    off = _off(r.m, kind, safety)                       # gray cells, as the row is now
    cells = ['<td class="nm%s" style="padding-left:%dpx"><span class="tw">%s</span>%s%s</td>'
             % (' dis' if 'name' in off else '', 8 + 16 * (top + depth - 1), tw, name,
                ''.join('<div class="ex">%s</div>' % x for x in extra)),
             _td(_cell(r, lambda m: escape(tia_type(m.type), False), 'type' in r.changes), 'type' in off),
             _td(_cell(r, _value_html, 'value' in r.changes), 'value' in off)]
    if has_retain:
        cells.append(_td(_cell(r, lambda m: _retain(m, depth, kind, safety), bool({'retain', 'section'} & r.changes)),
                         'retain' in off))
    if has_attrs:
        cells += [_td(_cell(r, lambda m, i=i: _boxes(m, safety)[i], bool({'attrs', 'section', 'type'} & r.changes)),
                      BOX_CELLS[i] in off, 'c') for i in range(4)]
    cells.append('<td>%s</td>' % _cell(r, _comment_html, 'comment' in r.changes))
    return '<tr%s>%s</tr>' % (' class="%s"' % cls if cls else '', ''.join(cells))
