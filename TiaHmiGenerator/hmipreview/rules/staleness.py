"""Staleness rule.

  staleness.export-newer   a generated document whose TIA export of the same kind and name was committed after
                           the document was last generated: TIA changed the object (hand edits) since, and an
                           import with Override would overwrite that change.
                           Preview: warning. for_import=True: error, unless override=True (then a warning again,
                           so the overwrite stays visible).

"Committed" is the committer time of the latest commit touching the export file (git log). "Last generated" is the
time the generator recorded in hmi/generated/generated.json (Repo.generated_time, written by hmixml.finish),
because a clone or checkout resets the mtime; a document without a readable entry falls back to the file's mtime.
An export that was never committed, or a repo without git, is not compared. Neither is a generated document equal
to its export (object-level diff, IDs and whitespace ignored): after the normal round trip (import, export, commit)
the export is newer, but TIA changed nothing an import could overwrite (project B 2026-10-06).
"""
import os
import subprocess
import time
from datetime import datetime, timezone

from ..diff import diff_trees
from ..findings import error, warning
from ..gitenv import NO_WINDOW, git_env


def check(repo, ctx):
    for d in repo.generated:
        exp = repo.export_of(d)
        if exp is None:
            continue
        committed = _commit_time(repo.path, exp.path)
        if committed is None:
            continue
        generated = _generated_time(repo, d)
        if generated >= committed:
            continue
        if not diff_trees(exp.tree, d.tree):
            continue
        make = error if ctx.for_import and not ctx.override else warning
        yield make(d.path, None, 'staleness.export-newer',
                   'The TIA export %s was committed %s, after %s %s was generated %s: TIA changed it since. '
                   'Regenerate from the new export, or import with override to overwrite the TIA change.'
                   % (exp.path, _fmt(committed), d.kind, d.name, _fmt(generated)))


def _generated_time(repo, doc):
    """When the generated document was last generated (seconds since the epoch): the recorded time, else mtime."""
    t = repo.generated_time(doc)
    if t is not None:
        return t
    try:
        return os.path.getmtime(os.path.join(repo.path, *doc.path.split('/')))
    except OSError:                 # not written yet (validated from an overlay): it is being generated now
        return time.time()


def _commit_time(repo_path, rel):
    """Committer time of the latest commit touching rel, or None (not committed, no git)."""
    try:
        out = subprocess.run(['git', '-C', repo_path, 'log', '-1', '--format=%ct', '--', rel],
                             capture_output=True, text=True, timeout=30, env=git_env(), creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return float(out.stdout.strip())


def _fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec='seconds')
