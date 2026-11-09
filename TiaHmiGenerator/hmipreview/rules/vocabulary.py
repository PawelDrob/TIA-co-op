"""Vocabulary rules: every element type, attribute name and attribute value in a generated document must be in the
screen object catalogue or in a reference export: the project's own exports (those of every HMI device folder) and
those under hmi/references (the catalogue is the limit, the project's style guide decides what is used).

  vocabulary.element-type   error: element type neither in the catalogue (Openness types and their parts) nor in
                            an export
  vocabulary.attribute      error: attribute name the catalogue and the exports do not know on that element type
  vocabulary.value          voc.judge: error for a value outside the catalogue and the exports (or one the round
                            trip lost); warning for a documented value or enum member whose spelling is not
                            confirmed (voc.free exempt: FREE_VALUES, colours)
"""
from .. import vocabulary as voc
from ..findings import Finding, error
from ..model import object_name, objects, parent_map


def check(repo, ctx):
    if not repo.generated:
        return
    v = voc.build(repo.exports + repo.other_exports + repo.references)
    for d in repo.generated:
        parents = parent_map(d.tree)
        for e in objects(d.tree):
            obj = object_name(e, parents)
            if not voc.known_type(e.tag, v):
                yield error(d.path, obj, 'vocabulary.element-type',
                            'Element type %s is neither in the screen object catalogue nor in any reference export.'
                            % e.tag)
                continue
            for a in voc.attribute_elements(e):
                if not voc.known_attribute(e.tag, a.tag, v):
                    yield error(d.path, obj, 'vocabulary.attribute',
                                'Attribute %s is not an attribute of %s in the screen object catalogue or any '
                                'reference export.' % (a.tag, e.tag))
                elif not voc.free(a.tag) and len(a) == 0:
                    r = voc.judge(e.tag, a.tag, a.text or '', v)
                    if r:
                        yield Finding(r[0], d.path, obj, 'vocabulary.value', r[1])
