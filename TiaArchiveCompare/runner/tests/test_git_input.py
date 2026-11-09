"""The runner's git input: two commits of a repo, with no TIA. The repos are made here, of TiaChangeReports' made-up test
plant, so the report step runs for real. From the repo root:
python -m unittest discover -s TiaArchiveCompare/runner/tests -t .
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from TiaArchiveCompare.runner import __main__ as cli
from TiaArchiveCompare.runner import gitrepo
from TiaArchiveCompare.runner.fake import PLANT
from TiaArchiveCompare.runner.run import TOOL_ROOT
from TiaArchiveCompare.runner.tests.test_runner import RunCase


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid'] + list(args),
                          check=True, capture_output=True, env=env).stdout.decode().strip()


def commit_folder(repo, source, message):
    """The repo's files become those of source, in one commit; its short hash."""
    git(repo, 'rm', '-rqf', '--ignore-unmatch', '.')
    shutil.copytree(source, repo, dirs_exist_ok=True)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '--allow-empty', '-m', message)
    return git(repo, 'rev-parse', '--short', 'HEAD')


def no_pc_check(_root):
    raise AssertionError('a git compare needs no TIA: this PC is not checked')


class GitRepo(RunCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, 'Line7')
        os.makedirs(self.repo)
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'core.autocrlf', 'false')

    def plant_commits(self):
        return (commit_folder(self.repo, os.path.join(PLANT, 'v1'), 'H001 Before'),
                commit_folder(self.repo, os.path.join(PLANT, 'v2'), 'H002 After, with | a message'))

    def run_git(self, before, after, **kw):
        return self.run_compare(before, after, check=no_pc_check, git=self.repo, **kw)


class TwoCommits(GitRepo):
    def test_the_page_is_the_page_of_the_report_tool(self):
        a, b = self.plant_commits()
        rec = self.run_git(a, b, title='Line 7')
        self.assertEqual(0, self.code)
        with open(rec.end()['report'], encoding='utf-8') as f:
            page = f.read()
        by_hand = os.path.join(self.tmp, 'by-hand.html')
        subprocess.run([sys.executable, '-m', 'TiaChangeReports', '--git', self.repo, a, b, '-o', by_hand, '--title',
                        'Line 7'], cwd=TOOL_ROOT, check=True, capture_output=True)
        with open(by_hand, encoding='utf-8') as f:
            self.assertEqual(f.read(), page)
        self.assertGreater(rec.end()['changed'], 0)

    def test_its_events_are_those_of_a_run(self):
        a, b = self.plant_commits()
        rec = self.run_git(a, b)
        self.assertEqual(['check', 'report'], [s['id'] for s in rec.events[0]['steps']])
        self.assertEqual({'check': 'done', 'report': 'done'}, rec.states())
        self.assertEqual('end', rec.events[-1]['t'])
        self.assertEqual([], rec.of('tia'))
        self.assertTrue(rec.end()['ok'])
        self.assertTrue(os.path.basename(rec.end()['folder']).endswith(' Line7 %s vs Line7 %s' % (a, b)))

    def test_the_default_title_names_the_repo_and_the_commits(self):
        a, b = self.plant_commits()
        with open(self.run_git(a, b).end()['report'], encoding='utf-8') as f:
            self.assertIn('<title>Line7: %s vs %s</title>' % (a, b), f.read())

    def test_run_json_records_the_commits(self):
        a, b = self.plant_commits()
        rec = self.run_git(a, b)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            run = json.load(f)
        self.assertEqual(['commit', 'commit'], [i['kind'] for i in run['inputs']])
        self.assertEqual([a, b], [i['commit'] for i in run['inputs']])
        self.assertEqual(git(self.repo, 'rev-parse', a), run['inputs'][0]['hash'])     # what names it for good
        self.assertEqual(os.path.abspath(self.repo), run['inputs'][0]['repo'])
        self.assertIsNone(run['exporter']['name'])

    def test_any_revision_git_knows_is_taken(self):
        self.plant_commits()
        self.assertEqual(0, (self.run_git('HEAD~1', 'HEAD'), self.code)[1])


class NothingStarted(GitRepo):
    """Said in plain words: the check fails with the sentence, no report is written."""

    def failed_with(self, rec):
        self.assertEqual(1, self.code)
        self.assertEqual('failed', rec.states()['check'])
        self.assertEqual('skipped', rec.states()['report'])
        self.assertNotIn('report', rec.end())
        return rec.end()['error']

    def test_a_folder_that_is_no_git_repo(self):
        self.repo = os.path.join(self.tmp, 'plain')
        os.makedirs(self.repo)
        self.assertIn('is no git repo', self.failed_with(self.run_git('a', 'b')))

    def test_a_folder_that_is_not_there(self):
        self.repo = os.path.join(self.tmp, 'gone')
        self.assertIn('was not found', self.failed_with(self.run_git('a', 'b')))

    def test_a_repo_with_no_exports(self):
        os.makedirs(os.path.join(self.tmp, 'text', 'docs'))
        with open(os.path.join(self.tmp, 'text', 'docs', 'notes.txt'), 'w') as f:
            f.write('x')
        a = commit_folder(self.repo, os.path.join(self.tmp, 'text'), 'one')
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'two')
        self.assertIn('no exports', self.failed_with(self.run_git(a, 'HEAD')))

    def test_a_commit_that_is_not_there(self):
        a, _ = self.plant_commits()
        error = self.failed_with(self.run_git(a, 'abc1234'))
        self.assertIn('after commit abc1234', error)
        self.assertIn('is not in', error)

    def test_a_revision_that_reads_as_an_option(self):
        a, _ = self.plant_commits()
        self.assertIn('is not in', self.failed_with(self.run_git(a, '--all')))

    def test_the_same_commit_twice(self):
        _, b = self.plant_commits()
        self.assertIn('the same commit', self.failed_with(self.run_git(b, 'HEAD')))

    def commit_files(self, message, *names):
        files = os.path.join(self.tmp, 'files')
        shutil.rmtree(files, True)
        os.makedirs(files)
        for name in names:
            os.makedirs(os.path.dirname(os.path.join(files, name)), exist_ok=True)
            with open(os.path.join(files, name), 'w', encoding='utf-8') as f:
                f.write('<notes/>')
        return commit_folder(self.repo, files, message)

    def test_an_xml_that_is_no_export_counts_for_nothing(self):
        a = self.commit_files('one', 'docs/notes.xml')
        b = self.commit_files('two', 'docs/notes.xml', 'docs/more.xml')
        self.assertIn('Neither commit holds exports', self.failed_with(self.run_git(a, b)))

    def test_generated_screens_are_no_exports(self):
        a = self.commit_files('one', 'plc/.gitkeep', 'library/.gitkeep', 'hmi/generated/screens/S.xml')
        b = self.commit_files('two', 'plc/.gitkeep', 'library/.gitkeep', 'hmi/generated/screens/S.xml', 'hmi/generated/screens/T.xml')
        self.assertIn('Neither commit holds exports', self.failed_with(self.run_git(a, b)))

    def test_the_inside_of_a_repo_is_said_in_plain_words(self):
        self.plant_commits()
        self.repo = os.path.join(self.repo, '.git')
        error = self.failed_with(self.run_git('HEAD~1', 'HEAD'))
        self.assertIn('choose the folder that holds its .git folder', error)
        self.assertNotIn('fatal', error)


class ACommitWithNoExports(GitRepo):
    """It is compared, and the log says what that does to the page."""

    def warnings(self, rec):
        return [e['text'] for e in rec.of('log') if e['level'] == 'warn']

    def commit_notes(self, message):
        files = os.path.join(self.tmp, 'files')
        shutil.rmtree(files, True)
        os.makedirs(os.path.join(files, 'plc'))
        with open(os.path.join(files, 'plc', '.gitkeep'), 'w') as f:
            f.write('')
        return commit_folder(self.repo, files, message)

    def page_of(self, rec):
        with open(rec.end()['report'], encoding='utf-8') as f:
            return f.read()

    def test_as_before_all_reads_new(self):
        a = self.commit_notes('the repo made')
        b = commit_folder(self.repo, os.path.join(PLANT, 'v1'), 'the first export')
        rec = self.run_git(a, b, title='Line 7')
        self.assertEqual(0, self.code)
        self.assertGreater(rec.end()['changed'], 0)
        self.assertIn('The before commit %s holds no exports, so everything in the other commit reads as new.' % a,
                      self.warnings(rec))
        by_hand = os.path.join(self.tmp, 'by-hand.html')
        subprocess.run([sys.executable, '-m', 'TiaChangeReports', '--git', self.repo, a, b, '-o', by_hand, '--title',
                        'Line 7'], cwd=TOOL_ROOT, check=True, capture_output=True)
        with open(by_hand, encoding='utf-8') as f:
            self.assertEqual(f.read(), self.page_of(rec))

    def test_as_after_all_reads_deleted(self):
        a = commit_folder(self.repo, os.path.join(PLANT, 'v1'), 'the first export')
        b = self.commit_notes('all gone')
        rec = self.run_git(a, b)
        self.assertEqual(0, self.code)
        self.assertGreater(rec.end()['changed'], 0)
        self.assertIn('The after commit %s holds no exports, so everything in the other commit reads as deleted.' % b,
                      self.warnings(rec))

    def test_both_holding_exports_warns_of_nothing(self):
        a, b = self.plant_commits()
        self.assertEqual([], self.warnings(self.run_git(a, b)))


class ExportsAtTheRoot(GitRepo):
    def test_a_repo_with_its_exports_at_its_root(self):
        fixtures = os.path.dirname(PLANT)
        a = commit_folder(self.repo, self.files_of(fixtures, 'Main.xml'), 'one')
        b = commit_folder(self.repo, self.files_of(fixtures, 'Main.xml', 'Jumps.xml'), 'two')
        commits, problem = gitrepo.read_commits(self.repo)
        self.assertIsNone(problem)
        self.assertEqual([b, a], [c.short for c in commits])
        self.assertIsNone(gitrepo.compare_problem(self.repo, a, b))
        rec = self.run_git(a, b)
        self.assertEqual(0, self.code)
        self.assertEqual(1, rec.end()['changed'])

    def files_of(self, fixtures, *names):
        files = os.path.join(self.tmp, 'files')
        shutil.rmtree(files, True)
        os.makedirs(files)
        for name in names:
            shutil.copy(os.path.join(fixtures, name), files)
        return files


class CommitList(GitRepo):
    def test_newest_first_by_short_hash_date_and_message(self):
        a, b = self.plant_commits()
        commits, problem = gitrepo.read_commits(self.repo)
        self.assertIsNone(problem)
        self.assertEqual([b, a], [c.short for c in commits])
        self.assertEqual('H002 After, with | a message', commits[0].subject)
        self.assertRegex(commits[0].date, r'^\d{4}-\d\d-\d\d \d\d:\d\d$')

    def test_a_commit_of_another_branch_is_listed(self):
        a, b = self.plant_commits()
        git(self.repo, 'switch', '-q', '-c', 'side', a)
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'on the side')
        side = git(self.repo, 'rev-parse', '--short', 'HEAD')
        git(self.repo, 'switch', '-q', '-')
        self.assertEqual({a, b, side}, {c.short for c in gitrepo.read_commits(self.repo)[0]})

    def test_the_problems_of_a_repo_in_plain_words(self):
        self.assertIn('has no commits', gitrepo.read_commits(self.repo)[1])
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        self.assertIn('is no git repo', gitrepo.read_commits(plain)[1])
        self.assertIn('was not found', gitrepo.read_commits(os.path.join(self.tmp, 'gone'))[1])
        commit_folder(self.repo, os.path.join(PLANT, 'v1'), 'only one')
        self.assertIn('has one commit', gitrepo.read_commits(self.repo)[1])
        inside = os.path.join(self.repo, 'plc')
        self.assertIn('is a folder inside', gitrepo.read_commits(inside)[1])

    def test_no_git_is_said(self):
        with mock.patch.object(subprocess, 'run', side_effect=FileNotFoundError()):
            self.assertIn('Git', gitrepo.read_commits(self.repo)[1])


class ProjectRepos(unittest.TestCase):
    def test_the_folders_of_the_roots_that_hold_a_repo(self):
        root = tempfile.mkdtemp(prefix='tac-')
        self.addCleanup(shutil.rmtree, root, True)
        for name in ('B\\.git', 'a\\.git', '_bridge\\sessions', 'plain'):
            os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, 'file.txt'), 'w') as f:
            f.write('x')
        self.assertEqual([os.path.join(root, 'a'), os.path.join(root, 'B')],
                         gitrepo.project_repos([root, os.path.join(root, 'gone')]))


class CommandLine(GitRepo):
    def main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['run', '--out-root', os.path.join(self.tmp, 'out'), '--data-root',
                             os.path.join(self.tmp, 'data')] + list(argv), stdin=io.BytesIO(), stdout=out)
        return code, [json.loads(x) for x in out.getvalue().splitlines()]

    def test_git_from_the_command_line(self):
        a, b = self.plant_commits()
        code, events = self.main('--git', self.repo, '--before', a, '--after', b)
        self.assertEqual(0, code)
        self.assertTrue(events[-1]['ok'])

    def test_stdin_held_open_as_the_window_does(self):
        """A thread of the runner is blocked reading stdin: on Windows a child that inherits that handle does not start
        until the read returns, which the window never makes it do."""
        a, b = self.plant_commits()
        p = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'TiaArchiveCompare.runner', 'run', '--git', self.repo,
                              '--before', a, '--after', b, '--out-root', os.path.join(self.tmp, 'out'), '--data-root',
                              os.path.join(self.tmp, 'data')], cwd=TOOL_ROOT, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        watchdog = threading.Timer(45, p.kill)
        watchdog.start()
        try:
            out = p.stdout.read()       # stdin stays open until it has ended
        finally:
            watchdog.cancel()
            p.stdin.close()
            p.stdout.close()
        self.assertEqual(0, p.wait(), out.decode('utf-8', 'replace')[-400:])

    def test_what_only_tia_does_is_a_usage_error(self):
        for option in ('--compile', '--no-cache', '--safety'):
            code, events = self.main('--git', self.repo, '--before', 'a', '--after', 'b', option)
            self.assertEqual(2, code, option)
            self.assertIn(option, events[-1]['error'])
        code, events = self.main('--git', self.repo, '--before', 'a', '--after', 'b', '--safety')
        self.assertIn('does not go with --git', events[-1]['error'])

    def test_the_hmi_of_the_commits_is_always_compared(self):
        hmi = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'samples', 'hmi')
        a = commit_folder(self.repo, os.path.join(hmi, 'v1'), 'one')
        b = commit_folder(self.repo, os.path.join(hmi, 'v2'), 'two')
        code, events = self.main('--git', self.repo, '--before', a, '--after', b)
        self.assertEqual(0, code)
        self.assertGreater(events[-1]['changed'], 0)


if __name__ == '__main__':
    unittest.main()
