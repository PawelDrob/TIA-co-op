"""The two dashboards as the setup window sees them: whether each runs, started with no console, opened in the browser.
No tkinter. A dashboard is told by what its port answers at /api/about (tools\\dashboard\\live.py), so another program
on the port is not taken for it; a dashboard started before it had that page is told by its heading, as the skill
tia-dashboard tells it. Stopping stays with its icon's menu."""
import http.client
import json
import os
import re
import socket
import subprocess
import time
import webbrowser
from dataclasses import dataclass

ABOUT = '/api/about'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NEW_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
ANSWER_SECONDS = 2
START_SECONDS = 20


@dataclass
class Dashboard:
    key: str
    title: str
    app: str            # what it says at /api/about
    port: int
    default_port: int
    tool: tuple         # what pythonw runs, from the clone
    headings: tuple     # the <h1> of builds that had no /api/about
    purpose: str

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/'

    def command(self, clone):
        port = ('--port', str(self.port)) if self.port != self.default_port else ()
        return [os.path.join(clone, '.venv', 'Scripts', 'pythonw.exe'), '-X', 'utf8',
                os.path.join(clone, self.tool[0]), *self.tool[1:], *port]


@dataclass
class Status:
    state: str          # running, stopped, other
    clone: str = ''     # of a running one, when it says
    text: str = ''      # of another program on the port


def dashboards(ports=None):
    """Both dashboards; ports: other ports than their defaults, (development, TIA), for a test."""
    development, tia = ports or (8770, 8771)
    return [
        Dashboard('development', 'Development dashboard', 'development-dashboard', development, 8770,
                  (os.path.join('tools', 'dashboard', 'review_server.py'),), ('Development dashboard',),
                  'For people changing this repo with agents: the questions of the agents, review pages and tickets.'),
        Dashboard('tia', 'TIA dashboard', 'tia-dashboard', tia, 8771, ('TiaAgentStatus', 'dashboard'),
                  ('TIA-co-op dashboard', 'TIA CO-OP DASHBOARD', 'TIA dashboard'),
                  'What the agents do to your TIA projects: what needs you, each bridge and its TIA, change reports.'),
    ]


def get(port, path):
    """(status, body) of a GET on this machine, None when nothing answers. No proxy."""
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=ANSWER_SECONDS)
    try:
        c.request('GET', path)
        r = c.getresponse()
        return r.status, r.read(1 << 20).decode('utf-8', 'replace')
    except (OSError, http.client.HTTPException):
        return None
    finally:
        c.close()


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def probe(dashboard):
    if not listening(dashboard.port):
        return Status('stopped')
    answer = get(dashboard.port, ABOUT)
    if answer and answer[0] == 200:
        try:
            about = json.loads(answer[1])
        except ValueError:
            about = None
        if isinstance(about, dict) and about.get('app') == dashboard.app:
            return Status('running', about.get('clone') if isinstance(about.get('clone'), str) else '')
    page = get(dashboard.port, '/')
    if page and page[0] == 200 and any(f'<h1>{h}</h1>' in page[1] for h in dashboard.headings):
        return Status('running')
    program = listener(dashboard.port)
    return Status('other', text=f'Port {dashboard.port} is taken by {program or "another program"}, which does not answer as the '
                                f'{dashboard.title.lower()}. Close that program, or start the dashboard by hand with --port.')


LISTEN_LINE = re.compile(r'^\s*TCP\s+(?:[\d.]+|\[[^\]]*\]):(\d+)\s+(?:0\.0\.0\.0|\[::\]):0\s+\S+\s+(\d+)\s*$')


def listener(port):
    """'name (process N)' of the program listening on the port, '' when it cannot be told. netstat's state word is in the
    language of Windows, so a listening line is told by its remote address, which is none."""
    try:
        out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, errors='replace', timeout=10,
                             stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).stdout
        pid = next((m[2] for m in map(LISTEN_LINE.match, out.splitlines()) if m and int(m[1]) == port), None)
        if not pid:
            return ''
        out = subprocess.run(['tasklist', '/fi', f'PID eq {pid}', '/fo', 'csv', '/nh'], capture_output=True, text=True,
                             errors='replace', timeout=10, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ''
    name = out.split('","')[0].strip().strip('"') if out.startswith('"') else ''
    return f'{name} (process {pid})' if name else f'process {pid}'


def start(dashboard, clone):
    """Starts it as its README does, with pythonw and no console, on its own so it outlives this window. (ok, text): ok once
    it answers as itself; a dashboard that cannot start shows its own box saying why."""
    command = dashboard.command(clone)
    if not os.path.isfile(command[0]):
        return False, f'{command[0]} is missing: run uv sync in {clone}.'
    try:
        process = subprocess.Popen(command, cwd=clone, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   close_fds=True, creationflags=NO_WINDOW | NEW_GROUP)
    except OSError as e:
        return False, f'It did not start: {e}'
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        status = probe(dashboard)
        if status.state == 'running':
            return True, f'Started: {dashboard.url}'
        if process.poll() is not None:
            return False, (f'It ended with exit code {process.returncode}. To read why, run in a terminal: '
                           + subprocess.list2cmdline([command[0].replace('pythonw.exe', 'python.exe'), *command[1:]]))
        time.sleep(0.2)
    return False, f'It did not answer within {START_SECONDS} s.'


def open_page(dashboard):
    return webbrowser.open(dashboard.url)
