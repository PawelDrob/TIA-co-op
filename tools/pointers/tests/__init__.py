import os
import subprocess
import sys

# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
# Without git, or when it fails, they stay and the tests that need no git still run.
try:
    _listed = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    _problem = 'exit code %d' % _listed.returncode if _listed.returncode else ''
except OSError as _error:
    _problem = str(_error)
if _problem:
    print('%s: git rev-parse --local-env-vars did not answer (%s): the names git reads a repo from stay in this process'
          % (__name__, _problem), file=sys.stderr)
else:
    for _name in _listed.stdout.split():
        os.environ.pop(_name, None)
