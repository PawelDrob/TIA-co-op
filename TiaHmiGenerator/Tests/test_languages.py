"""The languages of a generated document come from the project (its exports), else from the reference export: a
project with other languages than the catalogue's fixture or any earlier project loses none of them."""
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

import hmipreview
import hmixml
from Tests.fixture import TP1200, FixtureRepo, document, item

THREE = ['de-DE', 'fr-FR', 'it-IT']


def ml_text(comp, text, cultures=THREE):
    items = ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                    '<Text><body><p>%s %s</p></body></Text></AttributeList></MultilingualTextItem>' % (c, text, c)
                    for c in cultures)
    return '<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>' % (
        comp, items)


def ml_font(cultures=THREE):
    items = ''.join('<Hmi.Globalization.FontItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                    '<FontFamily>Tahoma</FontFamily><FontSize>13</FontSize><FontStyle>Regular</FontStyle>'
                    '</AttributeList></Hmi.Globalization.FontItem>' % c for c in cultures)
    return ('<Hmi.Globalization.MultiLingualFont ID="0" CompositionName="Font"><ObjectList>%s</ObjectList>'
            '</Hmi.Globalization.MultiLingualFont>' % items)


def reference(cultures=THREE, name='Reference'):
    """A full export with the text field preset S-Title, every text and font in cultures."""
    title = item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
                 children='<ObjectList>%s%s</ObjectList>' % (ml_font(cultures), ml_text('Text', 'Title', cultures)))
    return document('screen', name, [title], Number=1, BackColor='255, 255, 255')


def cultures_of(comp):
    """The cultures of a multilingual composition, in document order."""
    return [i.findtext('AttributeList/Culture') for i in comp.find('ObjectList')]


def texts_of(comp):
    """{culture: words} of a MultilingualText."""
    return {i.findtext('AttributeList/Culture'): ''.join(i.find('AttributeList/Text').itertext())
            for i in comp.find('ObjectList')}


def tag_table(cultures=THREE):
    """An export of a tag table with a commented tag: the kind of export the preview's model does not read."""
    return ('<?xml version="1.0" encoding="utf-8"?><Document><Engineering version="V20" /><Hmi.Tag.TagTable ID="0">'
            '<AttributeList><Name>Plant</Name></AttributeList><ObjectList><Hmi.Tag.Tag ID="1" CompositionName="Tags">'
            '<AttributeList><Name>zzT1</Name></AttributeList><ObjectList>%s</ObjectList></Hmi.Tag.Tag></ObjectList>'
            '</Hmi.Tag.TagTable></Document>' % ml_text('Comment', 'Motor', cultures))


def make_repo(test):
    repo = FixtureRepo(type_identifier=TP1200)
    test.addCleanup(repo.cleanup)
    hardware = hmipreview.resolution.resolve(TP1200)
    repo.panel(hardware.panel, hardware.width, hardware.height, hardware.portrait)
    return repo


class LanguagesTest(unittest.TestCase):
    def repo(self):
        return make_repo(self)

    def load(self, repo, text=None, name='Reference'):
        rel = repo.export('screen', name, text or reference(name=name))
        hmixml.set_colours({'screen': (255, 255, 255)})
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')))
        return rel

    def forget_loaded(self):
        """Nothing loaded by an earlier test: only the repo can say a language."""
        hmixml.TPL.clear()
        hmixml.SHAPES.clear()
        hmixml.LOADED_CULTURES.clear()

    def load_other_project(self, repo, text):
        """A reference export of another project (hmi/references): it does not say what the project's languages are."""
        rel = repo.write('hmi/references/sister/screens/Old.xml', text)
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')))

    def test_a_whole_object_copied_from_the_reference_export_keeps_every_language(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        e = hmixml.shape_item('Hmi.Screen.TextField', 'txtNew', 10, 10, 100, 30)
        self.assertEqual(THREE, cultures_of(e.find('ObjectList/MultilingualText')))
        self.assertEqual(THREE, cultures_of(e.find('ObjectList/Hmi.Globalization.MultiLingualFont')))

    def test_a_generated_text_stands_in_every_language_with_the_same_words(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        title = hmixml.item({'name': 'txtNew', 'type': 'Text field', 'style': 'S-Title', 'x': 10, 'y': 90, 'w': 100,
                             'h': 30, 'group': None, 'm': {'text': ['Hello']}})
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [title]))
        tl = hmixml.add('textlist', hmixml.textlist('tlNew', [(0, 'Off')]))
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])

        root = ET.parse(os.path.join(repo.path, *rel.split('/'))).getroot()
        texts = {m.get('CompositionName'): m for m in root.iter('MultilingualText')}
        self.assertEqual(THREE, cultures_of(texts['HelpText']))
        self.assertEqual({'de-DE': 'Hello', 'fr-FR': 'Hello', 'it-IT': 'Hello'}, texts_of(texts['Text']))
        lists = ET.parse(os.path.join(repo.path, *tl.split('/'))).getroot()
        self.assertEqual([THREE, THREE], [cultures_of(m) for m in lists.iter('MultilingualText')])

    def test_a_preset_with_fewer_languages_gets_the_others_from_its_first_text(self):
        repo = self.repo()
        repo.export('screen', 'Other', reference())
        title = item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
                     children='<ObjectList>%s%s</ObjectList>' % (
                         ml_font(['fr-FR']), ml_text('Text', 'Title', ['fr-FR'])))
        self.load_other_project(repo, document('screen', 'Old', [title], Number=2, BackColor='255, 255, 255'))
        hmixml.begin(repo.path)
        e = hmixml.template('S-Title')
        self.assertEqual({'de-DE': 'Title fr-FR', 'fr-FR': 'Title fr-FR', 'it-IT': 'Title fr-FR'},
                         texts_of(e.find('ObjectList/MultilingualText')))
        self.assertEqual(THREE, cultures_of(e.find('ObjectList/Hmi.Globalization.MultiLingualFont')))

    def test_an_empty_first_item_is_not_what_a_missing_language_copies(self):
        repo = self.repo()
        repo.export('screen', 'Other', reference())
        text = ('<MultilingualText ID="0" CompositionName="Text"><ObjectList>'
                '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>de-DE</Culture><Text />'
                '</AttributeList></MultilingualTextItem>'
                '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>fr-FR</Culture>'
                '<Text><body><p>Titre</p></body></Text></AttributeList></MultilingualTextItem>'
                '</ObjectList></MultilingualText>')
        title = item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
                     children='<ObjectList>%s%s</ObjectList>' % (ml_font(), text))
        self.load_other_project(repo, document('screen', 'Old', [title], Number=2, BackColor='255, 255, 255'))
        hmixml.begin(repo.path)
        self.assertEqual({'de-DE': '', 'fr-FR': 'Titre', 'it-IT': 'Titre'},
                         texts_of(hmixml.template('S-Title').find('ObjectList/MultilingualText')))

    def test_a_text_inside_a_copied_object_gets_the_languages_too(self):
        repo = self.repo()
        inner = item('Hmi.Screen.TextField', 'txtInner', Left=10, Top=150, Width=200, Height=30,
                     children='<ObjectList>%s</ObjectList>' % ml_text('Text', 'Inner', ['en-US']))
        grp = ('<Hmi.Screen.Group ID="0" CompositionName="ScreenItems"><AttributeList><ObjectName>grpRef</ObjectName>'
               '<TabIndex>-1</TabIndex></AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.Group>' % inner)
        repo.export('screen', 'Other', reference())
        self.load_other_project(repo, document('screen', 'Old', [grp], Number=2, BackColor='255, 255, 255'))
        hmixml.begin(repo.path)
        e = hmixml.shape_item('Hmi.Screen.Group', 'grpNew', 10, 10, 100, 30)
        self.assertEqual([THREE], [cultures_of(m) for m in e.iter('MultilingualText')])

    def test_a_type_from_the_catalogue_fixture_takes_the_projects_languages(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        gauge = hmixml.shape_item('Hmi.Screen.Gauge', 'gaugeNew', 400, 100, 200, 200)
        fonts = gauge.findall('ObjectList/Hmi.Globalization.MultiLingualFont')
        self.assertTrue(fonts)
        self.assertEqual([THREE] * len(fonts), [cultures_of(f) for f in fonts])

    def test_the_project_decides_over_an_export_of_another_project(self):
        repo = self.repo()
        self.load(repo)
        foreign = repo.write('hmi/references/sister/screens/Sister.xml', reference(['es-ES', 'pt-PT'], 'Sister'))
        hmixml.load_shapes(os.path.join(repo.path, *foreign.split('/')))
        repo.generated('screen', 'Old', reference(['es-ES'], 'Old'))  # neither does an earlier run's document count
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())

    def test_the_exports_of_another_hmi_device_count(self):
        repo = self.repo()
        repo.export('screen', 'Other', reference(), device='HMI_2')
        repo.write('hmi/HMI_1/panel.json', '{"panel": "1280x800", "width": 1280, "height": 800, "portrait": false}')
        repo.write('hmi/HMI_1/.keep', '')
        hmixml.begin(repo.path, device='HMI_1')
        self.assertEqual(THREE, hmixml.generated_cultures())

    def test_without_a_language_in_the_project_the_reference_export_decides(self):
        repo = self.repo()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'Reference.xml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(reference())
            hmixml.load_templates(path)
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())
        self.assertEqual(THREE, cultures_of(hmixml.ml_text('HelpText', None)))

    def test_languages_from_a_loaded_export_alone_are_a_warning(self):
        repo = self.repo()
        self.load_other_project(repo, reference(name='Old'))
        hmixml.begin(repo.path)
        hmixml.add('textlist', hmixml.textlist('tlNew', [(0, 'Off')]))
        found = [f for f in hmixml.finish() if f.rule == 'languages.no-export']
        self.assertEqual(['warning'], [f.severity for f in found])
        self.assertIn('de-DE, fr-FR, it-IT', found[0].message)

    def test_a_change_in_the_third_language_stands_in_the_preview_diff(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        e = hmixml.template('S-Title')
        for i in e.find('ObjectList/MultilingualText/ObjectList'):
            if i.findtext('AttributeList/Culture') == 'it-IT':
                al = i.find('AttributeList')
                al.remove(al.find('Text'))
                al.append(hmixml.body(['Titolo nuovo']))
        hmixml.add('screen', hmixml.screen_doc('Reference', 1, [e]))
        hmixml.finish()
        result = hmipreview.diff.compare(hmipreview.model.load(repo.path), 'screen', 'Reference', 'export')
        title = next(c for c in result['changes'] if c['object'] == 'S-Title')
        self.assertEqual([{'part': 'Text', 'culture': 'it-IT', 'old': 'Title it-IT', 'new': 'Titolo nuovo'}],
                         title['texts'])

    def test_a_tag_table_export_says_the_languages(self):
        repo = self.repo()
        repo.write('hmi/tags/Plant.xml', tag_table())
        self.forget_loaded()
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())
        hmixml.add('textlist', hmixml.textlist('tlNew', [(0, 'Off')]))
        self.assertEqual([], [f for f in hmixml.finish() if f.rule.startswith('languages.')])

    def test_a_tag_table_of_another_hmi_device_says_the_languages(self):
        repo = self.repo()
        repo.write('hmi/HMI_2/tags/Plant.xml', tag_table())
        repo.write('hmi/HMI_1/panel.json', '{"panel": "1280x800", "width": 1280, "height": 800, "portrait": false}')
        self.forget_loaded()
        hmixml.begin(repo.path, device='HMI_1')
        self.assertEqual(THREE, hmixml.generated_cultures())

    def test_a_tag_table_of_another_project_or_an_earlier_run_does_not(self):
        repo = self.repo()
        repo.write('hmi/references/sister/tags/Plant.xml', tag_table(['es-ES']))
        repo.write('hmi/generated/tags/Plant.xml', tag_table(['pt-PT']))
        repo.write('hmi/tags/Plant.xml', tag_table())
        self.forget_loaded()
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())

    def test_a_tag_table_written_by_hand_does_not_add_a_language_to_the_exported_screens(self):
        repo = self.repo()
        self.load(repo)
        repo.write('hmi/tags/Hand.xml', tag_table(['en-US']))     # a generator writes tag tables into this folder
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())
        title = hmixml.shape_item('Hmi.Screen.TextField', 'txtNew', 10, 90, 100, 30)
        other = hmixml.shape_item('Hmi.Screen.TextField', 'txtOther', 10, 150, 100, 30, THREE + ['en-US'])
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [title, other]))
        with self.assertRaises(hmixml.GenerationRefused) as ctx:
            hmixml.finish()
        found = [f for f in ctx.exception.findings if f.rule.startswith('languages.')]
        self.assertEqual({('languages.unknown', 'txtOther')}, {(f.rule, f.object) for f in found})
        self.assertIn('en-US', found[0].message)

    def test_an_unreadable_file_beside_the_exports_says_nothing_and_breaks_nothing(self):
        repo = self.repo()
        repo.write('hmi/tags/Broken.xml', '<Document><not closed')
        repo.write('hmi/tags/Plant.xml', tag_table())
        self.forget_loaded()
        hmixml.begin(repo.path)
        self.assertEqual(THREE, hmixml.generated_cultures())

    def test_an_object_with_no_text_needs_no_language(self):
        repo = self.repo()
        self.forget_loaded()
        hmixml.begin(repo.path)
        e = hmixml.shape_item('Hmi.Screen.Rectangle', 'rectNew', 10, 10, 100, 30)
        self.assertEqual('rectNew', e.findtext('AttributeList/ObjectName'))

    def test_an_object_with_a_text_needs_a_language(self):
        repo = self.repo()
        self.forget_loaded()
        hmixml.begin(repo.path)
        with self.assertRaisesRegex(ValueError, 'No language known'):
            hmixml.shape_item('Hmi.Screen.Gauge', 'gaugeNew', 10, 10, 100, 100)

    def test_a_text_the_generator_sets_fills_an_item_the_export_left_empty(self):
        repo = self.repo()
        repo.export('screen', 'Other', reference())
        text = ('<MultilingualText ID="0" CompositionName="Text"><ObjectList>'
                '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>de-DE</Culture><Text />'
                '</AttributeList></MultilingualTextItem>'
                '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>fr-FR</Culture>'
                '<Text><body><p>Titre</p></body></Text></AttributeList></MultilingualTextItem>'
                '</ObjectList></MultilingualText>')
        title = item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
                     children='<ObjectList>%s%s</ObjectList>' % (ml_font(), text))
        self.load_other_project(repo, document('screen', 'Old', [title], Number=2, BackColor='255, 255, 255'))
        hmixml.begin(repo.path)
        e = hmixml.item({'name': 'txtNew', 'type': 'Text field', 'style': 'S-Title', 'x': 10, 'y': 90, 'w': 100,
                         'h': 30, 'group': None, 'm': {'text': ['Hello']}})
        self.assertEqual({'de-DE': 'Hello', 'fr-FR': 'Hello', 'it-IT': 'Hello'},
                         texts_of(e.find('ObjectList/MultilingualText')))

    def test_with_no_language_known_a_text_is_refused_not_guessed(self):
        repo = self.repo()
        self.forget_loaded()
        hmixml.begin(repo.path)
        with self.assertRaisesRegex(ValueError, 'No language known'):
            hmixml.textlist('tlNew', [(0, 'Off')])

    def test_a_run_that_leaves_out_a_language_of_the_project_is_refused(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        e = hmixml.shape_item('Hmi.Screen.TextField', 'txtNew', 10, 90, 100, 30, ['de-DE'])
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [e]))
        with self.assertRaises(hmixml.GenerationRefused) as ctx:
            hmixml.finish()
        self.assertFalse(os.path.exists(os.path.join(repo.path, *rel.split('/'))))
        hits = [f for f in ctx.exception.findings if f.rule == 'languages.missing']
        self.assertEqual({'txtNew'}, {f.object for f in hits})
        self.assertIn('fr-FR, it-IT', hits[0].message)

    def test_a_language_no_export_carries_is_refused_as_tia_refuses_it(self):
        repo = self.repo()
        self.load(repo)
        hmixml.begin(repo.path)
        e = hmixml.shape_item('Hmi.Screen.TextField', 'txtNew', 10, 90, 100, 30, THREE + ['pl-PL'])
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [e]))
        with self.assertRaises(hmixml.GenerationRefused) as ctx:
            hmixml.finish()
        self.assertFalse(os.path.exists(os.path.join(repo.path, *rel.split('/'))))
        found = [f for f in ctx.exception.findings if f.rule == 'languages.unknown']
        self.assertEqual({('txtNew', 'error')}, {(f.object, f.severity) for f in found})
        self.assertIn('pl-PL', found[0].message)
        self.assertIn('export a screen again', found[0].message)       # the way out when the language was only just added in TIA

    def test_exports_alone_give_no_language_finding(self):
        repo = self.repo()
        repo.export('screen', 'A', reference())
        repo.export('screen', 'B', reference(['de-DE'], 'B'))
        self.assertEqual([], [f for f in hmipreview.validate(repo.path) if f.rule.startswith('languages.')])


class AliasTest(unittest.TestCase):
    """What a project calls its presets is the project's: the generator knows no name of its own."""

    def load(self, aliases=None):
        repo = make_repo(self)
        rel = repo.export('screen', 'Reference', reference())
        hmixml.set_colours({'screen': (255, 255, 255)})
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')), aliases=aliases)
        return repo

    def test_a_preset_nobody_named_is_refused_and_names_the_way_out(self):
        self.load()
        with self.assertRaisesRegex(KeyError, 'S-Unnamed.*alias'):
            hmixml.template('S-Unnamed')

    def test_a_project_names_its_own_preset(self):
        self.load({'S-Second': 'S-Title'})
        self.assertEqual('S-Title', hmixml.template('S-Second').findtext('AttributeList/ObjectName'))

    def test_an_alias_with_attributes_changes_only_its_copy(self):
        self.load({'S-Note': ('S-Title', {'VerticalAlignment': 'Bottom'})})
        self.assertEqual('Bottom', hmixml.template('S-Note').findtext('AttributeList/VerticalAlignment'))
        self.assertEqual('Top', hmixml.template('S-Title').findtext('AttributeList/VerticalAlignment'))

    def test_an_aliased_preset_passes_the_link_rules(self):
        repo = self.load({'S-Note': ('S-Title', {'VerticalAlignment': 'Bottom'})})
        hmixml.begin(repo.path)
        e = hmixml.item({'name': 'txtNote', 'type': 'Text field', 'style': 'S-Note', 'x': 10, 'y': 90, 'w': 100, 'h': 30,
                         'group': None, 'm': {'text': ['Note']}})
        hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [e]))
        self.assertEqual([], [f for f in hmixml.finish() if f.severity == 'error'])
        self.assertEqual({'preset': 'S-Note', 'source': 'S-Title', 'document': 'hmi/screens/Reference.xml'},
                         repo_presets(repo)['txtNote'])

    def test_a_symbolic_field_keeps_the_mode_of_its_preset_unless_told(self):
        repo = FixtureRepo(type_identifier=TP1200)
        self.addCleanup(repo.cleanup)
        sym = item('Hmi.Screen.SymbolicIOField', 'S-Sym', Left=10, Top=150, Width=200, Height=30, Mode='Input')
        rel = repo.export('screen', 'Reference', document('screen', 'Reference', [sym], Number=1,
                                                          BackColor='255, 255, 255'))
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')))
        o = {'name': 'symNew', 'type': 'Symbolic I/O field', 'style': 'S-Sym', 'x': 1, 'y': 1, 'w': 9, 'h': 9,
             'group': None, 'm': {'tl': 'tlNew'}}
        self.assertEqual('Input', hmixml.item(o).findtext('AttributeList/Mode'))
        o['m'] = {'tl': 'tlNew', 'mode': 'Output'}
        self.assertEqual('Output', hmixml.item(o).findtext('AttributeList/Mode'))


def repo_presets(repo):
    with open(os.path.join(repo.path, 'hmi', 'generated', 'generated.json'), encoding='utf-8') as f:
        record = json.load(f)
    return next(iter(record.values()))['presets']
