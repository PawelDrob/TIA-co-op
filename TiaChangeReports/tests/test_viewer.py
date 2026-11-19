"""The block viewer (TiaChangeReports/viewer): one block drawn as the report draws it, its source, a file it cannot draw,
the opening of its page and the registration for a double-click. No test opens a browser or writes the registry
outside its own key."""
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
from TiaChangeReports.viewer import browser, register, view
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
        why = html.split('class="why">')[1].split('</div>')[0]
        self.assertEqual(why, 'This file cannot be drawn: No such file or directory')
        self.assertIn('Cannot read this file: No such file or directory', html)

    def test_a_simaticml_export_in_upper_case_is_drawn(self):
        shutil.copy(os.path.join(FIXTURES, 'Main.xml'), os.path.join(self.dir, 'Main.XML'))
        html, title = view.page(os.path.join(self.dir, 'Main.XML'))
        self.assertEqual(title, 'Main [OB1]')
        self.assertNotIn('class="why"', html)
        self.assertTrue(SVG.search(html))

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


class Browser(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_a_page_goes_to_temp_and_old_pages_go(self):
        old = os.path.join(self.dir, 'old.html')
        with open(old, 'w') as f:
            f.write('x')
        os.utime(old, (time.time() - browser.KEEP - 60,) * 2)
        p = browser.write_page('<p>ü</p>', 'Filler [FB742]', self.dir)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.basename(p).startswith('Filler_FB742_-'))
        with open(p, encoding='utf-8') as f:
            self.assertEqual(f.read(), '<p>ü</p>')

    def test_the_page_opens_in_the_default_browser(self):
        opened = []
        browser.open_page(r'C:\Temp\a.html', start=opened.append)
        self.assertEqual(opened, [r'C:\Temp\a.html'])

    def test_main_opens_the_page_and_says_why_it_cannot(self):
        path = os.path.join(self.dir, 'Caller.s7dcl')
        _write(self.dir, {'Caller.s7dcl': CALLER})
        opened, said = [], []
        self.assertEqual(main([path], open_page=opened.append, message=said.append), 0)
        self.assertEqual(len(opened), 1)
        with open(opened[0], encoding='utf-8') as f:
            self.assertIn('<title>Caller [FB]</title>', f.read())
        os.remove(opened[0])

        def fails(p):
            raise OSError(1155, 'No application is associated with the specified file')
        self.assertEqual(main([path], open_page=fails, message=said.append), 1)
        self.assertEqual(said, ['The block viewer could not open %s in the default browser: No application is '
                                'associated with the specified file' % path])

    def test_html_writes_the_page_and_opens_nothing(self):
        _write(self.dir, {'Caller.s7dcl': CALLER})
        out = os.path.join(self.dir, 'out.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([os.path.join(self.dir, 'Caller.s7dcl'), '--html', out],
                                  open_page=lambda p: self.fail('opened')), 0)
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

    def test_the_state_reads_what_register_wrote_and_what_unregister_took_back(self):
        self.assertEqual(register.state(self.classes, self.choice), {'command': None, 'default': False, 'chosen': None})
        register.write_value(self.choice, '', 'Other.Editor', 'ProgId')
        register.register('"py" "viewer" "%1"', self.classes, self.choice, notify=False)
        self.assertEqual(register.state(self.classes, self.choice), {'command': '"py" "viewer" "%1"', 'default': True, 'chosen': 'Other.Editor'})
        register.unregister(self.classes, notify=False)
        self.assertEqual(register.state(self.classes, self.choice)['command'], None)

    def test_the_command_runs_pythonw_of_this_tree_on_the_viewer(self):
        cmd = register.command(r'C:\repo\TiaChangeReports\viewer')
        self.assertEqual(cmd, r'"C:\repo\.venv\Scripts\pythonw.exe" -X utf8 "C:\repo\TiaChangeReports\viewer" "%1"')


# An FB with members of UDT types: Hw holds the UDT Probe and a struct; Gone is in no file of the project.
MOTOR = '''FUNCTION_BLOCK "Motor"
    VAR_INPUT
        cmd : _.Probe;
    END_VAR
    VAR_IN_OUT
        io : _.Probe;
    END_VAR
    VAR
        head : _.Hw;
        lost : _.Gone;
    END_VAR
    VAR_TEMP
        scratch : _.Probe;
    END_VAR
END_FUNCTION_BLOCK
'''
HW = '''TYPE
    Hw : STRUCT
        { S7_MLC := "MLC_l" }
        low : Bool;
        probe : _.Probe;
        flow : STRUCT
            rate : Int;
        END_STRUCT;
    END_STRUCT;
END_TYPE
'''
HW_RES = 'MultiLingualTexts:\n  - id: MLC_l\n    en-US: low level reached\n'
PROBE = '''TYPE
    Probe : STRUCT
        { S7_SetPoint := "True" }
        up : Bool;
        down : Int := 5;
    END_STRUCT;
END_TYPE
'''
ROW = re.compile(r'<tr[^>]*><td class="nm" data-d="(\d)"( data-u)? style="[^"]*"><span class="tw">([^<]*)</span>(\w+)'
                 r'(.*?)</tr>')


class UdtMembers(unittest.TestCase):
    """A member of a UDT type opens onto the UDT's members, read from the UDT's file in the project, nested UDTs too;
    the report's interface table stays as it was."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        _write(self.dir, {'blocks/Motor.s7dcl': MOTOR, 'types/Hw.s7dcl': HW, 'types/Hw.s7res': HW_RES,
                          'types/Probe.s7dcl': PROBE})
        os.mkdir(os.path.join(self.dir, '.git'))                 # a repo: the viewer reads its types folder

    def rows(self, html):
        """[(level, opened, arrow, name)] of the interface table's member rows."""
        itf = next(t for t in html.split('<table class="itf"')[1:] if 'data-d="1"' in t.split('</table>')[0])
        return [(int(d), bool(u), tw, name) for d, u, tw, name, _ in ROW.findall(itf)]

    def test_a_udt_member_lists_the_udts_members_nested_udts_too(self):
        html, _ = view.page(os.path.join(self.dir, 'blocks', 'Motor.s7dcl'))
        self.assertEqual(self.rows(html), [
            (1, False, '▼', 'cmd'), (2, True, '', 'up'), (2, True, '', 'down'),
            (1, False, '▼', 'io'), (2, True, '', 'up'), (2, True, '', 'down'),
            (1, False, '▼', 'head'), (2, True, '', 'low'), (2, True, '▼', 'probe'), (3, True, '', 'up'),
            (3, True, '', 'down'), (2, True, '▼', 'flow'), (3, True, '', 'rate'),
            (1, False, '', 'lost'),
            (1, False, '▼', 'scratch'), (2, True, '', 'up'), (2, True, '', 'down')])
        cells = {}                                                               # (parent, member) -> its cells
        parent = None
        for d, _, _, name, rest in ROW.findall(html):
            parent = name if d == '1' else parent
            cells[parent, name] = rest
        self.assertIn('<span class="inh">low level reached</span>', cells['head', 'low'])   # from the UDT's .s7res
        self.assertIn('<span class="dflt">5</span>', cells['cmd', 'down'])                  # the UDT's default value
        self.assertIn('<span class="cb on dis">', cells['cmd', 'up'])           # ticked as the UDT has it, disabled
        self.assertEqual(re.findall(r'<span class="cb[^"]*">', cells['io', 'up']),
                         ['<span class="cb dis">'] * 4)                         # in-out: empty, as the in-out's own
        self.assertNotIn('dflt', cells['scratch', 'down'])                      # Temp: no default and no boxes
        self.assertNotIn('class="cb', cells['scratch', 'up'] + cells['scratch', 'down'])

    def test_the_reports_interface_table_does_not_open_them(self):
        go = MOTOR                                               # a member added to each section: each shows
        for k, last in enumerate(('cmd : _.Probe;', 'lost : _.Gone;', 'scratch : _.Probe;')):
            go = go.replace(last, last + '\n        go%d : Bool;' % k)
        _write(self.dir, {'after/Motor.s7dcl': go, 'after/Hw.s7dcl': HW, 'after/Probe.s7dcl': PROBE})
        os.rename(os.path.join(self.dir, 'blocks'), os.path.join(self.dir, 'before'))
        shutil.copy(os.path.join(self.dir, 'types', 'Hw.s7dcl'), os.path.join(self.dir, 'before'))
        shutil.copy(os.path.join(self.dir, 'types', 'Probe.s7dcl'), os.path.join(self.dir, 'before'))
        out = os.path.join(self.dir, 'report.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report([os.path.join(self.dir, 'before'), os.path.join(self.dir, 'after'), '--all',
                                     '-o', out]), 0)
        with open(out, encoding='utf-8') as f:
            page = f.read()
        motor = page.split('<b>Motor [FB]</b>', 1)[1]
        self.assertEqual([(d, tw, name) for d, _, tw, name in self.rows(motor)],
                         [(1, '▶', 'cmd'), (1, '', 'go0'), (1, '▶', 'head'), (1, '▶', 'lost'), (1, '', 'go1'),
                          (1, '▶', 'scratch'), (1, '', 'go2')])


# An FB with members in every section, a default, a retain of its own and one set in the instance, a UDT member and a
# multi-instance; its instance DB sets a start value of its own and one on a nested member.
PUMP = '''FUNCTION_BLOCK "Pump"
    VAR_INPUT
        start : Bool;
        speed : Int := 3;
    END_VAR
    VAR_OUTPUT
        running : Bool;
    END_VAR
    VAR_IN_OUT
        pos : Int;
    END_VAR
    VAR
        { S7_MLC := "MLC_s" }
        stat : Int := 7;
        cmd : _.Probe;
        drive : _.Valve;
        other : _.Valve;
    END_VAR
    VAR RETAIN
        count : DInt;
    END_VAR
    VAR DB_SPECIFIC
        kept : Int;
    END_VAR
    VAR_TEMP
        scratch : Int;
    END_VAR
    VAR CONSTANT
        LIMIT : Int := 1;
    END_VAR
END_FUNCTION_BLOCK
'''
PUMP_RES = 'MultiLingualTexts:\n  - id: MLC_s\n    en-US: state of the pump\n'
VALVE = '''FUNCTION_BLOCK "Valve"
    VAR_INPUT
        open : Bool;
    END_VAR
    VAR
        time : Int := 4;
        seal : _.Seal;
    END_VAR
    VAR_TEMP
        tmp : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
SEAL = '''FUNCTION_BLOCK "Seal"
    VAR
        worn : Bool;
        wait : TON_TIME;
    END_VAR
END_FUNCTION_BLOCK
'''
PUMP_DB = '''{
    S7_StandardRetain := "TRUE"
}
DATA_BLOCK PumpDb : Pump
    speed := 9;
    cmd.down := 2;
    drive.time := 6;
END_DATA_BLOCK
'''

# The SimaticML of the same instance DB, as TIA writes one: the FB's members of Input, Output, InOut and Static with
# the retain of this DB, a UDT's and a multi-instance's members nested, a StartValue only where the DB sets its own.
PUMP_DB_XML = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.InstanceDB ID="0">
    <AttributeList>
      <InstanceOfName>Pump</InstanceOfName>
      <InstanceOfType>FB</InstanceOfType>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
  <Section Name="Input">
    <Member Name="start" Datatype="Bool" Remanence="NonRetain" />
    <Member Name="speed" Datatype="Int" Remanence="NonRetain"><StartValue>9</StartValue></Member>
  </Section>
  <Section Name="Output"><Member Name="running" Datatype="Bool" Remanence="NonRetain" /></Section>
  <Section Name="InOut"><Member Name="pos" Datatype="Int" Remanence="NonRetain" /></Section>
  <Section Name="Static">
    <Member Name="stat" Datatype="Int" Remanence="NonRetain" />
    <Member Name="cmd" Datatype="&quot;Probe&quot;" Remanence="NonRetain">
      <Sections><Section Name="None">
        <Member Name="up" Datatype="Bool" />
        <Member Name="down" Datatype="Int"><StartValue>2</StartValue></Member>
      </Section></Sections>
    </Member>
    <Member Name="drive" Datatype="&quot;Valve&quot;" Remanence="NonRetain">
      <Sections>
        <Section Name="Input"><Member Name="open" Datatype="Bool" /></Section>
        <Section Name="Static"><Member Name="time" Datatype="Int"><StartValue>6</StartValue></Member></Section>
      </Sections>
    </Member>
    <Member Name="other" Datatype="&quot;Valve&quot;" Remanence="NonRetain" />
    <Member Name="count" Datatype="DInt" Remanence="Retain" />
    <Member Name="kept" Datatype="Int" Remanence="Retain" />
  </Section>
</Sections></Interface>
      <Name>PumpDb</Name>
      <Number>3</Number>
      <ProgrammingLanguage>DB</ProgrammingLanguage>
    </AttributeList>
  </SW.Blocks.InstanceDB>
</Document>
'''


class InstanceDb(unittest.TestCase):
    """An instance DB, and a DB of a UDT, shows the members of its FB or UDT from that block's file: by section, with
    the DB's own start values apart from the FB's defaults; a type the project lacks is said."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        _write(self.dir, {'blocks/Pump.s7dcl': PUMP, 'blocks/Pump.s7res': PUMP_RES, 'blocks/Valve.s7dcl': VALVE,
                          'blocks/Seal.s7dcl': SEAL, 'blocks/PumpDb.s7dcl': PUMP_DB, 'types/Probe.s7dcl': PROBE})
        os.mkdir(os.path.join(self.dir, '.git'))

    def page(self, rel):
        return view.page(os.path.join(self.dir, *rel.split('/')))[0]

    def cells(self, html):
        """{(parent, member): the rest of its row} and [(level, arrow, name)] of the interface table."""
        out, order, parent = {}, [], None
        for d, _, tw, name, rest in ROW.findall(html):
            parent = name if d == '1' else parent
            out[(parent, name) if d != '1' else name] = rest
            order.append((int(d), tw, name))
        return out, order

    def test_the_members_of_its_fb_by_section_its_own_start_values_apart(self):
        html = self.page('blocks/PumpDb.s7dcl')
        cells, order = self.cells(html)
        self.assertEqual([x for x in order if x[0] == 1], [
            (1, '', 'start'), (1, '', 'speed'), (1, '', 'running'), (1, '', 'pos'), (1, '', 'stat'), (1, '▼', 'cmd'),
            (1, '▼', 'drive'), (1, '▼', 'other'), (1, '', 'count'), (1, '', 'kept')])     # no Temp, no Constant
        self.assertEqual(re.findall(r'data-d="0"><span class="tw">▼</span>(\w+)', html),
                         ['Input', 'Output', 'InOut', 'Static'])
        self.assertIn('<td>9</td>', cells['speed'])                                    # the DB's own: black
        self.assertIn('<span class="dflt">7</span>', cells['stat'])                    # the FB's default: grey
        self.assertIn('state of the pump', cells['stat'])                              # the FB's comment
        self.assertIn('<td>2</td>', cells['cmd', 'down'])                              # a nested start value
        self.assertIn('<td>6</td>', cells['drive', 'time'])                           # inside a multi-instance
        self.assertNotIn(('drive', 'tmp'), cells)                                      # its Temp neither
        self.assertEqual([x for x in order if x[0] > 1], [                             # every multi-instance opens
            (2, '', 'up'), (2, '', 'down'),
            (2, '', 'open'), (2, '', 'time'), (2, '▼', 'seal'), (3, '', 'worn'), (3, '', 'wait'),
            (2, '', 'open'), (2, '', 'time'), (2, '▼', 'seal'), (3, '', 'worn'), (3, '', 'wait')])
        self.assertIn('<span class="dflt">4</span>', cells['other', 'time'])          # the FB's default in it
        self.assertIn('Members of FB Pump, from blocks/Pump.s7dcl.', html)
        self.assertNotIn('No members', html)

    def test_a_multi_instance_of_its_own_fb_by_a_chain_stays_closed(self):
        fb = 'FUNCTION_BLOCK "%s"\n    VAR\n        %s : _.%s;\n    END_VAR\nEND_FUNCTION_BLOCK\n'
        _write(self.dir, {'blocks/Ping.s7dcl': fb % ('Ping', 'pong', 'Pong'),
                          'blocks/Pong.s7dcl': fb % ('Pong', 'ping', 'Ping'),
                          'blocks/PingDb.s7dcl': 'DATA_BLOCK PingDb : Ping\nEND_DATA_BLOCK\n'})
        self.assertEqual(self.cells(self.page('blocks/PingDb.s7dcl'))[1], [(1, '▼', 'pong'), (2, '', 'ping')])

    def test_an_fbs_own_page_keeps_its_multi_instances_closed(self):
        order = self.cells(self.page('blocks/Pump.s7dcl'))[1]
        self.assertIn((1, '', 'drive'), order)
        self.assertNotIn('open', [n for _, _, n in order])

    def test_retain_as_the_fb_declares_it_and_set_in_the_instance(self):
        def retain(html, name):                                          # its Retain cell ticked
            cell = re.findall(r'<td[^>]*>(.*?)</td>', self.cells(html)[0][name])[2]
            return 'class="cb on' in cell
        html = self.page('blocks/PumpDb.s7dcl')
        self.assertEqual([retain(html, n) for n in ('stat', 'count', 'kept')], [False, True, True])
        _write(self.dir, {'blocks/PumpDb.s7dcl': PUMP_DB.replace('"TRUE"', '"FALSE"')})
        html = self.page('blocks/PumpDb.s7dcl')
        self.assertEqual([retain(html, n) for n in ('stat', 'count', 'kept')], [False, True, False])

    def test_a_db_whose_fb_is_not_in_the_project_says_so(self):
        _write(self.dir, {'blocks/LostDb.s7dcl': 'DATA_BLOCK LostDb : Gone\n    speed := 1;\nEND_DATA_BLOCK\n'})
        html = self.page('blocks/LostDb.s7dcl')
        self.assertIn('Instance of Gone: its members could not be read, no file of Gone', html)
        self.assertNotIn('No members', html)
        self.assertEqual(self.cells(html)[1], [(1, '', 'speed')])         # only what the DB says, below the line
        self.assertLess(html.index('could not be read'), html.index('<table class="itf"'))

    def test_a_db_of_a_udt_shows_the_udts_members(self):
        _write(self.dir, {'blocks/ProbeDb.s7dcl': '{\n    S7_StandardRetain := "TRUE"\n}\n'
                                                  'DATA_BLOCK ProbeDb : Probe\n    up := TRUE;\nEND_DATA_BLOCK\n'})
        html = self.page('blocks/ProbeDb.s7dcl')
        cells, order = self.cells(html)
        self.assertEqual(order, [(1, '', 'up'), (1, '', 'down')])
        self.assertEqual(re.findall(r'data-d="0"><span class="tw">▼</span>(\w+)', html), ['Static'])
        self.assertIn('<td>TRUE</td>', cells['up'])
        self.assertIn('<span class="dflt">5</span>', cells['down'])
        self.assertIn('Members of UDT Probe, from types/Probe.s7dcl.', html)

    def test_its_simaticml_export_gives_the_same_table(self):
        _write(self.dir, {'blocks/PumpDb.xml': PUMP_DB_XML})
        tables = [re.search(r'<div class="of">.*?</table>', self.page('blocks/PumpDb.' + x), re.S).group(0)
                  for x in ('s7dcl', 'xml')]
        self.assertEqual(tables[0], tables[1])
        self.assertIn('<td>9</td>', tables[1])
        _write(self.dir, {'blocks/PumpDb.s7dcl': PUMP_DB.replace('"TRUE"', '"FALSE"'),
                          'blocks/PumpDb.xml': PUMP_DB_XML.replace('"kept" Datatype="Int" Remanence="Retain"',
                                                                   '"kept" Datatype="Int" Remanence="NonRetain"')})
        self.assertEqual(*[re.search(r'<div class="of">.*?</table>', self.page('blocks/PumpDb.' + x), re.S).group(0)
                           for x in ('s7dcl', 'xml')])

    def test_a_db_of_a_udt_from_simaticml_gives_the_same_table(self):
        _write(self.dir, {
            'blocks/ProbeDb.s7dcl': '{\n    S7_StandardRetain := "TRUE"\n}\n'
                                    'DATA_BLOCK ProbeDb : Probe\n    down := 7;\nEND_DATA_BLOCK\n',
            'blocks/ProbeDb.xml': PUMP_DB_XML.split('<Interface>')[0].replace('Pump', 'Probe').replace('>FB<', '>UDT<')
            + '<Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">'
              '<Section Name="Static"><Member Name="up" Datatype="Bool" Remanence="Retain" />'
              '<Member Name="down" Datatype="Int" Remanence="Retain"><StartValue>7</StartValue></Member></Section>'
              '</Sections></Interface><Name>ProbeDb</Name><Number>4</Number>'
              '<ProgrammingLanguage>DB</ProgrammingLanguage></AttributeList></SW.Blocks.InstanceDB></Document>'})
        tables = [re.search(r'<div class="of">.*?</table>', self.page('blocks/ProbeDb.' + x), re.S).group(0)
                  for x in ('s7dcl', 'xml')]
        self.assertEqual(tables[0], tables[1])
        self.assertIn('<td>7</td>', tables[1])
        self.assertIn('<span class="cb on dis">', tables[1].split('>up<')[1].split('</tr>')[0])   # the DB's retain

    def test_the_reports_table_of_an_instance_db_is_as_before(self):
        from TiaChangeReports import iface
        blk, _, _, _ = view.block_of(os.path.join(self.dir, 'blocks', 'PumpDb.s7dcl'))
        self.assertEqual([r.path for r in iface.block_rows(blk, blk)],
                         [('speed',), ('cmd',), ('cmd', 'up'), ('cmd', 'down'), ('drive',), ('drive', 'open'),
                          ('drive', 'time'), ('drive', 'seal'), ('drive', 'tmp')])


if __name__ == '__main__':
    unittest.main()
