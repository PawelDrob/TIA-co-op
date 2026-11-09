"""The PLC tag tables of a change report: plc/tags/*.xml (plc/<device>/tags/ with several PLCs) of two snapshots, per PLC
and table, as objects of the page beside the blocks.

  compare(before, after)                  -> [TableDiff], one per table of either snapshot (a --git snapshot: the
                                             tables with a changed file)
  PlcTagPart(diffs, all_, draw_added_removed)
                                          the tables for the page, as hmi.HmiPart: items, sections, summary, json, lines

A snapshot's tag_tables() lists the files, known by their first element wherever they lie, and every .xml of no block in
a PLC's tags folder, table or not (one that holds none does not read, below). A table pairs by path, then
by its name in another folder of its PLC (moved), then by its tags in common (renamed). A tag or user constant pairs by
name, then by what is left of it: a tag by its address, a constant by its type and value, where that is unique among the
left ones of the table (renamed). A tag gone from one table and new in another of its PLC is told as moved there, both
rows drawn, also in a table otherwise only listed: its values may differ.

What is read: a tag's name, data type, address, comment and the three boxes, a constant's name, data type, value and
comment, in TIA's columns. An export has no Retain and no Supervision column: TIA keeps the first per PLC, not per tag,
and the bridge writes the second to plc/supervisions. An absent box is ticked, as TIA makes a new tag (the bridge
exports WithDefaults; a file written by hand may leave them out). Comments in the report's language, else the first
there is, as a block's. Anything else of the file that differs (a field no column shows, another language's text, also
one a tag swaps with another's, a comment's language gained or lost with the text shown the same, an object beside the
tags) is the report's note NOT_SHOWN, and a tag holding such a field reads changed. The export time
and the object numbers are no difference (simaticml._plain). The order of the tags in the file is: a tag out of the
common order of the two versions reads moved (diff.out_of_order). A file that does not parse is named in the snapshot's
skipped and is a table of the report with nothing in it and that note. A file that cannot be read (a lock) is named there
too and tells nothing of its content, not even whether its table is new or moved: it is no table of the report on either
side, and a table of another path stands alone, without it. The page names both."""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import escape
from types import SimpleNamespace
from typing import Optional
from urllib.parse import quote

from . import iface, s7dcl
from .compare import _other_texts_differ
from .diff import out_of_order
from .page import ADDED_OR_REMOVED, NET_NOT_SHOWN, NOT_SHOWN, ORDER, _folders
from .simaticml import _kid, _kids, _local, _mltext, _plain, _text
from .source import RENAMED_BLOCK_MIN, UNREADABLE, plc_device, stem

TABLE = 'SW.Tags.PlcTagTable'
TAG, CONSTANT = 'tag', 'constant'
KINDS = {'SW.Tags.PlcTag': TAG, 'SW.Tags.PlcUserConstant': CONSTANT}
BOXES = (('ExternalAccessible', 'accessible'), ('ExternalWritable', 'writable'), ('ExternalVisible', 'visible'))
WHERE = {TAG: ('LogicalAddress', 'address'), CONSTANT: ('Value', 'value')}
READ = {TAG: {'Name', 'DataTypeName', 'LogicalAddress'} | {b[0] for b in BOXES},
        CONSTANT: {'Name', 'DataTypeName', 'Value'}}
KIND_TEXT = 'PLC tag table'
LISTS = ((TAG, 'PLC tags', 'tag'), (CONSTANT, 'User constants', 'constant'))


@dataclass
class Entry:
    """A tag or user constant as the report reads it."""
    kind: str
    name: str
    type: str
    where: str                  # a tag's address, a constant's value
    boxes: tuple                # accessible, writable, visible
    comment: str
    unread: tuple               # what is left of its part of the file
    others: tuple               # its texts in the other languages
    parts: tuple                # its part of the file but the columns' attributes, every language


@dataclass
class Table:
    path: str
    name: str
    entries: list
    rest: list                  # what is left of the file without its name and entries
    text: str                   # the file; an error's text when it does not decode
    unreadable: bool = False


def _unread(plain, read, listed):
    """What the report leaves of an element (simaticml._plain): without the attributes `read`, the objects listed(object)
    says, and the lists that leaves empty."""
    kids = []
    for k in plain[3]:
        if k[0] == 'AttributeList':
            k = k[:3] + ([x for x in k[3] if x[0] not in read],)
        elif k[0] == 'ObjectList':
            k = k[:3] + ([x for x in k[3] if not listed(x)],)
        else:
            kids.append(k)
            continue
        if k[3]:
            kids.append(k)
    return plain[:3] + (kids,)


def _is_comment(obj):
    return obj[0] == 'MultilingualText' and ('CompositionName', 'Comment') in obj[1]


def _is_empty_comment(obj):
    """A comment with no text in any language, as TIA writes it: as none at all."""
    return _is_comment(obj) and not any(k[3] for k in obj[3])


def _other_texts(el, lang):
    """(language, text) of an element's texts in the languages other than lang, sorted."""
    items = (_kid(item, 'AttributeList') for item in el.iter() if _local(item.tag) == 'MultilingualTextItem')
    return tuple(sorted((_text(al, 'Culture'), _text(al, 'Text')) for al in items
                        if _text(al, 'Culture') != lang and _text(al, 'Text')))


def _entry(el, kind, lang):
    al = _kid(el, 'AttributeList')
    return Entry(kind, _text(al, 'Name'), _text(al, 'DataTypeName'), _text(al, WHERE[kind][0]),
                 tuple(_text(al, b[0], 'true').lower() != 'false' for b in BOXES), _mltext(el, 'Comment', lang),
                 _unread(_plain(el, lang=lang), READ[kind], _is_comment), _other_texts(el, lang),
                 _unread(_plain(el), READ[kind], _is_empty_comment))


def read_table(path, text):
    """The Table of an export's text; raises on a file that holds none or that it cannot read."""
    lang = s7dcl.LANG
    root = ET.fromstring(text.lstrip('\ufeff').encode('utf-8'))
    el = next((c for c in root if _local(c.tag) == TABLE), None)
    if el is None:
        raise ValueError('no PLC tag table in it')
    entries = [_entry(c, KINDS[_local(c.tag)], lang) for ol in _kids(el, 'ObjectList') for c in ol
               if _local(c.tag) in KINDS]
    rest = [_unread(k, {'Name'}, lambda obj: obj[0] in KINDS) if k[0] == TABLE else k for k in _plain(root, lang=lang)[3]]
    return Table(path, _text(_kid(el, 'AttributeList'), 'Name') or stem(path).rsplit('/', 1)[-1], entries, rest, text)


@dataclass
class Row:
    b: Optional[Entry]
    a: Optional[Entry]
    changes: set = field(default_factory=set)    # 'name', 'type', 'address' / 'value', the boxes, 'comment', 'order', 'unread'
    order: Optional[tuple] = None                # (was, now): 'first' or 'after <name>'
    moved_to: str = ''                           # the table a removed tag went to
    moved_from: str = ''                         # the table an added tag came from

    @property
    def m(self):
        return self.a or self.b

    @property
    def state(self):
        if self.b is None:
            return 'added'
        if self.a is None:
            return 'removed'
        if self.changes == {'order'}:
            return 'moved'
        return 'changed' if self.changes else 'same'


def _untold(r):
    """A paired row whose file differs in what its cells do not tell: its other languages, or else anything while the
    comment column shows no change. A comment edited in the report's language, its translations kept, is told."""
    if r.b is None or r.a is None:
        return False
    return r.b.others != r.a.others or (r.b.parts != r.a.parts and 'comment' not in r.changes)


def _changes(b, a):
    out = {f for f, x, y in (('name', b.name, a.name), ('type', b.type, a.type), (WHERE[a.kind][1], b.where, a.where),
                             ('comment', b.comment, a.comment), ('unread', b.unread, a.unread)) if x != y}
    return out | {box[1] for box, x, y in zip(BOXES, b.boxes, a.boxes) if x != y}


def _renamed(bs, as_, kind):
    """{index in bs: index in as_} of the entries left on both sides that are one renamed: the same address, or the same
    type and value of a constant, unique among them."""
    def key(e):
        return e.where if kind == TAG else (e.type, e.where)

    def once(entries):
        seen = {}
        for k, e in entries:
            if e.where:
                seen.setdefault(key(e), []).append(k)
        return {w: ks[0] for w, ks in seen.items() if len(ks) == 1}
    ob, oa = once(bs), once(as_)
    return {ob[w]: oa[w] for w in ob if w in oa}


def _place(names, k):
    return 'first' if not k else 'after %s' % names[k - 1]


def _rows(bs, as_, kind):
    """The rows of one kind in the order of the after version, a removed entry after its former predecessor."""
    free = {}
    for j, a in enumerate(as_):
        free.setdefault(a.name, []).append(j)
    pairs = {i: free[b.name].pop(0) for i, b in enumerate(bs) if free.get(b.name)}
    used = set(pairs.values())
    pairs.update(_renamed([(i, b) for i, b in enumerate(bs) if i not in pairs],
                          [(j, a) for j, a in enumerate(as_) if j not in used], kind))
    of_a = {j: i for i, j in pairs.items()}
    rows = [Row(bs[of_a[j]] if j in of_a else None, a) for j, a in enumerate(as_)]
    for r in rows:
        if r.b is not None:
            r.changes = _changes(r.b, r.a)
    kept = [(of_a[j], j) for j in range(len(as_)) if j in of_a]
    names_b, names_a = [b.name for b in bs], [a.name for a in as_]
    for (i, j), out in zip(kept, out_of_order([i for i, _ in kept])):
        if out:
            rows[j].changes.add('order')
            rows[j].order = (_place(names_b, i), _place(names_a, j))
    following, last = {}, None                   # {index of a row kept, None for the top: the removed rows after it}
    for i, b in enumerate(bs):
        if i in pairs:
            last = pairs[i]
        else:
            following.setdefault(last, []).append(Row(b, None))
    merged = list(following.get(None, ()))
    for j, r in enumerate(rows):
        merged += [r] + following.get(j, [])
    return merged


@dataclass
class TableDiff:
    before: Optional[Table]
    after: Optional[Table]
    rows: list
    not_shown: bool = False
    key: str = ''

    @property
    def path_b(self):
        return self.before.path if self.before else None

    @property
    def path_a(self):
        return self.after.path if self.after else None

    @property
    def device(self):
        return plc_device(self.path_a or self.path_b)

    @property
    def was(self):
        b, a = self.before, self.after
        return b.name if b and a and b.name != a.name else None

    @property
    def name(self):
        return (self.after or self.before).name

    @property
    def other_path(self):
        """The table is in another file than before."""
        return bool(self.path_b and self.path_a and self.path_b != self.path_a)

    @property
    def state(self):
        if not self.before:
            return 'new'
        if not self.after:
            return 'deleted'
        if self.was or self.not_shown or any(r.state != 'same' for r in self.rows):
            return 'changed'
        return 'moved' if self.path_b != self.path_a else 'same'

    def counts(self):
        out = {}
        for r in self.rows:
            if r.state != 'same':
                out[r.state] = out.get(r.state, 0) + 1
        return out


def _common(b, a):
    nb, na = {e.name for e in b.entries}, {e.name for e in a.entries}
    return 2.0 * len(nb & na) / (len(nb) + len(na)) if nb and na else 0.0


def _pair_tables(tb, ta):
    """[(Table | None, Table | None)]: by path, by name within a PLC, by tags in common within a PLC, best first."""
    out = [(tb.pop(p), ta.pop(p)) for p in [p for p in tb if p in ta]]
    for b in list(tb.values()):
        a = next((a for a in ta.values() if (a.name, plc_device(a.path)) == (b.name, plc_device(b.path))), None)
        if a is not None:
            out.append((tb.pop(b.path), ta.pop(a.path)))
    alike = sorted(((_common(b, a), b.path, a.path) for b in tb.values() for a in ta.values()
                    if plc_device(a.path) == plc_device(b.path)), key=lambda x: (-x[0], x[1], x[2]))
    for s, pb, pa in alike:
        if s >= RENAMED_BLOCK_MIN and pb in tb and pa in ta:
            out.append((tb.pop(pb), ta.pop(pa)))
    return out + [(b, None) for b in tb.values()] + [(None, a) for a in ta.values()]


def _read_side(snap):
    """({path: Table} of a snapshot, {path that cannot be read: a lock}). A file that does not read is in the
    snapshot's skipped; one that does not parse or decode an unreadable Table."""
    out, locked = {}, set()
    for p in snap.tag_tables():
        text = None
        try:
            text = snap.read(p)
            out[p] = read_table(p, text)
        except Exception as ex:                                  # noqa: BLE001 - any error of this file, as a block's
            snap.skipped.append((p, '%s: %s' % (UNREADABLE, ex)))
            if isinstance(ex, OSError):
                locked.add(p)
                continue
            if text is None:                                     # bytes that do not decode: they differ as the errors do
                text = str(ex)
            out[p] = Table(p, stem(p).rsplit('/', 1)[-1], [], [], text, True)
    return out, locked


def _mark_moved_tags(diffs):
    """A tag or constant removed from one table and added to another of its PLC under one name: told on both rows."""
    gone, came = {}, {}
    for d in diffs:
        for r in d.rows:
            if r.state in ('removed', 'added'):
                (gone if r.state == 'removed' else came).setdefault((d.device, r.m.kind, r.m.name), []).append((r, d))
    for key, rows in gone.items():
        there = came.get(key, ())
        if len(rows) == 1 and len(there) == 1:
            (r, d), (r2, d2) = rows[0], there[0]
            r.moved_to, r2.moved_from = d2.name, d.name


def compare(before, after):
    """[TableDiff] of every table of the two snapshots, the same ones too, but of a path locked on a side."""
    out = []
    (tb, lb), (ta, la) = _read_side(before), _read_side(after)
    for p in lb | la:                                            # named in skipped
        tb.pop(p, None)
        ta.pop(p, None)
    for b, a in _pair_tables(tb, ta):
        if (b and b.unreadable) or (a and a.unreadable):         # the same broken file twice: nothing changed
            out.append(TableDiff(b, a, [], not (b and a and b.text == a.text)))
            continue
        rows = []
        for kind in (TAG, CONSTANT):
            rows += _rows([e for e in (b.entries if b else ()) if e.kind == kind],
                          [e for e in (a.entries if a else ()) if e.kind == kind], kind)
        not_shown = bool(b and a) and (b.rest != a.rest or any('unread' in r.changes or _untold(r) for r in rows)
                                       or _other_texts_differ(SimpleNamespace(xml=b.text), SimpleNamespace(xml=a.text)))
        out.append(TableDiff(b, a, rows, not_shown))
    _mark_moved_tags(out)
    return out


# ---------------------------------------------------------------- the page: the look of a block's interface table

ROW_CLASS = {'added': 'ins', 'removed': 'del', 'changed': 'chg', 'moved': 'mov', 'same': ''}


def _notes(r):
    """What no column says of a row."""
    out = []
    if r.order:
        out.append('order: was %s, now %s' % r.order)
    if r.moved_to:
        out.append('moved to table %s' % r.moved_to)
    if r.moved_from:
        out.append('moved from table %s' % r.moved_from)
    if 'unread' in r.changes:
        out.append(NET_NOT_SHOWN)
    return out


def _row_html(r, ctx=''):
    cls = ' '.join(x for x in (ROW_CLASS[r.state], ctx) if x)
    m = r.m
    name = iface._both(escape(r.b.name), escape(r.a.name)) if 'name' in r.changes else escape(m.name)
    notes = ''.join('<div class="ex">%s</div>' % escape(x) for x in _notes(r))
    cells = ['<td class="tn"><span>%s</span>%s</td>' % (name, notes),          # a removed name struck through, not its notes
             '<td>%s</td>' % iface._cell(r, lambda e: escape(e.type, False), 'type' in r.changes),
             '<td>%s</td>' % iface._cell(r, lambda e: escape(e.where, False), WHERE[m.kind][1] in r.changes)]
    if m.kind == TAG:
        for k, box in enumerate(BOXES):
            cells.append(iface._td(iface._cell(r, lambda e, k=k: iface._box(e.boxes[k], k > 0 and not e.boxes[0]),
                                               box[1] in r.changes), k > 0 and not m.boxes[0], 'c'))
    cells.append('<td>%s</td>' % iface._cell(r, lambda e: escape(e.comment, False), 'comment' in r.changes))
    return '<tr%s>%s</tr>' % (' class="%s"' % cls if cls else '', ''.join(cells))


def _skip(n, ncols, word):
    return ('<tr class="skip"><td colspan="%d">⋯ %d unchanged %s%s<span class="hint"> (click to show all)</span></td></tr>'
            % (ncols, n, word, '' if n == 1 else 's'))


def _list_html(rows, title, word, kind, full):
    """A list of the table as TIA's editor has it, the changed rows, the unchanged ones folded in place (full: shown)."""
    if not rows or not (full or any(r.state != 'same' for r in rows)):
        return ''
    heads = ['Name', 'Data type', WHERE[kind][1].capitalize()]
    heads = ['<td>%s</td>' % h for h in heads]
    if kind == TAG:
        heads += ['<td class="c">%s</td>' % h for h in iface.ATTR_HEADS[:3]]
    heads.append('<td>Comment</td>')
    body, k = ['<tr class="hd">%s</tr>' % ''.join(heads)], 0
    while k < len(rows):
        if rows[k].state != 'same' or full:
            body.append(_row_html(rows[k]))
            k += 1
            continue
        j = k
        while j < len(rows) and rows[j].state == 'same':
            j += 1
        body.append(_skip(j - k, len(heads), word))
        body += [_row_html(x, 'ctx') for x in rows[k:j]]
        k = j
    return ('<div class="nw itfw"><div class="nwh"><b>%s</b></div><table class="itf">%s</table></div>'
            % (title, ''.join(body)))


def _facts(e):
    if e is None:
        return None
    out = {'type': e.type, WHERE[e.kind][1]: e.where, 'comment': e.comment}
    if e.kind == TAG:
        out.update((box[1], on) for box, on in zip(BOXES, e.boxes))
    return out


def _change_text(r):
    """What changed of a row, for the list: a moved address, a data type, ..."""
    b, a = r.b, r.a
    out = []
    if 'type' in r.changes:
        out.append('data type %s -> %s' % (b.type, a.type))
    field_ = WHERE[r.m.kind][1]
    if field_ in r.changes:
        out.append('%s %s -> %s' % (field_, b.where or '-', a.where or '-'))
    return out + [c for c in sorted(r.changes) if c in ('comment', 'accessible', 'writable', 'visible')] + _notes(r)


class Item:
    """A table on the page: its tree entry and section, as hmi.Item."""

    def __init__(self, d, multi, all_, draw_added_removed):
        self.d, self.multi = d, multi
        self.name = d.name
        self.state = d.state
        self.key = d.key
        self.folders = _folders(d.path_a or d.path_b)[0]
        self.order = ORDER
        self.opened = all_ or draw_added_removed or d.state not in ADDED_OR_REMOVED
        self.full = all_ or (draw_added_removed and d.state in ADDED_OR_REMOVED)

    def shown(self):
        """The rows the page shows: all of them or the changed ones, of a table only listed those moved between tables."""
        if not self.opened:
            return [r for r in self.d.rows if r.moved_to or r.moved_from]
        return [r for r in self.d.rows if self.full or r.state != 'same']

    def title(self):
        d = self.d
        return '%s → %s' % (d.was, d.name) if d.was else d.name

    def li(self, i):
        d = self.d
        return ('<li><a class="obj %s" href="#%s" data-i="%d" data-key="%s" title="%s"><span class="mk"></span>'
                '<span class="nm">%s</span><span class="k">[%s]%s</span></a></li>'
                % (self.state, quote(self.key, safe=''), i, escape(self.key),
                   escape('%s: %s%s' % (d.path_a or d.path_b, self.state, '; ' + NOT_SHOWN if d.not_shown else '')),
                   escape(self.name), KIND_TEXT, ' not shown' if d.not_shown else ''))

    def section(self):
        d = self.d
        pb, pa = d.path_b, d.path_a
        head = ('<div class="bh" id="blk-%s"><b>%s [%s]</b>%s%s%s<span class="paths">%s</span></div>'
                % (escape(self.key), escape(self.title()), KIND_TEXT,
                   ' <span class="k">%s</span>' % escape(d.device) if self.multi and d.device else '',
                   '<span class="nsh">%s</span>' % NOT_SHOWN if d.not_shown else '',
                   '' if self.state == 'changed' else '<span class="st %s">%s</span>' % (self.state, self.state),
                   escape(pa or pb if pb == pa or not (pa and pb) else '%s → %s' % (pb, pa))))
        rows = d.rows if self.opened else self.shown()
        lists = ''.join(_list_html([r for r in rows if r.m.kind == kind], title, word, kind, self.full)
                        for kind, title, word in LISTS)
        return '<section class="blk ptag">%s%s</section>' % (head, lists)


class PlcTagPart:
    """The tag tables on the page, in tree order: all_ also the unchanged ones and all their rows; a new table is drawn
    with its rows as added, a deleted one with them as removed; draw_added_removed False: each listed by its heading
    (drawn with all_)."""

    def __init__(self, diffs, all_=False, draw_added_removed=True):
        diffs = [d for d in diffs if d.state != 'same' or all_]
        multi = len({d.device for d in diffs}) > 1
        seen, self.items = {}, []
        for d in diffs:
            base = '%s:plctags:%s' % (d.device, d.name) if multi and d.device else 'plctags:%s' % d.name
            seen[base] = seen.get(base, 0) + 1
            d.key = base if seen[base] == 1 else '%s~%d' % (base, seen[base])
            self.items.append(Item(d, multi, all_, draw_added_removed))
        self.items.sort(key=lambda it: [(0, f.casefold()) for f in it.folders] + [(1, it.name.casefold())])   # the tree's

    def __len__(self):
        return len(self.items)

    def sections_html(self):
        return ''.join(it.section() for it in self.items)

    def summary_html(self):
        devices = any(it.d.device for it in self.items)
        rows = ''.join('<tr><td><a href="#blk-%s">%s</a></td>%s<td>%s</td><td>%s</td></tr>'
                       % (escape(quote(it.key, safe='')), escape(it.title()),
                          '<td>%s</td>' % escape(it.d.device or '') if devices else '', it.state,
                          ', '.join('%d %s' % (n, s) for s, n in sorted(it.d.counts().items()))
                          or ('not shown' if it.d.not_shown else ''))
                       for it in self.items)
        return ('<table class="sum psum"><tr><th>PLC tag table</th>%s<th>State</th><th>Tags and constants</th></tr>%s</table>'
                % ('<th>Device</th>' if devices else '', rows))

    def json(self):
        return [{'name': it.name, 'state': it.state, 'counts': it.d.counts(),
                 **({'device': it.d.device} if it.d.device else {}),
                 **({'was': it.d.was} if it.d.was else {}),
                 **({'movedFrom': it.d.path_b, 'movedTo': it.d.path_a} if it.d.other_path else {}),
                 **({'notShown': True} if it.d.not_shown else {}),
                 'rows': [{'kind': r.m.kind, 'name': r.m.name, 'state': r.state, 'changes': sorted(r.changes),
                           **({'was': r.b.name} if 'name' in r.changes else {}),
                           **({'order': dict(zip(('before', 'after'), r.order))} if r.order else {}),
                           **({'movedTo': r.moved_to} if r.moved_to else {}),
                           **({'movedFrom': r.moved_from} if r.moved_from else {}),
                           'before': _facts(r.b), 'after': _facts(r.a)} for r in it.shown()]}
                for it in self.items]

    def lines(self):
        out = []
        for it in self.items:
            d = it.d
            out.append('%-8s %-11s %s%s%s%s' % (it.state, 'plctagtable', '%s/%s' % (d.device, it.name) if it.multi and d.device
                                                else it.name, '  (was "%s")' % d.was if d.was else '',
                                                '  (from %s to %s)' % (d.path_b, d.path_a) if d.other_path else '',
                                                '  (%s)' % NOT_SHOWN if d.not_shown else ''))
            for r in it.shown():
                told = _change_text(r)
                out.append('    %-8s %-8s %s%s%s' % (r.state, r.m.kind, r.m.name,
                                                     '  (was "%s")' % r.b.name if 'name' in r.changes else '',
                                                     '  (%s)' % ', '.join(told) if told else ''))
        return out
