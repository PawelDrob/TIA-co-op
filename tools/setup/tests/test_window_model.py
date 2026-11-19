"""The setup window's model, without a window: what each page and the menu show for what setup's steps find."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.setup.window import model
from tools.setup.window.dashboards import Status, dashboards
from tools.setup.tests.test_setup import load_setup

setup = load_setup()
Finding = setup.Finding
CLONE = r'C:\Work\clone'
VIEWER = {'command': None, 'default': False, 'chosen': None, 'this': 'x', 'note': '', 'key': 'HKEY_CURRENT_USER\\K', 'progid': 'P'}


def look(*findings, claude=r'C:\bin\claude.exe', **more):
    found = {}
    for f in findings:
        found.setdefault(f.topic, []).append(f)
    return model.Look(clone=CLONE, claude=claude, findings=found, **more)


def row(rows, key):
    return next(r for r in rows if r.key == key)


class Pages(unittest.TestCase):
    def test_each_page_has_a_short_title_and_one_line_that_says_what_it_is(self):
        self.assertEqual(model.PAGES[0][1:], ('Installed', 'Tools used by this repository'))
        self.assertEqual(model.PAGES[1][1], 'Repository settings')
        for key, title, line in model.PAGES:
            self.assertLessEqual(len(title.split()), 2, title)
            self.assertNotIn('.', line, line)

    def test_each_row_says_what_it_is_and_whether_it_is_optional(self):
        rows = [r for key, _, _ in model.PAGES[:3] for r in model.page_rows(look(), key) if r.key in model.ABOUT]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r.about, model.ABOUT[r.key])
        self.assertTrue(row(model.page_rows(look(), 'installed'), 'Claude Code').optional)
        self.assertFalse(row(model.page_rows(look(), 'installed'), 'git').optional)
        self.assertTrue(row(model.page_rows(look(), 'bridge'), 'status line').optional)

    def test_something_missing_says_how_to_get_it_in_its_own_row(self):
        rows = model.page_rows(look(*setup.tia_step(), Finding('missing', "the Windows group 'X': TIA refuses", 'Openness group',
                                                               shown='You are not a member.', person_step='Join the group, then log off and on.')), 'installed')
        group = row(rows, 'Openness group')
        self.assertEqual((group.state, group.text), ('missing', 'You are not a member.\nJoin the group, then log off and on.'))
        tia = row(rows, 'TIA Portal')
        if tia.state == 'missing':
            self.assertIn('Install TIA Portal V20 with the TIA Openness option', tia.text)

    def test_a_change_shows_what_it_changes_and_where_with_its_button(self):
        change = Finding('change', 'MCP server tia: registers it for your Windows user: claude mcp add ... Claude Code keeps it in C:\\home\\.claude.json',
                         'MCP server tia', make=lambda: [])
        server = row(model.page_rows(look(change), 'bridge'), 'MCP server tia')
        self.assertEqual(server.state, 'todo')
        self.assertIn('Not done. Registers it for your Windows user', server.text)
        self.assertIn('.claude.json', server.text)
        self.assertEqual([(a.label, a.kind, a.finding) for a in server.actions], [('Register', 'make', change)])

    def test_a_finding_shows_what_setup_gives_the_window_in_place_of_its_line(self):
        rows = model.page_rows(look(Finding('question', 'Where? Ask the user, then run this again', 'projectsRoot', shown='Not set yet. Where?')), 'bridge')
        folder = row(rows, 'projectsRoot')
        self.assertEqual((folder.state, folder.text), ('todo', 'Not set yet. Where?'))

    def test_setups_own_findings_name_more_than_their_topic_in_the_window(self):
        """Each finding setup prints as only its topic gives the window its words."""
        findings = [*setup.git_step(), *setup.uv_step(), *setup.claude_step(), *setup.tia_step()]
        self.assertEqual([f for f in findings if f.kind == 'ok' and not f.shown], [])

    def test_a_folder_that_is_no_full_path_is_said_without_the_commands_option(self):
        found = setup.projects_root_step('Repos')
        self.assertEqual([f.kind for f in found], ['missing'])
        text = row(model.page_rows(look(*found), 'bridge'), 'projectsRoot').text
        self.assertEqual(text, 'Repos is not a full path on a drive, such as C:\\TIA-Projects.')
        self.assertIn('--projects-root', found[0].text)      # the command's own line keeps it

    def test_a_change_reads_as_a_sentence_without_its_topic(self):
        change = Finding('change', 'status line: adds the TIA row', 'status line', make=lambda: [])
        self.assertEqual(row(model.page_rows(look(change), 'bridge'), 'status line').text, 'Not done. Adds the TIA row')

    def test_without_claude_code_its_rows_say_so_and_lead_to_installed(self):
        lk = look(claude='')
        server = row(model.page_rows(lk, 'bridge'), 'MCP server tia')
        self.assertEqual((server.state, server.text), ('missing', model.NO_CLAUDE))
        self.assertEqual([(a.kind, a.target) for a in server.actions], [('page', 'installed')])
        self.assertNotIn('restart', [r.key for r in model.page_rows(lk, 'bridge')])

    def test_the_bridge_page_says_a_running_session_needs_a_restart_and_holds_the_bridges_settings(self):
        rows = model.page_rows(look(bridge_settings={'projectsRoot': 'C:\\R', 'archivesKept': 3}), 'bridge')
        self.assertIn('claude --continue', row(rows, 'restart').text)
        self.assertEqual([(r.title, r.text) for r in rows if r.title == 'archivesKept'], [('archivesKept', '3')])

    def test_settings_that_cannot_be_read_are_named(self):
        rows = model.page_rows(look(bridge_settings_error='TiaBridge\\settings.json cannot be read'), 'bridge')
        self.assertTrue(any('cannot be read' in r.text for r in rows))

    def test_the_worst_finding_of_a_topic_is_its_state_and_every_text_shows(self):
        rows = model.page_rows(look(Finding('missing', '.claude/settings.json does not enable X', 'tracked settings'),
                                    Finding('missing', '.claude/settings.json sets no LANG', 'tracked settings')), 'repository')
        tracked = row(rows, 'tracked settings')
        self.assertEqual(tracked.state, 'missing')
        self.assertEqual(tracked.text.count('.claude/settings.json'), 2)

    def test_the_tracked_settings_that_setup_says_nothing_of_are_right(self):
        self.assertEqual(row(model.page_rows(look(), 'repository'), 'tracked settings').state, 'ok')

    def test_the_topic_in_front_of_a_text_goes_as_the_title_says_it(self):
        self.assertEqual(model.without_topic('status line: the TIA row, in C:\\s.json', 'status line'), 'the TIA row, in C:\\s.json')
        self.assertEqual(model.without_topic('MCP server tia, for this folder', 'MCP server tia'), 'for this folder')
        self.assertEqual(model.without_topic('git', 'git'), 'git')

    def test_the_last_page_lists_what_a_person_does(self):
        rows = model.page_rows(look(person_steps=['Join the group.', 'Answer Yes.']), 'by-hand')
        self.assertEqual([(r.title, r.text) for r in rows], [('1.', 'Join the group.'), ('2.', 'Answer Yes.')])

    def test_a_page_is_found_by_its_key(self):
        self.assertEqual(model.page_index('installed'), 0)
        self.assertEqual(model.PAGES[model.page_index('bridge')][0], 'bridge')


class Menu(unittest.TestCase):
    def lk(self, *findings, **more):
        return look(*findings, viewer=dict(VIEWER, command='x', default=True), dashboards=[(d, Status('stopped')) for d in dashboards()], **more)

    def test_one_entry_a_page_with_what_it_holds_now(self):
        entries = model.menu_entries(self.lk())
        self.assertEqual([e[0] for e in entries], [k for k, _, _ in model.PAGES[:-1]])
        self.assertEqual(entries[0][1:3], model.PAGES[0][1:])

    def test_a_skipped_step_shows_as_not_done_and_its_page_does_it(self):
        change = Finding('change', 'status line: adds the TIA row', 'status line', make=lambda: [])
        bridge = dict((e[0], e) for e in model.menu_entries(self.lk(change)))['bridge']
        self.assertEqual(bridge[3:], ('todo', '1 not done or missing'))
        status = row(model.page_rows(self.lk(change), 'bridge'), 'status line')
        self.assertEqual([a.finding for a in status.actions], [change])

    def test_something_missing_that_is_needed_marks_its_entry(self):
        missing = Finding('missing', 'git: install it', 'git')
        self.assertEqual(model.menu_entries(self.lk(missing))[0][3], 'missing')

    def test_a_dashboard_that_is_not_running_is_nothing_missing(self):
        entries = dict((e[0], e) for e in model.menu_entries(self.lk()))
        self.assertEqual(entries['dashboards'][3:], ('info', '0 of 2 running'))
        self.assertEqual(entries['viewer'][3:], ('ok', 'All set'))


class Viewer(unittest.TestCase):
    THIS = '"C:\\Work\\clone\\.venv\\Scripts\\pythonw.exe" -X utf8 "C:\\Work\\clone\\TiaChangeReports\\viewer" "%1"'

    def viewer(self, **state):
        return model.viewer_row(look(viewer={**VIEWER, 'this': self.THIS, **state}))

    def test_not_registered_says_what_register_writes_and_where(self):
        r = self.viewer(key='HKEY_CURRENT_USER\\Software\\Test\\Classes', progid='The.Viewer')
        self.assertEqual(r.state, 'todo')
        self.assertIn('The.Viewer and .s7dcl under HKEY_CURRENT_USER\\Software\\Test\\Classes', r.text)
        self.assertIn(self.THIS, r.text)
        self.assertEqual([a.kind for a in r.actions], ['register'])
        self.assertTrue(r.optional)

    def test_registered_for_this_clone_can_be_undone(self):
        r = self.viewer(command=self.THIS, default=True)
        self.assertEqual(r.state, 'ok')
        self.assertEqual([a.kind for a in r.actions], ['unregister'])

    def test_registered_for_another_clone_is_named(self):
        other = self.THIS.replace('clone', 'other')
        r = self.viewer(command=other, default=True)
        self.assertEqual(r.state, 'warning')
        self.assertIn(other, r.text)
        self.assertEqual([a.kind for a in r.actions], ['register', 'unregister'])

    def test_a_choice_in_open_with_is_said(self):
        self.assertIn('as chosen', self.viewer(chosen='Other.Editor', note='Windows opens .s7dcl files with Other.Editor, as chosen').text)


class Dashboards(unittest.TestCase):
    def setUp(self):
        self.development = dashboards()[0]

    def test_running_says_its_address_and_whose_it_is(self):
        r = model.dashboard_row(self.development, Status('running', CLONE), CLONE)
        self.assertEqual(r.state, 'ok')
        self.assertIn('http://127.0.0.1:8770/', r.text)
        self.assertIn('Of this clone.', r.text)
        self.assertEqual([a.kind for a in r.actions], ['open'])
        self.assertIn('Of the clone C:\\other.', model.dashboard_row(self.development, Status('running', 'C:\\other'), CLONE).text)

    def test_not_running_can_be_started_and_says_its_address(self):
        r = model.dashboard_row(self.development, Status('stopped'), CLONE)
        self.assertEqual((r.state, [a.kind for a in r.actions]), ('todo', ['start']))
        self.assertIn('http://127.0.0.1:8770/', r.text)
        self.assertEqual(r.about, self.development.purpose)

    def test_another_program_on_its_port_is_named_and_nothing_starts(self):
        r = model.dashboard_row(self.development, Status('other', text='Port 8770 is taken by x.exe (process 7)'), CLONE)
        self.assertEqual((r.state, r.actions), ('warning', []))
        self.assertIn('x.exe (process 7)', r.text)


class FirstRun(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, 'TIA-co-op', 'setup-window.json')
        self.first_run = model.FirstRun(self.path)

    def test_the_pages_come_until_finish_then_the_menu(self):
        self.assertEqual(model.first_page(self.first_run, CLONE), 0)
        self.first_run.finish(CLONE)
        self.assertEqual(model.first_page(self.first_run, CLONE.lower() + '\\'), None)
        self.assertEqual(model.first_page(self.first_run, r'C:\Work\other'), 0)

    def test_each_clone_finishes_once_in_the_file(self):
        self.first_run.finish(CLONE)
        self.first_run.finish(r'C:\Work\other')
        self.first_run.finish(CLONE)
        self.assertEqual(json.loads(Path(self.path).read_text(encoding='utf-8')), {'finished': [r'C:\Work\other', CLONE]})

    def test_a_file_that_cannot_be_read_counts_as_none_finished(self):
        os.makedirs(os.path.dirname(self.path))
        Path(self.path).write_text('{not json', encoding='utf-8')
        self.assertFalse(self.first_run.done(CLONE))
        self.first_run.finish(CLONE)
        self.assertTrue(self.first_run.done(CLONE))

    def test_it_is_kept_outside_the_clone_per_user(self):
        self.assertTrue(model.first_run_store().startswith(os.environ['LOCALAPPDATA']))


class Outcome(unittest.TestCase):
    def test_a_failure_shows_in_the_tools_own_words(self):
        failed, text = model.outcome([Finding('missing', 'MCP server tia: claude mcp add failed:\n         error: no', 'MCP server tia')])
        self.assertTrue(failed)
        self.assertIn('error: no', text)

    def test_what_was_done_shows_when_nothing_failed(self):
        self.assertEqual(model.outcome([Finding('done', 'status line: the TIA row, in C:\\s.json', 'status line')]),
                         (False, 'status line: the TIA row, in C:\\s.json'))


if __name__ == '__main__':
    unittest.main()
