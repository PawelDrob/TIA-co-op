"""GET /api/catalogue?element=<export element>: what the preview's property panel (static/props.js) needs of
one type of the screen object catalogue (catalogue.py): toolbox name, attributes with TIA's display names and groups
in TIA's order, defaults, greyed-row conditions and descriptions, and the events and animations the type takes.
404 for an element the catalogue does not know."""
from . import catalogue
from .server import HttpError, json_response, route

ATTRIBUTE_KEYS = ('name', 'display', 'displayKnown', 'group', 'kind', 'default', 'shown', 'description', 'greyedWhen')


def type_entry(element):
    """The panel's view of a catalogue type, or None."""
    t = catalogue.by_element(element)
    if t is None:
        return None
    return {
        'element': t['element'], 'key': t['key'], 'toolbox': t.get('toolbox'), 'openness': t.get('openness'),
        'attributes': [{k: a[k] for k in ATTRIBUTE_KEYS if k in a} for a in t['attributes']],
        'events': t.get('events') or [], 'animations': t.get('animations') or [],
    }


@route('GET', '/api/catalogue')
def catalogue_type(req):
    element = req.param('element')
    entry = type_entry(element)
    if entry is None:
        raise HttpError(404, 'not in the catalogue: ' + element)
    return json_response(entry)
