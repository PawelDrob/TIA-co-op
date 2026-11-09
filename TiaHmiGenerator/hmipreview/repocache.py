"""RepoCache: the loaded repo and its findings, kept while the repo on disk is unchanged.

Loading and validating a real project (project B: 71 screens, 1 MB documents) takes about 0.6 s; the preview asked
for it several times per screen switch. The cache is keyed by a fingerprint of everything the model and the rules
read: (path, mtime, size) of every file under hmi/ and library/, tiabridge.json, and the git state the staleness
rule reads (HEAD, the branch ref, packed-refs). Taking the fingerprint is a directory walk with stat calls (a few
milliseconds), so every request still answers for the repo as it is on disk.
"""
import os
import threading

from . import diff, model
from .validator import check_repo

TREES = ('hmi', 'library')
FILES = ('tiabridge.json',)


def _stat(full):
    try:
        st = os.stat(full)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _git_dirs(repo_path):
    """(git dir, common dir) of the repo, or (None, None). A worktree's .git is a file naming its git dir."""
    dot = os.path.join(repo_path, '.git')
    if os.path.isdir(dot):
        return dot, dot
    try:
        with open(dot, encoding='utf-8') as f:
            line = f.read().strip()
    except OSError:
        return None, None
    if not line.startswith('gitdir:'):
        return None, None
    gitdir = os.path.normpath(os.path.join(repo_path, line[len('gitdir:'):].strip()))
    common = gitdir
    try:
        with open(os.path.join(gitdir, 'commondir'), encoding='utf-8') as f:
            common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
    except OSError:
        pass
    return gitdir, common


def git_state(repo_path):
    """What changes when a commit is made: HEAD, the ref it names, packed-refs (contents of HEAD, stats)."""
    gitdir, common = _git_dirs(repo_path)
    if gitdir is None:
        return None
    try:
        with open(os.path.join(gitdir, 'HEAD'), encoding='utf-8') as f:
            head = f.read().strip()
    except OSError:
        return None
    out = [head]
    if head.startswith('ref:'):
        ref = head[4:].strip().split('/')
        out += [_stat(os.path.join(gitdir, *ref)), _stat(os.path.join(common, *ref))]
    out.append(_stat(os.path.join(common, 'packed-refs')))
    return tuple(out)


def fingerprint(repo_path):
    """Hashable state of every file the model and the rules read."""
    items = []
    for top in TREES:
        for dirpath, dirnames, filenames in os.walk(os.path.join(repo_path, top)):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                items.append((os.path.relpath(full, repo_path), _stat(full)))
    for rel in FILES:
        items.append((rel, _stat(os.path.join(repo_path, rel))))
    items.append(('.git', git_state(repo_path)))
    return tuple(items)


class RepoCache:
    """repo() and findings() of the repo at repo_path, recomputed only when its fingerprint changed."""

    def __init__(self, repo_path, device=None):
        self.repo_path = os.path.abspath(repo_path)
        self.device = device          # the HMI device (model.select_device), None: hmiDevice or the only one
        self._lock = threading.Lock()
        self._key = None
        self._repo = None
        self._findings = None
        self._states = {}

    def _current(self):
        key = fingerprint(self.repo_path)
        if key != self._key:
            self._key, self._repo, self._findings = key, model.load(self.repo_path, device=self.device), None
            self._states = {}
        return key

    def repo(self):
        with self._lock:
            self._current()
            return self._repo

    def findings(self):
        """(repo, findings) of the same state of the repo."""
        with self._lock:
            self._current()
            if self._findings is None:
                self._findings = check_repo(self._repo)
            return self._repo, self._findings

    def states(self, against):
        """(repo, diff.states(repo, against)) of the same state of the repo: the project tree's change marks."""
        with self._lock:
            self._current()
            if against not in self._states:
                self._states[against] = diff.states(self._repo, against)
            return self._repo, self._states[against]
