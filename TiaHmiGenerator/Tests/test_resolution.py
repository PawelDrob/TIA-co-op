import json
import unittest

import hmixml
from hmipreview import model, validate
from Tests.fixture import TP1200, FixtureRepo, document


def resolution_findings(repo):
    return [(f.severity, f.rule, f.document) for f in validate(repo.path) if f.rule.startswith('resolution.')]


class ResolutionTest(unittest.TestCase):
    def make(self, type_identifier):
        repo = FixtureRepo(type_identifier=type_identifier)
        self.addCleanup(repo.cleanup)
        return repo

    def test_resolution_table_per_panel(self):
        # Comfort Panels operating instructions 07/2022, section 8.8.
        cases = [
            ('OrderNumber:6AV2 124-2DC01-0AX0/17.0.0.0', 480, 272),     # KTP400 Comfort
            ('OrderNumber:6AV2 124-1DC01-0AX0/17.0.0.0', 480, 272),     # KP400 Comfort
            ('OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0', 800, 480),     # TP700 Comfort
            ('OrderNumber:6AV2 124-0JC01-0AX0/17.0.0.0', 800, 480),     # TP900 Comfort
            ('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0', 1280, 800),    # TP1200 Comfort
            ('OrderNumber:6AV2 124-1QC02-0AX1/17.0.0.0', 1280, 800),    # KP1500 Comfort
            ('OrderNumber:6AV2 124-0UC02-0AX1/17.0.0.0', 1366, 768),    # TP1900 Comfort
            ('OrderNumber:6AV2 124-0XC02-0AX1/17.0.0.0', 1920, 1080),   # TP2200 Comfort
        ]
        for tid, w, h in cases:
            with self.subTest(tid):
                repo = self.make(tid)
                repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=w, Height=h))
                self.assertEqual([], resolution_findings(repo))
                path = repo.export('screen', 'Off', document('screen', 'Off', Number=2, Width=w + 1, Height=h))
                self.assertEqual([('warning', 'resolution.screen-size', path)], resolution_findings(repo))

    def test_portrait_swaps_width_and_height(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0//Portrait')
        repo.export('screen', 'Tall', document('screen', 'Tall', Number=1, Width=800, Height=1280))
        self.assertEqual([], resolution_findings(repo))
        path = repo.export('screen', 'Wide', document('screen', 'Wide', Number=2, Width=1280, Height=800))
        self.assertEqual([('warning', 'resolution.screen-size', path)], resolution_findings(repo))

    def test_order_number_without_spaces_and_firmware(self):
        repo = self.make('OrderNumber:6AV2124-0MC01-0AX0')
        repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=1280, Height=800))
        self.assertEqual([], resolution_findings(repo))

    def test_missing_type_identifier_is_an_error(self):
        repo = self.make(None)
        self.assertEqual([('error', 'resolution.unknown-device', 'tiabridge.json')], resolution_findings(repo))

    def test_order_number_not_in_the_table_is_an_error(self):
        repo = self.make('OrderNumber:6AV2 123-2GB03-0AX0/17.0.0.0')     # a Basic Panel
        found = [f for f in validate(repo.path) if f.rule == 'resolution.unknown-device']
        self.assertEqual(1, len(found))
        self.assertIn('6AV2123-2GB03-0AX0', found[0].message)

    def test_templates_are_cross_checked_too(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0')
        path = repo.export('template', 'T', document('template', 'T', Width=800, Height=480))
        self.assertEqual([('warning', 'resolution.screen-size', path)], resolution_findings(repo))

    def test_popups_carry_their_own_size(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0')
        repo.export('popup', 'P', document('popup', 'P', Width=400, Height=300))
        self.assertEqual([], resolution_findings(repo))

    def test_export_without_size_is_left_to_the_document_rules(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0')
        repo.export('screen', 'Minimal', document('screen', 'Minimal', Number=1, Width=None, Height=None,
                                                  export_setting='None'))
        self.assertEqual([], resolution_findings(repo))

    def test_generated_screen_of_another_size_is_an_error(self):
        repo = self.make('OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0')
        repo.generated('screen', 'Fits', document('screen', 'Fits', Number=1, Width=1280, Height=800))
        self.assertEqual([], resolution_findings(repo))
        path = repo.generated('screen', 'Old', document('screen', 'Old', Number=2, Width=800, Height=480))
        self.assertEqual([('error', 'resolution.screen-size', path)], resolution_findings(repo))


TP700 = 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0'


class SeveralHmiDevicesTest(unittest.TestCase):
    """TiaBridge writes hmiTypeIdentifier as {device: identifier} when the project has several HMI devices."""

    def make(self, type_identifier, hmi_device=None):
        repo = FixtureRepo(type_identifier=None)
        self.addCleanup(repo.cleanup)
        cfg = {'projectName': 'Fixture', 'hmiDevices': sorted(type_identifier),
               'hmiTypeIdentifier': type_identifier}
        if hmi_device is not None:
            cfg['hmiDevice'] = hmi_device
        repo.write('tiabridge.json', json.dumps(cfg, indent=2))
        return repo

    def test_the_only_entry_of_a_map_is_the_device(self):
        repo = self.make({'HMI_1': TP1200})
        repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=1280, Height=800))
        self.assertEqual([], resolution_findings(repo))
        self.assertEqual((1280, 800), (model.load(repo.path).resolution.width, model.load(repo.path).resolution.height))

    def test_hmi_device_picks_the_entry_of_a_map(self):
        repo = self.make({'HMI_1': TP1200, 'HMI_2': TP700}, hmi_device='HMI_2')
        repo.export('screen', 'Fits', document('screen', 'Fits', Number=1, Width=800, Height=480))
        self.assertEqual([], resolution_findings(repo))

    def test_several_devices_without_hmi_device_is_an_error_not_a_crash(self):
        repo = self.make({'HMI_1': TP1200, 'HMI_2': TP700})
        found = [f for f in validate(repo.path) if f.rule.startswith('resolution.')]
        self.assertEqual([('error', 'resolution.ambiguous-device', 'tiabridge.json')],
                         [(f.severity, f.rule, f.document) for f in found])
        self.assertIn('hmiDevice', found[0].message)
        self.assertIn('HMI_1', found[0].message)

    def test_hmi_device_not_in_the_map_is_an_error(self):
        repo = self.make({'HMI_1': TP1200, 'HMI_2': TP700}, hmi_device='HMI_9')
        found = [f for f in validate(repo.path) if f.rule.startswith('resolution.')]
        self.assertEqual(['resolution.ambiguous-device'], [f.rule for f in found])
        self.assertIn('HMI_9', found[0].message)

    def test_an_identifier_of_another_type_is_an_unknown_device(self):
        repo = self.make({'HMI_1': TP1200})
        repo.write('tiabridge.json', json.dumps({'hmiTypeIdentifier': 42}))
        self.assertEqual([('error', 'resolution.unknown-device', 'tiabridge.json')], resolution_findings(repo))

    def test_generator_run_takes_the_selected_device(self):
        repo = self.make({'HMI_1': TP1200, 'HMI_2': TP700}, hmi_device='HMI_2')
        with self.assertRaises(ValueError) as cm:      # no declared panel: the selected device is offered
            hmixml.begin(repo.path)
        self.assertIn('6AV2124-0GC01-0AX0', str(cm.exception))
        self.assertEqual((800, 480), (hmixml.begin(repo.path, panel='TP700').width, hmixml.size()[1]))
        hmixml.finish()
        repo = self.make({'HMI_1': TP1200, 'HMI_2': TP700})
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(repo.path)
        self.assertIn('hmiDevice', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
