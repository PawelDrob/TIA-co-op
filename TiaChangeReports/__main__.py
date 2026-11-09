"""python TiaChangeReports <before> <after> [<before> <after> ...] [--git REPO REV1 [REV2] ...] -o out.html
                         [--block NAME ...] [--network TITLE ...] [--all] [--new-blocks-listed] [--fragment] [--png out.png [--width N]] [--lang en-US]
                         [--only plc|hmi] [--before-set tia|generated] [--after-set tia|generated] [--json]

(from the repo root)

<before> / <after>: an export file (.s7dcl, its .s7res beside it) or an export folder (a project repo: every
.s7dcl under it, paired by path, else by file name, else a renamed block by kind and number or content). A
program block and the library type of its name with the same change show as the program block alone.
Several pairs go on one page in the given order.
What is read of a project repo: a folder or --git repo with plc/, hmi/ and library/ at its root, and every
export under them where such a repo holds one, reads only the paths under plc/, hmi/, project/, library/types/, library/faceplates/, library/mastercopies/ and library/global/
from the repo's root, at any depth under them. A block or tag table anywhere else (logs/, archives/, gen/, ...) is not
compared and is named as skipped and on the page, which then does not say "No changes."; library/changes/ (a library
review's working copies) goes unnamed. Any other folder or repo is read whole, but for the dot folders at its top.
HMI: the hmi/ folder of two folders or of a --git repo's revisions goes on the same page after the blocks (hmi.py,
compared by hmipreview: screens, templates, pop-ups drawn before | after with their changes, tag tables, text lists,
cycles and connections with theirs): every changed HMI object, with --all also the unchanged ones; not with --block
or --network. --only plc / --only hmi: one part alone. --before-set / --after-set generated: that side with the
generated documents (hmi/generated/) in place of the TIA exports of the same name, e.g. the review before an import:
--git REPO HEAD --after-set generated.
PLC tag tables: the plc/tags/ of two folders or of a --git repo's revisions go on the same page between the blocks and the
HMI objects (plctags.py): per PLC and table the tags and user constants added, removed and changed, in TIA's columns; a
new table is drawn with its tags as added, a deleted one with them as removed. Part of --only plc; not with --block
or --network.
--git: two revisions of a git repo (a project repo with its exports committed), only the blocks with a file changed
between them; REV2 default: the working tree. Repeatable; the revisions come after the path pairs on the page. The page
says under its title that a change never exported is not in it.
Other files (otherfiles.py): a changed file under those export folders that nothing of the report reads (.xlsx, .dat,
.json, a watch table, ...) is named on the page, "n other files changed, not read", which then does not say "No changes.";
what differs only in the export time stays silent, as do a library type's version told on the page, with its release
comment, hmi/references/ and hmi/generated/, and graphics.json, panel.json and handbuilt.json at hmi/ or a device's
folder. A file the page names as not compared is not on the line too, but stays in otherFiles. Over ten files, the line
gives a count per kind (the extension, else the file name) and the names fold open on a click. Of a folder or repo with none of plc/, hmi/, library/ at its root:
any changed file it does not read. Not with --block or --network, and --only keeps its own part.

Writes every changed block: block properties (version, ...) and interface (members added / removed / changed) apart,
marked apart in the summary, the list and --json, and each changed
network before | after: LAD as TIA-style ladder with the logic diff marked, SCL as a side-by-side line diff.
A new block shows its members and code as added, a deleted block (a library type too) as removed;
--new-blocks-listed lists a new or deleted block and a new or deleted PLC tag table by their heading only, for a very
large change, in the list and --json too; a block's content is drawn with --block, --network or --all, a table's
with --all. --network limits the
networks to those titles and the blocks to those holding one, --all shows unchanged networks and blocks
too. A named block or network shows also when unchanged; an unchanged named block with all its networks. --fragment writes only the <div class="ldiff"> to
paste into a report. --png also writes a screenshot of the page (headless Edge or Chrome, as hmipreview png); a page
taller than 16000 px in several, out-1.png, out-2.png, ..., cut between blocks (a taller block between networks),
listed after the page; a LAD network drawn below 70 % side by side is drawn there before above after at the
full width.
--json prints the result as one JSON object (page, before, after, blocks; plcTags when a table changed; skipped when a
file was; otherFiles when any; png: the PNGs)
instead of the list.
A file of a folder or revision that holds a block but is no block export (a global library type's version metadata),
or a block that does not parse, or one outside a project repo's export folders, is skipped: named once on stderr ("skipped <path>: <why>"), the rest is written.
The page names it too and does not say "No changes." over it, but for such a metadata file that is the same on both
sides. So is a tag table that cannot be read; one locked on a side is no table on the page, as nothing
tells whether it changed, is new or moved.
A --block name or --network title the inputs do not hold, changed or not, nor a file named as unread may, is
named on stderr ("--block X: no block of that name"; a title in the blocks --block selects) and in --json
(unmatched: {blocks, networks}).
Output is UTF-8, also into a pipe or file. Exit code 0, 2 on a usage error (also an -o or --png that cannot be
written, found before the inputs are read, and a file named as <before> / <after> that is no block export: another
file, a .s7res, an empty or broken .s7dcl, a tag table; and a file paired with a folder: give two
files or two folders), and on an HMI file or folder that cannot be read: named on stderr ("cannot read
<path>: <why>"), nothing written.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from TiaChangeReports.compare import compare_snapshots     # noqa: E402
from TiaChangeReports.page import FROM_COMMITS, FROM_WORKING_TREE, NET_NOT_SHOWN, NOT_SHOWN, listed, render    # noqa: E402
from TiaChangeReports.source import git_snapshots, not_compared, skipped, snapshot  # noqa: E402
from TiaChangeReports.otherfiles import other_files        # noqa: E402
from TiaChangeReports import hmi, plctags, s7dcl           # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(prog='TiaChangeReports')
    p.add_argument('paths', nargs='*', metavar='before after', help='export file or folder, in pairs')
    p.add_argument('--git', action='append', nargs='+', metavar='REPO REV1 [REV2]',
                   help='two revisions of a git repo (REV2 default: the working tree); repeatable')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--block', action='append',
                   help='block name (repeatable; a renamed block by either name); default: every changed block')
    p.add_argument('--network', action='append', help='network title (repeatable); default: every changed network')
    p.add_argument('--all', action='store_true', help='also unchanged networks, blocks and PLC tag tables')
    drawn_group = p.add_mutually_exclusive_group()
    drawn_group.add_argument('--new-blocks-listed', dest='draw_added_removed', action='store_false',
                             help="a new or deleted block and a new or deleted PLC tag table by their heading "
                                  "only, not their members, code and tags")
    drawn_group.add_argument('--new-blocks', dest='draw_added_removed', action='store_true',
                             help='the default: kept for older calls')
    p.set_defaults(draw_added_removed=True)
    p.add_argument('--fragment', action='store_true', help='write only the <div class="ldiff"> to paste into a page')
    p.add_argument('--title', help='page title')
    p.add_argument('--png', help='also write a PNG of the page')
    p.add_argument('--width', type=int, default=1400, help='PNG width in px (default 1400)')
    p.add_argument('--lang', default='en-US', help='text language of titles and comments (default en-US)')
    p.add_argument('--json', action='store_true', help='print the result as JSON')
    p.add_argument('--only', choices=('plc', 'hmi'), help='only the PLC blocks and tag tables or only the HMI objects')
    p.add_argument('--before-set', choices=('tia', 'generated'), default='tia',
                   help='HMI before side: the TIA exports (default) or with the generated documents in their place')
    p.add_argument('--after-set', choices=('tia', 'generated'), default='tia', help='HMI after side, as --before-set')
    a = p.parse_args(argv)
    s7dcl.LANG = a.lang
    if len(a.paths) % 2:
        print('before and after paths come in pairs', file=sys.stderr)
        return 2
    if not a.paths and not a.git:
        print('nothing to compare: give before and after paths or --git', file=sys.stderr)
        return 2
    if any(len(g) not in (2, 3) for g in a.git or []):
        print('--git takes a repo and one or two revisions', file=sys.stderr)
        return 2
    for b, af in zip(a.paths[::2], a.paths[1::2]):
        if os.path.isdir(b) != os.path.isdir(af) and os.path.exists(b) and os.path.exists(af):
            print('a file and a folder: give two files or two folders (%s, %s)' % (b, af), file=sys.stderr)
            return 2
    for opt, path in (('-o', a.out), ('--png', a.png)):
        why = path and _unwritable(path)
        if why:
            print('cannot write %s %s: %s' % (opt, os.path.abspath(path), why), file=sys.stderr)
            return 2
    plc_on, hmi_on = a.only != 'hmi', a.only != 'plc' and not (a.block or a.network)
    tags_on = plc_on and not (a.block or a.network)
    inputs = [(lambda b=b, af=af: (snapshot(b), snapshot(af)), lambda b=b, af=af: hmi.sides_of(b, af, folders=True))
              for b, af in zip(a.paths[::2], a.paths[1::2])]
    inputs += [(lambda g=g: git_snapshots(*g), lambda g=g: hmi.sides_of(*g)) for g in a.git or []]
    diffs, lb, la, snaps, hmi_pairs, tables, plc_not_compared, compared_inputs = [], [], [], [], [], [], [], []
    found = {'blocks': set(), 'networks': set()}
    for load, load_hmi in inputs:
        try:
            if plc_on:
                before, after = load()
                lb.append(before.label)
                la.append(after.label)
                diffs += compare_snapshots(before, after, set(a.block) if a.block else None,
                                           set(a.network) if a.network else None, a.all, found)
                if tags_on:
                    tables += plctags.compare(before, after)
                snaps += [before, after]
                plc_not_compared += not_compared(before, after)
            pair = load_hmi() if hmi_on else None
            if tags_on or pair:
                compared_inputs.append((before, after) if plc_on else load())
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        if pair:
            hmi_pairs.append(pair)
    try:
        compared = hmi.compare(hmi_pairs, a.before_set, a.after_set, a.all)
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 2
    part = hmi.HmiPart(compared, a.all) if hmi_pairs else None
    tag_part = plctags.PlcTagPart(tables, a.all, a.draw_added_removed)
    if not plc_on and part is not None:              # an HmiPart with nothing to list is falsy (__len__)
        lb, la = [x.before for x in part.results], [x.after for x in part.results]
    hmi_skipped = [x for res in (part.results if part is not None else ()) for x in res.skipped]
    all_skipped = skipped(snaps) + hmi_skipped
    for path, why in all_skipped:                        # no block export, or unreadable
        print('skipped %s: %s' % (path, why), file=sys.stderr)
    not_compared_files = plc_not_compared + hmi_skipped
    others = _other_files(compared_inputs, hmi_pairs, a, {path for path, why in all_skipped},
                          [(d.path_b, d.path_a) for d in diffs if d.path_b and d.path_a and d.path_b != d.path_a])
    named = {path for path, why in not_compared_files}   # on the page already, by why; counted in --json
    unmatched = _unmatched(a, found)
    for name in unmatched['blocks']:                     # a typo, not an unchanged block
        print('--block %s: no block of that name' % _arg(name), file=sys.stderr)
    for title in unmatched['networks']:
        print('--network %s: no network of that title%s' % (_arg(title), ' in the given blocks' if a.block else ''),
              file=sys.stderr)
    full = bool(a.block or a.network) or a.all
    html = render(diffs, '; '.join(lb), '; '.join(la), fragment=a.fragment, title=a.title,
                  full=full, hmi=part, lang=a.lang, draw_added_removed=a.draw_added_removed, plc_tags=tag_part,
                  not_compared=not_compared_files, source_note=_source_note(a.git),
                  other_files=[p for p in others if p not in named])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    res = {'page': os.path.abspath(a.out), 'before': '; '.join(lb), 'after': '; '.join(la),
           'blocks': [_block(d, full, a.draw_added_removed) for d in diffs]}
    if tag_part:
        res['plcTags'] = tag_part.json()
    if part is not None:
        res['hmi'] = part.json()
    if all_skipped:
        res['skipped'] = [{'path': path, 'reason': why} for path, why in all_skipped]
    if others:
        res['otherFiles'] = others
    if unmatched['blocks'] or unmatched['networks']:
        res['unmatched'] = unmatched
    if a.png:
        res['png'] = shoot(a.out, a.png, a.width)
    if a.json:
        print(json.dumps(res))
        return 0
    for d in diffs:
        name, was = d.names                              # the page header's names
        if d.state == 'moved' and not full:
            print('%-8s %-11s %s  (from %s to %s)' % (d.state, d.kind, name, d.path_b.rsplit('/', 1)[0],
                                                      d.path_a.rsplit('/', 1)[0]))
            continue
        head_only = listed(d, full, a.draw_added_removed)
        print('%-8s %-11s %s%s' % (d.state, d.kind, name, ('  (was "%s")' % was if was else '')
                                   + ('  (interface)' if d.itf_changed and not head_only else '')
                                   + ('  (properties)' if d.props_changed else '')
                                   + ('  (declaration: %s -> %s)' % d.declaration if d.declaration else '')
                                   + ('  (%s)' % NOT_SHOWN if d.not_shown else '')
                                   + ('  (%slibrary type %s)' % ('differs from ' if d.library_differs else '',
                                                                 d.library.name) if d.library else '')))
        for x in () if head_only else d.nets:
            print('    %-8s %-3s %5s -> %-5s %s' % (x.state, x.lang, x.before.index if x.before else '-',
                                                   x.after.index if x.after else '-', x.title)
                  + ('  (was "%s")' % x.before.title if x.renamed else '') + ('  (moved)' if x.moved else '')
                  + ('  (other order)' if x.reordered else '')
                  + ('  (%s)' % NET_NOT_SHOWN if x.not_shown else ''))
    for line in tag_part.lines() + (part.lines() if part is not None else []):
        print(line)
    for path in others:
        print('%-8s %-11s %s' % ('changed', 'not read', path))
    print(res['page'])
    for png in res.get('png', ()):
        print(png)
    return 0


def _source_note(gits):
    """What the page says of its --git inputs: what was never committed is not in a comparison of two revisions."""
    if not gits:
        return None
    return FROM_COMMITS if all(len(g) == 3 for g in gits) else FROM_WORKING_TREE


def _other_files(inputs, hmi_pairs, a, not_read, moved):
    """The changed files the report did not read, of every input (otherfiles.py), each once: under what --only keeps."""
    read = hmi.read_paths(hmi_pairs, a.before_set, a.after_set)

    def keep(path):
        return not hmi.beside_exports(path) and a.only != ('plc' if path.startswith(hmi.ROOTS) else 'hmi')
    return list(dict.fromkeys(p for before, after in inputs for p in other_files(before, after, read, not_read, keep, moved)))


def _unwritable(path):
    """Why `path` cannot be written (a folder, read-only, open in another program, under a file), else None: checked
    before the inputs are read. Makes its folder; a file it had to make for the check is removed."""
    if os.path.isdir(path):
        return 'is a folder'
    existed = os.path.exists(path)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        open(path, 'a').close()
    except OSError as ex:
        return ex.strerror or str(ex)
    if not existed:
        os.remove(path)
    return None


def _unmatched(a, found):
    """The --block names and --network titles the inputs do not hold (found: compare_snapshots'), in the given order."""
    return {key: [n for n in dict.fromkeys(names or ()) if n not in found[key]]
            for key, names in (('blocks', a.block), ('networks', a.network))}


def _arg(name):
    return '"%s"' % name if not name or re.search(r'\s', name) else name


def _version(v):
    return {'number': v.number, 'inWork': v.in_work} if v else None


def _names(d):
    """name, and was when renamed: the declared names, as the page header."""
    name, was = d.names
    return {'name': name, **({'was': was} if was else {})}


def _block(d, full=False, draw_added_removed=True):
    lib = d.library
    head_only = listed(d, full, draw_added_removed)      # as on the page
    nets = () if head_only else d.nets
    return {**_names(d), 'kind': d.kind, 'state': d.state, 'interface': bool(d.itf_changed and not head_only),
            'properties': bool(d.props_changed),
            **({'movedFrom': d.path_b, 'movedTo': d.path_a} if d.state == 'moved' else {}),
            **({'declaration': dict(zip(('before', 'after'), d.declaration))} if d.declaration else {}),
            **({'notShown': True} if d.not_shown else {}),
            **({'libraryType': {**_names(lib), 'path': lib.path_a or lib.path_b, 'before': _version(lib.ver_b),
                                'after': _version(lib.ver_a), 'differs': d.library_differs}} if lib else {}),
            'networks': [{'state': x.state, 'lang': x.lang, 'before': x.before.index if x.before else None,
                          'after': x.after.index if x.after else None, 'title': x.title,
                          **({'was': x.before.title} if x.renamed else {}),
                          **({'moved': True} if x.moved else {}),
                          **({'reordered': True} if x.reordered else {}),
                          **({'notShown': True} if x.not_shown else {})} for x in nets]}


PART = 16000      # px: the most one PNG of --png holds

# Run in the page after its own scripts (load, then a moment): MEASURE writes the layout into <body data-png>
# for --dump-dom; KEEP hides what lies outside one part (y0, y1) before the screenshot. Positions from the top of
# the page as a whole, rounded alike in both, so a part's bounds match the measured ones exactly.
MEASURE = ("<script>addEventListener('load',function(){setTimeout(function(){var y=scrollY,"
           "r=function(e){var b=e.getBoundingClientRect();return [Math.round(b.top+y),Math.round(b.bottom+y)]},"
           "sm=document.querySelector('.ldiff .sum');document.body.setAttribute('data-png',JSON.stringify({"
           "h:document.documentElement.scrollHeight,sum:sm?r(sm)[0]:null,blocks:[].map.call("
           "document.querySelectorAll('section.blk'),function(s){var h=s.querySelector(':scope>.bh');"
           "return r(s).concat([h?r(h)[1]:r(s)[0],[].filter.call(s.children,function(c){return c!=h})"
           ".map(function(c){return r(c)[0]})])})}))},100)})</script>")
KEEP = ("<script>addEventListener('load',function(){setTimeout(function(){var y0=%d,y1=%d,y=scrollY,hide=[],"
        "r=function(e){var b=e.getBoundingClientRect();return [Math.round(b.top+y),Math.round(b.bottom+y)]};"
        "[].forEach.call(document.querySelectorAll('section.blk'),function(s){var b=r(s);"
        "if(b[1]<=y0||b[0]>=y1)hide.push(s);else [].forEach.call(s.children,function(c){var t=r(c)[0];"
        "if(!c.classList.contains('bh')&&(t<y0||t>=y1))hide.push(c)})});"
        "var sm=document.querySelector('.ldiff .sum');if(y0&&sm)hide.push(sm);"
        "hide.forEach(function(e){e.style.display='none'})},100)})</script>")


def shoot(html, png, width):
    """PNGs of the page, every object in a row, as printed (`?all`), not the page's one object at a time.
    Measured first; a page taller than PART gives several (`<name>-1.png`, ...), cut between blocks, a block taller
    than a part between its networks with its header again; the title, column header and legend on each, the
    summary on the first. Each part shot from a copy of the page that hides the rest, cropped at the empty bottom
    (Pillow). `&png`: a LAD network too small side by side is drawn before above after (page.FOCUS_JS). Returns
    their paths."""
    import shutil
    import tempfile
    from html import unescape
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'TiaHmiGenerator'))
    from hmipreview.edge import Edge
    with open(html, encoding='utf-8') as f:
        text = f.read()
    tmp = tempfile.mkdtemp(prefix='tcr-png-')
    copy = os.path.join(tmp, os.path.basename(html))
    url = 'file:///' + os.path.abspath(copy).replace('\\', '/') + '?all&png'

    def page(script):
        with open(copy, 'w', encoding='utf-8') as f:
            f.write(text.replace('</body>', script + '</body>') if '</body>' in text else text + script)

    e = Edge()
    try:
        page(MEASURE)
        m = re.search(r'data-png="([^"]*)"', e.dump_dom(url, timeout=120, size=(width, 1000)))
        if not m:
            raise RuntimeError('--png: the page did not measure in the browser')
        parts = _parts(json.loads(unescape(m.group(1))), PART)
        pngs = _png_names(os.path.abspath(png), len(parts))
        for (y0, y1, h), out in zip(parts, pngs):
            page(KEEP % (y0, y1))
            for slack in (300, h):                       # shot taller than the part, cropped; once more if cut
                e.screenshot(url, out, width, h + slack, timeout=120)
                if _crop(out, h):
                    break
    finally:
        e.close(ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    if len(pngs) > 1 and os.path.isfile(png):            # a single PNG of an earlier run would pass for this one
        os.remove(png)
    return pngs


def _parts(m, part):
    """[(y0, y1, height)]: the page cut into parts of at most `part` px from its layout (m: MEASURE's). A cut at a
    block's top; inside a block taller than a part also at a network's top (never before its first one: no part
    with a header alone). A part after the first repeats what lies above the summary (title, column header,
    legend), one that starts inside a block that block's header; a network taller than a part is one part."""
    blocks, end = m['blocks'], m['h']
    over = m['sum'] if m['sum'] is not None else blocks[0][0] if blocks else 0
    cuts = {b[0] for b in blocks} | {end}
    for top, bottom, _, nets in blocks:
        if bottom - top + over > part:
            cuts |= set(nets[1:]) | {bottom}
    cuts = sorted(cuts)
    out, y = [], 0
    while y < end:
        inside = next((b for b in blocks if b[0] < y < b[1]), None)
        extra = (over if y else 0) + (inside[2] - inside[0] if inside else 0)
        y1 = max([c for c in cuts if y < c <= y + part - extra] or [min(c for c in cuts if c > y)])
        out.append((y, y1, y1 - y + extra))
        y = y1
    return out


def _png_names(png, n):
    """--png's path for one part, `<name>-1.png` ... for several."""
    root, ext = os.path.splitext(png)
    return [png] if n == 1 else ['%s-%d%s' % (root, k, ext) for k in range(1, n + 1)]


def _crop(png, h):
    """Crop the empty bottom of the shot, keeping a margin up to the part's height h; False when the page reaches
    the bottom (the window was too low)."""
    from PIL import Image
    im = Image.open(png).convert('RGB')
    bg = im.getpixel((2, im.height - 2))
    px = im.load()
    y = im.height - 1
    while y > 0 and all(px[x, y] == bg for x in range(0, im.width, 7)):
        y -= 1
    im.crop((0, 0, im.width, min(im.height, max(y + 1, min(y + 20, h))))).save(png)
    return y < im.height - 20


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')   # a pipe on Windows is cp1252: any title in the list
    sys.exit(main())
