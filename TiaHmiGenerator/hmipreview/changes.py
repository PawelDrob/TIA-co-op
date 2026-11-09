"""HMI changes between two sides (sides.py): what the change report shows of the hmi/ part of a project repo.

  compare(before, after, before_set='tia', after_set='tia', devices=None) -> Changes

Pairing: a document pairs with the document of the same device, kind and name on the other side; a screen, template
or pop-up left over on both sides pairs with the one of the same Number (a renamed screen) when that number is
unique among the left-over ones of its device and kind.

An object per pair: state 'new', 'deleted', 'changed' or 'same' (equal ids in one place, or only what no object in TIA
holds differs: IDs, a link's TargetID beside its name, DocumentInfo, indentation, and what the file format writes around
the values: Engineering version, CompositionName, DefaultImageStream's 'external'); 'from' {name, folder} when it was
renamed or moved to another TIA folder; 'number' of a drawn document (its Number, after else before); changes:
- drawn documents (screens, templates, pop-ups, slide-ins, global elements): diff.diff_trees per screen item, each
  part (Events, Animations, ...) spelled out fact by fact (fact_diff): 'RangeValues(Range_1)/BackColor 190, 215, 240';
  an added item the same way with what it is tied to (diff._added, _added_facts): its tag, function, list
- tag tables, text and graphic lists, cycles, connections, scripts: the root's attributes, links and parts, and
  each member (tag, list entry) added, removed or changed, an added or removed one with its facts
Folded: an attribute present on one side and absent on the other, where that side is a minimal export (a minimal
export leaves out a value equal to TIA's default, so absent means the default, not removed: Length 3 -> (none) in a
tag table) or holds that attribute nowhere (exported once with it and once without), gets fold 'export', one of
QUIET (no visible effect: TabIndex, ...) fold 'quiet'; a change of nothing else gets fold too; the rows of which
group an item stands in (diff.GROUP_ROWS) never, as empty there means no group. On an object of another type
(diff.TYPE_ROW) nothing folds as an export difference: absent may be an attribute that type does not hold, which no
export leaves out, and the document does not say which. The object lists the export differences in exportNoise
[{name, missing: 'before' | 'after', count}] and the export settings when they differ (exportSetting {before, after}).
Where used: a changed tag lists the drawn documents that link it and the documents with a text field naming it, on
each side (usedBefore, usedAfter; a deleted tag still used after: stillUsed), a text or graphic list and a template
list theirs (usedBy).

Graphics (project/graphics, sides.graphics): every graphic is an object of kind 'graphic' (device ''), 'same' when
its .xml and the files of '<name> files/' are, else its changes those of its .xml plus 'Image' when the default image
differs and 'File <file name>' for another file that differs or stands on one side only, with their paths where a path
differs, and 'Image changed' or 'File <file name> changed' with no values on one path; 'from' as for a document when
it moved to another folder; usedBy its screens (with their device); a graphic whose .xml does not parse is skipped and
named. The images the drawn documents link (Picture, PictureOff, ...) and those of the changed graphics (all_images: of
every graphic) are kept for the page: images {id: data URI}, pictures {'before' | 'after': {graphic name: image id}}; a
graphic object names its image ids in bimg / aimg. An image no browser draws (drawable: .emf, .wmf) is not kept: its
box stays labelled, and a change of it is still listed.

A document that does not parse is left out and named in skipped [(path, 'unreadable: ...')].

The drawn documents and text lists of both sides are kept for the page (docs: {id: SimaticML without DocumentInfo
and indentation}, equal ones once); an object names its ids in bdoc / adoc.
"""
import base64
import collections
import hashlib
import json
import mimetypes
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import diff as hdiff
from .model import attribute
from .rules.text import told_lines
from .sides import DRAWN, GRAPHICS, KIND_DIRS, FolderStamps, data_files, documents, graphic_folder, graphics

KIND_ORDER = list(KIND_DIRS.values()) + ['graphic']
EMBEDDED = DRAWN + ('textlist', 'graphiclist')       # documents the page needs whole
RENAMEABLE = ('screen', 'template', 'popup', 'slidein')
BROWSER_IMAGES = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg')     # no browser draws .emf or .wmf
MEMBERS = {'tagtable': 'Hmi.Tag.Tag', 'textlist': 'Hmi.TextGraphicList.TextListEntry',
           'graphiclist': 'Hmi.TextGraphicList.GraphicListEntry'}
USED = {'TextList': 'textlist', 'GraphicList': 'graphiclist', 'Template': 'template'}   # link kind -> object kind
FIELD_LINKS = {'HmiTag': 'Tag', 'HmiTextList': 'TextList', 'HmiGraphicList': 'GraphicList'}    # a field's link type
CONTAINERS = ('AttributeList', 'ObjectList', 'LinkList')
QUIET = {'TabIndex', 'SetTabOrderInFront', 'ActiveLayer', 'GridColor'}   # engineering only, no visible effect


@dataclass
class Changes:
    before: str                     # side labels, with the set
    after: str
    objects: list                   # one dict per document pair, in device, kind, folder, name order
    docs: dict                      # {doc id: SimaticML text}
    data: dict = field(default_factory=dict)   # {'before' | 'after': {device: {'handbuilt': [...], 'panel': {...}}}}
    images: dict = field(default_factory=dict)     # {image id: data URI}
    pictures: dict = field(default_factory=dict)   # {'before' | 'after': {graphic name: image id}}
    skipped: list = field(default_factory=list)    # [(path, why)]: documents that do not parse, left out

    def changed(self):
        return [o for o in self.objects if o['state'] != 'same']

    def to_dict(self):
        return {'before': self.before, 'after': self.after, 'objects': self.objects, 'docs': self.docs,
                'data': self.data, 'images': self.images, 'pictures': self.pictures,
                'skipped': [{'path': p, 'reason': why} for p, why in self.skipped]}

    def lines(self):
        """One line per changed object: 'changed  screen  Dev/Silo (3)'."""
        return ['%-8s %-11s %s%s%s (%d)' % (o['state'], o['kind'], o['device'] + '/' if o['device'] else '',
                                             o['folder'] + '/' if o['folder'] else '', o['name'],
                                             len(o.get('changes', ())))
                for o in self.changed()]


def strip(raw):
    """The SimaticML the page needs: without the BOM, DocumentInfo (installed products, export time), indentation
    and line ends (a working tree file has CRLF where its blob has LF)."""
    s = raw.decode('utf-8-sig').replace('\r\n', '\n')
    s = re.sub(r'<DocumentInfo>.*?</DocumentInfo>', '', s, flags=re.S)
    return re.sub(r'>\s+<', '><', s).strip()


def root_of(tree):
    return hdiff._root(tree)


def _short(tag):
    return tag.split('.')[-1]


# --- facts ----------------------------------------------------------------------------------------------------

def facts(elem, path=''):
    """Leaf facts of the children of elem as 'path = value' (IDs left out): an attribute, a link by its target
    name, a text per culture. A child object is named in the path by its Name, ObjectName or Culture (a FontItem)."""
    out = []
    for c in elem:
        tag = _short(c.tag)
        if tag in CONTAINERS:
            out += facts(c, path)
            continue
        if c.tag == 'MultilingualTextItem':
            al = c.find('AttributeList')
            t = al.find('Text') if al is not None else None
            txt = '\n'.join(told_lines(t)) if t is not None else ''
            if txt:
                out.append('%s[%s] = %s' % (path, al.findtext('Culture') or '', txt))
            continue
        p = (path + '/' if path else '') + tag
        if c.get('TargetID') is not None and len(c) <= 1:
            out.append('%s = %s' % (p, c.findtext('Name') or c.get('TargetID')))
        elif len(c):
            nm = attribute(c, 'Name') or attribute(c, 'ObjectName') or attribute(c, 'Culture')
            out += facts(c, p + ('(%s)' % nm if nm else ''))
        elif c.text and c.text.strip():
            out.append('%s = %s' % (p, c.text.strip()))
    return out


def _split(f):
    return f.split(' = ', 1) if ' = ' in f else (f, '')


def fact_diff(old_children, new_children):
    """[{path, old, new}] between two lists of part elements: facts of the same path paired as a change, the rest
    added (old None) or removed (new None)."""
    of = collections.Counter(f for c in old_children for f in facts(c, _short(c.tag)))
    nf = collections.Counter(f for c in new_children for f in facts(c, _short(c.tag)))
    came = collections.defaultdict(list)
    for f in (nf - of).elements():
        p, v = _split(f)
        came[p].append(v)
    out = []
    for f in (of - nf).elements():
        p, v = _split(f)
        out.append({'path': p, 'old': v, 'new': came[p].pop(0) if came.get(p) else None})
    out += [{'path': p, 'old': None, 'new': v} for p, vs in came.items() for v in vs]
    return out


def _added_facts(children):
    """The facts of a part of an added object, in the document's order: one object's rows stay together, so which tag
    or function belongs to which property or event can be read."""
    rows = [_split(f) for c in children for f in facts(c, _short(c.tag))]
    return [{'path': p, 'old': None, 'new': v} for p, v in rows]


def _fact_lines(who, part, fd):
    out = []
    for f in fd:
        if f['old'] is None:
            out.append('%s: %s %s added' % (who, f['path'], hdiff._q(f['new'])))
        elif f['new'] is None:
            out.append('%s: %s %s removed' % (who, f['path'], hdiff._q(f['old'])))
        else:
            out.append('%s: %s %s -> %s' % (who, f['path'], hdiff._q(f['old']), hdiff._q(f['new'])))
    return out


def _record(change, old_el, new_el):
    """The change as the page shows it: diff.Change as a dict, each changed part spelled out as facts, the lines."""
    d = change.to_dict()
    d['texts'] = [{k: v for k, v in t.items() if k != 'cultures'} for t in d['texts']]
    op = hdiff._own_parts(old_el) if old_el is not None else {}
    np_ = hdiff._own_parts(new_el) if new_el is not None else {}
    d['parts'] = [{'part': p, 'facts': _added_facts(np_.get(p, [])) if change.kind == 'added'
                   else fact_diff(op.get(p, []), np_.get(p, []))} for p in change.parts]
    lines = change.lines_without_parts()
    for p in d['parts']:
        lines += _fact_lines(change.who, p['part'], p['facts'])
    d['lines'] = lines
    return d


# --- diffs ----------------------------------------------------------------------------------------------------

def screen_changes(old_tree, new_tree):
    """Change records of a drawn document (old_tree / new_tree None: added / removed whole)."""
    oroot, nroot = root_of(old_tree), root_of(new_tree)
    oi, ni = hdiff.screen_items(oroot), hdiff.screen_items(nroot)
    out = []
    for c in hdiff.diff_trees(old_tree, new_tree):
        if c.object is None:
            out.append(_record(c, oroot, nroot))
        else:
            out.append(_record(c, oi.get(c.object), ni.get(c.object)))
    return out


def _member_name(el):
    n = attribute(el, 'Name')
    if n is None:                                       # list entries: by their range
        lo = attribute(el, 'From', '?')
        n = '%s..%s' % (lo, attribute(el, 'To', lo))
    return n


def members(root, tag):
    """{name: element} of the members (tags, list entries) of a tag table or list root."""
    out = {}
    ol = root.find('ObjectList') if root is not None and tag else None
    for c in ol if ol is not None else []:
        if c.tag == tag:
            out.setdefault(_member_name(c), c)
    return out


def member_changes(old_tree, new_tree, kind):
    """Change records of a tag table, list, cycle, connection or script: the root (attributes, links, parts other
    than the members), then each member added, removed or changed."""
    oroot, nroot = root_of(old_tree), root_of(new_tree)
    tag = MEMBERS.get(kind)
    out = []
    if oroot is not None and nroot is not None:
        c = hdiff._compare(None, nroot.tag, _without(oroot, tag), _without(nroot, tag), root=True)
        if c is not None:
            c.kind, c.name = 'changed', attribute(nroot, 'Name')
            out.append(_record(c, _without(oroot, tag), _without(nroot, tag)))
    om, nm = members(oroot, tag), members(nroot, tag)
    for n in list(nm) + [n for n in om if n not in nm]:
        o, w = om.get(n), nm.get(n)
        if o is None or w is None:
            el = w if w is not None else o
            k = 'added' if o is None else 'removed'
            own, counts = own_facts(el)
            out.append({'object': n, 'type': _short(el.tag), 'kind': k, 'old': None, 'new': None,
                        'attributes': [], 'texts': [], 'links': [], 'parts': [], 'facts': own, 'counts': counts,
                        'lines': ['%s %s: %s' % (_short(el.tag), n, k)]})
            continue
        c = hdiff._compare(n, w.tag, o, w)
        if c is not None:
            out.append(_record(c, o, w))
    return out


def own_facts(el):
    """(facts, {CompositionName: count}) of a member on its own: its attributes, links and texts (comment), and
    the number of its other parts (a structured tag's members: thousands of facts for a large data type)."""
    out, counts = [], collections.Counter()
    for c in el:
        if c.tag in ('AttributeList', 'LinkList'):
            out += facts(c)
        elif c.tag == 'ObjectList':
            for p in c:
                if p.tag == 'MultilingualText':
                    out += facts(p, p.get('CompositionName') or 'Text')
                else:
                    counts[p.get('CompositionName') or _short(p.tag)] += 1
    return out, dict(counts)


def _without(root, tag):
    """A copy of root without its member children (tag), so that the root compare sees its own parts only."""
    if root is None or not tag:
        return root
    cp = ET.Element(root.tag, root.attrib)
    for c in root:
        if c.tag == 'ObjectList':
            ol = ET.SubElement(cp, 'ObjectList')
            ol.extend(x for x in c if x.tag != tag)
        else:
            cp.append(c)
    return cp


# --- where used -----------------------------------------------------------------------------------------------

def tag_base(name):
    """The HMI tag a link names: 'Motor.speed' -> 'Motor', 'Lanes[3].mode' -> 'Lanes'; a quoted name is the tag's
    whole name: '"Lane[3]".mode' -> 'Lane[3]' (TIA names the HMI tag of an array element of a PLC tag so)."""
    if name.startswith('"'):
        end = name.find('"', 1)
        return name[1:end] if end > 0 else name[1:]
    return name.split('.', 1)[0].split('[', 1)[0]


def field_uses(tree):
    """{(link kind, name)} the fields inside a document's texts name, as '<namespace>.HmiTag:Motor.speed': whatever
    in a fieldinfo reads so, as the text row reads every value of it (rules.text)."""
    out = set()
    for info in tree.iter('fieldinfo'):
        for e in info.iter():
            link_type, _, n = (e.text or '').strip().partition(':')
            kind = FIELD_LINKS.get(link_type.rsplit('.', 1)[-1])
            if kind and n:
                out.add((kind, tag_base(n) if kind == 'Tag' else n))
    return out


def uses(tree):
    """{(link kind, name)} a drawn document links, its text fields too: 'Tag' by its HMI tag, 'TextList',
    'GraphicList', 'Template', 'Picture' (Picture, PictureOff, PictureOn, ...)."""
    out = set()
    for e in tree.iter():
        if e.get('TargetID') == '@OpenLink':
            n = e.findtext('Name')
            if not n:
                continue
            if e.tag == 'Tag':
                out.add(('Tag', tag_base(n)))
            elif e.tag in USED:
                out.add((e.tag, n))
            elif e.tag.startswith('Picture'):
                out.add(('Picture', n))
    return out | field_uses(tree)


# --- compare --------------------------------------------------------------------------------------------------

def _set_label(sd, which):
    return '%s, %s' % (sd.label, 'generated' if which == 'generated' else 'TIA')


def compare(before, after, before_set='tia', after_set='tia', devices=None, all_images=False):
    """The HMI changes from side before to side after (sides.py), each in its set ('tia' or 'generated').
    all_images: also the images of the unchanged graphics no drawn document links (a report of every object).
    ValueError for a side whose ids are no contents (sides.FolderStamps)."""
    for sd in (before, after):
        if isinstance(sd, FolderStamps):
            raise ValueError('%s: size and time prove no equal contents, nothing to compare by' % sd.label)
    bdocs = documents(before, before_set, devices)
    adocs = documents(after, after_set, devices)
    keys = sorted(set(bdocs) | set(adocs), key=repr)     # a fixed order: the document ids follow it

    def needed(own, other, k):
        return k in own and (k[1] in EMBEDDED or k not in other or own[k].id != other[k].id
                             or own[k].folder != other[k].folder)

    before.prefetch([bdocs[k].path for k in keys if needed(bdocs, adocs, k)])
    after.prefetch([adocs[k].path for k in keys if needed(adocs, bdocs, k)])
    raw, trees = {}, {}

    def tree(sd, e):
        key = (id(sd), e.path)
        if key not in trees:
            raw[key] = sd.read(e.path)
            trees[key] = ET.fromstring(raw[key])
        return trees[key]

    skipped = []
    for sd, own, other in ((before, bdocs, adocs), (after, adocs, bdocs)):
        for k in [k for k in keys if needed(own, other, k)]:
            try:
                tree(sd, own[k])
            except ET.ParseError as ex:             # left out on both sides, named; the rest is compared
                skipped.append((own.pop(k).path, 'unreadable: %s' % ex))
                other.pop(k, None)
    pairs = [(k, k) for k in keys if k in bdocs and k in adocs]
    pairs += _renamed([k for k in bdocs if k not in adocs], [k for k in adocs if k not in bdocs],
                      lambda k: attribute(root_of(tree(before, bdocs[k])), 'Number'),
                      lambda k: attribute(root_of(tree(after, adocs[k])), 'Number'))
    paired_b = {b for b, _ in pairs}
    paired_a = {a for _, a in pairs}
    pairs += [(k, None) for k in bdocs if k not in paired_b] + [(None, k) for k in adocs if k not in paired_a]

    docs, by_text = {}, {}

    def doc_id(sd, e):
        text = strip(raw[(id(sd), e.path)])
        if text not in by_text:                         # equal documents (both sides, sister devices) stored once
            by_text[text] = 'd%d' % len(by_text)
            docs[by_text[text]] = text
        return by_text[text]

    objects, refs = [], {'before': collections.defaultdict(set), 'after': collections.defaultdict(set)}
    for bk, ak in pairs:
        b, a = bdocs.get(bk), adocs.get(ak)
        e = a or b
        o = {'device': e.device, 'kind': e.kind, 'name': e.name, 'folder': e.folder,
             'origin': {'before': b and b.origin, 'after': a and a.origin},
             'path': {'before': b and b.path, 'after': a and a.path}}
        if b and a and (b.name, b.folder) != (a.name, a.folder):
            o['from'] = {'name': b.name, 'folder': b.folder}
        same = b is not None and a is not None and b.id == a.id and 'from' not in o
        bt = tree(before, b) if b and (e.kind in EMBEDDED or not same) else None
        at = tree(after, a) if a and (e.kind in EMBEDDED or not same) else None
        if e.kind in EMBEDDED:
            if bt is not None:
                o['bdoc'] = doc_id(before, b)
            if at is not None:
                o['adoc'] = doc_id(after, a)
            links_of = uses if e.kind in DRAWN else field_uses
            for t, side, k in ((bt, 'before', b), (at, 'after', a)):
                if t is not None:
                    for u in links_of(t):
                        refs[side][(e.device,) + u].add((k.kind, k.name))
        if e.kind in DRAWN:
            num = attribute(root_of(at if at is not None else bt), 'Number')
            if num:
                o['number'] = num
        if b is None or a is None:
            o['state'] = 'new' if b is None else 'deleted'
        elif same:
            o['state'] = 'same'
        else:
            o['state'] = 'changed'
        if o['state'] != 'same':
            o['changes'] = screen_changes(bt, at) if e.kind in DRAWN else member_changes(bt, at, e.kind)
            if o['state'] == 'changed' and not o['changes'] and 'from' not in o:
                o['state'] = 'same'                     # only the export time, IDs or indentation differ
            elif o['state'] == 'changed':
                fold(o, bt, at)
        objects.append(o)

    images, pictures = {}, {'before': {}, 'after': {}}
    objects += _graphics(before, after, refs, images, pictures, skipped, all_images)
    _where_used(objects, refs)
    objects.sort(key=lambda o: (o['device'].casefold(), KIND_ORDER.index(o['kind']), o['folder'].casefold(),
                                o['name'].casefold()))
    return Changes(_set_label(before, before_set), _set_label(after, after_set), objects, docs,
                   {'before': _data(before, devices), 'after': _data(after, devices)}, images, pictures,
                   list(dict.fromkeys(skipped)))


def _image_of(sd, xml_path, root):
    """(path, bytes) of a graphic's default image: DefaultImageStream names it relative to the .xml; None when it
    names none or the side lacks the file (a repo exported before the bridge kept the images)."""
    rel = attribute(root, 'DefaultImageStream') if root is not None else None
    if not rel:
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(xml_path), rel.replace('\\', '/')))
    if path not in sd.files():
        return None
    return path, sd.read(path)


def drawable(path):
    """True for an image file a browser can draw."""
    return posixpath.splitext(path)[1].lower() in BROWSER_IMAGES


def picture_files(sd):
    """{graphic name: path of its image} of side sd, for the images a browser can draw; a graphic whose .xml does not
    parse, or that has no image on the side, is left out, and its box is labelled instead."""
    out = {}
    for name, path in graphics(sd).items():
        try:
            img = _image_of(sd, path, root_of(ET.fromstring(sd.read(path))))
        except ET.ParseError:
            continue
        if img and drawable(img[0]):
            out[name] = img[0]
    return out


def _graphic_files(sd, path):
    """{file name: id} of the files of '<name> files/' beside a graphic's .xml."""
    folder = graphic_folder(path)
    return {p[len(folder):]: i for p, i in sd.files().items() if p.startswith(folder)}


def _same_graphic(before, b, after, a):
    """Whether two .xml paths are one place and their files have equal ids. Sides of two kinds never have equal ids:
    their bytes decide then, in _graphics."""
    return (b == a and before.files()[b] == after.files()[a]
            and _graphic_files(before, b) == _graphic_files(after, a))


def _graphic_change(name, row, old, new, line):
    """A change record of a graphic that is one attribute row and one line. A file on one path says only that it
    changed; a row of paths tells where a path differs."""
    if old == new:
        row, old, new = '%s changed' % row, None, None
    return {'object': None, 'type': 'MultiLingualGraphic', 'kind': 'changed', 'old': None, 'new': None, 'texts': [],
            'links': [], 'parts': [], 'attributes': [{'name': row, 'old': old, 'new': new}],
            'lines': ['MultiLingualGraphic %s: %s' % (name, line)]}


def _other_files(name, before, b, bi, after, a, ai):
    """The change records of the files of a graphic, by name, that the row of its default image (bi, ai: _image_of) does
    not tell: equal ids are equal, other ids prove nothing on sides of two kinds, so the bytes decide."""
    was, now = _graphic_files(before, b), _graphic_files(after, a)
    default = bi and bi[0], ai and ai[0]
    out = []
    for file in sorted(set(was) | set(now)):
        old = graphic_folder(b) + file if file in was else None
        new = graphic_folder(a) + file if file in now else None
        if (old in (None, default[0]) and new in (None, default[1])) or was.get(file) == now.get(file):
            continue
        if not (old and new and before.read(old) == after.read(new)):
            how = 'added' if old is None else 'removed' if new is None else 'changed'
            out.append(_graphic_change(name, 'File %s' % file, old, new, 'file %s %s' % (file, how)))
    return out


def _graphics(before, after, refs, images, pictures, skipped, all_images=False):
    """The graphic objects (state 'same' too, without changes); fills images and pictures (module doc) with the
    pictures the drawn documents link and those of the changed graphics (all_images: of every graphic). A graphic
    whose .xml does not parse is left out on both sides and named in skipped."""
    gb, ga = graphics(before), graphics(after)
    trees = {}

    def tree(sd, path):                     # the parsed .xml, None when it does not parse (then skipped once)
        if (id(sd), path) not in trees:
            try:
                trees[(id(sd), path)] = ET.fromstring(sd.read(path))
            except ET.ParseError as ex:
                trees[(id(sd), path)] = None
                skipped.append((path, 'unreadable: %s' % ex))
        return trees[(id(sd), path)]

    want = {side: {n for (_, kind, n) in refs[side] if kind == 'Picture'} for side in ('before', 'after')}
    out = []
    for name in sorted(set(gb) | set(ga), key=str.casefold):
        b, a = gb.get(name), ga.get(name)
        same = bool(b and a) and _same_graphic(before, b, after, a)
        if not same and ((b and tree(before, b) is None) or (a and tree(after, a) is None)):
            gb.pop(name, None)
            ga.pop(name, None)
            continue
        o = {'device': '', 'kind': 'graphic', 'name': name,
             'folder': posixpath.dirname((a or b)[len(GRAPHICS) + 1:]),
             'origin': {'before': b and 'export', 'after': a and 'export'}, 'path': {'before': b, 'after': a},
             'state': 'same' if same else 'new' if not b else 'deleted' if not a else 'changed', 'changes': []}
        if b and a and posixpath.dirname(b) != posixpath.dirname(a):
            o['from'] = {'name': name, 'folder': posixpath.dirname(b[len(GRAPHICS) + 1:])}
        if b and a and not same:
            bt, at = tree(before, b), tree(after, a)
            o['changes'] = member_changes(bt, at, 'graphic')
            bi, ai = _image_of(before, b, root_of(bt)), _image_of(after, a, root_of(at))
            if (bi and bi[1]) != (ai and ai[1]):
                o['changes'].append(_graphic_change(name, 'Image', bi and bi[0], ai and ai[0], 'image changed'))
            o['changes'] += _other_files(name, before, b, bi, after, a, ai)
            if not o['changes'] and 'from' not in o:
                o['state'] = 'same'                 # only what no object in TIA holds differs
        if o['state'] != 'same' or all_images:
            if b:
                want['before'].add(name)
            if a:
                want['after'].add(name)
        out.append(o)
    by_hash = {}
    for side, sd, g in (('before', before, gb), ('after', after, ga)):
        for name in sorted(want[side]):
            t = tree(sd, g[name]) if name in g else None
            img = _image_of(sd, g[name], root_of(t)) if t is not None else None
            if not img or not drawable(img[0]):
                continue
            h = hashlib.sha1(img[1]).hexdigest()
            if h not in by_hash:                    # the same image (both sides, two graphics) stored once
                by_hash[h] = 'i%d' % len(by_hash)
                mime = mimetypes.guess_type(img[0])[0] or 'application/octet-stream'
                images[by_hash[h]] = 'data:%s;base64,%s' % (mime, base64.b64encode(img[1]).decode('ascii'))
            pictures[side][name] = by_hash[h]
    for o in out:
        for side, key in (('before', 'bimg'), ('after', 'aimg')):
            if o['name'] in pictures[side]:
                o[key] = pictures[side][o['name']]
    return out


def _attribute_names(tree):
    root = root_of(tree)
    return {c.tag for al in root.iter('AttributeList') for c in al} if root is not None else set()


def fold(o, old_tree, new_tree):
    """Marks the export differences and the attributes without a visible effect in o's changes (module doc)."""
    settings = [t.findtext('DocumentInfo/ExportSetting') if t is not None else None for t in (old_tree, new_tree)]
    minimal = [x == 'None' for x in settings]
    gone = _attribute_names(old_tree) - _attribute_names(new_tree)
    came = _attribute_names(new_tree) - _attribute_names(old_tree)
    noise = collections.Counter()
    for c in o.get('changes', ()):
        if c['kind'] == 'added':                        # its Mode is the object's, no export difference
            continue
        retyped = any(a['name'] == hdiff.TYPE_ROW for a in c['attributes'])
        for a in c['attributes']:
            if a['name'] in hdiff.GROUP_ROWS:
                continue
            if not retyped and ((a['new'] is None and (minimal[1] or a['name'] in gone))
                                or (a['old'] is None and (minimal[0] or a['name'] in came))):
                a['fold'] = 'export'
                noise[(a['name'], 'after' if a['new'] is None else 'before')] += 1
            elif a['name'] in QUIET:
                a['fold'] = 'quiet'
        if (c['kind'] == 'changed' and c['attributes'] and not (c['texts'] or c['links'] or c['parts'])
                and all(a.get('fold') for a in c['attributes'])):
            c['fold'] = 'export' if any(a['fold'] == 'export' for a in c['attributes']) else 'quiet'
    if noise:
        o['exportNoise'] = [{'name': n, 'missing': side, 'count': k} for (n, side), k in sorted(noise.items())]
    if None not in settings and settings[0] != settings[1]:
        o['exportSetting'] = {'before': settings[0], 'after': settings[1]}


def _renamed(gone, came, bnum, anum):
    """Pairs (before key, after key) of left-over documents of a renameable kind with the same Number, unique among
    the left-over ones of their device and kind on both sides."""
    def by_number(keys, num):
        out = collections.defaultdict(list)
        for k in keys:
            if k[1] in RENAMEABLE:
                n = num(k)
                if n not in (None, ''):
                    out[(k[0], k[1], n)].append(k)
        return out
    bn, an = by_number(gone, bnum), by_number(came, anum)
    return [(bn[n][0], an[n][0]) for n in bn if len(bn[n]) == 1 and len(an.get(n, ())) == 1]


def _where_used(objects, refs):
    def used(side, device, kind, name):
        return [{'kind': k, 'name': n} for k, n in sorted(refs[side].get((device, kind, name), ()),
                                                          key=lambda x: (KIND_ORDER.index(x[0]), x[1].casefold()))]
    for o in objects:
        if o['kind'] == 'tagtable':
            for c in o.get('changes', ()):
                if c['object'] is not None:
                    c['usedBefore'] = used('before', o['device'], 'Tag', c['object'])
                    c['usedAfter'] = used('after', o['device'], 'Tag', c['object'])
                    if c['kind'] == 'removed' and c['usedAfter']:
                        c['stillUsed'] = True
        if o['kind'] == 'graphic':                     # project-wide: the users of every device
            o['usedBy'] = {side: sorted(({'device': dev, 'kind': k, 'name': n}
                                         for (dev, kind, name), users in refs[side].items()
                                         if kind == 'Picture' and name == o['name'] for k, n in users),
                                        key=lambda u: (u['device'].casefold(), KIND_ORDER.index(u['kind']),
                                                       u['name'].casefold()))
                           for side in ('before', 'after')}
        link = next((lk for lk, kind in USED.items() if kind == o['kind']), None)
        if link:
            o['usedBy'] = {'before': used('before', o['device'], link, (o.get('from') or o)['name']),
                           'after': used('after', o['device'], link, o['name'])}


def _data(sd, devices):
    """{device: {'handbuilt': ..., 'panel': ...}} of the data files of a side (one that does not parse left out; a
    read that fails stays the side's ValueError)."""
    out = {}
    for (device, fname), path in data_files(sd).items():
        if devices and device not in devices:
            continue
        raw = sd.read(path)
        try:
            out.setdefault(device, {})[fname[:-5]] = json.loads(raw.decode('utf-8-sig'))
        except ValueError:
            pass
    return out
