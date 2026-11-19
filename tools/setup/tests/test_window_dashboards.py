"""The dashboards as the setup window tells them: by what their port answers, started with no console. On free ports
with a stand-in server; no real dashboard starts, and nothing opens a window."""
import _winapi
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from tools.setup.window import dashboards as dash

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
NO_WINDOW = subprocess.CREATE_NO_WINDOW


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Probe(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.board = replace(dash.dashboards((self.port, free_port()))[0])

    def serve(self, app, heading=''):
        stub = subprocess.Popen([sys.executable, str(HERE / 'stub_dashboard.py'), app, str(self.port), heading],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        self.addCleanup(stub.wait)
        self.addCleanup(stub.kill)
        for _ in range(100):
            if dash.listening(self.port):
                return stub
            time.sleep(0.1)
        self.fail('the stand-in did not answer')

    def test_nothing_on_the_port_is_not_running(self):
        self.assertEqual(dash.probe(self.board).state, 'stopped')

    def test_its_own_answer_is_running_with_its_clone(self):
        self.serve(self.board.app)
        self.assertEqual(dash.probe(self.board), dash.Status('running', 'C:\\stub'))

    def test_another_program_on_the_port_is_named_as_that(self):
        stub = self.serve('')
        status = dash.probe(self.board)
        self.assertEqual(status.state, 'other')
        self.assertIn(f'Port {self.port} is taken by ', status.text)
        self.assertRegex(status.text, r'by python(w)?\.exe \(process \d+\)')     # the venv's python.exe is a launcher: its child listens

    def test_the_other_dashboard_on_the_port_is_not_this_one(self):
        self.serve('tia-dashboard')
        self.assertEqual(dash.probe(self.board).state, 'other')

    def test_a_dashboard_built_before_it_said_what_it_is_is_told_by_its_heading(self):
        self.serve('', 'Development dashboard')
        self.assertEqual(dash.probe(self.board), dash.Status('running'))


class Start(unittest.TestCase):
    """start() in a made-up clone whose .venv is this tree's, by a junction, and whose dashboard is the stand-in."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='setup-window-')
        self.addCleanup(self.remove, folder)
        self.clone = Path(folder.name)
        _winapi.CreateJunction(str(REPO / '.venv'), str(self.clone / '.venv'))
        self.addCleanup(os.rmdir, self.clone / '.venv')     # the junction only, never what it points at
        shutil.copy(HERE / 'stub_dashboard.py', self.clone)
        self.port = free_port()
        self.board = replace(dash.dashboards((self.port, free_port()))[0], tool=('stub_dashboard.py', 'development-dashboard', str(self.port)))

    @staticmethod
    def remove(folder):
        """The folder, once the launcher of the stopped stand-in, which stood in it, has ended too."""
        for _ in range(50):
            try:
                return folder.cleanup()
            except PermissionError:
                time.sleep(0.1)
        folder.cleanup()

    def stop(self):
        pid = dash.listener(self.port).split('process ')[-1].rstrip(')')
        if pid.isdigit():
            os.kill(int(pid), signal.SIGTERM)     # by its Windows number, which netstat gave

    def test_it_comes_up_with_no_console_and_answers_as_itself(self):
        self.addCleanup(self.stop)
        ok, text = dash.start(self.board, str(self.clone))
        self.assertTrue(ok, text)
        self.assertEqual(dash.probe(self.board).state, 'running')
        self.assertIn('"console": false', dash.get(self.port, '/api/about')[1])

    def test_one_that_ends_says_how_to_read_why(self):
        board = replace(self.board, tool=('no_such_script.py',))
        ok, text = dash.start(board, str(self.clone))
        self.assertFalse(ok)
        self.assertIn('exit code', text)
        self.assertIn('python.exe', text)

    def test_without_the_environment_it_says_to_make_it(self):
        ok, text = dash.start(self.board, str(self.clone / 'elsewhere'))
        self.assertFalse(ok)
        self.assertIn('uv sync', text)


class Commands(unittest.TestCase):
    def test_each_starts_as_its_readme_says_and_a_port_of_its_own_is_passed_on(self):
        development, tia = dash.dashboards()
        clone = r'C:\c'
        self.assertEqual(development.command(clone), [r'C:\c\.venv\Scripts\pythonw.exe', '-X', 'utf8', r'C:\c\tools\dashboard\review_server.py'])
        self.assertEqual(tia.command(clone), [r'C:\c\.venv\Scripts\pythonw.exe', '-X', 'utf8', r'C:\c\TiaAgentStatus', 'dashboard'])
        self.assertEqual(dash.dashboards((1, 2))[1].command(clone)[-2:], ['--port', '2'])

    def test_each_says_at_its_about_page_what_the_window_looks_for(self):
        sys.path.insert(0, str(REPO / 'tools' / 'dashboard'))
        self.addCleanup(sys.path.remove, str(REPO / 'tools' / 'dashboard'))
        import importlib
        import live
        import review_page
        import review_server
        from TiaAgentStatus import dashboard
        status_main = importlib.import_module('TiaAgentStatus.__main__')
        development, tia = dash.dashboards()
        self.assertEqual((live.ABOUT, review_server.APP, dashboard.APP), (dash.ABOUT, development.app, tia.app))
        self.assertEqual((review_page.PORT, status_main.DASHBOARD_PORT), (development.port, tia.port))
        self.assertIn(review_server.TITLE, development.headings)
        self.assertIn(dashboard.TITLE, tia.headings)


if __name__ == '__main__':
    unittest.main()
