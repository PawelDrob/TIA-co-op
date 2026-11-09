"""Document rules: HMI documents are full (decided 2026-10-06). The preview draws and checks only what a document
carries and never fills in a TIA default, so an attribute a document leaves out is reported, not guessed.

  document.incomplete   error: an object of a generated document lacks attributes that every object of its type
                        carries in the full reference exports (vocabulary.required; for a type no full export
                        holds, the catalogue's fixture). Generated objects are copied from full exports; one
                        built by hand or copied from a minimal export misses defaults.
                        Exports themselves are not checked: what TIA wrote is what TIA has.
  document.not-full     warning: a screen, template or pop-up export whose DocumentInfo/ExportSetting is not
                        'WithDefaults, WithReadOnly' (a minimal export, or none recorded). It still feeds the
                        vocabulary, but not the required attributes; export it again (TiaBridge exports full).
"""
from .. import vocabulary as voc
from ..findings import error, warning
from ..model import objects, parent_map, object_name

FULL_KINDS = ('screen', 'template', 'popup')


def check(repo, ctx):
    for d in repo.exports:
        if d.kind in FULL_KINDS and not d.full:
            yield warning(d.path, None, 'document.not-full',
                          "ExportSetting is %s, not 'WithDefaults, WithReadOnly': not a full export. The preview "
                          "draws only what a document carries; export it again (TiaBridge exports %ss full)."
                          % ("'%s'" % d.export_setting if d.export_setting is not None else 'not recorded',
                             d.kind))
    if not repo.generated:
        return
    v = voc.add_fixture_required(voc.build(repo.exports + repo.other_exports + repo.references))
    for d in repo.generated:
        parents = parent_map(d.tree)
        for e in objects(d.tree):
            missing = sorted(v.required.get(e.tag, set()) - {a.tag for a in voc.attribute_elements(e)})
            if missing:
                yield error(d.path, object_name(e, parents), 'document.incomplete',
                            "Attribute%s %s missing on %s; every %s in the full exports (or the catalogue's "
                            "fixture) carries %s. Generated objects must be copied from full exports."
                            % ('s' if len(missing) > 1 else '', ', '.join(missing), e.tag, e.tag,
                               'them' if len(missing) > 1 else 'it'))
