"""What the user picked as before / after: an archive, a project, or an earlier export folder."""
import os
import re

from . import gitrepo

KINDS = ('archive', 'project', 'exports', 'commit')
_EXT = re.compile(r'^\.(z?)ap(\d+)(_\d+)?$', re.IGNORECASE)     # as TiaBridge's Get-BackgroundSource


class Source:
    """kind: archive (.zap20, .zap19), project (.ap20 file, or the folder holding it), exports (a folder with block
    exports), or None with `problem` (plain words). `path` is what the exporter opens (the .ap20 file for a project)."""

    def __init__(self, given, kind=None, path=None, version=None, problem=None):
        self.given = given
        self.kind = kind
        self.path = path
        self.version = version
        self.problem = problem

    @property
    def upgrade(self):
        return bool(self.version and self.version < 20)

    @property
    def name(self):
        """The name the window, the folder and the report use: the file name without extension, or the folder name."""
        p = os.path.abspath(self.given).rstrip('\\/')
        base = os.path.basename(p)
        if os.path.isfile(p) or _EXT.match(os.path.splitext(base)[1]):
            base = os.path.splitext(base)[0]
        return base or p


class CommitSource(Source):
    """A commit of a git repo: given as the user named it (what the report gets), path the repo; full_hash None when
    the repo has no such commit (the check says so)."""

    def __init__(self, given, repo):
        super().__init__(given, 'commit', repo)
        self.short = gitrepo.short_of(repo, given)
        self.full_hash = gitrepo.full_hash(repo, given)

    @property
    def name(self):
        return '%s %s' % (gitrepo.repo_name(self.path), self.short)


def classify(given):
    p = os.path.abspath(given)
    if not os.path.exists(p):
        return Source(given, problem='%s was not found.' % p)
    if os.path.isfile(p):
        m = _EXT.match(os.path.splitext(p)[1])
        if not m:
            return Source(given, problem='%s is not a TIA Portal archive (.zap20, .zap19) or project (.ap20).' % p)
        version = int(m.group(2))
        kind = 'archive' if m.group(1) else 'project'
        if version > 20:
            return Source(given, kind, p, version, problem='%s is from TIA Portal V%d; this tool uses TIA Portal V20.'
                          % (os.path.basename(p), version))
        return Source(given, kind, p, version)
    projects = [f for f in sorted(os.listdir(p))
                if os.path.isfile(os.path.join(p, f)) and _EXT.match(os.path.splitext(f)[1])
                and not _EXT.match(os.path.splitext(f)[1]).group(1)]
    if len(projects) > 1:
        return Source(given, problem='%s holds several TIA projects (%s); pick the project file.'
                      % (p, ', '.join(projects)))
    if projects:
        s = classify(os.path.join(p, projects[0]))
        s.given = given
        return s
    if _has_exports(p):
        return Source(given, 'exports', p)
    return Source(given, problem='%s holds neither a TIA project nor block exports (.s7dcl, .xml).' % p)


def _has_exports(folder):
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith('.')]
        if any(f.endswith('.s7dcl') for f in files):
            return True
        if d != folder and any(f.endswith('.xml') for f in files):
            return True
    return False


_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(text, limit=60):
    """A file or folder name part: Windows-illegal characters replaced, shortened, no trailing dot or space."""
    s = _BAD.sub('_', text).strip()
    if len(s) > limit:
        s = s[:limit].rstrip()
    return s.rstrip('. ') or '_'


_SEP = re.compile(r'[-_ .]')
CUT = '~'           # marks where a name was shortened


def safe_pair(a, b, limit=60):
    """safe_name of two names that must stay apart (A and B of one run): a name longer than limit keeps its start
    and the part where it differs from the other, from the separator (- _ space .) before the difference:
    'plant-line-7-2026-10-19_161610' -> 'plant-l~2026-10-19_161610' (limit 25). When the difference starts within the first
    limit characters, the name is cut from the end as safe_name does."""
    a, b = safe_name(a, 10 ** 6), safe_name(b, 10 ** 6)
    p = 0
    while p < min(len(a), len(b)) and a[p].lower() == b[p].lower():
        p += 1
    # the difference from a whole word on, a date and time as a whole: '2026-10-19_161610', not '19_161610'
    word = p
    while word > 0 and (a[word - 1].isdigit() or a[word - 1] in '-_') and (p == len(a) or a[p].isdigit()):
        word -= 1
    if word == p:
        seps = [m.end() for m in _SEP.finditer(a[:p])]
        word = seps[-1] if seps else p
    while word < p and a[word] in '-_ .':
        word += 1
    return _short(a, p, word, limit), _short(b, p, word, limit)


def _short(name, p, word, limit):
    if len(name) <= limit:
        return name
    if p + 8 <= limit or p >= len(name):        # the difference shows in the first limit characters
        return safe_name(name, limit)
    least = min(10, limit // 4)                 # of the start
    if len(name) - word <= limit - len(CUT) - least:
        p = word
    rest = name[p:]
    head = max(limit - len(CUT) - len(rest), least)
    return safe_name(name[:head].rstrip() + CUT + rest, limit)
