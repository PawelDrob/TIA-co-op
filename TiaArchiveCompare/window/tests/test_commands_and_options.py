"""What the window sends the runner: its commands on stdin, its arguments, and the check of the inputs before a run; and
how the window's start ends."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from TiaArchiveCompare.window import __main__ as window_main
from TiaArchiveCompare.window.model import (RunOptions, answer_command, cancel_command, default_title, runner_arguments,
                                            skip_command)


class Commands(unittest.TestCase):
    def test_cancel_command(self):
        self.assertEqual('{"t":"cancel"}', cancel_command())

    def test_answer_commands(self):
        self.assertEqual('{"t":"answer","id":"a1","password":"p\\"w\\\\\u00e4"}', answer_command('a1', None, 'p"w\\\u00e4'))
        self.assertEqual('{"t":"answer","id":"a2","user":"maint","password":"x"}', answer_command('a2', 'maint', 'x'))
        self.assertEqual('{"t":"answer","id":"a3","user":"maint","password":"x","umc_global":true}',
                         answer_command('a3', 'maint', 'x', True))
        self.assertEqual('{"t":"answer","id":"a3","skip":true}', skip_command('a3'))


class Start(unittest.TestCase):
    """How the window's start ends; the mock stands in for the box a person would see."""

    def start(self, *argv):
        with (mock.patch.object(window_main, 'show_failure', return_value=1) as box, redirect_stdout(io.StringIO()),
              redirect_stderr(io.StringIO())):
            return window_main.start(list(argv)), box.call_count

    def test_help_is_no_failure(self):
        self.assertEqual((0, 0), self.start('--help'))

    def test_a_wrong_argument_shows_the_box(self):
        self.assertEqual((1, 1), self.start('--cancel-at', 'soon'))
        self.assertEqual((1, 1), self.start('--no-such-option'))


class DroppedOnTheShortcut(unittest.TestCase):
    """Windows passes a file dropped on the shortcut or the launcher as an argument."""

    def inputs(self, *argv):
        return window_main.inputs(window_main.parse(list(argv)))

    def test_one_file_stands_in_before(self):
        self.assertEqual(('D:\\Arch\\Line 7 ä.zap20', ''), self.inputs('D:\\Arch\\Line 7 ä.zap20'))

    def test_two_files_stand_in_before_and_after(self):
        self.assertEqual(('D:\\a.zap20', 'D:\\b.zap20'), self.inputs('D:\\a.zap20', 'D:\\b.zap20', '--hmi'))

    def test_the_options_come_first(self):
        self.assertEqual(('D:\\x.zap20', 'D:\\a.zap20'), self.inputs('D:\\a.zap20', '--before', 'D:\\x.zap20'))
        self.assertEqual(('', ''), self.inputs())


class Arguments(unittest.TestCase):
    def test_runner_arguments(self):
        o = RunOptions(before='D:\\Arch\\Line 7 old.zap20', after='D:\\Arch\\new.zap20', title='Line 7: before vs after')
        self.assertEqual(['-m', 'p', 'run', '--before', 'D:\\Arch\\Line 7 old.zap20', '--after', 'D:\\Arch\\new.zap20',
                          '--title', 'Line 7: before vs after'],
                         runner_arguments(['-m', 'p', 'run'], o))
        o.title, o.compile, o.safety, o.hmi, o.no_cache = '', True, True, True, True
        self.assertEqual(['-m', 'p', 'run', '--before', 'D:\\Arch\\Line 7 old.zap20', '--after', 'D:\\Arch\\new.zap20',
                          '--compile', '--safety', '--hmi', '--no-cache'],
                         runner_arguments(['-m', 'p', 'run'], o))

    def test_safety_only_with_compile(self):
        o = RunOptions(before='a', after='b', safety=True)
        self.assertEqual(['run', '--before', 'a', '--after', 'b'], runner_arguments(['run'], o))

    def test_default_title(self):
        self.assertEqual('Line7_2026-09-01 vs Line7_2026-10-28',
                         default_title('D:\\A\\Line7_2026-09-01.zap20', 'D:\\A\\Line7_2026-10-28.zap20'))
        self.assertEqual('export_old vs Line7', default_title('D:\\A\\export_old\\', 'D:\\B\\Line7\\Line7.ap20'))


class Validate(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='tac-window-tests-')
        self.addCleanup(folder.cleanup)
        self.dir = folder.name
        self.a, self.b = os.path.join(self.dir, 'a.zap20'), os.path.join(self.dir, 'b.zap20')
        for path in (self.a, self.b):
            with open(path, 'w') as f:
                f.write('x')

    def test_a_missing_input_is_named(self):
        self.assertEqual('Choose the before archive.', RunOptions(before='', after=self.b).validate())
        missing = os.path.join(self.dir, 'c.zap20')
        self.assertEqual('The after archive does not exist: ' + missing, RunOptions(before=self.a, after=missing).validate())

    def test_the_same_input_twice_is_refused(self):
        self.assertEqual('Before and after are the same.', RunOptions(before=self.a, after=self.a.upper()).validate())

    def test_a_file_and_a_folder_with_blanks_and_quotes_pass(self):
        self.assertIsNone(RunOptions(before=self.a, after=self.dir).validate())
        self.assertIsNone(RunOptions(before=' ' + self.a + ' ', after='"' + self.b + '"').validate())


if __name__ == '__main__':
    unittest.main()
