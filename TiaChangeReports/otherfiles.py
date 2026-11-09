"""The changed files a report does not read: named on its page, so that the page cannot say "No changes." over them
(reading them is for later).

  other_files(before, after, ...) -> [path], sorted, of two snapshots (source.py), from their root

A file counts when it differs between the two, under a project repo's export roots (source.changed_paths; all of a folder
with no such folders), and nothing of the report reads it: no block's file, no PLC tag table, no HMI document or project
graphic. A file that does not read counts, as the report tells nothing of it; a tag table that does not read does not, it
stands on the page. A file the page names as not compared is left off its line by __main__, so the page names it once,
and stays in otherFiles, which TIA Archive Compare counts. By name
only the caller's keep leaves a file out: the generator's documents and the lists beside an HMI's exports
(hmi.beside_exports); a master copy stands only in a .json, so mastercopies.json counts.

Only what the report tells otherwise, what an export writes differently per export, or a release comment by the
maintainer's word, stays silent:
- a SimaticML .xml: simaticml.alike_exports, the export time and the object numbers, as of a block.
- another .xml: the CreationDate on its root (alarm classes, system diagnostics).
- a .dat that is a zip of the same text files: the same, per file (those two again, as a full export writes them).
- a library type's .libinfo and .libint, new or deleted with its block: that block is listed.
- a .libinfo beside a block: told as that block's version when its number or in-work differs, as far as the version row
  tells it (VERSION_ROW, the author in its hover title; IsDefault when in-work differs too, as its word). Its release
  comment stays silent with them, though nothing of the report reads it: the maintainer's word, until the report
  reads such files and shows it. A comment with no version told counts, and so does what else differs.
- a .libint: its hashes of the files beside it, which are told for themselves; its Guid, which is the version's, when
  that version is told as above. What it depends on counts: a released version can move there with no new version.
- of a block that moved or was renamed, these two are compared old path against new; the new path is the one named.
All of a block that does not read counts: nothing tells its version, and a page holding only that says "No changes.".
Only the hashes of a .libint beside one stay silent: the report does not parse an unchanged block, so it does not know.
"""
import copy
import io
import os
import re
import zipfile

import yaml

from .compare import versions_differ
from .simaticml import alike_exports
from .source import changed_paths, lib_version, stem

_HEAD = r'^\s*(?:<\?[^>]*\?>\s*)?'
_ROOT_DATE = re.compile('(%s<[\\w.:-]+\\b[^<>]*?)\\s+CreationDate="[^"]*"' % _HEAD)
_SIMATICML = re.compile(_HEAD + r'<Document\b')
LIBRARY_META = ('.libinfo', '.libint')
HASHES = ('LibraryMetaFileHash', 'DocumentHash')                        # of a .libint
VERSION_ROW = ('VersionNumber', 'Author', 'InWork')                     # of LibraryVersion in a .libinfo


def _blocks_and_tables(snap):
    """(block exports, tag tables) of a snapshot, from a copy: paths() would drop what compare_snapshots added to its
    skipped."""
    listing = copy.copy(snap)
    return set(listing.paths()), set(listing.tag_tables())


def _without(text, top_keys=(), version_keys=()):
    """A library file's mapping without those keys, at its top and in its LibraryVersion; None when it is no mapping."""
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        return None
    for key in top_keys:
        doc.pop(key, None)
    version = doc.get('LibraryVersion')
    if isinstance(version, dict):
        for key in version_keys:
            version.pop(key, None)
        if version_keys and not version:
            del doc['LibraryVersion']
    return doc


def _alike_without(b, a, top_keys=(), version_keys=()):
    left = _without(b, top_keys, version_keys)
    return left is not None and left == _without(a, top_keys, version_keys)


def _only_the_root_date(b, a):
    return _ROOT_DATE.sub(r'\1', b) == _ROOT_DATE.sub(r'\1', a)


def _zipped_texts(data):
    """{name: text} of the files of a zip; what is no zip of text files raises."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {name: z.read(name).decode('utf-8-sig') for name in z.namelist()}


def _zip_differs_only_in_root_dates(b, a):
    b, a = _zipped_texts(b), _zipped_texts(a)
    return b.keys() == a.keys() and all(_only_the_root_date(b[name], a[name]) for name in b)


def _library_file_told(before, after, path, stems, moved_from):
    """A .libinfo or .libint differs at most in what the module's doc lets stay silent."""
    base, ext = os.path.splitext(path)
    base_b = moved_from.get(base, base)
    if base in moved_from.values() and after.read(path) is None:
        return True                                      # its block moved: compared at the new path
    b, a = before.read(base_b + ext), after.read(base + ext)
    if b == a:
        return True
    read_b, read_a = base_b in stems[0], base in stems[1]
    if (b is None and not read_b) or (a is None and not read_a):
        return read_b or read_a                          # new or deleted with its block
    if not (read_b or read_a) or b is None or a is None:
        return False
    vb, va = lib_version(before.read(base_b + '.libinfo')), lib_version(after.read(base + '.libinfo'))
    told = versions_differ(vb, va)
    if ext == '.libinfo':
        if not told:
            return False
        silent = VERSION_ROW + ('Comment',) + (('IsDefault',) if vb.in_work != va.in_work else ())
        return _alike_without(b, a, version_keys=silent)
    return _alike_without(b, a, top_keys=HASHES, version_keys=('Guid',) if told else ())


def _told_or_only_the_export(before, after, path, stems, moved_from):
    """The two versions of a file differ at most in what the module's doc lets stay silent. stems: per side, the block
    exports the report read, without their extension. moved_from: {stem after: stem before} of the blocks that moved."""
    if path.endswith(LIBRARY_META):
        return _library_file_told(before, after, path, stems, moved_from)
    if path.endswith('.dat'):
        b, a = before.read_bytes(path), after.read_bytes(path)
        return b is not None and a is not None and _zip_differs_only_in_root_dates(b, a)
    if not path.endswith('.xml'):
        return False
    b, a = before.read(path), after.read(path)
    if b is None or a is None:
        return False
    if _SIMATICML.match(b) and _SIMATICML.match(a):
        return alike_exports(b, a)
    return _only_the_root_date(b, a)


def _stays_silent(before, after, path, stems, moved_from):
    try:
        return _told_or_only_the_export(before, after, path, stems, moved_from)
    except Exception:                                    # noqa: BLE001 - any error of this file: it does not read, it counts
        return False


def other_files(before, after, hmi_read, not_read, keep, moved=()):
    """The files of the module's doc. hmi_read: the paths the HMI part reads, not_read: those the report found it cannot
    read, from the snapshot's root (hmi_read: of its repo). keep(path from the repo's root): what is asked about.
    moved: (path before, path after) of the blocks the report paired under another path."""
    b_blocks, b_tables = _blocks_and_tables(before)
    a_blocks, a_tables = _blocks_and_tables(after)
    not_read = set(not_read)
    b_blocks, a_blocks = b_blocks - not_read, a_blocks - not_read
    blocks = b_blocks | a_blocks
    read = blocks | {stem(p) + '.s7res' for p in blocks if p.endswith('.s7dcl')} | b_tables | a_tables
    hmi_read = set(hmi_read) - not_read

    def counts(path):
        return path not in read and before.prefix + path not in hmi_read and keep(before.prefix + path)
    stems = {stem(p) for p in b_blocks}, {stem(p) for p in a_blocks}
    moved_from = {stem(path_a): stem(path_b) for path_b, path_a in moved}
    return sorted(p for p in changed_paths(before, after, counts) if not _stays_silent(before, after, p, stems, moved_from))
