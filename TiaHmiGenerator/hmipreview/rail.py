"""The project tree (rail) shared by the change report (TiaChangeReports page.py) and the
HMI preview: one markup, one script, one style, used by both.

  BASE_CSS, CSS, JS     static/ldiff.css (the colours and font of .ldiff), static/rail.css, static/rail.js
                        (ldiffRail(root, options): folding, search, Ctrl+K lookup, key list, Ctrl+B strip)
  LAUNCHER              the lookup window, outside the rail
  node(top, folders)    the tree node of folders below top, made as needed
  nav_html(top)         the rail with the tree of top: folders first, then objects, each by name (as TIA sorts them)
  hmi_folders(device, kind, folder)   TIA's folders of an HMI document: device, TIA's folder for its kind, its folders

A tree node is {'dirs': {name: node}, 'objs': [(name, i, li html)], 'order': {folder name: rank}}; an object's <li>
holds <a class="obj STATE" data-key=... data-i=...><span class="mk"></span><span class="nm">NAME</span>
<span class="k">KIND</span></a>, STATE one of the change report's (new, changed, deleted, same, version) or none.
"""
import os
from html import escape

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')


def _read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as f:
        return f.read()


BASE_CSS = _read('ldiff.css')
CSS = _read('rail.css')
JS = _read('rail.js')

# The lookup window, one for every lookup, outside the rail so that it shows with the rail
# collapsed; its bar text and rows set by rail.js per lookup.
LAUNCHER = ('<div class="lch" hidden><div class="lb" role="dialog" aria-label="Lookup">'
            '<input type="text" spellcheck="false" autocomplete="off"><ul role="listbox"></ul></div></div>')

# TIA's folders of an HMI device, per kind of document, and their order under the device
KIND_TEXT = {'screen': 'Screen', 'template': 'Template', 'popup': 'Pop-up screen', 'slidein': 'Slide-in screen',
             'global': 'Global screen', 'textlist': 'Text list', 'graphiclist': 'Graphic list',
             'tagtable': 'HMI tag table', 'cycle': 'Cycle', 'connection': 'Connection', 'script': 'Script',
             'graphic': 'Graphic'}
FOLDERS = {'screen': ['Screens'], 'template': ['Screen management', 'Templates'],
           'popup': ['Screen management', 'Pop-up screens'], 'slidein': ['Screen management', 'Slide-in screens'],
           'global': ['Screen management'], 'tagtable': ['HMI tags'], 'connection': ['Connections'],
           'cycle': ['Cycles'], 'script': ['Scripts'], 'textlist': ['Text and graphic lists'],
           'graphiclist': ['Text and graphic lists']}
HMI_ORDER = {'Screens': 0, 'Screen management': 1, 'HMI tags': 2, 'Connections': 3, 'Scripts': 4, 'Cycles': 5,
             'Text and graphic lists': 6}
DEVICE = 'HMI'          # the tree folder of the HMI device of a one-device repo


def hmi_folders(device, kind, folder):
    """The tree folders of an HMI document: its device ('HMI' in a one-device repo), TIA's folders for its kind,
    then its own TIA folders (a/b)."""
    return [device or DEVICE] + FOLDERS.get(kind, [kind]) + (folder.split('/') if folder else [])


def count(node):
    return len(node['objs']) + sum(count(c) for c in node['dirs'].values())


def tree_items(node):
    """Folders first, then objects, each by name (as TIA sorts them); a node's sub-folders in its order. A folder's
    'n' in place of its count, 'shut' to start collapsed."""
    order = node.get('order') or {}
    out = []
    for name in sorted(node['dirs'], key=lambda n: (order.get(n, 3), n.casefold())):
        sub = node['dirs'][name]
        out.append('<li class="fd%s"><span class="fn"><span class="nm">%s</span><span class="n">%s</span></span>'
                   '<ul>%s</ul></li>' % (' shut' if sub.get('shut') else '', escape(name), sub.get('n', count(sub)),
                                         tree_items(sub)))
    out += [li for _, _, li in sorted(node['objs'], key=lambda o: (o[0].casefold(), o[1]))]
    return ''.join(out)


def node(top, folders, order=None):
    """The tree node of folders below top, made as needed; order: the order of the first folder's sub-folders (a
    device's)."""
    n = top
    for k, f in enumerate(folders):
        n = n['dirs'].setdefault(f, {'dirs': {}, 'objs': []})
        if k == 0 and order and not n.get('order'):
            n['order'] = order
    return n


def nav_html(top, example='prfd finds PrepareFillData'):
    """The rail: its head with the key list and strip buttons, the search box and the tree of top."""
    return ('<nav class="rail" aria-label="Project tree"><div class="rh"><b>Project tree</b><button type="button" '
            'class="rq" title="List every key (?)" aria-label="List every key">?</button><button type="button" '
            'class="rt" title="Hide or show the project tree (Ctrl+B)" aria-label="Hide or show the project tree">'
            '</button></div><div class="rs"><input type="search" placeholder="Search" aria-label="Search objects" '
            'title="Letters of the name in order (%s); Enter opens, Esc clears. '
            'Ctrl+K or / opens this search over the page, ? lists every key" '
            'spellcheck="false" autocomplete="off"></div><div class="nf">No object found</div>'
            '<ul class="tree">%s</ul></nav>' % (escape(example), tree_items(top)))
