"""Setup.wsf at the clone's top, and the block viewer's registration as the window does it. Setup.wsf runs under cscript,
which prints what wscript shows in a box: no window opens. The viewer registers under a key of the test's own."""
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from TiaChangeReports.viewer import register
from tools.setup.window import viewer

REPO = Path(__file__).resolve().parents[3]
SYSTEM = os.path.join(os.environ['SystemRoot'], 'System32')


class SetupFile(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='setup-wsf-')
        self.addCleanup(folder.cleanup)
        self.clone = Path(folder.name) / 'clone'
        self.clone.mkdir()
        shutil.copy(REPO / 'Setup.wsf', self.clone)
        self.home = Path(folder.name) / 'home'
        self.home.mkdir()

    def run_it(self):
        env = {'PATH': SYSTEM, 'SystemRoot': os.environ['SystemRoot'], 'USERPROFILE': str(self.home), 'TEMP': os.environ['TEMP']}
        done = subprocess.run(['cscript.exe', '//nologo', str(self.clone / 'Setup.wsf')], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        return done.returncode, done.stdout + done.stderr

    def test_without_uv_it_says_so_and_how_to_get_it_and_does_nothing(self):
        code, out = self.run_it()
        self.assertEqual(code, 1, out)
        self.assertIn('uv is missing', out)
        self.assertIn('https://docs.astral.sh/uv/getting-started/installation/', out)
        self.assertEqual(sorted(p.name for p in self.clone.iterdir()), ['Setup.wsf'])

    def test_it_is_at_the_top_of_the_clone(self):
        self.assertTrue((REPO / 'Setup.wsf').is_file())


class Viewer(unittest.TestCase):
    def setUp(self):
        root = r'Software\TiaCoopSetupWindowTest-%s' % uuid.uuid4().hex
        self.keys = (root + r'\Classes', root + r'\UserChoice')
        self.addCleanup(register.delete_tree, 'Software', root.split('\\', 1)[1])

    def test_register_writes_what_the_command_writes_and_unregister_takes_it_back(self):
        self.assertEqual(viewer.state(*self.keys)['command'], None)
        failed, text = viewer.register(*self.keys)
        self.assertFalse(failed, text)
        state = viewer.state(*self.keys)
        self.assertEqual(state['command'], register.command())
        self.assertEqual(state['command'], state['this'])
        self.assertTrue(state['default'])
        self.assertIn('.s7dcl files open in the block viewer', text)
        failed, text = viewer.unregister(self.keys[0])
        self.assertFalse(failed, text)
        self.assertEqual(viewer.state(*self.keys)['command'], None)

    def test_a_choice_in_open_with_comes_with_its_note(self):
        register.write_value(self.keys[1], '', 'Other.Editor', 'ProgId')
        self.assertIn('Other.Editor', viewer.state(*self.keys)['note'])


if __name__ == '__main__':
    unittest.main()
