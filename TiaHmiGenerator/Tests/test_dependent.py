import os
import sys
import unittest
import xml.etree.ElementTree as ET

from hmipreview import catalogue, validate
from hmipreview.model import attribute
from hmipreview.rules import dependent
from Tests.fixture import FixtureRepo, document, item

sys.path.insert(0, catalogue.DIR)
import roundtrip                                     # noqa: E402


def fixture_item(element, name, **changes):
    """The catalogue fixture's object of that type with changes, as an item of a fixture document."""
    attrs = {a.tag: a.text or '' for a in catalogue.fixture_objects()[element].find('AttributeList')}
    attrs.update(changes)
    return item(element, name, full=False, **attrs)


class DependentTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def found(self, *items, kind='generated'):
        doc = document('screen', 'New', list(items), Number=2)
        if kind == 'generated':
            self.repo.generated('screen', 'New', doc)
        else:
            self.repo.export('screen', 'New', doc)
        return [(f.severity, f.rule, f.object, f.message) for f in validate(self.repo.path)
                if f.rule.startswith('dependent.')]

    def test_the_fixture_objects_pass(self):
        # TIA's own objects, dropped from the toolbox unchanged
        items = [fixture_item(el, 'obj%d' % i)
                 for i, el in enumerate(sorted(catalogue.fixture_objects())) if el.startswith('Hmi.Screen.')
                 and el not in ('Hmi.Screen.Screen', 'Hmi.Screen.ScreenLayer')]
        self.assertEqual([], self.found(*items))

    def test_a_dependent_property_that_does_not_follow_its_main_property_is_an_error(self):
        # round trip try 2: TIA refused this gauge and ended
        found = self.found(fixture_item('Hmi.Screen.Gauge', 'gauge1', BackFillStyle='Solid',
                                        DialFillStyle='Transparent'))
        self.assertEqual({('error', 'dependent.value', 'gauge1')}, {f[:3] for f in found})
        text = ' '.join(f[3] for f in found)
        self.assertIn('DialFillStyle is Transparent; the rule table expects Solid because BackFillStyle is Solid', text)
        self.assertIn('BackFillStyle is Solid; the rule table expects FrameTransparent because DialFillStyle is Transparent',
                      text)
        self.assertIn('seen in TIA: refused, round trip try 2', text)
        self.assertIn('If TIA refuses it, the import ends TIA', text)

    def test_the_binary_io_field_of_try_1_is_refused_before_tia_sees_it(self):
        found = self.found(fixture_item('Hmi.Screen.IOField', 'io1', DataFormat='Binary', FormatPattern='9999999',
                                        FieldLength='10'))
        self.assertEqual(['FieldLength', 'FormatPattern'], sorted(f[3].split()[0] for f in found))

    def test_a_circle_radius_is_half_its_width_rounded_down(self):
        # project B's circles: Width 15, Radius 7 (exported by TIA)
        self.assertEqual([], self.found(fixture_item('Hmi.Screen.Circle', 'c1', Width=15, Height=15, Radius=7)))
        found = self.found(fixture_item('Hmi.Screen.Circle', 'c1', Width=16, Height=16, Radius=7))
        self.assertEqual(1, len(found))
        self.assertIn('Radius is 7; the rule table expects 8 (half of Width, rounded down)', found[0][3])

    def test_a_line_box_follows_its_start_and_end(self):
        found = self.found(fixture_item('Hmi.Screen.Line', 'line1', Left=10, Top=20, Width=50, Height=0,
                                        StartLeft=60, StartTop=20, EndLeft=10, EndTop=20))
        self.assertEqual([], found)
        found = self.found(fixture_item('Hmi.Screen.Line', 'line1', Left=10, Top=20, Width=40, Height=0,
                                        StartLeft=10, StartTop=20, EndLeft=60, EndTop=20))
        self.assertEqual(['Width is 40; the rule table expects 50 (the extent of StartLeft and EndLeft)'],
                         [f[3].split(' (dependent')[0] for f in found])

    def test_a_rule_tia_was_not_seen_to_apply_says_so(self):
        found = self.found(fixture_item('Hmi.Screen.Switch', 's1', Mode='GraphicSwitchButton', Flashing='Standard'))
        self.assertEqual(('error', 'dependent.value'), found[0][:2])
        self.assertIn('seen in TIA: not observed', found[0][3])

    def test_a_polygon_box_follows_its_points(self):
        pts = '\ufeff<Item>100, 50</Item><Item>130, 50</Item><Item>130, 90</Item>'
        self.assertEqual([], self.found(fixture_item('Hmi.Screen.Polygon', 'p1', Left=100, Top=50, Width=30,
                                                     Height=40, Points=pts)))
        found = self.found(fixture_item('Hmi.Screen.Polygon', 'p1', Left=100, Top=50, Width=20, Height=20,
                                        Points=pts))
        self.assertEqual(['Height', 'Width'], sorted(f[3].split()[0] for f in found))

    def test_a_relation_with_a_condition_holds_only_under_it(self):
        self.assertEqual([], self.found(fixture_item('Hmi.Screen.Gauge', 'g1', LockSquaredExtent='false',
                                                     Width=200, Height=150)))
        found = self.found(fixture_item('Hmi.Screen.Gauge', 'g1', LockSquaredExtent='true', Width=200, Height=150))
        self.assertIn('while LockSquaredExtent is true', found[0][3])

    def test_a_device_value_is_a_warning(self):
        found = self.found(fixture_item('Hmi.Screen.TextField', 't1', EdgeStyle='None'))
        self.assertEqual([('warning', 'dependent.device', 't1')], [f[:3] for f in found])

    def test_exports_are_not_checked(self):
        self.assertEqual([], self.found(fixture_item('Hmi.Screen.Gauge', 'gauge1', BackFillStyle='Solid',
                                                     DialFillStyle='Transparent'), kind='export'))


class TableTest(unittest.TestCase):
    def test_every_entry_names_a_catalogue_type_and_its_attributes(self):
        t = catalogue.dependent()
        for e in t['pairs'] + t['relations'] + t['deviceRefuses']:
            names = catalogue.attribute_names(e['element'])
            self.assertIsNotNone(names, e)
            used = set(e.get('when', {})) | set(e.get('then', {})) | set(e.get('of', [])) | {e.get('attribute')} - {None}
            self.assertEqual(set(), used - names - {'Points.x', 'Points.y'}, e)
        for r in t['relations']:
            self.assertIn(r['is'], ('equal', 'half', 'min', 'span'))

    def test_the_round_trip_reads_the_same_table(self):
        self.assertEqual({'DialFillStyle': 'Solid'}, roundtrip.DEPENDENT[('Hmi.Screen.Gauge', 'BackFillStyle', 'Solid')])
        self.assertIn(('Hmi.Screen.TextField', 'EdgeStyle', 'None'), roundtrip.DEVICE_REFUSES)
        self.assertEqual(len([p for p in catalogue.dependent()['pairs'] if len(p['when']) == 1]),
                         len(roundtrip.DEPENDENT))

    def test_every_source_says_what_the_committed_exports_show(self):
        """'taken': an object of the round trip follows the pair. 'holds in exports': the relation is evaluated and
        holds. 'not observed': no export has such an object, so nobody reads it as confirmed."""
        folder = os.path.join(catalogue.DIR, 'roundtrip', 'back')
        back = [e for f in os.listdir(folder) for e in ET.parse(os.path.join(folder, f)).getroot().iter()]
        fixture = list(catalogue.fixture_objects().values())
        t = catalogue.dependent()
        for p in t['pairs']:
            found = [e for e in back if e.tag == p['element'] and dependent._holds(e, p['when'])]
            if 'taken' in p['source']:
                self.assertTrue(found, p)
                for e in found:
                    self.assertEqual(p['then'], {k: attribute(e, k) for k in p['then']}, p)
            elif p['source'] == 'not observed':
                self.assertEqual([], found, p)
            else:
                self.assertIn('refused', p['source'], p)
        for r in t['relations']:
            found = [e for e in back + fixture if e.tag == r['element'] and dependent._holds(e, r.get('when'))]
            if r['source'] == 'not observed':
                self.assertEqual([], found, r)
                continue
            self.assertIn('holds in exports', r['source'], r)
            self.assertTrue(found, r)
            for e in found:
                self.assertEqual(float(attribute(e, r['attribute'])), dependent._expected(r, e), r)

        for d in t['deviceRefuses']:
            self.assertTrue(d['source'].startswith('no verdict'), d)
            self.assertEqual([], [e for e in back + fixture if e.tag == d['element']
                                  and attribute(e, d['attribute']) == d['value']], d)


if __name__ == '__main__':
    unittest.main()
