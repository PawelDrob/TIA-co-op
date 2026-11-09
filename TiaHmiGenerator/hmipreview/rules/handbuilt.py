"""Hand-built object rules (guide wincc-comfort-openness.md 7.1 and 7.2). The list is
hmi/[<device>/]handbuilt.json: [{screen, kind, x, y, w, h}], `screen` naming a screen, template or pop-up in TIA.

  handbuilt.override   error: a generated screen, template or pop-up with the name of a document that holds
                       hand-built objects. The import would Override it and the export cannot carry those
                       objects, so TIA would silently delete them (alarm view, diagnostics view, ...).
  handbuilt.overlap    error: an object of a generated document over (positive area) a hand-built rectangle of
                       the same document or of the template the document links. The hand-built control is drawn
                       on top and the object disappears under it.
"""
from ..findings import error
from ..geometry import Box, items, linked_template


def _box(entry):
    try:
        return Box(float(entry['x']), float(entry['y']), float(entry['w']), float(entry['h']))
    except (KeyError, TypeError, ValueError):
        return None


def check(repo, ctx):
    entries = repo.handbuilt
    if not entries:
        return
    for doc in repo.generated:
        if doc.kind not in ('screen', 'template', 'popup'):
            continue
        own = [e for e in entries if e.get('screen') == doc.name]
        if own:
            yield error(doc.path, None, 'handbuilt.override',
                        "%s %s holds hand-built objects (%s); importing it would Override and delete them. "
                        "Generate a new %s or rebuild those objects by hand."
                        % (doc.kind.capitalize(), doc.name, ', '.join(sorted({str(e.get('kind')) for e in own})),
                           doc.kind))
        tpl = linked_template(doc)
        rects = [(e, _box(e)) for e in entries
                 if e.get('screen') == doc.name or (tpl and e.get('screen') == tpl)]
        rects = [(e, b) for e, b in rects if b is not None]
        for it in items(doc):
            hit = [e for e, b in rects if it.box.intersects(b)]
            if hit:
                yield error(doc.path, it.name, 'handbuilt.overlap',
                            'Placed over the hand-built %s of %s; it would be hidden under it.'
                            % (', '.join(str(e.get('kind')) for e in hit), hit[0].get('screen')))
