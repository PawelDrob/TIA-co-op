"""Project repo model: the HMI documents and data files as they are on disk.

Layout (project repo). <hmi> is hmi/ for a project with one HMI device and hmi/<device>/ for each device of a
project with several (TiaBridge export; the folder is the device name with \\/:*?"<>| as _).
load() reads one device: the device given, else tiabridge.json hmiDevice, else the only device folder.
  <hmi>/screens, <hmi>/templates, <hmi>/popups, <hmi>/textlists  TIA exports (sub-folders = TIA folders)
  <hmi>/generated/{screens,templates,popups,textlists}       generated documents
  <hmi>/tags, <hmi>/generated/tags                           HMI tag tables, exported and generated: Repo.tag_tables
                                                             (kind 'tagtable'), apart from the documents above
  <hmi>/cycles                                               cycles as TIA exports them, which TiaBridge also imports
                                                             from there: Repo.cycles (kind 'cycle'), apart too
  hmi/<other device>/{screens,templates,popups,textlists}    exports of the other HMI devices: vocabulary only
  hmi/references/<source>/{screens,templates,popups,...}     full exports of another project (e.g. a sister project) whose
                                                             objects a generator copies: they feed the vocabulary
                                                             and the known styles and authorizations, nothing else
                                                             (not objects of this project's TIA)
  <hmi>/generated/planned.json                               planned items [{kind, name, note}]
  <hmi>/generated/generated.json                               per generated document, written by hmixml.finish:
                                                             {path: {generated: ISO time, presets: {ObjectName:
                                                             {preset, source, document}}}}; an old preset is a
                                                             plain string (the key only)
  <hmi>/handbuilt.json                                      hand-built objects [{screen, kind, x, y, w, h}]
  hmi/graphics.json                                          names of the project's graphics as TIA lists them
                                                             (Project.Graphics): pictures that exist although no
                                                             export shows them
  <hmi>/panel.json                                          declared target panel {panel, orderNumber (optional),
                                                             width, height, portrait}; written by the panel command
                                                             or hmixml.begin(repo, panel=...)
  library/faceplates/<folder>/<type>.type.json               TiaBridge export of kind faceplate_type: per faceplate
                                                             type {name, folder ('/'-separated library folder),
                                                             versions: ['0.0.3', ...]}, beside the version metadata
                                                             files <type>_V<version>.xml (not read here)
  tiabridge.json                                             hmiTypeIdentifier (string, or {device: id}),
                                                             optional hmiDevice (the device to read), startScreen

A generated document replaces the export of the same kind and name (effective set).
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

from . import resolution as _resolution
from .findings import error
from .sides import KIND_DIRS as _TOP_KIND_DIRS

KINDS = ('screen', 'template', 'popup', 'textlist')
TAG_TABLE = 'tagtable'    # the kind of a tag table document; not one of KINDS: no screen rule reads it
CYCLE = 'cycle'           # the kind of a cycle document; not one of KINDS either
KIND_DIRS = {'screen': 'screens', 'template': 'templates', 'popup': 'popups', 'textlist': 'textlists',
             TAG_TABLE: 'tags', CYCLE: 'cycles'}
EXPORT = 'export'
REFERENCE = 'reference'
REFERENCE_DIR = 'hmi/references'
GENERATED = 'generated'
FACEPLATE_DIR = 'library/faceplates'
TOP_FOLDERS = frozenset(_TOP_KIND_DIRS) | {GENERATED, 'references'}   # folders of hmi/ that are no device folder


def device_folders(repo_path):
    """The HMI device folders under hmi/ (sorted), [] for the one-device layout (hmi/screens, ...)."""
    top = os.path.join(repo_path, 'hmi')
    try:
        names = os.listdir(top)
    except OSError:
        return []
    return sorted(n for n in names if n not in TOP_FOLDERS and os.path.isdir(os.path.join(top, n)))


def folder_name(device):
    """The file or folder name TiaBridge makes of an object's or device's name (ConvertTo-SafeFileName, Repo.ps1): the
    characters Windows forbids and control characters as _, a dot, space, no-break space or U+0085 at the end as _, a
    device name with _ behind it, no name as _."""
    if not device:
        return '_'
    s = re.sub(r'[. \u00a0\u0085]+$', '_', re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', device))
    return re.sub(r'^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\.|$)',
                  r'\1_\2', s, flags=re.IGNORECASE)


DEVICE_HINT = ('pass --device NAME (python -m hmipreview), hmixml.begin(repo, device=NAME), or set hmiDevice in '
               'tiabridge.json')


def select_device(repo_path, config, device=None):
    """(device folder, problem) of the HMI device to read. With device folders under hmi/: device (a device name or
    its folder), else tiabridge.json hmiDevice, else the only folder; several folders and neither, or a name with no
    folder, give folder None and the problem (what to pass). Without device folders (one-device layout) the folder
    is ''; a device given must then be one of hmiTypeIdentifier's (it selects the hardware, as hmiDevice does)."""
    folders = device_folders(repo_path)
    if not folders:
        tid = config.get('hmiTypeIdentifier') if isinstance(config, dict) else None
        if device and isinstance(tid, dict) and not any(device in (k, folder_name(k)) for k in tid):
            return None, ("HMI device '%s' is not one of the HMI devices in tiabridge.json hmiTypeIdentifier (%s)."
                          % (device, ', '.join(sorted(tid)) or 'none'))
        return '', None
    wanted = device or (config.get('hmiDevice') if isinstance(config, dict) else None)
    if isinstance(wanted, str) and wanted:
        for f in folders:
            if f in (wanted, folder_name(wanted)):
                return f, None
        return None, ("HMI device '%s'%s has no folder under hmi/ (devices: %s); %s."
                      % (wanted, '' if device else ' (tiabridge.json hmiDevice)', ', '.join(folders), DEVICE_HINT))
    if len(folders) == 1:
        return folders[0], None
    return None, 'hmi/ holds the folders of several HMI devices (%s); choose one: %s.' % (', '.join(folders),
                                                                                          DEVICE_HINT)


def hmi_base(device):
    """The repo-relative folder of a device's HMI files: hmi, or hmi/<device folder>."""
    return 'hmi/' + device if device else 'hmi'


@dataclass
class Document:
    kind: str                 # 'screen' | 'template' | 'popup' | 'textlist' | 'tagtable' | 'cycle'
    origin: str               # 'export' | 'generated'
    path: str                 # repo-relative, forward slashes
    folder: str               # TIA folder below the kind folder, '/'-separated, '' at the root
    name: str                 # Name attribute of the root object (file stem if it has none)
    tree: ET.Element          # the <Document> element
    obj: ET.Element | None    # the root object (Hmi.Screen.Screen, ...), the first child with an ID

    def attr(self, name, default=None):
        """Attribute of the root object (AttributeList child text)."""
        return attribute(self.obj, name, default) if self.obj is not None else default

    @property
    def export_setting(self):
        """DocumentInfo/ExportSetting as TIA wrote it ('WithDefaults, WithReadOnly', 'None'), None when absent."""
        return self.tree.findtext('DocumentInfo/ExportSetting')

    @property
    def full(self):
        """A full export: every attribute, defaults and read-only ones included (ExportSetting names both)."""
        s = self.export_setting or ''
        return 'WithDefaults' in s and 'WithReadOnly' in s


@dataclass
class Repo:
    """The repo as load() read it. The data files are normalized there: config and generation are dicts,
    planned and handbuilt lists, whatever the files hold (a wrong type gives a repo.json finding)."""
    path: str
    config: dict
    exports: list
    generated: list
    planned: list             # planned.json entries as written (the links rules report malformed ones)
    handbuilt: list           # handbuilt.json entries that are objects
    resolution: object        # resolution.Resolution or None: the declared panel, else the hardware
    load_findings: list = field(default_factory=list)
    generation: dict = field(default_factory=dict)    # {path: {'generated': str or None, 'presets': {name: {...}}}}
    type_identifier: object = None   # TypeIdentifier of the selected HMI device (resolution.select_type_identifier)
    device_problem: str | None = None  # why no device could be selected (several devices, no hmiDevice)
    faceplate_types: list | None = None  # [{name, folder, versions}] of library/faceplates; None when not exported
    panel: object = None      # resolution.Resolution of the declared panel hmi/panel.json, None when not declared
    hardware: object = None   # resolution.Resolution of the selected HMI device's TypeIdentifier, None when unknown
    references: list = field(default_factory=list)  # documents under hmi/references/<source> (vocabulary only)
    graphics: list = field(default_factory=list)    # hmi/graphics.json: graphic names of the project
    device: str | None = ''   # device folder under hmi/ ('' one-device layout, None when none could be chosen)
    devices: list = field(default_factory=list)     # every device folder under hmi/ ([] one-device layout)
    other_exports: list = field(default_factory=list)  # exports of the other device folders (vocabulary only)
    tag_types: dict = field(default_factory=dict)      # {HMI tag name: HMI data type} of this device's tag tables
    tag_tables: list = field(default_factory=list)     # this device's tag tables (Document, kind 'tagtable'), exports
                                                       # then generated
    other_tag_tables: list = field(default_factory=list)  # tag table exports of the other devices and the references
    cycles: list = field(default_factory=list)         # this device's cycles (Document, kind 'cycle'), from <hmi>/cycles

    @property
    def base(self):
        """hmi, or hmi/<device folder>: the folder of this device's exports, generated documents and data files."""
        return hmi_base(self.device)

    @property
    def panel_file(self):
        return self.base + '/panel.json'

    @property
    def planned_file(self):
        return self.base + '/generated/planned.json'

    @property
    def generation_file(self):
        return self.base + '/generated/generated.json'

    @property
    def handbuilt_file(self):
        return self.base + '/handbuilt.json'

    def generated_stamp(self, doc):
        """The ISO time generated.json records for doc, or None."""
        return self.generation.get(doc.path, {}).get('generated')

    def generated_time(self, doc):
        """When the generator last wrote doc (seconds since the epoch), from generated.json; None if not recorded."""
        text = self.generated_stamp(doc)
        if text is None:
            return None
        try:
            t = datetime.fromisoformat(text)
        except ValueError:
            return None
        return t.timestamp() if t.tzinfo is not None else None

    def presets(self, doc):
        """{ObjectName: {preset, source, document}} the generator copied doc's objects from, from generated.json
        ({} if none): preset the template key (e.g. 'S-Title'), source the ObjectName of the exported object copied,
        document the export it came from; source and document None when not recorded (an old record is the key)."""
        return {k: dict(v) for k, v in self.generation.get(doc.path, {}).get('presets', {}).items()}

    @property
    def planned_items(self):
        """planned.json entries that are objects with a kind and a name (strings)."""
        return [p for p in self.planned
                if isinstance(p, dict) and isinstance(p.get('kind'), str) and isinstance(p.get('name'), str)
                and p['name']]

    @property
    def effective(self):
        """Exports replaced by the generated document of the same kind and name, plus new generated ones."""
        gen = {(d.kind, d.name) for d in self.generated}
        return [d for d in self.exports if (d.kind, d.name) not in gen] + list(self.generated)

    def export_of(self, doc):
        """The TIA export a generated document replaces, or None."""
        for d in self.exports:
            if d.kind == doc.kind and d.name == doc.name:
                return d
        return None

    def find(self, kind, name, origin=None):
        """Effective document of kind and name (or of that origin), or None."""
        docs = self.effective if origin is None else (self.exports if origin == EXPORT else self.generated)
        for d in docs:
            if d.kind == kind and d.name == name:
                return d
        return None


def attribute(elem, name, default=None):
    al = elem.find('AttributeList')
    if al is None:
        return default
    c = al.find(name)
    return default if c is None else (c.text or '')


def objects(elem):
    """Every object element (has an ID attribute) at or below elem, in document order."""
    return [e for e in elem.iter() if 'ID' in e.attrib]


def object_name(elem, parents):
    """ObjectName of the screen item holding elem (itself or the nearest ancestor), or None."""
    e = elem
    while e is not None:
        n = attribute(e, 'ObjectName')
        if n:
            return n
        e = parents.get(e)
    return None


def parent_map(tree):
    return {c: p for p in tree.iter() for c in p}


def _rel(repo_path, full):
    return os.path.relpath(full, repo_path).replace(os.sep, '/')


def _xml_files(repo_path, top_rel, overlay):
    """Repo-relative paths of the .xml files under the folder top_rel, on disk and in the overlay, sorted."""
    rels = set()
    for dirpath, _dirnames, filenames in os.walk(os.path.join(repo_path, *top_rel.split('/'))):
        rels.update(_rel(repo_path, os.path.join(dirpath, fn)) for fn in filenames)
    rels.update(r for r in overlay if r.startswith(top_rel + '/'))
    return sorted(r for r in rels if r.lower().endswith('.xml'))


def _parse_xml(repo_path, rel, overlay):
    """The root element of a repo file, from the overlay when it holds it. Raises ET.ParseError."""
    if rel in overlay:
        return ET.fromstring(overlay[rel])
    return ET.parse(os.path.join(repo_path, *rel.split('/'))).getroot()


def _tag_types(tables):
    """{HMI tag name: HMI data type} of tables, a later table's over an earlier one's. A tag that names no type is
    left out: its type is unknown."""
    types = {}
    for d in tables:
        for tag in d.tree.iter('Hmi.Tag.Tag'):
            name = attribute(tag, 'Name')
            dtype = tag.findtext('LinkList/HmiDataType/Name')
            if name and dtype:
                types[name] = dtype
    return types


def _load_docs(repo_path, base, origin, findings, overlay, kinds=KINDS):
    """Documents of kinds under base/<kind dir>, from disk and from the overlay (an overlay entry wins over the file).
    One that cannot be read is a document.parse finding in findings, and left out."""
    docs = []
    for kind in kinds:
        top_rel = base + '/' + KIND_DIRS[kind]
        for rel in _xml_files(repo_path, top_rel, overlay):
            folder, _, fn = rel[len(top_rel) + 1:].rpartition('/')
            try:
                tree = _parse_xml(repo_path, rel, overlay)
            except ET.ParseError as ex:
                findings.append(error(rel, None, 'document.parse', 'Not readable as XML: %s' % ex))
                continue
            obj = next((c for c in tree if 'ID' in c.attrib), None)
            name = (attribute(obj, 'Name') if obj is not None else None) or os.path.splitext(fn)[0]
            docs.append(Document(kind, origin, rel, folder, name, tree, obj))
    return docs


def _load_json(repo_path, rel, default, findings, overlay):
    """The JSON file rel (overlay first), checked to be of the type of default; default when missing or wrong."""
    try:
        if rel in overlay:
            data = json.loads(overlay[rel].decode('utf-8-sig'))
        else:
            full = os.path.join(repo_path, *rel.split('/'))
            if not os.path.exists(full):
                return default
            with open(full, encoding='utf-8-sig') as f:
                data = json.load(f)
    except (OSError, ValueError) as ex:
        findings.append(error(rel, None, 'repo.json', 'Not readable as JSON: %s' % ex))
        return default
    if not isinstance(data, type(default)):
        findings.append(error(rel, None, 'repo.json', 'Expected a JSON %s, found %s.'
                              % ('object' if isinstance(default, dict) else 'array', type(data).__name__)))
        return default
    return data


def _generation(raw):
    """generated.json records as {path: {'generated': str or None, 'presets': {ObjectName: {preset, source,
    document}}}}."""
    out = {}
    for path, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        stamp = rec.get('generated')
        presets = rec.get('presets')
        out[path] = {'generated': stamp if isinstance(stamp, str) else None,
                     'presets': {k: p for k, p in ((k, _preset(v)) for k, v in presets.items()) if p}
                     if isinstance(presets, dict) else {}}
    return out


def _preset(value):
    """One recorded preset as {preset, source, document}, None when unusable. An old record is a plain string: the
    key only. source: ObjectName of the exported object the generator copied; document: the export it came from
    (repo-relative), when the generator knew it."""
    def text(v):
        return v.strip() if isinstance(v, str) and v.strip() else None
    if isinstance(value, str):
        value = {'preset': value}
    if not isinstance(value, dict) or text(value.get('preset')) is None:
        return None
    return {'preset': text(value['preset']), 'source': text(value.get('source')),
            'document': text(value.get('document'))}


def _load_faceplate_types(repo_path, findings):
    """The faceplate type index files under library/faceplates as [{name, folder, versions}], or None when the
    folder holds none (the faceplate types were not exported)."""
    top = os.path.join(repo_path, *FACEPLATE_DIR.split('/'))
    rels = []
    for dirpath, _dirnames, filenames in os.walk(top):
        rels += [_rel(repo_path, os.path.join(dirpath, fn)) for fn in filenames if fn.lower().endswith('.type.json')]
    if not rels:
        return None
    out = []
    for rel in sorted(rels):
        rec = _load_json(repo_path, rel, {}, findings, {})
        name, folder, versions = rec.get('name'), rec.get('folder', ''), rec.get('versions')
        if not (isinstance(name, str) and name and isinstance(folder, str) and isinstance(versions, list)):
            if rec:
                findings.append(error(rel, None, 'repo.json', 'Expected {name, folder, versions: [...]}, found %r.'
                                      % (rec,)))
            continue
        out.append({'name': name, 'folder': folder.strip('/'),
                    'versions': [str(v) for v in versions if isinstance(v, (str, int, float))]})
    return out


def _load_references(repo_path, findings, overlay, kinds=KINDS):
    """Documents of kinds under hmi/references/<source>/<kind dir>, one folder per source project."""
    return [d for s in _reference_sources(repo_path)
            for d in _load_docs(repo_path, REFERENCE_DIR + '/' + s, REFERENCE, findings, overlay, kinds)]


def _load_other_devices(repo_path, folders, folder, kinds=KINDS):
    """The exports of kinds of the device folders other than folder, from disk only. One that cannot be read is
    left out without a finding: it is not this device's."""
    return [d for f in folders if f != folder for d in _load_docs(repo_path, hmi_base(f), EXPORT, [], {}, kinds)]


def _reference_sources(repo_path):
    """The source folders under hmi/references, sorted."""
    top = os.path.join(repo_path, *REFERENCE_DIR.split('/'))
    return sorted(n for n in os.listdir(top) if os.path.isdir(os.path.join(top, n))) if os.path.isdir(top) else []


def load(repo_path, overlay=None, device=None):
    """The repo at repo_path, for one HMI device (select_device: device, else hmiDevice, else the only device
    folder). overlay: {repo-relative path: bytes} of files read as if they were on disk with that content (hmixml
    validates a run's documents, planned.json and generated.json before writing them); git history and every other
    file still come from the repo. When no device can be chosen, nothing of a device is read and device_problem
    says why (the rule resolution.ambiguous-device reports it)."""
    repo_path = os.path.abspath(repo_path)
    overlay = {k.replace(os.sep, '/'): v for k, v in (overlay or {}).items()}
    findings = []
    config = _load_json(repo_path, 'tiabridge.json', {}, findings, overlay)
    folders = device_folders(repo_path)
    folder, device_problem = select_device(repo_path, config, device)
    faceplate_types = _load_faceplate_types(repo_path, findings)
    references = _load_references(repo_path, findings, overlay)
    graphics = [g for g in _load_json(repo_path, 'hmi/graphics.json', [], findings, overlay) if isinstance(g, str)]
    if folder is None:
        return Repo(repo_path, config, [], [], [], [], None, findings, {}, None, device_problem, faceplate_types,
                    None, None, references, graphics, None, folders)
    base = hmi_base(folder)
    exports = _load_docs(repo_path, base, EXPORT, findings, overlay)
    generated = _load_docs(repo_path, base + '/generated', GENERATED, findings, overlay)
    planned = _load_json(repo_path, base + '/generated/planned.json', [], findings, overlay)
    handbuilt = [h for h in _load_json(repo_path, base + '/handbuilt.json', [], findings, overlay)
                 if isinstance(h, dict)]
    generation = _generation(_load_json(repo_path, base + '/generated/generated.json', {}, findings, overlay))
    others = _load_other_devices(repo_path, folders, folder)
    # a tag table export that cannot be read is left out without a finding; a generated one would be imported
    tag_tables = (_load_docs(repo_path, base, EXPORT, [], overlay, (TAG_TABLE,))
                  + _load_docs(repo_path, base + '/generated', GENERATED, findings, overlay, (TAG_TABLE,)))
    other_tag_tables = (_load_other_devices(repo_path, folders, folder, (TAG_TABLE,))
                        + _load_references(repo_path, [], overlay, (TAG_TABLE,)))
    # TiaBridge imports a cycle from here: one that cannot be read is a finding
    cycles = _load_docs(repo_path, base, EXPORT, findings, overlay, (CYCLE,))
    tid, problem = _resolution.select_type_identifier(config, folder or device, folder_name)
    device_problem = device_problem or problem
    hardware = _resolution.resolve(tid)
    panel = None
    panel_rel = base + '/panel.json'
    if panel_rel in overlay or os.path.exists(os.path.join(repo_path, *panel_rel.split('/'))):
        before = len(findings)
        raw_panel = _load_json(repo_path, panel_rel, {}, findings, overlay)
        if len(findings) == before:              # readable JSON object: check its content
            panel, problem = _resolution.panel_resolution(raw_panel)
            if problem:
                findings.append(error(panel_rel, None, 'repo.json', problem))
    return Repo(repo_path, config, exports, generated, planned, handbuilt, panel or hardware, findings, generation,
                tid, device_problem, faceplate_types, panel, hardware, references, graphics, folder, folders, others,
                tag_types=_tag_types(tag_tables), tag_tables=tag_tables, other_tag_tables=other_tag_tables,
                cycles=cycles)
