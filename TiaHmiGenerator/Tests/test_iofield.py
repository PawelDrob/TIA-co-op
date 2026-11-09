import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, item


def tag_table(name, *tags):
    """A tag table in the shape of a TIA export: (tag name, HMI data type) of internal tags."""
    rows = ''.join('<Hmi.Tag.Tag ID="1" CompositionName="Tags"><AttributeList><Length>2</Length><Name>%s</Name>'
                   '</AttributeList><LinkList><DataType TargetID="@OpenLink"><Name>%s</Name></DataType>'
                   '<HmiDataType TargetID="@OpenLink"><Name>%s</Name></HmiDataType></LinkList></Hmi.Tag.Tag>'
                   % (tag, dtype, dtype) for tag, dtype in tags)
    return ('<?xml version="1.0" encoding="utf-8"?><Document><Engineering version="V20" /><Hmi.Tag.TagTable ID="0">'
            '<AttributeList><Name>%s</Name></AttributeList><ObjectList>%s</ObjectList></Hmi.Tag.TagTable></Document>'
            % (name, rows))


def io_field(tag='zzT3', pattern='99.99', **attrs):
    connection = ('<ObjectList><Hmi.Screen.Property ID="1" CompositionName="Properties"><AttributeList>'
                  '<Name>ProcessValue</Name></AttributeList><ObjectList><Hmi.Dynamic.TagConnectionDynamic ID="2" '
                  'CompositionName="Dynamic"><AttributeList><Indirect>false</Indirect></AttributeList><LinkList>'
                  '<Tag TargetID="@OpenLink"><Name>%s</Name></Tag></LinkList></Hmi.Dynamic.TagConnectionDynamic>'
                  '</ObjectList></Hmi.Screen.Property></ObjectList>' % tag) if tag else ''
    values = dict(Mode='Output', DataFormat='Decimal', FormatPattern=pattern, FieldLength=len(pattern.lstrip('s')),
                  ShiftDecimalPoint=0)
    values.update(attrs)
    return item('Hmi.Screen.IOField', 'zzIO', connection, full=False, **values)


class FormatPatternTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def found(self, field, tags=(('zzT3', 'Int'),), kind='generated', for_import=False):
        if tags:
            self.repo.write('hmi/tags/Plant.xml', tag_table('Plant', *tags))
        doc = document('screen', 'New', [field], Number=2)
        (self.repo.generated if kind == 'generated' else self.repo.export)('screen', 'New', doc)
        return [f for f in validate(self.repo.path, for_import=for_import) if f.rule.startswith('iofield.')]

    def test_the_pattern_the_compile_refused_on_an_int_tag_is_a_warning_naming_what_was_seen(self):
        found = self.found(io_field())
        self.assertEqual([('warning', 'zzIO', 'iofield.format-pattern')], [(f.severity, f.object, f.rule) for f in found])
        self.assertIn("FormatPattern 99.99 on tag 'zzT3' of type Int", found[0].message)
        self.assertIn('The format pattern of I/O field', found[0].message)
        self.assertIn('Why is not known', found[0].message)

    def test_the_pattern_that_compiled_on_the_same_tag_gets_nothing(self):
        self.assertEqual([], self.found(io_field(pattern='9999')))

    def test_the_import_check_does_not_refuse_it(self):
        # nobody has established what decides it: the compile keeps the last word
        self.assertEqual(['warning'], [f.severity for f in self.found(io_field(), for_import=True)])

    def test_a_decimal_point_on_a_floating_point_tag_gets_nothing(self):
        self.assertEqual([], self.found(io_field(), tags=(('zzT3', 'Real'),)))
        self.assertEqual([], self.found(io_field(), tags=(('zzT3', 'LReal'),)))

    def test_a_signed_pattern_on_an_int_tag_is_warned_about_though_it_was_not_tried(self):
        found = self.found(io_field(pattern='s99.99'))
        self.assertEqual(1, len(found))
        self.assertIn('FormatPattern s99.99', found[0].message)
        self.assertIn('no other pattern or tag type was tried', found[0].message)

    def test_a_tag_of_unknown_type_is_warned_about_and_says_so(self):
        found = self.found(io_field(tag='OnPlc'))
        self.assertEqual(1, len(found))
        self.assertIn("tag 'OnPlc' whose type is not in the tag tables", found[0].message)

    def test_a_generated_tag_table_counts_over_the_export(self):
        self.repo.write('hmi/generated/tags/Plant.xml', tag_table('Plant', ('zzT3', 'Real')))
        self.assertEqual([], self.found(io_field()))

    def test_the_tag_tables_of_the_device_count(self):
        self.repo.write('hmi/Panel_A/tags/Plant.xml', tag_table('Plant', ('zzT3', 'Real')))
        self.repo.write('hmi/Panel_B/tags/Plant.xml', tag_table('Plant', ('zzT3', 'Int')))
        doc = document('screen', 'New', [io_field()], Number=2)
        self.repo.generated('screen', 'New', doc, device='Panel_A')
        self.repo.generated('screen', 'New', doc, device='Panel_B')
        def warned(device):
            return [f.rule for f in validate(self.repo.path, device=device) if f.rule.startswith('iofield.')]
        self.assertEqual([], warned('Panel_A'))
        self.assertEqual(['iofield.format-pattern'], warned('Panel_B'))

    def test_an_unreadable_tag_table_leaves_the_type_unknown(self):
        self.repo.write('hmi/tags/Broken.xml', '<Document><Hmi.Tag.Tag>')
        found = self.found(io_field(), tags=())
        self.assertIn('whose type is not in the tag tables', found[0].message)

    def test_another_data_format_gets_nothing(self):
        self.assertEqual([], self.found(io_field(DataFormat='Hexadecimal')))

    def test_a_field_without_a_tag_gets_nothing(self):
        self.assertEqual([], self.found(io_field(tag=None)))

    def test_exports_are_not_checked(self):
        self.assertEqual([], self.found(io_field(), kind='export'))


if __name__ == '__main__':
    unittest.main()
