"""A report run of the TIA dashboard: the change report of a project as the user's TIA holds it, made without an agent
(docs\\adr\\0004-the-tia-dashboard-starts-a-report-run.md). The dashboard's button starts it as a process of its own, and the
page only reads what it writes. It starts TiaBridge in its report-run mode (TiaBridge.ps1 -ReportRun: tia_status, connect,
full_export and change_report, no session archive) and calls those tools as an agent does, with a git commit of the export
between: the bridge's own export, logs and state file.

Its record, <projectsRoot>\\_bridge\\report-runs\\<repo folder>.json, says what it does and how it ended; it is written
before the run looks for a bridge on the same TIA or repo, and an agent's bridge refuses that TIA and repo while the
record's process runs and the record has not ended (TiaBridge\\Tools\\Session.ps1). Two programs on one TIA have hung it.

Nothing is committed when the export did not hold the whole project: the repo goes back to its last commit, the logs of the
run's calls kept, so a change no export reached is never in a report as no change.
"""
import datetime
import json
import os
import subprocess
import sys

try:
    import msvcrt
except ImportError:     # not Windows: the tests only
    msvcrt = None
    import fcntl

from TiaAgentStatus import state as st
from TiaAgentStatus import watch

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
BRIDGE_SCRIPT = os.path.join(TOOLS, 'TiaBridge', 'TiaBridge.ps1')
POWERSHELL = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
# Every name git reads a repo from, as git rev-parse --local-env-vars lists them (a test holds this list to git's).
# Left by a parent, git prefers them to -C: it would act on the parent's repo.
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')
LOGS = 'logs'               # the bridge's logs of its calls: they go with the next commit, as after an agent
NAMED = 5                   # files not committed named in a refusal
FAILED_NAMED = 3            # objects that did not export named in a failure
CLIENT = 'report-run'       # the client of a report run's bridge in its state file (TiaBridge\State.ps1)
BRIDGE_ON_IT = 'Not now: a bridge is connected to this TIA.'
PUT_BACK = 'Nothing was committed; the repo is as it was.'


def going(project):
    return f'Not now: a report run of {project} is going on.'


def git_env():
    """This process's environment without a parent git's context, which git would prefer to -C."""
    return {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}


def runs_dir(root):
    return os.path.join(root, '_bridge', 'report-runs')


def record_path(root, folder):
    return os.path.join(runs_dir(root), folder + '.json')


def read_record(root, folder):
    try:
        with open(record_path(root, folder), encoding='utf-8-sig') as f:
            r = json.load(f)
        return r if isinstance(r, dict) else None
    except (OSError, ValueError):
        return None


def records(root):
    """{repo folder: record} of every record that reads."""
    try:
        names = sorted(n for n in os.listdir(runs_dir(root)) if n.endswith('.json') and n != 'settings.json')
    except OSError:
        return {}
    out = {}
    for n in names:
        r = read_record(root, n[:-5])
        if r:
            out[n[:-5]] = r
    return out


def is_running(r, procs):
    """A record whose run still runs: not ended, and its process alive and not started after the record (a pid taken
    again), or its bridge alive and started after it: a run killed leaves its bridge in the call it is in, on the TIA."""
    if r.get('ended') or not isinstance(r.get('pid'), int):
        return False
    if st.is_live(r, procs):
        return True
    bridge = procs.info(r['bridge']) if isinstance(r.get('bridge'), int) else None
    started = st.parse_time(r.get('started'))
    return bool(bridge) and started is not None and bridge['created'] >= started - st.REUSE_SLACK


def hold(root, folder):
    """This process's hold on the runs of the repo folder, an open file Windows keeps locked, or None while another
    process has it: two dashboards' runs of one repo started at the same moment, between their checks and their records.
    Windows lets it go with the process, so a run killed leaves none; its bridge left running counts by the record."""
    os.makedirs(runs_dir(root), exist_ok=True)
    f = open(os.path.join(runs_dir(root), folder + '.lock'), 'a+b')
    try:
        f.seek(0)
        if msvcrt:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def now_text():
    return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')


class Record:
    """The record of this run, written whole each time (temp file and rename: a reader never sees half of it)."""

    def __init__(self, root, folder, **fields):
        self.path = record_path(root, folder)
        self.data = {'v': 1, 'started': now_text(), 'ended': None, 'step': 'checks', 'outcome': None, 'text': '', **fields}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.write()

    def write(self, **fields):
        self.data.update(fields)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)


class Stop(Exception):
    """The run ends here: outcome and the words the page shows."""

    def __init__(self, outcome, text):
        super().__init__(text)
        self.outcome, self.text = outcome, text


def git(repo, *args, check=True):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=git_env(), creationflags=watch.NO_WINDOW)
    if check and r.returncode:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()}")
    return r


def uncommitted(repo):
    """The files of the repo git has no commit of as they are (untracked included, ignored not), the bridge's logs aside."""
    out = git(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames', '--', '.', f':(exclude){LOGS}').stdout
    return sorted(e[3:] for e in out.split('\0') if len(e) > 3)


def undo_bookkeeping(repo):
    """What connect wrote of its own in a clean repo, its time in tiabridge.json among it, back as committed: the commit is
    the export's, and a TIA with no change makes none. .gitignore stays: lines connect adds there keep the bridge's own
    files out of git."""
    changed = git(repo, 'diff', '--name-only', '-z', 'HEAD', '--', '.', f':(exclude){LOGS}', ':(exclude).gitignore').stdout
    paths = [p for p in changed.split('\0') if p]
    if paths:
        git(repo, 'checkout', '-q', 'HEAD', '--', *paths)


def put_back(repo):
    """The repo as at its last commit, the logs of the run's calls kept: it held nothing else before the run."""
    git(repo, 'reset', '-q', '--hard', 'HEAD')
    git(repo, 'clean', '-fdq', '-e', f'/{LOGS}/')


def reason(r):
    """Why a bridge call failed, in TIA's words where it gives them."""
    if not isinstance(r, dict):
        return 'no answer'
    for k in ('refused', 'stopped', 'note', 'gitError'):
        if isinstance(r.get(k), str) and r[k]:
            return r[k]
    e = r.get('error')
    if isinstance(e, dict) and e.get('message'):
        return f"{e.get('type') or 'error'}: {e['message']}" if e.get('type') else e['message']
    return 'it failed'


def full_result(repo, r):
    """A tool's result in full: the log it names, when its answer was shortened."""
    log = r.get('log') if isinstance(r, dict) else None
    if isinstance(log, str) and r.get('truncated'):
        try:
            with open(os.path.join(repo, log), encoding='utf-8-sig') as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return r


def export_problem(r):
    """Why an export does not hold the whole project as TIA has it, or '': then it may be committed."""
    if not isinstance(r, dict):
        return 'no answer'
    if r.get('stopped') or r.get('error') or r.get('refused'):
        return reason(r)
    failed = [f for f in r.get('failed') or [] if isinstance(f, str)]
    if failed:
        more = f' (+{len(failed) - FAILED_NAMED} more)' if len(failed) > FAILED_NAMED else ''
        n = len(failed)
        return f"{n} object{'s' if n != 1 else ''} did not export: {'; '.join(failed[:FAILED_NAMED])}{more}"
    if r.get('gitError'):
        return r['gitError']
    if r.get('removeErrors'):
        return 'files of objects no longer in TIA could not be removed: ' + '; '.join(map(str, r['removeErrors'][:FAILED_NAMED]))
    if r.get('keptRepos'):
        return 'git repos stand in the export folders: ' + ', '.join(map(str, r['keptRepos']))
    if r.get('keptUncommitted'):
        return 'files not committed stand in the export folders: ' + ', '.join(map(str, r['keptUncommitted'][:NAMED]))
    if r.get('ok') is False:
        return reason(r)
    return ''


def bridge_on(root, repo, tia, procs, mine):
    """A live bridge but this run's on that TIA or that repo: what an agent's bridge has written in its state file."""
    for s in st.live_states(st.sessions_dir(root), procs):
        if s.get('pid') == mine:
            continue
        if (tia and (s.get('tia') or {}).get('pid') == tia) or st.same_path(s.get('repo'), repo):
            return s
    return None


def other_run(root, folder, procs, pid):
    """The words for a report run but this one that runs, '' when none does."""
    for other, r in records(root).items():
        if other.casefold() != folder.casefold() and r.get('pid') != pid and is_running(r, procs):
            return going(r.get('project') or other)
    return ''


def folder_of(repo):
    return os.path.basename(os.path.normpath(repo))


def run(repo, root, start_bridge, procs, pid=None):
    """One report run of the project of repo; how it ended is in its record. start_bridge: the bridge to call, started.
    A run of the same repo that runs, or holds it (hold), keeps its record; a run of another is looked for once this
    one's record stands, so two that start at once both refuse."""
    folder = folder_of(repo)
    held = hold(root, folder)
    if not held:
        return {'outcome': 'refused', 'text': going((read_record(root, folder) or {}).get('project') or folder)}
    try:
        return run_held(repo, root, start_bridge, procs, pid)
    finally:
        held.close()


def run_held(repo, root, start_bridge, procs, pid):
    folder = folder_of(repo)
    pid = pid or os.getpid()
    mine = read_record(root, folder)
    if mine and mine.get('pid') != pid and is_running(mine, procs):
        return {'outcome': 'refused', 'text': going(mine.get('project') or folder)}
    try:
        with open(os.path.join(repo, 'tiabridge.json'), encoding='utf-8-sig') as f:
            path = json.load(f).get('projectPath')
    except (OSError, ValueError, AttributeError):
        path = None
    rec = Record(root, folder, pid=pid, project=folder, repo=repo, projectPath=path, tia=None, bridge=None)
    bridge = None
    try:
        if not isinstance(path, str) or not path:
            raise Stop('refused', f'Not run: {folder} records no TIA project. The button works on a project an agent has connected to.')
        rec.write(project=os.path.splitext(os.path.basename(path))[0])
        why = other_run(root, folder, procs, pid)
        if why:
            raise Stop('refused', why)
        if bridge_on(root, repo, None, procs, None):
            raise Stop('refused', BRIDGE_ON_IT)
        dirty = uncommitted(repo)
        if dirty:
            more = f' (+{len(dirty) - NAMED} more)' if len(dirty) > NAMED else ''
            raise Stop('refused', f"Not run: the repo has files not committed: {', '.join(dirty[:NAMED])}{more}. "
                                  'Commit or remove them first: the report would hold them.')
        rec.write(step='tia_status')
        bridge = start_bridge()
        rec.write(bridge=bridge.pid)
        r = bridge.call('tia_status', {})
        if not r.get('ok'):
            raise Stop('failed', f'Failed at tia_status: {reason(r)}')
        holding = [p for p in r.get('processes') or [] if isinstance(p, dict) and st.same_path(p.get('path'), path)]
        if not holding:
            raise Stop('refused', f'Not now: {path} is not open in TIA. Open it in TIA, then press again.')
        tia = holding[0]
        if tia.get('mode') == 'WithoutUserInterface':
            raise Stop('refused', f'Not now: {path} is open in a TIA without a window, a session of an agent.')
        rec.write(tia=tia.get('processId'))
        if bridge_on(root, repo, tia.get('processId'), procs, bridge.pid):
            raise Stop('refused', BRIDGE_ON_IT)
        rec.write(step='connect')
        r = bridge.call('connect', {'project': path, 'repo': folder})
        if not r.get('ok'):
            why = reason(r)
            raise Stop('refused', why) if why.startswith('Not now:') else Stop('failed', f'Failed at connect: {why}')
        undo_bookkeeping(repo)
        unsaved = bool(r.get('unsavedChanges'))
        rec.write(step='full_export', unsaved=unsaved)
        problem = export_problem(full_result(repo, bridge.call('full_export', {})))
        if problem:
            raise Stop('failed', f'Failed at full_export: {problem.rstrip(".")}. {PUT_BACK}')
        if not uncommitted(repo):
            raise Stop('same', 'TIA holds what the last commit holds: nothing to report.')
        rec.write(step='commit')
        title = f"TIA dashboard: {rec.data['project']} as TIA holds it{', unsaved edits included' if unsaved else ''}"
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', title)
        sha = git(repo, 'rev-parse', '--short', 'HEAD').stdout.strip()
        rec.write(step='change_report', commit=sha)
        r = bridge.call('change_report', {'rev2': sha, 'title': title})
        if not r.get('ok'):
            raise Stop('failed', f'Committed {sha}, but the change report failed: {reason(r)}')
        page = str(r.get('page') or '').replace('\\', '/').rsplit('/', 1)[-1]
        rec.write(page=page)
        raise Stop('done', f"Done: TIA as it stood{', unsaved edits included' if unsaved else ''}. Committed {sha}.")
    except Stop as s:
        outcome, text = s.outcome, s.text
    except Exception as e:     # the page says it, whatever it was
        outcome, text = 'failed', f"Failed at {rec.data['step']}: {str(e).rstrip('.')}."
    finally:
        if bridge:
            try:
                bridge.close()
            except Exception:
                pass
    # a connect, export or commit that did not end as a commit leaves nothing: the repo was clean but for logs\ before
    # connect, which writes to it (tiabridge.json, the docs it makes when missing) before it can still fail
    if outcome == 'failed' and rec.data['step'] in ('connect', 'full_export', 'commit'):
        try:
            put_back(repo)
            text = text if text.endswith(PUT_BACK) else f'{text} {PUT_BACK}'
        except Exception as e:
            text = f'{text} The repo could not be put back to its last commit: {e}'
    rec.write(outcome=outcome, text=text, ended=now_text())
    return rec.data


class McpBridge:
    """TiaBridge.ps1 -ReportRun as a process of this run, called over its standard input and output as an MCP client
    does. Its stderr goes to <projectsRoot>\\_bridge\\report-runs\\<repo folder>.log."""

    def __init__(self, root, folder, extra=()):
        os.makedirs(runs_dir(root), exist_ok=True)
        settings = os.path.join(runs_dir(root), 'settings.json')
        with open(settings, 'w', encoding='utf-8') as f:      # the bridge's settings, with this run's projects root
            json.dump({**st.bridge_settings(), 'projectsRoot': root}, f)
        self.err = open(os.path.join(runs_dir(root), folder + '.log'), 'w', encoding='utf-8')
        env = git_env()
        self.p = subprocess.Popen([POWERSHELL, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', BRIDGE_SCRIPT,
                                   '-ReportRun', '-SettingsPath', settings, *extra],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err, env=env,
                                  creationflags=watch.NO_WINDOW)
        self.pid, self.n = self.p.pid, 0
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'tia-dashboard-report-run', 'version': '1'}})
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def send(self, msg):
        self.p.stdin.write((json.dumps(msg) + '\n').encode('utf-8'))
        self.p.stdin.flush()

    def request(self, method, params):
        self.n += 1
        self.send({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params})
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f'the bridge ended (exit {self.p.wait()}); its log: {self.err.name}')
        reply = json.loads(line)
        if 'error' in reply:
            raise RuntimeError(f"the bridge answered {reply['error'].get('message')}")
        return reply['result']

    def call(self, name, args):
        result = self.request('tools/call', {'name': name, 'arguments': args})
        return json.loads(result['content'][0]['text'])

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(60)
        except subprocess.TimeoutExpired:
            self.p.kill()
        finally:
            self.p.stdout.close()
            self.err.close()


def main(a):
    from TiaAgentStatus.procs import WinProcesses
    root = a.root or st.projects_root()
    folder = folder_of(a.repo)
    r = run(a.repo, root, lambda: McpBridge(root, folder), WinProcesses())
    print(r.get('text', ''), flush=True)
    return 0 if r.get('outcome') in ('done', 'same') else 1


if __name__ == '__main__':
    sys.exit('Run it as: python -m TiaAgentStatus report-run --repo <repo>')
