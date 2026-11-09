"""GET /api/typenames: {export element: toolbox name} of the screen object catalogue ('Hmi.Screen.IOField': 'I/O
field'), for the toolbox objects that go through Openness. The browser app names objects with it as TIA does."""
from . import catalogue
from .server import json_response, route


@route('GET', '/api/typenames')
def type_names(req):
    return json_response({t['element']: t['toolbox']['name'] for t in catalogue.toolbox() if t.get('element')})
