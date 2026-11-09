"""Link states (exists / planned / unknown) per link kind, and open planned items."""
import json
import unittest

from hmipreview import link_states, model, validate
from Tests.fixture import FixtureRepo, document, item


def links_of(findings):
    return [(f.severity, f.rule, f.document, f.object) for f in findings if f.rule.startswith('links.')]


def link_list(kind, name):
    return '<LinkList><%s TargetID="@OpenLink"><Name>%s</Name></%s></LinkList>' % (kind, name, kind)


def sym_io(name, textlist):
    """Symbolic I/O field linking a text list (LinkList after the AttributeList, as exported)."""
    return ('<Hmi.Screen.SymbolicIOField ID="0" CompositionName="ScreenItems"><AttributeList><Height>20</Height>'
            '<Left>10</Left><ObjectName>%s</ObjectName><Top>90</Top><Width>50</Width></AttributeList>%s'
            '</Hmi.Screen.SymbolicIOField>' % (name, link_list('TextList', textlist)))


def textlist_doc(name):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>%s</Name></AttributeList>'
            '</Hmi.TextGraphicList.TextList></Document>\n' % name)


def graphic_view(name, picture):
    return item('Hmi.Screen.GraphicView', name, link_list('Picture', picture), Left=10, Top=90, Width=20, Height=20)


def button(name, links='', events=''):
    return item('Hmi.Screen.Button', name, links + ('<ObjectList>%s</ObjectList>' % events if events else ''),
                Left=10, Top=90, Width=80, Height=40)


def function(func, param, target_links):
    """Click event calling one system function with one parameter carrying target_links (a LinkList)."""
    return ('<Hmi.Event.Event ID="0" CompositionName="Events"><AttributeList><Name>Click</Name></AttributeList>'
            '<ObjectList><Hmi.Event.FunctionListEventHandler ID="0" CompositionName="EventHandler"><ObjectList>'
            '<Hmi.Event.FunctionListEntry ID="0" CompositionName="FunctionListEntries"><AttributeList>'
            '<Name>%s</Name><Type>SystemFunction</Type></AttributeList><ObjectList>'
            '<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList>'
            '<Name>%s</Name></AttributeList>%s</Hmi.Event.FunctionListEntryParameter></ObjectList>'
            '</Hmi.Event.FunctionListEntry></ObjectList></Hmi.Event.FunctionListEventHandler></ObjectList>'
            '</Hmi.Event.Event>' % (func, param, target_links))


def faceplate(name, type_name, authorization=None):
    iface = ''
    if authorization:
        iface = ('<ObjectList><Hmi.Screen.InterfacePropertySimple ID="0" CompositionName="Interface"><AttributeList>'
                 '<Name>Authorization</Name></AttributeList>%s</Hmi.Screen.InterfacePropertySimple></ObjectList>'
                 % link_list('Value', authorization))
    return item('Hmi.Screen.FaceplateInstance', name, iface, FaceplateTypeName=type_name, Left=10, Top=90,
                Width=100, Height=100)


def rectangle(name, top=90):
    return item('Hmi.Screen.Rectangle', name, Left=0, Top=top, Width=1, Height=1)


FP = '_Library@$@Redesign@$@Faceplate@$@faceplateDrive V 0.0.3'


def _export_screen(repo, items):
    repo.export('screen', 'Ref', document('screen', 'Ref', items, Number=1))


# kind -> (target name, make it exist in the exports, (screen items, screen kwargs) using it, object holding the link)
KIND_CASES = {
    'template': ('tplNew', lambda r, n: r.export('template', n, document('template', n)),
                 lambda n: ([], {'template': n}), None),
    'picture': ('logoNew', lambda r, n: _export_screen(r, [graphic_view('logo', n)]),
                lambda n: ([graphic_view('pic', n)], {}), 'pic'),
    'authorization': ('Service', lambda r, n: _export_screen(r, [button('b', link_list('Authorization', n))]),
                      lambda n: ([button('btn', link_list('Authorization', n))], {}), 'btn'),
    'screen': ('0100 Overview', lambda r, n: r.export('screen', n, document('screen', n, Number=7)),
               lambda n: ([button('btn', events=function('ActivateScreen', 'Screen name', link_list('Value', n)))],
                          {}), 'btn'),
    'popup': ('puUser', lambda r, n: r.export('popup', n, document('popup', n)),
              lambda n: ([button('btn', events=function('ShowPopupScreen', 'Name of the screen',
                                                         link_list('Value', n)))], {}), 'btn'),
    'faceplate': (FP, lambda r, n: r.faceplate_type('faceplateDrive', ['0.0.3'], 'Redesign/Faceplate'),
                  lambda n: ([faceplate('fp', n)], {}), 'fp'),
    'style': ('S-NewPanel', lambda r, n: _export_screen(r, [rectangle(n, top=0)]),
              lambda n: ([rectangle(n)], {}), 'S-NewPanel'),
}


class LinkTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def screen(self, items, **kw):
        return self.repo.generated('screen', 'New', document('screen', 'New', items, Number=2, **kw))

    def check(self, for_import=False):
        return links_of(validate(self.repo.path, for_import=for_import))


class TextListLinkTest(LinkTest):
    def test_text_list_in_the_exports_exists(self):
        self.repo.export('textlist', 'tlMode', textlist_doc('tlMode'))
        self.screen([sym_io('mode', 'tlMode')])
        self.assertEqual([], self.check())

    def test_text_list_neither_exported_nor_planned_is_an_unknown_link(self):
        path = self.screen([sym_io('mode', 'tlTypo')])
        self.assertEqual([('error', 'links.unknown', path, 'mode')], self.check())

    def test_open_planned_text_list_is_a_warning_in_the_preview(self):
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': 'made by hand in TIA'}])
        path = self.screen([sym_io('mode', 'tlNew')])
        self.assertEqual([('warning', 'links.planned', path, 'mode')], self.check())

    def test_open_planned_text_list_is_an_error_for_import(self):
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': ''}])
        path = self.screen([sym_io('mode', 'tlNew')])
        self.assertEqual([('error', 'links.planned', path, 'mode')], self.check(for_import=True))

    def test_planned_text_list_that_now_exists_is_closed(self):
        self.repo.export('textlist', 'tlNew', textlist_doc('tlNew'))
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': ''}])
        self.screen([sym_io('mode', 'tlNew')])
        self.assertEqual([], self.check(for_import=True))

    def test_generated_text_list_needs_no_planned_item(self):
        self.repo.generated('textlist', 'tlGen', textlist_doc('tlGen'))
        self.screen([sym_io('mode', 'tlGen')])
        self.assertEqual([], self.check(for_import=True))


class EveryLinkKindTest(unittest.TestCase):
    """Each link kind in its three states, one fixture repo per kind and state."""

    def run_case(self, kind, exists=False, planned=False, for_import=False, planned_name=None):
        """(severity, rule, object) of the links findings, and the object expected to hold the link."""
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        name, make, use, obj = KIND_CASES[kind]
        if exists:
            make(repo, name)
        if planned:
            repo.planned([{'kind': kind, 'name': planned_name or name, 'note': 'new'}])
        items, kw = use(name)
        repo.generated('screen', 'New', document('screen', 'New', items, Number=2, **kw))
        found = [(s, r, o) for s, r, _d, o in links_of(validate(repo.path, for_import=for_import))]
        return found, obj

    def test_exists_is_silent(self):
        for kind in KIND_CASES:
            with self.subTest(kind=kind):
                self.assertEqual([], self.run_case(kind, exists=True)[0])

    def test_unknown_is_an_error(self):
        for kind in KIND_CASES:
            with self.subTest(kind=kind):
                found, obj = self.run_case(kind)
                self.assertEqual([('error', 'links.unknown', obj)], found)

    def test_open_planned_is_a_warning_in_the_preview(self):
        for kind in KIND_CASES:
            with self.subTest(kind=kind):
                found, obj = self.run_case(kind, planned=True)
                self.assertEqual([('warning', 'links.planned', obj)], found)

    def test_open_planned_is_an_error_for_import(self):
        for kind in KIND_CASES:
            with self.subTest(kind=kind):
                found, obj = self.run_case(kind, planned=True, for_import=True)
                self.assertEqual([('error', 'links.planned', obj)], found)

    def test_planned_that_now_exists_is_closed(self):
        for kind in KIND_CASES:
            with self.subTest(kind=kind):
                self.assertEqual([], self.run_case(kind, exists=True, planned=True, for_import=True)[0])


class FaceplateLinkTest(LinkTest):
    def test_planned_by_type_and_version_without_the_library_path(self):
        self.repo.planned([{'kind': 'faceplate', 'name': 'faceplateDrive V 0.0.3', 'note': ''}])
        path = self.screen([faceplate('fp', FP)])
        self.assertEqual([('warning', 'links.planned', path, 'fp')], self.check())

    def test_planned_works_without_the_exported_library(self):
        self.repo.planned([{'kind': 'faceplate', 'name': FP, 'note': ''}])
        path = self.screen([faceplate('fp', FP)])
        self.assertEqual([('error', 'links.planned', path, 'fp')], self.check(for_import=True))

    def test_version_in_the_exported_library_exists(self):
        self.repo.faceplate_type('faceplateDrive', ['0.0.2', '0.0.3'], 'Redesign/Faceplate')
        self.screen([faceplate('fp', FP)])
        self.assertEqual([], self.check(for_import=True))
        doc = model.load(self.repo.path).find('screen', 'New')
        self.assertEqual(['exists'], [l.state for l in link_states(model.load(self.repo.path), doc)])

    def test_library_folder_as_the_bridge_exports_it_matches_the_link(self):
        # Shapes from project B (2026-10-06): the bridge index carries the '_Library' root, the link names it as its
        # first segment.
        self.repo.faceplate_type('faceplateStation20Operate', ['0.0.3'], '_Library/_Customer/Faceplate/Operate')
        name = '_Library@$@_Customer@$@Faceplate@$@Operate@$@faceplateStation20Operate V 0.0.3'
        self.screen([faceplate('fp', name)])
        self.assertEqual([], self.check(for_import=True))
        doc = model.load(self.repo.path).find('screen', 'New')
        self.assertEqual(['exists'], [l.state for l in link_states(model.load(self.repo.path), doc)])

    def test_version_only_on_an_exported_screen_is_unknown(self):
        self.repo.faceplate_type('faceplateDrive', ['0.0.3'], 'Redesign/Faceplate')
        old = FP.replace('0.0.3', '0.0.2')
        _export_screen(self.repo, [faceplate('fp0', old)])
        path = self.screen([faceplate('fp', old)])
        found = [f for f in validate(self.repo.path) if f.rule.startswith('links.')]
        self.assertEqual([('error', 'links.unknown', path, 'fp')], links_of(found))
        self.assertIn('0.0.3', found[0].message)

    def test_type_in_another_library_folder_is_unknown(self):
        self.repo.faceplate_type('faceplateDrive', ['0.0.3'], 'Old/Faceplate')
        path = self.screen([faceplate('fp', FP)])
        found = [f for f in validate(self.repo.path) if f.rule.startswith('links.')]
        self.assertEqual([('error', 'links.unknown', path, 'fp')], links_of(found))
        self.assertIn('Old/Faceplate', found[0].message)

    def test_without_the_exported_library_every_faceplate_is_unknown_with_a_hint(self):
        _export_screen(self.repo, [faceplate('fp0', FP)])
        path = self.screen([faceplate('fp', FP)])
        found = [f for f in validate(self.repo.path) if f.rule.startswith('links.')]
        self.assertEqual([('error', 'links.unknown', path, 'fp')], links_of(found))
        self.assertIn('library/faceplates', found[0].message)
        self.assertIn('faceplate_type', found[0].message)
        doc = model.load(self.repo.path).find('screen', 'New')
        link = link_states(model.load(self.repo.path), doc)[0]
        self.assertEqual(('unknown', True), (link.state, 'faceplate_type' in link.note))

    def test_authorization_on_the_faceplate_interface_is_resolved(self):
        self.repo.faceplate_type('faceplateDrive', ['0.0.3'], 'Redesign/Faceplate')
        self.screen([faceplate('fp', FP, authorization='Nobody')])
        found = [f for f in validate(self.repo.path) if f.rule.startswith('links.')]
        self.assertEqual([('error', 'links.unknown', 'fp')], [(f.severity, f.rule, f.object) for f in found])
        self.assertIn("authorization 'Nobody'", found[0].message)


class UnresolvedLinkTest(LinkTest):
    def test_tags_and_links_to_the_own_document_are_not_resolved(self):
        own = '<LinkList><Value TargetID="#0" /></LinkList>'
        self.screen([button('btn', link_list('Tag', 'noSuchTag'),
                            function('ShowPopupScreen', 'Name of the screen', own))])
        self.assertEqual([], self.check())

    def test_generated_screen_target_needs_no_planned_item(self):
        self.repo.generated('screen', 'Other', document('screen', 'Other', Number=3))
        self.screen([button('btn', events=function('ActivateScreen', 'Screen name', link_list('Value', 'Other')))])
        self.assertEqual([], self.check(for_import=True))


class PlannedEntryTest(LinkTest):
    def test_entry_without_a_known_kind_is_an_error(self):
        self.repo.planned([{'kind': 'colour', 'name': 'red', 'note': ''}])
        self.assertEqual([('error', 'links.planned-entry', 'hmi/generated/planned.json', None)], self.check())

    def test_valid_entries_are_silent(self):
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': ''}])
        self.assertEqual([], self.check())


class LinkStatesTest(LinkTest):
    """link_states(repo, doc): the links of one document with their states, for the inspect panel."""

    def test_lists_every_link_of_a_document_with_its_state(self):
        self.repo.export('template', 'tplMain', document('template', 'tplMain'))
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': 'by hand'}])
        self.screen([sym_io('mode', 'tlNew'), graphic_view('pic', 'logoTypo')], template='tplMain')
        repo = model.load(self.repo.path)
        doc = repo.find('screen', 'New')
        self.assertEqual([
            {'object': None, 'kind': 'template', 'name': 'tplMain', 'state': 'exists', 'note': ''},
            {'object': 'mode', 'kind': 'textlist', 'name': 'tlNew', 'state': 'planned', 'note': 'by hand'},
            {'object': 'pic', 'kind': 'picture', 'name': 'logoTypo', 'state': 'unknown', 'note': ''},
        ], [l.to_dict() for l in link_states(repo, doc)])

    def test_works_on_exported_documents_too(self):
        self.repo.export('screen', 'Old', document('screen', 'Old', [graphic_view('pic', 'logo')], Number=1))
        repo = model.load(self.repo.path)
        self.assertEqual([('pic', 'picture', 'logo', 'exists')],
                         [(l.object, l.kind, l.name, l.state) for l in link_states(repo, repo.find('screen', 'Old'))])


if __name__ == '__main__':
    unittest.main()


class RecordedPresetTest(LinkTest):
    """Ordinary objects do not carry their style preset; the generator records it in hmi/generated/generated.json."""

    def screen_with_preset(self, preset):
        path = self.screen([rectangle('rectA')])
        self.repo.write('hmi/generated/generated.json', json.dumps(
            {path: {'generated': '2026-10-06T13:00:00+00:00', 'presets': {'rectA': preset}}}))
        return path

    def test_recorded_preset_in_the_exports_exists(self):
        _export_screen(self.repo, [rectangle('S-Panel', top=0)])
        self.screen_with_preset('S-Panel')
        self.assertEqual([], self.check())
        repo = model.load(self.repo.path)
        doc = repo.find('screen', 'New', origin='generated')
        # an old record is the key only
        self.assertEqual({'rectA': {'preset': 'S-Panel', 'source': None, 'document': None}}, repo.presets(doc))
        self.assertIn(('rectA', 'style', 'S-Panel', 'exists'),
                      [(l.object, l.kind, l.name, l.state) for l in link_states(repo, doc)])

    def test_recorded_preset_neither_exported_nor_planned_is_an_unknown_link(self):
        path = self.screen_with_preset('S-Typo')
        self.assertEqual([('error', 'links.unknown', path, 'rectA')], self.check())

    def test_recorded_preset_planned_is_an_open_planned_link(self):
        self.repo.planned([{'kind': 'style', 'name': 'S-NewPanel', 'note': 'built from the style test screen'}])
        path = self.screen_with_preset('S-NewPanel')
        self.assertEqual([('warning', 'links.planned', path, 'rectA')], self.check())

    # project B gen_station 2026-10-06: the generator filled hmixml.TPL with alias keys ('S-Title') for exported objects
    # that are not named S-... (txtTitleLarge on the staging screen). The record names the key and the source.
    def test_preset_whose_source_object_is_exported_exists(self):
        _export_screen(self.repo, [rectangle('txtTitleLarge', top=0)])
        self.screen_with_preset({'preset': 'S-Title', 'source': 'txtTitleLarge', 'document': 'hmi/screens/Ref.xml'})
        self.assertEqual([], self.check())
        repo = model.load(self.repo.path)
        doc = repo.find('screen', 'New', origin='generated')
        self.assertEqual({'rectA': {'preset': 'S-Title', 'source': 'txtTitleLarge', 'document': 'hmi/screens/Ref.xml'}},
                         repo.presets(doc))
        style = [l for l in link_states(repo, doc) if l.kind == 'style']
        self.assertEqual([('rectA', 'S-Title', 'exists')], [(l.object, l.name, l.state) for l in style])
        self.assertIn('txtTitleLarge', style[0].note)
        self.assertIn('hmi/screens/Ref.xml', style[0].note)

    def test_preset_source_without_a_document_is_found_in_any_export(self):
        _export_screen(self.repo, [rectangle('txtTitleLarge', top=0)])
        self.screen_with_preset({'preset': 'S-Title', 'source': 'txtTitleLarge'})
        self.assertEqual([], self.check())

    def test_preset_source_is_looked_up_only_in_its_recorded_document(self):
        _export_screen(self.repo, [rectangle('txtTitleLarge', top=0)])
        path = self.screen_with_preset({'preset': 'S-Title', 'source': 'txtTitleLarge',
                                        'document': 'hmi/screens/Other.xml'})
        self.assertEqual([('error', 'links.unknown', path, 'rectA')], self.check())

    def test_unknown_preset_message_names_key_and_source(self):
        path = self.screen_with_preset({'preset': 'S-Title', 'source': 'txtGone', 'document': 'hmi/screens/Ref.xml'})
        found = [f for f in validate(self.repo.path) if f.rule == 'links.unknown']
        self.assertEqual([path], [f.document for f in found])
        self.assertIn("'S-Title'", found[0].message)
        self.assertIn("'txtGone'", found[0].message)
        self.assertIn('hmi/screens/Ref.xml', found[0].message)

    def test_preset_key_that_is_an_exported_s_object_exists_whatever_the_source(self):
        _export_screen(self.repo, [rectangle('S-Panel', top=0)])
        self.screen_with_preset({'preset': 'S-Panel', 'source': 'renamedSince'})
        self.assertEqual([], self.check())

    def test_planned_preset_key_with_a_missing_source_is_planned(self):
        self.repo.planned([{'kind': 'style', 'name': 'S-NewPanel', 'note': 'from the style test screen'}])
        path = self.screen_with_preset({'preset': 'S-NewPanel', 'source': 'S-NewPanel'})
        self.assertEqual([('warning', 'links.planned', path, 'rectA')], self.check())

    def test_no_record_no_preset_link(self):
        self.screen([rectangle('rectA')])
        repo = model.load(self.repo.path)
        self.assertEqual({}, repo.presets(repo.find('screen', 'New')))
        self.assertEqual([], self.check())


class ReferenceLinkTest(LinkTest):
    """hmi/references/<source>: another project's exports name styles and authorizations, not pictures or screens."""

    def reference(self, items):
        self.repo.write('hmi/references/B/screens/Other.xml', document('screen', 'Other', items, Number=40))

    def test_authorization_of_a_reference_export_is_known(self):
        self.reference([button('b', link_list('Authorization', 'Benutzerverwaltung'))])
        self.screen([button('btn', link_list('Authorization', 'Benutzerverwaltung'))])
        self.assertEqual([], self.check())

    def test_picture_of_a_reference_export_is_not_known(self):
        self.reference([graphic_view('logo', 'Logo_128')])
        path = self.screen([graphic_view('pic', 'Logo_128')])
        self.assertEqual([('error', 'links.unknown', path, 'pic')], self.check())

    def test_picture_in_the_graphics_list_of_the_project_is_known(self):
        self.repo.write('hmi/graphics.json', json.dumps(['Logo_128']))
        self.screen([graphic_view('pic', 'Logo_128')])
        self.assertEqual([], self.check())

    def test_screen_of_a_reference_export_is_not_known(self):
        self.repo.write('hmi/references/B/screens/0100 Overview.xml',
                        document('screen', '0100 Overview', Number=7))
        path = self.screen([button('btn', events=function('ActivateScreen', 'Screen name',
                                                          link_list('Value', '0100 Overview')))])
        self.assertEqual([('error', 'links.unknown', path, 'btn')], self.check())


class DataFileShapeTest(unittest.TestCase):
    def test_data_files_of_the_wrong_json_type_are_findings_not_crashes(self):
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        repo.write('hmi/generated/planned.json', json.dumps({'kind': 'textlist', 'name': 'x'}))
        repo.write('hmi/handbuilt.json', json.dumps({'screen': 'S'}))
        repo.write('hmi/generated/generated.json', json.dumps(['not', 'a', 'map']))
        found = [(f.severity, f.rule, f.document) for f in validate(repo.path) if f.rule == 'repo.json']
        self.assertEqual([('error', 'repo.json', 'hmi/generated/generated.json'),
                          ('error', 'repo.json', 'hmi/generated/planned.json'),
                          ('error', 'repo.json', 'hmi/handbuilt.json')], found)
