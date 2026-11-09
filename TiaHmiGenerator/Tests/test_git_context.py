"""A git-aware parent (a hook, another tool) leaves GIT_DIR and its like in the environment, and git prefers them to
-C: the preview and the checks read the repo they were asked for, and the parent's stays as it was."""
import _winapi
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from hmipreview import diff, gitenv, sides
from hmipreview.rules import staleness


def fixture_git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                           *args], check=True, capture_output=True, env=env).stdout


def text(out):
    return out.decode('utf-8').strip()


class ParentRepo(unittest.TestCase):
    """Two repos with a commit each: A, the parent's, and B, the one asked for. The same file name holds other
    contents in each."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.a, self.b = self.repo(tmp.name, 'A'), self.repo(tmp.name, 'B')
        self.context = {'GIT_DIR': os.path.join(self.a, '.git'), 'GIT_WORK_TREE': self.a,
                        'GIT_INDEX_FILE': os.path.join(self.a, '.git', 'index')}

    def repo(self, top, name):
        path = os.path.join(top, name)
        os.makedirs(os.path.join(path, 'hmi', 'screens'))
        fixture_git(path, 'init', '-q')
        self.put(path, 'hmi/screens/Main.xml', 'of ' + name)
        fixture_git(path, 'add', '-A')
        fixture_git(path, 'commit', '-q', '-m', 'in ' + name)
        return path

    def put(self, repo, rel, content):
        with open(os.path.join(repo, rel), 'w', encoding='utf-8', newline='') as f:
            f.write(content)

    def parent_state(self):
        with open(self.context['GIT_INDEX_FILE'], 'rb') as f:
            return f.read(), fixture_git(self.a, 'log', '--format=%H %s'), fixture_git(self.a, 'status', '--porcelain')

    def inherited(self, **names):
        return mock.patch.dict(os.environ, names)

    def test_a_read_stays_in_the_repo_asked_for(self):
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', None):
            names = {name: self.context[name]} if name else self.context
            with self.subTest(inherited=name or 'all three'), self.inherited(**names):
                self.assertEqual(text(sides._git(self.b, 'log', '-1', '--format=%s')), 'in B')
                self.assertEqual(text(sides._git(self.b, 'ls-files', '--cached', '--others')), 'hmi/screens/Main.xml')
                self.assertEqual(text(sides._git(self.b, 'diff', '--name-only')), '')

    def test_a_write_lands_in_the_repo_asked_for_and_leaves_the_parent_as_it_was(self):
        before = self.parent_state()
        self.put(self.b, 'hmi/screens/New.xml', 'new')
        with self.inherited(**self.context):
            sides._git(self.b, 'add', 'hmi/screens/New.xml')
            sides._git(self.b, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                       'commit', '-q', '-m', 'second in B')
        self.assertEqual(self.parent_state(), before)
        self.assertEqual(text(fixture_git(self.b, 'log', '-1', '--format=%s')), 'second in B')

    def test_the_rest_of_the_environment_stays(self):
        # as on a machine with no git identity of its own (a CI runner): git var refuses an author without an email
        with self.inherited(GIT_AUTHOR_NAME='Somebody Else', GIT_AUTHOR_EMAIL='else@example.invalid',
                            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', **self.context):
            self.assertIn('Somebody Else', text(sides._git(self.b, 'var', 'GIT_AUTHOR_IDENT')))
            self.assertEqual(os.environ['GIT_DIR'], self.context['GIT_DIR'])

    def test_a_repo_found_from_a_folder_is_the_one_holding_it(self):
        # also by another spelling of the folder: a junction here, a short (8.3) temp path on a CI runner. git names
        # the folder it resolved
        via = os.path.join(os.path.dirname(self.b), 'via')
        _winapi.CreateJunction(self.b, via)
        with self.inherited(**self.context):
            for folder in (self.b, via):
                with self.subTest(folder=folder):
                    self.assertEqual(os.path.realpath(sides.toplevel(folder)), os.path.realpath(self.b))

    def test_a_working_tree_side_lists_the_repo_asked_for(self):
        expected = sides.WorktreeSide(self.b).files()
        self.assertEqual(list(expected), ['hmi/screens/Main.xml'])
        self.put(self.a, 'hmi/screens/OnlyInA.xml', 'a')
        fixture_git(self.a, 'add', '-A')
        fixture_git(self.a, 'commit', '-q', '-m', 'second in A')
        with self.inherited(**self.context):
            self.assertEqual(sides.WorktreeSide(self.b).files(), expected)

    def test_the_base_of_a_diff_is_read_at_the_head_of_the_repo_asked_for(self):
        with self.inherited(**self.context):
            self.assertEqual(diff._git_show(self.b, 'hmi/screens/Main.xml'), b'of B')

    def test_head_blobs_are_read_at_the_head_of_the_repo_asked_for(self):
        with self.inherited(**self.context):
            self.assertEqual(diff.head_blobs(self.b, ['hmi/screens/Main.xml']), {'hmi/screens/Main.xml': b'of B'})

    def test_a_commit_time_is_of_the_repo_asked_for(self):
        rel = 'hmi/screens/OnlyInA.xml'
        self.put(self.a, rel, 'a')
        fixture_git(self.a, 'add', '-A')
        fixture_git(self.a, 'commit', '-q', '-m', 'second in A')
        with self.inherited(**self.context):
            self.assertIsNone(staleness._commit_time(self.b, rel))


class TheListOfGitsNames(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_it_holds_every_name_git_gives(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in gitenv.GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
