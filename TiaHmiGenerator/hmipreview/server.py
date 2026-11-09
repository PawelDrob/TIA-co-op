"""Preview server: JSON endpoints, a change stream and the static browser app for one project repo.

Standard library only (http.server, threading). Every request answers for the repo as it is on disk, so the
answers follow agent regenerations without a restart: the loaded repo and its findings are cached while the
fingerprint of the files they come from is unchanged (repocache.py). One server shows every HMI device of the repo:
an endpoint answers for the device of ?device= (a device folder under hmi/), without it for the
server's device (model.select_device: --device, else hmiDevice, else the only device folder, else the first).
Works without TIA.

Endpoints are entries of ROUTES: (method, path, handler). A handler takes a Request and returns a Response (or
writes the answer itself and returns None, like the change stream). Other modules add endpoints with
route('GET', '/api/diff')(handler) in their own file, imported at the bottom of this file.
"""
import ipaddress
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import changes as hchanges, model, running, sides
from .links import link_states
from .repocache import RepoCache

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
ORIGIN_NAMES = {model.EXPORT: 'tia', model.GENERATED: 'generated'}

ROUTES = []


def route(method, path):
    """Decorator: register handler(req) -> Response for an exact path."""
    def register(handler):
        ROUTES.append((method, path, handler))
        return handler
    return register


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Response:
    status: int = 200
    body: bytes = b''
    content_type: str = 'application/json; charset=utf-8'
    headers: dict = field(default_factory=dict)


def json_response(data, status=200):
    return Response(status, json.dumps(data, indent=1, ensure_ascii=False).encode('utf-8'))


@dataclass
class Request:
    handler: BaseHTTPRequestHandler
    server: 'PreviewServer'
    method: str
    path: str
    query: dict              # name -> first value

    @property
    def repo_path(self):
        return self.server.repo_path

    def cache(self):
        """The RepoCache of the device of ?device= (the server's device without it)."""
        return self.server.cache_for(self.query.get('device') or None)

    def repo(self):
        return self.cache().repo()

    def findings(self):
        """(repo, findings) of one state of the repo."""
        return self.cache().findings()

    def param(self, name, required=True, default=None):
        v = self.query.get(name)
        if v is None:
            if required:
                raise HttpError(400, 'missing query parameter: %s' % name)
            return default
        return v


# --- helpers shared by the endpoints ------------------------------------------------------------------------

def number(doc):
    n = doc.attr('Number')
    try:
        return int(n)
    except (TypeError, ValueError):
        return None


def doc_entry(repo, doc):
    e = {'kind': doc.kind, 'name': doc.name, 'folder': doc.folder, 'origin': ORIGIN_NAMES[doc.origin],
         'path': doc.path}
    if doc.kind == 'screen':
        e['number'] = number(doc)
    if doc.origin == model.GENERATED:
        exp = repo.export_of(doc)
        e['replaces'] = exp.path if exp else None
    return e


def _panel_dict(r):
    return {'width': r.width, 'height': r.height, 'portrait': r.portrait, 'orderNumber': r.order_number or None,
            'panel': r.panel or None}


def device(repo):
    """The panel the preview draws for: the declared panel (declared true), else the hardware; hardware: the HMI
    device in TIA when it differs from the declared panel (resolution.mismatch), else null."""
    r = repo.resolution
    if r is None:
        return None
    out = _panel_dict(r)
    out['declared'] = repo.panel is not None
    hw = repo.hardware
    out['hardware'] = _panel_dict(hw) if repo.panel is not None and hw is not None and hw != repo.panel and \
        not repo.panel.same_screen(hw) else None
    return out


def start_screen(repo, screens):
    configured = repo.config.get('startScreen')
    if configured:
        return configured
    numbered = [d for d in screens if number(d) is not None]
    if numbered:
        return min(numbered, key=lambda d: (number(d), d.name)).name
    return screens[0].name if screens else None


# --- endpoints ----------------------------------------------------------------------------------------------

@route('GET', '/api/about')
def about(req):
    """Which server this is: what the TIA dashboard asks before it links to a record of running.py. Only this machine
    is told: the repo path and the process number are not for the network a --host server answers."""
    if not on_this_machine(req.handler.client_address[0], req.server.server_address[0]):
        raise HttpError(403, 'only this machine is told which server this is')
    return json_response({'app': 'hmipreview', 'repo': req.server.repo_path, 'pid': os.getpid(),
                          'devices': model.device_folders(req.server.repo_path)})


@route('GET', '/api/screens')
def screen_list(req):
    repo = req.repo()
    eff = sorted(repo.effective, key=lambda d: (d.kind, d.folder, d.name))
    by_kind = {k: [doc_entry(repo, d) for d in eff if d.kind == k] for k in model.KINDS}
    screens = [d for d in eff if d.kind == 'screen']
    return json_response({
        'device': device(repo),
        'hmiDevice': repo.device,
        'devices': repo.devices,
        'startScreen': start_screen(repo, screens),
        'screens': by_kind['screen'],
        'templates': by_kind['template'],
        'popups': by_kind['popup'],
        'textlists': by_kind['textlist'],
    })


def read_text(repo_path, rel):
    with open(os.path.join(repo_path, *rel.split('/')), encoding='utf-8-sig') as f:
        return f.read()


def find_document(req, repo=None):
    """The document named by ?kind=&name=[&origin=tia|generated]; without origin the effective one."""
    repo = repo or req.repo()
    kind, name = req.param('kind'), req.param('name')
    origin = req.param('origin', required=False)
    origins = {v: k for k, v in ORIGIN_NAMES.items()}
    if origin is not None and origin not in origins:
        raise HttpError(400, 'origin must be tia or generated')
    doc = repo.find(kind, name, origins.get(origin))
    if doc is None:
        raise HttpError(404, 'no %s %s' % (kind, name))
    return repo, doc


@route('GET', '/api/document')
def one_document(req):
    repo, findings = req.findings()
    repo, doc = find_document(req, repo)
    e = doc_entry(repo, doc)
    e['xml'] = read_text(req.repo_path, doc.path)
    e['findings'] = [f.to_dict() for f in findings if f.document == doc.path]
    e['links'] = [l.to_dict() for l in link_states(repo, doc)]
    generated = doc.origin == model.GENERATED
    e['presets'] = repo.presets(doc) if generated else {}
    e['generated'] = repo.generated_stamp(doc) if generated else None
    return json_response(e)


@route('GET', '/api/findings')
def repo_findings(req):
    return json_response([f.to_dict() for f in req.findings()[1]])


@route('GET', '/api/handbuilt')
def handbuilt_objects(req):
    """Hand-built objects (hmi/[<device>/]handbuilt.json), all or those of ?screen=."""
    repo = req.repo()
    screen = req.param('screen', required=False)
    items = repo.handbuilt
    if screen is not None:
        items = [h for h in items if h.get('screen') == screen]
    return json_response(items)


@route('GET', '/api/pictures')
def picture_urls(req):
    """{graphic name: URL of its image} of the project graphics (project/graphics) a browser can draw. The URL holds
    the file's version, so a redraw after a change never shows the image the browser already has."""
    sd = sides.FolderStamps(req.repo_path)
    ids = sd.files()
    return json_response({n: '/api/picture?' + urllib.parse.urlencode({'name': n, 'v': ids[p]})
                          for n, p in hchanges.picture_files(sd).items()})


@route('GET', '/api/picture')
def picture_image(req):
    """The image of the project graphic ?name=; only those /api/pictures lists, so no path comes from the URL."""
    sd = sides.FolderStamps(req.repo_path)
    path = hchanges.picture_files(sd).get(req.param('name'))
    if path is None:
        raise HttpError(404, 'no picture %s' % req.param('name'))
    return Response(200, sd.read(path), mimetypes.guess_type(path)[0] or 'application/octet-stream')


HEARTBEAT = 15.0     # seconds between keep-alive comments on the change stream


def snapshot(repo_path):
    """{repo-relative path: (mtime_ns, size)} of every file the preview draws from: hmi/ and the project graphics."""
    out = {}
    for root in sides.ROOTS:
        for dirpath, _dirs, files in os.walk(os.path.join(repo_path, *root.split('/'))):
            for fn in files:
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                out[os.path.relpath(full, repo_path).replace(os.sep, '/')] = (st.st_mtime_ns, st.st_size)
    return out


def changes(before, after):
    """[(path, 'added'|'modified'|'removed')], sorted by path."""
    out = []
    for p in sorted(set(before) | set(after)):
        if p not in before:
            out.append((p, 'added'))
        elif p not in after:
            out.append((p, 'removed'))
        elif before[p] != after[p]:
            out.append((p, 'modified'))
    return out


@route('GET', '/api/events')
def change_stream(req):
    """Server-Sent Events: 'ready' once, then one 'change' {path, change} per changed file (snapshot)."""
    h, srv = req.handler, req.server
    h.close_connection = True
    h.send_response(200)
    h.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Connection', 'close')
    h.end_headers()

    def send(text):
        h.wfile.write(text.encode('utf-8'))
        h.wfile.flush()

    try:
        previous = snapshot(req.repo_path)
        reported = dict(previous)
        send('retry: 1000\nevent: ready\ndata: {}\n\n')
        last = time.monotonic()
        while not srv.stopping.wait(srv.poll_interval):
            now = snapshot(req.repo_path)
            for path, change in changes(reported, now):
                if now.get(path) != previous.get(path):
                    continue                          # still being written: report once it is stable
                send('event: change\ndata: %s\n\n' % json.dumps({'path': path, 'change': change}))
                if path in now:
                    reported[path] = now[path]
                else:
                    reported.pop(path, None)
                last = time.monotonic()
            previous = now
            if time.monotonic() - last >= HEARTBEAT:
                send(': keep-alive\n\n')
                last = time.monotonic()
    except (ConnectionError, OSError):
        pass                                          # browser went away
    return None


# --- HTTP plumbing ------------------------------------------------------------------------------------------

# The server binds 127.0.0.1 unless told otherwise (it serves the project's screens). With
# --host 0.0.0.0 the host of the engineering guest reaches it; it then still answers only clients on
# loopback, RFC 1918 private and link-local addresses (IPv6: ::1, unique local fc00::/7, fe80::/10).
LOCAL_NETWORKS = [ipaddress.ip_network(n) for n in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16',
    '::1/128', 'fc00::/7', 'fe80::/10')]


def client_ip(address):
    """The IP address of a client as the socket gives it, an IPv4 one mapped into IPv6 as IPv4, without an IPv6 %scope;
    None when it does not read."""
    try:
        ip = ipaddress.ip_address(str(address).split('%', 1)[0])
    except ValueError:
        return None
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped is not None else ip


def is_local_client(address):
    """True for a client address on loopback, a private (RFC 1918 / unique local) or a link-local network."""
    ip = client_ip(address)
    return ip is not None and any(ip in n for n in LOCAL_NETWORKS)


def on_this_machine(client, bound):
    """True for a client on loopback or on the address the server is bound to, both this machine."""
    ip = client_ip(client)
    return ip is not None and (ip.is_loopback or str(ip) == bound)


class Handler(BaseHTTPRequestHandler):
    server_version = 'hmipreview'
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def _dispatch(self, method):
        parts = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parts.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query, keep_blank_values=True).items()}
        req = Request(self, self.server, method, path, query)
        try:
            if not self.server.is_allowed_client(self.client_address[0]):
                raise HttpError(403, 'only clients on this guest and its host network are answered')
            handler = self._find(method, path)
            resp = handler(req)
        except HttpError as ex:
            resp = json_response({'error': ex.message}, ex.status)
        except Exception as ex:                       # report, keep serving
            resp = json_response({'error': '%s: %s' % (type(ex).__name__, ex)}, 500)
        if resp is not None:
            self._send(resp)

    def _find(self, method, path):
        allowed = False
        for m, p, h in ROUTES:
            if p == path:
                if m == method:
                    return h
                allowed = True
        if method == 'GET' and not path.startswith('/api/'):
            return static_file
        raise HttpError(405 if allowed else 404, 'no endpoint %s %s' % (method, path))

    def _send(self, resp):
        self.send_response(resp.status)
        self.send_header('Content-Type', resp.content_type)
        self.send_header('Content-Length', str(len(resp.body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp.body)

    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))


def static_path(url_path):
    """The file under STATIC_DIR a URL path names, or None when it would leave STATIC_DIR (.., backslashes, drive
    or absolute paths, links). Compared after realpath, so no spelling of the path can escape."""
    rel = url_path.lstrip('/') or 'index.html'
    root = os.path.realpath(STATIC_DIR)
    full = os.path.realpath(os.path.join(root, rel))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:                                # another drive
        return None
    return full if inside and full != root else None


def static_file(req):
    full = static_path(req.path)
    if full is None or not os.path.isfile(full):
        raise HttpError(404, 'not found: %s' % req.path)
    with open(full, 'rb') as f:
        body = f.read()
    ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
        ctype += '; charset=utf-8'
    return Response(200, body, ctype)


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, repo_path, address, poll_interval=0.5, verbose=False, device=None):
        self.repo_path = os.path.abspath(repo_path)
        self.poll_interval = poll_interval
        self.verbose = verbose
        self.stopping = threading.Event()
        self.is_allowed_client = is_local_client
        self.device = device
        self.cache = RepoCache(self.repo_path, device)
        self._caches = {}
        self._caches_lock = threading.Lock()
        super().__init__(address, Handler)

    def default_device(self):
        """The device folder an endpoint answers for without ?device=: the server's (--device, hmiDevice, the
        only one), else the first device folder when hmi/ holds several and none is chosen; '' one-device layout."""
        repo = self.cache.repo()
        if repo.device is None and repo.devices and self.device is None:
            return repo.devices[0]
        return repo.device

    def cache_for(self, device=None):
        """The RepoCache of a device folder (None: default_device()); 404 for a folder that is not a device."""
        if device is None:
            device = self.default_device()
        elif device not in model.device_folders(self.repo_path):
            raise HttpError(404, 'no HMI device folder %s under hmi/' % device)
        if device is None or device == self.cache.repo().device:
            return self.cache
        with self._caches_lock:
            if device not in self._caches:
                self._caches[device] = RepoCache(self.repo_path, device)
            return self._caches[device]

    def shutdown(self):
        self.stopping.set()
        super().shutdown()


def make_server(repo_path, host='127.0.0.1', port=8765, poll_interval=0.5, verbose=False, device=None):
    """A PreviewServer bound to host:port (port 0 = any free port), opening on device; call serve_forever()."""
    return PreviewServer(repo_path, (host, port), poll_interval, verbose, device)


def urls_for(httpd, host):
    """URLs to print, the main one first: the guest's host name and its IPv4 addresses when bound to all
    interfaces, else the bound host."""
    port = httpd.server_address[1]
    if host not in ('0.0.0.0', '::', ''):
        return ['http://%s:%d/' % (host, port)]
    name = socket.gethostname()
    urls = ['http://%s:%d/' % (name, port)]
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(name, None, socket.AF_INET)})
    except OSError:
        ips = []
    urls += ['http://%s:%d/' % (ip, port) for ip in ips if not ip.startswith('127.')]
    return urls


SERVING = 'Serving '     # start of the last start-up line; --detach reads stdout up to it


def serve(repo_path, host='127.0.0.1', port=8765, verbose=False, out=None, device=None):
    """Run the server until interrupted. Prints the URL (first line), further URLs, then 'Serving <repo>'. While it
    runs, its record in running.folder() tells the TIA dashboard where it is."""
    out = out or sys.stdout
    httpd = make_server(repo_path, host, port, verbose=verbose, device=device)
    urls = urls_for(httpd, host)
    out.write(urls[0] + '\n')
    for u in urls[1:]:
        out.write('also ' + u + '\n')
    dev, devices = httpd.default_device(), httpd.cache.repo().devices
    out.write('%s%s%s (Ctrl+C to stop)\n' % (SERVING, httpd.repo_path, ', HMI devices %s, opens %s' % (
        ', '.join(devices), dev) if len(devices) > 1 else ', HMI device %s' % dev if dev else ''))
    out.flush()
    where = running.folder()
    try:
        running.prune(where)
        running.write(where, running.record(httpd.repo_path, running.local_url(host, httpd.server_address[1])))
    except OSError:
        pass                                          # the preview works without; the dashboard does not show it
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        running.remove(where, os.getpid())
        httpd.stopping.set()
        httpd.server_close()


# What --detach adds when the server stays in a job that ends its processes on close: an agent's command runner may
# close it with the command.
IN_JOB_NOTE = ('note: the server could not leave the job this command runs in, so it may end when the command does. '
               'If the URL stops answering, ask the user to start the server in a terminal of their own.')


def detach(argv, out=None):
    """Start 'serve' (argv without --detach) as a background process; print its start-up lines and pid once it answers.

    It leaves the job of the calling command where the job lets it: an agent's command runner may end that
    job, and every process in it, when the command returns.

    Measured: in nested jobs, as under the python.exe of a venv, a launcher in a job of its own, the flag leaves the jobs
    that allow it and raises nothing for the others; and a job that keeps the server need not end it (the one this
    tool's own tests run in never does). So a probe asks the job it lands in."""
    import subprocess
    import tempfile
    out = out or sys.stdout
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env['PYTHONPATH'] = package_root + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env['PYTHONUNBUFFERED'] = '1'
    log = tempfile.NamedTemporaryFile('w', prefix='hmipreview-', suffix='.log', delete=False)

    def start(**kw):
        # UTF-8 on both ends of the pipe, whatever this process runs with: the repo path is in the lines
        return subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hmipreview'] + list(argv), cwd=package_root,
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log,
                                encoding='utf-8', **kw)
    in_job = False
    if os.name == 'nt':
        # Not DETACHED_PROCESS: the python.exe of a venv is a launcher, and a child it starts with no console gets a
        # window of its own.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            p = start(creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
        except PermissionError:      # the job does not let a process leave it; whether it ends it, the probe tells
            p = start(creationflags=flags)
        in_job = ends_on_close(flags)
    else:
        p = start(start_new_session=True)
    log.close()

    def failed(message):
        # The start-up lines go to the log only: the first of them is the URL, which an agent would hand on.
        with open(log.name, 'a', encoding='utf-8') as f:
            f.write(''.join(lines))
        out.write('%s, log: %s\n' % (message, log.name))
        return 1
    lines = []
    while True:
        line = p.stdout.readline()
        if not line:
            return failed('preview server did not start (exit %s)' % p.wait())
        lines.append(line)
        if line.startswith(SERVING):
            break
    p.stdout.close()
    url = lines[0].strip()
    if not answers(url):
        p.kill()
        p.wait()
        return failed('preview server does not answer at %s' % url)
    out.write(''.join(lines))
    out.write('pid %d (stop: Stop-Process -Id %d), log: %s\n' % (p.pid, p.pid, log.name))
    if in_job:
        out.write(IN_JOB_NOTE + '\n')
    out.flush()
    return 0


# Prints 1 when the innermost job this process is in ends its processes on close (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE).
JOB_PROBE = r'''
import ctypes
from ctypes import wintypes as w
class Basic(ctypes.Structure):
    _fields_ = [('user', ctypes.c_int64), ('job_user', ctypes.c_int64), ('flags', w.DWORD), ('min_ws', ctypes.c_size_t),
                ('max_ws', ctypes.c_size_t), ('processes', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD),
                ('scheduling', w.DWORD)]
class Extended(ctypes.Structure):
    _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('memory', ctypes.c_size_t * 4)]
k = ctypes.WinDLL('kernel32')
k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
EXTENDED_LIMIT_INFORMATION, KILL_ON_JOB_CLOSE = 9, 0x2000
info = Extended()
known = k.QueryInformationJobObject(None, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None)
print(1 if known and info.basic.flags & KILL_ON_JOB_CLOSE else 0)
'''


def ends_on_close(creationflags):
    """True when a process started with these flags lands in a job that ends its processes when it closes, as an
    agent's command runner may close it with the command. The interpreter itself is asked: the python.exe of a venv is
    a launcher in such a job of its own."""
    import subprocess
    python = getattr(sys, '_base_executable', '') or sys.executable
    try:
        r = subprocess.run([python, '-I', '-c', JOB_PROBE], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=10, creationflags=creationflags)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() == '1'


def answers(url):
    """True once an HTTP request to url gets a response, whatever its status, within 10 seconds; no proxy."""
    import http.client
    parts = urllib.parse.urlsplit(url)
    deadline = time.monotonic() + 10
    while True:
        c = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
        try:
            c.request('GET', '/')
            c.getresponse().read()
            return True
        except (OSError, http.client.HTTPException):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.1)
        finally:
            c.close()


from . import diffapi  # noqa: E402,F401  registers /api/diff
from . import treeapi  # noqa: E402,F401  registers /api/tree
from . import typesapi  # noqa: E402,F401  registers /api/typenames
from . import findingsapi  # noqa: E402,F401  registers /api/findingspage
from . import catalogueapi  # noqa: E402,F401  registers /api/catalogue
