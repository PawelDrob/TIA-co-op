"""What check_no_console.py judges, held to made-up process tables: the chain a .cmd of the old start.cmd's shape leaves
above the window must read as a console, also on the road through explorer.exe, which cannot run in the hook. Nothing
is started and no process is judged but those of the tables."""
import unittest

from TiaArchiveCompare.window.tests import check_no_console as check
from TiaArchiveCompare.window.tests.check_no_console import Seen, WindowEvent

SHELL, OTHER = 100, 150
CMD, CONHOST, LAUNCHER, WINDOW = 200, 201, 300, 301

ALREADY_THERE = {SHELL: Seen(1, 'explorer.exe'), OTHER: Seen(SHELL, 'cmd.exe')}
BEHIND_A_CMD = {CMD: Seen(SHELL, 'cmd.exe'), CONHOST: Seen(CMD, 'conhost.exe'), LAUNCHER: Seen(CMD, 'pythonw.exe'),
                WINDOW: Seen(LAUNCHER, 'pythonw.exe')}
BY_SHORTCUT = {LAUNCHER: Seen(SHELL, 'pythonw.exe'), WINDOW: Seen(LAUNCHER, 'pythonw.exe')}


def findings_from_the_window(new, events=()):
    measure = check.Measure()
    measure.processes.before = dict(ALREADY_THERE)
    measure.processes.seen = {**ALREADY_THERE, **new}
    measure.windows.events = list(events)
    return measure.findings([measure.processes.first_started_above(WINDOW)])


class ProcessesAboveTheWindow(unittest.TestCase):
    def test_a_cmd_that_has_ended_is_seen_with_its_conhost(self):
        found = findings_from_the_window(BEHIND_A_CMD)
        self.assertEqual(['cmd.exe', 'conhost.exe'], found['console_programs'])
        self.assertEqual(['cmd.exe', 'conhost.exe', 'pythonw.exe', 'pythonw.exe'], found['tree'])
        self.assertFalse(check.no_console_seen(found))

    def test_its_console_window_counts_as_its_own(self):
        console = WindowEvent('created', 'ConsoleWindowClass', CMD, None)
        found = findings_from_the_window(BEHIND_A_CMD, [console])
        self.assertEqual([console], found['console_windows_here'])
        self.assertEqual([], found['console_windows_elsewhere'])

    def test_a_cmd_no_poll_saw_still_finds_its_conhost(self):
        unseen = {pid: seen for pid, seen in BEHIND_A_CMD.items() if pid != CMD}
        found = findings_from_the_window(unseen)
        self.assertEqual(['conhost.exe'], found['console_programs'])
        self.assertFalse(check.no_console_seen(found))

    def test_a_shortcut_shows_none_and_stops_at_what_was_there(self):
        found = findings_from_the_window(BY_SHORTCUT)
        self.assertEqual(['pythonw.exe', 'pythonw.exe'], found['tree'])
        self.assertTrue(check.no_console_seen(found))

    def test_a_console_of_another_is_not_taken_for_its_own(self):
        other = WindowEvent('created', 'ConsoleWindowClass', OTHER, None)
        found = findings_from_the_window(BY_SHORTCUT, [other])
        self.assertEqual([], found['console_windows_here'])
        self.assertTrue(check.no_console_seen(found))

    def test_a_number_used_again_does_not_go_round(self):
        looped = {LAUNCHER: Seen(WINDOW, 'pythonw.exe'), WINDOW: Seen(LAUNCHER, 'pythonw.exe')}
        self.assertEqual(['pythonw.exe', 'pythonw.exe'], findings_from_the_window(looped)['tree'])


if __name__ == '__main__':
    unittest.main()
