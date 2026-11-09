"""What the window remembers, and where it finds the runner. Files in a temporary folder; no process is started."""
import os
import tempfile
import unittest

from TiaArchiveCompare.window.runner_process import RunnerCommand
from TiaArchiveCompare.window.settings import Settings, folder_of

RUNNER_MAIN = 'TiaArchiveCompare\\runner\\__main__.py'
VENV_PYTHON = '.venv\\Scripts\\python.exe'
WINDOW_DIR = 'TiaArchiveCompare\\window'


class SettingsFile(unittest.TestCase):
    def test_round_trip_missing_file_and_broken_file(self):
        folder = tempfile.TemporaryDirectory(prefix='tac-window-tests-')
        self.addCleanup(folder.cleanup)
        root = folder.name
        path = os.path.join(root, 'sub', 'window.json')
        s = Settings.load(path)
        self.assertIsNone(s.before_folder)
        s.before_folder, s.after_folder = 'D:\\Archives\\old', 'D:\\Archives\\new \u00e4'
        s.save(path)
        t = Settings.load(path)
        self.assertEqual('D:\\Archives\\old', t.before_folder)
        self.assertEqual('D:\\Archives\\new \u00e4', t.after_folder)
        with open(path, 'w') as f:
            f.write('{broken')
        self.assertIsNone(Settings.load(path).before_folder)

    def test_the_folder_a_picker_opens_next(self):
        self.assertEqual('D:\\Archives', folder_of('D:\\Archives\\a.zap20', False))
        self.assertEqual('D:\\Exports\\old', folder_of('D:\\Exports\\old', True))
        self.assertIsNone(folder_of('', False))


class WhereTheRunnerIs(unittest.TestCase):
    def tree(self, *files):
        folder = tempfile.TemporaryDirectory(prefix='tia-compare-')
        self.addCleanup(folder.cleanup)
        root = folder.name
        for name in files:
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w').close()
        os.makedirs(os.path.join(root, WINDOW_DIR), exist_ok=True)
        return root

    def test_the_venv_of_the_folder_that_holds_the_package(self):
        root = self.tree(RUNNER_MAIN, VENV_PYTHON)
        c = RunnerCommand.resolve(None, None, os.path.join(root, WINDOW_DIR))
        self.assertEqual(os.path.join(root, VENV_PYTHON), c.exe)
        self.assertEqual(root, c.work_dir)
        self.assertEqual(['-X', 'utf8', '-m', 'TiaArchiveCompare.runner', 'run'], c.prefix)

    def test_a_python_beside_the_window_comes_first(self):
        root = self.tree(RUNNER_MAIN, VENV_PYTHON, WINDOW_DIR + '\\python\\python.exe')
        window = os.path.join(root, WINDOW_DIR)
        self.assertEqual(os.path.join(window, 'python\\python.exe'), RunnerCommand.resolve(None, None, window).exe)

    def test_a_missing_venv_says_run_uv_sync_never_python_from_path(self):
        root = self.tree(RUNNER_MAIN)
        c = RunnerCommand.resolve(None, None, os.path.join(root, WINDOW_DIR))
        self.assertEqual(os.path.join(root, VENV_PYTHON), c.exe)
        self.assertTrue(c.start_failure('gone').endswith('gone Run uv sync in ' + root + ' once.'))

    def test_an_explicit_runner_is_kept_and_names_no_setup_step(self):
        root = self.tree(RUNNER_MAIN)
        c = RunnerCommand.resolve('C:\\x\\py.exe', ['stub.py', 'run'], os.path.join(root, WINDOW_DIR))
        self.assertEqual('C:\\x\\py.exe', c.exe)
        self.assertEqual('Could not start the runner (C:\\x\\py.exe): gone', c.start_failure('gone'))


if __name__ == '__main__':
    unittest.main()
