"""The findings list of the preview, below the screen: the validator's findings and the open planned
items of every HMI device, in sentences, grouped by document, then by rule, repeats folded.

    page(parts) -> {planned: [...], sections: [...]}     parts: [(device, repo, findings, planned)]

Order (the maintainer, 2026-11-05): the open planned items first, then the documents with errors, then those with warnings
only, the project's own findings (tiabridge.json, panel.json, planned.json ...: not an HMI document) last; inside a
document the rules with errors first, else in the validator's order; findings in the validator's order.

A sentence names the object's type (the catalogue's toolbox name) and ObjectName first: "Text field txtRack03
overlaps rectangle recRackSouth." Rules that say what else they are about (Finding.about) are written out with the
other objects' types; any other finding is "<Type> <name>: <message>", or its message without an object.

Folding: findings of objects of one document and rule about the same other things (Finding.about), or else with the
same message, two or more, fold into one line ("12 text fields overlap rectangle recRackSouth"; "15 objects: Font has
no item for es-ES ...").

planned: [{device, kind, name, note, usedBy: [{device, kind, name, object}]}]    (kind, name: of the document)
sections: [{device, kind, name, path, opens, files, errors, warnings, rules: [{rule, title, severity, rows}]}]
    kind and name of the HMI document; kind 'project' and name '' for the project's own findings
    opens: the preview draws this document for its kind and name (not an export a generated document replaces)
    files: the files the project's own findings are of; [] for a document
    rows: [{fold: null | text, key: null | str, severity, items: [{object, select, severity, text, rule, message}]}]
    key of a fold: its rule and what it is about, the same while its count changes
    select: the preview can select the object on the drawn document (not a group, not on a text list)
"""
import json
import re

from . import catalogue, model
from .findings import ERROR, WARNING
from .rules.structure import GROUP

# A heading per rule; a rule not named here is headed by its id.
TITLES = {
    'cycle.not-cycle': 'Not a cycle',
    'cycle.not-full': 'Cycle not exported full',
    'dependent.device': 'Value not taken on Comfort panels',
    'dependent.value': 'Dependent property',
    'document.incomplete': 'Attributes missing',
    'document.not-full': 'Not a full export',
    'document.parse': 'Not readable',
    'geometry.hidden': 'Hidden under another object',
    'geometry.outside': 'Outside the screen',
    'geometry.overlap': 'Objects overlap',
    'geometry.template-overlap': 'Over the template',
    'handbuilt.overlap': 'Over a hand-built object',
    'handbuilt.override': 'Hand-built objects would be lost',
    'iofield.format-pattern': 'Format pattern',
    'languages.missing': 'Language missing',
    'languages.no-export': 'Languages not known',
    'languages.unknown': 'Language not in the project',
    'links.planned': 'Links to planned items',
    'links.planned-entry': 'Planned item incomplete',
    'links.unknown': 'Link to nothing',
    'repo.json': 'Data file',
    'resolution.ambiguous-device': 'HMI device not chosen',
    'resolution.mismatch': 'Panel differs from TIA',
    'resolution.screen-size': 'Screen size',
    'resolution.unknown-device': 'HMI device unknown',
    'staleness.export-newer': 'Export newer than the generated document',
    'structure.duplicate-name': 'Object name used twice',
    'structure.duplicate-number': 'Screen number used twice',
    'structure.grouped-faceplate': 'Faceplate instance in a group',
    'tagtable.data-type': 'Data type the validator cannot check',
    'tagtable.hmi-data-type': 'HMI data type does not fit the data type',
    'tagtable.length': 'Length does not fit the data type',
    'text.fit': 'Text does not fit',
    'vocabulary.attribute': 'Attribute not known',
    'vocabulary.element-type': 'Object type not known',
    'vocabulary.value': 'Value not known',
}
LINK_TEXT = {'textlist': 'text list', 'popup': 'pop-up screen'}     # links.KINDS; the others as they are
PROJECT = 'project'


def type_name(tag):
    """The type of an object as TIA's toolbox names it ('Text field'); else from the element ('Faceplate
    instance'); 'Object' when not known."""
    if not tag:
        return 'Object'
    t = catalogue.by_element(tag)
    if t:
        name = (t.get('toolbox') or {}).get('name') or t.get('stem')
        if name:
            return name
    words = re.findall(r'[A-Z][a-z]*|[a-z]+|\d+', tag.split('.')[-1])
    return ' '.join([words[0]] + [w.lower() for w in words[1:]]) if words else tag


def lower(name):
    """A type name inside a sentence: 'rectangle', but 'I/O field' and 'HTML browser' kept."""
    return name if len(name) > 1 and (name[1].isupper() or not name[1].isalpha()) else name[:1].lower() + name[1:]


def plural(name):
    return name + ('es' if name.endswith(('s', 'x', 'ch', 'sh')) else 's')


def object_types(doc):
    """{ObjectName: element tag} of a document; None for no document (the project's own findings)."""
    if doc is None:
        return None
    return {model.attribute(e, 'ObjectName'): e.tag for e in model.objects(doc.tree) if model.attribute(e, 'ObjectName')}


def link_kind(kind):
    """A link target's kind inside a sentence: 'text list', 'screen'."""
    return LINK_TEXT.get(kind, lower(kind))


def _named(types, names):
    return ', '.join('%s %s' % (lower(type_name(types.get(n))), n) for n in names)


def sentence(f, types, template_types):
    """The finding as a sentence; types: {ObjectName: tag} of its document, template_types those of the template
    a geometry.template-overlap finding names. A finding of the project's own files (no types) starts with the
    file."""
    if f.object is None:
        return f.message if types is not None or not f.document else '%s: %s' % (f.document, f.message)
    types = types or {}
    subject = '%s %s' % (type_name(types.get(f.object)), f.object)
    about = list(f.about)
    if f.rule == 'geometry.overlap' and about:
        return '%s overlaps %s.' % (subject, _named(types, about))
    if f.rule == 'geometry.hidden' and about:
        return '%s is hidden under %s, which cover%s it entirely.' % (
            subject, _named(types, about), 's' if len(about) == 1 else '')
    if f.rule == 'geometry.template-overlap' and len(about) > 1:
        return '%s overlaps %s of template %s.' % (subject, _named(template_types, about[1:]), about[0])
    if f.rule == 'geometry.outside' and len(about) == 7:
        return '%s at %g,%g size %gx%g is outside the %s area %gx%g.' % (subject, *about)
    if f.rule == 'links.planned' and len(about) == 3:
        return '%s links %s %s, a planned item not in TIA yet%s.' % (
            subject, link_kind(about[0]), about[1], ' (%s)' % about[2] if about[2] else '')
    return '%s: %s' % (subject, f.message)


def fold_text(rule, items, types, template_types, about):
    """The line of a fold of items: two or more findings of one rule about the same things, or with one message."""
    types = types or {}
    tags = {types.get(f.object) for f in items}
    many = plural(lower(type_name(tags.pop()))) if len(tags) == 1 else 'objects'
    n = len(items)
    if rule == 'geometry.overlap':
        return '%d %s overlap %s' % (n, many, _named(types, about))
    if rule == 'geometry.hidden':
        return '%d %s are hidden under %s' % (n, many, _named(types, about))
    if rule == 'geometry.template-overlap':
        return '%d %s overlap %s of template %s' % (n, many, _named(template_types, about[1:]), about[0])
    if rule == 'links.planned':
        return '%d %s link the planned %s %s' % (n, many, link_kind(about[0]), about[1])
    if rule == 'links.unknown':
        return '%d %s link %s %s, which is neither exported nor planned' % (
            n, many, link_kind(about[0]), about[1])
    return '%d %s: %s' % (n, many, items[0].message)


def _worst(severities):
    return ERROR if ERROR in severities else WARNING


def rows(rule, found, types, template_types, kind=None):
    """The rows of one rule of a document: a fold per group of two or more findings of objects about the same
    things (else with the same message), at the place of its first finding; the others one row each. types:
    {ObjectName: tag} of the document; template_types(name) those of a template; kind: the document's."""
    def key(f):
        return None if f.object is None else ('about', f.about) if f.about else ('message', f.message)

    groups = {}
    for f in found:
        if key(f):
            groups.setdefault(key(f), []).append(f)
    out, done = [], set()
    for f in found:
        group = groups.get(key(f), []) if key(f) else []
        tt = template_types(f.about[0]) if rule == 'geometry.template-overlap' and f.about else {}
        if len(group) > 1:
            if key(f) in done:
                continue
            done.add(key(f))
            out.append({'fold': fold_text(rule, group, types, tt, f.about),
                         'key': json.dumps([rule, *key(f)]),
                         'severity': _worst({g.severity for g in group}),
                         'items': [_item(g, types, tt, kind) for g in group]})
        else:
            out.append({'fold': None, 'key': None, 'severity': f.severity, 'items': [_item(f, types, tt, kind)]})
    return out


def _item(f, types, template_types, kind):
    select = kind not in (None, 'textlist') and (types or {}).get(f.object) not in (None, GROUP)
    return {'object': f.object, 'select': select, 'severity': f.severity,
            'text': sentence(f, types, template_types), 'rule': f.rule, 'message': f.message}


def _section(device, repo, doc, path, found):
    types = object_types(doc)
    templates = {}

    def template_types(name):
        if name not in templates:
            templates[name] = object_types(repo.find('template', name)) or {}
        return templates[name]

    by_rule = {}
    for f in found:
        by_rule.setdefault(f.rule, []).append(f)
    rules = [{'rule': rule, 'title': TITLES.get(rule, rule), 'severity': _worst({f.severity for f in fs}),
              'rows': rows(rule, fs, types, template_types, doc.kind if doc else None)} for rule, fs in by_rule.items()]
    rules.sort(key=lambda r: r['severity'] != ERROR)
    errors = sum(f.severity == ERROR for f in found)
    return {'device': device, 'kind': doc.kind if doc else PROJECT, 'name': doc.name if doc else '', 'path': path,
            'opens': doc is not None and repo.find(doc.kind, doc.name) is doc,
            'files': [] if doc else sorted({f.document for f in found if f.document}),
            'errors': errors, 'warnings': len(found) - errors, 'rules': rules}


def page(parts):
    """The answer of /api/findingspage; parts: [(device, repo, findings, planned)], planned as links.open_planned."""
    planned, docs, project = [], [], []
    for device, repo, findings, open_items in parts:
        by_path = {d.path: d for d in repo.exports + repo.generated + repo.tag_tables}
        for p in open_items:
            used = []
            for u in p['usedBy']:
                d = by_path.get(u['document'])
                used.append({'device': device, 'kind': d.kind if d else None, 'name': d.name if d else u['document'],
                             'object': u['object']})
            planned.append({'device': device, 'kind': p['kind'], 'name': p['name'], 'note': p['note'],
                            'usedBy': used})
        by_doc, own = {}, []
        for f in findings:
            if f.document in by_path:
                by_doc.setdefault(f.document, []).append(f)
            else:
                own.append(f)
        docs += [_section(device, repo, by_path[path], path, found) for path, found in by_doc.items()]
        if own:
            s = _section(device, repo, None, '', own)
            project.append(s)
    docs.sort(key=lambda s: s['errors'] == 0)
    return {'planned': planned, 'sections': docs + project}
