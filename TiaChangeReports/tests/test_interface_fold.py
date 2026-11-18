"""A member with members folds and opens in the interface table, in the report and in the viewer, by the same code
(iface.py, page.py); in the report a fold that hides a changed row says that it holds a change."""
import contextlib
import io
import itertools
import json
import os
import pathlib
import re
import tempfile
import unittest
from html import unescape

from TiaChangeReports import __main__ as cli
from TiaChangeReports.tests import host_styles
from TiaChangeReports.tests.test_tia_look import _write
from TiaChangeReports.viewer import view


def _fb(static, temp=''):
    return ('FUNCTION_BLOCK "Mixer"\n    VAR\n%s    END_VAR\n%sEND_FUNCTION_BLOCK\n'
            % (static, '    VAR_TEMP\n%s    END_VAR\n' % temp if temp else ''))


MIXER = '''        s : STRUCT
            a : Bool;
            inner : STRUCT
                x : Int;
            END_STRUCT;
            b : Int;
        END_STRUCT;
        c : Bool;
        d : Int;
'''
BEFORE, AFTER = _fb(MIXER), _fb(MIXER.replace('b : Int;', 'b : DInt;'))
NETWORK = '''    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #c )
            Coil( #c )
        END_RUNG
    END_NETWORK
'''
# Input and Static, a change in each.
SECTIONS = tuple(t.replace('    VAR\n', '    VAR_INPUT\n        go : %s;\n    END_VAR\n    VAR\n' % g, 1)
                 for t, g in ((BEFORE, 'Bool'), (AFTER, 'Int')))
# Those with a network, changed in the after side as its members are.
WITH_NETWORK = tuple(t.replace('END_FUNCTION_BLOCK', NETWORK + 'END_FUNCTION_BLOCK') for t in SECTIONS)
WITH_NETWORK = WITH_NETWORK[0], WITH_NETWORK[1].replace('Contact( #c )', 'Contact( #s.a )')


def _udt(members):
    return 'TYPE\n    "typeLine" : STRUCT\n%s    END_STRUCT;\nEND_TYPE\n' % members


# A UDT with a struct one level deep, a member of it changed: the audit's case of 2026-11-18, fifth round.
LINE_MEMBERS = '        speed : Int;\n        motor : STRUCT\n            run : Bool;\n            fault : Bool;\n        END_STRUCT;\n'
TYPE_LINE = _udt(LINE_MEMBERS), _udt(LINE_MEMBERS.replace('fault : Bool;', 'fault : Int;'))

# Changes a fold could hide, as (before, after): the audit's cases of 2026-11-18, where the diff places a removed
# member elsewhere than under its own struct, and a change beside unchanged members that a "show all" opens.
CASES = {
    'renamed struct, a member removed': (
        _fb('        S : STRUCT\n            x : Bool;\n            y : Int;\n        END_STRUCT;\n        z : Bool;\n'),
        _fb('        S2 : STRUCT\n            y : Int;\n        END_STRUCT;\n        z : Bool;\n')),
    'struct moved to Temp, a member removed': (
        _fb('        U : STRUCT\n            p : Bool;\n        END_STRUCT;\n'
            '        S : STRUCT\n            a : Bool;\n            b : Int;\n        END_STRUCT;\n'),
        _fb('        U : STRUCT\n            p : Bool;\n        END_STRUCT;\n',
            '        S : STRUCT\n            a : Bool;\n        END_STRUCT;\n')),
    'one change beside unchanged members': (
        _fb('        s : STRUCT\n            a : Bool;\n            b : Bool;\n        END_STRUCT;\n'
            '        c : Bool;\n        d : Bool;\n'),
        _fb('        s : STRUCT\n            a : Int;\n            b : Bool;\n        END_STRUCT;\n'
            '        c : Bool;\n        d : Bool;\n')),
    'the Mixer': (BEFORE, AFTER),
}
# Folds inside folds: x and c changed, y and z an "unchanged members" row between them.
NESTED_STATIC = '''        s : STRUCT
            inner : STRUCT
                x : Int;
                y : Int;
            END_STRUCT;
            z : Bool;
        END_STRUCT;
        c : Bool;
'''
NESTED = (_fb(NESTED_STATIC), _fb(NESTED_STATIC.replace('x : Int;', 'x : DInt;').replace('c : Bool;', 'c : Int;')))
# A global DB with a UDT member its start value opens, and a Struct of its own.
UDT = '''TYPE
    Hw : STRUCT
        low : Bool;
        high : Bool;
    END_STRUCT;
END_TYPE
'''
LINE = '''DATA_BLOCK LineData
    VAR
        head : _.Hw;
        counters : STRUCT
            good : DInt;
        END_STRUCT;
    END_VAR

        head.low := TRUE;
END_DATA_BLOCK
'''

# The first interface table of the page, its "show all" on when ALL. A row by the text of its name cell (its extras
# left out).
SETUP = ("var t=[].filter.call(document.querySelectorAll('table.itf'),function(x){return x.querySelector('td.nm[data-d]')})[0];"
         "if(ALL&&t.closest('.nw'))t.closest('.nw').classList.add('all');"
         "function name(y){var c=y.cells[0].cloneNode(true);[].forEach.call(c.querySelectorAll('.ex'),function(e){e.remove()});"
         "return c.textContent.replace(/[\\u25b6\\u25bc]/g,'').trim()}"
         "function seen(y){return getComputedStyle(y).display!='none'}"
         "function cell(n){return [].filter.call(t.querySelectorAll('td.nm'),function(c){return name(c.parentNode)==n})[0]}"
         "function mark(y){return getComputedStyle(y.cells[0],'::after').content}")
# Each member that folds, folded alone: its mark, the changed rows it hid, the member rows still shown.
EACH = ("var out=[];[].forEach.call(t.rows,function(x){if(!x.classList.contains('mf-pa'))return;x.cells[0].click();"
        "out.push({row:name(x),mark:mark(x),hidden:[].filter.call(t.rows,function(y){"
        "return /(^|\\s)(ins|del|chg|mov)(\\s|$)/.test(y.className)&&!seen(y)}).map(name),"
        "shown:[].filter.call(t.rows,function(y){return y.cells[0]&&y.cells[0].hasAttribute('data-d')&&"
        "!y.classList.contains('skip')&&seen(y)}).map(name)});x.cells[0].click()});")
# s at first, after a click on inner, on s, on s again.
STEPS = ("var out=[];function note(){var s=cell('s');out.push({b:seen(cell('b').parentNode),x:seen(cell('x').parentNode),"
         "c:seen(cell('c').parentNode),tw:s.querySelector('.tw').textContent,mark:mark(s.parentNode)})}"
         "note();cell('inner').click();note();cell('s').click();note();cell('s').click();note();")
# inner folded, then s: the rows still shown, an "unchanged members" row as skip.
INSIDE = ("cell('inner').click();cell('s').click();var out=[].filter.call(t.rows,function(y){return y.cells[0]&&"
          "y.cells[0].hasAttribute('data-d')&&seen(y)}).map(function(y){return y.classList.contains('skip')?'skip':name(y)});")
# s folded: how its row and c's draw, which no other part's style may tell apart but by the mark.
LOOK = ("cell('s').click();function look(n){var y=cell(n).parentNode,st=getComputedStyle(y);"
        "return [st.borderTopWidth,st.borderTopStyle,st.cursor,st.backgroundColor,getComputedStyle(y.cells[1]).backgroundColor]}"
        "var out={s:look('s'),c:look('c'),mark:mark(cell('s').parentNode)};")
# Each section folded alone: its mark and the member rows still shown; then, all opened again, the rows shown.
SECTION = ("var out=[];function shown(){return [].filter.call(t.rows,function(y){return y.cells[0]&&"
           "y.cells[0].hasAttribute('data-d')&&!y.classList.contains('skip')&&seen(y)}).map(name)}"
           "[].forEach.call(t.rows,function(x){if(!x.classList.contains('sec'))return;x.cells[0].click();"
           "out.push({row:name(x),mark:mark(x),shown:shown()});x.cells[0].click()});out.push(shown());")
# Collapse all, then Expand all, by the block's buttons or by the keys C and E (HOW): the folded rows, the rows shown,
# the sections' marks and the networks folded, at first and after each.
ALL_FOLDS = ("function press(k){if(HOW=='key')document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'ce'[k],bubbles:true}));"
             "else document.querySelectorAll('.bh .fa button')[k].click()}"
             "var out=[];function note(){out.push({shut:[].filter.call(t.rows,function(y){return y.classList.contains('mf-shut')})"
             ".map(name),shown:[].filter.call(t.rows,function(y){return y.cells[0]&&y.cells[0].hasAttribute('data-d')&&"
             "!y.classList.contains('skip')&&seen(y)}).map(name),"
             "marks:[].filter.call(t.rows,function(y){return y.classList.contains('sec')}).map(mark),"
             "nets:document.querySelectorAll('.nw.fold').length})}note();press(0);note();press(1);note();")


def _probe(body, all_=True):
    return ("<script>addEventListener('load',function(){setTimeout(function(){var ALL=%s;%s%s"
            "document.body.setAttribute('data-fold',JSON.stringify(out))},100)})</script>"
            % ('true' if all_ else 'false', SETUP, body))


def _report(folder, before, after):
    _write(folder, {'b/Mixer.s7dcl': before, 'a/Mixer.s7dcl': after})
    out = os.path.join(folder, 'report.html')
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main([os.path.join(folder, 'b', 'Mixer.s7dcl'), os.path.join(folder, 'a', 'Mixer.s7dcl'),
                         '-o', out]) == 0
    with open(out, encoding='utf-8') as f:
        return f.read()


def _viewer(folder, text):
    _write(folder, {'a/Mixer.s7dcl': text})
    return view.page(os.path.join(folder, 'a', 'Mixer.s7dcl'))[0]


class Rows(unittest.TestCase):
    """What the page holds for the script: each member's level, and an "unchanged members" row's."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_the_report_gives_every_member_and_unchanged_run_its_level(self):
        html = _report(self.dir, BEFORE, AFTER)
        self.assertRegex(html, r'<td class="nm" data-d="1" style="[^"]*"><span class="tw">▼</span>s<')
        self.assertRegex(html, r'<td class="nm" data-d="2" style="[^"]*"><span class="tw">[^<]*</span>b<')
        skips = re.findall(r'<tr class="skip"><td colspan="\d+" data-d="(\d+)"', html)
        self.assertEqual(skips, ['2', '1'])         # a, inner, x before b; c, d after it

    def test_an_opened_udts_members_have_their_row_grey(self):
        _write(self.dir, {'b/Hw.s7dcl': UDT, 'b/LineData.s7dcl': LINE, 'a/Hw.s7dcl': UDT,
                          'a/LineData.s7dcl': LINE.replace(':= TRUE', ':= FALSE')})
        out = os.path.join(self.dir, 'report.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([os.path.join(self.dir, 'b'), os.path.join(self.dir, 'a'), '-o', out, '--all']), 0)
        with open(out, encoding='utf-8') as f:
            report = f.read()
        viewer = view.page(os.path.join(self.dir, 'a', 'LineData.s7dcl'))[0]
        for html in (report, viewer):
            self.assertEqual(re.findall(r'data-u style="[^"]*"><span class="tw">[^<]*</span>(\w+)<', html), ['low', 'high'])

    def test_collapse_all_without_networks_only_when_something_folds(self):
        """A section folds, so every block with one has the buttons; a UDT has none, so only a member with members."""
        flat = _fb('        c : Bool;\n'), _fb('        c : Int;\n')
        flat_udt = _udt('        speed : Int;\n'), _udt('        speed : DInt;\n')
        for k, (name, (before, after), want) in enumerate((('nested', (BEFORE, AFTER), True),
                                                           ('flat, a section', flat, True),
                                                           ('UDT, a struct one level deep', TYPE_LINE, True),
                                                           ('UDT, flat', flat_udt, False))):
            with self.subTest(name):
                folder = os.path.join(self.dir, str(k))
                for html in (_report(folder, before, after), _viewer(folder, after)):
                    self.assertEqual('<span class="fa">' in html, want)

    def test_a_section_row_has_level_0(self):
        for html in (_report(self.dir, *SECTIONS), _viewer(self.dir, SECTIONS[1])):
            self.assertEqual(re.findall(r'<td class="nm" data-d="0"><span class="tw">▼</span>(\w+)</td>', html),
                             ['Input', 'Static'])

    def test_the_viewer_gives_every_member_its_level(self):
        html = _viewer(self.dir, AFTER)
        for name, level in (('s', 1), ('a', 2), ('inner', 2), ('x', 3), ('b', 2), ('c', 1)):
            self.assertRegex(html, r'data-d="%d" style="[^"]*"><span class="tw">[^<]*</span>%s<' % (level, name))


class InTheBrowser(unittest.TestCase):
    """The fold itself, in headless Edge or Chrome (no window); skipped without one."""

    @classmethod
    def setUpClass(cls):
        cls.edge = host_styles.browser()
        if cls.edge is None:
            raise unittest.SkipTest('no Microsoft Edge or Google Chrome, or no hmipreview')

    @classmethod
    def tearDownClass(cls):
        cls.edge.close(ignore_errors=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def run_in(self, html, body, all_=True):
        out = os.path.join(self.dir, 'probe.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html.replace('</body>', _probe(body, all_) + '</body>'))
        dom = self.edge.dump_dom(pathlib.Path(out).as_uri(), timeout=120, size=(1400, 1000))
        return json.loads(unescape(re.search(r'data-fold="([^"]*)"', dom).group(1)))

    def test_a_fold_says_it_holds_a_change_exactly_when_it_hides_one(self):
        for k, (case, (before, after)) in enumerate(CASES.items()):
            with self.subTest(case):
                folds = self.run_in(_report(os.path.join(self.dir, str(k)), before, after), EACH)
                self.assertTrue(folds)
                for f in folds:
                    self.assertEqual(f['mark'], '"holds a change"' if f['hidden'] else 'none', f)
                if case == 'renamed struct, a member removed':          # x is drawn under S2
                    self.assertIn('x', [h for f in folds for h in f['hidden']])
                if case == 'one change beside unchanged members':        # all shown: s folds a and b
                    s = next(f for f in folds if f['row'] == 's')
                    self.assertEqual(s['shown'], ['Static', 's', 'c', 'd'])

    def test_a_fold_inside_a_fold_hides_the_unchanged_members_under_both(self):
        html = _report(self.dir, *NESTED)
        for all_ in (False, True):
            with self.subTest(show_all=all_):
                self.assertEqual(self.run_in(html, INSIDE, all_), ['Static', 's', 'c'])

    def test_the_mark_looks_the_same_beside_an_hmi_part(self):
        """A report with HMI changes loads the HMI part's style (hmi.css), whose classes the fold must not share: the
        folded member draws as any other row, but for its mark."""
        from TiaChangeReports import hmi
        html = _report(self.dir, BEFORE, AFTER).replace('</head>', '<style>%s</style></head>' % hmi.css())
        out = self.run_in(html, LOOK)
        self.assertEqual(out['mark'], '"holds a change"')
        self.assertEqual(out['s'], out['c'])

    def test_a_fold_in_the_report_opens_again(self):
        start, inner, shut, again = self.run_in(_report(self.dir, BEFORE, AFTER), STEPS)
        self.assertEqual((start['b'], start['tw'], start['mark']), (True, '▼', 'none'))    # open at first
        self.assertTrue(inner['b'])                                  # a fold of another member leaves b
        self.assertEqual((shut['b'], shut['tw'], shut['mark']), (False, '▶', '"holds a change"'))
        self.assertEqual((again['b'], again['tw'], again['mark']), (True, '▼', 'none'))

    def test_collapse_all_and_expand_all_fold_the_sections_and_members_with_the_networks(self):
        """In the report and in the viewer, by the buttons and by C and E: every section and member with members
        folds (the maintainer's ruling of 2026-11-18), only the section headings stay, each says it holds a change
        when it hides one, and everything opens again."""
        pages = {'report': _report(self.dir, *WITH_NETWORK), 'viewer': _viewer(self.dir, WITH_NETWORK[1])}
        for (where, html), how in itertools.product(pages.items(), ('button', 'key')):
            with self.subTest(where=where, how=how):
                start, shut, opened = self.run_in(html, "var HOW='%s';" % how + ALL_FOLDS)
                every = ['Input', 'go', 'Static', 's', 'a', 'inner', 'x', 'b', 'c', 'd']
                self.assertEqual(start, {'shut': [], 'shown': every, 'marks': ['none', 'none'], 'nets': 0})
                mark = '"holds a change"' if where == 'report' else 'none'
                self.assertEqual(shut, {'shut': ['Input', 'Static', 's', 'inner'], 'shown': ['Input', 'Static'],
                                        'marks': [mark, mark], 'nets': 1})
                self.assertEqual(opened, start)

    def test_a_section_folds_its_members(self):
        """Its heading folds and opens what is under it down to the next section; in the report it says it holds a
        change."""
        every = ['Input', 'go', 'Static', 's', 'a', 'inner', 'x', 'b', 'c', 'd']
        for where, html in (('report', _report(self.dir, *SECTIONS)), ('viewer', _viewer(self.dir, SECTIONS[1]))):
            with self.subTest(where):
                inp, static, opened = self.run_in(html, SECTION)
                mark = '"holds a change"' if where == 'report' else 'none'
                self.assertEqual(inp, {'row': 'Input', 'mark': mark, 'shown': [x for x in every if x != 'go']})
                self.assertEqual(static, {'row': 'Static', 'mark': mark, 'shown': ['Input', 'go', 'Static']})
                self.assertEqual(opened, every)

    def test_a_section_of_an_fc_folds_by_its_one_cell(self):
        """An FC's interface has no attribute columns: a section row is one cell over the table."""
        fc = ('FUNCTION "Mixer" : Void\n    VAR_INPUT\n        go : %s;\n    END_VAR\n    VAR_TEMP\n        t : Int;\n'
              '    END_VAR\nEND_FUNCTION\n')
        html = _report(self.dir, fc % 'Bool', fc % 'Int')
        self.assertRegex(html, r'<tr class="sec"><td colspan="\d+" data-d="0"><span class="tw">▼</span>Input</td>')
        inp, opened = self.run_in(html, SECTION)
        self.assertEqual(inp, {'row': 'Input', 'mark': '"holds a change"', 'shown': ['Input']})
        self.assertEqual(opened, ['Input', 'go'])

    def test_a_struct_folds_in_the_viewer_and_one_inside_it_stays_folded(self):
        start, inner, shut, again = self.run_in(_viewer(self.dir, AFTER), STEPS)
        self.assertEqual((start['x'], start['b'], start['c']), (True, True, True))
        self.assertEqual((inner['x'], inner['b']), (False, True))
        self.assertEqual((shut['x'], shut['b'], shut['c'], shut['tw'], shut['mark']), (False, False, True, '▶', 'none'))
        self.assertEqual((again['x'], again['b']), (False, True))   # opened again: inner is still folded


if __name__ == '__main__':
    unittest.main()
