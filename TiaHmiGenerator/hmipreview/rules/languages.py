"""Language rules: a generated document's texts and fonts carry the languages of the project.

The project's languages are the cultures its exports carry (project_cultures): TIA exports a text in every language
of the project, an empty one too (`<Text />`). The exported screens, templates, pop-ups and text lists of every HMI device
decide; only when those carry none, the other exports under hmi/ do (tag tables, ...: generators wrote tag tables by hand
into the folder exports go to before they went to generated/tags, and such a file may still be there, so one does not
add a language to the others). The generated documents and
hmi/references (another project's exports) never count. A language added in TIA is known once an exported screen,
template, pop-up or text list carries it; exporting a tag table again is not enough.

  languages.missing   error: a text or font of a generated document lacks a language the exports carry. The generator
                      writes every language (hmixml.generated_cultures); this catches a run that named its own
                      (shape_item cultures=), built a text by hand, or a document generated before a language came. TIA
                      imports such a document with no message, and that language then reads the word "Text" in Tahoma 16
                      Regular [PROBE].
  languages.unknown   error: a text or font of a generated document carries a language no export carries. TIA refuses
                      a language the project does not have, and nothing of the import goes in [PROBE]. A language added in
                      TIA and in no export yet is refused here too: export a screen again.
  languages.no-export warning: a generated document has texts or fonts, and no export of the project carries a language:
                      its languages came from the exports the run loaded, which may be another project's.
"""
import os
import xml.etree.ElementTree as ET

from ..findings import error, warning
from ..model import object_name, parent_map


def multilingual(root):
    """(element, its object list) of each element under root (itself too) whose list holds one item per culture."""
    for e in root.iter():
        items = e.find('ObjectList')
        if items is not None and len(items) and all(i.findtext('AttributeList/Culture') is not None for i in items):
            yield e, items


def document_cultures(root):
    """The cultures of the multilingual elements under root, each once, first seen first."""
    found = {}
    for _e, items in multilingual(root):
        for i in items:
            found.setdefault(i.findtext('AttributeList/Culture'))
    return list(found)


def _other_exports(repo, known):
    """The roots of the XML files under hmi/ that are no document of the model (tag tables, ...): not known, not
    generated, not hmi/references, in path order. A file not readable as XML says nothing."""
    skip = {'hmi/references'} | {'/'.join(['hmi'] + d + ['generated']) for d in [[]] + [[f] for f in repo.devices]}
    for dirpath, dirnames, filenames in os.walk(os.path.join(repo.path, 'hmi')):
        rel = os.path.relpath(dirpath, repo.path).replace(os.sep, '/')
        dirnames[:] = sorted(n for n in dirnames if rel + '/' + n not in skip)
        for name in sorted(filenames):
            if name.lower().endswith('.xml') and rel + '/' + name not in known:
                try:
                    yield ET.parse(os.path.join(dirpath, name)).getroot()
                except ET.ParseError:
                    pass


def _cultures_of(roots):
    found = {}
    for root in roots:
        for c in document_cultures(root):
            found.setdefault(c)
    return list(found)


def project_cultures(repo):
    """The languages of the project: the cultures of this device's documents, then of the other devices'; only when
    those carry none, of the other exports under hmi/."""
    docs = list(repo.exports) + list(repo.other_exports)
    return _cultures_of(d.tree for d in docs) or _cultures_of(_other_exports(repo, {d.path for d in docs}))


def check(repo, ctx):
    if not repo.generated:
        return
    project = project_cultures(repo)
    if not project:
        for d in repo.generated:
            written = document_cultures(d.tree)
            if written:
                yield warning(d.path, None, 'languages.no-export',
                              "Written in %s, but no export of the project carries a language, so nothing says these "
                              "are the project's. Export a screen of the HMI device and generate again."
                              % ', '.join(written))
        return
    for d in repo.generated:
        parents = parent_map(d.tree)
        for comp, items in multilingual(d.tree):
            name = object_name(comp, parents)
            part = comp.get('CompositionName') or comp.tag
            have = [i.findtext('AttributeList/Culture') for i in items]
            missing = [c for c in project if c not in have]
            unknown = [c for c in have if c not in project]
            if missing:
                yield error(d.path, name, 'languages.missing',
                            "%s has no item for %s; the project's exports carry %s. Generate it with every language "
                            "(no cultures= of your own)." % (part, ', '.join(missing), ', '.join(project)))
            if unknown:
                yield error(d.path, name, 'languages.unknown',
                            "%s has an item for %s, which no export carries (the project's exports carry %s). TIA refuses "
                            "a language the project does not have. If it was just added in TIA, export a screen again."
                            % (part, ', '.join(unknown), ', '.join(project)))
