"""The shortcut that starts the window. Real shortcut files in a temporary folder, read back; nothing is started, and no
test touches the Desktop. Whether it starts the window with no console: check_no_console.py."""
import os
import shutil
import subprocess
import tempfile
import unittest

from TiaArchiveCompare.window import shortcut

READ_SCRIPT = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
               "$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); "
               "$l.TargetPath; $l.Arguments; $l.WorkingDirectory")


def read_back(link):
    done = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', READ_SCRIPT], capture_output=True,
                          encoding='utf-8', env=dict(os.environ, LINK=link), creationflags=subprocess.CREATE_NO_WINDOW)
    return done.stdout.splitlines()


class Case(unittest.TestCase):
    def folder_with(self, *files):
        root = tempfile.mkdtemp(prefix='tia-compare ä-')
        self.addCleanup(shutil.rmtree, root, True)
        for name in files:
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w').close()
        return root


class WhichPython(Case):
    def test_the_venv(self):
        root = self.folder_with('.venv\\Scripts\\pythonw.exe')
        self.assertEqual(os.path.join(root, '.venv\\Scripts\\pythonw.exe'), shortcut.window_python(root))

    def test_one_placed_beside_the_window_comes_first(self):
        root = self.folder_with('.venv\\Scripts\\pythonw.exe', 'TiaArchiveCompare\\window\\python\\pythonw.exe')
        self.assertEqual(os.path.join(root, 'TiaArchiveCompare\\window\\python\\pythonw.exe'), shortcut.window_python(root))

    def test_none_names_uv_sync(self):
        root = self.folder_with('.venv\\Scripts\\python.exe')
        with self.assertRaisesRegex(shortcut.ShortcutError, 'Run uv sync in '):
            shortcut.window_python(root)


class TheFile(Case):
    def test_starts_the_window_from_the_clone_whatever_folder_it_stands_in(self):
        # The root is given by another spelling of its folder, upper case here, a short (8.3) temp path on a CI runner:
        # the shell writes the target by the folder's own name, so paths are compared resolved.
        root, folder = self.folder_with('.venv\\Scripts\\pythonw.exe'), self.folder_with()
        link = shortcut.make(folder, root.upper())
        self.assertEqual(os.path.join(folder, shortcut.NAME), link)
        target, arguments, working = read_back(link)
        resolved = os.path.realpath(root)
        self.assertEqual([os.path.join(resolved, '.venv\\Scripts\\pythonw.exe'), '-X utf8 -m TiaArchiveCompare.window', resolved],
                         [os.path.realpath(target), arguments, os.path.realpath(working)])

    def test_in_a_download_it_starts_the_launcher_at_its_top(self):
        root, folder = self.folder_with('TIA Archive Compare.exe', 'TiaArchiveCompare\\window\\python\\pythonw.exe'), self.folder_with()
        target, arguments, working = read_back(shortcut.make(folder, root))
        resolved = os.path.realpath(root)
        self.assertEqual([os.path.join(resolved, 'TIA Archive Compare.exe'), '', resolved],
                         [os.path.realpath(target), arguments, os.path.realpath(working)])

    def test_made_again_it_stands_on_the_new_paths(self):
        first, second, folder = self.folder_with('.venv\\Scripts\\pythonw.exe'), self.folder_with('.venv\\Scripts\\pythonw.exe'), self.folder_with()
        shortcut.make(folder, first)
        link = shortcut.make(folder, second)
        self.assertEqual(second, read_back(link)[2])
        self.assertEqual([shortcut.NAME], os.listdir(folder))

    def test_a_folder_that_is_not_there_is_said_and_nothing_made(self):
        root = self.folder_with('.venv\\Scripts\\pythonw.exe')
        gone = os.path.join(root, 'gone')
        with self.assertRaisesRegex(shortcut.ShortcutError, 'There is no folder'):
            shortcut.make(gone, root)
        self.assertFalse(os.path.exists(gone))
        self.assertEqual(['.venv'], os.listdir(root))


if __name__ == '__main__':
    unittest.main()
