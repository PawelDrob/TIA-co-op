"""GET /api/findingspage: the findings list below the preview's screen over every HMI device of the repo,
as findingspage.page answers it: the open planned items, then the findings by document and rule, in sentences."""
from . import model
from .findingspage import page
from .links import open_planned
from .server import json_response, route


def findings_page(server):
    parts = []
    for device in model.device_folders(server.repo_path) or ['']:
        repo, findings = server.cache_for(device or None).findings()
        if repo.device is None:
            continue
        parts.append((device, repo, findings, open_planned(repo)))
    return page(parts)


@route('GET', '/api/findingspage')
def findings_list(req):
    return json_response(findings_page(req.server))
