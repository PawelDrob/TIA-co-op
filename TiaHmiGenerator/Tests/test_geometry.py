import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, item, rect

PORTRAIT = 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0//Portrait'


def findings(repo, prefix):
    return [(f.severity, f.rule, f.document, f.object) for f in validate(repo.path) if f.rule.startswith(prefix)]


def group(name, members):
    return ('<Hmi.Screen.Group ID="0" CompositionName="ScreenItems"><AttributeList><ObjectName>%s</ObjectName>'
            '</AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.Group>' % (name, ''.join(members)))


class Base(unittest.TestCase):
    def make(self, **kw):
        repo = FixtureRepo(**kw)
        self.addCleanup(repo.cleanup)
        return repo


class OutsideResolutionTest(Base):
    def test_object_inside_the_screen_is_silent(self):
        repo = self.make()
        repo.generated('screen', 'S', document('screen', 'S', [rect('r', 0, 0, 1280, 800)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.outside'))

    def test_object_past_an_edge_is_an_error(self):
        repo = self.make()
        path = repo.generated('screen', 'S', document('screen', 'S', [
            rect('right', 1200, 100, 81, 10), rect('bottom', 0, 790, 10, 11), rect('left', -1, 100, 10, 10)],
            Number=1))
        self.assertEqual([('error', 'geometry.outside', path, 'bottom'),
                          ('error', 'geometry.outside', path, 'left'),
                          ('error', 'geometry.outside', path, 'right')], findings(repo, 'geometry.outside'))

    def test_size_a_document_leaves_out_is_not_guessed(self):
        # Before 2026-10-06 a missing Height of a text field counted as TIA's default 30 (minimal exports). Now the
        # box is what the document says (0 high) and document.incomplete reports the missing Height.
        repo = self.make()
        repo.export('screen', 'Reference', document('screen', 'Reference', [
            item('Hmi.Screen.TextField', 'S-Text', Left=0, Top=0, Width=100, Height=30)], Number=9))
        path = repo.generated('screen', 'S', document('screen', 'S', [
            item('Hmi.Screen.TextField', 'past', Left=200, Top=790, Width=100)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.outside'))
        self.assertEqual([('error', 'document.incomplete', path, 'past')], findings(repo, 'document.'))

    def test_portrait_panel_is_800_wide(self):
        repo = self.make(type_identifier=PORTRAIT)
        path = repo.generated('screen', 'S', document('screen', 'S', [
            rect('tall', 0, 1200, 800, 80), rect('wide', 0, 0, 801, 10)], Number=1))
        self.assertEqual([('error', 'geometry.outside', path, 'wide')], findings(repo, 'geometry.outside'))

    def test_group_members_are_checked(self):
        repo = self.make()
        path = repo.generated('screen', 'S', document('screen', 'S', [
            group('g', [rect('in', 0, 0, 10, 10), rect('out', 1275, 0, 10, 10)])], Number=1))
        self.assertEqual([('error', 'geometry.outside', path, 'out')], findings(repo, 'geometry.outside'))

    def test_popup_is_checked_against_its_own_size(self):
        repo = self.make()
        path = repo.generated('popup', 'P', document('popup', 'P', [
            rect('fits', 0, 0, 400, 300), rect('out', 350, 0, 51, 10)], Width=400, Height=300))
        self.assertEqual([('error', 'geometry.outside', path, 'out')], findings(repo, 'geometry.outside'))

    def test_template_objects_are_checked(self):
        repo = self.make()
        path = repo.generated('template', 'T', document('template', 'T', [rect('out', 0, 780, 10, 30)]))
        self.assertEqual([('error', 'geometry.outside', path, 'out')], findings(repo, 'geometry.outside'))

    def test_line_and_polyline_points(self):
        repo = self.make()
        pts = '\ufeff<Item>10, 10</Item><Item>1290, 20</Item>'
        path = repo.generated('screen', 'S', document('screen', 'S', [
            item('Hmi.Screen.Line', 'line', StartLeft=0, StartTop=100, EndLeft=1280, EndTop=100),
            item('Hmi.Screen.Polyline', 'poly', Points=pts)], Number=1))
        self.assertEqual([('error', 'geometry.outside', path, 'poly')], findings(repo, 'geometry.outside'))

    def test_exports_are_not_checked(self):
        repo = self.make()
        repo.export('screen', 'S', document('screen', 'S', [rect('r', 1200, 0, 100, 10)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.outside'))

    def test_unknown_device_skips_geometry(self):
        repo = self.make(type_identifier=None)
        repo.generated('screen', 'S', document('screen', 'S', [rect('r', 5000, 0, 100, 10)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.'))


class TemplateOverlapTest(Base):
    HEADER = rect('header', 0, 0, 1280, 80)
    NAV = rect('nav', 0, 720, 1280, 80)

    def test_object_over_the_exported_template_is_a_warning(self):
        repo = self.make()
        repo.export('template', 'T', document('template', 'T', [self.HEADER, self.NAV]))
        path = repo.generated('screen', 'S', document('screen', 'S', [
            rect('content', 0, 80, 1280, 640), rect('tooHigh', 10, 70, 100, 20)], template='T', Number=1))
        found = [f for f in validate(repo.path) if f.rule == 'geometry.template-overlap']
        self.assertEqual([('warning', path, 'tooHigh')], [(f.severity, f.document, f.object) for f in found])
        self.assertIn('header', found[0].message)

    def test_generated_template_replaces_its_export(self):
        repo = self.make()
        repo.export('template', 'T', document('template', 'T', [self.HEADER]))
        repo.generated('template', 'T', document('template', 'T', [rect('header', 0, 0, 1280, 40)]))
        repo.generated('screen', 'S', document('screen', 'S', [rect('r', 10, 50, 100, 20)], template='T', Number=1))
        self.assertEqual([], findings(repo, 'geometry.template-overlap'))

    def test_screen_without_template_has_the_full_resolution(self):
        repo = self.make()
        repo.export('template', 'T', document('template', 'T', [self.HEADER]))
        repo.generated('screen', 'S', document('screen', 'S', [rect('r', 0, 0, 1280, 800)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.'))

    def test_full_screen_template_background_does_not_count(self):
        repo = self.make()
        repo.export('template', 'T', document('template', 'T', [rect('background', 0, 0, 1280, 800), self.HEADER]))
        path = repo.generated('screen', 'S', document('screen', 'S', [rect('r', 10, 75, 100, 20)],
                                                       template='T', Number=1))
        self.assertEqual([('warning', 'geometry.template-overlap', path, 'r')],
                         findings(repo, 'geometry.template-overlap'))


class ObjectOverlapTest(Base):
    def test_partial_overlap_is_a_warning_on_the_later_object(self):
        repo = self.make()
        path = repo.generated('screen', 'S', document('screen', 'S', [
            rect('a', 100, 100, 100, 50), rect('b', 150, 120, 100, 50), rect('c', 400, 100, 10, 10)], Number=1))
        found = [f for f in validate(repo.path) if f.rule == 'geometry.overlap']
        self.assertEqual([('warning', path, 'b')], [(f.severity, f.document, f.object) for f in found])
        self.assertIn("'a'", found[0].message)

    def test_touching_edges_do_not_overlap(self):
        repo = self.make()
        repo.generated('screen', 'S', document('screen', 'S', [
            rect('a', 100, 100, 100, 50), rect('b', 200, 100, 100, 50)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.overlap'))

    def test_object_inside_another_is_layering_not_overlap(self):
        # A text field on a rectangle background, a button on a panel.
        repo = self.make()
        repo.generated('screen', 'S', document('screen', 'S', [
            rect('panel', 100, 100, 400, 300),
            item('Hmi.Screen.TextField', 'label', Left=110, Top=110, Width=100, Height=20)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.overlap'))

    def test_object_under_one_that_covers_it_is_a_hidden_warning(self):
        # The label comes first in document order, so the panel is drawn over it and hides it.
        repo = self.make()
        path = repo.generated('screen', 'S', document('screen', 'S', [
            item('Hmi.Screen.TextField', 'label', Left=110, Top=110, Width=100, Height=20),
            rect('panel', 100, 100, 400, 300)], Number=1))
        found = [f for f in validate(repo.path) if f.rule.startswith('geometry.')]
        self.assertEqual([('warning', 'geometry.hidden', path, 'label')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn("'panel'", found[0].message)

    def test_cover_shown_only_by_a_visibility_animation_does_not_hide(self):
        # A flashing copy over its original, shown in one state only (wincc-comfort-openness.md 7.2).
        repo = self.make()
        vis = ('<ObjectList><Hmi.Dynamic.VisibilityAnimation ID="0" CompositionName="Animations"><AttributeList>'
               '<Name>VisibilityAnimation</Name></AttributeList></Hmi.Dynamic.VisibilityAnimation></ObjectList>')
        repo.generated('screen', 'S', document('screen', 'S', [
            rect('original', 100, 100, 50, 50),
            item('Hmi.Screen.Rectangle', 'flashing', vis, Left=100, Top=100, Width=50, Height=50)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.'))

    def test_members_of_one_group_do_not_count(self):
        repo = self.make()
        path = repo.generated('screen', 'S', document('screen', 'S', [
            group('symbol', [rect('a', 100, 100, 50, 50), rect('b', 130, 130, 50, 50)]),
            rect('stray', 170, 170, 50, 50)], Number=1))
        self.assertEqual([('warning', 'geometry.overlap', path, 'stray')], findings(repo, 'geometry.overlap'))

    def test_invisible_buttons_and_lines_do_not_count(self):
        repo = self.make()
        pts = '\ufeff<Item>90, 90</Item><Item>300, 300</Item>'
        repo.generated('screen', 'S', document('screen', 'S', [
            rect('a', 100, 100, 100, 50),
            item('Hmi.Screen.Button', 'link', Left=150, Top=80, Width=200, Height=50, Mode='Invisible'),
            item('Hmi.Screen.Polyline', 'poly', Points=pts)], Number=1))
        self.assertEqual([], findings(repo, 'geometry.overlap'))
