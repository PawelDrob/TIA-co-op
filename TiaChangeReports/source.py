"""Inputs of a diff. A block version = name + .s7dcl text + .s7res text + a label for the page (BlockSource), or
the text of a SimaticML export (.xml) instead: OBs, which TiaBridge exports as SimaticML only, and blocks TIA refused
to export as SIMATIC SD (simaticml.py reads them).
A snapshot = a set of block versions keyed by path (one export file, an export folder, a git revision of a project
repo or its working tree; later a base snapshot with a patch applied). The diff and the renderer only see
BlockSource objects.

Every snapshot has paths() (its block exports, relative, '/'-separated: every .s7dcl, and every .xml that is the
SimaticML export of a PLC block or data type unless a .s7dcl of the same name is beside it), load(path) ->
BlockSource and read(path) -> text of any file of the snapshot, or None. load() also reads the .libinfo beside a
library type's export into BlockSource.version (LibVersion; None for a block that is not a library type).
paths() also sets skipped: [(path, why)], the .xml files that hold a block but are no block export (a global library
type's version metadata, TiaBridge's export of it); compare_snapshots adds the files that do not load
or parse. skipped(snapshots): each once.

What a snapshot reads: a folder or revision in a project repo's layout (_in_layout: all of REPO_MARKS at the
repo's root, and every export under them where such a repo holds one) reads its exports only, the paths under
EXPORT_ROOTS from the repo's root, and any TIA folder under a root reads, whatever its name. A block or tag table outside
the roots is named in skipped (LEFT_OUT); only REVIEW_COPIES, a library review's working copies, go unnamed. Any other
folder or repo is a set of exports as given: all of it but the dot folders at its top. git_snapshots decides once for
the two revisions: both in the layout, or both read whole.
changed_paths(before, after): the files of any kind that differ between two snapshots, for otherfiles.py.

git_snapshots(repo, rev1, rev2) -> two GitSnapshots restricted to the blocks with a file in
git diff --name-only rev1 rev2, so that unchanged blocks are not read; rev2 None = the working tree, every file load() reads
hashed (git's size and time are no proof).

pair_blocks(before, after) -> [(path_before | None, path_after | None)]: same relative path first, then the same
file name where it is unique on both sides (a block moved between folders, or a project block vs. its library type);
the extension does not count (a block exported as SimaticML once and as .s7dcl later pairs). The blocks left on both
sides then pair by content, a renamed block: same kind and number (and content 30% alike), else
similar content.

Not built yet, the seam for it: a patch on its own = PatchedSnapshot(base snapshot, unified diff).
"""
import difflib
import filecmp
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

import yaml

from .names import decl_name, decl_type
from .s7dcl import parse_block, parse_res, texts_for_keys
from .simaticml import BLOCK_RE, ELEMENT_RE, element_kind, export_kind, same_export

# Where a project repo holds exports, from its root, and what marks a repo as laid out so (test_export_roots holds the
# list to the folders TiaBridge's kinds export to; the report reads no file of the bridge).
EXPORT_ROOTS = ('plc/', 'hmi/', 'project/', 'library/types/', 'library/faceplates/', 'library/mastercopies/',
                'library/global/')
REPO_MARKS = ('plc', 'hmi', 'library')     # all three, in this case: a new project repo has them from its first commit
REVIEW_COPIES = 'library/changes/'
LEFT_OUT = 'not compared: outside the folders a project repo holds exports in'
TAG_TABLE = 'tag table'                # what a kind_of says of a PLC tag table
UNREADABLE = 'unreadable'              # what _head_kind says of a file it cannot read


def _table_or(first, kind):
    """TAG_TABLE when an export's first SW. element (None: none) is a PLC tag table's, else kind()."""
    return TAG_TABLE if first and first.startswith('<SW.Tags.PlcTagTable') else kind()


def stem(path):
    """Path of a block export without its extension (.s7dcl, .xml)."""
    for x in ('.s7dcl', '.xml'):
        if path.endswith(x):
            return path[:-len(x)]
    return path


def _exports(paths, kind_of, reads=lambda path: True):
    """Sorts paths. The block exports: every .s7dcl, and an .xml for which kind_of(path) (simaticml.export_kind) is
    'block', unless a .s7dcl of the same name is beside it (the .xml is left from a time TIA refused the SD export;
    TiaBridge writes .s7dcl for every block but OBs and know-how protected ones). -> (paths, skipped, tables): skipped
    the other .xml holding a block, [(path, why)] (a global library type's version metadata), and an
    export that reads(path) leaves out; tables the PLC tag tables, and the other .xml of no block in a PLC's tags folder.
    An .xml that cannot be read stays what its folder makes it, a table there and else a block: reading it names it,
    where leaving it out would read as a table or block deleted."""
    sd = {p[:-6] for p in paths if p.endswith('.s7dcl')}
    out, skipped, tables = [], [], []
    for p in paths:
        k = 'block' if p.endswith('.s7dcl') else kind_of(p) if p.endswith('.xml') and p[:-4] not in sd else None
        if k in (None, UNREADABLE) and p.endswith('.xml') and _in_tags_folder(p):   # holds no table: plctags names it
            k = TAG_TABLE
        elif k == UNREADABLE:
            k = 'block'
        if k and not reads(p):
            skipped.append((p, LEFT_OUT))
        elif k == 'block':
            out.append(p)
        elif k == TAG_TABLE:
            tables.append(p)
        elif k:
            skipped.append((p, k))
    return out, skipped, tables


def _in_place(path):
    """Does an .s7dcl or .xml stand where a project repo holds one, as far as REPO_MARKS tell: plc/<folder>/... or
    plc/<device>/<folder>/...; in a folder of hmi/, and no .s7dcl there; in a folder of library/. Outside them: yes."""
    parts = path.split('/')
    if parts[0] == 'plc':
        return parts[1] in PLC_EXPORT_FOLDERS or (len(parts) > 3 and parts[2] in PLC_EXPORT_FOLDERS)
    if parts[0] == 'hmi':
        return len(parts) > 2 and path.endswith('.xml')
    return parts[0] != 'library' or path.startswith(EXPORT_ROOTS + (REVIEW_COPIES,))


def _top_folders(files):
    """The folders at the top of files, paths from a root."""
    return {p.split('/', 1)[0] for p in files if '/' in p}


def _in_layout(files):
    """Are files, paths from a repo's root as written, a project repo's: not a plain folder with groups of those names."""
    return (set(REPO_MARKS) <= _top_folders(files)
            and all(_in_place(p) for p in files if p.endswith(('.s7dcl', '.xml'))))


def _reads(path, laid_out, prefix=''):
    """Is a path from a snapshot's folder read. laid_out, a project repo, prefix that folder in the repo: under
    EXPORT_ROOTS from the repo's root. Else: all but a dot folder at the top (.git)."""
    return (prefix + path).startswith(EXPORT_ROOTS) if laid_out else not (path.startswith('.') and '/' in path)


def _unnamed(path, laid_out, prefix=''):
    """Is a path not read and not named in skipped either: a library review's working copy, a plain folder's dot folder."""
    return (prefix + path).startswith(REVIEW_COPIES) if laid_out else not _reads(path, False)


def _head_kind(path):
    """The kind of a file (its root element is near the top): TAG_TABLE, else export_kind; UNREADABLE when it cannot
    be read."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read(65536)
    except OSError:
        return UNREADABLE
    first = re.search(ELEMENT_RE, text)
    return _table_or(first and first.group(), lambda: export_kind(text))


@dataclass
class LibVersion:
    """Version of a library type, from its <Type>.libinfo (LibraryVersion: VersionNumber, Author, InWork or
    IsDefault)."""
    number: str             # e.g. 3.0.6
    author: str = ''
    in_work: bool = False
    default: bool = False   # the default version of the type in its library


def lib_version(text):
    """.libinfo text -> LibVersion, None when there is none or it has no version number."""
    try:
        lv = (yaml.safe_load(text or '') or {}).get('LibraryVersion')
    except (yaml.YAMLError, AttributeError):
        return None
    if not isinstance(lv, dict) or lv.get('VersionNumber') is None:
        return None
    return LibVersion(str(lv['VersionNumber']), str(lv.get('Author') or ''), lv.get('InWork') is True,
                      lv.get('IsDefault') is True)


@dataclass
class BlockSource:
    name: str               # its file's name, e.g. Filler (the block's own name: Block.name, names.object_name)
    s7dcl: str              # SIMATIC SD text
    s7res: Optional[str]    # resource YAML (network titles, comments), None when there is none
    label: str              # shown on the page: a path, or "<rev>:<path>"
    version: Optional[LibVersion] = None    # a library type's version (.libinfo beside the .s7dcl)
    xml: Optional[str] = None               # a SimaticML export instead of .s7dcl / .s7res (those are '' / None)


def _read(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def name_of(path):
    """What the page calls a file or folder: the name of the git repo holding it and the path in the repo
    ("Plant/plc"), else its own name; never a directory of the machine."""
    path = os.path.abspath(path)
    top = path
    while not os.path.exists(os.path.join(top, '.git')):
        up = os.path.dirname(top)
        if up == top:
            return os.path.basename(path)
        top = up
    rel = os.path.relpath(path, top)
    return os.path.basename(top) + ('' if rel == '.' else '/' + rel.replace(os.sep, '/'))


def from_file(path):
    """A .s7dcl export with its .s7res and .libinfo beside it (same stem), or a SimaticML export (.xml)."""
    path = os.path.abspath(path)
    stem, ext = os.path.splitext(path)
    version = lib_version(_read_if(stem + '.libinfo'))
    if ext == '.xml':
        return BlockSource(name=os.path.basename(stem), s7dcl='', s7res=None, label=path, version=version,
                           xml=_read(path))
    return BlockSource(name=os.path.basename(stem), s7dcl=_read(path), s7res=_read_if(stem + '.s7res'), label=path,
                       version=version)


class FileSnapshot:
    """One export file named on the command line: one that is no block export is an error (ValueError, its path and
    why in one line), not an empty block nor a skipped file."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.label = name_of(self.path)
        self.skipped = []
        why = _no_block(self.path)
        if why:
            raise ValueError('%s: %s' % (self.path, why))

    def paths(self):
        return [os.path.basename(self.path)]

    def load(self, rel):
        return from_file(self.path)

    def read(self, rel):
        return _read_if(os.path.join(os.path.dirname(self.path), rel))

    def tag_tables(self):
        return []


def _no_block(path):
    """Why a file is no block export (another file, a .s7res, an .xml of no block, a .s7dcl that does not parse),
    else None."""
    ext = os.path.splitext(path)[1]
    if ext not in ('.s7dcl', '.xml'):
        return 'not a block export (%s)' % ('the texts of one: give its .s7dcl' if ext == '.s7res' else
                                            'an .s7dcl, or the SimaticML .xml of a block')
    kind = _head_kind(path) if ext == '.xml' else 'block'
    if kind not in ('block', UNREADABLE):                # one that cannot be read: reading it below says why
        return kind if kind and kind != TAG_TABLE else 'not a SimaticML block export'
    try:
        parse_block(from_file(path))
    except Exception as ex:                              # noqa: BLE001 - any error of this file
        why = str(ex)
        why = why[len(path) + 2:] if why.startswith(path + ': ') else why
        return why if why.startswith('not a ') else '%s: %s' % (UNREADABLE, why)
    return None


class FolderSnapshot:
    """Every block export under a folder (an export tree such as a TiaBridge project repo). The folder given is the root
    the layout is read from: a folder inside a repo is not read as the repo."""
    prefix = ''

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.label = name_of(self.root)
        self.skipped = []
        self._tables = None

    def tag_tables(self):
        """The files plctags.py reads, the PLC tag tables and what else is in a PLC's tags folder, as paths() found
        them."""
        if self._tables is None:
            self.paths()
        return self._tables

    def found(self):
        """Every file of the folder, an export or not."""
        found = []
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if d != self.root or x != '.git')
            found += [os.path.relpath(os.path.join(d, f), self.root).replace('\\', '/') for f in sorted(files)]
        return found

    def paths(self):
        found = self.found()
        laid_out = _in_layout(found)
        out = [p for p in found if p.endswith(('.s7dcl', '.xml')) and not _unnamed(p, laid_out)]
        out, self.skipped, self._tables = _exports(out, lambda p: _head_kind(os.path.join(self.root, p)),
                                                   lambda p: _reads(p, laid_out))
        return out

    def load(self, rel):
        return from_file(os.path.join(self.root, rel))

    def read(self, rel):
        return _read_if(os.path.join(self.root, rel))

    def read_bytes(self, rel):
        return _bytes_if(os.path.join(self.root, rel))


def _read_if(path):
    return _read(path) if os.path.isfile(path) else None


def _bytes_if(path):
    if not os.path.isfile(path):
        return None
    with open(path, 'rb') as f:
        return f.read()


GIT_CONTEXT = ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR')    # a parent's: git prefers them to -C


def _git(cwd, *args, input=None):
    env = {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
    # stdin is never inherited: a thread blocked reading it (the archive compare runner's) would hold this start; no
    # console either, for the window that runs without one
    try:
        r = subprocess.run(['git', '-C', cwd, '-c', 'core.quotepath=off'] + list(args), input=input or b'',
                           capture_output=True, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as ex:
        raise ValueError('git: %s' % ex)
    if r.returncode:
        raise ValueError('git %s in %s: %s' % (args[0], cwd, r.stderr.decode('utf-8', 'replace').strip()))
    return r.stdout


def _names(out):
    """Paths from a git -z listing."""
    return [p for p in out.decode('utf-8').split('\0') if p]


LOADED = ('.s7dcl', '.s7res', '.libinfo', '.xml')       # the files load() reads of a block


class _Blobs:
    """The files of a revision: its tree listed once, the contents read in one git cat-file --batch for many files
    (one git show per file took minutes for a full re-export). Shared by the copies of a
    GitSnapshot (compare.Callees)."""

    def __init__(self, root, rev):
        self.root, self.rev = root, rev
        self._tree = None       # {path: blob id}
        self._data = {}         # {path: bytes, None when the object is missing}

    def tree(self):
        if self._tree is None:
            self._tree = {}
            for rec in _names(_git(self.root, 'ls-tree', '-r', '-z', self.rev)):
                meta, path = rec.split('\t', 1)                 # <mode> <type> <id>\t<path>
                _, kind, oid = meta.split(' ')
                if kind == 'blob':
                    self._tree[path] = oid
        return self._tree

    def get(self, rel, more):
        """The bytes of rel, None when the revision has no such file; on the first read of rel also those of the
        files more() names."""
        tree = self.tree()
        if rel not in tree:
            return None
        if rel not in self._data:
            want = [p for p in dict.fromkeys([rel] + more()) if p in tree and p not in self._data]
            oids = list(dict.fromkeys(tree[p] for p in want))
            out = _git(self.root, 'cat-file', '--batch', input=''.join(o + '\n' for o in oids).encode())
            blobs, at = {}, 0
            for o in oids:                                      # <id> blob <size>\n<bytes>\n, or <id> missing\n
                eol = out.index(b'\n', at)
                head, at = out[at:eol].split(b' '), eol + 1
                if len(head) == 3:
                    blobs[o], at = out[at:at + int(head[2])], at + int(head[2]) + 1
            self._data.update((p, blobs.get(tree[p])) for p in want)
        return self._data[rel]


def _working_files(root):
    """The files of a working tree from root: tracked and untracked, not the ignored ones."""
    return [p for p in _names(_git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'))
            if os.path.isfile(os.path.join(root, p))]


class GitSnapshot:
    """A revision of a git repo, or its working tree (rev None: tracked and untracked files, not the ignored ones).
    repo may be a folder inside the repo: paths are relative to it. only: the stems (path without extension) to
    keep, e.g. the blocks changed between two revisions."""

    def __init__(self, repo, rev=None, only=None):
        self.root = os.path.abspath(repo)
        self.rev = rev
        self.only = only
        self.skipped = []
        self._tables = None
        if not os.path.isdir(self.root):
            raise ValueError('not a folder: %s' % repo)
        self._top, self.prefix = (_git(self.root, 'rev-parse', '--show-toplevel', '--show-prefix').decode('utf-8')
                                  .splitlines())
        self.changed = ()       # the files git_snapshots found changed between the two revisions
        self._laid_out = None
        if rev is None:
            self.label = '%s (working tree)' % name_of(self.root)
            return
        try:
            commit = _git(self.root, 'rev-parse', '--verify', '--short', rev + '^{commit}').decode().strip()
        except ValueError:
            raise ValueError('no commit %s in %s' % (rev, self.root))
        self.label = '%s @ %s' % (name_of(self.root), rev if rev.startswith(commit) else '%s (%s)' % (rev, commit))
        self._blobs = _Blobs(self.root, rev)

    def found(self):
        """Every file of this revision or working tree, an export or not, from the repo's root."""
        if self.rev is None:
            return _working_files(self._top)
        return list(_Blobs(self._top, self.rev).tree() if self.prefix else self._blobs.tree())

    def laid_out(self):
        """Is this revision or working tree a project repo's (_in_layout); git_snapshots may have decided for the pair."""
        if self._laid_out is None:
            self._laid_out = _in_layout(self.found())
        return self._laid_out

    def _reads(self, path):
        return _reads(path, self.laid_out(), self.prefix)

    def tag_tables(self):
        """The files plctags.py reads, the PLC tag tables and what else is in a PLC's tags folder, as paths() found
        them: restricted as it is."""
        if self._tables is None:
            self.paths()
        return self._tables

    def paths(self):
        if self.rev is None:
            ps = _working_files(self.root)
        else:
            ps = self._blobs.tree()
        laid_out = self.laid_out()
        ps = sorted({p for p in ps if p.endswith(('.s7dcl', '.xml')) and not _unnamed(p, laid_out, self.prefix)
                     and (self.only is None or stem(p) in self.only)})
        if self.rev is None:
            ps, self.skipped, self._tables = _exports(ps, lambda p: _head_kind(os.path.join(self.root, p)), self._reads)
            return ps
        first, holds = {}, set()
        if any(p.endswith('.xml') for p in ps):                 # the first SW. element of each SimaticML export
            for rec in self._grep('-o', '-m', '1', ELEMENT_RE).decode('utf-8').split('\n'):
                if '\0' in rec:
                    p, el = rec.split('\0', 1)
                    first.setdefault(p.split(':', 1)[1], el)
            if any(element_kind(first.get(p), False) != 'block' for p in ps if p in first):   # does it hold one?
                holds = {p.split(':', 1)[1] for p in _names(self._grep('-l', BLOCK_RE))}
        ps, self.skipped, self._tables = _exports(
            ps, lambda p: _table_or(first.get(p), lambda: element_kind(first.get(p), p in holds)), self._reads)
        return ps

    def _grep(self, *args):
        """git grep -z -E args in the .xml files of the revision."""
        try:
            return _git(self.root, 'grep', '-z', '-E', *args, self.rev, '--', '*.xml')
        except ValueError:                                      # git grep exits 1 when nothing matches
            return b''

    def read(self, rel):
        if self.rev is None:
            return _read_if(os.path.join(self.root, rel))
        data = self._blobs.get(rel, lambda: self._with(rel))
        if data is None:
            return None
        return data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')     # as open() reads a file

    def read_bytes(self, rel):
        if self.rev is None:
            return _bytes_if(os.path.join(self.root, rel))
        return self._blobs.get(rel, list)

    def _with(self, rel):
        """The files read together with rel: what load() reads of every block in only (a restricted snapshot loads
        them all), else of rel's block only."""
        st = os.path.splitext(rel)[0]
        stems = self.only if self.only is not None and st in self.only else {st}
        return [p for p in self._blobs.tree() if p.endswith(LOADED) and os.path.splitext(p)[0] in stems
                and self._reads(p)]

    def load(self, rel):
        st = stem(rel)
        text = self.read(rel)
        if text is None:
            raise ValueError('%s: no %s' % (self.label, rel))
        label = os.path.join(self.root, rel.replace('/', os.sep)) if self.rev is None else '%s:%s' % (self.rev, rel)
        version = lib_version(self.read(st + '.libinfo'))
        if rel.endswith('.xml'):
            return BlockSource(name=st.rsplit('/', 1)[-1], s7dcl='', s7res=None, label=label, version=version,
                               xml=text)
        return BlockSource(name=st.rsplit('/', 1)[-1], s7dcl=text, s7res=self.read(st + '.s7res'), label=label,
                           version=version)


def not_compared(before, after):
    """What a page names of the two snapshots' skipped, once both are read. Not an export of no block holding one that
    is the same on both sides: a global library type's version metadata in a compare of two folders, which else no such
    project's page could ever read "No changes." over; nor one unread on the other side, named so."""
    files = skipped((before, after))
    unread = {path for path, why in files if why.startswith(UNREADABLE)}
    return [(path, why) for path, why in files if why == LEFT_OUT or why.startswith(UNREADABLE)
            or path not in unread and not _same_on_both(before, after, path)]


def _same_on_both(before, after, path):
    """Does a file read the same on both sides, but for the export time; not when it cannot be read: one file never
    stops the report."""
    try:
        return same_export(before.read(path), after.read(path))
    except Exception:                                    # noqa: BLE001 - any error of this file
        return False


def _holds_export_folders(files):
    """Does a repo or folder hold any of a project repo's folders, as an export folder of some parts only does."""
    return bool(set(REPO_MARKS) & _top_folders(files))


def _files_differ(path_b, path_a):
    """Two files of two folders differ; one that cannot be opened counts as differing: nothing tells it is the same."""
    try:
        return not filecmp.cmp(path_b, path_a, shallow=False)
    except OSError:
        return True


def changed_paths(before, after, counts):
    """The files of two snapshots that differ, new and deleted too, of those counts(path) takes; only those are compared.
    With any of a project repo's folders on either side only the files under EXPORT_ROOTS, else all but the dot folders
    at the top: an export folder holds the exporting tool's own files beside them."""
    if isinstance(before, FileSnapshot):
        return []
    found_b, found_a = before.found(), after.found()
    tree = _holds_export_folders(found_b) or _holds_export_folders(found_a)

    def takes(path):
        return _reads(path, tree, before.prefix) and counts(path)
    if isinstance(before, GitSnapshot):
        return [p for p in before.changed if takes(p)]
    b, a = set(found_b), set(found_a)
    return [p for p in b | a if takes(p) and (p not in b or p not in a or _files_differ(
        os.path.join(before.root, p), os.path.join(after.root, p)))]


def skipped(snaps):
    """The files the snapshots skipped (no block export, or unreadable: compare_snapshots adds those), each
    (path, why) once, in order: a file skipped on both sides is named once."""
    return list(dict.fromkeys(x for s in snaps for x in getattr(s, 'skipped', ())))


def _changed_in_working_tree(snap):
    """The files load() reads whose bytes in the working tree are not those of the revision snap. By the blob id of
    every file: git's own word that a file is unchanged rests on its size and time, which an edit with the time restored
    passes. git hash-object applies git's filters, so a checkout's line ends differ from nothing; a blob
    that itself holds CRLF under core.autocrlf does differ here, which costs a read and shows nothing.
    A file it cannot read has no id and may differ: then all of them, and the comparison names that one."""
    tree = {p: oid for p, oid in snap._blobs.tree().items() if p.endswith(LOADED)}
    files = [p for p in _working_files(snap.root) if p.endswith(LOADED)]
    try:
        ids = _git(snap._top, 'hash-object', '--stdin-paths',       # takes its paths from the repo's root, wherever run
                   input=''.join(snap.prefix + p + '\n' for p in files).encode('utf-8')).decode().split()
    except ValueError:
        ids = []
    return (set(tree) | set(files)) - {p for p, oid in zip(files, ids) if tree.get(p) == oid}


def git_snapshots(repo, rev1, rev2=None):
    """Two revisions of a repo (rev2 None: its working tree), each restricted to the blocks with a changed file, read
    alike: a file one side leaves out and the other reads would be a block deleted or new that nobody touched."""
    before, after = GitSnapshot(repo, rev1), GitSnapshot(repo, rev2)
    before._laid_out = after._laid_out = before.laid_out() and after.laid_out()
    diff = ['diff', '--name-only', '--no-renames', '--no-ext-diff', '--relative', '-z', rev1]
    if rev2 is None:
        changed = _changed_in_working_tree(before)
        others = _names(_git(before.root, *diff)) + _names(_git(before.root, 'ls-files', '-z', '--others',
                                                                '--exclude-standard'))
        changed |= {p for p in others if not p.endswith(LOADED)}    # by git's word: what no block reads
    else:
        changed = _names(_git(before.root, *(diff + [rev2])))
    before.only = after.only = {os.path.splitext(p)[0] for p in changed}
    before.changed = after.changed = changed
    return before, after


def snapshot(arg):
    """A path on the command line: an export file or an export folder (git revisions: git_snapshots)."""
    if os.path.isdir(arg):
        return FolderSnapshot(arg)
    if os.path.isfile(arg):
        return FileSnapshot(arg)
    raise ValueError('neither an export file nor a folder: %s' % arg)


def pair_blocks(before, after):
    pb, pa = before.paths(), after.paths()
    if len(pb) == 1 and len(pa) == 1:
        return [(pb[0], pa[0])]
    out = []
    sb, sa = {stem(p): p for p in pb}, {stem(p) for p in pa}
    out += [(sb[stem(p)], p) for p in pa if stem(p) in sb]
    lb = [p for p in pb if stem(p) not in sa]
    la = [p for p in pa if stem(p) not in sb]

    def key(p):
        """The name, unique within one PLC's program blocks or within the library types: a block moved with its type
        holds the name twice on each side; one gone from a PLC and one new in another, or a program block gone and a
        library type new, are two objects."""
        return plc_device(p), _is_library(p), stem(p).rsplit('/', 1)[-1].lower()
    cb, ca = {}, {}
    for p in lb:
        cb.setdefault(key(p), []).append(p)
    for p in la:
        ca.setdefault(key(p), []).append(p)
    used_b, used_a = set(), set()
    for k, ps in ca.items():
        if len(ps) == 1 and len(cb.get(k, [])) == 1:
            out.append((cb[k][0], ps[0]))
            used_b.add(cb[k][0])
            used_a.add(ps[0])
    lb = [p for p in lb if p not in used_b]
    la = [p for p in la if p not in used_a]
    renamed = _pair_renamed(before, after, lb, la)
    out += renamed
    out += [(p, None) for p in lb if p not in {b for b, _ in renamed}]
    out += [(None, p) for p in la if p not in {a for _, a in renamed}]
    return out


# Content similarity from which a deleted and a new block of the same kind are one renamed block.
RENAMED_BLOCK_MIN = 0.6
# Content similarity from which two left blocks of the same kind and number are one renamed block: TIA may
# give a deleted block's number to an unrelated new block.
NUMBER_BLOCK_MIN = 0.3

_SETPOINT_FALSE = re.compile(r'S7_Set[Pp]oint\s*:=\s*"False"\s*;?')
_SETPOINT = re.compile(r'S7_Set[Pp]oint\b')
# The line that declares a block; of a real UDT export the one after TYPE
_DECL = re.compile(r'^[ \t]*(?:TYPE[ \t]*\r?\n[^\n]*|(?:FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\b[^\n]*)',
                   re.M)
_PRAGMA = re.compile(r'^[ \t]*\{([^{}]*)\}[ \t]*\r?\n?', re.M)     # on its own line: braces in a string are text
_SYNTAX = re.compile(r'^[A-Z_ #:{}]*$')    # END_VAR, # : STRUCT, a brace: alike in every block, not content


@dataclass
class _Left:
    """A block left unpaired by path and name: what pairing by content compares."""
    path: str
    library: bool           # under library/ (pairs only with library/), else a PLC block or type
    kind: tuple             # (FUNCTION_BLOCK, ''), an instance DB with its FB: (DATA_BLOCK, FB name)
    number: Optional[str]
    lines: list             # content_lines()


def _is_library(path):
    return path.startswith('library/') or '/library/' in path


PLC_FOLDERS = ('blocks', 'systemblocks', 'tags', 'technology', 'types')    # a PLC's folders in a repo (page.PLC_ROOTS)
PLC_EXPORT_FOLDERS = PLC_FOLDERS + ('alarms', 'forcetables', 'supervisions', 'watchtables')   # and those of no block


def _in_tags_folder(path):
    """In a PLC's tag tables folder of a repo: plc/tags/..., plc/<device>/tags/..."""
    parts = path.split('/')
    return parts[0] == 'plc' and len(parts) > 2 and parts[1 if plc_device(path) is None else 2] == 'tags'


def plc_device(path):
    """The PLC device folder of a repo path: plc/<device>/... with several PLCs; None with one PLC
    (plc/blocks/...) and outside plc/."""
    parts = path.split('/')
    return parts[1] if len(parts) > 3 and parts[0] == 'plc' and parts[1] not in PLC_FOLDERS else None


def _pragma_lines(m):
    """A pragma as one line per setting, without any S7_Setpoint (a library type's .s7dcl writes none): nothing left
    of `{ S7_Setpoint := "True" }`, not even a blank line, and the same lines however the export lays the pragma out."""
    kept = [e for e in (x.strip() for x in m.group(1).split(';')) if e and not _SETPOINT.match(e)]
    return ''.join(e + '\n' for e in kept)


def _masked(decl, names):
    """A declaration without the block's own name: a type's block can be declared otherwise than the type.
    Only there: elsewhere the name is what a user wrote."""
    for n in names:
        decl = re.sub(r'(?<![\w"#])%s(?![\w"])' % re.escape(n), '#', decl.replace('"%s"' % n, '"#"'))
    return decl


def _shown_lines(blk, names):
    """What the report shows of a parsed SimaticML export, as lines: properties, members, networks. Not the file's
    own lines, which differ per export: the export time, the object numbers, the order of the languages."""
    out = ['%s %s' % (blk.kind, _masked(blk.decl, names))] + ['%s := %s' % kv for kv in sorted(blk.props.items())]

    def walk(member):
        for c in member.children.values():
            attrs = sorted(c.attrs.items())
            out.append(' | '.join(str(x) for x in (c.section, c.name, c.type, c.value, c.comment, c.retain, attrs)))
            walk(c)
    walk(blk.interface.root)
    out.extend('%s := %s' % kv for kv in sorted(blk.interface.start.items()))
    for n in blk.networks:
        out.extend([n.lang, n.title, n.comment, n.label])
        out.extend(n.body.splitlines())
    return out


def content_lines(src, blk, syntax=False):
    """The lines of a block export to compare two blocks by content: stripped, without the block's own name, the
    texts in place of their MLC keys (TIA renumbers them per copy), no `S7_Setpoint := "False"` (the
    project block writes it, the released library version not), no `;` at the end and no line of
    keywords or braces only. syntax, to tell two changes apart rather than how alike two blocks are: only what the two
    exports write differently is left out, everything a user typed stays: the lines as they are but for
    the name in the declaration and the texts, each pragma as _pragma_lines, of a SimaticML export what the report
    shows of it (_shown_lines)."""
    names = {src.name, blk.name, decl_name(blk.decl)} - {''}
    if syntax:
        if src.xml is not None:
            return _shown_lines(blk, names)
        res = parse_res(src.s7res)
        text = texts_for_keys(src.s7dcl, res)
        text = _DECL.sub(lambda m: _masked(m.group(0), names), text, count=1)
        return _PRAGMA.sub(_pragma_lines, text).splitlines()
    if src.xml is not None:
        text = src.xml
        for n in names:
            text = text.replace('>%s<' % n, '>#<').replace('"%s"' % n, '"#"')
    else:
        res = parse_res(src.s7res)
        text = re.sub(r'"([^"\n]*)"', lambda m: '"%s"' % ('#' if m.group(1) in names else
                                                          res.get(m.group(1), m.group(1))), src.s7dcl)
        for n in names:                                  # unquoted: DATA_BLOCK FillerDb : Filler
            text = re.sub(r'(?<![\w"#])%s(?![\w"])' % re.escape(n), '#', text)
    lines = (l.strip().rstrip(';').strip() for l in _SETPOINT_FALSE.sub('', text).splitlines())
    return [l for l in lines if not _SYNTAX.match(l)]


def _left(snap, path):
    try:
        src = snap.load(path)
        blk = parse_block(src)
    except Exception:                                    # noqa: BLE001 - unreadable: stays deleted / new
        return None
    of = decl_type(blk.decl).strip('"') if blk.kind == 'DATA_BLOCK' else ''
    return _Left(path, _is_library(path), (blk.kind, of), blk.props.get('S7_BlockNumber'), content_lines(src, blk))


def _name_similarity(pb, pa):
    nb, na = (stem(p).rsplit('/', 1)[-1].lower() for p in (pb, pa))
    return difflib.SequenceMatcher(None, nb, na, autojunk=False).ratio()


def block_similarity(lb, la, atleast=0.0):
    """How alike two blocks' content_lines are, 0 to 1 (share of equal lines in order); 0 when it cannot reach
    atleast (not computed to the end) or one has none."""
    if not lb or not la:
        return 0.0
    sm = difflib.SequenceMatcher(None, lb, la, autojunk=False)
    if sm.real_quick_ratio() < atleast or sm.quick_ratio() < atleast:
        return 0.0
    return sm.ratio()


def _pair_renamed(before, after, lb, la, minsim=RENAMED_BLOCK_MIN, numsim=NUMBER_BLOCK_MIN):
    """Blocks left on both sides that are one renamed block, one-for-one, only a PLC block with a block of its PLC and
    a library type with a library type: same kind (an instance DB: of the same FB) and the same number where that
    number is unique among the left blocks of that kind on both sides and content_lines alike from numsim, else the
    same kind and content_lines alike from minsim, best first (equally alike: the more alike names first)."""
    if not lb or not la:
        return []
    groups = {}
    for side, snap, paths in ((0, before, lb), (1, after, la)):
        for p in paths:
            x = _left(snap, p)
            if x is not None and x.kind[0]:
                groups.setdefault((plc_device(p), x.library, x.kind), ([], []))[side].append(x)
    out = []
    for xb, xa in groups.values():
        if not xb or not xa:
            continue
        nb = [x.number for x in xb if x.number]
        na = [x.number for x in xa if x.number]
        for b in xb:
            if b.number and nb.count(b.number) == 1 and na.count(b.number) == 1:
                a = next(a for a in xa if a.number == b.number)
                if block_similarity(b.lines, a.lines, numsim) >= numsim:
                    out.append((b, a))
        done = {id(x) for pr in out for x in pr}
        cand = sorted(((s, i, j) for i, b in enumerate(xb) if id(b) not in done
                       for j, a in enumerate(xa) if id(a) not in done
                       for s in (block_similarity(b.lines, a.lines, minsim),) if s >= minsim),
                      key=lambda c: (-c[0], -_name_similarity(xb[c[1]].path, xa[c[2]].path), c[1], c[2]))
        for s, i, j in cand:
            if id(xb[i]) not in done and id(xa[j]) not in done:
                out.append((xb[i], xa[j]))
                done |= {id(xb[i]), id(xa[j])}
    return [(b.path, a.path) for b, a in out]
