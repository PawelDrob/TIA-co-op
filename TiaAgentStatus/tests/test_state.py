"""python -m unittest discover -s TiaAgentStatus/tests -t .   (from the repo root)"""
import json
import os
import unittest

from TiaAgentStatus import state as st
from TiaAgentStatus.tests.fakes import tempdir


class ProjectsRoot(unittest.TestCase):
    def setUp(self):
        self.settings = os.path.join(tempdir(self), 'settings.json')
        self.default = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects')

    def test_the_bridge_default_without_a_setting(self):
        self.assertEqual(self.default, st.projects_root(self.settings))         # no file
        for raw in (b'not json', b'[]', b'{"tiaRoot": "D:\\\\TIA"}'):
            with open(self.settings, 'wb') as f:
                f.write(raw)
            self.assertEqual(self.default, st.projects_root(self.settings), raw)

    def test_the_folder_as_the_bridge_reads_it(self):
        """Windows PowerShell 5.1 goes by the byte order mark, else ANSI: `>` writes UTF-16, Notepad's "ANSI" no mark,
        and a text editor's UTF-8 without a mark is read as ANSI too, garbled: the bridge's folder all the same."""
        folder = 'D:\\M\u00fcller\\Projects'
        text = json.dumps({'projectsRoot': folder}, ensure_ascii=False)
        garbled = folder.encode('utf-8').decode('mbcs')
        for raw, reads in ((text.encode('utf-8-sig'), folder), (text.encode('utf-16'), folder),
                           (text.encode('mbcs'), folder), (text.encode('utf-8'), garbled)):
            with open(self.settings, 'wb') as f:
                f.write(raw)
            self.assertEqual(reads, st.projects_root(self.settings), raw)


class BridgeSettings(unittest.TestCase):
    """What a report run passes on to its bridge, with its own projectsRoot (reportrun.McpBridge)."""

    def setUp(self):
        self.settings = os.path.join(tempdir(self), 'settings.json')

    def test_a_file_powershell_wrote_keeps_its_settings(self):
        with open(self.settings, 'w', encoding='utf-16') as f:                  # `>` in Windows PowerShell
            json.dump({'tiaRoot': 'D:\\Portal V20', 'archivesKept': 3}, f)
        self.assertEqual({'tiaRoot': 'D:\\Portal V20', 'archivesKept': 3}, st.bridge_settings(self.settings))

    def test_none_without_a_file_or_an_object(self):
        self.assertEqual({}, st.bridge_settings(self.settings))
        for raw in (b'not json', b'[]'):
            with open(self.settings, 'wb') as f:
                f.write(raw)
            self.assertEqual({}, st.bridge_settings(self.settings), raw)


if __name__ == '__main__':
    unittest.main()
