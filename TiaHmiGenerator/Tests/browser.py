"""Headless Edge (else Chrome) for the browser app tests: load a preview page, dump the drawn DOM and read it back
as a small element tree. Standard library only.

  edge_path()                    -> msedge.exe, else chrome.exe, or None (the tests skip with NOT_FOUND then)
  Edge().dump(url) -> Node       hmipreview.edge.Edge.dump_dom, parsed, once the page has drawn (dumped again with
                                 a larger budget while it has not); screenshot() always takes the largest budget;
                                 both run again while the browser failed a request to the page's server (its NetLog
                                 says, failed_requests), NET_TRIES runs at most, each such run named on stderr;
                                 close() kills every browser process still using its temp profile and removes it
  Node                           tag, attrs, children, text(); find(pred) / find_all(pred); obj(name); ready()
  png_colours(path)              the pixels of a screenshot, for what only the stylesheet decides

The page is driven by URL hooks of the app (static/app.js): ?screen=<name>, ?live=0 (no change stream, which
would keep virtual time from ever running out), ?click=<object>,<object>... (run-mode press/release/click on each
object in turn), ?inspect=<object>, ?fit=1, ?diff=commit|export. The app sets data-ready="1" on <html> when the
page is drawn.
"""
import json
import os
import struct
import sys
import urllib.parse
import zlib
from html.parser import HTMLParser

from hmipreview import edge as _edge
from hmipreview.edge import NOT_FOUND, EdgeError, edge_path  # noqa: F401  (used by the tests)

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []          # Node or str

    def text(self):
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children)

    @property
    def classes(self):
        return (self.attrs.get('class') or '').split()

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def find_all(self, pred):
        return [n for n in self.iter() if pred(n)]

    def find(self, pred):
        return next(iter(self.find_all(pred)), None)

    def ready(self):
        """data-ready of the page's <html>: '1' once drawn, 'error' when drawing failed, None before."""
        html = self.find(lambda n: n.tag == 'html')
        return html.attrs.get('data-ready') if html is not None else None

    def by_id(self, id_):
        return self.find(lambda n: n.attrs.get('id') == id_)

    def objs(self, name):
        """The drawn objects of that name (the project tree's links, a.obj, are not drawn objects)."""
        return self.find_all(lambda n: 'obj' in n.classes and n.tag != 'a' and n.attrs.get('data-name') == name)

    def obj(self, name):
        found = self.objs(name)
        return found[0] if found else None

    def body(self):
        """The shape that carries an object's geometry (class "body")."""
        return self.find(lambda n: 'body' in n.classes)

    def lines(self):
        """Text lines drawn in an object (class "line"), in order."""
        return [n.text() for n in self.find_all(lambda n: 'line' in n.classes)]

    def num(self, name):
        return float(self.attrs[name])

    def __repr__(self):
        return '<%s %s>' % (self.tag, self.attrs)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('#document', {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, [(k, v if v is not None else '') for k, v in attrs], self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, [(k, v if v is not None else '') for k, v in attrs], self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(html):
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def png_colours(path):
    """{(x, y): (r, g, b)} of a PNG as the browser writes it (8 bit, RGB or RGBA, not interlaced). Standard library only."""
    with open(path, 'rb') as f:
        data = f.read()
    pos, idat, width, height, channels = 8, [], 0, 0, 0
    while pos < len(data):
        size, kind = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + size]
        if kind == b'IHDR':
            width, height, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError('PNG form not read here: depth %d, colour %d, interlace %d' % (depth, colour, interlace))
            channels = 3 if colour == 2 else 4
        elif kind == b'IDAT':
            idat.append(chunk)
        pos += 12 + size
    raw = zlib.decompress(b''.join(idat))
    stride, previous, out = width * channels, bytes(width * channels), {}
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                row[i] = (row[i] + left) & 255
            elif kind == 2:
                row[i] = (row[i] + up) & 255
            elif kind == 3:
                row[i] = (row[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                row[i] = (row[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        for x in range(width):
            out[x, y] = tuple(row[x * channels:x * channels + 3])
        previous = row
    return out


NET_TRIES = 3       # runs of one page at most while the browser fails a request to its server


class Edge(_edge.Edge):
    BUDGETS = (8000, 30000, 120000)

    def __init__(self, path=None):
        super().__init__(path)
        self.netlog = os.path.join(self.profile, 'netlog.json')
        self.failed = []            # of the last run: failed_requests()
        self.failures = []          # every run that failed a request: (url, failed)

    def _run(self, extra, url, budget, timeout):
        """hmipreview.edge.Edge._run with a NetLog, read into failed."""
        if os.path.exists(self.netlog):
            os.remove(self.netlog)
        try:
            return super()._run(list(extra) + ['--log-net-log=' + self.netlog], url, budget, timeout)
        finally:
            self.failed = failed_requests(self.netlog, url)

    def dump(self, url, size=None):
        """The DOM once the page has drawn (data-ready on <html>), else the last one dumped. Dumped again with a larger
        virtual-time budget while it has not: on a slow machine (a CI runner) the browser dumped some pages before
        they had drawn, while a fast one dumps once."""
        for budget in self.BUDGETS:
            dom = parse(self.retried(url, lambda: self.dump_dom(url, budget, timeout(budget), size)))
            if dom.ready():
                break
        return dom

    def screenshot(self, url, out, width, height):
        """hmipreview.edge.Edge.screenshot with the largest budget: a PNG cannot say whether the page had drawn, and on
        a CI runner a shot at 8000 had not. An idle page costs no more with it, virtual time runs ahead of the clock."""
        budget, shoot = self.BUDGETS[-1], super().screenshot
        return self.retried(url, lambda: shoot(url, out, width, height, budget, timeout(budget)))

    def retried(self, url, run):
        """run() again while the browser failed a request to the page's server, NET_TRIES runs at most; each failed run
        named on stderr and kept in failures. On a CI runner the browser failed one now and then ("Failed to fetch")
        with no error raised by the server; whether the request reached it, the server's log of a failed page says
        (test_browser BrowserCase). One that fails on every run is given back."""
        for n in range(1, NET_TRIES + 1):
            result = run()
            if not self.failed:
                break
            self.failures.append((url, self.failed))
            sys.stderr.write('Tests.browser: run %d of %d of %s, the browser failed %s\n'
                             % (n, NET_TRIES, url, ', '.join('%s %s' % f for f in self.failed)))
        return result


def failed_requests(netlog, url):
    """[(url, net error name)] of the requests to the server of url (scheme, host and port) that the browser ended with
    a network error, from its NetLog (--log-net-log). [] without one (a stand-in browser writes none); [] too for one
    that does not read, which is named on stderr: a failed request in it goes unseen and is not run again."""
    try:
        with open(netlog, encoding='utf-8') as f:
            return _failed_requests(json.load(f), url)
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as ex:
        sys.stderr.write('Tests.browser: the NetLog of %s does not read (%s: %s), so a failed request in it goes unseen\n'
                         % (url, type(ex).__name__, ex))
        return []


def _failed_requests(log, url):
    c = log['constants']
    alive, url_request = c['logEventTypes']['REQUEST_ALIVE'], c['logSourceType']['URL_REQUEST']
    end, errors = c['logEventPhase']['PHASE_END'], {v: k for k, v in c['netError'].items()}
    server = urllib.parse.urlsplit(url)[:2]
    urls, out = {}, []
    for ev in log['events']:
        if ev['source']['type'] != url_request:
            continue
        params, source = ev.get('params') or {}, ev['source']['id']
        if 'url' in params:
            urls.setdefault(source, params['url'])
        if ev['type'] == alive and ev['phase'] == end and params.get('net_error', 0) < 0:
            asked = urls.get(source, '')
            if urllib.parse.urlsplit(asked)[:2] == server:
                out.append((asked, errors.get(params['net_error'], params['net_error'])))
    return out


def timeout(budget):
    """Seconds a browser run may take: virtual time runs ahead of the clock on an idle page, so the budget in seconds,
    plus a margin."""
    return 30 + budget // 1000
