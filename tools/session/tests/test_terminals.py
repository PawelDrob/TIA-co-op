"""The adapters, with a fake in place of the real herdr or claude process: the exact commands and the refusals."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from store import SessionError, write_state
from terminals import ANSWER_SECONDS, NOT_READ, Headless, Herdr, HerdrFailed, Printed, choose, child_environment, report_resume, run_herdr


class FakeHerdr:
    """Answers as herdr does, from what a test sets, and records every command."""

    def __init__(self, worktree):
        self.calls = []
        self.timeouts = []
        self.pane_cwd = worktree
        self.pane_tab = 'w1:t2'
        self.pane_gone = False
        self.start_failure = None
        self.screen = ''
        self.after_down = ''
        self.agent ={'agent': {'name': 'wf06', 'pane_id': 'w1:p2', 'agent_status': 'idle'}}
        self.foreground = []

    def __call__(self, args, timeout=None):
        self.calls.append(args)
        self.timeouts.append(timeout)
        if args[:2] == ['tab', 'create']:
            return {'tab': {'tab_id': 'w1:t2'}, 'root_pane': {'pane_id': 'w1:p2'}}
        if args[:2] == ['pane', 'process-info']:
            if self.pane_gone:
                raise HerdrFailed('pane_not_found', 'no pane')
            return {'process_info': {'foreground_processes': self.foreground}}
        if args[:2] == ['pane', 'get']:
            if self.pane_gone:
                raise HerdrFailed('pane_not_found', 'no pane')
            return {'pane': {'cwd': self.pane_cwd, 'tab_id': self.pane_tab}}
        if args[:2] == ['agent', 'start'] and self.start_failure:
            raise HerdrFailed(self.start_failure, 'not ready')
        if args[:2] == ['agent', 'get']:
            if self.agent is None:
                raise HerdrFailed('agent_not_found', 'no agent')
            return self.agent
        if args[:2] == ['agent', 'read']:
            return self.screen
        if args[:2] == ['agent', 'send-keys'] and args[3:] == ['Down'] and self.after_down:
            self.screen = self.after_down
        return {}

    def commands(self, *start):
        return [c for c in self.calls if c[:len(start)] == list(start)]


def record(worktree=r'C:\trees\wf-06'):
    return {'name': 'wf06', 'worktree': worktree, 'terminal': 'herdr', 'tab': 'w1:t2', 'pane': 'w1:p2'}


TRUST = ''' Accessing workspace:

 {folder}

 Quick safety check: Is this a project you created or one you trust?

 {no} No, exit
 {yes} Yes, I trust this folder

 Enter to confirm · Esc to cancel
'''
ARGS = ['--add-dir',r'C:\main', '--disallowedTools', 'AskUserQuestion', 'Bash(git push:*)']


class HerdrOpenTests(unittest.TestCase):
    def open_with(self, fake, worktree=r'C:\trees\wf-06'):
        return Herdr(run=fake, workspace='w1', sleep=lambda s: None).open(
            {'name': 'wf06', 'worktree': worktree}, ARGS, '/ticket a "quoted" prompt')

    def test_it_makes_a_tab_in_the_tree_starts_the_agent_and_sends_the_prompt(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fields = self.open_with(fake)
        self.assertEqual(fields, {'tab': 'w1:t2', 'pane': 'w1:p2'})
        self.assertEqual(fake.commands('tab', 'create')[0],
                         ['tab', 'create', '--workspace', 'w1', '--cwd', r'C:\trees\wf-06', '--label', 'wf06', '--no-focus'])
        self.assertEqual(fake.commands('agent', 'start')[0],
                         ['agent', 'start', 'wf06', '--kind', 'claude', '--pane', 'w1:p2', '--timeout', '60000', '--'] + ARGS)
        self.assertEqual(fake.commands('agent', 'prompt')[0], ['agent', 'prompt', 'wf06', '/ticket a "quoted" prompt'])

    def test_a_tab_in_the_wrong_folder_is_closed_and_nothing_starts(self):
        fake = FakeHerdr(r'C:\Users\someone')
        with self.assertRaisesRegex(SessionError, 'someone'):
            self.open_with(fake)
        self.assertEqual(fake.commands('tab', 'close'), [['tab', 'close', 'w1:t2']])
        self.assertEqual(fake.commands('agent', 'start'), [])

    def test_a_folder_given_with_other_slashes_or_case_is_the_same_folder(self):
        fake = FakeHerdr('c:/Trees/WF-06/')
        self.open_with(fake)
        self.assertEqual(len(fake.commands('agent', 'start')), 1)

    def keys(self, fake):
        return [c[3:] for c in fake.commands('agent', 'send-keys')]

    def test_a_trust_prompt_for_this_tree_moves_to_yes_before_it_confirms(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder=r'C:\trees\wf-06', no='❯', yes=' ')
        fake.after_down = TRUST.format(folder=r'C:\trees\wf-06', no=' ', yes='❯')
        self.open_with(fake)
        self.assertEqual(self.keys(fake), [['Down'], ['Enter']])
        self.assertEqual(len(fake.commands('agent', 'prompt')), 1)

    def test_a_trust_prompt_with_yes_already_chosen_only_confirms(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder=r'C:\trees\wf-06', no=' ', yes='❯')
        self.open_with(fake)
        self.assertEqual(self.keys(fake), [['Enter']])

    def test_a_trust_prompt_where_yes_cannot_be_reached_is_never_confirmed(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder=r'C:\trees\wf-06', no='❯', yes=' ')
        with self.assertRaisesRegex(SessionError, 'not ready'):
            self.open_with(fake)
        self.assertEqual(self.keys(fake), [['Down']])
        self.assertEqual(fake.commands('agent', 'prompt'), [])

    def test_a_trust_prompt_for_this_tree_is_recognised_when_the_path_wraps(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder='C:\\trees\\\n wf-06', no=' ', yes='❯')
        self.open_with(fake)
        self.assertEqual(self.keys(fake), [['Enter']])

    def test_a_trust_prompt_for_another_folder_gets_no_key_and_its_tab_is_closed(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder=r'C:\Users\someone', no=' ', yes='❯')
        with self.assertRaisesRegex(SessionError, r'not ready[\s\S]*someone'):
            self.open_with(fake)
        self.assertEqual(self.keys(fake), [])
        self.assertEqual(fake.commands('agent', 'prompt'), [])
        self.assertEqual(fake.commands('tab', 'close'), [['tab', 'close', 'w1:t2']])

    def test_a_session_that_exits_at_its_trust_prompt_says_so_and_its_tab_is_closed(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        fake.start_failure = 'agent_not_ready'
        fake.screen = TRUST.format(folder=r'C:\trees\wf-06', no=' ', yes='❯')
        fake.agent = None
        with self.assertRaisesRegex(SessionError, 'no agent'):
            self.open_with(fake)
        self.assertEqual(fake.commands('tab', 'close'), [['tab', 'close', 'w1:t2']])

    def test_a_prompt_herdr_refuses_closes_the_tab_too(self):
        fake = FakeHerdr(r'C:\trees\wf-06')
        real = fake.__call__
        def refusing(args):
            if args[:2] == ['agent', 'prompt']:
                fake.calls.append(args)
                raise HerdrFailed('agent_blocked', 'blocked')
            return real(args)
        with self.assertRaisesRegex(SessionError, 'blocked'):
            Herdr(run=refusing, workspace='w1', sleep=lambda s: None).open({'name': 'wf06', 'worktree': r'C:\trees\wf-06'}, ARGS, 'x')
        self.assertEqual(fake.commands('tab', 'close'), [['tab', 'close', 'w1:t2']])


class HerdrUseTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHerdr(r'C:\trees\wf-06')
        self.herdr = Herdr(run=self.fake, workspace='w1', sleep=lambda s: None)

    def test_a_prompt_goes_to_the_named_agent_in_its_own_pane(self):
        self.herdr.send(record(), 'hello')
        self.assertEqual(self.fake.commands('agent', 'prompt'), [['agent', 'prompt', 'wf06', 'hello']])

    def test_a_name_now_on_another_pane_gets_nothing(self):
        self.fake.agent['agent']['pane_id'] = 'w9:p9'
        with self.assertRaisesRegex(SessionError, 'w9:p9'):
            self.herdr.send(record(), 'hello')
        self.assertEqual(self.fake.commands('agent', 'prompt'), [])

    def test_alive_follows_the_agent_and_its_pane(self):
        self.assertTrue(self.herdr.alive(record()))
        self.fake.agent['agent']['pane_id'] = 'w9:p9'
        self.assertFalse(self.herdr.alive(record()))
        self.fake.agent = None
        self.assertFalse(self.herdr.alive(record()))

    def test_alive_is_unknown_when_herdr_does_not_answer(self):
        def down(args, timeout=None):
            raise HerdrFailed('', 'socket gone')
        self.assertIsNone(Herdr(run=down, workspace='w1').alive(record()))

    def test_alive_is_unknown_when_herdr_answers_with_something_else(self):
        self.assertIsNone(Herdr(run=lambda args, timeout=None: 'not json', workspace='w1').alive(record()))

    def test_end_closes_its_own_tab_and_nothing_else(self):
        self.herdr.end(record())
        self.assertEqual(self.fake.commands('tab', 'close'), [['tab', 'close', 'w1:t2']])
        self.assertEqual([c for c in self.fake.calls if c[0] != 'tab' and c[:2] != ['pane', 'get']], [])

    def test_a_tab_id_now_on_another_folder_is_left_open(self):
        self.fake.pane_cwd = r'C:\trees\another'
        with self.assertRaisesRegex(SessionError, 'another'):
            self.herdr.end(record())
        self.assertEqual(self.fake.commands('tab', 'close'), [])

    def test_a_pane_now_in_another_tab_is_left_open(self):
        self.fake.pane_tab = 'w1:t9'
        with self.assertRaisesRegex(SessionError, 'w1:t9'):
            self.herdr.end(record())
        self.assertEqual(self.fake.commands('tab', 'close'), [])

    def test_a_pane_already_gone_closes_nothing(self):
        self.fake.pane_gone = True
        self.assertIn('gone', self.herdr.end(record()))
        self.assertEqual(self.fake.commands('tab', 'close'), [])

    def test_a_question_left_unanswered_stops_it_on_either_kind(self):
        def never(args, timeout=None):
            raise HerdrFailed('no_answer', 'herdr agent did not answer')
        for ask in (lambda herdr: herdr.alive(record()), lambda herdr: herdr.guarded(record())):
            herdr = Herdr(run=never, workspace='w1')
            self.assertEqual(herdr.stopped, '')
            ask(herdr)
            self.assertEqual(herdr.stopped, 'did not answer')

    def test_a_server_that_is_down_stops_it_with_what_herdr_said(self):
        def down(args, timeout=None):
            raise HerdrFailed('server_not_running', 'no herdr server is running at x.sock')
        herdr = Herdr(run=down, workspace='w1')
        self.assertIsNone(herdr.alive(record()))
        self.assertEqual(herdr.stopped, 'could not be asked (no herdr server is running at x.sock)')

    def test_a_herdr_not_on_the_path_stops_it(self):
        with mock.patch('terminals.shutil.which', return_value=None):
            herdr = Herdr(workspace='w1')
            self.assertIsNone(herdr.alive(record()))
        self.assertEqual(herdr.stopped, 'could not be asked (herdr is not on the PATH)')

    def test_a_failure_herdr_gives_no_code_for_is_an_answer_and_does_not_stop_it(self):
        with mock.patch('terminals.shutil.which', return_value='herdr'), \
                mock.patch('terminals.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'something odd')):
            herdr = Herdr(workspace='w1')
            self.assertIsNone(herdr.alive(record()))
        self.assertEqual(herdr.stopped, '')

    def test_an_error_is_an_answer_and_does_not_stop_it(self):
        def refuses(args, timeout=None):
            raise HerdrFailed('agent_not_found', 'no agent')
        herdr = Herdr(run=refuses, workspace='w1')
        herdr.alive(record())
        herdr.guarded(record())
        self.assertEqual(herdr.stopped, '')

    def test_a_herdr_that_cannot_be_started_stops_it_and_raises_nothing(self):
        def broken(args, timeout=None):
            raise OSError('cannot run')
        herdr = Herdr(run=broken, workspace='w1')
        self.assertIsNone(herdr.alive(record()))
        self.assertEqual(herdr.guarded(record()), NOT_READ)
        self.assertEqual(herdr.stopped, 'could not be asked (cannot run)')

    def test_a_look_waits_a_short_time_only(self):
        self.herdr.alive(record())
        self.herdr.guarded(record())
        self.assertEqual(self.fake.timeouts, [ANSWER_SECONDS] * 2)

    def test_a_timeout_is_told_apart_from_other_failures(self):
        with mock.patch('terminals.shutil.which', return_value='herdr'), \
                mock.patch('terminals.subprocess.run', side_effect=subprocess.TimeoutExpired('herdr', 90)):
            with self.assertRaises(HerdrFailed) as caught:
                run_herdr(['agent', 'list'])
        self.assertEqual(caught.exception.code, 'no_answer')

    def test_a_herdr_that_hangs_is_a_failure_to_report(self):
        with mock.patch('terminals.shutil.which', return_value='herdr'), \
                mock.patch('terminals.subprocess.run', side_effect=subprocess.TimeoutExpired('herdr', 90)):
            with self.assertRaisesRegex(SessionError, 'did not answer'):
                run_herdr(['agent', 'list'])


class FakeProcesses:
    def __init__(self):
        self.spawned = []
        self.running = set()
        self.killed = []

    def spawn(self, command, cwd, prompt_file, log_file, env):
        self.spawned.append({'command': command, 'cwd': cwd, 'prompt': Path(prompt_file).read_text('utf-8'), 'env': env})
        pid = 100 + len(self.spawned)
        self.running.add(pid)
        return pid, pid * 10

    def alive(self, pid, stamp):
        return pid in self.running and stamp == pid * 10

    def kill(self, pid):
        self.killed.append(pid)
        self.running.discard(pid)


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.processes = FakeProcesses()
        self.headless = Headless(spawn=self.processes.spawn, alive=self.processes.alive, kill=self.processes.kill,
                                 claude='claude', env={'PATH': 'x', 'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w1:p1', 'KEEP': 'y'})
        self.record = {'name': 'wf06', 'worktree': 'C:\\tree', 'terminal': 'headless', 'folder': str(self.folder)}

    def opened(self):
        self.record.update(self.headless.open(self.record, ARGS, '/ticket first'))
        return self.record

    def test_the_first_turn_runs_print_mode_in_the_tree_with_the_prompt_on_stdin(self):
        fields = self.opened()
        run = self.processes.spawned[0]
        self.assertEqual(run['cwd'], 'C:\\tree')
        self.assertEqual(run['prompt'], '/ticket first')
        self.assertEqual(run['command'], ['claude', '-p', '--session-id', fields['session_id']] + ARGS)
        self.assertNotIn('/ticket first', run['command'])

    def test_the_child_sees_no_herdr(self):
        self.opened()
        self.assertEqual(self.processes.spawned[0]['env'], {'PATH': 'x', 'KEEP': 'y'})

    def test_a_prompt_while_a_turn_runs_is_refused_at_once(self):
        self.opened()
        self.headless.sleep = lambda seconds: self.fail('it waited for a turn that is still running')
        with self.assertRaisesRegex(SessionError, 'still working'):
            self.headless.send(self.record, 'next')
        self.assertEqual(len(self.processes.spawned), 1)

    def test_a_turn_that_has_reported_its_end_gets_time_to_exit(self):
        self.opened()
        write_state(self.folder, 'ended', 'Ready')
        naps = []
        def nap(seconds):
            naps.append(seconds)
            if len(naps) == 3:
                self.processes.running.clear()
        self.headless.sleep = nap
        self.headless.send(self.record, 'next')
        self.assertEqual(len(naps), 3)
        self.assertEqual(self.processes.spawned[1]['prompt'], 'next')

    def test_a_turn_that_reported_its_end_and_never_exits_is_refused_in_the_end(self):
        self.opened()
        write_state(self.folder, 'ended', 'Ready')
        self.headless.sleep = lambda seconds: None
        with self.assertRaisesRegex(SessionError, 'has not exited'):
            self.headless.send(self.record, 'next')
        self.assertEqual(len(self.processes.spawned), 1)

    def test_a_turn_with_background_tasks_is_refused_at_once_and_says_why(self):
        self.opened()
        write_state(self.folder, 'ended', 'I will wait for it.', background=1)
        self.headless.sleep = lambda seconds: self.fail('it waited for a process that waits for its background task')
        with self.assertRaisesRegex(SessionError, 'background'):
            self.headless.send(self.record, 'next')
        self.assertEqual(len(self.processes.spawned), 1)

    def test_the_next_turn_resumes_the_session(self):
        fields = self.opened()
        self.processes.running.clear()
        self.record.update(self.headless.send(self.record, 'next'))
        run = self.processes.spawned[1]
        self.assertEqual(run['command'], ['claude', '-p', '--resume', fields['session_id']] + ARGS)
        self.assertEqual(run['prompt'], 'next')
        self.assertEqual(self.record['pid'], 102)

    def test_end_kills_a_running_turn_and_leaves_an_ended_one(self):
        self.opened()
        self.headless.end(self.record)
        self.assertEqual(self.processes.killed, [101])
        self.processes.killed.clear()
        self.headless.end(self.record)
        self.assertEqual(self.processes.killed, [])

    def test_alive_means_the_turn_is_running(self):
        self.opened()
        self.assertTrue(self.headless.alive(self.record))
        self.processes.running.clear()
        self.assertFalse(self.headless.alive(self.record))

    def test_read_gives_the_end_of_the_log(self):
        self.opened()
        (self.folder / 'output.log').write_text('\n'.join(f'line {i}' for i in range(50)), encoding='utf-8')
        self.assertEqual(self.headless.read(self.record, 2), 'line 48\nline 49')


class PrintedTests(unittest.TestCase):
    def test_it_prints_a_command_that_starts_the_session_and_runs_nothing(self):
        lines = []
        fields = Printed(out=lines.append).open({'name': 'wf06', 'worktree': r'C:\tree'}, ['--flag', 'Bash(git push:*)', 'mcp__x__*'], '/ticket first')
        text = '\n'.join(lines)
        self.assertIn('claude --flag "Bash(git push:*)" "mcp__x__*"', text)
        self.assertIn('/ticket first', text)
        self.assertIn(r'C:\tree', text)
        self.assertEqual(fields, {})

    def test_a_path_with_backslashes_is_quoted_for_git_bash_too(self):
        lines = []
        Printed(out=lines.append).open({'name': 'wf06', 'worktree': r'C:\tree'}, ['--settings', r'C:\x\settings.json'], 'x')
        self.assertIn(r'--settings "C:\x\settings.json"', '\n'.join(lines))

    def test_it_tells_the_person_which_trust_prompt_to_accept(self):
        lines = []
        Printed(out=lines.append).open({'name': 'wf06', 'worktree': r'C:\tree'}, [], 'x')
        self.assertRegex('\n'.join(lines), r'(?i)trust prompt[^\n]*C:\\tree[^\n]*home folder never')

    def test_a_prompt_is_for_the_person_to_type(self):
        with self.assertRaisesRegex(SessionError, 'type it'):
            Printed(out=lambda s: None).send({'name': 'wf06'}, 'next')

    def test_nothing_is_known_of_whether_it_lives(self):
        self.assertIsNone(Printed(out=lambda s: None).alive({'name': 'wf06'}))


class WhoStandsInTheTreeTests(unittest.TestCase):
    def test_a_herdr_tab_stands_in_it_until_it_is_closed(self):
        self.assertTrue(Herdr(run=FakeHerdr('x'), workspace='w1').holds_tree({'name': 'wf06'}))

    def test_a_headless_session_only_while_a_turn_runs(self):
        processes = FakeProcesses()
        headless = Headless(alive=processes.alive)
        processes.running.add(5)
        self.assertTrue(headless.holds_tree({'pid': 5, 'stamp': 50}))
        self.assertFalse(headless.holds_tree({'pid': 6, 'stamp': 60}))

    def test_a_session_in_a_persons_own_terminal_ends_only_by_them(self):
        self.assertFalse(Printed(out=lambda s: None).holds_tree({'name': 'wf06'}))


class ChoiceTests(unittest.TestCase):
    def test_inside_herdr_it_is_herdr(self):
        self.assertEqual(choose({'HERDR_ENV': '1'}, which=lambda exe: 'herdr.exe'), 'herdr')

    def test_outside_herdr_it_is_headless_though_herdr_is_installed(self):
        self.assertEqual(choose({}, which=lambda exe: 'herdr.exe'), 'headless')

    def test_with_no_herdr_on_the_path_it_is_headless(self):
        self.assertEqual(choose({'HERDR_ENV': '1'}, which=lambda exe: None), 'headless')

    def test_the_child_environment_drops_herdr_from_the_path_too(self):
        env = child_environment({'Path': os.pathsep.join([r'C:\Users\me\.herdr\packages\bin', r'C:\Windows']), 'HERDR_ENV': '1'})
        self.assertEqual(env, {'Path': r'C:\Windows'})


class ResumeReport(unittest.TestCase):
    PANE = {'HERDR_PANE_ID': 'w1:p2'}
    PROMPT = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'abc-1'}

    def setUp(self):
        self.herdr = FakeHerdr('w')
        self.record = {**record(), 'args': ARGS}

    def reported(self):
        return self.herdr.commands('pane', 'report-agent-session')

    def test_a_prompt_tells_herdr_the_command_that_brings_the_session_back_under_its_arguments(self):
        report_resume(self.record, self.PROMPT, self.PANE, self.herdr)
        command = self.reported()[0]
        self.assertEqual(command[:7], ['pane', 'report-agent-session', 'w1:p2', '--source', 'session-tool', '--agent', 'claude'])
        self.assertEqual(command[command.index('--'):], ['--', 'claude', '--resume', 'abc-1', *ARGS])

    def test_each_report_counts_as_newer_than_the_last(self):
        report_resume(self.record, self.PROMPT, self.PANE, self.herdr)
        time.sleep(0.05)
        report_resume(self.record, {**self.PROMPT, 'session_id': 'abc-2'}, self.PANE, self.herdr)
        first, second = (int(c[c.index('--seq') + 1]) for c in self.reported())
        self.assertGreater(second, first)

    def test_a_session_outside_herdr_reports_nothing(self):
        report_resume(self.record, self.PROMPT, {}, self.herdr)
        self.assertEqual(self.herdr.calls, [])

    def test_a_turn_end_reports_again_as_herdr_may_have_refused_the_prompt_s_report(self):
        report_resume(self.record, {'hook_event_name': 'Stop', 'session_id': 'abc-1'}, self.PANE, self.herdr)
        self.assertEqual(len(self.reported()), 1)

    def test_a_clear_tells_herdr_the_new_id_at_once_and_not_with_the_next_prompt(self):
        report_resume(self.record, {'hook_event_name': 'SessionStart', 'source': 'clear', 'session_id': 'abc-2'}, self.PANE, self.herdr)
        command = self.reported()[0]
        self.assertEqual(command[command.index('--'):], ['--', 'claude', '--resume', 'abc-2', *ARGS])

    def test_nothing_else_reports(self):
        report_resume(self.record, {'hook_event_name': 'Notification', 'session_id': 'abc-1'}, self.PANE, self.herdr)
        self.assertEqual(self.herdr.calls, [])

    def test_a_record_with_no_arguments_reports_nothing_rather_than_a_command_without_guards(self):
        report_resume(record(), self.PROMPT, self.PANE, self.herdr)
        self.assertEqual(self.herdr.calls, [])

    def test_a_hook_with_no_session_id_reports_nothing(self):
        report_resume(self.record, {'hook_event_name': 'UserPromptSubmit'}, self.PANE, self.herdr)
        self.assertEqual(self.herdr.calls, [])


class RestoreRefused(unittest.TestCase):
    """What herdr 0.9.5 refuses as the command that brings a session back: then it comes back bare."""

    def refused(self, args):
        return Herdr(run=FakeHerdr('w'), workspace='w1').restore_refused(args)

    def test_a_session_of_ordinary_arguments_is_taken(self):
        self.assertEqual(self.refused(ARGS), '')

    def test_an_apostrophe_anywhere_is_refused(self):
        self.assertIn('apostrophe', self.refused([*ARGS, '--add-dir', r"C:\Users\Ann's\repos"]))

    def test_a_control_character_is_refused(self):
        self.assertIn('control character', self.refused([*ARGS, 'a\tb']))

    def test_more_than_64_arguments_with_claude_resume_and_its_id_are_refused(self):
        self.assertEqual(self.refused(['-x'] * 61), '')
        self.assertIn('65 arguments, herdr takes 64', self.refused(['-x'] * 62))

    def test_more_than_8_kib_are_refused(self):
        self.assertEqual(self.refused(['a' * 8000]), '')
        self.assertIn('herdr takes 8192', self.refused(['a' * 8200]))

    def test_the_other_terminals_restore_nothing_so_refuse_nothing(self):
        apostrophe = [r"C:\Ann's"]
        self.assertEqual(Headless().restore_refused(apostrophe), '')
        self.assertEqual(Printed(out=lambda line: None).restore_refused(apostrophe), '')


class GuardsOfARunningSession(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr('w')
        self.terminal = Herdr(run=self.herdr, workspace='w1')

    def test_a_process_with_its_settings_has_its_guards(self):
        self.herdr.foreground = [{'name': 'claude.exe', 'argv': ['claude.exe', '--resume', 'abc', '--settings', 's.json']}]
        self.assertIs(self.terminal.guarded(record()), True)

    def test_a_process_brought_back_with_nothing_but_resume_has_none(self):
        self.herdr.foreground = [{'name': 'claude.exe', 'argv': ['claude.exe', '--resume', 'abc']}]
        self.assertIs(self.terminal.guarded(record()), False)

    def test_a_pane_at_its_shell_says_nothing_of_guards(self):
        self.herdr.foreground = [{'name': 'powershell.exe', 'argv': ['powershell.exe', '-NoExit']}]
        self.assertIsNone(self.terminal.guarded(record()))

    def test_a_pane_herdr_does_not_know_is_not_read_and_accuses_nobody(self):
        self.herdr.pane_gone = True
        self.assertEqual(self.terminal.guarded(record()), NOT_READ)

    def test_a_process_whose_arguments_herdr_does_not_give_is_not_read(self):
        for shown in ({'name': 'claude.exe'}, {'name': 'claude.exe', 'argv': None}, {'name': 'claude.exe', 'argv': []}):
            self.herdr.foreground = [shown]
            self.assertEqual(self.terminal.guarded(record()), NOT_READ, shown)

    def test_one_process_with_its_settings_is_enough_though_another_cannot_be_read(self):
        self.herdr.foreground = [{'name': 'claude.exe'}, {'name': 'claude.exe', 'argv': ['claude.exe', '--settings', 's.json']}]
        self.assertIs(self.terminal.guarded(record()), True)

    def test_one_process_that_cannot_be_read_stops_the_accusation_against_another(self):
        self.herdr.foreground = [{'name': 'claude.exe'}, {'name': 'claude.exe', 'argv': ['claude.exe', '--resume', 'abc']}]
        self.assertEqual(self.terminal.guarded(record()), NOT_READ)

    def test_a_process_with_no_name_is_not_taken_for_the_session(self):
        self.herdr.foreground = [{'name': None, 'argv': None}]
        self.assertIsNone(self.terminal.guarded(record()))

    def test_an_answer_of_another_shape_is_not_read(self):
        self.herdr.foreground = None
        self.assertEqual(self.terminal.guarded(record()), NOT_READ)

    def test_the_other_terminals_cannot_tell(self):
        self.assertEqual(Printed(out=lambda line: None).stopped, '')
        self.assertEqual(Headless().stopped, '')
        self.assertIsNone(Printed(out=lambda line: None).guarded(record()))
        self.assertIsNone(Headless().guarded(record()))


if __name__ == '__main__':
    unittest.main()
