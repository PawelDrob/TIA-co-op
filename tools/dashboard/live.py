"""The live core of a local dashboard, shared by the pages of any dashboard in this repo. It knows nothing of what they show.

A page links the stylesheet and script through head(); bind Server to 127.0.0.1 only (another machine comes in through
something like tailscale serve); Handler.stream() holds a connection open and pushes an update whenever a
watch function returns something new, which dashboard.js shows. Every file a page loads comes from here: nothing is
fetched from the internet.
"""
import html
import json
import os
import re
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / 'vendor'
CHECK_SECONDS = 1.0       # how often a connection looks for changes
KEEPALIVE_SECONDS = 5     # a quiet connection writes this often; the write is how a closed tab is noticed

ASSETS = {'/dashboard.css': 'text/css; charset=utf-8', '/dashboard.js': 'text/javascript; charset=utf-8'}
VENDOR_KINDS = {'.js': 'text/javascript; charset=utf-8', '.woff2': 'font/woff2'}
ASSET_TAGS = '<link rel="stylesheet" href="/dashboard.css"><script src="/dashboard.js"></script>'    # in the head: the theme is set before anything is drawn
HOST = re.compile(r'([a-z0-9.-]+)(?::(\d{1,5}))?')
THIS_MACHINE = ('127.0.0.1', 'localhost')


def head(title):
    """Everything of a page before its body."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>'
            + ASSET_TAGS + '</head>')


def stamp(f):
    """What a connection watching one file looks at: changes when the file does, None when it is gone."""
    try:
        return str(f.stat().st_mtime_ns)
    except OSError:
        return None


class Handler(SimpleHTTPRequestHandler):
    # Listening on 127.0.0.1 keeps other machines out, not a web site in the browser here: one that points its own name at
    # 127.0.0.1 reads and posts as if it were this page. Its Host still names that site, so every request must name this
    # server: this machine with the server's port, or a proxy's address that ends in one of proxy_suffixes.
    proxy_suffixes = ()

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.host_is_ours():
            return True
        self.close_connection = True
        self.send_error(403, 'Not an address of this server')
        return False

    def host_is_ours(self):
        hosts = self.headers.get_all('Host') or []
        m = HOST.fullmatch(hosts[0].lower()) if len(hosts) == 1 else None
        if not m:
            return False
        if m.group(1) in THIS_MACHINE:
            return int(m.group(2) or 80) == self.server.server_address[1]
        return m.group(1).endswith(self.proxy_suffixes)

    def log_message(self, fmt, *args):
        pass

    def send_body(self, code, data, kind, cache='no-store'):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, code, body, kind):
        self.send_body(code, body.encode('utf-8'), kind)

    def send_asset(self, path):
        """Serves the stylesheet, the script or a vendored file; False when path is none of them."""
        if path in ASSETS:
            self.send_body(200, (HERE / path[1:]).read_bytes(), ASSETS[path])
            return True
        if path.startswith('/vendor/'):
            f = VENDOR / path[len('/vendor/'):]
            if f.suffix in VENDOR_KINDS and f.parent == VENDOR and f.is_file():
                self.send_body(200, f.read_bytes(), VENDOR_KINDS[f.suffix], 'max-age=86400')
                return True
        return False

    def stream(self, watch):
        """Holds the connection open: an update when it opens and when watch() returns something else. watch returns
        what the page needs as JSON; an OSError from it (a file moved while it was read) waits for the next look."""
        self.close_connection = True
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        try:
            last, quiet = None, 0.0
            while True:
                try:
                    now = watch()
                except OSError:
                    now = last
                if now is not None and now != last:
                    self.wfile.write(b'event: update\ndata: ' + json.dumps(now).encode('utf-8') + b'\n\n')
                    self.wfile.flush()
                    last, quiet = now, 0.0
                elif quiet >= KEEPALIVE_SECONDS:
                    self.wfile.write(b': still here\n\n')
                    self.wfile.flush()
                    quiet = 0.0
                time.sleep(CHECK_SECONDS)
                quiet += CHECK_SECONDS
        except OSError:       # the tab closed
            pass


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port in use and take its requests: it must fail instead.
    allow_reuse_address = os.name != 'nt'

