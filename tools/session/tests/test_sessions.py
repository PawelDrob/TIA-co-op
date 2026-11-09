"""Starting, prompting and closing, on a real temp git repo with a fake terminal in place of a real session."""
import _winapi
import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import session
from session import Sessions
from store import SessionError, record_hook, write_state
from terminals import NOT_READ, Herdr, HerdrFailed, report_resume

GIT_ENV = {k: v for k, v in os.environ.items() if k not in session.GIT_CONTEXT}
PUSH_RULES = ['Bash(git push:*)', 'Bash(git * push *)', 'Bash(git * push)',
              'PowerShell(git push:*)', 'PowerShell(git * push *)', 'PowerShell(git * push)']
STILL_HELD = (5, 32)    # Windows errors: access denied (a program's file still mapped), in use by another process


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args], env=GIT_ENV,
                          capture_output=True, text=True, check=True).stdout


class FakeTerminal:
    kind = 'fake'

    def __init__(self):
        self.opened, self.sent, self.ended = [], [], []
        self.holding = False
        self.on_prompt = lambda record, text: None
        self.living = True
        self.has_guards = None
        self.stopped = ''
        self.refusal = ''

    def restore_refused(self, args):
        self.refused_args = args
        return self.refusal

    def guarded(self, record):
        return self.has_guards

    def open(self, record, args, prompt):
        self.opened.append((dict(record), args, prompt))
        self.on_prompt(record, prompt)
        return {'tab': 't' + record['name']}

    def send(self, record, text):
        self.sent.append((record['name'], text))
        self.on_prompt(record, text)
        return {}

    def alive(self, record):
        return self.living

    def read(self, record, lines):
        return 'screen of ' + record['name']

    def holds_tree(self, record):
        return self.holding

    def end(self, record):
        self.ended.append(record['name'])
        return 'ended ' + record['name']


class Case(unittest.TestCase):
    reads_real_processes = False    # each look at the process list starts a PowerShell, about a second
    ends_real_processes = False    # True: close's wait for the tree to be let go pauses PAUSE s a try, as a handle can outlive its process
    PAUSE = 0.5

    def setUp(self):
        if not self.reads_real_processes:
            patcher = mock.patch('session.running_executables', return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)
        self.top = Path(tempfile.mkdtemp(prefix='session-test-')).resolve()
        self.addCleanup(self.remove_top)
        self.main = self.top / 'clone'
        self.main.mkdir()
        git(self.main, 'init', '-q', '-b', 'main')
        (self.main / 'a.txt').write_text('a', encoding='utf-8')
        (self.main / 'TiaArchiveCompare' / 'window').mkdir(parents=True)    # tracked, as in the clone: git status names window/bin
        (self.main / 'TiaArchiveCompare' / 'window' / 'README.md').write_text('w', encoding='utf-8')
        (self.main / '.gitignore').write_text('.scratch/\n.venv/\n__pycache__/\n/local/\n.playwright-mcp/\n', encoding='utf-8')
        git(self.main, 'add', '.')
        git(self.main, 'commit', '-q', '-m', 'first')
        self.scratch = self.main / '.scratch'
        self.ticket = self.write_ticket('ready-for-agent')
        (self.scratch / 'work' / 'map.md').write_text('# Map\n\n## Notes\n\nSessions: wk\n', encoding='utf-8')
        self.terminal = FakeTerminal()
        pause = (lambda s: time.sleep(self.PAUSE)) if self.ends_real_processes else (lambda s: None)
        self.sessions = Sessions(self.main, terminal_for=lambda kind: self.terminal, sleep=pause)
        self.commands = []
        real = self.sessions.git
        self.sessions.git = lambda *a, **k: (self.commands.append(a), real(*a, **k))[1]

    def remove_top(self):
        self.remove_folder(self.top)

    @staticmethod
    def remove_folder(folder, tries=100):
        """Windows can hold the folder, or a program copied into it, for a moment after the process has ended: `tries`
        attempts in all, 0.05 s apart, then it raises."""
        def writable(action, path, error):
            os.chmod(path, 0o700)
            action(path)
        for attempt in range(1, tries + 1):
            try:
                shutil.rmtree(folder, onexc=writable)
                return
            except OSError as error:
                if error.winerror not in STILL_HELD or attempt == tries:
                    raise
                time.sleep(0.05)

    def write_ticket(self, status, name='03-some-thing.md'):
        folder = self.scratch / 'work' / 'issues'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(f'# 03 Some thing\n\nType: task\nStatus: {status}\nBlocked by: none\n', encoding='utf-8')
        return path

    def session_claims_the_ticket(self, record, text):
        if text.startswith('/ticket'):
            self.write_ticket('claimed')
            write_state(self.sessions.store.folder(record['name']), 'ended', f'Ready: send `/mattpocock-skills:implement {self.ticket}`')

    def started(self, **options):
        self.terminal.on_prompt = self.session_claims_the_ticket
        return self.sessions.start(self.ticket, terminal='fake', coordinator='the lead', **options)

    @property
    def tree(self):
        return self.top / 'clone-worktrees' / 'work-03'

    def merged(self):
        """The ticket's branch, with a commit, merged into main."""
        (self.tree / 'b.txt').write_text('b', encoding='utf-8')
        git(self.tree, 'add', 'b.txt')
        git(self.tree, 'commit', '-q', '-m', 'work')
        git(self.main, 'merge', '-q', '--ff-only', 'feat/work-03-some-thing')

    def trees(self):
        return git(self.main, 'worktree', 'list')

    def branches(self):
        return git(self.main, 'branch', '--list')


class StartTests(Case):
    def test_it_makes_the_worktree_and_branch_from_the_ticket(self):
        self.started()
        self.assertIn(str(self.tree).replace('\\', '/'), self.trees())
        self.assertIn('feat/work-03-some-thing', self.branches())
        self.assertEqual(git(self.tree, 'branch', '--show-current').strip(), 'feat/work-03-some-thing')

    def test_the_session_is_named_by_the_prefix_on_the_map(self):
        self.started()
        self.assertEqual(self.terminal.opened[0][0]['name'], 'wk03')

    def test_without_a_map_the_effort_names_it(self):
        (self.scratch / 'work' / 'map.md').unlink()
        self.started()
        self.assertEqual(self.terminal.opened[0][0]['name'], 'work03')

    def test_it_denies_questions_the_bridge_and_pushing(self):
        self.started()
        _, args, _ = self.terminal.opened[0]
        denied = args[args.index('--disallowedTools') + 1:]
        for rule in ['AskUserQuestion', 'mcp__tia__*', *PUSH_RULES]:
            self.assertIn(rule, denied)
        self.assertEqual(args[args.index('--add-dir') + 1], str(self.main))

    def test_a_ticket_with_a_granted_background_session_keeps_the_bridge(self):
        self.started(allow_tia=True)
        _, args, _ = self.terminal.opened[0]
        self.assertNotIn('mcp__tia__*', args)
        self.assertIn('Bash(git push:*)', args)

    def test_extra_arguments_reach_the_agent(self):
        self.started(extra=['--permission-mode', 'auto'])
        self.assertEqual(self.terminal.opened[0][1][-2:], ['--permission-mode', 'auto'])

    def test_a_hook_during_the_first_prompt_finds_the_arguments_of_the_session(self):
        seen = []
        self.terminal.on_prompt = lambda record, text: seen.append(json.loads((Path(record['folder']) / 'session.json').read_text(encoding='utf-8')))
        self.sessions.start(self.ticket, 'c', terminal='fake', implement=False, extra=['--permission-mode', 'auto'])
        self.assertEqual(seen[0]['args'], self.terminal.opened[0][1])
        self.assertEqual(seen[0]['args'][-2:], ['--permission-mode', 'auto'])

    def test_the_hooks_of_the_session_write_to_its_folder(self):
        self.started()
        _, args, _ = self.terminal.opened[0]
        settings = json.loads(Path(args[args.index('--settings') + 1]).read_text('utf-8'))
        for event in ('Stop', 'StopFailure', 'UserPromptSubmit', 'Notification', 'SessionStart'):
            command = settings['hooks'][event][0]['hooks'][0]['command']
            self.assertIn('hook', command)
            self.assertIn((self.scratch / 'sessions' / 'wk03').as_posix(), command)
            self.assertNotIn('\\', command)

    def test_the_first_prompt_names_ticket_tree_branch_coordinator_and_neighbours(self):
        self.started(beside='wk04 on tools')
        self.assertEqual(self.terminal.opened[0][2],
                         f'/ticket {self.ticket} worktree {self.tree} branch feat/work-03-some-thing '
                         'coordinator the lead beside wk04 on tools')

    def test_implement_follows_once_the_ticket_is_claimed_and_the_turn_has_ended(self):
        self.started()
        self.assertEqual(self.terminal.sent, [('wk03', f'/mattpocock-skills:implement {self.ticket}')])

    def test_a_turn_that_ends_on_a_question_gets_no_implement(self):
        def asks(record, text):
            write_state(self.sessions.store.folder(record['name']), 'ended', 'Which branch do you mean?')
        self.terminal.on_prompt = asks
        with self.assertRaisesRegex(session.NotReady, r'Which branch do you mean\?[\s\S]*prompt wk03 --implement'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead')
        self.assertEqual(self.terminal.sent, [])

    def test_a_ticket_claimed_earlier_and_a_turn_that_ends_on_a_question_gets_no_implement(self):
        self.write_ticket('claimed')
        def asks(record, text):
            write_state(self.sessions.store.folder(record['name']), 'ended', 'Which branch do you mean?')
        self.terminal.on_prompt = asks
        with self.assertRaisesRegex(session.NotReady, r'Which branch do you mean\?'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead')
        self.assertEqual(self.terminal.sent, [])

    def test_a_turn_that_left_background_tasks_is_not_ready_yet(self):
        def waits(record, text):
            self.write_ticket('claimed')
            write_state(self.sessions.store.folder(record['name']), 'ended', f'Ready: send {session.IMPLEMENT}', background=1)
        self.terminal.on_prompt = waits
        with self.assertRaisesRegex(session.NotReady, 'not ready after 3 seconds'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead', timeout=3)
        self.assertEqual(self.terminal.sent, [])

    def test_a_command_herdr_will_refuse_for_a_restart_is_said_at_the_start(self):
        self.terminal.refusal = 'an apostrophe in an argument'
        said = self.started()
        self.assertIn('herdr will refuse the command that brings it back after a restart (an apostrophe in an argument)', said)
        self.assertEqual(self.terminal.refused_args, self.terminal.opened[0][1])
        self.assertTrue(self.terminal.sent, 'it still starts')

    def test_a_command_herdr_takes_says_nothing_of_it(self):
        self.assertNotIn('restart', self.started())

    def test_a_relative_folder_is_refused_before_anything_is_made(self):
        with self.assertRaisesRegex(SessionError, 'absolute'):
            self.started(worktree='rel-tree')
        self.assertNotIn('rel-tree', self.trees())
        self.assertEqual(self.terminal.opened, [])

    def test_a_folder_inside_the_clone_is_refused(self):
        with self.assertRaisesRegex(SessionError, 'inside the clone'):
            self.started(worktree=str(self.main / '.scratch' / 'tree'))
        self.assertEqual(self.terminal.opened, [])

    def test_a_session_counts_as_open_only_once_its_terminal_has_opened(self):
        seen = []
        real = self.terminal.open
        def looks(record, args, prompt):
            seen.append(self.sessions.store.open_sessions())
            seen.append(self.sessions.store.load(record['name'])['made_tree'])
            return real(record, args, prompt)
        self.terminal.open = looks
        self.started()
        self.assertEqual(seen, [[], True])
        self.assertEqual([r['name'] for r in self.sessions.store.open_sessions()], ['wk03'])

    def test_a_watcher_running_through_a_start_does_not_call_it_gone(self):
        watcher = self.sessions.watcher()
        watcher.look()
        self.terminal.living = False
        events = []
        real = self.terminal.open
        def looks(record, args, prompt):
            events.extend(watcher.look())
            return real(record, args, prompt)
        self.terminal.open = looks
        self.sessions.start(self.ticket, terminal='fake', coordinator='x', implement=False)
        self.assertEqual(events, [])

    def test_a_branch_and_a_folder_can_be_named(self):
        other = self.top / 'elsewhere'
        self.started(branch='feat/short', worktree=str(other))
        self.assertEqual(git(other, 'branch', '--show-current').strip(), 'feat/short')
        self.assertEqual(self.terminal.opened[0][0]['worktree'], str(other))

    def test_a_tree_made_earlier_counts_as_made_only_for_that_same_tree(self):
        self.started()
        self.sessions.close('wk03', session_only=True)
        other = self.top / 'not-mine'
        git(self.main, 'worktree', 'add', '-q', str(other), '-b', 'not-mine', 'main')
        self.write_ticket('ready-for-agent')
        self.started(branch='not-mine', worktree=str(other))
        self.assertFalse(self.sessions.store.load('wk03')['made_tree'])

    def test_a_session_asking_permission_stops_the_wait(self):
        def asks(record, text):
            write_state(self.sessions.store.folder(record['name']), 'asking', 'needs permission for Bash')
        self.terminal.on_prompt = asks
        with self.assertRaisesRegex(session.NotReady, 'needs permission for Bash'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead')

    def test_a_session_that_is_gone_stops_the_wait(self):
        self.terminal.living = False
        with self.assertRaisesRegex(session.NotReady, 'no longer runs'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead')

    def test_the_wait_has_an_end(self):
        with self.assertRaisesRegex(session.NotReady, r'not ready after 0 seconds'):
            self.sessions.start(self.ticket, terminal='fake', coordinator='the lead', timeout=0)

    def test_no_implement_asked_for_means_no_wait(self):
        self.sessions.start(self.ticket, terminal='fake', coordinator='the lead', implement=False)
        self.assertEqual(self.terminal.sent, [])

    def test_a_closed_ticket_is_refused(self):
        for status in ('done', 'wontfix', 'resolved'):
            self.write_ticket(status)
            with self.assertRaisesRegex(SessionError, status):
                self.started()
        self.assertEqual(self.terminal.opened, [])

    def test_a_ticket_outside_an_issues_folder_is_refused(self):
        other = self.scratch / 'loose.md'
        other.write_text('Status: ready-for-agent\n', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, 'issues'):
            self.sessions.start(other, terminal='fake', coordinator='x')

    def test_a_name_already_open_is_refused_and_opens_nothing(self):
        self.started()
        with self.assertRaisesRegex(SessionError, 'wk03 is open'):
            self.started()
        self.assertEqual(len(self.terminal.opened), 1)

    def test_a_name_that_is_not_one_is_refused_before_a_worktree_is_made(self):
        with self.assertRaisesRegex(SessionError, 'not a session name'):
            self.started(name='A b')
        self.assertFalse(self.tree.exists())

    def test_an_existing_tree_on_its_branch_is_used_and_not_counted_as_made(self):
        git(self.main, 'worktree', 'add', '-q', str(self.tree), '-b', 'feat/work-03-some-thing', 'main')
        self.started()
        self.assertFalse(self.sessions.store.load('wk03')['made_tree'])

    def test_a_tree_on_another_branch_is_refused(self):
        git(self.main, 'worktree', 'add', '-q', str(self.tree), '-b', 'other', 'main')
        with self.assertRaisesRegex(SessionError, 'other'):
            self.started()
        self.assertEqual(self.terminal.opened, [])

    def test_a_folder_in_the_way_is_refused(self):
        self.tree.mkdir(parents=True)
        with self.assertRaisesRegex(SessionError, 'not a worktree'):
            self.started()

    def test_a_terminal_that_fails_leaves_no_open_session(self):
        def fails(record, args, prompt):
            raise SessionError('no terminal')
        self.terminal.open = fails
        with self.assertRaisesRegex(SessionError, 'no terminal'):
            self.started()
        self.assertEqual(self.sessions.store.open_sessions(), [])
        self.assertTrue(self.tree.exists())


def load_first_setup():
    """tools/setup/setup.py, under a name of its own: the name setup is setuptools'."""
    path = Path(__file__).resolve().parents[2] / 'setup' / 'setup.py'
    spec = importlib.util.spec_from_file_location('first_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServerTests(Case):
    """Claude reads --strict-mcp-config as: only what --mcp-config names. Tried with a real claude: no server of a plugin, of the user or of claude.ai starts."""

    def args(self):
        return self.terminal.opened[-1][1]

    def servers(self):
        """The servers a session's arguments give it, by name."""
        args = self.args()
        self.assertIn('--strict-mcp-config', args)
        if '--mcp-config' not in args:
            return {}
        return json.loads(Path(args[args.index('--mcp-config') + 1]).read_text(encoding='utf-8'))['mcpServers']

    def test_a_session_gets_no_server_unless_it_asks(self):
        self.started()
        self.assertEqual(self.servers(), {})
        self.assertIn('mcp__tia__*', self.args())

    def test_claude_in_chrome_stays_out_as_strict_leaves_its_tools_listed(self):
        self.started(allow_browser=True)
        self.assertIn('--no-chrome', self.args())

    def test_allow_tia_starts_the_bridge_of_this_clone(self):
        self.started(allow_tia=True)
        self.assertEqual(self.servers(), {'tia': {
            'type': 'stdio', 'command': 'powershell.exe',
            'args': ['-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(self.main / 'TiaBridge' / 'TiaBridge.ps1')]}})
        self.assertNotIn('mcp__tia__*', self.args())

    def test_allow_browser_starts_playwright_and_leaves_the_bridge_out(self):
        self.started(allow_browser=True)
        self.assertEqual(self.servers(), {'playwright': {'type': 'stdio', 'command': 'npx', 'args': ['@playwright/mcp@latest']}})
        self.assertIn('mcp__tia__*', self.args())

    def test_the_bridge_starts_as_first_setup_registers_it_for_a_plain_claude(self):
        first_setup = load_first_setup()
        self.started(allow_tia=True)
        bridge = self.servers()['tia']
        *flags, script = [bridge['command'], *bridge['args']]
        *setup_flags, setup_script = first_setup.BRIDGE_COMMAND
        self.assertEqual(flags, setup_flags)
        self.assertEqual(Path(script).relative_to(self.main), Path(setup_script).relative_to(first_setup.CLONE))

    def test_both_can_be_asked_for(self):
        self.started(allow_tia=True, allow_browser=True)
        self.assertEqual(sorted(self.servers()), ['playwright', 'tia'])

    def test_their_config_is_a_file_in_the_session_folder(self):
        self.started(allow_tia=True)
        args = self.args()
        self.assertEqual(Path(args[args.index('--mcp-config') + 1]), self.scratch / 'sessions' / 'wk03' / 'mcp.json')

    def test_extra_arguments_still_come_last(self):
        self.started(allow_browser=True, extra=['--permission-mode', 'auto'])
        self.assertEqual(self.args()[-2:], ['--permission-mode', 'auto'])

    def test_the_arguments_kept_for_a_restart_are_the_ones_it_started_with(self):
        self.started(allow_tia=True, extra=['--permission-mode', 'auto'])
        record, args, _ = self.terminal.opened[-1]
        reported = []
        report_resume(self.sessions.store.load(record['name']), {'hook_event_name': 'Stop', 'session_id': 'abc-1'},
                      {'HERDR_PANE_ID': 'w:p1'}, reported.append)
        self.assertEqual(reported[0][-len(args):], args)
        self.assertIn('--strict-mcp-config', reported[0])
        self.assertIn('--mcp-config', reported[0])

    def test_an_audit_gets_no_server_unless_it_asks(self):
        self.started(allow_tia=True, allow_browser=True)
        self.sessions.audit('wk03', terminal='fake')
        self.assertEqual(self.servers(), {})
        self.assertIn('mcp__tia__*', self.args())

    def test_an_audit_keeps_a_server_named_after_the_two_dashes_as_it_keeps_all_of_that(self):
        self.started(extra=['--mcp-config', 'other.json'])
        self.sessions.audit('wk03', terminal='fake')
        self.assertEqual(self.args()[-2:], ['--mcp-config', 'other.json'])

    def test_an_audit_can_ask_for_each(self):
        self.started()
        self.sessions.audit('wk03', terminal='fake', allow_browser=True)
        self.assertEqual(sorted(self.servers()), ['playwright'])
        self.sessions.close('auditwk03', session_only=True)
        self.sessions.audit('wk03', terminal='fake', allow_tia=True)
        self.assertEqual(sorted(self.servers()), ['tia'])

    def test_the_command_line_reaches_both_commands(self):
        with mock.patch.object(session, 'main_tree', return_value=self.main), mock.patch.object(session, 'Sessions') as sessions, \
                mock.patch('builtins.print'):
            sessions.return_value.start.return_value = sessions.return_value.audit.return_value = ''
            session.main(['start', 't', '--coordinator', 'c', '--allow-browser'])
            session.main(['audit', 'wk03', '--allow-tia'])
        started, audited = sessions.return_value.start.call_args.kwargs, sessions.return_value.audit.call_args.kwargs
        self.assertEqual((started['allow_tia'], started['allow_browser']), (False, True))
        self.assertEqual((audited['allow_tia'], audited['allow_browser']), (True, False))


class AuditTests(Case):
    def test_a_fresh_session_works_in_the_tickets_tree_with_the_audit_prompt(self):
        self.started()
        self.sessions.audit('wk03', terminal='fake')
        record, args, prompt = self.terminal.opened[-1]
        self.assertEqual(record['name'], 'auditwk03')
        self.assertEqual(record['worktree'], str(self.tree))
        self.assertEqual(prompt, f'/audit {self.ticket} feat/work-03-some-thing {self.tree}')
        self.assertIn('Bash(git push:*)', args)

    def test_a_command_herdr_will_refuse_for_a_restart_is_said_for_an_audit_too(self):
        self.started()
        self.terminal.refusal = 'more than 64 arguments'
        self.assertIn('herdr will refuse', self.sessions.audit('wk03', terminal='fake'))

    def test_a_typo_opens_nothing(self):
        self.started()
        with self.assertRaisesRegex(SessionError, 'no session named wk3'):
            self.sessions.audit('wk3', terminal='fake')
        self.assertEqual(len(self.terminal.opened), 1)

    def test_it_runs_with_the_agent_arguments_of_the_ticket_session(self):
        self.started(extra=['--permission-mode', 'auto'])
        self.sessions.audit('wk03', terminal='fake')
        self.assertEqual(self.terminal.opened[-1][1][-2:], ['--permission-mode', 'auto'])

    def test_arguments_of_its_own_take_their_place(self):
        self.started(extra=['--permission-mode', 'auto'])
        self.sessions.audit('wk03', terminal='fake', extra=['--model', 'x'])
        self.assertEqual(self.terminal.opened[-1][1][-2:], ['--model', 'x'])
        self.assertNotIn('--permission-mode', self.terminal.opened[-1][1])


class PromptTests(Case):
    def test_a_typo_reaches_no_session(self):
        self.started()
        self.terminal.sent.clear()
        with self.assertRaisesRegex(SessionError, 'no session named wk3.*wk03'):
            self.sessions.prompt('wk3', 'hello')
        self.assertEqual(self.terminal.sent, [])

    def test_a_closed_session_gets_nothing(self):
        self.started()
        self.terminal.sent.clear()
        self.sessions.close('wk03', session_only=True)
        with self.assertRaisesRegex(SessionError, 'closed'):
            self.sessions.prompt('wk03', 'hello')
        self.assertEqual(self.terminal.sent, [])

    def test_a_prompt_clears_the_last_turns_end(self):
        self.started()
        self.sessions.prompt('wk03', 'hello')
        self.assertEqual(self.sessions.store.state('wk03')['state'], 'sent')
        self.assertEqual(self.terminal.sent[-1], ('wk03', 'hello'))

    def test_a_terminal_sees_the_last_turns_end_when_the_prompt_reaches_it(self):
        self.started()
        write_state(self.sessions.store.folder('wk03'), 'ended', 'x')
        seen = []
        self.terminal.on_prompt = lambda record, text: seen.append(self.sessions.store.state('wk03')['state'])
        self.sessions.prompt('wk03', 'hello')
        self.assertEqual(seen, ['ended'])

    def test_a_hook_that_answers_before_the_prompt_returns_is_not_overwritten(self):
        self.started()
        self.terminal.on_prompt = lambda record, text: write_state(self.sessions.store.folder('wk03'), 'working')
        self.sessions.prompt('wk03', 'hello')
        self.assertEqual(self.sessions.store.state('wk03')['state'], 'working')

    def test_a_refused_prompt_leaves_the_state_alone(self):
        self.started()
        write_state(self.sessions.store.folder('wk03'), 'ended', 'x')
        def refuses(record, text):
            raise SessionError('busy')
        self.terminal.send = refuses
        with self.assertRaises(SessionError):
            self.sessions.prompt('wk03', 'hello')
        self.assertEqual(self.sessions.store.state('wk03')['state'], 'ended')

    def test_implement_sends_the_tickets_own_prompt(self):
        self.sessions.start(self.ticket, terminal='fake', coordinator='x', implement=False)
        self.sessions.implement('wk03')
        self.assertEqual(self.terminal.sent, [('wk03', f'/mattpocock-skills:implement {self.ticket}')])

    def test_a_prompt_git_bash_turned_into_a_path_is_refused(self):
        self.assertTrue(session.mangled_by_git_bash('C:/Program Files/Git/ticket foo', {'MSYSTEM': 'MINGW64'}))
        self.assertFalse(session.mangled_by_git_bash('look at C:/Program Files/Git/x', {'MSYSTEM': 'MINGW64'}))
        self.assertFalse(session.mangled_by_git_bash('C:/Program Files/Git/ticket foo', {}))


class CloseTests(Case):
    def commands_run(self):
        """Without their paths: a temp path may hold any word."""
        return [' '.join(arg for arg in c if not Path(arg).is_absolute()) for c in self.commands]

    def test_after_the_merge_it_ends_the_session_and_removes_tree_and_branch(self):
        self.started()
        self.merged()
        self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertNotIn('work-03', self.trees())
        self.assertNotIn('feat/work-03', self.branches())
        self.assertEqual(self.sessions.store.open_sessions(), [])

    def test_a_typo_closes_nothing(self):
        self.started()
        with self.assertRaisesRegex(SessionError, 'no session named wk3'):
            self.sessions.close('wk3')
        self.assertEqual(self.terminal.ended, [])

    def test_an_unmerged_branch_is_refused_with_the_session_still_running(self):
        self.started()
        (self.tree / 'b.txt').write_text('b', encoding='utf-8')
        git(self.tree, 'add', 'b.txt')
        git(self.tree, 'commit', '-q', '-m', 'work')
        with self.assertRaisesRegex(SessionError, 'not merged'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue(self.tree.exists())

    def test_uncommitted_changes_are_refused_and_named(self):
        self.started()
        self.merged()
        (self.tree / 'a.txt').write_text('changed', encoding='utf-8')
        (self.tree / 'new.txt').write_text('new', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, r'uncommitted[\s\S]*a\.txt[\s\S]*new\.txt'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertEqual((self.tree / 'a.txt').read_text('utf-8'), 'changed')

    def test_ignored_files_are_refused_and_named_as_git_would_delete_them_unasked(self):
        self.started()
        self.merged()
        (self.tree / 'local').mkdir()
        (self.tree / 'local' / 'notes.md').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, r'ignored[\s\S]*local'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue((self.tree / 'local' / 'notes.md').exists())

    def test_what_uv_sync_and_python_make_again_does_not_stop_it(self):
        self.started()
        self.merged()
        for folder in ('.venv', 'tools/__pycache__'):
            (self.tree / folder).mkdir(parents=True)
            (self.tree / folder / 'x').write_text('x', encoding='utf-8')
        self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())

    def leave_what_tools_leave(self):
        """A browser's .playwright-mcp, ignored as in the clone, and the old window build, which the clone no longer ignores."""
        for folder in ('.playwright-mcp', 'TiaArchiveCompare/window/bin/Debug'):
            (self.tree / folder).mkdir(parents=True)
            (self.tree / folder / 'x').write_text('x', encoding='utf-8')

    def test_what_a_sessions_tools_leave_goes_with_the_tree(self):
        self.started()
        self.merged()
        self.leave_what_tools_leave()
        said = self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())
        self.assertNotIn('work-03', self.trees())
        self.assertIn('TiaArchiveCompare', said)
        self.assertFalse(any('--force' in c for c in self.commands_run()))

    def test_beside_those_any_other_stray_file_is_refused_and_nothing_deleted(self):
        self.started()
        self.merged()
        self.leave_what_tools_leave()
        (self.tree / 'TiaArchiveCompare' / 'window' / 'notes.md').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, r'uncommitted[\s\S]*notes\.md'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue((self.tree / '.playwright-mcp' / 'x').exists())
        self.assertTrue((self.tree / 'TiaArchiveCompare' / 'window' / 'bin' / 'Debug' / 'x').exists())

    def test_such_a_folder_holding_a_tracked_file_is_refused_before_the_session_ends(self):
        self.started()
        bin_folder = self.tree / 'TiaArchiveCompare' / 'window' / 'bin'
        bin_folder.mkdir()
        (bin_folder / 'kept.txt').write_text('k', encoding='utf-8')
        git(self.tree, 'add', 'TiaArchiveCompare/window/bin/kept.txt')
        self.merged()
        (bin_folder / 'built.exe').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, r'uncommitted[\s\S]*built\.exe'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue((bin_folder / 'built.exe').exists())

    def elsewhere(self, *files):
        """A folder outside the tree, with the files in it."""
        target = self.top / 'elsewhere'
        for name in files:
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text('w', encoding='utf-8')
        return target

    def a_link_is_refused_before_the_session_ends(self, folder, named):
        self.started()
        self.merged()
        target = self.elsewhere('keep.txt')
        _winapi.CreateJunction(str(target), str(self.tree / folder))
        with self.assertRaisesRegex(SessionError, r'uncommitted[\s\S]*' + named):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        os.rmdir(self.tree / folder)
        self.assertTrue((target / 'keep.txt').exists())

    def test_the_browsers_folder_as_a_link_is_refused_before_the_session_ends(self):
        self.a_link_is_refused_before_the_session_ends('.playwright-mcp', 'playwright')

    def test_the_window_build_as_a_link_is_refused_before_the_session_ends(self):
        self.a_link_is_refused_before_the_session_ends('TiaArchiveCompare/window/bin', 'window/bin')

    def test_a_link_higher_up_the_path_is_refused_and_deletes_nothing_it_leads_to(self):
        self.started()
        self.merged()
        target = self.elsewhere('README.md', 'bin/x')
        window = self.tree / 'TiaArchiveCompare' / 'window'
        self.remove_folder(window)
        _winapi.CreateJunction(str(target), str(window))
        with self.assertRaisesRegex(SessionError, r'uncommitted[\s\S]*window/bin'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        os.rmdir(window)
        self.assertTrue((target / 'bin' / 'x').exists())

    def test_a_tracked_folder_named_in_another_case_is_not_deleted_as_that_folder(self):
        self.started()
        tracked = self.tree / 'TiaArchiveCompare' / 'window' / 'Bin'
        tracked.mkdir()
        (tracked / 'x').write_text('x', encoding='utf-8')
        git(self.tree, 'add', 'TiaArchiveCompare/window/Bin/x')
        self.merged()
        said = self.sessions.close('wk03')
        self.assertNotIn('what tools left', said)
        self.assertFalse(self.tree.exists())

    def test_what_the_ending_session_writes_stops_the_remove_before_anything_is_deleted(self):
        self.started()
        self.merged()
        self.leave_what_tools_leave()
        ending = self.terminal.end

        def writes_as_it_ends(record):
            (self.tree / 'late.md').write_text('x', encoding='utf-8')
            return ending(record)
        self.terminal.end = writes_as_it_ends
        with self.assertRaisesRegex(SessionError, r'session ended, nothing of the tree removed[\s\S]*late\.md'):
            self.sessions.close('wk03')
        self.assertTrue((self.tree / '.playwright-mcp' / 'x').exists())
        self.assertTrue((self.tree / 'late.md').exists())

    def test_a_tree_already_gone_leaves_no_trace_in_git(self):
        self.started()
        self.merged()
        self.remove_folder(self.tree)
        self.sessions.close('wk03')
        self.assertNotIn('work-03', self.trees())
        self.assertNotIn('feat/work-03', self.branches())

    def test_a_tree_it_did_not_make_stays_and_it_says_so(self):
        git(self.main, 'worktree', 'add', '-q', str(self.tree), '-b', 'feat/work-03-some-thing', 'main')
        self.started()
        said = self.sessions.close('wk03')
        self.assertIn('did not make', said)
        self.assertIn('--remove-tree', said)
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertTrue(self.tree.exists())
        self.assertIn('feat/work-03', self.branches())

    def test_a_tree_it_did_not_make_goes_when_asked_and_still_not_if_dirty(self):
        git(self.main, 'worktree', 'add', '-q', str(self.tree), '-b', 'feat/work-03-some-thing', 'main')
        self.started()
        (self.tree / 'new.txt').write_text('new', encoding='utf-8')
        with self.assertRaisesRegex(SessionError, 'uncommitted'):
            self.sessions.close('wk03', remove_tree=True)
        (self.tree / 'new.txt').unlink()
        self.sessions.close('wk03', remove_tree=True)
        self.assertFalse(self.tree.exists())

    def test_session_only_keeps_tree_and_branch_and_a_later_close_removes_them(self):
        self.started()
        self.sessions.close('wk03', session_only=True)
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertTrue(self.tree.exists())
        self.merged()
        self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertFalse(self.tree.exists())

    def test_a_tree_another_open_session_uses_stays(self):
        self.started()
        self.sessions.audit('wk03', terminal='fake')
        self.merged()
        said = self.sessions.close('wk03')
        self.assertIn('auditwk03', said)
        self.assertTrue(self.tree.exists())
        self.sessions.close('auditwk03')
        self.assertFalse(self.tree.exists())

    def test_the_main_tree_is_never_removed(self):
        self.started()
        record = self.sessions.store.load('wk03')
        record['worktree'] = str(self.main)
        self.sessions.store.save(record)
        with self.assertRaisesRegex(SessionError, 'main working tree'):
            self.sessions.close('wk03', remove_tree=True)

    def test_it_refuses_to_remove_the_tree_it_stands_in(self):
        self.started()
        self.merged()
        with mock.patch('session.Path.cwd', return_value=self.tree / 'sub'):
            with self.assertRaisesRegex(SessionError, 'runs from'):
                self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])

    def test_it_refuses_to_remove_the_tree_its_python_or_script_lie_in(self):
        self.started()
        self.merged()
        with mock.patch('session.sys.executable', str(self.tree / '.venv' / 'python.exe')):
            with self.assertRaisesRegex(SessionError, 'runs from'):
                self.sessions.close('wk03')
        with mock.patch('session.__file__', str(self.tree / 'tools' / 'session.py')):
            with self.assertRaisesRegex(SessionError, 'runs from'):
                self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue(self.tree.exists())

    def test_commits_on_a_detached_head_are_refused(self):
        self.started()
        self.merged()
        git(self.tree, 'checkout', '-q', '--detach')
        (self.tree / 'c.txt').write_text('c', encoding='utf-8')
        git(self.tree, 'add', 'c.txt')
        git(self.tree, 'commit', '-q', '-m', 'on no branch')
        with self.assertRaisesRegex(SessionError, 'HEAD'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertTrue((self.tree / 'c.txt').exists())

    def test_a_tree_already_gone_leaves_the_entry_of_another_gone_tree_alone(self):
        other = self.top / 'other-tree'
        git(self.main, 'worktree', 'add', '-q', str(other), '-b', 'other', 'main')
        self.started()
        self.merged()
        self.remove_folder(self.tree)
        moved = self.top / 'moved-away'
        other.rename(moved)
        self.sessions.close('wk03')
        self.assertNotIn('work-03', self.trees())
        self.assertIn('other-tree', self.trees())
        moved.rename(other)
        self.assertEqual(git(other, 'branch', '--show-current').strip(), 'other')

    def test_a_branch_it_did_not_make_stays_and_it_says_so(self):
        git(self.main, 'branch', 'someone-own', 'main')
        self.started(branch='someone-own')
        said = self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())
        self.assertIn('someone-own', self.branches())
        self.assertIn('someone-own kept', said)

    def test_a_branch_it_did_not_make_goes_when_asked(self):
        git(self.main, 'branch', 'someone-own', 'main')
        self.started(branch='someone-own')
        self.sessions.close('wk03', remove_tree=True)
        self.assertNotIn('someone-own', self.branches())

    def test_a_branch_made_earlier_counts_as_made_when_the_same_session_starts_again(self):
        self.started()
        self.sessions.close('wk03', session_only=True)
        self.write_ticket('ready-for-agent')
        self.started()
        self.merged()
        self.sessions.close('wk03')
        self.assertNotIn('feat/work-03', self.branches())

    def test_a_tree_another_open_session_spells_differently_stays(self):
        self.started()
        self.merged()
        other = dict(self.sessions.store.load('wk03'), name='wk99', worktree=str(self.tree).upper())
        self.sessions.store.save(other)
        said = self.sessions.close('wk03')
        self.assertIn('wk99', said)
        self.assertTrue(self.tree.exists())

    def test_it_never_forces_and_never_touches_plugins(self):
        self.started()
        self.merged()
        self.sessions.close('wk03')
        run = self.commands_run()
        self.assertTrue(any('worktree remove' in c for c in run))
        self.assertFalse([c for c in run if '--force' in c or ' -f' in c or ' -D' in c or 'plugin' in c or 'claude' in c])


class HeldTreeTests(Case):
    """A real process standing in a real tree: git would delete what it can and fail on the folder."""
    reads_real_processes = True
    ends_real_processes = True

    def stand_in(self, folder):
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], cwd=folder)
        self.addCleanup(self.end_process, holder)
        return holder

    @staticmethod
    def end_process(holder):
        holder.kill()
        holder.wait()

    def end_and_let_go(self, holder):
        """Ends it and waits until the tree is free: close's first look at it does not wait, and a handle can outlive the process."""
        self.end_process(holder)
        for _ in range(10):
            if not session.folder_held(self.tree):
                return
            time.sleep(self.PAUSE)
        self.fail(f'{self.tree} is still held after its process ended')

    def intact(self):
        self.assertTrue((self.tree / 'a.txt').exists())
        self.assertIn('work-03', self.trees())

    def test_a_process_in_the_tree_is_refused_with_nothing_ended_and_nothing_deleted(self):
        self.started()
        self.merged()
        holder = self.stand_in(self.tree)
        with self.assertRaisesRegex(SessionError, 'stands in'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertEqual([r['name'] for r in self.sessions.store.open_sessions()], ['wk03'])
        self.intact()
        self.end_and_let_go(holder)
        self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())

    def test_a_process_in_a_subfolder_counts_too(self):
        self.started()
        self.merged()
        (self.tree / 'sub').mkdir()
        self.stand_in(self.tree / 'sub')
        with self.assertRaisesRegex(SessionError, 'stands in'):
            self.sessions.close('wk03')
        self.intact()

    def test_the_session_itself_standing_in_it_is_ended_first(self):
        self.started()
        self.merged()
        holder = self.stand_in(self.tree)
        self.terminal.holding = True
        self.terminal.end = lambda record: self.end_process(holder) or 'ended it'
        self.assertIn('ended it', self.sessions.close('wk03'))
        self.assertFalse(self.tree.exists())
        self.assertNotIn('feat/work-03', self.branches())

    def test_another_process_left_after_the_session_ended_keeps_the_tree_whole_and_a_later_close_finishes(self):
        self.started()
        self.merged()
        holder = self.stand_in(self.tree)
        self.terminal.holding = True
        with self.assertRaisesRegex(SessionError, 'session ended, nothing of the tree removed'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertEqual(self.sessions.store.open_sessions(), [])
        self.intact()
        self.assertIn('feat/work-03', self.branches())
        with self.assertRaisesRegex(SessionError, 'stands in'):
            self.sessions.close('wk03')
        self.intact()
        self.end_and_let_go(holder)
        self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())
        self.assertNotIn('feat/work-03', self.branches())

    def run_a_program_from(self, folder):
        """A copy of a program, running from this folder with its current folder elsewhere. Ended through its Popen, not by a number."""
        folder.mkdir(parents=True, exist_ok=True)
        program = shutil.copy(Path(os.environ['SystemRoot']) / 'System32' / 'ping.exe', folder)
        holder = subprocess.Popen([program, '-n', '120', '127.0.0.1'], cwd=self.main, stdout=subprocess.DEVNULL)
        self.addCleanup(self.end_process, holder)
        for _ in range(50):
            if any(session.inside(path, folder) for path in session.running_executables()):
                return holder
            time.sleep(0.1)
        self.fail('the program never showed in the process list')

    def test_a_program_running_from_the_tree_is_refused_though_the_folder_could_be_renamed(self):
        self.started()
        self.merged()
        holder = self.run_a_program_from(self.tree / '.venv' / 'Scripts')
        before = sorted(p.name for p in self.tree.iterdir())
        with self.assertRaisesRegex(SessionError, 'stands in'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, [])
        self.assertEqual([r['name'] for r in self.sessions.store.open_sessions()], ['wk03'])
        self.assertEqual(sorted(p.name for p in self.tree.iterdir()), before)
        self.assertIn('work-03', self.trees())
        self.end_process(holder)
        self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())

    def test_a_program_left_running_from_it_after_the_session_ended_keeps_the_tree_whole(self):
        self.started()
        self.merged()
        self.run_a_program_from(self.tree / '.venv' / 'Scripts')
        self.terminal.holding = True
        with self.assertRaisesRegex(SessionError, 'session ended, nothing of the tree removed'):
            self.sessions.close('wk03')
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.intact()

    def test_a_program_running_from_a_folder_with_a_like_name_does_not_count(self):
        self.started()
        self.run_a_program_from(Path(str(self.tree) + '-beside'))
        self.assertFalse(session.folder_held(self.tree))

    def test_a_process_list_that_cannot_be_read_is_said_and_nothing_is_taken_for_free(self):
        failed = subprocess.CompletedProcess([], 1, '', 'boom')
        with mock.patch('session.subprocess.run', return_value=failed):
            with self.assertRaisesRegex(SessionError, 'could not be read.*boom'):
                session.running_executables()

    def test_an_empty_process_list_counts_as_not_read(self):
        with mock.patch('session.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with self.assertRaisesRegex(SessionError, 'could not be read'):
                session.running_executables()

    def half_removes(self, keep=None):
        """What git worktree remove does when something appears after the check: files gone, entry gone, failure."""
        real = self.sessions.git
        def git_(*args, **kwargs):
            if args[:2] == ('worktree', 'remove'):
                for item in list(self.tree.iterdir()):
                    if item.name != keep:
                        self.remove_folder(item) if item.is_dir() else item.unlink()
                real('worktree', 'prune')
                self.sessions.git = real
                return 1, '', f'fatal: {self.tree} is not a working tree'
            return real(*args, **kwargs)
        self.sessions.git = git_

    def test_a_remove_that_fails_says_what_is_left_and_never_tree_kept(self):
        self.started()
        self.merged()
        self.half_removes()
        with self.assertRaises(SessionError) as refused:
            self.sessions.close('wk03')
        said = str(refused.exception)
        self.assertNotIn('tree kept', said)
        self.assertIn('not a working tree', said)
        self.assertRegex(said, r'0 entries')
        self.assertRegex(said, r'no worktree entry')
        self.assertRegex(said, r'feat/work-03-some-thing still there')

    def test_a_later_close_finishes_an_empty_folder_and_the_branch(self):
        self.started()
        self.merged()
        self.half_removes()
        with self.assertRaises(SessionError):
            self.sessions.close('wk03')
        said = self.sessions.close('wk03')
        self.assertFalse(self.tree.exists())
        self.assertNotIn('feat/work-03', self.branches())
        self.assertIn('already closed', said)

    def test_a_later_close_leaves_a_folder_that_still_holds_something_and_says_so(self):
        self.started()
        self.merged()
        self.half_removes(keep='a.txt')
        with self.assertRaises(SessionError):
            self.sessions.close('wk03')
        said = self.sessions.close('wk03')
        self.assertTrue((self.tree / 'a.txt').exists())
        self.assertRegex(said, r'no longer a worktree[^\n]*1 entries')
        self.assertNotIn('removed', said.split('feat/work-03')[0])

    def test_a_close_with_everything_gone_says_so_and_claims_no_removal(self):
        self.started()
        self.merged()
        self.sessions.close('wk03')
        said = self.sessions.close('wk03')
        self.assertNotIn('removed', said)
        self.assertRegex(said, r'tree already gone')
        self.assertRegex(said, r'branch [^ ]+ already gone')


class RemoveFolderTests(unittest.TestCase):
    """The tests' own cleanup: Windows can hold a folder for a moment after the process standing in it has ended."""
    in_use = PermissionError(13, 'The process cannot access the file because it is being used by another process', 'x', 32)
    denied = PermissionError(13, 'Access is denied', 'x.exe', 5)

    def setUp(self):
        patcher = mock.patch('time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_folder_held_a_moment_is_deleted_once_let_go(self):
        with mock.patch('shutil.rmtree', side_effect=[self.in_use, self.denied, None]) as removed:
            Case.remove_folder(Path('x'))
        self.assertEqual(removed.call_count, 3)

    def test_a_folder_held_past_the_tries_raises(self):
        with mock.patch('shutil.rmtree', side_effect=[self.in_use] * 3) as removed, self.assertRaises(PermissionError):
            Case.remove_folder(Path('x'), tries=3)
        self.assertEqual(removed.call_count, 3)

    def test_any_other_error_raises_at_once(self):
        with mock.patch('shutil.rmtree', side_effect=[FileNotFoundError(2, 'The system cannot find the path specified', 'x', 3)]) as removed, \
                self.assertRaises(FileNotFoundError):
            Case.remove_folder(Path('x'))
        self.assertEqual(removed.call_count, 1)


class CommandLineTests(Case):
    def test_a_watch_of_an_effort_that_does_not_exist_is_refused(self):
        with self.assertRaisesRegex(SessionError, 'no effort nope'):
            session.watch(self.sessions, argparse.Namespace(effort=['nope'], first=True, timeout=0), out=lambda s: None)

    def test_a_watch_timeout_counts_the_time_its_looks_take(self):
        """A look on a herdr that does not answer takes its timeout: a watch of 100 s must not run three times that."""
        self.sessions.start(self.ticket, 'c', terminal='fake', implement=False)
        now = [0.0]
        self.terminal.alive = lambda record: now.__setitem__(0, now[0] + 4)
        said = []
        with mock.patch('session.time.monotonic', lambda: now[0]), \
                mock.patch('session.time.sleep', lambda seconds: now.__setitem__(0, now[0] + seconds)):
            session.watch(self.sessions, argparse.Namespace(effort=None, first=False, timeout=100), out=said.append)
        self.assertEqual(said[-1], 'watch ended')
        self.assertLessEqual(now[0], 100 + 4)    # its last look, and no sleep past the end

    def test_a_prompt_file_with_a_byte_order_mark_loses_it(self):
        prompt = self.top / 'p.txt'
        prompt.write_bytes(b'\xef\xbb\xbf/ticket x')
        self.assertEqual(session.text_of(argparse.Namespace(file=str(prompt), text=None)), '/ticket x')

    def test_a_check_of_a_file_that_does_not_exist_is_refused_not_called_clean(self):
        with self.assertRaisesRegex(SessionError, 'nope.md'):
            session.check(self.sessions, argparse.Namespace(files=['nope.md']), out=lambda s: None)


class ListTests(Case):
    def started(self):
        self.sessions.start(self.ticket, 'c', terminal='fake', implement=False)

    def test_a_session_running_without_its_guards_says_so(self):
        self.started()
        self.terminal.has_guards = False
        self.assertIn('RUNS WITHOUT ITS GUARDS', self.sessions.listing())

    def test_one_that_has_them_or_cannot_tell_does_not(self):
        self.started()
        for known in (True, None):
            self.terminal.has_guards = known
            self.assertNotIn('GUARDS', self.sessions.listing())

    def test_arguments_that_cannot_be_read_are_said_as_that_and_accuse_nobody(self):
        self.started()
        self.terminal.has_guards = NOT_READ
        shown = self.sessions.listing()
        self.assertIn('could not be read', shown)
        self.assertNotIn('RUNS WITHOUT', shown)

    def listing_with_herdr(self, answer):
        """The listing of three sessions of a stand-in herdr, and what it was asked."""
        asked = []

        def stand_in(args, timeout=None):
            asked.append(args[:2])
            return answer(args)
        for name in ('wk01', 'wk02', 'wk03'):
            self.sessions.store.save({'name': name, 'ticket': str(self.ticket), 'worktree': 'w', 'terminal': 'herdr', 'pane': 'w1:p1'})
        sessions = Sessions(self.main, terminal_for=lambda kind: Herdr(run=stand_in, workspace='w1'), sleep=lambda s: None)
        return sessions.listing(), asked

    @staticmethod
    def never():
        raise HerdrFailed('no_answer', 'herdr did not answer')

    def test_a_herdr_that_never_answers_is_asked_once_however_many_sessions_and_the_list_says_so(self):
        shown, asked = self.listing_with_herdr(lambda args: self.never())
        self.assertEqual(asked, [['agent', 'get']])
        self.assertEqual(shown.count('ticket'), 3)
        self.assertIn('herdr did not answer', shown)

    def test_a_herdr_that_answers_agent_list_only_is_asked_once_too(self):
        shown, asked = self.listing_with_herdr(lambda args: {'agents': []} if args[:2] == ['agent', 'list'] else self.never())
        self.assertEqual([question for question in asked if question != ['agent', 'list']], [['agent', 'get']])
        self.assertIn('herdr did not answer', shown)

    def test_a_herdr_that_stops_at_process_info_is_asked_nothing_more_and_only_that_session_reads_as_not_read(self):
        def answer(args):
            return {'agent': {'pane_id': 'w1:p1'}} if args[:2] == ['agent', 'get'] else self.never()
        shown, asked = self.listing_with_herdr(answer)
        self.assertEqual(asked, [['agent', 'get'], ['pane', 'process-info']])
        self.assertEqual(shown.count('could not be read'), 1)
        self.assertIn('herdr did not answer', shown)

    def test_a_herdr_that_answers_late_in_the_look_is_said_stopped_only_when_it_stopped(self):
        said = []

        def answer(args):
            said.append(args[:2])
            if len(said) > 2:
                self.never()
            return {'agent': {'pane_id': 'w1:p1'}} if args[:2] == ['agent', 'get'] else {'process_info': {'foreground_processes': []}}
        shown, asked = self.listing_with_herdr(answer)
        self.assertEqual(asked, [['agent', 'get'], ['pane', 'process-info'], ['agent', 'get']])
        self.assertEqual(shown.count('did not answer'), 1)

    def test_a_herdr_that_cannot_be_started_leaves_the_list_standing_and_says_so(self):
        def broken(args):
            raise OSError('cannot run')
        shown, asked = self.listing_with_herdr(broken)
        self.assertEqual(shown.count('ticket'), 3)
        self.assertEqual(asked, [['agent', 'get']])
        self.assertIn('herdr could not be asked (cannot run)', shown)

    def test_a_herdr_whose_server_is_down_is_asked_once_and_the_list_says_why(self):
        def down(args):
            raise HerdrFailed('server_not_running', 'no herdr server is running at x.sock')
        shown, asked = self.listing_with_herdr(down)
        self.assertEqual(shown.count('ticket'), 3)
        self.assertEqual(asked, [['agent', 'get']])
        self.assertEqual(shown.count('no herdr server is running at x.sock'), 1)
        self.assertNotIn('did not answer', shown)

    def test_a_session_herdr_does_not_know_is_an_answer_and_not_a_herdr_that_is_down(self):
        def answer(args):
            raise HerdrFailed('agent_not_found', 'no agent wk01')
        shown, asked = self.listing_with_herdr(answer)
        self.assertEqual(len(asked), 3)
        self.assertNotIn('could not be asked', shown)

    def test_a_terminal_that_answers_is_not_said_to_be_stopped(self):
        self.started()
        self.assertNotIn('did not answer', self.sessions.listing())

    def test_a_session_that_is_gone_is_told_as_gone_only(self):
        self.started()
        watcher = self.sessions.watcher()
        watcher.look()
        self.terminal.has_guards = False
        self.terminal.living = False
        events = watcher.look()
        self.assertEqual(len(events), 1, events)
        self.assertIn('gone', events[0])

    def test_a_stopped_terminal_makes_a_watcher_call_nobody_gone(self):
        self.started()
        watcher = self.sessions.watcher()
        watcher.look()
        self.terminal.stopped = 'did not answer'
        self.terminal.living = False
        events = watcher.look()
        self.assertFalse([event for event in events if 'gone' in event], events)
        self.assertTrue([event for event in events if 'did not answer' in event], events)

    def test_a_pane_no_longer_its_own_says_nothing_of_its_guards(self):
        self.started()
        self.terminal.has_guards = False
        self.terminal.living = False
        self.assertNotIn('GUARDS', self.sessions.listing())

    def test_watch_looks_at_the_guards_through_the_terminal(self):
        self.started()
        watcher = self.sessions.watcher()
        watcher.look()
        self.terminal.has_guards = False
        self.assertTrue(any('without its guards' in event for event in watcher.look()))


class ResumeTests(Case):
    """list --resume, from the records alone: with herdr down, as it is after the PC went off."""
    ARGS = ['--settings', r'C:\c\.scratch\sessions\wk01\settings.json', '--disallowedTools', 'Bash(git push:*)', '--permission-mode', 'auto']

    def saved(self, name='wk01', terminal='herdr', **record):
        self.sessions.store.save({'name': name, 'ticket': str(self.ticket), 'worktree': r'C:\c-worktrees\work-01', 'terminal': terminal,
                                  'pane': 'w1:p1', 'args': self.ARGS, **record})
        return self.sessions.store.folder(name)

    @staticmethod
    def down(args, timeout=None):
        raise HerdrFailed('server_not_running', 'no herdr server is running')

    def resumed(self):
        sessions = Sessions(self.main, terminal_for=lambda kind: session.ADAPTERS[kind](**({'run': self.down} if kind == 'herdr' else {})),
                            sleep=lambda s: None)
        return sessions.listing(resume=True)

    def test_a_herdr_session_gets_the_command_that_starts_it_again_in_its_pane_with_its_arguments(self):
        record_hook(self.saved(), {'hook_event_name': 'Stop', 'session_id': '5f0c-id'})
        self.assertIn("\n  herdr agent start wk01 --kind claude --pane w1:p1 -- --resume 5f0c-id '--settings' "
                      r"'C:\c\.scratch\sessions\wk01\settings.json' '--disallowedTools' 'Bash(git push:*)' '--permission-mode' 'auto'"
                      '\n', self.resumed() + '\n')

    def test_a_record_with_no_arguments_comes_back_without_its_guards_and_gets_no_command(self):
        self.saved(args=None)
        shown = self.resumed()
        self.assertIn('COMES BACK WITHOUT ITS GUARDS: its record holds no arguments', shown)
        self.assertNotIn('--resume', shown)

    def test_a_session_whose_hook_reported_no_id_yet_gets_a_stand_in_and_where_to_read_it(self):
        self.saved()
        shown = self.resumed()
        self.assertIn('-- --resume <id> ', shown)
        self.assertIn('no session id recorded: read it from agent_session.value of herdr pane get w1:p1', shown)

    def test_a_command_herdr_will_not_keep_is_marked_and_its_apostrophe_still_typed_whole(self):
        record_hook(self.saved(args=[*self.ARGS, '--append-system-prompt', "don't"]), {'hook_event_name': 'Stop', 'session_id': 'i'})
        shown = self.resumed()
        self.assertIn(""" '--append-system-prompt' "don't"\n""", shown)
        self.assertIn('COMES BACK WITHOUT ITS GUARDS again: herdr refuses to keep this command (an apostrophe in an argument)', shown)

    def test_a_good_command_carries_no_mark(self):
        record_hook(self.saved(), {'hook_event_name': 'Stop', 'session_id': 'i'})
        self.assertNotIn('GUARDS', self.resumed())

    def test_a_headless_session_needs_nothing_typed(self):
        self.saved(terminal='headless')
        self.assertIn('its next prompt resumes it with its guards', self.resumed())

    def test_a_session_in_a_persons_terminal_gets_its_tree_and_the_claude_command(self):
        record_hook(self.saved(terminal='print'), {'hook_event_name': 'Stop', 'session_id': 'i'})
        self.assertIn(r"  cd 'C:\c-worktrees\work-01'; claude --resume i '--settings' ", self.resumed())

    def test_a_session_in_a_persons_terminal_with_no_id_is_told_where_its_transcript_is(self):
        self.saved(terminal='print')
        shown = self.resumed()
        self.assertIn("claude --resume <id> '--settings' ", shown)
        self.assertIn(r'no session id recorded: it is the name of its transcript, <id>.jsonl, in the folder for its tree under ~\.claude\projects' '\\',
                      shown)

    def test_the_command_comes_under_its_own_session(self):
        record_hook(self.saved('wk01'), {'hook_event_name': 'Stop', 'session_id': 'one'})
        record_hook(self.saved('wk02'), {'hook_event_name': 'Stop', 'session_id': 'two'})
        rows = self.resumed().splitlines()
        self.assertTrue(rows[0].startswith('wk01: '), rows)
        self.assertIn('herdr agent start wk01 ', rows[1])
        self.assertIn('--resume one ', rows[1])
        self.assertTrue(rows[2].startswith('wk02: '), rows)
        self.assertIn('--resume two ', rows[3])

    def test_the_cli_takes_the_flag(self):
        record_hook(self.saved(), {'hook_event_name': 'Stop', 'session_id': 'i'})
        out = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')    # main reconfigures it
        with mock.patch('session.main_tree', return_value=self.main), mock.patch.dict(session.ADAPTERS, herdr=lambda: Herdr(run=self.down)), \
                mock.patch('sys.stdout', out):
            self.assertEqual(session.main(['list', '--resume']), 0)
        out.seek(0)
        self.assertIn('herdr agent start wk01 ', out.read())

    def test_without_the_flag_list_shows_no_command(self):
        record_hook(self.saved(), {'hook_event_name': 'Stop', 'session_id': '5f0c-id'})
        self.assertNotIn('herdr agent start', self.sessions.listing())


class HookCommandTests(unittest.TestCase):
    def test_a_herdr_that_refuses_the_report_leaves_the_state_written(self):
        folder = Path(tempfile.mkdtemp(prefix='session-hook-'))
        self.addCleanup(shutil.rmtree, folder)
        (folder / 'session.json').write_text(json.dumps({'name': 'wk03', 'args': ['--settings', 's']}), encoding='utf-8')
        payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'abc'})
        with mock.patch('sys.stdin', io.StringIO(payload)), mock.patch.dict(os.environ, {'HERDR_PANE_ID': 'w1:p2'}), \
                mock.patch('terminals.run_herdr', side_effect=HerdrFailed('resume_not_accepted', 'no')) as herdr, mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(session.run_hook(str(folder)), 0)
        herdr.assert_called_once()
        self.assertEqual(json.loads((folder / 'state.json').read_text(encoding='utf-8'))['state'], 'working')

    def test_the_hook_never_fails_a_session(self):
        script = Path(session.__file__)
        done = subprocess.run([sys.executable, '-X', 'utf8', str(script), 'hook', r'C:\no\such\folder\nul\x'],
                              input='not json', capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)


class TheListOfGitsNames(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_it_holds_every_name_git_gives(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in session.GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
