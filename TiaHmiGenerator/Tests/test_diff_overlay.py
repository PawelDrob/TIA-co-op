"""Rendering: the diff toggle draws outlines on the canvas (added green, removed red ghost, moved light blue
with the old rectangle, changed amber: the change report's colours) and lists the changes in words. Checked in the
dumped DOM, no pixel comparison."""
import unittest

from Tests.fixture import document, rect
from Tests.browser import NOT_FOUND
from Tests.test_browser import EDGE, BrowserCase


def outlines(dom):
    layer = dom.by_id('diff-layer')
    return layer.find_all(lambda n: 'diff-outline' in n.classes)


def rect_of(node):
    return tuple(node.num(k) for k in ('x', 'y', 'width', 'height'))


def by(dom, name, part='new'):
    found = [n for n in outlines(dom) if n.attrs.get('data-name') == name and n.attrs.get('data-part') == part]
    return found[0] if found else None


@unittest.skipUnless(EDGE, NOT_FOUND)
class DiffOverlayTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [
            rect('same'), rect('moved', top=200), rect('gone', top=300), rect('recoloured', top=400,
                                                                               BackColor='1, 2, 3')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [
            rect('same'), rect('moved', left=50, top=210, width=120), rect('recoloured', top=400, BackColor='4, 5, 6'),
            rect('added', left=300, top=500)], Number=2))

    def test_each_change_kind_is_outlined_against_the_last_commit(self):
        dom = self.page(screen='Silo', diff='commit')

        added = by(dom, 'added')
        self.assertEqual(('added', (300, 500, 100, 50)), (added.attrs['data-change'], rect_of(added)))
        ghost = by(dom, 'gone', 'old')
        self.assertEqual(('removed', (10, 300, 100, 50)), (ghost.attrs['data-change'], rect_of(ghost)))
        self.assertIsNone(by(dom, 'gone'))
        moved_new, moved_old = by(dom, 'moved'), by(dom, 'moved', 'old')
        self.assertEqual(('moved', (50, 210, 120, 50)), (moved_new.attrs['data-change'], rect_of(moved_new)))
        self.assertEqual(('moved', (10, 200, 100, 50)), (moved_old.attrs['data-change'], rect_of(moved_old)))
        changed = by(dom, 'recoloured')
        self.assertEqual(('changed', (10, 400, 100, 50)), (changed.attrs['data-change'], rect_of(changed)))
        self.assertEqual({'added', 'gone', 'moved', 'recoloured'}, {n.attrs['data-name'] for n in outlines(dom)})

    def test_outline_colours_follow_the_change_kind(self):
        dom = self.page(screen='Silo', diff='commit')

        self.assertEqual({'added': 'diff-added', 'gone': 'diff-removed', 'moved': 'diff-moved',
                          'recoloured': 'diff-changed'},
                         {n: next(c for c in by(dom, n, 'old' if n == 'gone' else 'new').classes
                                  if c.startswith('diff-') and c != 'diff-outline') for n in
                          ('added', 'gone', 'moved', 'recoloured')})

    def test_change_list_in_words(self):
        dom = self.page(screen='Silo', diff='commit')

        items = dom.by_id('diff-list').find_all(lambda n: 'diff-line' in n.classes)
        self.assertEqual(['Rectangle moved: moved (10, 200) 100x50 -> (50, 210) 120x50',
                          "Rectangle recoloured: BackColor '1, 2, 3' -> '4, 5, 6'",
                          'Rectangle added: added at (300, 500) 100x50',
                          'Rectangle gone: removed from (10, 300) 100x50'],
                         [n.text() for n in items])
        self.assertEqual(['moved', 'recoloured', 'added', 'gone'], [n.attrs['data-object'] for n in items])

    def test_against_the_export(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('added', left=300, top=480)], Number=2))

        dom = self.page(screen='Silo', diff='export')

        self.assertEqual('export', dom.by_id('diff-slot').attrs.get('data-against'))
        moved = by(dom, 'added')
        self.assertEqual(('moved', (300, 500, 100, 50)), (moved.attrs['data-change'], rect_of(moved)))
        self.assertEqual((300, 480, 100, 50), rect_of(by(dom, 'added', 'old')))
        self.assertEqual({'same', 'moved', 'recoloured'},
                         {n.attrs['data-name'] for n in outlines(dom) if n.attrs['data-change'] == 'added'})

    def test_off_by_default(self):
        dom = self.page(screen='Silo')

        self.assertEqual([], outlines(dom))
        self.assertEqual('off', dom.by_id('diff-slot').attrs.get('data-against'))
        self.assertEqual({'off', 'commit', 'export'},
                         {n.attrs['data-against'] for n in dom.by_id('diff-controls').find_all(
                             lambda n: n.tag == 'button')})

    def test_exported_screen_against_its_last_commit(self):
        # an export has a diff too, export vs export (TIA changed between two exports)
        self.repo.export('screen', 'Overview', document('screen', 'Overview', [rect('r')], Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Overview', document('screen', 'Overview', [rect('r', left=40)], Number=1))

        dom = self.page(screen='Overview', diff='commit')

        self.assertEqual([('r', 'moved')], [(n.attrs['data-name'], n.attrs['data-change']) for n in outlines(dom)
                                            if n.attrs['data-part'] == 'new'])
        self.assertEqual('tia', dom.by_id('diff-slot').attrs.get('data-state'))
        self.assertEqual('Comparing: export vs export', dom.by_id('comparing').text())

    def test_the_header_says_what_is_compared(self):
        # The maintainer's words: "Comparing: export vs generated, generated vs generated, export vs export"
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('same')], Number=2))
        cases = {'commit': 'Comparing: generated vs generated', 'export': 'Comparing: export vs generated'}
        for against, text in cases.items():
            self.assertEqual(text, self.page(screen='Silo', diff=against).by_id('comparing').text())
        self.assertEqual('', self.page(screen='Silo').by_id('comparing').text())


if __name__ == '__main__':
    unittest.main()
