import unittest
from unittest import mock

from hmipreview import catalogue, validate
from hmipreview import vocabulary as voc
from Tests.fixture import FixtureRepo, document, item, rect


def fixture_attrs(element, **changes):
    """The attributes of the catalogue fixture's object of that type, with changes."""
    attrs = {a.tag: a.text or '' for a in catalogue.fixture_objects()[element].find('AttributeList')}
    attrs.update(changes)
    return attrs


def by_rule(findings, prefix):
    return [f for f in findings if f.rule.startswith(prefix)]


TEXT_LIST = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20"/>'
             '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>tlNew</Name>%s</AttributeList><ObjectList>'
             '<MultilingualText ID="1" CompositionName="Comment"><ObjectList><MultilingualTextItem ID="2" '
             'CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text/></AttributeList>'
             '</MultilingualTextItem></ObjectList></MultilingualText>'
             '<Hmi.TextGraphicList.TextListEntry ID="3" CompositionName="Entries"><AttributeList><From>0</From><To>0</To>'
             '</AttributeList><ObjectList><MultilingualText ID="4" CompositionName="Text"><ObjectList>'
             '<MultilingualTextItem ID="5" CompositionName="Items"><AttributeList><Culture>en-US</Culture>'
             '<Text>Off</Text></AttributeList></MultilingualTextItem></ObjectList></MultilingualText></ObjectList>'
             '</Hmi.TextGraphicList.TextListEntry></ObjectList></Hmi.TextGraphicList.TextList></Document>\n')


class TextListWithoutReferenceTest(unittest.TestCase):
    """A new project has no text list to copy from: its first generated one passes without a reference export."""

    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def test_a_generated_text_list_needs_no_reference_export(self):
        self.repo.generated('textlist', 'tlNew', TEXT_LIST % '')
        self.assertEqual([], by_rule(validate(self.repo.path), 'vocabulary.'))

    def test_the_range_real_exports_show_passes(self):
        self.repo.generated('textlist', 'tlNew', TEXT_LIST % '<ListRange>Binary</ListRange>')
        self.assertEqual([], by_rule(validate(self.repo.path), 'vocabulary.'))

    def test_a_range_no_export_shows_is_an_error_until_one_does(self):
        path = self.repo.generated('textlist', 'tlNew', TEXT_LIST % '<ListRange>Invented</ListRange>')
        found = by_rule(validate(self.repo.path), 'vocabulary.')
        self.assertEqual([('error', 'vocabulary.value', path)], [(f.severity, f.rule, f.document) for f in found])

    def test_an_attribute_a_text_list_does_not_have_is_still_an_error(self):
        path = self.repo.generated('textlist', 'tlNew', TEXT_LIST % '<Invented>1</Invented>')
        found = by_rule(validate(self.repo.path), 'vocabulary.')
        self.assertEqual([('error', 'vocabulary.attribute', path)], [(f.severity, f.rule, f.document) for f in found])
        self.assertIn('Invented', found[0].message)


class VocabularyTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        # Reference export: a rectangle with two colour values and a text field.
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [
            rect('S-Panel', BackColor='255, 255, 255'),
            rect('S-Dark', BackColor='0, 0, 0'),
            item('Hmi.Screen.TextField', 'S-Title', Left=0, Top=0, Width=10, Height=10, HorizontalAlignment='Left'),
        ], Number=1))

    def vocab(self):
        return by_rule(validate(self.repo.path), 'vocabulary.')

    def test_element_type_neither_in_the_catalogue_nor_in_an_export_is_an_error(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Invented', 'thing1', Left=10, Top=90, Width=50, Height=50)], Number=2))
        found = self.vocab()
        self.assertEqual(1, len(found))
        f = found[0]
        self.assertEqual(('error', 'vocabulary.element-type', path, 'thing1'),
                         (f.severity, f.rule, f.document, f.object))
        self.assertIn('Hmi.Screen.Invented', f.message)

    def test_a_catalogue_type_no_export_holds_passes_when_copied_from_the_fixture(self):
        # The catalogue is the limit, not the project. No export here has a gauge.
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Gauge', 'gauge1', full=False,
                 **fixture_attrs('Hmi.Screen.Gauge', Left=10, Top=90, Width=200, Height=200))], Number=2))
        self.assertEqual([], [f for f in validate(self.repo.path) if f.rule.startswith(('vocabulary.', 'document.'))])

    def test_a_type_no_export_holds_must_carry_the_fixture_attributes(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Gauge', 'gauge1', Left=10, Top=90, Width=50, Height=50)], Number=2))
        found = [f for f in validate(self.repo.path) if f.rule.startswith(('vocabulary.', 'document.'))]
        self.assertEqual([('error', 'document.incomplete', path, 'gauge1')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn('AngleMax', found[0].message)

    def test_attributes_and_values_of_the_catalogue_pass_without_an_export(self):
        # The text field's vertical alignment 'Bottom' and a border width no export shows: catalogue, not exports.
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.TextField', 'title', Left=1, Top=2, Width=3, Height=4, VerticalAlignment='Bottom',
                 BorderWidth=7)], Number=2))
        self.assertEqual([], self.vocab())

    def test_a_number_or_bool_in_the_wrong_form_is_an_error(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', BorderWidth='thick', UseDesignColorSchema='yes')], Number=2))
        found = self.vocab()
        self.assertEqual(['vocabulary.value', 'vocabulary.value'], [f.rule for f in found])
        text = ' '.join(f.message for f in found)
        self.assertIn('not a number', text)
        self.assertIn('not true or false', text)

    def test_a_member_of_tias_enum_not_documented_for_the_object_is_a_warning(self):
        # GraphX.FillStyle has the fill patterns; the rectangle's help documents solid and transparent only.
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', BackFillStyle='Pattern37')], Number=2))
        found = self.vocab()
        self.assertEqual([('warning', 'vocabulary.value', path, 'rect1')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn('GraphX.FillStyle', found[0].message)

    def test_a_help_name_that_is_no_export_spelling_is_an_error(self):
        # The help calls BarOrientation 1 'Bottom'; TIA's enum and the export spell it 'Down'.
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Bar', 'bar1', full=False, **fixture_attrs(
                'Hmi.Screen.Bar', Left=10, Top=90, Width=80, Height=200, BarOrientation='Bottom'))], Number=2))
        found = self.vocab()
        self.assertEqual([('error', 'vocabulary.value')], [(f.severity, f.rule) for f in found])
        self.assertIn("'Down'", found[0].message)

    def test_a_spelling_an_export_shows_passes_even_outside_the_catalogue(self):
        self.repo.export('screen', 'Odd', document('screen', 'Odd', [
            item('Hmi.Screen.TextField', 'S-Odd', Left=0, Top=0, Width=1, Height=1, HorizontalAlignment='Justify')],
            Number=5))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.TextField', 'title', Left=1, Top=2, Width=3, Height=4, HorizontalAlignment='Justify')],
            Number=2))
        self.assertEqual([], self.vocab())

    def test_element_types_seen_in_exports_are_silent(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', BackColor='0, 0, 0'),
            item('Hmi.Screen.TextField', 'title', Left=1, Top=2, Width=3, Height=4)], Number=2))
        self.assertEqual([], self.vocab())

    def test_attribute_name_not_seen_on_that_element_type_is_an_error(self):
        # HorizontalAlignment exists on the text field, not on the rectangle.
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', HorizontalAlignment='Left')], Number=2))
        found = self.vocab()
        self.assertEqual([('error', 'vocabulary.attribute', path, 'rect1')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn('HorizontalAlignment', found[0].message)
        self.assertIn('Hmi.Screen.Rectangle', found[0].message)

    def test_enum_value_neither_in_the_catalogue_nor_in_an_export_is_an_error(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.TextField', 'title', Left=1, Top=2, Width=3, Height=4, HorizontalAlignment='Sideways')],
            Number=2))
        found = self.vocab()
        self.assertEqual([('error', 'vocabulary.value', path, 'title')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn('Sideways', found[0].message)
        self.assertIn('HorizontalAlignment', found[0].message)
        self.assertIn("'Right'", found[0].message)            # the known spellings are listed

    def test_colours_are_free_values(self):
        # The maintainer: "it's just a color" - a colour no export has (here on BackColor and on a range of a colour
        # animation) is data, not a look the exports must show; the attribute name still has to be seen.
        anim = ('<ObjectList><Hmi.Dynamic.RangeAppearanceAnimation ID="0" CompositionName="Animations"><ObjectList>'
                '<Hmi.Dynamic.Range ID="0" CompositionName="RangeValues"><AttributeList><BackColor>%s</BackColor>'
                '<ForeColor>40, 40, 40</ForeColor></AttributeList></Hmi.Dynamic.Range></ObjectList>'
                '</Hmi.Dynamic.RangeAppearanceAnimation></ObjectList>')
        self.repo.export('screen', 'Anim', document('screen', 'Anim', [
            rect('S-Anim', BackColor='0, 0, 0', children=anim % '200, 16, 46')], Number=7))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', BackColor='1, 2, 3', children=anim % '190, 215, 240')], Number=2))
        self.assertEqual([], self.vocab())

    def test_value_seen_on_another_attribute_does_not_count(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('rect1', BorderWidth='255, 255, 255')], Number=2))
        self.assertEqual(['vocabulary.value'], [f.rule for f in self.vocab()])

    def test_geometry_names_text_and_ids_are_exempt_from_the_value_check(self):
        tf = item('Hmi.Screen.TextField', 'brandNewName', Left=777, Top=333, Width=444, Height=55,
                  children='<ObjectList><MultilingualText ID="0" CompositionName="Text"><ObjectList>'
                           '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList>'
                           '<Culture>en-US</Culture><Text><body><p>Never seen</p></body></Text>'
                           '</AttributeList></MultilingualTextItem></ObjectList></MultilingualText></ObjectList>')
        ref = item('Hmi.Screen.TextField', 'S-Text', Left=0, Top=0, Width=1, Height=1,
                   children='<ObjectList><MultilingualText ID="0" CompositionName="Text"><ObjectList>'
                            '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList>'
                            '<Culture>en-US</Culture><Text><body><p>x</p></body></Text>'
                            '</AttributeList></MultilingualTextItem></ObjectList></MultilingualText></ObjectList>')
        self.repo.export('screen', 'Reference2', document('screen', 'Reference2', [ref], Number=3))
        self.repo.generated('screen', 'Brand new screen', document('screen', 'Brand new screen', [tf], Number=4711))
        self.assertEqual([], self.vocab())

    def test_circle_radius_is_geometry_and_exempt_from_the_value_check(self):
        # project B 2026-10-06: a 44 x 44 circle got Radius 22 (Width / 2, WinCC guide 7.2); the export had 20.
        self.repo.export('screen', 'Circles', document('screen', 'Circles', [
            item('Hmi.Screen.Circle', 'S-Lamp', Left=0, Top=0, Width=40, Height=40, Radius=20)], Number=6))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Circle', 'lamp1', Left=10, Top=90, Width=44, Height=44, Radius=22)], Number=2))
        self.assertEqual([], self.vocab())

    def test_exports_themselves_are_not_checked(self):
        self.repo.export('screen', 'Odd', document('screen', 'Odd', [
            item('Hmi.Screen.Gauge', 'gauge1', Left=1, Top=1, Width=1, Height=1)], Number=5))
        self.assertEqual([], self.vocab())

    def test_all_reference_export_kinds_feed_the_vocabulary(self):
        self.repo.export('popup', 'Pop', document('popup', 'Pop', [
            item('Hmi.Screen.Circle', 'S-Circle', Left=0, Top=0, Width=1, Height=1)]), folder='Sub')
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Circle', 'c1', Left=10, Top=90, Width=20, Height=20)], Number=2))
        self.assertEqual([], self.vocab())

    def test_reference_exports_of_another_project_feed_the_vocabulary(self):
        self.repo.write('hmi/references/B/screens/Other.xml', document('screen', 'Other', [
            item('Hmi.Screen.Gauge', 'S-Gauge', Left=0, Top=0, Width=1, Height=1),
            rect('S-Blue', BackColor='72, 116, 160')], Number=40))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Gauge', 'gauge1', Left=10, Top=90, Width=50, Height=50),
            rect('rect1', BackColor='72, 116, 160')], Number=2))
        self.assertEqual([], self.vocab())

    def test_reference_exports_are_not_objects_of_the_project(self):
        self.repo.write('hmi/references/B/screens/Other.xml', document('screen', 'Other', [], Number=2))
        self.repo.generated('screen', 'New', document('screen', 'New', [], Number=2))
        found = [f.rule for f in validate(self.repo.path)]
        self.assertNotIn('structure.duplicate-number', found)


class JudgeTest(unittest.TestCase):
    """voc.judge on a made-up catalogue attribute: the outcomes that depend on the round trip's state."""
    ATTR = {'name': 'Orientation', 'kind': 'enum', 'values': {
        'confirmed': ['Up'], 'enum': 'GraphX.Made',
        'documented': [{'value': 0, 'constant': None, 'name': 'Top', 'spelling': 'Up', 'confirmed': True},
                       {'value': 1, 'constant': None, 'name': 'Bottom', 'spelling': 'Down', 'confirmed': False},
                       {'value': 2, 'constant': None, 'name': 'Left', 'spelling': 'Left', 'confirmed': False},
                       {'value': 3, 'constant': None, 'name': 'Middle', 'spelling': None, 'confirmed': False}],
        'lost': {'Left': 'Up'}}}
    MEMBERS = {'Up': 0, 'Down': 1, 'Left': 2, 'Wide': 4}

    def judge(self, value):
        with mock.patch.object(catalogue, 'attribute', return_value=self.ATTR):
            with mock.patch.object(catalogue, 'enum_members', return_value=self.MEMBERS):
                return voc.judge('Hmi.Screen.Made', 'Orientation', value, voc.Vocabulary())

    def test_confirmed_passes(self):
        self.assertIsNone(self.judge('Up'))

    def test_documented_spelling_not_confirmed_is_a_warning(self):
        self.assertEqual('warning', self.judge('Down')[0])

    def test_enum_member_not_documented_is_a_warning(self):
        self.assertEqual('warning', self.judge('Wide')[0])

    def test_value_the_round_trip_lost_is_an_error(self):
        severity, message = self.judge('Left')
        self.assertEqual('error', severity)
        self.assertIn("exported 'Up'", message)

    def test_help_name_without_a_spelling_is_an_error(self):
        self.assertEqual('error', self.judge('Middle')[0])
        self.assertEqual('error', self.judge('Bottom')[0])


if __name__ == '__main__':
    unittest.main()
