"""Agent PNGs: a headless Edge (else Chrome) screenshot of the preview page, the same renderer the user sees in the browser.

shoot(repo_path, kind, name, out, lang=None, device=None) -> (path, width, height)
  Starts a preview server on 127.0.0.1 (any free port) for the call and the HMI device (model.select_device), opens ?<kind>=<name>&live=0&png=1 (the app
  drops the sidebar and draws the screen at 0, 0, 1:1) and writes a PNG of the device resolution (a pop-up: its own
  Width x Height). The view is the effective document: the generated one where it exists, else the TIA export.
"""
import os
import threading
import urllib.parse

from . import model, server
from .edge import NOT_FOUND, Edge, EdgeError, edge_path

CANVAS = (1280, 800)        # static/app.js CANVAS: drawing area of a document without Width / Height, not a TIA value


class PngError(Exception):
    pass


def size_of(repo, doc):
    """Width x height the app draws the view at (static/app.js screenSize): the device resolution for screens and
    templates, else the document's Width x Height, else CANVAS."""
    if doc.kind != 'popup' and repo.resolution is not None:
        return repo.resolution.width, repo.resolution.height
    try:
        return int(float(doc.attr('Width'))), int(float(doc.attr('Height')))
    except (TypeError, ValueError):
        return CANVAS


def shoot(repo_path, kind, name, out, lang=None, device=None):
    repo = model.load(repo_path, device=device)
    doc = repo.find(kind, name)
    if doc is None:
        raise PngError('no %s %s (neither generated nor exported)' % (kind, name))
    if not edge_path():
        raise PngError(NOT_FOUND)
    width, height = size_of(repo, doc)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    httpd = server.make_server(repo_path, host='127.0.0.1', port=0, device=device)
    t = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    t.start()
    edge = Edge()
    try:
        q = {kind: name, 'live': '0', 'png': '1'}
        if lang:
            q['lang'] = lang
        url = 'http://127.0.0.1:%d/?%s' % (httpd.server_address[1], urllib.parse.urlencode(q))
        edge.screenshot(url, out, width, height)
    except EdgeError as ex:
        raise PngError(str(ex))
    finally:
        edge.close(ignore_errors=True)
        httpd.shutdown()
        httpd.server_close()
    return out, width, height
