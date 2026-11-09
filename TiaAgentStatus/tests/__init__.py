"""The tests of the agent status tools. The TIA dashboard they run reads the records of running HMI previews from a
folder of their own, not the one the previews of this machine write (TiaHmiGenerator\hmipreview\running.py)."""
import atexit
import os
import shutil
import subprocess
import tempfile

os.environ['HMIPREVIEW_RUNNING'] = tempfile.mkdtemp(prefix='agent-status-previews-')
atexit.register(shutil.rmtree, os.environ['HMIPREVIEW_RUNNING'], True)
# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
for _name in subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.split():
    os.environ.pop(_name, None)
