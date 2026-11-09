"""GET /api/diff?name=<screen>[&kind=screen][&against=commit|export]: object-level diff of a generated document
against its last commit (default) or its TIA export. Answer: diff.compare (see 10-contract)."""
from . import diff
from .server import HttpError, json_response, route


@route('GET', '/api/diff')
def document_diff(req):
    kind = req.param('kind', required=False, default='screen')
    name = req.param('name')
    against = req.param('against', required=False, default='commit')
    try:
        return json_response(diff.compare(req.repo(), kind, name, against))
    except diff.DiffError as ex:
        raise HttpError(ex.status, ex.message)
