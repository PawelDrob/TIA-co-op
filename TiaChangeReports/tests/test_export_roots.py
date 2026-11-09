"""The report reads a project repo's exports only, by path from the repo's root."""
import contextlib
import glob
import io
import json
import os
import re
import subprocess
import tempfile
import unittest

from TiaChangeReports.__main__ import main
from TiaChangeReports.names import file_safe
from TiaChangeReports.source import EXPORT_ROOTS, LEFT_OUT, FolderSnapshot, GitSnapshot, _in_place, git_snapshots
from TiaChangeReports.tests.test_change_reports import SRC, _git, _put
from TiaChangeReports.tests.test_plc_tags import table, tag

CHANGED = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
BRIDGE_TOOLS = os.path.join(os.path.dirname(__file__), '..', '..', 'TiaBridge', 'Tools')


def _report(*args):
    """The --json result of a report on args, the page in a temporary folder."""
    with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()) as printed:
        main(list(args) + ['-o', os.path.join(out, 'page.html'), '--json'])
    return json.loads(printed.getvalue())


def _page(*args):
    """The page of a report on args."""
    with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()):
        page = os.path.join(out, 'page.html')
        main(list(args) + ['-o', page])
        with open(page, encoding='utf-8') as f:
            return f.read()


NO_CHANGES = '<div class="empty">No changes.</div>'


def _blocks(result):
    return sorted((b['name'], b['state']) for b in result['blocks'])


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        _git(self.repo, 'init', '-q')
        _git(self.repo, 'config', 'core.autocrlf', 'false')

    def commit(self, files):
        _put(self.repo, files)
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'c')


MARKS = {'plc/.gitkeep': '', 'hmi/.gitkeep': '', 'library/.gitkeep': ''}     # what a new project repo commits
REVIEW = {'library/changes/1-Y/review/Y/Y.s7dcl': SRC, 'library/changes/1-Y/review/Y.released/Y.s7dcl': SRC}
NOT_EXPORTS = dict(REVIEW, **{'logs/L.s7dcl': SRC, 'archives/R.s7dcl': SRC, 'gen/G.s7dcl': SRC, 'R.s7dcl': SRC,
                              '.scratch/S.s7dcl': SRC})
IN_TIA_FOLDERS = {'plc/blocks/logs/A.s7dcl': SRC, 'plc/blocks/archives/B.s7dcl': SRC, 'plc/blocks/.dot/C.s7dcl': SRC,
                  'plc/blocks/library/changes/D.s7dcl': SRC, 'plc/PLC_2/blocks/gen/E.s7dcl': SRC,
                  'library/types/logs/F/F.s7dcl': SRC, 'library/global/Lib/types/G/G.s7dcl': SRC}


class ProjectRepo(Repo):
    """A repo in the bridge's layout: a path outside the roots reads no block, a TIA folder inside them is read."""

    def test_the_working_copies_of_a_review_are_no_blocks_of_the_commit(self):
        self.commit(dict(MARKS, **{'plc/blocks/A.s7dcl': SRC}))
        self.commit(dict(REVIEW, **{'plc/blocks/A.s7dcl': CHANGED}))
        self.assertEqual(_blocks(_report('--git', self.repo, 'HEAD~1', 'HEAD')), [('A', 'changed')])

    def test_they_are_none_in_the_working_tree_either(self):
        self.commit(dict(MARKS, **{'plc/blocks/A.s7dcl': SRC}))
        _put(self.repo, dict(REVIEW, **{'plc/blocks/A.s7dcl': CHANGED}))
        self.assertEqual(_blocks(_report('--git', self.repo, 'HEAD')), [('A', 'changed')])

    def test_a_revision_reads_the_roots_only(self):
        self.commit(dict(MARKS, **NOT_EXPORTS, **IN_TIA_FOLDERS))
        self.assertEqual(GitSnapshot(self.repo, 'HEAD').paths(), sorted(IN_TIA_FOLDERS))

    def test_the_working_tree_reads_the_roots_only(self):
        self.commit(MARKS)
        _put(self.repo, dict(NOT_EXPORTS, **IN_TIA_FOLDERS))
        self.assertEqual(GitSnapshot(self.repo).paths(), sorted(IN_TIA_FOLDERS))

    def test_a_folder_of_that_layout_reads_the_roots_only(self):
        _put(self.repo, dict(MARKS, **NOT_EXPORTS, **IN_TIA_FOLDERS))
        self.assertEqual(FolderSnapshot(self.repo).paths(), sorted(IN_TIA_FOLDERS))

    def test_a_folder_of_a_repo_is_anchored_at_the_repo(self):
        self.commit(dict(MARKS, **{'library/types/T/T.s7dcl': SRC, 'library/changes/1-Y/review/Y/Y.s7dcl': SRC}))
        library = os.path.join(self.repo, 'library')
        self.assertEqual(GitSnapshot(library, 'HEAD').paths(), ['types/T/T.s7dcl'])
        self.assertEqual(GitSnapshot(library).paths(), ['types/T/T.s7dcl'])

    def test_a_block_outside_the_roots_is_named_but_a_review_copy(self):
        """Each input; once, though both sides hold it."""
        left = {'logs/L.s7dcl', 'archives/R.s7dcl', 'gen/G.s7dcl', 'R.s7dcl', '.scratch/S.s7dcl'}
        self.commit(dict(MARKS, **NOT_EXPORTS))
        self.commit({p: CHANGED for p in NOT_EXPORTS})
        named = _report('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual({x['path'] for x in named['skipped']}, left)
        self.assertEqual({x['reason'] for x in named['skipped']}, {LEFT_OUT})
        self.assertEqual(len(named['skipped']), len(left))
        self.assertEqual(named['blocks'], [])
        for snap in (GitSnapshot(self.repo), FolderSnapshot(self.repo)):
            snap.paths()
            self.assertEqual({p for p, _ in snap.skipped}, left)

    def test_a_tag_table_outside_the_roots_is_named(self):
        self.commit(dict(MARKS, **{'other/Plant.xml': table('Plant', tag('Run'))}))
        snap = GitSnapshot(self.repo, 'HEAD')
        self.assertEqual(snap.paths(), [])
        self.assertEqual(snap.skipped, [('other/Plant.xml', LEFT_OUT)])

    def test_an_xml_of_no_export_outside_the_roots_is_not_named(self):
        """The shape of a generator's reference file in gen/."""
        self.commit(dict(MARKS, **{'gen/shape.xml': '<Document><Hmi.Screen.Screen ID="0" /></Document>'}))
        snap = GitSnapshot(self.repo, 'HEAD')
        self.assertEqual((snap.paths(), snap.skipped), ([], []))

    def test_the_commit_where_a_mark_first_appears_deletes_nothing(self):
        """Both revisions read alike: the first holds no hmi/, so neither is taken for a project repo."""
        files = {'plc/blocks/A.s7dcl': SRC, 'library/changes/1/Y.s7dcl': SRC, 'logs/L.s7dcl': SRC}
        self.commit(files)
        self.commit(dict({p: CHANGED for p in files}, **{'hmi/.gitkeep': ''}))
        self.assertEqual(_blocks(_report('--git', self.repo, 'HEAD~1', 'HEAD')),
                         [('A', 'changed'), ('L', 'changed'), ('Y', 'changed')])
        before, after = git_snapshots(self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual(before.paths(), after.paths())

    def test_a_change_in_a_tia_folder_named_logs_is_told(self):
        """For a block and for a tag table."""
        plant = table('Plant', tag('Run', address='%M0.0'))
        self.commit(dict(MARKS, **{'plc/blocks/logs/A.s7dcl': SRC, 'plc/tags/logs/Plant.xml': plant}))
        self.commit({'plc/blocks/logs/A.s7dcl': CHANGED,
                     'plc/tags/logs/Plant.xml': plant.replace('%M0.0', '%M0.1')})
        got = _report('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual(_blocks(got), [('A', 'changed')])
        self.assertEqual([t['name'] for t in got['plcTags']], ['Plant'])


class ThePage(Repo):
    """It names what the roots leave out of a change, and never says "No changes." over that."""

    def page_of_the_commit(self, first, then):
        self.commit(dict(MARKS, **first))
        self.commit(then)
        return _page('--git', self.repo, 'HEAD~1', 'HEAD')

    def test_a_block_left_out_is_named_in_place_of_no_changes(self):
        page = self.page_of_the_commit({'gen/G.s7dcl': SRC}, {'gen/G.s7dcl': CHANGED})
        self.assertIn('gen/G.s7dcl', page)
        self.assertNotIn(NO_CHANGES, page)

    def test_a_tag_table_left_out_is_named(self):
        plant = table('Plant', tag('Run'))
        page = self.page_of_the_commit({'other/Plant.xml': plant}, {'other/Plant.xml': plant.replace('%M0.0', '%M0.1')})
        self.assertIn('other/Plant.xml', page)
        self.assertNotIn(NO_CHANGES, page)

    def test_it_stands_beside_a_change_that_is_shown(self):
        page = self.page_of_the_commit({'gen/G.s7dcl': SRC, 'plc/blocks/A.s7dcl': SRC},
                                       {'gen/G.s7dcl': CHANGED, 'plc/blocks/A.s7dcl': CHANGED})
        self.assertIn('gen/G.s7dcl', page)
        self.assertIn('plc/blocks/A', page)

    def test_a_review_copy_is_not_named(self):
        page = self.page_of_the_commit(REVIEW, {p: CHANGED for p in REVIEW})
        self.assertNotIn('library/changes', page)
        self.assertIn(NO_CHANGES, page)

    def test_a_file_of_no_export_is_not_named(self):
        shape = '<Document><Hmi.Screen.Screen ID="0" /></Document>'
        page = self.page_of_the_commit({'gen/shape.xml': shape}, {'gen/shape.xml': shape.replace('0', '1')})
        self.assertNotIn('gen/shape.xml', page)
        self.assertIn(NO_CHANGES, page)

    def test_a_block_that_does_not_parse_is_not_this_line(self):
        """Inside the roots: test_other_files.py has the wider line on other files."""
        page = self.page_of_the_commit({'plc/blocks/Bad.xml': '<Document><SW.Blocks.FB ID="0" /></Document>'},
                                       {'plc/blocks/Bad.xml': '<Document><SW.Blocks.FB ID="1" /></Document>'})
        self.assertNotIn('Left out of this comparison', page)

    def test_the_path_is_text(self):
        page = self.page_of_the_commit({'gen/a&b/G.s7dcl': SRC}, {'gen/a&b/G.s7dcl': CHANGED})
        self.assertIn('gen/a&amp;b/G.s7dcl', page)

    def test_a_fragment_names_it_too(self):
        self.commit(dict(MARKS, **{'gen/G.s7dcl': SRC}))
        self.commit({'gen/G.s7dcl': CHANGED})
        page = _page('--git', self.repo, 'HEAD~1', 'HEAD', '--fragment')
        self.assertIn('gen/G.s7dcl', page)
        self.assertNotIn(NO_CHANGES, page)


class OtherInputs(Repo):
    """No project repo: what was given is exports, a report on it hides nothing."""

    FILES = {'A.s7dcl': SRC, '.dot.s7dcl': SRC, 'logs/L.s7dcl': SRC, 'src/library/changes/C.s7dcl': SRC,
             'src/.dot/D.s7dcl': SRC}

    def test_a_folder_is_read_whole(self):
        _put(self.repo, dict(self.FILES, **{'.top/T.s7dcl': SRC}))
        self.assertEqual(FolderSnapshot(self.repo).paths(), sorted(self.FILES))

    def test_a_repo_is_read_whole(self):
        self.commit(dict(self.FILES, **{'.top/T.s7dcl': SRC}))
        self.assertEqual(GitSnapshot(self.repo, 'HEAD').paths(), sorted(self.FILES))
        self.assertEqual(GitSnapshot(self.repo).paths(), sorted(self.FILES))

    def test_a_folder_inside_a_project_repo_is_what_was_given(self):
        _put(self.repo, dict(MARKS, **{'plc/blocks/logs/A.s7dcl': SRC, 'library/changes/C.s7dcl': SRC}))
        self.assertEqual(FolderSnapshot(os.path.join(self.repo, 'plc')).paths(), ['blocks/logs/A.s7dcl'])
        self.assertEqual(FolderSnapshot(os.path.join(self.repo, 'library')).paths(), ['changes/C.s7dcl'])

    def test_each_side_goes_by_its_own_layout(self):
        """Flat exports against a project repo: the block pairs by name, the review stays out."""
        with tempfile.TemporaryDirectory() as flat:
            _put(flat, {'A.s7dcl': SRC})
            _put(self.repo, dict(MARKS, **REVIEW, **{'plc/blocks/A.s7dcl': CHANGED}))
            self.assertEqual(_blocks(_report(flat, self.repo)), [('A', 'changed')])

    def test_a_group_named_like_a_mark_makes_no_repo(self):
        """Any name of a group, in any case: nothing of the folder drops out."""
        for marks in (('HMI', 'PLC', 'LIBRARY'), ('hmi',), ('plc',), ('plc', 'hmi'), ('PLC',), ('plc', 'hmi', 'library')):
            with self.subTest(marks), tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                before = {m + '/M%d.s7dcl' % i: SRC for i, m in enumerate(marks)}
                before['Main/B.s7dcl'] = SRC
                _put(d1, before)
                _put(d2, {p: CHANGED for p in before})
                self.assertEqual(FolderSnapshot(d1).paths(), sorted(before))
                self.assertEqual([s for _, s in _blocks(_report(d1, d2))], ['changed'] * len(before))

    def assertReadWhole(self, files):
        """A revision and the working tree of one repo read the same."""
        self.commit(files)
        self.assertEqual(GitSnapshot(self.repo, 'HEAD').paths(), sorted(files))
        self.assertEqual(GitSnapshot(self.repo).paths(), sorted(files))

    def test_a_group_named_like_a_mark_makes_no_repo_in_git(self):
        self.assertReadWhole({'HMI/A.s7dcl': SRC, 'PLC/C.s7dcl': SRC, 'library/L.s7dcl': SRC, 'Main/B.s7dcl': SRC})

    def test_groups_named_like_all_the_marks_make_no_repo_in_git(self):
        self.assertReadWhole({'plc/P.s7dcl': SRC, 'hmi/H.s7dcl': SRC, 'library/L.s7dcl': SRC, 'Main/B.s7dcl': SRC})

    def test_a_plain_folder_in_the_layout_still_names_what_it_leaves_out(self):
        """Groups that fit the layout to the letter: a project repo by every path, and the block beside them is told."""
        _put(self.repo, {'plc/blocks/P.s7dcl': SRC, 'hmi/screens/S.xml': '<Document />', 'library/types/L/L.s7dcl': SRC,
                         'Main/B.s7dcl': SRC})
        snap = FolderSnapshot(self.repo)
        self.assertEqual(snap.paths(), ['library/types/L/L.s7dcl', 'plc/blocks/P.s7dcl'])
        self.assertEqual(snap.skipped, [('Main/B.s7dcl', LEFT_OUT)])


@unittest.skipUnless(os.path.isdir(BRIDGE_TOOLS), 'no TiaBridge beside the report')
class BridgeFolders(unittest.TestCase):
    def test_every_folder_the_bridge_exports_to_is_read(self):
        """A root missing here hides every change of that kind. The report reads no file of the bridge; this test does."""
        tools = ''
        for f in glob.glob(os.path.join(BRIDGE_TOOLS, '*.ps1')):
            with open(f, encoding='utf-8') as text:
                tools += text.read()
        folders = set(re.findall(r"\bdir = '([^']+)'", tools)) | set(re.findall(r'"(library\\global)\\', tools))
        self.assertGreater(len(folders), 20)        # the pattern still finds them
        self.assertIn('library\\global', folders)
        self.assertEqual([f for f in folders if not (f.replace('\\', '/') + '/').startswith(EXPORT_ROOTS)], [])
        kinds = [f.replace('\\', '/') for f in folders]
        devices = [re.sub(r'^(plc|hmi)/', r'\1/Device/', f) for f in kinds]
        self.assertEqual([f for f in kinds + devices if not _in_place(f + '/Folder/X.xml')], [])

    def test_a_name_is_made_file_safe_as_the_bridge_does(self):
        """A name of another form finds no file of its own: the report would show the file's name, a block no call finds."""
        names = ['Ns:Block', 'a\\b/c:d*e?f"g<h>i|j', 'tab\tin', 'Block.', 'Block ', 'Block. .', 'Block\u00a0', 'Block\u0085',
                 'a.b', 'a b', 'con', 'NUL', 'Nul.txt', 'nullable', 'prn', 'aux.x', 'COM1', 'com\u00b9', 'lpt9.a', 'lpt',
                 'COM', 'conin$', 'CONOUT$.x', 'conin', '+-=', '\u00e4:\u00f6', '.', '...']
        repo = os.path.join(BRIDGE_TOOLS, '..', 'Repo.ps1')
        script = ('[Console]::OutputEncoding = [Text.Encoding]::UTF8; . "%s"; '
                  '@(($input | ConvertFrom-Json) | ForEach-Object { ConvertTo-SafeFileName $_ }) | ConvertTo-Json' % repo)
        run = subprocess.run(['powershell', '-NoProfile', '-Command', script], input=json.dumps(names), text=True,
                             encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(run.stdout), [file_safe(n) for n in names])


if __name__ == '__main__':
    unittest.main()
