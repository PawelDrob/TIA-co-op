"""Generator runs (hmixml) against a fixture project repo: what a run writes, and that it refuses on validator errors.

The rules themselves are tested through validate(); here only the generator's use of it.
"""
import json
import os
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest import mock

import hmipreview
import hmixml
from Tests.fixture import TP1200, FixtureRepo, document, item, rect


def _reference():
    """A full export (fixture shape) holding the style presets S-Panel (rectangle) and S-Title (text field, in
    group grpRef) and the graphic view picRef."""
    title = item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
                 VerticalAlignment='Middle', children='<ObjectList>%s</ObjectList>' % ml_text('Text', ['Title']))
    grp = ('<Hmi.Screen.Group ID="0" CompositionName="ScreenItems"><AttributeList><ObjectName>grpRef</ObjectName>'
           '<TabIndex>-1</TabIndex></AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.Group>' % title)
    pic = item('Hmi.Screen.GraphicView', 'picRef', Left=300, Top=90, Width=64, Height=64,
               children='<LinkList><Picture TargetID="@OpenLink"><Name>Logo</Name></Picture></LinkList>')
    return document('screen', 'Reference', [rect('S-Panel', BackColor='200, 200, 200'), grp, pic],
                    template='Reference template', Number=1, BackColor='255, 255, 255')


def ml_text(comp, lines):
    items = ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                    '<Text><body><p>%s</p></body></Text></AttributeList></MultilingualTextItem>' % (c, lines[0])
                    for c in ('en-US', 'es-ES'))
    return '<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>' % (
        comp, items)


REFERENCE = _reference()


def reference_export(repo):
    """A reference export in the shape hmixml writes, holding the style preset S-Panel; loaded as templates."""
    rel = repo.export('screen', 'Reference', REFERENCE)
    hmixml.set_colours({'screen': (255, 255, 255)})
    hmixml.load_templates(os.path.join(repo.path, *rel.split('/')))
    return rel


def panel(name, x=10, y=90, w=100, h=50):
    return hmixml.item({'name': name, 'type': 'Rectangle', 'style': 'S-Panel', 'x': x, 'y': y, 'w': w, 'h': h,
                        'group': None, 'm': {}})


def read_json(repo, rel):
    with open(os.path.join(repo.path, *rel.split('/')), encoding='utf-8-sig') as f:
        return json.load(f)


class GeneratorRunTest(unittest.TestCase):
    def make(self, type_identifier=TP1200):
        repo = FixtureRepo(type_identifier=type_identifier)
        self.addCleanup(repo.cleanup)
        hardware = hmipreview.resolution.resolve(type_identifier)
        if hardware is not None:                       # the declared panel is the hardware
            repo.panel(hardware.panel, hardware.width, hardware.height, hardware.portrait)
        reference_export(repo)
        return repo

    def test_run_writes_documents_and_planned_items(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.plan('faceplate', 'faceplateNew V 0.0.1', 'built by hand from staging screen 9101')
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')]), folder='zzStaging')
        hmixml.finish()

        self.assertEqual('hmi/generated/screens/zzStaging/9101 - Staging.xml', rel)
        written = ET.parse(os.path.join(repo.path, *rel.split('/'))).getroot()
        self.assertEqual('9101 - Staging', written.find('Hmi.Screen.Screen/AttributeList/Name').text)
        self.assertEqual([{'kind': 'faceplate', 'name': 'faceplateNew V 0.0.1',
                           'note': 'built by hand from staging screen 9101'}],
                         read_json(repo, 'hmi/generated/planned.json'))

    def test_run_records_the_generation_time_of_each_document(self):
        repo = self.make()
        hmixml.begin(repo.path)
        first = hmixml.add('screen', hmixml.screen_doc('9101 - A', 9101, [panel('rectA')]))
        hmixml.finish()
        hmixml.begin(repo.path)
        second = hmixml.add('screen', hmixml.screen_doc('9102 - B', 9102, [panel('rectB')]))
        before = datetime.now(timezone.utc)
        hmixml.finish()

        times = read_json(repo, 'hmi/generated/generated.json')
        self.assertEqual({first, second}, set(times))       # entries of earlier runs stay while their file does
        recorded = datetime.fromisoformat(times[second]['generated'])
        self.assertIsNotNone(recorded.tzinfo)
        self.assertLessEqual(abs((recorded - before).total_seconds()), 5)
        self.assertEqual({'rectB': {'preset': 'S-Panel', 'source': 'S-Panel', 'document': 'hmi/screens/Reference.xml'}},
                         times[second]['presets'])

    # project B gen_station 2026-10-06: the exports have no S- objects; the generator keys its templates by alias.
    def stage_export(self, repo):
        """A second reference export whose rectangle is not named S-..."""
        return repo.export('screen', 'Stage', REFERENCE.replace('S-Panel', 'rectStage').replace(
            '<Name>Reference</Name>', '<Name>Stage</Name>').replace('<Number>1</Number>', '<Number>2</Number>'))

    def alias_box(self, name):
        return hmixml.item({'name': name, 'type': 'Rectangle', 'style': 'S-Box', 'x': 10, 'y': 90, 'w': 100,
                            'h': 50, 'group': None, 'm': {}})

    def test_alias_filled_by_hand_records_key_and_source_object_and_passes(self):
        repo = self.make()
        rel = self.stage_export(repo)
        hmixml.troot = ET.parse(os.path.join(repo.path, *rel.split('/'))).getroot()
        stage = next(e for e in hmixml.troot.iter() if e.findtext('AttributeList/ObjectName') == 'rectStage')
        hmixml.TPL['S-Box'] = stage
        hmixml.begin(repo.path)
        doc = hmixml.add('screen', hmixml.screen_doc('9101 - Alias', 9101, [self.alias_box('rectA')]))
        hmixml.finish()
        self.assertEqual({'rectA': {'preset': 'S-Box', 'source': 'rectStage', 'document': None}},
                         read_json(repo, 'hmi/generated/generated.json')[doc]['presets'])

    def test_load_templates_with_aliases_records_the_source_document(self):
        repo = self.make()
        rel = self.stage_export(repo)
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')), aliases={'S-Box': 'rectStage'})
        hmixml.begin(repo.path)
        doc = hmixml.add('screen', hmixml.screen_doc('9101 - Alias', 9101, [self.alias_box('rectA')]))
        hmixml.finish()
        self.assertEqual({'rectA': {'preset': 'S-Box', 'source': 'rectStage', 'document': rel}},
                         read_json(repo, 'hmi/generated/generated.json')[doc]['presets'])

    def test_alias_whose_source_is_in_no_export_is_refused_naming_key_and_source(self):
        repo = self.make()
        hmixml.TPL['S-Box'] = ET.fromstring(
            '<Hmi.Screen.Rectangle ID="0" CompositionName="ScreenItems"><AttributeList><BackColor>200, 200, 200'
            '</BackColor><Height>1</Height><Left>0</Left><ObjectName>rectNowhere</ObjectName><Top>0</Top>'
            '<Width>1</Width></AttributeList></Hmi.Screen.Rectangle>')
        hmixml.begin(repo.path)
        hmixml.add('screen', hmixml.screen_doc('9101 - Alias', 9101, [self.alias_box('rectA')]))
        with self.assertRaises(hmixml.GenerationRefused) as cm:
            hmixml.finish()
        unknown = [f for f in cm.exception.findings if f.rule == 'links.unknown']
        self.assertEqual(['rectA'], [f.object for f in unknown])
        self.assertIn("'S-Box'", unknown[0].message)
        self.assertIn("'rectNowhere'", unknown[0].message)

    def test_a_name_no_file_can_hold_gets_the_file_the_bridge_would_write(self):
        repo = self.make()
        hmixml.begin(repo.path)
        rel = hmixml.add('screen', hmixml.screen_doc('Ns:Staging', 9101, [panel('rectA')]))
        self.assertEqual('hmi/generated/screens/Ns_Staging.xml', rel)

    def test_two_names_on_one_file_are_refused(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.add('screen', hmixml.screen_doc('Ns:Staging', 9101, [panel('rectA')]))
        with self.assertRaises(ValueError):
            hmixml.add('screen', hmixml.screen_doc('Ns_Staging', 9102, [panel('rectB')]))

    def test_names_differing_only_in_case_are_refused(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.add('screen', hmixml.screen_doc('Abc', 9101, [panel('rectA')]))
        with self.assertRaises(ValueError):
            hmixml.add('screen', hmixml.screen_doc('ABC', 9102, [panel('rectB')]))

    def test_a_folder_gets_the_form_the_bridge_would_write(self):
        repo = self.make()
        hmixml.begin(repo.path)
        rel = hmixml.add('screen', hmixml.screen_doc('S1', 9101, [panel('rectA')]), folder='Ns:Folder/NUL/Sub.')
        self.assertEqual('hmi/generated/screens/Ns_Folder/NUL_/Sub_/S1.xml', rel)

    def test_a_folder_cannot_climb_out_of_the_generated_folder(self):
        repo = self.make()
        hmixml.begin(repo.path)
        rel = hmixml.add('screen', hmixml.screen_doc('S1', 9101, [panel('rectA')]), folder='../..')
        self.assertEqual('hmi/generated/screens/_/_/S1.xml', rel)

    def test_planned_json_holds_only_the_items_of_the_latest_run(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.plan('textlist', 'tlOld', 'gone next run')
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')]))
        hmixml.finish()
        hmixml.begin(repo.path)
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')]))
        hmixml.finish()
        self.assertEqual([], read_json(repo, 'hmi/generated/planned.json'))

    def test_run_with_a_validator_error_is_refused_and_writes_nothing(self):
        repo = self.make()
        hmixml.begin(repo.path)
        hmixml.plan('textlist', 'tlKept', 'from the good run')
        good = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')]))
        hmixml.finish()
        good_full = os.path.join(repo.path, *good.split('/'))
        with open(good_full, 'rb') as f:
            before = f.read()
        planned_before = read_json(repo, 'hmi/generated/planned.json')
        times_before = read_json(repo, 'hmi/generated/generated.json')

        invented = ET.fromstring('<Hmi.Screen.Invented ID="0" CompositionName="ScreenItems"><AttributeList>'
                                 '<ObjectName>oops</ObjectName></AttributeList></Hmi.Screen.Invented>')
        hmixml.begin(repo.path)
        hmixml.plan('textlist', 'tlNew', 'must not appear')
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA'), invented]))
        new = hmixml.add('screen', hmixml.screen_doc('9102 - Other', 9102, [panel('rectB')]), folder='New')
        with self.assertRaises(hmixml.GenerationRefused) as cm:
            hmixml.finish()

        self.assertIn(('error', 'oops', 'vocabulary.element-type'),
                      [(f.severity, f.object, f.rule) for f in cm.exception.findings])
        with open(good_full, 'rb') as f:
            self.assertEqual(before, f.read())
        self.assertFalse(os.path.exists(os.path.join(repo.path, *new.split('/'))))
        self.assertFalse(os.path.exists(os.path.join(repo.path, 'hmi', 'generated', 'screens', 'New')))
        self.assertEqual(planned_before, read_json(repo, 'hmi/generated/planned.json'))
        self.assertEqual(times_before, read_json(repo, 'hmi/generated/generated.json'))

    def test_run_is_validated_before_anything_is_written(self):
        # The validator runs on the run's documents before they are written; a refused run never
        # puts a file into the repo, not even while it is being validated.
        repo = self.make()
        invented = ET.fromstring('<Hmi.Screen.Invented ID="0" CompositionName="ScreenItems"><AttributeList>'
                                 '<ObjectName>oops</ObjectName></AttributeList></Hmi.Screen.Invented>')
        hmixml.begin(repo.path)
        hmixml.plan('textlist', 'tlNew', 'must not appear')
        bad = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA'), invented]))
        run_files = [bad, 'hmi/generated/planned.json', 'hmi/generated/generated.json']
        on_disk_while_validating = []
        original = hmipreview.validate

        def spy(*args, **kw):
            on_disk_while_validating.extend(
                rel for rel in run_files if os.path.exists(os.path.join(repo.path, *rel.split('/'))))
            return original(*args, **kw)

        with mock.patch.object(hmipreview, 'validate', spy):
            with self.assertRaises(hmixml.GenerationRefused) as cm:
                hmixml.finish()
        self.assertIn(('oops', 'vocabulary.element-type'), [(f.object, f.rule) for f in cm.exception.findings])
        self.assertEqual([], on_disk_while_validating)
        self.assertFalse(os.path.exists(os.path.join(repo.path, 'hmi', 'generated')))

    def test_validator_takes_documents_from_an_overlay(self):
        repo = self.make()
        rel = 'hmi/generated/screens/Overlay.xml'
        hmixml.begin(repo.path)                        # a screen takes its size from a run
        text = hmixml.ET.tostring(hmixml.screen_doc('Overlay', 9101, [ET.fromstring(
            '<Hmi.Screen.Invented ID="0" CompositionName="ScreenItems"><AttributeList><ObjectName>x</ObjectName>'
            '</AttributeList></Hmi.Screen.Invented>')]), encoding='utf-8')
        hmixml.finish()                                # the run adds nothing; the document stays in memory
        found = hmipreview.validate(repo.path, overlay={rel: text})
        self.assertIn((rel, 'x', 'vocabulary.element-type'), [(f.document, f.object, f.rule) for f in found])
        self.assertFalse(os.path.exists(os.path.join(repo.path, *rel.split('/'))))
        self.assertEqual([], [f for f in hmipreview.validate(repo.path) if f.document == rel])

    def test_screens_and_templates_take_the_device_resolution_popups_their_own(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0//Portrait')
        hmixml.begin(repo.path)

        def size(doc, tag):
            al = doc.find(tag + '/AttributeList')
            return int(al.findtext('Width')), int(al.findtext('Height'))

        self.assertEqual((800, 1280), size(hmixml.screen('S', 9101, []), 'Hmi.Screen.Screen'))
        self.assertEqual((800, 1280), size(hmixml.screen_doc('S', 9101, []), 'Hmi.Screen.Screen'))
        self.assertEqual((800, 1280), size(hmixml.screen_doc('T', None, [], is_template=True),
                                           'Hmi.Screen.ScreenTemplate'))
        self.assertEqual((400, 300), size(hmixml.screen_doc('P', None, [], popup=(400, 300)),
                                          'Hmi.Screen.ScreenPopup'))
        hmixml.finish()

    def test_unknown_device_refuses_to_start_a_run(self):
        repo = self.make('OrderNumber:6AV2 123-2GB03-0AX0/17.0.0.0')
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path)
        self.assertIn('6AV2 123-2GB03-0AX0', str(cm.exception))

    def test_nothing_is_written_outside_a_run(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0//Portrait')
        hmixml.begin(repo.path)                        # a refused run ends the run too
        hmixml.add('screen', hmixml.screen_doc('Bad', 9101, [ET.fromstring(
            '<Hmi.Screen.Invented ID="0"><AttributeList><ObjectName>x</ObjectName></AttributeList>'
            '</Hmi.Screen.Invented>')]))
        with self.assertRaises(hmixml.GenerationRefused):
            hmixml.finish()
        self.assertFalse(hasattr(hmixml, 'write'))     # the only way to the disk is finish()
        for call in (lambda: hmixml.add('screen', None), hmixml.finish):
            with self.assertRaises(RuntimeError):
                call()
        self.assertFalse(os.path.exists(os.path.join(repo.path, 'hmi', 'generated')))

    # Full exports only (2026-10-06): the generator copies every object, root and layer included, from an
    # exported one and adds no attribute value of its own beyond geometry, names, texts and links.
    def attrs(self, elem):
        return {a.tag: a.text or '' for a in elem.find('AttributeList')}

    def test_screen_root_and_layer_are_copied_from_the_reference_export(self):
        repo = self.make()
        hmixml.begin(repo.path)
        doc = hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')])
        root = doc.find('Hmi.Screen.Screen')
        self.assertEqual({'ActiveLayer': '0', 'BackColor': '255, 255, 255', 'GridColor': '0, 0, 0', 'Height': '800',
                          'Name': '9101 - Staging', 'Number': '9101', 'Visible': 'true', 'Width': '1280'},
                         self.attrs(root))
        self.assertEqual({'Index': '0', 'Name': '', 'VisibleES': 'true'},
                         self.attrs(root.find('ObjectList/Hmi.Screen.ScreenLayer')))
        hmixml.add('screen', doc)
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])

    def test_template_and_popup_roots_need_a_full_export_of_their_kind(self):
        repo = self.make()
        tpl = repo.export('template', 'Main template', document('template', 'Main template', []))
        hmixml.begin(repo.path)
        hmixml.add('template', hmixml.screen_doc('9 - Generated template', None, [], is_template=True))
        with self.assertRaises(hmixml.GenerationRefused) as cm:
            hmixml.finish()
        self.assertIn(('document.incomplete', 'Hmi.Screen.ScreenTemplate'),
                      [(f.rule, f.message.split(' on ')[1].split(';')[0]) for f in cm.exception.findings
                       if f.rule == 'document.incomplete'])
        hmixml.load_shapes(os.path.join(repo.path, *tpl.split('/')))
        hmixml.begin(repo.path)
        doc = hmixml.screen_doc('9 - Generated template', None, [], is_template=True)
        self.assertEqual('true', doc.findtext('Hmi.Screen.ScreenTemplate/AttributeList/SetTabOrderInFront'))
        hmixml.add('template', doc)
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])

    def test_an_alias_with_attributes_keeps_every_attribute_of_its_preset(self):
        repo = self.make()
        hmixml.load_templates(os.path.join(repo.path, 'hmi', 'screens', 'Reference.xml'),
                              aliases={'S-Note': ('S-Title', {'VerticalAlignment': 'Top'})})
        e = hmixml.template('S-Note')
        self.assertEqual('Top', e.findtext('AttributeList/VerticalAlignment'))
        self.assertEqual(set(self.attrs(hmixml.TPL['S-Title'])), set(self.attrs(e)))

    def test_group_and_graphic_view_are_copied_from_exported_ones(self):
        repo = self.make()
        hmixml.begin(repo.path)
        g = hmixml.group('grpNew', [panel('rectA'), panel('rectB', y=150)])
        self.assertEqual({'ObjectName': 'grpNew', 'TabIndex': '-1'}, self.attrs(g))
        pic = hmixml.graphic_view('picNew', 10, 300, 128, 128, 'Logo')
        ref = self.attrs(next(e for e in hmixml.troot.iter('Hmi.Screen.GraphicView')))
        self.assertEqual(dict(ref, ObjectName='picNew', Left='10', Top='300', Width='128', Height='128'),
                         self.attrs(pic))
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [g, pic]))
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])

    def test_a_type_no_export_holds_is_copied_from_the_catalogue_fixture(self):
        # The reference export has no gauge or slider; the catalogue's fixture has.
        repo = self.make()
        hmixml.begin(repo.path)
        gauge = hmixml.shape_item('Hmi.Screen.Gauge', 'gaugeNew', 400, 100, 200, 200)
        attrs = self.attrs(gauge)
        self.assertEqual(('gaugeNew', '400', '100', '200', '200'),
                         tuple(attrs[k] for k in ('ObjectName', 'Left', 'Top', 'Width', 'Height')))
        self.assertIn('AngleMax', attrs)
        fonts = gauge.findall('ObjectList/Hmi.Globalization.MultiLingualFont')
        self.assertTrue(fonts)
        self.assertEqual([['en-US', 'es-ES']] * len(fonts),
                         [[i.findtext('AttributeList/Culture') for i in f.find('ObjectList')] for f in fonts])
        slider = hmixml.blank('Hmi.Screen.Slider', 'ScreenItems')
        for k, v in (('ObjectName', 'sliderNew'), ('Left', 700), ('Top', 100), ('Width', 60), ('Height', 300)):
            hmixml.setattr_(slider, k, v)
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [gauge, slider]))
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])

    def test_screen_size_comes_only_from_the_declared_panel(self):
        repo = FixtureRepo(type_identifier=None)       # no HMI device known: the declared panel alone decides
        self.addCleanup(repo.cleanup)
        reference_export(repo)
        repo.panel('TP700 Comfort', 800, 480)
        for build in (lambda: hmixml.screen('S', 9101, []), lambda: hmixml.screen_doc('S', 9101, []),
                      lambda: hmixml.screen_doc('T', None, [], is_template=True)):
            with self.assertRaises(RuntimeError):      # no run, no panel: no size to take
                build()
        hmixml.begin(repo.path)
        al = hmixml.screen_doc('S', 9101, []).find('Hmi.Screen.Screen/AttributeList')
        self.assertEqual(('800', '480'), (al.findtext('Width'), al.findtext('Height')))
        hmixml.finish()


if __name__ == '__main__':
    unittest.main()
