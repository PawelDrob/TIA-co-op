"""GET /api/tree[?against=off|commit|export]: the project tree of the preview, the change report's rail
(rail.py) over every HMI device of the repo: per device TIA's folders (Screens, Screen management > Templates /
Pop-up screens, Text and graphic lists) and the documents' own TIA folders, each document once by its name.

Answer: {rail: the <nav class="rail"> markup, launcher: the lookup window, devices: the device folders ([] in the
one-device layout), device: the folder the server shows without ?device=, against}. A document's link carries
data-device, data-kind, data-name and data-origin; its class is the change report's state against the base of
`against` (diff.states: new, changed, same) or none with the diff off. Its address (data-key) is
<device>:<kind>:<name>, <kind>:<name> in the one-device layout.
"""
from html import escape
from urllib.parse import quote, urlencode

from . import model, rail
from .server import HttpError, json_response, route

AGAINST = ('off', 'commit', 'export')
ORIGIN_TEXT = {model.GENERATED: 'Generated', model.EXPORT: 'Exported'}     # the maintainer's words, as in the header
STATE_TEXT = {'new': 'new', 'changed': 'changed', 'same': 'no change'}
BASE_TEXT = {'commit': 'against the last commit', 'export': 'against the TIA export'}


def item_li(i, device, doc, multi, state, against):
    key = ('%s:%s:%s' % (device, doc.kind, doc.name)) if multi else '%s:%s' % (doc.kind, doc.name)
    href = '?' + urlencode(([('device', device)] if multi else []) + [(doc.kind, doc.name)], quote_via=quote)
    kind = rail.KIND_TEXT.get(doc.kind, doc.kind)
    tip = '%s, %s: %s' % (kind, ORIGIN_TEXT[doc.origin], doc.path)
    if state != 'none':
        tip += '\n%s %s' % (STATE_TEXT[state], BASE_TEXT[against])
    return ('<li><a class="obj %s" href="%s" data-i="%d" data-key="%s" data-device="%s" data-kind="%s" '
            'data-name="%s" data-origin="%s" title="%s"><span class="mk"></span><span class="nm">%s</span>'
            '<span class="k">%s</span></a></li>'
            % (state, escape(href), i, escape(key), escape(device), doc.kind, escape(doc.name),
               'generated' if doc.origin == model.GENERATED else 'tia', escape(tip), escape(doc.name), escape(kind)))


def tree(server, against='off'):
    """The answer of /api/tree for the server's repo."""
    folders = model.device_folders(server.repo_path)
    top = {'dirs': {}, 'objs': []}
    i = 0
    for device in folders or ['']:
        cache = server.cache_for(device or None)
        if against == 'off':
            repo, states = cache.repo(), {}
        else:
            repo, states = cache.states(against)
        if repo.device is None:
            continue
        for doc in repo.effective:
            li = item_li(i, device, doc, bool(folders), states.get((doc.kind, doc.name), 'none'), against)
            rail.node(top, rail.hmi_folders(device, doc.kind, doc.folder), rail.HMI_ORDER)['objs'].append(
                (doc.name, i, li))
            i += 1
    return {'rail': rail.nav_html(top, example='ovw finds 010 - Overview'), 'launcher': rail.LAUNCHER,
            'devices': folders, 'device': server.default_device(), 'against': against}


@route('GET', '/api/tree')
def project_tree(req):
    against = req.param('against', required=False, default='off')
    if against not in AGAINST:
        raise HttpError(400, 'against must be off, commit or export')
    return json_response(tree(req.server, against))
