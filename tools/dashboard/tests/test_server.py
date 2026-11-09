"""The server on a made-up .scratch, reached like a browser reaches it."""
import contextlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from .support import Server, TOOLS, class_repo, effort_map, made_up_repo, ticket

import board  # noqa: E402
import review_page  # noqa: E402
import review_server  # noqa: E402


class Events:
    """Reads an event stream on its own socket, so a test can also see when the server notices it closing."""

    def __init__(self, port, query):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=8)
        self.sock.sendall(f'GET /events?{query} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n'.encode())
        self.buf = b''

    def next(self):
        while b'\n\n' not in self.buf.split(b'\r\n\r\n', 1)[-1] or b'event: update' not in self.buf:
            data = self.sock.recv(65536)
            if not data:
                raise EOFError(self.buf)
            self.buf += data
        head, _, rest = self.buf.rpartition(b'event: update\ndata: ')
        line, _, tail = rest.partition(b'\n\n')
        self.buf = b'\r\n\r\n' + tail
        return json.loads(line)

    def close(self):
        self.sock.close()


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = class_repo(cls)
        cls.scratch = cls.repo / '.scratch'
        cls.root = cls.scratch / 'reviews'
        (cls.root / 'answers').mkdir(parents=True)
        (cls.repo / 'CLAUDE.md').write_text('not a document of the dashboard', encoding='utf-8')
        (cls.repo / 'docs').mkdir()
        (cls.repo / 'docs' / 'guide.md').write_text('---\ntype: How-To\n---\n# A guide\n', encoding='utf-8')
        (cls.scratch / 'private-note.md').write_text('private', encoding='utf-8')
        (cls.scratch / 'no-map' / 'issues').mkdir(parents=True)
        (cls.scratch / 'no-map' / 'issues' / '01-old.md').write_text('# 01 Old\n\nStatus: open\nBlocked by: none\n', encoding='utf-8')
        (cls.scratch / 'no-map' / 'spec.md').write_text('# A spec\n', encoding='utf-8')
        for nested in ('trial/docs/copy-of-a-private-note.md', 'issues/sub/deeper.md'):
            (cls.scratch / 'no-map' / nested).parent.mkdir(parents=True)
            (cls.scratch / 'no-map' / nested).write_text('private', encoding='utf-8')
        (cls.scratch / 'notes').mkdir()
        (cls.scratch / 'notes' / 'x.md').write_text('private', encoding='utf-8')
        effort_map(cls.scratch, 'alpha')
        ticket(cls.scratch, 'alpha', '01-first.md', '# 01 First ticket\n\nType: task\nStatus: ready-for-agent\nBlocked by: none\n')
        (cls.scratch / 'alpha' / 'research').mkdir()
        (cls.scratch / 'alpha' / 'research' / 'deep.md').write_text('# Research of a mapped effort\n', encoding='utf-8')
        cls.server = Server(cls.scratch)
        cls.port = cls.server.port

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def get(self, path):
        return self.server.get(path)

    def status_code(self, path, data=None, headers=None):
        return self.server.status_code(path, data, headers)

    def page(self, name, *asks):
        args = ['--root', str(self.scratch), '--title', name, '--no-open']
        for ask in asks or ('Which one?',):
            args += ['--ask', ask]
        self.command(args)

    def command(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(review_page.main(args), 0)

    def tearDown(self):
        for f in list(self.root.glob('*.html')) + list((self.root / 'answers').glob('*')):
            f.unlink()
        for folder in (self.root / 'done', self.root / 'files'):      # only some tests make them
            if folder.exists():
                shutil.rmtree(folder)

    def test_start_page_gets_a_new_review_without_a_reload(self):
        ev = Events(self.port, 'start=1')
        self.addCleanup(ev.close)
        first = ev.next()
        self.assertIn('Reviews', first['parts']['reviews'])
        self.page('t new page')
        second = ev.next()
        self.assertIn('t new page', second['parts']['reviews'])
        self.assertIn('1 review', second['parts']['summary'])
        self.assertIn('(', second['title'])

    def test_review_page_connection_sees_rebuild_and_removal(self):
        self.page('t rebuilt')
        ev = Events(self.port, 'page=t%20rebuilt.html')
        self.addCleanup(ev.close)
        first = ev.next()['stamp']
        time.sleep(0.05)
        self.page('t rebuilt', 'Another?')
        second = ev.next()['stamp']
        self.assertNotEqual(first, second)
        (self.root / 't rebuilt.html').unlink()
        self.assertIsNone(ev.next()['stamp'])

    def test_served_review_page_has_shared_style_form_and_its_stamp(self):
        self.page('t form')
        text = self.get('/t%20form.html')
        self.assertIn('--you:', text)
        self.assertIn('class="review"', text)
        self.assertIn('<script src="/review_form.js"></script>', text)
        self.assertRegex(text, r'reviewForm\("\d+"\)')
        self.assertIn('Send answers', self.get('/review_form.js'))

    def test_a_ticket_title_opens_its_file_and_a_doc_opens_from_docs(self):
        text = self.get('/')
        self.assertIn('/doc/.scratch/alpha/issues/01-first.md', text)
        self.assertIn('dashboardDoc', self.get('/doc/.scratch/alpha/issues/01-first.md'))
        self.assertIn('A guide', self.get('/doc/docs/guide.md'))

    def test_a_ticket_under_no_map_opens_its_file(self):
        self.assertIn('/doc/.scratch/no-map/issues/01-old.md', self.get('/'))
        self.assertIn('dashboardDoc', self.get('/doc/.scratch/no-map/issues/01-old.md'))

    def test_the_contents_list_starts_with_reviews_and_jumps_to_each_topic(self):
        text = self.get('/')
        contents = re.search(r'<nav[^>]*class="topics".*?</nav>', text, re.S).group(0)
        self.assertEqual(re.findall(r'href="#([^"]+)"', contents), ['reviews', 'effort-alpha', 'no-map'])
        for target in ('id="reviews"', 'id="effort-alpha"', 'id="no-map"'):
            self.assertIn(target, text)
        self.assertLess(text.index('class="summary'), text.index('class="topics"'))

    def test_the_contents_list_counts_reviews_and_updates_live(self):
        ev = Events(self.port, 'start=1')
        self.addCleanup(ev.close)
        self.assertNotIn('class="you"', ev.next()['parts']['topics'])
        self.page('t counted')
        topics = ev.next()['parts']['topics']
        self.assertIn('<span class="you">● 1</span>', topics)
        self.assertIn('1 open', topics)

    def test_waiting_tickets_without_a_map_count_in_the_headline(self):
        ticket(self.scratch, 'loose-waits', '01-a.md', '# 01 A\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n')
        self.addCleanup(shutil.rmtree, self.scratch / 'loose-waits')
        text = self.get('/')
        self.assertIn('1 ticket waits for you.', text)
        self.assertIn('<title>(1) Development dashboard</title>', text)

    def test_a_folder_without_a_map_opens_its_tickets_and_top_files_and_nothing_deeper(self):
        self.assertEqual(self.status_code('/doc/.scratch/no-map/issues/01-old.md'), 200)
        self.assertEqual(self.status_code('/doc/.scratch/no-map/spec.md'), 200)
        self.assertEqual(self.status_code('/doc/.scratch/no-map/trial/docs/copy-of-a-private-note.md'), 404)
        self.assertEqual(self.status_code('/doc/.scratch/no-map/issues/sub/deeper.md'), 404)
        self.assertEqual(self.status_code('/events?doc=.scratch/no-map/trial/docs/copy-of-a-private-note.md'), 404)

    def test_an_effort_with_a_map_keeps_its_whole_folder(self):
        self.assertEqual(self.status_code('/doc/.scratch/alpha/research/deep.md'), 200)

    def test_every_id_on_the_start_page_is_there_once(self):
        ticket(self.scratch, 'alpha', '09-closed.md', '# 09 Closed\n\nStatus: done\nBlocked by: none\n')
        ticket(self.scratch, 'no-map', '09-closed.md', '# 09 Closed\n\nStatus: done\nBlocked by: none\n')
        self.addCleanup((self.scratch / 'alpha' / 'issues' / '09-closed.md').unlink)
        self.addCleanup((self.scratch / 'no-map' / 'issues' / '09-closed.md').unlink)
        ids = re.findall(r'\bid="([^"]+)"', self.get('/'))
        self.assertIn('closed-alpha', ids)
        self.assertIn('closed-no-map', ids)
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_doc_links_stay_inside_docs_and_efforts(self):
        self.assertEqual(self.status_code('/doc/CLAUDE.md'), 404)
        self.assertEqual(self.status_code('/doc/.scratch/../CLAUDE.md'), 404)
        self.assertEqual(self.status_code('/doc/.scratch/private-note.md'), 404)
        self.assertEqual(self.status_code('/doc/.scratch/notes/x.md'), 404)
        self.assertEqual(self.status_code('/events?doc=CLAUDE.md'), 404)
        self.assertEqual(self.status_code('/events?page=..%2Fx.html'), 404)

    def test_answer_is_written_and_only_json_is_taken(self):
        self.page('t answer')
        body = json.dumps({'title': 't', 'answers': [{'question': 'q', 'answer': 'a'}], 'comment': ''}).encode()
        self.assertEqual(self.status_code('/answer/t%20answer.html', body, {'Content-Type': 'text/plain'}), 415)
        self.assertFalse((self.root / 'answers' / 't answer.json').exists())
        self.assertEqual(self.status_code('/answer/t%20answer.html', body, {'Content-Type': 'application/json'}), 200)
        self.assertEqual(json.loads((self.root / 'answers' / 't answer.json').read_text(encoding='utf-8'))['answers'][0]['answer'], 'a')

    def test_an_answer_stays_inside_the_answers_folder(self):
        body = json.dumps({'answers': []}).encode()
        code = self.status_code('/answer/..%5C..%5Cescaped.html', body, {'Content-Type': 'application/json'})
        self.assertEqual(code, 404)
        self.assertFalse((self.scratch / 'escaped.json').exists())

    def asking_ticket(self, text='# 05 Asks you\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nKeep the **old** name?\n\n'
                                 '## Comments\n\n- audit, 2026-11-05: passed.\n'):
        """A ticket of the effort alpha with these very bytes, gone after the test; its address on the dashboard."""
        (self.scratch / 'alpha' / 'issues' / '05-asks.md').write_bytes(text.encode('utf-8'))
        self.addCleanup((self.scratch / 'alpha' / 'issues' / '05-asks.md').unlink, missing_ok=True)
        return '.scratch/alpha/issues/05-asks.md'

    def answer_ticket(self, rel, question, answer, kind='application/json'):
        body = json.dumps({'ticket': rel, 'question': question, 'answer': answer}).encode()
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/answer-ticket', data=body, headers={'Content-Type': kind})
        try:
            with urllib.request.urlopen(request, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    def test_a_ticket_that_asks_shows_its_question_with_an_answer_box_on_its_page(self):
        rel = self.asking_ticket()
        self.assertIn('1 ticket waits for you.', self.get('/'))
        text = self.get('/doc/' + rel)
        self.assertIn('id="ticket-ask"', text)
        self.assertIn('<script src="/review_form.js"></script>', text)
        self.assertRegex(text, r'ticketForm\(".scratch/alpha/issues/05-asks.md", "Keep the \*\*old\*\* name\?", "\d+"\)')
        self.assertIn('Send answer', self.get('/review_form.js'))

    def test_an_answer_goes_into_the_ticket_and_it_waits_no_more(self):
        rel = self.asking_ticket()
        code, reply = self.answer_ticket(rel, 'Keep the **old** name?', 'Yes.\nThe new one confuses.')
        self.assertEqual((code, reply['ok']), (200, True))
        text = (self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes().decode('utf-8')
        self.assertIn(f'## Question for the maintainer, answered {reply["at"]}\n', text)
        self.assertRegex(text, r'- audit, 2026-11-05: passed\.\n- .+, ' + re.escape(reply['at'])
                         + r', answer on the dashboard: Yes\.\n  The new one confuses\.\n$')
        self.assertNotIn('\r', text)
        self.assertIn('Nothing waits for you.', self.get('/'))
        self.assertNotIn('id="ticket-ask"', self.get('/doc/' + rel))

    def test_a_ticket_with_windows_line_ends_keeps_them(self):
        rel = self.asking_ticket('# 05 A\r\n\r\nStatus: claimed\r\nBlocked by: none\r\n\r\n## Question for the maintainer\r\n\r\nWhich?\r\n')
        self.assertEqual(self.answer_ticket(rel, 'Which?', 'This.')[0], 200)
        text = (self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes().decode('utf-8')
        self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertIn('answer on the dashboard: This.\r\n', text)

    def test_a_ticket_with_a_byte_order_mark_and_lone_carriage_returns_keeps_both(self):
        rel = self.asking_ticket('\ufeff# 05 A\r\rStatus: claimed\rBlocked by: none\r\r'
                                 '## Question for the maintainer\r\rWhich?\r\r## Comments\r\r- one.\r')
        self.assertIn('ticketForm(', self.get('/doc/' + rel))
        code, reply = self.answer_ticket(rel, 'Which?', 'This.\nAnd that.')
        self.assertEqual(code, 200)
        raw = (self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes()
        self.assertEqual(raw.decode('utf-8'), '\ufeff# 05 A\r\rStatus: claimed\rBlocked by: none\r\r'
                         f'## Question for the maintainer, answered {reply["at"]}\r\rWhich?\r\r## Comments\r\r'
                         f'- one.\r- {self.who()}, {reply["at"]}, answer on the dashboard: This.\r  And that.\r')

    def test_a_ticket_with_unix_line_ends_keeps_them(self):
        rel = self.asking_ticket('# 05 A\n\nStatus: claimed\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n')
        code, reply = self.answer_ticket(rel, 'Which?', 'This.')
        self.assertEqual(code, 200)
        self.assertEqual((self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes().decode('utf-8'),
                         '# 05 A\n\nStatus: claimed\nBlocked by: none\n\n'
                         f'## Question for the maintainer, answered {reply["at"]}\n\nWhich?\n\n## Comments\n\n'
                         f'- {self.who()}, {reply["at"]}, answer on the dashboard: This.\n')

    def who(self):
        """The name the server gives an answer: git's user.name where the test runs, as the server asks git in this repo."""
        out = subprocess.run(['git', '-C', str(self.repo), 'config', 'user.name'], capture_output=True, text=True)
        return out.stdout.strip() or 'Dashboard user'

    def test_an_answer_on_a_ticket_s_page_leaves_a_record_for_the_watch(self):
        rel = self.asking_ticket()
        code, reply = self.answer_ticket(rel, 'Keep the **old** name?', 'Yes.')
        self.assertEqual(code, 200)
        self.addCleanup(shutil.rmtree, self.root.parent / 'reviews' / 'ticket-answers')
        record = json.loads((self.root / 'ticket-answers' / 'alpha-05-asks.json').read_text(encoding='utf-8'))
        self.assertEqual(record, {'ticket': rel, 'at': reply['at'], 'who': self.who(), 'answer': 'Yes.'})

    def test_an_answer_to_a_question_changed_since_the_page_opened_is_refused(self):
        rel = self.asking_ticket()
        before = (self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes()
        code, reply = self.answer_ticket(rel, 'Rename it?', 'Yes.')
        self.assertEqual(code, 409)
        self.assertIn('reload', reply['error'])
        self.assertEqual((self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes(), before)

    def test_a_ticket_that_does_not_wait_for_you_has_no_answer_box_and_takes_no_answer(self):
        effort_map(self.scratch, 'later', '# Map\n\n## Notes\n\n- Postponed for now.\n')
        self.addCleanup(shutil.rmtree, self.scratch / 'later')
        for name, effort, head in (('blocked', 'alpha', 'Status: ready-for-agent\nBlocked by: 01\n'),   # 01 is open: ready-for-agent
                                   ('closed', 'alpha', 'Status: done\nBlocked by: none\n'),
                                   ('not readable', 'alpha', 'Status: sort of done\nBlocked by: none\n'),
                                   ('postponed', 'later', 'Status: in-review\nBlocked by: none\n')):
            with self.subTest(name):
                f = self.scratch / effort / 'issues' / '05-asks.md'
                f.parent.mkdir(exist_ok=True)
                f.write_bytes(f'# 05 Asks {name}\n\n{head}\n## Question for the maintainer\n\nWhich?\n'.encode('utf-8'))
                self.addCleanup(f.unlink, missing_ok=True)
                rel = f'.scratch/{effort}/issues/05-asks.md'
                before = f.read_bytes()
                self.assertIn('Nothing waits for you.', self.get('/'))
                self.assertNotIn('id="ticket-ask"', self.get('/doc/' + rel))
                code, reply = self.answer_ticket(rel, 'Which?', 'This.')
                self.assertEqual((code, reply), (409, {'ok': False, 'error': 'the ticket does not wait for your answer now: reload'}))
                self.assertEqual(f.read_bytes(), before)

    def test_an_open_grilling_or_prototype_says_at_the_top_it_waits_in_its_session(self):
        for kind in ('grilling', 'prototype'):
            with self.subTest(kind):
                rel = self.asking_ticket(f'# 05 Talk\n\nType: {kind}\nStatus: open\nBlocked by: none\n\n## Question\n\nWhich way?\n')
                text = self.get('/doc/' + rel)
                self.assertIn(f'<p class="ticket-page you">This {kind} waits for you in its session: answer it there.</p>', text)
                self.assertLess(text.index('ticket-page you'), text.index('id="doc"'))
                self.assertNotIn('id="ticket-ask"', text)

    def test_a_blocked_or_closed_grilling_says_nothing_of_a_session(self):
        for head in ('Status: open\nBlocked by: 01\n', 'Status: resolved\nBlocked by: none\n'):
            with self.subTest(head):
                rel = self.asking_ticket(f'# 05 Talk\n\nType: grilling\n{head}\n## Question\n\nWhich way?\n')
                self.assertNotIn('in its session', self.get('/doc/' + rel))

    def test_a_blank_answer_or_one_not_in_json_is_refused(self):
        rel = self.asking_ticket()
        before = (self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes()
        self.assertEqual(self.answer_ticket(rel, 'Keep the **old** name?', '  \n ')[0], 400)
        self.assertEqual(self.answer_ticket(rel, 'Keep the **old** name?', 'Yes.', 'text/plain')[0], 415)
        self.assertEqual((self.scratch / 'alpha' / 'issues' / '05-asks.md').read_bytes(), before)

    def test_an_answer_goes_only_into_a_ticket(self):
        self.asking_ticket()
        for rel in ('docs/guide.md', '.scratch/alpha/research/deep.md', '.scratch/private-note.md', 'CLAUDE.md',
                    '.scratch/alpha/issues/../../alpha/issues/05-asks.md/..', '.scratch/alpha/issues/09-none.md'):
            with self.subTest(rel):
                self.assertEqual(self.answer_ticket(rel, 'Keep the **old** name?', 'Yes.')[0], 404)
        self.assertEqual((self.repo / 'docs' / 'guide.md').read_text(encoding='utf-8'), '---\ntype: How-To\n---\n# A guide\n')

    def test_a_ticket_whose_review_page_waits_links_it_from_the_board_and_its_page(self):
        rel = self.asking_ticket('# 05 Looked at\n\nStatus: in-review\nBlocked by: none\nReview page: t about 05\n')
        self.assertIn('Nothing waits for you.', self.get('/'))
        self.page('t about 05')
        board_text = self.get('/')
        self.assertIn('1 review waits for you.', board_text)      # one ask, counted once
        self.assertIn('href="/t%20about%2005.html">review page</a>', board_text)
        text = self.get('/doc/' + rel)
        self.assertIn('href="/t%20about%2005.html"', text)
        self.assertIn('waits for your answers on its review page', text)
        self.assertNotIn('id="ticket-ask"', text)
        self.answer('t about 05', 'Which one?')
        self.assertIn('Nothing waits for you.', self.get('/'))
        self.assertIn('href="/t%20about%2005.html">review page</a>', self.get('/'))

    def test_a_page_with_no_questions_waits_for_nobody(self):
        args = ['--root', str(self.scratch), '--title', 't to read', '--note', 'Just so you know.', '--no-open']
        self.command(args)
        text = self.get('/')
        self.assertIn('t to read', text)
        self.assertIn('To read', text)
        self.assertIn('Nothing waits for you.', text)

    def answer(self, page, *questions):
        self.send(page, [(q, 'yes') for q in questions])

    def test_a_page_rebuilt_with_a_new_question_waits_again(self):
        self.page('t again', 'First?')
        self.answer('t again', 'First?')
        self.assertIn('Nothing waits for you.', self.get('/'))
        self.page('t again', 'First?', 'Second?')
        text = self.get('/')
        self.assertIn('1 review waits', text)
        self.assertIn('1 question not answered', text)
        self.answer('t again', 'First?', 'Second?')
        self.assertIn('Nothing waits for you.', self.get('/'))

    def send(self, page, answers, comment=''):
        body = json.dumps({'title': page, 'comment': comment,
                           'answers': [{'question': q, 'answer': a} for q, a in answers]}).encode()
        name = urllib.parse.quote(page)
        self.assertEqual(self.status_code(f'/answer/{name}.html', body, {'Content-Type': 'application/json'}), 200)

    def test_a_blank_answer_leaves_the_page_waiting(self):
        self.page('t blank', 'Merge it?')
        self.send('t blank', [('Merge it?', '  \n')])
        text = self.get('/')
        self.assertIn('1 review waits', text)
        self.assertIn('1 question not answered', text)
        self.send('t blank', [('Merge it?', 'yes')])
        self.assertIn('Nothing waits for you.', self.get('/'))

    def test_a_blank_send_on_a_page_with_no_questions_stays_to_read(self):
        self.command(['--root', str(self.scratch), '--title', 't blank read', '--note', 'Just so you know.', '--no-open'])
        self.send('t blank read', [], comment='  ')
        text = self.get('/')
        self.assertIn('To read (1)', text)
        self.assertNotIn('Answered, the agent is on it', text)
        self.send('t blank read', [], comment='Read it, thanks.')
        self.assertIn('Answered, the agent is on it', self.get('/'))

    def test_a_page_with_some_answers_blank_counts_only_those(self):
        self.page('t part', 'First?', 'Second?', 'Third?')
        self.send('t part', [('First?', 'yes'), ('Second?', ''), ('Third?', ' ')], comment='a comment answers no question')
        text = self.get('/')
        self.assertIn('1 review waits', text)
        self.assertIn('2 questions not answered', text)

    def take_down(self, name):
        self.command(['--root', str(self.scratch), '--done', name])

    def test_a_page_built_after_it_was_taken_down_says_it_is_a_new_round(self):
        self.page('t round')
        self.assertNotIn('round 1', self.get('/'))
        self.assertNotIn('round 2', self.get('/'))
        self.take_down('t round')
        self.page('t round')
        self.assertIn('round 2, 1 question', self.get('/'))
        self.take_down('t round')
        self.page('t round')
        self.assertIn('round 3, 1 question', self.get('/'))

    def test_a_page_rebuilt_after_an_answer_is_a_new_round_and_before_one_is_not(self):
        self.page('t rebuilt round', 'First?')
        self.page('t rebuilt round', 'First?', 'Better worded?')
        self.assertNotIn('round 2', self.get('/'))
        self.answer('t rebuilt round', 'First?', 'Better worded?')
        self.page('t rebuilt round', 'First?', 'Better worded?', 'Second?')
        self.assertIn('round 2, 1 question not answered', self.get('/'))
        self.page('t rebuilt round', 'First?', 'Better worded?', 'Second, better worded?')
        self.assertIn('round 2, 1 question not answered', self.get('/'))

    def test_an_answer_written_in_the_same_clock_tick_as_a_rebuild_is_not_counted_twice(self):
        self.page('t tick', 'First?')
        self.answer('t tick', 'First?')
        self.page('t tick', 'First?', 'Second?')
        page, answers = self.root / 't tick.html', self.root / 'answers' / 't tick.json'
        same = answers.stat().st_mtime_ns
        os.utime(page, ns=(same, same))
        self.page('t tick', 'First?', 'Second, better worded?')
        self.assertIn('round 2, 1 question not answered', self.get('/'))

    def test_answers_sent_again_after_a_rebuild_start_the_next_round(self):
        self.page('t again round', 'First?')
        self.answer('t again round', 'First?')
        self.page('t again round', 'First?', 'Second?')
        self.answer('t again round', 'First?', 'Second?')
        self.page('t again round', 'First?', 'Second?', 'Third?')
        self.assertIn('round 3, 1 question not answered', self.get('/'))

    def test_answers_moved_by_hand_start_no_round(self):
        self.page('t moved', 'First?')
        self.answer('t moved', 'First?')
        self.page('t moved', 'First?')
        (self.root / 'answers' / 't moved.json').unlink()
        self.page('t moved', 'First?')
        self.assertIn('round 2, 1 question', self.get('/'))

    def test_rounds_add_up_over_a_rebuild_and_a_take_down(self):
        self.page('t mixed', 'First?')
        self.answer('t mixed', 'First?')
        self.page('t mixed', 'Second?')
        self.take_down('t mixed')
        self.page('t mixed', 'Third?')
        self.assertIn('round 3, 1 question', self.get('/'))

    def test_pages_taken_down_before_rounds_existed_count_as_rounds(self):
        for folder in ('t old', 't old 2'):
            (self.root / 'done' / folder).mkdir(parents=True)
            (self.root / 'done' / folder / 't old.html').write_text('<html><body>old</body></html>', encoding='utf-8')
        self.page('t old')
        self.assertIn('round 3, 1 question', self.get('/'))

    def test_a_page_named_like_a_second_take_down_is_a_page_of_its_own(self):
        self.page('t name')
        self.take_down('t name')
        self.page('t name 2')
        self.assertNotIn('round 2', self.get('/'))

    def test_a_new_round_says_so_on_the_page_too(self):
        self.page('t on page')
        self.take_down('t on page')
        self.page('t on page')
        self.assertIn('round 2', self.get('/t%20on%20page.html'))

    def test_a_question_with_special_characters_counts_as_answered(self):
        question = 'Keep <b> & "quotes"?'
        self.page('t special', question)
        self.assertIn('1 review waits', self.get('/'))
        self.answer('t special', question)
        self.assertIn('Nothing waits for you.', self.get('/'))

    def test_a_hand_built_page_counts_what_the_form_gives_a_box(self):
        (self.root / 't hand.html').write_text(
            '<html><body><main><div class="ask"><ul><li>One?</li><li>Two <b>bold</b> rest?</li></ul></div>'
            '<section><h2>Notes</h2><ul><li>Not a question.</li></ul></section></main></body></html>', encoding='utf-8')
        text = self.get('/')
        self.assertIn('1 review waits', text)
        self.assertIn('2 questions', text)
        self.answer('t hand', 'One?', 'Two ')       # what the form sends: each item's first node
        self.assertIn('Nothing waits for you.', self.get('/'))

    def test_a_page_or_answer_it_cannot_read_leaves_the_start_page_up_and_says_so(self):
        self.page('t good', 'Still here?')
        self.page('t bad answer', 'Why?')
        (self.root / 'answers' / 't bad answer.json').write_text('{not json', encoding='utf-8')
        (self.root / 't bad page.html').write_bytes(b'<li><span>caf\xe9</span></li>')
        text = self.get('/')
        self.assertIn('Not readable (2)', text)
        self.assertIn('t bad answer', text)
        self.assertIn('t bad page', text)
        self.assertIn('t good', text)
        self.assertIn('1 review waits', text)
        self.assertEqual(self.status_code('/t%20bad%20page.html'), 200)

    def test_a_page_taken_down_leaves_the_start_page_and_its_connection_hears_it(self):
        self.page('t down')
        self.assertIn('1 review waits', self.get('/'))
        ev = Events(self.port, 'page=t%20down.html')
        self.addCleanup(ev.close)
        self.assertIsNotNone(ev.next()['stamp'])
        self.command(['--root', str(self.scratch), '--done', 't down'])
        self.assertIsNone(ev.next()['stamp'])
        self.assertNotIn('t down', self.get('/'))

    def test_nothing_a_page_loads_comes_from_the_internet(self):
        self.page('t local')
        pages = [self.get(p) for p in ('/', '/t%20local.html', '/doc/docs/guide.md', '/dashboard.css', '/dashboard.js', '/review_form.js')]
        for text in pages:
            self.assertEqual(re.findall(r'(?:src|href)="https?:[^"]*"|url\([\'"]?https?:[^)]*\)|@import[^;]*', text), [])

    def test_the_files_pages_load_are_served(self):
        for path in re.findall(r"url\('(/vendor/[^']+)'\)", self.get('/dashboard.css')) + ['/vendor/marked.min.js']:
            self.assertEqual(self.status_code(path), 200, path)
        self.assertEqual(self.status_code('/vendor/..%5Clive.py'), 404)


class HostTest(unittest.TestCase):
    """A web page whose name someone has pointed at 127.0.0.1 can reach this server from a browser, as its own site."""

    @classmethod
    def setUpClass(cls):
        cls.repo = class_repo(cls)
        cls.scratch = cls.repo / '.scratch'
        (cls.scratch / 'reviews' / 'answers').mkdir(parents=True)
        (cls.scratch / 'reviews' / 'Asked.html').write_text('<html><body><p>page</p></body></html>', encoding='utf-8')
        cls.server = Server(cls.scratch)
        cls.addClassCleanup(cls.server.stop)

    def setUp(self):
        self.answer = self.scratch / 'reviews' / 'answers' / 'Asked.json'
        self.answer.unlink(missing_ok=True)

    def ask(self, method, host, path='/', body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=10)
        self.addCleanup(c.close)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader('Host', host)
        if body is not None:
            c.putheader('Content-Type', 'application/json')
            c.putheader('Content-Length', str(len(body)))
        c.endheaders(body)
        return c.getresponse().status

    def raw(self, head):
        with socket.create_connection(('127.0.0.1', self.server.port), timeout=10) as s:
            s.sendall(head.encode())
            return s.recv(64).split(b' ')[1]

    def post(self, host):
        return self.ask('POST', host, '/answer/Asked.html', json.dumps({'title': 'Asked', 'answers': []}).encode())

    def test_this_machine_by_name_or_address_with_the_server_s_port_gets_in(self):
        for host in (f'127.0.0.1:{self.server.port}', f'localhost:{self.server.port}', f'LOCALHOST:{self.server.port}'):
            self.assertEqual(self.ask('GET', host), 200, host)

    def test_any_other_host_is_refused(self):
        port = self.server.port
        for host in ('attacker.example', f'attacker.example:{port}', '127.0.0.1', 'localhost', '127.0.0.1:1', 'localhost:1',
                     f'127.0.0.1.attacker.example:{port}', f'localhost.:{port}', f'[::1]:{port}', 'x', '',
                     'ts.net.attacker.example', 'attackerts.net', f'attacker.example:{port}@127.0.0.1'):
            self.assertEqual(self.ask('GET', host), 403, host)

    def test_a_forged_host_gets_no_head_no_stream_no_page_and_writes_no_answer(self):
        forged = 'attacker.example'
        self.assertEqual(self.ask('HEAD', forged), 403)
        self.assertEqual(self.ask('GET', forged, '/events?start=1'), 403)
        self.assertEqual(self.ask('GET', forged, '/Asked.html'), 403)
        self.assertEqual(self.ask('GET', forged, '/dashboard.css'), 403)
        self.assertEqual(self.post(forged), 403)
        self.assertFalse(self.answer.exists())

    def test_the_answer_still_goes_in_on_the_real_host(self):
        self.assertEqual(self.post(f'127.0.0.1:{self.server.port}'), 200)
        self.assertTrue(self.answer.exists())

    def test_no_host_or_two_hosts_are_refused(self):
        self.assertEqual(self.raw('GET / HTTP/1.0\r\n\r\n'), b'403')
        good = f'127.0.0.1:{self.server.port}'
        self.assertEqual(self.raw(f'GET / HTTP/1.1\r\nHost: {good}\r\nHost: attacker.example\r\n\r\n'), b'403')

    def test_tailscale_serve_hands_on_the_address_it_was_asked_for_and_gets_in(self):
        # as measured on tailscale 1.104.4: Host: <machine>.<tailnet>.ts.net, with :<port> on a port other than 443
        for host in ('machine.tailnet.ts.net', 'machine.tailnet.ts.net:8443'):
            self.assertEqual(self.ask('GET', host), 200, host)
        self.assertEqual(self.post('machine.tailnet.ts.net'), 200)
        self.assertTrue(self.answer.exists())


class SecondServerTest(unittest.TestCase):
    def test_a_port_with_a_dashboard_on_it_is_refused_with_a_message(self):
        repo = made_up_repo(self)
        first = Server(repo / 'first' / '.scratch')
        self.addCleanup(first.stop)
        run = subprocess.run([sys.executable, '-X', 'utf8', str(TOOLS / 'review_server.py'), '--port', str(first.port),
                              '--root', str(repo / 'second' / '.scratch')], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('is taken', run.stderr)


class AnswerIntoTicketTest(unittest.TestCase):
    """The answer written into a ticket in this process, where a test can step in while it is written."""
    TEXT = b'# 05 A\n\nStatus: in-review\nBlocked by: none\n\n## Question for the maintainer\n\nWhich?\n'
    REL = '.scratch/alpha/issues/05-a.md'

    def setUp(self):
        self.scratch = (made_up_repo(self) / '.scratch').resolve()
        effort_map(self.scratch, 'alpha')
        self.file = self.scratch / 'alpha' / 'issues' / '05-a.md'
        self.file.parent.mkdir()
        self.file.write_bytes(self.TEXT)
        for name, value in (('SCRATCH', self.scratch), ('ROOT', self.scratch / 'reviews'), ('who_answers', lambda: 'Sam')):
            patcher = mock.patch.object(review_server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(review_server.time, 'sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer(self):
        return review_server.answer_ticket(self.REL, 'Which?', 'Yes.')

    def left_behind(self):
        """Files beside the ticket and records of answers: what an answer that did not go in must not leave."""
        records = self.scratch / 'reviews' / 'ticket-answers'
        return (sorted(p.name for p in self.file.parent.iterdir() if p != self.file)
                + (sorted(p.name for p in records.iterdir()) if records.exists() else []))

    def test_an_edit_made_while_the_answer_is_written_in_stays_and_the_answer_is_refused(self):
        real = board.with_answer

        def edited_meanwhile(*args):
            self.file.write_bytes(self.TEXT + b'\n## Comments\n\n- an agent, meanwhile.\n')
            return real(*args)
        with mock.patch.object(board, 'with_answer', edited_meanwhile):
            code, reply = self.answer()
        self.assertEqual(code, 409)
        self.assertIn('send it again', reply['error'])
        self.assertTrue(self.file.read_bytes().endswith(b'- an agent, meanwhile.\n'))
        self.assertEqual(self.left_behind(), [])

    def test_a_ticket_held_open_is_tried_again_then_refused_and_stays_as_it_was(self):
        with mock.patch.object(Path, 'replace', side_effect=PermissionError('held')) as replace:
            code, reply = self.answer()
        self.assertEqual(code, 503)
        self.assertEqual(replace.call_count, review_server.REPLACE_TRIES)
        self.assertEqual(self.file.read_bytes(), self.TEXT)
        self.assertEqual(self.left_behind(), [])

    def test_an_open_grilling_names_its_session_when_herdr_runs_one(self):
        self.file.write_bytes(b'# 05 Talk\n\nType: grilling\nStatus: open\nBlocked by: none\n\n## Question\n\nWhich way?\n')
        with mock.patch.object(board, 'agents', return_value={'alpha05': 'working'}):
            _, html_text = review_server.doc_page(self.REL)
        self.assertIn('<p class="ticket-page you">This grilling waits for you in its session, alpha05: answer it there.</p>', html_text)

    def test_a_ticket_held_open_for_a_moment_takes_the_answer(self):
        real, calls = Path.replace, []

        def held_once(path, target):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError('held')
            return real(path, target)
        with mock.patch.object(Path, 'replace', held_once):
            code, _ = self.answer()
        self.assertEqual(code, 200)
        self.assertIn(b'answer on the dashboard: Yes.', self.file.read_bytes())
        self.assertEqual(self.left_behind(), ['alpha-05-a.json'])


class WhoAnswersTest(unittest.TestCase):
    def test_the_name_is_of_the_repo_of_the_scratch_with_a_parents_git_context_inherited(self):
        base = made_up_repo(self).resolve()
        for name in ('parent', 'clone'):
            (base / name).mkdir()
            for args in (['init', '-q'], ['config', 'user.name', 'Of the ' + name]):
                subprocess.run(['git', '-C', str(base / name), *args], check=True, capture_output=True)
        context = {'GIT_DIR': str(base / 'parent' / '.git'), 'GIT_WORK_TREE': str(base / 'parent')}
        with mock.patch.object(review_server, 'SCRATCH', base / 'clone' / '.scratch'), mock.patch.dict(os.environ, context):
            self.assertEqual(review_server.who_answers(), 'Of the clone')


if __name__ == '__main__':
    unittest.main()
