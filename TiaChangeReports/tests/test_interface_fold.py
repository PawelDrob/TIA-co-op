"""A member with members folds and opens in the interface table, in the report and in the viewer, by the same code
(iface.py, page.py); in the report a fold over a changed member says that it holds a change."""
import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from html import unescape

from TiaChangeReports import __main__ as cli
from TiaChangeReports.viewer import view

BEFORE = '''FUNCTION_BLOCK "Mixer"
    VAR
        s : STRUCT
            a : Bool;
            inner : STRUCT
                x : Int;
            END_STRUCT;
            b : Int;
        END_STRUCT;
        c : Bool;
        d : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
AFTER = BEFORE.replace('b : Int;', 'b : DInt;')
HOLDS = r'<td class="nm[^"]*" data-d="[0-9]+" data-hc'

# Run in the page after its own scripts: rows shown and the state of s, at first, after a click on inner's name cell,
# on s's, on s's again; into <body data-fold>. A row by the name in its name cell.
PROBE = ("<script>addEventListener('load',function(){setTimeout(function(){var out=[],t=[].filter.call("
         "document.querySelectorAll('table.itf'),function(x){return x.querySelector('td.nm[data-d]')})[0];"
         "function cell(n){return [].filter.call(t.querySelectorAll('td.nm'),function(c){"
         "return c.textContent.replace(/[\\u25b6\\u25bc]/g,'')==n})[0]}"
         "function seen(n){return getComputedStyle(cell(n).parentNode).display!='none'}"
         "function note(){var s=cell('s');out.push({b:seen('b'),x:seen('x'),c:seen('c'),"
         "tw:s.querySelector('.tw').textContent,mark:getComputedStyle(s,'::after').content})}"
         "note();cell('inner').click();note();cell('s').click();note();cell('s').click();note();"
         "document.body.setAttribute('data-fold',JSON.stringify(out))},100)})</script>")


def _put(folder, name, text):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def _report(folder):
    """The report of Mixer from BEFORE to AFTER."""
    b, a = _put(folder, 'b/Mixer.s7dcl', BEFORE), _put(folder, 'a/Mixer.s7dcl', AFTER)
    out = os.path.join(folder, 'report.html')
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main([b, a, '-o', out]) == 0
    with open(out, encoding='utf-8') as f:
        return f.read()


class Rows(unittest.TestCase):
    """What the page holds for the script: each member's level, and which hold a change."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_the_report_marks_the_members_a_changed_member_is_under(self):
        html = _report(self.dir)
        self.assertRegex(html, r'<td class="nm" data-d="1" data-hc style="[^"]*"><span class="tw">▼</span>s<')
        self.assertRegex(html, r'<td class="nm" data-d="2" style="[^"]*"><span class="tw">[^<]*</span>b<')
        self.assertEqual(len(re.findall(HOLDS, html)), 1)

    def test_the_viewer_gives_every_member_its_level_and_marks_none(self):
        html, _ = view.page(_put(self.dir, 'a/Mixer.s7dcl', AFTER))
        for name, level in (('s', 1), ('a', 2), ('inner', 2), ('x', 3), ('b', 2), ('c', 1)):
            self.assertRegex(html, r'data-d="%d" style="[^"]*"><span class="tw">[^<]*</span>%s<' % (level, name))
        self.assertEqual(re.findall(HOLDS, html), [])


class InTheBrowser(unittest.TestCase):
    """The fold itself, in headless Edge or Chrome (no window); skipped without one."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(cli.HERE), 'TiaHmiGenerator'))
        from hmipreview.edge import Edge, edge_path
        if not edge_path():
            raise unittest.SkipTest('no Microsoft Edge or Google Chrome')
        cls.edge = Edge()

    @classmethod
    def tearDownClass(cls):
        cls.edge.close(ignore_errors=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def fold(self, html):
        out = os.path.join(self.dir, 'probe.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html.replace('</body>', PROBE + '</body>'))
        dom = self.edge.dump_dom(pathlib.Path(out).as_uri(), timeout=120, size=(1400, 1000))
        return json.loads(unescape(re.search(r'data-fold="([^"]*)"', dom).group(1)))

    def test_a_fold_in_the_report_says_it_holds_a_change(self):
        start, inner, shut, again = self.fold(_report(self.dir))
        self.assertEqual((start['b'], start['tw'], start['mark']), (True, '▼', 'none'))    # open at first
        self.assertTrue(inner['b'])                                  # a fold of another member leaves b
        self.assertEqual((shut['b'], shut['tw'], shut['mark']), (False, '▶', '"holds a change"'))
        self.assertEqual((again['b'], again['tw'], again['mark']), (True, '▼', 'none'))

    def test_a_struct_folds_in_the_viewer_and_one_inside_it_stays_folded(self):
        start, inner, shut, again = self.fold(view.page(_put(self.dir, 'a/Mixer.s7dcl', AFTER))[0])
        self.assertEqual((start['x'], start['b'], start['c']), (True, True, True))
        self.assertEqual((inner['x'], inner['b']), (False, True))
        self.assertEqual((shut['x'], shut['b'], shut['c'], shut['tw'], shut['mark']), (False, False, True, '▶', 'none'))
        self.assertEqual((again['x'], again['b']), (False, True))   # opened again: inner is still folded


if __name__ == '__main__':
    unittest.main()
