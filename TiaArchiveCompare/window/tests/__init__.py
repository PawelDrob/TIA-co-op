import os
import subprocess

# Started by a git-aware parent (a hook or an alias of another repo), a run by hand would carry the parent's repo into
# every git -C of a fixture, whose commits would land there: the names git reads a repo from leave this process.
for _name in subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True).stdout.split():
    os.environ.pop(_name, None)
