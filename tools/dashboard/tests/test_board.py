"""What the board reads from a .scratch folder: any map, its tickets, in the issue tracker's format."""
import os
import re
import subprocess
import unittest
from unittest import mock

from .support import effort_map, made_up_repo, ticket

import board  # noqa: E402


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.scratch = made_up_repo(self) / '.scratch'
        self.scratch.mkdir()
        patcher = mock.patch.object(board, 'agents', return_value={})
        self.agents = patcher.start()
        self.addCleanup(patcher.stop)

    def html(self):
        return board.tickets_html(self.scratch)[:2]

    def entries(self):
        return {e['name']: e for e in board.tickets_html(self.scratch)[2]}

    def test_any_folder_with_a_map_is_an_effort_with_its_destination(self):
        effort_map(self.scratch, 'some-effort', '# Map\n\n## Destination\n\nA thing\nthat works.\n\n## Notes\n\nx\n')
        ticket(self.scratch, 'some-effort', '01-a.md', '# 01 A ticket\n\nStatus: ready-for-agent\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertIn('<h2>Some effort tickets</h2>', text)
        self.assertIn('A thing that works.', text)
        self.assertIn('A ticket', text)
        self.assertEqual(waiting, 0)

    def test_a_folder_with_tickets_and_no_map_shows_under_no_map_with_its_name(self):
        ticket(self.scratch, 'old-feature', '01-a.md', '# 01 Old ticket\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nWhich colour?\n')
        ticket(self.scratch, 'old-feature', '02-b.md', '# 02 Other ticket\n\nStatus: ready-for-agent\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertIn('id="no-map"', text)
        self.assertIn('<h2>No map</h2>', text)
        self.assertIn('<h3>old-feature</h3>', text)
        self.assertIn('Old ticket', text)
        self.assertIn('Other ticket', text)
        self.assertEqual(waiting, 1)
        self.assertEqual((self.entries()['No map']['waiting'], self.entries()['No map']['open']), (1, 2))

    def test_no_map_adds_up_its_folders_and_folders_with_something_open_come_first(self):
        ticket(self.scratch, 'aaa-finished', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'zzz-live', '01-a.md', '# 01 Z\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nWhich colour?\n')
        ticket(self.scratch, 'mmm-live', '01-a.md', '# 01 M\n\nStatus: claimed\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertEqual(waiting, 1)
        self.assertEqual((self.entries()['No map']['waiting'], self.entries()['No map']['open']), (1, 2))
        self.assertLess(text.index('mmm-live'), text.index('zzz-live'))
        self.assertLess(text.index('zzz-live'), text.index('aaa-finished'))

    def test_a_folder_with_a_map_is_not_under_no_map_and_an_empty_issues_folder_shows_nothing(self):
        effort_map(self.scratch, 'mapped')
        ticket(self.scratch, 'mapped', '01-a.md', '# 01 A\n\nStatus: open\nBlocked by: none\n')
        (self.scratch / 'empty' / 'issues').mkdir(parents=True)
        (self.scratch / 'notes').mkdir()
        (self.scratch / 'notes' / 'x.md').write_text('# x', encoding='utf-8')
        text, _ = self.html()
        self.assertNotIn('No map', text)
        self.assertNotIn('empty', text)
        self.assertEqual(list(self.entries()), ['Mapped'])

    def test_a_shared_number_under_no_map_is_not_readable_for_the_open_ticket(self):
        ticket(self.scratch, 'loose', '19-one.md', '# 19 One\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'loose', '19-two.md', '# 19 Two\n\nStatus: ready-for-human\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertIn('Not readable (1)', text)
        self.assertIn('number 19 is on 2 tickets', text)
        self.assertIn('Closed (1)', text)
        self.assertEqual(waiting, 0)

    def test_no_map_counts_change_the_version(self):
        ticket(self.scratch, 'loose', '01-a.md', '# 01 A\n\nStatus: open\nBlocked by: none\n')
        before = board.version(self.scratch)
        ticket(self.scratch, 'loose', '02-b.md', '# 02 B\n\nStatus: open\nBlocked by: none\n')
        self.assertNotEqual(before, board.version(self.scratch))

    def test_each_effort_is_a_topic_that_counts_waiting_and_open(self):
        effort_map(self.scratch, 'some-effort')
        ticket(self.scratch, 'some-effort', '01-a.md', '# 01 A\n\nStatus: ready-for-human\nBlocked by: none\n\n## Question for the maintainer\n\nWhich colour?\n')
        ticket(self.scratch, 'some-effort', '02-b.md', '# 02 B\n\nStatus: claimed\nBlocked by: none\n')
        ticket(self.scratch, 'some-effort', '03-c.md', '# 03 C\n\nStatus: ready-for-agent\nBlocked by: 02\n')
        ticket(self.scratch, 'some-effort', '04-d.md', '# 04 D\n\nStatus: done\nBlocked by: none\n')
        text, _ = self.html()
        entry = self.entries()['Some effort']
        self.assertEqual((entry['waiting'], entry['open'], entry['note']), (1, 3, ''))
        self.assertIn(f'id="{entry["id"]}"', text)

    def test_topics_run_efforts_then_no_map_then_postponed(self):
        effort_map(self.scratch, 'aaa-later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        ticket(self.scratch, 'aaa-later', '01-a.md', '# 01 A\n\nStatus: ready-for-human\nBlocked by: none\n')
        effort_map(self.scratch, 'zzz-now')
        ticket(self.scratch, 'mmm-loose', '01-a.md', '# 01 A\n\nStatus: open\nBlocked by: none\n')
        self.assertEqual(list(self.entries()), ['Zzz now', 'No map', 'Aaa later'])
        text, _ = self.html()
        self.assertLess(text.index('Zzz now'), text.index('No map'))
        self.assertLess(text.index('No map'), text.index('Aaa later'))

    def test_a_postponed_topic_shows_open_tickets_and_nothing_waiting(self):
        effort_map(self.scratch, 'later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        ticket(self.scratch, 'later', '01-a.md', '# 01 A\n\nStatus: ready-for-human\nBlocked by: none\n')
        ticket(self.scratch, 'later', '02-b.md', '# 02 B\n\nStatus: done\nBlocked by: none\n')
        entry = self.entries()['Later']
        self.assertEqual((entry['waiting'], entry['open'], entry['note']), (0, 1, 'postponed'))
        self.assertIn(f'id="{entry["id"]}"', self.html()[0])

    def folded_lists(self):
        """The folded lists of the page, as (id, its summary), in page order. An id of None is a list with none."""
        return re.findall(r'<details(?:[^>]*\bid="([^"]*)")?[^>]*><summary>(.*?)</summary>', self.html()[0])

    def test_every_folded_list_has_an_id_of_its_own(self):
        effort_map(self.scratch, 'mapped')
        ticket(self.scratch, 'mapped', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        effort_map(self.scratch, 'later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        ticket(self.scratch, 'later', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'loose', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'other-loose', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        ids = [i for i, _ in self.folded_lists()]
        self.assertEqual(sorted(ids), ['closed-loose', 'closed-mapped', 'closed-other-loose', 'effort-later'])

    def test_a_folded_list_keeps_its_id_when_other_lists_come_and_go(self):
        effort_map(self.scratch, 'parser')
        ticket(self.scratch, 'parser', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        self.assertEqual([i for i, _ in self.folded_lists()], ['closed-parser'])
        effort_map(self.scratch, 'exporter')       # earlier on the page: its first closed ticket comes before parser's
        ticket(self.scratch, 'exporter', '01-a.md', '# 01 A\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'parser', '02-b.md', '# 02 B\n\nStatus: done\nBlocked by: none\n')
        lists = self.folded_lists()
        self.assertEqual([i for i, _ in lists], ['closed-exporter', 'closed-parser'])
        self.assertIn('Closed (2)', lists[1][1])

    def test_the_contents_list_links_each_topic_and_marks_what_waits(self):
        text = board.contents_html([
            {'id': 'reviews', 'name': 'Reviews', 'waiting': 2, 'open': 3, 'note': ''},
            {'id': 'effort-a b', 'name': 'A b', 'waiting': 0, 'open': 4, 'note': ''},
            {'id': 'effort-c', 'name': 'C <x>', 'waiting': 0, 'open': 1, 'note': 'postponed'},
        ])
        self.assertIn('href="#reviews"', text)
        self.assertIn('href="#effort-a%20b"', text)
        self.assertIn('<span class="you">● 2</span>', text)
        self.assertEqual(text.count('class="you"'), 1)
        self.assertIn('3 open', text)
        self.assertIn('postponed, 1 open', text)
        self.assertIn('C &lt;x&gt;', text)

    def test_a_map_with_no_tickets_says_so(self):
        effort_map(self.scratch, 'new')
        self.assertIn('No tickets yet.', self.html()[0])

    def test_a_ticket_written_by_to_tickets_is_readable(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '07-a.md', '# 07: Title\n\n**What to build:** x\n\n**Blocked by:** none\n\n**Status:** ready-for-human\n')
        text, waiting = self.html()
        self.assertEqual(self.section_of(text, '>Title<'), ['Yours to start'])
        self.assertEqual(waiting, 0)

    def test_an_open_grilling_waits_for_a_person_and_an_open_task_does_not(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-g.md', '# 01 G\n\nType: grilling\nStatus: open\nBlocked by: none\n')
        ticket(self.scratch, 'e', '02-t.md', '# 02 T\n\nType: task\nStatus: open\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertEqual(waiting, 1)
        self.assertLess(text.index('Waits for you'), text.index('>G<'))
        self.assertLess(text.index('Ready for an agent'), text.index('>T<'))

    def test_a_value_it_cannot_read_gets_its_own_section(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 A\n\nStatus: sort of done\nBlocked by: none\n')
        text, _ = self.html()
        self.assertIn('Not readable', text)
        self.assertIn('Status: sort of done', text)

    def test_a_missing_line_is_called_missing_not_a_valid_value(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 A\n\nStatus: ready-for-agent\n')
        ticket(self.scratch, 'e', '02-b.md', '# 02 B\n\nBlocked by: none\n')
        text, _ = self.html()
        self.assertIn('Blocked by: missing', text)
        self.assertIn('Status: missing', text)
        self.assertNotIn('Blocked by: none', text)

    def test_two_open_tickets_with_one_number_both_show_as_not_readable(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-one.md', '# 01 Ticket one\n\nStatus: ready-for-human\nBlocked by: none\n')
        ticket(self.scratch, 'e', '01-two.md', '# 01 Ticket two\n\nStatus: ready-for-agent\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertIn('Not readable (2)', text)
        self.assertIn('Ticket one', text)
        self.assertIn('Ticket two', text)
        self.assertIn('number 01 is on 2 tickets', text)
        self.assertEqual(waiting, 0)

    def test_two_closed_tickets_with_one_number_both_stay_closed(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-one.md', '# 01 Ticket one\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'e', '01-two.md', '# 01 Ticket two\n\nStatus: resolved\nBlocked by: none\n')
        text, _ = self.html()
        self.assertIn('Closed (2)', text)
        self.assertNotIn('Not readable', text)

    def test_a_shared_number_blocks_until_every_ticket_with_it_is_closed(self):
        effort_map(self.scratch, 'e')
        effort_map(self.scratch, 'other')
        ticket(self.scratch, 'e', '01-one.md', '# 01 One\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'e', '01-two.md', '# 01 Two\n\nStatus: claimed\nBlocked by: none\n')
        ticket(self.scratch, 'e', '02-next.md', '# 02 Next\n\nStatus: ready-for-agent\nBlocked by: 01\n')
        ticket(self.scratch, 'other', '03-far.md', '# 03 Far\n\nStatus: ready-for-agent\nBlocked by: e/01\n')
        text, _ = self.html()
        self.assertIn('waits for 01', text)
        self.assertIn('waits for e/01', text)

    def test_a_postponed_effort_lists_both_tickets_with_one_number(self):
        effort_map(self.scratch, 'later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        ticket(self.scratch, 'later', '01-one.md', '# 01 Ticket one\n\nStatus: open\nBlocked by: none\n')
        ticket(self.scratch, 'later', '01-two.md', '# 01 Ticket two\n\nStatus: open\nBlocked by: none\n')
        text, _ = self.html()
        self.assertIn('postponed (2)', text)
        self.assertIn('Ticket one', text)
        self.assertIn('Ticket two', text)

    def test_a_ticket_waits_for_an_open_ticket_of_another_effort(self):
        effort_map(self.scratch, 'one')
        effort_map(self.scratch, 'two')
        ticket(self.scratch, 'one', '01-a.md', '# 01 A\n\nStatus: ready-for-agent\nBlocked by: two/03\n')
        ticket(self.scratch, 'two', '03-b.md', '# 03 B\n\nStatus: claimed\nBlocked by: none\n')
        self.assertIn('waits for two/03', self.html()[0])
        ticket(self.scratch, 'two', '03-b.md', '# 03 B\n\nStatus: done\nBlocked by: none\n')
        self.assertNotIn('waits for two/03', self.html()[0])

    def test_a_postponed_effort_is_listed_closed_and_counts_for_nothing(self):
        effort_map(self.scratch, 'later', '# Map\n\n## Destination\n\nx\n\n## Notes\n\n- This effort has been postponed since 2026-01-01.\n')
        ticket(self.scratch, 'later', '01-a.md', '# 01 Parked\n\nStatus: ready-for-human\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertEqual(waiting, 0)
        self.assertIn('Later tickets, postponed (1)', text)
        self.assertIn('Parked', text)

    def test_a_note_that_only_mentions_postponing_changes_nothing(self):
        effort_map(self.scratch, 'e', '# Map\n\n## Notes\n\n- The review of ticket 3 was postponed once.\n')
        ticket(self.scratch, 'e', '01-a.md', '# 01 A\n\nStatus: ready-for-human\nBlocked by: none\n\n## Question for the maintainer\n\nWhich colour?\n')
        self.assertEqual(self.html()[1], 1)

    def test_a_running_session_is_found_by_the_prefix_the_map_names(self):
        effort_map(self.scratch, 'long-name', '# Map\n\nSessions: ln\n\n## Destination\n\nx\n')
        ticket(self.scratch, 'long-name', '04-a.md', '# 04 A\n\nStatus: claimed\nBlocked by: none\n')
        self.agents.return_value = {'ln04': 'working'}
        self.assertIn('session working', self.html()[0])

    def section_of(self, text, title):
        """The names of the sections whose rows hold this ticket title."""
        sections = re.findall(r'<section class="status[^"]*"><h3>\S+ (.*?) \(\d+\)</h3>(.*?)</section>', text, re.S)
        return [name for name, rows in sections if title in rows]

    def one_ticket_with_session(self, status, sessions, body=''):
        effort_map(self.scratch, 'effort', '# Map\n\nSessions: ef\n\n## Destination\n\nx\n')
        ticket(self.scratch, 'effort', '04-a.md', f'# 04 The ticket\n\nStatus: {status}\nBlocked by: none\n{body}')
        self.agents.return_value = sessions
        return self.html()

    def test_a_ticket_with_a_question_waits_with_a_session_open_or_working(self):
        for state, shown in (('idle', 'question, session open'), ('working', 'question, session working')):
            with self.subTest(state):
                text, waiting = self.one_ticket_with_session('claimed', {'ef04': state}, '\n## Question for the maintainer\n\nWhich one?\n')
                self.assertEqual(self.section_of(text, 'The ticket'), ['Waits for you'])
                self.assertEqual(waiting, 1)
                self.assertIn(shown, text)

    def test_work_ready_for_a_person_runs_while_a_session_works_on_it(self):
        text, waiting = self.one_ticket_with_session('ready-for-human', {'ef04': 'working'})
        self.assertEqual(self.section_of(text, 'The ticket'), ['Running now'])
        self.assertEqual(waiting, 0)

    def test_a_status_it_cannot_read_stays_not_readable_with_a_session_open(self):
        text, _ = self.one_ticket_with_session('half done', {'ef04': 'idle'})
        self.assertEqual(self.section_of(text, 'The ticket'), ['Not readable'])
        self.assertIn('Status: half done, session open', text)

    def test_a_ticket_in_review_runs_while_an_agent_works_and_is_with_the_coordinator_when_none_does(self):
        text, waiting = self.one_ticket_with_session('in-review', {'auditef04': 'working'})
        self.assertEqual(self.section_of(text, 'The ticket'), ['Running now'])
        self.assertEqual(waiting, 0)
        text, waiting = self.one_ticket_with_session('in-review', {'auditef04': 'idle'})
        self.assertEqual(self.section_of(text, 'The ticket'), ['With the coordinator'])
        self.assertIn('in-review, session open', text)
        self.assertEqual(waiting, 0)

    def test_a_claimed_ticket_with_a_session_open_is_running_now(self):
        text, _ = self.one_ticket_with_session('claimed', {'ef04': 'idle'})
        self.assertEqual(self.section_of(text, 'The ticket'), ['Running now'])

    # What waits for you: a question in the ticket, or a review page about it that waits for answers. Nothing else asks.

    def test_in_review_or_needs_info_with_nothing_asked_is_with_the_coordinator(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Audited\n\nStatus: in-review\nBlocked by: none\n')
        ticket(self.scratch, 'e', '02-b.md', '# 02 Reporter asked\n\nStatus: needs-info\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertEqual(self.section_of(text, 'Audited'), ['With the coordinator'])
        self.assertEqual(self.section_of(text, 'Reporter asked'), ['With the coordinator'])
        self.assertEqual(waiting, 0)
        self.assertEqual(self.entries()['E']['waiting'], 0)

    def test_work_ready_for_a_person_with_nothing_asked_is_yours_to_start_and_does_not_count(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Grey instructions\n\nStatus: ready-for-human\nBlocked by: none\n')
        text, waiting = self.html()
        self.assertEqual(self.section_of(text, 'Grey instructions'), ['Yours to start'])
        self.assertEqual(waiting, 0)
        self.assertNotIn('Waits for you', text)

    def test_an_open_question_puts_any_open_ticket_under_waits_for_you(self):
        effort_map(self.scratch, 'e')
        for n, status in enumerate(('in-review', 'ready-for-human', 'claimed', 'ready-for-agent', 'needs-info'), 1):
            ticket(self.scratch, 'e', f'0{n}-a.md', f'# 0{n} Asks {status}\n\nStatus: {status}\nBlocked by: none\n\n'
                                                    '## Question for the maintainer\n\nKeep the old name?\n\n## Comments\n')
        text, waiting = self.html()
        self.assertEqual(waiting, 5)
        for status in ('in-review', 'ready-for-human', 'claimed', 'ready-for-agent', 'needs-info'):
            self.assertEqual(self.section_of(text, f'Asks {status}'), ['Waits for you'])

    def test_a_question_deep_in_a_long_ticket_is_found(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Long\n\nStatus: in-review\nBlocked by: none\n\n' + 'Text.\n\n' * 40
               + '## Question for the maintainer\n\nWhich one?\n')
        self.assertEqual(self.section_of(self.html()[0], 'Long'), ['Waits for you'])

    def test_an_answered_question_asks_nothing(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Answered\n\nStatus: in-review\nBlocked by: none\n\n'
                                             '## Question for the maintainer, answered 2026-11-05 14:30\n\nWhich one?\n')
        text, waiting = self.html()
        self.assertEqual(self.section_of(text, 'Answered'), ['With the coordinator'])
        self.assertEqual(waiting, 0)

    def test_a_closed_ticket_with_a_question_left_in_it_stays_closed(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Closed\n\nStatus: done\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n')
        text, waiting = self.html()
        self.assertIn('Closed (1)', text)
        self.assertEqual(waiting, 0)

    def test_a_blocked_ticket_never_asks_by_its_question_or_its_review_page(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Blocker\n\nStatus: claimed\nBlocked by: none\n')
        ticket(self.scratch, 'e', '02-b.md', '# 02 Asks while blocked\n\nStatus: ready-for-agent\nBlocked by: 01\n\n'
                                             '## Question for the maintainer\n\nWhich?\n')
        ticket(self.scratch, 'e', '03-c.md', '# 03 Page while blocked\n\nStatus: in-review\nBlocked by: 01\nReview page: p\n')
        text, waiting = self.with_pages(p='waiting')
        self.assertEqual(self.section_of(text, 'Asks while blocked'), ['Blocked'])
        self.assertEqual(self.section_of(text, 'Page while blocked'), ['Blocked'])
        self.assertEqual((waiting, self.page_entries['E']['waiting']), (0, 0))

    def test_a_wayfinder_question_asks_the_maintainer_nothing(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Research\n\nType: research\nStatus: open\nBlocked by: none\n\n'
                                             '## Question\n\nWhich parser library?\n')
        ticket(self.scratch, 'e', '02-b.md', '# 02 Agent task\n\nType: task\nStatus: in-review\nBlocked by: none\n\n'
                                             '## Question\n\nWhat does the reader take?\n')
        text, waiting = self.html()
        self.assertEqual(self.section_of(text, 'Research'), ['Ready for an agent'])
        self.assertEqual(self.section_of(text, 'Agent task'), ['With the coordinator'])
        self.assertEqual(waiting, 0)
        self.assertEqual(board.question('# 01\n\n## Question\n\nWhich?\n'), '')

    def with_pages(self, **pages):
        """The start page with these review pages, by title: their state as the server reads it."""
        def page(title):
            return (pages[title], '/' + title + '.html') if title in pages else None
        text, waiting, entries = board.tickets_html(self.scratch, page)
        self.page_entries = {e['name']: e for e in entries}
        return text, waiting

    def test_a_ticket_whose_review_page_waits_for_answers_waits_for_you_and_links_the_page(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Looked at\n\nStatus: in-review\nBlocked by: none\nReview page: audit e 01\n')
        text, waiting = self.with_pages(**{'audit e 01': 'waiting'})
        self.assertEqual(self.section_of(text, 'Looked at'), ['Waits for you'])
        self.assertEqual(waiting, 0)          # the headline counts that page once, with the reviews
        self.assertEqual(self.page_entries['E']['waiting'], 1)
        self.assertIn('href="/audit e 01.html">review page</a>', text)
        self.assertIn('review page waits', text)

    def test_a_review_page_answered_or_to_read_asks_nothing_but_stays_linked(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Looked at\n\nStatus: in-review\nBlocked by: none\nReview page: audit e 01\n')
        for state in ('answered', 'to_read'):
            with self.subTest(state):
                text, waiting = self.with_pages(**{'audit e 01': state})
                self.assertEqual(self.section_of(text, 'Looked at'), ['With the coordinator'])
                self.assertEqual(waiting, 0)
                self.assertIn('href="/audit e 01.html">review page</a>', text)

    def test_a_review_page_taken_down_leaves_neither_wait_nor_link(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Looked at\n\nStatus: in-review\nBlocked by: none\nReview page: audit e 01\n')
        text, waiting = self.with_pages()
        self.assertEqual(self.section_of(text, 'Looked at'), ['With the coordinator'])
        self.assertNotIn('review page', text)

    def test_the_sections_come_in_the_order_of_who_has_to_act(self):
        effort_map(self.scratch, 'e')
        ticket(self.scratch, 'e', '01-a.md', '# 01 Mine to start\n\nStatus: ready-for-human\nBlocked by: none\n')
        ticket(self.scratch, 'e', '02-a.md', '# 02 At audit\n\nStatus: in-review\nBlocked by: none\n')
        ticket(self.scratch, 'e', '03-a.md', '# 03 Asking\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n')
        text = self.html()[0]
        self.assertLess(text.index('Waits for you'), text.index('With the coordinator'))
        self.assertLess(text.index('With the coordinator'), text.index('Yours to start'))

    def test_a_ticket_s_place_and_open_session_are_read_from_its_file(self):
        effort_map(self.scratch, 'effort', '# Map\n\nSessions: ef\n\n## Destination\n\nx\n')
        ticket(self.scratch, 'effort', '04-a.md', '# 04 Talk it through\n\nType: grilling\nStatus: open\nBlocked by: none\n')
        path = self.scratch / 'effort' / 'issues' / '04-a.md'
        self.assertEqual(board.placed(path, self.scratch), ('Waits for you', 'grilling'))
        for seen, name in (({}, ''), ({'ef04': 'idle'}, 'ef04'), ({'auditef04': 'working'}, 'auditef04'), ({'ef05': 'idle'}, '')):
            with self.subTest(seen):
                self.agents.return_value = seen
                self.assertEqual(board.open_session(path, self.scratch), name)

    def test_a_ticket_under_no_map_has_its_folder_as_session_prefix_and_a_postponed_one_no_place(self):
        ticket(self.scratch, 'loose', '02-a.md', '# 02 A\n\nType: grilling\nStatus: open\nBlocked by: none\n')
        self.agents.return_value = {'loose02': 'idle'}
        self.assertEqual(board.open_session(self.scratch / 'loose' / 'issues' / '02-a.md', self.scratch), 'loose02')
        effort_map(self.scratch, 'later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        ticket(self.scratch, 'later', '03-a.md', '# 03 A\n\nType: grilling\nStatus: open\nBlocked by: none\n')
        self.assertIsNone(board.placed(self.scratch / 'later' / 'issues' / '03-a.md', self.scratch))

    def test_the_line_to_tickets_writes_for_no_blockers_reads_as_none(self):
        effort_map(self.scratch, 'effort')
        ticket(self.scratch, 'effort', '01-a.md', '# 01 The ticket\n\n**Blocked by:** None (can start immediately)\n\n**Status:** ready-for-agent\n')
        self.assertEqual(self.section_of(self.html()[0], 'The ticket'), ['Ready for an agent'])

    def test_none_with_anything_else_behind_it_may_hide_a_blocker_and_is_not_readable(self):
        effort_map(self.scratch, 'effort')
        ticket(self.scratch, 'effort', '01-a.md', '# 01 The ticket\n\nStatus: ready-for-agent\nBlocked by: None (needs 03 first)\n')
        self.assertEqual(self.section_of(self.html()[0], 'The ticket'), ['Not readable'])

    def test_a_title_under_blocked_by_says_what_to_write_instead(self):
        effort_map(self.scratch, 'effort')
        ticket(self.scratch, 'effort', '02-a.md', '# 02 The ticket\n\nStatus: ready-for-agent\nBlocked by: Read the old header\n')
        text = self.html()[0]
        self.assertEqual(self.section_of(text, 'The ticket'), ['Not readable'])
        self.assertIn('Blocked by: Read the old header (write ticket numbers)', text)

    def test_without_a_sessions_line_the_prefix_is_the_folder_name(self):
        effort_map(self.scratch, 'alpha')
        ticket(self.scratch, 'alpha', '04-a.md', '# 04 A\n\nStatus: claimed\nBlocked by: none\n')
        self.agents.return_value = {'auditalpha04': 'working'}
        self.assertIn('audit running', self.html()[0])

    def test_version_changes_when_a_ticket_or_a_map_does(self):
        effort_map(self.scratch, 'e')
        before = board.version(self.scratch)
        ticket(self.scratch, 'e', '01-a.md', '# 01 A\n\nStatus: open\nBlocked by: none\n')
        after_ticket = board.version(self.scratch)
        self.assertNotEqual(before, after_ticket)
        effort_map(self.scratch, 'f')
        self.assertNotEqual(after_ticket, board.version(self.scratch))


ASKING = ('# 04 A ticket\n\nStatus: in-review\nBlocked by: none\n\nWhat was done.\n\n'
          '## Question for the maintainer\n\nKeep the old name?\n\n## Comments\n\n- audit, 2026-11-05: passed.\n')


class AnswerTest(unittest.TestCase):
    """An answer given on the ticket's page: into the comments in the person's words, and the question no longer open."""

    def answered(self, text=ASKING, answer='Yes, keep it.'):
        return board.with_answer(text, answer, 'Sam', '2026-11-05 14:30')

    def test_the_answer_is_the_newest_comment_with_who_and_when_and_the_question_is_closed(self):
        self.assertEqual(self.answered(), (
            '# 04 A ticket\n\nStatus: in-review\nBlocked by: none\n\nWhat was done.\n\n'
            '## Question for the maintainer, answered 2026-11-05 14:30\n\nKeep the old name?\n\n## Comments\n\n- audit, 2026-11-05: passed.\n'
            '- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n'))

    def test_an_answered_ticket_asks_nothing_more(self):
        self.assertEqual(board.question(ASKING), 'Keep the old name?')
        self.assertEqual(board.question(self.answered()), '')

    def test_lines_of_an_answer_stay_in_its_comment(self):
        text = self.answered(answer='First this.\r\n\r\n## Comments\nthen that.')
        self.assertTrue(text.endswith('- Sam, 2026-11-05 14:30, answer on the dashboard: First this.\n\n'
                                      '  ## Comments\n  then that.\n'))
        self.assertEqual(text.count('\n## Comments'), 1)

    def test_control_characters_do_not_reach_the_ticket(self):
        text = self.answered(answer='C:\\docs\x0coo\tand\x07 more')
        self.assertTrue(text.endswith('answer on the dashboard: C:\\docsoo    and more\n'))

    def test_a_ticket_without_comments_gets_them(self):
        text = self.answered('# 04 A\n\nStatus: claimed\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n')
        self.assertTrue(text.endswith('## Question for the maintainer, answered 2026-11-05 14:30\n\nWhich?\n\n## Comments\n\n'
                                      '- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n'))

    def test_the_answer_goes_under_comments_when_a_section_follows_them(self):
        text = self.answered('# 04 A\n\nStatus: claimed\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n\n'
                             '## Comments\n\n- one.\n\n## Answer\n\nThe decision.\n')
        self.assertIn('- one.\n- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n\n## Answer\n\nThe decision.\n', text)

    def test_with_two_questions_the_first_is_answered_and_the_second_stays_open(self):
        text = self.answered('# 04 A\n\nStatus: claimed\nBlocked by: none\n\n## Question for the maintainer\n\nFirst?\n\n## Question for the maintainer\n\nSecond?\n')
        self.assertEqual(board.question(text), 'Second?')

    def test_a_question_heading_inside_a_code_block_asks_nothing(self):
        text = ('# 04 A\n\nStatus: claimed\nBlocked by: none\n\nHow a ticket asks:\n\n```\n## Question for the maintainer\n\nWhich?\n```\n\n'
                '~~~\n## Question for the maintainer\n~~~\n')
        self.assertEqual(board.question(text), '')
        with self.assertRaises(ValueError):
            self.answered(text)
        self.assertEqual(board.question(text + '\n## Question for the maintainer\n\nReally this?\n'), 'Really this?')
        self.assertIn('```\n## Question for the maintainer\n', self.answered(text + '\n## Question for the maintainer\n\nReally this?\n'))

    def test_a_comments_heading_inside_a_code_block_does_not_take_the_answer(self):
        text = ('# 04 A\n\nStatus: claimed\nBlocked by: none\n\nA ticket as it was quoted:\n\n```\n## Comments\n\n- old.\n```\n\n'
                '## Question for the maintainer\n\nWhich?\n\n## Comments\n\n- one.\n')
        self.assertEqual(self.answered(text), text.replace('## Question for the maintainer\n', '## Question for the maintainer, '
                         'answered 2026-11-05 14:30\n') + '- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n')

    def test_a_section_heading_inside_a_code_block_does_not_end_the_question(self):
        text = '# 04 A\n\n## Question for the maintainer\n\nWhich of these?\n\n```\n## Not a section\n```\n\n## Comments\n'
        self.assertEqual(board.question(text), 'Which of these?\n\n```\n## Not a section\n```')

    def test_a_longer_fence_quoting_a_shorter_one_closes_only_with_its_own_length(self):
        text = ('# 04 A\n\nHow a ticket quotes one:\n\n````\n```\n## Question for the maintainer\n\nQuoted?\n```\n\n## Comments\n````\n\n'
                '## Question for the maintainer\n\nReally this?\n\n## Comments\n\n- one.\n')
        self.assertEqual(board.question(text), 'Really this?')
        self.assertTrue(self.answered(text).endswith('## Comments\n\n- one.\n- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n'))
        self.assertIn('````\n```\n## Question for the maintainer\n\nQuoted?\n```\n\n## Comments\n````', self.answered(text))

    def test_a_tilde_fence_holding_a_backtick_line_closes_only_with_tildes(self):
        text = ('# 04 A\n\n~~~\n```\n## Question for the maintainer\n\nQuoted?\n\n## Comments\n~~~\n\n'
                '## Question for the maintainer\n\nReally this?\n\n## Comments\n\n- one.\n')
        self.assertEqual(board.question(text), 'Really this?')
        self.assertTrue(self.answered(text).endswith('## Comments\n\n- one.\n- Sam, 2026-11-05 14:30, answer on the dashboard: Yes, keep it.\n'))

    def test_a_fence_left_open_hides_the_rest_and_a_closing_fence_takes_nothing_after_it(self):
        self.assertEqual(board.question('# 04 A\n\n```\n## Question for the maintainer\n\nWhich?\n'), '')
        self.assertEqual(board.question('# 04 A\n\n```\n``` not a close\n## Question for the maintainer\n\nWhich?\n'), '')

    def test_an_answer_with_a_code_block_keeps_it_inside_its_entry(self):
        text = ('# 04 A\n\n## Question for the maintainer\n\nFirst?\n\n## Question for the maintainer\n\nSecond?\n\n'
                '## Comments\n\n- one.\n\n## Notes\n\nKept apart.\n')
        once = board.with_answer(text, '```\ncode\n```', 'Sam', '2026-11-05 14:30')
        self.assertIn('- Sam, 2026-11-05 14:30, answer on the dashboard:\n  ```\n  code\n  ```\n\n## Notes', once)
        self.assertTrue(all(end < once.index('## Notes') for _, end in board.code_blocks(once)))
        twice = board.with_answer(once, 'Plain.', 'Sam', '2026-11-05 14:31')
        self.assertTrue(twice.endswith('  ```\n- Sam, 2026-11-05 14:31, answer on the dashboard: Plain.\n\n## Notes\n\nKept apart.\n'))

    def test_a_code_block_an_answer_leaves_open_is_closed_in_its_entry(self):
        text = board.with_answer(ASKING, 'Like this:\n~~~~\ncode', 'Sam', '2026-11-05 14:30')
        self.assertTrue(text.endswith('answer on the dashboard: Like this:\n  ~~~~\n  code\n  ~~~~\n'))
        self.assertEqual(board.code_blocks(text)[-1][1], len(text) - 1)

    def test_no_open_question_or_a_blank_answer_writes_nothing(self):
        with self.assertRaises(ValueError):
            self.answered(self.answered())
        with self.assertRaises(ValueError):
            self.answered(answer=' \n\t ')


class WithoutHerdrTest(unittest.TestCase):
    def test_no_herdr_means_no_sessions(self):
        with mock.patch.object(board, '_agents', (0.0, {})), \
                mock.patch.object(board.subprocess, 'run', side_effect=FileNotFoundError('herdr')):
            self.assertEqual(board.agents(), {})


class DefaultScratchTest(unittest.TestCase):
    def git(self, folder, *args):
        subprocess.run(['git', '-C', str(folder), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                       check=True, capture_output=True)

    def test_a_worktree_shares_the_scratch_of_the_main_tree(self):
        base = made_up_repo(self).resolve()
        main = base / 'main'
        main.mkdir()
        self.git(main, 'init')
        self.git(main, 'commit', '--allow-empty', '-m', 'first')
        self.git(main, 'worktree', 'add', str(base / 'other'))
        self.assertEqual(board.default_scratch(base / 'other').resolve(), main / '.scratch')

    def test_it_is_of_the_folder_asked_about_with_a_parents_git_context_inherited(self):
        base = made_up_repo(self).resolve()
        a, b = base / 'a', base / 'b'
        for repo in (a, b):
            repo.mkdir()
            self.git(repo, 'init')
        with mock.patch.dict(os.environ, {'GIT_DIR': str(a / '.git'), 'GIT_WORK_TREE': str(a),
                                          'GIT_COMMON_DIR': str(a / '.git')}):
            self.assertEqual(board.default_scratch(b).resolve(), b / '.scratch')

    def test_outside_git_it_is_two_levels_above_the_tools(self):
        repo = made_up_repo(self).resolve()
        tools = repo / 'tools' / 'dashboard'
        tools.mkdir(parents=True)
        with mock.patch.object(board.subprocess, 'run', side_effect=FileNotFoundError('git')):
            self.assertEqual(board.default_scratch(tools).resolve(), repo / '.scratch')


class GitsOwnList(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_every_name_of_git_is_dropped(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in board.GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
