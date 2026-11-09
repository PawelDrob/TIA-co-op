"""A process table for the tests: the same two methods as procs.WinProcesses."""
import datetime
import json
import os
import tempfile

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 30, 14, 0, 0, tzinfo=UTC)


class FakeProcesses:
    def __init__(self):
        self.procs = {}   # pid -> {parent, name, created, cpu, memory}

    def add(self, pid, parent=0, name='x.exe', created=None, cpu=0.0, memory=None):
        self.procs[pid] = {'parent': parent, 'name': name, 'created': created or NOW - datetime.timedelta(hours=1),
                           'cpu': cpu, 'memory': memory}
        return self

    def kill(self, pid):
        self.procs.pop(pid, None)

    def tree(self):
        return {pid: (p['parent'], p['name']) for pid, p in self.procs.items()}

    def info(self, pid):
        p = self.procs.get(pid)
        return {'created': p['created'], 'cpu': p['cpu'], 'memory': p['memory']} if p else None


def tempdir(test):
    """A temporary folder removed after the test, which fails if it cannot go."""
    folder = tempfile.TemporaryDirectory(prefix='agent-status-test-')      # it deletes git's read-only files, rmtree does not
    test.addCleanup(folder.cleanup)
    return folder.name


def iso(t):
    return t.isoformat(timespec='milliseconds')


def state(pid, claude, project='zzPlant', tia=None, window=True, operation=None, started=None, **more):
    """A state file as TiaBridge writes it."""
    s = {'v': 1, 'pid': pid, 'client': 'mcp', 'started': iso(started or NOW - datetime.timedelta(minutes=30)),
         'updated': iso(NOW), 'session': None, 'claude': {'pid': claude, 'from': 'ancestor'}, 'herdr': None,
         'project': project, 'repo': None, 'boundSince': None,
         'tia': {'pid': tia, 'window': window} if tia else None, 'operation': operation,
         'lastOperation': None, 'lastPrompt': None}
    s.update(more)
    return s


def write(directory, s):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{s['pid']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(s, f)
    return path
