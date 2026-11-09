"""The two sides of an HMI change report: the HMI documents of a folder, a git revision or a working tree.

A side lists the files under hmi/ and project/graphics/ (GRAPHICS: the project graphics, an image each in
'<name> files/' beside its .xml) as {path: id} (repo-relative, '/'-separated; equal ids = equal contents) and reads
one as bytes. GitSide reads a revision through one git ls-tree and one git cat-file --batch per prefetch;
WorktreeSide gives the git blob id of each file (git hash-object of its bytes), so a document equal to the other
side's is never parsed. FolderSide hashes every file. FolderStamps breaks the rule on ids: they are size and time, for
one folder watched over time, so changes.compare refuses it.

documents(side, set) -> {(device, kind, name): Entry}, the documents of one set:
  'tia'        the TIA exports: hmi/<kind dir>/..., with several HMI devices hmi/<device>/<kind dir>/...
  'generated'  the exports with the generated documents (hmi/[<device>/]generated/<kind dir>/...) in place of those
               of the same device, kind and name: what TIA holds after the import
name is the file stem, which TiaBridge and hmixml derive from the Name. hmi/references/ is never read.
data_files(side) -> {(device, file): path} of hmi/[<device>/]handbuilt.json and panel.json.
graphics(side) -> {name: path} of the project graphics' .xml files (name: the file stem).
"""
import hashlib
import os
import subprocess
from dataclasses import dataclass

from .gitenv import NO_WINDOW, git_env

KIND_DIRS = {'screens': 'screen', 'templates': 'template', 'popups': 'popup', 'slideins': 'slidein',
             'global': 'global', 'textlists': 'textlist', 'graphiclists': 'graphiclist', 'tags': 'tagtable',
             'cycles': 'cycle', 'connections': 'connection', 'scripts': 'script'}
DRAWN = ('screen', 'template', 'popup', 'slidein', 'global')     # documents the page draws
SETS = ('tia', 'generated')
SKIP_TOP = ('references',)
DATA_FILES = ('handbuilt.json', 'panel.json')
HMI_LISTS = DATA_FILES + ('graphics.json',)          # the lists beside an HMI's exports, none an export of TIA
GRAPHICS = 'project/graphics'
ROOTS = ('hmi', GRAPHICS)
GENERATED = 'generated'
EXPORT = 'export'


def _git(root, *args, input=None):
    # stdin is never inherited: a thread blocked reading it (the archive compare runner's) would hold this start; no
    # console either, for the window that runs without one
    try:
        r = subprocess.run(['git', '-C', root, '-c', 'core.quotepath=off'] + list(args), input=input or b'',
                           capture_output=True, env=git_env(), creationflags=NO_WINDOW)
    except OSError as ex:
        raise ValueError('git: %s' % ex)
    if r.returncode:
        raise ValueError('git %s in %s: %s' % (args[0], root, r.stderr.decode('utf-8', 'replace').strip()))
    return r.stdout


def _names(out):
    return [p for p in out.decode('utf-8').split('\0') if p]


def toplevel(repo):
    """The root of the git repo holding the folder repo (ValueError when it is none)."""
    if not os.path.isdir(repo):
        raise ValueError('not a folder: %s' % repo)
    return os.path.normpath(_git(repo, 'rev-parse', '--show-toplevel').decode('utf-8').strip())


def _unreadable(full, ex):
    return ValueError('cannot read %s: %s' % (full, ex.strerror or ex))


class FolderSide:
    """hmi/ without hmi/references/, and project/graphics/, below root (a repo checkout or an export folder); ids are
    hashes of the bytes. Size and time prove nothing between two folders: a zip keeps times to two seconds, a tool can
    stamp every file alike. A file or folder that cannot be read is a ValueError naming it."""

    def __init__(self, root, label=None):
        self.root = os.path.abspath(root)
        self.label = label or os.path.basename(self.root.rstrip('\\/'))
        self._files = None

    def files(self):
        if self._files is None:
            ids = {}
            for top in ROOTS:
                base = os.path.join(self.root, *top.split('/'))
                for d, dirs, fs in self._walk(base):
                    if top == 'hmi' and d == base:
                        dirs[:] = [x for x in dirs if x not in SKIP_TOP]
                    for f in fs:
                        full = os.path.join(d, f)
                        ids[os.path.relpath(full, self.root).replace(os.sep, '/')] = self._id(full)
            self._files = ids
        return self._files

    def _walk(self, base):
        """os.walk of base: a folder it cannot list is a ValueError naming it, a missing base lists nothing."""
        def failed(ex):
            if not (isinstance(ex, FileNotFoundError) and ex.filename == base):
                raise _unreadable(ex.filename or base, ex)
        return os.walk(base, onerror=failed)

    def _id(self, full):
        try:
            with open(full, 'rb') as f:
                return hashlib.file_digest(f, 'sha1').hexdigest()
        except OSError as ex:
            raise _unreadable(full, ex)

    def prefetch(self, paths):
        pass

    def read(self, path):
        full = os.path.join(self.root, path)
        try:
            with open(full, 'rb') as f:
                return f.read()
        except OSError as ex:
            raise _unreadable(full, ex)


class FolderStamps(FolderSide):
    """One folder watched over time, without hashing it (the preview's pictures); ids are (size, mtime): a hint that a
    file changed there, no proof that two folders agree, so changes.compare refuses it. A hint needs no whole listing:
    a folder an export is renaming is left out, and the next look finds it."""

    def _walk(self, base):
        return os.walk(base)

    def _id(self, full):
        st = os.stat(full)
        return 'f:%d:%d' % (st.st_size, st.st_mtime_ns)


class GitSide:
    """Revision rev of the repo holding the folder repo; ids are git blob ids."""

    def __init__(self, repo, rev):
        self.root = toplevel(repo)
        self.rev = rev
        try:
            short = _git(self.root, 'rev-parse', '--verify', '--short', rev + '^{commit}').decode().strip()
        except ValueError:
            raise ValueError('no commit %s in %s' % (rev, self.root))
        self.label = '%s @ %s' % (os.path.basename(self.root), rev if rev.startswith(short) else
                                  '%s (%s)' % (rev, short))
        self._files = {}
        for rec in _names(_git(self.root, 'ls-tree', '-r', '-z', rev, '--', *ROOTS)):
            meta, path = rec.split('\t', 1)                 # <mode> <type> <id>\t<path>
            _, kind, oid = meta.split(' ')
            if kind == 'blob':
                self._files[path] = oid
        self._data = {}

    def files(self):
        return self._files

    def prefetch(self, paths):
        """Reads the files paths names in one git cat-file --batch."""
        want = [p for p in dict.fromkeys(paths) if p in self._files and p not in self._data]
        if not want:
            return
        oids = list(dict.fromkeys(self._files[p] for p in want))
        out = _git(self.root, 'cat-file', '--batch', input=''.join(o + '\n' for o in oids).encode())
        blobs, at = {}, 0
        for o in oids:                                      # <id> blob <size>\n<bytes>\n
            eol = out.index(b'\n', at)
            head, at = out[at:eol].split(b' '), eol + 1
            if len(head) == 3:
                blobs[o], at = out[at:at + int(head[2])], at + int(head[2]) + 1
        self._data.update((p, blobs.get(self._files[p])) for p in want)

    def read(self, path):
        if path not in self._data:
            self.prefetch([path])
        data = self._data.get(path)
        if data is None:
            raise ValueError('%s: no %s' % (self.label, path))
        return data


class WorktreeSide(FolderSide):
    """The working tree of the repo holding the folder repo: tracked and untracked files under ROOTS (not the
    ignored ones, not hmi/references/). ids are git blob ids of the bytes there, comparable with a GitSide's. Git's own
    word that a file is unchanged rests on its size and time, which an edit with the time restored passes, so every
    file is hashed."""

    def __init__(self, repo):
        super().__init__(toplevel(repo))
        self.label = '%s (working tree)' % os.path.basename(self.root)

    def files(self):
        if self._files is None:
            excludes = [':(exclude)hmi/%s' % top for top in SKIP_TOP]
            listed = _names(_git(self.root, 'ls-files', '-c', '-o', '-z', '--exclude-standard', '--',
                                 *ROOTS, *excludes))
            present = sorted(p for p in set(listed) if os.path.isfile(os.path.join(self.root, p)))
            self._files = dict(zip(present, self._blob_ids(present)))
        return self._files

    def _blob_ids(self, paths):
        """The git blob ids of the files paths; a file that cannot be read is a ValueError naming it, as of a folder."""
        try:
            return _git(self.root, 'hash-object', '--stdin-paths', input=''.join(p + '\n' for p in paths)
                        .encode('utf-8')).decode().split()
        except ValueError:
            for p in paths:
                self.read(p)
            raise


def side(repo, rev=None):
    """A revision of the repo holding the folder repo, or its working tree when rev is None."""
    return WorktreeSide(repo) if rev is None else GitSide(repo, rev)


@dataclass
class Entry:
    device: str       # HMI device folder under hmi/, '' in a one-device repo
    kind: str         # KIND_DIRS value: 'screen', 'tagtable', ...
    folder: str       # TIA folder below the kind folder, '/'-separated, '' at the root
    name: str         # file stem
    path: str         # repo-relative path
    id: str           # the side's file id
    origin: str       # 'export' | 'generated'


def classify(path):
    """(device, origin, kind, folder, name) of an HMI document path, or None (data files, references, other)."""
    parts = path.split('/')
    if parts[0] != 'hmi' or not path.endswith('.xml'):
        return None
    parts = parts[1:]
    if not parts or parts[0] in SKIP_TOP:
        return None
    device = ''
    if parts[0] not in KIND_DIRS and parts[0] != GENERATED:
        device, parts = parts[0], parts[1:]
    origin = EXPORT
    if parts and parts[0] == GENERATED:
        origin, parts = GENERATED, parts[1:]
    if len(parts) < 2 or parts[0] not in KIND_DIRS:
        return None
    return device, origin, KIND_DIRS[parts[0]], '/'.join(parts[1:-1]), parts[-1][:-4]


def documents(sd, which='tia', devices=None):
    """{(device, kind, name): Entry} of side sd in set which ('tia' or 'generated'); devices limits the devices."""
    if which not in SETS:
        raise ValueError('set must be tia or generated: %s' % which)
    out, gen = {}, {}
    for path, fid in sd.files().items():
        c = classify(path)
        if not c:
            continue
        device, origin, kind, folder, name = c
        if devices and device not in devices:
            continue
        (gen if origin == GENERATED else out)[(device, kind, name)] = Entry(device, kind, folder, name, path, fid,
                                                                            origin)
    if which == GENERATED:
        for k, e in gen.items():
            if k in out and not e.folder:       # a generated document at the root replaces the export where it is
                e.folder = out[k].folder
            out[k] = e
    return out


def _device_file(path, names):
    """(device, file name) of a path hmi/<name> or hmi/<device>/<name> of names (device '' at hmi/), else None."""
    parts = path.split('/')
    if parts[0] == 'hmi' and parts[-1] in names and len(parts) in (2, 3):
        return parts[1] if len(parts) == 3 else '', parts[-1]
    return None


def data_files(sd):
    """{(device, file name): path} of handbuilt.json and panel.json of side sd."""
    out = {}
    for path in sd.files():
        key = _device_file(path, DATA_FILES)
        if key:
            out[key] = path
    return out


def is_hmi_list(path):
    """Is a path one of HMI_LISTS beside an HMI's exports: graphics.json, as TIA lists the project's graphics, and the
    data files, at hmi/ or a device's folder."""
    return _device_file(path, HMI_LISTS) is not None


def graphics(sd):
    """{name: path} of the .xml files of the project graphics of side sd (name: the file stem)."""
    pre = GRAPHICS + '/'
    return {p[len(pre):-4].rsplit('/', 1)[-1]: p for p in sd.files() if p.startswith(pre) and p.endswith('.xml')}


def graphic_folder(path):
    """The folder of the files of a project graphic, of the path of its .xml: '<name> files/' beside it."""
    return path[:-4] + ' files/'
