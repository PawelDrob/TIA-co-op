"""A dashboard server on a made-up repo folder, reached the way a browser reaches it."""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent.parent
sys.path.insert(0, str(TOOLS))
os.environ['DASHBOARD_NO_ICON'] = '1'      # every server a test starts, also through review_page.py: nothing on the desktop of the person


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def made_up_repo(test):
    """An empty folder that stands for a clone; the test's cleanup removes it, and fails the test if it cannot."""
    folder = tempfile.TemporaryDirectory(prefix='dashboard-test-')      # it deletes git's read-only files, rmtree does not
    test.addCleanup(folder.cleanup)
    return Path(folder.name)


def class_repo(cls):
    """The same for all tests of a class; a folder that cannot go fails the class."""
    folder = tempfile.TemporaryDirectory(prefix='dashboard-test-')
    cls.addClassCleanup(folder.cleanup)
    return Path(folder.name)


def ticket(scratch, effort, name, text):
    folder = scratch / effort / 'issues'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding='utf-8')


def effort_map(scratch, effort, text='# Map\n\n## Destination\n\nThe goal.\n'):
    (scratch / effort).mkdir(parents=True, exist_ok=True)
    (scratch / effort / 'map.md').write_text(text, encoding='utf-8')


def headless():
    """Headless Edge or Chrome; None without either or hmipreview, and the test skips."""
    sys.path.insert(0, str(REPO / 'TiaHmiGenerator'))
    try:
        from hmipreview.edge import Edge, edge_path
    except ImportError:
        return None
    return Edge() if edge_path() else None


def dom_at_load(edge, url):
    """The DOM of a real page when it has loaded. Edge.dump_dom waits for virtual time to run out, which a page holding its
    live connection open never lets it do."""
    try:
        return subprocess.run([edge.path, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                               '--disable-extensions', '--user-data-dir=' + edge.profile, '--dump-dom', url],
                              capture_output=True, timeout=30, env=edge.environment()).stdout.decode('utf-8', 'replace')
    finally:
        edge.kill()


# the theme switch, as dashboard.js makes it, among the direct content of the page's top bar
SWITCH_IN_TOP = re.compile(r'class="top">(?:(?!</header>|</div>).)*?<button[^>]*class="theme"[^>]*aria-label="Switch to \w+ mode"[^>]*><svg',
                           re.S)


class Server:
    def __init__(self, scratch):
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(TOOLS / 'review_server.py'),
                                      '--port', str(self.port), '--root', str(scratch)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        self.proc.kill()
        raise RuntimeError('the server did not start: ' + self.proc.communicate()[1].decode(errors='replace'))

    def stop(self):
        self.proc.kill()
        self.proc.wait()
        self.proc.stderr.close()

    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}', timeout=15) as r:
            return r.read().decode('utf-8')

    def status_code(self, path, data=None, headers=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
