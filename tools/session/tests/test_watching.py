"""The watcher on real files in a temp folder: what wakes a coordinator, once, and what survives re-arming."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from store import Store, write_state
from watching import Watcher


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.scratch = Path(tmp.name)
        self.store = Store(self.scratch)
        self.ticket = self.scratch / 'work' / 'issues' / '03-a.md'
        self.ticket.parent.mkdir(parents=True)
        self.write_ticket('claimed')
        self.answers = self.scratch / 'reviews' / 'answers'
        self.answers.mkdir(parents=True)
        self.living = {}
        self.guards = {}
        self.stopped = {}
        self.add_session('wk03', self.ticket)

    def add_session(self, name, ticket, terminal='fake', effort='work'):
        self.store.save({'name': name, 'ticket': str(ticket), 'worktree': 'w', 'terminal': terminal, 'effort': effort})

    def write_ticket(self, status, comment=''):
        self.ticket.write_text(f'# 03 A\n\nStatus: {status}\n\n## Comments\n\n{comment}', encoding='utf-8')

    def watcher(self, efforts=()):
        return Watcher(self.scratch, self.store, self.look_at, efforts=efforts)

    def look_at(self, records):
        return {r['name']: (self.living.get(r['name'], True), self.guards.get(r['name'])) for r in records}, dict(self.stopped)

    def armed(self, efforts=()):
        watcher = self.watcher(efforts)
        watcher.look()
        return watcher


class TicketEvents(Case):
    def test_the_first_look_only_takes_the_baseline(self):
        self.assertEqual(self.watcher().look(), [])

    def test_a_status_change_wakes_with_the_status(self):
        watcher = self.armed()
        self.write_ticket('in-review')
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('ticket wk03 in-review', events[0])

    def test_a_comment_under_the_same_status_wakes_too_and_shows_the_comment(self):
        self.write_ticket('in-review', '- first\n')
        watcher = self.armed()
        self.write_ticket('in-review', '- first\n- fixed the findings, commit abc\n')
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('fixed the findings, commit abc', events[0])

    def test_nothing_new_is_no_event_and_one_change_wakes_once(self):
        watcher = self.armed()
        self.assertEqual(watcher.look(), [])
        self.write_ticket('in-review')
        self.assertEqual(len(watcher.look()), 1)
        self.assertEqual(watcher.look(), [])

    def test_a_change_of_a_ticket_no_session_works_on_is_left_alone(self):
        other = self.ticket.with_name('04-b.md')
        other.write_text('# 04 B\n\nStatus: ready-for-agent\n', encoding='utf-8')
        watcher = self.armed()
        other.write_text('# 04 B\n\nStatus: claimed\n', encoding='utf-8')
        self.assertEqual(watcher.look(), [])

    def test_an_effort_named_adds_all_its_tickets(self):
        other = self.ticket.with_name('04-b.md')
        other.write_text('# 04 B\n\nStatus: ready-for-agent\n', encoding='utf-8')
        watcher = self.armed(efforts=['work'])
        other.write_text('# 04 B\n\nStatus: claimed\n', encoding='utf-8')
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('04-b.md claimed', events[0])

    def test_an_effort_named_leaves_out_sessions_of_another_effort(self):
        other = self.scratch / 'else' / 'issues' / '01-x.md'
        other.parent.mkdir(parents=True)
        other.write_text('Status: claimed\n', encoding='utf-8')
        self.add_session('el01', other, effort='else')
        watcher = self.armed(efforts=['work'])
        write_state(self.store.folder('el01'), 'ended', 'hello')
        other.write_text('Status: in-review\n', encoding='utf-8')
        self.assertEqual(watcher.look(), [])

    def test_a_control_character_in_a_changed_ticket_is_reported(self):
        watcher = self.armed()
        self.ticket.write_bytes(b'Status: claimed\n\nsee docs\x0coo.md\n')
        events = watcher.look()
        self.assertTrue(any('U+000C' in e and r'docs\foo.md' in e and ':3:' in e for e in events), events)

    def test_a_control_character_found_on_arming_is_reported_at_once(self):
        self.ticket.write_bytes(b'Status: claimed\n\nsee docs\x0coo.md\n')
        self.assertTrue(any('U+000C' in e for e in self.watcher().look()))


class AnswerEvents(Case):
    def test_a_new_answer_and_a_changed_one_wake(self):
        watcher = self.armed()
        answer = self.answers / 'page one.json'
        answer.write_text('{"q": "yes"}', encoding='utf-8')
        self.assertEqual([('answer page one' in e) for e in watcher.look()], [True])
        answer.write_text('{"q": "no"}', encoding='utf-8')
        self.assertEqual([('answer page one' in e) for e in watcher.look()], [True])
        self.assertEqual(watcher.look(), [])

    def test_no_answers_folder_is_no_trouble(self):
        self.answers.rmdir()
        self.assertEqual(self.watcher().look(), [])

    def ticket_answer(self, name, answer):
        """What the dashboard writes when a ticket's question is answered on its page."""
        folder = self.scratch / 'reviews' / 'ticket-answers'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text('{"ticket": ".scratch/other/issues/07-b.md", "at": "2026-11-05 14:30", "who": "Sam", '
                                   f'"answer": {answer!r}}}'.replace("'", '"'), encoding='utf-8')

    def test_an_answer_on_a_ticket_s_page_wakes_as_an_answer_for_a_ticket_with_no_session(self):
        watcher = self.armed(efforts=['work'])
        self.ticket_answer('other-07-b.json', 'Keep it.\nBoth ways.')
        self.assertEqual(watcher.look(), ['answer to ticket other/issues/07-b.md from Sam: Keep it. Both ways.'])
        self.assertEqual(watcher.look(), [])

    def test_an_answer_on_a_ticket_s_page_given_while_unarmed_comes_on_re_arming_and_once(self):
        self.armed()
        self.ticket_answer('other-07-b.json', 'Yes.')
        self.assertEqual(self.watcher().look(), ['answer to ticket other/issues/07-b.md from Sam: Yes.'])
        self.assertEqual(self.watcher().look(), [])

    def test_an_answer_record_it_cannot_read_still_wakes(self):
        watcher = self.armed()
        folder = self.scratch / 'reviews' / 'ticket-answers'
        folder.mkdir(parents=True)
        (folder / 'x-01-a.json').write_text('{not json', encoding='utf-8')
        self.assertEqual(watcher.look(), ['answer to ticket x-01-a: record not readable'])


class SessionEvents(Case):
    def test_a_turn_that_ends_on_a_question_wakes_with_no_file_saved_but_its_state(self):
        watcher = self.armed()
        write_state(self.store.folder('wk03'), 'ended', 'Some text.\n\nWhich branch do you mean?\n')
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('session wk03 turn ended', events[0])
        self.assertIn('Which branch do you mean?', events[0])

    def test_a_turn_that_ended_with_background_tasks_says_they_still_run(self):
        watcher = self.armed()
        write_state(self.store.folder('wk03'), 'ended', 'I will wait for it.', background=2)
        self.assertIn('session wk03 turn ended, 2 background tasks still running: I will wait for it.', watcher.look()[0])

    def test_two_turns_with_the_same_message_wake_twice(self):
        watcher = self.armed()
        write_state(self.store.folder('wk03'), 'ended', 'same')
        self.assertEqual(len(watcher.look()), 1)
        write_state(self.store.folder('wk03'), 'working')
        self.assertEqual(watcher.look(), [])
        write_state(self.store.folder('wk03'), 'ended', 'same')
        self.assertEqual(len(watcher.look()), 1)

    def test_asking_permission_and_failing_wake(self):
        watcher = self.armed()
        write_state(self.store.folder('wk03'), 'asking', 'needs permission for Bash')
        self.assertIn('needs permission for Bash', watcher.look()[0])
        write_state(self.store.folder('wk03'), 'failed', 'rate_limit')
        self.assertIn('session wk03 turn failed: rate_limit', watcher.look()[0])

    def test_a_session_that_is_gone_wakes_once(self):
        watcher = self.armed()
        self.living['wk03'] = False
        self.assertEqual([('session wk03 gone' in e) for e in watcher.look()], [True])
        self.assertEqual(watcher.look(), [])

    def test_unknown_liveness_is_not_gone(self):
        watcher = self.armed()
        self.living['wk03'] = None
        self.assertEqual(watcher.look(), [])

    def test_a_headless_session_between_turns_is_not_gone(self):
        self.add_session('wk03', self.ticket, terminal='headless')
        write_state(self.store.folder('wk03'), 'ended', 'x')
        watcher = self.armed()
        self.living['wk03'] = False
        self.assertEqual(watcher.look(), [])

    def test_a_headless_turn_that_dies_mid_way_is_gone(self):
        self.add_session('wk03', self.ticket, terminal='headless')
        write_state(self.store.folder('wk03'), 'working')
        watcher = self.armed()
        self.living['wk03'] = False
        self.assertEqual([('session wk03 gone' in e) for e in watcher.look()], [True])

    def test_a_session_started_while_watching_is_picked_up(self):
        watcher = self.armed()
        other = self.ticket.with_name('04-b.md')
        other.write_text('Status: claimed\n', encoding='utf-8')
        self.add_session('wk04', other)
        write_state(self.store.folder('wk04'), 'ended', 'Ready')
        text = ' '.join(watcher.look())
        self.assertIn('session wk04 turn ended', text)

    def test_a_closed_session_is_dropped(self):
        watcher = self.armed()
        record = self.store.load('wk03')
        record['closed'] = 'now'
        self.store.save(record)
        write_state(self.store.folder('wk03'), 'ended', 'x')
        self.write_ticket('done')
        self.living['wk03'] = False
        self.assertEqual(watcher.look(), [])


class ReArming(Case):
    def test_what_happened_between_two_watchers_is_not_lost(self):
        self.armed()
        self.write_ticket('in-review')
        write_state(self.store.folder('wk03'), 'ended', 'Report.')
        (self.answers / 'page.json').write_text('{}', encoding='utf-8')
        text = ' '.join(self.watcher().look())
        for part in ('ticket wk03 in-review', 'session wk03 turn ended', 'answer page'):
            self.assertIn(part, text)

    def test_watchers_of_different_efforts_keep_their_own_baseline(self):
        self.armed(efforts=['work'])
        self.write_ticket('in-review')
        self.armed()
        self.assertEqual(len(self.watcher(efforts=['work']).look()), 1)


class StoppedTerminals(Case):
    def test_a_herdr_that_stops_answering_wakes_once(self):
        watcher = self.armed()
        self.stopped = {'herdr': 'did not answer'}
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('herdr did not answer', events[0])
        self.assertEqual(watcher.look(), [])

    def test_a_herdr_that_is_down_wakes_once_with_what_it_said(self):
        watcher = self.armed()
        self.stopped = {'herdr': 'could not be asked (no herdr server is running)'}
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('herdr could not be asked (no herdr server is running), so not all', events[0])
        self.assertEqual(watcher.look(), [])

    def test_re_arming_does_not_say_it_again(self):
        watcher = self.armed()
        self.stopped = {'herdr': 'did not answer'}
        watcher.look()
        self.assertEqual(self.watcher().look(), [])

    def test_it_wakes_again_after_it_answered_and_stopped_again(self):
        watcher = self.armed()
        self.stopped = {'herdr': 'did not answer'}
        watcher.look()
        self.stopped = {}
        self.assertEqual(watcher.look(), [])
        self.stopped = {'herdr': 'did not answer'}
        self.assertEqual(len(watcher.look()), 1)


class GuardEvents(Case):
    def test_a_session_found_without_its_guards_wakes_once(self):
        watcher = self.armed()
        self.guards['wk03'] = False
        events = watcher.look()
        self.assertEqual(len(events), 1)
        self.assertIn('session wk03 runs without its guards', events[0])
        self.assertEqual(watcher.look(), [])

    def test_re_arming_does_not_say_it_again(self):
        watcher = self.armed()
        self.guards['wk03'] = False
        watcher.look()
        self.assertEqual(self.watcher().look(), [])

    def test_it_wakes_again_after_they_came_back_and_went_again(self):
        watcher = self.armed()
        self.guards['wk03'] = False
        watcher.look()
        self.guards['wk03'] = True
        self.assertEqual(watcher.look(), [])
        self.guards['wk03'] = False
        self.assertEqual(len(watcher.look()), 1)

    def test_not_knowing_is_no_event(self):
        watcher = self.armed()
        for unknown in (None, 'not read'):
            self.guards['wk03'] = unknown
            self.assertEqual(watcher.look(), [])

    def test_not_reading_them_does_not_forget_they_were_gone(self):
        watcher = self.armed()
        self.guards['wk03'] = False
        watcher.look()
        self.guards['wk03'] = 'not read'
        watcher.look()
        self.guards['wk03'] = False
        self.assertEqual(watcher.look(), [])


if __name__ == '__main__':
    unittest.main()
