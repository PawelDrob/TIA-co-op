"""A member with members folds and opens in the interface table, in the report and in the viewer, by the same code
(iface.py, page.py); in the report a fold that hides a changed row says that it holds a change."""
import contextlib
import io
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

# The first interface table of the page, its "show all" on. A row by the text of its name cell (its extras left out).
SETUP = ("var t=[].filter.call(document.querySelectorAll('table.itf'),function(x){return x.querySelector('td.nm[data-d]')})[0];"
         "if(t.closest('.nw'))t.closest('.nw').classList.add('all');"
         "function name(y){var c=y.cells[0].cloneNode(true);[].forEach.call(c.querySelectorAll('.ex'),function(e){e.remove()});"
         "return c.textContent.replace(/[\\u25b6\\u25bc]/g,'').trim()}"
         "function seen(y){return getComputedStyle(y).display!='none'}"
         "function cell(n){return [].filter.call(t.querySelectorAll('td.nm'),function(c){return name(c.parentNode)==n})[0]}"
         "function mark(y){return getComputedStyle(y.cells[0],'::after').content}")
# Each member that folds, folded alone: its mark, the changed rows it hid, the member rows still shown.
EACH = ("var out=[];[].forEach.call(t.rows,function(x){if(!x.classList.contains('pa'))return;x.cells[0].click();"
        "out.push({row:name(x),mark:mark(x),hidden:[].filter.call(t.rows,function(y){"
        "return /(^|\\s)(ins|del|chg|mov)(\\s|$)/.test(y.className)&&!seen(y)}).map(name),"
        "shown:[].filter.call(t.rows,function(y){return y.cells[0]&&y.cells[0].hasAttribute('data-d')&&"
        "!y.classList.contains('skip')&&seen(y)}).map(name)});x.cells[0].click()});")
# s at first, after a click on inner, on s, on s again.
STEPS = ("var out=[];function note(){var s=cell('s');out.push({b:seen(cell('b').parentNode),x:seen(cell('x').parentNode),"
         "c:seen(cell('c').parentNode),tw:s.querySelector('.tw').textContent,mark:mark(s.parentNode)})}"
         "note();cell('inner').click();note();cell('s').click();note();cell('s').click();note();")


def _probe(body):
    return ("<script>addEventListener('load',function(){setTimeout(function(){%s%s"
            "document.body.setAttribute('data-fold',JSON.stringify(out))},100)})</script>" % (SETUP, body))


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

    def run_in(self, html, body):
        out = os.path.join(self.dir, 'probe.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html.replace('</body>', _probe(body) + '</body>'))
        dom = self.edge.dump_dom(pathlib.Path(out).as_uri(), timeout=120, size=(1400, 1000))
        return json.loads(unescape(re.search(r'data-fold="([^"]*)"', dom).group(1)))

    def test_a_fold_says_it_holds_a_change_exactly_when_it_hides_one(self):
        for case, (before, after) in CASES.items():
            with self.subTest(case):
                folds = self.run_in(_report(os.path.join(self.dir, str(len(case))), before, after), EACH)
                self.assertTrue(folds)
                for f in folds:
                    self.assertEqual(f['mark'], '"holds a change"' if f['hidden'] else 'none', f)
                if case == 'renamed struct, a member removed':          # x is drawn under S2
                    self.assertIn('x', [h for f in folds for h in f['hidden']])
                if case == 'one change beside unchanged members':        # all shown: s folds a and b
                    s = next(f for f in folds if f['row'] == 's')
                    self.assertEqual(s['shown'], ['s', 'c', 'd'])

    def test_a_fold_in_the_report_opens_again(self):
        start, inner, shut, again = self.run_in(_report(self.dir, BEFORE, AFTER), STEPS)
        self.assertEqual((start['b'], start['tw'], start['mark']), (True, '▼', 'none'))    # open at first
        self.assertTrue(inner['b'])                                  # a fold of another member leaves b
        self.assertEqual((shut['b'], shut['tw'], shut['mark']), (False, '▶', '"holds a change"'))
        self.assertEqual((again['b'], again['tw'], again['mark']), (True, '▼', 'none'))

    def test_a_struct_folds_in_the_viewer_and_one_inside_it_stays_folded(self):
        start, inner, shut, again = self.run_in(_viewer(self.dir, AFTER), STEPS)
        self.assertEqual((start['x'], start['b'], start['c']), (True, True, True))
        self.assertEqual((inner['x'], inner['b']), (False, True))
        self.assertEqual((shut['x'], shut['b'], shut['c'], shut['tw'], shut['mark']), (False, False, True, '▶', 'none'))
        self.assertEqual((again['x'], again['b']), (False, True))   # opened again: inner is still folded


if __name__ == '__main__':
    unittest.main()
