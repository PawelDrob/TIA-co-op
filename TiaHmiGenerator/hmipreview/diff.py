"""Object-level diff of two SimaticML documents, matched by ObjectName.

  diff_trees(old, new)            -> [Change]  old / new are <Document> elements (old None: everything is added)
  base_tree(repo, doc, against)   -> (<Document> or None, base description)  'commit': the document at git HEAD
                                     (generated against generated, an export against the export); 'export': the
                                     TIA export of the same kind and name (an export is its own base)
  compare(repo_path, kind, name, against) -> dict  the answer of /api/diff and of the CLI
  states(repo, against)           -> {(kind, name): 'new' | 'changed' | 'same'}  every effective document of the
                                     repo's device, the change report's marks of the preview's project tree

A change per screen item (groups included) whose ObjectName is only in one document (added / removed) or whose
content differs: 'moved' when its bounding box changed (Left / Top / Width / Height, line ends, points, radius),
else 'changed'. An added one holds what it is tied to, for the change report: its Mode, its links, its parts other
than texts and fonts (Properties with their tags, Events, Animations, ...) and a text that holds a tag or list field;
lines() gives it one line. Each other change lists the changed attributes, texts (per culture, a tag or list field
inside one in its words: rules.text.told_lines), links (LinkList) and other parts (compositions such as Events,
Animations, Font, compared without IDs). A polyline's or polygon's Points are the attribute 'Points' when they differ
by more than the box says (a shape moved whole has only its new position), old and new as '10, 20; 30, 40', 'points'
naming those on one side only for the drawing; a Line's start and end are the attribute 'Ends', in the same form, when
it runs another way (mirrored or its ends swapped), which its box does not say. Left, Top, Width or Height that
differ where the box does not follow them (it comes from a Line's ends, or there is none) are attributes of their own;
another Radius always is, as a box of Width and Height does not follow it. Another type under the same name is the
first attribute, 'Object type' (TYPE_ROW), with both types' short names. Attributes of the root object (BackColor of
the screen, ...) are one change with object None, with a layer's Name and VisibleES as 'Layer <Index> <attribute>', and
the attribute 'Layers' (their Index values) when the two documents do not hold the same layers; an item put on another
layer has the attribute 'Layer' (its Index). IDs are not compared.

An item that stands directly in another group, or leaves or enters one, has the attribute 'Group' (the group's name,
None for none), and a group whose items are others, an added or removed one too, the attribute 'Members' (their names
in order). A change of a group has as its box the one around its members, for the drawing.

Attribute 'layerOrder' is an item's position, counted from 1, in the document's list of the items of its layer or
group: the order in the export; what it means on TIA's screen: the guide, section 4. Most items whose position
differs were only shifted by another, so the row goes only where items that stand together in both documents, whatever
their layer or group is called there, changed sides: on those whose position differs with the most such pairs, ties
all of them, until no pair is left untold. Two that swap both have a row, as the file does not say which one moved, so
one step past a neighbour reads as a swap; one that alone passed two or more others has the only row. An item whose
position is the same has no row, as a row would read as
no change: with items new or gone in the same list, the one that moved can be such an item, and those it passed have the
rows.
"""
import collections
import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .geometry import Box, GROUP, LINE, LINE_ENDS, box_of, line_ends, points_of
from .gitenv import NO_WINDOW, git_env
from .model import GENERATED, attribute
from .rules.text import told_lines

AGAINST = ('commit', 'export')
GEOMETRY = {'Left', 'Top', 'Width', 'Height', 'StartLeft', 'StartTop', 'EndLeft', 'EndTop', 'Points'}
BOX_VALUES = {'Left': 'x', 'Top': 'y', 'Width': 'w', 'Height': 'h'}
TEXT_PARTS = ('MultilingualText',)
GROUP_ROWS = {'Group', 'Members'}     # no attributes of an export: one side empty is no export difference
TYPE_ROW = 'Object type'     # with its space: 'Type' is an attribute of its own
FONT_PARTS = ('Hmi.Globalization.MultiLingualFont',)
ADDED_ATTRIBUTES = ('Mode',)     # input or output of a field, which no drawing shows; told on every kind that has it


@dataclass
class Change:
    object: str | None        # ObjectName; None for the root object (the screen itself)
    type: str                 # element tag without 'Hmi.Screen.' (Rectangle, Button, Screen, ...)
    kind: str                 # 'added' | 'removed' | 'moved' | 'changed'
    old: dict | None = None   # {x, y, w, h} before (None for added or without geometry)
    new: dict | None = None   # {x, y, w, h} after (None for removed or without geometry)
    attributes: list = field(default_factory=list)   # [{name, old, new}] (None = absent)
    texts: list = field(default_factory=list)        # [{part, culture, old, new}] (None = absent)
    links: list = field(default_factory=list)        # [{kind, old, new}] link target names (None = absent)
    parts: list = field(default_factory=list)        # composition names whose content changed (Events, ...)
    name: str | None = None   # root object only: the document's Name

    def to_dict(self):
        return {'object': self.object, 'type': self.type, 'kind': self.kind, 'old': self.old, 'new': self.new,
                'attributes': self.attributes, 'texts': self.texts, 'links': self.links, 'parts': self.parts}

    @property
    def who(self):
        """How a line names the item: its type and object name, or for the root object its type and Name."""
        return '%s %s' % (self.type, self.object if self.object is not None else self.name)

    def lines(self):
        """The change in words, one line per item: 'Button btnStart: TextOff 'Start' -> 'Run''; an added item has one
        line."""
        if self.kind == 'added':
            return self.lines_without_parts()[:1]
        return self.lines_without_parts() + ['%s: %s changed' % (self.who, p) for p in self.parts]

    def lines_without_parts(self):
        """The lines without those of the parts, which the change report spells out fact by fact."""
        who = self.who
        out = []
        if self.kind == 'added':
            out.append('%s: added%s' % (who, ' at ' + _rect(self.new) if self.new else ''))
        if self.kind == 'removed':
            out.append('%s: removed%s' % (who, ' from ' + _rect(self.old) if self.old else ''))
            return out
        if self.kind == 'moved':
            out.append('%s: moved %s -> %s' % (who, _rect(self.old), _rect(self.new)))
        for a in self.attributes:
            out.append('%s: %s %s -> %s' % (who, a['name'], _q(a['old']), _q(a['new'])))
        for t in self.texts:     # the culture is named when the text has more than one
            label = t['part'] + (' [%s]' % t['culture'] if t.get('cultures', 1) > 1 else '')
            out.append('%s: %s %s -> %s' % (who, label, _q(t['old']), _q(t['new'])))
        for l in self.links:
            out.append('%s: %s link %s -> %s' % (who, l['kind'], _q(l['old']), _q(l['new'])))
        return out


def _num(v):
    return int(v) if float(v).is_integer() else v


def _rect(r):
    return '(%s, %s) %sx%s' % (r['x'], r['y'], r['w'], r['h']) if r else '(no box)'


def _q(v):
    if v is None:
        return '(none)'
    return "'%s'" % v.replace('\n', '\\n')


def _box_values(b):
    return {'x': _num(b.x), 'y': _num(b.y), 'w': _num(b.w), 'h': _num(b.h)}


def _box(elem):
    b = box_of(elem)
    return None if b is None else _box_values(b)


def _short(tag):
    return tag.split('.')[-1]


def _root(tree):
    return next((c for c in tree if 'ID' in c.attrib), None) if tree is not None else None


def screen_items(root):
    """{ObjectName: element} of every screen item below root, groups and group members included (first wins)."""
    out = {}
    if root is None:
        return out
    for e in root.iter():
        if e.get('CompositionName') == 'ScreenItems':
            n = attribute(e, 'ObjectName')
            if n and n not in out:
                out[n] = e
    return out


def _attributes(elem):
    al = elem.find('AttributeList')
    if al is None:
        return {}
    return {c.tag: _canon(c) if len(c) else (c.text or '') for c in al}


def _canon(elem, drop_ids=True):
    """Canonical text of a subtree: tag, attributes without ID, text, children in order."""
    attrs = sorted((k, v) for k, v in elem.attrib.items() if not (drop_ids and k == 'ID'))
    text = (elem.text or '').strip()
    tail = ''.join(_canon(c) + (c.tail or '').strip() for c in elem)
    return '<%s%s>%s%s</>' % (elem.tag, ''.join(' %s=%r' % kv for kv in attrs), text, tail)


def _links(elem):
    ll = elem.find('LinkList')
    out = {}
    if ll is None:
        return out
    for c in ll:
        name = c.findtext('Name')
        out.setdefault(c.tag, name if name is not None else c.get('TargetID') or '')
    return out


def _own_parts(elem):
    """{CompositionName: [child]} of the item's ObjectList, without screen items (they are items of their own)."""
    ol = elem.find('ObjectList')
    out = {}
    if ol is None:
        return out
    for c in ol:
        comp = c.get('CompositionName') or c.tag
        if comp == 'ScreenItems' or c.tag == 'Hmi.Screen.ScreenLayer':
            continue
        out.setdefault(comp, []).append(c)
    return out


def _texts(children):
    """{culture: text} of MultilingualText children."""
    out = {}
    for mt in children:
        for it in mt.iter('MultilingualTextItem'):
            al = it.find('AttributeList')
            if al is None:
                continue
            t = al.find('Text')
            out[al.findtext('Culture') or ''] = '\n'.join(told_lines(t)) if t is not None else ''
    return out


def _points_text(pts):
    return '; '.join('%s, %s' % (_num(x), _num(y)) for x, y in pts)


def _only_in(pts, other):
    """The points of pts that other does not hold, as [x, y]."""
    return [[_num(x), _num(y)] for (x, y) in (collections.Counter(pts) - collections.Counter(other)).elements()]


def _points_change(old, new):
    """The attribute row of two Points values (None absent), None when they are the same points or the same shape
    moved whole: then the box says all of it. Values that hold no point are shown as they stand."""
    op, np_ = points_of(old), points_of(new)
    if op and np_:
        if op == np_ or (len(op) == len(np_) and len({(n[0] - o[0], n[1] - o[1]) for o, n in zip(op, np_)}) == 1):
            return None
    elif old == new:
        return None
    return {'name': 'Points', 'old': _points_text(op) if op else old, 'new': _points_text(np_) if np_ else new,
            'points': {'old': _only_in(op, np_), 'new': _only_in(np_, op)}}


def _way(ends):
    """Which way a line runs on each axis: -1, 0 or 1."""
    (sx, sy), (ex, ey) = ends
    return (ex > sx) - (ex < sx), (ey > sy) - (ey < sy)


def _ends_change(old, new):
    """The attribute row of a Line that runs another way, None otherwise: its box says its place and size, not which
    corner each end is at. Values that cannot be read are shown as they stand. Only a Line against a Line: another
    object under its name has no ends to compare."""
    if old.tag != LINE or new.tag != LINE:
        return None
    oe, ne = line_ends(old), line_ends(new)
    if oe and ne:
        if _way(oe) == _way(ne):
            return None
        return {'name': 'Ends', 'old': _points_text(oe), 'new': _points_text(ne),
                'points': {'old': _only_in(oe, ne), 'new': _only_in(ne, oe)}}
    written = ['%s, %s; %s, %s' % tuple(attribute(e, k, '') for k in LINE_ENDS) for e in (old, new)]
    return None if written[0] == written[1] else {'name': 'Ends', 'old': written[0], 'new': written[1]}


def _same_number(a, b):
    """Two values of an attribute, left out counting 0; values that cannot be read as they stand."""
    try:
        return float(a or 0) == float(b or 0)
    except ValueError:
        return a == b


def _unsaid_box_values(oa, na, ob, nb):
    """The attribute rows of Left, Top, Width, Height that differ where the boxes do not say it."""
    return [{'name': k, 'old': oa.get(k), 'new': na.get(k)} for k, part in BOX_VALUES.items()
            if not _same_number(oa.get(k), na.get(k)) and (ob == nb or (ob and nb and ob[part] == nb[part]))]


def _compared(old, new, ob, nb):
    """The boxes two sides are compared by: none when neither has one; else a Line with nothing written, which is drawn
    as not drawn, has its ends at 0."""
    if not (ob or nb):
        return None, None
    return tuple(box or ({'x': 0, 'y': 0, 'w': 0, 'h': 0} if elem.tag == LINE else None)
                 for elem, box in ((old, ob), (new, nb)))


def _compare(name, tag, old, new, root=False):
    oa, na = _attributes(old), _attributes(new)
    attrs = [{'name': k, 'old': oa.get(k), 'new': na.get(k)}
             for k in sorted(set(oa) | set(na)) if oa.get(k) != na.get(k) and k not in GEOMETRY | {'ObjectName'}]
    ob, nb = (None, None) if root else (_box(old), _box(new))
    compared = _compared(old, new, ob, nb)
    shapes = [_points_change(oa.get('Points'), na.get('Points')), _ends_change(old, new)]
    unsaid = _unsaid_box_values(oa, na, *compared)
    attrs = sorted(attrs + [a for a in shapes if a] + unsaid, key=lambda a: a['name'])
    if root:
        attrs = [{'name': k, 'old': oa.get(k), 'new': na.get(k)}
                 for k in sorted(set(oa) | set(na)) if oa.get(k) != na.get(k)]
    if old.tag != new.tag:
        attrs.insert(0, {'name': TYPE_ROW, 'old': _short(old.tag), 'new': _short(new.tag)})
    ol, nl = _links(old), _links(new)
    links = [{'kind': k, 'old': ol.get(k), 'new': nl.get(k)} for k in sorted(set(ol) | set(nl))
             if ol.get(k) != nl.get(k)]
    op, np_ = _own_parts(old), _own_parts(new)
    texts, parts = [], []
    for comp in sorted(set(op) | set(np_)):
        oc, nc = op.get(comp, []), np_.get(comp, [])
        if all(c.tag in TEXT_PARTS for c in oc + nc):
            ot, nt = _texts(oc), _texts(nc)
            n = len(set(ot) | set(nt))
            texts += [{'part': comp, 'culture': cu, 'old': ot.get(cu), 'new': nt.get(cu), 'cultures': n}
                      for cu in sorted(set(ot) | set(nt)) if ot.get(cu) != nt.get(cu)]
        elif [_canon(c) for c in oc] != [_canon(c) for c in nc]:
            parts.append(comp)
    moved = compared[0] != compared[1]
    if not (attrs or links or texts or parts or moved):
        return None
    ch = Change(name, _short(tag), 'moved' if moved else 'changed', ob, nb, attrs, texts, links, parts)
    return ch


def _added(name, elem, members_rows):
    """The change of an item only the new document holds: its box, what it is tied to, and members_rows, what a group
    holds (_members_rows)."""
    attrs = _attributes(elem)
    rows = members_rows + [{'name': k, 'old': None, 'new': attrs[k]} for k in ADDED_ATTRIBUTES if k in attrs]
    links = [{'kind': k, 'old': None, 'new': v} for k, v in sorted(_links(elem).items())]
    texts, parts = [], []
    for comp, children in sorted(_own_parts(elem).items()):
        if all(c.tag in TEXT_PARTS for c in children):
            if any(c.find('.//fieldinfo') is not None for c in children):       # a field: a tag or a list
                told = _texts(children)
                texts += [{'part': comp, 'culture': cu, 'old': None, 'new': t, 'cultures': len(told)}
                          for cu, t in sorted(told.items())]
        elif not all(c.tag in FONT_PARTS for c in children):
            parts.append(comp)
    return Change(name, _short(elem.tag), 'added', None, _box(elem), rows, texts, links, parts)


def _layers(root):
    """({layer Index: {Name, VisibleES}}, {ObjectName: layer Index}) of the layers of root and their items."""
    layers, of = {}, {}
    ol = root.find('ObjectList') if root is not None else None
    for l in ol if ol is not None else []:
        if l.get('CompositionName') != 'Layers':
            continue
        idx = attribute(l, 'Index', '')
        layers[idx] = {k: attribute(l, k) for k in ('Name', 'VisibleES')}
        for n in screen_items(l):
            of.setdefault(n, idx)
    return layers, of


def _places(root):
    """{place: {ObjectName: position in its list, from 1}} of the items that stand side by side, in order; a place is a
    layer ('layer', Index), a group (its ObjectName) or None (the root, without layers)."""
    out = {}
    for e in root.iter() if root is not None else ():
        items = e.findall("ObjectList/*[@CompositionName='ScreenItems']")
        if items:
            place = ('layer', attribute(e, 'Index', '')) if e.get('CompositionName') == 'Layers' else (
                attribute(e, 'ObjectName'))
            positions = out.setdefault(place, {})
            for position, item in enumerate(items, 1):
                n = attribute(item, 'ObjectName')
                if n:
                    positions.setdefault(n, position)
    return out


def _told_of(changed_sides):
    """The names of changed_sides ({name: names it changed sides with}) that tell every pair: those with the most pairs,
    ties all of them, until none is left."""
    rest = {n: set(others) for n, others in changed_sides.items()}
    told = set()
    while any(rest.values()):
        most = max(len(v) for v in rest.values())
        told |= {n for n, v in rest.items() if len(v) == most}
        rest = {n: v - told for n, v in rest.items() if n not in told}
    return told


def _order_rows(was, now):
    """{name: attribute row 'layerOrder'} of the positions in two lists of the same items. An item whose position is the
    same has no row; two that changed sides cannot both be such an item, so every pair stays told."""
    changed_sides = {n: [m for m in was if (was[m] < was[n]) != (now[m] < now[n])] for n in was if was[n] != now[n]}
    return {n: {'name': 'layerOrder', 'old': str(was[n]), 'new': str(now[n])} for n in _told_of(changed_sides)}


def _order_changes(old_places, new_places):
    """{name: attribute row 'layerOrder'} of the items of two _places: those of one place in old that share a place in
    new."""
    now_in = {n: place for place, positions in new_places.items() for n in positions}
    out = {}
    for was in old_places.values():
        by_place = collections.defaultdict(list)
        for n in was:
            if n in now_in:
                by_place[now_in[n]].append(n)
        for place, together in by_place.items():
            out.update(_order_rows({n: was[n] for n in together}, {n: new_places[place][n] for n in together}))
    return out


def _group_of(places):
    """{name: the group it stands in directly} of the items of _places that stand in one."""
    return {n: place for place, positions in places.items() if isinstance(place, str) for n in positions}


def _members_rows(was, now):
    """The attribute row 'Members' of a group's two lists (positions of _places), when they do not hold the same items:
    a new order alone is told by 'layerOrder'."""
    if was.keys() == now.keys():
        return []
    return [{'name': 'Members', 'old': ', '.join(was) or None, 'new': ', '.join(now) or None}]


def _outline(elem):
    """The box a change of a group is drawn with: it has none of its own, so the one around its members; None when no
    member has one, or for no element. A plain object, which stood or stands as a group of its name, has its own box."""
    boxes = [b for b in map(box_of, screen_items(elem).values()) if b is not None]
    if not boxes:
        return None
    x, y = min(b.x for b in boxes), min(b.y for b in boxes)
    return _box_values(Box(x, y, max(b.right for b in boxes) - x, max(b.bottom for b in boxes) - y))


def diff_trees(old, new):
    """Changes from document old to document new (<Document> elements; old None = empty document)."""
    oroot, nroot = _root(old), _root(new)
    (olay, oof), (nlay, nof) = _layers(oroot), _layers(nroot)
    changes = []
    if oroot is not None and nroot is not None:
        c = _compare(None, nroot.tag, oroot, nroot, root=True)
        lay = [{'name': 'Layer %s %s' % (i, k), 'old': olay[i][k], 'new': nlay[i][k]}
               for i in sorted(set(olay) & set(nlay), key=_layer_key) for k in ('Name', 'VisibleES')
               if olay[i][k] != nlay[i][k]]
        if set(olay) != set(nlay):
            lay.append({'name': 'Layers', 'old': _index_list(olay), 'new': _index_list(nlay)})
        if lay:
            c = c or Change(None, _short(nroot.tag), 'changed')
            c.attributes += lay
        if c is not None:
            c.kind = 'changed'
            c.name = attribute(nroot, 'Name')
            changes.append(c)
    oi, ni = screen_items(oroot), screen_items(nroot)
    old_places, new_places = _places(oroot), _places(nroot)
    orders = _order_changes(old_places, new_places)
    ogroup, ngroup = _group_of(old_places), _group_of(new_places)
    for n, e in ni.items():
        members_rows = _members_rows(old_places.get(n, {}), new_places.get(n, {}))
        if n not in oi:
            changes.append(_added(n, e, members_rows))
            continue
        c = _compare(n, e.tag, oi[n], e)
        place_rows = [{'name': 'Layer', 'old': oof.get(n), 'new': nof.get(n)}] if oof.get(n) != nof.get(n) else []
        if ogroup.get(n) != ngroup.get(n):
            place_rows.append({'name': 'Group', 'old': ogroup.get(n), 'new': ngroup.get(n)})
        if n in orders:
            place_rows.append(orders[n])
        place_rows += members_rows
        if place_rows:
            c = c or Change(n, _short(e.tag), 'changed', _box(oi[n]), _box(e))
            c.attributes += place_rows
        if c is not None:
            changes.append(c)
    for n, e in oi.items():
        if n not in ni:
            changes.append(Change(n, _short(e.tag), 'removed', _box(e), None,
                                  _members_rows(old_places.get(n, {}), {})))
    for c in changes:
        for t in c.texts:
            t.setdefault('cultures', 1)
        sides = oi.get(c.object), ni.get(c.object)
        if any(e is not None and e.tag == GROUP for e in sides):
            c.old, c.new = map(_outline, sides)
            if c.kind == 'moved' and c.old == c.new:     # _compare had a group's box as none
                c.kind = 'changed'
    return changes


def _layer_key(i):
    return (0, int(i)) if i.isdigit() else (1, i)


def _index_list(layers):
    return ', '.join(sorted(layers, key=_layer_key)) or None


def _git_show(repo_path, rel):
    """The bytes of rel at HEAD, or None when HEAD or the file at HEAD does not exist."""
    try:
        r = subprocess.run(['git', '-C', repo_path, 'show', 'HEAD:' + rel], capture_output=True, env=git_env(),
                           creationflags=NO_WINDOW)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def base_tree(repo, doc, against):
    """(<Document> element or None, {'against', 'path', 'ref'}) of the base doc is compared with."""
    if against == 'commit':
        data = _git_show(repo.path, doc.path)
        info = {'against': 'commit', 'path': doc.path if data is not None else None,
                'ref': 'HEAD' if data is not None else None}
        if data is None:
            return None, info
        return ET.fromstring(data), info
    exp = repo.export_of(doc) if doc.origin == GENERATED else doc
    return (exp.tree if exp is not None else None,
            {'against': 'export', 'path': exp.path if exp is not None else None, 'ref': None})


class DiffError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def compare(repo, kind, name, against='commit'):
    """The diff of the document kind/name (the generated one, else the export) against its base, as the endpoint
    and CLI answer it."""
    if against not in AGAINST:
        raise DiffError(400, 'against must be commit or export')
    doc = repo.find(kind, name)
    if doc is None:
        raise DiffError(404, 'no %s %s' % (kind, name))
    old, info = base_tree(repo, doc, against)
    changes = diff_trees(old, doc.tree)
    out = []
    for c in changes:
        d = c.to_dict()
        d['texts'] = [{k: v for k, v in t.items() if k != 'cultures'} for t in d['texts']]
        out.append(d)
    return {'kind': kind, 'name': name, 'path': doc.path, 'origin': 'generated' if doc.origin == GENERATED else 'tia',
            'against': against, 'base': info,
            'changes': out, 'lines': [l for c in changes for l in c.lines()],
            'lineObjects': [c.object for c in changes for _ in c.lines()]}


def head_blobs(repo_path, paths):
    """{repo-relative path: bytes at git HEAD} of those of paths that exist there; {} without git or HEAD. One
    git cat-file --batch for all of them."""
    if not paths:
        return {}
    try:
        r = subprocess.run(['git', '-C', repo_path, 'cat-file', '--batch'], capture_output=True, env=git_env(),
                           input=''.join('HEAD:%s\n' % p for p in paths).encode('utf-8'), creationflags=NO_WINDOW)
    except OSError:
        return {}
    if r.returncode != 0:
        return {}
    out, data, pos = {}, r.stdout, 0
    for p in paths:
        nl = data.find(b'\n', pos)
        if nl < 0:
            break
        head = data[pos:nl].split()
        pos = nl + 1
        if len(head) != 3 or not head[2].isdigit():
            continue                                  # '<name> missing'
        size = int(head[2])
        out[p] = data[pos:pos + size]
        pos += size + 1
    return out


def _same_document(old, new, kind):
    """Whether the documents old and new (<Document> elements) show no change: no object change for a drawn
    document, the same XML for a text list."""
    if kind == 'textlist':
        return ET.tostring(old) == ET.tostring(new)
    return not diff_trees(old, new)


def _read(repo_path, rel):
    try:
        with open(os.path.join(repo_path, *rel.split('/')), 'rb') as f:
            return f.read()
    except OSError:
        return None


def _lf(data):
    return data.replace(b'\r\n', b'\n')


def states(repo, against):
    """The change report's state of every effective document of the repo's device against its base (base_tree):
    {(kind, name): 'new' (no base), 'changed' or 'same'}. A document equal to its base byte for byte (line ends
    aside) is not parsed again."""
    if against not in AGAINST:
        raise DiffError(400, 'against must be commit or export')
    docs = repo.effective
    blobs = head_blobs(repo.path, [d.path for d in docs]) if against == 'commit' else {}
    out = {}
    for d in docs:
        key = (d.kind, d.name)
        if against == 'commit':
            data = blobs.get(d.path)
            if data is None:
                out[key] = 'new'
                continue
            now = _read(repo.path, d.path)
            if now is not None and _lf(now) == _lf(data):
                out[key] = 'same'
                continue
            try:
                old = ET.fromstring(data)
            except ET.ParseError:
                out[key] = 'changed'
                continue
        else:
            exp = repo.export_of(d) if d.origin == GENERATED else d
            if exp is None or exp is d:
                out[key] = 'new' if exp is None else 'same'
                continue
            old = exp.tree
        out[key] = 'same' if _same_document(old, d.tree, d.kind) else 'changed'
    return out
