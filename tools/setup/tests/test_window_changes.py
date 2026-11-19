"""The window changes what setup.ps1 changes for the same answers: its buttons call the steps of setup.py, in a temp clone
with a temp Claude config and fake claude and whoami, as the setup tests run the command."""
import importlib.util
import json
import os
import subprocess
import unittest
from unittest import mock

from tools.setup.tests.test_setup import GIT_ENV, SetupCase, git
from tools.setup.window import model
from tools.setup.window.dashboards import Status, dashboards

ANSWER = r'C:\Work\Repos'


class TheWindowsChanges(SetupCase):
    def setup_module(self):
        """setup.py of the temp clone, in this process, with the environment the command gets."""
        env = {**self.env(), 'SystemRoot': str(self.system_root)}
        self.patch = mock.patch.dict(os.environ, env, clear=True)
        self.patch.start()
        self.addCleanup(self.leave)
        spec = importlib.util.spec_from_file_location('first_setup_of_the_clone', self.clone / 'tools' / 'setup' / 'setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def leave(self):
        """Back to this process's own environment, once."""
        if self.patch:
            self.patch.stop()
            self.patch = None

    def read(self, setup, folder=None):
        return model.read(setup, lambda: {}, lambda: [(d, Status('stopped')) for d in dashboards()], folder)

    def press_every_change(self, setup, folder):
        """Each button that changes something, page by page, as a person presses them; the outcomes."""
        outcomes = []
        for page in ('pc', 'bridge'):
            for row in model.page_rows(self.read(setup, folder), page):
                for action in row.actions:
                    if action.kind == 'make':
                        outcomes.append(model.outcome(action.finding.make()))
        return outcomes

    def state(self):
        """What setup leaves on the temp home and clone, the order of the claude calls aside."""
        hooks = subprocess.run(['git', '-C', str(self.clone), 'config', '--local', '--get-all', 'core.hooksPath'], env=GIT_ENV,
                               capture_output=True, text=True).stdout.strip()     # exit code 1 while there is none
        claude_state = self.config / '.claude.json'
        return {'bridge': self.stored(), 'user': self.user(), 'hooks': hooks,
                'claude': json.loads(claude_state.read_text()) if claude_state.exists() else {},
                'changes': sorted(json.dumps(c) for c in self.changes())}

    def undo(self):
        """Back to the fresh clone of setUp."""
        git(self.clone, 'config', '--local', '--unset', 'core.hooksPath')
        for f in (self.user_settings, self.config / '.claude.json', self.config / 'fake-plugins.json', self.config / 'claude-calls.log'):
            f.unlink(missing_ok=True)
        self.bridge_settings.write_text(json.dumps({'tiaRoot': str(self.tia), 'archivesKept': 3}))

    def test_every_button_changes_what_the_command_changes_for_the_same_answer(self):
        setup = self.setup_module()
        self.assertEqual([failed for failed, _ in self.press_every_change(setup, ANSWER)], [False] * 5)
        by_window = self.state()
        self.undo()
        self.leave()
        code, out = self.answered()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), by_window)

    def test_after_the_buttons_the_command_finds_nothing_to_do(self):
        setup = self.setup_module()
        self.press_every_change(setup, ANSWER)
        self.leave()
        code, out = self.answered()
        self.assertEqual(code, 0, out)
        self.assertNotIn('done ', out)

    def test_a_step_skipped_stays_not_done_and_its_button_still_does_it(self):
        setup = self.setup_module()
        look = self.read(setup)
        status = next(r for r in model.settings_groups(look)[1][1] if r.key == 'status line')
        self.assertEqual(status.state, 'todo')
        self.assertNotIn('statusLine', self.user())
        failed, text = model.outcome(status.actions[0].finding.make())
        self.assertFalse(failed, text)
        self.assertIn('statusLine', self.user())
        status = next(r for r in model.settings_groups(self.read(setup))[1][1] if r.key == 'status line')
        self.assertEqual(status.state, 'ok')

    def test_a_failed_change_shows_the_tools_own_message(self):
        self.extra_env = {'FAKE_CLAUDE_FAIL': 'mcp add'}
        setup = self.setup_module()
        server = next(r for r in model.page_rows(self.read(setup), 'bridge') if r.key == 'MCP server tia')
        failed, text = model.outcome(server.actions[0].finding.make())
        self.assertTrue(failed)
        self.assertIn('Filename too long', text)

    def test_reading_changes_nothing(self):
        setup = self.setup_module()
        before = self.state()
        self.read(setup, ANSWER)
        self.assertEqual(self.state(), before)

    def test_a_worktree_shows_what_setup_says_and_nothing_else(self):
        tree = self.temp / 'tree'
        git(self.clone, 'worktree', 'add', '-q', str(tree))
        self.clone = tree
        setup = self.setup_module()
        look = self.read(setup)
        self.assertEqual(look.findings, {})
        self.assertIn('worktree of', setup.worktree_refusal(look.worktree_of))
        self.assertTrue(model.same_folder(look.worktree_of, self.temp / 'clone'))


if __name__ == '__main__':
    unittest.main()
