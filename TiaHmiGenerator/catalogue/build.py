"""Build the screen object catalogue: catalogue.json (read by hmixml and the preview) and the docs page
docs/agent/wincc-screen-objects.md.

Inputs, all in this folder:
  toolbox.json   hand-kept: the toolbox, TIA's Properties window rows (display names, groups) transcribed from
                 screenshots, greyed-row conditions, descriptions in our own words, the preview's coverage
  fixture/       full exports (WithDefaults, WithReadOnly) of the test screens: every toolbox object dropped with no
                 setting changed, device style WinCC Dark (V20 Update 7). They decide which attributes a Comfort
                 Panel object has and their defaults.
  helpfacts.json facts from TIA's installed help (VBS object reference): per object its properties with the runtime
                 access, per property the documented values (number, VB constant, name), ranges, the mode tables.
                 No help text. Refreshed with --help-zip.
  seen.json      what full exports of project repos use: element types, attribute names and kinds, enum spellings
                 per (element, attribute), links, compositions, event names, animation types. Names and spellings
                 only, nothing project-specific. Refreshed with --seen.
  enums.json     TIA's own enum types of the Comfort screen objects (member names, which are the export
                 spellings, and numbers), read by reflection from TIA's HMI library (Siemens.Simatic.Hmi.Global.dll,
                 namespace Siemens.Simatic.Hmi.Utah.GraphX). Refreshed with --enums. toolbox.json 'enumTypes' says
                 which enum an attribute takes; a documented help value gets its export spelling from it.
  roundtrip/     the spelling round trip (roundtrip.py): sent.json (the values the zz test screens
                 zzTestSpellings and zzTestSpellings2 set, one per object) and back/ (those screens as TIA exported
                 them after the import). A value that came back is confirmed; one that came back different is lost.

Run from TiaHmiGenerator:
  python catalogue\\build.py                       rebuild from the committed inputs
  python catalogue\\build.py --help-zip "C:\\Program Files\\Siemens\\Automation\\Portal V20\\Help\\en-US\\VBSObjectsWCCCenUS.zip"
  python catalogue\\build.py --seen <repo> [--seen <repo> ...]
  python catalogue\\build.py --enums "C:\\Program Files\\Siemens\\Automation\\Portal V20\\Bin\\Siemens.Simatic.Hmi.Global.dll"
  python catalogue\\build.py --check               exit 1 when the outputs differ from a rebuild

Standard library only (--enums runs Windows PowerShell). Precedence: the fixture decides which attributes exist and
their defaults; the screenshots (toolbox.json) decide display name, group and order; the help gives allowed values;
TIA's enums give their export spellings.
"""
import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOLBOX = os.path.join(HERE, 'toolbox.json')
FIXTURE = os.path.join(HERE, 'fixture')
HELPFACTS = os.path.join(HERE, 'helpfacts.json')
SEEN = os.path.join(HERE, 'seen.json')
ENUMS = os.path.join(HERE, 'enums.json')
ROUNDTRIP = os.path.join(HERE, 'roundtrip')
OUT = os.path.join(HERE, 'catalogue.json')
DOC = os.path.join(REPO, 'docs', 'agent', 'wincc-screen-objects.md')
SCHEMA = 1
NS = 'Hmi.Screen.'

# Attributes whose value is free text or data, never an enum, whatever it looks like.
TEXT = frozenset({'ObjectName', 'Name', 'FormatPattern', 'Unit', 'Text', 'FontFamily', 'FaceplateTypeName', 'Value',
                  'Culture'})
LISTS = frozenset({'Points', 'Columns'})
BLOBS = frozenset({'OcxState'})
# Export name -> help name where they differ.
HELP_ALIAS = {'ObjectName': 'Name', 'HotKey': 'Hotkey'}
COLOUR = re.compile(r'^\d{1,3}, \d{1,3}, \d{1,3}$')
NUMBER = re.compile(r'^-?\d+(\.\d+)?$')
IDENT = re.compile(r'^[A-Z][A-Za-z0-9]*$')
ACCESS = frozenset({'R', 'RW', 'W', '-'})


def kind_of(name, value):
    """Kind of an attribute from its name and one exported value."""
    if name in TEXT:
        return 'text'
    if name in LISTS:
        return 'list'
    if name in BLOBS:
        return 'blob'
    v = (value or '').strip()
    if COLOUR.match(v):
        return 'colour'
    if v in ('true', 'false'):
        return 'bool'
    if NUMBER.match(v):
        return 'number'
    if IDENT.match(v):
        return 'enum'
    return 'text'


# ----------------------------------------------------------------------------------------------- help parsing

class _Blocks(HTMLParser):
    """Flattens a help page into blocks: ('p', text) for paragraphs and list items, ('table', rows) with rows as
    lists of (text, href) cells."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.text, self.href = [], [], None
        self.table_depth, self.rows, self.cell, self.row = 0, None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            self.table_depth += 1
            if self.table_depth == 1 and 'title' not in (a.get('class') or ''):
                self._flush()
                self.rows = []
        elif self.rows is not None and tag == 'tr':
            self.row = []
        elif self.rows is not None and tag in ('td', 'th'):
            self.cell, self.href = [], None
        elif tag == 'a' and a.get('href') and self.cell is not None and self.href is None:
            self.href = a['href']
        elif tag in ('p', 'li', 'br') and self.rows is None:
            self._flush()

    def handle_endtag(self, tag):
        if tag == 'table':
            self.table_depth -= 1
            if self.table_depth == 0 and self.rows is not None:
                self.blocks.append(('table', self.rows))
                self.rows = None
        elif self.rows is not None and tag in ('td', 'th') and self.cell is not None:
            self.row.append((' '.join(''.join(self.cell).split()), self.href))
            self.cell = None
        elif self.rows is not None and tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag in ('p', 'li') and self.rows is None:
            self._flush()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif self.rows is None:
            self.text.append(data)

    def _flush(self):
        t = ' '.join(''.join(self.text).split())
        if t:
            self.blocks.append(('p', t))
        self.text = []

    def close(self):
        super().close()
        self._flush()
        return self.blocks


def blocks(data):
    p = _Blocks()
    p.feed(data)
    return p.close()


def _toc(zf):
    """Help titles (without the device scope in brackets) -> page path, for object and property pages."""
    root = ET.fromstring(zf.read('Toc/Default.xml'))
    ns = '{http://www.siemens.com/2014/09/Automation/HelpPrototype/TocStorage}'
    objects, props = {}, {}
    for sec in root.iter(ns + 'TocEntry'):
        title = sec.get('title') or ''
        target = objects if title.startswith('Objects A-I') or title.startswith('Objects K-Z') else \
            props if title.startswith('Properties ') else None
        if target is None:
            continue
        for e in sec.findall(ns + 'TocEntry'):
            name = re.sub(r'\s*\(.*\)\s*$', '', e.get('title')).strip()
            target.setdefault(name, e.get('itemid').split('/', 1)[1])
    return objects, props


def _number(v):
    return int(v) if re.match(r'^-?\d+$', v) else v


def _expand(value, const):
    """A table row, or a range row ('196608 - 196644' | 'hmiFillStylePattern1 - hmiFillStylePattern37') expanded
    into one (value, constant) per number."""
    mv = re.match(r'^(-?\d+)\s*-\s*(-?\d+)$', value)
    mc = re.match(r'^([A-Za-z]+?)(\d+)\s*-\s*([A-Za-z]+?)(\d+)$', const)
    if mv and mc and mc.group(1) == mc.group(3):
        v0, v1, c0, c1 = int(mv.group(1)), int(mv.group(2)), int(mc.group(2)), int(mc.group(4))
        if v1 - v0 == c1 - c0 >= 0:
            return [(str(v0 + i), '%s%d' % (mc.group(1), c0 + i)) for i in range(v1 - v0 + 1)]
    return [(value, const)]


def _value_tables(bl):
    """Value tables of a property page: [{scope: [objects] or None, rows: [{value, constant, name}]}]."""
    out, last_p = [], ''
    for kind, b in bl:
        if kind == 'p':
            last_p = b
            continue
        head = [c[0] for c in b[0]] if b else []
        if not head:
            continue
        rows = []
        if len(head) >= 2 and head[1].lower().startswith('vb constant'):
            pairs = []
            for r in b[1:]:
                if len(r) >= 2:
                    pairs += _expand(r[0][0], r[1][0])
            consts = [c for v, c in pairs]
            prefix = os.path.commonprefix(consts) if len(consts) > 1 else 'hmi'
            for v, const in pairs:
                rows.append({'value': _number(v), 'constant': const, 'name': const[len(prefix):] or const})
        elif len(head) >= 2 and head[0].lower() == 'value' and head[1].lower() == 'designation':
            # "Value | Designation | Description": the number, then the name
            for r in b[1:]:
                if len(r) >= 2 and r[1][0]:
                    rows.append({'value': _number(r[0][0]), 'constant': None, 'name': r[1][0]})
        elif head[0].lower() in ('designation', 'value') and len(head) >= 2:
            for r in b[1:]:
                if not r or not r[0][0]:
                    continue
                if not re.match(r'^-?\d+$', r[0][0]):
                    rows.append({'value': None, 'constant': None, 'name': r[0][0]})
                    continue
                # "Value | Description" with numbers: the description is the name when it is one ("Rounded");
                # a sentence is help text and is not kept (the row then is no enum value)
                d = r[1][0] if len(r) > 1 else ''
                if d and len(d.split()) <= 3 and not d.endswith('.'):
                    rows.append({'value': int(r[0][0]), 'constant': None, 'name': d})
        else:
            continue
        scope = None
        if re.search(r'\bobjects?\b', last_p) and 'support' in last_p:
            scope = re.findall(r'"([A-Za-z]+)"', last_p) or None
        out.append({'scope': scope, 'rows': rows})
    return out


def parse_help(zip_path, names):
    """Facts from TIA's VBS object reference for the help object names in names: per object the property rows
    (name, access per runtime, page) and the mode table; per property page its documented values and range."""
    zf = zipfile.ZipFile(zip_path)
    objects, props = _toc(zf)
    facts = {'source': os.path.basename(zip_path), 'objects': {}, 'properties': {}}
    pages = {}
    for name in names:
        page = objects.get(name)
        if not page:
            continue
        bl = blocks(zf.read(page).decode('utf-8-sig', 'replace'))
        vbs = None
        for i, (kind, b) in enumerate(bl):
            if kind == 'p' and b.startswith('Type identifier in VBS') and i + 1 < len(bl) and bl[i + 1][0] == 'p':
                vbs = bl[i + 1][1]
        rows, modes = [], None
        for kind, b in bl:
            if kind != 'table' or not b:
                continue
            head = [c[0] for c in b[0]]
            if head and head[0] == 'Property' and len(head) > 1 and all(h.startswith('"') for h in head[1:]):
                names_m = [h.strip('"').replace(' mode', '').strip('"') for h in head[1:]]
                modes = {'modes': names_m, 'rows': {}}
                for r in b[1:]:
                    modes['rows'][r[0][0]] = [m for m, c in zip(names_m, r[1:]) if c[0].lower() == 'x']
                continue
            for r in b:
                if len(r) == 5 and all(c[0] in ACCESS for c in r[1:4]):
                    href = r[0][1]
                    rows.append({'name': r[0][0], 'access': [c[0] for c in r[1:4]]})
                    if href:
                        pages[r[0][0]] = os.path.dirname(page) + '/' + href
        facts['objects'][name] = {'vbsType': vbs, 'page': page, 'properties': rows, 'modes': modes}
    for prop, page in sorted(pages.items()):
        try:
            data = zf.read(page).decode('utf-8-sig', 'replace')
        except KeyError:
            continue
        bl = blocks(data)
        text = ' '.join(b for k, b in bl if k == 'p')
        m = re.search(r'[Vv]alue range from (-?\d+) to (-?\d+)', text)
        facts['properties'][prop] = {'page': page, 'range': [int(m.group(1)), int(m.group(2))] if m else None,
                                     'tables': _value_tables(bl)}
    return facts


# ----------------------------------------------------------------------------------------------- exports

def _objects(root):
    for e in root.iter():
        if e.get('ID') is not None and e.find('AttributeList') is not None:
            yield e


def scan_exports(repos):
    """What the full exports under <repo>/hmi (not hmi/generated) use, per element type. Only names, kinds and enum
    spellings: free text, numbers and colours are never recorded."""
    el = {}
    docs = 0
    for repo in repos:
        for dp, dn, fn in os.walk(os.path.join(repo, 'hmi')):
            dn[:] = [d for d in dn if d != 'generated']
            for f in fn:
                if not f.endswith('.xml'):
                    continue
                try:
                    root = ET.parse(os.path.join(dp, f)).getroot()
                except ET.ParseError:
                    continue
                if not (root.findtext('DocumentInfo/ExportSetting') or '').startswith('WithDefaults'):
                    continue
                docs += 1
                for e in _objects(root):
                    if e.tag.startswith(('Hmi.Tag', 'Hmi.TextGraphicList', 'Hmi.Cycle')):
                        continue
                    d = el.setdefault(e.tag, {'attributes': {}, 'values': {}, 'links': set(), 'compositions': set(),
                                              'events': set(), 'animations': set()})
                    for a in e.find('AttributeList'):
                        k = kind_of(a.tag, a.text)
                        prev = d['attributes'].get(a.tag)
                        d['attributes'][a.tag] = k if prev in (None, k) else 'text' if 'text' in (prev, k) else prev
                        if k == 'enum':
                            d['values'].setdefault(a.tag, set()).add(a.text.strip())
                    ll = e.find('LinkList')
                    for ln in (ll if ll is not None else []):
                        d['links'].add(ln.tag)
                    ol = e.find('ObjectList')
                    for c in (ol if ol is not None else []):
                        if c.get('ID') is None:
                            continue
                        d['compositions'].add('%s %s' % (c.get('CompositionName'), c.tag))
                        if c.tag == 'Hmi.Event.Event' and e.tag != NS + 'FaceplateInstance':
                            # a faceplate's events are named by its type (project-specific): not recorded
                            d['events'].add(c.findtext('AttributeList/Name'))
                        if c.tag.startswith('Hmi.Dynamic.') and c.get('CompositionName') == 'Animations':
                            d['animations'].add(c.tag)
    out = {}
    for tag, d in sorted(el.items()):
        out[tag] = {
            'attributes': dict(sorted(d['attributes'].items())),
            'values': {k: sorted(v) for k, v in sorted(d['values'].items()) if d['attributes'].get(k) == 'enum'},
            'links': sorted(d['links']), 'compositions': sorted(d['compositions']),
            'events': sorted(x for x in d['events'] if x), 'animations': sorted(d['animations'])}
    return {'about': 'Element types, attribute kinds, enum spellings, links, compositions, events and animations seen '
                     'in full exports of project repos (names and spellings only).', 'documents': docs,
            'elements': out}


def read_fixture():
    """Element type -> first object of that type in the fixture exports: {attributes: [(name, value)],
    compositions: {name: (tag, default)}, links: [names], file}."""
    out = {}
    for f in sorted(os.listdir(FIXTURE)):
        if not f.endswith('.xml'):
            continue
        root = ET.parse(os.path.join(FIXTURE, f)).getroot()
        for e in _objects(root):
            if e.tag in out:
                continue
            comps = {}
            ol = e.find('ObjectList')
            for c in (ol if ol is not None else []):
                cn = c.get('CompositionName')
                if c.tag == 'Hmi.Globalization.MultiLingualFont':
                    comps[cn] = (c.tag, _font(c))
                elif c.tag == 'MultilingualText':
                    comps[cn] = (c.tag, _mltext(c))
            ll = e.find('LinkList')
            out[e.tag] = {'attributes': [(a.tag, a.text or '') for a in e.find('AttributeList')],
                          'compositions': comps, 'links': [x.tag for x in (ll if ll is not None else [])], 'file': f}
    return out


ENUM_NAMESPACES = ('GraphX', 'GraphX.Controls', 'Modules.ScreenModules')
_ENUMS_PS = r'''
$asm = [Reflection.Assembly]::ReflectionOnlyLoadFrom($env:CATALOGUE_ENUMS_DLL)
try { $types = $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ } }
foreach ($t in $types) {
  if (-not $t.IsEnum -or $t.Namespace -notlike 'Siemens.Simatic.Hmi.Utah.*') { continue }
  foreach ($f in ($t.GetFields() | Where-Object { $_.IsStatic })) { "{0}`t{1}`t{2}" -f $t.FullName, $f.Name, $f.GetRawConstantValue() }
}
'''


def read_enums_dll(dll):
    """TIA's enum types of the Comfort screen objects from its HMI library, by reflection (metadata only, TIA is not
    started): {'GraphX.BarOrientation': {'Up': 0, ...}} for the namespaces ENUM_NAMESPACES below
    Siemens.Simatic.Hmi.Utah. The member names are the export spellings."""
    r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _ENUMS_PS],
                       capture_output=True, text=True, errors='replace', check=True,   # its messages are not UTF-8
                       env=dict(os.environ, CATALOGUE_ENUMS_DLL=os.path.abspath(dll)))
    out = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split('\t')
        if len(parts) != 3:
            continue
        full, member, number = parts
        rel = full[len('Siemens.Simatic.Hmi.Utah.'):]
        if rel.rsplit('.', 1)[0] in ENUM_NAMESPACES:
            out.setdefault(rel, {})[member] = int(number)
    if not out:
        raise SystemExit('no enum types read from %s: %s' % (dll, r.stderr.strip()))
    enums = {k: dict(sorted(v.items(), key=lambda kv: (kv[1], kv[0]))) for k, v in sorted(out.items())}
    return {'about': "TIA's enum types of the Comfort screen objects: member names (the export spellings) and "
                     "numbers, read by reflection from TIA's HMI library (names and numbers only).",
            'source': os.path.basename(dll), 'enums': enums}


def read_roundtrip():
    """The spelling round trip: ({(element, attribute): {'confirmed': set, 'lost': {sent: exported}}}, problems)
    from roundtrip/sent.json (values the zz screens set, one per object) and roundtrip/back/*.xml (TIA's exports of
    those screens after the import). An object not exported back gives no result and a problem."""
    sent_path = os.path.join(ROUNDTRIP, 'sent.json')
    back_dir = os.path.join(ROUNDTRIP, 'back')
    if not os.path.exists(sent_path) or not os.path.isdir(back_dir):
        return {}, []
    back = {}
    for f in sorted(os.listdir(back_dir)):
        if f.endswith('.xml'):
            for e in _objects(ET.parse(os.path.join(back_dir, f)).getroot()):
                al = e.find('AttributeList')
                back[(e.tag, al.findtext('ObjectName'))] = {a.tag: a.text or '' for a in al}
    if not back:
        return {}, []
    out, problems = {}, []
    for s in _load(sent_path)['values']:
        got = back.get((s['element'], s['object']))
        if got is None:
            problems.append('round trip: %s %s not in the export back' % (s['element'], s['object']))
            continue
        r = out.setdefault((s['element'], s['attribute']), {'confirmed': set(), 'lost': {}})
        if got.get(s['attribute']) == s['value']:
            r['confirmed'].add(s['value'])
        else:
            r['lost'][s['value']] = got.get(s['attribute'])
    return out, problems


def _culture(c, culture='en-US'):
    items = [i for i in c.iter() if i.findtext('AttributeList/Culture') is not None]
    for i in items:
        if i.findtext('AttributeList/Culture') == culture:
            return i.find('AttributeList')
    return items[0].find('AttributeList') if items else None


def _font(c):
    a = _culture(c)
    if a is None:
        return None
    s = '%s, %spx' % (a.findtext('FontFamily'), a.findtext('FontSize'))
    style = a.findtext('FontStyle')
    return s + (', style=' + style if style and style != 'Regular' else '')


def _mltext(c):
    a = _culture(c)
    if a is None:
        return ''
    t = a.find('Text')
    return re.sub(r'\s+', ' ', ''.join(t.itertext())).strip() if t is not None else ''


# ----------------------------------------------------------------------------------------------- assembly

def _row(s):
    parts = [p.strip() for p in s.split('|')]
    parts += [''] * (5 - len(parts))
    group, display, target, shown, flags = parts[:5]
    return {'group': group, 'display': display, 'target': target, 'shown': shown, 'flags': set(flags.split())}


def _known(row):
    """displayKnown of a screenshot row: True; 'cut' when the name was cut off and is kept with '...'; 'inferred'
    when a cut-off name was completed from the same suffix seen whole elsewhere."""
    if 'cut' not in row['flags']:
        return True
    return 'cut' if row['display'].endswith('...') else 'inferred'


def _cond(s, attrs):
    s = s.strip()
    if s == 'always':
        return {'always': True}
    m = re.match(r'^(\w+)\s*(!=|=| in )\s*(.+)$', s)
    if not m:
        raise ValueError('greyed condition %r' % s)
    attr, op, vals = m.group(1), m.group(2).strip(), [v.strip() for v in m.group(3).split(',')]
    if attr not in attrs:
        raise ValueError('greyed condition %r: %s is not an attribute of the type' % (s, attr))
    return {'attribute': attr, 'op': {'=': 'eq', '!=': 'ne', 'in': 'in'}[op], 'values': vals}


def _shown_matches(kind, default, shown):
    """Checks a screenshot value against the export default where both are plain; None when not comparable."""
    if not shown or shown.endswith('...') or default is None:
        return None
    if kind == 'colour':
        return shown == default
    if kind == 'bool':
        return {'[x]': 'true', '[ ]': 'false'}.get(shown) == default
    if kind == 'number' and NUMBER.match(shown):
        return float(shown) == float(default)
    if kind == 'font':
        return shown == default
    return None


def _documented(hf, help_name, type_help):
    """Documented values of one property for one help object: list of {value, constant, name} and the range."""
    p = hf['properties'].get(help_name)
    if not p:
        return [], None
    vals = []
    for t in p['tables']:
        if t['scope'] and type_help not in t['scope']:
            continue
        for r in t['rows']:
            if r not in vals:
                vals.append(r)
    return vals, p['range']


def _spellings(documented, members):
    """Help name -> TIA's enum member (the export spelling) for each documented value: the member of the same name
    (any case), else the member of the same number unless another documented value has it by name; None when the
    enum has neither. Empty without an enum."""
    if not members:
        return {}
    lower = {m.lower(): m for m in members}
    by_name = {d['name']: lower.get(str(d['name']).lower()) for d in documented}
    claimed = {m for m in by_name.values() if m}
    by_number = {}
    for m, n in members.items():
        by_number.setdefault(n, m)
    out = {}
    for d in documented:
        m = by_name[d['name']]
        if m is None and isinstance(d['value'], int) and by_number.get(d['value']) not in claimed | {None}:
            m = by_number[d['value']]
        out[d['name']] = m
    return out


def _values(kind, confirmed, documented, rng, elsewhere=(), enum=None, members=None, lost=None):
    """confirmed: spellings seen on this type (exports, fixture, round trip); documented: the help's values, each
    with its export spelling from TIA's enum (members) when known, confirmed when that spelling (else the name) is
    one of them, spellingSeen when another type's export uses it for the same attribute; lost: values the round trip
    sent that TIA did not keep."""
    if kind != 'enum' and not documented:
        return None
    seen = set(confirmed)
    spell = _spellings(documented, members)
    doc = []
    for d in documented:
        e = {'value': d['value'], 'constant': d['constant'], 'name': d['name']}
        if members:
            e['spelling'] = spell[d['name']]
        s = e['spelling'] if members else d['name']
        e['confirmed'] = s in seen
        if not e['confirmed'] and s is not None and s in elsewhere:
            e['spellingSeen'] = True
        doc.append(e)
    out = {'confirmed': sorted(seen)}
    if doc:
        out['documented'] = doc
    if rng:
        out['range'] = rng
    if enum:
        out['enum'] = enum
    if lost:
        out['lost'] = dict(sorted(lost.items()))
    return out


def enum_type(toolbox, key, name):
    """TIA's enum type of an attribute from toolbox.json enumTypes ('Key.Attr' before 'Attr'); a name without a
    namespace is in GraphX."""
    m = toolbox.get('enumTypes', {})
    e = m.get('%s.%s' % (key, name)) or m.get(name)
    return e if e is None or '.' in e else 'GraphX.' + e


def _help_rows(hf, help_name):
    o = hf['objects'].get(help_name) if help_name else None
    if not o:
        return {}, None, None
    return {r['name'].lower(): r for r in o['properties']}, o, o.get('vbsType')


def _access(r):
    return dict(zip(('professional', 'advanced', 'panel'), r['access'])) if r else None


def all_spellings(fixture, seen):
    """Attribute name -> every enum spelling seen for it on any element type (fixture and exports)."""
    out = {}
    for fx in fixture.values():
        for n, v in fx['attributes']:
            if kind_of(n, v) == 'enum':
                out.setdefault(n, set()).add(v.strip())
    for sn in seen['elements'].values():
        for n, vals in sn['values'].items():
            out.setdefault(n, set()).update(vals)
    return out


def build_type(t, fixture, seen, hf, desc, spellings, toolbox=None, enums=None, roundtrip=None):
    key = t.get('key')
    element = NS + key if key else None
    fx = fixture.get(element) if element else None
    sn = seen['elements'].get(element, {}) if element else {}
    help_name = t.get('help')
    hrows, hobj, vbs = _help_rows(hf, help_name)
    out = {'key': key, 'element': element}
    if t.get('toolbox'):
        out['toolbox'] = {'group': t['toolbox'][0], 'name': t['toolbox'][1]}
    if fx:
        stem = dict(fx['attributes']).get('ObjectName', '')
        out['stem'] = re.sub(r'_1$', '', stem) or None
    out['openness'] = bool(fx or sn)
    out['source'] = 'fixture' if fx else 'exports' if sn else 'help' if hobj else None
    out['purpose'] = t.get('purpose')
    out['help'] = {'object': help_name, 'vbsType': vbs} if hobj else None

    attrs = []
    defaults = dict(fx['attributes']) if fx else {}
    kinds = {n: kind_of(n, v) for n, v in defaults.items()}
    for n, k in sn.get('attributes', {}).items():
        kinds.setdefault(n, k)
    confirmed = sn.get('values', {})
    rows = [_row(r) for r in t.get('rows', [])]
    greyed = {k: [_cond(c, kinds) for c in v] for k, v in t.get('greyed', {}).items()}
    used = set()
    problems = []

    def help_for(name):
        hn = HELP_ALIAS.get(name, name)
        return hn, hrows.get(hn.lower())

    def attr_entry(name, row):
        kind = kinds.get(name)
        default = defaults.get(name) if fx else None
        hn, hr = help_for(name)
        documented, rng = _documented(hf, hr['name'] if hr else hn, help_name) if hr or hobj else ([], None)
        if name in t.get('helpValuesWrong', []):
            documented = []
        conf = set(confirmed.get(name, []))
        if kind == 'enum' and default is not None:
            conf.add(default)
        rt = (roundtrip or {}).get((element, name), {})
        conf |= rt.get('confirmed', set())
        enum = enum_type(toolbox or {}, key, name) if kind == 'enum' else None
        members = (enums or {}).get(enum)
        if enum and members is None:
            problems.append('%s %s: enum %s not in enums.json' % (key, name, enum))
        if members and not conf <= set(members):
            problems.append('%s %s: confirmed %s not members of %s' % (key, name, sorted(conf - set(members)), enum))
        a = {'name': name, 'display': row['display'] if row else name,
             'displayKnown': _known(row) if row else False,
             'group': row['group'] if row else None, 'kind': kind, 'default': default}
        if row and row['shown'] and kind in ('enum', 'number') and row['shown'] != default \
                and not row['shown'].endswith('...'):
            a['shown'] = row['shown']
        v = _values(kind, conf, documented, rng, spellings.get(name, ()), enum if members else None, members,
                    rt.get('lost'))
        if v:
            a['values'] = v
        a['description'] = desc.get(name)
        a['access'] = _access(hr)
        if name in greyed:
            a['greyedWhen'] = greyed[name]
        if row and 'unsure' in row['flags']:
            a['unsure'] = True
        if row:
            ok = _shown_matches(kind, default, row['shown'])
            if ok is False:
                problems.append('%s %s: screenshot %r, export %r' % (key, name, row['shown'], default))
        return a

    for row in rows:
        tg = row['target']
        if tg == '-':
            attrs.append({'name': None, 'display': row['display'], 'displayKnown': _known(row), 'group': row['group'], 'kind': None, 'export': False,
                          'description': desc.get('~' + row['display'])})
            continue
        if tg.startswith('@'):
            comp = tg[1:]
            fc = (fx or {}).get('compositions', {}).get(comp)
            seen_comp = any(c.split(' ')[0] == comp for c in sn.get('compositions', []))
            if not fc and not seen_comp:
                problems.append('%s %s: composition not in the export' % (key, tg))
            kind = 'font' if (fc and fc[0].endswith('MultiLingualFont')) or 'font' in comp.lower() else 'text'
            a = {'name': tg, 'display': row['display'], 'displayKnown': _known(row),
                 'group': row['group'], 'kind': kind, 'default': fc[1] if fc else None,
                 'description': desc.get(tg)}
            hn, hr = help_for(comp)
            a['access'] = _access(hr)
            if tg in greyed:
                a['greyedWhen'] = greyed[tg]
            ok = _shown_matches(kind, a['default'], row['shown'])
            if ok is False:
                problems.append('%s %s: screenshot %r, export %r' % (key, tg, row['shown'], a['default']))
            attrs.append(a)
            used.add(tg)
            continue
        if tg.startswith(('link:', 'tag:')):
            kind, name = tg.split(':', 1)
            sure = not name.endswith('?')
            name = name.rstrip('?')
            a = {'name': kind + ':' + name, 'display': row['display'], 'displayKnown': True, 'group': row['group'],
                 'kind': kind, 'default': None, 'description': desc.get(kind + ':' + name)}
            if not sure:
                a['nameSeen'] = False
            hn, hr = help_for(name)
            a['access'] = _access(hr)
            attrs.append(a)
            used.add(a['name'])
            continue
        if fx and tg not in defaults:
            problems.append('%s %s: not an attribute of the export' % (key, tg))
        attrs.append(attr_entry(tg, row))
        used.add(tg)
    names = list(defaults) if fx else sorted(sn.get('attributes', {}))
    for n in names:
        if n not in used:
            attrs.append(attr_entry(n, None))
            used.add(n)
    if fx:
        for comp, (tag, dflt) in fx['compositions'].items():
            if '@' + comp not in used:
                kind = 'font' if tag.endswith('MultiLingualFont') else 'text'
                attrs.append({'name': '@' + comp, 'display': '@' + comp, 'displayKnown': False, 'group': None,
                              'kind': kind, 'default': dflt, 'description': desc.get('@' + comp)})
    if not fx and not sn and hobj:
        for r in hobj['properties']:
            documented, rng = _documented(hf, r['name'], help_name)
            a = {'name': r['name'], 'display': r['name'], 'displayKnown': False, 'group': None,
                 'kind': 'enum' if documented else None, 'default': None,
                 'description': desc.get(r['name']), 'access': _access(r)}
            v = _values('enum' if documented else None, [], documented, rng)
            if v:
                a['values'] = v
            attrs.append(a)
    _mode_conditions(t, attrs, rows, hobj, kinds, defaults, problems)
    for k in greyed:
        if k not in used:
            problems.append('%s greyed %s: not a row of the type' % (key, k))
    out['attributes'] = attrs
    links = sorted({a['name'][5:] for a in attrs if a.get('kind') == 'link'} | set(sn.get('links', [])))
    out['links'] = links
    out['events'] = sn.get('events', [])
    out['animations'] = sn.get('animations', [])
    out['preview'] = t.get('preview')
    return out, problems


def _mode_conditions(t, attrs, rows, hobj, kinds, defaults, problems):
    """Greyed conditions from the help's mode table: an attribute not available in a mode is greyed in it. Kept only
    when the screenshot agrees for the default mode (the help's tables are about runtime access and disagree with
    the editor for some rows); attributes get the table as 'modes' either way."""
    if not hobj or not hobj.get('modes'):
        return
    table, spell = hobj['modes'], t.get('modes', {})
    default_mode = defaults.get('Mode')
    default_help = next((m for m, s in spell.items() if s == default_mode), None)
    grey_rows = {}
    for r in rows:
        grey_rows[r['target']] = 'grey' in r['flags']
    by_name = {a['name']: a for a in attrs if a.get('name')}
    for prop, avail in table['rows'].items():
        name = prop if prop in kinds else '@' + prop if '@' + prop in by_name else None
        a = by_name.get(name)
        if not a:
            continue
        a['modes'] = {'available': avail, 'of': table['modes']}
        unavailable = [m for m in table['modes'] if m not in avail]
        if not unavailable or default_help is None or name not in grey_rows:
            continue
        if (default_help in unavailable) != grey_rows[name]:
            a['modes']['disagrees'] = True
            continue
        vals = [spell[m] for m in unavailable if spell.get(m)]
        if not vals:
            continue
        cond = {'attribute': 'Mode', 'op': 'in', 'values': vals, 'from': 'help'}
        if len(vals) < len(unavailable):
            cond['partial'] = True
        a.setdefault('greyedWhen', []).append(cond)


def build_parts(fixture, seen, types):
    """Element types below the screen objects (fonts, texts, animations, events, properties ...)."""
    known = {t['element'] for t in types if t.get('element')}
    parts = {}
    for tag, fx in fixture.items():
        if tag in known:
            continue
        parts[tag] = {'attributes': {n: {'kind': kind_of(n, v), 'default': v} for n, v in fx['attributes']}}
    for tag, sn in seen['elements'].items():
        if tag in known:
            continue
        p = parts.setdefault(tag, {'attributes': {}})
        for n, k in sn['attributes'].items():
            a = p['attributes'].setdefault(n, {'kind': k, 'default': None})
            if k == 'text':                 # exports hold free forms the fixture's one value does not show
                a['kind'] = 'text'          # (FontStyle 'Bold, Italic')
        for n, vals in sn['values'].items():
            p['attributes'][n]['values'] = {'confirmed': vals}
        for k in ('links', 'compositions', 'events'):
            if sn.get(k):
                p[k] = sn[k]
    for p in parts.values():                # a fixture default is a confirmed spelling too
        for a in p['attributes'].values():
            if a['kind'] == 'enum' and a['default'] is not None:
                conf = set(a.get('values', {}).get('confirmed', [])) | {a['default']}
                a['values'] = {'confirmed': sorted(conf)}
    # Element types without attributes that objects hold (texts, fonts, event handlers ...): known, empty.
    held = {c.split(' ', 1)[1] for sn in seen['elements'].values() for c in sn.get('compositions', [])}
    held |= {tag for fx in fixture.values() for tag, _ in fx['compositions'].values()}
    for tag in held - known - set(parts):
        parts[tag] = {'attributes': {}}
    return dict(sorted(parts.items()))


def build(toolbox, fixture, seen, hf, enums=None, roundtrip=None):
    desc = toolbox['descriptions']
    types, problems = [], []
    spellings = all_spellings(fixture, seen)
    enum_members = (enums or {}).get('enums', {})
    for t in toolbox['types']:
        out, p = build_type(t, fixture, seen, hf, desc, spellings, toolbox, enum_members, roundtrip)
        types.append(out)
        problems += p
    for tp in types:
        for a in tp['attributes']:
            if a.get('name') and not a.get('description') and tp['openness']:
                problems.append('%s %s: no description' % (tp['key'], a['name']))
    cat = {
        'schema': SCHEMA,
        'about': 'WinCC Comfort screen object catalogue (TIA Portal V20 Update 7). Built by catalogue/build.py; '
                 'see docs/agent/wincc-screen-objects.md.',
        'tia': 'V20 Update 7',
        'style': 'WinCC Dark',
        'sources': {'fixture': sorted(f for f in os.listdir(FIXTURE) if f.endswith('.xml')),
                    'help': hf.get('source'), 'seenDocuments': seen.get('documents'),
                    'enums': (enums or {}).get('source'), 'roundTrip': bool(roundtrip)},
        'types': types,
        'parts': build_parts(fixture, seen, types),
        'enums': {e: enum_members[e] for e in sorted({a['values']['enum'] for tp in types for a in tp['attributes']
                                                      if (a.get('values') or {}).get('enum')})},
    }
    return cat, problems


# ----------------------------------------------------------------------------------------------- docs page

def _md(s):
    return '' if s is None else str(s).replace('|', '\\|').replace('\n', ' ')


def _cond_text(c):
    if c.get('always'):
        return 'always'
    op = {'eq': '=', 'ne': '!=', 'in': 'in'}[c['op']]
    s = '%s %s %s' % (c['attribute'], op, ', '.join(c['values']))
    if c.get('from') == 'help':
        s += ' (help%s)' % (', partial' if c.get('partial') else '')
    return s


def _values_text(a):
    v = a.get('values')
    if not v:
        return ''
    parts = []
    conf = v.get('confirmed', [])
    if conf:
        parts.append(', '.join('`%s`' % x for x in conf))
    lost = v.get('lost', {})
    doc = [d for d in v.get('documented', []) if not d['confirmed'] and d.get('spelling') not in lost]
    if doc:
        parts.append('documented, not confirmed: ' + ', '.join(_documented_text(d, 'enum' in v) for d in doc))
    if lost:
        parts.append('lost in the round trip: ' + ', '.join(
            '`%s` (exported %s)' % (k, '`%s`' % w if w is not None else 'nothing') for k, w in lost.items()))
    if v.get('range'):
        parts.append('range %s to %s' % tuple(v['range']))
    if v.get('enum'):
        parts.append('enum `%s`' % v['enum'])
    return '; '.join(parts)


def _documented_text(d, enum):
    """One documented value: its export spelling, with the help's name where it differs and the number."""
    num = [str(d['value'])] if d['value'] is not None else []
    seen = ' (spelling seen on another object)' if d.get('spellingSeen') else ''
    if not enum:
        return '%s%s%s' % (d['name'], ' (%s)' % num[0] if num else '', seen)
    if d.get('spelling') is None:
        return '%s (%s)' % (d['name'], '; '.join(num + ["not in TIA's enum"]))
    help_name = ['help: %s' % d['name']] if d['spelling'] != d['name'] else []
    extra = ', '.join(help_name + num)
    return '`%s`%s%s' % (d['spelling'], ' (%s)' % extra if extra else '', seen)


def _display(a):
    d = _md(a['display'])
    if a.get('displayKnown') is False:
        return '*%s*' % d
    if a.get('displayKnown') == 'inferred':
        return d + ' (inferred)'
    return d


def render_doc(cat, generated):
    L = []
    L.append('---')
    L.append('type: Guide')
    L.append('title: WinCC Comfort screen objects')
    L.append('description: Every object of the WinCC Comfort toolbox with every option, its TIA display name and '
             'group, export name, default, allowed values and what the HMI preview draws; generated from '
             'TiaHmiGenerator/catalogue/catalogue.json.')
    L.append('tags: [hmi, wincc-comfort, openness, simatic-ml, agents]')
    L.append('generated: { by: %s, at: %s }' % generated)
    L.append('sources:')
    L.append('  - id: catalogue')
    L.append('    resource: ../../TiaHmiGenerator/catalogue/catalogue.json')
    L.append('    title: Screen object catalogue (data file)')
    L.append('  - id: guide')
    L.append('    resource: wincc-comfort-openness.md')
    L.append('    title: WinCC Comfort screen generation with TIA Portal Openness')
    L.append('  - id: help')
    L.append('    resource: TIA Portal V20 installed help, VBS object reference (VBSObjectsWCCCenUS)')
    L.append('    title: TIA help, read at build time')
    L.append('---')
    L.append('')
    L.append('# WinCC Comfort screen objects')
    L.append('')
    L.append('<!-- Generated by TiaHmiGenerator/catalogue/build.py from catalogue.json; edit toolbox.json and rebuild. '
             '-->')
    L.append('')
    L.append('Every object the WinCC Comfort toolbox (TIA Portal %s) puts on a screen, with every option. Use it to '
             'generate screens (which attributes an object has, their export names and allowed values) and to read '
             'an export. The data is `TiaHmiGenerator\\catalogue\\catalogue.json` (section 3); this page is generated '
             'from it.' % cat['tia'])
    L.append('')
    L.append('## 1. Reading the tables')
    L.append('')
    L.append('- **Display name and group** are TIA\'s, from its Properties window in the table view, sorted by '
             'group and name as TIA sorts them. A name in *italics* is the export name: the row was not in a '
             'screenshot, or is not in the Properties window (`TabIndex`). A name ending in "..." was cut off in the '
             'screenshot; "(inferred)": it was cut off and is completed from the same ending seen whole on another '
             'row ("(border)", "(layout)", "(appearance)").')
    L.append('- **Export name**: the element in the SimaticML `AttributeList`; `@Name` an `ObjectList` member '
             '(`MultilingualText` or `MultiLingualFont`) with that `CompositionName`; `link:Name` a `LinkList` '
             'entry; `tag:Name` a `Properties` entry with a tag connection; `-` a row TIA shows that the export '
             'does not carry. A link or tag name marked "not seen" was not in an export yet.')
    L.append('- **Default**: the value of the object as dropped from the toolbox, device style %s, in the export\'s '
             'spelling; TIA\'s text for it in brackets where it differs ("Round" is shown "Flush"). The defaults are '
             'a reference only: a project\'s objects follow its own style presets.' % cat['style'])
    L.append('- **Values** of an enum: the spellings confirmed by an export or by the spelling round trip (a zz test '
             'screen with the value set, imported and exported again; they import), then the values TIA\'s help '
             'documents that nothing has confirmed yet, in their export spelling: the member of TIA\'s own enum '
             'type for the attribute (named last, read from TIA\'s HMI library) of the same name, or of the same '
             'number, with the help\'s name and number in brackets ("not in TIA\'s enum": no member, TIA cannot read '
             'it). Values the round trip sent and TIA did not keep are listed as lost. The HMI preview\'s validator '
             'passes a confirmed value, warns on a documented one or another member of the enum (TIA may refuse it '
             'at import) and refuses anything else.')
    L.append('- **Greyed** when: the conditions under which TIA greys the row, where known (seen in several '
             'screenshots, obvious, or from the help\'s mode table where the screenshots agree).')
    L.append('- **Openness**: the 20 basic objects and elements and the user view go through Openness (export and '
             'import). The other 14 controls are left out of the export silently ([WinCC guide](wincc-comfort-'
             'openness.md) 7.1): build them by hand in TIA; their properties come from the help only, without '
             'defaults or display names.')
    L.append('')
    L.append('## 2. Objects')
    L.append('')
    L.append('| Toolbox group | Object | Export element | Openness | Preview |')
    L.append('|---|---|---|---|---|')
    for t in cat['types']:
        if not t.get('toolbox'):
            continue
        anchor = _anchor(t)
        prev = (t.get('preview') or {}).get('state', 'none')
        L.append('| %s | [%s](#%s) | %s | %s | %s |' % (
            t['toolbox']['group'], t['toolbox']['name'], anchor,
            '`%s`' % t['element'] if t['element'] else '-', 'yes' if t['openness'] else 'no, build by hand', prev))
    L.append('')
    L.append('Besides the toolbox: ' + ', '.join('[%s](#%s)' % (t['key'], _anchor(t)) for t in cat['types']
                                                 if not t.get('toolbox')) + '.')
    L.append('')
    L.append('Preview: drawn (the look from the export), placeholder (a labelled box), none (a hatched '
             '"not drawn" box).')
    L.append('')
    for t in cat['types']:
        L += _type_section(t)
    L.append('## 3. The data file')
    L.append('')
    L.append('`TiaHmiGenerator\\catalogue\\catalogue.json`, schema %d. Read it with `hmipreview.catalogue` '
             '(`load()`, `by_element()`, `attribute()`, `attribute_names()`, `enum_members()`, `fixture_objects()`). '
             'Top level: `schema`, `tia`, `style`, `sources`, `types` (the objects above, in this order), `parts` '
             '(element types below the objects: fonts, texts, animations, events, properties, with their attributes '
             'and confirmed values; those without attributes empty), `enums` (TIA\'s enum types the attributes '
             'name: member -> number).' % cat['schema'])
    L.append('')
    L.append('A type: `key` (element without `Hmi.Screen.`, null for a control whose element is unknown), '
             '`element`, `toolbox` {`group`, `name`}, `stem` (TIA\'s default ObjectName without `_1`), `openness`, '
             '`source` (fixture | exports | help), `purpose`, `help` {`object`, `vbsType`}, `attributes`, `links`, '
             '`events` and `animations` (seen in exports), `preview` {`state`, `drawn`, `notDrawn`, `note`}.')
    L.append('')
    L.append('An attribute: `name` (export name, `@Composition`, `link:Name`, `tag:Name`, or null for a row the '
             'export does not carry, then `export` false), `display`, `displayKnown` (true; "cut": cut off in the '
             'screenshot, kept with "..."; "inferred": cut off and completed; false: the export name), `group` (TIA\'s, null when not in the Properties window), `kind` (colour | bool | number | '
             'enum | text | list | blob | font | link | tag), `default` (export spelling; fonts as "Tahoma, 13px, '
             'style=Bold"), `shown` (TIA\'s text for the default when it differs), `values` {`confirmed` (seen in '
             'an export, the fixture or the round trip), `documented` [{`value`, `constant`, `name`, `spelling` '
             '(the export spelling from TIA\'s enum, null: no member; only with `enum`), `confirmed`, '
             '`spellingSeen`}], `range`, `enum` (TIA\'s enum type), `lost` {sent: exported}}, `description`, `access` '
             '{`professional`, `advanced`, `panel`: R | RW | -} (runtime access per the help), `greyedWhen` '
             '[{`attribute`, `op` eq | ne | in, `values`} or {`always`}; any one greys], `modes` (the help\'s mode '
             'table), `unsure` (the display row may belong to another attribute), `nameSeen` false (a link or tag '
             'name not seen in an export).')
    L.append('')
    L.append('## 4. Rebuilding')
    L.append('')
    L.append('From `TiaHmiGenerator`, with `<py>` = `<tool repo>\\.venv\\Scripts\\python.exe -X utf8`: `<py> catalogue\\build.py` rebuilds `catalogue.json` and this page from the '
             'committed inputs; `--check` fails when they are not current (a unit test runs it). Inputs: '
             '`toolbox.json` (by hand: display names, groups and order from TIA\'s Properties window, greyed-row '
             'conditions, descriptions in our own words, the preview\'s coverage, `enumTypes`: the enum type of each '
             'enum attribute), `fixture\\` (full exports of the test screens, every toolbox object dropped '
             'unchanged; `hmixml` copies a type no project export holds from it: `blank`, `shape_item`), '
             '`helpfacts.json` (facts read from TIA\'s installed help: `--help-zip <Help\\en-US\\VBSObjectsWCCCenUS'
             '.zip>`; names, access, constants and ranges, never help text), `seen.json` (enum spellings, links, '
             'events and animations seen in full exports: `--seen <project repo>`, repeatable; names and spellings '
             'only), `enums.json` (TIA\'s enum types of the screen objects, member names and numbers, by reflection '
             'from its HMI library: `--enums <Bin\\Siemens.Simatic.Hmi.Global.dll>`; Windows PowerShell, TIA is not '
             'started) and `roundtrip\\` (the spelling round trip).')
    L.append('')
    L.append('The spelling round trip: `<py> catalogue\\roundtrip.py <folder>` writes the test screens '
             '`zzTestSpellings.xml` and `zzTestSpellings2.xml` (objects copied from the fixture, one documented '
             'spelling not yet confirmed per object, with the dependent properties the table expects; values taken as '
             'not allowed on Comfort panels left out, those one panel may not allow on the second screen; dependent '
             'properties and device refusals from `dependent.json`, which the validator reads as well) and '
             '`roundtrip\\sent.json`. Import each screen into a project, '
             'export it again, put the exports into `roundtrip\\back\\` without their `InstalledProducts`, and '
             'rebuild: a value that came back is confirmed, one that came back different is lost. Only the '
             'coordinator\'s bridge touches TIA.')
    L.append('')
    L.append('A new TIA version: export the two test screens again (every toolbox object dropped, full export), '
             'replace the fixture (strip the device, project and tag names), take new screenshots where the '
             'Properties window changed, run the build with `--help-zip`, `--enums` and `--seen`, read the problems '
             'it prints (screenshot values that differ from the export defaults, rows without an export attribute, '
             'confirmed spellings that are no member of the enum named), and run the round trip again.')
    L.append('')
    return '\n'.join(L).rstrip() + '\n'


def _anchor(t):
    title = _title(t)
    return re.sub(r'[^a-z0-9 -]', '', title.lower()).replace(' ', '-')


def _title(t):
    if t.get('toolbox'):
        return t['toolbox']['name']
    return t['key']


def _type_section(t):
    L = ['### %s' % _title(t), '']
    facts = []
    facts.append('Element `%s`' % t['element'] if t['element'] else 'Export element unknown')
    if t.get('stem'):
        facts.append('default name `%s_1`' % t['stem'])
    facts.append('Openness: %s' % ('yes' if t['openness'] else 'no (build by hand)'))
    if t.get('help'):
        facts.append('help object `%s`' % t['help']['object'])
    L.append(_md(t.get('purpose') or '') + ' ' + '; '.join(facts) + '.')
    L.append('')
    pv = t.get('preview')
    if pv:
        s = 'Preview: %s' % pv.get('state')
        if pv.get('note'):
            s += ' (%s)' % pv['note']
        if pv.get('notDrawn'):
            s += '. Not drawn: ' + '; '.join('`%s` (%s)' % (k, v) for k, v in pv['notDrawn'].items())
        L.append(s + '.')
        L.append('')
    extra = []
    if t.get('links'):
        extra.append('links: ' + ', '.join('`%s`' % x for x in t['links']))
    if t.get('events'):
        extra.append('events seen: ' + ', '.join('`%s`' % x for x in t['events']))
    if t.get('animations'):
        extra.append('animations seen: ' + ', '.join('`%s`' % x.split('.')[-1] for x in t['animations']))
    if extra:
        L.append('In exports: ' + '; '.join(extra) + '.')
        L.append('')
    attrs = t['attributes']
    if not attrs:
        return L
    if t['source'] == 'help':
        L.append("Properties in TIA's help (%d; the export names are not known, the help's names usually match): %s."
                 % (len(attrs), ', '.join('`%s`' % a['name'] for a in attrs)))
        L.append('')
        enums = [a for a in attrs if a.get('values')]
        if enums:
            L.append('| Property (help) | Documented values |')
            L.append('|---|---|')
            for a in enums:
                L.append('| `%s` | %s |' % (a['name'], _md(_values_text(a))))
            L.append('')
        return L
    L.append('| Group | Display name | Export name | Kind | Default | Values | Greyed when | Description |')
    L.append('|---|---|---|---|---|---|---|---|')
    for a in attrs:
        name = '`%s`' % a['name'] if a.get('name') else '-'
        if a.get('nameSeen') is False:
            name += ' (not seen)'
        if a.get('unsure'):
            name += ' (unsure)'
        dflt = a.get('default')
        dtext = '' if dflt is None else '`%s`' % dflt if dflt != '' else '(empty)'
        if a.get('shown'):
            dtext += ' (%s)' % _md(a['shown'])
        grey = '; '.join(_cond_text(c) for c in a.get('greyedWhen', []))
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            _md(a.get('group') or ''), _display(a), name, a.get('kind') or '', _md(dtext), _md(_values_text(a)),
            _md(grey), _md(a.get('description'))))
    L.append('')
    return L


# ----------------------------------------------------------------------------------------------- main

def _read(path):
    if not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False) + '\n'


def _now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _doc_body(text):
    """The docs page without its generated stamp, for comparing rebuilds."""
    return re.sub(r'^generated: .*$', '', text, count=1, flags=re.M)


def outputs(by=None):
    """(catalogue JSON text, docs page text, problems) from the committed inputs. The docs page keeps its
    generated stamp when its content did not change."""
    toolbox = _load(TOOLBOX)
    fixture = read_fixture()
    seen = _load(SEEN)
    hf = _load(HELPFACTS)
    enums = _load(ENUMS) if os.path.exists(ENUMS) else None
    roundtrip, rt_problems = read_roundtrip()
    cat, problems = build(toolbox, fixture, seen, hf, enums, roundtrip)
    problems = rt_problems + problems
    old = _read(DOC)
    m = re.search(r'^generated: \{ by: (\S+), at: (\S+) \}$', old, re.M)
    doc = render_doc(cat, m.groups() if m else (by or 'process:catalogue-build', _now()))
    if _doc_body(doc) != _doc_body(old):
        doc = render_doc(cat, (by or (m.group(1) if m else 'process:catalogue-build'), _now()))
    return _dump(cat), doc, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--help-zip', help='TIA help VBSObjectsWCCCenUS.zip: refresh helpfacts.json')
    ap.add_argument('--seen', action='append', default=[], help='project repo whose full exports refresh seen.json')
    ap.add_argument('--enums', help="TIA's Siemens.Simatic.Hmi.Global.dll: refresh enums.json")
    ap.add_argument('--check', action='store_true', help='exit 1 when catalogue.json or the docs page is not current')
    ap.add_argument('--by', help='actor for the docs page generated stamp (default: keep, or process:catalogue-build)')
    args = ap.parse_args(argv)
    if args.help_zip:
        names = [t['help'] for t in _load(TOOLBOX)['types'] if t.get('help')]
        with open(HELPFACTS, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_dump(parse_help(args.help_zip, names)))
    if args.enums:
        enums = _dump(read_enums_dll(args.enums))
        with open(ENUMS, 'w', encoding='utf-8', newline='\n') as f:
            f.write(enums)
    if args.seen:
        with open(SEEN, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_dump(scan_exports(args.seen)))
    cat, doc, problems = outputs(args.by)
    for p in problems:
        print('problem:', p, file=sys.stderr)
    if args.check:
        cur_cat = _read(OUT)
        cur_doc = _read(DOC)
        stale = [p for p, a, b in ((OUT, cat, cur_cat), (DOC, _doc_body(doc), _doc_body(cur_doc))) if a != b]
        for p in stale:
            print('not current:', os.path.relpath(p, REPO), file=sys.stderr)
        return 1 if stale else 0
    for path, text in ((OUT, cat), (DOC, doc)):
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
    print('wrote %s and %s (%d problems)' % (os.path.relpath(OUT, REPO), os.path.relpath(DOC, REPO), len(problems)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
