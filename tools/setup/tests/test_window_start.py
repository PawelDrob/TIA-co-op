"""Setup.wsf at the clone's top, and the block viewer's registration as the window does it. Setup.wsf runs under cscript,
which prints what wscript shows in a box: no window opens. The viewer registers under a key of the test's own."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from TiaChangeReports.tests import registry_guard
from TiaChangeReports.viewer import register
from tools.setup.window import __main__ as window_main
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


class SnapOnlyInATestsEnvironment(unittest.TestCase):
    """--snap finishes the first run and --snap-changes presses every button: neither may land on the person's own."""

    def refusal(self, *args, config=None):
        environ = {'CLAUDE_CONFIG_DIR': config} if config else {}
        return window_main.refusal(window_main.parse(list(args)), environ)

    def test_snap_without_its_own_first_run_record_is_refused(self):
        self.assertIn('--first-run', self.refusal('--snap', 'out'))
        self.assertEqual(self.refusal('--snap', 'out', '--first-run', 'f.json'), '')

    def test_changes_need_a_test_key_and_a_claude_config_in_the_temp_folder(self):
        snap = ('--snap', 'out', '--first-run', 'f.json', '--snap-changes')
        temp_config = os.path.join(tempfile.gettempdir(), 'setup-x', 'config')
        self.assertIn('--viewer-key', self.refusal(*snap, config=temp_config))
        self.assertIn('CLAUDE_CONFIG_DIR', self.refusal(*snap, '--viewer-key', 'K'))
        self.assertIn('CLAUDE_CONFIG_DIR', self.refusal(*snap, '--viewer-key', 'K', config=os.path.expanduser(r'~\.claude')))
        self.assertEqual(self.refusal(*snap, '--viewer-key', 'K', config=temp_config), '')


class Viewer(unittest.TestCase):
    def setUp(self):
        root = registry_guard.own_key(self, 'TiaCoopSetupWindowTest')
        self.keys = (root + r'\Classes', root + r'\UserChoice')

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

    def test_register_xml_writes_what_the_command_writes_and_unregister_xml_takes_it_back(self):
        self.assertEqual(viewer.state(*self.keys)['xml']['command'], None)
        failed, text = viewer.register_xml(self.keys[0])
        self.assertFalse(failed, text)
        xml = viewer.state(*self.keys)['xml']
        self.assertEqual((xml['command'], xml['listed'], xml['progid']), (register.command(), True, register.XML_PROGID))
        self.assertEqual(xml['command'], xml['this'])
        self.assertIn('"Open with" lists the block viewer for .xml files', text)
        self.assertEqual(viewer.state(*self.keys)['command'], None)          # nothing of .s7dcl
        failed, text = viewer.unregister_xml(self.keys[0])
        self.assertFalse(failed, text)
        self.assertEqual(viewer.state(*self.keys)['xml']['listed'], False)

    def test_a_choice_in_open_with_comes_with_its_note(self):
        register.write_value(self.keys[1], '', 'Other.Editor', 'ProgId')
        self.assertIn('Other.Editor', viewer.state(*self.keys)['note'])


if __name__ == '__main__':
    unittest.main()
