"""A git repo as the input of a comparison: its commits, and whether two of them can be compared, in plain words. Only
reads the repo, needs no TIA. The window uses it too, to fill its pickers."""
import os
import subprocess
from dataclasses import dataclass

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
GIT_CONTEXT = ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR')    # a parent's: git prefers them to -C
ALL_COMMITS = ['--branches', '--tags', '--remotes']
MAYBE_EXPORTS = ['*.s7dcl', '*.xml']  # at any depth: a quick look over the whole history; of two commits the report itself says


@dataclass
class Commit:
    hash: str
    short: str
    date: str
    subject: str


class _GitFailed(Exception):
    def __init__(self, text):
        super().__init__(text)
        self.text = text


def _git(folder, *args):
    env = {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
    try:
        r = subprocess.run(['git', '-C', folder, '-c', 'log.showSignature=false'] + list(args), capture_output=True,
                           stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW)
    except OSError as ex:
        raise _GitFailed('Git could not be started (%s). Install Git and put it on the PATH.' % (ex.strerror or ex))
    if r.returncode:
        raise _GitFailed(r.stderr.decode('utf-8', 'replace').strip() or 'exit code %d' % r.returncode)
    return r.stdout.decode('utf-8', 'replace')


def _unreadable(folder, failure):
    return '%s could not be read as a git repo (%s).' % (folder, failure)


def _repo_problem(folder):
    """Why folder is not the top of a git repo, in plain words; else None."""
    if not os.path.isdir(folder):
        return '%s was not found.' % folder
    try:
        lines = _git(folder, 'rev-parse', '--show-toplevel', '--show-prefix').splitlines()
    except _GitFailed as ex:
        if 'not a git repository' in ex.text:
            return '%s is no git repo.' % folder
        if 'work tree' in ex.text:      # a bare repo, or the .git folder itself
            return '%s is not the folder of a git repo: choose the folder that holds its .git folder.' % folder
        return ex.text if ex.text.startswith('Git could not') else _unreadable(folder, ex.text)
    if len(lines) > 1 and lines[1]:     # a parent's commits are not this folder's
        return '%s is a folder inside the git repo %s; choose the repo.' % (folder, os.path.normpath(lines[0]))
    return None


def _refs(folder):
    """What to list: every branch, tag and remote branch, and HEAD when it has a commit (not yet in an empty repo)."""
    try:
        _git(folder, 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}')
        return ALL_COMMITS + ['HEAD']
    except _GitFailed:
        return ALL_COMMITS


def _exports_problem(folder, refs):
    if not _git(folder, 'log', '-1', '--format=%h', *refs, '--', *MAYBE_EXPORTS).strip():
        return '%s holds no exports: none of its commits has a .s7dcl or .xml export.' % folder
    return None


def read_commits(folder):
    """(the commits of the repo, newest first; None) or ([], why they cannot be compared, in plain words)."""
    try:
        problem = _repo_problem(folder)
        if problem:
            return [], problem
        refs = _refs(folder)
        out = _git(folder, 'log', '-z', '--date-order', '--encoding=UTF-8', '--date=format:%Y-%m-%d %H:%M',
                   '--format=%H%x01%h%x01%ad%x01%s', *refs, '--')
        commits = [Commit(*record.split('\x01', 3)) for record in out.split('\0') if record]
        if not commits:
            return [], '%s has no commits yet.' % folder
        problem = _exports_problem(folder, refs)
        if problem:
            return [], problem
        if len(commits) == 1:
            return [], '%s has one commit: there is nothing to compare it with.' % folder
        return commits, None
    except _GitFailed as ex:
        return [], _unreadable(folder, ex.text)


def full_hash(folder, rev):
    """The full hash of a revision, None when the repo has no such commit. A name that reads as an option is none."""
    if not rev or rev.startswith('-'):
        return None
    try:
        return _git(folder, 'rev-parse', '--verify', '--quiet', rev + '^{commit}').strip()
    except _GitFailed:
        return None


def short_of(folder, rev):
    """The short hash of a revision, rev itself when there is no such commit or no such repo."""
    try:
        return _git(folder, 'rev-parse', '--verify', '--quiet', '--short', rev + '^{commit}').strip() or rev
    except _GitFailed:
        return rev


def _holds_exports(folder, commit):
    """Does the report read anything in this commit: asked of the report, as only it knows an export from another .xml."""
    from TiaChangeReports import hmi, source     # here: the window needs them only at Compare
    try:
        snapshot = source.GitSnapshot(folder, commit)
        return bool(snapshot.paths() or snapshot.tag_tables() or hmi.holds_objects(folder, commit))
    except ValueError as ex:
        raise _GitFailed(str(ex))


def compare_problem(folder, before, after):
    """Why these two commits of folder cannot be compared, in plain words; None when they can."""
    try:
        problem = _repo_problem(folder)
        if problem:
            return problem
        problem = _exports_problem(folder, _refs(folder))
        if problem:
            return problem
        hashes = []
        for side, rev in (('before', before), ('after', after)):
            full = full_hash(folder, rev)
            if not full:
                return 'The %s commit %s is not in %s.' % (side, rev, folder)
            hashes.append(full)
        if hashes[0] == hashes[1]:
            return 'Before and after are the same commit (%s).' % short_of(folder, before)
        if not _holds_exports(folder, hashes[0]) and not _holds_exports(folder, hashes[1]):
            return ('Neither commit holds exports (%s, %s), so there is nothing to compare. Choose another commit.'
                    % (short_of(folder, before), short_of(folder, after)))
        return None
    except _GitFailed as ex:
        return _unreadable(folder, ex.text)


def no_exports_warning(folder, before, after):
    """What a commit with no exports does to the report, in plain words; None when both hold some. For two commits
    compare_problem has passed. A repo that fails only now: None, and the report's step says what is wrong."""
    try:
        for side, rev, reads in (('before', before, 'new'), ('after', after, 'deleted')):
            if not _holds_exports(folder, full_hash(folder, rev)):
                return ('The %s commit %s holds no exports, so everything in the other commit reads as %s.'
                        % (side, short_of(folder, rev), reads))
    except _GitFailed:
        pass
    return None


def default_title(folder, before, after):
    return '%s: %s vs %s' % (repo_name(folder), before, after)


def repo_name(folder):
    return os.path.basename(os.path.abspath(folder).rstrip('\\/')) or folder


def project_repos(roots):
    """The folders directly under the roots that hold a git repo, by name."""
    found = []
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        found += [os.path.join(root, n) for n in names if os.path.exists(os.path.join(root, n, '.git'))]
    return sorted(dict.fromkeys(found), key=lambda p: os.path.basename(p).casefold())
