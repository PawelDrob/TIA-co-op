"""The export cache: %LOCALAPPDATA%\\TIA Compare\\exports\\<key>\\ with export\\ (the block exports) and meta.json.

key = SHA-256 of the source (archive bytes; a project folder's file names and bytes) + TIA version + exporter
version + scope + compile mode. An entry is built in the run's work folder and renamed into the cache
only when complete, so a cancel or a crash leaves no half entry. The last `keep` entries stay (by last use).
"""
import hashlib
import json
import os
import shutil
import time

META = 'meta.json'
EXPORT = 'export'


def file_digest(path, progress=None, chunk=4 << 20):
    """SHA-256 of a file; progress(done_mb, total_mb) after each chunk."""
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done >> 20, total >> 20)
    return h.hexdigest()


def folder_digest(folder, progress=None):
    """SHA-256 of a project folder's files: relative path and bytes; size and time do not tell a change for certain.
    progress(done_mb, total_mb) as in file_digest, over the whole folder. OSError when a file or folder cannot be
    read: the digest would not stand for the project."""
    def fail(ex):
        raise ex

    paths = []
    for d, dirs, files in os.walk(folder, onerror=fail):
        dirs.sort()
        paths += [os.path.join(d, f) for f in sorted(files)]
    total = sum(os.path.getsize(p) for p in paths)
    h = hashlib.sha256()
    done = 0
    for p in paths:
        file_progress = progress and (lambda mb, _, base=done >> 20: progress(base + mb, total >> 20))
        try:
            digest = file_digest(p, file_progress)
            done += os.path.getsize(p)
        except OSError as ex:
            ex.filename = ex.filename or p                  # a failed read names no file
            raise
        h.update(('%s|%s\n' % (os.path.relpath(p, folder).lower(), digest)).encode('utf-8'))
    return h.hexdigest()


def make_key(digest, tia, exporter, scope, compile_mode):
    text = json.dumps({'source': digest, 'tia': tia, 'exporter': exporter, 'scope': list(scope),
                       'compile': compile_mode}, sort_keys=True)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Entry:
    def __init__(self, folder):
        self.folder = folder
        self.export = os.path.join(folder, EXPORT)
        with open(os.path.join(folder, META), encoding='utf-8') as f:
            self.meta = json.load(f)


class Cache:
    def __init__(self, root, keep=10):
        self.root = root
        self.keep = keep

    def path(self, key):
        return os.path.join(self.root, key)

    def lookup(self, key):
        """The complete entry of `key` (its last use set to now), else None."""
        folder = self.path(key)
        try:
            entry = Entry(folder)
        except (OSError, ValueError):
            return None
        if not os.path.isdir(entry.export):
            return None
        now = time.time()
        try:
            os.utime(os.path.join(folder, META), (now, now))
        except OSError:
            pass
        return entry

    def store(self, built, key, meta):
        """Moves the folder `built` (holding export\\) into the cache as `key`, with meta.json; replaces an older
        entry of the key. Returns the entry. Same volume as the work folder: one rename."""
        with open(os.path.join(built, META), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=1)
        os.makedirs(self.root, exist_ok=True)
        dest = self.path(key)
        if os.path.exists(dest):
            old = dest + '.old-%d' % os.getpid()
            os.replace(dest, old)
            shutil.rmtree(old, ignore_errors=True)
        os.replace(built, dest)
        return Entry(dest)

    def prune(self, keep_keys=()):
        """Removes all but the `keep` entries used last; never one of keep_keys (this run's). Returns removed keys."""
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        entries = []
        for n in names:
            p = os.path.join(self.root, n)
            if '.old-' in n:                       # a replace that a crash interrupted
                shutil.rmtree(p, ignore_errors=True)
                continue
            try:
                entries.append((os.path.getmtime(os.path.join(p, META)), n))
            except OSError:
                shutil.rmtree(p, ignore_errors=True)       # not an entry (no meta): a leftover
        entries.sort(reverse=True)
        removed = []
        for i, (_, n) in enumerate(entries):
            if i >= self.keep and n not in keep_keys:
                shutil.rmtree(os.path.join(self.root, n), ignore_errors=True)
                removed.append(n)
        return removed
