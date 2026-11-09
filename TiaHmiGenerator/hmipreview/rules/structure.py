"""Structure rules. Generated documents only: an export is already in TIA.

  structure.grouped-faceplate   a faceplate instance inside a Hmi.Screen.Group (error: "It is not allowed to
                                import grouped Faceplate instances", wincc-comfort-openness.md 7.2)
  structure.duplicate-name      two objects with one ObjectName in one screen, template or pop-up (error)
  structure.duplicate-number    a generated screen whose Number another screen of the effective set holds (error,
                                reported on each generated screen involved). The effective set is the generated
                                screens plus the exports they do not replace, so a generated screen replacing its
                                own export is not a duplicate.
"""
from ..findings import error
from ..model import GENERATED, attribute, objects, parent_map

FACEPLATE = 'Hmi.Screen.FaceplateInstance'
GROUP = 'Hmi.Screen.Group'


def check(repo, ctx):
    yield from _grouped_faceplates(repo)
    yield from _duplicate_names(repo)
    yield from _duplicate_numbers(repo)


def _duplicate_numbers(repo):
    by_number = {}
    for d in repo.effective:                      # a replaced export no longer holds its number
        if d.kind == 'screen' and d.attr('Number'):
            by_number.setdefault(d.attr('Number').strip(), []).append(d)
    for number, docs in sorted(by_number.items()):
        if len(docs) < 2:
            continue
        for d in docs:
            if d.origin != GENERATED:
                continue
            others = ', '.join('%s (%s)' % (o.name, o.origin) for o in docs if o is not d)
            yield error(d.path, None, 'structure.duplicate-number',
                        'Screen %s has number %s, which screen %s also has; screen numbers must be unique in '
                        'the device.' % (d.name, number, others))


def _duplicate_names(repo):
    for d in repo.generated:
        if d.kind == 'textlist':
            continue
        count = {}
        for e in objects(d.tree):
            n = attribute(e, 'ObjectName')
            if n:
                count[n] = count.get(n, 0) + 1
        for n, c in sorted(count.items()):
            if c > 1:
                yield error(d.path, n, 'structure.duplicate-name',
                            '%d objects on %s %s are named %s; object names must be unique per screen.'
                            % (c, d.kind, d.name, n))


def _grouped_faceplates(repo):
    for d in repo.generated:
        parents = parent_map(d.tree)
        for e in d.tree.iter(FACEPLATE):
            p = parents.get(e)
            while p is not None and p.tag != GROUP:
                p = parents.get(p)
            if p is not None:
                yield error(d.path, attribute(e, 'ObjectName'), 'structure.grouped-faceplate',
                            "Faceplate instance %s is inside group %s; TIA refuses to import grouped faceplate "
                            "instances. Place it as a single screen item."
                            % (attribute(e, 'ObjectName'), attribute(p, 'ObjectName')))
