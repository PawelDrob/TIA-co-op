"""Object-level diff of a generated screen against its last commit or its TIA export: over HTTP and through the CLI."""
import json
import os
import subprocess
import sys
import unittest

from Tests.fixture import FixtureRepo, document, item, rect
from Tests.test_server import ServerCase

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # TiaHmiGenerator


def text(comp, en, es=None):
    """A MultilingualText composition (rich text, as exported) in en-US and optionally es-ES."""
    items = [('en-US', en)] + ([('es-ES', es)] if es is not None else [])
    return ('<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>'
            % (comp, ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList>'
                             '<Culture>%s</Culture><Text><body><p>%s</p></body></Text></AttributeList>'
                             '</MultilingualTextItem>' % (cu, t) for cu, t in items)))


def button(name, label, es=None, left=10, top=90, children='', **attrs):
    return item('Hmi.Screen.Button', name, '<ObjectList>%s%s</ObjectList>' % (children, text('TextOff', label, es)),
                Left=left, Top=top, Width=120, Height=40, **attrs)


class DiffAgainstCommitTest(ServerCase):
    def test_moved_object_has_its_old_and_new_rectangle(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=10, top=90)], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=20, top=100)], Number=2))
        self.serve()

        data = self.get_json('/api/diff', name='Silo', against='commit')

        self.assertEqual([{'object': 'r1', 'type': 'Rectangle', 'kind': 'moved',
                           'old': {'x': 10, 'y': 90, 'w': 100, 'h': 50},
                           'new': {'x': 20, 'y': 100, 'w': 100, 'h': 50},
                           'attributes': [], 'texts': [], 'links': [], 'parts': []}],
                         data['changes'])
        self.assertEqual(['Rectangle r1: moved (10, 90) 100x50 -> (20, 100) 100x50'], data['lines'])

    def test_added_and_removed_objects_unchanged_ones_not_listed(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('keep'), rect('old', top=200)],
                                                       Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('keep'), rect('new', top=300)],
                                                       Number=2))
        self.serve()

        data = self.get_json('/api/diff', name='Silo')

        self.assertEqual([('new', 'added', None, {'x': 10, 'y': 300, 'w': 100, 'h': 50}),
                          ('old', 'removed', {'x': 10, 'y': 200, 'w': 100, 'h': 50}, None)],
                         [(c['object'], c['kind'], c['old'], c['new']) for c in data['changes']])
        self.assertEqual(['Rectangle new: added at (10, 300) 100x50',
                          'Rectangle old: removed from (10, 200) 100x50'], data['lines'])

    def test_button_text_change_in_words(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [button('btnStart', 'Start')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [button('btnStart', 'Run')], Number=2))
        self.serve()

        data = self.get_json('/api/diff', name='Silo')

        self.assertEqual(["Button btnStart: TextOff 'Start' -> 'Run'"], data['lines'])
        [c] = data['changes']
        self.assertEqual(('changed', [{'part': 'TextOff', 'culture': 'en-US', 'old': 'Start', 'new': 'Run'}]),
                         (c['kind'], c['texts']))
        self.assertEqual(c['old'], c['new'])

    def test_text_in_two_languages_names_the_culture(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [
            button('b', 'Start', es='Iniciar')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [
            button('b', 'Start', es='Arrancar')], Number=2))
        self.serve()
        self.assertEqual(["Button b: TextOff [es-ES] 'Iniciar' -> 'Arrancar'"],
                         self.get_json('/api/diff', name='Silo')['lines'])

    def test_attribute_link_and_event_changes_of_one_object(self):
        def field(color, tag, event):
            links = '<LinkList><Tag TargetID="@OpenLink"><Name>%s</Name></Tag></LinkList>' % tag
            events = ('<ObjectList><Hmi.Event.Event ID="0" CompositionName="Events"><AttributeList>'
                      '<Name>%s</Name></AttributeList></Hmi.Event.Event></ObjectList>' % event)
            return item('Hmi.Screen.IOField', 'f1', links + events, Left=10, Top=90, Width=80, Height=30,
                        BackColor=color)
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [field('1, 2, 3', 'a', 'Press')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [field('4, 5, 6', 'b', 'Release')],
                                                       Number=2))
        self.serve()

        data = self.get_json('/api/diff', name='Silo')

        [c] = data['changes']
        self.assertEqual(('f1', 'IOField', 'changed'), (c['object'], c['type'], c['kind']))
        self.assertEqual([{'name': 'BackColor', 'old': '1, 2, 3', 'new': '4, 5, 6'}], c['attributes'])
        self.assertEqual([{'kind': 'Tag', 'old': 'a', 'new': 'b'}], c['links'])
        self.assertEqual(['Events'], c['parts'])
        self.assertEqual(["IOField f1: BackColor '1, 2, 3' -> '4, 5, 6'",
                          "IOField f1: Tag link 'a' -> 'b'",
                          'IOField f1: Events changed'], data['lines'])

    def test_screen_attributes_are_a_change_without_object(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=3))
        self.serve()

        data = self.get_json('/api/diff', name='Silo')

        self.assertEqual([(None, 'Screen', 'changed', [{'name': 'Number', 'old': '2', 'new': '3'}])],
                         [(c['object'], c['type'], c['kind'], c['attributes']) for c in data['changes']])
        self.assertEqual(["Screen Silo: Number '2' -> '3'"], data['lines'])

    def test_ids_and_layout_whitespace_do_not_count(self):
        xml = document('screen', 'Silo', [button('b', 'Go')], Number=2)
        self.repo.generated('screen', 'Silo', xml.replace('ID="0"', 'ID="5"'))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', xml.replace('><', '>\n  <'))
        self.serve()
        self.assertEqual([], self.get_json('/api/diff', name='Silo')['changes'])

    def test_document_not_yet_committed_is_all_added(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        self.serve()
        data = self.get_json('/api/diff', name='Silo', against='commit')
        self.assertEqual({'against': 'commit', 'path': None, 'ref': None}, data['base'])
        self.assertEqual([('r1', 'added')], [(c['object'], c['kind']) for c in data['changes']])

    def test_base_names_the_committed_file(self):
        path = self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        self.repo.commit()
        self.serve()
        data = self.get_json('/api/diff', name='Silo')
        self.assertEqual(('screen', 'Silo', path, 'commit'), (data['kind'], data['name'], data['path'],
                                                              data['against']))
        self.assertEqual({'against': 'commit', 'path': path, 'ref': 'HEAD'}, data['base'])
        self.assertEqual(([], []), (data['changes'], data['lines']))


class DiffAgainstExportTest(ServerCase):
    def test_changes_the_import_would_make_to_the_tia_screen(self):
        exp = self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1'), rect('alarm', top=300)],
                                                          Number=2), folder='G05')
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', width=200),
                                                                          button('b', 'Go')], Number=2))
        self.repo.commit()
        self.serve()

        data = self.get_json('/api/diff', name='Silo', against='export')

        self.assertEqual({'against': 'export', 'path': exp, 'ref': None}, data['base'])
        self.assertEqual(['Rectangle r1: moved (10, 90) 100x50 -> (10, 90) 200x50',
                          'Button b: added at (10, 90) 120x40',
                          'Rectangle alarm: removed from (10, 300) 100x50'], data['lines'])

    def test_new_screen_without_export_is_all_added(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2))
        self.serve()
        data = self.get_json('/api/diff', name='New', against='export')
        self.assertIsNone(data['base']['path'])
        self.assertEqual(['Rectangle r1: added at (10, 90) 100x50'], data['lines'])

    def test_popup_by_kind(self):
        self.repo.export('popup', 'Pop', document('popup', 'Pop', [rect('r1')], Width=300, Height=200))
        self.repo.generated('popup', 'Pop', document('popup', 'Pop', [rect('r1', left=20)], Width=300, Height=200))
        self.serve()
        data = self.get_json('/api/diff', kind='popup', name='Pop', against='export')
        self.assertEqual(['Rectangle r1: moved (10, 90) 100x50 -> (20, 90) 100x50'], data['lines'])


class ExportDiffTest(ServerCase):
    """An export has a diff too: against its last commit (export vs export), against the export itself
    (nothing generated for it: no change)."""

    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        self.repo.commit()
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=20)], Number=2))
        self.serve()

    def test_against_the_last_commit(self):
        data = self.get_json('/api/diff', name='Silo')
        self.assertEqual(('tia', ['Rectangle r1: moved (10, 90) 100x50 -> (20, 90) 100x50']),
                         (data['origin'], data['lines']))

    def test_against_the_export_is_itself(self):
        data = self.get_json('/api/diff', name='Silo', against='export')
        self.assertEqual(([], 'hmi/screens/Silo.xml'), (data['lines'], data['base']['path']))


class StatesTest(unittest.TestCase):
    """The project tree's marks, every effective document against its base."""

    def test_against_the_last_commit_and_the_export(self):
        from hmipreview import diff, model
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        tl = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
              '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>tlMode</Name><Note>%s</Note></AttributeList>'
              '</Hmi.TextGraphicList.TextList></Document>\n')
        repo.export('screen', 'Same', document('screen', 'Same', [rect('r1')], Number=1))
        repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        repo.export('textlist', 'tlMode', tl % 'a')
        repo.commit()
        repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=30)], Number=2))
        repo.export('textlist', 'tlMode', tl % 'b')
        repo.generated('popup', 'Pop', document('popup', 'Pop', Width=300, Height=200))

        loaded = model.load(repo.path)
        self.assertEqual({('screen', 'Same'): 'same', ('screen', 'Silo'): 'changed', ('textlist', 'tlMode'): 'changed',
                          ('popup', 'Pop'): 'new'}, diff.states(loaded, 'commit'))
        self.assertEqual({('screen', 'Same'): 'same', ('screen', 'Silo'): 'changed', ('textlist', 'tlMode'): 'same',
                          ('popup', 'Pop'): 'new'}, diff.states(loaded, 'export'))


class DiffErrorTest(ServerCase):
    def test_document_that_does_not_exist_is_not_found(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', Number=2))
        self.serve()
        self.assertEqual(404, self.get_error('/api/diff', name='Nope'))
        self.assertEqual(404, self.get_error('/api/diff', name='Silo', kind='popup'))

    def test_bad_base_and_missing_name_are_bad_requests(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', Number=2))
        self.serve()
        self.assertEqual(400, self.get_error('/api/diff', name='Silo', against='yesterday'))
        self.assertEqual(400, self.get_error('/api/diff'))


def run_cli(*args):
    return subprocess.run([sys.executable, '-m', 'hmipreview'] + list(args), cwd=PACKAGE_ROOT,
                          capture_output=True, text=True, encoding='utf-8')


class DiffCliTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [button('btnStart', 'Begin')], Number=2))
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [button('btnStart', 'Start')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [button('btnStart', 'Run'),
                                                                          rect('r9', top=300)], Number=2))

    def test_prints_the_changes_against_the_last_commit_by_default(self):
        r = run_cli('diff', self.repo.path, 'Silo')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(["Button btnStart: TextOff 'Start' -> 'Run'",
                          'Rectangle r9: added at (10, 300) 100x50'], r.stdout.splitlines())

    def test_against_the_export(self):
        r = run_cli('diff', self.repo.path, 'Silo', '--against', 'export')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("Button btnStart: TextOff 'Begin' -> 'Run'", r.stdout.splitlines()[0])

    def test_json_is_the_endpoint_answer(self):
        r = run_cli('diff', self.repo.path, 'Silo', '--json')
        data = json.loads(r.stdout)
        self.assertEqual(['btnStart', 'r9'], [c['object'] for c in data['changes']])

    def test_no_changes_says_so(self):
        self.repo.commit()
        r = run_cli('diff', self.repo.path, 'Silo')
        self.assertEqual((0, 'No changes against the last commit.'), (r.returncode, r.stdout.strip()))

    def test_screen_that_does_not_exist_exits_one(self):
        r = run_cli('diff', self.repo.path, 'Nope')
        self.assertEqual(1, r.returncode)
        self.assertIn('no screen Nope', r.stderr)


if __name__ == '__main__':
    unittest.main()
