"""A changed file the report does not read is named on its page, which then cannot say "No changes."."""
import contextlib
import io
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from TiaChangeReports.__main__ import main
from TiaChangeReports.tests.test_change_reports import SRC, _git, _put
from TiaChangeReports.tests.test_export_roots import CHANGED, MARKS, NO_CHANGES, _page, _report, Repo
from TiaChangeReports.tests.test_plc_tags import table, tag

WATCH = ('<?xml version="1.0" encoding="utf-8"?><Document><DocumentInfo><Created>%s</Created></DocumentInfo>'
         '<SW.WatchAndForceTables.PlcWatchTable ID="0"><AttributeList><Name>%s</Name></AttributeList>'
         '</SW.WatchAndForceTables.PlcWatchTable></Document>')
ALARMS = ('<?xml version="1.0" encoding="utf-8"?>\n<AlarmServiceGlobalSettingsData SchemaVersion="%s" ProjectName="P" '
          'CreationDate="%s">\n  <AlarmClass Name="%s" />\n</AlarmServiceGlobalSettingsData>')
MASTER_COPIES = 'library/mastercopies/mastercopies.json'
DAT = 'project/alarmclasses/classes.dat'
TYPE = 'library/types/F/T/T'
LIBINFO = 'LibraryType:\n  Guid: a\nLibraryVersion:\n  VersionNumber: %s\n  Author: %s\n  IsDefault: true\n'
LIBINT = ('DocumentHash:\n  - FileName: T.s7dcl\n    Hash: %s\nLibraryMetaFileHash: %s\nLibraryVersion:\n  Guid: %s\n%s')
DEPENDS = '  DependsOn:\n    - TypeName: S\n      VersionNumber: %s\n'
COMMENT = '  Comment:\n    en-US: %s\n'
SCREEN = ('<Document><Hmi.Screen.Screen ID="0"><AttributeList><Name>S</Name><Number>%d</Number></AttributeList>'
          '</Hmi.Screen.Screen></Document>')


def _zip_of(**files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, b'\xef\xbb\xbf' + text.encode('utf-8'))
    return out.getvalue()


@contextlib.contextmanager
def _cannot_open(*paths):
    """While it stands, these files cannot be opened, as ones another program holds."""
    really_open = open

    def denied(file, *args, **kwargs):
        if isinstance(file, str) and os.path.normpath(file) in paths:
            raise PermissionError(13, 'Permission denied', file)
        return really_open(file, *args, **kwargs)
    with mock.patch('builtins.open', denied):
        yield


def _write_bytes(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


class Commit(Repo):
    def others(self, first, then, *args):
        """otherFiles of a commit `then` over a commit `first`."""
        return self.report_of(first, then, *args).get('otherFiles', [])

    def report_of(self, first, then, *args):
        """The report of a commit `then` over a commit `first`."""
        self.commit(dict(MARKS, **first))
        self.commit(then)
        return _report('--git', self.repo, 'HEAD~1', 'HEAD', *args)

    def page_of(self, first, then):
        """The page of a commit `then` over a commit `first`."""
        self.commit(dict(MARKS, **first))
        self.commit(then)
        return _page('--git', self.repo, 'HEAD~1', 'HEAD')


class TheLine(Commit):
    @staticmethod
    def files(n, text):
        """n library files that no block reads, and a workbook."""
        files = {'library/types/F/T%d/T%d.libint' % (i, i): 'a: %s\n' % text for i in range(n - 1)}
        files['project/texts/texts.XLSX'] = text
        return files

    def test_a_long_line_counts_per_kind_and_folds_its_names(self):
        page = self.page_of(self.files(12, '1'), self.files(12, '2'))
        self.assertIn('<summary>12 other files changed, not read: 11 .libint, 1 .xlsx</summary>', page)
        for path in self.files(12, '2'):
            self.assertIn(path, page)
        self.assertNotIn(NO_CHANGES, page)

    def test_a_line_of_ten_files_is_not_folded(self):
        page = self.page_of(self.files(10, '1'), self.files(10, '2'))
        self.assertIn('10 other files changed, not read: library/types/F/T0/T0.libint, ', page)
        self.assertNotIn('<summary>10 other files', page)


class WhatIsNamed(Commit):
    def test_a_workbook_and_a_data_file_of_a_full_export_are_named_in_place_of_no_changes(self):
        self.commit(MARKS)
        _write_bytes(self.repo, 'project/texts/texts.xlsx', b'PK\x03\x04\xff\xfe one')
        _write_bytes(self.repo, 'project/alarmclasses/classes.dat', b'\x00\xff one')
        self.commit({})
        _write_bytes(self.repo, 'project/texts/texts.xlsx', b'PK\x03\x04\xff\xfe two')
        _write_bytes(self.repo, 'project/alarmclasses/classes.dat', b'\x00\xff two')
        self.commit({})
        got = _report('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual(got['otherFiles'], ['project/alarmclasses/classes.dat', 'project/texts/texts.xlsx'])
        page = _page('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertIn('2 other files changed, not read: project/alarmclasses/classes.dat, project/texts/texts.xlsx', page)
        self.assertNotIn(NO_CHANGES, page)

    def test_the_line_reads_for_one_file(self):
        self.commit(dict(MARKS, **{MASTER_COPIES: '[]'}))
        self.commit({MASTER_COPIES: '[1]'})
        page = _page('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertIn('1 other file changed, not read: %s' % MASTER_COPIES, page)
        self.assertNotIn(NO_CHANGES, page)

    def test_a_new_and_a_deleted_file_count(self):
        self.assertEqual(self.others({'project/a.dat': 'a'}, {'project/a.dat': None, 'project/b.dat': 'b'}),
                         ['project/a.dat', 'project/b.dat'])

    def test_it_stands_beside_a_change_that_is_shown(self):
        self.commit(dict(MARKS, **{'plc/blocks/A.s7dcl': SRC, MASTER_COPIES: '[]'}))
        self.commit({'plc/blocks/A.s7dcl': CHANGED, MASTER_COPIES: '[1]'})
        page = _page('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertIn('plc/blocks/A', page)
        self.assertIn('1 other file changed, not read', page)

    def test_the_list_on_stdout_names_it(self):
        self.commit(dict(MARKS, **{MASTER_COPIES: '[]'}))
        self.commit({MASTER_COPIES: '[1]'})
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()) as printed:
            main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', os.path.join(out, 'p.html')])
        self.assertIn('not read', printed.getvalue())
        self.assertIn(MASTER_COPIES, printed.getvalue())

    def test_a_block_that_does_not_read_is_named_once(self):
        page = self.page_of({'plc/blocks/A.xml': '<Document><SW.Blocks.FB/></Document>'},
                            {'plc/blocks/A.xml': '<Document><SW.Blocks.FB ID="1"/><broken></Document>'})
        self.assertEqual(1, page.count('plc/blocks/A.xml'))    # as not compared, not on this line too
        self.assertNotIn(NO_CHANGES, page)
        self.assertEqual(_report('--git', self.repo, 'HEAD~1', 'HEAD')['otherFiles'], ['plc/blocks/A.xml'])  # counted

    def test_the_working_tree_counts_a_changed_and_an_untracked_file(self):
        self.commit(dict(MARKS, **{'project/a.dat': 'a', 'project/t.xlsx': 'a', 'library/types/F/L/L.libint': 'a: 1\n'}))
        _put(self.repo, {'project/a.dat': 'b', 'project/new.dat': 'c', 'project/t.xlsx': 'b',
                         'library/types/F/L/L.libint': 'a: 2\n'})
        self.assertEqual(_report('--git', self.repo, 'HEAD')['otherFiles'],
                         ['library/types/F/L/L.libint', 'project/a.dat', 'project/new.dat', 'project/t.xlsx'])

    def test_two_inputs_name_a_file_once(self):
        self.commit(dict(MARKS, **{MASTER_COPIES: '[]'}))
        self.commit({MASTER_COPIES: '[1]'})
        got = _report('--git', self.repo, 'HEAD~1', 'HEAD', '--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual(got['otherFiles'], [MASTER_COPIES])

    def test_a_revision_of_a_folder_in_a_repo_names_it_from_that_folder(self):
        self.commit({'sub/plc/.gitkeep': '', 'sub/plc/x.dat': 'a'})
        self.commit({'sub/plc/x.dat': 'b'})
        got = _report('--git', os.path.join(self.repo, 'sub'), 'HEAD~1', 'HEAD')
        self.assertEqual(got['otherFiles'], ['plc/x.dat'])


class WhatStaysSilent(Commit):
    def assert_silent(self, first, then, *args):
        got = self.report_of(first, then, *args)
        self.assertNotIn('otherFiles', got)
        return got

    def test_a_file_only_its_export_time_differs_in(self):
        self.assert_silent({'plc/watchtables/W.xml': WATCH % ('2026-01-01', 'W')},
                           {'plc/watchtables/W.xml': WATCH % ('2026-02-02', 'W')})
        self.assertIn(NO_CHANGES, _page('--git', self.repo, 'HEAD~1', 'HEAD'))

    def test_a_real_change_beside_the_export_time_is_named(self):
        self.assertEqual(self.others({'plc/watchtables/W.xml': WATCH % ('2026-01-01', 'W')},
                                     {'plc/watchtables/W.xml': WATCH % ('2026-02-02', 'W2')}),
                         ['plc/watchtables/W.xml'])

    def test_the_creation_date_on_a_root_stays_silent(self):
        self.assert_silent({'project/alarmclasses/a.xml': ALARMS % ('2.0', '2026-01-01T00:00:00Z', 'A')},
                           {'project/alarmclasses/a.xml': ALARMS % ('2.0', '2026-02-02T00:00:00Z', 'A')})

    def test_anything_else_of_such_a_file_is_named(self):
        for b, a in ((('2.0', 'D', 'A'), ('2.0', 'D', 'B')), (('2.0', 'D', 'A'), ('3.0', 'D', 'A'))):
            with self.subTest(after=a):
                self.assertEqual(self.others({'project/alarmclasses/a.xml': ALARMS % b},
                                             {'project/alarmclasses/a.xml': ALARMS % a}), ['project/alarmclasses/a.xml'])

    def test_a_creation_date_inside_such_a_file_is_named(self):
        doc = '<Root><AlarmClass Name="A" CreationDate="%s" /></Root>'
        self.assertEqual(self.others({'project/a.xml': doc % '1'}, {'project/a.xml': doc % '2'}), ['project/a.xml'])

    def dat_named(self, first, then):
        """otherFiles of a commit that takes a .dat from `first` to `then`, its bytes."""
        self.commit(MARKS)
        for data in (first, then):
            _write_bytes(self.repo, DAT, data)
            self.commit({})
        return _report('--git', self.repo, 'HEAD~1', 'HEAD').get('otherFiles', [])

    def test_a_zipped_dat_only_the_creation_date_on_its_root_differs_in(self):
        self.assertEqual(self.dat_named(_zip_of(c=ALARMS % ('2.0', '2026-01-01T00:00:00Z', 'A')),
                                        _zip_of(c=ALARMS % ('2.0', '2026-02-02T00:00:00Z', 'A'))), [])

    def test_another_text_in_a_zipped_dat_is_named(self):
        self.assertEqual(self.dat_named(_zip_of(c=ALARMS % ('2.0', 'D', 'A')), _zip_of(c=ALARMS % ('2.0', 'D', 'B'))), [DAT])

    def test_a_file_more_in_a_zipped_dat_is_named(self):
        self.assertEqual(self.dat_named(_zip_of(c=ALARMS % ('2.0', 'D', 'A')),
                                        _zip_of(c=ALARMS % ('2.0', 'D', 'A'), d='x')), [DAT])

    def test_another_file_name_in_a_zipped_dat_is_named(self):
        self.assertEqual(self.dat_named(_zip_of(c=ALARMS % ('2.0', 'D', 'A')), _zip_of(d=ALARMS % ('2.0', 'D', 'A'))), [DAT])

    def test_a_dat_that_is_no_zip_any_more_is_named(self):
        self.assertEqual(self.dat_named(_zip_of(c=ALARMS % ('2.0', 'D', 'A')), b'\x00\xff'), [DAT])

    def test_a_file_outside_the_export_folders(self):
        self.assert_silent({'logs/a.json': '1', 'changes/a.md': '1', 'tiabridge.json': '1', 'library/changes/1/a.json': '1'},
                           {'logs/a.json': '2', 'changes/a.md': '2', 'tiabridge.json': '2', 'library/changes/1/a.json': '2'})

    def test_what_the_report_reads(self):
        plant = table('Plant', tag('Run'))
        got = self.assert_silent({'plc/blocks/A.s7dcl': SRC, 'plc/blocks/A.s7res': 'a: 1\n', 'plc/tags/Plant.xml': plant},
                                 {'plc/blocks/A.s7dcl': CHANGED, 'plc/blocks/A.s7res': 'a: 2\n',
                                  'plc/tags/Plant.xml': plant.replace('%M0.0', '%M0.1')})
        self.assertEqual([t['name'] for t in got['plcTags']], ['Plant'])

    def test_a_tag_table_that_does_not_read_stands_on_the_page_alone(self):
        self.assert_silent({'plc/tags/Plant.xml': table('Plant', tag('Run'))}, {'plc/tags/Plant.xml': '<Document>'})

    def test_an_hmi_document_and_a_graphic(self):
        self.assert_silent({'hmi/screens/S.xml': SCREEN % 1, 'project/graphics/G.xml': '<Document><X/></Document>',
                            'project/graphics/G files/G.png': 'a'},
                           {'hmi/screens/S.xml': SCREEN % 2, 'project/graphics/G.xml': '<Document><Y/></Document>',
                            'project/graphics/G files/G.png': 'b'})

    def test_the_generator_s_documents_and_the_references_of_the_hmi_folder(self):
        paths = ('hmi/generated/generated.json', 'hmi/generated/screens/S.xml', 'hmi/references/R.xml',
                 'hmi/Panel/generated/planned.json')
        self.assert_silent({p: '1' for p in paths}, {p: '2' for p in paths})

    def test_the_lists_of_the_hmi_folder_and_of_a_device_stay_silent(self):
        paths = ('hmi/graphics.json', 'hmi/panel.json', 'hmi/handbuilt.json', 'hmi/Panel/graphics.json',
                 'hmi/Panel/panel.json', 'hmi/Panel/handbuilt.json')
        self.assert_silent({p: '1' for p in paths}, {p: '2' for p in paths})

    def test_another_file_of_the_hmi_folder_is_named(self):
        self.assertEqual(self.others({'hmi/notes.json': '1', 'hmi/a/b/panel.json': '1'},
                                     {'hmi/notes.json': '2', 'hmi/a/b/panel.json': '2'}),
                         ['hmi/a/b/panel.json', 'hmi/notes.json'])

    def test_a_generated_document_the_report_reads_is_not_named_and_the_rest_of_the_folder_stays_silent(self):
        self.assert_silent({'hmi/screens/S.xml': SCREEN % 1, 'hmi/generated/screens/S.xml': SCREEN % 1},
                           {'hmi/generated/screens/S.xml': SCREEN % 2}, '--after-set', 'generated')


class LibraryFiles(Commit):
    def type_files(self, version='0.0.1', author='A', guid='g', depends='', hash_='h', comment=None):
        return {TYPE + '.s7dcl': SRC, TYPE + '.libinfo': LIBINFO % (version, author) + (COMMENT % comment if comment else ''),
                TYPE + '.libint': LIBINT % (hash_, hash_, guid, depends)}

    def test_only_the_hashes_of_a_libint_stay_silent(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(hash_='other')), [])

    def test_a_libint_that_depends_on_another_version_with_no_new_version_is_named(self):
        self.assertEqual(self.others(self.type_files(depends=DEPENDS % '0.0.2'), self.type_files(depends=DEPENDS % '0.0.3')),
                         [TYPE + '.libint'])

    def test_a_new_version_tells_its_libinfo_and_its_libint_guid(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(version='0.0.2', guid='other')), [])

    def test_a_new_version_that_depends_on_another_names_the_libint(self):
        self.assertEqual(self.others(self.type_files(depends=DEPENDS % '1'),
                                     self.type_files(version='0.0.2', guid='other', depends=DEPENDS % '2')),
                         [TYPE + '.libint'])

    def test_another_guid_on_the_same_version_is_named(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(guid='other')), [TYPE + '.libint'])

    def test_another_author_on_the_same_version_is_named(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(author='B')), [TYPE + '.libinfo'])

    def moved(self, files):
        """The files of a type, at the folder G in place of F."""
        return {path.replace('/F/', '/G/'): text for path, text in files.items()}

    def report_of_a_move(self, first, then):
        return self.report_of(first, dict({path: None for path in first}, **self.moved(then)))

    def test_a_moved_type_with_nothing_else_lists_its_block_alone(self):
        got = self.report_of_a_move(self.type_files(), self.type_files())
        self.assertEqual([b['state'] for b in got['blocks']], ['moved'])
        self.assertNotIn('otherFiles', got)

    def test_a_moved_type_with_a_new_version_tells_them(self):
        got = self.report_of_a_move(self.type_files(), self.type_files(version='0.0.2', guid='other'))
        self.assertNotIn('otherFiles', got)

    def test_a_release_comment_that_differs_on_a_moved_type_is_named_at_its_new_path(self):
        got = self.report_of_a_move(self.type_files(comment='one'), self.type_files(comment='two'))
        self.assertEqual(got['otherFiles'], ['library/types/G/T/T.libinfo'])

    def test_a_release_comment_that_differs_on_a_moved_new_version_stays_silent(self):
        got = self.report_of_a_move(self.type_files(comment='one'), self.type_files(version='0.0.2', guid='other', comment='two'))
        self.assertNotIn('otherFiles', got)

    def test_a_moved_type_that_depends_on_another_version_is_named_at_its_new_path(self):
        got = self.report_of_a_move(self.type_files(depends=DEPENDS % '1'), self.type_files(depends=DEPENDS % '2'))
        self.assertEqual(got['otherFiles'], ['library/types/G/T/T.libint'])

    def test_a_new_version_that_is_no_longer_the_default_is_named(self):
        version = dict(self.type_files(version='0.0.2', guid='other'))
        version[TYPE + '.libinfo'] = version[TYPE + '.libinfo'].replace('  IsDefault: true\n', '')
        self.assertEqual(self.others(self.type_files(), version), [TYPE + '.libinfo'])

    def test_a_version_put_in_work_tells_its_default_going(self):
        version = dict(self.type_files(version='0.0.2', guid='other'))
        version[TYPE + '.libinfo'] = version[TYPE + '.libinfo'].replace('IsDefault: true', 'InWork: true')
        self.assertEqual(self.others(self.type_files(), version), [])

    def test_a_libint_that_does_not_read_is_named(self):
        self.assertEqual(self.others(self.type_files(), {TYPE + '.libint': 'X: 2026-13-45\n'}), [TYPE + '.libint'])

    def test_only_the_hashes_of_a_libint_beside_a_block_that_does_not_read_stay_silent(self):
        files = dict(self.type_files(), **{TYPE + '.s7dcl': 'not a block'})
        self.assertEqual(self.others(files, {TYPE + '.libint': LIBINT % ('other', 'other', 'g', '')}), [])

    def test_a_new_version_by_another_author_tells_its_libinfo(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(version='0.0.2', guid='other', author='B')), [])

    def test_a_new_version_with_the_same_release_comment_tells_its_libinfo(self):
        self.assertEqual(self.others(self.type_files(comment='one'), self.type_files(version='0.0.2', guid='other', comment='one')),
                         [])

    def test_a_release_comment_that_differs_on_a_new_version_stays_silent(self):
        self.assertEqual(self.others(self.type_files(comment='one'), self.type_files(version='0.0.2', guid='other', comment='two')),
                         [])

    def test_a_release_comment_a_new_version_gains_stays_silent(self):
        self.assertEqual(self.others(self.type_files(), self.type_files(version='0.0.2', guid='other', comment='one')), [])

    def test_a_release_comment_that_differs_on_a_version_put_in_work_stays_silent(self):
        files = self.type_files(comment='two')
        files[TYPE + '.libinfo'] = files[TYPE + '.libinfo'].replace('IsDefault: true', 'InWork: true')
        self.assertEqual(self.others(self.type_files(comment='one'), files), [])

    def test_a_release_comment_that_differs_on_a_new_version_beside_a_block_that_does_not_read_is_named(self):
        unread = dict(self.type_files(comment='one'), **{TYPE + '.s7dcl': 'not a block'})
        self.assertEqual(self.others(unread, {TYPE + '.libinfo': LIBINFO % ('0.0.2', 'A') + COMMENT % 'two'}), [TYPE + '.libinfo'])

    def test_something_else_that_differs_beside_a_release_comment_on_a_new_version_is_named(self):
        version = dict(self.type_files(version='0.0.2', guid='other', comment='two'))
        version[TYPE + '.libinfo'] = version[TYPE + '.libinfo'].replace('  IsDefault: true\n', '')
        self.assertEqual(self.others(self.type_files(comment='one'), version), [TYPE + '.libinfo'])

    def test_a_release_comment_that_differs_alone_is_named(self):
        self.assertEqual(self.others(self.type_files(comment='one'), self.type_files(comment='two')), [TYPE + '.libinfo'])

    def test_a_version_beside_a_block_that_does_not_read_is_named(self):
        got = self.report_of(dict(self.type_files(), **{TYPE + '.s7dcl': 'not a block'}),
                             {TYPE + '.libinfo': LIBINFO % ('0.0.2', 'A')})
        self.assertEqual(got['otherFiles'], [TYPE + '.libinfo'])
        self.assertEqual(got['blocks'], [])
        self.assertNotIn(NO_CHANGES, _page('--git', self.repo, 'HEAD~1', 'HEAD'))

    def test_a_new_version_beside_a_block_that_does_not_read_names_its_libint_too(self):
        got = self.report_of(dict(self.type_files(), **{TYPE + '.s7dcl': 'not a block'}),
                             {TYPE + '.libinfo': LIBINFO % ('0.0.2', 'A'), TYPE + '.libint': LIBINT % ('h', 'h', 'other', '')})
        self.assertEqual(got['otherFiles'], [TYPE + '.libinfo', TYPE + '.libint'])

    def test_a_new_type_whose_block_does_not_read_names_its_files_once(self):
        page = self.page_of({}, dict(self.type_files(), **{TYPE + '.s7dcl': 'not a block'}))
        for ext in ('.libinfo', '.libint', '.s7dcl'):    # on this line, or the block as not compared
            self.assertEqual(1, page.count(TYPE + ext), ext)
        self.assertNotIn(NO_CHANGES, page)

    def test_the_texts_of_a_block_that_does_not_read_are_named(self):
        got = self.report_of({'plc/blocks/A.s7dcl': 'not a block', 'plc/blocks/A.s7res': 'a: 1\n'},
                             {'plc/blocks/A.s7res': 'a: 2\n'})
        self.assertEqual(got['otherFiles'], ['plc/blocks/A.s7res'])
        self.assertNotIn(NO_CHANGES, _page('--git', self.repo, 'HEAD~1', 'HEAD'))

    def test_a_new_type_lists_its_block_alone(self):
        self.assertEqual(self.others({}, self.type_files()), [])

    def test_a_deleted_type_lists_its_block_alone(self):
        self.assertEqual(self.others(self.type_files(), {p: None for p in self.type_files()}), [])

    def test_a_libint_with_no_block_beside_it_is_named(self):
        self.assertEqual(self.others({'library/types/F/L/L.libint': 'a: 1\n'}, {'library/types/F/L/L.libint': 'a: 2\n'}),
                         ['library/types/F/L/L.libint'])

    def test_a_libint_that_is_no_mapping_is_named(self):
        files = self.type_files()
        self.assertEqual(self.others(files, {TYPE + '.libint': '- [unclosed'}), [TYPE + '.libint'])


class Damaged(Commit):
    def test_an_xml_with_an_unknown_encoding_is_named(self):
        doc = '<?xml version="1.0" encoding="bogus"?><Document><a>%d</a></Document>'
        self.assertEqual(self.others({'plc/watchtables/W.xml': doc % 1}, {'plc/watchtables/W.xml': doc % 2}),
                         ['plc/watchtables/W.xml'])

    def test_a_dat_the_zip_reader_fails_on_is_named(self):
        with mock.patch('TiaChangeReports.otherfiles.zipfile.ZipFile', side_effect=ValueError('negative seek value')):
            self.assertEqual(self.others({DAT: '1'}, {DAT: '2'}), [DAT])


class WhatIsAsked(Commit):
    FILES = {'hmi/notes.json': '1', 'project/a.dat': '1'}
    THEN = {'hmi/notes.json': '2', 'project/a.dat': '2'}

    def test_only_plc_leaves_out_the_hmi_folders(self):
        self.assertEqual(self.others(self.FILES, self.THEN, '--only', 'plc'), ['project/a.dat'])

    def test_only_hmi_leaves_out_the_rest(self):
        self.assertEqual(self.others(self.FILES, self.THEN, '--only', 'hmi'), ['hmi/notes.json'])

    def test_a_named_block_has_no_line(self):
        files = dict(self.FILES, **{'plc/blocks/A.s7dcl': SRC})
        self.assertEqual(self.others(files, self.THEN, '--block', 'A'), [])


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.before, self.after = os.path.join(self.tmp.name, 'b'), os.path.join(self.tmp.name, 'a')

    def others(self, before, after):
        _put(self.before, before)
        _put(self.after, after)
        return _report(self.before, self.after).get('otherFiles', [])

    def test_a_plain_folder_names_any_changed_file_it_does_not_read(self):
        self.assertEqual(self.others({'a.s7dcl': SRC, 'notes.txt': '1', 'same.txt': 's', 'gone.txt': 'g'},
                                     {'a.s7dcl': SRC, 'notes.txt': '2', 'same.txt': 's', 'new.txt': 'n'}),
                         ['gone.txt', 'new.txt', 'notes.txt'])

    def test_an_export_folder_of_some_parts_counts_its_export_folders_alone(self):
        before, after = {'plc/blocks/A.s7dcl': SRC}, {'plc/blocks/A.s7dcl': SRC}
        for side, text in ((before, '1'), (after, '2')):
            side.update({'logs/run.json': text, 'tiabridge.json': text, 'plc/watchtables/W.dat': text})
        self.assertEqual(self.others(before, after), ['plc/watchtables/W.dat'])

    def test_a_zipped_dat_of_two_folders_only_the_creation_date_differs_in(self):
        for side, date in ((self.before, '2026-01-01T00:00:00Z'), (self.after, '2026-02-02T00:00:00Z')):
            _put(side, {'a.s7dcl': SRC})
            _write_bytes(side, 'c.dat', _zip_of(c=ALARMS % ('2.0', date, 'A')))
        self.assertEqual(_report(self.before, self.after).get('otherFiles', []), [])

    def test_a_file_of_an_export_folder_that_cannot_be_opened_is_named(self):
        names = ['library/types/F/T/T.libinfo', 'plc/watchtables/W.xml', 'project/c.dat', 'project/c.xlsx']
        _put(self.before, dict({'plc/blocks/A.s7dcl': SRC}, **{name: 'one' for name in names}))
        _put(self.after, dict({'plc/blocks/A.s7dcl': SRC}, **{name: 'two' for name in names}))
        with _cannot_open(*(os.path.join(self.after, name.replace('/', os.sep)) for name in names)):
            page = _page(self.before, self.after)
            self.assertEqual(_report(self.before, self.after)['otherFiles'], names)
        for name in names:                               # on this line, or as not compared
            self.assertEqual(1, page.count(name), name)
        self.assertNotIn(NO_CHANGES, page)

    def test_a_file_as_input_has_no_line(self):
        _put(self.tmp.name, {'x.s7dcl': SRC, 'y.s7dcl': CHANGED})
        got = _report(os.path.join(self.tmp.name, 'x.s7dcl'), os.path.join(self.tmp.name, 'y.s7dcl'))
        self.assertNotIn('otherFiles', got)


if __name__ == '__main__':
    unittest.main()
