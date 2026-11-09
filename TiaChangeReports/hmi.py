"""The HMI part of a change report: the hmi/ folder of the inputs, compared by hmipreview (TiaHmiGenerator), as
objects of the page beside the PLC blocks.

  sides_of(before, after)       -> (side, side) or None   two folders, or (repo, rev1, rev2) of --git
  HmiPart(changes, all_=False)  the objects of one or more hmipreview.changes.Changes for the page

The documents and the pictures (data URIs) share the page's docs map, renamed per Changes (p0d3, p0i1).
An object is on the page when it changed (with all_ also when not). Its address (key) is '<kind>:<name>', with
several HMI devices '<device>:<kind>:<name>', a second one of the same key '~2' (block_keys' way); it sits in the
project tree under its device (TIA's name for the device; 'HMI' in a one-device repo), then TIA's folder for its kind
(Screens, Screen management, HMI tags, ...), then its TIA folders. Its section holds the header and an empty view
that hmi.js fills from the page's data (gzip + base64 JSON of the objects with their changes and the documents).
"""
import base64
import gzip
import json
import os
import sys
from html import escape
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
WINCC = os.path.join(os.path.dirname(HERE), 'TiaHmiGenerator')
if WINCC not in sys.path:
    sys.path.insert(0, WINCC)

from hmipreview import changes as hchanges   # noqa: E402
from hmipreview import jsbundle, rail, sides  # noqa: E402

# TIA's folders of an HMI device per kind, their order, the kinds' names: shared with the HMI preview's tree
KIND_TEXT, FOLDERS, ORDER, DEVICE = rail.KIND_TEXT, rail.FOLDERS, rail.HMI_ORDER, rail.DEVICE
GRAPHICS = ['Languages & resources', 'Project graphics']     # TIA's folders of the project graphics
ROOTS = tuple(root + '/' for root in sides.ROOTS)            # where the HMI part reads, from the repo's root


def sides_of(before, after=None, rev2=None, folders=False):
    """The two sides of the HMI part, or None when neither has an hmi/ folder: two folders (folders=True), else a
    repo and two revisions (rev2 None: the working tree)."""
    if folders:
        if not any(os.path.isdir(os.path.join(p, 'hmi')) for p in (before, after)):
            return None
        return sides.FolderSide(before), sides.FolderSide(after)
    b, a = sides.side(before, after), sides.side(before, rev2)
    return (b, a) if b.files() or a.files() else None


def holds_objects(repo, rev):
    """Does this revision hold an HMI object as TIA exported it (generated documents are none)."""
    return bool(sides.documents(sides.side(repo, rev)))


def compare(pairs, before_set='tia', after_set='tia', all_=False):
    """[hmipreview Changes] of the side pairs; all_: with the images of every graphic (--all lists them all)."""
    return [hchanges.compare(b, a, before_set, after_set, all_images=all_) for b, a in pairs]


def beside_exports(path):
    """Is a repo path under hmi/ no export of TIA: hmi/references/ and a device's generated/, the generator's documents,
    which --before-set and --after-set read; and the lists beside the exports (sides.is_hmi_list), the maintainer's
    word."""
    parts = path.split('/')
    folders = parts[1:-1]
    return parts[0] == 'hmi' and (parts[1:2] == [sides.SKIP_TOP[0]] or sides.GENERATED in folders[:2]
                                  or sides.is_hmi_list(path))


def read_paths(pairs, before_set, after_set):
    """The paths the HMI part reads of side pairs, from the repo's root or the folder: its documents in the given sets,
    the project graphics with their image folders. The data files only help to draw: a change in one is not told."""
    out = set()
    for b, a in pairs:
        for sd, which in ((b, before_set), (a, after_set)):
            out |= {e.path for e in sides.documents(sd, which).values()}
            shown = sides.graphics(sd).values()
            folders = tuple(sides.graphic_folder(p) for p in shown)
            out |= set(shown) | {p for p in sd.files() if folders and p.startswith(folders)}
    return out


class Item:
    """An HMI object on the page."""

    def __init__(self, o, key, multi):
        self.o, self.key = o, key
        self.name = o['name']
        self.folders = (GRAPHICS + (o['folder'].split('/') if o['folder'] else []) if o['kind'] == 'graphic' else
                        rail.hmi_folders(o['device'], o['kind'], o['folder']))
        self.order = ORDER
        self.multi = multi

    def tree_key(self):
        """Where it sits in the tree, as the tree sorts: device, TIA's folders of the device in TIA's order, then
        folders before objects, each by name."""
        return ([(0, 0, self.folders[0].casefold()), (0, ORDER.get(self.folders[1], 9), '')]
                + [(0, 0, f.casefold()) for f in self.folders[2:]] + [(1, 0, self.name.casefold())])

    @property
    def state(self):
        return self.o['state']

    def kind_text(self):
        n = self.o.get('number')
        return '[%s%s]' % (KIND_TEXT.get(self.o['kind'], self.o['kind']), ' %s' % n if n else '')

    def li(self, i):
        """The tree entry; data-i is its section."""
        o = self.o
        n = len(o.get('changes') or ())
        return ('<li><a class="obj %s" href="#%s" data-i="%d" data-key="%s" title="%s"><span class="mk"></span>'
                '<span class="nm">%s</span><span class="k">%s</span></a></li>'
                % (o['state'], quote(self.key, safe=''), i, escape(self.key),
                   escape('%s: %s%s' % (o['path']['after'] or o['path']['before'], o['state'],
                                        ', %d change%s' % (n, '' if n == 1 else 's') if n else '')),
                   escape(self.name), escape(self.kind_text())))

    def section(self, index):
        """The section: header as a block's (TIA's title band), the view hmi.js fills."""
        o = self.o
        pb, pa = o['path']['before'], o['path']['after']
        return ('<section class="blk hmi" data-o="%d"><div class="bh" id="blk-%s"><b>%s %s</b>%s%s'
                '<span class="paths">%s</span></div><div class="hv"></div></section>'
                % (index, escape(self.key), escape(self.name), escape(self.kind_text()),
                   ' <span class="k">%s</span>' % escape(o['device']) if self.multi and o['device'] else '',
                   '' if o['state'] == 'changed' else '<span class="st %s">%s</span>' % (o['state'], o['state']),
                   escape(pa or pb if pb == pa or not (pa and pb) else '%s → %s' % (pb, pa))))


class HmiPart:
    """The HMI objects of one or more Changes on the page: items (tree entries and sections, in tree order), the
    data hmi.js draws them from."""

    def __init__(self, results, all_=False):
        self.results = results
        objects, parts, docs = [], [], {}
        for p, res in enumerate(results):
            ren = {k: 'p%d%s' % (p, k) for k in list(res.docs) + list(res.images)}
            parts.append({'before': res.before, 'after': res.after, 'data': res.data,
                          'pictures': {side: {n: ren[i] for n, i in pics.items()}
                                       for side, pics in res.pictures.items()}})
            docs.update((ren[k], v) for k, v in list(res.docs.items()) + list(res.images.items()))
            for o in res.objects:
                o = dict(o, part=p)
                for side in ('bdoc', 'adoc', 'bimg', 'aimg'):
                    if side in o:
                        o[side] = ren[o[side]]
                objects.append(o)
        devices = {(o['part'], o['device']) for o in objects}
        multi = len(devices) > 1
        seen, self.items = {}, []
        for i, o in enumerate(objects):
            base = ('%s:%s:%s' % (o['device'], o['kind'], o['name']) if multi and o['device']
                    else '%s:%s' % (o['kind'], o['name']))
            seen[base] = seen.get(base, 0) + 1
            o['key'] = base if seen[base] == 1 else '%s~%d' % (base, seen[base])
            if o['state'] != 'same' or all_:
                self.items.append((Item(o, o['key'], multi), i))
        self.items.sort(key=lambda x: x[0].tree_key())          # the tree's order: the page's, prev / next
        self.index = [i for _, i in self.items]
        self.items = [it for it, _ in self.items]
        self.objects, self.parts, self.docs = objects, parts, docs

    def __len__(self):
        return len(self.items)

    def data_html(self, lang):
        payload = json.dumps({'lang': lang, 'parts': self.parts, 'docs': self.docs, 'objects': self.objects},
                             ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return ('<script type="application/octet-stream" class="hmidata">%s</script>'
                % base64.b64encode(gzip.compress(payload, 9, mtime=0)).decode('ascii'))

    def sections_html(self):
        return ''.join(it.section(i) for it, i in zip(self.items, self.index))

    def summary_html(self):
        rows = ''.join('<tr><td><a href="#blk-%s">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                       % (escape(quote(it.key, safe='')), escape(it.name), escape(KIND_TEXT.get(it.o['kind'], '')),
                          escape(it.o['device'] or ''), it.state, len(it.o.get('changes') or ()) or '')
                       for it in self.items)
        return ('<table class="sum hsum"><tr><th>HMI object</th><th>Type</th><th>Device</th><th>State</th>'
                '<th>Changes</th></tr>%s</table>' % rows)

    def json(self):
        return [{'device': it.o['device'], 'kind': it.o['kind'], 'name': it.name, 'state': it.state,
                 'changes': len(it.o.get('changes') or ()),
                 **({'was': it.o['from']['name']} if it.o.get('from') else {})}
                for it in self.items]

    def lines(self):
        return ['%-8s %-11s %s%s' % (it.state, it.o['kind'], '/'.join(it.folders[:1] + [it.name]) if it.multi else
                                     it.name, '  (was "%s")' % it.o['from']['name'] if it.o.get('from') else '')
                for it in self.items]


def script(path):
    with open(os.path.join(HERE, path), encoding='utf-8') as f:
        return f.read()


def css():
    return script('hmi.css')


def js():
    """hmi.js with the preview's drawing code bound inside it."""
    return script('hmi.js').replace('/*BUNDLE*/', jsbundle.bundle().replace("'use strict';\n", '', 1), 1)
