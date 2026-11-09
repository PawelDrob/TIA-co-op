"""The declared target panel hmi/panel.json: source of the resolution, checked against the hardware."""
import json
import os
import unittest
import xml.etree.ElementTree as ET

import hmixml
from hmipreview import validate
from Tests.fixture import TP1200, FixtureRepo, document
from Tests.test_cli import run_cli
from Tests.test_generator import reference_export

TP700 = 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0'


def resolution_findings(repo):
    return [(f.severity, f.rule, f.document) for f in validate(repo.path) if f.rule.startswith('resolution.')]


class DeclaredPanelTest(unittest.TestCase):
    def make(self, type_identifier=TP1200):
        repo = FixtureRepo(type_identifier=type_identifier)
        self.addCleanup(repo.cleanup)
        return repo

    def test_saved_panel_is_the_resolution_without_a_type_identifier(self):
        repo = self.make(None)
        repo.panel('TP700 Comfort', 800, 480)
        repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=800, Height=480))
        self.assertEqual([], resolution_findings(repo))
        path = repo.generated('screen', 'Big', document('screen', 'Big', Number=2, Width=1280, Height=800))
        self.assertEqual([('error', 'resolution.screen-size', path)], resolution_findings(repo))

    def test_panel_and_hardware_of_another_size_is_a_mismatch_naming_both(self):
        repo = self.make(TP700)
        repo.panel()                                                       # TP1200 Comfort 1280 x 800
        repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=1280, Height=800))
        self.assertEqual([('error', 'resolution.mismatch', 'hmi/panel.json')], resolution_findings(repo))
        message = next(f.message for f in validate(repo.path) if f.rule == 'resolution.mismatch')
        self.assertIn('TP1200 Comfort', message)
        self.assertIn('TP700 Comfort', message)
        self.assertIn('6AV2124-0GC01-0AX0', message)

    def test_panel_and_hardware_of_another_orientation_is_a_mismatch(self):
        repo = self.make(TP1200 + '//Portrait')
        repo.panel()
        self.assertEqual([('error', 'resolution.mismatch', 'hmi/panel.json')], resolution_findings(repo))

    def test_panel_matching_the_hardware_is_silent(self):
        repo = self.make(TP1200)
        repo.panel('TP1200 Comfort', 1280, 800, order_number='6AV2124-0MC01-0AX0')
        self.assertEqual([], resolution_findings(repo))

    def test_panel_matching_the_device_selected_by_hmi_device(self):
        repo = self.make(None)
        repo.write('tiabridge.json', json.dumps({'hmiTypeIdentifier': {'HMI_1': TP1200, 'HMI_2': TP700},
                                                 'hmiDevice': 'HMI_2'}))
        repo.panel()
        self.assertEqual([('error', 'resolution.mismatch', 'hmi/panel.json')], resolution_findings(repo))
        repo.panel('TP700 Comfort', 800, 480)
        self.assertEqual([], resolution_findings(repo))

    def test_neither_panel_nor_hardware_names_the_panel_command(self):
        repo = self.make(None)
        found = [f for f in validate(repo.path) if f.rule.startswith('resolution.')]
        self.assertEqual(['resolution.unknown-device'], [f.rule for f in found])
        self.assertIn('python -m hmipreview panel', found[0].message)

    def test_unusable_panel_file_is_a_repo_error(self):
        repo = self.make()
        repo.write('hmi/panel.json', json.dumps({'panel': 'TP1200 Comfort', 'width': '1280'}))
        found = [f for f in validate(repo.path) if f.document == 'hmi/panel.json']
        self.assertEqual([('error', 'repo.json')], [(f.severity, f.rule) for f in found])


def read_panel(repo):
    with open(os.path.join(repo.path, 'hmi', 'panel.json'), encoding='utf-8-sig') as f:
        return json.load(f)


def has_panel_file(repo):
    return os.path.exists(os.path.join(repo.path, 'hmi', 'panel.json'))


class GeneratorPanelTest(unittest.TestCase):
    def make(self, type_identifier=TP1200):
        repo = FixtureRepo(type_identifier=type_identifier)
        self.addCleanup(repo.cleanup)
        return repo

    def test_first_run_without_a_panel_asks_and_offers_the_hardware(self):
        repo = self.make(TP1200)
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path)
        msg = str(cm.exception)
        self.assertIn('python -m hmipreview panel', msg)
        self.assertIn('TP2200 Comfort', msg)                        # the panel table
        self.assertIn('6AV2124-0MC01-0AX0', msg)                    # the hardware offered as the default
        self.assertFalse(has_panel_file(repo))                      # nothing saved silently

    def test_first_run_without_panel_or_hardware_names_the_command(self):
        repo = self.make('OrderNumber:6AV2 123-2GB03-0AX0/17.0.0.0')
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path)
        self.assertIn('python -m hmipreview panel', str(cm.exception))
        self.assertIn('6AV2 123-2GB03-0AX0', str(cm.exception))

    def test_begin_with_a_panel_saves_the_choice_with_the_run(self):
        repo = self.make(None)
        res = hmixml.begin(repo.path, panel='TP700 Comfort')
        self.assertEqual((800, 480), (res.width, res.height))
        self.assertEqual((800, 480), hmixml.size())
        hmixml.finish()
        self.assertEqual({'panel': 'TP700 Comfort', 'width': 800, 'height': 480, 'portrait': False},
                         read_panel(repo))
        self.assertEqual((800, 480), (hmixml.begin(repo.path).width, hmixml.begin(repo.path).height))
        hmixml.finish()

    def test_begin_with_the_saved_panel_again_is_fine_another_one_is_refused(self):
        repo = self.make(None)
        repo.panel('TP700 Comfort', 800, 480)
        hmixml.begin(repo.path, panel='TP700')
        hmixml.finish()
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path, panel='TP1200 Comfort')
        self.assertIn('TP700 Comfort', str(cm.exception))
        self.assertIn('python -m hmipreview panel', str(cm.exception))

    def test_begin_refuses_a_panel_that_collides_with_the_hardware(self):
        repo = self.make(TP700)
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path, panel='TP1200 Comfort')
        self.assertIn('TP700 Comfort', str(cm.exception))
        self.assertFalse(has_panel_file(repo))
        repo.panel()                                                # saved earlier, hardware changed since
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path)
        self.assertIn('TP1200 Comfort', str(cm.exception))

    def test_refused_run_does_not_save_the_panel(self):
        repo = self.make(None)
        reference_export(repo)
        hmixml.begin(repo.path, panel='1280x800')
        hmixml.add('screen', hmixml.screen_doc('Bad', 9101, [ET.fromstring(
            '<Hmi.Screen.Invented ID="0"><AttributeList><ObjectName>x</ObjectName></AttributeList>'
            '</Hmi.Screen.Invented>')]))
        with self.assertRaises(hmixml.GenerationRefused):
            hmixml.finish()
        self.assertFalse(has_panel_file(repo))


class PanelCommandTest(unittest.TestCase):
    def make(self, type_identifier=TP1200):
        repo = FixtureRepo(type_identifier=type_identifier)
        self.addCleanup(repo.cleanup)
        return repo

    def test_panel_by_name_is_saved(self):
        repo = self.make()
        r = run_cli('panel', repo.path, 'TP1200')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual({'panel': 'TP1200 Comfort', 'width': 1280, 'height': 800, 'portrait': False},
                         read_panel(repo))
        self.assertIn('TP1200 Comfort', r.stdout)

    def test_panel_by_order_number_portrait(self):
        repo = self.make(TP1200 + '//Portrait')
        r = run_cli('panel', repo.path, '6AV2 124-0MC01-0AX0', '--portrait')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual({'panel': 'TP1200 Comfort', 'orderNumber': '6AV2124-0MC01-0AX0', 'width': 800,
                          'height': 1280, 'portrait': True}, read_panel(repo))
        self.assertEqual([], [f for f in validate(repo.path) if f.rule.startswith('resolution.')])

    def test_panel_by_size(self):
        repo = self.make(None)
        r = run_cli('panel', repo.path, '1024x600')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual({'panel': '1024x600', 'width': 1024, 'height': 600, 'portrait': False}, read_panel(repo))

    def test_panel_colliding_with_the_hardware_is_refused_and_not_saved(self):
        repo = self.make(TP700)
        r = run_cli('panel', repo.path, 'TP1200 Comfort')
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn('TP700 Comfort', r.stderr)
        self.assertFalse(has_panel_file(repo))

    def test_unknown_panel_lists_the_table(self):
        repo = self.make()
        r = run_cli('panel', repo.path, 'TP9999')
        self.assertEqual(2, r.returncode, r.stdout + r.stderr)
        self.assertIn('TP1200 Comfort', r.stderr)
        self.assertFalse(has_panel_file(repo))


if __name__ == '__main__':
    unittest.main()
