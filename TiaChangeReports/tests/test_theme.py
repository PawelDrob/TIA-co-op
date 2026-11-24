"""The report's colours from one palette (theme.py; the palette and TIA's native theme: TiaHmiGenerator\\hmipreview\\
static\\tia-theme.css): no colour of what the report draws stands outside the palette's block (NoColourOutsideThePalette);
every name is used and can take a host's value (TheNames); a theme of the user's own changes every colour of the page,
the fragment and the viewer, and nothing the renderer writes (ATrialPalette, in Edge); a faulty theme file is refused
with its line (ThemeFiles, TheOptions). The trial palette, every name a colour of its own, lives here only."""
import ast
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from html import unescape
from pathlib import Path

from TiaChangeReports import __main__ as cli
from TiaChangeReports import hmi as hmipart
from TiaChangeReports import page, render_lad, scl_colours, theme
from TiaChangeReports.tests import host_styles
from TiaChangeReports.viewer import __main__ as viewer_cli
from TiaChangeReports.viewer import view

HERE = os.path.dirname(os.path.abspath(__file__))
PLANT = os.path.join(HERE, 'fixtures', 'plant')
JUMPS = os.path.join(HERE, 'fixtures', 'Jumps.s7dcl')

# The files whose colours the palette holds: each must keep none of its own.
SOURCES = ['TiaChangeReports/render_lad.py', 'TiaChangeReports/scl_colours.py', 'TiaChangeReports/page.py',
           'TiaChangeReports/viewer/view.py', 'TiaChangeReports/hmi.css', 'TiaHmiGenerator/hmipreview/static/ldiff.css',
           'TiaHmiGenerator/hmipreview/static/rail.css']
ROOT = os.path.dirname(os.path.dirname(HERE))
LAYOUT = {'--fw', '--fh', '--mb', '--width-in-pane'}                # custom properties of the layout, no colours

NAMED = ('black|white|red|green|blue|gray|grey|silver|yellow|orange|purple|navy|teal|maroon|olive|lime|aqua|fuchsia|'
         'pink|brown|gold|cyan|magenta|darkgray|darkgrey|lightgray|lightgrey|whitesmoke|gainsboro|dimgray|dimgrey')
# A colour as CSS or SVG writes it: #hex, a colour function, or a colour's name in a declaration's value or an
# attribute's (not a word of a text: "drawn faint").
COLOUR = re.compile(r'(?<![&\w-])#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\(|'
                    r'[a-z-]+\s*[:=]\s*["\']?[^;{}<>"\'\n]*?(?<![\w-])(?:%s)(?![\w-])' % NAMED, re.I)


def quiet(f, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return f(*a)


def report(folder, *extra, name='plant.html', sides=(os.path.join(PLANT, 'v1'), os.path.join(PLANT, 'v2'))):
    """The page (or with --fragment the fragment) of fixtures\\plant v1 -> v2: summary, interface, LAD, SCL, the tree;
    or of other sides."""
    out = os.path.join(folder, name)
    code = quiet(cli.main, list(sides) + ['-o', out] + list(extra))
    assert code == 0, code
    with open(out, encoding='utf-8') as f:
        return f.read()


def hmi_sides(folder):
    """Two folders of an HMI project: a screen changed (a rectangle moved), one new, a tag table changed."""
    from TiaChangeReports.tests.test_hmi_part import rect, screen, tag_table
    out = []
    for side, left, files in (('b', 10, {}), ('a', 50, {'Gate.xml': screen('Gate', 12)})):
        files = dict(files, **{'Filler.xml': screen('Filler', 10, rect('lamp', left=left) + rect('door', 200))})
        for name, text in files.items():
            os.makedirs(os.path.join(folder, side, 'hmi', 'screens'), exist_ok=True)
            with open(os.path.join(folder, side, 'hmi', 'screens', name), 'w', encoding='utf-8') as f:
                f.write(text)
        os.makedirs(os.path.join(folder, side, 'hmi', 'tags'), exist_ok=True)
        with open(os.path.join(folder, side, 'hmi', 'tags', 'Plant.xml'), 'w', encoding='utf-8') as f:
            f.write(tag_table('Plant', [('Motor', '100 ms' if side == 'b' else '1 s')]))
        out.append(os.path.join(folder, side))
    return out


def drawn_css(html):
    """What of an HTML page can hold a colour, but its script: the text of each <style>, each style="..." and each
    colour attribute of an element (fill, stroke, ...)."""
    html = re.sub(r'<script\b.*?</script>', '', html, flags=re.S)
    out = re.findall(r'<style>(.*?)</style>', html, re.S)
    out += re.findall(r'\sstyle="([^"]*)"', html)
    out += ['%s:%s' % m for m in re.findall(r'\s(fill|stroke|stop-color|flood-color|color|bgcolor)="([^"]*)"', html)]
    return '\n'.join(out)


def colours_outside(html, *blocks):
    """The colours of html's styles and attributes, the palette's blocks taken out first."""
    for b in blocks:
        assert b in html, b[:80]
        html = html.replace(b, '')
    text = drawn_css(html)
    return sorted({text[max(0, m.start() - 60):m.end() + 10] for m in COLOUR.finditer(text)})


def strings(src):
    """The strings of a Python source but its docstrings: its CSS, HTML and SVG, not its prose."""
    tree = ast.parse(src)
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


def trial_values():
    """Each name of the palette a colour no other name and no value of TIA's native theme has."""
    out = {n: '#%02x%02x%02x' % (17 + i, 200 - i, 33 + (i * 7) % 200) for i, n in enumerate(theme.NAMES)}
    assert len(set(out.values())) == len(out)
    assert not set(out.values()) & {v.lower() for v in theme.NATIVE.values()}
    return out


def theme_file(folder, values, name='trial.css', head='--theme-format: 1;'):
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('.ldiff {\n  %s\n%s}\n' % (head, ''.join('  %s: %s;\n' % kv for kv in values.items())))
    return path


class NoColourOutsideThePalette(unittest.TestCase):
    """The page, the fragment and the viewer's page write no colour but in the palette's block (theme.css): none in
    any style and no colour attribute in the SVG. none, transparent and currentColor are no colours."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.page = report(cls.tmp.name)
        cls.frag = report(cls.tmp.name, '--fragment', name='plant.fragment.html')
        cls.jumps = view.page(JUMPS)[0]
        cls.hmi = report(cls.tmp.name, name='hmi.html', sides=hmi_sides(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_an_hmi_page(self):
        self.assertIn('data-key="screen:Filler"', self.hmi)
        self.assertEqual(colours_outside(self.hmi, theme.css(page=True)), [])

    def test_the_page(self):
        self.assertIn('class="rail"', self.page)                               # the tree's CSS with it
        self.assertEqual(colours_outside(self.page, theme.css(page=True)), [])

    def test_the_fragment(self):
        self.assertEqual(colours_outside(self.frag, theme.css()), [])

    def test_the_viewer(self):
        self.assertIn('class="jl"', self.jumps)                                # jump labels, a Switch, a JumpList
        self.assertEqual(colours_outside(self.jumps, theme.css(page=True)), [])

    def test_the_hmi_part(self):
        """Drawn only with an HMI object on the page: its style, as the page holds it."""
        self.assertEqual(colours_outside('<style>%s</style>' % hmipart.css()), [])

    def test_the_drawing_writes_no_colour(self):
        """What the renderer writes, read in its source: no fill or stroke but none, no colour in a string."""
        with open(render_lad.__file__, encoding='utf-8') as f:
            src = f.read()
        self.assertEqual(re.findall(r'(?:fill|stroke)="(?!none")[^"]*"', src), [])
        self.assertEqual(re.findall(r'''['"]#[0-9a-fA-F]{3,8}['"]''', src), [])

    def test_a_literal_put_back_is_found(self):
        """The check finds a colour in each form a source could write one."""
        for put in ('color:#0a4f9e', 'fill="#1a1a1a"', 'background:rgba(0,0,0,.18)', 'border:1px solid gray',
                    'stroke:hsl(0 0% 50%)', 'style="background:white"'):
            self.assertTrue(colours_outside('<style>.ldiff a{%s}</style><svg><rect %s/></svg>' % (put, put)), put)
        self.assertEqual(colours_outside('<p>&#8203;#inAuto 16#00FF</p><style>.x{fill:none;stroke:currentColor;'
                                         'background:transparent;border-color:var(--grid)}</style>'), [])

    def test_each_source_file_holds_no_colour(self):
        """The files whose colours the palette took over (SOURCES), read as they are: a colour in one fails here even
        where no page draws it."""
        for rel in SOURCES:
            with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
                src = f.read()
            if rel.endswith('.py'):
                src = '\n'.join(strings(src))
            hits = [m.group(0) for m in COLOUR.finditer(src)]
            self.assertEqual(hits, [], rel)


class TheNames(unittest.TestCase):
    """One list of names, each used, each a plain colour, each able to take a host's value (a VS Code theme's
    var(--vscode-...))."""

    def css(self):
        return (page.CSS + page.RAIL_CSS + page.FOCUS_CSS + hmipart.css() + view.PAGE_CSS +
                page.render([], 'b', 'a'))

    def test_the_palette_reads_as_a_theme(self):
        self.assertEqual(theme.read(theme.rail.THEME_CSS, 'tia-theme.css', theme.NAMES), theme.NATIVE)
        self.assertGreater(len(theme.NAMES), 100)
        for name, value in theme.NATIVE.items():
            self.assertTrue(theme.is_colour(value), (name, value))

    def test_each_name_is_used_and_each_used_name_is_one(self):
        used = set(re.findall(r'var\((--[a-z0-9-]+)\)', self.css()))
        used |= {name for _, name, _ in scl_colours.KINDS.values()}
        self.assertEqual(sorted(set(theme.NAMES) - used), [])
        self.assertEqual(sorted(used - set(theme.NAMES) - LAYOUT), [])

    def test_no_name_is_computed_from(self):
        """A name stands alone where it is used: no colour mixed or computed from it, so that any value works."""
        css = self.css()
        for f in ('calc(', 'color-mix(', 'rgb(', 'hsl(', 'from '):
            for m in re.finditer(re.escape(f), css):
                self.assertNotRegex(css[m.start():css.find(')', m.start()) + 1], r'var\(--(?!fw|fh|mb|width)', f)

    def test_the_dev_docs_table_has_each_name_once(self):
        """docs\\dev\\tools\\tia-change-reports.md: the names against VS Code's colours, in the palette's order."""
        with open(os.path.join(ROOT, 'docs', 'dev', 'tools', 'tia-change-reports.md'), encoding='utf-8') as f:
            rows = re.findall(r'^\| `(--[a-z0-9-]+)` \| (?:`[a-zA-Z.]+`|\*per kind\*) \|$', f.read(), re.M)
        self.assertEqual(rows, theme.NAMES)

    def test_the_marks_are_one_set(self):
        """A ladder's marks and the background of an SCL line, an interface row and a badge are the same four names."""
        for mark in render_lad.MARKS:
            self.assertIn('.ldiff svg .hl.%s{fill:var(--%s-fill)}' % (mark, mark), render_lad.CSS)
        self.assertFalse(hasattr(render_lad, 'FILL'))


class ThemeFiles(unittest.TestCase):
    """A theme file: one block .ldiff { ... }, --theme-format: 1; first, then --name: colour; lines. What it leaves out
    keeps TIA's value; anything else is refused with the line, nothing drawn."""

    def read(self, text):
        return theme.read(text, 'my.css', theme.NAMES)

    def refused(self, text, line, what):
        with self.assertRaises(theme.ThemeError) as e:
            self.read(text)
        self.assertTrue(str(e.exception).startswith('my.css:%d: ' % line), str(e.exception))
        self.assertIn(what, str(e.exception))

    def test_a_theme_gives_some_names(self):
        text = '/* mine */\n.ldiff {\n  --theme-format: 1;\n  --wire: #00ff00;   /* green wires */\n  --page:rgb(10, 20, 30)\n}\n'
        self.assertEqual(self.read(text), {'--wire': '#00ff00', '--page': 'rgb(10, 20, 30)'})

    def test_what_it_leaves_out_keeps_tias_value(self):
        css = theme.css(theme.Theme('my.css', {'--wire': '#00ff00'}))
        self.assertTrue(css.startswith(theme.css()), css[:200])                # TIA's whole block first
        self.assertTrue(css.endswith('@media screen{:where(.ldiff){--wire:#00ff00}}\n'), css[-200:])

    def test_each_form_of_colour(self):
        for value in ('#abc', '#abcd', '#a1b2c3', '#a1b2c3d4', 'rgb(1,2,3)', 'rgba(1, 2, 3, .5)', 'rgb(1 2 3 / 50%)',
                      'hsl(120deg 50% 50%)', 'hsla(120, 50%, 50%, 0.3)', 'transparent', 'TRANSPARENT'):
            self.assertEqual(self.read('.ldiff{--theme-format:1;--wire:%s}' % value), {'--wire': value}, value)

    def test_no_colour_is_refused(self):
        for value in ('green', 'var(--vscode-editor-foreground)', '#12', 'rgb(1,2)', 'url(x.png)', '#fff</style>',
                      'rgb(a,b,c)', '', '#ff00ff !important'):
            self.refused('.ldiff {\n --theme-format: 1;\n --wire: %s;\n}' % value, 3, 'is no colour')

    def test_a_name_it_does_not_know(self):
        self.refused('.ldiff {\n --theme-format: 1;\n\n --wires: #000;\n}', 4, '--wires is no name of the palette')

    def test_a_name_twice(self):
        self.refused('.ldiff {\n --theme-format: 1;\n --wire: #000;\n --wire: #111;\n}', 4, 'given twice (line 3)')

    def test_the_format_first(self):
        self.refused('.ldiff {\n --wire: #000;\n}', 2, 'starts with --theme-format: 1;')
        self.refused('.ldiff {\n}', 1, 'starts with --theme-format: 1;')
        self.refused('.ldiff {\n --theme-format: 2;\n}', 2, 'not one this report reads')

    def test_one_block_and_nothing_else(self):
        self.refused('\n\nbody {\n --theme-format: 1;\n}', 3, 'a theme is one block')
        self.refused('.ldiff {\n --theme-format: 1;\n}\n.x { color: red }', 4, 'nothing may follow')
        self.refused('.ldiff {\n --theme-format: 1;\n', 1, 'not closed')
        self.refused('.ldiff {\n --theme-format: 1;\n color: red;\n}', 3, 'not a line of a theme')
        self.refused('.ldiff {\n --theme-format: 1;\n /* open\n}', 3, 'comment /* is not closed')

    def test_load(self):
        self.assertEqual((theme.load().name, theme.load().values), ('tia', {}))
        self.assertEqual(theme.load('tia').values, {})
        with tempfile.TemporaryDirectory() as d:
            path = theme_file(d, {'--wire': '#123456'})
            self.assertEqual(theme.load(path).values, {'--wire': '#123456'})
            with self.assertRaises(theme.ThemeError) as e:
                theme.load(os.path.join(d, 'none.css'))
            self.assertIn('no theme of that name (tia) and no theme file there', str(e.exception))


class TheOptions(unittest.TestCase):
    """--theme on the report and the viewer: a faulty file is a usage error with its line, nothing written."""

    def test_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            bad = theme_file(d, {'--wire': 'green'})
            out, err = os.path.join(d, 'r.html'), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = cli.main([os.path.join(PLANT, 'v1'), os.path.join(PLANT, 'v2'), '-o', out, '--theme', bad])
            self.assertEqual(code, 2)
            self.assertIn('--theme %s:3: --wire: ' % bad, err.getvalue())
            self.assertFalse(os.path.exists(out))
            good = report(d, '--theme', theme_file(d, {'--wire': '#123456'}, 'good.css'))
            self.assertIn('@media screen{:where(:root){--wire:#123456}}', good)

    def test_the_help(self):
        for main in (cli.main, viewer_cli.main):
            text = io.StringIO()
            with contextlib.redirect_stdout(text), self.assertRaises(SystemExit):
                main(['--help'])
            self.assertIn(r'default: your theme file %LOCALAPPDATA%\tia-co-op\theme.css when there, else tia',
                          ' '.join(text.getvalue().split()))

    def test_the_viewer(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'v.html')
            quiet(viewer_cli.main, [JUMPS, '--html', out, '--theme', theme_file(d, {'--wire': '#123456'})])
            with open(out, encoding='utf-8') as f:
                self.assertIn('@media screen{:where(:root){--wire:#123456}}', f.read())
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
                viewer_cli.main([JUMPS, '--html', out, '--theme', theme_file(d, {'--nope': '#000'}, 'bad.css')])
            self.assertEqual(e.exception.code, 2)
            self.assertIn('bad.css:3: --nope is no name of the palette', err.getvalue())


class TheDefaultTheme(unittest.TestCase):
    """%LOCALAPPDATA%\\tia-co-op\\theme.css (theme.USER_THEME; the tests point it at a folder of their own): the report
    and the viewer given no --theme draw in it when it is there; --theme tia draws without it; a faulty one stops
    them, named."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kept = theme.USER_THEME
        theme.USER_THEME = os.path.join(self.tmp.name, 'tia-co-op', 'theme.css')

    def tearDown(self):
        theme.USER_THEME = self.kept
        self.tmp.cleanup()

    def put(self, values):
        os.makedirs(os.path.dirname(theme.USER_THEME))
        theme_file(os.path.dirname(theme.USER_THEME), values, 'theme.css')

    def test_the_place(self):
        self.assertEqual(theme.user_theme({'LOCALAPPDATA': r'C:\Users\u\AppData\Local'}),
                         r'C:\Users\u\AppData\Local\tia-co-op\theme.css')
        self.assertEqual(theme.load().name, 'tia')                                   # not there: TIA's

    def test_the_report(self):
        self.put({'--wire': '#123456'})
        self.assertIn('@media screen{:where(:root){--wire:#123456}}', report(self.tmp.name))
        self.assertNotIn('@media screen', report(self.tmp.name, '--theme', 'tia', name='tia.html'))

    def test_the_viewer(self):
        self.put({'--wire': '#123456'})
        out = os.path.join(self.tmp.name, 'v.html')
        quiet(viewer_cli.main, [JUMPS, '--html', out])
        with open(out, encoding='utf-8') as f:
            self.assertIn('@media screen{:where(:root){--wire:#123456}}', f.read())

    def test_a_faulty_one(self):
        self.put({'--wire': 'green'})
        out, err = os.path.join(self.tmp.name, 'r.html'), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main([os.path.join(PLANT, 'v1'), os.path.join(PLANT, 'v2'), '-o', out])
        self.assertEqual(code, 2)
        self.assertIn('the default theme %s:3: --wire: ' % theme.USER_THEME, err.getvalue())
        self.assertIn('--theme tia draws without it', err.getvalue())
        self.assertFalse(os.path.exists(out))
        said = []
        self.assertEqual(viewer_cli.main([JUMPS], open_page=lambda p: self.fail('opened'), message=said.append), 2)
        self.assertIn('%s:3: --wire: ' % theme.USER_THEME, said[0])


# Every element's colours in the browser, its ::before and ::after too, the page's head and body with them.
PROPS = ['color', 'background-color', 'background-image', 'border-top-color', 'border-right-color',
         'border-bottom-color', 'border-left-color', 'outline-color', 'box-shadow', 'text-decoration-color', 'fill',
         'stroke', 'caret-color', 'column-rule-color']
# An HMI screen (svg.hs but its change outlines, .dl) and a colour value's swatch (.cs) are in the project's colours,
# no theme's. A moment after load, so that the HMI part has drawn the open object.
PROBE = """<script>addEventListener('load',function(){setTimeout(function(){var P=%s,o=[];
[].forEach.call(document.querySelectorAll('%s'),function(e){if(e.closest('script,style,.cs'))return;
 if(e.closest('svg.hs')&&!e.closest('.dl'))return;
 var svg=e instanceof SVGElement;
 [null,'::before','::after'].forEach(function(p){var c=getComputedStyle(e,p);if(p&&c.content=='none')return;
  P.forEach(function(k){if(!svg&&(k=='fill'||k=='stroke'))return;var v=c.getPropertyValue(k);o.push([e.tagName.toLowerCase()+'.'+(e.getAttribute('class')||'')+
   (p||''),k,v])})})});
var x=document.createElement('pre');x.id='colours';x.textContent=JSON.stringify(o);document.body.appendChild(x)},1000)})
</script>"""


def computed(edge, html, folder, name, inside='body'):
    """[(element, property, value)] of every element of html at or inside the selector inside."""
    probe = PROBE % (json.dumps(PROPS), '%s,%s *' % (inside, inside))
    i = html.rfind('</body>')
    html = html[:i] + probe + html[i:]
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    dom = edge.dump_dom(Path(path).as_uri(), size=(1400, 900))
    m = re.search(r'<pre id="colours">(.*?)</pre>', dom, re.S)
    if not m:
        raise AssertionError('no colours from Edge for %s' % path)
    return [tuple(x) for x in json.loads(unescape(m.group(1))) if x[0] != 'pre.']


def rgb(hex_):
    return 'rgb(%d, %d, %d)' % tuple(int(hex_[k:k + 2], 16) for k in (1, 3, 5))


class ATrialPalette(unittest.TestCase):
    """The same report under a theme that gives every name a colour of its own: every colour of every element of the
    page, the fragment and the viewer's page is one of the theme's, so nothing does not follow; and what the renderer
    wrote is the same but for the theme's block. A host's stylesheet wins over the report's own values."""

    @classmethod
    def setUpClass(cls):
        cls.edge = host_styles.browser()
        if cls.edge is None:
            raise unittest.SkipTest('no Edge or Chrome')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.values = trial_values()
        cls.trial = theme.load(theme_file(cls.tmp.name, cls.values))
        cls.allowed = {rgb(v) for v in cls.values.values()} | {'rgba(0, 0, 0, 0)'}

    @classmethod
    def tearDownClass(cls):
        cls.edge.close(ignore_errors=True)
        cls.tmp.cleanup()

    def assert_follows(self, html, name, inside='body'):
        bad = {}
        for el, prop, value in computed(self.edge, html, self.tmp.name, name, inside):
            for c in re.findall(r'rgba?\([^)]*\)', value):
                if c not in self.allowed:
                    bad.setdefault((el, prop), c)
        self.assertEqual(sorted(bad.items())[:20], [], name)

    def test_the_page(self):
        html = report(self.tmp.name, '--theme', self.trial.name, name='trial.html')
        self.assert_follows(html, 'trial-page.html')
        default = report(self.tmp.name, name='default.html')
        self.assertEqual(html.replace(theme.css(self.trial, page=True), ''), default.replace(theme.css(page=True), ''))

    def test_an_hmi_page(self):
        """The HMI part's own chrome: the toolbar, the panes, the change list, the outlines on a screen."""
        html = report(self.tmp.name, '--theme', self.trial.name, name='trial-hmi.html', sides=hmi_sides(self.tmp.name))
        self.assert_follows(html, 'trial-hmi-page.html')

    def test_the_png(self):
        """--png draws the page in a headless browser, on the screen: the theme's colours, not print's."""
        png = os.path.join(self.tmp.name, 'trial.png')
        report(self.tmp.name, '--theme', self.trial.name, '--png', png, name='trial-png.html')
        from PIL import Image
        img = Image.open(png).convert('RGB')
        self.assertEqual('rgb(%d, %d, %d)' % img.getpixel((img.width - 1, img.height - 1)), rgb(self.values['--page']))

    def test_the_fragment(self):
        html = report(self.tmp.name, '--fragment', '--theme', self.trial.name, name='trial.fragment.html')
        self.assert_follows(host_styles.bare(html, 1300), 'trial-fragment.html', '.ldiff')
        default = report(self.tmp.name, '--fragment', name='default.fragment.html')
        self.assertEqual(html.replace(theme.css(self.trial), ''), default.replace(theme.css(), ''))

    def test_the_viewer(self):
        html = view.page(JUMPS, self.trial)[0]
        self.assert_follows(html, 'trial-viewer.html')
        self.assertEqual(html.replace(theme.css(self.trial, page=True), ''),
                         view.page(JUMPS)[0].replace(theme.css(page=True), ''))

    def test_print_takes_tias_values(self):
        self.assertIn('@media screen{', theme.css(self.trial))

    def test_a_hosts_stylesheet_wins(self):
        """A host page that sets the names on .ldiff, before the fragment's own <style> as a webview's head does,
        draws in its values: a VS Code theme's var(--vscode-...) among them."""
        frag = report(self.tmp.name, '--fragment', name='host.fragment.html')
        host = ('<!doctype html><html><head><meta charset="utf-8"><style>body{--vscode-editor-foreground:#123456}'
                '.ldiff{%s}</style></head><body>%s</body></html>'
                % (''.join('%s:%s;' % (n, 'var(--vscode-editor-foreground)' if n == '--text' else v)
                           for n, v in self.values.items()), frag))
        got = computed(self.edge, host, self.tmp.name, 'host.html', '.ldiff')
        self.assertIn(('div.ldiff', 'color', 'rgb(18, 52, 86)'), got)
        self.assert_follows(host.replace('#123456', self.values['--text']), 'host-follows.html', '.ldiff')


if __name__ == '__main__':
    unittest.main()
