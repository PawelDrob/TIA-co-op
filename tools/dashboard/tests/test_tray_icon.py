"""What the icon does with what Windows tells it, on a stand-in for user32 and shell32: no test shows anything on a desktop."""
import contextlib
import io
import os
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from . import support  # noqa: F401  (puts the dashboard's folder on the path)

import live  # noqa: E402
import tray  # noqa: E402

if os.name == 'nt':
    import tray_icon  # noqa: E402

WINDOW, TASKBAR_CREATED, CHOSE_NOTHING = 77, 49300, 0
WM_LBUTTONUP, WM_MOUSEMOVE, WM_PAINT = 0x0202, 0x0200, 0x000F


class Taskbar:
    """shell32: says yes or no to each call, as scripted, and which icons it holds."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def Shell_NotifyIconW(self, op, data):
        self.calls.append(op)
        return self.answers.pop(0) if self.answers else True


@unittest.skipUnless(os.name == 'nt', 'the icon is Windows only')
class IconTest(unittest.TestCase):
    def setUp(self):
        self.opened, self.stopped = [], []
        self.icon = tray_icon.Icon('A dashboard', 'http://127.0.0.1:1/', Path('a.ico'), 7, self.opened.append, lambda: self.stopped.append(1))
        self.icon.hwnd, self.icon.hicon, self.icon.taskbar_created = WINDOW, 5, TASKBAR_CREATED
        self.icon.user32, self.icon.shell32 = mock.MagicMock(), Taskbar()
        self.user32 = self.icon.user32
        self.user32.TrackPopupMenu.return_value = CHOSE_NOTHING

    def tell(self, event):
        """What the taskbar sends for an event on the icon: the event in the low word, the icon's id in the high word."""
        return self.icon.message(WINDOW, tray_icon.WM_ICON, 0, event | (7 << 16))

    def stands(self):
        self.icon.shown = True


class ClickTest(IconTest):
    def test_one_left_click_opens_the_page_and_no_menu(self):
        self.tell(tray_icon.NIN_SELECT)
        self.assertEqual(self.opened, ['http://127.0.0.1:1/'])
        self.user32.TrackPopupMenu.assert_not_called()

    def test_enter_on_the_icon_does_what_a_left_click_does(self):
        self.tell(tray_icon.NIN_KEYSELECT)
        self.assertEqual(self.opened, ['http://127.0.0.1:1/'])
        self.user32.TrackPopupMenu.assert_not_called()

    def test_a_double_click_opens_one_page(self):
        with mock.patch.object(tray_icon.time, 'monotonic', side_effect=[100.0, 100.3]):
            self.tell(tray_icon.NIN_SELECT)
            self.tell(tray_icon.NIN_SELECT)
        self.assertEqual(len(self.opened), 1)

    def test_a_click_later_opens_the_page_again(self):
        with mock.patch.object(tray_icon.time, 'monotonic', side_effect=[100.0, 102.0]):
            self.tell(tray_icon.NIN_SELECT)
            self.tell(tray_icon.NIN_SELECT)
        self.assertEqual(len(self.opened), 2)

    def test_the_first_click_after_the_start_opens_the_page_however_early(self):
        with mock.patch.object(tray_icon.time, 'monotonic', return_value=0.1):
            self.tell(tray_icon.NIN_SELECT)
        self.assertEqual(len(self.opened), 1)

    def test_a_right_click_opens_the_menu_and_no_page(self):
        self.tell(tray_icon.WM_CONTEXTMENU)
        self.user32.TrackPopupMenu.assert_called_once()
        self.assertEqual(self.opened, [])

    def test_the_mouse_passing_over_or_a_button_coming_up_does_nothing(self):
        for event in (WM_MOUSEMOVE, WM_LBUTTONUP):
            self.tell(event)
        self.user32.TrackPopupMenu.assert_not_called()
        self.assertEqual(self.opened, [])

    def test_a_page_that_cannot_open_does_not_pass_through_windows(self):
        def refuses(url):
            raise OSError('no browser')

        self.icon.open_page = refuses
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.tell(tray_icon.NIN_SELECT), 0)
        self.assertIn('no browser', err.getvalue())


class MenuTest(IconTest):
    def choose(self, row):
        self.user32.TrackPopupMenu.return_value = row
        self.tell(tray_icon.WM_CONTEXTMENU)

    def test_its_rows_say_which_dashboard(self):
        self.tell(tray_icon.WM_CONTEXTMENU)
        rows = [c.args[3] for c in self.user32.AppendMenuW.call_args_list]
        self.assertEqual(rows, ['Open A dashboard', None, 'Stop A dashboard'])

    def test_open_opens_the_page_and_leaves_it_running(self):
        self.choose(tray_icon.OPEN)
        self.assertEqual(self.opened, ['http://127.0.0.1:1/'])
        self.assertEqual(self.stopped, [])

    def test_stop_takes_the_icon_away_and_ends_the_server(self):
        self.stands()
        self.choose(tray_icon.STOP)
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_DELETE])
        self.assertEqual(self.stopped, [1])

    def test_closing_the_menu_with_nothing_chosen_does_nothing(self):
        self.choose(CHOSE_NOTHING)
        self.assertEqual((self.opened, self.stopped), ([], []))

    def test_the_menu_is_taken_down_after_it_closes(self):
        self.tell(tray_icon.WM_CONTEXTMENU)
        self.user32.DestroyMenu.assert_called_once()


class CloseTest(IconTest):
    def close_message(self):
        return self.icon.message(WINDOW, tray_icon.WM_CLOSE, 0, 0)

    def test_a_close_from_outside_ends_the_server_as_stop_does(self):
        """taskkill without /F: with only the window gone, the server would run on with no icon to stop it by."""
        self.stands()
        self.close_message()
        self.assertEqual(self.stopped, [1])
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_DELETE])
        self.user32.DestroyWindow.assert_called_once_with(WINDOW)

    def test_a_close_from_outside_ends_it_also_with_the_icon_not_up_yet(self):
        self.close_message()
        self.assertEqual(self.stopped, [1])

    def test_the_icon_closing_itself_does_not_stop_the_server_again(self):
        self.stands()
        self.icon.close()
        self.user32.PostMessageW.assert_called_once_with(WINDOW, tray_icon.WM_CLOSE, 0, 0)
        self.close_message()
        self.assertEqual(self.stopped, [])
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_DELETE])
        self.user32.DestroyWindow.assert_called_once_with(WINDOW)

    def test_closing_twice_takes_the_icon_away_once(self):
        self.stands()
        self.icon.close()
        self.icon.close()
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_DELETE])

    def test_the_window_going_ends_its_message_loop(self):
        self.icon.message(WINDOW, tray_icon.WM_DESTROY, 0, 0)
        self.user32.PostQuitMessage.assert_called_once_with(0)


class AddTest(IconTest):
    def add_with(self, *answers):
        self.icon.shell32 = Taskbar(*answers)
        return self.icon.add()

    def test_an_add_the_taskbar_takes_stands_and_asks_for_the_events_of_version_4(self):
        self.assertTrue(self.add_with(True, True))
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_ADD, tray_icon.NIM_SETVERSION])
        self.assertTrue(self.icon.shown)

    def test_a_refused_add_that_went_in_all_the_same_is_taken_up_by_modify(self):
        self.assertTrue(self.add_with(False, True, True))
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_ADD, tray_icon.NIM_MODIFY, tray_icon.NIM_SETVERSION])
        self.assertTrue(self.icon.shown)

    def test_refused_twice_it_does_not_stand(self):
        self.assertFalse(self.add_with(False, False))
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_ADD, tray_icon.NIM_MODIFY])
        self.assertFalse(self.icon.shown)

    def test_what_it_gives_the_taskbar_says_which_dashboard(self):
        d = self.icon.described()
        self.assertEqual((d.hWnd, d.uID, d.szTip), (WINDOW, 7, 'A dashboard - http://127.0.0.1:1/'))
        self.assertEqual(d.uCallbackMessage, tray_icon.WM_ICON)

    def test_a_long_tooltip_is_cut_to_what_the_taskbar_holds(self):
        self.icon.name = 'x' * 300
        self.assertEqual(len(self.icon.described().szTip), tray_icon.TIP_CHARS)


class RetryTest(IconTest):
    def timer_tick(self):
        return self.icon.message(WINDOW, tray_icon.WM_TIMER, 1, 0)

    def test_refused_it_asks_again_on_a_timer(self):
        self.icon.shell32 = Taskbar(False, False)
        self.icon.add_or_retry()
        self.user32.SetTimer.assert_called_once_with(WINDOW, 1, tray_icon.RETRY_MS, None)

    def test_taken_at_once_no_timer_runs(self):
        self.icon.add_or_retry()
        self.user32.SetTimer.assert_not_called()

    def test_the_timer_ends_when_the_taskbar_takes_it(self):
        self.timer_tick()
        self.user32.KillTimer.assert_called_once_with(WINDOW, 1)

    def test_the_timer_runs_on_while_the_taskbar_refuses(self):
        self.icon.shell32 = Taskbar(False, False)
        self.timer_tick()
        self.user32.KillTimer.assert_not_called()

    def test_a_restarted_explorer_gets_the_icon_again(self):
        self.icon.message(WINDOW, TASKBAR_CREATED, 0, 0)
        self.assertEqual(self.icon.shell32.calls, [tray_icon.NIM_ADD, tray_icon.NIM_SETVERSION])

    def test_a_restarted_explorer_still_busy_gets_a_timer(self):
        self.icon.shell32 = Taskbar(False, False)
        self.icon.message(WINDOW, TASKBAR_CREATED, 0, 0)
        self.user32.SetTimer.assert_called_once()


class OtherMessagesTest(IconTest):
    def test_what_the_icon_does_not_handle_goes_to_windows(self):
        self.user32.DefWindowProcW.return_value = 42
        self.assertEqual(self.icon.message(WINDOW, WM_PAINT, 1, 2), 42)
        self.user32.DefWindowProcW.assert_called_once_with(WINDOW, WM_PAINT, 1, 2)


class Page(live.Handler):
    def do_GET(self):
        return self.send_text(200, 'the page', 'text/plain; charset=utf-8')


@unittest.skipUnless(os.name == 'nt', 'the icon is Windows only')
class NoDesktopTest(unittest.TestCase):
    def test_the_real_icon_with_no_desktop_leaves_the_server_answering(self):
        """Its own thread takes what Windows refuses: start returns as ever, and the reason goes to the stderr."""
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)
        os.environ.pop(tray.NO_ICON, None)
        server = live.Server(('127.0.0.1', 0), Page)
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        with mock.patch.object(tray_icon, 'win32', side_effect=OSError('no desktop in this session')), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            serving = threading.Thread(target=tray.serve, args=(server, 'A dashboard', url, Path('a.ico'), 7), daemon=True)
            serving.start()
            with urllib.request.urlopen(url, timeout=10) as r:
                self.assertEqual(r.read(), b'the page')
            server.shutdown()
            serving.join(10)
        self.assertFalse(serving.is_alive())
        self.assertIn('no desktop in this session', err.getvalue())


if __name__ == '__main__':
    unittest.main()
