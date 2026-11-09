"""Link states: every link of a document resolves to exists / planned / unknown.

Link kinds and where they are read:
  textlist       <TextList> link (symbolic I/O field)
  template       <Template> link of a screen root
  picture        <Picture...> links (graphic view Picture, button PictureOn / PictureOff, ...)
  authorization  <Authorization> link, and the Value link of a faceplate interface property named Authorization
  screen         Value link of the 'Screen name' parameter of ActivateScreen
  popup          Value link of the 'Name of the screen' parameter of ShowPopupScreen
  faceplate      FaceplateTypeName attribute of a faceplate instance (type and version)
  style          a generated object whose ObjectName starts with 'S-' is a style preset; an ordinary object does not
                 carry the preset it was copied from, so for generated documents the presets hmixml recorded in
                 hmi/generated/generated.json (Repo.presets) are links of kind 'style' of those objects too. The
                 link name is the recorded key (the template key, 'S-Title'); the record may also name the source,
                 the exported object actually copied (its ObjectName, and the export document when known).
Tag, StyleItem and links to the own document (TargetID '#0') are not resolved. A link without a Name is left open.

exists:  screens, templates, pop-ups and text lists: a TIA export of that kind and name. Faceplate type versions:
         the exported project library (library/faceplates, TiaBridge export kind faceplate_type; model.py) lists
         the type with that version, in the library folder the FaceplateTypeName names (its segments between the
         first, '_Library', and the last). A version used on an exported screen does not count: the screen may be
         older than the library. Without library/faceplates every faceplate link is unknown, with a note to export
         the faceplate types first. Pictures, authorizations and style presets have no document of their own in
         the repo, so the known set is what the reference exports show: every Picture / Authorization link target
         and every 'S-' object seen in an export. A picture or authorization that is in the project but never
         linked from an exported screen therefore needs a planned item until an export shows it. A recorded style
         preset also exists when its source object is in a reference export (by ObjectName, only in the recorded
         document when there is one): a generator may key its templates by alias ('S-Title' -> txtTitleLarge).
planned: an entry in planned.json [{kind, name, note}] that does not exist; or, for screens, templates, pop-ups
         and text lists, a generated document of that kind and name (the run brings it into TIA).
unknown: anything else; always an error (rule links.unknown). For a faceplate the note says why; for a recorded
         style preset the note names the source (and its document).

Open planned item = a planned.json entry that does not exist and is not generated in the repo. A document that uses
one gets the finding links.planned: a warning in the preview, an error with for_import. A planned item that exists
now is closed and gives no finding. A generated target gives no finding (it is imported in the same run).
A faceplate name matches the full FaceplateTypeName or its last '@$@' segment ('faceplateX V 1.0.0').
"""
from dataclasses import asdict, dataclass

from .model import GENERATED, attribute, object_name, parent_map

EXISTS = 'exists'
PLANNED = 'planned'
UNKNOWN = 'unknown'

KINDS = ('style', 'textlist', 'template', 'picture', 'faceplate', 'screen', 'popup', 'authorization')
DOC_KINDS = ('screen', 'template', 'popup', 'textlist')
FP_SEP = '@$@'


@dataclass(frozen=True)
class Link:
    object: str | None       # ObjectName of the screen item holding the link, None for the document root
    kind: str                # one of KINDS
    name: str                # link target
    state: str               # exists | planned | unknown
    note: str = ''           # planned.json note, 'generated' for a generated target, why an unknown faceplate is
                             # unknown, '' otherwise

    def to_dict(self):
        return asdict(self)


def _faceplate_key(name):
    return name.rsplit(FP_SEP, 1)[-1].strip()


def parse_faceplate(name):
    """FaceplateTypeName '_Library@$@<folder>@$@...@$@<type> V <x.y.z>' -> (folder or None, type, version or None).
    folder is the '/'-joined segments between the first and the last; None when the name has no '@$@'."""
    parts = [p.strip() for p in name.split(FP_SEP)]
    last = parts[-1]
    typ, sep, version = last.rpartition(' V ')
    if not sep:
        typ, version = last, None
    folder = '/'.join(parts[1:-1]) if len(parts) > 1 else None
    return folder, typ.strip(), version.strip() if version else None


NO_LIBRARY = ('the faceplate types are not exported (no library/faceplates in the repo); export them first with '
              'TiaBridge export kind faceplate_type')


def faceplate_problem(types, name):
    """None when the faceplate type version of FaceplateTypeName name is in the exported library types
    ([{name, folder, versions}] or None), else why not."""
    if types is None:
        return NO_LIBRARY
    folder, typ, version = parse_faceplate(name)
    same = [t for t in types if t['name'] == typ]
    if not same:
        return "faceplate type '%s' is not in the exported project library (library/faceplates)" % typ
    with_version = [t for t in same if version in t['versions']]
    if not with_version:
        have = sorted({v for t in same for v in t['versions']})
        return "faceplate type '%s' has version(s) %s in the exported project library, not %s" % (
            typ, ', '.join(have) or 'none', version)
    if folder is not None and not any(_library_folder(t['folder']) == folder for t in with_version):
        return "faceplate type '%s' V %s is in library folder %s, the link names %s" % (
            typ, version, ', '.join(sorted(t['folder'] or '(root)' for t in with_version)), folder or '(root)')
    return None


def _library_folder(folder):
    """Library folder of a type index without the '_Library' root the bridge writes (project B 2026-10-06:
    '_Library/_Customer/Faceplate/Operate'), as parse_faceplate gives it ('_Customer/Faceplate/Operate')."""
    parts = (folder or '').split('/')
    return '/'.join(parts[1:] if parts[0] == '_Library' else parts)


def raw_links(doc):
    """(object, kind, name) for every link in the document, in document order."""
    parents = parent_map(doc.tree)
    out = []

    def add(elem, kind, name):
        if name:
            out.append((object_name(elem, parents), kind, name.strip()))

    for e in doc.tree.iter():
        if e.tag == 'LinkList':
            owner = parents.get(e)
            for l in e:
                if l.get('TargetID') != '@OpenLink':
                    continue
                name = l.findtext('Name')
                if l.tag == 'TextList':
                    add(owner, 'textlist', name)
                elif l.tag == 'Template':
                    add(owner, 'template', name)
                elif l.tag.startswith('Picture'):
                    add(owner, 'picture', name)
                elif l.tag == 'Authorization':
                    add(owner, 'authorization', name)
                elif l.tag == 'Value':
                    kind = _value_kind(owner, parents)
                    if kind:
                        add(owner, kind, name)
        elif e.tag == 'FaceplateTypeName' and parents.get(e) is not None and parents[e].tag == 'AttributeList':
            add(parents[parents[e]], 'faceplate', e.text)
        elif e.tag == 'ObjectName' and (e.text or '').startswith('S-'):
            add(parents[parents[e]], 'style', e.text)
    return out


def _value_kind(owner, parents):
    """Kind of a Value link from its owner: a function parameter or a faceplate interface property."""
    pname = attribute(owner, 'Name')
    if owner.tag == 'Hmi.Event.FunctionListEntryParameter':
        func = parents.get(parents.get(owner))
        fname = attribute(func, 'Name') if func is not None else None
        if fname == 'ActivateScreen' and pname == 'Screen name':
            return 'screen'
        if fname == 'ShowPopupScreen' and pname == 'Name of the screen':
            return 'popup'
        return None
    if owner.tag.startswith('Hmi.Screen.InterfaceProperty') and pname == 'Authorization':
        return 'authorization'
    return None


def document_links(repo, doc):
    """(object, kind, name, source) for raw_links of doc (source None) plus, for a generated document, one 'style'
    link per object with a recorded preset: name the key, source the record {preset, source, document}."""
    out = [(obj, kind, name, None) for obj, kind, name in raw_links(doc)]
    if doc.origin == GENERATED:
        out += [(obj, 'style', rec['preset'], rec) for obj, rec in sorted(repo.presets(doc).items())
                if not obj.startswith('S-')]
    return out


def _source_text(rec):
    """'copied from 'txtTitleLarge' in hmi/screens/x.xml' for a recorded preset with a source, else ''."""
    if not rec or not rec.get('source'):
        return ''
    return "copied from '%s'%s" % (rec['source'], ' in %s' % rec['document'] if rec.get('document') else '')


class Resolver:
    """Link states for one repo."""

    def __init__(self, repo):
        self.repo = repo
        self.known = {k: set() for k in KINDS}
        self.object_names = {}          # export path -> ObjectNames of its objects
        for d in repo.exports:
            self.known[d.kind].add(d.name)
            self.object_names[d.path] = {e.text.strip() for e in d.tree.iter('ObjectName') if e.text}
            for _obj, kind, name in raw_links(d):
                if kind in ('picture', 'authorization', 'style'):
                    self.known[kind].add(name)
        for d in repo.other_exports:    # another HMI device of the project: its objects as style sources and the
            self.object_names[d.path] = {e.text.strip() for e in d.tree.iter('ObjectName') if e.text}
            for _obj, kind, name in raw_links(d):   # project graphics it shows; its screens, templates, text
                if kind in ('picture', 'style'):    # lists and authorizations are its own
                    self.known[kind].add(name)
        for d in repo.references:       # another project's exports: its styles and authorizations, not its
            for _obj, kind, name in raw_links(d):   # pictures or screens (those must be in this project)
                if kind in ('authorization', 'style'):
                    self.known[kind].add(name)
        self.known['picture'].update(repo.graphics)     # hmi/graphics.json, as TIA lists the project's graphics
        self.generated = {(d.kind, d.name) for d in repo.generated}
        self.planned = {}
        for p in repo.planned_items:
            if p['kind'] in KINDS:
                self.planned[(p['kind'], self._key(p['kind'], p['name']))] = p.get('note') or ''

    @staticmethod
    def _key(kind, name):
        return _faceplate_key(name) if kind == 'faceplate' else name.strip()

    def exists(self, kind, name):
        if kind == 'faceplate':
            return faceplate_problem(self.repo.faceplate_types, name) is None
        return name in self.known[kind]

    def source_exists(self, rec):
        """The recorded source object of a style preset is in a reference export (its recorded document, if any)."""
        if not rec or not rec.get('source'):
            return False
        if rec.get('document'):
            return rec['source'] in self.object_names.get(rec['document'], ())
        return any(rec['source'] in names for names in self.object_names.values())

    def state(self, kind, name, source=None):
        """(state, note, is_open_planned). source: the recorded preset {preset, source, document} of a style link."""
        copied = _source_text(source)
        if self.exists(kind, name) or (kind == 'style' and self.source_exists(source)):
            return EXISTS, copied, False
        if kind in DOC_KINDS and (kind, name) in self.generated:
            return PLANNED, GENERATED, False
        key = (kind, self._key(kind, name))
        if key in self.planned:
            return PLANNED, self.planned[key], True
        if kind == 'faceplate':
            return UNKNOWN, faceplate_problem(self.repo.faceplate_types, name), False
        if copied:
            return UNKNOWN, '%s, which is not in %s either' % (
                copied, 'that export' if source.get('document') else 'any reference export'), False
        return UNKNOWN, '', False

    def links(self, doc):
        out = []
        for obj, kind, name, source in document_links(self.repo, doc):
            st, note, _ = self.state(kind, name, source)
            out.append(Link(obj, kind, name, st, note))
        return out


def open_planned(repo):
    """Open planned items: planned.json entries that neither exist nor are generated, one per kind and name, in
    planned.json order, as {kind, name, note, usedBy: [{document, object}]} with the generated documents using them."""
    res = resolver(repo)
    uses = {}
    for doc in repo.generated:
        for obj, kind, name, _source in document_links(repo, doc):
            uses.setdefault((kind, res._key(kind, name)), []).append({'document': doc.path, 'object': obj})
    out, seen = [], set()
    for p in repo.planned_items:
        kind, name = p['kind'], p['name']
        if kind not in KINDS:
            continue
        key = (kind, res._key(kind, name))
        if key in seen or not res.state(kind, name)[2]:
            continue
        seen.add(key)
        out.append({'kind': kind, 'name': name, 'note': p.get('note') or '', 'usedBy': uses.get(key, [])})
    return out


def link_states(repo, doc):
    """Every link of doc with its state, as Link records (object, kind, name, state, note), in document order.
    For the preview's inspect panel; repo is a model.Repo, doc one of its documents."""
    return resolver(repo).links(doc)


def resolver(repo):
    """The Resolver of repo, built once per loaded repo (the preview server keeps one repo while the disk is
    unchanged; building it walks every export)."""
    res = repo.__dict__.get('_resolver')
    if res is None:
        res = repo.__dict__['_resolver'] = Resolver(repo)
    return res
