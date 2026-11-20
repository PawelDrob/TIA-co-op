"""The viewer's page of one block export: the block drawn in one column, as the change report draws it, and the source
text of its file; a file it cannot read shows its source with the reason.

page(path) -> (html, title). Self-contained: nothing is fetched. The drawing is the report's: its styles and script
(page.CSS, page.JS), the interface table (iface.html), the ladder in its frame (render_lad.Layout, page._lad_pane), the
text of an SCL network (s7dcl.scl_lines). The title bar, comment field and text table are the report's classes in one
column, written here. A LAD network's SVG is the one the report draws for it unchanged (test_viewer holds them to
the same bytes). Calls and types are read from the project the file is in (project_root), as the report reads them
from the folder it compares."""
import os
import xml.etree.ElementTree as ET
from dataclasses import replace
from html import escape
from types import SimpleNamespace

from TiaChangeReports import iface
from TiaChangeReports.compare import BlockDiff, Callees
from TiaChangeReports.page import CSS, FOLD_ALL, JS, _lad_pane, folds, version_html
from TiaChangeReports.render_lad import Layout
from TiaChangeReports.s7dcl import LANG, parse_block, scl_lines
from TiaChangeReports.simaticml import parse_interface
from TiaChangeReports.source import REPO_MARKS, FolderSnapshot, from_file, name_of

EXTENSIONS = ('.s7dcl', '.xml')
NO_MARKS = SimpleNamespace(status={}, other={})   # a network's diff with nothing changed


def project_root(path):
    """The folder the viewer reads a block's calls and types from: the nearest folder above the file that holds a
    project repo's plc, hmi and library folders, else the nearest git repo's top, else the file's own folder."""
    folder = os.path.dirname(os.path.abspath(path))
    for marks in (REPO_MARKS, ('.git',)):
        d = folder
        while True:
            if all(os.path.exists(os.path.join(d, m)) for m in marks):
                return d
            up = os.path.dirname(d)
            if up == d:
                break
            d = up
    return folder


def block_of(path):
    """(the parsed block with its calls' interfaces, its BlockSource, the root it reads calls from, its path from that
    root). Raises what the readers raise for a file that is no block export."""
    if os.path.splitext(path)[1].lower() not in EXTENSIONS:
        raise ValueError('not a block export: an .s7dcl, or the SimaticML .xml of a block')
    src = from_file(path)
    if src.xml is None and os.path.splitext(path)[1].lower() == '.xml':     # from_file reads a lower-case .xml only
        src = replace(src, s7dcl='', s7res=None, xml=src.s7dcl)
    blk = parse_block(src)
    root = project_root(path)
    rel = os.path.relpath(os.path.abspath(path), root).replace(os.sep, '/')
    blk.callees = Callees(FolderSnapshot(root)).at(rel)
    return blk, src, root, rel


def _xml_db(src):
    """The SimaticML of a DB read as a global DB's: its members with their retain. The reader leaves them out of an
    instance DB and a DB of a UDT, which the .s7dcl does not repeat either; it reads only the start values set there."""
    return parse_interface(ET.fromstring(src.xml.lstrip('\ufeff').encode('utf-8')), LANG, db=True)


def own_retain(blk, src, base):
    """The retain a DB sets itself, on its members of iface.set_by_db. The .s7dcl writes it as S7_StandardRetain, a
    SimaticML export on each such member."""
    if src.xml is None:
        return blk.props.get('S7_StandardRetain', '').upper() == 'TRUE'
    own = _xml_db(src).root.children
    return any(own[k].retain is True for k, m in base.root.children.items() if k in own and iface.set_by_db(m))


def lad_svg(net, blk):
    """A LAD network's SVG in its frame, as the report draws an unchanged one: at TIA's 100 %, never wider than the
    window."""
    return _lad_pane(Layout(net.rungs, blk.interface, blk.callees, net.label), None, NO_MARKS)


def _lines_table(lines):
    """Text with its line numbers, as one side of the report's SCL table."""
    rows = ''.join('<tr><td class="ln">%d</td><td>%s</td></tr>' % (k, escape(line) or '&#8203;')
                   for k, line in enumerate(lines, 1))
    return '<table class="scl"><colgroup><col style="width:3.2em"><col></colgroup>%s</table>' % rows


def network_html(net, blk):
    """One network, as one side of the report's: title bar, comment field, the ladder or the text."""
    title = ('<div class="nwt"><span class="side"><span class="no">Network %d:</span><span class="ti">%s</span>'
             '</span></div>' % (net.index, escape(net.title)))
    comment = ('<span class="cf">%s</span>' % escape(net.comment) if net.comment
               else '<span class="cf none">Comment</span>')
    if net.lang == 'LAD' and net.rungs is not None:
        body = '<div class="panes"><div class="pane"><div class="pb">%s</div></div></div>' % lad_svg(net, blk)
    else:
        body = _lines_table(scl_lines(net.body))
    return '<div class="nw">%s<div class="nwc"><span class="side">%s</span></div>%s</div>' % (title, comment, body)


def _props_html(blk):
    """Every block property the file holds, as the report's property list."""
    rows = iface.props_rows({}, blk.props)
    if not rows:
        return ''
    return ('<div class="nw itfw"><div class="nwh"><b>Properties</b></div><table class="itf"><tr class="sec"><td '
            'colspan="4">Block properties</td></tr>%s</table></div>'
            % ''.join('<tr><td class="nm">%s</td><td colspan="3">%s</td></tr>' % (escape(n), escape(a or ''))
                      for n, _, a in rows))


def heading(blk):
    """The block's name and kind as the report's block header writes them: Name [FB12]."""
    d = BlockDiff(None, None, blk, blk, [], False, 'same')
    return '%s [%s%s]' % (d.name, d.kind, blk.props.get('S7_BlockNumber') or '')


def _type_html(name, itf, root, table):
    """An instance DB's or a DB of a UDT's interface: the file its members come from (itf, the FB's or UDT's), which
    start values are its own, and the table; or that its members could not be read, above the start values the DB sets
    (table)."""
    if itf is None:
        return ('<div class="of none">Instance of %s: its members could not be read, the project holds no FB or UDT of '
                'that name.</div>%s' % (escape(name), table))
    kind = 'UDT' if itf.block.kind == 'TYPE' else 'FB'
    path = os.path.relpath(itf.block.label, root).replace(os.sep, '/')
    head = 'Members of %s %s, from %s.' % (kind, escape(name), escape(path))
    if not table:
        return '<div class="of">%s</div><div class="empty">The %s declares no members.</div>' % (head, kind)
    return ('<div class="of">%s A start value in black is the DB\'s own, one in grey the %s\'s default.</div>%s'
            % (head, kind, table))


def block_html(blk, src, rel, root):
    """The block drawn: header, properties, interface, every network. The report's Collapse all and Expand all when
    something folds. An instance DB or a DB of a UDT with the members of its FB or UDT (from root), and a line saying
    from which file, or that they could not be read."""
    name, base = iface.db_type(blk)
    db = None if name is None else base is not None and own_retain(blk, src, base)     # None: no DB of a type
    itf = iface.html(blk, blk, whole=True, db=db)
    parts = ['<div class="bh"><b>%s</b>%s<span class="paths">%s</span>%s</div>'
             % (escape(heading(blk)), version_html(src.version, src.version), escape(rel),
                FOLD_ALL if blk.networks or folds(itf) else ''),
             _props_html(blk)]
    if name:
        itf = _type_html(name, base, root, itf)
    if itf:
        parts.append('<div class="nw itfw"><div class="nwh"><b>Interface</b><span class="tag">DECLARATION</span></div>'
                     '%s</div>' % itf)
    parts += [network_html(n, blk) for n in blk.networks]
    if not blk.networks and not itf:
        parts.append('<div class="empty">No members and no networks.</div>')
    return '<section class="blk">%s</section>' % ''.join(parts)


def _read_text(path):
    """(text, None), or (None, why) when the file cannot be read."""
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            return f.read(), None
    except OSError as ex:
        return None, ex.strerror or str(ex)


def sources(path):
    """[(file name, text or None, why)]: the file, and the .s7res beside an .s7dcl when there is one."""
    out = [(os.path.basename(path),) + _read_text(path)]
    res = os.path.splitext(path)[0] + '.s7res'
    if path.lower().endswith('.s7dcl') and os.path.isfile(res):
        out.append((os.path.basename(res),) + _read_text(res))
    return out


def source_html(path):
    parts = []
    for name, text, why in sources(path):
        body = (_lines_table(text.split('\n') if not text.endswith('\n') else text[:-1].split('\n'))
                if text is not None else '<div class="empty">Cannot read this file: %s</div>' % escape(why))
        parts.append('<div class="nw"><div class="nwh"><b>%s</b></div>%s</div>' % (escape(name), body))
    return ''.join(parts)


def why_unreadable(ex, path):
    """An error of the readers as one line for the page, without the file's path: an error of the system its text
    alone (No such file or directory)."""
    if isinstance(ex, OSError) and ex.strerror:
        return ex.strerror
    why = str(ex) or type(ex).__name__
    for p in (os.path.abspath(path), path):
        if why.startswith(p + ': '):
            why = why[len(p) + 2:]
    return why


# The viewer's own look, around the report's: a bar with the file and the switch, the report's block in one column.
PAGE_CSS = """
body{margin:0;background:#fff;font:13px/1.45 "Segoe UI",Arial,Helvetica,sans-serif;color:#000}
.vbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:6px 14px;flex-wrap:wrap;background:#f0f0f0;
  border-bottom:1px solid #c8c8c8;padding:6px 16px}
.vbar .file{font-size:12.5px;color:#595959;word-break:break-all}
.vbar .sw{display:inline-flex;margin-left:auto}
.vbar .sw button{font:12px "Segoe UI",Arial,sans-serif;color:#000;background:#fbfbfb;border:1px solid #adadad;padding:3px 14px;
  cursor:pointer}
.vbar .sw button+button{border-left:0}
.vbar .sw button[aria-pressed=true]{background:#d9d9d9;font-weight:600}
.vbar .sw button:disabled{color:#a0a0a0;cursor:default}
main{padding:0 16px 40px}
.why{margin:12px 0;padding:8px 12px;background:#fde7e9;border:1px solid #c42b1c;white-space:pre-wrap;word-break:break-word}
.view[hidden]{display:none}
.read{margin:4px 0 0;font-size:12px;color:#595959}
.ldiff .of{padding:3px 8px;font-size:12px;color:#595959;word-break:break-word}
.ldiff .of.none{background:#fde7e9;color:#000}
.ldiff .nwt,.ldiff .nwc,.ldiff .panes{grid-template-columns:1fr}
.ldiff .nwc .side{padding-left:30px}
.ldiff .src .nw table.scl td{white-space:pre-wrap}
.ldiff .src .nwh b{font:13px Consolas,"Courier New",monospace}
"""

# The switch: Drawing / Source, by its buttons or D and S. A file opens on its drawing, one that cannot be drawn on its
# source; the source shown is #source in the address, so that a reload keeps it. C and E press Collapse all and Expand
# all while the drawing shows, as in the report.
SWITCH_JS = """
(function(){var bs=document.querySelectorAll('.vbar .sw button'),vs={};
document.querySelectorAll('.view').forEach(function(v){vs[v.getAttribute('data-view')]=v});
function show(k,keep){if(!vs[k]||document.querySelector('.vbar .sw button[data-view='+k+']').disabled)return;
 bs.forEach(function(b){b.setAttribute('aria-pressed',b.getAttribute('data-view')==k?'true':'false')});
 for(var x in vs)vs[x].hidden=x!=k;if(keep)history.replaceState(null,'',k=='source'?'#source':location.pathname)}
bs.forEach(function(b){b.onclick=function(){show(b.getAttribute('data-view'),true)}});
var fa=document.querySelectorAll('.view[data-view=drawing] .bh .fa button');
fa.forEach(function(b,k){b.title+=k?' (E)':' (C)'});
document.addEventListener('keydown',function(e){if(e.ctrlKey||e.altKey||e.metaKey||/^(INPUT|TEXTAREA)$/.test(e.target.tagName))return;
 var c=e.key.toLowerCase(),k={d:'drawing',s:'source'}[c],f={c:0,e:1}[c];if(k){e.preventDefault();show(k,true)}
 else if(f!==undefined&&fa[f]&&!vs.drawing.hidden){e.preventDefault();fa[f].click()}});
if(location.hash=='#source')show('source',false)})();
"""


def page(path):
    """(html, title) of the viewer's page of path. A file the readers cannot draw opens on its source, with why."""
    path = os.path.abspath(path)
    drawing, why, title = None, None, os.path.basename(path)
    try:
        blk, src, root, rel = block_of(path)
        drawing = block_html(blk, src, rel, root)
        title = heading(blk)
        read = '<p class="read">Calls and types read from %s</p>' % escape(name_of(root))
    except Exception as ex:                              # noqa: BLE001 - any error of this file: its source, with why
        why = why_unreadable(ex, path)
    button = '<button type="button" data-view="%s" aria-pressed="%s" title="%s (%s)"%s>%s</button>'
    switch = ('<span class="sw" role="group" aria-label="View">%s%s</span>'
              % (button % ('drawing', 'true' if drawing else 'false', 'The block drawn', 'D', '' if drawing else ' disabled',
                           'Drawing'),
                 button % ('source', 'false' if drawing else 'true', 'The text of the file', 'S', '', 'Source')))
    bar = '<header class="vbar"><b>%s</b><span class="file">%s</span>%s</header>' % (
        escape(title), escape(path), switch)
    shown = ('<div class="view" data-view="drawing"><div class="ldiff" data-page>%s%s<script>%s</script></div></div>'
             % (drawing, read, JS) if drawing else '')
    source = ('<div class="view" data-view="source"%s><div class="ldiff src">%s%s</div></div>'
              % (' hidden' if drawing else '',
                 '<div class="why">This file cannot be drawn: %s</div>' % escape(why) if why else '', source_html(path)))
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, '
            'initial-scale=1"><title>%s</title><style>%s</style><style>%s</style></head><body>%s<main>%s%s</main>'
            '<script>%s</script></body></html>'
            % (escape(title), CSS, PAGE_CSS, bar, shown, source, SWITCH_JS))
    return html, title
