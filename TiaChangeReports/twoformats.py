"""The bed of the two formats: does the report say the same from .s7dcl as from SimaticML? It runs on a repo laid out
as the two-format benchmark run's (each commit holds .s7dcl under plc/ and library/, and SimaticML of the same
objects under simaticml/), reads its commits and changes nothing.

A report is reduced to its facts (facts()); two reports say the same when their facts are the same multiset. What the
facts hold and what they cannot see: docs/dev/tools/tia-change-reports.md, section "The two formats against each other".

Two checks:
- nothing changed: per commit, the report from its .s7dcl to its SimaticML. Every object and network it lists is a
  difference.
- the same change: per commit, the report of the commit from its .s7dcl and from its SimaticML. Every object whose
  facts are not the same in both is a difference.

Each difference gets its causes (CAUSES), each named from what differs. What no rule names is 'unknown: ...', or a
field by its path ('SimaticML field: ...'), whose kind is unknown."""
import argparse
import difflib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(HERE))

from TiaChangeReports.compare import _other_texts_differ, _unread_differs, compare_snapshots, files_alike  # noqa: E402
from TiaChangeReports.diff import changed_params                                    # noqa: E402
from TiaChangeReports.iface import FIELDS, _value, block_rows, props_rows           # noqa: E402
from TiaChangeReports.render_lad import Layout                                       # noqa: E402
from TiaChangeReports.s7dcl import scl_lines                                         # noqa: E402
from TiaChangeReports.source import GitSnapshot, _git, git_snapshots, stem           # noqa: E402

ROOTS = ('plc/blocks/', 'plc/types/', 'library/types/')     # the folders both formats hold, from a side's root
XML_ROOT = 'simaticml'                                      # the SimaticML side's folder in the repo

READER, ONE_FIELD, NOTE, DRAWING, DIFF, ONE_OBJECT = (
    'reader', 'a field only one format writes', "the note's raw comparison", 'the drawing', 'the diff',
    'an object exported in one format only')
# A field neither reader reads gives both reports the same note: the second check cannot see it as a difference, and in
# the first it is part of 'note: files'.

# id: (kind, what it is). An id with a colon carries what was seen and has no kind: 'unknown: ...', 'SimaticML
# field: <path>', '.s7dcl field: <pragma>', 'SimaticML unread: <path>'.
CAUSES = {
    'quoted names': (READER, 'a member name .s7dcl writes in quotes ("Db"."step", #"a") and SimaticML without'),
    'pin case': (READER, "a block call's pin name in another case: the diff compares it as written, as a user may "
                         "rename it in case (an instruction's pin in any case)"),
    'pin order': (READER, "an element's unnamed operands in another order: the diff compares them by their place (a "
                          "named pin by its name, in any order)"),
    'pin direction': (READER, "a coil's operand read as an output (=>) from .s7dcl and as an input (:=) from SimaticML"),
    'templates': (ONE_FIELD, 'a type template SimaticML writes and .s7dcl does not (value_type, ptr_type, Card, ...)'),
    'ENO': (READER, "a box's ENO generated read from one format and not from the other: SimaticML writes DisabledENO, "
                    ".s7dcl S7_GenerateENO := \"TRUE\" where it is false and nothing where it is true"),
    'rung order': (READER, 'the rungs in another order: SimaticML holds no order, the reader takes the order of the '
                           "file's elements, which TIA's export varies"),
    'FBD lines': (READER, 'an FBD network read into other lines from the two formats'),
    'note: files': (NOTE, "the block's note compares the raw files, which differ between two formats"),
    'note: LAD lines': (NOTE, "a LAD network's note compares its text, which the two formats write otherwise"),
    'note: SimaticML order': (NOTE, 'a SimaticML network written in another order, with other ids, and nothing else'),
    'note: .s7dcl jump label': (NOTE, "a .s7dcl network's note when its jump label changed, the label shown"),
    'type members': (ONE_FIELD, 'SimaticML spells out the members of a type a block uses (an instance DB, a DB of a '
                                'UDT, a member of a UDT, the pins of a call); .s7dcl names the type'),
    'block number': (ONE_FIELD, 'the number TIA gives a block, in SimaticML only'),
    'SimaticML missing': (ONE_OBJECT, 'an .s7dcl and no SimaticML of the object in this commit, SimaticML of it in '
                                      'another'),
    'SimaticML never': (ONE_OBJECT, 'an .s7dcl and no SimaticML of the object in any commit'),
    '.s7dcl missing': (ONE_OBJECT, 'SimaticML and no .s7dcl of the object in this commit'),
    'declaration': (READER, "a block's declaration read with its own name in quotes from SimaticML"),
    'DB retain': (ONE_FIELD, "a DB's S7_StandardRetain: .s7dcl writes it, the SimaticML of these DBs has no "
                             "IsRetainMemResEnabled"),
    'instance DB access': (ONE_FIELD, "an instance DB's S7_Optimized: .s7dcl writes it, SimaticML has no MemoryLayout "
                                      "for an instance DB"),
    'SCL language': (READER, "an SCL block's language: .s7dcl's S7_EditorMode, SimaticML's ProgrammingLanguage, kept "
                             "as two properties"),
    'safety spelling': (READER, 'S7_Safety "True" from .s7dcl, "TRUE" from SimaticML'),
    'user-defined id': (READER, ".s7dcl's S7_UserDefinedId is SimaticML's HeaderName, which the reader does not read"),
    'member setpoint': (ONE_FIELD, 'SetPoint on a member of a library type: SimaticML writes it, .s7dcl writes none'),
    'constant type': (ONE_FIELD, "the type of a literal (ConstantType): SimaticML writes it, .s7dcl writes the "
                                 "literal alone"),
    'section attributes': (ONE_FIELD, "the attributes SimaticML writes on every member of a section (Accessibility, "
                                      "Remanence, ExternalAccessible, ExternalVisible, ExternalWritable, SetPoint); "
                                      ".s7dcl writes one only where it is set"),
    'standard access fields': (ONE_FIELD, 'MemoryReserve and IsRetainMemResEnabled, which SimaticML writes for a '
                                          'block with standard access'),
    'another kind of block': (ONE_FIELD, 'a block become another kind (FC, FB): SimaticML writes the sections and '
                                         'attributes of the kind'),
    'instance DB start values': (READER, "an instance DB's start values: the SimaticML reader leaves them to the "
                                         "note, the .s7dcl reader shows them"),
    'library link across formats': (DIFF, "a program block marked as differing from its library type: the two "
                                           "changes compared as text, each from one format to the other"),
    'author': (READER, "a block's author: S7_Author shown from .s7dcl, HeaderAuthor left to the note from SimaticML"),
    'drawn otherwise: mark areas': (DRAWING, 'an element marked alike, the marked areas drawn otherwise'),
}


def kind_of(cause):
    return CAUSES[cause][0] if cause in CAUSES else 'unknown'


def property_cause(name, vb, va, kind):
    """The cause of a property the report reads otherwise from the two formats, vb from .s7dcl, va from SimaticML:
    named only for the values seen, else 'unknown: property ...'."""
    rules = {'Retain': va is None and kind in ('DB', 'Instance DB'),
             'Optimized access': va is None and kind == 'Instance DB',
             'Language': vb is None and va == 'SCL', 'S7_EditorMode': vb == 'SCL' and va is None,
             'Safety': vb is not None and va is not None and vb != va and vb.lower() == va.lower(),
             'S7_UserDefinedId': va is None, 'S7_Author': va is None}
    names = {'Retain': 'DB retain', 'Optimized access': 'instance DB access', 'Language': 'SCL language',
             'S7_EditorMode': 'SCL language', 'Safety': 'safety spelling', 'S7_UserDefinedId': 'user-defined id',
             'S7_Author': 'author'}
    return names[name] if rules.get(name) else 'unknown: property %s %s -> %s' % (name, vb, va)


# ---------------------------------------------------------------- the two sides

def _kept(paths):
    return {stem(p) for p in paths if p.startswith(ROOTS)}


def sides_at(repo, rev):
    """(the .s7dcl side, the SimaticML side) of one commit: snapshots of the folders both formats hold."""
    sd = GitSnapshot(repo, rev)
    sd.only = _kept(sd._blobs.tree())
    xml = GitSnapshot(os.path.join(repo, XML_ROOT), rev)
    xml._laid_out = False                                   # read whole: its root is no project repo's
    xml.only = _kept(xml._blobs.tree())
    return sd, xml


def change_of(repo, rev1, rev2):
    """((before, after) from .s7dcl, (before, after) from SimaticML): the report of rev1 -> rev2 in each format, the
    blocks with a changed file, as --git takes them."""
    sd = git_snapshots(repo, rev1, rev2)
    xml = git_snapshots(os.path.join(repo, XML_ROOT), rev1, rev2)
    for x in xml:
        x._laid_out = False
    for pair in (sd, xml):
        keep = {s for s in pair[0].only if s.startswith(ROOTS)}
        for x in pair:
            x.only = keep
    return sd, xml


# ---------------------------------------------------------------- facts

def _object(d):
    """The key of a listed object: its path without the extension, the same in both formats."""
    return stem(d.path_a or d.path_b)


def _net(p):
    """The key of a network: its number before and after and its title."""
    return (p.before.index if p.before else None, p.after.index if p.after else None, p.title)


def _element(el):
    """An element as compared (Element.sig): no element id, no wire name, its ENO generated or not."""
    return el.sig()


def _layouts(pair, d):
    b, a = pair.before, pair.after
    lb = Layout(b.rungs, d.before.interface, d.before.callees, b.label, pair.label_state, pair.lad.other) if b else None
    la = Layout(a.rungs, d.after.interface, d.after.callees, a.label, pair.label_state, pair.lad.other) if a else None
    return lb, la


def _marks(pair, d):
    """The marks of a LAD network: (side, element, fill, the areas of it marked from its own corner)."""
    out = []
    lb, la = _layouts(pair, d)
    for lay, other, side in ((lb, la, 'before'), (la, lb, 'after')):
        if lay is None:
            continue
        at = {el.eid: (el, ex, y) for el, ex, y in lay._placed()}
        got = {}
        for eid, fill, layer, x, y, w, h in lay.marks(pair.lad.status, pair.lad.other,
                                                      'removed' if side == 'before' else 'added', other):
            el, ex, ey = at[eid]
            got.setdefault(eid, (el, fill, []))[2].append((layer, round(x - ex), round(y - ey), round(w), round(h)))
        out += [(side, _element(el), fill, tuple(sorted(areas))) for el, fill, areas in got.values()]
    return out


def _show(v):
    return tuple(sorted(v.items())) if isinstance(v, dict) else v


def facts(diffs):
    """Counter of the facts of a report (module doc)."""
    out = Counter()
    for d in diffs:
        o = _object(d)
        out[(o, 'state', d.state)] += 1
        out[(o, 'kind', d.kind)] += 1
        if d.declaration:
            out[(o, 'declaration') + d.declaration] += 1
        if d.not_shown:
            out[(o, 'note')] += 1
        if d.library:
            out[(o, 'library', d.library.block.name, d.library_differs)] += 1
        if d.state in ('version', 'moved'):
            continue
        if d.before and d.after:
            for r in block_rows(d.before, d.after):
                if r.state == 'same':
                    continue
                if r.b is None or r.a is None:
                    out[(o, 'interface', r.path, r.state) + tuple(_show(_value(r.m, f)) for f in FIELDS)] += 1
                    continue
                for f in sorted(r.changes):
                    part = 'start value' if f == 'value' else 'interface'
                    vals = (_show(_value(r.b, f)), _show(_value(r.a, f))) if f in FIELDS else ()
                    out[(o, part, r.path, r.state, f) + vals] += 1
            for name, vb, va in props_rows(d.before.props, d.after.props):
                out[(o, 'property', name, vb, va)] += 1
        for p in d.nets:
            n = _net(p)
            out[(o, 'network', n, p.state, p.lang)] += 1
            for tag, on in _tags(p):
                if on:
                    out[(o, 'network tag', n, tag)] += 1
            if p.before and p.after:
                for f in ('title', 'comment'):
                    if getattr(p.before, f) != getattr(p.after, f):
                        out[(o, 'network ' + f, n, getattr(p.before, f), getattr(p.after, f))] += 1
            if p.lad is not None:
                for m in _marks(p, d):
                    out[(o, 'mark', n) + m] += 1
            else:
                for sign, line in _lines(p):
                    out[(o, 'line', n, sign, line)] += 1
    return out


def _tags(p):
    return (('moved', p.moved), ('other order', p.reordered), ('renamed', p.renamed), ('note', p.not_shown),
            ('label', p.label_state != 'same'))


def _lines(p):
    """('-' or '+', line) of the lines of an SCL or FBD network that differ; all of a side without the network."""
    bl, al = (scl_lines(x.body) if x else [] for x in (p.before, p.after))
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, bl, al, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        yield from (('-', x) for x in bl[i1:i2])
        yield from (('+', x) for x in al[j1:j2])


# ---------------------------------------------------------------- an element read otherwise

def _unquoted(v):
    return re.sub(r'(?<=[.#])"([^"]+)"', r'\1', v)


def _normal(sig, steps, other_templates):
    instr, inst, call, params, templates, expr, no_eno = sig
    ps = list(params)
    if 'ENO' in steps:
        no_eno = None
    if 'quoted names' in steps:
        ps = [(n, d, _unquoted(v)) for n, d, v in ps]
        inst = _unquoted(inst)
    if 'pin case' in steps:
        ps = [(n.lower(), d, v) for n, d, v in ps]
    if 'pin direction' in steps:
        ps = [(n, '', v) for n, d, v in ps]
    if 'pin order' in steps:
        ps = sorted(ps)
    if 'templates' in steps:
        templates = tuple(x for x in templates if x[0] in other_templates)
    return instr, inst, call, tuple(ps), templates, expr, no_eno


STEPS = ('quoted names', 'pin case', 'pin direction', 'pin order', 'templates', 'ENO')


def element_causes(x, y):
    """Why two versions of an element compare unequal, each as compared (_element): the fewest of STEPS that make them
    equal, the first such set in the order of STEPS; 'unknown: element' when all of them do not."""
    if x == y:
        return set()
    tx, ty = {k for k, v in x[4]}, {k for k, v in y[4]}
    for n in range(1, len(STEPS) + 1):
        for steps in combinations(STEPS, n):
            if _normal(x, steps, ty) == _normal(y, steps, tx):
                return set(steps)
    return {'unknown: element %s' % x[0]}


# ---------------------------------------------------------------- what moved in a file

def _local(tag):
    return tag.rsplit('}', 1)[-1]


def xml_fields(element):
    """Counter of (path, attributes, text) of an element and all under it: no UId or ID (the export numbers them), no
    order, no DocumentInfo (the export's time and products)."""
    out = Counter()

    def walk(e, path):
        tag = _local(e.tag)
        if tag == 'DocumentInfo':
            return
        p = path + '/' + tag
        out[(p, tuple(sorted((k, v) for k, v in e.attrib.items() if k not in ('UId', 'ID'))),
             (e.text or '').strip())] += 1
        for c in e:
            walk(c, p)
    walk(element, '')
    return out


NAMED_TAGS = ('BooleanAttribute', 'IntegerAttribute', 'StringAttribute', 'DateAttribute', 'TemplateValue', 'Section')


def xml_moved(xb, xa):
    """What differs between two SimaticML elements (xml_fields), order and ids aside: 'path@attribute', 'path#text',
    'path added' or 'path removed'; an attribute element by its Name ('.../BooleanAttribute[SetPoint]#text')."""
    fb, fa = xml_fields(xb), xml_fields(xa)
    by = {}
    for k in (fb - fa).elements():
        by.setdefault((k[0], dict(k[1]).get('Name')), ([], []))[0].append(k)
    for k in (fa - fb).elements():
        by.setdefault((k[0], dict(k[1]).get('Name')), ([], []))[1].append(k)
    out = set()
    for (path, name), (gone, new) in by.items():
        label = path + ('[%s]' % name if name and path.rsplit('/', 1)[-1] in NAMED_TAGS else '')
        for x, y in zip(gone, new):
            ax, ay = dict(x[1]), dict(y[1])
            out |= {'%s@%s' % (label, k) for k in set(ax) | set(ay) if ax.get(k) != ay.get(k)}
            if x[2] != y[2]:
                out.add(label + '#text')
        if len(gone) != len(new):
            out.add(label + (' added' if len(new) > len(gone) else ' removed'))
    return sorted(out)


def _root(text):
    return ET.fromstring(text.encode('utf-8'))


def _typed_db(root):
    """A DB whose members are its type's: an instance DB, a DB of a UDT."""
    blk = next((e for e in root if _local(e.tag).startswith('SW.Blocks.')), None)
    if blk is None:
        return False
    return _local(blk.tag) == 'SW.Blocks.InstanceDB' or any(_local(e.tag) == 'InstanceOfName' for e in blk.iter())


def sd_moved(tb, ta):
    """The pragmas (S7_...) of the lines that differ between two .s7dcl texts, else 'lines'."""
    lb, la = (t.splitlines() if t else [] for t in (tb, ta))
    out = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lb, la, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        for line in lb[i1:i2] + la[j1:j2]:
            m = re.match(r'\s*(S7_\w+)\s*:=', line)
            out.add(m.group(1) if m else 'lines')
    return sorted(out)


def _xml_label(path):
    return re.sub(r'^/(Document/)?SW\.Blocks\.\w+/', '', path)


# What xml_moved names -> the cause, the first that matches.
XML_FIELDS = [
    (r'/AttributeList/(Number|AutoNumber)#text$', 'block number'),
    (r'/ConstantType#text$', 'constant type'),
    (r'/TemplateValue\[\w+\] (added|removed)$', 'templates'),
    (r'/CallInfo/Parameter@Type$', 'type members'),
    (r'/Member/AttributeList/BooleanAttribute\[(ExternalAccessible|ExternalVisible|ExternalWritable|SetPoint)\]'
     r'|/Member@(Accessibility|Remanence)$|/Member/AttributeList (added|removed)$', 'section attributes'),
    (r'/AttributeList/(MemoryReserve|IsRetainMemResEnabled)\b', 'standard access fields'),
]
# What the SimaticML reader reads and shows: a network's note is not on it while something else moved.
XML_READ = (r'/Access@Scope$', r'/Symbol/Component (added|removed)$', r'/Symbol/Component@Name$',
            r'/TemplateValue\[\w+\]#text$', r'/ConstantValue#text$', r'/MemoryLayout#text$', r'/NameCon@Name$',
            r'/Label@Name$', r'/InstanceOfName#text$')
# What the .s7dcl reader shows and the SimaticML reader leaves to the note.
XML_UNREAD = [(r'/Member/StartValue', 'instance DB start values'), (r'/HeaderAuthor\b', 'author')]
SD_FIELDS = {'S7_StandardRetain': 'DB retain'}


def field_causes(fmt, moved, typed_db=False, shown=False):
    """The causes of what one format moved and the other did not, or of what one format's note sees: fmt 'xml' or
    'sd', moved what xml_moved or sd_moved names; typed_db: of a DB whose members are its type's; shown: the other
    report shows something there that this reader may leave to its note. A field no table names keeps its path and has
    no kind: 'SimaticML field: <path>' ('SimaticML unread: <path>' when shown), '.s7dcl field: <pragma>'."""
    if fmt == 'sd':
        return {SD_FIELDS.get(f, '.s7dcl field: %s' % f) for f in moved}
    if any(re.search(r'^/(Document/)?SW\.Blocks\.\w+ (added|removed)$', f) for f in moved):
        return {'another kind of block'}
    unread = [f for f in moved if not any(re.search(r, f) for r in XML_READ)] or moved
    out = set()
    for f in unread:
        cause = next((c for r, c in XML_UNREAD if re.search(r, f)), None) if shown else None
        if cause is None and '/Interface/' in f and (typed_db or '/Member/Sections/' in f):
            cause = 'type members'
        cause = cause or next((c for r, c in XML_FIELDS if re.search(r, f)), None)
        out.add(cause or '%s: %s' % ('SimaticML unread' if shown else 'SimaticML field', _xml_label(f)))
    return out


# ---------------------------------------------------------------- check 1: nothing changed

def nothing_changed(repo, rev, files=None):
    """[{object, network, causes}]: every object and network the report from rev's .s7dcl to its SimaticML lists."""
    files = files or Files(repo)
    sd, xml = sides_at(repo, rev)
    out = []
    for d in compare_snapshots(sd, xml):
        o = _object(d)
        if not (d.before and d.after):                    # its file in one format only: so are its networks
            why = files.missing(o, bool(d.after))
            out += [{'object': o, 'network': None, 'causes': [why]}]
            out += [{'object': o, 'network': list(_net(p)), 'causes': [why]} for p in d.nets]
            continue
        nets = [{'object': o, 'network': list(_net(p)), 'causes': sorted(_network_causes(p, d))} for p in d.nets]
        own = _object_causes(d, sd, xml)
        if not own and not nets:
            own = {'unknown: listed, nothing seen'}
        out.append({'object': o, 'network': None, 'causes': sorted(own.union(*(x['causes'] for x in nets)))})
        out += nets
    return out


def _object_causes(d, sd, xml):
    """Why a block is listed between its two formats, apart from its networks."""
    out = set()
    if d.declaration:
        out.add('declaration' if _same_decl(d.declaration, d.block.name) else 'unknown: declaration')
    if d.not_shown:
        bsrc, asrc = sd.load(d.path_b), xml.load(d.path_a)
        if not files_alike(bsrc, asrc):
            out.add('note: files')
        if _other_texts_differ(bsrc, asrc):
            out.add('unknown: note, texts in another language')
        if _unread_differs(bsrc, asrc, d.before, d.after, d.nets):
            out.add('unknown: note, unread part')
    for name, vb, va in props_rows(d.before.props, d.after.props):
        out.add(property_cause(name, vb, va, d.kind))
    xml_members = bool(d.after.interface.root.children)
    for r in block_rows(d.before, d.after):
        if r.state == 'same':
            continue
        if r.b is None or r.a is None:
            out.add('unknown: interface, member %s' % r.state)
        for f in r.changes:
            if f == 'attrs':
                ab, aa = r.b.attrs or {}, r.a.attrs or {}
                out |= {'member setpoint' if k == 'S7_Setpoint' and ab.get(k) is None and aa.get(k) == 'True'
                        else 'unknown: interface, %s' % k for k in set(ab) | set(aa) if ab.get(k) != aa.get(k)}
            elif f == 'value' and d.kind == 'Instance DB' and not xml_members:
                out.add('instance DB start values')       # the SimaticML reader reads no member of an instance DB
            else:
                out.add('unknown: interface, %s' % f)
    if d.library_differs:
        out.add('library link across formats')
    return out


def _network_causes(p, d):
    """Why a network is listed between its two formats."""
    b, a = p.before, p.after
    if not (b and a):
        return {'unknown: network %s' % p.state}
    out = set()
    if p.reordered or p.moved:
        out.add('rung order' if p.reordered else 'unknown: network moved')
    if p.not_shown:
        out.add('note: LAD lines' if p._unseen() else 'unknown: network note')
    for f in ('title', 'comment', 'label'):
        if getattr(b, f) != getattr(a, f):
            out.add('unknown: network %s' % f)
    if b.lang != a.lang:
        out.add('unknown: language')
    if p.lad is None:
        if list(_lines(p)):
            out.add('FBD lines' if b.lang == 'FBD' else 'unknown: %s lines' % b.lang)
        return out or {'unknown: network'}
    lb, la = _layouts(p, d)
    for el, x, y in lb._placed():
        st, o = p.lad.status.get(el.eid, 'same'), p.lad.other.get(el.eid)
        if st == 'changed' and o is not None:
            out |= element_causes(_element(el), _element(o))
        elif st == 'moved':
            out.add('rung order' if p.reordered else 'unknown: element moved')
        elif st != 'same':
            out.add('unknown: element %s' % st)
        if st in ('same', 'changed') and o is not None and o.eid in la.views:
            keys = lb.views[el.eid].drawn_otherwise(la.views[o.eid]) - changed_params(el, o)
            if keys and _element(el) == _element(o):
                out.add('unknown: drawn otherwise, %s' % ', '.join(sorted(keys)))
    for el, x, y in la._placed():
        if p.lad.status.get(el.eid, 'same') in ('added', 'removed'):
            out.add('unknown: element %s' % p.lad.status[el.eid])
    return out or {'unknown: network'}


# ---------------------------------------------------------------- check 2: the same change

class Files:
    """Which files of an object each format holds, per commit, and which objects ever had SimaticML."""

    def __init__(self, repo):
        self.repo = repo
        self._trees = {}
        self._ever = None

    def tree(self, rev):
        if rev not in self._trees:
            out = {}
            for line in _git(self.repo, 'ls-tree', '-r', rev).decode('utf-8').splitlines():
                meta, path = line.split('\t', 1)
                out[path] = meta.split()[2]
            self._trees[rev] = out
        return self._trees[rev]

    def ever_xml(self):
        """The objects with SimaticML in any commit."""
        if self._ever is None:
            out = _git(self.repo, 'log', 'HEAD', '--format=', '--name-only', '--', XML_ROOT).decode('utf-8')
            self._ever = {stem(p[len(XML_ROOT) + 1:]) for p in out.splitlines() if p.endswith('.xml')}
        return self._ever

    def of(self, rev, o):
        """{'sd': blob id or None, 'xml': blob id or None} of object o at rev."""
        t = self.tree(rev)
        return {'sd': t.get(self.sd_path(rev, o)), 'xml': t.get(xml_path(o))}

    def sd_path(self, rev, o):
        """The file of object o on the .s7dcl side at rev: its .s7dcl, else the .xml TIA writes there for an OB."""
        t = self.tree(rev)
        return o + '.s7dcl' if o + '.s7dcl' in t or o + '.xml' not in t else o + '.xml'

    def text(self, rev, path):
        try:
            return _git(self.repo, 'show', '%s:%s' % (rev, path)).decode('utf-8-sig')
        except ValueError:
            return None

    def one_format(self, rev1, rev2, o):
        """The cause when object o has a file in one format only at rev1 or rev2 (missing()), else None."""
        for rev in (rev1, rev2):
            f = self.of(rev, o)
            if bool(f['sd']) != bool(f['xml']):
                return self.missing(o, bool(f['xml']))
        return None

    def missing(self, o, has_xml):
        """The cause of object o with a file in one format only (has_xml: the SimaticML one): what is seen, not why."""
        if has_xml:
            return '.s7dcl missing'
        return 'SimaticML missing' if o in self.ever_xml() else 'SimaticML never'


def xml_path(o):
    return '%s/%s.xml' % (XML_ROOT, o)


def same_change(repo, rev1, rev2, files=None):
    """[{object, causes, sd, xml}]: every object whose facts differ between the report of rev1 -> rev2 from .s7dcl and
    from SimaticML; sd and xml its facts that only that report holds."""
    files = files or Files(repo)
    (sb, sa), (xb, xa) = change_of(repo, rev1, rev2)
    ds, dx = compare_snapshots(sb, sa), compare_snapshots(xb, xa)
    fs, fx = facts(ds), facts(dx)
    if fs == fx:
        return []
    by_s, by_x = {_object(d): d for d in ds}, {_object(d): d for d in dx}
    refs = {}                         # an object -> the objects a listed block of either report joins it with
    for d in ds + dx:
        stems = {stem(p) for x in (d, d.library) if x for p in (x.path_b, x.path_a) if p}
        for s in stems:
            refs.setdefault(s, set()).update(stems)
    out = []
    for o in sorted({k[0] for k in (fs - fx) + (fx - fs)}):
        of_sd, of_xml = _where(fs, lambda k: k[0] == o), _where(fx, lambda k: k[0] == o)
        side = Side(files, rev1, rev2)
        causes = _change_causes(o, refs.get(o, {o}) | {o}, by_s.get(o), by_x.get(o), of_sd, of_xml, side)
        out.append({'object': o, 'causes': sorted(causes),
                    'sd': [list(k[1:]) for k in sorted(of_sd - of_xml, key=str)],
                    'xml': [list(k[1:]) for k in sorted(of_xml - of_sd, key=str)]})
    return out


def _where(facts_, keep):
    return Counter({k: v for k, v in facts_.items() if keep(k)})


class Side:
    """The repo's files and the two commits of a check of the same change: the texts of an object's two versions."""

    def __init__(self, files, rev1, rev2):
        self.files, self.rev1, self.rev2 = files, rev1, rev2

    def texts(self, d, fmt):
        """(before, after) text of the block d of one report lists, fmt 'sd' or 'xml': by its own paths, which differ
        for a block renamed or moved; None for a version it does not have."""
        def path(rev, p):
            if p is None:
                return None
            o = stem(p)
            return xml_path(o) if fmt == 'xml' else self.files.sd_path(rev, o)
        return tuple(self.files.text(rev, x) if x else None
                     for rev, x in ((self.rev1, path(self.rev1, d.path_b)), (self.rev2, path(self.rev2, d.path_a))))


def _change_causes(o, related, ds, dx, fs, fx, side):
    """related: o and the objects either report joins it with (a rename, a move, its library type or program
    block). One of them with a file in one format only: the reports cannot hold the same of o, nothing else is
    looked for. A file only one format moved: the other report holds nothing of o, what moved is the cause."""
    for x in sorted(related):
        why = side.files.one_format(side.rev1, side.rev2, x)
        if why:
            return {why}
    before, after = side.files.of(side.rev1, o), side.files.of(side.rev2, o)
    moved_sd, moved_xml = before['sd'] != after['sd'], before['xml'] != after['xml']
    if moved_sd != moved_xml:
        return _moved_alone(o, 'sd' if moved_sd else 'xml', side)
    out = _block_part(o, ds, dx, fs, fx, side)
    nets = {k[2] for k in (fs - fx) + (fx - fs) if k[1] in NET_FACTS}
    for n in sorted(nets, key=str):
        out |= _net_part(n, dx, fs, fx)
    return out or {'unknown: object'}


NET_FACTS = ('network', 'network tag', 'mark', 'line', 'network title', 'network comment')


def _moved_alone(o, fmt, side):
    """The fields of an object that moved in one format and not in the other."""
    if fmt == 'sd':
        path = side.files.sd_path(side.rev2, o)
        tb, ta = side.files.text(side.rev1, path), side.files.text(side.rev2, path)
        if path.endswith('.xml'):
            return field_causes('sd', ['SimaticML of an OB'])
        return field_causes('sd', sd_moved(tb, ta))
    tb, ta = (side.files.text(r, xml_path(o)) for r in (side.rev1, side.rev2))
    rb, ra = _root(tb), _root(ta)
    return field_causes('xml', xml_moved(rb, ra), _typed_db(ra)) or {'unknown: SimaticML moved alone'}


BLOCK_FACTS = ('state', 'kind', 'declaration', 'note', 'library', 'interface', 'start value', 'property')
SHOWN = ('property', 'start value', 'interface')


def _block_part(o, ds, dx, fs, fx, side):
    """The causes of the block-level facts that differ."""
    only_s = _where(fs, lambda k: k[1] in BLOCK_FACTS) - _where(fx, lambda k: k[1] in BLOCK_FACTS)
    only_x = _where(fx, lambda k: k[1] in BLOCK_FACTS) - _where(fs, lambda k: k[1] in BLOCK_FACTS)
    if not (only_s or only_x):
        return set()
    out = set()
    shown_s = [k for k in only_s if k[1] in SHOWN]
    told = set()                                          # shown facts a cause of the SimaticML note accounts for
    if (o, 'note') in only_x:
        tb, ta = side.texts(dx, 'xml') if dx else (None, None)
        if tb is None or ta is None:
            out.add('unknown: SimaticML note')
        else:
            moved = xml_moved(_head(_root(tb)), _head(_root(ta)))
            causes = field_causes('xml', moved, _typed_db(_root(ta)), bool(shown_s))
            out |= causes or {'unknown: SimaticML note'}
            for k in shown_s:
                if UNREAD_SHOWN.get(k[1] if k[1] != 'property' else k[2]) in causes:
                    told.add(k)
    if (o, 'note') in only_s:
        tb, ta = side.texts(ds, 'sd') if ds else (None, None)
        out |= {'unknown: .s7dcl note, %s' % f for f in sd_moved(tb, ta)} or {'unknown: .s7dcl note'}
    decl = [k for k in only_s + only_x if k[1] == 'declaration']
    if decl:
        name = o.rsplit('/', 1)[-1]
        out.add('declaration' if len({tuple(_without_name(x, name) for x in k[2:]) for k in decl}) == 1
                else 'unknown: declaration')
    for part in ('state', 'kind'):                        # listed by both reports, as another state or kind
        vs, vx = ({k[2] for k in c if k[1] == part} for c in (fs, fx))
        if vs and vx and vs != vx:
            out.add('unknown: %s %s / %s' % (part, sorted(vs)[0], sorted(vx)[0]))
    for k in only_s + only_x:
        if k[1] in ('note', 'state', 'kind', 'declaration') or k in told:
            continue
        out.add('unknown: %s' % k[1])
    return out           # an object one report alone lists: its state and kind follow from the causes of the rest


# A fact the .s7dcl report shows (its part, or a property's name) -> the cause naming the SimaticML reader's gap.
UNREAD_SHOWN = {'start value': 'instance DB start values', 'Author': 'author', 'S7_Author': 'author'}


def _without_name(decl, name):
    """A declaration without the block's own name, quoted or not."""
    return re.sub(r'\s+', ' ', re.sub(r'(?<![\w"])"?%s"?(?![\w"])' % re.escape(name), '', decl)).strip()


def _same_decl(pair, name):
    """(before, after) declarations that differ only in the block's own name, written or not, quoted or not."""
    return _without_name(pair[0], name) == _without_name(pair[1], name)


def _head(root):
    """A SimaticML export without its networks: what a note on the block reads."""
    for parent in root.iter():
        for c in list(parent):
            if _local(c.tag) == 'ObjectList':
                parent.remove(c)
    return root


def _net_part(n, dx, fs, fx):
    """The causes of one network's facts that differ."""
    def of(c):
        return Counter({k: v for k, v in c.items() if len(k) > 2 and k[2] == n and k[1] in NET_FACTS})
    ns, nx = of(fs), of(fx)
    if ns == nx:
        return set()
    out = set()
    tags_s, tags_x = {k[3] for k in ns if k[1] == 'network tag'}, {k[3] for k in nx if k[1] == 'network tag'}
    if 'other order' in tags_s ^ tags_x:
        out.add('rung order')
    ms, mx = ([k[3:] for k in c.elements() if k[1] == 'mark'] for c in (ns, nx))
    ls, lx = ([k[3:] for k in c.elements() if k[1] == 'line'] for c in (ns, nx))
    if 'note' in tags_x - tags_s:
        out |= _xml_note(n, dx, Counter(ms) != Counter(mx) or Counter(ls) != Counter(lx))
    if 'note' in tags_s - tags_x:
        out.add('note: .s7dcl jump label' if 'label' in tags_s else 'unknown: .s7dcl network note')
    for tag in (tags_s ^ tags_x) - {'other order', 'note'}:
        out.add('unknown: network tag %s' % tag)
    out |= _mark_causes(ms, mx, 'rung order' in out)
    if Counter(ls) != Counter(lx):
        out.add('unknown: lines')
    for part in ('network title', 'network comment'):
        if {k for k in ns if k[1] == part} != {k for k in nx if k[1] == part}:
            out.add('unknown: %s' % part)
    st_s, st_x = ({k[3:] for k in c if k[1] == 'network'} for c in (ns, nx))
    if st_s and st_x and st_s != st_x:                    # listed by both reports, in another state or language
        out.add('unknown: network %s / %s' % tuple(' '.join(sorted(x)[0]) for x in (st_s, st_x)))
    elif st_s != st_x and not out:                        # listed by one alone: follows from what the causes name
        out.add('unknown: network listed by one report alone')
    return out or {'unknown: network'}


def _xml_note(n, dx, shown):
    """A SimaticML network noted and the .s7dcl one not: what differs in its part of the file, order and ids aside.
    shown: the .s7dcl report marks the network otherwise, what the SimaticML reader may leave to the note."""
    p = next((p for p in (dx.nets if dx else ()) if _net(p) == n), None)
    if p is None or not (p.before and p.after and p.before.raw and p.after.raw):
        return {'unknown: SimaticML network note'}
    moved = xml_moved(p.before.raw[1], p.after.raw[1])
    if not moved:
        return {'note: SimaticML order'}
    return field_causes('xml', [re.sub(r'^/SW\.Blocks\.CompileUnit/AttributeList/NetworkSource/', 'network/', f)
                                for f in moved], shown=shown)


def _mark_causes(ms, mx, reordered):
    """The marks of one network from each report, (side, element, fill, areas). A mark of one paired with a mark of the
    other on the same side with the same fill, the element read otherwise: its causes (element_causes), the areas
    alike or not, as the drawing marks the text it reads. What is left of one report alone: a box it marks between two
    versions read otherwise (the before and the after mark of one element in it); else, of elements marked moved in a
    network the tags say is in another order of its rungs, 'rung order'; else unknown."""
    left_s, left_x = list((Counter(ms) - Counter(mx)).elements()), list((Counter(mx) - Counter(ms)).elements())
    out = set()
    for same_areas in (True, False):
        for m in list(left_s):
            y = next((y for y in left_x if y[0] == m[0] and y[2] == m[2] and (y[3] == m[3] or not same_areas)
                      and _explained(m[1], y[1])), None)
            if y is not None:
                out |= element_causes(m[1], y[1]) or {'drawn otherwise: mark areas'}
                left_s.remove(m)
                left_x.remove(y)
    for left in (left_s, left_x):
        for m in [m for m in left if m[0] == 'before']:
            y = next((y for y in left if y[0] == 'after' and m[1] != y[1] and _explained(m[1], y[1])), None)
            if y is not None:
                out |= element_causes(m[1], y[1])
                left.remove(m)
                left.remove(y)
    if left_s or left_x:
        fills = {m[2] for m in left_s + left_x}
        out.add('rung order' if reordered and fills == {'moved'} else 'unknown: marks %s' % ', '.join(sorted(fills)))
    return out


def _explained(x, y):
    return not any(c.startswith('unknown') for c in element_causes(x, y))


# ---------------------------------------------------------------- the run

def commits(repo, since=None, until=None):
    """The commits of the repo, oldest first, from since to until (default: HEAD), both included. since by default:
    the first commit with a file under simaticml/, the first that can hold both formats."""
    out = _git(repo, 'rev-list', '--reverse', until or 'HEAD').decode().split()
    if not since:
        first = _git(repo, 'rev-list', '--reverse', until or 'HEAD', '--', XML_ROOT).decode().split()
        if not first:
            raise ValueError('no commit of %s holds a %s folder' % (repo, XML_ROOT))
        since = first[0]
    return out[out.index(_git(repo, 'rev-parse', since).decode().strip()):]


def subjects(repo):
    return dict(line.split(' ', 1) for line in
                _git(repo, 'log', '--format=%H %s').decode('utf-8').splitlines() if ' ' in line)


def row_of(subject):
    m = re.match(r'([A-Z]+\d+):?\s', subject)
    return m.group(1) if m else ''


def run(repo, since, until, checks, progress=None):
    """{'nothing changed': [{commit, row, differences}], 'same change': [...]} over the commits since .. until."""
    cs = commits(repo, since, until)
    subj = subjects(repo)
    out = {}
    files = Files(repo)
    if 'nothing' in checks:
        out['nothing changed'] = []
        for k, c in enumerate(cs):
            out['nothing changed'].append({'commit': c[:7], 'row': row_of(subj.get(c, '')),
                                           'differences': nothing_changed(repo, c, files)})
            if progress:
                progress('nothing changed', k + 1, len(cs))
    if 'same' in checks:
        out['same change'] = []
        for k, (c1, c2) in enumerate(zip(cs, cs[1:])):
            out['same change'].append({'commit': c2[:7], 'row': row_of(subj.get(c2, '')),
                                       'differences': same_change(repo, c1, c2, files)})
            if progress:
                progress('same change', k + 1, len(cs) - 1)
    return out


def counts(result):
    """Text lines: per check, the counts by cause."""
    lines = []
    nc = result.get('nothing changed')
    if nc:
        def objs(r):
            return {x['object'] for x in r['differences']}

        def nets(r):
            return [x for x in r['differences'] if x['network'] is not None]
        worst = max(nc, key=lambda r: (len(objs(r)), len(nets(r))))
        picks = [('start', nc[0]), ('head', nc[-1]), ('worst', worst)]
        lines.append('Nothing changed: %d commits. Objects (networks) listed: %s' % (len(nc), ', '.join(
            '%s %s %d (%d)' % (name, r['commit'], len(objs(r)), len(nets(r))) for name, r in picks)))
        lines.append('  %-44s %-38s %s' % ('cause', 'kind', '  '.join('%-13s' % n for n, _ in picks)))
        per = {}
        for name, r in picks:
            for x in r['differences']:
                for c in x['causes']:
                    per.setdefault(c, {}).setdefault(name, [set(), 0, 0])
                    e = per[c][name]
                    if x['network'] is None:
                        e[0].add(x['object'])
                    else:
                        e[1] += 1
                        e[2] += len(x['causes']) == 1
        for c in sorted(per, key=lambda c: (-per[c].get('start', [set(), 0])[1], -len(per[c].get('start', [set()])[0]), c)):
            cells = []
            for name, _ in picks:
                o, n, alone = per[c].get(name, [set(), 0, 0])
                cells.append('%-13s' % ('%d/%d (%d)' % (len(o), n, alone)))
            lines.append('  %-44s %-38s %s' % (c[:44], kind_of(c)[:38], '  '.join(cells)))
        lines.append('  (objects/networks (networks with no other cause))')
    sc = result.get('same change')
    if sc:
        rows = [r for r in sc if r['differences']]
        lines.append('The same change: %d commits, %d whose two reports differ' % (len(sc), len(rows)))
        per = {}
        for r in rows:
            for x in r['differences']:
                for c in x['causes']:
                    e = per.setdefault(c, [set(), 0, set()])
                    e[0].add(r['commit'])
                    e[1] += 1
                    if all(c2 == c for y in r['differences'] for c2 in y['causes']):
                        e[2].add(r['commit'])
        lines.append('  %-44s %-38s %s' % ('cause', 'kind', 'commits objects (alone)'))
        for c in sorted(per, key=lambda c: (-len(per[c][0]), c)):
            lines.append('  %-44s %-38s %-7d %-7d (%d)' % (c[:44], kind_of(c)[:38], len(per[c][0]), per[c][1],
                                                            len(per[c][2])))
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(prog='TiaChangeReports.twoformats', description=__doc__.split('\n\n')[0])
    p.add_argument('repo', help='a repo laid out as the two-format run: .s7dcl under plc/ and library/, SimaticML '
                                'under simaticml/')
    p.add_argument('--since', help='first commit (default: the first with a file under simaticml/)')
    p.add_argument('--until', help='last commit (default: HEAD)')
    p.add_argument('--check', choices=('nothing', 'same', 'both'), default='both',
                   help='nothing changed, the same change, or both (default: both)')
    p.add_argument('--json', help='also write every difference with its causes, and for the same change the facts '
                                  'each report alone holds, to this file')
    a = p.parse_args(argv)
    checks = ('nothing', 'same') if a.check == 'both' else (a.check,)

    def progress(check, k, n):
        if k % 25 == 0 or k == n:
            print('%s: %d of %d' % (check, k, n), file=sys.stderr, flush=True)
    try:
        result = run(a.repo, a.since, a.until, checks, progress)
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 2
    for line in counts(result):
        print(line)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=1, default=list)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    sys.exit(main())
