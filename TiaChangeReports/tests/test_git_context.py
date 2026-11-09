"""A git-aware parent (a hook, another tool) leaves GIT_DIR and its like in the environment, and git prefers them to
-C: the report reads the repo it was asked for, and the parent's stays as it was."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from TiaChangeReports import source


def fixture_git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                           *args], check=True, capture_output=True, env=env).stdout


def text(out):
    return out.decode('utf-8').strip()


class ParentRepo(unittest.TestCase):
    """Two repos with a commit each: A, the parent's, and B, the one asked for."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.a, self.b = self.repo(tmp.name, 'A'), self.repo(tmp.name, 'B')
        self.context = {'GIT_DIR': os.path.join(self.a, '.git'), 'GIT_WORK_TREE': self.a,
                        'GIT_INDEX_FILE': os.path.join(self.a, '.git', 'index')}

    def repo(self, top, name):
        path = os.path.join(top, name)
        os.makedirs(path)
        fixture_git(path, 'init', '-q')
        self.put(path, name + '.s7dcl')
        fixture_git(path, 'add', '-A')
        fixture_git(path, 'commit', '-q', '-m', 'in ' + name)
        return path

    def put(self, repo, name):
        with open(os.path.join(repo, name), 'w', encoding='utf-8') as f:
            f.write('x\n')

    def parent_state(self):
        with open(self.context['GIT_INDEX_FILE'], 'rb') as f:
            return f.read(), fixture_git(self.a, 'log', '--format=%H %s'), fixture_git(self.a, 'status', '--porcelain')

    def inherited(self, **names):
        return mock.patch.dict(os.environ, names)

    def test_a_read_stays_in_the_repo_asked_for(self):
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', None):
            names = {name: self.context[name]} if name else self.context
            with self.subTest(inherited=name or 'all three'), self.inherited(**names):
                self.assertEqual(text(source._git(self.b, 'log', '-1', '--format=%s')), 'in B')
                self.assertEqual(text(source._git(self.b, 'ls-files', '--cached', '--others')), 'B.s7dcl')

    def test_a_write_lands_in_the_repo_asked_for_and_leaves_the_parent_as_it_was(self):
        before = self.parent_state()
        self.put(self.b, 'New.s7dcl')
        with self.inherited(**self.context):
            source._git(self.b, 'add', 'New.s7dcl')
            source._git(self.b, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                        'commit', '-q', '-m', 'second in B')
        self.assertEqual(self.parent_state(), before)
        self.assertEqual(text(fixture_git(self.b, 'log', '-1', '--format=%s')), 'second in B')

    def test_the_rest_of_the_environment_stays(self):
        # as on a machine with no git identity of its own (a CI runner): git var refuses an author without an email
        with self.inherited(GIT_AUTHOR_NAME='Somebody Else', GIT_AUTHOR_EMAIL='else@example.invalid',
                            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', **self.context):
            self.assertIn('Somebody Else', text(source._git(self.b, 'var', 'GIT_AUTHOR_IDENT')))
            self.assertEqual(os.environ['GIT_DIR'], self.context['GIT_DIR'])

    def test_a_report_of_the_repo_asked_for_lists_its_changes(self):
        self.put(self.b, 'Second.s7dcl')
        fixture_git(self.b, 'add', '-A')
        fixture_git(self.b, 'commit', '-q', '-m', 'second in B')
        with self.inherited(**self.context):
            before, after = source.git_snapshots(self.b, 'HEAD~1', 'HEAD')
            self.assertEqual(after.paths(), ['Second.s7dcl'])
            self.assertEqual(before.paths(), [])


class TheListOfGitsNames(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_it_holds_every_name_git_gives(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in source.GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
