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
keeping the object numbers it had; an .s7dcl statement also with only its pragmas of the version after. Read the same as
before, the unit differs in what the report does not read. A unit one version has is left to what the report shows, as
a part or instruction comes with its fields and pragmas; one around the network's source (a title or comment TIA writes
empty, a field of the network) is tried too, taken out or put in. A pair that reads otherwise is no tag, also where the
same unit holds a field the report does not read (an SCL operand's Scope beside its name). Two units that differ only
together (a wire and the pin it reaches) are not tried together: one of them alone reads otherwise, so they are no
tag."""
import copy
import difflib
import re
from collections import namedtuple

from . import s7dcl, simaticml
from .simaticml import _local, _plain

# key: what it holds; code: an .s7dcl statement's lines, without its pragmas; shape: its kind; alone: tried also where
# one version has it
Unit = namedtuple('Unit', 'key shape where alone code', defaults=(False, None))

# SimaticML elements of a network that hold units, on the way down from its CompileUnit
_HOLDERS = {'SW.Blocks.CompileUnit', 'AttributeList', 'ObjectList', 'NetworkSource', 'FlgNet', 'Parts', 'Wires', 'Labels',
            'StructuredText', 'StatementList'}
_OWN = -1                                 # where[-1] of a holder's own attributes and text
_NUMBERS = ('UId', 'ID')                  # which object is which: the drawing tells what a wire connects


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
        out.append(Unit((_local(el.tag), _attrs(el), (el.text or '').strip()), (up, _OWN), where + (_OWN,)))
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


def _attrs(el):
    return tuple(sorted((k, v) for k, v in el.attrib.items() if k not in _NUMBERS))


def _blank(plain):
    """_plain without the object numbers."""
    tag, attrs, text, kids = plain
    return tag, tuple((k, v) for k, v in attrs if k not in _NUMBERS), text, tuple(_blank(k) for k in kids)


def _at(el, where):
    for k in where:
        el = el[k]
    return el


def _xml_again(b, a, x, y):
    """[Network b read again with its unit x as unit y of network a, keeping x's object numbers]."""
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
        numbers = {k: v for k, v in el.attrib.items() if k in _NUMBERS}
        el.attrib.clear()
        el.attrib.update({k: v for k, v in src.attrib.items() if k not in _NUMBERS}, **numbers)
        el.text = src.text
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


# ---------------------------------------------------------------- .s7dcl

_PIN = re.compile(r'("[^"]+"|\w+)\s*(?::=|=>)')


def _sd_units(raw):
    """A LAD network's statements, each with the pragma blocks in front of it, and its end with those after the last;
    where: (first line of its pragmas, first line of its statement, line after it) in the network's body."""
    _, _, body, res, _ = raw
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
    """Network b read again with its statement x as statement y of network a; and with only its pragmas of y."""
    _, pragma, body, res, itf = b.raw
    lines, other = body.splitlines(), a.raw[2].splitlines()
    whole = lines[:x.where[0]] + other[y.where[0]:y.where[2]] + lines[x.where[2]:]
    out = [whole]
    if x.key[0] != y.key[0]:
        out.append(lines[:x.where[0]] + other[y.where[0]:y.where[1]] + lines[x.where[1]:])
    return [s7dcl.network(b.index, pragma, '\n'.join(t), res, itf, next(s7dcl._blocks)) for t in out]
