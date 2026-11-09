"""Geometry of screen items: bounding boxes in absolute screen pixels, shared by the rules, the renderer and the
preview server.

  items(doc)            -> [Item]  every drawable screen item of a screen / template / pop-up, groups expanded
  bounds(doc, res)      -> Box or None  the area objects of doc must stay in (screens and templates: the device
                           resolution; pop-ups: their own Width x Height; None when unknown)
  linked_template(doc)  -> name of the template the document links, or None

Coordinates (wincc-comfort-openness.md 4.2): Left / Top / Width / Height; Line: StartLeft / StartTop / EndLeft /
EndTop; Polyline / Polygon: Points with absolute screen coordinates (U+FEFF, then <Item>x, y</Item>...);
Circle: Left / Top and Width / Height, else Radius (bounding square). Group members carry absolute coordinates;
a Group itself has no geometry and is not an item.
Nothing is guessed: an attribute the document leaves out counts 0 (Left, Top) or 0 high / wide, and the document
rules report it (document.incomplete). Exports are full (2026-10-06), so they carry every one.
"""
import re
from dataclasses import dataclass

from .model import attribute

GROUP = 'Hmi.Screen.Group'

LINE_TYPES = ('Hmi.Screen.Line', 'Hmi.Screen.Polyline')


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def inside(self, other):
        """Entirely within other (edges may touch)."""
        return (self.x >= other.x and self.y >= other.y and self.right <= other.right
                and self.bottom <= other.bottom)

    def intersects(self, other):
        """Overlap with a positive area (touching edges and zero-width lines do not count)."""
        return (min(self.right, other.right) > max(self.x, other.x)
                and min(self.bottom, other.bottom) > max(self.y, other.y))


@dataclass(frozen=True)
class Item:
    name: str            # ObjectName
    type: str            # element tag, e.g. Hmi.Screen.Rectangle
    box: Box             # absolute bounding box
    group: str | None    # ObjectName of the outermost group holding it, or None
    elem: object         # the XML element


LINE = 'Hmi.Screen.Line'
LINE_ENDS = ('StartLeft', 'StartTop', 'EndLeft', 'EndTop')


def _num(elem, name):
    v = attribute(elem, name)
    if v is None or v == '':
        return None
    try:
        return float(v)
    except ValueError:
        return None


def points_of(value):
    """[(x, y)] of a Points value, in its order; [] when it holds none."""
    return [tuple(float(v) for v in m.split(','))
            for m in re.findall(r'<Item>\s*([-\d.]+\s*,\s*[-\d.]+)\s*</Item>', value or '')]


def line_ends(elem):
    """[(x, y) of the start, (x, y) of the end] of a screen item, a value left out counting 0 as in the drawing; None
    when one cannot be read."""
    try:
        sx, sy, ex, ey = (float(attribute(elem, k) or 0) for k in LINE_ENDS)
    except ValueError:
        return None
    return [(sx, sy), (ex, ey)]


def box_of(elem):
    """Bounding box of one screen item element, or None when it has no readable geometry: Points, then the ends (of a
    Line any end written, line_ends; of another object all four), then Left, Top, Width, Height, Radius."""
    pts = points_of(attribute(elem, 'Points'))
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if elem.tag == LINE:
        has_ends = any(attribute(elem, k) is not None for k in LINE_ENDS)
    else:
        has_ends = None not in (_num(elem, k) for k in LINE_ENDS)
    ends = line_ends(elem) if has_ends else None
    if ends:
        (sx, sy), (ex, ey) = ends
        return Box(min(sx, ex), min(sy, ey), abs(ex - sx), abs(ey - sy))
    x, y, w, h = (_num(elem, n) for n in ('Left', 'Top', 'Width', 'Height'))
    if (w is None or h is None) and _num(elem, 'Radius') is not None:
        w = h = 2 * _num(elem, 'Radius')
    if w is None and h is None:
        return None
    return Box(x or 0.0, y or 0.0, w or 0.0, h or 0.0)


def items(doc):
    """Drawable screen items of a document in document order, group members expanded."""
    out = []

    def walk(elem, group):
        for c in elem:
            if c.get('CompositionName') == 'ScreenItems':
                name = attribute(c, 'ObjectName') or ''
                if c.tag == GROUP:
                    walk(c.find('ObjectList') if c.find('ObjectList') is not None else c, group or name)
                    continue
                b = box_of(c)
                if b is not None:
                    out.append(Item(name, c.tag, b, group, c))
            elif c.get('CompositionName') in (None, 'Layers') or c.tag == 'ObjectList':
                walk(c, group)

    if doc.obj is not None:
        walk(doc.obj, None)
    return out


def bounds(doc, res):
    """The area the objects of doc must stay in, or None when unknown."""
    if doc.kind in ('screen', 'template'):
        return Box(0, 0, res.width, res.height) if res is not None else None
    if doc.kind == 'popup':
        w, h = _num(doc.obj, 'Width'), _num(doc.obj, 'Height')
        return Box(0, 0, w, h) if w is not None and h is not None else None
    return None


def linked_template(doc):
    if doc.obj is None:
        return None
    return doc.obj.findtext('LinkList/Template/Name') or None
