"""The pointer check: a file an agent is pointed at must be in the repo, and a skill's frontmatter must parse."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.pointers.check_pointers import DOCUMENTS, GIT_CONTEXT, bad_frontmatter, dangling

SKILL = '.claude/skills/ticket/SKILL.md'
TRACKED = {
    'CLAUDE.md',
    'tools/dashboard/review_page.py',
    SKILL,
    '.claude/skills/coordinate/SESSIONS.md',
    'docs/agents/issue-tracker.md',
}


def check(text, path=SKILL):
    return dangling({path: text}, TRACKED)


class DanglingPointers(unittest.TestCase):
    def test_a_relative_link_to_a_tracked_file_holds(self):
        self.assertEqual(check('[sessions](../coordinate/SESSIONS.md)'), [])

    def test_a_relative_link_to_a_file_gone_is_named(self):
        self.assertEqual(check('[old](../coordinate/GONE.md)'), [(SKILL, 1, '../coordinate/GONE.md')])

    def test_a_link_with_an_anchor_is_read_without_it(self):
        self.assertEqual(check('[x](../../../docs/agents/issue-tracker.md#status-values)'), [])

    def test_web_links_and_plain_anchors_are_left_alone(self):
        self.assertEqual(check('[a](https://example.com/x.md) [b](#steps) [c](mailto:a@example.com)'), [])

    def test_a_repo_path_in_backticks_with_either_slash_holds(self):
        self.assertEqual(check(r'`tools\dashboard\review_page.py` and `docs/agents/issue-tracker.md`'), [])

    def test_a_repo_path_in_backticks_gone_is_named_with_its_line(self):
        self.assertEqual(check('first\n' + r'`tools\dashboard\gone.py --done x`'), [(SKILL, 2, r'tools\dashboard\gone.py')])

    def test_a_path_inside_a_command_in_a_fence_is_read(self):
        self.assertEqual(check('```\n' + r'<py> tools\dashboard\gone.py --title "x"' + '\n```'), [(SKILL, 2, r'tools\dashboard\gone.py')])

    def test_a_folder_named_holds_when_files_are_under_it(self):
        self.assertEqual(check('`tools\\dashboard\\`'), [])

    def test_words_that_only_look_like_paths_are_left_alone(self):
        self.assertEqual(check(r'`feat/workflow-05` `origin/main` `read/write` `~/.claude/x.md` `C:\x\y.md`'), [])

    def test_placeholders_and_globs_are_left_alone(self):
        self.assertEqual(check(r'`tools\dashboard\<name>.py` `docs/*/x.md`'), [])

    def test_untracked_local_folders_are_not_the_checks_business(self):
        self.assertEqual(check(r'`.scratch\reviews\answers\` `.venv\Scripts\python.exe`'), [])

    def test_a_named_root_markdown_file_gone_is_named(self):
        self.assertEqual(check('`CLAUDE.md` holds, `GONE.md` does not'), [(SKILL, 1, 'GONE.md')])

    def test_a_named_markdown_file_beside_the_document_holds(self):
        self.assertEqual(dangling({'.claude/skills/coordinate/SKILL.md': '`SESSIONS.md`'}, TRACKED), [])

    def test_a_link_with_a_title_is_read_without_it(self):
        self.assertEqual(check('[old](../coordinate/GONE.md "the old one")'), [(SKILL, 1, '../coordinate/GONE.md')])
        self.assertEqual(check('[new](../coordinate/SESSIONS.md "the sessions")'), [])

    def test_a_relative_path_in_backticks_is_read_from_the_document(self):
        self.assertEqual(check('`../coordinate/SESSIONS.md`'), [])
        self.assertEqual(check('`../x/GONE.md`'), [(SKILL, 1, '../x/GONE.md')])
        self.assertEqual(check(r'`..\x\GONE.md` `./GONE.md`'), [(SKILL, 1, r'..\x\GONE.md'), (SKILL, 1, './GONE.md')])

    def test_a_relative_path_in_backticks_that_leaves_the_repo_is_left_alone(self):
        self.assertEqual(check('`../../../../sibling/x.md`'), [])

    def test_a_path_git_ignores_is_a_local_file_and_holds(self):
        ignored = {'tools/settings.json'}.__contains__
        self.assertEqual(dangling({SKILL: '`tools/settings.json` `tools/gone.json`'}, TRACKED, ignored),
                         [(SKILL, 1, 'tools/gone.json')])

    def test_a_reference_style_link_gone_is_named(self):
        self.assertEqual(check('[old]: ../coordinate/GONE.md "the old one"'), [(SKILL, 1, '../coordinate/GONE.md')])

    def test_a_reference_style_link_that_holds_or_leaves_the_repo_passes(self):
        self.assertEqual(check('[a]: ../coordinate/SESSIONS.md\n[b]: https://example.com/x.md'), [])


class Frontmatter(unittest.TestCase):
    def test_a_good_skill_passes(self):
        text = '---\nname: ticket\ndescription: "Run: a ticket."\ndisable-model-invocation: true\n---\n\nBody'
        self.assertEqual(bad_frontmatter({SKILL: text}), [])

    def test_a_colon_in_a_plain_description_is_named_with_its_line(self):
        text = '---\nname: ticket\ndescription: Run sessions over a map: start, watch.\n---\n'
        found = bad_frontmatter({SKILL: text})
        self.assertEqual([(path, line) for path, line, _ in found], [(SKILL, 3)])
        self.assertIn('mapping values are not allowed', found[0][2])

    def test_a_skill_with_no_frontmatter_fails(self):
        self.assertEqual(bad_frontmatter({SKILL: '# Ticket\n'}), [(SKILL, 1, 'no frontmatter')])

    def test_frontmatter_that_never_closes_fails(self):
        self.assertEqual(bad_frontmatter({SKILL: '---\nname: ticket\n'}), [(SKILL, 1, 'no frontmatter')])

    def test_a_description_is_required(self):
        self.assertEqual(bad_frontmatter({SKILL: '---\nname: ticket\n---\n'}), [(SKILL, 1, 'no description')])

    def test_the_name_is_the_folder(self):
        self.assertEqual(bad_frontmatter({SKILL: '---\nname: audit\ndescription: x\n---\n'}),
                         [(SKILL, 1, 'name audit, in folder ticket')])

    def test_a_flag_written_as_a_string_is_named(self):
        text = '---\nname: ticket\ndescription: x\ndisable-model-invocation: "yes"\n---\n'
        self.assertEqual(bad_frontmatter({SKILL: text}), [(SKILL, 1, 'disable-model-invocation is not true or false')])

    def test_a_flag_written_yes_is_named_though_yaml_reads_it_as_true(self):
        text = '---\nname: ticket\ndescription: x\ndisable-model-invocation: yes\n---\n'
        self.assertEqual(bad_frontmatter({SKILL: text}), [(SKILL, 1, 'disable-model-invocation is not true or false')])

    def test_a_flag_with_a_comment_passes(self):
        text = '---\nname: ticket\ndescription: x\ndisable-model-invocation: true # typed prompt only\n---\n'
        self.assertEqual(bad_frontmatter({SKILL: text}), [])

    def test_the_body_of_a_skill_can_quote_the_flag(self):
        text = '---\nname: ticket\ndescription: x\n---\n\ndisable-model-invocation: yes\n'
        self.assertEqual(bad_frontmatter({SKILL: text}), [])

    def test_a_misspelt_key_is_named(self):
        text = '---\nname: ticket\ndescription: x\ndisable-model-invokation: true\n---\n'
        self.assertEqual(bad_frontmatter({SKILL: text}),
                         [(SKILL, 1, 'disable-model-invokation: did you mean disable-model-invocation?')])

    def test_a_key_like_no_known_one_is_left_alone(self):
        text = '---\nname: ticket\ndescription: x\nargument-hint: y\nsomething-new: z\n---\n'
        self.assertEqual(bad_frontmatter({SKILL: text}), [])

    def test_the_contributor_documents_are_read(self):
        for path in ('AGENTS.md', 'CODING_STANDARDS.md', 'CONTRIBUTING.md'):
            self.assertTrue(DOCUMENTS.match(path), path)

    def test_other_documents_need_none(self):
        self.assertEqual(bad_frontmatter({'.claude/skills/coordinate/SESSIONS.md': '# Sessions\n', 'CODING_STANDARDS.md': '# x\n'}), [])


class InARepo(unittest.TestCase):
    """The script on a real index: staged, ignored and gone files, a bad frontmatter, and the exit code."""

    def run_check(self, files, ignore='', inherited=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        with tempfile.TemporaryDirectory() as root:
            def git(*args):
                subprocess.run(['git', *args], cwd=root, env=env, check=True, capture_output=True)
            git('init', '-q')
            (Path(root) / '.gitignore').write_text(ignore, encoding='utf-8')
            for name, text in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
            git('add', '-A')
            script = Path(__file__).parents[1] / 'check_pointers.py'
            done = subprocess.run([sys.executable, '-X', 'utf8', str(script)], cwd=root, env={**env, **(inherited or {})},
                                  capture_output=True, text=True)
            return done.returncode, done.stdout

    SKILL_HEAD = '---\nname: ticket\ndescription: x\n---\n'

    def test_a_clean_tree_passes(self):
        code, out = self.run_check({SKILL: self.SKILL_HEAD + '`tools/a.py`', 'tools/a.py': ''})
        self.assertEqual((code, out), (0, ''))

    def test_a_gitignored_file_in_a_tracked_folder_holds(self):
        code, out = self.run_check({SKILL: self.SKILL_HEAD + '`tools/settings.json`', 'tools/a.py': ''}, 'tools/settings.json\n')
        self.assertEqual((code, out), (0, ''))

    def test_a_file_gone_fails_with_its_line(self):
        code, out = self.run_check({SKILL: self.SKILL_HEAD + '`tools/gone.py`', 'tools/a.py': ''})
        self.assertEqual(code, 1)
        self.assertIn(SKILL + ':5:', out)

    def test_a_readme_naming_a_file_gone_fails_for_the_repo_tools_and_each_tool(self):
        for readme in ('README.md', 'tools/README.md', 'TiaBridge/README.md'):
            code, out = self.run_check({readme: '`tools/gone.py`', 'tools/a.py': ''})
            self.assertEqual(code, 1, readme)
            self.assertIn(readme + ':1:', out)

    def test_the_readme_of_a_tool_in_a_folder_of_any_name_is_read(self):
        code, out = self.run_check({'PlcLint/README.md': '`tools/gone.py`', 'tools/a.py': ''})
        self.assertEqual(code, 1)
        self.assertIn('PlcLint/README.md:1:', out)

    def test_a_folders_own_notes_are_not_read(self):
        code, out = self.run_check({'tools/okf/README.md': '`index.md`', 'TiaBridge/Tests/README.md': '`tools/gone.py`', 'tools/a.py': ''})
        self.assertEqual((code, out), (0, ''))

    def test_a_readme_link_is_read_from_its_own_folder(self):
        code, out = self.run_check({'tools/README.md': '[a](a.py) [setup](../docs/setup.md)', 'tools/a.py': '', 'docs/setup.md': ''})
        self.assertEqual((code, out), (0, ''))

    def test_it_reads_the_repo_it_stands_in_with_a_parents_git_context_inherited(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        with tempfile.TemporaryDirectory() as parent:
            subprocess.run(['git', 'init', '-q'], cwd=parent, env=env, check=True, capture_output=True)
            git_dir = os.path.join(parent, '.git')
            code, out = self.run_check({SKILL: self.SKILL_HEAD + '`tools/gone.py`', 'tools/a.py': ''},
                                       inherited={'GIT_DIR': git_dir, 'GIT_WORK_TREE': parent,
                                                  'GIT_INDEX_FILE': os.path.join(git_dir, 'index')})
        self.assertEqual(code, 1)
        self.assertIn(SKILL + ':5:', out)

    def test_a_bad_frontmatter_fails_with_its_line(self):
        code, out = self.run_check({SKILL: '---\nname: ticket\ndescription: a map: start\n---\n'})
        self.assertEqual(code, 1)
        self.assertIn(SKILL + ':3:', out)


class GitsOwnList(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_every_name_of_git_is_dropped(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
