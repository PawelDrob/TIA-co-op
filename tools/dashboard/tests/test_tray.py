"""What a dashboard does around its icon, on a real server and a stand-in icon: no test shows anything on a desktop."""
import contextlib
import http.client
import io
import os
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from .support import TOOLS

import live  # noqa: E402
import review_page  # noqa: E402
import tray  # noqa: E402


class Page(live.Handler):
    def do_GET(self):
        if self.path == '/events':
            return self.stream(lambda: {'n': 1})
        return self.send_text(200, 'the page', 'text/plain; charset=utf-8')


class StandInIcon:
    """Records what serve does with an icon, and lets a test press its menu."""
    made = []

    def __init__(self, name, url, icon_file, icon_id, open_page, stop):
        self.name, self.url, self.icon_file, self.icon_id = name, url, icon_file, icon_id
        self.open_page, self.stop = open_page, stop
        self.started = threading.Event()
        self.closed = 0
        StandInIcon.made.append(self)

    def start(self):
        self.started.set()

    def close(self):
        self.closed += 1


class CannotBeMade(StandInIcon):
    def __init__(self, *args):
        raise OSError('the icon could not be made')


class Serving:
    """tray.serve on its own thread, as the main thread of a dashboard runs it."""

    def __init__(self, test, make_icon):
        StandInIcon.made = []
        self.server = live.Server(('127.0.0.1', 0), Page)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'
        self.thread = threading.Thread(target=tray.serve, daemon=True, args=(self.server, 'A dashboard', self.url, Path('a.ico'), 7),
                                       kwargs={'make_icon': make_icon})
        self.thread.start()
        test.addCleanup(self.end)

    def end(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(10)

    def answers(self):
        with urllib.request.urlopen(self.url, timeout=10) as r:
            return r.read().decode('utf-8')


class ServeTest(unittest.TestCase):
    def setUp(self):
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)
        os.environ.pop(tray.NO_ICON, None)

    def test_the_page_answers_with_the_icon_up_and_the_icon_says_which_dashboard(self):
        s = Serving(self, StandInIcon)
        self.assertEqual(s.answers(), 'the page')
        icon = StandInIcon.made[0]
        self.assertTrue(icon.started.wait(10))
        self.assertEqual((icon.name, icon.url, icon.icon_id), ('A dashboard', s.url, 7))

    def test_stop_ends_the_server_and_takes_the_icon_away(self):
        s = Serving(self, StandInIcon)
        s.answers()
        StandInIcon.made[0].stop()
        s.thread.join(10)
        self.assertFalse(s.thread.is_alive(), 'serve did not end')
        self.assertEqual(StandInIcon.made[0].closed, 1)
        with self.assertRaises(OSError):
            s.answers()

    def test_stop_ends_it_with_a_page_holding_its_live_connection(self):
        s = Serving(self, StandInIcon)
        held = http.client.HTTPConnection('127.0.0.1', s.server.server_address[1], timeout=10)
        self.addCleanup(held.close)
        held.request('GET', '/events')
        reply = held.getresponse()
        self.assertIn(b'event: update', reply.readline())
        StandInIcon.made[0].stop()
        s.thread.join(10)
        self.assertFalse(s.thread.is_alive(), 'an open tab kept the dashboard running')

    def test_an_icon_that_cannot_be_made_leaves_it_answering(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = Serving(self, CannotBeMade)
            self.assertEqual(s.answers(), 'the page')
        self.assertIn('the icon could not be made', err.getvalue())

    def test_the_icon_opens_the_page_in_the_default_browser_of_windows(self):
        """One road for both dashboards, with no browser named: DASHBOARD_BROWSER is for --open of review_page.py."""
        s = Serving(self, StandInIcon)
        s.answers()
        self.assertIs(StandInIcon.made[0].open_page, tray.webbrowser.open)

    def test_the_off_switch_makes_no_icon(self):
        os.environ[tray.NO_ICON] = '1'
        s = Serving(self, StandInIcon)
        self.assertEqual(s.answers(), 'the page')
        self.assertEqual(StandInIcon.made, [])

    def test_ctrl_c_takes_the_icon_away(self):
        class Interrupted:
            closed = False

            def serve_forever(self):
                raise KeyboardInterrupt

            def shutdown(self):
                pass

            def server_close(self):
                Interrupted.closed = True

        StandInIcon.made = []
        tray.serve(Interrupted(), 'A dashboard', 'http://x/', Path('a.ico'), 7, make_icon=StandInIcon)
        self.assertEqual(StandInIcon.made[0].closed, 1)
        self.assertTrue(Interrupted.closed)


class GuardedTest(unittest.TestCase):
    """pythonw has no stderr: what stops a dashboard at its start must reach the person some other way."""

    def run_guarded(self, main):
        with mock.patch.object(tray, 'show_box') as box:
            try:
                code = tray.guarded('A dashboard', main)
            except SystemExit as e:
                code = ('exit', e.code)
        return code, box

    def test_with_no_console_a_refusal_comes_up_in_a_box(self):
        def refused():
            sys.exit('Port 1 is taken')

        with mock.patch.object(sys, 'stderr', None):
            code, box = self.run_guarded(refused)
        self.assertEqual(code, 1)
        box.assert_called_once_with('A dashboard', 'Port 1 is taken')

    def test_with_no_console_a_wrong_option_says_how_to_read_why(self):
        def wrong_option():
            sys.exit(2)     # what argparse does, after writing to the stderr pythonw does not have

        with mock.patch.object(sys, 'stderr', None):
            code, box = self.run_guarded(wrong_option)
        self.assertEqual(code, 1)
        self.assertIn('python.exe', box.call_args[0][1])

    def test_with_no_console_a_fault_comes_up_in_a_box(self):
        def fault():
            raise ValueError('it broke')

        with mock.patch.object(sys, 'stderr', None):
            code, box = self.run_guarded(fault)
        self.assertEqual(code, 1)
        self.assertIn('it broke', box.call_args[0][1])

    def test_with_no_console_an_ordinary_end_shows_nothing(self):
        with mock.patch.object(sys, 'stderr', None):
            code, box = self.run_guarded(lambda: 0)
        self.assertEqual(code, 0)
        box.assert_not_called()

    def test_with_a_stderr_nothing_is_shown(self):
        """A session starts the server with its stderr on the null device: losing a race for the port opens no box."""
        def refused():
            sys.exit('Port 1 is taken')

        code, box = self.run_guarded(refused)
        self.assertEqual(code, ('exit', 'Port 1 is taken'))
        box.assert_not_called()


class NoConsoleTest(unittest.TestCase):
    def test_a_session_starts_the_server_with_no_console_window(self):
        """Measured: the python.exe of a venv started DETACHED_PROCESS hands a real, visible console to its child."""
        with mock.patch.object(review_page.subprocess, 'Popen') as started, mock.patch.object(review_page, 'server_running', return_value=True):
            self.assertTrue(review_page.start_server(Path('scratch'), 1))
        flags = started.call_args.kwargs['creationflags']
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        self.assertFalse(flags & subprocess.DETACHED_PROCESS)

    def test_a_session_starts_the_program_a_person_starts(self):
        """Measured: Windows keeps "show on the taskbar" per program and id, with python.exe and pythonw.exe as two entries of one icon."""
        with mock.patch.object(review_page.subprocess, 'Popen') as started, mock.patch.object(review_page, 'server_running', return_value=True):
            review_page.start_server(Path('scratch'), 1)
        self.assertEqual(Path(started.call_args.args[0][0]).name.lower(), 'pythonw.exe')


class DefaultBrowserTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'the Windows default')
    def test_with_nothing_set_python_goes_to_the_windows_default(self):
        """Asks which browser it would take, and starts none. BROWSER is python's own override: nothing here sets it outside tray_check.py."""
        env = {k: v for k, v in os.environ.items() if k != 'BROWSER'}
        run = subprocess.run([sys.executable, '-X', 'utf8', '-c', 'import webbrowser; print(type(webbrowser.get()).__name__)'], capture_output=True,
                             text=True, timeout=30, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(run.stdout.strip(), 'WindowsDefault', run.stderr)


class OffWindowsTest(unittest.TestCase):
    def test_a_machine_with_no_win32_can_still_import_it(self):
        """ctypes has neither name off Windows, where the dashboards have branches of their own in live.py and review_page.py."""
        code = ('import ctypes, sys; del ctypes.WINFUNCTYPE, ctypes.WinDLL; sys.path.insert(0, sys.argv[1]); import tray; print(tray.NO_ICON)')
        run = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(TOOLS)], capture_output=True, text=True, timeout=30,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual((run.returncode, run.stdout.strip()), (0, tray.NO_ICON), run.stderr)


class IconFilesTest(unittest.TestCase):
    def test_each_dashboard_has_its_own_icon_with_the_sizes_a_taskbar_asks_for(self):
        files = [tray.DEVELOPMENT_ICON, tray.TIA_ICON]
        self.assertNotEqual(files[0].read_bytes(), files[1].read_bytes())
        for f in files:
            data = f.read_bytes()
            self.assertEqual(data[:4], b'\0\0\1\0', f.name)
            sizes = {data[6 + 16 * i] or 256 for i in range(int.from_bytes(data[4:6], 'little'))}
            self.assertLessEqual({16, 20, 24, 32, 40, 48}, sizes, f.name)

    def test_the_two_dashboards_have_their_own_place_in_the_taskbar_settings(self):
        """Windows keeps "show on the taskbar" per program and id, and both run on the same pythonw.exe."""
        self.assertNotEqual(tray.DEVELOPMENT_ID, tray.TIA_ID)


if __name__ == '__main__':
    unittest.main()
