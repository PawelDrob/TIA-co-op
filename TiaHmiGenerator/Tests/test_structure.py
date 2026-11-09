import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, group, item, rect

FP_TYPE = '_Library@$@Types@$@Faceplate@$@fpMotor V 0.0.1'


def structure_findings(repo, **kw):
    return [(f.severity, f.rule, f.document, f.object) for f in validate(repo.path, **kw)
            if f.rule.startswith('structure.')]


def faceplate(name):
    return item('Hmi.Screen.FaceplateInstance', name, Left=10, Top=90, Width=100, Height=100,
                FaceplateTypeName=FP_TYPE)


class GroupedFaceplateTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def test_faceplate_inside_a_group_is_an_error(self):
        path = self.repo.generated('screen', 'S1', document('screen', 'S1', [group('grp1', faceplate('fp1'))],
                                                            Number=9101))
        self.assertEqual([('error', 'structure.grouped-faceplate', path, 'fp1')], structure_findings(self.repo))

    def test_faceplate_on_its_own_is_fine(self):
        self.repo.generated('screen', 'S1', document('screen', 'S1', [faceplate('fp1'), group('grp1', rect('r1'))],
                                                     Number=9101))
        self.assertEqual([], structure_findings(self.repo))


class DuplicateNameTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def test_two_objects_with_one_name_on_a_screen_are_an_error(self):
        path = self.repo.generated('screen', 'S1', document('screen', 'S1', [rect('r1'), group('grp1', rect('r1'))],
                                                            Number=9101))
        self.assertEqual([('error', 'structure.duplicate-name', path, 'r1')], structure_findings(self.repo))

    def test_same_name_on_two_screens_is_fine(self):
        self.repo.generated('screen', 'S1', document('screen', 'S1', [rect('r1')], Number=9101))
        self.repo.generated('popup', 'P1', document('popup', 'P1', [rect('r1')]))
        self.assertEqual([], structure_findings(self.repo))


class DuplicateNumberTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def test_generated_screen_with_the_number_of_an_exported_screen_is_an_error(self):
        self.repo.export('screen', 'Overview', document('screen', 'Overview', Number=10))
        path = self.repo.generated('screen', 'New', document('screen', 'New', Number=10))
        self.assertEqual([('error', 'structure.duplicate-number', path, None)], structure_findings(self.repo))

    def test_two_generated_screens_with_one_number_are_both_reported(self):
        a = self.repo.generated('screen', 'A', document('screen', 'A', Number=9101))
        b = self.repo.generated('screen', 'B', document('screen', 'B', Number=9101), folder='Sub')
        self.assertEqual([('error', 'structure.duplicate-number', a, None),
                          ('error', 'structure.duplicate-number', b, None)], structure_findings(self.repo))

    def test_generated_screen_replacing_its_own_export_is_not_a_duplicate(self):
        self.repo.export('screen', 'Overview', document('screen', 'Overview', Number=10))
        self.repo.generated('screen', 'Overview', document('screen', 'Overview', Number=10))
        self.repo.generated('screen', 'Other', document('screen', 'Other', Number=11))
        self.assertEqual([], structure_findings(self.repo))

    def test_screen_moved_to_the_number_a_replaced_export_frees_is_fine(self):
        self.repo.export('screen', 'Old', document('screen', 'Old', Number=10))
        self.repo.generated('screen', 'Old', document('screen', 'Old', Number=12))
        self.repo.generated('screen', 'New', document('screen', 'New', Number=10))
        self.assertEqual([], structure_findings(self.repo))


if __name__ == '__main__':
    unittest.main()
