"""What a session starts without, from a stand-in of Claude Code's folder and of a tree: the user's own are never read."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from left_out import ALL, BUILT_IN_SKILLS, BUNDLED, TOOLS, left_out
from store import SessionError


def skill(folder, name):
    (folder / name).mkdir(parents=True, exist_ok=True)
    (folder / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n', encoding='utf-8')


class LeftOutTests(unittest.TestCase):
    def setUp(self):
        self.top = Path(tempfile.mkdtemp(prefix='left-out-test-')).resolve()
        self.addCleanup(shutil.rmtree, self.top)
        self.home, self.main, self.tree = self.top / 'home', self.top / 'clone', self.top / 'clone-worktrees' / 'work-03'
        for folder in (self.home, self.main, self.tree):
            folder.mkdir(parents=True)
        self.settings({'model': 'x', 'enabledPlugins': {'mattpocock-skills@official': True, 'feature-dev@official': True,
                                                        'frontend-design@official': True, 'context7@official': False}})
        for name in ('docx', 'pdf'):
            skill(self.home / 'skills' / 'synced' / 'account-1', name)
        for root in (self.main, self.tree):
            skill(root / '.claude' / 'skills', 'ticket')
            skill(root / '.claude' / 'skills', 'review-page')

    def settings(self, data, path=None):
        path = path or self.home / 'settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def left(self, keep=()):
        return left_out(self.home, self.tree, self.main, keep)

    def test_the_six_tools_no_skill_calls_go_and_agent_stays(self):
        self.assertEqual(self.left().tools, list(TOOLS))
        self.assertEqual(TOOLS, ('Artifact', 'Workflow', 'SendFeedback', 'ScheduleWakeup', 'ReportFindings', 'ListAgents'))
        self.assertNotIn('Agent', TOOLS)

    def test_each_plugin_the_user_has_on_goes_but_the_ticket_flows(self):
        self.assertEqual(self.left().plugins, ['feature-dev@official', 'frontend-design@official'])
        self.assertEqual(self.left().settings()['enabledPlugins'], {'feature-dev@official': False, 'frontend-design@official': False})

    def test_the_trees_own_settings_decide_after_the_users(self):
        self.settings({'enabledPlugins': {'feature-dev@official': False, 'csharp-lsp@official': True}},
                      self.tree / '.claude' / 'settings.json')
        self.settings({'enabledPlugins': {'csharp-lsp@official': False}}, self.tree / '.claude' / 'settings.local.json')
        self.assertEqual(self.left().plugins, ['frontend-design@official'])

    def test_no_settings_and_a_broken_one_leave_no_plugin_out(self):
        (self.home / 'settings.json').write_text('{not json', encoding='utf-8')
        self.assertEqual(self.left().plugins, [])
        (self.home / 'settings.json').unlink()
        self.assertEqual(self.left().plugins, [])

    def test_synced_skills_the_built_in_plugins_and_the_bundled_ones_go(self):
        left = self.left()
        self.assertEqual(left.skills[:3], ['docx', 'pdf', *BUILT_IN_SKILLS])
        self.assertTrue(left.bundled)
        self.assertEqual(left.settings()['disableBundledSkills'], True)
        self.assertEqual(left.settings()['skillOverrides']['docx'], 'off')

    def test_a_synced_skill_named_as_one_of_the_repos_stays_as_the_name_would_take_both(self):
        skill(self.home / 'skills' / 'synced' / 'account-2', 'review-page')
        self.assertNotIn('review-page', self.left().skills)

    def test_the_main_trees_copies_of_the_repos_skills_go_and_the_trees_own_stay(self):
        skills = self.left().skills
        self.assertIn('clone:review-page', skills)
        self.assertIn('clone:ticket', skills)
        self.assertNotIn('review-page', skills)
        self.assertNotIn('ticket', skills)

    def test_in_the_main_tree_itself_there_is_no_copy(self):
        self.assertFalse([name for name in left_out(self.home, self.main, self.main).skills if ':' in name])

    def test_keep_brings_back_a_tool_a_plugin_by_its_name_a_skill_and_the_bundled(self):
        left = self.left(['Artifact', 'feature-dev', 'docx', BUNDLED])
        self.assertNotIn('Artifact', left.tools)
        self.assertEqual(left.plugins, ['frontend-design@official'])
        self.assertNotIn('docx', left.skills)
        self.assertFalse(left.bundled)
        self.assertNotIn('disableBundledSkills', left.settings())

    def test_a_plugin_is_kept_by_its_whole_name_too(self):
        self.assertEqual(self.left(['frontend-design@official']).plugins, ['feature-dev@official'])

    def test_keep_all_leaves_nothing_out(self):
        left = self.left([ALL])
        self.assertEqual((left.tools, left.plugins, left.skills, left.bundled), ([], [], [], False))
        self.assertEqual(left.settings(), {})

    def test_a_name_it_does_not_leave_out_is_refused_with_what_it_can_keep(self):
        for name in ('Artifacts', 'mattpocock-skills', 'context7', 'ticket', 'clone:ticket'):
            with self.assertRaisesRegex(SessionError, rf'--keep {name}: not among[\s\S]*Artifact[\s\S]*feature-dev[\s\S]*docx'):
                self.left([name])

    def test_the_users_settings_are_only_read(self):
        before = (self.home / 'settings.json').read_bytes()
        self.left()
        self.assertEqual((self.home / 'settings.json').read_bytes(), before)

    def test_the_summary_counts_what_went(self):
        self.assertEqual(self.left().summary(), 'left out: 6 tools, 2 plugins, 5 skills, the bundled skills. --keep <name> brings one back')


if __name__ == '__main__':
    unittest.main()
