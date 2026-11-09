import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, rect

ALARM_VIEW = {'screen': '010 Alarms', 'kind': 'alarm view', 'x': 0, 'y': 80, 'w': 1280, 'h': 560}


def findings(repo):
    return [(f.severity, f.rule, f.document, f.object) for f in validate(repo.path)
            if f.rule.startswith('handbuilt.')]


class HandbuiltTest(unittest.TestCase):
    def make(self):
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        return repo

    def test_generated_screen_replacing_a_screen_with_handbuilt_objects_is_an_error(self):
        repo = self.make()
        repo.handbuilt([ALARM_VIEW])
        repo.export('screen', '010 Alarms', document('screen', '010 Alarms', [rect('ack', 10, 650, 100, 50)], Number=10))
        path = repo.generated('screen', '010 Alarms',
                              document('screen', '010 Alarms', [rect('ack', 10, 650, 100, 50)], Number=10))
        found = [f for f in validate(repo.path) if f.rule == 'handbuilt.override']
        self.assertEqual([('error', path, None)], [(f.severity, f.document, f.object) for f in found])
        self.assertIn('alarm view', found[0].message)

    def test_other_generated_screens_are_silent(self):
        repo = self.make()
        repo.handbuilt([ALARM_VIEW])
        repo.generated('screen', '011 Other', document('screen', '011 Other', [rect('r', 0, 80, 1280, 560)],
                                                      Number=11))
        self.assertEqual([], findings(repo))

    def test_template_holding_a_handbuilt_object_cannot_be_replaced(self):
        repo = self.make()
        repo.handbuilt([dict(ALARM_VIEW, screen='T', kind='alarm window', y=0, h=40)])
        path = repo.generated('template', 'T', document('template', 'T', [rect('r', 0, 720, 1280, 80)]))
        self.assertEqual([('error', 'handbuilt.override', path, None)], findings(repo))

    def test_object_over_a_handbuilt_rectangle_of_the_linked_template_is_an_error(self):
        repo = self.make()
        repo.handbuilt([{'screen': 'T', 'kind': 'alarm window', 'x': 0, 'y': 80, 'w': 1280, 'h': 40}])
        repo.export('template', 'T', document('template', 'T'))
        path = repo.generated('screen', 'S', document('screen', 'S', [
            rect('under', 100, 100, 100, 50), rect('clear', 100, 120, 100, 50)], template='T', Number=1))
        found = [f for f in validate(repo.path) if f.rule == 'handbuilt.overlap']
        self.assertEqual([('error', path, 'under')], [(f.severity, f.document, f.object) for f in found])
        self.assertIn('alarm window', found[0].message)

    def test_entries_for_other_screens_do_not_apply(self):
        repo = self.make()
        repo.handbuilt([ALARM_VIEW])
        repo.export('template', 'T', document('template', 'T'))
        repo.generated('screen', 'S', document('screen', 'S', [rect('r', 100, 100, 100, 50)], template='T', Number=1))
        self.assertEqual([], findings(repo))
