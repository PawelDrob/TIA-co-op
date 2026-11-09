"""The real hook, run by git commit in a throwaway repo. The suites it runs are stubbed."""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

from tools.hooks.tests.fixture import CLEAN_ENV, errors_of_a_test_holding_a_file, init_repo

ROOT = Path(__file__).resolve().parents[3]


class HookRepo(unittest.TestCase):
    with_venv = True

    def setUp(self):
        self.temp_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_folder.cleanup)
        self.folder = Path(self.temp_folder.name)
        self.repo = self.folder / 'repo'
        self.repo.mkdir()
        shutil.copytree(ROOT / '.githooks', self.repo / '.githooks')
        self.put('TiaBridge/Tests/parse.ps1', '')
        self.put('tools/pointers/check_pointers.py', '')
        self.put('.gitignore', '.scratch/\n.venv/\n')
        init_repo(self.repo)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'base')
        self.git('config', 'core.hooksPath', '.githooks')
        if self.with_venv:
            venv.create(self.repo / '.venv', with_pip=False)

    def put(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def git(self, *args, check=True, **env):
        return subprocess.run(['git', *args], cwd=self.repo, env={**CLEAN_ENV, **env}, check=check, capture_output=True,
                              encoding='utf-8')

    def commit(self, **env):
        return self.git('commit', '-m', 'a change', check=False, **env)

    def commit_past_the_hooks(self, message):
        self.git('-c', 'core.hooksPath=no-hooks-here', 'commit', '-q', '-m', message)

    def sh(self, *args, cwd=None, **env):
        return subprocess.run(['sh', *args], cwd=cwd or self.repo, env={**CLEAN_ENV, **env}, capture_output=True, encoding='utf-8',
                              timeout=120)

    def audit(self, cwd=None, **env):
        return self.sh('.githooks/pre-commit', 'main', cwd=cwd, **env)

    def commits(self):
        return int(self.git('rev-list', '--count', 'HEAD').stdout)

    def assertRefused(self, result, *texts):
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertEqual(self.commits(), 1, output)
        for text in texts:
            self.assertIn(text, output)

    def assertCommitted(self, result):
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(self.commits(), 2, output)


class Cleanup(unittest.TestCase):
    def test_a_folder_that_cannot_go_fails_the_test(self):
        self.assertIn('held', errors_of_a_test_holding_a_file(self, HookRepo))


class ACommitOfTheBridgeAlone(HookRepo):
    """The report's list of export folders is held to the bridge's when only the bridge changes."""
    PASSES = 'import unittest\n\nclass T(unittest.TestCase):\n    def test(self):\n        pass\n'

    def setUp(self):
        super().setUp()
        self.put('TiaBridge/Tests/run.ps1', '')
        self.put('TiaAgentStatus/__init__.py', '')
        self.put('TiaAgentStatus/tests/__init__.py', '')
        self.put('TiaAgentStatus/tests/test_stub.py', self.PASSES)
        self.put('TiaChangeReports/__init__.py', '')
        self.put('TiaChangeReports/tests/__init__.py', '')
        self.git('add', '-A')
        self.commit_past_the_hooks('stubs')

    def commit_the_bridge(self, folders_test):
        self.put('TiaChangeReports/tests/test_export_roots.py',
                 'import unittest\n\nclass BridgeFolders(unittest.TestCase):\n    def test(self):\n        %s\n' % folders_test)
        self.git('add', 'TiaChangeReports')
        self.commit_past_the_hooks('the test')
        self.put('TiaBridge/Tools/New.ps1', '')
        self.git('add', 'TiaBridge')
        return self.commit()

    def test_a_folder_the_report_does_not_read_refuses_it(self):
        result = self.commit_the_bridge('self.fail()')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('EXPORT_ROOTS', result.stderr)

    def test_otherwise_it_goes_through(self):
        result = self.commit_the_bridge('pass')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("the report reads the bridge's export folders", result.stderr)


class DocumentsAndTheirLog(HookRepo):
    """A document added, moved, removed or deprecated takes a line in docs/log.md."""
    HEADER = '---\ntype: Guide\ntitle: A\n---\n\nSome text of this document, long enough for git to see a move.\n'

    def setUp(self):
        super().setUp()
        self.put('tools/okf/Test-OkfBundle.ps1', '')
        self.put('docs/log.md', '# Log\n')
        self.put('docs/index.md', '# Index\n')
        self.put('docs/user/a.md', self.HEADER)
        self.git('add', '-A')
        self.commit_past_the_hooks('docs')

    def assertNeedsTheLog(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('docs/log.md', result.stdout + result.stderr)

    def assertPasses(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def add_document(self):
        self.put('docs/user/b.md', self.HEADER)
        self.git('add', 'docs/user/b.md')

    def test_a_new_document_without_a_line_is_refused(self):
        self.add_document()
        self.assertNeedsTheLog(self.commit())

    def test_a_new_document_with_a_line_goes_through(self):
        self.add_document()
        self.put('docs/log.md', '# Log\n\n## 2026-01-02\n* **Creation**: b\n')
        self.git('add', 'docs/log.md')
        self.assertPasses(self.commit())

    def test_a_moved_document_without_a_line_is_refused(self):
        self.git('mv', 'docs/user/a.md', 'docs/user/c.md')
        self.assertNeedsTheLog(self.commit())

    def test_a_removed_document_without_a_line_is_refused(self):
        self.git('rm', '-q', 'docs/user/a.md')
        self.assertNeedsTheLog(self.commit())

    def test_a_deprecated_document_without_a_line_is_refused(self):
        self.put('docs/user/a.md', self.HEADER.replace('title: A\n', 'title: A\nstatus: deprecated\n'))
        self.git('add', 'docs/user/a.md')
        self.assertNeedsTheLog(self.commit())

    def test_a_document_deprecated_in_quotes_without_a_line_is_refused(self):
        self.put('docs/user/a.md', self.HEADER.replace('title: A\n', 'title: A\nstatus: "deprecated"\n'))
        self.git('add', 'docs/user/a.md')
        self.assertNeedsTheLog(self.commit())

    def test_a_new_document_with_a_name_git_would_quote_is_refused_without_a_line(self):
        self.put('docs/user/ä-b.md', self.HEADER)
        self.git('add', 'docs/user')
        self.assertNeedsTheLog(self.commit())

    def test_a_change_of_text_or_an_index_needs_no_line(self):
        self.put('docs/user/a.md', self.HEADER + 'More.\n')
        self.put('docs/user/index.md', '# Index\n')
        self.git('add', 'docs')
        self.assertPasses(self.commit())

    def test_the_audit_form_reads_the_branch(self):
        self.git('branch', '-M', 'main')
        self.git('checkout', '-q', '-b', 'feature')
        self.add_document()
        self.commit_past_the_hooks('a document with no line')
        self.assertNeedsTheLog(self.audit())


class StubsOfEveryFolder(HookRepo):
    """A repo with a passing stub suite in the folders of the suites below, committed."""
    PASSES = 'import unittest\n\nclass T(unittest.TestCase):\n    def test(self):\n        pass\n'

    def suite(self, folder, test=PASSES):
        self.put(f'{folder}/__init__.py', '')
        self.put(f'{folder}/tests/__init__.py', '')
        self.put(f'{folder}/tests/test_stub.py', test)

    def setUp(self):
        super().setUp()
        self.put('TiaBridge/Tests/run.ps1', '')
        self.put('tools/__init__.py', '')
        for folder in ('TiaAgentStatus', 'TiaChangeReports', 'tools/hooks', 'tools/pointers', 'tools/setup'):
            self.suite(folder)
        self.git('add', '-A')
        self.commit_past_the_hooks('stubs')


def titles(output):
    """The lines of a hook's summary that name a step."""
    return [line for line in output.splitlines() if line.startswith('pre-commit: ')]


class EverySuite(StubsOfEveryFolder):
    """sh .githooks/pre-commit --all [<suite>...]: every suite the hook knows, or those named, with nothing staged, for CI and by hand."""

    def test_it_runs_the_suites_of_every_folder(self):
        result = self.sh('.githooks/pre-commit', '--all')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for suite in ('TiaBridge unit tests', 'TiaChangeReports unit tests', 'pointer check tests', 'first setup tests'):
            self.assertIn(suite, result.stdout)

    def test_a_suite_that_fails_fails_it(self):
        self.suite('tools/setup', self.PASSES.replace('pass', 'self.fail()'))
        self.git('add', '-A')
        self.commit_past_the_hooks('a failing suite')
        result = self.sh('.githooks/pre-commit', '--all')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('first setup tests failed', result.stdout)

    def test_a_variable_of_the_environment_refuses_nothing(self):
        result = subprocess.run(['sh', '.githooks/pre-commit', '--all'], cwd=self.repo, capture_output=True, encoding='utf-8',
                                env={**CLEAN_ENV, 'docs_added_moved_removed': 'x', 'docs_deprecated': 'x'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_named_suites_run_alone(self):
        result = self.sh('.githooks/pre-commit', '--all', 'tiachangereports_unittest', 'pointer_check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(titles(result.stdout), ['pre-commit: TiaChangeReports unit tests', 'pre-commit: pointer check'])

    def test_a_name_of_no_suite_runs_nothing(self):
        result = self.sh('.githooks/pre-commit', '--all', 'tiabridge_pester', 'no_such_suite')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, 'pre-commit: no suite no_such_suite in this hook, nothing run\n')


class APlainCommitIgnoresTheVariablesOfTheHook(StubsOfEveryFolder):
    """The hook's own variables in the environment of a commit change nothing: it runs the suites of what is staged."""

    def setUp(self):
        super().setUp()
        self.put('tools/setup/a.py', '')
        self.git('add', 'tools/setup')

    def test_the_mode_of_ci(self):
        result = self.commit(mode='--groups')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: first setup tests', result.stdout + result.stderr)
        self.assertNotIn('"include"', result.stdout + result.stderr)

    def test_named_suites(self):
        result = self.commit(named_suites='parse_check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: first setup tests', result.stdout + result.stderr)


class TheJobsOfCI(StubsOfEveryFolder):
    """sh .githooks/pre-commit --groups: the matrix of CI's jobs, each long suite in a job of its own, the others in one."""

    def groups(self):
        result = self.sh('.githooks/pre-commit', '--groups')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)['include']

    def test_each_long_suite_has_a_job_and_the_others_share_one(self):
        self.assertEqual(self.groups(), [
            {'name': 'TiaBridge unit tests', 'suites': 'tiabridge_pester'},
            {'name': 'TiaChangeReports unit tests', 'suites': 'tiachangereports_unittest'},
            {'name': 'hook tests', 'suites': 'hooks_unittest'},
            {'name': 'the other suites', 'suites': 'parse_check tiaagentstatus_unittest pointer_check pointers_unittest '
                                                   'setup_unittest'}])

    def test_the_jobs_run_every_suite_once(self):
        every = titles(self.sh('.githooks/pre-commit', '--all').stdout)
        in_jobs = []
        for group in self.groups():
            result = self.sh('.githooks/pre-commit', '--all', *group['suites'].split())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            in_jobs += titles(result.stdout)
        self.assertEqual(sorted(in_jobs), sorted(every))


PASSES = 'import unittest\n\nclass T(unittest.TestCase):\n    def test(self):\n        pass\n'


class ABranchWithSuites(HookRepo):
    """A branch feature off main, with the stub suites of the folders FOLDERS committed on it."""
    FOLDERS = ()

    def stub(self, folder):
        return PASSES

    def setUp(self):
        super().setUp()
        self.put('.gitignore', '.scratch/\n.venv/\n__pycache__/\n')
        self.put('tools/__init__.py', '')
        self.git('add', '-A')
        self.commit_past_the_hooks('stubs')
        self.git('switch', '-q', '-c', 'feature')
        for folder in self.FOLDERS:
            self.put(f'{folder}/__init__.py', '')
            self.put(f'{folder}/tests/__init__.py', '')
            self.put(f'{folder}/tests/test_stub.py', self.stub(folder))
        self.git('add', '-A')
        self.commit_past_the_hooks('suites')

    def assertRan(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: parse check', result.stdout)
        self.assertNotIn('suites skipped', result.stdout)

    def assertSkipped(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: suites skipped, they passed on ', result.stdout)
        self.assertNotIn('pre-commit: parse check', result.stdout)


class AStampOfAPassingRun(ABranchWithSuites):
    """A run with a ref that passed is not run again for the same commit and the same commit of the ref."""
    FOLDERS = ('tools/setup',)
    # The stub fails with MAKE_IT_FAIL set and leaves the file LEAVE_A_FILE in the tree, so the commits stay the same.
    STUB = '''import os
import unittest
from pathlib import Path


class T(unittest.TestCase):
    def test(self):
        if os.environ.get('LEAVE_A_FILE'):
            Path(os.environ['LEAVE_A_FILE']).write_text('left')
        self.assertFalse(os.environ.get('MAKE_IT_FAIL'))
'''

    def stub(self, folder):
        return self.STUB

    def test_a_second_run_on_the_same_pair_skips_the_suites(self):
        self.assertRan(self.audit())
        self.assertSkipped(self.audit())

    def test_a_rebase_that_moves_nothing_keeps_the_pair(self):
        self.assertRan(self.audit())
        self.git('rebase', 'main')
        self.assertSkipped(self.audit())

    def test_a_new_commit_runs_them(self):
        self.assertRan(self.audit())
        self.put('tools/setup/more.py', '')
        self.git('add', '-A')
        self.commit_past_the_hooks('more')
        self.assertRan(self.audit())

    def test_a_moved_main_runs_them(self):
        self.assertRan(self.audit())
        self.git('switch', '-q', 'main')
        self.put('b.txt', 'on main\n')
        self.git('add', 'b.txt')
        self.commit_past_the_hooks('on main')
        self.git('switch', '-q', 'feature')
        self.assertRan(self.audit())

    def test_a_change_in_the_tree_runs_them_and_leaves_the_stamp_of_the_clean_tree(self):
        def staged():
            self.put('tools/setup/more.py', '')
            self.git('add', 'tools/setup/more.py')

        changes = {'staged': staged,
                   'not staged': lambda: self.put('tools/setup/__init__.py', '# changed\n'),
                   'a new file': lambda: self.put('tools/setup/more.py', '')}
        self.assertRan(self.audit())
        for name, change in changes.items():
            with self.subTest(name):
                change()
                result = self.audit()
                self.assertRan(result)
                self.assertIn('pre-commit: passed, no stamp: the tree held a change before the run (tools/setup/', result.stdout)
                self.git('reset', '-q', '--hard')
                self.git('clean', '-q', '-f', '--', 'tools')
                self.assertSkipped(self.audit())

    def test_a_new_file_runs_them_though_git_status_would_not_show_it(self):
        self.assertRan(self.audit())
        self.git('config', 'status.showUntrackedFiles', 'no')
        self.put('tools/setup/more.py', '')
        self.assertRan(self.audit())

    def test_the_audit_runs_them_whatever_the_stamp_says_and_stamps_for_the_merge(self):
        self.assertRan(self.audit())
        self.assertRan(self.audit(PRE_COMMIT_NO_SKIP='1'))
        self.assertSkipped(self.audit())

    def test_a_failing_run_leaves_no_stamp(self):
        for _ in range(2):
            result = self.audit(MAKE_IT_FAIL='1')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('first setup tests failed', result.stdout)

    def test_a_failing_run_takes_away_the_stamp_of_an_earlier_pass(self):
        self.assertRan(self.audit())
        failed = self.audit(PRE_COMMIT_NO_SKIP='1', MAKE_IT_FAIL='1')
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertRan(self.audit())

    def test_a_pass_that_changes_the_tree_says_it_left_no_stamp(self):
        result = self.audit(LEAVE_A_FILE='left.txt')
        self.assertRan(result)
        self.assertIn('pre-commit: passed, no stamp: the tree or a commit changed during the run (left.txt)', result.stdout)
        (self.repo / 'left.txt').unlink()
        self.assertRan(self.audit())

    def test_every_suite_never_skips(self):
        self.assertRan(self.audit())
        every = self.sh('.githooks/pre-commit', '--all').stdout
        self.assertIn('pre-commit: parse check', every)
        self.assertNotIn('suites skipped', every)

    def test_the_stamp_is_of_one_tree(self):
        self.assertRan(self.audit())
        other = self.folder / 'other'
        self.git('worktree', 'add', '-q', '--detach', str(other), 'feature')
        venv.create(other / '.venv', with_pip=False)
        self.assertRan(self.audit(cwd=other))
        self.assertSkipped(self.audit(cwd=other))
        self.assertSkipped(self.audit())


class SuitesSideBySide(ABranchWithSuites):
    """The suites run in the background, at most PRE_COMMIT_JOBS at once, each into its own log, the summary in order."""
    FOLDERS = ('TiaAgentStatus', 'tools/pointers', 'tools/setup')
    # Each stub waits in a meeting folder until MEETING_SIZE of them are there and two seconds more, or until the others
    # have come or gone, and writes how many it saw at once.
    MEETS = '''import os
import time
import unittest
from pathlib import Path

MEETING = Path(%r)


class T(unittest.TestCase):
    def test(self):
        here = MEETING / 'here'
        gone = MEETING / 'gone'
        here.mkdir(parents=True, exist_ok=True)
        gone.mkdir(exist_ok=True)
        me = here / %r
        me.touch()
        size = int(os.environ['MEETING_SIZE'])
        most = 0
        met = None
        end = time.monotonic() + 30
        while time.monotonic() < end:
            present = len(list(here.iterdir()))
            most = max(most, present)
            if present >= size and met is None:
                met = time.monotonic()
            if (met is not None and time.monotonic() - met > 2) or present + len(list(gone.iterdir())) >= 3:
                break
            time.sleep(0.05)
        (MEETING / ('most-' + me.name)).write_text(str(most))
        (gone / me.name).touch()
        me.unlink()
'''

    def stub(self, folder):
        return self.MEETS % (str(self.folder / 'meeting'), folder.replace('/', '-'))

    def most_at_once(self):
        return max(int(path.read_text()) for path in (self.folder / 'meeting').glob('most-*'))

    def test_they_run_two_at_once_by_default(self):
        result = self.audit(MEETING_SIZE='2')
        self.assertRan(result)
        self.assertEqual(self.most_at_once(), 2, result.stdout)

    def test_they_run_as_many_at_once_as_asked(self):
        result = self.audit(PRE_COMMIT_JOBS='3', MEETING_SIZE='3')
        self.assertRan(result)
        self.assertEqual(self.most_at_once(), 3, result.stdout)

    def test_the_summary_keeps_the_order_of_the_hook(self):
        result = self.audit(MEETING_SIZE='2')
        self.assertRan(result)
        titles = ['parse check', 'TiaAgentStatus unit tests', 'pointer check', 'pointer check tests', 'first setup tests']
        lines = [line for line in result.stdout.splitlines() if line.startswith('pre-commit: ')]
        self.assertEqual([line for line in lines if line[len('pre-commit: '):] in titles], ['pre-commit: ' + t for t in titles])

    def test_a_value_that_is_no_number_above_0_falls_back_to_two_and_says_so(self):
        for value in ('many', '00', '+3', '99999999999999999999999'):
            with self.subTest(value):
                result = self.audit(PRE_COMMIT_JOBS=value, MEETING_SIZE='2', PRE_COMMIT_NO_SKIP='1')
                self.assertRan(result)
                self.assertEqual(self.most_at_once(), 2, result.stdout)
                self.assertIn(f'PRE_COMMIT_JOBS is {value}, not a number above 0: 2 at once', result.stdout)
                shutil.rmtree(self.folder / 'meeting')


def ended(pid):
    """Whether the Windows process pid ends within ten seconds."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return True
    try:
        return kernel32.WaitForSingleObject(handle, 10000) == 0
    finally:
        kernel32.CloseHandle(handle)


class AStoppedRun(ABranchWithSuites):
    """A hook stopped while a suite runs in the background ends that suite."""
    FOLDERS = ('tools/setup',)
    WAITS = '''import os
import time
import unittest
from pathlib import Path


class T(unittest.TestCase):
    def test(self):
        Path(%r).write_text(str(os.getpid()))
        time.sleep(60)
'''

    def stub(self, folder):
        return self.WAITS % str(self.folder / 'pid')

    def test_it_ends_the_suites_still_running(self):
        pid = (self.folder / 'pid').as_posix()
        result = self.sh('-c', 'sh .githooks/pre-commit main & hook=$!; i=0; '
                               f'while [ ! -s "{pid}" ] && [ $i -lt 300 ]; do sleep 0.1; i=$((i + 1)); done; '
                               'kill $hook; wait $hook')
        self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
        self.assertIn('pre-commit: stopped, the steps still running ended', result.stdout)
        self.assertTrue(ended(int((self.folder / 'pid').read_text())))
        self.assertEqual(list((self.repo / '.git').glob('pre-commit-run.*')), [])


class FailingSuitesSideBySide(ABranchWithSuites):
    FOLDERS = ('tools/pointers', 'tools/setup')

    def stub(self, folder):
        return PASSES.replace('pass', f'print("{folder} broke"); self.fail()')

    def test_each_fails_the_hook_and_keeps_its_own_log(self):
        result = self.audit()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        out = result.stdout
        self.assertLess(out.index('pre-commit: pointer check tests failed, full output in '),
                        out.index('pre-commit: first setup tests failed, full output in '))
        self.assertIn('pre-commit: checks failed, commit refused', out)
        git_dir = self.repo / '.git'
        pointers = (git_dir / 'pointers-unittest.log').read_text(encoding='utf-8')
        setup = (git_dir / 'setup-unittest.log').read_text(encoding='utf-8')
        self.assertIn('tools/pointers broke', pointers)
        self.assertNotIn('tools/setup broke', pointers)
        self.assertIn('tools/setup broke', setup)
        self.assertNotIn('tools/pointers broke', setup)


class TheHead(unittest.TestCase):
    """The head of the hook, read by strangers: whose PC its times and limits are of."""

    def test_it_names_whose_pc(self):
        head = (ROOT / '.githooks/pre-commit').read_text(encoding='utf-8').split('\nfail=0\n')[0]
        self.assertIn("the maintainer's PC", head)
        self.assertNotRegex(head, r"\bthis (repo's )?PC\b")


class TheFunctions(unittest.TestCase):
    def test_none_hides_a_command_of_its_name(self):
        names = re.findall(r'^\s*([A-Za-z_]\w*)\(\) \{', (ROOT / '.githooks/pre-commit').read_text(encoding='utf-8'), re.M)
        self.assertIn('tested_pair', names)
        found = subprocess.run(['sh', '-c', 'for name; do command -v "$name"; done', 'sh', *names], env=CLEAN_ENV,
                               capture_output=True, encoding='utf-8')
        self.assertEqual(found.stdout, '')


class AParentsRepo(StubsOfEveryFolder):
    """Started by a git-aware parent (a hook or an alias of another repo), which leaves GIT_DIR and its like in the
    environment: with an argument no commit is going on, and the hook reads the repo it stands in."""
    FAILS_ON_A_NAME_OF_GITS = '''import os
import subprocess
import unittest


class T(unittest.TestCase):
    def test(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual([name for name in names if name in os.environ], [])
'''

    def setUp(self):
        super().setUp()
        self.parent = self.folder / 'parent'
        self.parent.mkdir()
        init_repo(self.parent)
        subprocess.run(['git', '-C', str(self.parent), 'commit', '-q', '--allow-empty', '-m', 'base'], check=True, env=CLEAN_ENV,
                       capture_output=True)
        self.context = {'GIT_DIR': str(self.parent / '.git'), 'GIT_WORK_TREE': str(self.parent)}

    def assertNoLogInTheParent(self):
        left = [path.name for path in (self.parent / '.git').iterdir() if path.name.startswith('pre-commit') or path.suffix == '.log']
        self.assertEqual(left, [])

    def test_a_run_with_a_ref_reads_its_own_branch(self):
        self.git('switch', '-q', '-c', 'feature')
        self.put('tools/setup/a.py', '')
        self.git('add', 'tools/setup')
        self.commit_past_the_hooks('a change of first setup')
        result = self.audit(**self.context)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: first setup tests', result.stdout)
        self.assertTrue((self.repo / '.git' / 'setup-unittest.log').is_file())
        self.assertNoLogInTheParent()

    def test_every_suite_is_of_its_own_tree(self):
        result = self.sh('.githooks/pre-commit', '--all', **self.context)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: first setup tests', result.stdout)
        self.assertNoLogInTheParent()

    def test_the_jobs_of_ci_are_of_its_own_tree(self):
        result = self.sh('.githooks/pre-commit', '--groups', **self.context)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('setup_unittest', result.stdout)

    def test_the_suites_of_a_commit_get_no_name_git_reads_a_repo_from(self):
        self.suite('tools/setup', self.FAILS_ON_A_NAME_OF_GITS)
        self.git('add', 'tools/setup')
        result = self.git('-c', 'core.abbrev=9', 'commit', '-m', 'a change', check=False)    # -c reaches a hook as GIT_CONFIG_PARAMETERS
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pre-commit: first setup tests', result.stdout + result.stderr)


class AnOuterRun(unittest.TestCase):
    """The hook runs these tests: its PRE_COMMIT_ variables, an audit's or a CI's, change no hook a test starts."""

    def test_its_variables_reach_no_inner_hook(self):
        env = {**{key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
               'PRE_COMMIT_NO_SKIP': '1', 'PRE_COMMIT_JOBS': '1'}
        inner = ['tools.hooks.tests.test_hooks.AStampOfAPassingRun.test_a_second_run_on_the_same_pair_skips_the_suites',
                 'tools.hooks.tests.test_hooks.SuitesSideBySide.test_they_run_two_at_once_by_default']
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', *inner], cwd=ROOT, env=env,
                                capture_output=True, encoding='utf-8', timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)


class WithNoVenv(HookRepo):
    """Python runs on the .venv of the tree: a commit that needs it is refused without one, any other goes through."""
    with_venv = False

    def test_a_commit_that_needs_python_is_refused(self):
        self.put('tools/setup/a.py', '')
        self.git('add', 'tools/setup')
        self.assertRefused(self.commit(), 'no .venv in this tree', 'uv sync')

    def test_any_other_commit_goes_through_without_the_pointer_check(self):
        self.put('a.txt', 'clean\n')
        self.git('add', 'a.txt')
        result = self.commit()
        self.assertCommitted(result)
        self.assertIn('no .venv in this tree, pointer check skipped', result.stdout + result.stderr)

    def test_the_jobs_of_ci_need_none(self):
        """CI asks for its jobs on a runner without the .venv."""
        self.put('TiaBridge/a.ps1', '')
        self.git('add', '-A')
        self.commit_past_the_hooks('the bridge')
        result = self.sh('.githooks/pre-commit', '--groups')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['include'][0], {'name': 'TiaBridge unit tests', 'suites': 'tiabridge_pester'})


if __name__ == '__main__':
    unittest.main()
