"""HMI cycles: TiaBridge imports a cycle from its export folder (hmi/cycles) after these rules. A minimal export
leaves out StartAtStartingPoint when it is true, and TIA's import of such a file set it false on every cycle of a
project; a full export goes back unchanged (docs/agent/openness-v20.md section 2, Cycles).
"""
import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, cycle


class CycleRuleTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def found(self, text, rel='hmi/cycles/Fast.xml', for_import=True, device=None):
        self.repo.write(rel, text)
        return [(f.severity, f.document, f.object, f.rule)
                for f in validate(self.repo.path, for_import=for_import, device=device) if f.rule.startswith('cycle.')]

    def test_a_full_export_passes(self):
        self.assertEqual([], self.found(cycle('Fast')))

    def test_a_minimal_export_is_refused_for_import(self):
        self.assertEqual([('error', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-full')],
                         self.found(cycle('Fast', 'None', full=False)))

    def test_a_minimal_export_whose_cycle_has_the_attribute_is_refused_too(self):
        # a minimal export writes StartAtStartingPoint false; the other defaults are still left out
        self.assertEqual([('error', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-full')],
                         self.found(cycle('Fast', 'None', full=False, StartAtStartingPoint='false')))

    def test_a_full_export_without_the_attribute_is_refused(self):
        self.assertEqual([('error', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-full')],
                         self.found(cycle('Fast', StartAtStartingPoint=None)))

    def test_a_file_without_export_setting_is_refused(self):
        self.assertEqual([('error', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-full')],
                         self.found(cycle('Fast', None)))

    def test_the_message_says_what_tia_did_and_the_way_out(self):
        self.repo.write('hmi/cycles/Fast.xml', cycle('Fast', 'None', full=False))
        message = [f.message for f in validate(self.repo.path, for_import=True) if f.rule == 'cycle.not-full'][0]
        self.assertIn("ExportSetting is 'None'", message)
        self.assertIn('StartAtStartingPoint', message)
        self.assertIn('as false', message)
        self.assertIn('Export the cycles again', message)

    def test_the_preview_warns(self):
        self.assertEqual([('warning', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-full')],
                         self.found(cycle('Fast', 'None', full=False), for_import=False))

    def test_another_object_in_the_cycles_folder_is_refused(self):
        self.assertEqual([('error', 'hmi/cycles/Fast.xml', 'Fast', 'cycle.not-cycle')],
                         self.found(cycle('Fast', root='Hmi.TextGraphicList.TextList')))

    def test_a_document_that_is_no_xml_is_refused(self):
        self.repo.write('hmi/cycles/Fast.xml', '<Document>')
        self.assertIn(('error', 'hmi/cycles/Fast.xml', 'document.parse'),
                      [(f.severity, f.document, f.rule) for f in validate(self.repo.path, for_import=True)])

    def test_the_cycles_of_the_device_given(self):
        self.repo.write('hmi/HMI_A/cycles/Fast.xml', cycle('Fast', 'None', full=False))
        self.assertEqual([('error', 'hmi/HMI_B/cycles/Slow.xml', 'Slow', 'cycle.not-full')],
                         self.found(cycle('Slow', 'None', full=False), rel='hmi/HMI_B/cycles/Slow.xml', device='HMI_B'))


if __name__ == '__main__':
    unittest.main()
