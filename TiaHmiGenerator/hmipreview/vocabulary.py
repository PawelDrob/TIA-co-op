"""Vocabulary: what a generated document may contain. The limit is the screen object catalogue (catalogue.json:
every toolbox type that goes through Openness, every attribute of it, every value it lists), widened by the
reference exports (the element types, attribute names per type and values per (type, attribute) an export shows are
what TIA wrote). And the attributes required per type: the names every object of that type carries in the full
exports (ExportSetting 'WithDefaults, WithReadOnly'); for a type no full export holds, those of the catalogue's
fixture. Minimal exports add to the names and values, never to required.

An object element is any element with an ID attribute; its attributes are the children of its own AttributeList.
"""
import re
from dataclasses import dataclass, field

from . import catalogue
from .findings import ERROR, WARNING
from .model import objects

NUMBER = re.compile(r'^-?\d+(\.\d+)?$')

# Attributes whose value is free (not compared with the exports): geometry, names, text and IDs,
# plus attributes that carry data rather than a look: screen numbers (checked for duplicates instead), point
# lists, line ends and the circle radius (geometry: Width / 2, WinCC guide 7.2), text list ranges, animation
# ranges, function parameter values, the faceplate type name (a link, checked by the link rules).
FREE_VALUES = frozenset({
    'Left', 'Top', 'Width', 'Height', 'Name', 'ObjectName', 'Text',
    'Number', 'Points', 'StartLeft', 'StartTop', 'EndLeft', 'EndTop', 'Radius',
    'From', 'To', 'LowerLimit', 'UpperLimit', 'RangeStart', 'RangeEnd', 'Value',
    'FaceplateTypeName',
})


def free(name):
    """True when the attribute's value is not compared with the exports: FREE_VALUES and every colour (an attribute
    named ...Color: BackColor, ForeColor, BorderColor, Color, gradient colours). A colour is data (the maintainer:
    "it's just a color"); the element type and the attribute name still have to be in an export."""
    return name in FREE_VALUES or name.endswith('Color')


@dataclass
class Vocabulary:
    types: set = field(default_factory=set)
    attributes: dict = field(default_factory=dict)    # type -> set of attribute names
    values: dict = field(default_factory=dict)        # (type, attribute) -> set of values
    required: dict = field(default_factory=dict)      # type -> attribute names every full-export object carries

    def add_full(self, elem):
        names = {a.tag for a in attribute_elements(elem)}
        self.required[elem.tag] = self.required[elem.tag] & names if elem.tag in self.required else names

    def add(self, elem):
        t = elem.tag
        self.types.add(t)
        names = self.attributes.setdefault(t, set())
        for a in attribute_elements(elem):
            names.add(a.tag)
            if not free(a.tag) and len(a) == 0:
                self.values.setdefault((t, a.tag), set()).add(a.text or '')


# Document types the screen object catalogue leaves out (it holds what a screen holds), with their attributes as an export
# of a text list shows them: hmixml.textlist writes this shape. Without them a new project needed a reference export of a
# text list before its first generated one passed.
TEXT_LIST_TYPES = {
    'Hmi.TextGraphicList.TextList': frozenset({'Name', 'ListRange'}),
    'Hmi.TextGraphicList.TextListEntry': frozenset({'From', 'To'}),
}
TEXT_LIST_VALUES = {('Hmi.TextGraphicList.TextList', 'ListRange'): frozenset({'Binary'})}   # what exports show


def known_type(element, v):
    """True when the catalogue or a reference export knows the element type, or it is a text list's."""
    return element in v.types or element in TEXT_LIST_TYPES or catalogue.attribute_names(element) is not None


def known_attribute(element, name, v):
    return (name in v.attributes.get(element, ()) or name in (catalogue.attribute_names(element) or ())
            or name in TEXT_LIST_TYPES.get(element, ()))


def judge(element, name, value, v):
    """None when the value of a known attribute is fine, else (severity, message). Fine: a value a reference export
    shows; by the catalogue's kind any number (number), true or false (bool), any text, list, colour or font; for an
    enum a confirmed spelling (seen in an export, the fixture, or kept by the round trip). Warning: a value TIA's
    help documents, or a member of TIA's enum, that no export or round trip has confirmed (TIA may refuse it at
    import). Error: anything else, and a value the round trip lost."""
    seen = v.values.get((element, name), set()) | TEXT_LIST_VALUES.get((element, name), frozenset())
    if value in seen:
        return None
    a = catalogue.attribute(element, name)
    if a is None:
        return ERROR, "%s.%s = '%s' is not seen in any reference export (seen: %s)." % (
            element, name, value, _list(seen))
    kind = a.get('kind')
    if kind == 'number':
        return None if NUMBER.match(value.strip()) else (
            ERROR, "%s.%s = '%s' is not a number." % (element, name, value))
    if kind == 'bool':
        return None if value in ('true', 'false') else (
            ERROR, "%s.%s = '%s' is not true or false." % (element, name, value))
    if kind != 'enum':
        return None
    vals = a.get('values') or {}
    confirmed = set(vals.get('confirmed', [])) | seen
    if value in confirmed:
        return None
    lost = vals.get('lost', {})
    if value in lost:
        return ERROR, "%s.%s = '%s' is not kept by TIA: the spelling round trip exported %s instead." % (
            element, name, value, "'%s'" % lost[value] if lost[value] is not None else 'nothing')
    members = catalogue.enum_members(vals['enum']) if vals.get('enum') else None
    documented = [d.get('spelling') if members else d['name'] for d in vals.get('documented', [])]
    if value in documented:
        return WARNING, ("%s.%s = '%s' is documented in TIA's help, but no export or round trip has confirmed the "
                         "spelling; TIA may refuse it at import (confirmed: %s)."
                         % (element, name, value, _list(confirmed)))
    if members and value in members:
        return WARNING, ("%s.%s = '%s' is in TIA's enum %s, but neither documented for this object nor confirmed; "
                         "TIA may refuse it at import (confirmed: %s)."
                         % (element, name, value, vals['enum'], _list(confirmed)))
    known = sorted(confirmed) + [x for x in documented if x and x not in confirmed]
    return ERROR, ("%s.%s = '%s' is neither in the screen object catalogue nor in a reference export (known: %s)."
                   % (element, name, value, _list(known, ordered=True)))


def _list(values, limit=8, ordered=False):
    vals = list(values) if ordered else sorted(values)
    s = ', '.join("'%s'" % x for x in vals[:limit])
    return s + (', ...' if len(vals) > limit else '') if vals else 'none'


def add_fixture_required(v):
    """Adds the required attributes of the types no reference export holds, from the catalogue's fixture (a
    generator copies such a type from it: hmixml.blank). A type only minimal exports hold stays without. Returns v."""
    for tag, e in catalogue.fixture_objects().items():
        if tag not in v.types:
            v.required[tag] = {a.tag for a in attribute_elements(e)}
    return v


def attribute_elements(elem):
    al = elem.find('AttributeList')
    return list(al) if al is not None else []


def build(documents):
    v = Vocabulary()
    for d in documents:
        for e in objects(d.tree):
            v.add(e)
            if getattr(d, 'full', False):
                v.add_full(e)
    return v
