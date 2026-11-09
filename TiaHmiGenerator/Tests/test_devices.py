"""Projects with several HMI devices: TiaBridge exports each device into hmi/<device>/ (screens,
templates, pop-ups, text lists, generated documents and data files). The loader, the validator, the generator, the
commands and the preview server read one device: the one given (--device, device=), else tiabridge.json hmiDevice,
else the only device folder.
"""
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.request

import hmixml
from hmipreview import model, server, validate
from Tests.fixture import TP1200, FixtureRepo, document, item, rect
from Tests.test_cli import run_cli
from Tests.test_generator import REFERENCE, panel, read_json

TP700 = 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0'


def rules(findings):
    return [(f.severity, f.rule, f.document) for f in findings]


class DeviceRepoCase(unittest.TestCase):
    """Devices HMI_A (TP1200 Comfort) and HMI_B (TP700 Comfort), each with its own screen Main."""

    def setUp(self):
        self.repo = FixtureRepo(type_identifier={'HMI_A': TP1200, 'HMI_B': TP700})
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('rA')], Number=1), device='HMI_A')
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('rB')], Number=1, Width=800,
                                                    Height=480), device='HMI_B')


class SelectionTest(DeviceRepoCase):
    def test_several_device_folders_and_no_choice_is_an_error_naming_them(self):
        found = validate(self.repo.path)
        self.assertEqual([('error', 'resolution.ambiguous-device', 'tiabridge.json')], rules(found))
        self.assertIn('HMI_A, HMI_B', found[0].message)
        self.assertIn('--device', found[0].message)
        self.assertEqual([], model.load(self.repo.path).exports)

    def test_the_device_given_is_read_with_its_own_resolution(self):
        repo = model.load(self.repo.path, device='HMI_B')
        self.assertEqual(('HMI_B', 'hmi/HMI_B', ['HMI_A', 'HMI_B']), (repo.device, repo.base, repo.devices))
        self.assertEqual(['hmi/HMI_B/screens/Main.xml'], [d.path for d in repo.exports])
        self.assertEqual((800, 480), (repo.resolution.width, repo.resolution.height))
        self.assertEqual([], validate(self.repo.path, device='HMI_B'))
        self.assertEqual([], validate(self.repo.path, device='HMI_A'))

    def test_hmiDevice_chooses_when_no_device_is_given(self):
        self.repo.config(hmiDevice='HMI_A')
        self.assertEqual('HMI_A', model.load(self.repo.path).device)
        self.assertEqual('HMI_B', model.load(self.repo.path, device='HMI_B').device)   # the option wins

    def test_the_only_device_folder_needs_no_choice(self):
        repo = FixtureRepo(type_identifier={'HMI_A': TP1200, 'HMI_B': TP700})
        self.addCleanup(repo.cleanup)
        repo.export('screen', 'Main', document('screen', 'Main', [rect('rB')], Number=1, Width=800, Height=480),
                    device='HMI_B')
        loaded = model.load(repo.path)
        self.assertEqual(('HMI_B', TP700), (loaded.device, loaded.type_identifier))
        self.assertEqual([], validate(repo.path))

    def test_a_device_without_a_folder_is_an_error(self):
        found = validate(self.repo.path, device='HMI_X')
        self.assertEqual([('error', 'resolution.ambiguous-device', 'tiabridge.json')], rules(found))
        self.assertIn("'HMI_X'", found[0].message)

    def test_a_device_name_finds_its_folder_with_the_characters_TIA_names_allow_and_files_do_not(self):
        repo = FixtureRepo(type_identifier={'Panel:Left': TP700, 'HMI_A': TP1200})
        self.addCleanup(repo.cleanup)
        repo.export('screen', 'Main', document('screen', 'Main', [rect('r')], Number=1, Width=800, Height=480),
                    device='Panel_Left')
        repo.export('screen', 'Main', document('screen', 'Main', [rect('r')], Number=1), device='HMI_A')
        for name in ('Panel:Left', 'Panel_Left'):
            with self.subTest(name):
                loaded = model.load(repo.path, device=name)
                self.assertEqual(('Panel_Left', TP700), (loaded.device, loaded.type_identifier))

    def test_a_device_missing_from_hmiTypeIdentifier_has_no_hardware(self):
        self.repo.config(hmiTypeIdentifier={'HMI_A': TP1200})
        found = validate(self.repo.path, device='HMI_B')
        self.assertEqual([('error', 'resolution.unknown-device', 'tiabridge.json')], rules(found))
        self.assertIn("HMI device 'HMI_B'", found[0].message)
        self.assertIn('hmi/HMI_B/panel.json', found[0].message)

    def test_one_device_layout_keeps_hmiDevice_and_takes_the_option_as_the_device_of_the_map(self):
        repo = FixtureRepo(type_identifier={'HMI_A': TP1200, 'HMI_B': TP700})
        self.addCleanup(repo.cleanup)
        repo.export('screen', 'Main', document('screen', 'Main', [rect('r')], Number=1, Width=800, Height=480))
        self.assertEqual(['resolution.ambiguous-device'], [f.rule for f in validate(repo.path)])
        self.assertEqual([], validate(repo.path, device='HMI_B'))
        self.assertEqual(['resolution.ambiguous-device'], [f.rule for f in validate(repo.path, device='HMI_X')])


class PerDeviceFilesTest(DeviceRepoCase):
    def test_generated_documents_and_data_files_are_the_devices_own(self):
        self.repo.generated('screen', 'Main', document('screen', 'Main', [rect('rA'), rect('rA2', left=300)],
                                                       Number=1), device='HMI_A')
        self.repo.planned([{'kind': 'faceplate'}], device='HMI_A')
        self.repo.handbuilt([{'screen': 'Main', 'kind': 'AlarmView', 'x': 0, 'y': 0, 'w': 50, 'h': 50}],
                            device='HMI_B')
        a = model.load(self.repo.path, device='HMI_A')
        self.assertEqual(['hmi/HMI_A/generated/screens/Main.xml'], [d.path for d in a.generated])
        self.assertEqual([], a.handbuilt)
        self.assertEqual(1, len(model.load(self.repo.path, device='HMI_B').handbuilt))
        self.assertEqual([('error', 'links.planned-entry', 'hmi/HMI_A/generated/planned.json')],
                         rules(validate(self.repo.path, device='HMI_A')))
        self.assertEqual([], validate(self.repo.path, device='HMI_B'))

    def test_the_declared_panel_is_the_devices_own(self):
        self.repo.panel('TP1200 Comfort', 1280, 800, device='HMI_B')
        self.assertEqual([('error', 'resolution.mismatch', 'hmi/HMI_B/panel.json')],
                         [x for x in rules(validate(self.repo.path, device='HMI_B')) if x[1] == 'resolution.mismatch'])
        self.assertEqual([], validate(self.repo.path, device='HMI_A'))

    def test_vocabulary_comes_from_every_devices_exports_and_links_from_the_devices_own(self):
        clock = item('Hmi.Screen.Clock', 'clockB', Left=10, Top=90, Width=60, Height=60)
        self.repo.export('template', 'TplB', document('template', 'TplB', [clock], Width=800, Height=480),
                         device='HMI_B')
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Clock', 'clockA', Left=10, Top=90, Width=60, Height=60)], template='TplB', Number=5),
            device='HMI_A')
        found = validate(self.repo.path, device='HMI_A')
        self.assertEqual([], [f for f in found if f.rule.startswith(('vocabulary.', 'document.'))])
        self.assertEqual([('error', 'links.unknown', 'hmi/HMI_A/generated/screens/New.xml')],
                         [x for x in rules(found) if x[1].startswith('links.')])   # template TplB is HMI_B's

    def test_screen_numbers_are_compared_within_the_device(self):
        self.assertEqual([], [f for f in validate(self.repo.path, device='HMI_A')
                              if f.rule == 'structure.duplicate-number'])


class GeneratorTest(DeviceRepoCase):
    def setUp(self):
        super().setUp()
        rel = self.repo.export('screen', 'Reference', REFERENCE, device='HMI_A')
        hmixml.set_colours({'screen': (255, 255, 255)})
        hmixml.load_templates(os.path.join(self.repo.path, *rel.split('/')))
        self.repo.panel('TP1200 Comfort', 1280, 800, device='HMI_A')

    def test_begin_without_a_device_refuses_naming_the_devices(self):
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(self.repo.path)
        self.assertIn('HMI_A, HMI_B', str(cm.exception))

    def test_a_run_writes_into_the_devices_folder(self):
        hmixml.begin(self.repo.path, device='HMI_A')
        hmixml.plan('screen', '9200 - Later', 'next run')
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - Staging', 9101, [panel('rectA')]), folder='zz')
        hmixml.finish()
        self.assertEqual('hmi/HMI_A/generated/screens/zz/9101 - Staging.xml', rel)
        self.assertTrue(os.path.isfile(os.path.join(self.repo.path, *rel.split('/'))))
        self.assertEqual([{'kind': 'screen', 'name': '9200 - Later', 'note': 'next run'}],
                         read_json(self.repo, 'hmi/HMI_A/generated/planned.json'))
        self.assertEqual([rel], list(read_json(self.repo, 'hmi/HMI_A/generated/generated.json')))
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, 'hmi', 'generated')))
        self.assertEqual(os.path.join(self.repo.path, 'hmi', 'HMI_A', 'generated', 'screens'),
                         hmixml.generated_dirs(self.repo.path, device='HMI_A')['screen'])

    def test_a_run_declares_the_panel_of_its_device(self):
        hmixml.begin(self.repo.path, panel='TP700', device='HMI_B')
        hmixml.add('screen', hmixml.screen_doc('9101 - B', 9101, [panel('rectB')]))
        hmixml.finish()
        self.assertEqual(800, read_json(self.repo, 'hmi/HMI_B/panel.json')['width'])

    def test_one_device_layout_validates_with_the_device_given_to_begin(self):
        repo = FixtureRepo(type_identifier={'HMI_A': TP1200, 'HMI_B': TP700})
        self.addCleanup(repo.cleanup)
        rel = repo.export('screen', 'Reference', REFERENCE)
        hmixml.load_templates(os.path.join(repo.path, *rel.split('/')))
        hmixml.begin(repo.path, panel='TP700', device='HMI_B')
        rel = hmixml.add('screen', hmixml.screen_doc('9101 - B', 9101, [panel('rectB')]))
        hmixml.finish()
        self.assertEqual('hmi/generated/screens/9101 - B.xml', rel)
        self.assertTrue(os.path.isfile(os.path.join(repo.path, *rel.split('/'))))

    def test_the_panel_must_fit_the_devices_hardware(self):
        with self.assertRaises(ValueError) as cm:
            hmixml.begin(self.repo.path, panel='TP1200', device='HMI_B')
        self.assertIn('resolution.mismatch', str(cm.exception))


class CommandTest(DeviceRepoCase):
    def test_validate_takes_the_device(self):
        r = run_cli('validate', self.repo.path)
        self.assertEqual(1, r.returncode)
        self.assertIn('resolution.ambiguous-device', r.stdout)
        r = run_cli('validate', self.repo.path, '--device', 'HMI_B', '--json')
        self.assertEqual((0, []), (r.returncode, json.loads(r.stdout)), r.stderr)

    def test_the_other_commands_refuse_without_a_device(self):
        # serve shows every device: it refuses only a device that is not one
        for args in (('serve', '--port', '0', '--device', 'HMI_C'), ('diff', 'Main'), ('png', 'Main', 'x.png'),
                     ('panel', 'TP700')):
            with self.subTest(args[0]):
                r = run_cli(args[0], self.repo.path, *args[1:])
                self.assertEqual(2, r.returncode, r.stdout + r.stderr)
                self.assertIn('HMI_A, HMI_B', r.stderr)

    def test_panel_writes_the_devices_panel_file(self):
        r = run_cli('panel', self.repo.path, 'TP700', '--device', 'HMI_B')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('hmi/HMI_B/panel.json', r.stdout)
        self.assertEqual(480, read_json(self.repo, 'hmi/HMI_B/panel.json')['height'])
        self.assertEqual(1, run_cli('panel', self.repo.path, 'TP700', '--device', 'HMI_A').returncode)  # TP1200


class ServerTest(DeviceRepoCase):
    def test_the_server_shows_its_device_and_lists_the_others(self):
        httpd = server.make_server(self.repo.path, host='127.0.0.1', port=0, device='HMI_B')
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = 'http://127.0.0.1:%d/api/screens' % httpd.server_address[1]
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        self.assertEqual(('HMI_B', ['HMI_A', 'HMI_B']), (data['hmiDevice'], data['devices']))
        self.assertEqual(['hmi/HMI_B/screens/Main.xml'], [s['path'] for s in data['screens']])
        self.assertEqual(800, data['device']['width'])


class AllDevicesServerTest(DeviceRepoCase):
    """One server shows every device; ?device= picks the device an endpoint answers for."""

    def serve(self, **kw):
        httpd = server.make_server(self.repo.path, host='127.0.0.1', port=0, **kw)
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.base = 'http://127.0.0.1:%d' % httpd.server_address[1]

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return json.loads(r.read().decode('utf-8'))

    def test_without_a_choice_it_opens_the_first_device(self):
        self.serve()
        data = self.get('/api/screens')
        self.assertEqual(('HMI_A', ['hmi/HMI_A/screens/Main.xml']), (data['hmiDevice'], [s['path'] for s in data['screens']]))
        self.assertEqual([], [f for f in self.get('/api/findings') if f['rule'] == 'resolution.ambiguous-device'])

    def test_device_parameter(self):
        self.serve(device='HMI_A')
        data = self.get('/api/screens?device=HMI_B')
        self.assertEqual(('HMI_B', 480), (data['hmiDevice'], data['device']['height']))
        doc = self.get('/api/document?device=HMI_B&kind=screen&name=Main')
        self.assertEqual('hmi/HMI_B/screens/Main.xml', doc['path'])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get('/api/screens?device=HMI_C')
        self.assertEqual(404, cm.exception.code)
        cm.exception.close()

    def test_the_tree_holds_every_device(self):
        self.serve(device='HMI_B')
        data = self.get('/api/tree')
        self.assertEqual((['HMI_A', 'HMI_B'], 'HMI_B'), (data['devices'], data['device']))
        self.assertEqual(['HMI_A:screen:Main', 'HMI_B:screen:Main'], re.findall(r'data-key="([^"]+)"', data['rail']))
        self.assertEqual(['HMI_A', 'Screens', 'HMI_B', 'Screens'],
                         re.findall(r'<span class="fn"><span class="nm">([^<]+)</span>', data['rail']))


class FolderNameTest(unittest.TestCase):
    """The same mapping as ConvertTo-SafeFileName in the bridge's Repo.ps1, tested there name by name."""

    def test_the_cases_of_the_bridge(self):
        for name, folder in (('Plain', 'Plain'), ('a\\b/c:d*e?f"g<h>i|j', 'a_b_c_d_e_f_g_h_i_j'), ('a\tb', 'a_b'),
                             ('Line.', 'Line_'), ('Line ', 'Line_'), ('Line. .', 'Line_'), ('...', '_'), ('a.b c', 'a.b c'),
                             ('F\u00a0', 'F_'), ('F\u0085', 'F_'),
                             ('NUL', 'NUL_'), ('nul', 'nul_'), ('COM1', 'COM1_'), ('LPT9', 'LPT9_'), ('COM¹', 'COM¹_'),
                             ('CONIN$', 'CONIN$_'), ('NUL.txt', 'NUL_.txt'), ('CONSOLE', 'CONSOLE'), ('COM10', 'COM10'),
                             ('', '_')):
            self.assertEqual(folder, model.folder_name(name), name)


if __name__ == '__main__':
    unittest.main()
