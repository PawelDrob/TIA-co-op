"""The screen object catalogue: catalogue.json current with its inputs, consistent with the fixture exports, the
reader, and the build's help and export parsing on made-up samples."""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from hmipreview import catalogue

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(os.path.dirname(HERE), 'catalogue', 'build.py')
_spec = importlib.util.spec_from_file_location('catalogue_build', BUILD)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


class Current(unittest.TestCase):
    def test_outputs_are_current(self):
        cat, doc, problems = build.outputs()
        self.assertEqual([], problems)
        with open(build.OUT, encoding='utf-8') as f:
            self.assertEqual(cat, f.read(), 'catalogue.json is not current: python catalogue\\build.py')
        with open(build.DOC, encoding='utf-8') as f:
            self.assertEqual(build._doc_body(doc), build._doc_body(f.read()), 'docs page is not current')

    def test_fixture_carries_no_installation_details(self):
        for f in os.listdir(build.FIXTURE):
            root = ET.parse(os.path.join(build.FIXTURE, f)).getroot()
            self.assertIsNone(root.find('DocumentInfo/InstalledProducts'), f)
            self.assertEqual('WithDefaults, WithReadOnly', root.findtext('DocumentInfo/ExportSetting'), f)


class Contents(unittest.TestCase):
    def test_toolbox(self):
        tb = catalogue.toolbox()
        self.assertEqual(34, len(tb))
        self.assertEqual({'Basic objects': 8, 'Elements': 11, 'Controls': 15},
                         {g: sum(1 for t in tb if t['toolbox']['group'] == g)
                          for g in ('Basic objects', 'Elements', 'Controls')})
        through = [t['toolbox']['name'] for t in tb if t['openness']]
        self.assertEqual(20, len(through))
        self.assertIn('User view', through)
        self.assertNotIn('Alarm view', through)

    def test_every_fixture_attribute_with_its_default(self):
        for tag, fx in build.read_fixture().items():
            for name, value in fx['attributes']:
                entry = catalogue.attribute(tag, name)
                self.assertIsNotNone(entry, '%s %s' % (tag, name))
                self.assertEqual(value, entry['default'], '%s %s' % (tag, name))

    def test_display_names_and_groups(self):
        a = catalogue.attribute('Hmi.Screen.Line', 'LineEndShapeStyle')
        self.assertEqual(('Line-end shape', 'Appearance', 'Round', 'Flush'),
                         (a['display'], a['group'], a['default'], a['shown']))
        tab = catalogue.attribute('Hmi.Screen.Button', 'TabIndex')
        self.assertEqual((False, None), (tab['displayKnown'], tab['group']))
        font = catalogue.attribute('Hmi.Screen.TextField', '@Font')
        self.assertEqual(('font', 'Tahoma, 13px, style=Bold', 'Text format'), (font['kind'], font['default'], font['group']))

    def test_values_confirmed_and_documented(self):
        a = catalogue.attribute('Hmi.Screen.Rectangle', 'EdgeStyle')
        self.assertIn('Solid', a['values']['confirmed'])
        names = {d['name']: d for d in a['values']['documented']}
        self.assertEqual('hmiLineStyleDashDot', names['DashDot']['constant'])
        self.assertTrue(names['DashDot']['confirmed'])         # by the spelling round trip (2026-10-31)
        self.assertIn('DashDot', a['values']['confirmed'])
        # the help's TextField / IOField table (None, Solid) does not apply to a rectangle
        self.assertNotIn('None', names)

    def test_greyed_conditions(self):
        a = catalogue.attribute('Hmi.Screen.TextField', 'Height')
        self.assertEqual([{'attribute': 'FitToLargest', 'op': 'eq', 'values': ['true']}], a['greyedWhen'])
        self.assertEqual([{'always': True}], catalogue.attribute('Hmi.Screen.Circle', 'Width')['greyedWhen'])

    def test_controls_from_the_help(self):
        t = next(t for t in catalogue.toolbox() if t['toolbox']['name'] == 'Alarm view')
        self.assertEqual(('help', None, False), (t['source'], t['element'], t['openness']))
        self.assertTrue(t['attributes'])

    def test_parts(self):
        self.assertIn('FontStyle', catalogue.load()['parts']['Hmi.Globalization.FontItem']['attributes'])


class Parsing(unittest.TestCase):
    PAGE = ('<html><body><table class="title"><tr><td>X</td></tr></table>'
            '<p>Optional. Value range from -1 to 2.</p>'
            '<p>The objects "Rectangle" and "Circle" support the styles:</p>'
            '<table><tr><td>Value</td><td>VB constant</td><td>Explanation</td></tr>'
            '<tr><td>0</td><td>hmiWidgetStyleSolid</td><td>a</td></tr>'
            '<tr><td>1</td><td>hmiWidgetStyleDash</td><td>b</td></tr></table>'
            '<p>Other objects:</p>'
            '<table><tr><td>Designation</td><td>Description</td></tr><tr><td>None</td><td>c</td></tr></table>'
            '</body></html>')

    def test_value_tables(self):
        tables = build._value_tables(build.blocks(self.PAGE))
        self.assertEqual(['Rectangle', 'Circle'], tables[0]['scope'])
        self.assertEqual([{'value': 0, 'constant': 'hmiWidgetStyleSolid', 'name': 'Solid'},
                          {'value': 1, 'constant': 'hmiWidgetStyleDash', 'name': 'Dash'}], tables[0]['rows'])
        self.assertEqual((None, [{'value': None, 'constant': None, 'name': 'None'}]),
                         (tables[1]['scope'], tables[1]['rows']))

    def test_value_designation_table(self):
        page = ('<html><body><table><tr><td>Value</td><td>Designation</td><td>Description</td></tr>'
                '<tr><td>0</td><td>Top</td><td>A sentence.</td></tr>'
                '<tr><td>1</td><td>Bottom</td><td>Another sentence.</td></tr></table></body></html>')
        self.assertEqual([{'value': 0, 'constant': None, 'name': 'Top'}, {'value': 1, 'constant': None, 'name': 'Bottom'}],
                         build._value_tables(build.blocks(page))[0]['rows'])

    def test_value_description_table_keeps_names_not_sentences(self):
        page = ('<html><body><table><tr><td>Value</td><td>Description</td></tr>'
                '<tr><td>0</td><td>Rounded</td></tr>'
                '<tr><td>1</td><td>The edge sits on the line below the text.</td></tr></table></body></html>')
        self.assertEqual([{'value': 0, 'constant': None, 'name': 'Rounded'}],
                         build._value_tables(build.blocks(page))[0]['rows'])

    def test_range_row_expanded(self):
        page = ('<html><body><table><tr><td>Value</td><td>VB constant</td><td>Explanation</td></tr>'
                '<tr><td>0</td><td>hmiFillStyleSolid</td><td>a</td></tr>'
                '<tr><td>196608 - 196610</td><td>hmiFillStylePattern1 - hmiFillStylePattern3</td><td>b</td></tr>'
                '</table></body></html>')
        rows = build._value_tables(build.blocks(page))[0]['rows']
        self.assertEqual([(0, 'Solid'), (196608, 'Pattern1'), (196609, 'Pattern2'), (196610, 'Pattern3')],
                         [(r['value'], r['name']) for r in rows])

    def test_cut_names(self):
        self.assertEqual('cut', build._known({'display': 'Position of scale mark l...', 'flags': {'cut'}}))
        self.assertEqual('inferred', build._known({'display': 'Scale inner distance (layout)', 'flags': {'cut'}}))
        self.assertIs(True, build._known({'display': 'Height', 'flags': set()}))

    def test_conditions(self):
        attrs = {'Mode': 'enum', 'BorderWidth': 'number'}
        self.assertEqual({'attribute': 'Mode', 'op': 'in', 'values': ['Text', 'Invisible']},
                         build._cond('Mode in Text, Invisible', attrs))
        self.assertEqual({'attribute': 'BorderWidth', 'op': 'ne', 'values': ['0']}, build._cond('BorderWidth != 0', attrs))
        with self.assertRaises(ValueError):
            build._cond('Nope = 1', attrs)

    def test_scan_records_spellings_not_names(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo)
        os.makedirs(os.path.join(repo, 'hmi', 'screens'))
        doc = ('<Document><DocumentInfo><ExportSetting>WithDefaults, WithReadOnly</ExportSetting></DocumentInfo>'
               '<Hmi.Screen.Screen ID="0"><AttributeList><Name>Made Up Screen</Name><Number>7</Number></AttributeList>'
               '<ObjectList><Hmi.Screen.Rectangle ID="1" CompositionName="ScreenItems"><AttributeList>'
               '<ObjectName>rectSample</ObjectName><EdgeStyle>Dash</EdgeStyle><BackColor>1, 2, 3</BackColor>'
               '</AttributeList></Hmi.Screen.Rectangle></ObjectList></Hmi.Screen.Screen></Document>')
        with open(os.path.join(repo, 'hmi', 'screens', 'a.xml'), 'w', encoding='utf-8') as f:
            f.write(doc)
        seen = build.scan_exports([repo])
        rect = seen['elements']['Hmi.Screen.Rectangle']
        self.assertEqual({'EdgeStyle': ['Dash']}, rect['values'])
        self.assertEqual('colour', rect['attributes']['BackColor'])
        self.assertNotIn('rectSample', str(seen))
        self.assertNotIn('Made Up Screen', str(seen))

    def test_spellings_by_name_then_by_unclaimed_number(self):
        documented = [{'value': 0, 'name': 'Top'}, {'value': 1, 'name': 'Bottom'}, {'value': 3, 'name': 'Gray'},
                      {'value': 4, 'name': 'Colored'}, {'value': '65536*', 'name': 'Odd'}]
        members = {'Up': 0, 'Down': 1, 'Colored': 3}
        self.assertEqual({'Top': 'Up', 'Bottom': 'Down', 'Gray': None, 'Colored': 'Colored', 'Odd': None},
                         build._spellings(documented, members))

    def test_values_with_an_enum(self):
        documented = [{'value': 0, 'constant': None, 'name': 'Top'}, {'value': 1, 'constant': None, 'name': 'Bottom'},
                      {'value': 2, 'constant': None, 'name': 'Middle'}]
        v = build._values('enum', {'Up'}, documented, None, (), 'GraphX.Made', {'Up': 0, 'Down': 1},
                          {'Down': 'Up'})
        self.assertEqual(['Up'], v['confirmed'])
        self.assertEqual([('Up', True), ('Down', False), (None, False)],
                         [(d['spelling'], d['confirmed']) for d in v['documented']])
        self.assertEqual(('GraphX.Made', {'Down': 'Up'}), (v['enum'], v['lost']))
        text = build._values_text({'values': v})
        self.assertIn('lost in the round trip: `Down` (exported `Up`)', text)
        self.assertIn("Middle (2; not in TIA's enum)", text)

    def test_round_trip_confirms_what_came_back_and_loses_the_rest(self):
        rt = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, rt)
        os.makedirs(os.path.join(rt, 'back'))
        sent = {'values': [
            {'element': 'Hmi.Screen.Bar', 'object': 'zzBar1', 'attribute': 'BarOrientation', 'value': 'Down'},
            {'element': 'Hmi.Screen.Bar', 'object': 'zzBar2', 'attribute': 'BarOrientation', 'value': 'Left'},
            {'element': 'Hmi.Screen.Bar', 'object': 'zzBar3', 'attribute': 'BarOrientation', 'value': 'Up'}]}
        with open(os.path.join(rt, 'sent.json'), 'w', encoding='utf-8') as f:
            json.dump(sent, f)
        bars = ''.join('<Hmi.Screen.Bar ID="%d" CompositionName="ScreenItems"><AttributeList><ObjectName>%s'
                       '</ObjectName><BarOrientation>%s</BarOrientation></AttributeList></Hmi.Screen.Bar>' % (i, n, v)
                       for i, (n, v) in enumerate((('zzBar1', 'Down'), ('zzBar2', 'Up'))))
        with open(os.path.join(rt, 'back', 'zzTestSpellings.xml'), 'w', encoding='utf-8') as f:
            f.write('<Document><Hmi.Screen.Screen ID="9"><AttributeList><Name>zz</Name></AttributeList><ObjectList>'
                    '%s</ObjectList></Hmi.Screen.Screen></Document>' % bars)
        with mock.patch.object(build, 'ROUNDTRIP', rt):
            out, problems = build.read_roundtrip()
        r = out[('Hmi.Screen.Bar', 'BarOrientation')]
        self.assertEqual(({'Down'}, {'Left': 'Up'}), (r['confirmed'], r['lost']))
        self.assertEqual(['round trip: Hmi.Screen.Bar zzBar3 not in the export back'], problems)

    def test_documented_values_carry_their_export_spelling(self):
        a = catalogue.attribute('Hmi.Screen.Bar', 'BarOrientation')
        self.assertEqual('GraphX.BarOrientation', a['values']['enum'])
        self.assertEqual({'Top': 'Up', 'Bottom': 'Down', 'Left': 'Left', 'Right': 'Right'},
                         {d['name']: d['spelling'] for d in a['values']['documented']})


if __name__ == '__main__':
    unittest.main()
