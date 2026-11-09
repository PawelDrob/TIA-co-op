"""The screen object catalogue (TiaHmiGenerator/catalogue/catalogue.json, built by catalogue/build.py; schema and
meaning in docs/agent/wincc-screen-objects.md section 3): every WinCC Comfort toolbox object with its attributes,
TIA display names and groups, defaults, allowed values and the preview's coverage.

    from hmipreview import catalogue
    t = catalogue.by_element('Hmi.Screen.Slider')        # the type, or None
    a = catalogue.attribute('Hmi.Screen.Slider', 'BarOrientation')
    a['values']['confirmed']                               # spellings seen in exports
"""
import json
import os
import xml.etree.ElementTree as ET
from functools import lru_cache

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'catalogue')
PATH = os.path.join(DIR, 'catalogue.json')
FIXTURE = os.path.join(DIR, 'fixture')


@lru_cache(maxsize=1)
def load(path=PATH):
    """The catalogue as a dict (schema, tia, style, sources, types, parts)."""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def types():
    """All types: the toolbox objects in toolbox order, then the screen-level objects (screen, template, ...)."""
    return load()['types']


def toolbox():
    """The 34 toolbox objects."""
    return [t for t in types() if t.get('toolbox')]


@lru_cache(maxsize=None)
def _by_element():
    return {t['element']: t for t in types() if t.get('element')}


def by_element(element):
    """The type of an export element ('Hmi.Screen.Button'), or None."""
    return _by_element().get(element)


def attribute(element, name):
    """One attribute of a type by export name ('BackColor', '@Font', 'link:Picture', 'tag:ProcessValue'), or None.
    For an element below the screen objects (fonts, animations ...) the entry of 'parts'."""
    t = by_element(element)
    if t is None:
        p = load()['parts'].get(element)
        return p['attributes'].get(name) if p else None
    for a in t['attributes']:
        if a.get('name') == name:
            return a
    return None


@lru_cache(maxsize=None)
def _parts():
    return load()['parts']


def attribute_names(element):
    """Export attribute names (AttributeList children) the catalogue knows for an element: a type's attributes
    (without compositions, links and tags) or a part's; None when the catalogue does not know the element, or knows
    it only from TIA's help (a control that does not go through Openness)."""
    t = by_element(element)
    if t is not None:
        if not t.get('openness'):
            return None
        return {a['name'] for a in t['attributes']
                if a.get('name') and not a['name'].startswith(('@', 'link:', 'tag:'))}
    p = _parts().get(element)
    return set(p['attributes']) if p else None


@lru_cache(maxsize=1)
def dependent():
    """The dependent-property table (catalogue/dependent.json; its 'about' has the meaning): pairs, relations and
    deviceRefuses. Read by rules/dependent.py and catalogue/roundtrip.py."""
    with open(os.path.join(DIR, 'dependent.json'), encoding='utf-8') as f:
        return json.load(f)


def enum_members(name):
    """Members of one of TIA's enum types (catalogue 'enums', from TIA's HMI library) by name, or None."""
    return load().get('enums', {}).get(name)


@lru_cache(maxsize=1)
def fixture_objects():
    """Element type -> the first object of that type in the fixture (full exports of the test screens with every
    toolbox object dropped unchanged), as parsed elements. Copy them, never change them."""
    out = {}
    for f in sorted(os.listdir(FIXTURE)):
        if f.endswith('.xml'):
            for e in ET.parse(os.path.join(FIXTURE, f)).getroot().iter():
                if 'ID' in e.attrib and e.find('AttributeList') is not None:
                    out.setdefault(e.tag, e)
    return out
