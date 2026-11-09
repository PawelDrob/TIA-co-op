"""hmixml - build WinCC Comfort (TIA Portal V20) SimaticML screens, text lists and tag tables for
Openness import. Generic part of the generator; see docs/agent/wincc-comfort-openness.md.

Every object is copied from a full export (ExportSetting WithDefaults, WithReadOnly; decided 2026-10-06): screen
items from the style presets (load_templates), roots, layers, groups and graphic views from the first exported
object of their type (blank; load_templates and load_shapes collect them). A type no loaded export holds is copied
from the screen object catalogue's fixture (TiaHmiGenerator/catalogue/fixture: every toolbox object that goes through
Openness, dropped unchanged; blank, shape_item copies a whole one). The generator sets geometry, names, texts,
formats, links, animations and events, never a default value of its own: a type neither holds gets an empty
attribute list, and the validator refuses the run (document.incomplete).

Object dict (one per screen item):
  name, type ('Rectangle', 'Text field', 'I/O field', 'Symbolic I/O field', 'Button', 'Polygon'),
  style (template ObjectName, e.g. 'S-Panel'), x, y, w, h (screen coordinates, or faceplate
  coordinates plus ox/oy), group (dict with 'key' or None), m (dict):
    text=[lines]            Text field text / Button TextOff+TextOn
    fmt='s99.9'             I/O field format pattern (FieldLength = digits + point)
    tl='tlName'             Symbolic I/O field text list
    mode='Output'           Symbolic I/O field Mode; without it the preset's stays
    anim=('appear', value, backKey, foreKey)   RangeAppearanceAnimation, colours from COL
    vis=True                VisibilityAnimation 1..1 visible
    event='hold'            Press: SetBitWhileKeyPressed (tag open)
    grp='Banner'            group key overriding the panel group
  Tags are left open (no LinkList); a later pass can add them.

Languages: every text and font of a generated document has one item per language of the project
(generated_cultures(): the cultures of the project's exports, else of the exports loaded; ValueError when neither holds
one). A text the generator sets is given once and written in every language, the same words: a language with no text
of its own shows that text. A text it does not set stays as copied: a missing language is a copy of the first item
holding a text, an item empty in the export stays empty. Translate in TIA afterwards; a screen generated and imported
again with Override replaces those translations.

Generator run (output into a project repo, validated before anything stays written; the only way a document
reaches the disk):
  begin(repo, panel=None, device=None)
                              start a run for the project repo and one HMI device: the resolution of the declared
                              target panel (<hmi>/panel.json, or panel= saved with the run); ValueError without a
                              declared panel, when it differs from the HMI device in tiabridge.json
                              (hmiTypeIdentifier), or when no device can be chosen. <hmi> is hmi/ for a project
                              with one HMI device, hmi/<device>/ with several (the device folder of TiaBridge's
                              export): device names it, else tiabridge.json hmiDevice, else the only device folder
                              (hmipreview.model.select_device)
  plan(kind, name, note)      declare a planned item (style preset, text list, template, picture, faceplate
                              type version, screen, ...) next to the object that uses it
  tag_table(name, tags)       a tag table in the shape of a TIA export, Length and HmiDataType from the data type
                              (in a run; rules.tagtable)
  add(kind, doc, folder='')   queue a document ('screen' | 'template' | 'popup' | 'textlist' | 'tagtable') for
                              <hmi>/generated/<kind dir>/<folder>/<Name>.xml; returns that repo-relative path
  finish()                    validate first: hmipreview.validate runs on the repo with the run's documents,
                              <hmi>/generated/planned.json (exactly the items planned in this run) and generated.json
                              as an in-memory overlay (model.load overlay), prints the run's findings (document,
                              object, rule, reason) and returns them. Only without errors are the files written.
                              On any error GenerationRefused is raised with the findings and nothing of the run
                              has touched the repo at any point.
  generated.json              <hmi>/generated/generated.json, one record per generated document, kept for earlier
                              runs' files while they exist:
                                {"<repo-relative path>": {"generated": "<ISO 8601 time with offset>",
                                                          "presets": {"<ObjectName>": {"preset": "<TPL key>",
                                                            "source": "<ObjectName copied>",
                                                            "document": "<repo-relative export> or null"}}}}
                              generated: when a run last wrote it; the staleness rule prefers it over the mtime,
                              which a clone or checkout resets. presets: per screen item copied by template() /
                              item() during the run, the TPL key, the ObjectName of the TPL element actually
                              copied (an exported S- object, or the object an alias points to), and the export it
                              came from when load_templates loaded
                              it (null for a TPL filled by hand); the SimaticML does not carry it. Read with
                              hmipreview.model (Repo.generated_time(doc), Repo.presets(doc); an old record that is
                              a plain string is the key only); the link rules check the presets.
  generated_dirs(repo, device=None)  {kind: absolute folder} under <hmi>/generated
  screen() / screen_doc()     screens and templates sized to the run's declared panel (RuntimeError outside a
                              run); pop-ups keep their own size.

The run's findings are those on its own files plus repo-level ones (tiabridge.json, ...); findings on other
documents are the business of their own run and of the preview.

Validated from an overlay, not in a staging copy: every other file and the git history (staleness compares export
commit times with the recorded generation times) come from the real repo, so the preview never sees a refused run.
"""
import copy
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

COL = {}          # colour keys -> 'r, g, b'; set by the caller (set_colours)

def set_colours(d):
    COL.clear()
    COL.update({k: '%d, %d, %d' % v for k, v in d.items()})

# ---------------------------------------------------------------- templates
troot = None
TPL = {}
SHAPES = {}       # element type -> the first object of that type in the exports loaded (load_templates, load_shapes)
TPL_SOURCE = {}   # key -> (template element, absolute path of the export it was loaded from); set by load_templates
LOADED_CULTURES = []   # the cultures of the exports loaded, first seen first (load_templates, load_shapes)

def load_templates(path, aliases=None):
    """Template objects = every screen item whose ObjectName starts with 'S-' on an exported screen, plus
    aliases {key: ObjectName} for exported objects not named S-... ({'S-Title': 'txtTitleLarge'}); KeyError when an
    alias names no screen item of the export. A project's own look on a preset is an alias too: {key: (ObjectName,
    {attribute: value})} is a copy of that object with those attributes set ({'S-Note': ('S-Title',
    {'VerticalAlignment': 'Top'})}), and {'S-Lit': 'S-Button'} a second name for one. The run records each key
    with the object and this export."""
    global troot
    troot = ET.parse(path).getroot()
    TPL.clear()
    TPL_SOURCE.clear()
    SHAPES.clear()
    LOADED_CULTURES.clear()
    _add_export(troot)
    by_name = {}
    for e in troot.iter():
        al = e.find('AttributeList')
        if al is not None and e.get('CompositionName') == 'ScreenItems':
            n = al.findtext('ObjectName')
            if n:
                by_name.setdefault(n, e)
                if n.startswith('S-'):
                    TPL[n] = e
    for key, alias in (aliases or {}).items():
        name, attrs = alias if isinstance(alias, tuple) else (alias, None)
        if name not in by_name:
            raise KeyError('alias %s: no screen item %r in %s' % (key, name, path))
        TPL[key] = by_name[name]
        if attrs:
            TPL[key] = copy.deepcopy(by_name[name])
            for k, v in attrs.items():
                setattr_(TPL[key], k, v)
    full = os.path.abspath(path)
    TPL_SOURCE.update({k: (e, full) for k, e in TPL.items()})
    return TPL

def load_shapes(path):
    """Add the objects of another full export (a screen template, a pop-up, ...) as shapes: blank() copies the
    attributes of the first object of a type from the exports loaded, root objects and layers included. The
    exports must be full (ExportSetting WithDefaults, WithReadOnly), or the copies lack the defaults."""
    _add_export(ET.parse(path).getroot())

def _add_export(root):
    """Take the first object of each type of an export as its shape, and the export's cultures."""
    for e in root.iter():
        if 'ID' in e.attrib and e.find('AttributeList') is not None:
            SHAPES.setdefault(e.tag, e)
    _hmipreview()
    from hmipreview.rules import languages
    LOADED_CULTURES.extend(c for c in languages.document_cultures(root) if c not in LOADED_CULTURES)

def generated_cultures():
    """The languages of generated texts and fonts, nothing of the generator's own: in a run the cultures of the
    project's exports (read by begin; rules.languages), else, with no export carrying one or outside a run, those of
    the exports loaded (load_templates, load_shapes), which may be another project's: the validator warns of that
    (languages.no-export). [] when neither holds one."""
    return list((_run.cultures if _run is not None else None) or LOADED_CULTURES)

def _need_cultures():
    cultures = generated_cultures()
    if not cultures:
        raise ValueError('No language known: no export of the project and no loaded export carries a text. Export a '
                         'screen of the HMI device (TiaBridge export) and run again.')
    return cultures

def _shape(tag):
    """The first object of type tag in the loaded exports, else in the screen object catalogue's fixture (full
    exports of test screens with every toolbox object dropped unchanged: a type no project export holds, such as a
    gauge or a slider), else None."""
    shape = SHAPES.get(tag)
    if shape is None:
        _hmipreview()
        from hmipreview import catalogue
        shape = catalogue.fixture_objects().get(tag)
    return shape

def blank(tag, composition=None):
    """A new object of type tag with the attribute list of the first such object in the loaded exports, else in
    the catalogue's fixture (no links, no children); an empty attribute list when neither holds one, which the
    validator reports as document.incomplete."""
    e = ET.Element(tag, {'ID': '0'})
    if composition:
        e.set('CompositionName', composition)
    shape = _shape(tag)
    e.append(copy.deepcopy(shape.find('AttributeList')) if shape is not None else ET.Element('AttributeList'))
    return e

def shape_item(tag, name, x, y, w, h, cultures=None):
    """A whole screen item of type tag ('Hmi.Screen.Gauge') copied from the first such object of the loaded
    exports, else from the catalogue's fixture: its attributes, fonts and texts (one item per culture of cultures,
    default generated_cultures(); _set_cultures), without links, animations, events and properties; name and box set
    (Left, Top, Width, Height where the type has them). KeyError when neither holds one; ValueError when the object
    has a text or font and no language is known."""
    shape = _shape(tag)
    if shape is None:
        raise KeyError('no %s in the loaded exports or the catalogue fixture' % tag)
    e = copy.deepcopy(shape)
    e.set('CompositionName', 'ScreenItems')
    for ll in e.findall('LinkList'):
        e.remove(ll)
    ol = e.find('ObjectList')
    for c in list(ol if ol is not None else []):
        if c.get('CompositionName') in ('Animations', 'Events', 'Properties'):
            ol.remove(c)
    _hmipreview()
    from hmipreview.rules import languages
    if next(languages.multilingual(e), None) is not None:
        _set_cultures(e, cultures or _need_cultures())
    have = {a.tag for a in e.find('AttributeList')}
    for k, v in (('ObjectName', name), ('Left', x), ('Top', y), ('Width', w), ('Height', h)):
        if k in have:
            setattr_(e, k, v)
    return e

def _set_cultures(e, cultures):
    """Every text and font under e gets the items of cultures, in that order: a missing one is a copy of the first item
    holding a text (else the first item) with its culture changed, an item of another culture goes."""
    _hmipreview()
    from hmipreview.rules import languages
    for _comp, ol in list(languages.multilingual(e)):
        items = {i.findtext('AttributeList/Culture'): i for i in ol}
        base = next((i for i in ol if i.find('AttributeList/Text') is not None
                     and ''.join(i.find('AttributeList/Text').itertext()).strip()), ol[0])
        new = []
        for c in cultures:
            i = items.get(c)
            if i is None:
                i = copy.deepcopy(base)
                i.find('AttributeList/Culture').text = c
            new.append(i)
        ol[:] = new

def template(style):
    """A copy of the style preset in the project's languages (_set_cultures). The presets are the S- objects of the
    export and the aliases of load_templates."""
    if style not in TPL:
        raise KeyError('style preset %s: no S- object of that name in the export loaded, and no alias of '
                       'load_templates' % style)
    e = copy.deepcopy(TPL[style])
    cultures = generated_cultures()
    if cultures:
        _set_cultures(e, cultures)
    return _copied(e, style)

def _copied(elem, key):
    """Remember, during a run, which template key a screen item was copied from, the source object (the TPL
    element's ObjectName) and, when load_templates loaded that element, its export."""
    if _run is not None:
        src = TPL.get(key)
        loaded = TPL_SOURCE.get(key)
        _run.copied[id(elem)] = (elem, {
            'preset': key,
            'source': src.findtext('AttributeList/ObjectName') if src is not None else None,
            'path': loaded[1] if loaded is not None and loaded[0] is src else None})
    return elem

# ---------------------------------------------------------------- helpers
def setattr_(e, name, value):
    al = e.find('AttributeList')
    c = al.find(name)
    if c is None:
        c = ET.SubElement(al, name)
    c.text = str(value)
    al[:] = sorted(al, key=lambda x: x.tag)

def sort_objects(e):
    ol = e.find('ObjectList')
    if ol is not None:
        ol[:] = sorted(ol, key=lambda x: x.get('CompositionName') or '')

def child_list(e):
    ol = e.find('ObjectList')
    if ol is None:
        ol = ET.SubElement(e, 'ObjectList')
    return ol

def body(lines):
    t = ET.Element('Text')
    b = ET.SubElement(t, 'body')
    p = ET.SubElement(b, 'p')
    if len(lines) == 1:
        p.text = lines[0]
    else:
        p.text = lines[0]
        for ln in lines[1:]:
            br = ET.SubElement(p, 'br')
            br.tail = ln
    return t

def set_text(e, comp, lines):
    for mt in e.iter('MultilingualText'):
        if mt.get('CompositionName') == comp:
            for it in mt.iter('MultilingualTextItem'):
                al = it.find('AttributeList')
                old = al.find('Text')
                al.remove(old)
                al.append(body(lines))
            return
    raise KeyError(comp)

def ml_text(comp, lines):
    mt = ET.Element('MultilingualText', {'ID': '0', 'CompositionName': comp})
    ol = ET.SubElement(mt, 'ObjectList')
    for c in _need_cultures():
        it = ET.SubElement(ol, 'MultilingualTextItem', {'ID': '0', 'CompositionName': 'Items'})
        al = ET.SubElement(it, 'AttributeList')
        ET.SubElement(al, 'Culture').text = c
        if lines is None:
            ET.SubElement(al, 'Text')
        else:
            al.append(body(lines))
    return mt

def appear_anim(value, back, fore):
    a = ET.Element('Hmi.Dynamic.RangeAppearanceAnimation', {'ID': '0', 'CompositionName': 'Animations'})
    ET.SubElement(ET.SubElement(a, 'AttributeList'), 'Name').text = 'RangeAppearanceAnimation'
    ol = ET.SubElement(a, 'ObjectList')
    ET.SubElement(ol, 'Hmi.Dynamic.TagElementTrigger', {'ID': '0', 'CompositionName': 'RangeTag'})
    r = ET.SubElement(ol, 'Hmi.Dynamic.Range', {'ID': '0', 'CompositionName': 'RangeValues'})
    al = ET.SubElement(r, 'AttributeList')
    ET.SubElement(al, 'BackColor').text = COL[back]
    ET.SubElement(al, 'FlashingType').text = 'No'
    ET.SubElement(al, 'ForeColor').text = COL[fore]
    ET.SubElement(al, 'LowerLimit').text = str(value)
    ET.SubElement(al, 'UpperLimit').text = str(value)
    return a

def vis_anim():
    a = ET.Element('Hmi.Dynamic.VisibilityAnimation', {'ID': '0', 'CompositionName': 'Animations'})
    al = ET.SubElement(a, 'AttributeList')
    ET.SubElement(al, 'Name').text = 'VisibilityAnimation'
    ET.SubElement(al, 'RangeEnd').text = '1'
    ET.SubElement(al, 'RangeStart').text = '1'
    ET.SubElement(al, 'Visible').text = 'true'
    ET.SubElement(ET.SubElement(a, 'ObjectList'), 'Hmi.Dynamic.TagElementTrigger', {'ID': '0', 'CompositionName': 'VisibilityTag'})
    return a

def hold_event():
    ev = ET.Element('Hmi.Event.Event', {'ID': '0', 'CompositionName': 'Events'})
    ET.SubElement(ET.SubElement(ev, 'AttributeList'), 'Name').text = 'Press'
    h = ET.SubElement(ET.SubElement(ev, 'ObjectList'), 'Hmi.Event.FunctionListEventHandler', {'ID': '0', 'CompositionName': 'EventHandler'})
    fe = ET.SubElement(ET.SubElement(h, 'ObjectList'), 'Hmi.Event.FunctionListEntry', {'ID': '0', 'CompositionName': 'FunctionListEntries'})
    al = ET.SubElement(fe, 'AttributeList')
    ET.SubElement(al, 'Name').text = 'SetBitWhileKeyPressed'
    ET.SubElement(al, 'Type').text = 'SystemFunction'
    ol = ET.SubElement(fe, 'ObjectList')
    p1 = ET.SubElement(ol, 'Hmi.Event.FunctionListEntryParameter', {'ID': '0', 'CompositionName': 'Parameters'})
    ET.SubElement(ET.SubElement(p1, 'AttributeList'), 'Name').text = 'Tag'
    p2 = ET.SubElement(ol, 'Hmi.Event.FunctionListEntryParameter', {'ID': '0', 'CompositionName': 'Parameters'})
    al2 = ET.SubElement(p2, 'AttributeList')
    ET.SubElement(al2, 'Name').text = 'Bit'
    ET.SubElement(al2, 'Value', {'Type': 'System.Int32'}).text = '0'
    return ev

def link(e, kind, name):
    ll = e.find('LinkList')
    if ll is None:
        ll = ET.Element('LinkList')
        kids = list(e)
        idx = kids.index(e.find('AttributeList')) + 1
        e.insert(idx, ll)
    l = ET.SubElement(ll, kind, {'TargetID': '@OpenLink'})
    ET.SubElement(l, 'Name').text = name

# ---------------------------------------------------------------- one screen item
def item(o):
    st, m = o['style'], o['m']
    e = template(st)
    # drop animations / properties / events the template may carry
    ol = e.find('ObjectList')
    if ol is not None:
        for c in list(ol):
            if c.get('CompositionName') in ('Animations', 'Events', 'Properties'):
                ol.remove(c)
    x, y = o['x'] + o.get('ox', 0), o['y'] + o.get('oy', 0)
    setattr_(e, 'ObjectName', o['name'])
    if o['type'] == 'Polygon':                        # Polyline as the preset: closed triangle 20 x 20
        pts = [(x, y + 20), (x + 11, y), (x + 20, y + 20), (x, y + 20)]
        setattr_(e, 'Points', '\ufeff' + ''.join(f'<Item>{a}, {b}</Item>' for a, b in pts))
        setattr_(e, 'Left', x); setattr_(e, 'Top', y); setattr_(e, 'Width', 20); setattr_(e, 'Height', 20)
    else:
        setattr_(e, 'Left', x); setattr_(e, 'Top', y); setattr_(e, 'Width', o['w']); setattr_(e, 'Height', o['h'])
    if o['type'] == 'Circle':                          # exported circles carry Radius = Width / 2 beside the box
        setattr_(e, 'Radius', o['w'] // 2)
    if o['type'] == 'Text field':
        set_text(e, 'Text', m['text'])
    if o['type'] == 'Button':
        set_text(e, 'TextOff', m['text'])
        set_text(e, 'TextOn', m['text'])
        child_list(e).append(hold_event())
    if o['type'] == 'I/O field':
        setattr_(e, 'FormatPattern', m['fmt'])
        setattr_(e, 'FieldLength', len(m['fmt'].lstrip('s')))
    if o['type'] == 'Symbolic I/O field':
        if 'mode' in m:
            setattr_(e, 'Mode', m['mode'])
        link(e, 'TextList', m['tl'])
    a = m.get('anim')
    if a:
        child_list(e).append(appear_anim(a[1], a[2], a[3]))
    if m.get('vis'):
        child_list(e).append(vis_anim())
    sort_objects(e)
    return e

def group(name, members):
    g = blank('Hmi.Screen.Group', 'ScreenItems')
    setattr_(g, 'ObjectName', name)
    ol = ET.SubElement(g, 'ObjectList')
    for mbr in members:
        ol.append(mbr)
    return g

# ---------------------------------------------------------------- document
def document(root_elem):
    doc = ET.Element('Document')
    ET.SubElement(doc, 'Engineering', {'version': 'V20'})
    if troot is not None:            # a tag table needs no loaded export
        doc.append(copy.deepcopy(troot.find('DocumentInfo')))
    doc.append(root_elem)
    n = 0
    for e in doc.iter():
        if 'ID' in e.attrib:
            e.set('ID', format(n, 'X')); n += 1
    return doc

def indent(e, level=0):
    # like ET.indent, but rich text (<Text><body><p>..</p></body></Text>) stays on one line as exported
    if e.tag == 'Text':
        return
    kids = list(e)
    if kids:
        pad = '\n' + '  ' * (level + 1)
        if not (e.text or '').strip():
            e.text = pad
        for k in kids:
            indent(k, level + 1)
            if not (k.tail or '').strip():
                k.tail = pad
        kids[-1].tail = '\n' + '  ' * level

def serialize(doc):
    """The bytes finish() puts in a file: UTF-8 with BOM, CRLF, indented as exported."""
    indent(doc)
    s = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding='unicode') + '\n'
    return s.replace('\n', '\r\n').encode('utf-8-sig')

def _root(tag, name, width, height, number=None, back=None):
    """Root object copied from an exported one of its type (blank), with name, size, number and colour set."""
    root = blank(tag)
    for k, v in (('BackColor', back), ('Height', height), ('Name', name), ('Number', number), ('Width', width)):
        if v is not None:
            setattr_(root, k, v)
    return root

def _layer(parent):
    """Layer 0 copied from an exported layer (blank), unnamed; returns its ObjectList."""
    lay = blank('Hmi.Screen.ScreenLayer', 'Layers')
    setattr_(lay, 'Index', 0)
    setattr_(lay, 'Name', '')
    parent.append(lay)
    return ET.SubElement(lay, 'ObjectList')

def screen(name, number, objs):
    width, height = size()
    sc = _root('Hmi.Screen.Screen', name, width, height, number, COL['screen'])
    ol = ET.SubElement(sc, 'ObjectList')
    ol.append(ml_text('HelpText', None))
    items = _layer(ol)
    # group per panel (group key) and the banner objects; background and strip stay single
    order, groups = [], {}
    for o in objs:
        e = item(o)
        gk = o['m'].get('grp') or (o['group']['key'] if o['group'] and o['group']['key'] not in ('bg', 'strip') else None)
        if gk:
            if gk not in groups:
                groups[gk] = []
                order.append(('g', gk))
            groups[gk].append(e)
        else:
            order.append(('e', e))
    for kind, v in order:
        if kind == 'e':
            items.append(v)
        else:
            items.append(group('grp' + v, groups[v]) if len(groups[v]) > 1 else groups[v][0])
    return document(sc)

def tag_table(name, tags):
    """Tag table document, in a run (begin). tags: dicts, one per HMI tag:
      name         the HMI tag
      data_type    DataType, the PLC's ('Int', 'Word', '"Motor_UDT"', ...), or the internal tag's
      cycle        AcquisitionCycle ('1 s', '100 ms'); optional: an internal tag's export carries none
      plc_tag      ControllerTag ('"Data".speed'); with connection, the tag reads the PLC; without both, internal
      connection   Connection
      hmi_type     HmiDataType; without it the one TIA takes for data_type (Word gets UInt; rules.tagtable)
    Length is the size of data_type: the S7 size of an elementary type or of an array of one (not of Bool), and of
    another S7 type of a fixed size (Time, Char, DTL, ...; not of an array of one), else, for a string or a PLC data
    type, the Length its tags carry in the project's tag table files (rules.tagtable). ValueError when nothing knows
    the size or the HmiDataType, or the data type is one the validator cannot check: an Int tag with Length 1 ended
    TIA."""
    _need_run('tag_table')
    from hmipreview.rules import tagtable
    known = _run.tag_knowledge
    tt = ET.Element('Hmi.Tag.TagTable', {'ID': '0'})
    ET.SubElement(ET.SubElement(tt, 'AttributeList'), 'Name').text = name
    ol = ET.SubElement(tt, 'ObjectList')
    for t in tags:
        dtype = t['data_type']
        size = known.size(dtype)
        if size is None:
            raise ValueError('tag %s: %s Begin the run again after.' % (t['name'], known.size_problem(dtype)))
        hmi_type = t.get('hmi_type') or known.hmi_type(dtype)
        if hmi_type is None:
            raise ValueError('tag %s: the HmiDataType of data type %s is not known, as no tag table export of the '
                             'project holds a tag of it; %s and begin the run again'
                             % (t['name'], dtype, tagtable.EXPORT_ONE))
        tag = ET.SubElement(ol, 'Hmi.Tag.Tag', {'ID': '0', 'CompositionName': 'Tags'})
        al = ET.SubElement(tag, 'AttributeList')
        ET.SubElement(al, 'Length').text = str(size)
        ET.SubElement(al, 'Name').text = t['name']
        ll = ET.SubElement(tag, 'LinkList')
        for kind, value in (('AcquisitionCycle', t.get('cycle')), ('Connection', t.get('connection')),
                            ('ControllerTag', t.get('plc_tag')), ('DataType', dtype), ('HmiDataType', hmi_type)):
            if value is not None:
                ET.SubElement(ET.SubElement(ll, kind, {'TargetID': '@OpenLink'}), 'Name').text = value
        tol = ET.SubElement(tag, 'ObjectList')
        tol.append(ml_text('Comment', None))
        tol.append(ml_text('DisplayName', None))
    return document(tt)

def textlist(name, entries):
    tl = ET.Element('Hmi.TextGraphicList.TextList', {'ID': '0'})
    ET.SubElement(ET.SubElement(tl, 'AttributeList'), 'Name').text = name
    ol = ET.SubElement(tl, 'ObjectList')
    ol.append(ml_text('Comment', None))
    for v, txt in entries:
        en = ET.SubElement(ol, 'Hmi.TextGraphicList.TextListEntry', {'ID': '0', 'CompositionName': 'Entries'})
        al = ET.SubElement(en, 'AttributeList')
        ET.SubElement(al, 'From').text = str(v)
        ET.SubElement(al, 'To').text = str(v)
        ET.SubElement(en, 'ObjectList').append(ml_text('Text', [txt]))
    return document(tl)


# ================================================================ tags, events, graphics, templates (01.10.2026, redesign)
# Shapes copied from the project B exports (zzExportTest2, 5003, 002, template 02, 1005).
def tag_link(parent, name, kind='Tag'):
    """<LinkList><Tag TargetID="@OpenLink"><Name>name</Name></Tag></LinkList> under parent (after its AttributeList)."""
    ll = parent.find('LinkList')
    if ll is None:
        ll = ET.Element('LinkList')
        al = parent.find('AttributeList')
        parent.insert(list(parent).index(al) + 1 if al is not None else 0, ll)
    l = ET.SubElement(ll, kind, {'TargetID': '@OpenLink'})
    ET.SubElement(l, 'Name').text = name
    return l

def process_value(e, tag):
    """I/O field / symbolic I/O field: ProcessValue property connected to a tag."""
    p = ET.Element('Hmi.Screen.Property', {'ID': '0', 'CompositionName': 'Properties'})
    ET.SubElement(ET.SubElement(p, 'AttributeList'), 'Name').text = 'ProcessValue'
    d = ET.SubElement(ET.SubElement(p, 'ObjectList'), 'Hmi.Dynamic.TagConnectionDynamic', {'ID': '0', 'CompositionName': 'Dynamic'})
    ET.SubElement(ET.SubElement(d, 'AttributeList'), 'Indirect').text = 'false'
    tag_link(d, tag)
    child_list(e).append(p)

def trigger(comp, tag):
    t = ET.Element('Hmi.Dynamic.TagElementTrigger', {'ID': '0', 'CompositionName': comp})
    if tag:
        tag_link(t, tag)
    return t

def appear_anim_tag(tag, ranges):
    """RangeAppearanceAnimation; ranges = [(lower, upper, backKey, foreKey)]; tag None leaves the trigger open."""
    a = ET.Element('Hmi.Dynamic.RangeAppearanceAnimation', {'ID': '0', 'CompositionName': 'Animations'})
    ET.SubElement(ET.SubElement(a, 'AttributeList'), 'Name').text = 'RangeAppearanceAnimation'
    ol = ET.SubElement(a, 'ObjectList')
    ol.append(trigger('RangeTag', tag))
    for lo, hi, back, fore in ranges:
        r = ET.SubElement(ol, 'Hmi.Dynamic.Range', {'ID': '0', 'CompositionName': 'RangeValues'})
        al = ET.SubElement(r, 'AttributeList')
        ET.SubElement(al, 'BackColor').text = COL[back]
        ET.SubElement(al, 'FlashingType').text = 'No'
        ET.SubElement(al, 'ForeColor').text = COL[fore]
        ET.SubElement(al, 'LowerLimit').text = str(lo)
        ET.SubElement(al, 'UpperLimit').text = str(hi)
    return a

def vis_anim_tag(tag, lo=1, hi=1, visible=True):
    a = ET.Element('Hmi.Dynamic.VisibilityAnimation', {'ID': '0', 'CompositionName': 'Animations'})
    al = ET.SubElement(a, 'AttributeList')
    ET.SubElement(al, 'Name').text = 'VisibilityAnimation'
    ET.SubElement(al, 'RangeEnd').text = str(hi)
    ET.SubElement(al, 'RangeStart').text = str(lo)
    ET.SubElement(al, 'Visible').text = 'true' if visible else 'false'
    ET.SubElement(a, 'ObjectList').append(trigger('VisibilityTag', tag))
    return a

def func(name, params=()):
    """One system function. params: (name, kind, value) with kind 'link' (tag / screen / pop-up by name,
    None = left open), 'self' (the own screen or pop-up, TargetID #0), 'int' (System.Int32) or 'double' (System.Double)."""
    fe = ET.Element('Hmi.Event.FunctionListEntry', {'ID': '0', 'CompositionName': 'FunctionListEntries'})
    al = ET.SubElement(fe, 'AttributeList')
    ET.SubElement(al, 'Name').text = name
    ET.SubElement(al, 'Type').text = 'SystemFunction'
    if params:
        ol = ET.SubElement(fe, 'ObjectList')
        for pn, kind, val in params:
            p = ET.SubElement(ol, 'Hmi.Event.FunctionListEntryParameter', {'ID': '0', 'CompositionName': 'Parameters'})
            pal = ET.SubElement(p, 'AttributeList')
            ET.SubElement(pal, 'Name').text = pn
            if kind == 'link':
                if val is not None:
                    tag_link(p, val, 'Value')
            elif kind == 'self':                      # the own screen / pop-up (TargetID #0, as exported)
                ll = ET.Element('LinkList')
                p.insert(list(p).index(pal) + 1, ll)
                ET.SubElement(ll, 'Value', {'TargetID': '#0'})
            else:
                ET.SubElement(pal, 'Value', {'Type': 'System.Int32' if kind == 'int' else 'System.Double'}).text = str(val)
    return fe

def event(name, funcs):
    ev = ET.Element('Hmi.Event.Event', {'ID': '0', 'CompositionName': 'Events'})
    ET.SubElement(ET.SubElement(ev, 'AttributeList'), 'Name').text = name
    h = ET.SubElement(ET.SubElement(ev, 'ObjectList'), 'Hmi.Event.FunctionListEventHandler', {'ID': '0', 'CompositionName': 'EventHandler'})
    ol = ET.SubElement(h, 'ObjectList')
    for f in funcs:
        ol.append(f)
    return ev

def graphic_view(name, x, y, w, h, picture):
    """Graphic view copied from an exported one (blank): its look as exported, geometry, name and picture set."""
    e = blank('Hmi.Screen.GraphicView', 'ScreenItems')
    for k, v in (('Height', h), ('Left', x), ('ObjectName', name), ('Top', y), ('Width', w)):
        setattr_(e, k, v)
    tag_link(e, picture, 'Picture')
    return e

def renumber(doc):
    n = 0
    for e in doc.iter():
        if 'ID' in e.attrib:
            e.set('ID', format(n, 'X')); n += 1

def screen_doc(name, number, items, template=None, events=(), back='screen', is_template=False, popup=None):
    """Screen, screen template or pop-up screen document from ready screen-item elements, in the order of the
    file (layerOrder of hmipreview.diff; what it means on TIA's screen: the guide, section 4). popup=(width, height):
    Hmi.Screen.ScreenPopup as exported (Place Data, run 5): no number, no template, no help text."""
    kind = 'Hmi.Screen.ScreenTemplate' if is_template else ('Hmi.Screen.ScreenPopup' if popup else 'Hmi.Screen.Screen')
    width, height = popup if popup else size()
    root = _root(kind, name, width, height, number if not is_template and not popup else None,
                 COL[back] if not is_template else None)
    if template:
        tag_link(root, template, 'Template')
    ol = ET.SubElement(root, 'ObjectList')
    for ev in events:
        ol.append(ev)
    if not is_template and not popup:
        ol.append(ml_text('HelpText', None))
    lol = _layer(ol)
    for it in items:
        lol.append(it)
    doc = document(root)
    renumber(doc)
    return doc


# ================================================================ generator run (06.10.2026, HMI preview)
KIND_DIRS = {'screen': 'screens', 'template': 'templates', 'popup': 'popups', 'textlist': 'textlists',
             'tagtable': 'tags'}
# Below <hmi> (hmi, or hmi/<device folder>: hmipreview.model.hmi_base); read by hmipreview (model.Repo.planned_file,
# generation_file: generated_time, presets; panel_file: the declared target panel).
PLANNED = 'generated/planned.json'
GENERATED_TIMES = 'generated/generated.json'
PANEL = 'panel.json'


class GenerationRefused(Exception):
    """The validator found errors in a run; nothing of the run was kept. .findings: the run's findings."""

    def __init__(self, findings):
        self.findings = findings
        errors = [f for f in findings if f.severity == 'error']
        super().__init__('%d error(s), nothing written:\n%s' % (len(errors), '\n'.join(str(f) for f in errors)))


class _Run:
    def __init__(self, repo, resolution, base='hmi', device=None):
        self.repo = repo
        self.resolution = resolution
        self.base = base         # hmi, or hmi/<device folder>
        self.device = device     # the device folder, else the device given to begin (one-device layout); or None
        self.planned = []
        self.docs = []           # (repo-relative path, doc)
        self.copied = {}         # id(screen item) -> (screen item, {preset, source, path}) (_copied)
        self.panel_file = None   # bytes of hmi/panel.json when begin(panel=...) declares the panel with this run
        self.cultures = []       # the languages of the project's exports (rules.languages.project_cultures)
        self.tag_knowledge = None  # rules.tagtable.Knowledge: ELEMENTARY, FIXED_SIZE and the project's tag table
                                   # exports


_run = None


def _hmipreview():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import hmipreview
    from hmipreview import resolution
    return hmipreview, resolution


def _config(repo):
    try:
        with open(os.path.join(repo, 'tiabridge.json'), encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError) as ex:
        raise ValueError('tiabridge.json of %s not readable: %s' % (repo, ex))


def _device(repo, config, device):
    """The device folder ('' for the one-device layout) of the run; ValueError when none can be chosen."""
    _hmipreview()
    from hmipreview import model
    folder, problem = model.select_device(repo, config, device)
    if problem:
        raise ValueError(problem)
    return folder


def generated_dirs(repo, device=None):
    """{kind: absolute folder} of the generated documents of an HMI device (begin) in a project repo."""
    repo = os.path.abspath(repo)
    folder = _device(repo, _config(repo), device)
    base = os.path.join(repo, 'hmi', *([folder] if folder else []), 'generated')
    return {k: os.path.join(base, d) for k, d in KIND_DIRS.items()}


def begin(repo, panel=None, device=None):
    """Start a generator run for the project repo and one HMI device; returns the resolution of the declared target
    panel.

    device: with one folder per HMI device under hmi/ (hmi/<device>/...), the device's name or folder; without it
    tiabridge.json hmiDevice, else the only device folder; ValueError when none can be chosen. The run writes into
    the device's folder (<hmi> = hmi/<device>, or hmi with one device).
    The panel is declared once in <hmi>/panel.json (python -m hmipreview panel, or panel= here: the panel name, order
    number or WxH, saved with the run's files by finish). Without a declared panel and without panel= it raises
    ValueError listing the panels and offering the HMI device in TIA as the default; it never saves one silently.
    It also raises when panel= differs from the declared panel, and when the declared panel and the HMI device in
    TIA (tiabridge.json hmiTypeIdentifier) differ in size or orientation (resolution.mismatch)."""
    global _run
    _hp, resolution = _hmipreview()
    from hmipreview import model
    repo = os.path.abspath(repo)
    config = _config(repo)
    folder = _device(repo, config, device)
    base = model.hmi_base(folder)
    tid, problem = resolution.select_type_identifier(config, folder or device, model.folder_name)
    if problem:
        raise ValueError(problem)
    hardware = resolution.resolve(tid)
    panel_rel = base + '/' + PANEL
    saved = _saved_panel(repo, panel_rel, resolution)
    panel_file = None
    if panel is not None:
        chosen = resolution.parse_panel(panel)
        res, _ = resolution.panel_resolution(chosen)
        if saved is not None and not (res.same_screen(saved) and res.panel == saved.panel):
            raise ValueError('The target panel is declared as %s in %s; begin(panel=%r) asks for %s. Declare it '
                             'again to change it: %s' % (saved.describe(), panel_rel, panel,
                                                         res.describe(), resolution.PANEL_COMMAND))
        if saved is None:
            panel_file = resolution.panel_bytes(chosen)
    elif saved is not None:
        res = saved
    else:
        raise ValueError(_ask_for_panel(resolution, tid, hardware, panel_rel, folder))
    if hardware is not None and not res.same_screen(hardware):
        raise ValueError('resolution.mismatch: the target panel %s differs from the HMI device in TIA, %s. Declare '
                         'the panel again (%s) or fix the device in TIA.'
                         % (res.describe(), hardware.describe(), resolution.PANEL_COMMAND))
    _run = _Run(repo, res, base, folder or device)
    _run.panel_file = panel_file
    from hmipreview.rules import languages, tagtable
    loaded = model.load(repo, device=folder or device)
    _run.cultures = languages.project_cultures(loaded)
    _run.tag_knowledge = tagtable.knowledge(loaded)
    return res


def _saved_panel(repo, rel, resolution):
    """Resolution of the panel file rel (<hmi>/panel.json), None when there is none; ValueError when it is not
    usable."""
    full = os.path.join(repo, *rel.split('/'))
    if not os.path.exists(full):
        return None
    try:
        with open(full, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError) as ex:
        raise ValueError('%s not readable: %s' % (rel, ex))
    res, problem = resolution.panel_resolution(data)
    if problem:
        raise ValueError('%s: %s' % (rel, problem))
    return res


def _ask_for_panel(resolution, tid, hardware, panel_rel, folder):
    """The message of a first run without a declared panel: the table, the command, the hardware as the default."""
    dev = ' --device "%s"' % folder if folder else ''
    lines = ['No target panel declared (%s). Ask the user which panel the screens are for, then declare it once:'
             % panel_rel, '  ' + resolution.PANEL_COMMAND,
             '  (or hmixml.begin(repo, panel=...), saved with the run)', 'Panels:', resolution.panel_table()]
    if hardware is not None:
        spec = hardware.order_number + (' --portrait' if hardware.portrait else '')
        lines.append('The HMI device in TIA is %s; to take it: python -m hmipreview panel <repo> %s%s'
                     % (hardware.describe(), spec, dev))
    elif tid:
        lines.append("The HMI device in TIA, '%s', is not in the table; give the panel or its size WxH." % (tid,))
    return '\n'.join(lines)


def size():
    """(width, height) of screens and templates: the run's declared panel. RuntimeError outside a run."""
    _need_run('size')
    return _run.resolution.width, _run.resolution.height


def _need_run(fn):
    if _run is None:
        raise RuntimeError('%s() outside a run: call begin(repo) first' % fn)


def plan(kind, name, note=''):
    """Declare a planned item of this run (one entry per kind and name)."""
    _need_run('plan')
    if not any(p['kind'] == kind and p['name'] == name for p in _run.planned):
        _run.planned.append({'kind': kind, 'name': name, 'note': note})


def add(kind, doc, folder=''):
    """Queue a document of this run; returns its repo-relative path."""
    from hmipreview import model
    _need_run('add')
    if kind not in KIND_DIRS:
        raise ValueError('kind %r, expected one of %s' % (kind, ', '.join(KIND_DIRS)))
    root = next((c for c in doc if 'ID' in c.attrib), None)
    name = root.findtext('AttributeList/Name') if root is not None else None
    if not name:
        raise ValueError('document without a Name')
    # the file-safe form, as TiaBridge writes it: a ':' in a path would write an alternate stream, and no file. An import
    # makes the TIA folder of the path, so a folder that changed here needs target_folder for its real name.
    parts = ([_run.base, 'generated', KIND_DIRS[kind]]
             + [model.folder_name(p) for p in folder.replace('\\', '/').split('/') if p])
    rel = '/'.join(parts + [model.folder_name(name) + '.xml'])
    # without case: Windows would hold one file for both
    if any(r.lower() == rel.lower() for r, _ in _run.docs):
        raise ValueError('%s added twice in this run (or a name differing only in case)' % rel)
    _run.docs.append((rel, doc))
    return rel


def _full(rel):
    return os.path.join(_run.repo, *rel.split('/'))


def _relevant(f, paths):
    """A finding belongs to the run when it is on one of the run's files or on the repo (tiabridge.json,
    <hmi>/panel.json, ...: any file that is not a document)."""
    return f.document in paths or not f.document.lower().endswith('.xml')


def finish():
    """Validate the run, then write it or refuse it (module docstring). Returns the run's findings."""
    global _run
    _need_run('finish')
    hp, _res = _hmipreview()
    try:
        return _finish(hp)
    finally:
        _run = None                 # a run ends with finish, kept or refused


def _json_bytes(data):
    return (json.dumps(data, indent=2, sort_keys=isinstance(data, dict)) + '\n').encode('utf-8')


def _presets(doc):
    """{ObjectName: {preset, source, document}} of the screen items in doc that template() copied during this run;
    document repo-relative, None when the export is unknown or outside the repo."""
    out = {}
    for e in doc.iter():
        hit = _run.copied.get(id(e))
        if hit is not None and hit[0] is e:
            name = e.findtext('AttributeList/ObjectName')
            if name:
                rec = hit[1]
                out[name] = {'preset': rec['preset'], 'source': rec['source'], 'document': _repo_rel(rec['path'])}
    return out


def _repo_rel(path):
    if not path:
        return None
    try:
        rel = os.path.relpath(path, _run.repo)
    except ValueError:                                # another drive
        return None
    return None if rel.startswith('..') or os.path.isabs(rel) else rel.replace(os.sep, '/')


def _generation_record():
    """generated.json after this run: records of earlier runs whose file still exists, this run's documents now."""
    try:
        with open(_full(_run.base + '/' + GENERATED_TIMES), encoding='utf-8-sig') as f:
            record = json.load(f)
        if not isinstance(record, dict):
            record = {}
    except (OSError, ValueError):
        record = {}
    record = {p: r for p, r in record.items() if os.path.exists(_full(p))}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    for rel, doc in _run.docs:
        record[rel] = {'generated': now, 'presets': _presets(doc)}
    return record


def _finish(hp):
    """Validate the run's files as an overlay on the repo; write them only when there is no error."""
    files = {rel: serialize(doc) for rel, doc in _run.docs}
    files[_run.base + '/' + PLANNED] = _json_bytes(_run.planned)
    files[_run.base + '/' + GENERATED_TIMES] = _json_bytes(_generation_record())
    if _run.panel_file is not None:
        files[_run.base + '/' + PANEL] = _run.panel_file
    findings = [f for f in hp.validate(_run.repo, overlay=files, device=_run.device) if _relevant(f, files)]
    for f in findings:
        print(f)
    if any(f.severity == hp.ERROR for f in findings):
        raise GenerationRefused(findings)
    for rel, data in files.items():
        os.makedirs(os.path.dirname(_full(rel)), exist_ok=True)
        with open(_full(rel), 'wb') as f:
            f.write(data)
    return findings
