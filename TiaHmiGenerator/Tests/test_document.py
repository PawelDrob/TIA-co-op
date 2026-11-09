"""Document rules: generated objects carry every attribute the full exports carry on that type; exports are full."""
import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, item, rect


def by_rule(findings, prefix):
    return [f for f in findings if f.rule.startswith(prefix)]


def text_field(name, **attrs):
    return item('Hmi.Screen.TextField', name, **{'Left': 10, 'Top': 90, 'Width': 100, 'Height': 30, **attrs})


class DocumentRulesTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [
            rect('S-Panel'), text_field('S-Title')], Number=1))

    def found(self, prefix='document.'):
        return by_rule(validate(self.repo.path), prefix)

    def test_generated_object_without_an_attribute_every_full_export_carries_is_an_error(self):
        # project B 2026-10-06: copies of minimally exported text fields had no Height; the preview had to guess 30.
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            text_field('title', Height=None, VerticalAlignment=None)], Number=2))
        found = self.found()
        self.assertEqual([('error', 'document.incomplete', path, 'title')],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn('Height, VerticalAlignment', found[0].message)
        self.assertIn('Hmi.Screen.TextField', found[0].message)
        self.assertIn('full exports', found[0].message)

    def test_complete_generated_document_is_silent(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1'), text_field('t1')], Number=2))
        self.assertEqual([], self.found())

    def test_root_object_is_checked_too(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2,
                                                             GridColor=None))
        found = self.found()
        self.assertEqual([('document.incomplete', path, None)], [(f.rule, f.document, f.object) for f in found])
        self.assertIn('GridColor', found[0].message)
        self.assertIn('Hmi.Screen.Screen', found[0].message)

    def test_an_attribute_some_full_export_objects_lack_is_not_required(self):
        self.repo.export('screen', 'Other', document('screen', 'Other', [rect('S-Thin', Flashing=None)], Number=3))
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1', Flashing=None)], Number=2))
        self.assertEqual([], self.found())

    def test_minimal_exports_do_not_set_the_required_attributes_and_are_reported(self):
        self.repo.export('screen', 'Old', document('screen', 'Old', [rect('S-Old', full=False)], Number=3,
                                                   full=False, export_setting='None'), folder='Legacy')
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2))
        found = self.found()
        self.assertEqual([('warning', 'document.not-full', 'hmi/screens/Legacy/Old.xml', None)],
                         [(f.severity, f.rule, f.document, f.object) for f in found])
        self.assertIn("'None'", found[0].message)

    def test_export_without_export_setting_is_not_full(self):
        self.repo.export('popup', 'Pop', document('popup', 'Pop', [], Width=300, Height=200, export_setting=None))
        self.assertEqual(['document.not-full'], [f.rule for f in self.found()])

    def test_exports_are_not_checked_for_completeness(self):
        self.repo.export('screen', 'Odd', document('screen', 'Odd', [text_field('S-Odd', Height=None)], Number=3))
        self.assertEqual([], self.found())

    def test_without_any_full_export_nothing_is_required(self):
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        repo.export('screen', 'Old', document('screen', 'Old', [rect('S-Old', full=False)], Number=1, full=False,
                                              export_setting='None'))
        repo.generated('screen', 'New', document('screen', 'New', [rect('r1', full=False)], Number=2, full=False))
        self.assertEqual(['document.not-full'], [f.rule for f in by_rule(validate(repo.path), 'document.')])


if __name__ == '__main__':
    unittest.main()
