"""An object is named on the report as TIA names it, not by its file's name, which is that name made file-safe."""
import unittest

from TiaChangeReports.compare import Callees
from TiaChangeReports.names import file_safe
from TiaChangeReports.source import GitSnapshot
from TiaChangeReports.tests.test_export_roots import Repo, _page, _report

FC = '{ S7_Optimized := "TRUE" }\nFUNCTION "zzNs:Block" : Void\n    VAR_INPUT\n        a : Bool;\n    END_VAR\nBEGIN\nEND_FUNCTION\n'
TYPE_PATH = 'library/types/zzBm/zzNs_Block/zzNs_Block.s7dcl'
MARKS = {'plc/.gitkeep': '', 'library/.gitkeep': ''}


def udt(head):
    return 'TYPE\n%s : STRUCT\n        x : Bool;\n    END_STRUCT;\nEND_TYPE\n' % head


class Names(Repo):
    def setUp(self):
        super().setUp()
        self.commit(MARKS)

    def report_of_the_commit(self, files):
        self.commit(files)
        return _report('--git', self.repo, 'HEAD~1', 'HEAD'), _page('--git', self.repo, 'HEAD~1', 'HEAD')

    def named(self, files):
        return [b['name'] for b in self.report_of_the_commit(files)[0]['blocks']]

    def test_a_new_type_with_a_colon_reads_as_its_document_declares_it(self):
        result, page = self.report_of_the_commit({TYPE_PATH: FC})
        self.assertEqual([b['name'] for b in result['blocks']], ['zzNs:Block'])
        self.assertIn('<title>zzNs:Block changes</title>', page)
        self.assertIn('<span class="nm">zzNs:Block</span>', page)
        self.assertIn('<b>zzNs:Block [FC]</b>', page)
        self.assertNotIn('<span class="nm">zzNs_Block', page)

    def test_a_program_block_with_a_colon_too(self):
        self.assertEqual(self.named({'plc/blocks/zzNs_Block.s7dcl': FC}), ['zzNs:Block'])

    def test_a_file_of_another_case_is_named_by_it_all_the_same(self):
        self.assertEqual(self.named({'plc/blocks/zzns_block.s7dcl': FC}), ['zzNs:Block'])

    def test_its_file_stays_on_the_page_where_it_is_a_path(self):
        self.assertIn(TYPE_PATH, self.report_of_the_commit({TYPE_PATH: FC})[1])

    def test_a_summary_link_holds_the_name_encoded(self):
        """Not read as network 12 of block Ns: the address of a network is the block's and /12."""
        page = self.report_of_the_commit({'plc/blocks/Ns_12.s7dcl': FC.replace('zzNs:Block', 'Ns/12'),
                                          'plc/blocks/Other.s7dcl': FC.replace('zzNs:Block', 'Other')})[1]
        self.assertIn('<a href="#blk-Ns%2F12">Ns/12</a>', page)

    def test_a_type_whose_document_declares_its_instance_keeps_the_types_name(self):
        declared = FC.replace('zzNs:Block', 'Trolley_1')
        self.assertEqual(self.named({'library/types/Trolley/Trolley.s7dcl': declared}), ['Trolley'])

    def test_a_type_with_a_colon_whose_document_declares_its_instance_reads_by_its_file(self):
        """Its name is in no export, and taking _1 off would be a guess: this one still reads file-safe."""
        declared = FC.replace('zzNs:Block', 'zzNs:Block_1')
        self.assertEqual(self.named({TYPE_PATH: declared}), ['zzNs_Block'])

    def test_a_block_of_the_types_file_safe_name_is_another_object(self):
        """The same change in both: each stays on the page under its own name, neither the other's library type."""
        block = FC.replace('zzNs:Block', 'zzNs_Block')
        self.commit({TYPE_PATH: FC, 'plc/blocks/zzNs_Block.s7dcl': block})
        result = self.report_of_the_commit({TYPE_PATH: FC.replace('a : Bool', 'a : Int'),
                                            'plc/blocks/zzNs_Block.s7dcl': block.replace('a : Bool', 'a : Int')})[0]
        self.assertEqual(sorted((b['name'], 'libraryType' in b) for b in result['blocks']),
                         [('zzNs:Block', False), ('zzNs_Block', False)])

    def test_a_name_holding_a_quote_reads_with_it(self):
        """The row's name only. A quote in a name is not handled as a whole, and no real export holds one."""
        self.assertEqual(self.named({'plc/blocks/a_b.s7dcl': FC.replace('zzNs:Block', 'a""b')}), ['a"b'])

    def test_a_program_block_names_the_library_type_of_its_change_as_declared(self):
        self.commit({TYPE_PATH: FC, 'plc/blocks/zzNs_Block.s7dcl': FC})
        changed = FC.replace('a : Bool', 'a : Int')
        result, page = self.report_of_the_commit({TYPE_PATH: changed, 'plc/blocks/zzNs_Block.s7dcl': changed})
        self.assertEqual([(b['name'], b['libraryType']['name']) for b in result['blocks']], [('zzNs:Block', 'zzNs:Block')])
        self.assertIn('library type zzNs:Block', page)

    def test_a_block_given_the_colon_is_a_rename_on_one_file(self):
        self.commit({'plc/blocks/zzNs_Block.s7dcl': FC.replace('zzNs:Block', 'zzNs_Block')})
        result = self.report_of_the_commit({'plc/blocks/zzNs_Block.s7dcl': FC})[0]
        self.assertEqual([(b['name'], b['was']) for b in result['blocks']], [('zzNs:Block', 'zzNs_Block')])

    def test_either_name_selects_it(self):
        self.commit({TYPE_PATH: FC})
        self.commit({TYPE_PATH: FC.replace('a : Bool', 'a : Int')})
        for name in ('zzNs:Block', 'zzNs_Block'):
            result = _report('--git', self.repo, 'HEAD~1', 'HEAD', '--block', name)
            self.assertEqual([b['name'] for b in result['blocks']], ['zzNs:Block'])

    def test_either_name_selects_a_data_type_too(self):
        path = 'plc/types/zzNs_Data.s7dcl'
        self.commit({path: udt('    "zzNs:Data"')})
        self.commit({path: udt('    "zzNs:Data"').replace('x : Bool', 'x : Int')})
        for name in ('zzNs:Data', 'zzNs_Data'):
            result = _report('--git', self.repo, 'HEAD~1', 'HEAD', '--block', name)
            self.assertEqual(([b['name'] for b in result['blocks']], result.get('unmatched')), (['zzNs:Data'], None))

    def test_both_names_of_a_data_type_given_are_both_found(self):
        path = 'plc/types/zzNs_Data.s7dcl'
        self.commit({path: udt('    "zzNs:Data"')})
        self.commit({path: udt('    "zzNs:Data"').replace('x : Bool', 'x : Int')})
        result = _report('--git', self.repo, 'HEAD~1', 'HEAD', '--block', 'zzNs_Data', '--block', 'zzNs:Data')
        self.assertEqual(([b['name'] for b in result['blocks']], result.get('unmatched')), (['zzNs:Data'], None))

    def test_a_data_type_declares_its_name_on_the_line_after_TYPE(self):
        self.assertEqual(self.named({'plc/types/zzNs_Data.s7dcl': udt('    "zzNs:Data"')}), ['zzNs:Data'])

    def test_behind_the_pragma_block_of_a_safety_data_type_too(self):
        self.assertEqual(self.named({'plc/types/zzNs_Data.s7dcl': udt('{ S7_Safety := "True" }\n    "zzNs:Data"')}),
                         ['zzNs:Data'])

    def test_a_simaticml_export_reads_as_it_declares_itself(self):
        xml = ('<Document><SW.Blocks.OB ID="0"><AttributeList><Name>zzNs:Ob</Name><Number>123</Number>'
               '<ProgrammingLanguage>LAD</ProgrammingLanguage></AttributeList></SW.Blocks.OB></Document>')
        self.assertEqual(self.named({'plc/blocks/zzNs_Ob.xml': xml}), ['zzNs:Ob'])


class ColonInItsOwnName(Repo):
    """The colon of `"Ns:Db" : "Fb"` that says what the block is of comes after its name, not in it."""
    FB = 'FUNCTION_BLOCK "zzNs:Fb"\nVAR\n    a : Bool;\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK\n'
    UDT = udt('    "zzNs:Udt"')

    def setUp(self):
        super().setUp()
        self.commit(dict(MARKS, **{'plc/blocks/zzNs_Fb.s7dcl': self.FB, 'plc/types/zzNs_Udt.s7dcl': self.UDT}))

    def kind_of(self, decl):
        self.commit({'plc/blocks/zzNs_Db.s7dcl': 'DATA_BLOCK %s\nVAR\n    a : Bool;\nEND_VAR\nBEGIN\nEND_DATA_BLOCK\n' % decl})
        return [(b['name'], b['kind']) for b in _report('--git', self.repo, 'HEAD~1', 'HEAD')['blocks']]

    def test_a_global_db_is_no_instance_db(self):
        self.assertEqual(self.kind_of('"zzNs:Db"'), [('zzNs:Db', 'DB')])

    def test_a_db_of_a_data_type_is_a_global_db(self):
        self.assertEqual(self.kind_of('"zzNs:Db" : "zzNs:Udt"'), [('zzNs:Db', 'DB')])

    def test_an_instance_db_is_one(self):
        self.assertEqual(self.kind_of('"zzNs:Db" : "zzNs:Fb"'), [('zzNs:Db', 'Instance DB')])

    def test_a_quote_in_its_name_does_not_end_it(self):
        """What the declaration says it is of, only: see test_a_name_holding_a_quote_reads_with_it."""
        self.assertEqual(self.kind_of('"zz""Db" : "zzNs:Fb"')[0][1], 'Instance DB')

    def test_an_instance_db_stands_for_its_fb(self):
        self.commit({'plc/blocks/zzNs_Db.s7dcl': 'DATA_BLOCK "zzNs:Db" : "zzNs:Fb"\nBEGIN\nEND_DATA_BLOCK\n'})
        callees = Callees(GitSnapshot(self.repo, 'HEAD'))
        self.assertEqual(list(callees('zzNs:Db').root.children), ['a'])
        self.assertEqual(list(callees.db('zzNs:Db').interface.root.children), ['a'])
        self.assertEqual(callees.instance_of('zzNs:Db'), '"zzNs:Fb"')

    def test_an_instance_db_renamed_is_one_renamed_block(self):
        values = 'BEGIN\n    a := TRUE;\n    b := TRUE;\n    c := TRUE;\nEND_DATA_BLOCK\n'
        self.commit({'plc/blocks/zzNs_A.s7dcl': 'DATA_BLOCK "zzNs:A" : "zzNs:Fb"\n' + values})
        self.commit({'plc/blocks/zzNs_A.s7dcl': None, 'plc/blocks/zzNs_B.s7dcl': 'DATA_BLOCK "zzNs:B" : "zzNs:Fb"\n' + values,
                     'plc/blocks/New.s7dcl': FC.replace('zzNs:Block', 'New')})      # one on each side would pair anyway
        self.assertEqual(sorted((b['name'], b.get('was')) for b in _report('--git', self.repo, 'HEAD~1', 'HEAD')['blocks']),
                         [('New', None), ('zzNs:B', 'zzNs:A')])

    @staticmethod
    def instance_db_xml(name, of):
        return ('<Document><SW.Blocks.InstanceDB ID="0"><AttributeList><InstanceOfName>%s</InstanceOfName><Name>%s</Name>'
                '<Number>16</Number><ProgrammingLanguage>DB</ProgrammingLanguage></AttributeList></SW.Blocks.InstanceDB></Document>'
                % (of, name))

    def test_a_simaticml_instance_db_renamed_is_told(self):
        self.commit({'plc/blocks/zzNs_A.xml': self.instance_db_xml('zzNs:A', 'zzNs:Fb')})
        self.commit({'plc/blocks/zzNs_A.xml': None, 'plc/blocks/zzNs_B.xml': self.instance_db_xml('zzNs:B', 'zzNs:Fb')})
        self.assertEqual([(b['name'], b.get('was'), b['kind']) for b in _report('--git', self.repo, 'HEAD~1', 'HEAD')['blocks']],
                         [('zzNs:B', 'zzNs:A', 'Instance DB')])

    def test_a_simaticml_instance_db_stands_for_its_fb(self):
        self.commit({'plc/blocks/zzNs_A.xml': self.instance_db_xml('zzNs:A', 'zzNs:Fb')})
        callees = Callees(GitSnapshot(self.repo, 'HEAD'))
        self.assertEqual(list(callees('zzNs:A').root.children), ['a'])
        self.assertEqual(callees.instance_of('zzNs:A'), 'zzNs:Fb')

    def test_a_simaticml_instance_db_of_a_system_block_names_it_unquoted(self):
        """A quote would say a block of the project, and the box would lose the system block's pins (render_lad)."""
        self.commit({'plc/blocks/zzNs_Cam.xml': self.instance_db_xml('zzNs:Cam', 'DQ4_CAM')})
        self.assertEqual(Callees(GitSnapshot(self.repo, 'HEAD')).instance_of('zzNs:Cam'), 'DQ4_CAM')

    def test_a_data_type_renamed_is_one_renamed_block(self):
        self.commit({'plc/types/zzNs_A.s7dcl': udt('    "zzNs:A"')})
        self.commit({'plc/types/zzNs_A.s7dcl': None, 'plc/types/zzNs_B.s7dcl': udt('    "zzNs:B"'),
                     'plc/types/New.s7dcl': udt('    "New"').replace('x : Bool', 'other : Int')})   # one on each side would pair anyway
        self.assertEqual(sorted((b['name'], b.get('was')) for b in _report('--git', self.repo, 'HEAD~1', 'HEAD')['blocks']),
                         [('New', None), ('zzNs:B', 'zzNs:A')])

    def test_a_function_of_a_void_return_has_no_return_row(self):
        self.commit({TYPE_PATH: FC})
        self.commit({TYPE_PATH: FC.replace('a : Bool', 'a : Int')})
        self.assertNotIn('>Return<', _page('--git', self.repo, 'HEAD~1', 'HEAD'))

    def test_a_changed_return_type_shows_under_the_functions_name(self):
        self.commit({TYPE_PATH: FC})
        self.commit({TYPE_PATH: FC.replace(': Void', ': Int')})
        page = _page('--git', self.repo, 'HEAD~1', 'HEAD')
        self.assertIn('</span>zzNs:Block</td><td>Int</td>', page)


class FileSafe(unittest.TestCase):
    def test_known_names(self):
        for name, file in (('Ns:Block', 'Ns_Block'), ('Ns/Data', 'Ns_Data'), ('Block.', 'Block_'), ('Block .', 'Block_'),
                           ('NUL', 'NUL_'), ('nul.txt', 'nul_.txt'), ('COM1', 'COM1_'), ('Console', 'Console'),
                           ('a+b-c=d', 'a+b-c=d')):
            self.assertEqual(file_safe(name), file)


if __name__ == '__main__':
    unittest.main()
