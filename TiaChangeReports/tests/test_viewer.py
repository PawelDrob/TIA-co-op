"""The block viewer (TiaChangeReports/viewer): one block drawn as the report draws it, its source, a file it cannot draw,
its window and the registration for a double-click. No test opens a window or writes the registry outside its own key."""
import contextlib
import io
import os
import re
import shutil
import tempfile
import time
import unittest
import uuid
import winreg

from TiaChangeReports.__main__ import main as report
from TiaChangeReports.tests.test_tia_look import CALLEE, CALLER, CALLER_RES, _write
from TiaChangeReports.viewer import register, view, window
from TiaChangeReports.viewer.__main__ import main

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
PLANT = os.path.join(FIXTURES, 'plant', 'v2')
SVG = re.compile(r'<svg style="[^"]*" xmlns="[^"]*" class="lad".*?</svg>', re.S)


def _project(root):
    """A project repo with LAD, SCL and SimaticML blocks, a call whose callee is in another folder, a DB, a UDT."""
    shutil.copytree(os.path.join(PLANT, 'plc'), os.path.join(root, 'plc'))
    shutil.copytree(os.path.join(PLANT, 'library'), os.path.join(root, 'library'))
    for name in ('Jumps.s7dcl', 'Jumps.s7res', 'Main.xml'):
        shutil.copy(os.path.join(FIXTURES, name), os.path.join(root, 'plc', 'blocks', name))
    _write(root, {'plc/blocks/Calls/Caller.s7dcl': CALLER, 'plc/blocks/Calls/Caller.s7res': CALLER_RES,
                  'plc/blocks/Drives/Drive.s7dcl': CALLEE, 'hmi/README.txt': 'no HMI\n'})


def _report_svgs(page):
    """{block heading: [the after side's SVG of each LAD network]} of a report of a folder against itself."""
    out = {}
    for sec in page.split('<section class="blk')[1:]:
        name = re.search(r'<div class="bh"[^>]*><b>(.*?)</b>', sec).group(1)
        panes = re.findall(r'<div class="panes"><div class="pane"><div class="pb">(.*?)</div></div>'
                           r'<div class="pane"><div class="pb">(.*?)</div></div></div>', sec, re.S)
        out[name] = [after for _, after in panes]
    return out


class Drawing(unittest.TestCase):
    """A LAD network in the viewer is the SVG the report draws for it with --all, byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, 'Plant')
        _project(cls.root)
        out = os.path.join(cls.tmp, 'report.html')
        with contextlib.redirect_stdout(io.StringIO()):
            assert report([cls.root, cls.root, '--all', '-o', out]) == 0
        with open(out, encoding='utf-8') as f:
            cls.report = _report_svgs(f.read())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def page(self, rel):
        return view.page(os.path.join(self.root, *rel.split('/')))

    def test_every_lad_network_is_the_reports_svg(self):
        files = ['plc/blocks/Jumps.s7dcl', 'plc/blocks/Main.xml', 'plc/blocks/Calls/Caller.s7dcl',
                 'plc/blocks/Safety/HatchLogic.s7dcl', 'library/types/Bottling/Filler/Filler.s7dcl']
        drawn = 0
        for rel in files:
            html, title = self.page(rel)
            with self.subTest(rel):
                self.assertIn(title, self.report)
                self.assertEqual(SVG.findall(html), self.report[title])
                drawn += len(self.report[title])
        self.assertGreater(drawn, 10)

    def test_a_call_box_has_its_pins_from_the_callees_file_in_the_project(self):
        html, _ = self.page('plc/blocks/Calls/Caller.s7dcl')
        with tempfile.TemporaryDirectory() as d:                 # alone in its folder: no callee
            alone = os.path.join(d, 'Caller.s7dcl')
            shutil.copy(os.path.join(self.root, 'plc', 'blocks', 'Calls', 'Caller.s7dcl'), alone)
            without, _ = view.page(alone)
        self.assertIn('Drives one motor.', html)                 # the callee's comment over its box
        self.assertNotIn('Drives one motor.', without)
        self.assertIn('Calls and types read from Plant', html)

    def test_one_column_header_properties_interface_networks(self):
        html, title = self.page('library/types/Bottling/Filler/Filler.s7dcl')
        self.assertEqual(title, 'Filler [FB742]')
        self.assertIn('<b>Filler [FB742]</b>', html)
        self.assertIn('<td class="nm">Comment</td><td colspan="3">Fills one container. </td>', html)
        self.assertIn('iSettleTime', html)                        # every member, none folded
        self.assertNotIn('unchanged member', html)
        self.assertEqual(html.count('<div class="nw">'), 8 + 2)  # its 8 networks, and the source's two files
        for mark in ('class="hl ', 'tx del', 'tx ins', 'tr class="ins"', 'Before', 'After', 'class="sum"'):
            self.assertNotIn(mark, html)                          # no change marks, sides or summary
        self.assertIn('IF #statHead.Probe.High AND NOT', html)     # an SCL network as text

    def test_a_db_and_a_udt_show_their_members(self):
        html, title = self.page('plc/blocks/Safety/HatchDb.s7dcl')
        self.assertTrue(title.startswith('HatchDb ['), title)
        self.assertIn('Start value', html)
        html, _ = self.page('plc/types/typeHatch.s7dcl')
        self.assertIn('<div class="view" data-view="drawing">', html)
        self.assertIn('Interface', html)


class Source(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def put(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def test_the_switch_shows_the_file_and_its_s7res_as_text(self):
        path = self.put('Caller.s7dcl', CALLER)
        self.put('Caller.s7res', CALLER_RES)
        html, _ = view.page(path)
        src = html.split('data-view="source"', 2)[2]
        self.assertIn('<b>Caller.s7dcl</b>', src)
        self.assertIn('<b>Caller.s7res</b>', src)
        self.assertIn('en-US: second drive', src)
        self.assertIn('&quot;Caller&quot;', src)                # escaped
        self.assertIn('<div class="view" data-view="source" hidden>', html)
        self.assertIn('data-view="drawing" aria-pressed="true"', html)

    def test_a_file_it_cannot_draw_opens_on_its_source_with_why(self):
        cases = {'Broken.s7dcl': ('FUNCTION_BLOCK "Broken"\n  VAR\n', 'not a SIMATIC SD block export: no END_FUNCTION_BLOCK'),
                 'Empty.s7dcl': ('', 'not a SIMATIC SD block export: empty'),
                 'Texts.s7res': (CALLER_RES, 'not a block export'),
                 'Tags.xml': ('<?xml version="1.0"?><Document><SW.Tags.PlcTagTable ID="0"/></Document>',
                              'not a SimaticML block export')}
        for name, (text, why) in cases.items():
            with self.subTest(name):
                html, title = view.page(self.put(name, text))
                self.assertEqual(title, name)
                self.assertIn('<div class="why">This file cannot be drawn: ' + why, html)
                self.assertNotIn(self.dir, html.split('class="why">')[1].split('</div>')[0])   # no path in why
                self.assertNotIn('<div class="view" data-view="drawing">', html)
                self.assertIn('<div class="view" data-view="source">', html)
                self.assertIn('data-view="drawing" aria-pressed="false" title="The block drawn (D)" disabled', html)
                self.assertIn('<b>%s</b>' % name, html)

    def test_a_file_that_is_not_there(self):
        html, _ = view.page(os.path.join(self.dir, 'Gone.s7dcl'))
        self.assertIn('class="why">This file cannot be drawn: ', html)
        self.assertIn('Cannot read this file: ', html)

    def test_the_project_root(self):
        nested = os.path.join(self.dir, 'Plant', 'plc', 'blocks', 'A')
        os.makedirs(nested)
        f = os.path.join(nested, 'A.s7dcl')
        self.assertEqual(view.project_root(f), nested)            # no repo: its own folder
        os.makedirs(os.path.join(self.dir, '.git'))
        self.assertEqual(view.project_root(f), self.dir)          # a git repo's top
        for m in ('hmi', 'library'):
            os.makedirs(os.path.join(self.dir, 'Plant', m))
        self.assertEqual(view.project_root(f), os.path.join(self.dir, 'Plant'))   # a project repo, before git


class Window(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_a_page_goes_to_temp_and_old_pages_go(self):
        old = os.path.join(self.dir, 'old.html')
        with open(old, 'w') as f:
            f.write('x')
        os.utime(old, (time.time() - window.KEEP - 60,) * 2)
        p = window.write_page('<p>ü</p>', 'Filler [FB742]', self.dir)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.basename(p).startswith('Filler_FB742_-'))
        with open(p, encoding='utf-8') as f:
            self.assertEqual(f.read(), '<p>ü</p>')

    def test_the_browser_opens_the_page_as_an_app_window(self):
        args = window.app_command(r'C:\Edge\msedge.exe', r'C:\Temp\A b.html')
        self.assertEqual(args, [r'C:\Edge\msedge.exe', '--app=file:///C:/Temp/A%20b.html'])
        args = window.app_command('msedge.exe', r'C:\Temp\a.html', profile=r'C:\P')
        self.assertEqual(args[1], r'--user-data-dir=C:\P')
        self.assertEqual(args[-1], '--app=file:///C:/Temp/a.html')
        started = []
        window.open_window(r'C:\Temp\a.html', browser='msedge.exe', start=lambda a, **k: started.append(a))
        self.assertEqual(started, [['msedge.exe', '--app=file:///C:/Temp/a.html']])

    def test_no_browser_says_so(self):
        import TiaChangeReports.viewer.window as w
        real = w.edge_path
        w.edge_path = lambda: None
        try:
            with self.assertRaises(LookupError) as e:
                window.open_window('a.html', start=lambda *a, **k: self.fail('started'))
            self.assertIn('Edge', str(e.exception))
        finally:
            w.edge_path = real

    def test_main_opens_one_window_on_the_page_and_says_why_it_cannot(self):
        path = os.path.join(self.dir, 'Caller.s7dcl')
        _write(self.dir, {'Caller.s7dcl': CALLER})
        opened, said = [], []
        self.assertEqual(main([path], open_window=lambda p, profile=None: opened.append(p), message=said.append), 0)
        self.assertEqual(len(opened), 1)
        with open(opened[0], encoding='utf-8') as f:
            self.assertIn('<title>Caller [FB]</title>', f.read())
        os.remove(opened[0])

        def fails(p, profile=None):
            raise LookupError(window.NO_BROWSER)
        self.assertEqual(main([path], open_window=fails, message=said.append), 1)
        self.assertEqual(said, [window.NO_BROWSER])

    def test_html_writes_the_page_and_opens_nothing(self):
        _write(self.dir, {'Caller.s7dcl': CALLER})
        out = os.path.join(self.dir, 'out.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([os.path.join(self.dir, 'Caller.s7dcl'), '--html', out],
                                  open_window=lambda *a, **k: self.fail('opened')), 0)
        self.assertTrue(os.path.isfile(out))


class Register(unittest.TestCase):
    """In a key of the test's own under HKEY_CURRENT_USER, deleted after it."""

    def setUp(self):
        self.root = r'Software\TiaChangeReportsViewerTest-%s' % uuid.uuid4().hex
        self.classes = self.root + r'\Classes'
        self.choice = self.root + r'\UserChoice'
        self.addCleanup(register.delete_tree, 'Software', self.root.split('\\', 1)[1])

    def get(self, sub, name=''):
        return register.read_value(self.classes, sub, name)

    def test_register_and_take_it_back(self):
        lines = register.register('"py" "viewer" "%1"', self.classes, self.choice, notify=False)
        self.assertEqual(self.get('.s7dcl'), register.PROGID)
        self.assertEqual(self.get(register.PROGID + r'\shell\open\command'), '"py" "viewer" "%1"')
        self.assertEqual(self.get(r'.s7dcl\OpenWithProgids', register.PROGID), '')
        self.assertEqual(len(lines), 1)
        register.unregister(self.classes, notify=False)
        self.assertIsNone(self.get(register.PROGID))
        with self.assertRaises(OSError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.classes + r'\.s7dcl')

    def test_the_program_there_before_comes_back(self):
        register.write_value(self.classes, '.s7dcl', 'Other.Editor')
        register.register('cmd', self.classes, self.choice, notify=False)
        register.register('cmd', self.classes, self.choice, notify=False)     # again: the one before stays known
        self.assertEqual(self.get('.s7dcl'), register.PROGID)
        lines = register.unregister(self.classes, notify=False)
        self.assertEqual(self.get('.s7dcl'), 'Other.Editor')
        self.assertIn('back to Other.Editor', lines[0])

    def test_the_program_there_last_comes_back(self):
        register.write_value(self.classes, '.s7dcl', 'Other.Editor')
        register.register('cmd', self.classes, self.choice, notify=False)
        register.write_value(self.classes, '.s7dcl', 'Newer.Editor')          # another program took .s7dcl since
        register.register('cmd', self.classes, self.choice, notify=False)
        register.unregister(self.classes, notify=False)
        self.assertEqual(self.get('.s7dcl'), 'Newer.Editor')

    def test_a_choice_in_open_with_is_named(self):
        register.write_value(self.choice, '', 'Other.Editor', 'ProgId')
        lines = register.register('cmd', self.classes, self.choice, notify=False)
        self.assertIn('Windows opens .s7dcl files with Other.Editor', lines[1])

    def test_the_command_runs_pythonw_of_this_tree_on_the_viewer(self):
        cmd = register.command(r'C:\repo\TiaChangeReports\viewer')
        self.assertEqual(cmd, r'"C:\repo\.venv\Scripts\pythonw.exe" -X utf8 "C:\repo\TiaChangeReports\viewer" "%1"')


if __name__ == '__main__':
    unittest.main()
