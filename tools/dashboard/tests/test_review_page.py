"""The review_page.py command: builds a page, takes it down, shows it in the browser."""
import _winapi
import contextlib
import io
import json
import os
import subprocess
import unittest
import urllib.request
from unittest import mock

from .support import Server, free_port, made_up_repo

import review_page  # noqa: E402


class ReviewPageTest(unittest.TestCase):
    def setUp(self):
        # The root is given by another spelling of its folder, a junction (a short 8.3 temp path on a CI runner);
        # review_page.py resolves it, so the paths it prints are the resolved ones.
        folder = made_up_repo(self)
        (folder / 'clone').mkdir()
        _winapi.CreateJunction(str(folder / 'clone'), str(folder / 'via'))
        self.root = folder / 'via' / '.scratch'
        self.scratch = self.root.resolve()
        self.reviews = self.scratch / 'reviews'

    def run_page(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = review_page.main(['--root', str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def build_with_everything(self, title='My page'):
        attachment = self.scratch.parent / 'report.html'
        attachment.write_text('<p>a report</p>', encoding='utf-8')
        self.assertEqual(self.run_page('--title', title, '--ask', 'Which?', '--no-open', f'{attachment}::The report')[0], 0)
        answers = self.reviews / 'answers'
        answers.mkdir()
        (answers / f'{title}.json').write_text(json.dumps({'at': 'now', 'answers': []}), encoding='utf-8')

    def test_a_page_is_written_under_the_root_with_its_question_and_file(self):
        code, out, _ = self.run_page('--title', 'A: title', '--ask', 'Why?', '--note', 'Context', '--no-open')
        self.assertEqual(code, 0)
        page = self.reviews / 'A_ title.html'
        self.assertEqual(out.strip(), str(page))
        text = page.read_text(encoding='utf-8')
        self.assertIn('<li><span>Why?</span></li>', text)
        self.assertIn('Context', text)

    def test_done_moves_page_files_and_answers_out_and_keeps_links_working(self):
        self.build_with_everything()
        code, out, _ = self.run_page('--done', 'My page')
        self.assertEqual(code, 0)
        self.assertFalse((self.reviews / 'My page.html').exists())
        self.assertFalse((self.reviews / 'files' / 'My page').exists())
        self.assertFalse((self.reviews / 'answers' / 'My page.json').exists())
        done = self.reviews / 'done' / 'My page'
        self.assertIn(str(done), out)
        self.assertTrue((done / 'My page.html').exists())
        self.assertTrue((done / 'answers' / 'My page.json').exists())
        link = 'files/My%20page/report.html'
        self.assertIn(link, (done / 'My page.html').read_text(encoding='utf-8'))
        self.assertTrue((done / 'files' / 'My page' / 'report.html').exists())

    def test_done_works_for_a_page_with_no_answer_and_no_files(self):
        self.run_page('--title', 'Bare', '--ask', 'Why?', '--no-open')
        self.assertEqual(self.run_page('--done', 'Bare')[0], 0)
        self.assertTrue((self.reviews / 'done' / 'Bare' / 'Bare.html').exists())

    def test_done_twice_keeps_both(self):
        self.run_page('--title', 'Again', '--ask', 'First?', '--no-open')
        self.run_page('--done', 'Again')
        self.run_page('--title', 'Again', '--ask', 'Second?', '--no-open')
        self.run_page('--done', 'Again')
        self.assertIn('First?', (self.reviews / 'done' / 'Again' / 'Again.html').read_text(encoding='utf-8'))
        self.assertIn('Second?', (self.reviews / 'done' / 'Again 2' / 'Again.html').read_text(encoding='utf-8'))

    def test_done_of_a_page_that_is_not_there_says_so(self):
        code, _, err = self.run_page('--done', 'Nothing here')
        self.assertEqual(code, 1)
        self.assertIn('Nothing here', err)

    def test_title_is_required_to_build(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            review_page.main(['--root', str(self.scratch), '--ask', 'x'])


class BrowserTest(unittest.TestCase):
    """Only --open starts a browser; building a page is pushed to the dashboard. The server is real."""

    def setUp(self):
        self.scratch = made_up_repo(self) / '.scratch'
        self.server = Server(self.scratch)
        self.addCleanup(self.server.stop)
        self.base = ['--root', str(self.scratch), '--port', str(self.server.port)]

    def build(self):
        self.assertEqual(review_page.main([*self.base, '--title', 'Shown', '--ask', 'Why?']), 0)

    def open_page(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.build()
        self.assertEqual(review_page.main([*self.base, '--open', 'Shown']), 0)

    def test_building_a_page_starts_no_browser_and_prints_its_address(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {'DASHBOARD_BROWSER': r'C:\some folder\browser.exe'}), \
                mock.patch.object(review_page.webbrowser, 'open') as default, \
                mock.patch.object(review_page.subprocess, 'Popen') as started, contextlib.redirect_stdout(out):
            self.build()
        default.assert_not_called()
        started.assert_not_called()
        self.assertIn(f'http://127.0.0.1:{self.server.port}/Shown.html', out.getvalue())
        self.assertIn('Shown', self.server.get('/'))

    def test_open_starts_the_default_browser_on_the_page(self):
        with mock.patch.dict(os.environ), mock.patch.object(review_page.webbrowser, 'open', return_value=True) as opened, \
                contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop('DASHBOARD_BROWSER', None)
            self.open_page()
        opened.assert_called_once_with(f'http://127.0.0.1:{self.server.port}/Shown.html')

    def test_dashboard_browser_names_the_browser_for_open(self):
        with mock.patch.dict(os.environ, {'DASHBOARD_BROWSER': r'C:\some folder\browser.exe'}), \
                mock.patch.object(review_page.subprocess, 'Popen') as started, \
                mock.patch.object(review_page.webbrowser, 'open') as default, contextlib.redirect_stdout(io.StringIO()):
            self.open_page()
        self.assertEqual(started.call_args.args[0], [r'C:\some folder\browser.exe', f'http://127.0.0.1:{self.server.port}/Shown.html'])
        self.assertTrue(started.call_args.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
        default.assert_not_called()

    def test_open_with_no_browser_still_prints_where_to_look(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ), mock.patch.object(review_page.webbrowser, 'open', return_value=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop('DASHBOARD_BROWSER', None)
            self.open_page()
        self.assertIn(f'http://127.0.0.1:{self.server.port}/Shown.html', out.getvalue())


class StartingTheServerTest(unittest.TestCase):
    """review_page.py starts the server itself when none runs: for real here, on a port of its own."""

    def start(self, scratch, *args):
        """Runs review_page.py; returns (exit code, stderr, port, the mock of the default browser)."""
        port = free_port()
        started, real_popen = [], subprocess.Popen

        def popen(*a, **k):
            started.append(real_popen(*a, **k))
            return started[-1]

        err = io.StringIO()
        with mock.patch.dict(os.environ), mock.patch.object(review_page.subprocess, 'Popen', popen), \
                mock.patch.object(review_page.webbrowser, 'open', return_value=True) as opened, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            os.environ.pop('DASHBOARD_BROWSER', None)
            code = review_page.main(['--root', str(scratch), '--port', str(port), *args])
        for proc in started:
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
        return code, err.getvalue(), port, opened

    def test_a_started_server_runs_on_a_path_outside_the_code_page(self):
        scratch = made_up_repo(self) / '\u65e5\u672c\u0142' / '.scratch'
        code, err, port, opened = self.start(scratch, '--title', 'Far', '--ask', 'Why?')
        self.assertEqual((code, err), (0, ''))
        opened.assert_not_called()
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=15) as r:
            self.assertIn('1 review waits', r.read().decode('utf-8'))

    def test_a_server_that_does_not_come_up_is_reported_and_no_browser_opens(self):
        not_a_folder = made_up_repo(self) / 'a file'
        not_a_folder.write_text('in the way', encoding='utf-8')
        code, err, port, opened = self.start(not_a_folder, '--open', 'Anything')
        self.assertEqual(code, 1)
        self.assertIn(f'did not start on port {port}', err)
        self.assertIn('review_server.py', err)
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
