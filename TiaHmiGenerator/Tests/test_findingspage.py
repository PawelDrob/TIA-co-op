"""The findings list below the preview's screen: sentences, folds, order; and /api/findingspage."""
import unittest

from hmipreview import findingspage, model, validate
from hmipreview.findings import error, warning
from hmipreview.links import open_planned
from Tests.fixture import FixtureRepo, document, group, item, rect
from Tests.test_server import ServerCase


def button(name, left, top, width=100, height=40):
    return item('Hmi.Screen.Button', name, Left=left, Top=top, Width=width, Height=height)


def symbolic(name, textlist):
    return item('Hmi.Screen.SymbolicIOField', name,
                '<LinkList><TextList TargetID="@OpenLink"><Name>%s</Name></TextList></LinkList>' % textlist,
                Left=100, Top=100, Width=120, Height=24)


def answer(repo):
    r = model.load(repo.path)
    return findingspage.page([('', r, validate(repo.path), open_planned(r))])


def texts(section):
    return [(row['fold'], [i['text'] for i in row['items']]) for rule in section['rules'] for row in rule['rows']]


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)


class SentenceTest(Base):
    def test_objects_overlapping_the_same_object_fold_into_one_line(self):
        self.repo.generated('screen', 'S', document('screen', 'S', [
            rect('recBack', 100, 100, 400, 100),
            button('btnA', 80, 120), button('btnB', 300, 180),
            rect('recOther', 700, 100, 100, 100), button('btnC', 750, 150)], Number=1))

        [s] = answer(self.repo)['sections']

        self.assertEqual(('screen', 'S'), (s['kind'], s['name']))
        self.assertEqual([('2 buttons overlap rectangle recBack', ['Button btnA overlaps rectangle recBack.',
                                                                  'Button btnB overlaps rectangle recBack.']),
                          (None, ['Button btnC overlaps rectangle recOther.'])], texts(s))
        self.assertEqual(['btnA', 'btnB'], [i['object'] for i in s['rules'][0]['rows'][0]['items']])
        self.assertEqual(('Objects overlap', 'geometry.overlap'), (s['rules'][0]['title'], s['rules'][0]['rule']))

    def test_template_objects_are_named_with_their_type_and_the_template(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [
            item('Hmi.Screen.TextField', 'txtHeader', Left=0, Top=0, Width=400, Height=40)]))
        self.repo.generated('screen', 'S', document('screen', 'S', [button('btnTop', 10, 10)], template='Tpl',
                                                   Number=1))

        [s] = [x for x in answer(self.repo)['sections'] if x['name'] == 'S']

        self.assertIn((None, ['Button btnTop overlaps text field txtHeader of template Tpl.']), texts(s))

    def test_an_object_outside_the_screen_is_named_once(self):
        self.repo.panel()
        self.repo.generated('screen', 'S', document('screen', 'S', [
            item('Hmi.Screen.IOField', 'io1', Left=1250, Top=760, Width=80, Height=30)], Number=1))

        [s] = [x for x in answer(self.repo)['sections'] if x['name'] == 'S']

        self.assertIn((None, ['I/O field io1 at 1250,760 size 80x30 is outside the screen area 1280x800.']), texts(s))

    def test_objects_with_the_same_message_fold(self):
        found = [warning('S.xml', n, 'text.fit', "en-US text 'Go' is 143 px wide.") for n in ('b1', 'b2')]
        found.append(warning('S.xml', 'b3', 'text.fit', "en-US text 'Stop' is 90 px wide."))
        types = {n: 'Hmi.Screen.Button' for n in ('b1', 'b2', 'b3')}
        rows = findingspage.rows('text.fit', found, types, lambda name: {})
        self.assertEqual(["2 buttons: en-US text 'Go' is 143 px wide.", None], [r['fold'] for r in rows])

    def test_a_finding_without_its_own_sentence_names_the_object_before_the_message(self):
        f = error('hmi/generated/screens/S.xml', 'io1', 'vocabulary.value', 'Value X is not known.')
        self.assertEqual('I/O field io1: Value X is not known.',
                         findingspage.sentence(f, {'io1': 'Hmi.Screen.IOField'}, {}))

    def test_a_link_to_a_planned_item_says_so_with_its_note(self):
        self.repo.planned([{'kind': 'textlist', 'name': 'tlModes', 'note': 'modes ticket'}])
        self.repo.generated('screen', 'S', document('screen', 'S', [symbolic('sym1', 'tlModes')], Number=1))

        [s] = answer(self.repo)['sections']

        self.assertIn((None, ['Symbolic I/O field sym1 links text list tlModes, a planned item not in TIA yet '
                              '(modes ticket).']), texts(s))

    def test_type_names_are_the_toolboxs(self):
        self.assertEqual(['Text field', 'I/O field', 'Faceplate instance', 'Object'],
                         [findingspage.type_name(t) for t in ('Hmi.Screen.TextField', 'Hmi.Screen.IOField',
                                                              'Hmi.Screen.FaceplateInstance', None)])
        self.assertEqual(['text field', 'I/O field'], [findingspage.lower(n) for n in ('Text field', 'I/O field')])


class FoldTest(Base):
    def test_a_folds_key_stays_while_its_count_changes(self):
        def fold_key(*names):
            found = [warning('S.xml', n, 'geometry.overlap', 'Overlaps x.', about=['recBack']) for n in names]
            [row] = findingspage.rows('geometry.overlap', found, {}, lambda name: {})
            return row['key']

        self.assertEqual(fold_key('b1', 'b2'), fold_key('b1', 'b2', 'b3'))
        self.assertNotEqual(fold_key('b1', 'b2'),
                            findingspage.rows('geometry.hidden', [
                                warning('S.xml', n, 'geometry.hidden', 'Drawn under.', about=['recBack'])
                                for n in ('b1', 'b2')], {}, lambda name: {})[0]['key'])


class OpenTest(Base):
    def test_a_finding_opens_only_the_document_the_preview_draws(self):
        self.repo.export('screen', 'S', document('screen', 'S', [rect('r0')], Number=1, export_setting='None'))
        self.repo.export('screen', 'T', document('screen', 'T', [rect('r0')], Number=2, export_setting='None'))
        self.repo.generated('screen', 'S', document('screen', 'S', [rect('r', 10, 10), rect('r2', 50, 50)],
                                                   Number=1))

        opens = {s['path']: s['opens'] for s in answer(self.repo)['sections'] if s['kind'] == 'screen'}

        self.assertEqual({'hmi/screens/S.xml': False, 'hmi/screens/T.xml': True,
                          'hmi/generated/screens/S.xml': True}, opens)

    def test_groups_and_text_list_rows_select_nothing(self):
        self.repo.generated('screen', 'S', document('screen', 'S', [
            group('grp', rect('a', 10, 10)), group('grp', rect('b', 300, 10)), rect('c', 500, 10),
            rect('c', 700, 10)], Number=1))

        [s] = answer(self.repo)['sections']

        select = {i['object']: i['select'] for r in s['rules'] for row in r['rows'] for i in row['items']}
        self.assertEqual({'grp': False, 'c': True}, select)
        [row] = findingspage.rows('languages.missing', [warning('T.xml', 'Font', 'languages.missing', 'x')],
                                  {'Font': 'Hmi.Screen.TextField'}, lambda name: {}, 'textlist')
        self.assertFalse(row['items'][0]['select'])

    def test_the_project_box_names_the_files_of_its_findings(self):
        self.repo.panel('TP900 Comfort', 800, 480)
        self.repo.planned([{'kind': 'nothing'}])

        [s] = [x for x in answer(self.repo)['sections'] if x['kind'] == 'project']

        self.assertEqual(['hmi/generated/planned.json', 'hmi/panel.json'], s['files'])


class OrderTest(Base):
    def test_planned_items_then_errors_then_warnings_then_the_project(self):
        self.repo.planned([{'kind': 'template', 'name': 'NewTpl', 'note': 'build in TIA'}])
        self.repo.generated('screen', 'A', document('screen', 'A', [rect('r', 10, 10), rect('r2', 50, 50)],
                                                   Number=1, Width=800, Height=480))
        self.repo.generated('screen', 'B', document('screen', 'B', [rect('far', 770, 10)], template='NewTpl',
                                                   Number=2, Width=800, Height=480))
        self.repo.panel('TP900 Comfort', 800, 480)

        a = answer(self.repo)

        [p] = a['planned']
        self.assertEqual(('template', 'NewTpl', 'build in TIA'), (p['kind'], p['name'], p['note']))
        self.assertEqual([{'device': '', 'kind': 'screen', 'name': 'B', 'object': None}], p['usedBy'])
        self.assertEqual(['B', 'A', ''], [s['name'] for s in a['sections']])
        self.assertEqual(['screen', 'screen', 'project'], [s['kind'] for s in a['sections']])
        b = a['sections'][0]
        self.assertGreater(b['errors'], 0)
        self.assertEqual('error', b['rules'][0]['severity'])
        self.assertTrue(texts(a['sections'][2])[0][1][0].startswith('hmi/panel.json: '))


class EndpointTest(ServerCase):
    def test_the_findings_list_of_the_repo(self):
        self.repo.generated('screen', 'S', document('screen', 'S', [rect('r', 10, 10), rect('r2', 50, 50)],
                                                   Number=1))
        self.serve()
        data = self.get_json('/api/findingspage')
        self.assertEqual([], data['planned'])
        self.assertEqual([['Rectangle r2 overlaps rectangle r.']],
                         [[i['text'] for row in rule['rows'] for i in row['items']]
                          for rule in data['sections'][0]['rules']])


if __name__ == '__main__':
    unittest.main()
