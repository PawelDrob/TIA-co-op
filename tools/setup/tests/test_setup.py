"""The setup command, run as a person or an agent runs it: in a temp clone, with a temp Claude config and fake claude and whoami."""
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from TiaAgentStatus.tests import fakes

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
REPO = TOOL.parents[1]
GIT_ENV = dict(os.environ)    # without the names git reads a repo from: __init__.py of this package drops them
PLUGIN = 'mattpocock-skills@claude-plugins-official'
SYSTEM = os.path.join(os.environ['SystemRoot'], 'System32')
IN_GROUP = r'MACHINE\Siemens TIA Openness'


def git_bash():
    """Git's bash, which Claude Code runs a status line with on Windows; not WSL's."""
    return next(p / 'bin' / 'bash.exe' for p in Path(shutil.which('git')).parents if (p / 'bin' / 'bash.exe').exists())


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args], env=GIT_ENV,
                          capture_output=True, text=True, check=True).stdout


class SetupCase(unittest.TestCase):
    def setUp(self):
        self.temp_folder = tempfile.TemporaryDirectory(prefix='setup-')     # it deletes git's read-only files, rmtree does not
        self.addCleanup(self.temp_folder.cleanup)
        self.temp = Path(self.temp_folder.name).resolve()
        self.clone = self.temp / 'clone'
        (self.clone / 'tools' / 'setup').mkdir(parents=True)
        (self.clone / 'TiaBridge').mkdir()
        shutil.copy(TOOL / 'setup.py', self.clone / 'tools' / 'setup')
        shutil.copy(TOOL / 'setup.ps1', self.clone / 'tools' / 'setup')
        (self.clone / 'TiaBridge' / 'TiaBridge.ps1').write_text('# bridge\n')
        (self.clone / '.claude').mkdir()
        self.tracked_settings = self.clone / '.claude' / 'settings.json'
        self.tracked_settings.write_text(json.dumps({'enabledPlugins': {PLUGIN: True}}))
        git(self.clone.parent, 'init', '-q', str(self.clone))
        git(self.clone, 'add', '-A')
        git(self.clone, 'commit', '-qm', 'first')
        self.config = self.temp / 'config'
        self.config.mkdir()
        self.tia = self.temp / 'Portal V20'
        (self.tia / 'PublicAPI' / 'V20').mkdir(parents=True)
        (self.tia / 'PublicAPI' / 'V20' / 'Siemens.Engineering.dll').write_text('dll')
        self.bridge_settings = self.clone / 'TiaBridge' / 'settings.json'
        self.bridge_settings.write_text(json.dumps({'tiaRoot': str(self.tia), 'archivesKept': 3}))
        self.user_settings = self.config / 'settings.json'
        self.fakes = self.temp / 'fakes'
        self.fakes.mkdir()
        shutil.copy(HERE / 'fake_claude.py', self.fakes)
        self.put_claude_on_the_path()
        self.system_root = self.temp / 'windows'
        (self.system_root / 'System32').mkdir(parents=True)
        (self.system_root / 'System32' / 'whoami.cmd').write_text('@echo "%FAKE_GROUP%","Alias","S-1-5-32-1","Enabled group"\n')
        self.fake('uv', '@echo uv')
        self.group = IN_GROUP
        self.extra_env = {}
        self.path = [str(self.fakes), str(Path(shutil.which('git')).parent), SYSTEM]

    def put_claude_on_the_path(self):
        self.fake('claude', f'@"{sys.executable}" "%~dp0fake_claude.py" %*')

    def fake(self, name, line):
        (self.fakes / f'{name}.cmd').write_text(line + '\n')

    def env(self):
        env = {k: v for k, v in GIT_ENV.items() if k != 'FAKE_CLAUDE_FAIL'}
        env.update(PATH=os.pathsep.join(self.path), CLAUDE_CONFIG_DIR=str(self.config), FAKE_GROUP=self.group, USERPROFILE=str(self.temp / 'home'))
        env.update(self.extra_env)
        return env

    def run_setup(self, *args, cwd=None):
        """Runs the tool in the clone; its exit code and what it printed."""
        done = subprocess.run([sys.executable, '-X', 'utf8', str(self.clone / 'tools' / 'setup' / 'setup.py'), *args], cwd=cwd or self.clone,
                              env={**self.env(), 'SystemRoot': str(self.system_root)}, capture_output=True, text=True, encoding='utf-8', stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(done.stderr, '')
        return done.returncode, done.stdout

    def answered(self):
        return self.run_setup('--projects-root', r'C:\Work\Repos')

    def calls(self):
        log = self.config / 'claude-calls.log'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def changes(self):
        return [c for c in self.calls() if c[:2] != ['plugin', 'list']]

    def user(self):
        return json.loads(self.user_settings.read_text(encoding='utf-8')) if self.user_settings.exists() else {}

    def allow(self):
        return self.user()['permissions']['allow']

    def stored(self):
        return json.loads(self.bridge_settings.read_text(encoding='ascii'))


class Cleanup(SetupCase):
    def test_the_temp_clone_goes_with_the_test(self):
        self.doCleanups()
        self.assertFalse(self.temp.exists())


class CleanupThatFails(unittest.TestCase):
    def test_a_folder_that_cannot_go_fails_the_test(self):
        class Holding(SetupCase):
            def runTest(self):
                self.held = (self.temp / 'held').open('w')

        case = Holding()
        result = unittest.TestResult()
        case.run(result)
        case.held.close()
        self.addCleanup(case.temp_folder.cleanup)
        self.assertIn('held', ''.join(text for _, text in result.errors))


class FreshClone(SetupCase):
    def test_sets_up_what_it_can_and_asks_for_the_projects_root(self):
        code, out = self.run_setup()

        self.assertEqual(code, 3, out)
        self.assertEqual(git(self.clone, 'config', '--local', 'core.hooksPath').strip(), '.githooks')
        script = str(self.clone / 'TiaBridge' / 'TiaBridge.ps1')
        self.assertIn(['mcp', 'add', '--scope', 'user', 'tia', '--', 'powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', script], self.calls())
        self.assertIn(['plugin', 'marketplace', 'add', 'anthropics/claude-plugins-official'], self.calls())
        self.assertIn(['plugin', 'install', PLUGIN, '--scope', 'user'], self.calls())
        self.assertIn('--projects-root', out)
        self.assertIn(str(self.temp / 'home' / 'TIA-Projects'), out)
        self.assertNotIn('projectsRoot', self.stored())
        self.assertNotIn('permissions', self.user())


class WithoutClaudeCode(SetupCase):
    def setUp(self):
        super().setUp()
        (self.fakes / 'claude.cmd').unlink()

    def person_steps(self, out):
        return out.split('A person does these, once:')[1]

    def test_it_is_no_failure_and_the_rest_still_runs(self):
        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertNotIn('missing', out)
        self.assertEqual(git(self.clone, 'config', '--local', 'core.hooksPath').strip(), '.githooks')
        self.assertEqual(self.stored()['projectsRoot'], r'C:\Work\Repos')
        self.assertIn('ok       TIA Portal V20', out)
        self.assertIn("ok       the Windows group 'Siemens TIA Openness'", out)

    def test_a_clone_that_no_longer_enables_the_plugin_is_named(self):
        self.tracked_settings.write_text('{}')

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('missing  .claude', out)
        self.assertIn('so a Claude Code session here goes without it', out)

    def test_what_holds_only_for_claude_code_says_so(self):
        _, out = self.answered()

        self.assertIn('each time it starts; with Claude Code, in every new session and at claude mcp get tia', out)
        self.assertIn('Claude Code allow rules for read, edit and git', out)

    def test_a_person_reads_what_it_left_out_once_with_the_command_for_their_agent(self):
        code, out = self.answered()

        self.assertEqual(code, 0, out)
        command = subprocess.list2cmdline(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', rf'{self.clone}\TiaBridge\TiaBridge.ps1'])
        self.assertEqual(out.count(command), 1, out)
        self.assertEqual(out.count('did not register'), 1, out)
        steps = self.person_steps(out)
        self.assertIn(command, steps)
        line = next(line for line in steps.splitlines() if command in line)
        self.assertIn('did not register the MCP server tia', line)
        self.assertIn(PLUGIN, line)
        self.assertIn('not on the PATH', line)
        self.assertIn('Tested with Claude Code only', line)
        self.assertIn('first connect', steps)

    def test_the_command_holds_a_clone_path_with_a_space_as_one_argument(self):
        spaced = self.temp / 'my clone'
        self.clone.rename(spaced)
        self.clone = spaced
        self.bridge_settings = spaced / 'TiaBridge' / 'settings.json'

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertIn(rf'-File "{spaced}\TiaBridge\TiaBridge.ps1"', out)

    def test_it_asks_no_person_for_a_claude_code_session(self):
        _, out = self.answered()

        self.assertNotIn('trust prompt', out)
        self.assertNotIn('tia_status', out)

    def test_the_first_run_still_asks_for_the_projects_root(self):
        code, out = self.run_setup()

        self.assertEqual(code, 3, out)
        self.assertIn('Question:', out)
        self.assertIn('did not register', out)

    def test_a_root_moved_while_claude_is_away_takes_the_old_rules_with_it(self):
        self.put_claude_on_the_path()
        self.run_setup('--projects-root', r'C:\Old\Repos')
        (self.fakes / 'claude.cmd').unlink()

        code, out = self.run_setup('--projects-root', r'C:\New\Repos')

        self.assertEqual(code, 0, out)
        self.assertIn('Read(//c/New/Repos/**)', self.allow())
        self.assertFalse([r for r in self.allow() if 'Old' in r], self.allow())

    def test_a_run_after_claude_code_came_does_what_it_left_out(self):
        self.answered()
        self.put_claude_on_the_path()

        code, out = self.run_setup()

        self.assertEqual(code, 0, out)
        self.assertNotIn('did not register', out)
        script = str(self.clone / 'TiaBridge' / 'TiaBridge.ps1')
        self.assertIn(['mcp', 'add', '--scope', 'user', 'tia', '--', 'powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', script], self.calls())
        self.assertIn(['plugin', 'install', PLUGIN, '--scope', 'user'], self.calls())
        self.assertIn('Read(//c/Work/Repos/**)', self.allow())


class WhatIsMissing(SetupCase):
    def test_all_there_says_what_a_person_does_next(self):
        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertNotIn('missing', out)
        self.assertIn('new session', out)
        self.assertIn('trust', out)
        self.assertIn('first connect', out)
        self.assertNotIn('did not register', out)

    def test_a_session_that_ran_setup_goes_on_with_its_task(self):
        _, out = self.answered()

        self.assertRegex(out, r'session in [^\n]* ran this setup[^\n]*claude --continue[^\n]*task[^\n]*Otherwise start a new session')

    def test_tia_v20_without_openness_is_named(self):
        (self.tia / 'PublicAPI' / 'V20' / 'Siemens.Engineering.dll').unlink()

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('missing  TIA Portal V20', out)
        self.assertIn(str(self.tia), out)
        self.assertIn('tiaRoot', out)

    def test_the_openness_group_is_named(self):
        self.group = r'BUILTIN\Users'

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn("missing  the Windows group 'Siemens TIA Openness'", out)
        self.assertIn('log off', out)

    def test_the_group_is_read_from_the_windows_whoami_not_one_on_the_path(self):
        # Git Bash puts its own whoami first, which prints the user's name and no groups: seen in a real run.
        self.fake('whoami', '@echo someone')

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertIn("ok       the Windows group 'Siemens TIA Openness'", out)

    def test_git_is_named(self):
        self.path.remove(str(Path(shutil.which('git')).parent))

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('missing  git', out)

    def test_a_missing_item_and_the_question_both_show(self):
        self.group = r'BUILTIN\Users'

        code, out = self.run_setup()

        self.assertEqual(code, 1, out)
        self.assertIn('missing', out)
        self.assertIn('Question', out)

    def test_another_hook_path_is_named_and_stays(self):
        git(self.clone, 'config', '--local', 'core.hooksPath', 'elsewhere')

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('missing  commit hook', out)
        self.assertIn('elsewhere', out)
        self.assertEqual(git(self.clone, 'config', '--local', 'core.hooksPath').strip(), 'elsewhere')

    def test_a_second_clone_gets_the_server_for_its_folder_and_the_first_keeps_its_own(self):
        other = r'C:\other\TiaBridge\TiaBridge.ps1'
        state = {'mcpServers': {'tia': {'type': 'stdio', 'command': 'powershell.exe', 'args': ['-File', other]}}}
        (self.config / '.claude.json').write_text(json.dumps(state))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        script = str(self.clone / 'TiaBridge' / 'TiaBridge.ps1')
        self.assertIn(['mcp', 'add', '--scope', 'local', 'tia', '--', 'powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', script], self.calls())
        self.assertEqual(json.loads((self.config / '.claude.json').read_text())['mcpServers'], state['mcpServers'])
        self.assertIn(other, out)
        self.assertIn('claude mcp remove --scope user tia', out)

        adds = len([c for c in self.calls() if c[:2] == ['mcp', 'add']])
        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['mcp', 'add']]), adds)
        self.assertIn(other, out)

    def test_this_clone_takes_user_scope_once_that_is_free(self):
        state = {'mcpServers': {'tia': {'type': 'stdio', 'command': 'powershell.exe', 'args': ['-File', r'C:\other\TiaBridge\TiaBridge.ps1']}}}
        state_file = self.config / '.claude.json'
        state_file.write_text(json.dumps(state))
        self.answered()
        now = json.loads(state_file.read_text())
        del now['mcpServers']['tia']
        state_file.write_text(json.dumps(now))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        script = str(self.clone / 'TiaBridge' / 'TiaBridge.ps1')
        self.assertEqual(json.loads(state_file.read_text())['mcpServers']['tia']['args'][-1], script)

    def test_a_tracked_file_that_no_longer_enables_the_plugin_is_named_and_stays(self):
        # What `claude plugin uninstall --scope project` leaves: seen on a real worktree.
        self.tracked_settings.write_text(json.dumps({'enabledPlugins': {}}))

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('missing  .claude', out)
        self.assertIn('git restore', out)
        self.assertEqual(json.loads(self.tracked_settings.read_text()), {'enabledPlugins': {}})

    def test_what_only_a_person_can_do_goes_in_one_list(self):
        (self.tia / 'PublicAPI' / 'V20' / 'Siemens.Engineering.dll').unlink()
        self.group = r'BUILTIN\Users'

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        steps = out[out.index('A person does these'):]
        self.assertIn('Install TIA Portal V20', steps)
        self.assertIn('Siemens TIA Openness', steps)
        self.assertIn('trust prompt', steps)
        self.assertIn('approve the plugin', steps)

    def test_a_failed_plugin_install_is_named(self):
        self.extra_env['FAKE_CLAUDE_FAIL'] = 'plugin install'

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn(f'missing  plugin {PLUGIN}', out)
        self.assertIn('Filename too long', out)

    def assert_failure_shows_its_cause(self, failing, step):
        self.extra_env['FAKE_CLAUDE_FAIL'] = failing

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn(f'missing  {step}', out)
        self.assertIn('Filename too long', out)
        self.assertIn('and the repository exists.', out)

    def test_a_failed_marketplace_shows_its_cause_where_it_stands_in_the_output(self):
        self.assert_failure_shows_its_cause('plugin marketplace', 'plugin')

    def test_a_failed_registration_shows_its_cause_where_it_stands_in_the_output(self):
        self.assert_failure_shows_its_cause('mcp add', 'MCP server tia')

    def test_a_long_failure_keeps_its_head_and_tail_and_says_how_much_went(self):
        # A real marketplace clone under a long path printed some 900 lines of one error.
        self.extra_env.update(FAKE_CLAUDE_FAIL='plugin marketplace', FAKE_CLAUDE_NOISE='3000')

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn('Filename too long', out)
        self.assertIn('and the repository exists.', out)
        self.assertIn('lines left out', out)
        self.assertLess(len(out.splitlines()), 70, out)

    def test_the_group_is_named_when_windows_has_no_whoami(self):
        # Never one from the PATH instead: that is the wrong answer the System32 lookup is there to stop.
        (self.system_root / 'System32' / 'whoami.cmd').unlink()

        code, out = self.answered()

        self.assertEqual(code, 1, out)
        self.assertIn("missing  the Windows group 'Siemens TIA Openness'", out)

    def test_an_entry_of_project_scope_does_not_count_as_installed(self):
        # What a session leaves for its clone, seen on a real machine.
        (self.config / 'fake-plugins.json').write_text(json.dumps([{'id': PLUGIN, 'scope': 'project', 'enabled': True, 'projectPath': str(self.clone)}]))

        self.answered()

        self.assertIn(['plugin', 'install', PLUGIN, '--scope', 'user'], self.calls())

    def test_a_failed_run_comes_right_on_the_next(self):
        self.extra_env['FAKE_CLAUDE_FAIL'] = 'plugin marketplace'
        self.answered()
        self.extra_env.clear()

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertIn(f'done     plugin {PLUGIN}', out)

    def test_nothing_tracked_changes(self):
        self.answered()
        self.answered()

        self.assertEqual(git(self.clone, 'status', '--short', '--', '.', ':!TiaBridge/settings.json'), '')


class Worktree(SetupCase):
    def test_a_worktree_is_refused_and_named_for_its_main_tree(self):
        tree = self.temp / 'the tree'
        git(self.clone, 'worktree', 'add', '-q', '-b', 'side', str(tree))
        (tree / 'tools' / 'setup').mkdir(parents=True, exist_ok=True)
        shutil.copy(TOOL / 'setup.py', tree / 'tools' / 'setup')
        self.clone, main = tree, self.clone

        code, out = self.run_setup()

        self.assertEqual(code, 1, out)
        self.assertIn(str(main), out)
        self.assertIn('worktree', out)
        self.assertEqual(self.calls(), [])
        self.assertFalse(git(tree, 'config', '--local', '--default', '', 'core.hooksPath').strip())


class Starter(SetupCase):
    def start(self):
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.clone / 'tools' / 'setup' / 'setup.ps1')],
                              env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)

    def test_no_uv_is_named_before_anything_else(self):
        (self.fakes / 'uv.cmd').unlink()

        done = self.start()

        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('missing  uv', done.stdout)
        self.assertIn('https://docs.astral.sh/uv/', done.stdout)

    def test_a_failed_uv_sync_is_named(self):
        self.fake('uv', '@exit /b 7')

        done = self.start()

        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('uv sync failed', done.stdout)


class StatusLine(SetupCase):
    def this_clone(self):
        forward = self.clone.as_posix()
        return f'"{forward}/.venv/Scripts/python.exe" -X utf8 "{forward}/TiaAgentStatus" statusline'

    def in_a_folder(self, name):
        moved = self.temp / name
        self.clone.rename(moved)
        self.clone = moved
        self.bridge_settings = moved / 'TiaBridge' / 'settings.json'
        return moved

    def test_a_fresh_home_gets_the_tia_row_of_this_clone(self):
        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], {'type': 'command', 'command': self.this_clone(), 'refreshInterval': 5})
        self.assertIn('done     status line', out)

    def assert_git_bash_reads_its_two_paths(self, name):
        moved = self.in_a_folder(name)
        code, out = self.answered()
        self.assertEqual(code, 0, out)

        words = subprocess.run([str(git_bash()), '-c', 'printf "%s\\n" ' + self.user()['statusLine']['command']],
                               capture_output=True, text=True, check=True).stdout.splitlines()

        self.assertEqual(words, [f'{moved.as_posix()}/.venv/Scripts/python.exe', '-X', 'utf8', f'{moved.as_posix()}/TiaAgentStatus', 'statusline'])
        code, out = self.answered()
        self.assertIn('ok       status line: the TIA row', out)

    def test_git_bash_reads_the_command_of_a_folder_with_a_space_as_its_two_paths(self):
        self.assert_git_bash_reads_its_two_paths('my clone')

    def test_git_bash_reads_the_command_of_a_folder_with_a_dollar_as_its_two_paths(self):
        self.assert_git_bash_reads_its_two_paths('a$b')

    def test_git_bash_reads_the_command_of_a_folder_with_a_backtick_as_its_two_paths(self):
        self.assert_git_bash_reads_its_two_paths('a`b')

    def test_the_command_setup_wrote_prints_the_row_of_the_bridge_of_its_session(self):
        spaced = self.in_a_folder('my clone')
        shutil.copytree(REPO / 'TiaAgentStatus', spaced / 'TiaAgentStatus', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        (spaced / '.venv' / 'Scripts').mkdir(parents=True)
        shutil.copy(REPO / '.venv' / 'pyvenv.cfg', spaced / '.venv')
        shutil.copy(REPO / '.venv' / 'Scripts' / 'python.exe', spaced / '.venv' / 'Scripts')
        projects = self.temp / 'projects'
        code, out = self.run_setup('--projects-root', str(projects))
        self.assertEqual(code, 0, out)
        # This test process stands in for the bridge of Claude process 4242 and for its TIA, as in TiaAgentStatus's tests. The row
        # reads the real process table, where a bridge process started over 5 s after its record's `started` is a reused pid:
        # a minute ahead puts `started` after this process's start.
        started = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
        fakes.write(projects / '_bridge' / 'sessions', fakes.state(os.getpid(), 4242, project='Plant A', tia=os.getpid(), window=False, started=started))

        done = subprocess.run([str(git_bash()), '-c', self.user()['statusLine']['command']], input='{"session_id": "x"}',
                              env={**self.env(), 'CLAUDE_PID': '4242'}, capture_output=True, text=True, encoding='utf-8', timeout=60)

        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertRegex(done.stdout, r'^TIA: Plant A · no window · idle · \d+ MB$')

    def test_a_re_run_leaves_a_right_entry_alone(self):
        self.answered()
        before = self.user_settings.read_bytes()

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user_settings.read_bytes(), before)
        self.assertIn('ok       status line: the TIA row', out)

    def test_an_entry_written_by_hand_as_the_readme_had_it_is_right(self):
        forward = self.clone.as_posix()
        mine = {'type': 'command', 'command': f'{forward}/.venv/Scripts/python.exe -X utf8 {forward}/TiaAgentStatus statusline'}
        self.user_settings.write_text(json.dumps({'statusLine': mine}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], mine)
        self.assertIn('ok       status line: the TIA row', out)

    def test_the_readme_form_by_hand_in_a_folder_with_a_space_is_not_right(self):
        spaced = self.in_a_folder('my clone')
        forward = spaced.as_posix()
        split = {'type': 'command', 'command': f'{forward}/.venv/Scripts/python.exe -X utf8 {forward}/TiaAgentStatus statusline'}
        self.user_settings.write_text(json.dumps({'statusLine': split}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], split)
        self.assertNotIn('ok       status line: the TIA row', out)
        self.assertIn(self.this_clone(), out)

    def assert_not_the_row(self, command):
        broken = {'type': 'command', 'command': command}
        self.user_settings.write_text(json.dumps({'statusLine': broken}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], broken)
        self.assertNotIn('status line: the TIA row', out)
        self.assertIn(self.this_clone(), out)

    def test_an_unquoted_path_with_backslashes_is_not_the_row(self):
        # Git Bash reads C:\x\.venv as C:x.venv
        self.assert_not_the_row(f'{self.clone}\\.venv\\Scripts\\python.exe -X utf8 {self.clone}\\TiaAgentStatus statusline')

    def test_a_quote_without_its_pair_is_not_the_row(self):
        forward = self.clone.as_posix()
        self.assert_not_the_row(f'{forward}/.venv/Scripts/python.exe" -X utf8 "{forward}/TiaAgentStatus" statusline')

    def test_the_python_of_another_clone_is_not_the_row(self):
        forward = self.clone.as_posix()
        self.assert_not_the_row(f'"D:/Other clone/.venv/Scripts/python.exe" -X utf8 "{forward}/TiaAgentStatus" statusline')

    def test_a_quoted_path_may_have_backslashes(self):
        mine = {'type': 'command', 'command': f'"{self.clone}\\.venv\\Scripts\\python.exe" -X utf8 "{self.clone}\\TiaAgentStatus" statusline'}
        self.user_settings.write_text(json.dumps({'statusLine': mine}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], mine)
        self.assertIn('ok       status line: the TIA row', out)

    def assert_a_bare_path_is_not_the_row(self, name):
        forward = self.in_a_folder(name).as_posix()
        self.assert_not_the_row(f'{forward}/.venv/Scripts/python.exe -X utf8 {forward}/TiaAgentStatus statusline')

    def test_a_bare_path_with_a_single_quote_is_not_the_row(self):
        self.assert_a_bare_path_is_not_the_row("a'b")

    def test_a_bare_path_with_a_parenthesis_is_not_the_row(self):
        self.assert_a_bare_path_is_not_the_row('a(b')

    def test_a_bare_path_with_a_semicolon_is_not_the_row(self):
        self.assert_a_bare_path_is_not_the_row('a;b')

    def test_a_bare_path_with_braces_is_not_the_row(self):
        self.assert_a_bare_path_is_not_the_row('{b,c}')

    def test_the_row_of_another_clone_is_named_and_stays(self):
        theirs = {'type': 'command', 'command': '"D:/Other clone/.venv/Scripts/python.exe" -X utf8 "D:/Other clone/TiaAgentStatus" statusline'}
        self.user_settings.write_text(json.dumps({'statusLine': theirs}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], theirs)
        line = next(line for line in out.splitlines() if 'status line' in line)
        self.assertIn(r'D:\Other clone', line)
        self.assertIn('then run this again', line)

    def test_a_status_line_of_the_users_own_stays_and_one_line_says_how_to_add_the_row(self):
        own = {'type': 'command', 'command': '~/bin/my-line.sh', 'padding': 0}
        self.user_settings.write_text(json.dumps({'statusLine': own}))

        code, out = self.answered()

        self.assertEqual(code, 0, out)
        self.assertEqual(self.user()['statusLine'], own)
        before = self.user_settings.read_bytes()
        self.answered()
        self.assertEqual(self.user_settings.read_bytes(), before)
        lines = [line for line in out.splitlines() if 'status line' in line]
        self.assertEqual(len(lines), 1, out)
        self.assertIn(self.this_clone(), lines[0])
        self.assertIn(str(self.clone / 'TiaAgentStatus' / 'README.md'), lines[0])


def load_setup():
    """setup.py under a name of its own: the name setup is setuptools'."""
    spec = importlib.util.spec_from_file_location('first_setup', TOOL / 'setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StatusLineAtADriveRoot(unittest.TestCase):
    """A temp clone cannot stand at a drive root, so this reads the command of one back without running setup."""

    def test_a_clone_at_a_drive_root_reads_back_as_itself(self):
        setup = load_setup()
        command = '"D:/.venv/Scripts/python.exe" -X utf8 "D:/TiaAgentStatus" statusline'

        self.assertEqual(setup.status_command(Path('D:\\')), command)
        self.assertTrue(setup.same_path(setup.clone_of({'type': 'command', 'command': command}), 'D:\\'))


class ProjectsRoot(SetupCase):
    def test_an_answer_goes_in_the_bridge_settings_and_the_allow_rules(self):
        self.user_settings.write_text(json.dumps({'model': 'opus', 'permissions': {'allow': ['Bash(ls:*)'], 'deny': ['Read(x)']}}))

        code, out = self.run_setup('--projects-root', r'c:\Work\TIA Repos')

        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored(), {'tiaRoot': str(self.tia), 'archivesKept': 3, 'projectsRoot': r'C:\Work\TIA Repos'})
        settings = json.loads(self.user_settings.read_text())
        self.assertEqual(settings['model'], 'opus')
        self.assertEqual(settings['permissions']['deny'], ['Read(x)'])
        # Forms seen to work on Claude Code 2.1.318; a backslash in a rule or a git command never matched.
        self.assertEqual(settings['permissions']['allow'], [
            'Bash(ls:*)',
            'Read(//c/Work/TIA Repos/**)', 'Edit(//c/Work/TIA Repos/**)',
            'Bash(git -C C:/Work/TIA Repos/*)', 'Bash(git -C "C:/Work/TIA Repos/*)',
            'PowerShell(git -C C:/Work/TIA Repos/*)', 'PowerShell(git -C "C:/Work/TIA Repos/*)',
        ])
        self.assertIn('git -C "C:/Work/TIA Repos/<repo>"', out)

    def test_setup_makes_no_folder_there_and_says_who_does(self):
        root = self.temp / 'repos'

        code, out = self.run_setup('--projects-root', str(root))

        self.assertEqual(code, 0, out)
        self.assertFalse(root.exists())
        self.assertIn(r'_bridge\sessions', out)

    def test_a_re_run_shows_the_stored_value_and_changes_nothing(self):
        self.run_setup('--projects-root', r'C:\Work\Repos')
        files = (self.bridge_settings.read_bytes(), self.user_settings.read_bytes(), git(self.clone, 'config', '--local', '--list'))
        calls = len(self.changes())

        code, out = self.run_setup()

        self.assertEqual(code, 0, out)
        self.assertIn(r'C:\Work\Repos', out)
        self.assertNotIn('Question', out)
        self.assertNotIn('done ', out)
        self.assertEqual(len(self.changes()), calls)
        self.assertEqual((self.bridge_settings.read_bytes(), self.user_settings.read_bytes(), git(self.clone, 'config', '--local', '--list')), files)

    def test_the_same_value_again_changes_nothing(self):
        self.run_setup('--projects-root', r'C:\Work\Repos')
        before = self.user_settings.read_bytes(), self.bridge_settings.read_bytes()

        code, out = self.run_setup('--projects-root', 'c:/work/repos/')

        self.assertEqual(code, 0, out)
        self.assertEqual((self.user_settings.read_bytes(), self.bridge_settings.read_bytes()), before)

    def test_a_changed_value_updates_setting_and_rules_and_moves_no_repo(self):
        old = self.temp / 'old'
        (old / 'ProjectA').mkdir(parents=True)
        (old / 'ProjectA' / 'file').write_text('x')
        self.user_settings.write_text(json.dumps({'permissions': {'allow': ['Bash(ls:*)']}}))
        self.run_setup('--projects-root', str(old))
        new = self.temp / 'new'

        code, out = self.run_setup('--projects-root', str(new))

        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored()['projectsRoot'], str(new))
        allow = self.allow()
        self.assertIn('Bash(ls:*)', allow)
        self.assertEqual(len(allow), 7)
        self.assertFalse([r for r in allow if '/old' in r], allow)
        self.assertTrue((old / 'ProjectA' / 'file').exists())
        self.assertFalse(new.exists())
        self.assertIn(str(old), out)

    def test_a_changed_value_says_what_it_does_to_another_clone_on_the_old_folder(self):
        old = self.temp / 'old'
        self.run_setup('--projects-root', str(old))

        code, out = self.run_setup('--projects-root', str(self.temp / 'new'))

        self.assertEqual(code, 0, out)
        self.assertIn('Another clone on the old folder loses these rules', out)
        self.assertIn('run setup in it', out)

    def test_a_rule_gone_comes_back(self):
        self.run_setup('--projects-root', r'C:\Work\Repos')
        self.user_settings.write_text('{}')

        code, out = self.run_setup()

        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.allow()), 6)

    def test_a_long_path_warns_with_the_room_left(self):
        code, out = self.run_setup('--projects-root', 'C:\\' + 'a' * 60)

        self.assertEqual(code, 0, out)
        self.assertIn('143', out)
        # 143 - 63 for the folder - 39 for the repo folder and archive name around two project names
        self.assertIn('20 characters', out)

    def test_a_short_path_does_not_warn(self):
        code, out = self.run_setup('--projects-root', r'C:\Users\Someone\TIA-Projects')

        self.assertEqual(code, 0, out)
        self.assertNotIn('143', out)

    def test_a_relative_path_is_refused_and_changes_nothing(self):
        for path in ('Repos', r'\\server\share\Repos', 'C:\\My Repos"'):
            with self.subTest(path):
                code, out = self.run_setup('--projects-root', path)

                self.assertEqual(code, 1, out)
                self.assertIn('--projects-root', out)
                self.assertNotIn('projectsRoot', self.stored())
                self.assertNotIn('permissions', self.user())

    def test_user_settings_that_cannot_be_read_stay_and_are_named(self):
        self.user_settings.write_text('{ not json')

        code, out = self.run_setup('--projects-root', r'C:\Work\Repos')

        self.assertEqual(code, 1, out)
        self.assertIn(str(self.user_settings), out)
        self.assertEqual(self.user_settings.read_text(), '{ not json')
        self.assertNotIn('projectsRoot', self.stored())

    def test_bridge_settings_that_cannot_be_read_stay_and_are_named(self):
        self.bridge_settings.write_text('{ not json')

        code, out = self.run_setup('--projects-root', r'C:\Work\Repos')

        self.assertEqual(code, 1, out)
        self.assertIn(str(self.bridge_settings), out)
        self.assertEqual(self.bridge_settings.read_text(), '{ not json')
        self.assertNotIn('permissions', self.user())

    def test_settings_with_a_byte_order_mark_are_read(self):
        self.user_settings.write_bytes(b'\xef\xbb\xbf{"model": "opus"}')
        self.bridge_settings.write_bytes(b'\xef\xbb\xbf' + json.dumps({'tiaRoot': str(self.tia)}).encode())

        code, out = self.run_setup('--projects-root', r'C:\Work\Repos')

        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.user_settings.read_text())['model'], 'opus')

    def test_bridge_settings_are_read_as_the_bridge_reads_them(self):
        # Windows PowerShell 5.1 goes by the byte order mark, else ANSI: `>` writes UTF-16, Notepad's "ANSI" no mark
        text = json.dumps({'tiaRoot': str(self.tia), 'projectsRoot': 'C:\\Users\\Müller\\Repos'}, ensure_ascii=False)
        for written in ('utf-16', 'mbcs'):
            with self.subTest(written):
                self.bridge_settings.write_bytes(text.encode(written))

                code, out = self.run_setup()

                self.assertEqual(code, 0, out)
                self.assertIn('projectsRoot C:\\Users\\Müller\\Repos. To change it', out)
                self.assertIn(f'TIA Portal V20 with TIA Openness, {self.tia}', out)
                self.assertEqual(self.bridge_settings.read_bytes(), text.encode(written))

    def test_a_name_outside_ascii_stays_readable_for_windows_powershell(self):
        # Windows PowerShell 5.1 reads a file with no byte order mark as ANSI, so the bridge's settings stay plain ASCII.
        code, out = self.run_setup('--projects-root', 'C:\\Users\\Zażółć\\Repos')

        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored()['projectsRoot'], 'C:\\Users\\Zażółć\\Repos')
        self.assertIn('Read(//c/Users/Zażółć/Repos/**)', self.allow())


class TheListOfGitsNames(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_it_holds_every_name_git_gives(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in load_setup().GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
