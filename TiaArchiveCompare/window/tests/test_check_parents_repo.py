"""The window's check by hand (check.py), as it starts, takes the names git reads a repo from out of its process: started
by a git-aware parent, the commits of its made-up repo would otherwise land in the parent's. Only its import runs
here: no window opens."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LISTING = ['git', 'rev-parse', '--local-env-vars']


class AParentsRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Every name git gives, so a drop cut down to some of them fails here. None is left out: set to a folder, alone
        # or all at once, none made this call fail (git 2.45.1, 2026-11-10), as git answers it before it reads them.
        # The two a hook sets are in it whatever git says, also without git.
        try:
            listed = subprocess.run(LISTING, capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            listed = []
        cls.parents = listed + [name for name in ('GIT_DIR', 'GIT_WORK_TREE') if name not in listed]

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='parents-repo-')
        self.addCleanup(shutil.rmtree, self.folder, True)

    def imported(self, **changed):
        """What a process that imports check.py keeps of a parent's repo, and what it wrote to stderr."""
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path), **dict.fromkeys(self.parents, self.folder),
               **changed}
        show = 'import os, %s\nprint(*[name for name in %r if name in os.environ])' % (__package__ + '.check', self.parents)
        done = subprocess.run([sys.executable, '-X', 'utf8', '-c', show], env=env, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.split(), done.stderr

    def test_its_names_leave_the_process_of_the_check(self):
        kept, said = self.imported()
        self.assertEqual(kept, [], said)
        self.assertNotIn(' '.join(LISTING), said)

    def test_without_git_they_stay_and_the_check_says_so(self):
        kept, said = self.imported(PATH=self.folder)
        self.assertEqual(kept, self.parents)
        self.assertIn('git rev-parse --local-env-vars did not answer (', said)
        self.assertNotIn('Traceback', said)

    def test_when_git_fails_they_stay_and_the_check_says_so(self):
        # a program of Windows that fails on git's arguments stands in for a git that fails
        shutil.copy(os.path.join(os.environ['SystemRoot'], 'System32', 'where.exe'), os.path.join(self.folder, 'git.exe'))
        kept, said = self.imported(PATH=self.folder)
        self.assertEqual(kept, self.parents)
        self.assertIn('git rev-parse --local-env-vars failed (exit code ', said)
        self.assertNotIn('did not answer', said)
