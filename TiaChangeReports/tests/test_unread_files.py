"""The page names a file the report could not read or compare, and never says "No changes." over it."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from TiaChangeReports.__main__ import main
from TiaChangeReports.page import NOT_SHOWN
from TiaChangeReports.tests.test_change_reports import LIB_META, META, SRC, _fixture, _git, _locked, _put
from TiaChangeReports.tests.test_plc_tags import table, tag

CHANGED = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
NO_CHANGES = 'No changes.'
COULD_NOT_READ = 'Not compared, could not be read and may hold a change: '
NO_BLOCK_EXPORT = 'Not compared, no block export though a block is in it: '
BLOCK = 'plc/blocks/A.s7dcl'
TABLE = 'plc/tags/Plant.xml'
NOTES = 'plc/Notes.xml'
PLANT = table('Plant', tag('run', '%M1.0'))


def _put_bytes(root, path, data):
    os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
    with open(os.path.join(root, path), 'wb') as f:
        f.write(data)


class Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(tmp.name, 'Plant')
        os.makedirs(self.repo)
        _git(self.repo, 'init', '-q')
        _git(self.repo, 'config', 'core.autocrlf', 'false')

    def commit(self, files):
        _put(self.repo, files)
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'files')

    def report(self, *inputs):
        """(the --json result, the page) of a report on inputs."""
        page = os.path.join(self.tmp, 'out', 'page.html')
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, main(list(inputs) + ['-o', page, '--json']))
        with open(page, encoding='utf-8') as f:
            return json.loads(printed.getvalue()), f.read()

    def working_tree(self, locked):
        """The report on HEAD against the working tree, with the file locked."""
        return _locked(os.path.join(self.repo, locked), lambda: self.report('--git', self.repo, 'HEAD', '--only', 'plc'))

    def assert_named_as_unread(self, page, path):
        self.assertIn(COULD_NOT_READ + path, page)
        self.assertNotIn(NO_CHANGES, page)


class ALockedFile(Files):
    def test_a_locked_block_with_an_edit_in_it_is_named_in_place_of_no_changes(self):
        self.commit({BLOCK: SRC})
        _put(self.repo, {BLOCK: CHANGED})

        res, page = self.working_tree(BLOCK)

        self.assertEqual([], res['blocks'])
        self.assertEqual([BLOCK], [s['path'] for s in res['skipped']])
        self.assert_named_as_unread(page, BLOCK)

    def test_a_locked_xml_of_no_block_holds_to_the_same_words(self):
        self.commit({NOTES: '<Document><Nothing/></Document>'})

        _, page = self.working_tree(NOTES)

        self.assert_named_as_unread(page, NOTES)

    def test_a_locked_xml_of_no_block_in_a_folder_compare_too(self):
        _put(self.tmp, {'a/' + NOTES: '<Document><Nothing/></Document>', 'b/' + NOTES: '<Document><Nothing/></Document>'})
        before, after = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')

        _, page = _locked(os.path.join(after, NOTES), lambda: self.report(before, after))

        self.assert_named_as_unread(page, NOTES)

    def test_a_locked_simaticml_block_is_named_once(self):
        self.commit({'plc/blocks/Main.xml': _fixture()})

        _, page = self.working_tree('plc/blocks/Main.xml')

        self.assertEqual(1, page.count('plc/blocks/Main.xml'))
        self.assert_named_as_unread(page, 'plc/blocks/Main.xml')

    def test_the_note_stands_beside_a_change_that_is_shown(self):
        self.commit({BLOCK: SRC, 'plc/blocks/B.s7dcl': SRC})
        _put(self.repo, {BLOCK: CHANGED, 'plc/blocks/B.s7dcl': CHANGED})

        res, page = self.working_tree('plc/blocks/B.s7dcl')

        self.assertEqual(['changed'], [b['state'] for b in res['blocks']])
        self.assertIn(COULD_NOT_READ + 'plc/blocks/B.s7dcl', page)

    def test_one_that_may_declare_the_block_asked_for_is_named_and_the_name_is_no_typo(self):
        """--block Q: a locked file named otherwise may declare Q."""
        self.commit({BLOCK: SRC})
        _put(self.repo, {'plc/blocks/N.s7dcl': SRC.replace('"T"', '"Q"', 1)})

        res, page = _locked(os.path.join(self.repo, 'plc/blocks/N.s7dcl'),
                            lambda: self.report('--git', self.repo, 'HEAD', '--only', 'plc', '--block', 'Q'))

        self.assertEqual(['plc/blocks/N.s7dcl'], [s['path'] for s in res['skipped']])
        self.assertNotIn('unmatched', res)
        self.assert_named_as_unread(page, 'plc/blocks/N.s7dcl')

    def test_one_that_may_declare_the_block_asked_for_on_the_side_before_too(self):
        _put(self.tmp, {'a/plc/blocks/N.s7dcl': SRC.replace('"T"', '"Q"', 1), 'b/' + BLOCK: SRC})
        before, after = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')

        res, page = _locked(os.path.join(before, 'plc/blocks/N.s7dcl'),
                            lambda: self.report(before, after, '--block', 'Q'))

        self.assertNotIn('unmatched', res)
        self.assert_named_as_unread(page, 'plc/blocks/N.s7dcl')


class ALockedTagTable(Files):
    def assert_no_table_and_named_as_unread(self, res, page, path):
        self.assertNotIn('plcTags', res)
        self.assertNotIn(NOT_SHOWN, page)
        self.assert_named_as_unread(page, path)

    def test_unchanged_it_says_it_could_not_be_read_and_not_that_it_changed(self):
        self.commit({TABLE: PLANT})

        res, page = self.working_tree(TABLE)

        self.assert_no_table_and_named_as_unread(res, page, TABLE)

    def test_with_an_edit_in_it_it_says_the_same(self):
        self.commit({TABLE: PLANT})
        _put(self.repo, {TABLE: table('Plant', tag('run', '%M1.1'))})

        res, page = self.working_tree(TABLE)

        self.assert_no_table_and_named_as_unread(res, page, TABLE)

    def test_in_a_folder_compare_too(self):
        _put(self.tmp, {'a/' + TABLE: PLANT, 'b/' + TABLE: PLANT})
        before, after = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')

        res, page = _locked(os.path.join(before, TABLE), lambda: self.report(before, after))

        self.assert_no_table_and_named_as_unread(res, page, TABLE)

    def test_moved_with_an_edit_it_reads_no_state_of_its_own_and_its_old_path_reads_deleted(self):
        """moved would say its content is the same; the old path is gone, which is known."""
        old, new = 'plc/tags/Old/Plant.xml', 'plc/tags/New/Plant.xml'
        self.commit({old: PLANT})
        os.remove(os.path.join(self.repo, old))
        _put(self.repo, {new: table('Plant', tag('run', '%M2.0'))})

        res, page = self.working_tree(new)

        self.assertEqual([('deleted', 'Plant')], [(t['state'], t['name']) for t in res['plcTags']])
        self.assertNotIn(NOT_SHOWN, page)
        self.assert_named_as_unread(page, new)

    def test_new_it_says_it_could_not_be_read_and_not_that_it_is_new(self):
        self.commit({BLOCK: SRC})
        _put(self.repo, {TABLE: PLANT})

        res, page = self.working_tree(TABLE)

        self.assert_no_table_and_named_as_unread(res, page, TABLE)

    def test_deleted_between_two_folders_it_says_it_could_not_be_read_and_not_that_it_is_deleted(self):
        _put(self.tmp, {'a/' + TABLE: PLANT, 'a/' + BLOCK: SRC, 'b/' + BLOCK: SRC})
        before, after = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')

        res, page = _locked(os.path.join(before, TABLE), lambda: self.report(before, after))

        self.assert_no_table_and_named_as_unread(res, page, TABLE)


class AFileThatDoesNotParse(Files):
    def test_a_block_is_named_in_place_of_no_changes(self):
        _put(self.tmp, {'a/' + BLOCK: SRC, 'b/' + BLOCK: 'FUNCTION_BLOCK "A"\nthis is { not s7dcl\n'})

        _, page = self.report(os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b'))

        self.assert_named_as_unread(page, BLOCK)

    def test_a_table_read_on_one_side_tells_it_differs_and_is_named(self):
        self.commit({TABLE: PLANT})
        self.commit({TABLE: '<Document><SW.Tags.PlcTagTable ID="0"><broken'})

        res, page = self.report('--git', self.repo, 'HEAD~1', 'HEAD')

        self.assertEqual(['changed'], [t['state'] for t in res['plcTags']])
        self.assertIn(COULD_NOT_READ + TABLE, page)


class AFileThatDoesNotDecode(Files):
    def test_a_table_still_reads_changed_as_its_bytes_are_known(self):
        self.commit({TABLE: PLANT})
        _put_bytes(self.repo, TABLE, PLANT.replace('run', 'rün').encode('latin-1'))
        self.commit({})

        res, _ = self.report('--git', self.repo, 'HEAD~1', 'HEAD')

        self.assertEqual(['changed'], [t['state'] for t in res['plcTags']])

    def test_an_export_of_no_block_is_named_and_the_rest_is_written(self):
        _put(self.tmp, {'a/' + META: LIB_META, 'a/' + BLOCK: SRC, 'b/' + BLOCK: CHANGED})
        _put_bytes(self.tmp, 'b/' + META, LIB_META.replace('typePosition', 'typePositïon').encode('latin-1'))

        res, page = self.report(os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b'))

        self.assertEqual(['changed'], [b['state'] for b in res['blocks']])
        self.assertIn(NO_BLOCK_EXPORT + META, page)


class AnExportOfNoBlockHoldingOne(Files):
    def folders(self, before, after):
        _put(self.tmp, {'a/' + META: before, 'b/' + META: after})
        return self.report(os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b'))

    def test_changed_in_a_tags_folder_it_is_named_in_place_of_no_changes(self):
        path = 'plc/tags/N.xml'
        self.commit({path: LIB_META})
        self.commit({path: LIB_META.replace('0.0.1<', '0.0.2<')})

        res, page = self.report('--git', self.repo, 'HEAD~1', 'HEAD')

        self.assertEqual([path], [s['path'] for s in res['skipped']])
        self.assertIn(NO_BLOCK_EXPORT + path, page)
        self.assertNotIn(NO_CHANGES, page)

    def test_changed_between_two_folders_it_is_named(self):
        _, page = self.folders(LIB_META, LIB_META.replace('0.0.1<', '0.0.2<'))

        self.assertIn(NO_BLOCK_EXPORT + META, page)
        self.assertNotIn(NO_CHANGES, page)

    def test_the_same_on_both_sides_the_page_says_no_changes(self):
        """A project's global library types: else no compare of two folders of it could ever read so."""
        res, page = self.folders(LIB_META, LIB_META)

        self.assertEqual([META], [s['path'] for s in res['skipped']])
        self.assertNotIn(META, page)
        self.assertIn(NO_CHANGES, page)

    def test_locked_on_a_side_it_is_named_as_unread_only(self):
        _put(self.tmp, {'a/' + META: LIB_META, 'b/' + META: LIB_META.replace('0.0.1<', '0.0.2<')})
        before, after = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')

        _, page = _locked(os.path.join(after, META), lambda: self.report(before, after))

        self.assertNotIn(NO_BLOCK_EXPORT, page)
        self.assert_named_as_unread(page, META)

    def test_differing_only_in_the_export_time_it_is_the_same(self):
        stamped = '<Document><DocumentInfo><Created>%s</Created></DocumentInfo>'       # where an export writes it
        one = LIB_META.replace('<Document>', stamped % '2026-01-01T00:00:00Z', 1)
        two = LIB_META.replace('<Document>', stamped % '2026-02-02T00:00:00Z', 1)
        self.assertNotEqual(one, two)

        _, page = self.folders(one, two)

        self.assertIn(NO_CHANGES, page)


if __name__ == '__main__':
    unittest.main()
