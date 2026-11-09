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
        with open(self.settings, 'wb') as f:
            f.write(b'{"tiaRoot": "D:\\\\TIA"}')
        self.assertEqual(self.default, st.projects_root(self.settings))
        for raw in (b'', b' \r\n', b'[]', b'null', b'5'):                       # the bridge runs on its defaults with these
            with open(self.settings, 'wb') as f:
                f.write(raw)
            self.assertEqual(self.default, st.projects_root(self.settings), raw)

    def test_the_name_in_any_case_as_the_bridge_takes_it(self):
        for name in ('ProjectsRoot', 'PROJECTSROOT', 'projectsroot'):
            with open(self.settings, 'w') as f:
                json.dump({name: 'D:/Projects'}, f)
            self.assertEqual('D:/Projects', st.projects_root(self.settings), name)

    def test_a_file_it_cannot_read_is_said_not_taken_for_none(self):
        """The bridge reads the first with its folder and refuses the others: the default folder is right for none."""
        for raw, why in ((b"{'projectsRoot': 'D:/Projects'}", 'not strict JSON'),
                         (b'{"projectsRoot": "D:/a", "ProjectsRoot": "D:/b"}', 'projectsRoot and ProjectsRoot'),
                         (b'{"x": [{"a": 1, "A": 2}]}', 'a and A'), (b'{"": 1}', 'an empty name')):
            with open(self.settings, 'wb') as f:
                f.write(raw)
            with self.assertRaises(st.SettingsUnreadable, msg=raw) as caught:
                st.projects_root(self.settings)
            self.assertIn(why, str(caught.exception))
            self.assertIn(self.settings, str(caught.exception))
        os.remove(self.settings)
        os.mkdir(self.settings)                                                 # there, and not a file to open
        with self.assertRaises(st.SettingsUnreadable) as caught:
            st.projects_root(self.settings)
        self.assertIn(f'{self.settings} cannot be read', str(caught.exception))

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

    def test_none_without_a_file(self):
        self.assertEqual({}, st.bridge_settings(self.settings))

    def test_a_name_is_found_as_the_file_spells_it(self):
        settings = {'TIAROOT': 'D:/Portal V20'}
        self.assertEqual('TIAROOT', st.spelled(settings, 'tiaRoot'))
        self.assertEqual('projectsRoot', st.spelled(settings, 'projectsRoot'))


class CommandLine(unittest.TestCase):
    """The commands that take the folder from the bridge's settings when no --root names it."""

    def test_settings_they_cannot_read_stop_them_in_words(self):
        from unittest import mock

        from TiaAgentStatus import __main__ as cli
        unreadable = st.SettingsUnreadable('settings.json is not strict JSON (x)')
        for command in (['watch', '--once'], ['dashboard'], ['report-run', '--repo', 'zzLine']):
            with mock.patch.object(st, 'bridge_settings', side_effect=unreadable), self.assertRaises(SystemExit) as stopped:
                cli.main(command)
            self.assertEqual('settings.json is not strict JSON (x). Fix the file, or name the folder with --root.',
                             stopped.exception.code, command)


if __name__ == '__main__':
    unittest.main()
