"""Link rules. Generated documents only; the resolution is in hmipreview/links.py.

  links.unknown        link target neither exists nor is planned: error
  links.planned        link to an open planned item: warning, error with for_import
  links.planned-entry  planned.json entry without a known kind or a name: error
"""
from .. import links as lk
from ..findings import error, warning


def check(repo, ctx):
    res = lk.resolver(repo)
    for i, p in enumerate(repo.planned):
        if not (isinstance(p, dict) and p.get('kind') in lk.KINDS and p.get('name')):
            yield error(repo.planned_file, None, 'links.planned-entry',
                        'Entry %d needs a kind (one of %s) and a name: %r.' % (i, ', '.join(lk.KINDS), p))
    for d in repo.generated:
        for obj, kind, name, source in lk.document_links(repo, d):
            state, note, is_open = res.state(kind, name, source)
            if state == lk.UNKNOWN:
                yield error(d.path, obj, 'links.unknown',
                            "%s '%s' is neither in the reference exports nor a planned item%s."
                            % (kind, name, ': %s' % note if note else ''), about=(kind, name, note or ''))
            elif is_open:
                make = error if ctx.for_import else warning
                yield make(d.path, obj, 'links.planned',
                           "%s '%s' is a planned item that does not exist in TIA yet%s."
                           % (kind, name, ' (%s)' % note if note else ''), about=(kind, name, note or ''))
