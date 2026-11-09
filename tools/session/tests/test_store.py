"""The session records and what the hook writes for each kind of event."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from store import SessionError, Store, record_hook


class HookTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name))
        self.store.save({'name': 'wf06', 'ticket': 't.md', 'worktree': 'w', 'terminal': 'fake'})
        self.folder = self.store.folder('wf06')

    def state(self):
        return self.store.state('wf06')

    def test_a_new_prompt_means_working(self):
        record_hook(self.folder, {'hook_event_name': 'UserPromptSubmit', 'prompt': 'go'})
        self.assertEqual(self.state()['state'], 'working')

    def test_a_turn_that_ends_keeps_its_last_message(self):
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'Which one do you want?'})
        self.assertEqual((self.state()['state'], self.state()['message']), ('ended', 'Which one do you want?'))

    def test_each_end_of_a_turn_is_a_new_mark(self):
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'same'})
        first = self.state()['mark']
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'same'})
        self.assertNotEqual(self.state()['mark'], first)

    def test_a_turn_that_ends_with_background_tasks_counts_them(self):
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'waiting', 'background_tasks': [{'id': 'a'}]})
        self.assertEqual((self.state()['state'], self.state()['background']), ('ended', 1))
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'done', 'background_tasks': []})
        self.assertEqual(self.state()['background'], 0)

    def test_a_failed_turn_says_so(self):
        record_hook(self.folder, {'hook_event_name': 'StopFailure', 'error': 'rate_limit'})
        self.assertEqual((self.state()['state'], self.state()['message']), ('failed', 'rate_limit'))

    def test_a_permission_prompt_counts_and_an_idle_notice_does_not(self):
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'done'})
        record_hook(self.folder, {'hook_event_name': 'Notification', 'notification_type': 'idle_prompt', 'message': 'idle'})
        self.assertEqual(self.state()['state'], 'ended')
        record_hook(self.folder, {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                                  'message': 'Claude needs your permission to use Bash'})
        self.assertEqual((self.state()['state'], self.state()['message']),
                         ('asking', 'Claude needs your permission to use Bash'))

    def test_the_newest_session_id_a_hook_reports_is_kept_whatever_the_event(self):
        self.assertIsNone(self.store.session_id('wf06'))
        record_hook(self.folder, {'hook_event_name': 'UserPromptSubmit', 'session_id': 'first'})
        self.assertEqual(self.store.session_id('wf06'), 'first')
        record_hook(self.folder, {'hook_event_name': 'SessionStart', 'source': 'clear', 'session_id': 'after-clear'})
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'done'})
        self.assertEqual(self.store.session_id('wf06'), 'after-clear')

    def test_a_long_message_is_cut(self):
        record_hook(self.folder, {'hook_event_name': 'Stop', 'last_assistant_message': 'x' * 100000})
        self.assertLess(len(self.state()['message']), 5000)


class NameTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name))
        self.store.save({'name': 'wf06', 'ticket': 't.md', 'worktree': 'w', 'terminal': 'fake'})

    def test_a_typo_is_refused_and_names_the_open_sessions(self):
        with self.assertRaisesRegex(SessionError, r'no session named wf60.*wf06'):
            self.store.load('wf60')

    def test_a_name_that_is_a_path_is_refused(self):
        for bad in ('..\\..\\x', '../x', 'A b', ''):
            with self.assertRaisesRegex(SessionError, 'not a session name'):
                self.store.load(bad)

    def test_a_closed_session_leaves_the_open_list(self):
        record = self.store.load('wf06')
        record['closed'] = 'now'
        self.store.save(record)
        self.assertEqual(self.store.open_sessions(), [])
        self.assertEqual(self.store.load('wf06')['closed'], 'now')

    def test_the_files_on_disk_are_json(self):
        self.assertEqual(json.loads((self.store.folder('wf06') / 'session.json').read_text('utf-8'))['name'], 'wf06')


if __name__ == '__main__':
    unittest.main()
