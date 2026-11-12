"""HMI changes between two sides (sides.py, changes.py): the hmi/ part of the change report, on fixture repos with
commits."""
import json
import msvcrt
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from hmipreview import changes, diff, geometry, jsbundle, sides
from Tests.fixture import FULL_SETTING, FixtureRepo, cycle, document, group, item, rect

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # TiaHmiGenerator


def text(comp, en):
    return ('<MultilingualText ID="0" CompositionName="%s"><ObjectList><MultilingualTextItem ID="0" '
            'CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text><body><p>%s</p></body></Text>'
            '</AttributeList></MultilingualTextItem></ObjectList></MultilingualText>' % (comp, en))


def tag_link(name):
    return '<Tag TargetID="@OpenLink"><Name>%s</Name></Tag>' % name


def range_anim(tag, back):
    """A RangeAppearanceAnimation with one range (guide 4.3)."""
    return ('<Hmi.Dynamic.RangeAppearanceAnimation ID="0" CompositionName="Animations"><AttributeList>'
            '<Name>RangeAppearanceAnimation</Name></AttributeList><ObjectList>'
            '<Hmi.Dynamic.TagElementTrigger ID="0" CompositionName="RangeTag"><LinkList>%s</LinkList>'
            '</Hmi.Dynamic.TagElementTrigger><Hmi.Dynamic.Range ID="0" CompositionName="RangeValues"><AttributeList>'
            '<BackColor>%s</BackColor><FlashingType>No</FlashingType><LowerLimit>1</LowerLimit>'
            '<UpperLimit>1</UpperLimit></AttributeList></Hmi.Dynamic.Range></ObjectList>'
            '</Hmi.Dynamic.RangeAppearanceAnimation>' % (tag_link(tag), back))


def lamp(name, tag, back='0, 160, 0'):
    """A rectangle coloured by a tag."""
    return rect(name, children=None) if tag is None else item(
        'Hmi.Screen.Rectangle', name, '<ObjectList>%s</ObjectList>' % range_anim(tag, back),
        Left=10, Top=90, Width=40, Height=40)


def symbolic(name, textlist):
    return item('Hmi.Screen.SymbolicIOField', name,
                '<LinkList><TextList TargetID="@OpenLink"><Name>%s</Name></TextList></LinkList>' % textlist,
                Left=100, Top=90, Width=120, Height=30)


def tag(name, plc, cycle='100 ms', members=0, comment=''):
    """An HMI tag in the shape of a tag table export; members: that many structure members."""
    mem = ''.join('<Hmi.Tag.TagStructureMember ID="0" CompositionName="Members"><AttributeList><Name>m%d</Name>'
                  '</AttributeList></Hmi.Tag.TagStructureMember>' % i for i in range(members))
    return ('<Hmi.Tag.Tag ID="0" CompositionName="Tags"><AttributeList><Length>2</Length><Name>%s</Name>'
            '</AttributeList><LinkList><AcquisitionCycle TargetID="@OpenLink"><Name>%s</Name></AcquisitionCycle>'
            '<Connection TargetID="@OpenLink"><Name>HMI_Connection_1</Name></Connection>'
            '<ControllerTag TargetID="@OpenLink"><Name>%s</Name></ControllerTag></LinkList><ObjectList>%s%s'
            '</ObjectList></Hmi.Tag.Tag>' % (name, cycle, plc, text('Comment', comment), mem))


def tag_table(name, tags):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><DocumentInfo>'
            '<Created>2026-10-06T00:00:00</Created><ExportSetting>None</ExportSetting></DocumentInfo>'
            '<Hmi.Tag.TagTable ID="0"><AttributeList><Name>%s</Name></AttributeList><ObjectList>%s</ObjectList>'
            '</Hmi.Tag.TagTable></Document>\n' % (name, ''.join(tags)))


def text_list(name, entries):
    ents = ''.join('<Hmi.TextGraphicList.TextListEntry ID="0" CompositionName="Entries"><AttributeList>'
                   '<From>%d</From><To>%d</To></AttributeList><ObjectList>%s</ObjectList>'
                   '</Hmi.TextGraphicList.TextListEntry>' % (v, v, text('Text', t)) for v, t in entries)
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><DocumentInfo>'
            '<Created>2026-10-06T00:00:00</Created></DocumentInfo><Hmi.TextGraphicList.TextList ID="0">'
            '<AttributeList><Name>%s</Name></AttributeList><ObjectList>%s</ObjectList>'
            '</Hmi.TextGraphicList.TextList></Document>\n' % (name, ents))


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def head(self):
        return self.repo.git('rev-parse', 'HEAD').strip()

    def compare(self, rev1, rev2=None, **kw):
        return changes.compare(sides.side(self.repo.path, rev1), sides.side(self.repo.path, rev2), **kw)

    def obj(self, result, name, kind=None):
        found = [o for o in result.objects if o['name'] == name and (kind is None or o['kind'] == kind)]
        self.assertEqual(1, len(found), [(o['kind'], o['name']) for o in result.objects])
        return found[0]


class MovedTest(RepoCase):
    def test_a_document_moved_with_identical_bytes_reads_as_moved_between_revisions(self):
        path = self.repo.export('screen', 'Main', document('screen', 'Main', [rect('Box')], Number=1))
        self.repo.commit()
        os.remove(os.path.join(self.repo.path, *path.split('/')))
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('Box')], Number=1), folder='Units')
        self.repo.commit()

        main = self.obj(self.compare('HEAD~1', 'HEAD'), 'Main')

        self.assertEqual(('changed', {'name': 'Main', 'folder': ''}), (main['state'], main['from']))


class SidesTest(RepoCase):
    def test_working_tree_ids_equal_the_revision_ids_of_unchanged_files(self):
        kept = self.repo.export('screen', 'Kept', document('screen', 'Kept', [rect('r1')], Number=1))
        edited = self.repo.export('screen', 'Edited', document('screen', 'Edited', [rect('r1')], Number=2))
        gone = self.repo.export('screen', 'Gone', document('screen', 'Gone', [rect('r1')], Number=3))
        self.repo.commit()
        self.repo.export('screen', 'Edited', document('screen', 'Edited', [rect('r1', left=50)], Number=2))
        os.remove(os.path.join(self.repo.path, *gone.split('/')))
        new = self.repo.export('screen', 'New', document('screen', 'New', [rect('r1')], Number=4))

        rev = sides.side(self.repo.path, 'HEAD').files()
        wt = sides.side(self.repo.path).files()

        self.assertEqual(rev[kept], wt[kept])
        self.assertNotEqual(rev[edited], wt[edited])
        self.assertNotIn(gone, wt)
        self.assertIn(new, wt)
        self.assertNotIn(new, rev)

    def test_a_tracked_file_edited_with_its_time_restored_reads_as_changed(self):
        path = self.repo.export('screen', 'Main', document('screen', 'Main', [rect('Box', left=128)], Number=1))
        full = os.path.join(self.repo.path, *path.split('/'))
        long_ago = (1700000000, 1700000000)     # older than the index: git takes the file as unchanged by its time
        os.utime(full, long_ago)
        self.repo.commit()
        self.repo.write(path, document('screen', 'Main', [rect('Box', left=228)], Number=1))
        os.utime(full, long_ago)
        self.repo.git('update-index', '--refresh')
        self.assertEqual('', self.repo.git('status', '--porcelain'))

        main = self.obj(self.compare('HEAD'), 'Main')

        self.assertEqual('changed', main['state'])
        self.assertEqual(['Rectangle Box: moved (128, 90) 100x50 -> (228, 90) 100x50'], main['changes'][0]['lines'])

    def test_documents_by_device_folder_and_without_references(self):
        self.repo.write('hmi/Panel_A/screens/Main/Start.xml', document('screen', 'Start'))
        self.repo.write('hmi/Panel_B/tags/Plant/Motors.xml', tag_table('Motors', []))
        self.repo.write('hmi/references/other/screens/Copy.xml', document('screen', 'Copy'))
        self.repo.write('hmi/panel.json', '{}')

        docs = sides.documents(sides.FolderSide(self.repo.path))

        self.assertEqual({('Panel_A', 'screen', 'Start'): 'Main', ('Panel_B', 'tagtable', 'Motors'): 'Plant'},
                         {k: e.folder for k, e in docs.items()})

    def test_generated_set_lays_the_generated_documents_over_the_exports(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', Number=1), folder='Units')
        self.repo.export('screen', 'Door', document('screen', 'Door', Number=2))
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', Number=1))
        sd = sides.FolderSide(self.repo.path)

        tia = sides.documents(sd, 'tia')
        gen = sides.documents(sd, 'generated')

        self.assertEqual('export', tia[('', 'screen', 'Silo')].origin)
        silo = gen[('', 'screen', 'Silo')]
        self.assertEqual(('generated', 'Units'), (silo.origin, silo.folder))
        self.assertEqual('export', gen[('', 'screen', 'Door')].origin)

    def test_unknown_revision_is_a_value_error(self):
        self.repo.commit()
        with self.assertRaises(ValueError):
            sides.side(self.repo.path, 'nosuchrev')


class ScreenChangesTest(RepoCase):
    def test_states_of_documents(self):
        self.repo.export('screen', 'Same', document('screen', 'Same', [rect('r1')], Number=1))
        self.repo.export('screen', 'Edited', document('screen', 'Edited', [rect('r1')], Number=2))
        self.repo.export('screen', 'Gone', document('screen', 'Gone', Number=3))
        self.repo.commit()
        self.repo.export('screen', 'Edited', document('screen', 'Edited', [rect('r1', left=40)], Number=2))
        os.remove(os.path.join(self.repo.path, 'hmi', 'screens', 'Gone.xml'))
        self.repo.export('screen', 'New', document('screen', 'New', Number=4))
        self.repo.commit()

        result = self.compare('HEAD~1', 'HEAD')

        self.assertEqual([('Edited', 'changed'), ('Gone', 'deleted'), ('New', 'new'), ('Same', 'same')],
                         [(o['name'], o['state']) for o in result.objects])
        self.assertEqual(['Rectangle r1: moved (10, 90) 100x50 -> (40, 90) 100x50'],
                         self.obj(result, 'Edited')['changes'][0]['lines'])
        self.assertEqual(['changed  screen      Edited (1)', 'deleted  screen      Gone (0)',
                          'new      screen      New (0)'], result.lines())

    def test_a_new_export_of_an_unchanged_screen_is_the_same(self):
        doc = document('screen', 'Silo', [rect('r1')], Number=1)
        self.repo.export('screen', 'Silo', doc)
        self.repo.commit()
        self.repo.export('screen', 'Silo', doc.replace('2026-10-06T00:00:00', '2026-10-30T12:00:00')
                         .replace('><', '>\n  <'))

        result = self.compare('HEAD')

        self.assertEqual('same', self.obj(result, 'Silo')['state'])

    def test_renamed_screen_pairs_by_its_number(self):
        self.repo.export('screen', '10 - Silo', document('screen', '10 - Silo', [rect('r1')], Number=10))
        self.repo.export('screen', '11 - Door', document('screen', '11 - Door', Number=11))
        self.repo.commit()
        for f in ('10 - Silo', '11 - Door'):
            os.remove(os.path.join(self.repo.path, 'hmi', 'screens', f + '.xml'))
        self.repo.export('screen', '10 - Silo table', document('screen', '10 - Silo table', [rect('r1')], Number=10),
                         folder='Units')
        self.repo.export('screen', '12 - Gate', document('screen', '12 - Gate', Number=12))

        result = self.compare('HEAD')

        silo = self.obj(result, '10 - Silo table')
        self.assertEqual(('changed', {'name': '10 - Silo', 'folder': ''}), (silo['state'], silo['from']))
        self.assertEqual(["Screen 10 - Silo table: Name '10 - Silo' -> '10 - Silo table'"],
                         silo['changes'][0]['lines'])
        self.assertEqual('deleted', self.obj(result, '11 - Door')['state'])
        self.assertEqual('new', self.obj(result, '12 - Gate')['state'])

    def test_animation_parts_are_spelled_out_fact_by_fact(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [lamp('lamp1', 'Motor.run', '0, 160, 0')],
                                                    Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [lamp('lamp1', 'Motor.fault', '200, 0, 0')],
                                                    Number=1))

        result = self.compare('HEAD')

        c = self.obj(result, 'Silo')['changes'][0]
        self.assertEqual(['Animations'], [p['part'] for p in c['parts']])
        self.assertEqual(
            ["Rectangle lamp1: RangeAppearanceAnimation/TagElementTrigger/Tag 'Motor.run' -> 'Motor.fault'",
             "Rectangle lamp1: RangeAppearanceAnimation/Range/BackColor '0, 160, 0' -> '200, 0, 0'"], c['lines'])

    def test_a_document_that_does_not_parse_is_skipped_and_named(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=1))
        self.repo.export('screen', 'Door', document('screen', 'Door', Number=2))
        self.repo.commit()
        self.repo.write('hmi/screens/Silo.xml', '<Document><Hmi.Screen.Screen ID="0"><broken')
        self.repo.export('screen', 'Door', document('screen', 'Door', [rect('r1')], Number=2))

        result = self.compare('HEAD')

        self.assertEqual(['Door'], [o['name'] for o in result.objects])
        self.assertEqual(['hmi/screens/Silo.xml'], [p for p, _ in result.skipped])
        self.assertTrue(result.skipped[0][1].startswith('unreadable: '))

    def test_documents_are_embedded_once_without_document_info(self):
        doc = document('screen', 'Silo', [rect('r1')], Number=1)
        self.repo.export('screen', 'Silo', doc)
        self.repo.write('hmi/Panel_B/screens/Silo.xml', doc)
        self.repo.commit()

        result = self.compare('HEAD')

        self.assertEqual(1, len(result.docs))
        self.assertEqual({'d0'}, {o[k] for o in result.objects for k in ('bdoc', 'adoc')})
        self.assertNotIn('DocumentInfo', result.docs['d0'])
        self.assertNotIn('\n', result.docs['d0'].split('?>', 1)[1].strip())

    def test_tia_against_generated_is_the_review_before_import(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=1))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1'), rect('r2', top=200)],
                                                       Number=1))

        result = self.compare('HEAD', after_set='generated')

        silo = self.obj(result, 'Silo')
        self.assertEqual(({'before': 'export', 'after': 'generated'}, 'changed'), (silo['origin'], silo['state']))
        self.assertEqual(['Rectangle r2: added at (10, 200) 100x50'], [l for c in silo['changes'] for l in c['lines']])
        self.assertTrue(result.after.endswith('(working tree), generated'), result.after)

    def test_data_files_per_side_and_device(self):
        self.repo.handbuilt([{'screen': 'Alarms', 'kind': 'alarm view', 'x': 0, 'y': 80, 'w': 1280, 'h': 600}])
        self.repo.write('hmi/Panel_B/panel.json', json.dumps({'panel': 'TP700 Comfort'}))
        self.repo.commit()

        result = self.compare('HEAD')

        self.assertEqual({'': {'handbuilt': [{'screen': 'Alarms', 'kind': 'alarm view', 'x': 0, 'y': 80,
                                              'w': 1280, 'h': 600}]},
                          'Panel_B': {'panel': {'panel': 'TP700 Comfort'}}}, result.data['after'])

    def test_a_data_file_that_does_not_parse_is_left_out(self):
        self.repo.write('hmi/panel.json', '{not json')
        self.repo.write('hmi/Panel_B/panel.json', json.dumps({'panel': 'TP700 Comfort'}))
        self.repo.commit()

        self.assertEqual({'Panel_B': {'panel': {'panel': 'TP700 Comfort'}}}, self.compare('HEAD').data['after'])


def points(*pts):
    return '\ufeff' + ''.join('<Item>%s, %s</Item>' % p for p in pts)


class PointsTest(RepoCase):
    """A polyline or polygon is its points: one moved inside the bounding box is a change like any other."""
    ZIG = ((10, 10), (50, 40), (90, 10))

    def changes_of(self, old, new, tag='Hmi.Screen.Polyline'):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [item(tag, 'wire', Points=old)], Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [item(tag, 'wire', Points=new)], Number=1))
        return self.obj(self.compare('HEAD'), 'Silo').get('changes', [])

    def test_a_point_moved_inside_the_box_is_told_with_old_and_new(self):
        for tag in ('Hmi.Screen.Polyline', 'Hmi.Screen.Polygon'):
            with self.subTest(tag):
                self.fresh()
                c, = self.changes_of(points(*self.ZIG), points((10, 10), (60, 40), (90, 10)), tag)

                self.assertEqual(('wire', 'changed'), (c['object'], c['kind']))
                self.assertEqual(c['old'], c['new'])                 # the box stays: the outline sits on both sides
                a, = c['attributes']
                self.assertEqual(('Points', '10, 10; 50, 40; 90, 10', '10, 10; 60, 40; 90, 10'),
                                 (a['name'], a['old'], a['new']))
                self.assertEqual(["%s wire: Points '10, 10; 50, 40; 90, 10' -> '10, 10; 60, 40; 90, 10'"
                                  % tag.split('.')[-1]], c['lines'])

    def test_the_moved_points_are_named_for_the_drawing(self):
        c, = self.changes_of(points(*self.ZIG), points((10, 10), (60, 40), (90, 10)))

        self.assertEqual({'old': [[50, 40]], 'new': [[60, 40]]}, c['attributes'][0]['points'])

    def test_a_point_added_in_the_box_and_a_reversed_line_are_told(self):
        c, = self.changes_of(points(*self.ZIG), points((10, 10), (30, 20), (50, 40), (90, 10)))
        self.assertEqual({'old': [], 'new': [[30, 20]]}, c['attributes'][0]['points'])

        self.fresh()
        c, = self.changes_of(points(*self.ZIG), points(*reversed(self.ZIG)))
        self.assertEqual('90, 10; 50, 40; 10, 10', c['attributes'][0]['new'])

    def test_a_shape_moved_whole_is_told_by_its_position_alone(self):
        c, = self.changes_of(points(*self.ZIG), points(*((x + 5, y + 7) for x, y in self.ZIG)))

        self.assertEqual('moved', c['kind'])
        self.assertEqual([], c['attributes'])
        self.assertEqual(['Polyline wire: moved (10, 10) 80x30 -> (15, 17) 80x30'], c['lines'])

    def test_a_shape_resized_also_tells_its_points(self):
        c, = self.changes_of(points(*self.ZIG), points((10, 10), (50, 40), (120, 10)))

        self.assertEqual('moved', c['kind'])
        self.assertEqual('10, 10; 50, 40; 120, 10', c['attributes'][0]['new'])
        self.assertEqual(2, len(c['lines']))

    def test_the_same_points_written_otherwise_are_no_change(self):
        same = '<Item>10,10</Item><Item> 50 , 40 </Item><Item>90.0, 10</Item>'

        self.assertEqual([], self.changes_of(points(*self.ZIG), same))

    def test_points_that_cannot_be_read_still_show_when_they_differ(self):
        c, = self.changes_of('one', 'two')

        self.assertEqual(('one', 'two'), (c['attributes'][0]['old'], c['attributes'][0]['new']))

    def test_points_only_one_export_holds_are_folded_as_the_other_attributes(self):
        def doc(setting, **kw):
            return document('screen', 'Silo', [item('Hmi.Screen.Polyline', 'wire', Left=10, Top=10, Width=80, Height=30,
                                                    **kw)], export_setting=setting, Number=1)
        self.repo.export('screen', 'Silo', doc('WithDefaults, WithReadOnly', Points=points(*self.ZIG)))
        self.repo.commit()
        self.repo.export('screen', 'Silo', doc('None'))

        c, = self.obj(self.compare('HEAD'), 'Silo')['changes']

        self.assertEqual('export', c['attributes'][0].get('fold'))
        self.assertEqual('export', c.get('fold'))


class TypeChangedTest(RepoCase):
    """Another type under the same name is told as such and never folds: absent may be an attribute that type does not
    hold, which no export leaves out."""
    LINE = dict(StartLeft=10, StartTop=10, EndLeft=50, EndTop=40)
    POINTS = points((10, 10), (50, 40))

    def change_of(self, old, new, **kw):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [old], Number=1, **kw))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [new], Number=1, **kw))
        o = self.obj(self.compare('HEAD'), 'Silo')
        c, = o['changes']
        return o, c

    def assert_told_and_not_folded(self, o, c, was, now):
        self.assertEqual(('Object type', was, now), tuple(c['attributes'][0][k] for k in ('name', 'old', 'new')))
        self.assertEqual(now, c['type'])
        self.assertIsNone(c.get('fold'))
        self.assertEqual([], [a['name'] for a in c['attributes'] if a.get('fold')])
        self.assertNotIn('exportNoise', o)

    def test_a_line_and_a_polyline_in_the_same_box_are_told_and_not_folded(self):
        line = item('Hmi.Screen.Line', 'wire', full=False, **self.LINE)
        polyline = item('Hmi.Screen.Polyline', 'wire', full=False, Points=self.POINTS)
        for old, new, was, now in ((line, polyline, 'Line', 'Polyline'), (polyline, line, 'Polyline', 'Line')):
            with self.subTest(was):
                self.fresh()
                o, c = self.change_of(old, new)

                self.assert_told_and_not_folded(o, c, was, now)
                self.assertEqual('changed', c['kind'])
                self.assertEqual({'x': 10, 'y': 10, 'w': 40, 'h': 30}, c['old'])
                self.assertEqual(c['old'], c['new'])
                self.assertEqual("%s wire: Object type '%s' -> '%s'" % (now, was, now), c['lines'][0])

    def test_a_polygon_and_an_ellipse_in_the_same_box_are_told_and_not_folded(self):
        polygon = item('Hmi.Screen.Polygon', 'shape', full=False, Points=points((10, 10), (50, 10), (50, 40)))
        ellipse = item('Hmi.Screen.Ellipse', 'shape', full=False, Left=10, Top=10, Width=40, Height=30)
        for old, new, was, now in ((polygon, ellipse, 'Polygon', 'Ellipse'), (ellipse, polygon, 'Ellipse', 'Polygon')):
            with self.subTest(was):
                self.fresh()
                o, c = self.change_of(old, new)

                self.assert_told_and_not_folded(o, c, was, now)

    def test_nothing_of_it_folds_as_an_export_difference_on_a_minimal_export_either(self):
        o, c = self.change_of(item('Hmi.Screen.Line', 'wire', full=False, LineWidth=3, **self.LINE),
                              item('Hmi.Screen.Polyline', 'wire', full=False, Points=self.POINTS),
                              export_setting='None')

        self.assert_told_and_not_folded(o, c, 'Line', 'Polyline')
        self.assertEqual(['Object type', 'LineWidth', 'Points'], [a['name'] for a in c['attributes']])

    def test_the_same_attributes_under_another_type_are_a_change(self):
        o, c = self.change_of(item('Hmi.Screen.Polyline', 'wire', full=False, Points=self.POINTS),
                              item('Hmi.Screen.Polygon', 'wire', full=False, Points=self.POINTS))

        self.assertEqual('changed', o['state'])
        self.assertEqual(["Polygon wire: Object type 'Polyline' -> 'Polygon'"], c['lines'])

    def test_another_type_in_another_box_tells_both(self):
        o, c = self.change_of(item('Hmi.Screen.Rectangle', 'r', full=False, Left=10, Top=10, Width=40, Height=30),
                              item('Hmi.Screen.Ellipse', 'r', full=False, Left=90, Top=10, Width=40, Height=30))

        self.assertEqual('moved', c['kind'])
        self.assertEqual(['Object type'], [a['name'] for a in c['attributes']])

    def test_another_type_with_no_box_on_either_side_is_not_moved(self):
        for old, new in (('Hmi.Screen.Line', 'Hmi.Screen.Rectangle'), ('Hmi.Screen.Rectangle', 'Hmi.Screen.Line')):
            with self.subTest(old):
                self.fresh()
                o, c = self.change_of(item(old, 'r', full=False), item(new, 'r', full=False))

                self.assertEqual(('changed', None, None), (c['kind'], c['old'], c['new']))
                self.assertEqual(["%s r: Object type '%s' -> '%s'" % (new[11:], old[11:], new[11:])], c['lines'])

    def test_an_empty_line_against_an_object_with_no_box_tells_what_that_object_says(self):
        line = item('Hmi.Screen.Line', 'r', full=False)
        rectangle = item('Hmi.Screen.Rectangle', 'r', full=False, Left=10, Top=20)
        for old, new, rows in ((line, rectangle, [('Left', None, '10'), ('Top', None, '20')]),
                               (rectangle, line, [('Left', '10', None), ('Top', '20', None)])):
            with self.subTest(rows[0][1]):
                self.fresh()
                o, c = self.change_of(old, new)

                self.assertEqual(('changed', None, None), (c['kind'], c['old'], c['new']))
                self.assertEqual(['Object type'] + [r[0] for r in rows], [a['name'] for a in c['attributes']])
                self.assertEqual(rows, [(a['name'], a['old'], a['new']) for a in c['attributes'][1:]])

    def test_an_attribute_without_a_visible_effect_stays_folded_beside_it(self):
        o, c = self.change_of(item('Hmi.Screen.Polyline', 'wire', full=False, Points=self.POINTS, TabIndex=3),
                              item('Hmi.Screen.Polygon', 'wire', full=False, Points=self.POINTS, TabIndex=4))

        self.assertEqual({'Object type': None, 'TabIndex': 'quiet'},
                         {a['name']: a.get('fold') for a in c['attributes']})
        self.assertIsNone(c.get('fold'))


LIST = 'Vendor.Hmi.Lists.HmiTextList:%s'
TAG = 'Vendor.Hmi.Tag.HmiTag:%s'


def fieldinfo(name='0', domain='HMICommonTextList', ref=LIST % 'Modes', sub=TAG % 'modeNow', length='5'):
    return ('<fieldinfo name="%s" domaintype="%s"><reference TargetID="@OpenLink"><name>%s</name></reference>'
            '<subreference TargetID="@OpenLink"><name>%s</name></subreference><domaindata><format length="%s" />'
            '</domaindata></fieldinfo>' % (name, domain, ref, sub, length))


def field_text(comp='Text', body='Mode: <field ref="0" />', infos=None):
    infos = fieldinfo() if infos is None else infos
    return ('<MultilingualText ID="0" CompositionName="%s"><ObjectList><MultilingualTextItem ID="0" '
            'CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text><body><p>%s</p></body>'
            '<fieldinfos>%s</fieldinfos></Text></AttributeList></MultilingualTextItem></ObjectList>'
            '</MultilingualText>' % (comp, body, infos))


class BoxGoneTest(RepoCase):
    """An object with a box on one side only stops nothing: it is told."""

    def test_a_box_on_one_side_only_is_told(self):
        whole, bare = rect('r', left=10, top=90, width=100, height=50), item('Hmi.Screen.Rectangle', 'r', full=False)
        for old, new, was, now, line in (
                (whole, bare, {'x': 10, 'y': 90, 'w': 100, 'h': 50}, None, 'moved (10, 90) 100x50 -> (no box)'),
                (bare, whole, None, {'x': 10, 'y': 90, 'w': 100, 'h': 50}, 'moved (no box) -> (10, 90) 100x50')):
            with self.subTest(line):
                self.fresh()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [old], Number=1))
                self.repo.commit()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [new], Number=1))

                c = [c for c in self.obj(self.compare('HEAD'), 'Silo')['changes'] if c['object'] == 'r'][0]

                self.assertEqual(('moved', was, now), (c['kind'], c['old'], c['new']))
                self.assertIn('Rectangle r: ' + line, c['lines'])


class BoxValuesTest(RepoCase):
    """Left, Top, Width and Height: told by the box row, and in a row of their own where the box does not say it."""

    def changes_of(self, tag, old, new):
        def doc(attrs):
            return document('screen', 'Silo', [item(tag, 'r', full=False, **attrs)], Number=1)
        self.repo.export('screen', 'Silo', doc(old))
        self.repo.commit()
        self.repo.export('screen', 'Silo', doc(new))
        return self.obj(self.compare('HEAD'), 'Silo').get('changes', [])

    def test_only_a_line_takes_its_box_from_an_end_written(self):
        for end in ('5', ''):
            with self.subTest(end):
                self.fresh()
                size = dict(StartLeft=end, Top=10, Width=40, Height=40)
                c, = self.changes_of('Hmi.Screen.Rectangle', dict(size, Left=10), dict(size, Left=200))

                self.assertEqual(('moved', 10, 200), (c['kind'], c['old']['x'], c['new']['x']))

    def test_another_object_with_all_four_ends_still_takes_its_box_from_them(self):
        ends = dict(StartTop=0, EndLeft=50, EndTop=40, Left=1, Top=2, Width=3, Height=4)
        c, = self.changes_of('Hmi.Screen.Rectangle', dict(ends, StartLeft=10), dict(ends, StartLeft=20))

        self.assertEqual(('moved', 10, 20), (c['kind'], c['old']['x'], c['new']['x']))

    def test_a_box_value_the_box_does_not_follow_is_told_in_a_row(self):
        partly = dict(StartLeft=10, EndLeft=50, EndTop=40, Top=0, Width=40, Height=40)
        whole = dict(partly, StartTop=0)
        for why, tag, base in (('a Line with an end left out', 'Hmi.Screen.Line', partly),
                               ('a Line with all four ends', 'Hmi.Screen.Line', whole),
                               ('only Left and Top', 'Hmi.Screen.Rectangle', dict(Top=5))):
            with self.subTest(why):
                self.fresh()
                c, = self.changes_of(tag, dict(base, Left=10), dict(base, Left=20))

                self.assertEqual('changed', c['kind'])
                self.assertEqual([('Left', '10', '20')], [(a['name'], a['old'], a['new']) for a in c['attributes']])
                self.assertEqual(["%s r: Left '10' -> '20'" % tag.split('.')[-1]], c['lines'])

    def test_a_box_value_gone_from_a_line_of_ends_0_is_a_row(self):
        c, = self.changes_of('Hmi.Screen.Line', dict(StartLeft=0, Left=5), {})

        self.assertEqual([('Left', '5', None)], [(a['name'], a['old'], a['new']) for a in c['attributes']])

    def test_a_box_value_the_box_says_has_no_row(self):
        size = dict(Top=10, Width=40, Height=40)
        c, = self.changes_of('Hmi.Screen.Rectangle', dict(size, Left=10), dict(size, Left=20))
        self.assertEqual(('moved', []), (c['kind'], c['attributes']))

        self.fresh()
        ends = dict(StartTop=0, EndTop=40, Top=0, Width=40, Height=40)
        c, = self.changes_of('Hmi.Screen.Line', dict(ends, StartLeft=10, EndLeft=50, Left=10),
                             dict(ends, StartLeft=20, EndLeft=60, Left=20))
        self.assertEqual(('moved', []), (c['kind'], c['attributes']))

    def test_a_box_value_written_otherwise_or_left_out_as_0_is_no_change(self):
        ends = dict(StartLeft=10, StartTop=0, EndLeft=50, EndTop=40)
        for old, new in ((dict(ends, Left='10'), dict(ends, Left='10.0')), (dict(ends, Left='0'), dict(ends))):
            with self.subTest(old):
                self.fresh()
                self.assertEqual([], self.changes_of('Hmi.Screen.Line', old, new))

    def test_a_box_value_that_cannot_be_read_shows_when_it_differs(self):
        ends = dict(StartLeft=10, StartTop=0, EndLeft=50, EndTop=40)
        c, = self.changes_of('Hmi.Screen.Line', dict(ends, Left='a'), dict(ends, Left='b'))

        self.assertEqual([('Left', 'a', 'b')], [(a['name'], a['old'], a['new']) for a in c['attributes']])

    def test_a_line_with_nothing_written_has_no_box_and_compares_as_ends_0(self):
        bare = ET.fromstring('<Hmi.Screen.Line ID="0"><AttributeList><ObjectName>r</ObjectName></AttributeList>'
                             '</Hmi.Screen.Line>')
        self.assertIsNone(geometry.box_of(bare))
        self.assertEqual([], self.changes_of('Hmi.Screen.Line', dict(StartLeft=0), {}))


class LineEndsTest(RepoCase):
    """The box of a Line says its place and size, not which corner each end is at: that is told as well."""

    def changes_of(self, old, new, **box):
        def doc(ends):
            sx, sy, ex, ey = ends
            return document('screen', 'Silo', [item('Hmi.Screen.Line', 'wire', full=False, StartLeft=sx, StartTop=sy,
                                                    EndLeft=ex, EndTop=ey, **box)], Number=1)
        self.repo.export('screen', 'Silo', doc(old))
        self.repo.commit()
        self.repo.export('screen', 'Silo', doc(new))
        return self.obj(self.compare('HEAD'), 'Silo').get('changes', [])

    def test_a_line_mirrored_in_its_box_is_told_with_old_and_new(self):
        c, = self.changes_of((10, 10, 50, 40), (50, 10, 10, 40))

        self.assertEqual(('wire', 'changed'), (c['object'], c['kind']))
        self.assertEqual(c['old'], c['new'])                 # the box stays: the outline sits on both sides
        a, = c['attributes']
        self.assertEqual(('Ends', '10, 10; 50, 40', '50, 10; 10, 40'), (a['name'], a['old'], a['new']))
        self.assertEqual(["Line wire: Ends '10, 10; 50, 40' -> '50, 10; 10, 40'"], c['lines'])

    def test_the_ends_that_moved_are_named_for_the_drawing(self):
        c, = self.changes_of((10, 10, 50, 40), (50, 10, 10, 40))

        self.assertEqual({'old': [[10, 10], [50, 40]], 'new': [[50, 10], [10, 40]]}, c['attributes'][0]['points'])

    def test_a_line_mirrored_the_other_way_and_its_ends_swapped_are_told(self):
        for new, told in (((10, 40, 50, 10), '10, 40; 50, 10'), ((50, 40, 10, 10), '50, 40; 10, 10')):
            with self.subTest(told):
                self.fresh()
                c, = self.changes_of((10, 10, 50, 40), new)

                self.assertEqual(told, c['attributes'][0]['new'])

    def test_ends_swapped_mark_no_point_in_the_drawing(self):
        c, = self.changes_of((10, 10, 50, 40), (50, 40, 10, 10))

        self.assertEqual({'old': [], 'new': []}, c['attributes'][0]['points'])

    def test_a_straight_line_with_its_ends_swapped_is_told(self):
        c, = self.changes_of((10, 10, 50, 10), (50, 10, 10, 10))

        self.assertEqual('50, 10; 10, 10', c['attributes'][0]['new'])

    def test_a_line_mirrored_and_moved_tells_both(self):
        c, = self.changes_of((10, 10, 50, 40), (150, 110, 110, 140))

        self.assertEqual('moved', c['kind'])
        self.assertEqual(['Ends'], [a['name'] for a in c['attributes']])

    def test_a_line_moved_or_resized_the_same_way_round_keeps_its_box_row_alone(self):
        for new in ((110, 110, 150, 140), (10, 10, 70, 40)):
            with self.subTest(new):
                self.fresh()
                c, = self.changes_of((10, 10, 50, 40), new)

                self.assertEqual(('moved', []), (c['kind'], c['attributes']))

    def test_the_same_ends_written_otherwise_are_no_change(self):
        self.assertEqual([], self.changes_of((10, 10, 50, 40), ('10.0', '10.0', '50.0', '40.0')))

    def test_a_line_mirrored_with_an_end_left_out_is_told_as_the_drawing_counts_it(self):
        c, = self.changes_of((10, None, 50, 40), (50, None, 10, 40))

        self.assertEqual(('10, 0; 50, 40', '50, 0; 10, 40'), (c['attributes'][0]['old'], c['attributes'][0]['new']))

    def test_a_line_mirrored_with_an_end_left_out_has_a_box_and_marks_for_the_drawing(self):
        c, = self.changes_of((10, None, 50, 40), (50, None, 10, 40))

        box = {'x': 10, 'y': 0, 'w': 40, 'h': 40}
        self.assertEqual((box, box), (c['old'], c['new']))
        self.assertEqual({'old': [[10, 0], [50, 40]], 'new': [[50, 0], [10, 40]]}, c['attributes'][0]['points'])

    def test_a_line_moved_with_an_end_left_out_is_told(self):
        for old, new, was, now in (
                ((10, None, 50, 40), (10, None, 70, 40), (10, 0, 40, 40), (10, 0, 60, 40)),
                ((None, 10, 50, 40), (None, 10, 50, 60), (0, 10, 50, 30), (0, 10, 50, 50)),
                ((10, 10, None, 40), (20, 10, None, 40), (0, 10, 10, 30), (0, 10, 20, 30)),
                ((10, 10, 50, None), (10, 30, 50, None), (10, 0, 40, 10), (10, 0, 40, 30))):
            with self.subTest(old):
                self.fresh()
                c, = self.changes_of(old, new)

                self.assertEqual('moved', c['kind'])
                self.assertEqual((was, now), tuple((b['x'], b['y'], b['w'], b['h']) for b in (c['old'], c['new'])))

    def test_a_line_moved_with_an_end_left_out_is_told_though_a_box_stays_written(self):
        c, = self.changes_of((10, None, 50, 40), (10, None, 70, 40), Left=1, Top=2, Width=3, Height=4)

        self.assertEqual({'x': 10, 'y': 0, 'w': 60, 'h': 40}, c['new'])

    def test_an_end_left_out_and_the_same_end_written_as_0_are_no_change(self):
        for old, new in (((10, None, 50, 40), (10, 0, 50, 40)), ((10, 0, 50, 40), (10, None, 50, 40)),
                         ((0, None, None, None), (None, None, None, None)),
                         ((None, None, None, None), (None, 0, None, None))):
            with self.subTest(old):
                self.fresh()
                self.assertEqual([], self.changes_of(old, new))

    def test_ends_that_cannot_be_read_still_show_when_they_differ(self):
        c, = self.changes_of(('a', 10, 50, 40), ('b', 10, 50, 40))

        self.assertEqual(('Ends', 'a, 10; 50, 40', 'b, 10; 50, 40'),
                         (c['attributes'][0]['name'], c['attributes'][0]['old'], c['attributes'][0]['new']))

    def test_ends_that_cannot_be_read_and_are_the_same_are_no_change(self):
        self.assertEqual([], self.changes_of(('a', 10, 50, 40), ('a', 10, 50, 40)))

    def test_a_line_replaced_by_another_object_of_that_name_has_no_ends_row(self):
        line = item('Hmi.Screen.Line', 'wire', full=False, StartLeft=60, StartTop=250, EndLeft=160, EndTop=300, Left=60,
                    Top=250, Width=100, Height=50)
        other = item('Hmi.Screen.Rectangle', 'wire', full=False, Left=60, Top=250, Width=100, Height=50)
        for why, old, new in (('line to rectangle', line, other), ('rectangle to line', other, line)):
            with self.subTest(why):
                self.fresh()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [old], Number=1))
                self.repo.commit()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [new], Number=1))

                told = self.obj(self.compare('HEAD'), 'Silo').get('changes', [])

                self.assertEqual([], [a for c in told for a in c['attributes'] if a['name'] == 'Ends'])

    def test_another_object_holding_ends_has_no_ends_row(self):
        def doc(sx, ex):
            return document('screen', 'Silo', [item('Hmi.Screen.Rectangle', 'wire', full=False, StartLeft=sx, StartTop=10,
                                                    EndLeft=ex, EndTop=40)], Number=1)
        self.repo.export('screen', 'Silo', doc(10, 50))
        self.repo.commit()
        self.repo.export('screen', 'Silo', doc(50, 10))

        self.assertEqual([], self.obj(self.compare('HEAD'), 'Silo').get('changes', []))

    def test_a_line_turned_diagonal_tells_which_way(self):
        c, = self.changes_of((10, 10, 10, 40), (50, 10, 10, 40))

        self.assertEqual('50, 10; 10, 40', c['attributes'][0]['new'])


def label(child):
    return item('Hmi.Screen.TextField', 'lbl', '<ObjectList>%s</ObjectList>' % child, Left=10, Top=10, Width=200,
                Height=30)


def list_doc(entries):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><DocumentInfo>'
            '<Created>2026-10-06T00:00:00</Created></DocumentInfo><Hmi.TextGraphicList.TextList ID="0">'
            '<AttributeList><Name>Modes</Name></AttributeList><ObjectList>%s</ObjectList>'
            '</Hmi.TextGraphicList.TextList></Document>\n'
            % ''.join('<Hmi.TextGraphicList.TextListEntry ID="0" CompositionName="Entries"><AttributeList>'
                      '<From>1</From><To>1</To></AttributeList><ObjectList>%s</ObjectList>'
                      '</Hmi.TextGraphicList.TextListEntry>' % e for e in entries))


class TextFieldsTest(RepoCase):
    """A tag or list field inside a text is part of the text: told with its old and new value."""
    FIELD = '{HMICommonTextList, HmiTextList:Modes, HmiTag:modeNow, length 5}'
    TOLD = 'Mode: ' + FIELD

    def texts_of(self, old, new):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [label(old)], Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [label(new)], Number=1))
        return [t for c in self.obj(self.compare('HEAD'), 'Silo').get('changes', []) for t in c['texts']]

    def test_another_tag_in_a_field_is_told_with_old_and_new(self):
        t, = self.texts_of(field_text(), field_text(infos=fieldinfo(sub=TAG % 'modeNext')))

        self.assertEqual(('Text', 'en-US', self.TOLD, self.TOLD.replace('modeNow', 'modeNext')),
                         (t['part'], t['culture'], t['old'], t['new']))

    def test_each_value_of_a_field_is_told(self):
        for kw, word in (({'ref': LIST % 'Speeds'}, 'HmiTextList:Speeds'), ({'domain': 'OtherDomain'}, 'OtherDomain'),
                         ({'length': '9'}, 'length 9')):
            with self.subTest(word):
                self.fresh()
                t, = self.texts_of(field_text(), field_text(infos=fieldinfo(**kw)))

                self.assertEqual(self.TOLD, t['old'])
                self.assertIn(word, t['new'])

    def test_a_field_added_or_moved_in_the_text_is_told(self):
        t, = self.texts_of(field_text(body='Mode: '), field_text())
        self.assertEqual(('Mode: \n' + self.FIELD, self.TOLD), (t['old'], t['new']))   # its info is read unused too

        self.fresh()
        t, = self.texts_of(field_text(), field_text(body='<field ref="0" /> :Mode'))
        self.assertEqual(self.FIELD + ' :Mode', t['new'])

    def test_a_field_pointing_at_nothing_is_told(self):
        t, = self.texts_of(field_text(), field_text(body='Mode: <field ref="7" />'))

        self.assertEqual('Mode: {no field 7}\n' + self.FIELD, t['new'])

    def test_fields_renumbered_with_the_same_meaning_are_no_change(self):
        renumbered = field_text(body='Mode: <field ref="3" />', infos=fieldinfo(name='3'))

        self.assertEqual([], self.texts_of(field_text(), renumbered))

    def test_a_text_without_fields_reads_as_before(self):
        t, = self.texts_of(field_text(body='a<br />b', infos=''), field_text(body='a<br />c', infos=''))

        self.assertEqual(('a\nb', 'a\nc'), (t['old'], t['new']))

    def test_a_field_in_a_list_entry_is_told(self):
        self.repo.export('textlist', 'Modes', list_doc([field_text()]))
        self.repo.commit()
        self.repo.export('textlist', 'Modes', list_doc([field_text(infos=fieldinfo(sub=TAG % 'modeNext'))]))

        c, = self.obj(self.compare('HEAD'), 'Modes')['changes']

        self.assertEqual(self.TOLD.replace('modeNow', 'modeNext'), c['texts'][0]['new'])

    def test_a_new_list_entry_tells_its_field(self):
        self.repo.export('textlist', 'Modes', list_doc([]))
        self.repo.commit()
        self.repo.export('textlist', 'Modes', list_doc([field_text()]))

        c, = self.obj(self.compare('HEAD'), 'Modes')['changes']

        self.assertEqual(['From = 1', 'To = 1', 'Text[en-US] = ' + self.TOLD], c['facts'])


def layered(name, layers, number=1):
    """A screen with the layers [(index, visible, items)]."""
    doc = document('screen', name, Number=number)
    body = ''.join('<Hmi.Screen.ScreenLayer ID="0" CompositionName="Layers"><AttributeList><Index>%d</Index><Name />'
                   '<VisibleES>%s</VisibleES></AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.ScreenLayer>'
                   % (i, 'true' if v else 'false', ''.join(items)) for i, v, items in layers)
    start = doc.index('<Hmi.Screen.ScreenLayer')
    return doc[:start] + body + doc[doc.index('</Hmi.Screen.ScreenLayer>') + len('</Hmi.Screen.ScreenLayer>'):]


class FieldUsesTest(RepoCase):
    """A tag or list named only in a text field is used: by "Used by" and "still used" as by any other link."""
    SILO = [{'kind': 'screen', 'name': 'Silo'}]

    def table_without(self, gone, write_doc, write_doc_after=None):
        """The change records of the tag table with tag gone deleted, by tag."""
        self.repo.write('hmi/tags/Plant.xml', tag_table('Plant', [tag('Keep', 'Keep'), tag(gone, gone)]))
        write_doc()
        self.repo.commit()
        self.repo.write('hmi/tags/Plant.xml', tag_table('Plant', [tag('Keep', 'Keep')]))
        if write_doc_after:
            write_doc_after()
        return {c['object']: c for c in self.obj(self.compare('HEAD'), 'Plant')['changes']}

    def on_screen(self, infos):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [label(field_text(infos=infos))], Number=1))

    def test_a_tag_only_in_a_text_field_is_still_used(self):
        by = self.table_without('modeNow', lambda: self.on_screen(fieldinfo()))

        self.assertEqual((self.SILO, True), (by['modeNow']['usedAfter'], by['modeNow']['stillUsed']))

    def test_a_tag_only_in_a_field_is_told_by_its_base_name(self):
        for named, base in (('Motor.speed', 'Motor'), ('Lanes[3].mode', 'Lanes'), ('"Lane[3]".mode', 'Lane[3]')):
            with self.subTest(named):
                self.fresh()
                by = self.table_without(base, lambda: self.on_screen(fieldinfo(sub=TAG % named)))

                self.assertEqual(self.SILO, by[base]['usedAfter'])

    def test_a_tag_as_the_field_s_reference_counts(self):
        by = self.table_without('modeNow', lambda: self.on_screen(
            '<fieldinfo name="0" domaintype="HMICommonTagDisplayFormat"><reference TargetID="@OpenLink"><name>%s</name>'
            '</reference></fieldinfo>' % (TAG % 'modeNow')))

        self.assertEqual(self.SILO, by['modeNow']['usedAfter'])

    def test_a_list_only_in_a_text_field_is_used_by_the_screen(self):
        self.repo.export('textlist', 'Modes', text_list('Modes', [(0, 'Off')]))
        self.on_screen(fieldinfo())
        self.repo.commit()
        self.repo.export('textlist', 'Modes', text_list('Modes', [(0, 'Auto')]))

        self.assertEqual({'before': self.SILO, 'after': self.SILO}, self.obj(self.compare('HEAD'), 'Modes')['usedBy'])

    def test_a_tag_only_in_a_list_entry_s_field_is_still_used_by_the_list(self):
        by = self.table_without('modeNow', lambda: self.repo.export('textlist', 'Modes', list_doc([field_text()])))

        self.assertEqual(([{'kind': 'textlist', 'name': 'Modes'}], True),
                         (by['modeNow']['usedAfter'], by['modeNow']['stillUsed']))

    def test_a_field_taken_out_ends_the_use(self):
        c = self.table_without('modeNow', lambda: self.on_screen(fieldinfo()), lambda: self.on_screen(''))['modeNow']

        self.assertEqual((self.SILO, [], None), (c['usedBefore'], c['usedAfter'], c.get('stillUsed')))

    def test_every_link_a_field_holds_counts_as_the_text_row_reads_it(self):
        def uses(info):
            return changes.field_uses(ET.fromstring('<Text><fieldinfos>%s</fieldinfos></Text>' % info))

        for why, info, expected in (
                ('both links', fieldinfo(), {('TextList', 'Modes'), ('Tag', 'modeNow')}),
                ('a graphic list', '<fieldinfo><reference><name>Vendor.Hmi.Lists.HmiGraphicList:Lamps</name>'
                                   '</reference></fieldinfo>', {('GraphicList', 'Lamps')}),
                ('deeper down', '<fieldinfo><domaindata><link><name>%s</name></link></domaindata></fieldinfo>'
                                % (TAG % 'modeNow'), {('Tag', 'modeNow')}),
                ('the name as the text of the link', '<fieldinfo><reference> %s </reference></fieldinfo>'
                                                     % (TAG % 'modeNow'), {('Tag', 'modeNow')}),
                ('no namespace', '<fieldinfo><reference>HmiTag:modeNow</reference></fieldinfo>', {('Tag', 'modeNow')}),
                ('not a link', '<fieldinfo><format length="5">5</format><x>Other:thing</x></fieldinfo>', set())):
            with self.subTest(why):
                self.assertEqual(expected, uses(info))


class OrderTest(RepoCase):
    """layerOrder: an object's position in the document's list of its layer or group, the order in the export."""

    def order_lines(self, before, after, kind='screen'):
        self.repo.export(kind, 'Silo', before)
        self.repo.commit()
        self.repo.export(kind, 'Silo', after)
        return [l for c in self.obj(self.compare('HEAD'), 'Silo', kind).get('changes', ()) for l in c['lines']]

    def test_two_objects_that_swap_are_both_named(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b', top=200)]),
                                 document('screen', 'Silo', [rect('b', top=200), rect('a')]))

        self.assertEqual(["Rectangle b: layerOrder '2' -> '1'",
                          "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_one_brought_to_the_end_of_the_list_is_one_row_the_others_only_shifted(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b'), rect('c'), rect('d')]),
                                 document('screen', 'Silo', [rect('b'), rect('c'), rect('d'), rect('a')]))

        self.assertEqual(["Rectangle a: layerOrder '1' -> '4'"], lines)

    def test_three_reversed_the_one_in_the_middle_keeps_its_position_and_has_no_row(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b'), rect('c')]),
                                 document('screen', 'Silo', [rect('c'), rect('b'), rect('a')]))

        self.assertEqual(["Rectangle c: layerOrder '3' -> '1'", "Rectangle a: layerOrder '1' -> '3'"], lines)

    def test_every_pair_that_changed_sides_has_a_row_on_one_of_the_two(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b'), rect('c'), rect('d'), rect('e')]),
                                 document('screen', 'Silo', [rect('b'), rect('c'), rect('a'), rect('e'), rect('d')]))

        self.assertEqual(["Rectangle a: layerOrder '1' -> '3'", "Rectangle e: layerOrder '5' -> '4'",
                          "Rectangle d: layerOrder '4' -> '5'"], lines)

    def test_an_object_new_or_gone_between_two_others_changes_no_order(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('gone'), rect('b')]),
                                 document('screen', 'Silo', [rect('a'), rect('new'), rect('b')]))

        self.assertEqual(['Rectangle new: added at (10, 90) 100x50', 'Rectangle gone: removed from (10, 90) 100x50'],
                         lines)

    def test_objects_only_shifted_by_a_new_or_gone_one_have_no_row(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('gone'), rect('a'), rect('b')]),
                                 document('screen', 'Silo', [rect('a'), rect('b'), rect('new')]))

        self.assertEqual(['Rectangle new: added at (10, 90) 100x50', 'Rectangle gone: removed from (10, 90) 100x50'],
                         lines)

    def test_the_positions_are_those_in_the_file_also_with_others_new_or_gone(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('gone'), rect('a'), rect('b')]),
                                 document('screen', 'Silo', [rect('b'), rect('a')]))

        self.assertEqual(["Rectangle b: layerOrder '3' -> '1'", 'Rectangle gone: removed from (10, 90) 100x50'], lines)

    def test_one_whose_position_stays_the_same_has_no_row_those_it_passed_have_them(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('x'), rect('y'), rect('a'), rect('b'), rect('c')]),
                                 document('screen', 'Silo', [rect('b'), rect('c'), rect('a')]))

        self.assertEqual(["Rectangle b: layerOrder '4' -> '1'", "Rectangle c: layerOrder '5' -> '2'",
                          'Rectangle x: removed from (10, 90) 100x50', 'Rectangle y: removed from (10, 90) 100x50'],
                         lines)

    def test_same_order_with_another_object_changed_tells_no_order(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b')]),
                                 document('screen', 'Silo', [rect('a', left=20), rect('b')]))

        self.assertEqual(['Rectangle a: moved (10, 90) 100x50 -> (20, 90) 100x50'], lines)

    def test_a_move_and_an_order_change_of_one_object_are_both_told(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('a'), rect('b')]),
                                 document('screen', 'Silo', [rect('b'), rect('a', left=20)]))

        self.assertEqual(["Rectangle b: layerOrder '2' -> '1'",
                          'Rectangle a: moved (10, 90) 100x50 -> (20, 90) 100x50',
                          "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_each_layer_has_its_own_order(self):
        lines = self.order_lines(layered('Silo', [(0, True, [rect('a'), rect('b')]), (2, True, [rect('c')])]),
                                 layered('Silo', [(0, True, [rect('b'), rect('a')]), (2, True, [rect('c')])]))

        self.assertEqual(["Rectangle b: layerOrder '2' -> '1'",
                          "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_objects_on_two_layers_written_the_other_way_round_change_no_order(self):
        lines = self.order_lines(layered('Silo', [(0, True, [rect('a')]), (2, True, [rect('b')])]),
                                 layered('Silo', [(2, True, [rect('b')]), (0, True, [rect('a')])]))

        self.assertEqual([], lines)

    def test_an_object_put_on_another_layer_has_no_order_row(self):
        lines = self.order_lines(layered('Silo', [(0, True, [rect('a'), rect('b')]), (2, True, [])]),
                                 layered('Silo', [(0, True, [rect('b')]), (2, True, [rect('a')])]))

        self.assertEqual(["Rectangle a: Layer '0' -> '2'"], lines)

    def test_two_objects_that_change_layer_together_and_swap_are_told(self):
        lines = self.order_lines(layered('Silo', [(0, True, [rect('a'), rect('b')]), (2, True, [])]),
                                 layered('Silo', [(0, True, []), (2, True, [rect('b'), rect('a')])]))

        self.assertEqual(["Rectangle b: Layer '0' -> '2'", "Rectangle b: layerOrder '2' -> '1'",
                          "Rectangle a: Layer '0' -> '2'", "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_members_that_swap_in_a_renamed_group_are_told(self):
        lines = self.order_lines(document('screen', 'Silo', [group('g', rect('a'), rect('b'))]),
                                 document('screen', 'Silo', [group('h', rect('b'), rect('a'))]))

        self.assertIn("Rectangle b: layerOrder '2' -> '1'", lines)
        self.assertIn("Rectangle a: layerOrder '1' -> '2'", lines)

    def test_members_that_swap_on_their_way_to_another_group_are_told(self):
        lines = self.order_lines(document('screen', 'Silo', [group('g1', rect('a'), rect('b'), rect('x')),
                                                             group('g2', rect('y'))]),
                                 document('screen', 'Silo', [group('g1', rect('x')),
                                                             group('g2', rect('b'), rect('a'), rect('y'))]))

        self.assertEqual(["Group g1: Members 'a, b, x' -> 'x'", "Group g2: Members 'y' -> 'b, a, y'",
                          "Rectangle b: Group 'g1' -> 'g2'", "Rectangle b: layerOrder '2' -> '1'",
                          "Rectangle a: Group 'g1' -> 'g2'", "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_members_of_a_group_that_swap_are_named_and_the_group_is_not(self):
        lines = self.order_lines(document('screen', 'Silo', [rect('x'), group('g', rect('a'), rect('b'))]),
                                 document('screen', 'Silo', [rect('x'), group('g', rect('b'), rect('a'))]))

        self.assertEqual(["Rectangle b: layerOrder '2' -> '1'",
                          "Rectangle a: layerOrder '1' -> '2'"], lines)

    def test_a_group_that_changes_sides_is_told_and_its_members_are_not(self):
        g = group('g', rect('a'), rect('b'))
        lines = self.order_lines(document('screen', 'Silo', [g, rect('x')]),
                                 document('screen', 'Silo', [rect('x'), g]))

        self.assertEqual(["Rectangle x: layerOrder '2' -> '1'", "Group g: layerOrder '1' -> '2'"], lines)

    def test_a_template_and_a_pop_up_tell_it_as_a_screen(self):
        for kind in ('template', 'popup'):
            with self.subTest(kind):
                lines = self.order_lines(document(kind, 'Silo', [rect('a'), rect('b')]),
                                         document(kind, 'Silo', [rect('b'), rect('a')]), kind)

                self.assertEqual(["Rectangle b: layerOrder '2' -> '1'",
                                  "Rectangle a: layerOrder '1' -> '2'"], lines)


class GroupTest(RepoCase):
    """Which group an object stands in: the rows 'Group' of the object and 'Members' of the group, and the box of a
    group on the drawing."""

    def by_object(self, before, after, kind='screen'):
        self.repo.export(kind, 'Silo', document(kind, 'Silo', before))
        self.repo.commit()
        self.repo.export(kind, 'Silo', document(kind, 'Silo', after))
        return {c['object']: c for c in self.obj(self.compare('HEAD'), 'Silo', kind).get('changes', ())}

    def test_each_object_that_changes_its_group_says_from_where_to_where(self):
        a, b, c, d, x, y = (rect(n) for n in 'abcdxy')
        cases = {
            'out of a group': ([group('g', a, b), x], [group('g', b), a, x], {'a': ('g', None)}),
            'into a group': ([a, group('g', b)], [group('g', a, b)], {'a': (None, 'g')}),
            'two that swap groups': ([group('g1', a), group('g2', b)], [group('g1', b), group('g2', a)],
                                     {'a': ('g1', 'g2'), 'b': ('g2', 'g1')}),
            'all that swap groups': ([group('g1', a, b), group('g2', c, d)], [group('g1', c, d), group('g2', a, b)],
                                     {'a': ('g1', 'g2'), 'b': ('g1', 'g2'), 'c': ('g2', 'g1'), 'd': ('g2', 'g1')}),
            'one to another group': ([group('g1', a, x), group('g2', y)], [group('g1', x), group('g2', a, y)],
                                     {'a': ('g1', 'g2')}),
            'a group into a group': ([group('g1', a), group('g2', b)], [group('g1', a, group('g2', b))],
                                     {'g2': (None, 'g1')}),
        }
        for why, (before, after, expected) in cases.items():
            with self.subTest(why):
                self.fresh()
                rows = {name: (r['old'], r['new']) for name, change in self.by_object(before, after).items()
                        for r in change['attributes'] if r['name'] == 'Group'}
                self.assertEqual(expected, rows)

    def test_two_objects_put_in_a_new_group_are_named_by_it_and_marked(self):
        line = item('Hmi.Screen.Line', 'zzLine', StartLeft=10, StartTop=20, EndLeft=110, EndTop=20)
        box = rect('zzBox', left=50, top=100, width=100, height=50)

        by = self.by_object([line, box], [group('zzGroup', line, box)])

        self.assertEqual('added', by['zzGroup']['kind'])
        self.assertEqual([{'name': 'Members', 'old': None, 'new': 'zzLine, zzBox'}], by['zzGroup']['attributes'])
        self.assertEqual({'x': 10, 'y': 20, 'w': 140, 'h': 130}, by['zzGroup']['new'])
        self.assertEqual({'x': 50, 'y': 100, 'w': 100, 'h': 50}, by['zzBox']['old'])
        self.assertEqual({'x': 50, 'y': 100, 'w': 100, 'h': 50}, by['zzBox']['new'])
        self.assertEqual(["Rectangle zzBox: Group (none) -> 'zzGroup'"], by['zzBox']['lines'])

    def test_a_group_that_loses_and_gains_members_lists_them_before_and_after(self):
        a, x, y = rect('a'), rect('x'), rect('y')

        by = self.by_object([group('g1', a, x), group('g2', y)], [group('g1', x), group('g2', a, y)])

        self.assertEqual(["Group g1: Members 'a, x' -> 'x'"], by['g1']['lines'])
        self.assertEqual(["Group g2: Members 'y' -> 'a, y'"], by['g2']['lines'])

    def test_a_group_taken_apart_names_what_it_held(self):
        a, b = rect('a'), rect('b', top=200)

        by = self.by_object([group('g', a, b)], [a, b])

        self.assertEqual('removed', by['g']['kind'])
        self.assertEqual([{'name': 'Members', 'old': 'a, b', 'new': None}], by['g']['attributes'])
        self.assertEqual({'x': 10, 'y': 90, 'w': 100, 'h': 160}, by['g']['old'])

    def test_a_member_that_changes_in_the_commit_that_groups_it_says_both(self):
        before = [rect('a', BackColor='1, 1, 1'), rect('b', top=200)]
        after = [group('g', rect('a', left=40, BackColor='2, 2, 2'), rect('b', top=200))]

        by = self.by_object(before, after)

        self.assertEqual(["Rectangle a: moved (10, 90) 100x50 -> (40, 90) 100x50",
                          "Rectangle a: BackColor '1, 1, 1' -> '2, 2, 2'",
                          "Rectangle a: Group (none) -> 'g'"], by['a']['lines'])
        self.assertEqual({'x': 10, 'y': 90, 'w': 100, 'h': 50}, by['a']['old'])
        self.assertEqual({'x': 40, 'y': 90, 'w': 100, 'h': 50}, by['a']['new'])
        self.assertEqual([{'name': 'Members', 'old': None, 'new': 'a, b'}], by['g']['attributes'])

    def test_a_group_and_a_plain_object_of_its_name_are_each_drawn_as_they_are(self):
        a = rect('a', left=10, top=10, width=10, height=10)
        plain = rect('g', left=40, top=40, width=5, height=5)
        around_a, of_plain = {'x': 10, 'y': 10, 'w': 10, 'h': 10}, {'x': 40, 'y': 40, 'w': 5, 'h': 5}
        for why, before, after, old, new in (('group to plain', [group('g', a)], [plain, a], around_a, of_plain),
                                             ('plain to group', [plain, a], [group('g', a)], of_plain, around_a)):
            with self.subTest(why):
                self.fresh()
                by = self.by_object(before, after)
                self.assertEqual(old, by['g']['old'])
                self.assertEqual(new, by['g']['new'])
                self.assertEqual('moved', by['g']['kind'])

    def test_a_group_and_a_plain_object_of_its_name_on_one_box_did_not_move(self):
        a = rect('a', left=10, top=10, width=10, height=10)
        plain = rect('g', left=10, top=10, width=10, height=10)
        for why, before, after in (('group to plain', [group('g', a)], [plain, a]),
                                   ('plain to group', [plain, a], [group('g', a)])):
            with self.subTest(why):
                self.fresh()
                by = self.by_object(before, after)
                self.assertEqual('changed', by['g']['kind'])
                self.assertFalse([l for l in by['g']['lines'] if ': moved ' in l], by['g']['lines'])

    def test_a_new_order_inside_a_group_changes_no_members(self):
        a, b = rect('a'), rect('b')

        by = self.by_object([group('g', a, b)], [group('g', b, a)])

        self.assertEqual({'a', 'b'}, set(by))

    def test_a_row_on_a_group_is_drawn_around_its_members_on_each_side(self):
        a = rect('a', left=10, top=10, width=10, height=10)
        b = rect('b', left=40, top=40, width=10, height=10)
        x = rect('x', left=100, top=100, width=10, height=10)

        by = self.by_object([group('g', a, b), x], [x, group('g', a, b)])

        self.assertEqual('changed', by['g']['kind'])
        self.assertEqual(['layerOrder'], [r['name'] for r in by['g']['attributes']])
        self.assertEqual({'x': 10, 'y': 10, 'w': 40, 'h': 40}, by['g']['old'])
        self.assertEqual({'x': 10, 'y': 10, 'w': 40, 'h': 40}, by['g']['new'])

    def test_a_group_inside_a_group_counts_for_the_box_of_the_outer_one(self):
        a = rect('a', left=10, top=10, width=10, height=10)
        b = rect('b', left=90, top=90, width=10, height=10)

        by = self.by_object([], [group('g1', a, group('g2', b))])

        self.assertEqual({'x': 10, 'y': 10, 'w': 90, 'h': 90}, by['g1']['new'])
        self.assertEqual({'x': 90, 'y': 90, 'w': 10, 'h': 10}, by['g2']['new'])
        self.assertEqual([{'name': 'Members', 'old': None, 'new': 'a, g2'}], by['g1']['attributes'])

    def test_a_group_with_no_member_that_has_a_box_has_no_outline(self):
        by = self.by_object([], [group('g', item('Hmi.Screen.Button', 'b'))])

        self.assertIsNone(by['g']['new'])

    def test_a_template_and_a_pop_up_tell_it_as_a_screen(self):
        for kind in ('template', 'popup'):
            with self.subTest(kind):
                self.fresh()
                by = self.by_object([rect('a')], [group('g', rect('a'))], kind)
                self.assertEqual(["Rectangle a: Group (none) -> 'g'"], by['a']['lines'])

    def test_a_change_of_group_on_a_minimal_export_is_never_folded(self):
        for why, before, after, name in (('in', [rect('a')], [group('g', rect('a'))], 'a'),
                                         ('out', [group('g', rect('a'))], [rect('a')], 'a'),
                                         ('new group', [rect('a')], [group('g', rect('a'))], 'g'),
                                         ('gone group', [group('g', rect('a'))], [rect('a')], 'g')):
            with self.subTest(why):
                self.fresh()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', before, export_setting='None'))
                self.repo.commit()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', after, export_setting='None'))

                screen = self.obj(self.compare('HEAD'), 'Silo')

                c = next(c for c in screen['changes'] if c['object'] == name)
                self.assertNotIn('fold', c)
                self.assertEqual([], [r['name'] for r in c['attributes'] if r.get('fold')])
                self.assertNotIn('exportNoise', screen)


def process_value(tag_name):
    """Property ProcessValue on a tag, as an export writes it on an I/O field, bar, switch, slider or gauge."""
    return ('<Hmi.Screen.Property ID="0" CompositionName="Properties"><AttributeList><Name>ProcessValue</Name>'
            '</AttributeList><ObjectList><Hmi.Dynamic.TagConnectionDynamic ID="0" CompositionName="Dynamic">'
            '<AttributeList><Indirect>false</Indirect></AttributeList><LinkList>%s</LinkList>'
            '</Hmi.Dynamic.TagConnectionDynamic></ObjectList></Hmi.Screen.Property>' % tag_link(tag_name))


def screen_item(type_, name, *children, links='', **attrs):
    """A screen item of that type with those children in its ObjectList, written as given."""
    return item('Hmi.Screen.' + type_, name, '%s<ObjectList>%s</ObjectList>' % (links, ''.join(children)), full=False,
                Left=200, Top=360, Width=120, Height=40, **attrs)


FONT = ('<Hmi.Globalization.MultiLingualFont ID="0" CompositionName="Font"><ObjectList>'
        '<Hmi.Globalization.FontItem ID="0" CompositionName="Items"><AttributeList><Culture>en-US</Culture>'
        '<FontFamily>Tahoma</FontFamily></AttributeList>'
        '</Hmi.Globalization.FontItem></ObjectList></Hmi.Globalization.MultiLingualFont>')


def screen_parameter(screen):
    return ('<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList><Name>Screen name'
            '</Name></AttributeList><LinkList><Value TargetID="@OpenLink"><Name>%s</Name></Value></LinkList>'
            '</Hmi.Event.FunctionListEntryParameter>' % screen)


def click(function, parameters=''):
    """Event Click calling that system function, as an export writes it."""
    return ('<Hmi.Event.Event ID="0" CompositionName="Events"><AttributeList><Name>Click</Name></AttributeList>'
            '<ObjectList><Hmi.Event.FunctionListEventHandler ID="0" CompositionName="EventHandler"><ObjectList>'
            '<Hmi.Event.FunctionListEntry ID="0" CompositionName="FunctionListEntries"><AttributeList><Name>%s</Name>'
            '<Type>SystemFunction</Type></AttributeList><ObjectList>%s</ObjectList></Hmi.Event.FunctionListEntry>'
            '</ObjectList>'
            '</Hmi.Event.FunctionListEventHandler></ObjectList></Hmi.Event.Event>' % (function, parameters))


class AddedObjectTest(RepoCase):
    """What an added screen object is tied to, which the drawing cannot say, is in its change."""

    def added(self, *items, export_setting=FULL_SETTING):
        """The changes of a screen that gets those items, the side before as that export setting writes it."""
        self.repo.export('screen', 'Silo', document('screen', 'Silo', Number=1, export_setting=export_setting))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', list(items), Number=1))
        return self.obj(self.compare('HEAD'), 'Silo')['changes']

    @staticmethod
    def rows(change):
        return [(f['path'], f['old'], f['new']) for p in change['parts'] for f in p['facts']]

    def test_an_io_field_names_its_tag_and_mode(self):
        c, = self.added(screen_item('IOField', 'zzIO', process_value('zzT1'), Mode='Output'))

        self.assertEqual('added', c['kind'])
        self.assertEqual([{'name': 'Mode', 'old': None, 'new': 'Output'}], c['attributes'])
        self.assertEqual([('Property/Name', None, 'ProcessValue'),
                          ('Property/TagConnectionDynamic/Indirect', None, 'false'),
                          ('Property/TagConnectionDynamic/Tag', None, 'zzT1')], self.rows(c))
        self.assertEqual(['IOField zzIO: added at (200, 360) 120x40', "IOField zzIO: Mode (none) -> 'Output'",
                          "IOField zzIO: Property/Name 'ProcessValue' added",
                          "IOField zzIO: Property/TagConnectionDynamic/Indirect 'false' added",
                          "IOField zzIO: Property/TagConnectionDynamic/Tag 'zzT1' added"], c['lines'])

    def test_its_mode_is_not_folded_after_a_minimal_export(self):
        c, = self.added(screen_item('IOField', 'zzIO', Mode='Input'), export_setting='None')

        self.assertEqual([{'name': 'Mode', 'old': None, 'new': 'Input'}], c['attributes'])

    def test_every_kind_on_a_tag_names_it(self):
        for type_, tag_name in (('Bar', 'zzT3'), ('Switch', 'zzT2'), ('Slider', 'zzT3'), ('Gauge', 'zzT3')):
            with self.subTest(type_):
                self.fresh()
                c, = self.added(screen_item(type_, 'zz', process_value(tag_name)))

                self.assertIn(('Property/TagConnectionDynamic/Tag', None, tag_name), self.rows(c))

    def test_a_symbolic_field_names_its_text_list(self):
        c, = self.added(screen_item('SymbolicIOField', 'zzSymbolic', process_value('zzT1'),
                                    links='<LinkList><TextList TargetID="@OpenLink"><Name>zzList</Name></TextList>'
                                          '</LinkList>'))

        self.assertEqual([{'kind': 'TextList', 'old': None, 'new': 'zzList'}], c['links'])
        self.assertIn("SymbolicIOField zzSymbolic: TextList link (none) -> 'zzList'", c['lines'])
        self.assertIn(('Property/TagConnectionDynamic/Tag', None, 'zzT1'), self.rows(c))

    def test_a_button_names_its_click_function_and_target(self):
        c, = self.added(screen_item('Button', 'zzButton', click('ActivateScreen', screen_parameter('zzB'))))

        path = 'Event/FunctionListEventHandler/FunctionListEntry(ActivateScreen)'
        self.assertEqual([('Event/Name', None, 'Click'),
                          (path + '/Name', None, 'ActivateScreen'),
                          (path + '/Type', None, 'SystemFunction'),
                          (path + '/FunctionListEntryParameter(Screen name)/Name', None, 'Screen name'),
                          (path + '/FunctionListEntryParameter(Screen name)/Value', None, 'zzB')], self.rows(c))

    def test_each_event_keeps_its_own_function_in_the_rows(self):
        press = click('First').replace('<Name>Click</Name>', '<Name>Press</Name>')
        release = click('Second').replace('<Name>Click</Name>', '<Name>Release</Name>')

        c, = self.added(screen_item('Button', 'zzButton', press, release))

        self.assertEqual(['Press', 'First', 'Release', 'Second'],
                         [new for path, _, new in self.rows(c) if path.endswith('/Name')])

    def test_a_tag_that_shows_or_colours_it_is_named(self):
        c, = self.added(screen_item('Rectangle', 'zzLamp', range_anim('zzT1', '0, 160, 0')))

        self.assertIn(('RangeAppearanceAnimation/TagElementTrigger/Tag', None, 'zzT1'), self.rows(c))

    def test_a_field_in_its_text_is_told_and_a_plain_text_or_font_is_not(self):
        c, = self.added(screen_item('TextField', 'zzPlain', text('Text', 'Back'), FONT))
        self.assertEqual(([], [], ['TextField zzPlain: added at (200, 360) 120x40']),
                         (c['texts'], c['parts'], c['lines']))

        self.fresh()
        c, = self.added(screen_item('TextField', 'zzField', field_text()))
        self.assertEqual([('Text', 'en-US', None, TextFieldsTest.TOLD)],
                         [(t['part'], t['culture'], t['old'], t['new']) for t in c['texts']])

    def test_the_list_of_the_preview_keeps_one_line(self):
        field = screen_item('IOField', 'zzIO', process_value('zzT1'), Mode='Output')

        change, = diff.diff_trees(ET.fromstring(document('screen', 'Silo', Number=1)),
                                  ET.fromstring(document('screen', 'Silo', [field], Number=1)))

        self.assertEqual(['IOField zzIO: added at (200, 360) 120x40'], change.lines())

    def test_a_new_screen_lists_the_same(self):
        self.repo.export('screen', 'Other', document('screen', 'Other', Number=2))
        self.repo.commit()
        field = screen_item('IOField', 'zzIO', process_value('zzT1'))
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [field], Number=1))

        silo = self.obj(self.compare('HEAD'), 'Silo')
        c, = silo['changes']

        self.assertEqual('new', silo['state'])
        self.assertIn(('Property/TagConnectionDynamic/Tag', None, 'zzT1'), self.rows(c))


class LayerAndFoldTest(RepoCase):
    def test_object_put_on_another_layer_and_a_layer_hidden(self):
        self.repo.export('screen', 'Silo', layered('Silo', [(0, True, [rect('r1')]), (2, True, [rect('r2', top=200)])]))
        self.repo.commit()
        self.repo.export('screen', 'Silo', layered('Silo', [(0, True, []),
                                                            (2, False, [rect('r1'), rect('r2', top=200)])]))

        result = self.compare('HEAD')

        self.assertEqual(["Screen Silo: Layer 2 VisibleES 'true' -> 'false'", "Rectangle r1: Layer '0' -> '2'"],
                         [l for c in self.obj(result, 'Silo')['changes'] for l in c['lines']])

    def test_another_radius_is_an_attribute_whatever_the_box_does(self):
        def circle(size, radius):
            return item('Hmi.Screen.Circle', 'c1', Left=10, Top=90, Width=size, Height=size, Radius=radius)
        for size in (40, 50):
            with self.subTest(size=size):
                self.fresh()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [circle(40, 20)], Number=1))
                self.repo.commit()
                self.repo.export('screen', 'Silo', document('screen', 'Silo', [circle(size, 33)], Number=1))

                silo = self.obj(self.compare('HEAD'), 'Silo')

                self.assertIn("Circle c1: Radius '20' -> '33'", silo['changes'][0]['lines'])

    def test_a_layer_with_another_index_reads_as_changed(self):
        self.repo.write('hmi/global/Elements.xml', layered('Elements', [(0, True, [])]))
        self.repo.commit()
        self.repo.write('hmi/global/Elements.xml', layered('Elements', [(5, True, [])]))

        elements = self.obj(self.compare('HEAD'), 'Elements')

        self.assertEqual('changed', elements['state'])
        self.assertEqual(["Screen Elements: Layers '0' -> '5'"], [l for c in elements['changes'] for l in c['lines']])

    def test_a_layer_added_beside_another_reads_as_changed(self):
        self.repo.export('screen', 'Silo', layered('Silo', [(0, True, [rect('r1')])]))
        self.repo.commit()
        self.repo.export('screen', 'Silo', layered('Silo', [(0, True, [rect('r1')]), (3, True, [])]))

        silo = self.obj(self.compare('HEAD'), 'Silo')

        self.assertEqual(["Screen Silo: Layers '0' -> '0, 3'"], [l for c in silo['changes'] for l in c['lines']])

    def test_layers_written_the_other_way_round_read_as_same(self):
        self.repo.export('screen', 'Silo', layered('Silo', [(0, True, [rect('r1')]), (2, True, [])]))
        self.repo.commit()
        self.repo.export('screen', 'Silo', layered('Silo', [(2, True, []), (0, True, [rect('r1')])]))

        self.assertEqual('same', self.obj(self.compare('HEAD'), 'Silo')['state'])

    def test_attribute_absent_in_a_minimal_export_is_folded(self):
        minimal = lambda tags: tag_table('Plant', tags)      # ExportSetting None
        self.repo.write('hmi/tags/Plant.xml', minimal([tag('Motor', 'Motor'), tag('Fan', 'Fan')]))
        self.repo.commit()
        self.repo.write('hmi/tags/Plant.xml', minimal([tag('Motor', 'Motor').replace('<Length>2</Length>', ''),
                                                       tag('Fan', 'Fan', cycle='1 s')]))

        table = self.obj(self.compare('HEAD'), 'Plant')

        by = {c['object']: c for c in table['changes']}
        self.assertEqual('export', by['Motor']['fold'])
        self.assertNotIn('fold', by['Fan'])
        self.assertEqual([{'name': 'Length', 'missing': 'after', 'count': 1}], table['exportNoise'])

    def test_a_cycle_exported_full_after_a_minimal_export_is_changed_and_folded(self):
        # TiaBridge exports cycles full from 2026-11-12: the first export of an older repo's cycles adds the
        # attributes the minimal one left out, a change of the file and not of the cycle
        self.repo.write('hmi/cycles/Fast.xml', cycle('Fast', 'None', full=False))
        self.repo.commit()
        self.repo.write('hmi/cycles/Fast.xml', cycle('Fast'))

        fast = self.obj(self.compare('HEAD'), 'Fast', 'cycle')

        self.assertEqual('changed', fast['state'])
        self.assertEqual(['export'], [c['fold'] for c in fast['changes']])
        self.assertEqual([{'name': n, 'missing': 'before', 'count': 1} for n in
                          ('StartAtStartingPoint', 'StartingPoint', 'TriggerAtShutdown', 'TriggerAtStartup')],
                         fast['exportNoise'])
        self.assertEqual({'before': 'None', 'after': FULL_SETTING}, fast['exportSetting'])

    def test_tab_order_alone_is_folded_as_without_visible_effect(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1', TabIndex=1), rect('r2', TabIndex=2)],
                                                    Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1', TabIndex=2),
                                                                       rect('r2', TabIndex=1, left=40)], Number=1))

        by = {c['object']: c for c in self.obj(self.compare('HEAD'), 'Silo')['changes']}

        self.assertEqual('quiet', by['r1']['fold'])
        self.assertNotIn('fold', by['r2'])                  # moved too
        self.assertEqual('quiet', by['r2']['attributes'][0]['fold'])


class MemberChangesTest(RepoCase):
    def test_tags_added_removed_changed_with_where_used(self):
        self.repo.write('hmi/tags/Plant.xml', tag_table('Plant', [tag('Motor', 'Motor'), tag('Lane[3]', 'Lanes[3]'),
                                                                  tag('Old', 'Old')]))
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [lamp('lamp1', 'Motor.run'),
                                                                       lamp('lamp2', '"Lane[3]".mode')], Number=1))
        self.repo.export('screen', 'Door', document('screen', 'Door', [lamp('lamp1', 'Old.x')], Number=2))
        self.repo.commit()
        self.repo.write('hmi/tags/Plant.xml', tag_table('Plant', [tag('Motor', 'Motor', cycle='1 s'),
                                                                  tag('Lane[3]', 'Lanes[3]'),
                                                                  tag('Fan', 'Fan', members=40, comment='cooling')]))

        result = self.compare('HEAD')

        table = self.obj(result, 'Plant')
        by = {c['object']: c for c in table['changes']}
        self.assertEqual(['Fan', 'Motor', 'Old'], sorted(by))
        self.assertEqual(["Tag Motor: AcquisitionCycle link '100 ms' -> '1 s'"], by['Motor']['lines'])
        self.assertEqual([{'kind': 'screen', 'name': 'Silo'}], by['Motor']['usedAfter'])
        self.assertEqual(['Tag Fan: added'], by['Fan']['lines'])
        self.assertIn('ControllerTag = Fan', by['Fan']['facts'])
        self.assertIn('Comment[en-US] = cooling', by['Fan']['facts'])
        self.assertEqual({'Members': 40}, by['Fan']['counts'])
        self.assertEqual(([{'kind': 'screen', 'name': 'Door'}], True), (by['Old']['usedAfter'], by['Old']['stillUsed']))

    def test_quoted_tag_link_names_the_whole_tag(self):
        self.assertEqual('Lane[3]', changes.tag_base('"Lane[3]".mode'))
        self.assertEqual('Lanes', changes.tag_base('Lanes[3].mode'))
        self.assertEqual('Motor', changes.tag_base('Motor'))

    def test_text_list_entries_and_where_used(self):
        self.repo.export('textlist', 'tlMode', text_list('tlMode', [(0, 'Off'), (1, 'Auto')]))
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [symbolic('sym1', 'tlMode')], Number=1))
        self.repo.commit()
        self.repo.export('textlist', 'tlMode', text_list('tlMode', [(0, 'Off'), (1, 'Automatic'), (2, 'Manual')]))

        result = self.compare('HEAD')

        tl = self.obj(result, 'tlMode')
        self.assertEqual(["TextListEntry 1..1: Text 'Auto' -> 'Automatic'", 'TextListEntry 2..2: added'],
                         [l for c in tl['changes'] for l in c['lines']])
        silo = [{'kind': 'screen', 'name': 'Silo'}]
        self.assertEqual({'before': silo, 'after': silo}, tl['usedBy'])
        self.assertIn('adoc', tl)              # the page draws symbolic I/O fields from it

    def test_root_attributes_of_a_table(self):
        self.repo.write('hmi/cycles/Fast.xml', tag_table('Fast', []).replace('<Name>Fast</Name>',
                                                                            '<Name>Fast</Name><Time>100</Time>'))
        self.repo.commit()
        self.repo.write('hmi/cycles/Fast.xml', tag_table('Fast', []).replace('<Name>Fast</Name>',
                                                                            '<Name>Fast</Name><Time>50</Time>'))

        result = self.compare('HEAD')

        self.assertEqual(["TagTable Fast: Time '100' -> '50'"],
                         self.obj(result, 'Fast', 'cycle')['changes'][0]['lines'])


PNG_A = b'\x89PNG\r\n\x1a\nfirst'
PNG_B = b'\x89PNG\r\n\x1a\nsecond'


def graphic(name, image=True):
    """A project graphic as TiaBridge exports it: <name>.xml naming '<name> files\\DefaultImageStream.png'."""
    stream = ('<DefaultImageStream external="path">%s files\\DefaultImageStream.png</DefaultImageStream>' % name
              if image else '')
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<Hmi.Globalization.MultiLingualGraphic ID="0"><AttributeList><DefaultDithering>false</DefaultDithering>'
            '%s<Name>%s</Name></AttributeList></Hmi.Globalization.MultiLingualGraphic></Document>\n' % (stream, name))


def graphic_view(name, picture):
    return item('Hmi.Screen.GraphicView', name,
                '<LinkList><Picture TargetID="@OpenLink"><Name>%s</Name></Picture></LinkList>' % picture,
                Left=10, Top=90, Width=64, Height=64)


class GraphicsTest(RepoCase):
    def put_image(self, name, data):
        full = os.path.join(self.repo.path, 'project', 'graphics', name + ' files', 'DefaultImageStream.png')
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(data)

    def setUp(self):
        super().setUp()
        self.repo.write('project/graphics/Logo.xml', graphic('Logo'))
        self.put_image('Logo', PNG_A)
        self.repo.write('project/graphics/Arrow.xml', graphic('Arrow'))
        self.put_image('Arrow', PNG_A)                     # the same image as Logo: embedded once
        self.repo.write('project/graphics/Unused.xml', graphic('Unused'))
        self.put_image('Unused', PNG_B)
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [graphic_view('gv1', 'Logo'),
                                                                       graphic_view('gv2', 'Arrow')], Number=1))
        self.repo.commit()

    def test_pictures_the_screens_use_are_embedded_once(self):
        result = self.compare('HEAD')

        self.assertEqual({'Logo', 'Arrow'}, set(result.pictures['after']))
        self.assertEqual(1, len(result.images))
        self.assertTrue(next(iter(result.images.values())).startswith('data:image/png;base64,'))
        self.assertEqual({'Arrow': 'same', 'Logo': 'same', 'Unused': 'same'},
                         {o['name']: o['state'] for o in result.objects if o['kind'] == 'graphic'})

    def test_every_image_with_all_images(self):
        result = self.compare('HEAD', all_images=True)

        self.assertEqual({'Logo', 'Arrow', 'Unused'}, set(result.pictures['after']))
        self.assertEqual(2, len(result.images))
        self.assertIn('aimg', self.obj(result, 'Unused', 'graphic'))

    def test_graphic_whose_xml_does_not_parse_is_skipped_and_named(self):
        self.repo.write('project/graphics/Logo.xml', '<Document><Hmi.Globalization.MultiLingualGraphic ID="0"><broken')

        result = self.compare('HEAD')

        self.assertEqual(['project/graphics/Logo.xml'], [p for p, _ in result.skipped])
        self.assertEqual([], [o for o in result.objects if o['name'] == 'Logo'])
        self.assertNotIn('Logo', result.pictures['after'])
        self.assertIn('Arrow', result.pictures['after'])

    def test_changed_image_is_a_graphic_object_with_where_used(self):
        self.put_image('Logo', PNG_B)

        result = self.compare('HEAD')

        logo = self.obj(result, 'Logo', 'graphic')
        self.assertEqual('changed', logo['state'])
        self.assertEqual(['MultiLingualGraphic Logo: image changed'], [l for c in logo['changes'] for l in c['lines']])
        self.assertNotEqual(logo['bimg'], logo['aimg'])
        self.assertEqual([{'device': '', 'kind': 'screen', 'name': 'Silo'}], logo['usedBy']['after'])
        self.assertEqual(result.pictures['after']['Logo'], logo['aimg'])

    def test_image_no_browser_draws_is_not_embedded_and_its_change_is_listed(self):
        def emf(data):
            full = os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'DefaultImageStream.emf')
            with open(full, 'wb') as f:
                f.write(data)
        self.repo.write('project/graphics/Logo.xml', graphic('Logo').replace('.png', '.emf'))
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'DefaultImageStream.png'))
        emf(b'first')
        self.repo.commit()
        emf(b'second')

        result = self.compare('HEAD')

        self.assertNotIn('Logo', result.pictures['after'])
        logo = self.obj(result, 'Logo', 'graphic')
        self.assertEqual('changed', logo['state'])
        self.assertEqual(['MultiLingualGraphic Logo: image changed'], [l for c in logo['changes'] for l in c['lines']])

    def put_file(self, rel, data):
        full = os.path.join(self.repo.path, 'project', 'graphics', *rel.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(data)

    def test_a_second_file_with_other_bytes_reads_as_changed(self):
        self.put_file('Logo files/Other.png', PNG_A)
        self.repo.commit()
        self.put_file('Logo files/Other.png', PNG_B)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual('changed', logo['state'])
        self.assertEqual(['MultiLingualGraphic Logo: file Other.png changed'],
                         [l for c in logo['changes'] for l in c['lines']])

    def rows_of(self, logo):
        return [(a['name'], a['old'], a['new']) for c in logo['changes'] for a in c['attributes']]

    def test_a_file_with_other_bytes_on_one_path_says_only_that_it_changed(self):
        self.put_file('Logo files/Other.png', PNG_A)
        self.repo.commit()
        self.put_file('Logo files/Other.png', PNG_B)
        self.put_image('Logo', PNG_B)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual([('Image changed', None, None), ('File Other.png changed', None, None)], self.rows_of(logo))

    def test_a_file_on_another_path_shows_both_paths(self):
        self.put_file('Logo files/Other.png', PNG_A)
        self.repo.commit()
        self.put_file('Sub/Logo files/Other.png', PNG_B)
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'Other.png'))
        self.move_logo_to_sub(PNG_B)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual(
            [('Image', 'project/graphics/Logo files/DefaultImageStream.png',
              'project/graphics/Sub/Logo files/DefaultImageStream.png'),
             ('File Other.png', 'project/graphics/Logo files/Other.png', 'project/graphics/Sub/Logo files/Other.png')],
            self.rows_of(logo))

    def test_a_file_on_one_side_only_shows_its_path(self):
        self.put_file('Logo files/Gone.png', PNG_A)
        self.repo.commit()
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'Gone.png'))
        self.put_file('Logo files/Came.png', PNG_A)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual([('File Came.png', None, 'project/graphics/Logo files/Came.png'),
                          ('File Gone.png', 'project/graphics/Logo files/Gone.png', None)], self.rows_of(logo))

    def test_a_second_file_added_or_gone_reads_as_changed(self):
        self.put_file('Logo files/Gone.png', PNG_A)
        self.repo.commit()
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'Gone.png'))
        self.put_file('Logo files/Came.png', PNG_A)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual(['MultiLingualGraphic Logo: file Came.png added', 'MultiLingualGraphic Logo: file Gone.png removed'],
                         [l for c in logo['changes'] for l in c['lines']])

    def test_a_second_file_equal_but_for_git_s_line_ends_reads_as_same(self):
        self.repo.git('config', 'core.autocrlf', 'true')
        self.put_file('Logo files/Other.svg', b'<svg>\r\n</svg>\r\n')
        self.repo.commit()
        self.repo.write('project/graphics/Logo.xml', graphic('Logo').replace(
            '<Hmi.Globalization', '<DocumentInfo><Created>2026</Created></DocumentInfo><Hmi.Globalization', 1))

        self.assertEqual('same', self.obj(self.compare('HEAD'), 'Logo', 'graphic')['state'])

    def test_a_file_that_was_the_default_image_and_stays_beside_the_new_one_is_told(self):
        self.put_file('Logo files/New.png', PNG_A)
        self.repo.commit()
        self.repo.write('project/graphics/Logo.xml', graphic('Logo').replace('DefaultImageStream.png', 'New.png'))
        self.put_image('Logo', PNG_B)                      # the old default, New.png equal to what it held

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertIn('MultiLingualGraphic Logo: file DefaultImageStream.png changed',
                      [l for c in logo['changes'] for l in c['lines']])

    def test_a_second_file_with_equal_bytes_on_sides_of_other_ids_reads_as_same(self):
        self.put_file('Logo files/Other.png', PNG_A)
        self.repo.commit()

        result = changes.compare(sides.side(self.repo.path, 'HEAD'), sides.FolderSide(self.repo.path))

        self.assertEqual('same', self.obj(result, 'Logo', 'graphic')['state'])

    def move_logo_to_sub(self, image):
        self.put_file('Sub/Logo.xml', graphic('Logo').encode('utf-8'))
        self.put_file('Sub/Logo files/DefaultImageStream.png', image)
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo.xml'))
        os.remove(os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'DefaultImageStream.png'))

    def test_a_graphic_moved_with_identical_bytes_reads_as_moved(self):
        self.move_logo_to_sub(PNG_A)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual(('changed', {'name': 'Logo', 'folder': ''}, 'Sub', []),
                         (logo['state'], logo['from'], logo['folder'], logo['changes']))

    def test_a_graphic_moved_with_another_image_says_both(self):
        self.move_logo_to_sub(PNG_B)

        logo = self.obj(self.compare('HEAD'), 'Logo', 'graphic')

        self.assertEqual({'name': 'Logo', 'folder': ''}, logo['from'])
        self.assertEqual(['MultiLingualGraphic Logo: image changed'], [l for c in logo['changes'] for l in c['lines']])

    def test_picture_files_are_the_images_a_browser_draws(self):
        self.repo.write('project/graphics/Vector.xml', graphic('Vector').replace('.png', '.emf'))
        full = os.path.join(self.repo.path, 'project', 'graphics', 'Vector files', 'DefaultImageStream.emf')
        os.makedirs(os.path.dirname(full))
        with open(full, 'wb') as f:
            f.write(b'emf')
        self.repo.write('project/graphics/NoImage.xml', graphic('NoImage', image=False))
        self.repo.write('project/graphics/Lost.xml', graphic('Lost'))                  # names a file that is not there
        self.repo.write('project/graphics/Broken.xml', '<Document><broken')

        files = changes.picture_files(sides.FolderSide(self.repo.path))

        self.assertEqual({'Logo': 'project/graphics/Logo files/DefaultImageStream.png',
                          'Arrow': 'project/graphics/Arrow files/DefaultImageStream.png',
                          'Unused': 'project/graphics/Unused files/DefaultImageStream.png'}, files)

    def test_graphic_exported_without_its_image(self):
        self.repo.write('project/graphics/Logo.xml', graphic('Logo', image=False))

        result = self.compare('HEAD')

        self.assertNotIn('Logo', result.pictures['after'])
        self.assertEqual("MultiLingualGraphic Logo: DefaultImageStream 'Logo files\\DefaultImageStream.png' -> (none)",
                         self.obj(result, 'Logo', 'graphic')['changes'][0]['lines'][0])

    def test_revision_lists_the_graphics_folder(self):
        files = sides.side(self.repo.path, 'HEAD').files()

        self.assertIn('project/graphics/Logo files/DefaultImageStream.png', files)
        self.assertEqual({'Logo', 'Arrow', 'Unused'}, set(sides.graphics(sides.side(self.repo.path, 'HEAD'))))


class TwoFoldersTest(unittest.TestCase):
    """Two export folders: a file's length and time say nothing about its bytes."""
    TIME = 1700000000

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.before, self.after = os.path.join(tmp.name, 'before'), os.path.join(tmp.name, 'after')

    def put(self, folder, path, data, at=TIME):
        full = os.path.join(folder, *path.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
        os.utime(full, (at, at))

    def put_logo(self, folder, image, at=TIME):
        self.put(folder, 'project/graphics/Logo.xml', graphic('Logo'), at)
        self.put(folder, 'project/graphics/Logo files/DefaultImageStream.png', image, at)

    def compare(self, name, kind=None):
        result = changes.compare(sides.FolderSide(self.before), sides.FolderSide(self.after))
        return next(o for o in result.objects if o['name'] == name and (kind is None or o['kind'] == kind))

    def test_other_bytes_of_equal_length_and_time_read_as_changed(self):
        self.put(self.before, 'hmi/screens/Main.xml', document('screen', 'Main', [rect('Box', left=100)], Number=1))
        self.put(self.after, 'hmi/screens/Main.xml', document('screen', 'Main', [rect('Box', left=200)], Number=1))

        main = self.compare('Main')

        self.assertEqual('changed', main['state'])
        self.assertEqual(['Rectangle Box: moved (100, 90) 100x50 -> (200, 90) 100x50'], main['changes'][0]['lines'])

    def test_a_tag_table_with_other_bytes_of_equal_length_and_time_reads_as_changed(self):
        self.put(self.before, 'hmi/tags/Motors.xml', tag_table('Motors', [tag('speed', 'DB1.speed', cycle='100 ms')]))
        self.put(self.after, 'hmi/tags/Motors.xml', tag_table('Motors', [tag('speed', 'DB1.speed', cycle='500 ms')]))

        self.assertEqual('changed', self.compare('Motors')['state'])

    def test_a_graphic_whose_image_has_other_bytes_of_equal_length_and_time_reads_as_changed(self):
        self.put_logo(self.before, b'image A')
        self.put_logo(self.after, b'image B')

        self.assertEqual('changed', self.compare('Logo', 'graphic')['state'])

    def test_identical_bytes_with_other_times_stay_unchanged(self):
        screen = document('screen', 'Main', [rect('Box')], Number=1)
        self.put(self.before, 'hmi/screens/Main.xml', screen, at=self.TIME)
        self.put(self.after, 'hmi/screens/Main.xml', screen, at=self.TIME + 3600)
        self.put_logo(self.before, b'image A', at=self.TIME)
        self.put_logo(self.after, b'image A', at=self.TIME + 3600)

        self.assertEqual(('same', 'same'), (self.compare('Main')['state'], self.compare('Logo', 'graphic')['state']))

    def test_a_document_moved_with_identical_bytes_reads_as_moved(self):
        screen = document('screen', 'Main', [rect('Box')], Number=1)
        self.put(self.before, 'hmi/screens/Main.xml', screen)
        self.put(self.after, 'hmi/screens/Units/Main.xml', screen)

        main = self.compare('Main')

        self.assertEqual(('changed', {'name': 'Main', 'folder': ''}), (main['state'], main['from']))
        self.assertEqual([], main['changes'])

    def test_a_moved_tag_table_that_does_not_parse_is_skipped(self):
        self.put(self.before, 'hmi/tags/Motors.xml', '<broken')
        self.put(self.after, 'hmi/tags/Units/Motors.xml', '<broken')

        result = changes.compare(sides.FolderSide(self.before), sides.FolderSide(self.after))

        self.assertEqual(['hmi/tags/Motors.xml'], [p for p, _ in result.skipped])

    def test_references_are_not_listed(self):
        self.put(self.after, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))
        self.put(self.after, 'hmi/references/other/screens/Copy.xml', document('screen', 'Copy', Number=2))

        for side in (sides.FolderSide, sides.FolderStamps):
            self.assertEqual(['hmi/screens/Main.xml'], list(side(self.after).files()))

    def denying(self, name, error=PermissionError):
        """os.scandir denies the folders called name, as Windows does without the right to list them."""
        real = os.scandir

        def scandir(path):
            if os.path.basename(path) == name:
                raise error(13, 'Access is denied', path)
            return real(path)
        return mock.patch('os.scandir', scandir)

    def test_a_folder_that_cannot_be_listed_is_named(self):
        screen = document('screen', 'Main', Number=1)
        self.put(self.before, 'hmi/screens/Units/Main.xml', screen)
        self.put(self.after, 'hmi/screens/Units/Main.xml', screen)

        for root in (self.before, self.after):
            with self.denying('Units'), self.assertRaisesRegex(ValueError, r'cannot read .*Units: Access is denied'):
                sides.FolderSide(root).files()
        with self.denying('Units'), self.assertRaisesRegex(ValueError, 'Units'):
            changes.compare(sides.FolderSide(self.before), sides.FolderSide(self.after))

    def test_a_root_that_cannot_be_listed_is_named(self):
        self.put(self.after, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))

        with self.denying('hmi'), self.assertRaisesRegex(ValueError, 'cannot read .*hmi'):
            sides.FolderSide(self.after).files()

    def test_a_missing_root_is_an_empty_listing(self):
        self.put(self.before, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))
        self.put(self.after, 'project/graphics/Logo.xml', graphic('Logo'))

        self.assertEqual(['hmi/screens/Main.xml'], list(sides.FolderSide(self.before).files()))
        self.assertEqual(['project/graphics/Logo.xml'], list(sides.FolderSide(self.after).files()))
        self.assertEqual({}, sides.FolderSide(os.path.join(self.after, 'nothing')).files())

    def test_a_folder_gone_below_a_root_is_named(self):
        self.put(self.after, 'hmi/screens/Units/Main.xml', document('screen', 'Main', Number=1))

        with self.denying('Units', FileNotFoundError), self.assertRaisesRegex(ValueError, 'cannot read .*Units'):
            sides.FolderSide(self.after).files()

    def test_stamps_list_the_rest_when_a_folder_is_gone(self):
        self.put(self.after, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))
        self.put(self.after, 'hmi/screens/Units/Door.xml', document('screen', 'Door', Number=2))

        with self.denying('Units', FileNotFoundError):
            self.assertEqual(['hmi/screens/Main.xml'], list(sides.FolderStamps(self.after).files()))

    def test_references_that_cannot_be_listed_stop_nothing(self):
        self.put(self.after, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))
        self.put(self.after, 'hmi/references/other/screens/Copy.xml', document('screen', 'Copy', Number=2))

        with self.denying('references'):
            self.assertEqual(['hmi/screens/Main.xml'], list(sides.FolderSide(self.after).files()))

    def test_a_listing_that_failed_leaves_no_part_of_it_behind(self):
        for name in 'ABC':
            self.put(self.after, 'hmi/screens/%s.xml' % name, document('screen', name, Number=1))
        side = sides.FolderSide(self.after)
        locked = os.path.join(self.after, 'hmi', 'screens', 'B.xml')

        with open(locked, 'r+b') as f:
            size = os.path.getsize(locked)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, size)
            try:
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, 'B.xml'):
                        side.files()
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, size)

        self.assertEqual(3, len(side.files()))

    def test_size_and_time_ids_are_refused_as_a_side(self):
        self.put(self.before, 'hmi/screens/Main.xml', document('screen', 'Main', Number=1))

        for pair in ((sides.FolderStamps, sides.FolderSide), (sides.FolderSide, sides.FolderStamps)):
            with self.assertRaisesRegex(ValueError, 'size and time'):
                changes.compare(pair[0](self.before), pair[1](self.before))


class BundleTest(unittest.TestCase):
    def test_bundle_binds_the_preview_modules_as_classic_scripts(self):
        js = jsbundle.bundle()

        self.assertIn('const X = (() => {', js)
        self.assertIn('const R = (() => {', js)
        self.assertIsNone(re.search(r'^\s*(import|export) ', js, flags=re.M))
        self.assertRegex(js, r'return \{[^}]*\bdrawItems\b')
        self.assertRegex(js, r'return \{[^}]*\bscreenItems\b')


class CliTest(RepoCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'hmipreview', 'changes', self.repo.path] + list(args),
                              cwd=PACKAGE_ROOT, capture_output=True, text=True, encoding='utf-8')

    def test_lines_and_json(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1', top=100)], Number=1))

        out = self.run_cli('HEAD')
        js = self.run_cli('HEAD', '--json')

        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual('changed  screen      Silo (1)', out.stdout.splitlines()[1])
        self.assertEqual('changed', json.loads(js.stdout)['objects'][0]['state'])

    def test_unknown_revision_exits_1(self):
        self.repo.commit()
        r = self.run_cli('nosuchrev')
        self.assertEqual(1, r.returncode)
        self.assertIn('no commit nosuchrev', r.stderr)


if __name__ == '__main__':
    unittest.main()
