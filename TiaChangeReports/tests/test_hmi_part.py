"""The HMI part of the page (hmi.py, hmi.js): the hmi/ folder of a --git repo or of two folders beside the PLC
blocks, compared by hmipreview. Made-up repo: a PLC block and the screens, a template and a tag table of an HMI."""
import base64
import contextlib
import gzip
import io
import json
import msvcrt
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html import unescape
from unittest import mock

from TiaChangeReports.tests.test_change_reports import RES, SRC, _git, _put

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT_ATTRS = '<BackColor>255, 255, 255</BackColor><Height>800</Height><Width>1280</Width>'


def screen(name, number, items='', template=None, kind='Screen'):
    links = ('<LinkList><Template TargetID="@OpenLink"><Name>%s</Name></Template></LinkList>' % template
             if template else '')
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><DocumentInfo>'
            '<Created>2026-10-06T00:00:00</Created></DocumentInfo><Hmi.Screen.%s ID="0"><AttributeList>%s'
            '<Name>%s</Name><Number>%d</Number></AttributeList>%s<ObjectList><Hmi.Screen.ScreenLayer ID="1" '
            'CompositionName="Layers"><AttributeList><Index>0</Index><Name /><VisibleES>true</VisibleES>'
            '</AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.ScreenLayer></ObjectList></Hmi.Screen.%s>'
            '</Document>\n' % (kind, ROOT_ATTRS, name, number, links, items, kind))


def rect(name, left=10, tag=None):
    anim = ('<ObjectList><Hmi.Dynamic.VisibilityAnimation ID="5" CompositionName="Animations"><AttributeList>'
            '<Name>VisibilityAnimation</Name></AttributeList><ObjectList><Hmi.Dynamic.TagElementTrigger ID="6" '
            'CompositionName="VisibilityTag"><LinkList><Tag TargetID="@OpenLink"><Name>%s</Name></Tag></LinkList>'
            '</Hmi.Dynamic.TagElementTrigger></ObjectList></Hmi.Dynamic.VisibilityAnimation></ObjectList>' % tag
            if tag else '')
    return ('<Hmi.Screen.Rectangle ID="2" CompositionName="ScreenItems"><AttributeList><BackColor>0, 160, 0'
            '</BackColor><BackFillStyle>Solid</BackFillStyle><Height>40</Height><Left>%d</Left><ObjectName>%s'
            '</ObjectName><Top>100</Top><Width>40</Width></AttributeList>%s</Hmi.Screen.Rectangle>'
            % (left, name, anim))


def tag_table(name, tags):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><Hmi.Tag.TagTable '
            'ID="0"><AttributeList><Name>%s</Name></AttributeList><ObjectList>%s</ObjectList></Hmi.Tag.TagTable>'
            '</Document>\n' % (name, ''.join(
                '<Hmi.Tag.Tag ID="%d" CompositionName="Tags"><AttributeList><Name>%s</Name></AttributeList>'
                '<LinkList><AcquisitionCycle TargetID="@OpenLink"><Name>%s</Name></AcquisitionCycle></LinkList>'
                '</Hmi.Tag.Tag>' % (i + 1, t, c) for i, (t, c) in enumerate(tags))))


def hmi_data(html):
    """The page's HMI data (gzip + base64 JSON)."""
    m = re.search(r'<script type="application/octet-stream" class="hmidata">([^<]*)</script>', html)
    return json.loads(gzip.decompress(base64.b64decode(m.group(1))))


def json_attribute(dom, name):
    """The JSON a page's script wrote in that attribute."""
    return json.loads(unescape(re.search(r'%s="([^"]*)"' % name, dom).group(1)))


class HmiPart(unittest.TestCase):
    """Commit one: block A, screens Filler (on template Main) and Door, tag table Plant. Commit two: A changed, a
    rectangle of Filler moved, Gate new, tag Motor's cycle changed; Door and Main unchanged."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = r = os.path.join(tmp.name, 'Plant')
        self.out = os.path.join(tmp.name, 'out', 'page.html')
        os.makedirs(r)
        _git(r, 'init', '-q')
        _git(r, 'config', 'core.autocrlf', 'false')
        _put(r, {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES,
                 'hmi/screens/Units/Filler.xml': screen('Filler', 10, rect('lamp', tag='Motor.run'), template='Main'),
                 'hmi/screens/Door.xml': screen('Door', 11, rect('door')),
                 'hmi/templates/Main.xml': screen('Main', 0, rect('logo'), kind='ScreenTemplate'),
                 'hmi/tags/Plant.xml': tag_table('Plant', [('Motor', '100 ms')])})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'one')
        _put(r, {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                 'hmi/screens/Units/Filler.xml': screen('Filler', 10, rect('lamp', left=50, tag='Motor.run'),
                                                      template='Main'),
                 'hmi/screens/Gate.xml': screen('Gate', 12),
                 'hmi/tags/Plant.xml': tag_table('Plant', [('Motor', '1 s')])})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'two')

    def main(self, *args, revs=('HEAD~1', 'HEAD')):
        from TiaChangeReports.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--git', self.repo, *revs, '-o', self.out] + list(args))
        self.assertEqual(0, code)
        with open(self.out, encoding='utf-8') as f:
            return out.getvalue(), f.read()

    def test_blocks_and_hmi_objects_in_one_tree(self):
        _, html = self.main()

        keys = re.findall(r'<a class="obj (\w+)" href="#[^"]*" data-i="(\d+)" data-key="([^"]*)"', html)
        self.assertEqual([('changed', '0', 'A'), ('changed', '1', 'screen:Filler'), ('new', '2', 'screen:Gate'),
                          ('changed', '3', 'tagtable:Plant')], sorted(keys, key=lambda k: k[1]))
        tree = re.sub(r'<[^>]+>', ' ', html[html.index('<ul class="tree">'):html.index('</nav>')]).split()
        self.assertEqual(['HMI', '3', 'Screens', '2', 'Units', '1', 'Filler', '[Screen', '10]', 'Gate', '[Screen', '12]',
                          'HMI', 'tags', '1', 'Plant', '[HMI', 'tag', 'table]'],
                         tree[tree.index('HMI'):tree.index('plc')])
        self.assertEqual(4, len(re.findall(r'<section class="blk(?: hmi" data-o="\d+)?">', html)))
        self.assertIn('<section class="blk hmi" data-o="', html)
        self.assertIn('id="blk-screen:Filler"', html)
        self.assertIn('<table class="sum hsum">', html)

    def test_page_data_holds_the_changes_and_the_documents_drawn(self):
        _, html = self.main()

        data = hmi_data(html)
        by = {o['key']: o for o in data['objects']}
        self.assertEqual({'screen:Filler', 'screen:Gate', 'screen:Door', 'template:Main', 'tagtable:Plant'}, set(by))
        self.assertEqual(['Rectangle lamp: moved (10, 100) 40x40 -> (50, 100) 40x40'],
                         [l for c in by['screen:Filler']['changes'] for l in c['lines']])
        self.assertIn(by['template:Main']['adoc'], data['docs'])            # drawn under Filler, though unchanged
        motor = by['tagtable:Plant']['changes'][0]
        self.assertEqual([{'kind': 'screen', 'name': 'Filler'}], motor['usedAfter'])
        self.assertEqual('en-US', data['lang'])

    def test_two_objects_that_only_swap_are_on_the_page_both_named(self):
        _put(self.repo, {'hmi/screens/Door.xml': screen('Door', 11, rect('door') + rect('frame'))})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'three')
        _put(self.repo, {'hmi/screens/Door.xml': screen('Door', 11, rect('frame') + rect('door'))})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'four')

        out, html = self.main()

        self.assertIn('changed  screen      Door', out)
        door, = [o for o in hmi_data(html)['objects'] if o['name'] == 'Door']
        self.assertEqual('changed', door['state'])
        self.assertEqual([('frame', '2', '1'), ('door', '1', '2')],
                         [(c['object'], a['old'], a['new']) for c in door['changes'] for a in c['attributes']
                          if a['name'] == 'layerOrder'])

    def test_listing_and_json(self):
        out, _ = self.main()
        res = json.loads(self.main('--json')[0])

        self.assertIn('changed  screen      Filler', out)
        self.assertIn('new      screen      Gate', out)
        self.assertEqual([('screen', 'Filler', 'changed', 1), ('screen', 'Gate', 'new', 0),
                          ('tagtable', 'Plant', 'changed', 1)],
                         [(o['kind'], o['name'], o['state'], o['changes']) for o in res['hmi']])

    def test_only_one_part(self):
        _, plc = self.main('--only', 'plc')
        _, hmi = self.main('--only', 'hmi')
        _, block = self.main('--block', 'A')

        self.assertNotIn('hmidata', plc)
        self.assertNotIn('data-key="A"', hmi)
        self.assertIn('data-key="screen:Filler"', hmi)
        self.assertIn('<title>HMI changes</title>', hmi)
        self.assertNotIn('hmidata', block)

    def test_unchanged_objects_with_all(self):
        _, html = self.main('--all', '--only', 'hmi')

        self.assertIn('data-key="screen:Door"', html)
        self.assertIn('data-key="template:Main"', html)

    def test_generated_after_set(self):
        _put(self.repo, {'hmi/generated/screens/Door.xml': screen('Door', 11, rect('door') + rect('bell', left=80))})

        out, html = self.main('--after-set', 'generated', '--only', 'hmi', revs=('HEAD',))

        door = {o['key']: o for o in hmi_data(html)['objects']}['screen:Door']
        self.assertEqual(('changed', {'before': 'export', 'after': 'generated'}), (door['state'], door['origin']))
        self.assertIn('changed  screen      Door', out)

    def test_changed_graphic_in_the_project_graphics_with_its_images(self):
        img = os.path.join('project', 'graphics', 'Logo files', 'DefaultImageStream.png')
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Hmi.Globalization.MultiLingualGraphic ID="0">'
               '<AttributeList><DefaultImageStream external="path">Logo files\\DefaultImageStream.png'
               '</DefaultImageStream><Name>Logo</Name></AttributeList></Hmi.Globalization.MultiLingualGraphic>'
               '</Document>\n')
        _put(self.repo, {'project/graphics/Logo.xml': xml, img: 'one'})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'logo')
        _put(self.repo, {img: 'two'})

        _, html = self.main('--only', 'hmi', revs=('HEAD',))

        tree = re.sub(r'<[^>]+>', ' ', html[html.index('<ul class="tree">'):html.index('</nav>')]).split()
        self.assertEqual(['Languages', '&amp;', 'resources', '1', 'Project', 'graphics', '1', 'Logo', '[Graphic]'],
                         tree)
        logo = {o['key']: o for o in hmi_data(html)['objects']}['graphic:Logo']
        data = hmi_data(html)
        self.assertEqual(['data:image/png;base64,b25l', 'data:image/png;base64,dHdv'],
                         [data['docs'][logo['bimg']], data['docs'][logo['aimg']]])

    def test_unchanged_graphics_with_all(self):
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Hmi.Globalization.MultiLingualGraphic ID="0">'
               '<AttributeList><DefaultImageStream external="path">Fan files\\DefaultImageStream.png'
               '</DefaultImageStream><Name>Fan</Name></AttributeList></Hmi.Globalization.MultiLingualGraphic>'
               '</Document>\n')
        _put(self.repo, {'project/graphics/Fan.xml': xml,
                         os.path.join('project', 'graphics', 'Fan files', 'DefaultImageStream.png'): 'fan'})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'fan')

        _, plain = self.main('--only', 'hmi', revs=('HEAD',))
        _, every = self.main('--only', 'hmi', '--all', revs=('HEAD',))

        self.assertNotIn('data-key="graphic:Fan"', plain)
        self.assertIn('data-key="graphic:Fan"', every)
        fan = {o['key']: o for o in hmi_data(every)['objects']}['graphic:Fan']
        self.assertEqual('data:image/png;base64,ZmFu', hmi_data(every)['docs'][fan['aimg']])

    def test_unreadable_documents_as_the_only_hmi_changes_are_named(self):
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Hmi.Globalization.MultiLingualGraphic ID="0">'
               '<AttributeList><Name>Fan</Name></AttributeList></Hmi.Globalization.MultiLingualGraphic></Document>\n')
        _put(self.repo, {'project/graphics/Fan.xml': xml})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'fan')
        _put(self.repo, {'project/graphics/Fan.xml': '<Document><broken',
                         'hmi/screens/Door.xml': '<Document><Hmi.Screen.Screen ID="0"><broken'})

        printed, html = self.main('--only', 'hmi', '--json', revs=('HEAD',))
        res = json.loads(printed)

        self.assertIn('Not compared, could not be read and may hold a change: hmi/screens/Door.xml, project/graphics/Fan.xml', html)
        self.assertNotIn('No changes.', html)
        self.assertEqual(['hmi/screens/Door.xml', 'project/graphics/Fan.xml'],
                         sorted(s['path'] for s in res['skipped']))
        self.assertEqual([], res['hmi'])
        self.assertIn('Plant @ HEAD', res['before'])
        self.assertIn('(working tree)', res['after'])

    def test_two_folders(self):
        before, after = os.path.join(self.repo, '..', 'b'), os.path.join(self.repo, '..', 'a')
        for d, rev in ((before, 'HEAD~1'), (after, 'HEAD')):
            os.makedirs(d)
            _git(self.repo, 'worktree', 'add', '-q', '--detach', os.path.abspath(d), rev)
        from TiaChangeReports.__main__ import main
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, main([before, after, '-o', self.out, '--only', 'hmi']))
        with open(self.out, encoding='utf-8') as f:
            self.assertIn('data-key="screen:Filler"', f.read())

    def run_on_locked(self, locked, *args):
        """(exit code, stderr) of the report while another program holds the file locked (repo-relative)."""
        from TiaChangeReports.__main__ import main
        full = os.path.join(self.repo, *locked.split('/'))
        err = io.StringIO()
        with open(full, 'r+b') as f:
            size = os.path.getsize(full)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, size)
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = main([*args, '-o', self.out, '--only', 'hmi'])
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, size)
        return code, err.getvalue()

    def test_a_locked_file_nothing_reads_stops_no_report(self):
        _put(self.repo, {'hmi/references/other/screens/Copy.xml': screen('Copy', 20)})
        after = os.path.join(self.repo, '..', 'a')
        shutil.copytree(os.path.join(self.repo, 'hmi'), os.path.join(after, 'hmi'))

        code, _ = self.run_on_locked('hmi/references/other/screens/Copy.xml', self.repo, after)

        self.assertEqual(0, code)

    def test_a_locked_reference_of_the_working_tree_stops_no_report(self):
        _put(self.repo, {'hmi/references/other/screens/Copy.xml': screen('Copy', 20)})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'reference')

        code, _ = self.run_on_locked('hmi/references/other/screens/Copy.xml', '--git', self.repo, 'HEAD')

        self.assertEqual(0, code)

    def test_a_locked_document_of_a_folder_ends_in_a_message_naming_it(self):
        after = os.path.join(self.repo, '..', 'a')
        shutil.copytree(os.path.join(self.repo, 'hmi'), os.path.join(after, 'hmi'))

        code, err = self.run_on_locked('hmi/screens/Door.xml', self.repo, after)

        self.assertEqual(2, code)
        self.assertIn('Door.xml', err)
        self.assertFalse(os.path.exists(self.out))

    def test_a_locked_document_of_the_working_tree_ends_in_a_message_naming_it(self):
        code, err = self.run_on_locked('hmi/screens/Units/Filler.xml', '--git', self.repo, 'HEAD~1')

        self.assertEqual(2, code)
        self.assertIn('cannot read', err)
        self.assertIn('Filler.xml', err)

    def test_a_locked_data_file_of_the_working_tree_ends_in_a_message_naming_it(self):
        names = ('handbuilt.json', 'panel.json')
        _put(self.repo, {'hmi/' + n: '{}' for n in names})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'data')
        for n in names:                       # older than the index: git takes it as unchanged and reads no byte of it
            os.utime(os.path.join(self.repo, 'hmi', n), (1700000000, 1700000000))
        _git(self.repo, 'update-index', '--refresh')

        for n in names:
            code, err = self.run_on_locked('hmi/' + n, '--git', self.repo, 'HEAD')

            self.assertEqual((2, True), (code, n in err), err)

    def test_a_value_error_of_building_the_page_is_no_message(self):
        from TiaChangeReports import __main__ as cli
        with mock.patch.object(cli.hmi, 'HmiPart', side_effect=ValueError('a bug')):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'a bug'):
                cli.main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', self.out, '--only', 'hmi'])

    def test_fragment_carries_its_data_and_script(self):
        _, frag = self.main('--fragment')

        self.assertTrue(frag.startswith('<div class="ldiff">'))
        self.assertNotIn('class="rail"', frag)
        self.assertIn('class="hmidata"', frag)
        self.assertIn('const R = (() => {', frag)

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_page_script_parses(self):
        _, html = self.main()
        scripts = re.findall(r'<script>(.*?)</script>', html, flags=re.S)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for i, js in enumerate(scripts):
            p = os.path.join(tmp.name, 's%d.js' % i)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(js)
            r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
            self.assertEqual(0, r.returncode, r.stderr)

    def test_data_holds_no_time(self):
        """The gzip header's time field is empty: the page does not depend on when it was made."""
        _, html = self.main()
        m = re.search(r'class="hmidata">([^<]*)<', html)
        self.assertEqual(base64.b64decode(m.group(1))[4:8], bytes(4))

    def test_two_runs_give_the_same_bytes(self):
        """Also under another hash seed: nothing on the page follows a set's order."""
        pages = set()
        for seed in ('0', '1', '2', '3', '12345'):
            r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'TiaChangeReports', '--git', self.repo, 'HEAD~1', 'HEAD',
                                '-o', self.out], cwd=TOP, env=dict(os.environ, PYTHONHASHSEED=seed),
                               capture_output=True, text=True)
            self.assertEqual(0, r.returncode, r.stderr)
            with open(self.out, 'rb') as f:
                pages.add(f.read())
        self.assertEqual(len(pages), 1)


class ResizedObject(unittest.TestCase):
    """A change of an object's box is told as what it is: moved, resized or both (hmi.js, placeChange)."""

    def place(self, old, new):
        with open(os.path.join(TOP, 'TiaChangeReports', 'hmi.js'), encoding='utf-8') as f:
            fn = re.search(r'^function placeChange\(c\) \{.*?^\}$', f.read(), flags=re.S | re.M).group(0)
        code = '%s;console.log(JSON.stringify(placeChange(%s)))' % (fn, json.dumps({'kind': 'moved', 'old': old, 'new': new}))
        r = subprocess.run(['node', '-e', code], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_words(self):
        box = {'x': 10, 'y': 20, 'w': 100, 'h': 50}
        self.assertEqual(self.place(box, dict(box, x=11)), ['moved', 'Position'])
        self.assertEqual(self.place(box, dict(box, y=21)), ['moved', 'Position'])
        self.assertEqual(self.place(box, dict(box, w=101)), ['resized', 'Size'])
        self.assertEqual(self.place(box, dict(box, h=51)), ['resized', 'Size'])
        self.assertEqual(self.place(box, dict(box, x=11, h=51)), ['moved and resized', 'Position and size'])


class DrawnOnThePage(unittest.TestCase):
    """A point moved inside its box and another tag in a text field, in a browser: told, outlined on both sides; the point marked, the field
    not drawn (the export does not hold what TIA shows there)."""

    @staticmethod
    def wire(points):
        return ('<Hmi.Screen.Polyline ID="2" CompositionName="ScreenItems"><AttributeList><Color>0, 0, 0</Color>'
                '<LineWidth>1</LineWidth><ObjectName>wire</ObjectName><Points>\ufeff%s</Points></AttributeList>'
                '</Hmi.Screen.Polyline>' % ''.join('&lt;Item&gt;%d, %d&lt;/Item&gt;' % p for p in points))

    @staticmethod
    def label(tag):
        return ('<Hmi.Screen.TextField ID="3" CompositionName="ScreenItems"><AttributeList><Height>30</Height><Left>10'
                '</Left><ObjectName>lbl</ObjectName><Top>200</Top><Width>400</Width></AttributeList><ObjectList>'
                '<Hmi.Globalization.MultiLingualFont ID="4" CompositionName="Font"><ObjectList>'
                '<Hmi.Globalization.FontItem ID="5" CompositionName="Items"><AttributeList><Culture>en-US</Culture>'
                '<FontFamily>Tahoma</FontFamily><FontSize>13</FontSize><FontStyle>Regular</FontStyle></AttributeList>'
                '</Hmi.Globalization.FontItem></ObjectList></Hmi.Globalization.MultiLingualFont>'
                '<MultilingualText ID="6" CompositionName="Text"><ObjectList><MultilingualTextItem ID="7" '
                'CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text><body><p>Mode: <field ref="0" />'
                '</p></body><fieldinfos><fieldinfo name="0" domaintype="HMICommonTextList"><reference '
                'TargetID="@OpenLink"><name>Vendor.Hmi.Lists.HmiTextList:Modes</name></reference><subreference '
                'TargetID="@OpenLink"><name>Vendor.Hmi.Tag.HmiTag:%s</name></subreference></fieldinfo></fieldinfos>'
                '</Text></AttributeList></MultilingualTextItem></ObjectList></MultilingualText></ObjectList>'
                '</Hmi.Screen.TextField>' % tag)

    def test_a_moved_point_is_marked_and_a_field_is_told_in_the_row_alone(self):
        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, self.wire([(10, 10), (50, 90), (90, 10)])
                                                        + self.label('modeNow'))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, self.wire([(10, 10), (60, 90), (90, 10)])
                                                        + self.label('modeNext'))}, '#screen%3ASilo')

        self.assertEqual([('50', '90'), ('60', '90')], re.findall(r'<circle[^>]*\bcx="(\d+)" cy="(\d+)"', dom))
        self.assertIn('10, 10; 50, 90; 90, 10', re.sub(r'</?span>', '', dom))
        self.assertIn('10, 10; 60, 90; 90, 10', re.sub(r'</?span>', '', dom))
        self.assertEqual(['Mode: ', 'Mode: '], re.findall(r'<text[^>]*>(Mode: [^<]*)</text>', dom))
        self.assertEqual(2, len(re.findall(r'<rect[^>]*class="changed"[^>]*data-name="lbl"', dom)))
        row = re.sub(r'</?span>', '', dom)
        self.assertIn('Mode: {HMICommonTextList, HmiTextList:Modes, HmiTag:modeNow}', row)
        self.assertIn('Mode: {HMICommonTextList, HmiTextList:Modes, HmiTag:modeNext}', row)

    def page(self, before_files, after_files, url_end, script=''):
        """The DOM of the report of those two sides, with that end of its address (#object, ?all) and that script
        added to the page."""
        edge, url = self.browser_and_url(before_files, after_files, url_end, script)
        return edge.dump_dom(url, timeout=120, size=(1400, 1000))

    def browser_and_url(self, before_files, after_files, url_end, script):
        """A browser and the address of the report of those two sides, as page."""
        from TiaChangeReports.__main__ import main
        from TiaChangeReports.tests import host_styles
        edge = host_styles.browser()
        if edge is None:
            self.skipTest('no Edge or Chrome')
        self.addCleanup(edge.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        before, after, out = (os.path.join(tmp.name, n) for n in ('before', 'after', 'p.html'))
        _put(before, before_files)
        _put(after, after_files)
        for rel in after_files:       # a folder side knows a file by its size and time: same size, same clock tick
            os.utime(os.path.join(after, rel), (1, 1))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, main([before, after, '-o', out]))
        if script:
            text = pathlib.Path(out).read_text(encoding='utf-8')
            head, end, tail = text.rpartition('</body>')
            pathlib.Path(out).write_text(head + script + end + tail, encoding='utf-8')
        return edge, pathlib.Path(out).as_uri() + url_end

    @staticmethod
    def line(sx, sy, ex, ey):
        ends = (('EndLeft', ex), ('EndTop', ey), ('StartLeft', sx), ('StartTop', sy))
        return ('<Hmi.Screen.Line ID="2" CompositionName="ScreenItems"><AttributeList><Color>0, 0, 0</Color><LineWidth>1'
                '</LineWidth><ObjectName>wire</ObjectName>%s</AttributeList></Hmi.Screen.Line>'
                % ''.join('<%s>%d</%s>' % (k, v, k) for k, v in ends if v is not None))

    def test_a_mirrored_line_with_an_end_left_out_is_outlined_marked_and_named_as_incomplete(self):
        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, self.line(10, None, 50, 40))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, self.line(50, None, 10, 40))}, '#screen%3ASilo')

        self.assertEqual([('10', '0'), ('50', '40'), ('50', '0'), ('10', '40')],
                         re.findall(r'<circle[^>]*\bcx="(\d+)" cy="(\d+)"', dom))
        self.assertEqual(2, len(re.findall(r'<rect[^>]*class="changed"[^>]*data-name="wire"', dom)))
        self.assertEqual(2, len(re.findall(r'<g[^>]*data-missing="[^"]*StartTop', dom)))

    def test_a_line_replaced_by_a_polyline_in_its_box_is_outlined_and_told_in_a_row(self):
        wire = ('<Hmi.Screen.Polyline ID="2" CompositionName="ScreenItems"><AttributeList><Color>0, 0, 0</Color><LineWidth>1'
                '</LineWidth><ObjectName>wire</ObjectName><Points>\ufeff&lt;Item&gt;10, 10&lt;/Item&gt;&lt;Item&gt;50, 40'
                '&lt;/Item&gt;</Points></AttributeList></Hmi.Screen.Polyline>')
        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, self.line(10, 10, 50, 40))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, wire)}, '#screen%3ASilo')

        self.assertEqual(2, len(re.findall(r'<rect[^>]*class="changed"[^>]*data-name="wire"', dom)))
        self.assertRegex(re.sub(r'</?span>', '', dom), r'Object type</td><td[^>]*>Line</td><td[^>]*>Polyline</td>')
        self.assertNotIn('<details class="hf"', dom)

    def test_an_object_that_lost_its_box_is_told_in_a_row(self):
        bare = ('<Hmi.Screen.Rectangle ID="2" CompositionName="ScreenItems"><AttributeList><ObjectName>door</ObjectName>'
                '</AttributeList></Hmi.Screen.Rectangle>')

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, rect('door', left=10))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, bare)}, '#screen%3ASilo')

        shown = re.sub(r'</?span>', '', dom)
        self.assertIn('Position and size', shown)
        self.assertIn('(10, 100) 40 x 40', shown)

    def test_a_line_with_nothing_written_is_labelled_not_drawn(self):
        def bare(color):
            return self.line(None, None, None, None).replace('0, 0, 0', color)

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, bare('1, 1, 1'))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, bare('2, 2, 2'))}, '#screen%3ASilo')

        self.assertIn('not drawn: Line', dom)
        self.assertEqual(2, len(re.findall(r'<g[^>]*class="[^"]*not-drawn', dom)))

    def test_another_object_with_an_end_written_is_drawn_at_its_own_box(self):
        def moved(left):
            return rect('door', left=left).replace('<ObjectName>', '<StartLeft>5</StartLeft><ObjectName>')

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, moved(10))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, moved(200))}, '#screen%3ASilo')

        self.assertRegex(dom, r'<g[^>]*data-name="door"[^>]*data-x="200"')
        self.assertIn('(10, 100) 40 x 40', re.sub(r'</?span>', '', dom))

    def test_a_mirrored_line_is_marked_and_told(self):
        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, self.line(10, 10, 50, 40))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, self.line(50, 10, 10, 40))}, '#screen%3ASilo')

        self.assertEqual([('10', '10'), ('50', '40'), ('50', '10'), ('10', '40')],
                         re.findall(r'<circle[^>]*\bcx="(\d+)" cy="(\d+)"', dom))
        shown = re.sub(r'</?span>', '', dom)
        self.assertIn('10, 10; 50, 40', shown)
        self.assertIn('50, 10; 10, 40', shown)

    def test_an_added_field_names_its_tag_mode_and_text_list_on_the_page(self):
        field = ('<Hmi.Screen.SymbolicIOField ID="2" CompositionName="ScreenItems"><AttributeList><Height>40</Height>'
                 '<Left>10</Left><Mode>Output</Mode><ObjectName>zzField</ObjectName><Top>10</Top><Width>120</Width>'
                 '</AttributeList><LinkList><TextList TargetID="@OpenLink"><Name>zzList</Name></TextList></LinkList>'
                 '<ObjectList><Hmi.Screen.Property ID="3" CompositionName="Properties"><AttributeList>'
                 '<Name>ProcessValue</Name></AttributeList><ObjectList><Hmi.Dynamic.TagConnectionDynamic ID="4" '
                 'CompositionName="Dynamic"><LinkList><Tag TargetID="@OpenLink"><Name>zzT1</Name></Tag></LinkList>'
                 '</Hmi.Dynamic.TagConnectionDynamic></ObjectList></Hmi.Screen.Property></ObjectList>'
                 '</Hmi.Screen.SymbolicIOField>')

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1)}, {'hmi/screens/Silo.xml': screen('Silo', 1, field)},
                        '#screen%3ASilo')

        rows = re.findall(r'<tr><td class="p">([^<]*)</td><td[^>]*></td><td class="w">([^<]*)</td></tr>', dom)
        self.assertEqual([('Mode', 'Output'), ('TextList link', 'zzList'), ('Property/Name', 'ProcessValue'),
                          ('Property/TagConnectionDynamic/Tag', 'zzT1')], rows)

    FIELD = ('<Hmi.Screen.IOField ID="2" CompositionName="ScreenItems"><AttributeList><Height>40</Height>'
             '<Left>10</Left><Mode>Output</Mode><ObjectName>%s</ObjectName><Top>10</Top><Width>120</Width>'
             '</AttributeList><ObjectList><Hmi.Screen.Property ID="3" CompositionName="Properties"><AttributeList>'
             '<Name>ProcessValue</Name></AttributeList><ObjectList><Hmi.Dynamic.TagConnectionDynamic ID="4" '
             'CompositionName="Dynamic"><LinkList><Tag TargetID="@OpenLink"><Name>zzT1</Name></Tag></LinkList>'
             '</Hmi.Dynamic.TagConnectionDynamic></ObjectList></Hmi.Screen.Property></ObjectList>'
             '</Hmi.Screen.IOField>')

    # Waits for the HMI part, then runs a test's steps. They have key(k), row(name), triangle(row), state(names) and
    # fill out, which ends up in data-fold.
    ROW_PROBE = """<script>
    window.addEventListener('load', function () {
      var tries = 0, t = setInterval(function () {
        if (document.querySelector('.ldiff').getAttribute('data-hmi') !== 'ready' && ++tries < 400) return;
        clearInterval(t);
        function key(k) { document.body.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true})); }
        function row(n) { return document.querySelector('.hc[data-name="' + n + '"]'); }
        function triangle(c) {
          var e = c.querySelector('.ht'), s = e && getComputedStyle(e, '::before');
          return !e ? null : s.borderTopWidth === '6px' ? 'open' : s.borderLeftWidth === '6px' ? 'shut' : 'other';
        }
        function state(names) {
          return names.map(function (n) {
            var c = row(n), rows = c.querySelector('table.hd');
            return [n, rows && getComputedStyle(rows).display !== 'none', triangle(c)];
          });
        }
        var out = {};
        STEPS
        document.body.setAttribute('data-fold', JSON.stringify(out));
      }, 25);
    });
    </script>"""

    def test_c_and_e_collapse_and_expand_the_rows_of_an_added_object(self):
        probe = self.ROW_PROBE.replace('STEPS', """
            var names = ['zzField', 'box'];
            out.start = state(names);
            key('c'); out.collapsed = state(names); out.head = row('zzField').querySelector('.hw').textContent;
            key('l'); out.afterRedraw = state(names);
            key('e'); out.expanded = state(names);""")

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1, rect('box'))},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, rect('box', left=30) + self.FIELD % 'zzField')},
                        '#screen%3ASilo', probe)

        out = json_attribute(dom, 'data-fold')
        opened = [['zzField', True, 'open'], ['box', True, None]]
        shut = [['zzField', False, 'shut'], ['box', True, None]]
        self.assertEqual(opened, out['start'])
        self.assertEqual(shut, out['collapsed'])
        self.assertEqual(shut, out['afterRedraw'])
        self.assertEqual(opened, out['expanded'])
        self.assertEqual('zzFieldIOFieldadded', out['head'])

    def test_a_click_on_the_triangle_folds_that_row_only_and_a_click_beside_it_selects(self):
        probe = self.ROW_PROBE.replace('STEPS', """
            var names = ['zzOne', 'zzTwo'];
            function click(e) { e.dispatchEvent(new MouseEvent('click', {bubbles: true})); }
            click(row('zzOne').querySelector('.ht'));
            out.clicked = state(names); out.selected = row('zzOne').classList.contains('sel');
            key('l'); out.afterRedraw = state(names);
            click(row('zzOne').querySelector('.ht')); out.clickedAgain = state(names);
            click(row('zzTwo').querySelector('.hw b'));
            out.beside = state(names); out.selectedBeside = row('zzTwo').classList.contains('sel');
            key('c'); click(row('zzTwo').querySelector('.ht')); out.afterC = state(names);
            key('e'); out.afterE = state(names);""")
        added = self.FIELD % 'zzOne' + self.FIELD % 'zzTwo'

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1)},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, added)}, '#screen%3ASilo', probe)

        out = json_attribute(dom, 'data-fold')
        opened = [['zzOne', True, 'open'], ['zzTwo', True, 'open']]
        one_shut = [['zzOne', False, 'shut'], ['zzTwo', True, 'open']]
        self.assertEqual(one_shut, out['clicked'])
        self.assertFalse(out['selected'])
        self.assertEqual(one_shut, out['afterRedraw'])
        self.assertEqual(opened, out['clickedAgain'])
        self.assertEqual(opened, out['beside'])
        self.assertTrue(out['selectedBeside'])
        self.assertEqual(one_shut, out['afterC'])
        self.assertEqual(opened, out['afterE'])

    def test_an_added_object_with_no_rows_has_no_triangle(self):
        probe = self.ROW_PROBE.replace('STEPS', "out.start = state(['plain']);")

        dom = self.page({'hmi/screens/Silo.xml': screen('Silo', 1)},
                        {'hmi/screens/Silo.xml': screen('Silo', 1, rect('plain'))}, '#screen%3ASilo', probe)

        self.assertEqual([['plain', None, None]], json_attribute(dom, 'data-fold')['start'])

    def test_the_triangle_of_a_row_is_the_one_of_a_network_open_and_shut(self):
        probe = self.ROW_PROBE.replace('STEPS', """
            var parts = ['borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'borderTopColor',
                         'borderLeftColor', 'borderTopStyle', 'left', 'marginTop'];
            function look(e) {
              var s = getComputedStyle(e, '::before');
              return parts.map(function (p) { return s[p]; });
            }
            var net = document.querySelector('.nw .nwt'), mine = row('zzField').querySelector('.ht');
            out.netOpen = look(net); out.rowOpen = look(mine);
            net.parentNode.classList.add('fold'); key('c');
            out.netShut = look(net); out.rowShut = look(mine);""")
        block = {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES}
        changed = {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), 'plc/A.s7res': RES}

        dom = self.page({**block, 'hmi/screens/Silo.xml': screen('Silo', 1)},
                        {**changed, 'hmi/screens/Silo.xml': screen('Silo', 1, self.FIELD % 'zzField')},
                        '#screen%3ASilo', probe)

        out = json_attribute(dom, 'data-fold')
        self.assertEqual(out['netOpen'], out['rowOpen'])
        self.assertEqual(out['netShut'], out['rowShut'])
        self.assertNotEqual(out['rowOpen'], out['rowShut'])

    def test_c_and_e_on_a_block_fold_its_networks_and_leave_the_screen_as_it_was(self):
        probe = """<script>
        window.addEventListener('load', function () {
          var tries = 0, t = setInterval(function () {
            if (document.querySelector('.ldiff').getAttribute('data-hmi') !== 'ready' && ++tries < 400) return;
            clearInterval(t);
            function key(k) { document.body.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true})); }
            function folded() { return document.querySelectorAll('section.blk.on .nw.fold').length; }
            var out = {start: folded()};
            key('c'); out.collapsed = folded();
            key('e'); out.expanded = folded();
            key('c');
            location.hash = '#screen%3ASilo';
            setTimeout(function () {
              out.screen = !!document.querySelector('section.blk.hmi.on .hc.added:not(.shut)');
              document.body.setAttribute('data-fold', JSON.stringify(out));
            }, 200);
          }, 25);
        });
        </script>"""
        block = {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES}
        changed = {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), 'plc/A.s7res': RES}

        dom = self.page({**block, 'hmi/screens/Silo.xml': screen('Silo', 1)},
                        {**changed, 'hmi/screens/Silo.xml': screen('Silo', 1, rect('box'))}, '#A', probe)

        out = json_attribute(dom, 'data-fold')
        self.assertEqual(0, out['start'])
        self.assertGreater(out['collapsed'], 0)
        self.assertEqual(0, out['expanded'])
        self.assertTrue(out['screen'])

    def test_a_deleted_tag_only_in_fields_is_still_used_by_the_screen_and_the_list(self):
        field = re.search(r'<MultilingualText .*</MultilingualText>', self.label('modeNow')).group()
        modes = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
                 '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>Modes</Name></AttributeList><ObjectList>'
                 '<Hmi.TextGraphicList.TextListEntry ID="1" CompositionName="Entries"><AttributeList><From>1</From>'
                 '<To>1</To></AttributeList><ObjectList>%s</ObjectList></Hmi.TextGraphicList.TextListEntry>'
                 '</ObjectList></Hmi.TextGraphicList.TextList></Document>\n' % field)
        same = {'hmi/screens/Silo.xml': screen('Silo', 1, self.label('modeNow')), 'hmi/textlists/Modes.xml': modes}

        dom = self.page(dict(same, **{'hmi/tags/Plant.xml': tag_table('Plant', [('Keep', '1 s'), ('modeNow', '1 s')])}),
                        dict(same, **{'hmi/tags/Plant.xml': tag_table('Plant', [('Keep', '1 s')])}),
                        '#tagtable%3APlant')

        self.assertRegex(dom, r'Deleted, still used by\s*<(a|span)\b[^>]*>Silo</\1>, <(a|span)\b[^>]*>Modes</\2>')

    @staticmethod
    def text_list(*texts):
        """A text list Modes with an entry of each text, valued from 1; 3 * n keeps the IDs of the entries apart."""
        entries = ''.join(
            '<Hmi.TextGraphicList.TextListEntry ID="%d" CompositionName="Entries"><AttributeList><From>%d</From><To>%d</To>'
            '</AttributeList><ObjectList><MultilingualText ID="%d" CompositionName="Text"><ObjectList><MultilingualTextItem '
            'ID="%d" CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text><body><p>%s</p></body></Text>'
            '</AttributeList></MultilingualTextItem></ObjectList></MultilingualText></ObjectList>'
            '</Hmi.TextGraphicList.TextListEntry>' % (3 * n, n, n, 3 * n + 1, 3 * n + 2, t) for n, t in enumerate(texts, 1))
        return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><Hmi.TextGraphicList.TextList '
                'ID="0"><AttributeList><Name>Modes</Name></AttributeList><ObjectList>%s</ObjectList>'
                '</Hmi.TextGraphicList.TextList></Document>\n' % entries)

    def test_a_deleted_text_list_shows_its_entries_as_removed_and_no_table(self):
        same = {'hmi/screens/Silo.xml': screen('Silo', 1)}

        dom = self.page(dict(same, **{'hmi/textlists/Modes.xml': self.text_list('Auto')}), same, '#textlist%3AModes')

        self.assertRegex(re.sub(r'</?span>', '', dom), r'>removed<.*?<td class="o">Auto</td><td class=""></td>')
        self.assertNotIn('class="sum hlt"', dom)
        self.assertNotRegex(dom, r'>\s*null\s*<')

    def test_a_text_list_that_lost_every_entry_shows_no_table(self):
        dom = self.page({'hmi/textlists/Modes.xml': self.text_list('Auto')}, {'hmi/textlists/Modes.xml': self.text_list()},
                        '#textlist%3AModes')

        self.assertRegex(re.sub(r'</?span>', '', dom), r'>removed<.*?<td class="o">Auto</td><td class=""></td>')
        self.assertNotIn('class="sum hlt"', dom)
        self.assertNotRegex(dom, r'>\s*null\s*<')

    def test_a_changed_text_list_keeps_its_table(self):
        dom = self.page({'hmi/textlists/Modes.xml': self.text_list('Auto')},
                        {'hmi/textlists/Modes.xml': self.text_list('Manual')}, '#textlist%3AModes')

        self.assertRegex(dom, r'(?s)class="sum hlt".*>Manual<')
        self.assertNotRegex(dom, r'>\s*null\s*<')

    LOGO = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Hmi.Globalization.MultiLingualGraphic ID="0">'
            '<AttributeList><DefaultImageStream external="path">Logo files\\DefaultImageStream.png'
            '</DefaultImageStream><Name>Logo</Name></AttributeList></Hmi.Globalization.MultiLingualGraphic></Document>\n')

    def logo_in(self, folder):
        """The graphic Logo in that folder of the project graphics, beside a screen."""
        top = 'project/graphics/' + (folder + '/' if folder else '')
        return {'hmi/screens/Silo.xml': screen('Silo', 1), top + 'Logo.xml': self.LOGO,
                top + 'Logo files/DefaultImageStream.png': 'one'}

    def test_a_graphic_deleted_added_or_only_moved_says_no_word_of_no_changes(self):
        silo = {'hmi/screens/Silo.xml': screen('Silo', 1)}
        for name, before, after in (('deleted', self.logo_in(''), silo), ('added', silo, self.logo_in('')),
                                    ('moved', self.logo_in(''), self.logo_in('Icons'))):
            with self.subTest(name):
                dom = self.page(before, after, '#graphic%3ALogo')

                self.assertIn('class="hv" data-drawn="1"', dom)
                self.assertNotIn('No changes', dom)

    # Writes data-scales on the body: per layout and mode the drawn scale and width of each side shown (toggle: the
    # first view and the one after Space); the width the scroll bars take; the width a pane has for a drawing.
    SCALES_SCRIPT = """<script>(function () {
      function measure() {
        var o = {};
        document.querySelectorAll('section.blk.hmi.on .hp, .ldiff:not(.one) .hp').forEach(function (p) {
          var s = p.querySelector('svg.hs'), box = s && s.getBoundingClientRect(), v = s && s.viewBox.baseVal;
          if (s && box.width) o[p.classList.contains('before') ? 'before' : 'after'] = {x: box.width / v.width, y: box.height / v.height, width: box.width};
        });
        return o;
      }
      function layout(name) {
        [].find.call(document.querySelectorAll('.htb button'), function (b) { return b.textContent === name; }).click();
      }
      var wait = setInterval(function () {
        if (!document.querySelector('.hv[data-drawn] svg.hs')) return;
        clearInterval(wait);
        var out = {fit: measure(), bar: 0, room: 0}, b = document.querySelector('.htb button[title^="Fit"]');
        document.querySelectorAll('.hb').forEach(function (e) {
          var c = getComputedStyle(e);
          out.bar = Math.max(out.bar, e.offsetWidth - e.clientWidth);
          out.room = e.clientWidth - parseFloat(c.paddingLeft) - parseFloat(c.paddingRight);
        });
        if (b) {
          b.click();
          out.full = measure();
          document.querySelector('.htb button[title^="Fit"]').click();
          layout('Stacked');
          out.stacked = measure();
          layout('Toggle');
          out.toggle = measure();
          document.body.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true}));
          out.switched = measure();
        }
        document.body.setAttribute('data-scales', JSON.stringify(out));
      }, 50);
    })();</script>"""

    @staticmethod
    def popup(w, hh):
        """A pop-up of that size with a rectangle filling it."""
        frame = (rect('zzFrame').replace('<Height>40</Height>', '<Height>%d</Height>' % hh)
                 .replace('<Left>10</Left>', '<Left>0</Left>').replace('<Top>100</Top>', '<Top>0</Top>')
                 .replace('<Width>40</Width>', '<Width>%d</Width>' % w))
        return {'hmi/popups/Pop.xml': screen('Pop', 1, frame, kind='ScreenPopup').replace(
            ROOT_ATTRS, '<BackColor>255, 255, 255</BackColor><Height>%d</Height><Width>%d</Width>' % (hh, w))}

    def scales(self, before, after, url_end='#popup%3APop'):
        """The drawn scales of a pop-up of size before -> size after."""
        dom = self.page(self.popup(*before), self.popup(*after), url_end, self.SCALES_SCRIPT)
        return json_attribute(dom, 'data-scales')

    def assert_one_scale(self, sides):
        for axis in ('x', 'y'):
            self.assertAlmostEqual(sides['before'][axis], sides['after'][axis], places=3, msg=sides)

    def test_a_wider_pop_up_is_drawn_wider_at_the_scale_of_the_narrower_side(self):
        got = self.scales((440, 240), (520, 240))

        self.assert_one_scale(got['fit'])
        self.assertEqual(got['room'], got['fit']['after']['width'])           # the wider side still fills the pane
        self.assertAlmostEqual(440 / 520, got['fit']['before']['width'] / got['fit']['after']['width'], places=2)
        self.assertEqual(got['full'], {'before': {'x': 1, 'y': 1, 'width': 440}, 'after': {'x': 1, 'y': 1, 'width': 520}})

    def test_a_narrower_pop_up_is_drawn_narrower(self):
        got = self.scales((520, 240), (440, 240))

        self.assert_one_scale(got['fit'])
        self.assertAlmostEqual(440 / 520, got['fit']['after']['width'] / got['fit']['before']['width'], places=2)

    def test_a_taller_pop_up_is_drawn_taller(self):
        got = self.scales((440, 240), (440, 300))['fit']

        self.assert_one_scale(got)
        self.assertGreater(got['after']['y'] * 300, got['before']['y'] * 240)

    def test_a_scroll_bar_on_one_side_takes_nothing_from_its_scale(self):
        run = subprocess.run

        def with_scroll_bars(args, **kw):
            return run([a for a in args if a != '--hide-scrollbars'], **kw)
        with mock.patch('subprocess.run', with_scroll_bars):
            got = self.scales((440, 240), (440, 1200))

        self.assertGreater(got['bar'], 0)
        self.assert_one_scale(got['fit'])

    def test_stacked_draws_one_scale(self):
        got = self.scales((440, 240), (520, 240))

        self.assert_one_scale(got['stacked'])
        self.assertAlmostEqual(440 / 520, got['stacked']['before']['width'] / got['stacked']['after']['width'], places=2)
        self.assertGreater(got['stacked']['after']['width'], got['fit']['after']['width'])    # the panes are wider

    def test_toggle_draws_one_scale_across_the_switch(self):
        got = self.scales((440, 240), (520, 240))

        self.assertEqual(['after'], list(got['toggle']))
        self.assertEqual(['before'], list(got['switched']))
        self.assert_one_scale({'before': got['switched']['before'], 'after': got['toggle']['after']})
        self.assertAlmostEqual(440 / 520, got['switched']['before']['width'] / got['toggle']['after']['width'], places=2)

    def test_the_divider_alone_stands_between_the_panes(self):
        import PIL.Image
        script = """<script>var wait = setInterval(function () {
          if (!document.querySelector('.hv[data-drawn] svg.hs')) return;
          clearInterval(wait);
          var b = document.querySelector('section.blk.hmi.on .hps').getBoundingClientRect();
          document.body.setAttribute('data-panes', JSON.stringify([b.left, b.top]));
        }, 50);</script>"""
        edge, url = self.browser_and_url(self.popup(440, 240), self.popup(520, 240), '#popup%3APop', script)
        dom = edge.dump_dom(url, timeout=120, size=(1400, 1000))
        left, top = json_attribute(dom, 'data-panes')
        with tempfile.TemporaryDirectory() as folder:
            with PIL.Image.open(edge.screenshot(url, os.path.join(folder, 'p.png'), 1400, 1000)) as picture:
                shown = picture.convert('RGB')
                row = [shown.getpixel((x, round(top) + 3)) for x in range(round(left), shown.width)]    # above the drawings

        runs = [c for i, c in enumerate(row) if i == 0 or c != row[i - 1]]
        grey = (127, 127, 127)
        self.assertEqual(6, len(runs), runs)                                   # frame, pane, divider, pane, frame, page
        self.assertEqual((grey, grey), (runs[1], runs[3]), runs)
        self.assertEqual(runs[0], runs[4], runs)
        self.assertNotEqual(grey, runs[2])

    def test_all_on_one_page_draws_one_scale(self):
        self.assert_one_scale(self.scales((440, 240), (520, 240), '?all')['fit'])


if __name__ == '__main__':
    unittest.main()
