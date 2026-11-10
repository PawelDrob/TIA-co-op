"""The tests of the agent status tools. The TIA dashboard they run reads the records of running HMI previews from a
folder of their own, not the one the previews of this machine write (TiaHmiGenerator\hmipreview\running.py)."""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

os.environ['HMIPREVIEW_RUNNING'] = tempfile.mkdtemp(prefix='agent-status-previews-')
atexit.register(shutil.rmtree, os.environ['HMIPREVIEW_RUNNING'], True)
# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
# Without git, or when it fails, they stay and the tests that need no git still run.
try:
    _listed = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    _problem = 'failed (exit code %d)' % _listed.returncode if _listed.returncode else ''
except OSError as _error:
    _problem = 'did not answer (%s)' % _error
if _problem:
    print('%s: git rev-parse --local-env-vars %s: the names git reads a repo from stay in this process'
          % (__name__, _problem), file=sys.stderr)
else:
    for _name in _listed.stdout.split():
        os.environ.pop(_name, None)
