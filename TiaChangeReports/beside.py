"""What a network's part of the file holds and the report does not read, told also beside a change the report shows:
the network's tag, which names nothing.

The part is cut into units. SimaticML: each part, operand, call, wire, label and token, each title and comment, and each
other field around them (_xml_units). An .s7dcl LAD network: each statement with the pragma blocks in front of it, an
instruction with the lines of its parameters, and the network's end with the pragma blocks after its last statement
(_sd_units): a pragma belongs to what follows it. Its settings, which the report does not read at all, are compared as
they stand (in Network.source). The units of the two versions are paired: those alike by what they hold, the rest in
order by their kind. The kind of an instruction holds the pins wired to it or written in it, of a wire its ends but an
open one: an instruction whose pins changed pairs with nothing, and its pin count or pragma comes with the pins the
drawing shows.

A pair that differs is tried alone: the version before with that one unit of the version after, read again, the unit
keeping the object numbers it had; a SimaticML wire with its ends on the parts of the version before that hold the same
(_wire_reaching); an .s7dcl statement also with only its pragmas of the version after. Read the same as before, the unit
differs in what the report does not read. The fields of a SimaticML wire and its ends, which the report reads none of,
are compared apart, each wire by what it connects wherever the file writes it (_wire_fields_differ). A unit one version
has is left to what the report shows, as a part or instruction comes with its fields and pragmas; one around the
network's source (a title or comment TIA writes empty, a field of the network) is tried too, taken out or put in. A pair
that reads otherwise is no tag, also where the same unit holds a field the report does not read (an SCL operand's Scope
beside its name). Two units that differ only together (a wire and the pin it reaches) are not tried together: one of
them alone reads otherwise, so they are no tag."""
import copy
import difflib
import re
from collections import Counter, namedtuple

from . import s7dcl, simaticml
from .simaticml import _NUMBERS, _blank, _held, _local, _plain, _unnumbered

# key: what it holds; code: an .s7dcl statement's lines, without its pragmas; shape: its kind; alone: tried also where
# one version has it
Unit = namedtuple('Unit', 'key shape where alone code', defaults=(False, None))

# SimaticML elements of a network that hold units, on the way down from its CompileUnit
_HOLDERS = {'SW.Blocks.CompileUnit', 'AttributeList', 'ObjectList', 'NetworkSource', 'FlgNet', 'Parts', 'Wires', 'Labels',
            'StructuredText', 'StatementList'}
_OWN = -1                                 # where[-1] of a holder's own attributes and text


def unread_beside(b, a, reads_same):
    """Two versions of a network in one format and language: a unit differs that, put alone into the version before,
    reads the same. reads_same(before, other): what the report reads of the two networks is alike."""
    if not (b.raw and a.raw and b.raw[0] == a.raw[0] and b.lang == a.lang):
        return False
    if b.raw[0] == 'sd':
        if b.source[1] != a.source[1]:
            return True                   # a setting of the network: none is read
        if b.lang != 'LAD':
            return False                  # its lines are shown as they stand
        units, again = _sd_units, _sd_again
    else:
        if _wire_fields_differ(b.raw[1], a.raw[1], b.raw[2]):
            return True                   # a field of a wire: none is read
        units, again = _xml_units, _xml_again
    bu, au = units(b.raw), units(a.raw)
    for x, y in _pairs(bu, au):
        try:
            tries = again(b, a, x, y)
        except IndexError:                # the version before has nowhere to put it: no try
            continue
        if any(reads_same(b, other) for other in tries):
            return True
    return False


def align(xs, ys, *levels):
    """[(i, j)]: xs[i] and ys[j] paired in order, by the first level (a function of an item) where they are alike, then
    in each stretch between those by the next."""
    if not levels or not xs or not ys:
        return []
    out, i0, j0 = [], 0, 0
    for i, j, n in difflib.SequenceMatcher(None, [levels[0](x) for x in xs], [levels[0](y) for y in ys],
                                           autojunk=False).get_matching_blocks():
        out += [(i0 + a, j0 + b) for a, b in align(xs[i0:i], ys[j0:j], *levels[1:])]
        out += [(i + k, j + k) for k in range(n)]
        i0, j0 = i + n, j + n
    return out


def _pairs(bu, au):
    """(before, after) for the units that differ: paired by what they hold, then by their code, then by their kind. A
    unit left without a partner that may be tried alone: (it, None) or (None, it)."""
    pairs = align(bu, au, lambda u: u.key, lambda u: u.key if u.code is None else u.code, lambda u: u.shape)
    yield from ((bu[i], au[j]) for i, j in pairs if bu[i].key != au[j].key)
    paired_b, paired_a = {i for i, _ in pairs}, {j for _, j in pairs}
    yield from ((x, None) for i, x in enumerate(bu) if i not in paired_b and x.alone)
    yield from ((None, y) for j, y in enumerate(au) if j not in paired_a and y.alone)


# ---------------------------------------------------------------- SimaticML

def _xml_units(raw):
    _, cu, lang = raw
    pins = {}
    for con in cu.iter():
        if _local(con.tag) == 'NameCon':
            pins.setdefault(con.get('UId'), set()).add(con.get('Name'))
    out = []

    def walk(el, where, up):
        out.append(Unit((_local(el.tag), _unnumbered(el), (el.text or '').strip()), (up, _OWN), where + (_OWN,)))
        for k, c in enumerate(el):
            tag = _local(c.tag)
            if tag in _HOLDERS:
                walk(c, where + (k,), up + (tag,))
            elif tag != 'DocumentInfo' and not (lang and simaticml._other_language(c, lang)):
                shape = (up, tag, c.get('Name'), _ends(c, pins))
                out.append(Unit(_blank(_plain(c, lang=lang)), shape, where + (k,), 'NetworkSource' not in up))
    walk(cu, (), ())
    return out


def _ends(el, pins):
    """What an element connects: the pins wired to a part or call, the ends of a wire (an open end is none)."""
    tag = _local(el.tag)
    if tag in ('Part', 'Call'):
        return tuple(sorted(pins.get(el.get('UId'), ())))
    if tag == 'Wire':
        return tuple(sorted((_local(c.tag), c.get('Name') or '') for c in el if _local(c.tag) != 'OpenCon'))
    return ()


def _at(el, where):
    for k in where:
        el = el[k]
    return el


def _xml_again(b, a, x, y):
    """[Network b read again with its unit x as unit y of network a, keeping x's object numbers]; a wire as
    _wire_reaching puts it, [] for none."""
    _, cu, lang = b.raw
    other = a.raw[1]
    h = copy.deepcopy(cu)
    if x is None or y is None:                   # one version has it: added to or taken from the version before
        if y is None:
            _at(h, x.where[:-1]).remove(_at(h, x.where))
        else:
            holder = _at(h, y.where[:-1])
            holder.insert(min(y.where[-1], len(holder)), copy.deepcopy(_at(other, y.where)))
    elif x.where[-1] == _OWN:
        el, src = _at(h, x.where[:-1]), _at(other, y.where[:-1])
        _take_fields(el, src)
        el.text = src.text
    elif _local(_at(other, y.where).tag) == 'Wire':
        w = _wire_reaching(_at(cu, x.where), _at(other, y.where), cu, other, lang)
        if w is None:
            return []
        _at(h, x.where[:-1])[x.where[-1]] = w
    else:
        parent = _at(h, x.where[:-1])
        old, new = parent[x.where[-1]], copy.deepcopy(_at(other, y.where))
        for name in _NUMBERS:
            olds, news = ([e for e in t.iter() if name in e.attrib] for t in (old, new))
            if len(olds) == len(news):
                for o, n in zip(olds, news):
                    n.set(name, o.get(name))
        parent[x.where[-1]] = new
    return [simaticml.network(h, b.index, next(s7dcl._blocks), lang)]


def _wire_reaching(old, new, cu, other, lang):
    """The wire new of network other put in the place of the wire old of network cu, its ends on the parts of cu that
    hold what they reach in other (_numbered_before); an end on a part or operand that changed, the end old had at its
    place. None where an end reaches nothing there, or the wire is old up to the order of its ends after the first
    (simaticml.wire_end). Its fields come with it; those alone _wire_fields_differ tells."""
    reach = copy.deepcopy(new)
    number = _numbered_before(cu, other, lang)
    for k, end in enumerate(reach):
        if _local(end.tag) not in ('NameCon', 'IdentCon'):
            continue
        if end.get('UId') in number:
            end.set('UId', number[end.get('UId')])
        elif k < len(old) and _local(old[k].tag) == _local(end.tag):
            end.set('UId', old[k].get('UId'))       # on what changed: the end the wire had there
        else:
            return None                              # an end that reaches nothing there
    reach.set('UId', old.get('UId'))
    return reach if _wire(reach) != _wire(old) else None


def _wire_fields(cu, lang):
    """Counter of a network's wires as (what each connects, its fields): an end by its kind, its pin and what it reaches,
    a part with the operands on its pins or an operand by what it holds, the ends after the first in any order
    (simaticml.wire_ends); the fields of the wire and of each end that holds one, but their numbers and pins."""
    parts, _, operand, wires = _read_net(cu, lang)
    what = dict(operand, **{x[0]: x[1] for x in parts})
    out = Counter()
    for w in wires:
        ends = [(_local(e.tag), e.get('Name') or '', repr(what.get(e.get('UId'))) if _local(e.tag) in ('NameCon', 'IdentCon')
                 else '') for e in w]
        held = sorted((end, f) for end, e in zip(ends, w) for f in [tuple(x for x in _unnumbered(e) if x[0] != 'Name')] if f)
        out[simaticml.wire_ends(ends), _unnumbered(w), tuple(held)] += 1
    return out


def _wire_fields_differ(cu, other, lang):
    """A field of a wire or of a wire's end differs between two networks, each wire by what it connects, wherever the
    file writes it (_wire_fields): two wires that connect the same, by their fields; the wires a change of the logic
    leaves without such a partner, by their fields alone, the ends by their kind and pin."""
    mine, theirs = _wire_fields(cu, lang), _wire_fields(other, lang)
    left, left_o = mine - theirs, theirs - mine
    if {k[0] for k in left} & {k[0] for k in left_o}:
        return True                                  # the same connections, other fields

    def alone(c):
        return Counter((own, tuple(sorted((end[:2], f) for end, f in held))) for (_, own, held), n in c.items()
                       for _ in range(n) if own or held)
    return alone(left) != alone(left_o)


def _take_fields(el, src):
    """el with the fields of src, keeping its own numbers."""
    numbers = {k: v for k, v in el.attrib.items() if k in _NUMBERS}
    el.attrib.clear()
    el.attrib.update({k: v for k, v in src.attrib.items() if k not in _NUMBERS}, **numbers)


def _wire(w):
    """A wire as compared: its own fields and its ends, each by the number of what it reaches (simaticml.wire_end)."""
    return _unnumbered(w), simaticml.wire_ends([simaticml.wire_end(c, lambda uid: uid) for c in w])


def _read_net(cu, lang):
    """A network's FlgNet read by what its objects hold: ([(number, what it holds with the operands on its pins, what it
    holds, kind)] of its parts and calls in their order, {operand: the pins it is on}, {operand: what it holds}, its
    wires)."""
    flg = next((e for e in cu.iter() if _local(e.tag) == 'FlgNet'), None)
    held, wires = _held(flg, 'Parts'), _held(flg, 'Wires')
    operand = {p.get('UId'): _blank(_plain(p, lang=lang)) for p in held if _local(p.tag) == 'Access'}
    pins, on = {}, {}                                    # operand -> the pins it is on; part -> [(pin, operand)]
    for w in wires:
        reached = tuple((e.get('UId'), e.get('Name')) for e in w if _local(e.tag) == 'NameCon')
        for e in w:
            if _local(e.tag) == 'IdentCon':
                pins[e.get('UId')] = reached
                for uid, pin in reached:
                    on.setdefault(uid, []).append((pin, operand.get(e.get('UId'))))
    parts = []
    for p in held:
        if _local(p.tag) != 'Access':
            what = _blank(_plain(p, lang=lang))
            parts.append((p.get('UId'), (what, tuple(sorted(on.get(p.get('UId'), ()), key=repr))), what,
                          (_local(p.tag), p.get('Name'))))
    return parts, pins, operand, wires


def _numbered_before(cu, other, lang):
    """{the number of an object of network other: the number of the object of network cu that holds the same}. A part
    or call by what it holds with the operands on its pins: one that each network holds once pairs wherever it stands
    (a user's change can move it); the rest in their order, by that, then by what they hold, then by their kind. An
    operand by the pins it is on, of those parts."""
    (mine, pins, _, _), (theirs, pins_o, _, _) = _read_net(cu, lang), _read_net(other, lang)
    once, once_o = (Counter(x[1] for x in xs) for xs in (mine, theirs))
    single = {x[1]: x[0] for x in mine if once[x[1]] == 1}
    out = {x[0]: single[x[1]] for x in theirs if once_o[x[1]] == 1 and x[1] in single}
    rest, rest_o = [x for x in mine if x[0] not in out.values()], [x for x in theirs if x[0] not in out]
    for i, j in align(rest_o, rest, lambda x: x[1], lambda x: x[2], lambda x: x[3]):
        out[rest_o[i][0]] = rest[j][0]
    operand_at = {ends: uid for uid, ends in pins.items()}
    for uid, ends in pins_o.items():
        here = tuple((out.get(u), n) for u, n in ends)
        if here in operand_at:
            out[uid] = operand_at[here]
    return out


# ---------------------------------------------------------------- .s7dcl

_PIN = re.compile(r'("[^"]+"|\w+)\s*(?::=|=>)')


def _sd_units(raw):
    """A LAD network's statements, each with the pragma blocks in front of it, and its end with those after the last;
    where: (first line of its pragmas, first line of its statement, line after it) in the network's body."""
    _, _, body, res, _, _ = raw
    lines = body.splitlines()
    out, first, settings, i = [], None, {}, 0
    while i <= len(lines):
        if i == len(lines):                              # the end: what the pragmas left stand before
            start = end = i
            shape = ('end',)
            code = ''
        else:
            t = lines[i].strip()
            if not t:
                i += 1
                continue
            if t.startswith('{'):
                first = i if first is None else first
                block = t
                i += 1
                while '}' not in block and i < len(lines):
                    block += '\n' + lines[i]
                    i += 1
                settings.update(s7dcl._pragmas(block[:block.index('}') + 1] if '}' in block else block))
                continue
            start, end = i, i + 1
            if '(' in t and not t.rstrip(';').endswith(')'):  # an instruction over several lines, up to its bracket
                while end < len(lines) and lines[end].strip() not in (')', ');'):
                    end += 1
                end = min(end + 1, len(lines))
            text = ' '.join(x.strip() for x in lines[start:end])
            shape = (_instruction(t), tuple(_PIN.findall(text)))    # other pins: no partner, its pragmas come with them
            code = ' '.join(s7dcl.lad_lines('\n'.join(lines[start:end])))
        key = (tuple(sorted((n, res.get(v, v)) for n, v in settings.items())), re.sub(r'wire#\w+', 'wire#', code, flags=re.I))
        out.append(Unit(key, shape, (start if first is None else first, start, end), code=key[1]))
        first, settings = None, {}
        i = end + 1 if i == len(lines) else end
    return out


def _instruction(line):
    """What a line of a LAD network starts with, without an instance, which is an operand: an instruction's name
    ('#inst.TON' TON, '#inst' or '"DB"' a call), RUNG, a wire."""
    head = re.match(r'[^(\s]*', line).group(0)
    if head.startswith(('#', '"')):
        return head.rsplit('.', 1)[-1] if re.search(r'\.\w+$', head) else 'call'
    return head


def _sd_again(b, a, x, y):
    """Network b read again with its statement x as statement y of network a; and with only its pragmas of y; as its
    block reads it, an F-block's as one."""
    _, pragma, body, res, itf, safety = b.raw
    lines, other = body.splitlines(), a.raw[2].splitlines()
    whole = lines[:x.where[0]] + other[y.where[0]:y.where[2]] + lines[x.where[2]:]
    out = [whole]
    if x.key[0] != y.key[0]:
        out.append(lines[:x.where[0]] + other[y.where[0]:y.where[1]] + lines[x.where[1]:])
    return [s7dcl.network(b.index, pragma, '\n'.join(t), res, itf, next(s7dcl._blocks), safety) for t in out]
