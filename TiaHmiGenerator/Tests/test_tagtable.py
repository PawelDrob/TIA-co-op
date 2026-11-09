"""HMI tag tables: a generated tag table is checked before TIA sees it, as a screen is. An Int tag
with Length 1 ended TIA on import (NonRecoverableException, "Cannot set the length ... The length of the data type is
2"), and HmiDataType Word did too (docs/agent/wincc-comfort-openness.md section 7.2).

The rules through validate(), the builder through a generator run.
"""
import os
import unittest
import xml.etree.ElementTree as ET

import hmipreview
import hmixml
from hmipreview import findingspage, model, validate
from hmipreview.links import open_planned
from Tests.fixture import TP1200, FixtureRepo


def tag(name, data_type, hmi_type=None, length='size', plc=False):
    """One Hmi.Tag.Tag in the shape of a TIA export; length 'size' is the S7 size of an Int, None leaves it out."""
    length = 2 if length == 'size' else length
    attrs = ('<Length>%s</Length>' % length if length is not None else '') + '<Name>%s</Name>' % name
    links = '<AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>'
    if plc:
        links += ('<Connection TargetID="@OpenLink"><Name>Connection_1</Name></Connection>'
                  '<ControllerTag TargetID="@OpenLink"><Name>"Data".%s</Name></ControllerTag>' % name)
    links += '<DataType TargetID="@OpenLink"><Name>%s</Name></DataType>' % data_type
    if hmi_type is not False:
        links += '<HmiDataType TargetID="@OpenLink"><Name>%s</Name></HmiDataType>' % (hmi_type or data_type)
    return ('<Hmi.Tag.Tag ID="1" CompositionName="Tags"><AttributeList>%s</AttributeList><LinkList>%s</LinkList>'
            '</Hmi.Tag.Tag>' % (attrs, links))


def table(name, *tags):
    return ('<?xml version="1.0" encoding="utf-8"?><Document><Engineering version="V20" /><Hmi.Tag.TagTable ID="0">'
            '<AttributeList><Name>%s</Name></AttributeList><ObjectList>%s</ObjectList></Hmi.Tag.TagTable></Document>'
            % (name, ''.join(tags)))


class TagTableRuleTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def found(self, *tags, rel='hmi/generated/tags/New.xml'):
        self.repo.write(rel, table('New', *tags))
        return [f for f in validate(self.repo.path, for_import=True) if f.rule.startswith('tagtable.')]

    def test_an_int_tag_with_length_1_is_refused_naming_the_length_tia_wants(self):
        found = self.found(tag('zzSpeed', 'Int', length=1))
        self.assertEqual([('error', 'hmi/generated/tags/New.xml', 'zzSpeed', 'tagtable.length')],
                         [(f.severity, f.document, f.object, f.rule) for f in found])
        self.assertIn('Length 1', found[0].message)
        self.assertIn('Int is 2', found[0].message)
        self.assertIn('NonRecoverableException', found[0].message)

    def test_tags_of_the_size_their_data_type_has_pass(self):
        self.assertEqual([], self.found(tag('zzSpeed', 'Int'), tag('zzOn', 'Bool', length=1),
                                        tag('zzWord', 'Word', 'UInt', plc=True)))

    def test_a_tag_without_length_is_refused(self):
        self.assertEqual(['tagtable.length'], [f.rule for f in self.found(tag('zzSpeed', 'Int', length=None))])

    def test_hmi_data_type_word_is_refused_naming_uint(self):
        found = self.found(tag('zzWord', 'Word', 'Word', plc=True))
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in found])
        self.assertIn('UInt', found[0].message)
        self.assertIn('was not found', found[0].message)

    def test_a_tag_without_hmi_data_type_is_refused(self):
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in self.found(tag('zzSpeed', 'Int', False))])

    def test_an_hmi_data_type_no_export_shows_is_refused_until_one_does(self):
        found = self.found(tag('zzLevel', 'Real', length=4))
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in found])
        self.assertIn('export a tag table', found[0].message)
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Level', 'Real', length=4, plc=True)))
        self.assertEqual([], self.found(tag('zzLevel', 'Real', length=4)))

    def test_a_hand_built_table_under_tags_does_not_teach_the_crash(self):
        # found by a probe: hand-built tables were imported from hmi/tags before generated/tags, and the one that
        # ended TIA was such a file; it holds an Int tag of Length 1 and an HmiDataType Word on a Word
        crash = (tag('Speed', 'Int', length=1), tag('Status', 'Word', 'Word', length=2, plc=True))
        self.repo.write('hmi/tags/Plant.xml', table('Plant', *crash))
        found = self.found(tag('Speed', 'Int', length=1), tag('Status', 'Word', 'Word', length=2, plc=True),
                           rel='hmi/generated/tags/Plant.xml')
        self.assertEqual([('Speed', 'tagtable.length'), ('Status', 'tagtable.hmi-data-type')],
                         [(f.object, f.rule) for f in found])
        self.assertIn('Int is 2', found[0].message)
        self.assertIn('TIA takes UInt', found[1].message)

    def test_an_export_pairing_an_elementary_type_otherwise_does_not_confirm_it(self):
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Level', 'Real', 'LReal', length=4, plc=True)))
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in self.found(tag('zzLevel', 'Real', 'LReal',
                                                                                      length=4))])
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in self.found(tag('zzLevel', 'Real', length=4))])

    def test_a_data_type_of_unknown_size_is_refused_until_an_export_shows_its_length(self):
        string = 'String[10]'
        found = self.found(tag('zzName', string, 'String', length=12))
        self.assertEqual(['tagtable.hmi-data-type', 'tagtable.length'], [f.rule for f in found])
        self.assertIn('not known', found[1].message)
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Name', string, 'String', length=12, plc=True)))
        self.assertEqual([], self.found(tag('zzName', string, 'String', length=12)))
        self.assertEqual(['tagtable.length'], [f.rule for f in self.found(tag('zzName', string, 'String', length=2))])

    def test_an_array_of_an_elementary_type_is_sized_from_its_bounds_whatever_a_file_says(self):
        # found by a probe: a hand-built file under hmi/tags with the same wrong Length taught it
        array = 'Array [0..1] of Int'
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Pair', array, length=1)))
        found = self.found(tag('zzPair', array, length=1))
        self.assertEqual(['tagtable.length'], [f.rule for f in found])
        self.assertIn('Array [0..1] of Int is 4', found[0].message)
        self.assertEqual([], self.found(tag('zzPair', array, length=4)))
        self.assertEqual([], self.found(tag('zzGrid', 'Array [1..2, 0..2] of Word', 'Array [1..2, 0..2] of UInt',
                                            length=12)))

    def test_an_array_of_bool_or_of_bounds_that_are_no_numbers_is_refused_whatever_a_file_says(self):
        for array in ('Array [0..7] of Bool', 'Array [0..#N] of Int'):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Bits', array, length=1)))
            found = self.found(tag('zzBits', array, length=1))
            self.assertEqual(['tagtable.length'], [f.rule for f in found], array)
            self.assertIn('in TIA', found[0].message)

    def test_an_elementary_type_in_another_case_is_refused_and_teaches_nothing(self):
        # found by a probe: 'int' Length 1 with HmiDataType Int, in a hand-built file and generated
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Speed', 'int', 'Int', length=1)))
        for dtype, want in (('int', 'Write it as Int'), ('array [0..1] of int', 'Write it as Array [0..1] of Int')):
            found = self.found(tag('zzSpeed', dtype, 'Int', length=1))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], dtype)
            self.assertIn(want, found[0].message)

    def test_a_fixed_size_type_outside_elementary_takes_its_s7_size_whatever_a_file_says(self):
        # found by a probe: the same tag with a wrong Length in a hand-built file and generated (Length 1; a
        # Char is 1, so 2)
        for dtype, size, wrong in (('Time', 4, 1), ('Char', 1, 2), ('DTL', 12, 1)):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Value', dtype, length=wrong)))
            found = self.found(tag('zzValue', dtype, length=wrong))
            self.assertIn('tagtable.length', [f.rule for f in found], dtype)
            self.assertIn('%s is %d' % (dtype, size), next(f for f in found if f.rule == 'tagtable.length').message)

    def test_the_hmi_data_type_of_a_fixed_size_type_is_the_one_an_export_of_its_size_pairs_it_with(self):
        found = self.found(tag('zzTime', 'Time', length=4))
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in found])
        # a file whose Length is not the type's size is not TIA's export: it teaches nothing
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Delay', 'Time', length=1)))
        self.assertEqual(['tagtable.hmi-data-type'], [f.rule for f in self.found(tag('zzTime', 'Time', length=4))])
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Delay', 'Time', length=4)))
        self.assertEqual([], self.found(tag('zzTime', 'Time', length=4)))
        # no HmiDataType is assumed: the export's is taken, whatever its name
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Stamp', 'Date_And_Time', 'DateTime', length=8)))
        self.assertEqual([], self.found(tag('zzStamp', 'Date_And_Time', 'DateTime', length=8)))
        self.assertEqual(['tagtable.hmi-data-type'],
                         [f.rule for f in self.found(tag('zzStamp', 'Date_And_Time', length=8))])

    def test_an_array_of_a_fixed_size_type_outside_elementary_is_refused_whatever_a_file_says(self):
        array = 'Array [0..1] of Time'
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Delays', array, length=1)))
        found = [f for f in self.found(tag('zzDelays', array, length=1)) if f.rule == 'tagtable.length']
        self.assertEqual(1, len(found))
        self.assertIn('in TIA', found[0].message)

    def test_another_name_of_a_fixed_size_type_is_refused_and_teaches_nothing(self):
        for dtype, want in (('TOD', 'Time_Of_Day'), ('Date_And_LTime', 'LDT')):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Clock', dtype, length=1)))
            found = self.found(tag('zzClock', dtype, length=1))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], dtype)
            self.assertIn('Write it as %s.' % want, found[0].message)

    def test_a_data_type_that_is_neither_one_the_rule_knows_nor_one_an_export_teaches_is_refused(self):
        # the review's probes: other S7 types of a fixed size, a character no strip() removes
        for dtype in ('Timer', 'HW_IO', 'Int\u200b', '\ufeffInt', 'string[10]', 'String[\uff11\uff10]',
                      'Struct'):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Value', dtype, length=1)))
            found = self.found(tag('zzValue', dtype, length=1))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], repr(dtype))
            self.assertIn('in TIA', found[0].message)

    def test_a_quoted_name_of_a_type_the_rule_holds_is_refused_and_teaches_nothing(self):
        # found by probes: a file and a generated tag with the same quoted S7 type name, Length 1
        for dtype, hmi in (('"Int"', 'Int'), ('"time"', 'Word'), ('"TOD"', 'Time_Of_Day'),
                           ('Array [0..1] of "Int"', 'Array [0..1] of Int')):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Value', dtype, hmi, length=1)))
            found = self.found(tag('zzValue', dtype, hmi, length=1))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], dtype)
            self.assertIn('quoted', found[0].message)

    def test_a_string_and_a_plc_data_type_and_arrays_of_them_are_learned_from_an_export(self):
        types = ('WString[20]', '"Motor_UDT"', 'Array [0..1] of "Motor_UDT"', 'Array [0..3] of String[10]')
        self.repo.write('hmi/tags/Plant.xml', table('Plant', *(tag('T%d' % i, t, length=40, plc=True)
                                                               for i, t in enumerate(types))))
        self.assertEqual([], self.found(*(tag('zz%d' % i, t, length=40) for i, t in enumerate(types))))

    def test_a_data_type_with_white_space_around_it_is_refused_and_teaches_nothing(self):
        # found by a probe: 'Int ' with HmiDataType Int and Length 1, in a hand-built file and generated
        for dtype in ('Int ', '\nInt\n', ' String[10]'):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Speed', dtype, 'Int', length=1)))
            found = self.found(tag('zzSpeed', dtype, 'Int', length=1))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], repr(dtype))
            self.assertIn('white space', found[0].message)
            self.assertIn('Write it as %s' % dtype.strip(), found[0].message)

    def test_an_array_not_written_as_tia_writes_it_is_refused_and_teaches_nothing(self):
        # found by probes, with HmiDataType of the same spelling and Length 4 in a file and generated
        for dtype in ('Array [0..1] of\nInt', 'Array[0..1]of Int', 'Array  [0..1] of Int', 'Array [0..1] of\tInt'):
            self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Pair', dtype, length=4)))
            found = self.found(tag('zzPair', dtype, length=4))
            self.assertEqual(['tagtable.data-type'], [f.rule for f in found], repr(dtype))
            self.assertIn('Write it as Array [0..1] of Int.', found[0].message)

    def test_bounds_of_digits_other_than_ascii_are_not_numbers(self):
        found = self.found(tag('zzPair', 'Array [0..\uff11] of Int', length=4))
        self.assertEqual(['tagtable.length'], [f.rule for f in found])
        self.assertIn('not numbers', found[0].message)

    def test_a_length_of_digits_other_than_ascii_teaches_nothing_and_ends_nothing(self):
        # found by a probe: Length '\u00b2' passed isdigit() and made int() raise
        self.repo.write('hmi/tags/Plant.xml', table('Plant', tag('Level', 'Real', length='\u00b2'),
                                                    tag('Name', 'String[10]', 'String', length='\u0661\u0662')))
        found = self.found(tag('zzLevel', 'Real', length=4), tag('zzName', 'String[10]', 'String', length=12))
        self.assertEqual([('zzLevel', 'tagtable.hmi-data-type'), ('zzName', 'tagtable.length')],
                         [(f.object, f.rule) for f in found])

    def test_an_array_whose_bounds_run_backwards_is_refused_saying_so(self):
        found = self.found(tag('zzPair', 'Array [2..1] of Int', length=4))
        self.assertEqual(['tagtable.length'], [f.rule for f in found])
        self.assertIn('backwards', found[0].message)
        self.assertNotIn('not numbers', found[0].message)

    def test_the_exports_of_other_devices_and_references_teach_too(self):
        self.repo.write('hmi/references/Sister/tags/T.xml', table('T', tag('A', 'Real', length=4)))
        self.assertEqual([], self.found(tag('zzLevel', 'Real', length=4)))

    def test_exports_are_not_checked(self):
        self.assertEqual([], self.found(tag('Speed', 'Int', 'Word', length=1), rel='hmi/tags/Plant.xml'))

    def test_an_unreadable_generated_table_is_an_error(self):
        self.repo.write('hmi/generated/tags/Broken.xml', '<Document><Hmi.Tag.Tag>')
        found = [f for f in validate(self.repo.path) if f.document == 'hmi/generated/tags/Broken.xml']
        self.assertEqual(['document.parse'], [f.rule for f in found])

    def test_the_findings_page_shows_a_tag_table_as_a_document_of_its_own(self):
        self.found(tag('zzSpeed', 'Int', length=1))
        r = model.load(self.repo.path)
        sections = findingspage.page([('', r, validate(self.repo.path), open_planned(r))])['sections']
        s = next(s for s in sections if s['path'] == 'hmi/generated/tags/New.xml')
        self.assertEqual(('tagtable', 'New', False), (s['kind'], s['name'], s['opens']))
        self.assertEqual(['Length does not fit the data type'], [x['title'] for x in s['rules']])

    def test_a_device_folder_is_read_for_its_device(self):
        self.repo.write('hmi/Panel_A/generated/tags/New.xml', table('New', tag('zzSpeed', 'Int', length=1)))
        self.repo.write('hmi/Panel_B/tags/Plant.xml', table('Plant', tag('Speed', 'Int')))
        rules = [f.rule for f in validate(self.repo.path, device='Panel_A') if f.rule.startswith('tagtable.')]
        self.assertEqual(['tagtable.length'], rules)
        self.assertEqual([], [f for f in validate(self.repo.path, device='Panel_B') if f.rule.startswith('tagtable.')])


class TagTableRunTest(unittest.TestCase):
    def make(self):
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        hw = hmipreview.resolution.resolve(TP1200)
        repo.panel(hw.panel, hw.width, hw.height, hw.portrait)
        repo.write('hmi/textlists/T.xml', '<?xml version="1.0" encoding="utf-8"?><Document>'
                   '<Engineering version="V20" /><Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>T</Name></AttributeList><ObjectList>'
                   '<MultilingualText ID="1" CompositionName="Comment"><ObjectList><MultilingualTextItem ID="2" '
                   'CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text /></AttributeList>'
                   '</MultilingualTextItem></ObjectList></MultilingualText></ObjectList>'
                   '</Hmi.TextGraphicList.TextList></Document>')
        return repo

    @staticmethod
    def tags_of(doc):
        out = {}
        for t in doc.iter('Hmi.Tag.Tag'):
            out[t.findtext('AttributeList/Name')] = (
                t.findtext('AttributeList/Length'), t.findtext('LinkList/DataType/Name'),
                t.findtext('LinkList/HmiDataType/Name'), t.findtext('LinkList/ControllerTag/Name'),
                t.findtext('LinkList/Connection/Name'), t.findtext('LinkList/AcquisitionCycle/Name'))
        return out

    def test_the_builder_sets_length_and_hmi_data_type_from_the_data_type(self):
        repo = self.make()
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('Plant', [
            {'name': 'zzSpeed', 'data_type': 'Int', 'cycle': '1 s'},
            {'name': 'zzOn', 'data_type': 'Bool', 'cycle': '1 s'},
            {'name': 'zzStatus', 'data_type': 'Word', 'cycle': '100 ms', 'plc_tag': '"Data".status',
             'connection': 'Connection_1'}])
        rel = hmixml.add('tagtable', doc)
        hmixml.finish()
        self.assertEqual('hmi/generated/tags/Plant.xml', rel)
        written = ET.parse(os.path.join(repo.path, *rel.split('/'))).getroot()
        self.assertEqual({'zzSpeed': ('2', 'Int', 'Int', None, None, '1 s'),
                          'zzOn': ('1', 'Bool', 'Bool', None, None, '1 s'),
                          'zzStatus': ('2', 'Word', 'UInt', '"Data".status', 'Connection_1', '100 ms')},
                         self.tags_of(written))
        # the shape of a TIA export: Comment and DisplayName in the project's languages
        comps = [m.get('CompositionName') for m in written.find('Hmi.Tag.TagTable/ObjectList/Hmi.Tag.Tag/ObjectList')]
        self.assertEqual(['Comment', 'DisplayName'], comps)
        self.assertEqual([], [f for f in validate(repo.path, for_import=True) if f.severity == 'error'])

    def test_the_builder_takes_length_and_hmi_data_type_from_an_export(self):
        repo = self.make()
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Name', 'String[10]', 'String', length=12, plc=True)))
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('New', [{'name': 'zzName', 'data_type': 'String[10]', 'cycle': '1 s'}])
        self.assertEqual(('12', 'String[10]', 'String'), self.tags_of(doc)['zzName'][:3])

    def test_the_builder_sizes_an_array_from_its_bounds(self):
        repo = self.make()
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Pair', 'Array [0..1] of Word', 'Array [0..1] of Word',
                                                            length=1, plc=True)))
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('New', [{'name': 'zzPair', 'data_type': 'Array [0..1] of Word', 'cycle': '1 s'}])
        self.assertEqual(('4', 'Array [0..1] of Word', 'Array [0..1] of UInt'), self.tags_of(doc)['zzPair'][:3])

    def test_the_builder_keeps_to_the_sizes_and_hmi_types_a_hand_built_table_contradicts(self):
        repo = self.make()
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Speed', 'Int', length=1),
                                               tag('Status', 'Word', 'Word', length=2, plc=True)))
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('New', [{'name': 'zzSpeed', 'data_type': 'Int'},
                                       {'name': 'zzStatus', 'data_type': 'Word'}])
        self.assertEqual({'zzSpeed': ('2', 'Int', 'Int'), 'zzStatus': ('2', 'Word', 'UInt')},
                         {k: v[:3] for k, v in self.tags_of(doc).items()})

    def test_the_builder_sizes_a_fixed_size_type_itself_and_takes_its_hmi_data_type_from_an_export(self):
        repo = self.make()
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Delay', 'Time', 'Int', length=1)))
        hmixml.begin(repo.path)
        with self.assertRaises(ValueError) as cm:      # a file of another Length teaches nothing
            hmixml.tag_table('New', [{'name': 'zzDelay', 'data_type': 'Time'}])
        self.assertIn('export', str(cm.exception))
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Delay', 'Time', length=4)))
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('New', [{'name': 'zzDelay', 'data_type': 'Time'}])
        self.assertEqual(('4', 'Time', 'Time'), self.tags_of(doc)['zzDelay'][:3])

    def test_an_internal_tag_without_a_cycle_has_no_acquisition_cycle_as_its_export(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.add('tagtable', hmixml.tag_table('Plant', [{'name': 'zzCount', 'data_type': 'DInt'}]))
        hmixml.finish()
        written = ET.parse(os.path.join(repo.path, 'hmi', 'generated', 'tags', 'Plant.xml')).getroot()
        self.assertEqual({'zzCount': ('4', 'DInt', 'DInt', None, None, None)}, self.tags_of(written))

    def test_the_builder_refuses_a_data_type_of_unknown_size(self):
        repo = self.make()
        hmixml.begin(repo.path)
        with self.assertRaises(ValueError) as cm:
            hmixml.tag_table('New', [{'name': 'zzName', 'data_type': 'String[10]', 'cycle': '1 s'}])
        self.assertIn('String[10]', str(cm.exception))
        self.assertIn('export', str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            hmixml.tag_table('New', [{'name': 'zzBits', 'data_type': 'Array [0..7] of Bool'}])
        self.assertIn('array of Bool', str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            hmixml.tag_table('New', [{'name': 'zzSpeed', 'data_type': 'int'}])
        self.assertIn('Write it as Int', str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            hmixml.tag_table('New', [{'name': 'zzSpeed', 'data_type': 'Int '}])
        self.assertIn('white space', str(cm.exception))

    def test_the_builder_refuses_a_data_type_with_a_final_newline_that_a_file_holds(self):
        # found by a probe: TAUGHT's $ matched before a final newline, and the builder took Length 1
        repo = self.make()
        repo.write('hmi/tags/Plant.xml', table('Plant', tag('Name', 'String[10]\n', length=1)))
        hmixml.begin(repo.path)
        with self.assertRaises(ValueError) as cm:
            hmixml.tag_table('New', [{'name': 'zzS', 'data_type': 'String[10]\n'}])
        self.assertIn('white space', str(cm.exception))

    def test_a_run_with_an_int_tag_of_length_1_is_refused_and_writes_nothing(self):
        repo = self.make()
        hmixml.begin(repo.path)
        doc = hmixml.tag_table('Plant', [{'name': 'zzSpeed', 'data_type': 'Int', 'cycle': '1 s'}])
        next(doc.iter('Length')).text = '1'          # by hand, as the tag that ended TIA
        hmixml.add('tagtable', doc)
        with self.assertRaises(hmixml.GenerationRefused) as cm:
            hmixml.finish()
        self.assertIn(('zzSpeed', 'tagtable.length'), [(f.object, f.rule) for f in cm.exception.findings])
        self.assertFalse(os.path.exists(os.path.join(repo.path, 'hmi', 'generated')))

    def test_generated_dirs_name_the_tag_folder(self):
        repo = self.make()
        self.assertEqual(os.path.join(repo.path, 'hmi', 'generated', 'tags'),
                         hmixml.generated_dirs(repo.path)['tagtable'])


if __name__ == '__main__':
    unittest.main()
