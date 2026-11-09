"""The TIA dashboard: what happens to the projects, when and how. A local page on 127.0.0.1 that reads: the bridges'
state files through the watcher (with a herdr that renames and notifies nothing, or none at all), the tool logs and the
change reports of the project repos, git history, the records of the HMI previews that run, each asked whether it
answers, and the records of the report runs. It never writes a state file or a record and never touches TIA itself.

One button writes, on the request of the dashboard's own page only: "Make a change report of TIA now" starts a report
run of the project (TiaAgentStatus\\reportrun.py), a process of its own that attaches to the user's TIA through the
bridge, exports, commits and makes the report (docs\\adr\\0004-the-tia-dashboard-starts-a-report-run.md). The page then
reads the run's record like the rest.
"""
import datetime
import hmac
import html
import http.client
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from TiaAgentStatus import reportrun
from TiaAgentStatus import state as st
from TiaAgentStatus import statusline, table, watch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools' / 'dashboard'))
import live    # noqa: E402
import tray    # noqa: E402

TITLE = 'TIA CO-OP DASHBOARD'
TIA_EXE = 'siemens.automation.portal.exe'
SEP = ' · '
TIA_ASKS = 'TIA asks: '
# lastPrompt.answer when the bridge's guard closed the box (TiaBridge\Tools\Background.ps1). Anything else leaves it open:
# "left to the person at TIA", "(none of ... left to TIA)", "(not answered: ...)", "(not handled: ...)", or none written.
BOX_CLOSED = ('Cancel', 'Abort', 'No', 'NoToAll', 'Ok', 'handled')
# The page sees bridges, not agents: a bridge is an agent's link to TIA, idle while its agent reads, edits or thinks. It
# names the bridge for what it knows of one, and the agent for who acts: who calls, asks, is gone, or is to be asked.
IDLE = 'Bridge idle'
NO_BRIDGE = 'No bridge connected'
# the marks of dashboard.css's status standard, and the order of what comes first on the list
MARKS = {'need': '●', 'fail': '!', 'run': '▸', 'quiet': '○', 'past': '!'}
RANK = {'need': 0, 'fail': 1, 'run': 2, 'quiet': 3, 'past': 3}
CALLS_SHOWN = 100         # per project; the page says how many there are
FAILURE_CHARS = 300
# what Write-ToolLog names a log; the date as a month and day can be
LOG_NAME = re.compile(r'^(20\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])_[0-2]\d[0-5]\d[0-5]\d)_(.+?)(?:_\d+)?\.json$')
QUIET_TOOLS = {'list', 'tia_status', 'probe', 'background_steps'}     # the agent looks around; grey in the history
# changes\reports\<commit date>_<commit>.html, or <commit date>_<rev1>-<rev2>.html (TiaBridge\Tools\Report.ps1)
REPORT_NAME = re.compile(r'^(\d{4}-\d{2}-\d{2})_(?:(\w+)-)?(\w+)\.html$')
SUBJECT_RETRY_SECONDS = 60
# The records of the HMI previews that run: <folder>\<pid>.json {repo, url, pid, started}, the folder and the record as
# TiaHmiGenerator\hmipreview\running.py has them. A record counts while its process runs and its server answers
# GET <url>api/about with its repo and pid.
PREVIEW_FOLDER_ENV = 'HMIPREVIEW_RUNNING'
PREVIEW_SECONDS = 1.0
# A report run just started counts as running this long, or until its record is there: a second press starts none.
STARTING_SECONDS = 30
BUTTON = 'Make a change report of TIA now'
# The button's request: JSON with the page's token, which a page of another site can neither read nor send (its Origin
# is not this page's either).
REPORT_RUN = """document.addEventListener('click', function (e) {
  var b = e.target.closest && e.target.closest('button[data-report-run]');
  if (!b) return;
  b.disabled = true;
  var said = b.parentNode.parentNode.querySelector('.run-said');
  fetch('/api/report-run', {method: 'POST', headers: {'Content-Type': 'application/json',
        'X-Report-Token': document.querySelector('meta[name="report-token"]').content},
        body: JSON.stringify({project: b.dataset.reportRun})})
    .then(function (r) { return r.json(); })
    .then(function (j) { if (said) said.textContent = j.ok ? 'Starting.' : j.error; })
    .catch(function (err) { if (said) said.textContent = 'Not started: ' + err; b.disabled = false; });
});
"""
# The chosen project is the page's address, #<name>: it survives a live update and a reload and can be linked.
CHOSEN = """function showChosen(moved) {
  var want = '', known = false;
  try { want = decodeURIComponent(location.hash.slice(1)); } catch (e) {}
  document.querySelectorAll('#pane .chosen').forEach(function (s) {
    s.hidden = s.dataset.project !== want;
    if (!s.hidden) {
      known = true;
      if (moved === true) { s.querySelector('h2').focus({preventScroll: true}); window.scrollTo(0, 0); }
    }
  });
  document.querySelectorAll('#pane .nothing-chosen').forEach(function (s) { s.hidden = known; });
  document.querySelectorAll('#list .row').forEach(function (r) {
    r.setAttribute('aria-current', known && r.dataset.project === want);
  });
  document.body.classList.toggle('one-chosen', known);
}
window.addEventListener('hashchange', function () { showChosen(true); });
"""


def esc(x):
    return html.escape(str(x))


class NoHerdr:
    """A machine without herdr: the watcher gets no tabs, and there is no agent state from it."""
    status = {}

    def tabs(self):
        return {}

    def pane_tabs(self):
        return {}

    def pane_pids(self, pane):
        return []

    def rename(self, tab, label):
        pass

    def notify(self, title, body, sound='none'):
        pass


class ReadOnlyHerdr(watch.HerdrCli):
    """herdr as the watcher sees it, without its renames and notifications; status: {tab id: agent state}."""

    def __init__(self, exe='herdr'):
        super().__init__(exe)
        self.status = {}

    def tabs(self):
        self.status = {}
        got = self._run('tab', 'list').get('tabs', [])
        self.status = {t['tab_id']: t.get('agent_status') for t in got}
        return {t['tab_id']: t.get('label', '') for t in got}

    def rename(self, tab, label):
        pass

    def notify(self, title, body, sound='none'):
        pass


def duration(ms):
    """250 ms, 1.5 s, 1:05, 1:02:03"""
    if ms < 1000:
        return f'{ms} ms'
    if ms < 60000:
        return f'{ms / 1000:.1f} s'
    m, s = divmod(ms // 1000, 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02}:{s:02}' if h else f'{m}:{s:02}'


def why(x):
    """The text of a failure as a log gives it: a string, or a dict with a message; never its stack trace."""
    if isinstance(x, dict):
        x = x.get('message')
    return x if isinstance(x, str) and x else ''


def failure(r, failed):
    """Why a call failed, from what a tool log holds: the call's own reason, else that of its first failed object."""
    for text in [why(r.get(k)) for k in ('refused', 'error', 'summary')]:
        if text:
            return text
    for item in failed:
        messages = item.get('messages') if isinstance(item.get('messages'), dict) else {}
        listed = [m.get('description') for m in messages.get('messages') or [] if isinstance(m, dict)]
        for text in [why(item.get('refused')), why(item.get('error'))] + [why(m) for m in listed]:
            if text:
                return text
    return ''


def count(x):
    return x if isinstance(x, int) else 0


def describe(tool, at, r):
    """One tool log as a line of history; r None when the log does not read."""
    if not isinstance(r, dict):
        return {'tool': tool, 'at': at, 'ok': False, 'what': 'log not readable', 'ms': None}
    items = [i for i in r.get('items') or [] if isinstance(i, dict)] if isinstance(r.get('items'), (list, tuple)) else []
    failed = [i for i in items if i.get('ok') is False]
    ok = r.get('ok') is not False and not failed
    ms, words = r.get('durationMs'), []
    if tool == 'background_steps':
        words.append(f"session closed after {duration(count(r.get('totalMs')))}, "
                     f"TIA peak {count(r.get('tiaPeakWorkingSetMB')) / 1024:.1f} GB")
        ms = None
    elif tool == 'compile':
        errors = r['errors'] if isinstance(r.get('errors'), int) else sum(count(i.get('errors')) for i in items)
        names = ', '.join(str(i['name']) for i in items[:3] if i.get('name')) or str(r.get('scope') or '')
        text = f"{errors} errors, {sum(count(i.get('warnings')) for i in items)} warnings"
        if r.get('failedTotal'):
            text += f", {r['failedTotal']} not consistent"
        words.append(f'{names}: {text}' if names else text)
    elif tool == 'change_report':
        words.append(compared(r.get('before'), r.get('after')))
    elif tool == 'full_export':
        words.append(f"{count(r.get('exported'))} exported, {count(r.get('failedCount'))} failed")
    elif items:
        shown = failed or items
        names = [str(i['name']) for i in shown[:3] if i.get('name')]
        if names:
            words.append(', '.join(names) + (f' +{len(shown) - len(names)}' if len(shown) > len(names) else ''))
        if failed:
            words.append(f'{len(failed)} of {len(items)} failed')
    if why(r.get('reason')):
        words.append(r['reason'])
    if not ok:
        text = failure(r, failed)
        words.append(text if len(text) <= FAILURE_CHARS else text[:FAILURE_CHARS].rstrip() + '…')
    call = {'tool': tool, 'at': at, 'ok': ok, 'what': SEP.join(w for w in words if w),
            'ms': ms if isinstance(ms, int) else None}
    if tool == 'change_report' and r.get('page'):
        call['page'] = str(r['page']).replace('\\', '/').rsplit('/', 1)[-1]
        call['compared'] = compared(r.get('before'), r.get('after'))
    return call


def side(text):
    """The commit of one side of a change report as its log gives it: zz-line @ HEAD~1 (93a42fa) -> 93a42fa."""
    m = re.search(r'\(([^()]+)\)\s*$', text)
    return m.group(1) if m else text.split('@')[-1].strip()


def compared(before, after):
    return f'{side(before)} to {side(after)}' if isinstance(before, str) and isinstance(after, str) else ''


def log_time(name):
    """When the call of a tool log ended, from its name; None when the name is no tool log's, also one like 30 February."""
    m = LOG_NAME.match(name)
    if not m:
        return None
    s = m.group(1)
    try:
        return datetime.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[9:11]), int(s[11:13]), int(s[13:15]))
    except ValueError:
        return None


class Logs:
    """The tool calls of the project repos, from their logs\\ folders."""

    def __init__(self):
        self.read = {}     # path -> line of history: a tool log that reads does not change

    def calls(self, repo):
        """(the newest calls of a repo, newest first; how many there are)."""
        folder = os.path.join(repo, 'logs')
        try:
            names = sorted((n for n in os.listdir(folder) if log_time(n)), reverse=True)
        except OSError:
            return [], 0
        return [self.call(folder, n) for n in names[:CALLS_SHOWN]], len(names)

    def call(self, folder, name):
        path = os.path.join(folder, name)
        if path in self.read:
            return self.read[path]
        m = LOG_NAME.match(name)
        at = log_time(name)
        try:
            with open(path, encoding='utf-8-sig') as f:
                r = json.load(f)
        except (OSError, ValueError):      # also one still being written: the next round reads it again
            return describe(m.group(2), at, None)
        self.read[path] = describe(m.group(2), at, r)
        return self.read[path]

    def compared(self, repo):
        """{report page: what its newest change_report call compared}."""
        folder = os.path.join(repo, 'logs')
        try:
            names = sorted(n for n in os.listdir(folder) if '_change_report' in n and log_time(n))
        except OSError:
            return {}
        calls = [self.call(folder, n) for n in names]
        return {c['page']: c['compared'] for c in calls if c.get('page')}


def report_files(repo):
    """{name: path} of the report pages directly in changes\\reports\\ of a repo. Nothing that leads out of that folder,
    through a link in the path or a link as the file: a report link serves these and nothing else."""
    folder = Path(repo, 'changes', 'reports')
    try:
        names = os.listdir(folder)
        base = folder.resolve()
        if base != Path(repo).resolve() / 'changes' / 'reports':
            return {}
        return {n: folder / n for n in names
                if n.lower().endswith('.html') and (folder / n).is_file() and (folder / n).resolve().parent == base}
    except OSError:
        return {}


class ReportLists:
    """report_files of each repo for the rounds, listed again only when its changes\\reports\\ folder changed: a page
    added, removed or renamed changes the folder's time, and a link or another folder put in its place changes what
    the folder reads as (lstat and stat). A request for a page checks it in full again (Dashboard.report_file)."""

    def __init__(self):
        self.seen = {}      # repo -> (what its folder read as, its report_files)

    def of(self, repo):
        folder = os.path.join(repo, 'changes', 'reports')
        try:
            link, target = os.lstat(folder), os.stat(folder)
        except OSError:
            self.seen.pop(repo, None)
            return {}
        key = tuple((s.st_mtime_ns, s.st_ino, s.st_dev) for s in (link, target))
        hit = self.seen.get(repo)
        if hit and hit[0] == key:
            return hit[1]
        files = report_files(repo)
        self.seen[repo] = (key, files)
        return files


def made_of(f, m):
    """When a report page was made: (as the page says it, the time it sorts by, its size). That is when its file was
    written, by change_report or by hand, and nothing else writes it: git ignores changes/reports/. A file whose time does
    not read, gone or locked since its folder was listed, says the commit date of its name, sorts at the start of that
    day, and has no size."""
    try:
        stat = f.stat()
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime)), stat.st_mtime, stat.st_size
    except OSError:
        if not m:
            return '', 0.0, None
        day = datetime.datetime.strptime(m.group(1), '%Y-%m-%d')
        return m.group(1), day.timestamp(), None


class Subjects:
    """Commit subjects from git (read only). One git could not name is asked again after a minute."""

    def __init__(self):
        self.known = {}     # (repo, commit) -> (time asked, subject or '')

    def of(self, repo, commit):
        got = self.known.get((repo, commit))
        if got and (got[1] or time.monotonic() - got[0] < SUBJECT_RETRY_SECONDS):
            return got[1]
        env = reportrun.git_env()
        try:
            r = subprocess.run(['git', '-C', str(repo), 'log', '-1', '--format=%s', commit, '--'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=10, env=env, creationflags=watch.NO_WINDOW)
            subject = r.stdout.strip() if r.returncode == 0 else ''
        except (OSError, subprocess.SubprocessError):
            subject = ''
        self.known[(repo, commit)] = (time.monotonic(), subject)
        return subject


def previews_folder():
    return os.environ.get(PREVIEW_FOLDER_ENV) or os.path.join(
        os.environ.get('LOCALAPPDATA') or tempfile.gettempdir(), 'hmipreview', 'running')


def about(url):
    """What an HMI preview server at url says of itself, None when nothing answers there as one. No proxy, a second at
    most: a round waits for it."""
    parts = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(parts.hostname, parts.port, timeout=PREVIEW_SECONDS)
    try:
        c.request('GET', '/api/about')
        r = c.getresponse()
        got = json.loads(r.read(65536)) if r.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()
    return got if isinstance(got, dict) and got.get('app') == 'hmipreview' else None


def previews(folder, procs):
    """The HMI previews that run, oldest first: [{repo, url, started, devices}]. A record counts while its process runs
    and its server says it is that one: a port can be another's after a preview ended by Stop-Process. Read only: the
    next preview to start removes the records of those that are gone. The round waits for each answer, a second at most:
    only for a process that runs, so a record left behind costs nothing until Windows gives its number again."""
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith('.json'))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            with open(os.path.join(folder, n), encoding='utf-8') as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if not (isinstance(r, dict) and isinstance(r.get('repo'), str) and isinstance(r.get('url'), str)
                and isinstance(r.get('pid'), int) and r['url'].startswith('http://')) or procs.info(r['pid']) is None:
            continue
        got = about(r['url'])
        if not got or got.get('pid') != r['pid'] or not st.same_path(got.get('repo'), r['repo']):
            continue
        devices = got.get('devices') if isinstance(got.get('devices'), list) else []
        out.append({'repo': r['repo'], 'url': r['url'], 'started': st.parse_time(r.get('started')),
                    'devices': [d for d in devices if isinstance(d, str)]})
    return sorted(out, key=lambda x: x['started'] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))


def folder_of(repo):
    """The folder name of a repo path as a state file gives it."""
    return os.path.basename(repo.replace('\\', '/').rstrip('/')) if repo else ''


def spawn_run(root):
    """What starts a report run of a repo: a process of its own, with no window, that outlives the dashboard."""
    def start(repo):
        # Not DETACHED_PROCESS: the python.exe of a venv is a launcher, and a child it starts with no console gets a window of its own.
        flags = watch.NO_WINDOW | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'TiaAgentStatus', 'report-run', '--repo', repo, '--root', root],
                         cwd=reportrun.TOOLS, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    return start


class Dashboard:
    def __init__(self, procs, herdr, root, quiet_minutes=5.0, now=None, start_run=None):
        self.root, self.procs, self.herdr = root, procs, herdr
        self.watcher = watch.Watcher(procs, herdr, root, quiet_minutes, now)
        self.logs = Logs()
        self.subjects = Subjects()
        self.report_lists = ReportLists()
        self.latest = {'parts': {'summary': '', 'list': '', 'pane': '', 'others': ''}, 'title': TITLE, 'updated': ''}
        self.token = secrets.token_urlsafe(24)      # in the page: what a request to start a report run must carry
        self.start_run = start_run or spawn_run(root)
        self.starting = {}                          # repo folder -> (monotonic, when) of a run just started
        self.lock = threading.Lock()

    def folders(self):
        """{folder name: path} of the project repos under the root: those with tool logs or change reports."""
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            return {}
        found = {}
        for n in names:
            path = os.path.join(self.root, n)
            if not n.startswith('_') and (os.path.isdir(os.path.join(path, 'logs'))
                                          or os.path.isdir(os.path.join(path, 'changes', 'reports'))):
                found[n] = path
        return found

    def projects(self, rows, running=()):
        """Every project worked on or previewed, newest call first."""
        found = {name.casefold(): self.project(name, path) for name, path in self.folders().items()}

        def project_of(repo):
            """The project of a repo, made when there is none yet."""
            key = folder_of(repo).casefold()
            if key not in found:
                found[key] = self.project(folder_of(repo), repo)
            return found[key]
        for r in rows:
            if r['state'].get('repo'):
                project_of(r['state']['repo'])['rows'].append(r)
        for preview in running:
            project_of(preview['repo'])['previews'].append(preview)
        out = sorted((p for p in found.values() if p['calls'] or p['rows'] or p['reports'] or p['previews']),
                     key=lambda p: p['name'])
        out.sort(key=lambda p: p['calls'][0]['at'] if p['calls'] else datetime.datetime.min, reverse=True)
        return out

    def project(self, name, path):
        calls, total = self.logs.calls(path)
        return {'name': name, 'path': path, 'rows': [], 'calls': calls, 'total': total, 'reports': self.reports(name, path),
                'previews': []}

    def reports(self, name, path):
        """The change reports of a project, newest made first: what a link says of each."""
        files = self.report_lists.of(path)
        told = self.logs.compared(path) if files else {}
        out = []
        for file, f in files.items():
            m = REPORT_NAME.match(file)
            made, at, size = made_of(f, m)
            rev1, rev2 = m.group(2, 3) if m else (None, None)
            from_name = '' if not m else f'{rev1} to {rev2}' if rev1 else f'parent of {rev2} to {rev2}'
            out.append({'href': f'/report/{urllib.parse.quote(name)}/{urllib.parse.quote(file)}',
                        'title': (self.subjects.of(path, rev2) or rev2) if m else file,
                        'made': made, 'at': at, 'compared': told.get(file) or from_name, 'bytes': size})
        return sorted(out, key=lambda r: (r['at'], r['href']), reverse=True)

    def report_file(self, name, file):
        """The file a report link means; None for anything else: a known repo by its exact name, a file listed by report_files."""
        repos = self.folders()
        for r in self.watcher.view['rows']:
            repo = r['state'].get('repo')
            if repo and folder_of(repo).casefold() not in {k.casefold() for k in repos}:
                repos[folder_of(repo)] = repo
        return report_files(repos[name]).get(file) if name in repos else None

    def just_started(self, folder, record):
        """When the run of folder was started from this page, while it counts as starting: not yet its record, and not
        over STARTING_SECONDS ago."""
        got = self.starting.get(folder)
        if not got or time.monotonic() - got[0] > STARTING_SECONDS:
            return None
        made = st.parse_time((record or {}).get('started'))
        return None if made and made >= got[1] - datetime.timedelta(seconds=2) else got[1]

    def run_view(self, folder, path, rows, runs):
        """The report run of a project as its part shows it: running (its record, the call of its bridge), else its last
        record and why the button waits, if it does."""
        record = next((r for k, r in runs.items() if k.casefold() == folder.casefold()), None)
        live = bool(record) and reportrun.is_running(record, self.procs)
        since = self.just_started(folder, record)
        view = {'record': record, 'running': live or bool(since), 'since': st.parse_time(record['started']) if live else since,
                'doing': '', 'waits': ''}
        if live:
            bridge = next((r['state'] for r in rows if r['state'].get('pid') == record.get('bridge')), {})
            view['doing'] = statusline.operation_text(bridge['operation']) if bridge.get('operation') else str(record.get('step') or '')
            view['step'] = record.get('step')
        elif since:
            view['doing'] = 'starting'
        else:
            view['waits'] = self.waits(folder, path, rows, runs)
        return view

    def waits(self, folder, path, rows, runs):
        """Why a report run of the repo cannot start now, '' when it can: one runs or starts, or a bridge is on that repo
        (the run itself checks the TIA too, and an agent's bridge on it)."""
        for k, r in runs.items():
            if reportrun.is_running(r, self.procs) or self.just_started(k, r):
                return reportrun.going(r.get('project') or k)
        for k in self.starting:
            if self.just_started(k, None) and k not in runs:
                return reportrun.going(k)
        for r in rows:
            s = r['state']
            if not r.get('orphan') and s.get('client') != reportrun.CLIENT and st.same_path(s.get('repo'), path):
                return reportrun.BRIDGE_ON_IT
        return ''

    def start(self, name):
        """Starts a report run of the project the page names: (status, '' or why not)."""
        with self.lock:
            path = self.folders().get(name) if name and not name.startswith('_') else None
            if not path:
                return 404, 'No project of that name.'
            why = self.waits(name, path, self.watcher.view['rows'], reportrun.records(self.root))
            if why:
                return 409, why
            self.starting[name] = (time.monotonic(), datetime.datetime.now(datetime.timezone.utc))
            try:
                self.start_run(path)
            except OSError as e:
                del self.starting[name]
                return 500, f'The report run did not start: {e}'
            return 200, ''

    def agent_note(self, r):
        """The agent, when that tells something: it waits for an answer (herdr's word) or its process is gone. A person reading
        "agent running" takes it for something it did."""
        s = r['state']
        tab = (self.watcher.known.get(s.get('pid')) or {}).get('tab')
        word = self.herdr.status.get(tab)
        if word and word != 'unknown':
            return 'The agent waits for an answer.' if word == 'blocked' else ''
        claude = (s.get('claude') or {}).get('pid')
        return 'The agent is gone.' if claude and not self.procs.info(claude) else ''

    def state(self, r, calls):
        """What one bridge is in, the worst of it; what to do about it is the person's, who asks the agent."""
        s, info = r['state'], r['info']
        tia, op, last = s.get('tia'), s.get('operation'), s.get('lastOperation') or {}
        window = (tia or {}).get('window', True)
        doing = statusline.operation_text(op) if op else ''
        end = f'end process {(tia or {}).get("pid")} in Task Manager.'
        if r.get('orphan'):
            memory = statusline.memory((info or {}).get('memory'))
            return status('need', 'A TIA was left running', f'A TIA without a window was left running, holding {memory}.', f'Close it: {end}')
        if tia and not info:
            during = f' during {doing}' if doing else ''
            return status('fail', 'TIA closed', f'TIA closed or crashed{during}.', 'Ask the agent to connect again.')
        if op and statusline.prompt_of(s) and s['lastPrompt'].get('answer') not in BOX_CLOSED:
            return status('need', 'TIA asks a question', f'{TIA_ASKS}{asked_text(s["lastPrompt"])}',
                          'Answer it in TIA.' if window else f'No one can answer it: this TIA has no window. It may hang: ask the agent, or {end}')
        if op and (self.watcher.known.get(s.get('pid')) or {}).get('quiet'):
            return status('need', 'TIA has stopped working', f'TIA does nothing during {doing}.',
                          'Look in TIA for an open message box.' if window else f'It may hang: ask the agent, or {end}')
        if op:
            return status('run', doing)
        if last.get('ok') is False:
            name = last.get('name')
            reason = calls[0]['what'] if calls and calls[0]['tool'] == name else ''
            return status('fail', f'{name} failed', f'{name} failed: {reason.rstrip(".")}.' if reason else f'{name} failed.',
                          'Ask the agent what it will do about it.')
        return status('quiet', IDLE)

    def agent(self, r, now, calls):
        """What the page says of one bridge, or of a TIA without a window its bridge left."""
        s, info = r['state'], r['info']
        tia, op = s.get('tia'), s.get('operation')
        state = self.state(r, calls)
        # while no call runs: since the end of its last call, else since it started; a project's row has its last call already
        calls_nothing = not op and not r.get('orphan') and not (tia and not info)
        since = st.parse_time((s.get('lastOperation') or {}).get('ended') or s.get('started')) if calls_nothing else None
        project = s.get('project')
        tia_words = None
        if tia and info:
            cpu = f', {table.cpu(r["cpu"])} CPU' if r.get('cpu') is not None else ''
            tia_words = ('with a window' if tia.get('window', True) else 'without a window',
                         f'{statusline.memory(info.get("memory"))} memory{cpu}')
        return {'state': state, 'doing': statusline.operation_text(op) if op and not r.get('orphan') else '',
                'time': statusline.elapsed(op.get('since'), now) if op and not r.get('orphan') else '',
                'since': when_text(since, now) if since else '',
                'note': '' if r.get('orphan') else self.agent_note(r), 'ended': bool(r.get('orphan')), 'tia': tia_words, 'gone': bool(tia and not info),
                'run': s.get('client') == reportrun.CLIENT,
                'tia_project': project if project and project.casefold() != folder_of(s.get('repo')).casefold() else '',
                'prompt': '' if state['what'].startswith(TIA_ASKS) else table.prompt_text(s.get('lastPrompt'))}

    def loose_tias(self, rows):
        """The TIA processes no bridge holds: a person can run a TIA of their own, so nothing about them needs anyone."""
        held = {(r['state'].get('tia') or {}).get('pid') for r in rows}
        return [{'pid': pid, 'memory': statusline.memory((self.procs.info(pid) or {}).get('memory'))}
                for pid, (_, name) in sorted(self.procs.tree().items()) if name.lower() == TIA_EXE and pid not in held]

    def tick(self):
        """One round: what the page shows, read again. A round that fails leaves the rest as it was and says so."""
        try:
            self.watcher.round()
            now = self.watcher.view['now']
            # a TIA with a window that lost its bridge can be someone's own, with work not saved: loose_tias lists it
            rows = [r for r in self.watcher.view['rows']
                    if not (r.get('orphan') and (r['state'].get('tia') or {}).get('window', True))]
            found = self.projects(rows, previews(previews_folder(), self.procs))
            runs = reportrun.records(self.root)
            for p in found:
                p['agents'] = [self.agent(r, now, p['calls']) for r in p['rows']]
                p['run'] = self.run_view(p['name'], p['path'], rows, runs)
            found.sort(key=lambda p: RANK[worst(p)['kind']] if p['agents'] else len(RANK))     # stable: newest first in each
            free = [self.agent(r, now, []) for r in rows if not r['state'].get('repo')]
            summary, waiting = summary_html(found, free)
            self.publish({'summary': summary, 'list': list_html(found, self.root), 'pane': pane_html(found),
                          **{key: text for p in found for key, text in project_parts(p, now).items()},
                          'others': others_html(free, self.loose_tias(rows))},
                         f'({waiting}) {TITLE}' if waiting else TITLE)
        except Exception as e:     # the next round tries again
            self.publish(dict(self.latest['parts'], summary='<p class="summary fail">The agents could not be read'
                                                            f'<small>{esc(repr(e))}</small></p>'), TITLE)

    def publish(self, parts, title):
        """What a connection pushes next; unchanged while nothing on the page changes."""
        if parts != self.latest['parts'] or title != self.latest['title']:
            self.latest = {'parts': parts, 'title': title, 'updated': self.watcher.now().astimezone().strftime('%H:%M:%S')}


def status(kind, short, what='', do=''):
    """short: the words on the list; what and do: a need in full and what to do about it, in the headline."""
    return {'kind': kind, 'mark': MARKS[kind], 'short': short, 'what': what, 'do': do}


def asked_text(p):
    words = ': '.join(x for x in (p.get('caption'), p.get('text')) if x) or p.get('kind') or '?'
    return ' '.join(words.split())


def worst(p):
    """The state a project's row shows: of its agents, or of its last call."""
    if p['agents']:
        return min((a['state'] for a in p['agents']), key=lambda s: RANK[s['kind']])
    if p['calls'] and not p['calls'][0]['ok']:
        return status('past', f'Last call failed: {p["calls"][0]["tool"]}')
    return status('quiet', NO_BRIDGE)


def need_html(where, a):
    s = a['state']
    return (f'<li class="{s["kind"]}">{where} <span class="what">{s["mark"]} {esc(s["what"])}</span> '
            f'<span class="do">{esc(s["do"])}</span></li>')


def summary_html(found, free):
    """The headline: every need and what to do about it, above the list and the pane, so that nothing chosen can hide one.
    Amber when anything waits for the person, red when only failures do. Returns also how many."""
    needs = [(f'<a href="#{esc(project_hash(p["name"]))}">{esc(p["name"])}</a>', a) for p in found for a in p['agents'] if a['state']['what']]
    needs += [('<a href="#bridges">A bridge with no project</a>', a) for a in free if a['state']['what']]
    if not needs:
        return '<p class="summary">Nothing needs you</p>', 0
    cls = 'you' if any(a['state']['kind'] == 'need' for _, a in needs) else 'fail'
    head = f'{len(needs)} need{"s" if len(needs) == 1 else ""} you'
    return (f'<p class="summary {cls}">{head}</p><ul class="needs">{"".join(need_html(where, a) for where, a in needs)}</ul>', len(needs))


def project_hash(name):
    return urllib.parse.quote(name, safe='')


def list_html(found, root):
    """The list as slots: a change on one row leaves the others as they are. It changes only when the projects do."""
    if not found:
        return (f'<p class="goal">No project worked on yet. A project shows here once an agent has made a tool call on it '
                f'through TiaBridge. Projects root: {esc(root)}</p>')
    rows = ''.join(f'<a class="row" id="row-{esc(p["name"])}" href="#{esc(project_hash(p["name"]))}" data-project="{esc(p["name"])}"></a>' for p in found)
    return f'<div class="list-head"><span>Project</span><span>Last call</span></div><nav aria-label="Projects">{rows}</nav>'


def part_html(title, slot, scroll=False, top=''):
    """A part of the chosen project: its heading and its slot; top, a slot of its own above the scrolled one."""
    keep = f' class="body scroll" data-scroll tabindex="0" role="region" aria-label="{esc(title)}"' if scroll else ' class="body"'
    above = f'<div id="{esc(top)}" class="run-slot"></div>' if top else ''
    return f'<section class="part"><h3>{esc(title)}</h3>{above}<div id="{esc(slot)}"{keep}></div></section>'


def optional_part_html(slot):
    """A part of the chosen project that shows only while it has something to say: the slot is the part, heading and
    all, and an empty one hides (dashboard.css, :empty)."""
    return f'<section class="part optional" id="{esc(slot)}"></section>'


def pane_html(found):
    """The chosen project, each in its slots and hidden until the page's address names it."""
    sections = ''.join(
        f'<section class="chosen" id="project-{esc(p["name"])}" data-project="{esc(p["name"])}" hidden>'
        '<a class="back" href="#">All projects</a>'
        f'<h2 tabindex="-1">{esc(p["name"])}</h2>'
        f'{part_html("Agent is calling", "now-" + p["name"])}{part_html("TIA", "tia-" + p["name"])}'
        f'{optional_part_html("preview-" + p["name"])}'
        f'{part_html("Change reports", "reports-" + p["name"], True, "run-" + p["name"])}'
        f'{part_html("History", "history-" + p["name"], True)}</section>'
        for p in found)
    return f'<section class="nothing-chosen" data-project=""><p class="goal">Choose a project to see what happens on it.</p></section>{sections}'


def state_html(s, more=''):
    return f'<span class="state {s["kind"]}"><span class="mark">{s["mark"]}</span> {esc(s["short"])}{esc(more)}</span>'


def when_text(at, now):
    """hh:mm on this machine's clock when today, else the date; a time without a zone is one of this machine."""
    at = at.astimezone()
    return at.strftime('%H:%M') if at.date() == now.astimezone().date() else at.strftime('%Y-%m-%d')


def row_html(p, now):
    """A row: the name, when its last call was, the state. A call that runs shows with its time."""
    s = worst(p)
    running = next((a for a in p['agents'] if a['state'] is s), None)
    time_ = f' {running["time"]}' if running and running['time'] and s['kind'] == 'run' else ''
    more = f'{time_} ({len(p["agents"])} bridges)' if len(p['agents']) > 1 else time_
    when = when_text(p['calls'][0]['at'], now) if p['calls'] else ''
    return f'<span class="name">{esc(p["name"])}</span><span class="when">{esc(when)}</span>{state_html(s, more)}'


def label(p, i):
    """Whose a line is: the dashboard's report run, or which agent's when there are two."""
    if p['agents'][i].get('run'):
        return 'Report run: '
    return f'Agent {i + 1}: ' if len(p['agents']) > 1 else ''


def now_html(p):
    if not p['agents']:
        return '<p class="plain">No bridge on this project.</p>'
    out = []
    for i, a in enumerate(p['agents']):
        who = label(p, i)
        if a['ended']:
            out.append(f'<p class="plain">{esc(who + "has ended." if who else "The agent has ended.")}</p>')
        elif a['doing']:
            out.append(f'<p class="doing">{esc(who)}{esc(a["doing"])} <span class="time">{esc(a["time"])}</span></p>')
        else:
            words = f'calling nothing since {a["since"]}' if a['since'] else 'calling nothing right now'
            out.append(f'<p class="plain">{esc(who + words if who else words[0].upper() + words[1:])}</p>')
        if a['note']:
            out.append(f'<p class="plain">{esc(a["note"])}</p>')
    return ''.join(out)


def tia_lines(a, who=''):
    """A TIA in plain words; who: which agent's, when there are two."""
    def said(text):
        return f'{who}{text}' if who else text[0].upper() + text[1:]
    if a['gone']:
        out = [f'<p class="plain">{esc(said("TIA has closed."))}</p>']
    elif a['tia']:
        out = [f'<p>{esc(said(a["tia"][0]))}</p><p class="plain">{esc(a["tia"][1])}</p>']
    else:
        out = [f'<p class="plain">{esc(said("holds no TIA."))}</p>']
    if a['tia_project']:
        out.append(f'<p class="plain">Project in TIA: {esc(a["tia_project"])}</p>')
    if a['prompt']:
        out.append(f'<p class="plain">It last asked: {esc(a["prompt"])}</p>')
    return ''.join(out)


def tia_html(p):
    if not p['agents']:
        return '<p class="plain">No bridge holds a TIA for it.</p>'
    return ''.join(tia_lines(a, label(p, i)) for i, a in enumerate(p['agents']))


def project_parts(p, now):
    """What each slot of a project holds. Each changes by itself, so that a scrolled area stays where it is."""
    n = p['name']
    return {f'row-{n}': row_html(p, now), f'now-{n}': now_html(p), f'tia-{n}': tia_html(p),
            f'preview-{n}': previews_html(p['previews'], now),
            f'run-{n}': run_html(p['run'], n, now),
            f'reports-{n}': ''.join(report_html(r) for r in p['reports']) or '<p class="plain">No change report yet.</p>',
            f'history-{n}': history_html(p)}


def others_html(free, loose):
    """Bridges with no project, each its own line, and the TIAs no bridge holds; a heading only over a line."""
    rows = []
    for a in free:
        time_ = (f' {a["time"]}' if a['time'] and a['state']['kind'] == 'run'
                 else f' since {a["since"]}' if a['since'] and a['state']['kind'] == 'quiet' else '')
        note = f'<p class="plain">{esc(a["note"])}</p>' if a['note'] else ''
        rows.append(f'<div class="other">{state_html(a["state"], time_)}{tia_lines(a)}{note}</div>')
    out = f'<section id="bridges"><h2>Bridges with no project</h2>{"".join(rows)}</section>' if rows else ''
    if loose:
        tias = ''.join(f'<div class="other plain">Process {esc(t["pid"])}, {esc(t["memory"])} memory</div>' for t in loose)
        out += f'<section><h2>TIA with no bridge</h2><p class="goal">Yours, or left by an agent that ended.</p>{tias}</section>'
    return out


def call_html(c):
    cls = 'call' + (' fail' if not c['ok'] else ' quiet' if c['tool'] in QUIET_TOOLS else '')
    mark = f'{MARKS["fail"]} ' if not c['ok'] else ''
    ms = duration(c['ms']) if c['ms'] is not None else ''
    what = f' {esc(c["what"])}' if c['what'] else ''
    return (f'<div class="{cls}"><span class="at">{c["at"].strftime("%H:%M:%S")}</span>'
            f'<span class="what">{mark}<span class="tool">{esc(c["tool"])}</span>{what}</span><span class="ms">{ms}</span></div>')


def history_html(p):
    out, day = [], None
    if p['total'] > len(p['calls']):
        out.append(f'<p class="goal">Newest {len(p["calls"])} of {p["total"]} calls. All of them: '
                   f'{esc(os.path.join(p["path"], "logs"))}</p>')
    for c in p['calls']:
        if c['at'].date() != day:
            day = c['at'].date()
            out.append(f'<div class="day">{day.isoformat()}</div>')
        out.append(call_html(c))
    return ''.join(out) or '<p class="goal">No call yet.</p>'


def run_html(view, name, now):
    """The report run of a project: while it runs, what its bridge calls and since when; else the button, why it waits if
    it does, and how the last run ended."""
    if view['running']:
        time_ = statusline.elapsed(view['since'].isoformat(), now) if view['since'] else ''
        out = [f'<p class="run"><b>{MARKS["run"]} Making a change report: {esc(view["doing"])}</b> <span class="time">{esc(time_)}</span></p>']
        if view.get('step') == 'connect':
            out.append('<p class="run plain">TIA may ask to allow access: answer it in TIA.</p>')
        out.append('<p class="run plain">Leave TIA alone until it ends: an edit made during the export may land in it half.</p>')
        return ''.join(out)
    off = ' disabled' if view['waits'] else ''
    out = [f'<p><button class="act" type="button" data-report-run="{esc(name)}"{off}>{BUTTON}</button></p>',
           f'<p class="run-said run plain" role="status">{esc(view["waits"])}</p>']
    r = view['record']
    if r and r.get('ended'):
        ended, started = st.parse_time(r['ended']), st.parse_time(r.get('started'))
        when = when_text(ended, now) if ended else ''
        text = str(r.get('text') or '')
        if r.get('outcome') == 'done' and text.startswith('Done: ') and ended and started:
            text = f'Done, {statusline.elapsed(started.isoformat(), ended)}: {text[len("Done: "):]}'
        fail = r.get('outcome') in ('failed', 'refused')
        out.append(f'<p class="run{" fail" if fail else " plain"}">{MARKS["fail"] + " " if fail else ""}{esc(when)} {esc(text)}</p>')
    elif r:
        out.append(f'<p class="run fail">{MARKS["fail"]} The report run ended without a word: its process is gone.</p>')
    return ''.join(out)


def report_html(r):
    size = '' if r['bytes'] is None else f'{max(1, round(r["bytes"] / 1024))} KB'
    what = f'<div class="facts">{esc(r["compared"])}</div>' if r['compared'] else ''
    return (f'<div class="report"><span class="at">{esc(r["made"])}</span><span class="what">'
            f'<a href="{esc(r["href"])}" target="_blank" rel="noopener">{esc(r["title"])}</a>{what}</span>'
            f'<span class="ms">{size}</span></div>')


def previews_html(running, now):
    """The HMI preview part, heading and all, while a preview runs; nothing, and the part hides, while none does."""
    if not running:
        return ''
    return f'<h3>HMI preview</h3><div class="body">{"".join(preview_html(preview, now) for preview in running)}</div>'


def preview_html(preview, now):
    """A running HMI preview: a link per HMI device it serves, one to the preview when the repo has one device."""
    url = preview['url']
    links = ([(url + '?' + urllib.parse.urlencode({'device': d}, quote_via=urllib.parse.quote), d) for d in preview['devices']]
             or [(url, url)])
    since = f'since {when_text(preview["started"], now)}' if preview['started'] else ''
    facts = f'<div class="facts">{esc(preview["url"])}</div>' if preview['devices'] else ''
    return ''.join(f'<div class="report"><span class="at">{esc(since)}</span><span class="what">'
                   f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(text)}</a>{facts}</span></div>'
                   for href, text in links)


def page(d):
    """The page: its slots stay empty until the first update, which comes when the connection opens."""
    head = live.head(d.latest['title']).replace('</head>', f'<meta name="report-token" content="{esc(d.token)}"></head>', 1)
    return (head + f'<body><main class="tia"><header class="top"><h1>{TITLE}</h1>'
            '<span class="live" id="live"></span></header><div id="summary"></div><div class="columns"><div class="side"><div id="list"></div>'
            f'<div id="others"></div></div><div id="pane"></div></div></main><script>{CHOSEN}{REPORT_RUN}dashboardBoard(showChosen);</script></body></html>')


def make_server(d, port):
    """The server of this page, on this machine only. Its handler knows the page, its events, the assets of the live core
    and report links, and nothing else: live.Handler would serve the working folder to a GET or HEAD it passes on."""

    class Handler(live.Handler):
        def send_head(self):
            self.send_error(404)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            parts = url.path.split('/')
            if url.path == '/':
                return self.send_text(200, page(d), 'text/html; charset=utf-8')
            if url.path == '/events' and url.query == 'start=1':
                return self.stream(lambda: d.latest)
            if self.send_asset(url.path):
                return None
            if len(parts) == 4 and parts[1] == 'report':
                f = d.report_file(urllib.parse.unquote(parts[2]), urllib.parse.unquote(parts[3]))
                if f:
                    return self.send_body(200, f.read_bytes(), 'text/html; charset=utf-8')
            return self.send_text(404, 'Not found.', 'text/plain; charset=utf-8')

        def do_POST(self):
            """The one request that writes: start a report run. Only the dashboard's own page sends it: JSON (which a form
            of another site cannot send), the page's token, and the page's own address as Origin. The Host check before
            it (live.Handler) keeps out a site that points its name at this machine."""
            if urllib.parse.urlparse(self.path).path != '/api/report-run':
                return self.send_error(501)
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                return self.reply(415, 'JSON only.')
            token = self.headers.get('X-Report-Token', '')
            if not hmac.compare_digest(token.encode('utf-8', 'replace'), d.token.encode('utf-8')) \
                    or self.headers.get('Origin') != f'http://{self.headers.get("Host")}':
                return self.reply(403, 'Not from the dashboard\'s own page.')
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 4096)) or b'{}')
                name = body.get('project') if isinstance(body, dict) else None
            except ValueError:
                name = None
            code, why = d.start(name if isinstance(name, str) else '')
            return self.reply(code, why)

        def reply(self, code, why):
            self.send_text(code, json.dumps({'ok': True} if code == 200 else {'ok': False, 'error': why}), 'application/json')

    return live.Server(('127.0.0.1', port), Handler)


def rounds(tick, every, clock=time.monotonic, sleep=time.sleep):
    """Calls tick every `every` seconds, one round at a time: a round that runs over skips the starts it missed, so rounds
    never queue up behind a slow one."""
    due = clock()
    while True:
        due += every
        late = clock() - due
        if late > 0:
            due += math.ceil(late / every) * every
        sleep(max(0.0, due - clock()))
        tick()


def guarded(start):
    return tray.guarded(TITLE, start)


def main(a):
    from TiaAgentStatus.procs import WinProcesses
    root = a.root or st.projects_root()
    d = Dashboard(WinProcesses(), ReadOnlyHerdr() if shutil.which('herdr') else NoHerdr(), root, a.quiet_minutes)
    try:
        server = make_server(d, a.port)
    except OSError as e:
        sys.exit(f'Port {a.port} is taken ({e}): another dashboard runs there, or use --port.')
    d.tick()
    threading.Thread(target=rounds, args=(d.tick, a.every), daemon=True).start()
    print(f'http://127.0.0.1:{a.port}/ on {root}', flush=True)
    tray.serve(server, tray.TIA_NAME, f'http://127.0.0.1:{a.port}/', tray.TIA_ICON, tray.TIA_ID)
    return 0
