"""The TIA dashboard as a browser reaches it: made-up state files, logs and reports in a made-up projects root, a fake
process table, a real server on a free port."""
import datetime
import html
import http.client
import http.server
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from TiaAgentStatus import dashboard
from TiaAgentStatus import state as st
from TiaAgentStatus.tests.fakes import FakeProcesses, NOW, iso, state, tempdir, write
from tools.dashboard.tests import support


def log(root, repo, name, **result):
    """A tool log as Write-ToolLog leaves it: name is <yyyyMMdd_HHmmss>_<tool>[_n]."""
    folder = os.path.join(root, repo, 'logs')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name + '.json'), 'w', encoding='utf-8-sig') as f:
        json.dump(result, f)


def report(root, repo, name, body='<html>the report</html>', made=None):
    """A report page as change_report leaves it; made, a local datetime, sets the time the file was written."""
    folder = os.path.join(root, repo, 'changes', 'reports')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    if made:
        os.utime(path, (made.timestamp(), made.timestamp()))


def commit(root, repo, subject):
    """A commit in a real git repo; its short hash."""
    path = os.path.join(root, repo)
    os.makedirs(path, exist_ok=True)
    git = ['git', '-C', path, '-c', 'user.name=x', '-c', 'user.email=x@example.com', '-c', 'commit.gpgsign=false']
    subprocess.run([*git, 'init', '-q'], check=True)
    subprocess.run([*git, 'commit', '-q', '--allow-empty', '-m', subject], check=True)
    return subprocess.run([*git, 'rev-parse', '--short', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()


START = NOW - datetime.timedelta(minutes=30)     # when a bridge of a test started


def hm(t):
    """A time as the page shows it, in this machine's zone: hh:mm on NOW's day, else the date. NOW is 14:00 UTC, which is
    a few minutes past midnight east of UTC+10, where START is the day before."""
    t = t.astimezone()
    return t.strftime('%H:%M') if t.date() == NOW.astimezone().date() else t.strftime('%Y-%m-%d')


def plain(page):
    """The text a viewer reads."""
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', page)).split())


class Case(unittest.TestCase):
    def setUp(self):
        self.root = tempdir(self)
        self.previews = tempdir(self)
        patcher = mock.patch.dict(os.environ, {'HMIPREVIEW_RUNNING': self.previews})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.procs = FakeProcesses()
        self.now = NOW
        self.d = None

    def bridge(self, pid, **more):
        self.procs.add(pid)
        more.setdefault('project', None)
        s = state(pid, more.pop('claude', None), **more)
        write(st.sessions_dir(self.root), s)
        return s

    def held(self, **more):
        """A bridge on zz-line holding TIA 300."""
        self.procs.add(300, memory=3 * 2**30, cpu=10.0)
        more.setdefault('project', 'zzPlant')
        return self.bridge(200, repo=os.path.join(self.root, 'zz-line'), tia=300, **more)

    def running(self, minutes=1):
        return {'name': 'import', 'since': iso(NOW - datetime.timedelta(minutes=minutes))}

    def failed(self):
        return {'name': 'compile', 'ok': False, 'ended': iso(NOW), 'ms': 3}

    def tick(self):
        if self.d is None:
            self.d = dashboard.Dashboard(self.procs, dashboard.NoHerdr(), self.root, now=lambda: self.now)
        self.d.tick()

    def serve(self):
        self.tick()
        server = dashboard.make_server(self.d, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def get(self, path, method='GET'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status, r.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, ''

    def page(self):
        self.tick()
        return dashboard.page(self.d)

    def parts(self):
        self.tick()
        return self.d.latest['parts']

    def text(self, part):
        return plain(self.parts()[part])

    def row(self, name='zz-line'):
        """The project's row on the list."""
        return self.text(f'row-{name}')

    def headline(self):
        return self.parts()['summary']

    def chosen(self, name='zz-line'):
        """What choosing the project shows: the html of its four parts."""
        parts = self.parts()
        return ''.join(parts[f'{key}-{name}'] for key in ('now', 'tia', 'reports', 'history'))

    def project(self, name):
        """All the list and the pane say of a project."""
        parts = self.parts()
        self.assertIn(f'row-{name}', parts, f'{name} is not on the list')
        return parts[f'row-{name}'] + self.chosen(name)


class TheList(Case):
    def test_the_projects_worked_on_are_links_that_can_be_kept(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        log(self.root, 'zz-press', '20261030_130000_import', ok=True)
        rows = re.findall(r'<a class="row" id="row-([^"]+)" href="#([^"]+)"', self.parts()['list'])
        self.assertEqual(sorted(rows), [('zz-line', 'zz-line'), ('zz-press', 'zz-press')])

    def test_a_folder_nothing_was_done_in_is_not_listed(self):
        os.makedirs(os.path.join(self.root, 'zz-input', 'zzPlant'))
        os.makedirs(os.path.join(self.root, 'zz-empty', 'logs'))
        os.makedirs(os.path.join(self.root, '_bridge', 'logs'))
        log(self.root, '_bridge', '20261030_120000_list', ok=True)
        self.assertNotIn('class="row"', self.parts()['list'])

    def test_with_nothing_at_all_the_page_says_so(self):
        parts = self.parts()
        self.assertIn('Nothing needs you', plain(parts['summary']))
        self.assertIn('No project worked on yet', plain(parts['list']))
        self.assertIn(self.root, plain(parts['list']))
        self.assertEqual(parts['others'], '')

    def test_what_needs_you_comes_first_then_a_project_with_an_agent_then_the_newest(self):
        log(self.root, 'zz-a-old', '20261001_120000_compile', ok=True)
        log(self.root, 'zz-z-new', '20261030_120000_compile', ok=True)
        log(self.root, 'zz-held', '20260901_120000_compile', ok=True)
        log(self.root, 'zz-stuck', '20260801_120000_compile', ok=True)
        self.bridge(200, project='zzPlant', repo=os.path.join(self.root, 'zz-held'))
        self.bridge(201, project='zzPlant', repo=os.path.join(self.root, 'zz-stuck'), lastOperation=self.failed())
        self.assertEqual(re.findall(r'id="row-([^"]+)"', self.parts()['list']), ['zz-stuck', 'zz-held', 'zz-z-new', 'zz-a-old'])

    def test_a_project_an_agent_just_opened_shows_with_no_call_yet(self):
        self.bridge(200, project='zzPlant', repo=os.path.join(self.root, 'zz-fresh'))
        self.assertIn('zz-fresh', self.row('zz-fresh'))

    def test_a_repo_outside_the_projects_root_still_shows(self):
        other = tempdir(self)
        self.bridge(200, project='zzPlant', repo=os.path.join(other, 'zz-elsewhere'))
        self.assertIn('zz-elsewhere', self.row('zz-elsewhere'))

    def test_names_are_escaped_and_the_link_is_quoted(self):
        log(self.root, "zz&line'", '20261030_120000_compile', ok=True)
        parts = self.parts()
        self.assertIn('href="#zz%26line%27"', parts['list'])
        self.assertIn('zz&amp;line&#x27;', parts["row-zz&line'"])
        self.assertNotIn('zz&line', parts["row-zz&line'"])

    def test_a_row_holds_the_name_the_state_and_when_its_last_call_was_and_nothing_else(self):
        log(self.root, 'zz-line', '20261001_120000_compile', ok=True)
        report(self.root, 'zz-line', '2026-10-30_abc1234.html')
        self.assertEqual(self.row(), 'zz-line 2026-10-01 ○ No bridge connected')

    def test_a_call_of_today_shows_its_time(self):
        today = NOW.astimezone().strftime('%Y%m%d')
        log(self.root, 'zz-line', f'{today}_081500_compile', ok=True)
        self.assertEqual(self.row(), 'zz-line 08:15 ○ No bridge connected')

    def test_an_idle_bridge_is_on_the_row_with_no_second_time(self):
        # the row's last call already says when: "08:15 ○ Bridge idle since 08:15" said it twice
        at = NOW.astimezone().replace(hour=8, minute=15, second=0)
        log(self.root, 'zz-line', at.strftime('%Y%m%d_%H%M%S_') + 'export', ok=True)
        self.held(lastOperation={'name': 'export', 'ok': True, 'ended': iso(at + datetime.timedelta(seconds=40)), 'ms': 40000})
        self.assertEqual(self.row(), 'zz-line 08:15 ○ Bridge idle')

    def test_two_idle_bridges_are_one_idle_row_with_no_time_of_either(self):
        repo = os.path.join(self.root, 'zz-line')
        for pid, minutes in ((200, 50), (201, 5)):
            self.bridge(pid, project='zzPlant', repo=repo, started=NOW - datetime.timedelta(hours=1),
                        lastOperation={'name': 'save', 'ok': True, 'ended': iso(NOW - datetime.timedelta(minutes=minutes)), 'ms': 3})
        self.assertEqual(self.row(), 'zz-line ○ Bridge idle (2 bridges)')

    def test_a_call_that_runs_is_on_the_row_with_its_time(self):
        self.held(operation={'name': 'export', 'part': 'blocks', 'n': 31, 'of': 115,
                             'since': iso(NOW - datetime.timedelta(minutes=2, seconds=10))})
        self.assertIn('▸ export blocks 31/115 2:10', self.row())

    def test_a_row_says_how_many_bridges_when_there_are_two(self):
        self.held()
        self.assertNotIn('bridges', self.row())
        self.bridge(201, project='zzPlant', repo=os.path.join(self.root, 'zz-line'))
        self.assertIn('(2 bridges)', self.row())

    def test_a_failed_last_call_with_no_agent_on_it_is_said_but_needs_nothing(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        log(self.root, 'zz-line', '20261030_130000_save', ok=False, refused='Save refused.')
        self.assertIn('! Last call failed: save', self.row())
        self.assertIn('Nothing needs you', plain(self.headline()))
        self.assertNotIn('class="state fail"', self.parts()['row-zz-line'])

    def test_a_failure_a_later_call_mended_is_not_on_the_row(self):
        log(self.root, 'zz-line', '20261030_120000_save', ok=False, refused='Save refused.')
        log(self.root, 'zz-line', '20261030_130000_save', ok=True)
        self.assertNotIn('failed', self.row())


class NeedsYou(Case):
    """Every need and what to do about it stand in the headline, above the list and the pane, whatever is chosen."""

    def need(self):
        return plain(self.headline())

    def test_nothing_needs_you_when_all_is_well(self):
        self.held(operation=self.running(), lastOperation={'name': 'list', 'ok': True, 'ended': iso(NOW)})
        self.assertIn('Nothing needs you', self.need())
        self.assertEqual(self.d.latest['title'], dashboard.TITLE)

    def test_tia_asks_something_during_a_call_is_amber_and_says_to_answer_it(self):
        self.held(operation=self.running(), lastPrompt={'at': iso(NOW), 'kind': 'message', 'caption': 'Import',
                                                        'text': 'Overwrite the block?'})
        self.assertIn('summary you', self.headline())
        text = self.need()
        self.assertIn('1 needs you', text)
        self.assertIn('zz-line ● TIA asks: Import: Overwrite the block? Answer it in TIA.', text)
        self.assertEqual(self.d.latest['title'], f'(1) {dashboard.TITLE}')
        self.assertIn('● TIA asks a question', self.row())

    def test_a_prompt_from_before_the_call_asks_nothing(self):
        self.held(operation=self.running(), lastPrompt={'at': iso(NOW - datetime.timedelta(hours=1)), 'kind': 'message',
                                                        'caption': 'Import', 'text': 'Overwrite?'})
        self.assertIn('Nothing needs you', self.need())

    def test_no_cpu_during_a_call_is_amber_after_the_quiet_minutes(self):
        self.held(operation=self.running())
        self.tick()
        self.now = NOW + datetime.timedelta(minutes=4)
        self.assertIn('Nothing needs you', self.need())
        self.now = NOW + datetime.timedelta(minutes=6)
        self.assertIn('summary you', self.headline())
        self.assertIn('TIA does nothing during import. Look in TIA for an open message box.', self.need())
        self.assertIn('● TIA has stopped working', self.row())

    def test_no_cpu_on_a_tia_with_no_window_names_the_process_to_end(self):
        self.held(window=False, operation=self.running())
        self.tick()
        self.now = NOW + datetime.timedelta(minutes=6)
        self.assertIn('It may hang: ask the agent, or end process 300 in Task Manager.', self.need())

    def test_a_tia_that_works_needs_nothing(self):
        self.held(operation=self.running())
        self.tick()
        self.procs.procs[300]['cpu'] += 60.0
        self.now = NOW + datetime.timedelta(minutes=6)
        self.assertIn('Nothing needs you', self.need())

    def left_tia(self, window, repo='zz-line', project='zzPlant'):
        self.procs.add(300, name='Siemens.Automation.Portal.exe', memory=2 * 2**30)
        path = os.path.join(self.root, repo) if repo else None
        write(st.sessions_dir(self.root), state(200, None, project=project, tia=300, window=window, repo=path))
        if repo:
            log(self.root, repo, '20261030_120000_compile', ok=True)

    def test_a_left_tia_without_a_window_is_amber_and_says_how_to_close_it(self):
        self.left_tia(window=False)
        self.assertIn('summary you', self.headline())
        self.assertIn('zz-line ● A TIA without a window was left running, holding 2.0 GB. Close it: end process 300 in Task Manager.',
                      self.need())
        self.assertEqual(self.d.latest['title'], f'(1) {dashboard.TITLE}')
        self.assertIn('● A TIA was left running', self.row())

    def test_a_left_tia_with_no_repo_needs_you_too(self):
        self.left_tia(window=False, repo=None, project=None)
        self.assertIn('A bridge with no project ● A TIA without a window was left running', self.need())

    def test_a_left_tia_with_a_window_is_one_of_the_tias_no_bridge_holds_and_needs_nothing(self):
        self.left_tia(window=True)
        text = self.need()
        self.assertIn('Nothing needs you', text)
        self.assertEqual(self.d.latest['title'], dashboard.TITLE)
        others = self.text('others')
        self.assertIn('TIA with no bridge', others)
        self.assertIn('Process 300, 2.0 GB memory', others)
        self.assertNotIn('close it', self.need())

    def test_a_left_tia_with_a_window_is_nothing_on_its_project(self):
        self.left_tia(window=True)
        self.assertIn('○ No bridge connected', self.row())
        self.assertIn('No bridge on this project', plain(self.chosen()))

    def test_the_last_call_failed_is_red_says_why_and_clears_with_the_next_good_one(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=False, items=[{'name': 'PLC_1', 'errors': 2, 'warnings': 0}])
        self.held(lastOperation=self.failed())
        self.assertIn('summary fail', self.headline())
        self.assertIn('zz-line ! compile failed: PLC_1: 2 errors, 0 warnings. Ask the agent what it will do about it.', self.need())
        self.assertIn('! compile failed', self.row())
        self.held(lastOperation={'name': 'compile', 'ok': True, 'ended': iso(NOW), 'ms': 3})
        self.assertIn('Nothing needs you', self.need())

    def test_a_reason_that_ends_its_own_sentence_is_not_given_a_second_stop(self):
        log(self.root, 'zz-line', '20261030_120000_save', ok=False, refused='Save refused.')
        self.held(lastOperation={'name': 'save', 'ok': False, 'ended': iso(NOW), 'ms': 3})
        self.assertIn('save failed: Save refused. Ask the agent', self.need())

    def test_a_failed_call_followed_by_a_running_one_waits_for_that_one(self):
        self.held(operation=self.running(), lastOperation=self.failed())
        self.assertIn('Nothing needs you', self.need())

    def test_a_tia_gone_counts_and_names_the_call_it_went_in(self):
        self.held(operation=self.running(2))
        self.procs.kill(300)
        self.assertIn('summary fail', self.headline())
        self.assertIn('zz-line ! TIA closed or crashed during import. Ask the agent to connect again.', self.need())
        self.assertEqual(self.d.latest['title'], f'(1) {dashboard.TITLE}')
        self.assertIn('! TIA closed', self.row())

    def test_a_tia_gone_with_no_call_says_only_that(self):
        self.held()
        self.procs.kill(300)
        self.assertIn('zz-line ! TIA closed or crashed. Ask the agent to connect again.', self.need())

    def test_amber_wins_the_headline_and_every_need_is_counted(self):
        self.held(lastOperation=self.failed())
        self.bridge(201, operation=self.running(), lastPrompt={'at': iso(NOW), 'kind': 'message', 'caption': 'Q'})
        self.assertIn('summary you', self.headline())
        text = self.need()
        self.assertIn('2 need you', text)
        self.assertIn('A bridge with no project ● TIA asks: Q', text)
        self.assertIn('zz-line ! compile failed', text)

    def test_two_agents_on_a_project_each_show_their_need(self):
        repo = os.path.join(self.root, 'zz-line')
        self.bridge(200, project='zzPlant', repo=repo, lastOperation=self.failed())
        self.bridge(201, project='zzPlant', repo=repo, operation=self.running(), lastPrompt={'at': iso(NOW), 'kind': 'message', 'caption': 'Q'})
        text = self.need()
        self.assertIn('2 need you', text)
        self.assertIn('zz-line ! compile failed', text)
        self.assertIn('zz-line ● TIA asks: Q', text)

    def test_a_need_links_to_its_project(self):
        self.held(lastOperation=self.failed())
        self.assertIn('<a href="#zz-line">zz-line</a>', self.headline())

    def test_a_need_of_a_bridge_with_no_project_links_to_that_section(self):
        self.bridge(201, lastOperation=self.failed())
        self.assertIn('<a href="#bridges">A bridge with no project</a>', self.headline())
        self.assertIn('id="bridges"', self.parts()['others'])

    def test_the_headline_stands_above_the_list_and_the_pane(self):
        page = self.page()
        self.assertLess(page.index('id="summary"'), page.index('id="list"'))
        self.assertLess(page.index('id="summary"'), page.index('id="pane"'))

    def test_a_need_is_not_said_twice(self):
        self.held(operation=self.running(), lastPrompt={'at': iso(NOW), 'kind': 'message', 'caption': 'Import',
                                                        'text': 'Overwrite the block?'})
        self.assertNotIn('Overwrite the block?', self.project('zz-line'))
        self.assertEqual(plain(self.headline()).count('Overwrite the block?'), 1)

    def test_text_from_a_prompt_or_a_log_is_escaped_in_a_need(self):
        log(self.root, 'zz-line', '20261030_120000_save', ok=False, refused='<img src=x>')
        self.held(lastOperation={'name': 'save', 'ok': False, 'ended': iso(NOW), 'ms': 3})
        self.assertNotIn('<img', self.headline())
        self.assertIn('&lt;img src=x&gt;', self.headline())
        self.held(operation=self.running(), lastPrompt={'at': iso(NOW), 'kind': 'message', 'caption': '<img src=y>'})
        self.assertNotIn('<img', self.headline())
        self.assertIn('&lt;img src=y&gt;', self.headline())

    def test_a_round_that_fails_says_so_on_the_page(self):
        self.held()
        self.tick()

        def broken(pid):
            raise RuntimeError('no process table')
        self.procs.info = broken
        self.assertIn('no process table', self.need())


class WhatTheBridgeWrites(Case):
    """lastPrompt.answer as TiaBridge's prompt guard writes it (Tools\\Background.ps1): a box it closed needs nobody, a box it
    left open waits for someone."""
    CLOSED = ('Cancel', 'Abort', 'No', 'NoToAll', 'Ok', 'handled')
    WAITING = ('left to the person at TIA', '(none of Cancel, Abort, No, NoToAll, Ok offered: left to TIA)',
               '(not answered: Boom)', '(not handled: Boom)')

    def box(self, answer, window=True, kind='notification'):
        p = {'at': iso(NOW), 'kind': kind, 'caption': 'Export', 'text': 'Export Completed'}
        if answer is not None:
            p['answer'] = answer
        self.held(window=window, project='zz-line', operation=self.running(), lastPrompt=p)

    def test_every_answer_the_guard_can_write_is_one_this_page_knows(self):
        source = os.path.join(os.path.dirname(os.path.dirname(dashboard.__file__)), 'TiaBridge', 'Tools', 'Background.ps1')
        with open(source, encoding='utf-8') as f:
            guard = f.read()
        offered = re.search(r'string\[\] Answers = \{([^}]+)\}', guard).group(1)
        written = set(re.findall(r'"([^"]+)"', offered)) | {w for w in re.findall(r'answer = "([^"]*)"', guard) if w}
        self.assertEqual(written, set(self.CLOSED) | {'left to the person at TIA', '(none of Cancel, Abort, No, NoToAll, Ok offered: left to TIA)',
                                                      '(not answered: ', '(not handled: '})

    def test_a_box_the_bridge_closed_needs_nobody_and_the_call_shows_on(self):
        for answer in self.CLOSED:
            self.box(answer)
            self.assertIn('Nothing needs you', plain(self.headline()), answer)
            self.assertIn('▸ import 1:00', self.row(), answer)
            self.assertIn(f'Export: Export Completed -> {answer}', self.text('tia-zz-line'), answer)

    def test_a_box_left_open_on_a_tia_with_a_window_says_to_answer_it_there(self):
        for answer in self.WAITING:
            self.box(answer)
            self.assertIn('summary you', self.headline(), answer)
            self.assertIn('zz-line ● TIA asks: Export: Export Completed Answer it in TIA.', plain(self.headline()), answer)
            self.assertIn('● TIA asks a question', self.row(), answer)
            self.assertNotIn(answer, plain(self.headline()), 'the bridge\'s words are not the person\'s')
            self.assertNotIn('Export Completed', self.text('tia-zz-line'), 'said once')

    def test_a_box_left_open_on_a_tia_with_no_window_says_no_one_can_answer_it(self):
        for answer in self.WAITING:
            self.box(answer, window=False)
            self.assertIn('summary you', self.headline(), answer)
            self.assertIn('TIA asks: Export: Export Completed No one can answer it: this TIA has no window. It may hang: ask the agent, '
                          'or end process 300 in Task Manager.', plain(self.headline()), answer)

    def test_a_box_with_no_answer_written_counts_as_waiting(self):
        self.box(None)
        self.assertIn('Answer it in TIA.', plain(self.headline()))


class TheChosenProject(Case):
    def pane(self):
        self.tick()
        return self.d.latest['parts']['pane']

    def now_part(self):
        return self.text('now-zz-line')

    def tia_part(self):
        return self.text('tia-zz-line')

    def test_it_has_named_parts_and_is_shown_by_the_page_s_script(self):
        """Four, and the HMI preview while one runs: an optional part, its heading in its slot (class HmiPreview)."""
        self.held()
        m = re.search(r'<section [^>]*id="project-zz-line"[^>]*hidden.*?</section>\s*</section>', self.pane(), re.S)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r'<h3>([^<]+)</h3>', self.pane()), ['Agent is calling', 'TIA', 'Change reports', 'History'])
        self.assertEqual(re.findall(r'<section class="part optional" id="([^"]+)"></section>', self.pane()), ['preview-zz-line'])

    def test_nothing_is_chosen_at_first_and_the_pane_says_what_choosing_does(self):
        self.held()
        self.assertIn('Choose a project', plain(self.pane()))

    def test_history_and_reports_scroll_in_their_own_areas_and_keep_their_place(self):
        self.held()
        for key in ('history', 'reports'):
            self.assertRegex(self.pane(), rf'<div id="{key}-zz-line" class="[^"]*scroll[^"]*" data-scroll tabindex="0" role="region"')

    def test_all_projects_goes_back(self):
        self.held()
        self.assertIn('<a class="back" href="#">All projects</a>', self.pane())

    def test_the_call_that_runs_shows_with_its_time(self):
        self.held(operation={'name': 'export', 'part': 'blocks', 'n': 31, 'of': 115,
                             'since': iso(NOW - datetime.timedelta(minutes=2, seconds=10))})
        self.assertEqual(self.now_part(), 'export blocks 31/115 2:10')

    def test_an_agent_with_no_call_yet_calls_nothing_since_its_bridge_started(self):
        self.held(started=START)
        self.assertEqual(self.now_part(), f'Calling nothing since {hm(START)}')

    def test_an_agent_calls_nothing_since_its_last_call_ended(self):
        ended = NOW - datetime.timedelta(minutes=7)
        self.held(started=START, lastOperation={'name': 'export', 'ok': True, 'ended': iso(ended), 'ms': 3})
        self.assertEqual(self.now_part(), f'Calling nothing since {hm(ended)}')

    def test_a_call_of_another_day_says_the_date(self):
        ended = NOW - datetime.timedelta(days=2)
        self.held(started=START, lastOperation={'name': 'export', 'ok': True, 'ended': iso(ended), 'ms': 3})
        self.assertEqual(self.now_part(), f'Calling nothing since {ended.astimezone().strftime("%Y-%m-%d")}')

    def test_an_agent_whose_last_call_failed_calls_nothing_since_it_ended(self):
        ended = NOW - datetime.timedelta(minutes=7)
        self.held(started=START, lastOperation=dict(self.failed(), ended=iso(ended)))
        self.assertEqual(self.now_part(), f'Calling nothing since {hm(ended)}')

    def test_an_agent_whose_tia_closed_says_no_since(self):
        self.held(started=START)
        self.procs.kill(300)
        self.assertEqual(self.now_part(), 'Calling nothing right now')

    def test_with_no_time_to_read_it_calls_nothing_right_now(self):
        s = self.held()
        write(st.sessions_dir(self.root), dict(s, started='later'))
        self.assertEqual(self.now_part(), 'Calling nothing right now')

    def test_no_bridge_says_so(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.assertEqual(self.now_part(), 'No bridge on this project.')
        self.assertEqual(self.tia_part(), 'No bridge holds a TIA for it.')

    def test_an_agent_that_ended_and_left_a_tia_is_not_calling_anything(self):
        self.procs.add(300, name='Siemens.Automation.Portal.exe', memory=2**30)
        write(st.sessions_dir(self.root), state(200, None, project='zz-line', tia=300, window=False,
                                                repo=os.path.join(self.root, 'zz-line')))
        self.assertEqual(self.now_part(), 'The agent has ended.')
        self.assertEqual(self.tia_part(), 'Without a window 1.0 GB memory')

    def test_a_tia_says_window_memory_and_cpu(self):
        self.held(window=False, project='zz-line')
        self.tick()
        self.procs.procs[300]['cpu'] += 30.0
        self.now = NOW + datetime.timedelta(seconds=30)
        self.assertEqual(self.tia_part(), 'Without a window 3.0 GB memory, 100% CPU')

    def test_a_tia_with_a_window_says_so(self):
        self.held()
        self.assertIn('With a window', self.tia_part())

    def test_an_agent_with_no_tia_says_so(self):
        self.bridge(200, project='zzPlant', repo=os.path.join(self.root, 'zz-line'))
        self.assertEqual(self.tia_part(), 'Holds no TIA. Project in TIA: zzPlant')

    def test_a_tia_that_went_says_so(self):
        self.held()
        self.procs.kill(300)
        self.assertIn('TIA has closed.', self.tia_part())

    def test_the_tia_project_shows_only_when_it_differs_from_the_folder(self):
        self.held(project='zzPlant')
        self.assertIn('Project in TIA: zzPlant', self.tia_part())
        self.held(project='ZZ-Line')
        self.assertNotIn('Project in TIA', self.tia_part())

    def test_the_last_prompt_stays_after_its_call(self):
        self.held(lastPrompt={'at': iso(NOW - datetime.timedelta(minutes=9)), 'kind': 'message', 'caption': 'Import',
                              'text': 'Overwrite the block?', 'answer': 'No'})
        self.assertIn('It last asked:', self.tia_part())
        self.assertIn('Import: Overwrite the block? -> No', self.tia_part())

    def test_the_last_prompt_is_escaped(self):
        self.held(lastPrompt={'at': iso(NOW - datetime.timedelta(minutes=9)), 'kind': 'message', 'caption': '<img src=x>', 'answer': 'No'})
        self.assertNotIn('<img', self.parts()['tia-zz-line'])
        self.assertIn('&lt;img src=x&gt;', self.parts()['tia-zz-line'])

    def test_two_agents_have_a_line_each(self):
        self.procs.add(300, memory=3 * 2**30).add(301, memory=2**30)
        repo = os.path.join(self.root, 'zz-line')
        self.bridge(200, project='zz-line', repo=repo, tia=300, window=False, started=NOW - datetime.timedelta(minutes=50),
                    operation={'name': 'export', 'since': iso(NOW - datetime.timedelta(minutes=2))})
        self.bridge(201, project='zz-line', repo=repo, tia=301, started=NOW - datetime.timedelta(minutes=40))
        self.assertEqual(self.now_part(), f'Agent 1: export 2:00 Agent 2: calling nothing since {hm(NOW - datetime.timedelta(minutes=40))}')
        self.assertEqual(self.tia_part(), 'Agent 1: without a window 3.0 GB memory Agent 2: with a window 1.0 GB memory')

    def test_without_herdr_only_an_agent_that_is_gone_is_worth_saying(self):
        self.procs.add(100)
        self.held(claude=100)
        self.assertNotIn('gent', self.now_part().replace('Agent is calling', ''))
        self.procs.kill(100)
        self.assertIn('The agent is gone.', self.now_part())

    def tabs(self, status):
        class Tabs(dashboard.ReadOnlyHerdr):
            def __init__(self):
                super().__init__('no-such-herdr')
                self.calls = []

            def _run(self, *args):
                self.calls.append(args)
                if args[:2] == ('tab', 'list'):
                    return {'tabs': [{'tab_id': 't1', 'label': 'someone', 'agent_status': status}]}
                raise AssertionError(f'herdr {args}')
        return Tabs()

    def test_an_agent_that_waits_for_an_answer_says_so_and_nothing_is_renamed_or_notified(self):
        herdr = self.tabs('blocked')
        self.d = dashboard.Dashboard(self.procs, herdr, self.root, now=lambda: self.now)
        self.held(herdr={'tab': 't1', 'pane': 'p1'})
        self.tick()     # the watcher would rename the tab here: its _run raises on anything but tab list
        self.assertIn('The agent waits for an answer.', self.now_part())
        self.assertNotIn('someone', plain(self.project('zz-line')))
        self.assertEqual({a[:2] for a in herdr.calls}, {('tab', 'list')})

    def test_a_tia_without_a_window_starting_notifies_nothing(self):
        herdr = self.tabs('working')
        self.d = dashboard.Dashboard(self.procs, herdr, self.root, now=lambda: self.now)
        self.tick()     # the watcher notifies a TIA with no window that comes after its first round
        self.held(window=False, herdr={'tab': 't1', 'pane': 'p1'})
        self.tick()
        self.assertTrue(self.d.watcher.notes, 'the watcher had something to notify')
        self.assertEqual({a[:2] for a in herdr.calls}, {('tab', 'list')})

    def test_an_agent_that_works_or_is_done_is_not_worth_saying(self):
        for status in ('working', 'done', 'idle'):
            self.d = dashboard.Dashboard(self.procs, self.tabs(status), self.root, now=lambda: self.now)
            self.held(started=START, herdr={'tab': 't1', 'pane': 'p1'})
            self.assertEqual(self.now_part(), f'Calling nothing since {hm(START)}', status)

    def test_herdr_that_fails_is_as_no_herdr(self):
        class Down(dashboard.ReadOnlyHerdr):
            def _run(self, *args):
                raise RuntimeError('herdr is not running')

        self.procs.add(100)
        self.d = dashboard.Dashboard(self.procs, Down(), self.root, now=lambda: self.now)
        self.held(claude=100, started=START)
        self.assertEqual(self.now_part(), f'Calling nothing since {hm(START)}')
        self.procs.kill(100)
        self.assertIn('The agent is gone.', self.now_part())

    def test_no_bridge_or_process_word_where_none_is_needed(self):
        self.held(operation=self.running())
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        text = plain(self.project('zz-line')).lower()
        self.assertNotIn('bridge', text)
        self.assertNotIn('process', text)
        self.assertNotIn('200', text)


class OtherBridges(Case):
    """Bridges with no project have their own section, each its own line; so do the TIAs no bridge holds."""

    def others(self):
        return self.text('others')

    def test_every_bridge_with_no_project_has_its_own_line(self):
        for pid in (201, 202, 203):
            self.bridge(pid, started=START)
        self.assertEqual(self.parts()['others'].count('class="other"'), 3)
        idle = f'○ Bridge idle since {hm(START)} Holds no TIA.'
        self.assertEqual(self.others(), f'Bridges with no project {idle} {idle} {idle}')

    def test_a_call_with_no_project_shows_with_its_time_outside_the_list(self):
        self.bridge(201, operation={'name': 'background_open', 'step': 'start', 'since': iso(NOW - datetime.timedelta(seconds=5))})
        self.assertNotIn('class="row"', self.parts()['list'])
        self.assertIn('▸ background_open start 0:05', self.others())

    def test_its_tia_is_said_in_the_same_words(self):
        self.procs.add(300, memory=2**30)
        self.bridge(201, tia=300, window=False)
        self.assertIn('Without a window 1.0 GB memory', self.others())

    def test_a_tia_project_with_no_repo_yet_is_named(self):
        self.bridge(201, project='zzPlant')
        self.assertIn('Project in TIA: zzPlant', self.others())

    def test_an_agent_that_is_gone_is_said(self):
        self.procs.add(100)
        self.bridge(201, claude=100)
        self.procs.kill(100)
        self.assertIn('The agent is gone.', self.others())

    def test_no_number_for_an_agent(self):
        self.bridge(201)
        self.assertNotIn('201', self.others())

    def test_a_tia_no_agent_holds_is_listed_and_needs_nothing(self):
        self.procs.add(400, name='Siemens.Automation.Portal.exe', memory=2**30)
        self.procs.add(401, name='other.exe', memory=2**30)
        self.held()
        self.procs.procs[300]['name'] = 'Siemens.Automation.Portal.exe'
        others = self.others()
        self.assertIn('TIA with no bridge', others)
        self.assertIn('Process 400, 1.0 GB memory', others)
        self.assertNotIn('Process 401', others)
        self.assertNotIn('Process 300', others)
        self.assertIn('Nothing needs you', plain(self.headline()))

    def test_a_tia_no_agent_holds_may_hold_work_not_saved_so_nothing_tells_to_close_it(self):
        self.procs.add(400, name='Siemens.Automation.Portal.exe', memory=2**30)
        self.assertNotIn('close', self.others().lower())
        self.assertIn('Yours, or left by an agent that ended.', self.others())

    def test_with_none_the_section_is_not_there(self):
        # "No agent is running" under it read as the whole machine, while an agent worked on a project
        self.held()
        self.assertEqual(self.parts()['others'], '')


class History(Case):
    def test_every_call_has_its_own_line_newest_first_with_time_and_duration(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True, durationMs=1500, items=[])
        log(self.root, 'zz-line', '20261030_120001_compile_2', ok=True, durationMs=250, items=[])
        log(self.root, 'zz-line', '20261030_120105_import', ok=True, durationMs=65000,
            items=[{'name': 'zzPump', 'ok': True}, {'name': 'zzValve', 'ok': True}])
        text = plain(self.project('zz-line'))
        self.assertEqual(re.findall(r'12:\d\d:\d\d', text), ['12:01:05', '12:00:01', '12:00:00'])
        self.assertIn('2026-10-30', text)
        self.assertIn('import zzPump, zzValve', text)
        self.assertIn('1:05', text)
        self.assertIn('1.5 s', text)

    def test_many_objects_are_counted_not_listed(self):
        log(self.root, 'zz-line', '20261030_120000_import', ok=True,
            items=[{'name': f'zz{i}', 'ok': True} for i in range(5)])
        self.assertIn('zz0, zz1, zz2 +2', plain(self.project('zz-line')))

    def test_a_failed_call_says_why(self):
        log(self.root, 'zz-line', '20261030_120000_save', ok=False, refused='Save refused.')
        log(self.root, 'zz-line', '20261030_120001_import', ok=False,
            items=[{'name': 'zzPump', 'ok': False, 'error': {'message': 'Bad block'}}, {'name': 'zzValve', 'ok': True}])
        log(self.root, 'zz-line', '20261030_120002_list', ok=False, error={'type': 'X', 'message': 'Not connected'})
        part = self.project('zz-line')
        text = plain(part)
        self.assertIn('Save refused.', text)
        self.assertIn('zzPump', text)
        self.assertIn('1 of 2 failed', text)
        self.assertIn('Bad block', text)
        self.assertIn('Not connected', text)
        self.assertEqual(part.count('class="call fail'), 3)

    def test_a_compile_gives_its_errors_and_warnings(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True, failedTotal=4,
            items=[{'name': 'PLC_1', 'ok': True, 'errors': 2, 'warnings': 1}])
        self.assertIn('PLC_1: 2 errors, 1 warnings, 4 not consistent', plain(self.project('zz-line')))

    def test_a_full_export_gives_its_counts(self):
        log(self.root, 'zz-line', '20261030_120000_full_export', ok=False, exported=40, failedCount=2)
        self.assertIn('40 exported, 2 failed', plain(self.project('zz-line')))

    def test_a_save_gives_its_reason_and_a_closed_session_its_length(self):
        log(self.root, 'zz-line', '20261030_120000_archive', ok=True, reason='before the pump change')
        log(self.root, 'zz-line', '20261030_120001_background_steps', totalMs=125000, tiaPeakWorkingSetMB=2048)
        text = plain(self.project('zz-line'))
        self.assertIn('before the pump change', text)
        self.assertIn('session closed after 2:05, TIA peak 2.0 GB', text)

    def test_a_log_not_readable_shows_and_is_read_again(self):
        folder = os.path.join(self.root, 'zz-line', 'logs')
        os.makedirs(folder)
        path = os.path.join(folder, '20261030_120000_import.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{"ok": tr')
        self.assertIn('log not readable', plain(self.project('zz-line')))
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'items': [{'name': 'zzPump', 'ok': True}]}, f)
        text = plain(self.project('zz-line'))
        self.assertNotIn('log not readable', text)
        self.assertIn('zzPump', text)

    def test_a_name_that_only_looks_like_a_time_is_no_call_and_takes_nothing_down(self):
        log(self.root, 'zz-line', '20261030_120000_import', ok=True)
        log(self.root, 'zz-line', '20260230_100000_save', ok=True)
        log(self.root, 'zz-line', '20261030_290000_save', ok=True)
        log(self.root, 'zz-line', '20260230_100000_change_report', ok=True, page='changes\\reports\\a.html')
        text = plain(self.project('zz-line'))
        self.assertIn('import', text)
        self.assertNotIn('save', text)
        self.assertNotIn('could not be read', plain(self.headline()))
        self.assertNotIn('Newest', text)

    def test_other_files_in_logs_are_no_calls(self):
        log(self.root, 'zz-line', '20261030_120000_import', ok=True)
        folder = os.path.join(self.root, 'zz-line', 'logs')
        with open(os.path.join(folder, 'library.log'), 'w', encoding='utf-8') as f:
            f.write('x')
        log(self.root, 'zz-line', '20261399_120000_import', ok=True)
        self.assertEqual(plain(self.project('zz-line')).count('import'), 1)

    def test_only_the_newest_calls_show_and_the_page_says_how_many_there_are(self):
        for i in range(dashboard.CALLS_SHOWN + 3):
            log(self.root, 'zz-line', f'20261030_{10 + i // 60:02}{i % 60:02}00_list', ok=True)
        part = self.project('zz-line')
        self.assertEqual(part.count('class="call'), dashboard.CALLS_SHOWN)
        text = plain(part)
        self.assertIn(f'Newest {dashboard.CALLS_SHOWN} of {dashboard.CALLS_SHOWN + 3} calls', text)
        self.assertIn(os.path.join(self.root, 'zz-line', 'logs'), text)

    def test_text_from_a_log_is_escaped(self):
        log(self.root, 'zz-line', '20261030_120000_import', ok=False, refused='<script>alert(1)</script>')
        self.assertNotIn('<script>alert', self.project('zz-line'))

    def test_no_agent_is_named(self):
        self.procs.add(100)
        self.bridge(200, claude=100, project='zzPlant', repo=os.path.join(self.root, 'zz-line'),
                    session='a-session', herdr={'tab': 't1', 'pane': 'p1'})
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        text = plain(self.project('zz-line'))
        for private in ('a-session', 't1', 'Claude 100'):
            self.assertNotIn(private, text)


class ChangeReports(Case):
    def test_the_commit_subject_is_the_link_with_what_was_compared_size_and_date(self):
        h = commit(self.root, 'zz-line', 'Pump: longer start delay')
        name = f'2026-10-30_{h}.html'
        report(self.root, 'zz-line', name, 'x' * 3000)
        log(self.root, 'zz-line', '20261030_120000_change_report', ok=True, page=f'changes\\reports\\{name}',
            before='zz-line @ HEAD~1 (93a42fa)', after=f'zz-line @ HEAD ({h})')
        part = self.project('zz-line')
        self.assertRegex(part, rf'<a href="/report/zz-line/{name}" target="_blank" rel="noopener">Pump: longer start delay</a>')
        text = plain(part)
        self.assertIn(f'93a42fa to {h}', text)
        self.assertIn('3 KB', text)

    def test_a_report_shows_the_date_and_time_it_was_made_to_the_minute(self):
        report(self.root, 'zz-line', '2026-10-30_abc1234.html', made=datetime.datetime(2026, 11, 6, 14, 32, 59))
        self.assertIn('2026-11-06 14:32', self.text('reports-zz-line'))
        self.assertNotIn('2026-10-30', self.text('reports-zz-line'))

    def test_reports_of_one_day_are_newest_made_first_whatever_their_commit_date(self):
        report(self.root, 'zz-line', '2026-11-06_aaa1111.html', made=datetime.datetime(2026, 11, 6, 9, 5))
        report(self.root, 'zz-line', '2026-11-01_bbb2222.html', made=datetime.datetime(2026, 11, 6, 14, 32))
        report(self.root, 'zz-line', '2026-11-05_ccc3333.html', made=datetime.datetime(2026, 11, 6, 11, 0))
        text = self.text('reports-zz-line')
        self.assertLess(text.index('2026-11-06 14:32'), text.index('bbb2222'))
        self.assertLess(text.index('bbb2222'), text.index('2026-11-06 11:00'))
        self.assertLess(text.index('ccc3333'), text.index('2026-11-06 09:05'))
        self.assertLess(text.index('2026-11-06 09:05'), text.index('aaa1111'))

    def test_a_report_whose_time_does_not_read_still_shows_its_date(self):
        report(self.root, 'zz-line', '2026-11-06_aaa1111.html', made=datetime.datetime(2026, 11, 6, 9, 5))
        files = dashboard.report_files(os.path.join(self.root, 'zz-line'))
        gone = os.path.join(self.root, 'zz-line', 'changes', 'reports', '2026-11-04_bbb2222.html')
        files['2026-11-04_bbb2222.html'] = dashboard.Path(gone)
        with mock.patch.object(dashboard, 'report_files', return_value=files):
            part = self.parts()['reports-zz-line']
        shown = re.findall(r'<span class="at">([^<]*)</span><span class="what"><a href="/report/zz-line/([^"]+)"', part)
        self.assertEqual(shown, [('2026-11-06 09:05', '2026-11-06_aaa1111.html'), ('2026-11-04', '2026-11-04_bbb2222.html')])

    def test_with_no_log_the_name_tells_what_was_compared(self):
        report(self.root, 'zz-line', '2026-10-30_abc1234.html')
        report(self.root, 'zz-line', '2026-10-31_aaa1111-bbb2222.html')
        text = plain(self.project('zz-line'))
        self.assertIn('parent of abc1234 to abc1234', text)
        self.assertIn('aaa1111 to bbb2222', text)

    def test_a_subject_is_escaped(self):
        h = commit(self.root, 'zz-line', '<img src=x>')
        report(self.root, 'zz-line', f'2026-10-30_{h}.html')
        self.assertNotIn('<img', self.parts()['reports-zz-line'])
        self.assertIn('&lt;img src=x&gt;', self.parts()['reports-zz-line'])

    def test_a_commit_git_does_not_know_links_by_its_hash(self):
        report(self.root, 'zz-line', '2026-10-30_abc1234.html')
        self.assertRegex(self.project('zz-line'), r'target="_blank" rel="noopener">abc1234</a>')

    def test_a_report_of_another_name_still_shows(self):
        report(self.root, 'zz-line', 'by hand.html')
        self.assertRegex(self.project('zz-line'), r'<a href="/report/zz-line/by%20hand.html"[^>]*>by hand.html</a>')

    def test_a_project_with_only_reports_is_on_the_list_newest_report_first(self):
        report(self.root, 'zz-line', '2026-10-30_aaa1111.html', made=datetime.datetime(2026, 10, 30, 9, 0))
        report(self.root, 'zz-line', '2026-11-01_bbb2222.html', made=datetime.datetime(2026, 11, 1, 9, 0))
        text = self.text('reports-zz-line')
        self.assertLess(text.index('bbb2222'), text.index('aaa1111'))
        self.assertNotIn('bbb2222', self.row())

    def test_a_project_with_none_says_so(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.assertIn('No change report yet', plain(self.project('zz-line')))

    def test_a_round_lists_the_reports_folder_again_only_when_it_changed(self):
        report(self.root, 'zz-line', '2026-10-30_aaa1111.html')
        self.tick()
        with mock.patch.object(dashboard, 'report_files', wraps=dashboard.report_files) as listed:
            self.tick()
            self.assertEqual(listed.call_count, 0)
            report(self.root, 'zz-line', '2026-10-31_bbb2222.html')
            self.assertIn('bbb2222', self.text('reports-zz-line'))
            self.assertEqual(listed.call_count, 1)

    def test_a_report_removed_goes_from_the_next_round(self):
        report(self.root, 'zz-line', '2026-10-30_aaa1111.html')
        report(self.root, 'zz-line', '2026-10-31_bbb2222.html')
        self.assertIn('aaa1111', self.text('reports-zz-line'))
        os.remove(os.path.join(self.root, 'zz-line', 'changes', 'reports', '2026-10-30_aaa1111.html'))
        self.assertNotIn('aaa1111', self.text('reports-zz-line'))
        self.assertIn('bbb2222', self.text('reports-zz-line'))

    def test_a_change_report_call_in_the_history_says_what_it_compared(self):
        log(self.root, 'zz-line', '20261030_120000_change_report', ok=True, page='changes\\reports\\a.html',
            before='zz-line @ HEAD~1 (aaa1111)', after='zz-line @ HEAD (bbb2222)')
        self.assertIn('change_report aaa1111 to bbb2222', plain(self.project('zz-line')))


def hmipreview_running():
    """TiaHmiGenerator\\hmipreview\\running.py, what a preview server keeps its record with, read as a file: the package
    itself loads the validator."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        'TiaHmiGenerator', 'hmipreview', 'running.py')
    spec = importlib.util.spec_from_file_location('hmipreview_running', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Preview:
    """A stand-in for an HMI preview server: it answers /api/about as one does, for a repo and pid."""

    def __init__(self, test, repo, pid, devices=(), app='hmipreview'):
        about = json.dumps({'app': app, 'repo': repo, 'pid': pid, 'devices': list(devices)}).encode('utf-8')

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = (200, about) if self.path == '/api/about' else (404, b'')
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'


class HmiPreview(Case):
    STARTED = datetime.datetime(2026, 10, 30, 13, 42, tzinfo=datetime.timezone.utc)

    def record(self, url, pid=7000, repo=None, started=None):
        """The record a preview server keeps while it runs, written as hmipreview writes it."""
        running = hmipreview_running()
        r = running.record(repo or os.path.join(self.root, 'zz-line'), url, pid=pid)
        r['started'] = (started or self.STARTED).isoformat()
        running.write(self.previews, r)
        self.procs.add(pid, name='python.exe')

    def links(self, name='zz-line'):
        return re.findall(r'<a href="([^"]+)" target="_blank" rel="noopener">([^<]+)</a>',
                          self.parts().get(f'preview-{name}', ''))

    def test_the_dashboard_looks_where_a_preview_keeps_its_record(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Users\x\AppData\Local'}):
            os.environ.pop('HMIPREVIEW_RUNNING')
            self.assertEqual(hmipreview_running().folder(), dashboard.previews_folder())
            self.assertEqual(os.path.join(r'C:\Users\x\AppData\Local', 'hmipreview', 'running'), dashboard.previews_folder())

    def test_a_running_preview_links_each_hmi_device_of_its_project(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        p = Preview(self, os.path.join(self.root, 'zz-line'), 7000, devices=['HMI_A', 'HMI 2'])
        self.record(p.url)
        self.assertEqual([(p.url + '?device=HMI_A', 'HMI_A'), (p.url + '?device=HMI%202', 'HMI 2')], self.links())
        text = self.text('preview-zz-line')
        self.assertIn(f'since {hm(self.STARTED)}', text)
        self.assertIn(p.url, text)
        self.assertRegex(self.parts()['preview-zz-line'], r'^<h3>HMI preview</h3><div class="body">')

    def test_a_preview_of_one_device_links_the_preview(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        p = Preview(self, os.path.join(self.root, 'zz-line'), 7000)
        self.record(p.url)
        self.assertEqual([(p.url, p.url)], self.links())

    def test_a_project_with_no_preview_has_an_empty_preview_part(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.assertEqual('', self.parts()['preview-zz-line'])
        self.assertIn('<section class="part optional" id="preview-zz-line"></section>', self.parts()['pane'])

    def test_an_empty_part_hides_in_every_browser_the_guide_names(self):
        """:empty, not :has(), which Firefox has only from 121 (TiaAgentStatus/README.md names 120)."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            'tools', 'dashboard', 'dashboard.css')
        with open(path, encoding='utf-8') as f:
            rules = [line for line in f if '.optional' in line]
        self.assertEqual(['.part.optional:empty { display: none; }\n'], rules)

    def test_a_preview_that_stopped_is_gone(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        p = Preview(self, os.path.join(self.root, 'zz-line'), 7000)
        self.record(p.url)
        self.assertTrue(self.links())
        p.server.shutdown()
        p.server.server_close()
        self.assertEqual([], self.links())

    def test_a_record_whose_process_is_gone_is_not_asked(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        p = Preview(self, os.path.join(self.root, 'zz-line'), 7000)
        self.record(p.url)
        del self.procs.procs[7000]
        with mock.patch.object(dashboard, 'about', side_effect=AssertionError('asked')):
            self.assertEqual([], self.links())

    def test_a_port_another_server_took_shows_no_link(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        repo = os.path.join(self.root, 'zz-line')
        for pid, p in ((7000, Preview(self, os.path.join(self.root, 'zz-other'), 7000)),    # another repo's preview
                       (7001, Preview(self, repo, 7002)),                                    # another server of this repo
                       (7003, Preview(self, repo, 7003, app='something else'))):
            self.record(p.url, pid=pid)
        self.assertEqual([], self.links())

    def test_a_project_with_only_a_running_preview_is_on_the_list(self):
        p = Preview(self, os.path.join(self.root, 'zz-line'), 7000)
        self.record(p.url)
        self.assertIn('zz-line', self.row())
        self.assertEqual([(p.url, p.url)], self.links())

    def test_the_dashboard_leaves_the_records_as_they_are(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.record('http://127.0.0.1:9/', pid=7000)
        self.record('http://127.0.0.1:9/', pid=7001)
        del self.procs.procs[7001]
        with open(os.path.join(self.previews, 'notes.txt'), 'w') as f:
            f.write('not a record')
        before = sorted(os.listdir(self.previews))
        self.tick()
        self.assertEqual(before, sorted(os.listdir(self.previews)))

    def test_a_record_that_does_not_read_is_left_out(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        for name, text in (('1.json', '{"repo": '), ('2.json', '[]'), ('3.json', '{"repo": 1, "url": "x", "pid": 3}'),
                           ('4.json', json.dumps({'repo': 'r', 'url': 'file:///C:/x', 'pid': 4}))):
            with open(os.path.join(self.previews, name), 'w') as f:
                f.write(text)
        self.procs.add(3)
        self.procs.add(4)
        self.assertEqual([], self.links())
        self.assertNotIn('could not be read', self.headline())


class Serving(Case):
    def setUp(self):
        super().setUp()
        report(self.root, 'zz-line', '2026-10-30_abc1234.html', '<html>the report</html>')

    def test_a_report_is_served_as_a_page(self):
        self.serve()
        self.assertEqual(self.get('/report/zz-line/2026-10-30_abc1234.html'), (200, '<html>the report</html>'))

    def test_the_page_holds_what_skill_tia_dashboard_looks_for(self):
        """The skill tells a running dashboard by its header; a page without one sends an agent to start a second one. The
        header of older builds counts too: a dashboard runs on through an update of the clone."""
        skill = os.path.join(os.path.dirname(os.path.dirname(dashboard.__file__)), '.claude', 'skills', 'tia-dashboard', 'SKILL.md')
        with open(skill, encoding='utf-8') as f:
            text = f.read()
        self.assertIn(f'`<h1>{dashboard.TITLE}</h1>`', text)
        self.assertIn('`<h1>TIA dashboard</h1>`', text)
        self.serve()
        status, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn(f'<h1>{dashboard.TITLE}</h1>', body)

    def test_nothing_else_is_served(self):
        folder = os.path.join(self.root, 'zz-line')
        report(self.root, 'zz-line', 'notes.txt', 'private')
        with open(os.path.join(folder, 'changes', 'next.html'), 'w', encoding='utf-8') as f:
            f.write('private')
        with open(os.path.join(self.root, 'secret.html'), 'w', encoding='utf-8') as f:
            f.write('private')
        os.makedirs(os.path.join(folder, 'changes', 'reports', 'sub'))
        with open(os.path.join(folder, 'changes', 'reports', 'sub', 'deep.html'), 'w', encoding='utf-8') as f:
            f.write('private')
        report(self.root, '_bridge', 'x.html', 'private')
        self.serve()
        for path in ('/report/zz-line/notes.txt', '/report/zz-line/next.html', '/report/zz-line/../next.html',
                     '/report/zz-line/..%2fnext.html', '/report/zz-line/..%5cnext.html',
                     '/report/zz-line/..%2f..%2f..%2fsecret.html', '/report/zz-line/sub%2fdeep.html',
                     '/report/zz-line/sub/deep.html', '/report/zz-line/sub', '/report/zz-line/', '/report/zz-line',
                     '/report/zz-line/C:%5cWindows%5cwin.ini', '/report/nobody/2026-10-30_abc1234.html',
                     '/report/..%2fzz-line/2026-10-30_abc1234.html', '/report/ZZ-LINE/2026-10-30_abc1234.html',
                     '/report/_bridge/x.html', '/zz-line/changes/reports/2026-10-30_abc1234.html',
                     '/CLAUDE.md', '/pyproject.toml', '/TiaAgentStatus/dashboard.py', '/secret.html', '/dashboard.py',
                     '/vendor/../live.py', '/vendor/%2e%2e%2flive.py', '/events', '/events?doc=CLAUDE.md'):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_head_serves_nothing_from_the_working_folder_either(self):
        self.serve()
        for path in ('/pyproject.toml', '/TiaAgentStatus/', '/'):
            self.assertEqual(self.get(path, 'HEAD')[0], 404, path)

    def test_a_write_is_refused(self):
        self.serve()
        self.assertEqual(self.get('/report/zz-line/2026-10-30_abc1234.html', 'POST')[0], 501)
        self.assertEqual(self.get('/report/zz-line/2026-10-30_abc1234.html', 'DELETE')[0], 501)

    def test_a_reports_folder_that_leads_elsewhere_serves_nothing(self):
        outside = tempdir(self)
        with open(os.path.join(outside, '2026-10-30_abc1234.html'), 'w', encoding='utf-8') as f:
            f.write('private')
        os.makedirs(os.path.join(self.root, 'zz-other', 'changes'))
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', os.path.join(self.root, 'zz-other', 'changes', 'reports'), outside],
                              capture_output=True)
        self.addCleanup(subprocess.run, ['cmd', '/c', 'rmdir', os.path.join(self.root, 'zz-other', 'changes', 'reports')],
                        capture_output=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.serve()
        self.assertEqual(self.get('/report/zz-other/2026-10-30_abc1234.html')[0], 404)
        self.assertNotIn('abc1234', self.parts().get('reports-zz-other', ''))

    def test_a_folder_named_like_a_report_is_no_report(self):
        os.makedirs(os.path.join(self.root, 'zz-line', 'changes', 'reports', 'x.html'))
        self.serve()
        self.assertEqual(self.get('/report/zz-line/x.html')[0], 404)
        self.assertNotIn('x.html', self.parts()['reports-zz-line'])

    def test_a_report_file_that_leads_elsewhere_is_not_served(self):
        outside = tempdir(self)
        target = os.path.join(outside, 'private.html')
        with open(target, 'w', encoding='utf-8') as f:
            f.write('private')
        try:
            os.symlink(target, os.path.join(self.root, 'zz-line', 'changes', 'reports', 'link.html'))
        except OSError:
            self.skipTest('this user may not make symbolic links')
        self.serve()
        self.assertEqual(self.get('/report/zz-line/link.html')[0], 404)

    def with_host(self, method, host, path='/'):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        self.addCleanup(c.close)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader('Host', host)
        c.endheaders()
        return c.getresponse().status

    def test_this_machine_gets_in_by_address_or_name_with_the_port(self):
        self.serve()
        for host in (f'127.0.0.1:{self.port}', f'localhost:{self.port}'):
            self.assertEqual(self.with_host('GET', host), 200, host)

    def test_any_other_host_is_refused_also_a_proxy_s_address(self):
        self.serve()
        report_path = '/report/zz-line/2026-10-30_abc1234.html'
        for host in ('attacker.example', f'attacker.example:{self.port}', '127.0.0.1:1', 'machine.tailnet.ts.net',
                     'machine.tailnet.ts.net:8443'):
            self.assertEqual(self.with_host('GET', host), 403, host)
            self.assertEqual(self.with_host('HEAD', host), 403, host)
            self.assertEqual(self.with_host('POST', host), 403, host)
            self.assertEqual(self.with_host('GET', host, '/events?start=1'), 403, host)
            self.assertEqual(self.with_host('GET', host, report_path), 403, host)

    def test_it_listens_on_this_machine_only(self):
        self.tick()
        server = dashboard.make_server(self.d, 0)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], '127.0.0.1')

    def test_the_theme_switch_has_its_place_outside_what_updates_swap(self):
        page = self.page()
        self.assertIn('<script src="/dashboard.js"></script>', page.split('</head>')[0])
        self.assertLess(page.index('class="top"'), page.index('</header>'))
        self.assertLess(page.index('</header>'), page.index('id="summary"'))

    def test_the_theme_switch_is_in_the_top_bar_in_a_browser(self):
        edge = support.headless()
        if not edge:
            self.skipTest('no Microsoft Edge, Google Chrome or hmipreview')
        self.addCleanup(edge.close)
        self.serve()
        self.assertRegex(support.dom_at_load(edge, f'http://127.0.0.1:{self.port}/'), support.SWITCH_IN_TOP)

    def test_the_stylesheet_and_script_of_the_live_core_are_served(self):
        self.serve()
        self.assertIn('--you', self.get('/dashboard.css')[1])
        self.assertIn('dashboardBoard', self.get('/dashboard.js')[1])

    def test_a_folder_a_bridge_names_outside_the_root_serves_its_reports(self):
        other = tempdir(self)
        report(other, 'zz-elsewhere', '2026-10-30_abc1234.html', 'elsewhere')
        self.bridge(200, project='zzPlant', repo=os.path.join(other, 'zz-elsewhere'))
        self.serve()
        self.assertEqual(self.get('/report/zz-elsewhere/2026-10-30_abc1234.html'), (200, 'elsewhere'))


class ReportRuns(Case):
    """The button that starts a report run (TiaAgentStatus\\reportrun.py), and the line of the run under it."""

    def setUp(self):
        super().setUp()
        log(self.root, 'zz-line', '20261106_100000_full_export', ok=True)
        self.started = []

    def tick(self):
        if self.d is None:
            self.d = dashboard.Dashboard(self.procs, dashboard.NoHerdr(), self.root, now=lambda: self.now,
                                         start_run=self.started.append)
        self.d.tick()

    def press(self, project='zz-line', token=None, origin=None, kind='application/json', body=None):
        """The button's request as a page sends it; each header can be left out (None) or changed."""
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        self.addCleanup(c.close)
        data = json.dumps({'project': project}).encode() if body is None else body
        headers = {'Content-Length': str(len(data))}
        for k, v in (('Content-Type', kind), ('X-Report-Token', token if token is not None else self.d.token),
                     ('Origin', origin if origin is not None else f'http://127.0.0.1:{self.port}')):
            if v:
                headers[k] = v
        c.request('POST', '/api/report-run', data, headers)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b'{}')

    def record(self, folder='zz-line', pid=900, **more):
        self.procs.add(pid, name='python.exe')
        r = {'v': 1, 'pid': pid, 'started': iso(NOW - datetime.timedelta(minutes=5)), 'ended': None, 'step': 'full_export',
             'outcome': None, 'text': '', 'project': 'zzLine', 'repo': os.path.join(self.root, folder), 'bridge': 901, 'tia': 300}
        r.update(more)
        os.makedirs(os.path.join(self.root, '_bridge', 'report-runs'), exist_ok=True)
        with open(os.path.join(self.root, '_bridge', 'report-runs', folder + '.json'), 'w', encoding='utf-8') as f:
            json.dump(r, f)

    def test_the_dashboard_s_own_page_starts_a_run_of_the_project(self):
        self.serve()
        self.assertIn(f'<meta name="report-token" content="{self.d.token}">', self.get('/')[1])
        self.assertEqual(self.press(), (200, {'ok': True}))
        self.assertEqual(self.started, [os.path.join(self.root, 'zz-line')])

    def test_a_request_without_the_page_s_token_or_from_another_page_starts_nothing(self):
        self.serve()
        for case in ({'token': ''}, {'token': 'guessed'}, {'origin': ''}, {'origin': 'http://attacker.example'},
                     {'origin': f'http://localhost:{self.port}.attacker.example'}, {'origin': 'null'}):
            with self.subTest(**case):
                self.assertEqual(self.press(**case)[0], 403)
        self.assertEqual(self.press(kind='text/plain')[0], 415)
        self.assertEqual(self.press(kind='application/x-www-form-urlencoded', body=b'project=zz-line')[0], 415)
        self.assertEqual(self.started, [])

    def test_a_project_the_dashboard_does_not_know_is_refused(self):
        self.serve()
        for project in ('zz-nothing', '..', '_bridge', ''):
            with self.subTest(project=project):
                self.assertEqual(self.press(project)[0], 404)
        self.assertEqual(self.started, [])

    def test_the_button_waits_while_a_bridge_is_connected_and_says_so(self):
        self.held()
        self.serve()
        part = self.parts()['run-zz-line']
        self.assertRegex(part, r'<button [^>]*disabled')
        self.assertIn('Not now: a bridge is connected to this TIA', plain(part))
        self.assertEqual(self.press(), (409, {'ok': False, 'error': 'Not now: a bridge is connected to this TIA.'}))
        self.assertEqual(self.started, [])

    def test_a_second_press_starts_no_second_run(self):
        self.serve()
        self.assertEqual(self.press()[0], 200)
        status, reply = self.press()
        self.assertEqual(status, 409)
        self.assertEqual(reply['error'], 'Not now: a report run of zz-line is going on.')
        self.assertEqual(len(self.started), 1)

    def test_the_button_says_what_to_press(self):
        part = self.parts()['run-zz-line']
        self.assertRegex(part, r'<button class="act" type="button" data-report-run="zz-line">Make a change report of TIA now</button>')
        self.assertNotIn('disabled', part)

    def test_a_running_run_shows_the_bridge_s_call_and_its_time_and_no_button(self):
        self.record()
        self.procs.add(901)
        write(st.sessions_dir(self.root), state(901, 900, repo=os.path.join(self.root, 'zz-line'), tia=300, client='report-run',
                                                operation={'name': 'full_export', 'part': 'blocks', 'n': 412, 'of': 1180,
                                                           'since': iso(NOW - datetime.timedelta(minutes=3))}))
        text = self.text('run-zz-line')
        self.assertIn('▸ Making a change report: full_export blocks 412/1180 5:00', text)
        self.assertIn('Leave TIA alone until it ends', text)
        self.assertNotIn('<button', self.parts()['run-zz-line'])
        self.assertIn('Report run: full_export blocks 412/1180', self.text('now-zz-line'))

    def test_a_run_waiting_on_connect_says_tia_may_ask(self):
        self.record(step='connect')
        self.assertIn('TIA may ask to allow access: answer it in TIA.', self.text('run-zz-line'))

    def test_another_project_s_run_holds_the_button(self):
        log(self.root, 'zz-other', '20261106_100000_full_export', ok=True)
        self.record('zz-other', project='zzOther')
        part = self.parts()['run-zz-line']
        self.assertRegex(part, r'<button [^>]*disabled')
        self.assertIn('Not now: a report run of zzOther is going on.', plain(part))

    def test_a_run_that_ended_says_how_with_its_time(self):
        end = NOW - datetime.timedelta(minutes=1)
        self.record(ended=iso(end), outcome='done', text='Done: TIA as it stood. Committed 8d0e7b4.', commit='8d0e7b4')
        self.assertIn(f'{hm(end)} Done, 4:00: TIA as it stood. Committed 8d0e7b4.', self.text('run-zz-line'))
        self.assertIn('<button class="act"', self.parts()['run-zz-line'])
        self.record(ended=iso(end), outcome='failed', text='Failed at full_export: TIA ended. Nothing was committed; the repo is as it was.')
        part = self.parts()['run-zz-line']
        self.assertIn('class="run fail"', part)
        self.assertIn(f'! {hm(end)} Failed at full_export: TIA ended.', plain(part))

    def test_a_run_whose_process_is_gone_without_an_end_says_so(self):
        self.record()
        self.procs.kill(900)
        self.assertIn('The report run ended without a word', self.text('run-zz-line'))


class Live(Case):
    def events(self):
        """The updates of a connection, one by one."""
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('GET', '/events?start=1')
        r = c.getresponse()
        self.addCleanup(c.close)
        self.assertEqual(r.getheader('Content-Type').split(';')[0], 'text/event-stream')
        while True:
            line = r.readline().decode('utf-8')
            if line.startswith('data: '):
                yield json.loads(line[6:])

    def test_the_page_runs_on_the_shared_live_script_and_shows_the_chosen_project_from_its_address(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        page = self.page()
        self.assertIn('dashboardBoard(', page)
        self.assertIn('hashchange', page)
        self.assertIn('location.hash', page)

    def test_every_part_has_its_own_slot_once(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        log(self.root, 'zz-press', '20261030_130000_compile', ok=True)
        self.tick()
        slots = re.findall(r' id="([^"]+)"', dashboard.page(self.d) + ''.join(self.d.latest['parts'].values()))
        for part in self.d.latest['parts']:
            self.assertEqual(slots.count(part), 1, part)

    def test_a_connection_gets_the_page_then_what_changed(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.serve()
        updates = self.events()
        first = next(updates)
        self.assertIn('row-zz-line', first['parts']['list'])
        self.assertTrue(first['updated'])
        log(self.root, 'zz-press', '20261030_130000_compile', ok=True)
        self.tick()
        self.assertIn('row-zz-press', next(updates)['parts']['list'])

    def test_nothing_new_makes_no_update(self):
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.tick()
        before = self.d.latest
        self.tick()
        self.assertIs(self.d.latest, before)

    def changed_by(self, change):
        self.tick()
        before = dict(self.d.latest['parts'])
        change()
        after = self.parts()
        return {k for k in after if after[k] != before.get(k)}

    def test_a_new_call_changes_only_its_project_s_parts_so_a_scrolled_area_stays(self):
        today = NOW.astimezone().strftime('%Y%m%d')
        log(self.root, 'zz-line', f'{today}_120000_compile', ok=True)
        log(self.root, 'zz-press', '20261001_120000_compile', ok=True)
        changed = self.changed_by(lambda: log(self.root, 'zz-line', f'{today}_130000_save', ok=True))
        self.assertEqual(changed, {'row-zz-line', 'history-zz-line'})

    def test_the_time_of_a_call_changes_only_what_shows_it(self):
        self.held(operation=self.running())
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        self.tick()     # a TIA's CPU shows from its second round
        self.now = NOW + datetime.timedelta(seconds=5)
        self.tick()

        def later():
            self.now = NOW + datetime.timedelta(seconds=10)
        self.assertEqual(self.changed_by(later), {'row-zz-line', 'now-zz-line'})

    def test_it_writes_nothing(self):
        self.procs.add(300, memory=2**30)
        self.bridge(200, project='zzPlant', repo=os.path.join(self.root, 'zz-line'), tia=300,
                    operation={'name': 'import', 'since': iso(NOW)})
        write(st.sessions_dir(self.root), state(201, None, tia=300))     # a bridge that is gone
        log(self.root, 'zz-line', '20261030_120000_compile', ok=True)
        report(self.root, 'zz-line', '2026-10-30_abc1234.html')

        def everything():
            return {os.path.join(d, n): os.stat(os.path.join(d, n)).st_mtime_ns
                    for d, dirs, files in os.walk(self.root) for n in dirs + files}
        before = everything()
        self.serve()
        self.get('/')
        self.get('/report/zz-line/2026-10-30_abc1234.html')
        self.tick()
        self.assertEqual(everything(), before)


class ACommitsSubject(unittest.TestCase):
    def test_it_is_of_the_repo_a_state_file_names_with_a_parents_git_context_inherited(self):
        repos = {}
        for name in ('A', 'B'):
            repos[name] = support.made_up_repo(self)
            for args in (['init', '-q'], ['-c', 'user.name=x', '-c', 'user.email=x@example.com', '-c', 'commit.gpgsign=false',
                                          'commit', '-q', '--allow-empty', '-m', 'in ' + name]):
                subprocess.run(['git', '-C', str(repos[name]), *args], check=True, capture_output=True)
        git_dir = str(repos['A'] / '.git')
        with mock.patch.dict(os.environ, {'GIT_DIR': git_dir, 'GIT_WORK_TREE': str(repos['A']),
                                          'GIT_INDEX_FILE': os.path.join(git_dir, 'index')}):
            self.assertEqual(dashboard.Subjects().of(str(repos['B']), 'HEAD'), 'in B')


class Rounds(unittest.TestCase):
    """The rounds after the first, on a made-up clock: (when each started, how long the waits before it were)."""

    class Enough(Exception):
        pass

    def run_rounds(self, every, lasting):
        clock, started, waits = [0.0], [], []

        def tick():
            started.append(clock[0])
            clock[0] += lasting[len(started) - 1]
            if len(started) == len(lasting):
                raise self.Enough

        def sleep(s):
            waits.append(s)
            clock[0] += s
        with self.assertRaises(self.Enough):
            dashboard.rounds(tick, every, clock=lambda: clock[0], sleep=sleep)
        return started, waits

    def test_a_round_starts_every_period_from_the_start_of_the_last(self):
        started, _ = self.run_rounds(1.0, [0.25, 0.5, 0.25])
        self.assertEqual(started, [1.0, 2.0, 3.0])

    def test_a_round_that_overruns_skips_the_starts_it_missed_rather_than_stack_them(self):
        started, waits = self.run_rounds(1.0, [2.5, 0.25, 0.25])
        self.assertEqual(started, [1.0, 4.0, 5.0])
        self.assertTrue(all(w >= 0 for w in waits), waits)


class TheEveryOption(unittest.TestCase):
    """dashboard --every S: the seconds between two rounds, as the command hands them to the rounds."""

    def every(self, *args):
        """What the rounds get, their thread run at once."""
        from TiaAgentStatus import __main__ as command
        got = []

        def thread(target, args, daemon):
            return mock.Mock(start=lambda: target(*args))
        with mock.patch.object(dashboard, 'rounds', side_effect=lambda tick, every: got.append(every)), \
                mock.patch.object(dashboard.threading, 'Thread', side_effect=thread), \
                mock.patch.object(dashboard, 'make_server'), mock.patch.object(dashboard.tray, 'serve'), \
                mock.patch.object(dashboard.shutil, 'which', return_value=None), \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            command.main(['dashboard', '--root', tempdir(self), *args])
        return got

    def test_it_is_one_second_by_default(self):
        self.assertEqual(self.every(), [1.0])

    def test_it_takes_seconds(self):
        self.assertEqual(self.every('--every', '2.5'), [2.5])

    def test_none_less_endless_or_no_number_is_refused_also_by_watch(self):
        from TiaAgentStatus import __main__ as command
        said = f"argument --every: takes seconds, more than 0, not '{{}}'"   # what the box of a wrong option says
        for value in ('0', '-1', 'inf', 'nan', 'often'):
            with self.subTest(value), mock.patch('sys.stderr', new_callable=io.StringIO) as err, \
                    self.assertRaises(SystemExit):
                try:
                    self.every('--every', value)
                finally:
                    self.assertIn(said.format(value), err.getvalue())
            with self.subTest('watch ' + value), mock.patch('sys.stderr', new_callable=io.StringIO) as err, \
                    self.assertRaises(SystemExit):
                try:
                    command.main(['watch', '--once', '--every', value])
                finally:
                    self.assertIn(said.format(value), err.getvalue())


class TheCommand(unittest.TestCase):
    """python TiaAgentStatus dashboard, on the real process table, with no herdr and no git on the PATH."""

    def start(self, root, port):
        env = dict(os.environ, PATH='', DASHBOARD_NO_ICON='1')
        p = subprocess.Popen([sys.executable, '-X', 'utf8', os.path.join(os.path.dirname(dashboard.__file__)), 'dashboard',
                              '--root', root, '--port', str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.stderr.close)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        return p

    @staticmethod
    def free_port():
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def test_a_real_bridge_state_file_shows_with_no_herdr(self):
        root = tempdir(self)
        write(st.sessions_dir(root), state(os.getpid(), None, project=None, started=datetime.datetime.now(datetime.timezone.utc)))
        report(root, 'zz-line', '2026-10-30_abc1234.html')
        port = self.free_port()
        p = self.start(root, port)
        for _ in range(100):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/events?start=1', timeout=5) as r:
                    while True:
                        line = r.readline().decode('utf-8')
                        if line.startswith('data: '):
                            parts = json.loads(line[6:])['parts']
                            break
                break
            except OSError:
                self.assertIsNone(p.poll(), 'the server ended')
                time.sleep(0.1)
        else:
            self.fail('the server did not start')
        # the real process table: a TIA open on this machine may follow, under its own heading
        self.assertTrue(plain(parts['others']).startswith('Bridges with no project ○ Bridge idle since '), plain(parts['others'])[:60])
        self.assertIn('zz-line', plain(parts['row-zz-line']))
        self.assertIn('abc1234', plain(parts['reports-zz-line']))

    def test_a_port_in_use_is_said_and_not_shared(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            s.listen()
            p = self.start(tempdir(self), s.getsockname()[1])
            self.assertNotEqual(p.wait(timeout=20), 0)
            self.assertIn(b'is taken', p.stderr.read())


if __name__ == '__main__':
    unittest.main()
