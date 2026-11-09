"""The preview server over HTTP, started on a fixture repo."""
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from hmipreview import catalogue, model, server
from Tests.fixture import FixtureRepo, document, item, rect

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # TiaHmiGenerator


class ServerCase(unittest.TestCase):
    start_screen = None

    def setUp(self):
        self.repo = FixtureRepo(start_screen=self.start_screen)
        self.addCleanup(self.repo.cleanup)

    def serve(self, **kw):
        httpd = server.make_server(self.repo.path, host='127.0.0.1', port=0, **kw)
        t = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
        t.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
        self.addCleanup(stop)
        self.base = 'http://127.0.0.1:%d' % httpd.server_address[1]
        return httpd

    def get(self, path, **params):
        url = self.base + path + ('?' + urllib.parse.urlencode(params) if params else '')
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read()

    def get_json(self, path, **params):
        status, ctype, body = self.get(path, **params)
        self.assertEqual(200, status)
        self.assertIn('application/json', ctype)
        return json.loads(body.decode('utf-8'))

    def get_error(self, path, **params):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(path, **params)
        cm.exception.close()
        return cm.exception.code


class ScreenListTest(ServerCase):
    def test_lists_exported_and_generated_screens_merged_with_origin_and_folder(self):
        self.repo.export('screen', 'Overview', document('screen', 'Overview', Number=10), folder='Main')
        self.repo.export('screen', 'Silo', document('screen', 'Silo', Number=20), folder='Stations/G05')
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=20),
                            folder='Stations/G05')
        self.repo.generated('screen', 'New', document('screen', 'New', Number=30))
        self.repo.export('template', 'Tpl', document('template', 'Tpl'))
        self.repo.export('popup', 'Pop', document('popup', 'Pop', Width=300, Height=200))
        self.serve()

        data = self.get_json('/api/screens')

        self.assertEqual(
            [('screen', 'New', '', 'generated', 30, 'hmi/generated/screens/New.xml'),
             ('screen', 'Overview', 'Main', 'tia', 10, 'hmi/screens/Main/Overview.xml'),
             ('screen', 'Silo', 'Stations/G05', 'generated', 20, 'hmi/generated/screens/Stations/G05/Silo.xml')],
            sorted((d['kind'], d['name'], d['folder'], d['origin'], d['number'], d['path'])
                   for d in data['screens']))
        self.assertEqual([('Tpl', 'tia')], [(d['name'], d['origin']) for d in data['templates']])
        self.assertEqual([('Pop', 'tia')], [(d['name'], d['origin']) for d in data['popups']])
        silo = next(d for d in data['screens'] if d['name'] == 'Silo')
        self.assertEqual('hmi/screens/Stations/G05/Silo.xml', silo['replaces'])

    def test_device_resolution_comes_from_the_type_identifier(self):
        self.serve()
        self.assertEqual({'width': 1280, 'height': 800, 'portrait': False, 'orderNumber': '6AV2124-0MC01-0AX0',
                          'panel': 'TP1200 Comfort', 'declared': False, 'hardware': None},
                         self.get_json('/api/screens')['device'])

    def test_device_is_the_declared_panel(self):
        self.repo.panel()
        self.serve()
        self.assertEqual({'width': 1280, 'height': 800, 'portrait': False, 'orderNumber': None,
                          'panel': 'TP1200 Comfort', 'declared': True, 'hardware': None},
                         self.get_json('/api/screens')['device'])

    def test_device_reports_the_hardware_when_it_differs_from_the_declared_panel(self):
        self.repo.panel('TP700 Comfort', 800, 480)
        self.serve()
        device = self.get_json('/api/screens')['device']
        self.assertEqual(('TP700 Comfort', 800, 480, True), (device['panel'], device['width'], device['height'],
                                                             device['declared']))
        self.assertEqual({'width': 1280, 'height': 800, 'portrait': False, 'orderNumber': '6AV2124-0MC01-0AX0',
                          'panel': 'TP1200 Comfort'}, device['hardware'])

    def test_unknown_device_has_no_resolution(self):
        self.repo = FixtureRepo(type_identifier=None)
        self.addCleanup(self.repo.cleanup)
        self.serve()
        self.assertIsNone(self.get_json('/api/screens')['device'])

    def test_start_screen_without_config_is_the_first_by_number(self):
        self.repo.export('screen', 'B', document('screen', 'B', Number=5))
        self.repo.generated('screen', 'A', document('screen', 'A', Number=7))
        self.repo.export('screen', 'C', document('screen', 'C', Number=3))
        self.serve()
        self.assertEqual('C', self.get_json('/api/screens')['startScreen'])


GRAPHIC = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Hmi.Globalization.MultiLingualGraphic ID="0"><AttributeList>'
           '<DefaultImageStream external="path">%s files\\DefaultImageStream.%s</DefaultImageStream><Name>%s</Name>'
           '</AttributeList></Hmi.Globalization.MultiLingualGraphic></Document>\n')


class PictureTest(ServerCase):
    def setUp(self):
        super().setUp()
        for name, ext, data in (('Logo', 'png', b'\x89PNG first'), ('Vector', 'emf', b'emf')):
            self.repo.write('project/graphics/%s.xml' % name, GRAPHIC % (name, ext, name))
            full = os.path.join(self.repo.path, 'project', 'graphics', name + ' files', 'DefaultImageStream.' + ext)
            os.makedirs(os.path.dirname(full))
            with open(full, 'wb') as f:
                f.write(data)
        self.serve()

    def test_lists_the_images_a_browser_draws_and_serves_them(self):
        urls = self.get_json('/api/pictures')

        self.assertEqual(['Logo'], list(urls))
        status, ctype, body = self.get(urls['Logo'])
        self.assertEqual((200, 'image/png', b'\x89PNG first'), (status, ctype, body))

    def test_a_changed_image_gets_another_url(self):
        before = self.get_json('/api/pictures')['Logo']
        full = os.path.join(self.repo.path, 'project', 'graphics', 'Logo files', 'DefaultImageStream.png')
        with open(full, 'wb') as f:
            f.write(b'\x89PNG second, longer')

        after = self.get_json('/api/pictures')['Logo']

        self.assertNotEqual(before, after)
        self.assertEqual(b'\x89PNG second, longer', self.get(after)[2])

    def test_pictures_hash_no_file(self):
        with mock.patch('hashlib.file_digest', side_effect=AssertionError('hashed')):
            urls = self.get_json('/api/pictures')

            self.assertEqual(200, self.get(urls['Logo'])[0])

    def test_a_graphic_folder_gone_during_an_export_leaves_the_rest_listed(self):
        real = os.scandir

        def scandir(path):
            if os.path.basename(path) == 'Vector files':
                raise FileNotFoundError(2, 'gone', path)
            return real(path)

        with mock.patch('os.scandir', scandir):
            self.assertEqual(['Logo'], list(self.get_json('/api/pictures')))

    def test_a_name_that_is_no_listed_picture_is_not_found(self):
        self.assertEqual(404, self.get_error('/api/picture', name='Vector'))
        self.assertEqual(404, self.get_error('/api/picture', name='..\\..\\tiabridge'))

    def test_a_repo_without_graphics_has_no_pictures(self):
        shutil.rmtree(os.path.join(self.repo.path, 'project'))
        self.assertEqual({}, self.get_json('/api/pictures'))


class DocumentTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [rect('S-Panel')], Number=1))
        self.repo.export('template', 'Tpl', document('template', 'Tpl'))

    def test_generated_document_with_its_findings_and_links(self):
        xml = document('screen', 'New', [
            rect('r1'),
            item('Hmi.Screen.Invented', 'gauge1', Left=1, Top=90, Width=2, Height=2)], template='Tpl', Number=2)
        path = self.repo.generated('screen', 'New', xml, folder='G05')
        self.serve()

        data = self.get_json('/api/document', kind='screen', name='New')

        self.assertEqual(('screen', 'New', 'G05', 'generated', path),
                         (data['kind'], data['name'], data['folder'], data['origin'], data['path']))
        self.assertTrue(data['xml'].startswith('<?xml'))
        self.assertIn('<ObjectName>gauge1</ObjectName>', data['xml'])
        self.assertEqual([('error', path, 'gauge1', 'vocabulary.element-type')],
                         [(f['severity'], f['document'], f['object'], f['rule']) for f in data['findings']])
        self.assertEqual([{'object': None, 'kind': 'template', 'name': 'Tpl', 'state': 'exists', 'note': ''}],
                         data['links'])

    def test_generated_document_replaces_the_export_unless_the_export_is_asked_for(self):
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [rect('old')], Number=5))
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('new')], Number=5))
        self.serve()

        self.assertIn('<ObjectName>new</ObjectName>', self.get_json('/api/document', kind='screen', name='Silo')['xml'])
        exp = self.get_json('/api/document', kind='screen', name='Silo', origin='tia')
        self.assertEqual('tia', exp['origin'])
        self.assertIn('<ObjectName>old</ObjectName>', exp['xml'])

    def test_planned_link_state_is_reported(self):
        self.repo.planned([{'kind': 'template', 'name': 'NewTpl', 'note': 'built by hand'}])
        self.repo.generated('screen', 'New', document('screen', 'New', template='NewTpl', Number=2))
        self.serve()
        links = self.get_json('/api/document', kind='screen', name='New')['links']
        self.assertEqual([('template', 'NewTpl', 'planned', 'built by hand')],
                         [(l['kind'], l['name'], l['state'], l['note']) for l in links])

    def test_presets_and_generation_time_from_the_generator_sidecar(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1'), rect('r2')], Number=2))
        self.repo.write('hmi/generated/generated.json', json.dumps(
            {path: {'generated': '2026-10-06T10:00:00+02:00', 'presets': {
                'r1': 'S-Panel',
                'r2': {'preset': 'S-Gone', 'source': 'rectGone', 'document': 'hmi/screens/Gone.xml'}}}}))
        self.repo.planned([{'kind': 'style', 'name': 'S-Gone', 'note': 'new preset'}])
        self.serve()

        data = self.get_json('/api/document', kind='screen', name='New')

        self.assertEqual({'r1': {'preset': 'S-Panel', 'source': None, 'document': None},
                          'r2': {'preset': 'S-Gone', 'source': 'rectGone', 'document': 'hmi/screens/Gone.xml'}},
                         data['presets'])
        self.assertEqual('2026-10-06T10:00:00+02:00', data['generated'])
        self.assertIn({'object': 'r2', 'kind': 'style', 'name': 'S-Gone', 'state': 'planned', 'note': 'new preset'},
                      data['links'])
        self.assertEqual([{'device': '', 'kind': 'screen', 'name': 'New', 'object': 'r2'}],
                         self.get_json('/api/findingspage')['planned'][0]['usedBy'])

    def test_export_has_no_presets(self):
        self.serve()
        data = self.get_json('/api/document', kind='screen', name='Reference')
        self.assertEqual(({}, None), (data['presets'], data['generated']))

    def test_missing_document_is_not_found(self):
        self.serve()
        self.assertEqual(404, self.get_error('/api/document', kind='screen', name='Nope'))

    def test_kind_and_name_are_required(self):
        self.serve()
        self.assertEqual(400, self.get_error('/api/document', kind='screen'))


class RepoDataTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [rect('S-Panel')], Number=1))

    def test_findings_of_the_whole_repo(self):
        a = self.repo.generated('screen', 'A', document('screen', 'A', [
            item('Hmi.Screen.Invented', 'g1', Left=1, Top=90, Width=2, Height=2)], Number=2))
        b = self.repo.generated('screen', 'B', document('screen', 'B', template='Missing', Number=3))
        self.serve()
        self.assertEqual([(a, 'g1', 'vocabulary.element-type'), (b, None, 'links.unknown')],
                         [(f['document'], f['object'], f['rule']) for f in self.get_json('/api/findings')])

    def test_open_planned_items_with_the_documents_using_them(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl'))
        self.repo.planned([{'kind': 'template', 'name': 'NewTpl', 'note': 'build in TIA'},
                           {'kind': 'template', 'name': 'Tpl', 'note': 'exists by now'},
                           {'kind': 'textlist', 'name': 'tlUnused'}])
        self.repo.generated('screen', 'New', document('screen', 'New', template='NewTpl', Number=2))
        self.serve()
        self.assertEqual([{'device': '', 'kind': 'template', 'name': 'NewTpl', 'note': 'build in TIA',
                           'usedBy': [{'device': '', 'kind': 'screen', 'name': 'New', 'object': None}]},
                          {'device': '', 'kind': 'textlist', 'name': 'tlUnused', 'note': '', 'usedBy': []}],
                         self.get_json('/api/findingspage')['planned'])

    def test_hand_built_objects_per_screen(self):
        alarm = {'screen': 'Alarms', 'kind': 'alarm view', 'x': 0, 'y': 80, 'w': 1280, 'h': 600}
        diag = {'screen': 'Diag', 'kind': 'diagnostics view', 'x': 0, 'y': 80, 'w': 1280, 'h': 600}
        self.repo.handbuilt([alarm, diag])
        self.serve()
        self.assertEqual([alarm], self.get_json('/api/handbuilt', screen='Alarms'))
        self.assertEqual([alarm, diag], self.get_json('/api/handbuilt'))
        self.assertEqual([], self.get_json('/api/handbuilt', screen='Other'))

    def test_type_names_are_the_toolbox_names_of_the_catalogue(self):
        self.serve()
        names = self.get_json('/api/typenames')
        self.assertEqual('I/O field', names['Hmi.Screen.IOField'])
        self.assertEqual('Button', names['Hmi.Screen.Button'])
        self.assertEqual(len([t for t in catalogue.toolbox() if t.get('element')]), len(names))   # through Openness


class RepoCacheTest(ServerCase):
    """The server reads and validates the repo once per state on disk, not once per request (project B 2026-10-06:
    a screen switch took 2 s, every /api/document loaded and validated all 71 screens twice)."""

    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [rect('S-Panel')], Number=1))
        self.repo.export('template', 'Tpl', document('template', 'Tpl'))

    def test_requests_on_an_unchanged_repo_read_it_once(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], template='Tpl', Number=2))
        self.serve()
        with mock.patch.object(model, 'load', wraps=model.load) as load:
            self.get_json('/api/screens')
            self.get_json('/api/document', kind='screen', name='New')
            self.get_json('/api/document', kind='template', name='Tpl')
            self.get_json('/api/findings')
            self.get_json('/api/findingspage')
            self.get_json('/api/handbuilt')
        self.assertEqual(1, load.call_count)

    def test_a_changed_file_shows_in_the_next_answer(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2))
        self.serve()
        self.assertEqual([], self.get_json('/api/document', kind='screen', name='New')['findings'])

        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Invented', 'gauge1', Left=1, Top=90, Width=2, Height=2)], Number=2))

        data = self.get_json('/api/document', kind='screen', name='New')
        self.assertIn('<ObjectName>gauge1</ObjectName>', data['xml'])
        self.assertEqual(['vocabulary.element-type'], [f['rule'] for f in data['findings']])
        self.assertEqual(['vocabulary.element-type'], [f['rule'] for f in self.get_json('/api/findings')])

    def test_an_added_and_a_removed_file_show(self):
        self.serve()
        self.assertEqual(['Reference'], [s['name'] for s in self.get_json('/api/screens')['screens']])
        path = self.repo.generated('screen', 'New', document('screen', 'New', Number=2))
        self.assertEqual(['New', 'Reference'], sorted(s['name'] for s in self.get_json('/api/screens')['screens']))
        os.remove(os.path.join(self.repo.path, *path.split('/')))
        self.assertEqual(['Reference'], [s['name'] for s in self.get_json('/api/screens')['screens']])

    def test_a_changed_config_file_shows(self):
        self.repo.export('screen', 'B', document('screen', 'B', Number=5))
        self.serve()
        self.assertEqual('Reference', self.get_json('/api/screens')['startScreen'])
        self.repo.write('tiabridge.json', json.dumps({'startScreen': 'B'}))
        self.assertEqual('B', self.get_json('/api/screens')['startScreen'])

    def test_a_new_commit_shows_in_the_staleness_findings(self):
        # Staleness compares with the commit time of the export: a commit changes no file under hmi/.
        self.repo.export('screen', 'S1', document('screen', 'S1', [rect('r1')], Number=10))
        path = self.repo.generated('screen', 'S1', document('screen', 'S1', [rect('r1', left=20)], Number=10))
        self.repo.write('hmi/generated/generated.json', json.dumps({path: {'generated': '2026-10-06T10:00:00+00:00'}}))
        self.serve()
        self.assertEqual([], [f for f in self.get_json('/api/findings') if f['rule'].startswith('staleness.')])

        self.repo.commit('export', date='2026-10-06T12:00:00+00:00')

        self.assertEqual([('warning', 'staleness.export-newer', path)],
                         [(f['severity'], f['rule'], f['document']) for f in self.get_json('/api/findings')
                          if f['rule'].startswith('staleness.')])


class ChangeStreamTest(ServerCase):
    def open_stream(self):
        r = urllib.request.urlopen(self.base + '/api/events', timeout=10)
        self.addCleanup(r.close)
        self.assertIn('text/event-stream', r.headers.get('Content-Type'))
        self.assertEqual(('ready', {}), self.next_event(r))
        return r

    @staticmethod
    def next_event(r):
        """(event, data) of the next event; comment lines (heartbeats) are skipped."""
        event, data = 'message', []
        while True:
            line = r.readline().decode('utf-8').rstrip('\r\n')
            if line == '':
                if data:
                    return event, json.loads('\n'.join(data))
                continue
            if line.startswith(':'):
                continue
            k, _, v = line.partition(':')
            v = v[1:] if v.startswith(' ') else v
            if k == 'event':
                event = v
            elif k == 'data':
                data.append(v)

    def test_one_event_per_changed_file_under_hmi(self):
        old = self.repo.generated('screen', 'Old', document('screen', 'Old', Number=1))
        self.serve(poll_interval=0.05)
        r = self.open_stream()

        self.repo.write('tiabridge.json', '{}')                      # outside what is drawn: no event
        new = self.repo.generated('screen', 'New', document('screen', 'New', Number=2))
        self.assertEqual(('change', {'path': new, 'change': 'added'}), self.next_event(r))

        self.repo.touch(old, time.time() + 5)
        self.assertEqual(('change', {'path': old, 'change': 'modified'}), self.next_event(r))

        os.remove(os.path.join(self.repo.path, *new.split('/')))
        self.assertEqual(('change', {'path': new, 'change': 'removed'}), self.next_event(r))


    def test_a_changed_project_graphic_is_an_event_too(self):
        self.repo.write('project/graphics/Logo.xml', '<Document />')
        self.serve(poll_interval=0.05)
        r = self.open_stream()

        self.repo.write('project/graphics/Logo files/DefaultImageStream.png', 'first')
        self.assertEqual(('change', {'path': 'project/graphics/Logo files/DefaultImageStream.png', 'change': 'added'}),
                         self.next_event(r))


class CatalogueTest(ServerCase):
    def test_answers_a_type_with_tia_names_groups_and_events(self):
        self.serve()

        t = self.get_json('/api/catalogue', element='Hmi.Screen.Button')

        self.assertEqual(('Hmi.Screen.Button', 'Button'), (t['element'], t['toolbox']['name']))
        back = next(a for a in t['attributes'] if a['name'] == 'BackColor')
        self.assertEqual(('Background color', 'Appearance', 'colour'), (back['display'], back['group'], back['kind']))
        self.assertIn('greyedWhen', back)
        self.assertIn('Click', t['events'])
        groups = list(dict.fromkeys(a['group'] for a in t['attributes'] if a['group']))
        self.assertEqual(['Appearance', 'Design'], groups[:2])          # TIA's order

    def test_unknown_element_is_not_found(self):
        self.serve()
        self.assertEqual(404, self.get_error('/api/catalogue', element='Hmi.Screen.Invented'))
        self.assertEqual(400, self.get_error('/api/catalogue'))


class StaticAppTest(ServerCase):
    def test_root_serves_the_browser_app(self):
        self.serve()
        status, ctype, body = self.get('/')
        self.assertEqual(200, status)
        self.assertIn('text/html', ctype)
        self.assertIn(b'src="app.js"', body)
        status, ctype, body = self.get('/app.js')
        self.assertEqual(200, status)
        self.assertIn('javascript', ctype)
        self.assertIn(b'/api/screens', body)

    def test_unknown_paths_are_not_found(self):
        self.serve()
        self.assertEqual(404, self.get_error('/nope.js'))
        self.assertEqual(404, self.get_error('/api/nope'))
        self.assertEqual(404, self.get_error('/../server.py'))
        self.assertEqual(404, self.get_error('/%2e%2e/server.py'))

    def test_backslash_and_drive_paths_do_not_escape_the_app_folder(self):
        # Windows: a backslash is a separator too, and a drive letter makes the path absolute.
        self.serve()
        self.assertEqual(404, self.get_error('/x%5C..%5C..%5Cserver.py'))
        self.assertEqual(404, self.get_error('/%5C..%5Cserver.py'))
        outside = os.path.abspath(server.__file__).replace(os.sep, '/')
        self.assertEqual(404, self.get_error('/' + urllib.parse.quote(outside)))
        self.assertEqual(404, self.get_error('/' + urllib.parse.quote(os.path.abspath(server.__file__))))


def remove_log(printed):
    """Removes the log that --detach names in what it printed. Windows holds the file for a moment after the kill; longer raises."""
    path = re.search(r'log: (.+)', printed).group(1).strip()
    deadline = time.monotonic() + 10
    while True:
        try:
            return os.remove(path)
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def stop_serving(printed):
    """Ends the server --detach printed the pid of, while it still serves: the job it was in may have ended it, and
    Windows soon gives a pid to another process."""
    if not refuses(int(re.search(r':(\d+)/', printed).group(1)), seconds=2):
        os.kill(int(re.search(r'pid (\d+)', printed).group(1)), signal.SIGTERM)


def refuses(port, seconds=10):
    """True once nothing listens on 127.0.0.1:port within the seconds; a killed process lets go of it in a moment."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
        except OSError:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)


KILL_ON_JOB_CLOSE, BREAKAWAY_OK = 0x2000, 0x800

IN_A_JOB = r'''
import ctypes, subprocess, sys
from ctypes import wintypes as w
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateJobObjectW.restype = w.HANDLE
k.GetCurrentProcess.restype = w.HANDLE
k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
class Basic(ctypes.Structure):
    _fields_ = [('user', ctypes.c_int64), ('job_user', ctypes.c_int64), ('flags', w.DWORD), ('min_ws', ctypes.c_size_t),
                ('max_ws', ctypes.c_size_t), ('processes', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD),
                ('scheduling', w.DWORD)]
class Extended(ctypes.Structure):
    _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('memory', ctypes.c_size_t * 4)]
job = k.CreateJobObjectW(None, None)
EXTENDED_LIMIT_INFORMATION = 9
info = Extended()
info.basic.flags = int(sys.argv[1])
if not (job and k.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info))
        and k.AssignProcessToJobObject(job, k.GetCurrentProcess())):
    sys.exit('job: error %d' % ctypes.get_last_error())
r = subprocess.run(sys.argv[2:], capture_output=True, timeout=60)
sys.stdout.buffer.write(r.stdout)
sys.stderr.buffer.write(r.stderr)
sys.exit(r.returncode)
'''


def run_in_job(flags, argv):
    """Runs argv in a new job object with these limit flags, from a helper that ends, and the job with it, when argv returns."""
    return subprocess.run([sys.executable, '-X', 'utf8', '-c', IN_A_JOB, str(flags)] + argv, cwd=PACKAGE_ROOT,
                          capture_output=True, encoding='utf-8', timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)


class ServeCommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Main', document('screen', 'Main', Number=1))

    def check_url(self, url):
        self.assertRegex(url, r'^http://127\.0\.0\.1:\d+/$')
        with urllib.request.urlopen(url + 'api/screens', timeout=10) as r:
            self.assertEqual(['Main'], [s['name'] for s in json.loads(r.read())['screens']])

    def test_serve_prints_its_url_and_answers(self):
        p = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hmipreview', 'serve', self.repo.path, '--host',
                              '127.0.0.1', '--port', '0'], cwd=PACKAGE_ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, encoding='utf-8')

        def stop():
            p.kill()
            p.wait()
            p.stdout.close()
        self.addCleanup(stop)
        self.check_url(p.stdout.readline().strip())

    def test_detach_prints_url_and_pid_and_leaves_the_server_running(self):
        r = subprocess.run(self.serve_detached(), cwd=PACKAGE_ROOT, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, r.returncode, r.stderr)
        lines = r.stdout.splitlines()
        pid = int(re.search(r'pid (\d+)', r.stdout).group(1))
        self.addCleanup(remove_log, r.stdout)
        self.addCleanup(os.kill, pid, signal.SIGTERM)
        self.check_url(lines[0].strip())

    def test_detach_with_a_non_ascii_repo_path(self):
        """URL and pid reach the user whether the parent runs with -X utf8 (as documented) or not, for a name with a
        character cp1252 has and a name with one it has not."""
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8')}
        for name in ('Pr\u00fcfstand', '\u0141\u00f3d\u017a'):
            renamed = os.path.join(os.path.dirname(self.repo.path), name + ' ' + os.path.basename(self.repo.path))
            os.rename(self.repo.path, renamed)
            self.repo.path = renamed
            for flags in ([], ['-X', 'utf8']):
                with self.subTest(name=name, flags=flags):
                    r = subprocess.run([sys.executable] + flags + ['-m', 'hmipreview', 'serve', renamed, '--host',
                                                                   '127.0.0.1', '--port', '0', '--detach'],
                                       cwd=PACKAGE_ROOT, capture_output=True, timeout=30, env=env)
                    self.assertEqual(0, r.returncode, r.stderr.decode('utf-8', 'replace'))
                    text = r.stdout.decode('utf-8')
                    pid = int(re.search(r'pid (\d+)', text).group(1))
                    self.assertIn(name, text)
                    self.check_url(text.splitlines()[0].strip())
                    os.kill(pid, signal.SIGTERM)   # before the next rename: the server reads the repo
                    remove_log(text)

    def test_serve_listens_on_this_machine_only_by_default(self):
        p = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hmipreview', 'serve', self.repo.path, '--port', '0'],
                             cwd=PACKAGE_ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8')

        def stop():
            p.kill()
            p.wait()
            p.stdout.close()
        self.addCleanup(stop)
        self.check_url(p.stdout.readline().strip())
        self.assertFalse(p.stdout.readline().startswith('also '))     # no LAN addresses

    @unittest.skipUnless(os.name == 'nt', 'a job object is Windows')
    def test_detached_server_outlives_the_job_of_the_command_that_started_it(self):
        """As an agent's command runner: the command runs in a job that ends its processes when the command ends."""
        r = run_in_job(KILL_ON_JOB_CLOSE | BREAKAWAY_OK, self.serve_detached())
        self.assertEqual(0, r.returncode, r.stderr)
        pid = int(re.search(r'pid (\d+)', r.stdout).group(1))
        self.addCleanup(remove_log, r.stdout)
        self.addCleanup(os.kill, pid, signal.SIGTERM)
        time.sleep(1)     # the job is closed, as the helper has ended; ending its processes takes a moment
        self.check_url(r.stdout.splitlines()[0].strip())
        self.assertNotIn(server.IN_JOB_NOTE, r.stdout)

    @unittest.skipUnless(os.name == 'nt', 'a job object is Windows')
    def test_a_job_that_ends_its_processes_and_lets_none_leave_still_gets_the_url_and_a_note(self):
        """Through the venv's python.exe, a launcher in a job of its own, as an agent runs it, where the flag raises
        nothing and the server stays in the outer job; and through the interpreter itself, right in the job, where the
        flag is refused."""
        for python in (sys.executable, sys._base_executable):
            with self.subTest(python=python):
                r = run_in_job(KILL_ON_JOB_CLOSE, self.serve_detached(python))
                self.assertEqual(0, r.returncode, r.stderr)
                stop_serving(r.stdout)
                remove_log(r.stdout)
                self.assertRegex(r.stdout.splitlines()[0], r'^http://127\.0\.0\.1:\d+/$')
                self.assertIn(server.IN_JOB_NOTE, r.stdout)

    @unittest.skipUnless(os.name == 'nt', 'a job object is Windows')
    def test_a_job_that_keeps_its_processes_but_does_not_end_them_gives_no_note(self):
        """As some agents' command shells do: a job that lets no process leave and does not end them on close; the
        server outlives it."""
        for python in (sys.executable, sys._base_executable):
            with self.subTest(python=python):
                r = run_in_job(0, self.serve_detached(python))
                self.assertEqual(0, r.returncode, r.stderr)
                stop_serving(r.stdout)
                remove_log(r.stdout)
                self.assertNotIn(server.IN_JOB_NOTE, r.stdout)

    def test_a_server_that_does_not_answer_gives_no_url_and_is_stopped(self):
        out = io.StringIO()
        with mock.patch.object(server, 'answers', return_value=False):
            code = server.detach(self.serve_args(), out=out)
        self.assertEqual(1, code)
        printed = out.getvalue()
        remove_log(printed)
        self.assertRegex(printed, r'preview server does not answer at http://127\.0\.0\.1:\d+/, log: ')
        self.assertEqual([], [line for line in printed.splitlines() if line.startswith('http')])
        self.assertNotIn('pid ', printed)
        self.assertTrue(refuses(int(re.search(r':(\d+)/', printed).group(1))))

    @unittest.skipUnless(os.name == 'nt', 'a console window is Windows')
    def test_detach_opens_no_console_window(self):
        """Measured: the venv's python.exe, a launcher, started DETACHED_PROCESS hands a real, visible console window to
        the interpreter it starts. CREATE_NO_WINDOW gives every process a console no one sees."""
        out = io.StringIO()
        with mock.patch.object(subprocess, 'Popen', side_effect=subprocess.Popen) as started:
            code = server.detach(self.serve_args(), out=out)
        self.assertEqual(0, code, out.getvalue())
        stop_serving(out.getvalue())
        remove_log(out.getvalue())
        self.assertTrue(started.call_args_list)
        for call in started.call_args_list:
            flags = call.kwargs['creationflags']
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW, call)
            self.assertFalse(flags & subprocess.DETACHED_PROCESS, call)

    def serve_args(self):
        """What follows python -m hmipreview: serve on the fixture repo, on a free port of this machine."""
        return ['serve', self.repo.path, '--host', '127.0.0.1', '--port', '0']

    def serve_detached(self, python=sys.executable):
        return [python, '-X', 'utf8', '-m', 'hmipreview'] + self.serve_args() + ['--detach']

    def test_missing_repo_is_a_usage_error(self):
        r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'hmipreview', 'serve',
                            os.path.join(self.repo.path, 'nope')], cwd=PACKAGE_ROOT, capture_output=True,
                           encoding='utf-8', timeout=30)
        self.assertEqual(2, r.returncode)


class ConfiguredStartScreenTest(ServerCase):
    start_screen = 'B'

    def test_start_screen_from_tiabridge_json(self):
        self.repo.export('screen', 'B', document('screen', 'B', Number=5))
        self.repo.export('screen', 'C', document('screen', 'C', Number=3))
        self.serve()
        self.assertEqual('B', self.get_json('/api/screens')['startScreen'])


class ClientAddressTest(unittest.TestCase):
    """Reachable only from the engineering guest and its host network."""

    def test_loopback_private_and_link_local_clients_are_allowed(self):
        for addr in ('127.0.0.1', '127.8.9.10', '10.0.0.5', '172.16.0.1', '172.31.255.254', '192.168.56.1',
                     '169.254.10.20', '::1', 'fe80::1', 'fe80::1%12', 'fd12:3456::1', 'fc00::1',
                     '::ffff:192.168.1.4', '::ffff:127.0.0.1'):
            with self.subTest(addr):
                self.assertTrue(server.is_local_client(addr))

    def test_public_and_unreadable_clients_are_refused(self):
        for addr in ('8.8.8.8', '172.32.0.1', '100.64.0.1', '192.0.2.1', '2001:db8::1', '2a00:1450::1',
                     '::ffff:8.8.8.8', '0.0.0.0', '', 'not an address', None):
            with self.subTest(addr):
                self.assertFalse(server.is_local_client(addr))


class LocalClientOverHttpTest(ServerCase):
    def test_request_from_loopback_is_answered(self):
        self.serve()
        status, _ctype, _body = self.get('/api/screens')
        self.assertEqual(200, status)

    def test_request_from_another_network_is_forbidden(self):
        httpd = self.serve()
        httpd.is_allowed_client = lambda addr: False      # as if the client were outside the host network
        self.assertEqual(403, self.get_error('/api/screens'))
        self.assertEqual(403, self.get_error('/'))


if __name__ == '__main__':
    unittest.main()
