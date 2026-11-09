"""Geometry rules. Generated screens, templates and pop-ups only; exports are in TIA already. Skipped while the
device resolution is unknown (resolution.unknown-device blocks).

  geometry.outside            error: an object not entirely inside the screen (device resolution, portrait
                              swapped) or, for a pop-up, inside its own Width x Height.
  geometry.template-overlap   warning: a screen object overlapping (positive area) an object of the template the
                              screen links, read from the effective template (generated replaces export). A
                              template object covering the whole screen is a background and does not count.
                              No template link: the screen has the full resolution and nothing to overlap.
  geometry.overlap            warning: two objects of one document overlapping, reported on the later object in
                              document order (drawn on top), naming the earlier ones. What counts:
                              - a positive area in common; touching edges do not count;
                              - not when one lies entirely inside the other: that is layering (text on a
                                rectangle background, a button on a panel, a flashing copy over its original),
                                as long as the inner object is drawn above (geometry.hidden otherwise);
                              - not between members of the same group (a group is a composed symbol); a member
                                against an object outside its group does count;
                              - not for invisible buttons (link areas laid over other objects on purpose) nor
                                for lines and polylines, whose bounding box is not their drawn area.
  geometry.hidden             warning: an object drawn below (earlier in document order) an object that covers it
                              entirely, so it cannot be seen. A cover with BackFillStyle Transparent or with a
                              visibility animation (shown in one state only) does not hide; invisible buttons and
                              lines neither hide nor are checked; group membership does not matter.
"""
from ..findings import error, warning
from ..geometry import LINE_TYPES, bounds, items, linked_template
from ..model import attribute


def check(repo, ctx):
    if repo.resolution is None:
        return
    for doc in repo.generated:
        area = bounds(doc, repo.resolution)
        if area is None:
            continue
        for it in items(doc):
            if not it.box.inside(area):
                b = it.box
                yield error(doc.path, it.name, 'geometry.outside',
                            '%s at %g,%g size %gx%g is outside the %s area %gx%g.'
                            % (it.type.split('.')[-1], b.x, b.y, b.w, b.h, doc.kind, area.w, area.h),
                            about=(b.x, b.y, b.w, b.h, doc.kind, area.w, area.h))
        yield from _overlap(doc)
        if doc.kind == 'screen':
            yield from _template_overlap(repo, doc, area)


def _counts_for_overlap(it):
    if it.type in LINE_TYPES:       # the bounding box of a line is not its drawn area
        return False
    return not (it.type == 'Hmi.Screen.Button' and attribute(it.elem, 'Mode') == 'Invisible')


def _hides(cover):
    """A later object hides what it covers unless it is see-through or shown only by a visibility animation."""
    if attribute(cover.elem, 'BackFillStyle') == 'Transparent':
        return False
    return cover.elem.find('.//Hmi.Dynamic.VisibilityAnimation') is None


def _overlap(doc):
    seen = []
    for it in items(doc):
        if not _counts_for_overlap(it):
            continue
        hit = [o.name for o in seen
               if it.box.intersects(o.box) and not it.box.inside(o.box) and not o.box.inside(it.box)
               and not (it.group and it.group == o.group)]
        if hit:
            yield warning(doc.path, it.name, 'geometry.overlap',
                          'Overlaps %s.' % ', '.join("'%s'" % n for n in hit), about=hit)
        seen.append(it)
    yield from _hidden([it for it in items(doc) if _counts_for_overlap(it)], doc)


def _hidden(drawn, doc):
    for i, it in enumerate(drawn):
        covers = [o.name for o in drawn[i + 1:]
                  if it.box.w > 0 and it.box.h > 0 and it.box.inside(o.box) and _hides(o)]
        if covers:
            yield warning(doc.path, it.name, 'geometry.hidden',
                          'Drawn under %s, which covers it entirely; move it after them in the document or '
                          'out from under them.' % ', '.join("'%s'" % n for n in covers), about=covers)


def _template_overlap(repo, doc, area):
    name = linked_template(doc)
    tpl = repo.find('template', name) if name else None
    if tpl is None:                 # no template: full resolution; a missing one is a link finding
        return
    under = [t for t in items(tpl) if not area.inside(t.box)]     # a full-screen background does not count
    for it in items(doc):
        hit = [t.name for t in under if it.box.intersects(t.box)]
        if hit:
            yield warning(doc.path, it.name, 'geometry.template-overlap',
                          'Overlaps %s of template %s.' % (', '.join(hit), tpl.name), about=[tpl.name] + hit)
