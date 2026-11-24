"""The report's colours from one palette (theme.py; the palette and TIA's native theme: TiaHmiGenerator\\hmipreview\\
static\\tia-theme.css): no colour of what the report draws stands outside the palette's block (NoColourOutsideThePalette);
every name is used and can take a host's value (TheNames); a theme of the user's own changes every colour of the page,
the fragment and the viewer, and nothing the renderer writes (ATrialPalette, in Edge), but an HMI screen; a faulty
theme file is refused with its line, or why it cannot be read (ThemeFiles, TheOptions); a theme takes what the browser
takes of its forms (TheFormsOfColour), and the page holds each colour in one form the browser reads as the colour read
(TheWrittenForm). The trial palette, every name a colour of its own, lives here only."""
import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
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
           'TiaHmiGenerator/hmipreview/static/rail.css', 'TiaHmiGenerator/hmipreview/static/rail.js']
ROOT = os.path.dirname(os.path.dirname(HERE))
LAYOUT = {'--fw', '--fh', '--mb', '--width-in-pane'}                # custom properties of the layout, no colours

# A colour outside the palette is found three ways.
# 1. By its property, with no list of CSS's names: a property that takes a colour and nothing else (PROPERTY: color,
#    each *-color as background-color, stop-color or lighting-color, bgcolor, fill, stroke), in CSS or as an attribute
#    of an element, with any value but the palette's var(--name), none, transparent, currentColor and inherit.
#    In a source, var(%s) is a template: the page it writes is checked with the name. On a page it is a finding.
# 2. Anywhere else, so in a shorthand (border, background, outline, box-shadow, ...), a gradient or a filter: #hex, a
#    colour function (COLOUR), or a word of CSS Color 4's lists of named and system colours in a declaration's value
#    (COLOUR_NAME; not a word of a text, "drawn faint"). A value of a property that names properties (transition) is no
#    colour. In a source the names are not looked for in a script (a JS string), whose words they are ("window").
# 3. In a script, what it gives an element's style (script_css): style.backgroundColor = ..., style.background = ...,
#    setAttribute('fill', ...), style.setProperty('border-color', ...), and the declarations of a cssText or a style
#    attribute, each read as the CSS declaration it makes and checked by 1 and 2, names too. A colour a script gives
#    from a variable (style.color = c) is found as well: its value is no var(--name).
PROPERTY = r'(?:[a-z-]*-)?color|bgcolor|fill|stroke'
KEYWORDS = {'none', 'transparent', 'currentcolor', 'inherit'}
COLOUR_PROPERTY = re.compile(r'(?<![\w-])(%s)\s*[:=]\s*"?([^;{}<>"\n]*?)\s*(?=[;}"\n]|$)' % PROPERTY, re.I)
PALETTE_VALUE = re.compile(r'var\((--[a-z0-9-]+|%s)\)')
NAMED = (
    # the named colours (148)
    'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood '
    'cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod '
    'darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon '
    'darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray '
    'dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green '
    'greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon '
    'lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon '
    'lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta '
    'maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen '
    'mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive '
    'olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru '
    'pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell '
    'sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise '
    'violet wheat white whitesmoke yellow yellowgreen '
    # the system colours (19), and those CSS Color 4 keeps deprecated (23)
    'accentcolor accentcolortext activetext buttonborder buttonface buttontext canvas canvastext field fieldtext '
    'graytext highlight highlighttext linktext mark marktext selecteditem selecteditemtext visitedtext activeborder '
    'activecaption appworkspace background buttonhighlight buttonshadow captiontext inactiveborder inactivecaption '
    'inactivecaptiontext infobackground infotext menu menutext scrollbar threeddarkshadow threedface threedhighlight '
    'threedlightshadow threedshadow window windowframe windowtext').split()
COLOUR = re.compile(r'(?<![&\w-])#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\(', re.I)
COLOUR_NAME = re.compile(r'(?<![\w-])(?!transition|will-change)[a-z-]+\s*[:=]\s*["\']?[^;{}<>"\'\n]*?'
                         r'(?<![\w-])(?:%s)(?![\w-])' % '|'.join(NAMED), re.I)


def colours_in(text, names=True, source=False):
    """The colours text, CSS or what drawn_css makes of a page, holds outside the palette: each a piece of text around
    it. names: look for colour names in values too. source: text of a source, where var(%s) is a template."""
    out = list(COLOUR.finditer(text)) + (list(COLOUR_NAME.finditer(text)) if names else [])
    allowed = theme.NAMES + (['%s'] if source else [])
    for m in COLOUR_PROPERTY.finditer(text):
        words = re.sub(r'\s*!important$', '', m.group(2).strip('\'`'), flags=re.I).split()
        palette = [PALETTE_VALUE.fullmatch(w) for w in words]
        if not words or any(w.lower() not in KEYWORDS and not (v and v.group(1) in allowed)
                            for w, v in zip(words, palette)):
            out.append(m)
    return sorted({text[max(0, m.start() - 60):m.end() + 10] for m in out})


def script_css(js):
    """The CSS declarations a script gives an element's style, a line each, the quotes taken out of the value:
    style.backgroundColor = 'x' is background-color:x, setAttribute('fill', 'x') fill:x; a cssText or a style
    attribute is its declarations."""
    def value(v):
        return re.sub(r'[\'"`]', '', v).strip()
    out = []
    for m in re.finditer(r'\.style\.([a-zA-Z]+)\s*\+?=\s*([^;}\n]*)', js):
        prop = re.sub('([A-Z])', lambda c: '-' + c.group(1).lower(), m.group(1))
        out.append(value(m.group(2)) if prop == 'css-text' else '%s:%s' % (prop, value(m.group(2))))
    for m in re.finditer(r'\b(?:setAttribute|setProperty)\(\s*[\'"`]([\w-]+)[\'"`]\s*,\s*([^;}\n]*)\)', js):
        out.append(value(m.group(2)) if m.group(1) == 'style' else '%s:%s' % (m.group(1), value(m.group(2))))
    return '\n'.join(out)


def source_colours(rel, src):
    """The colours a source file holds outside the palette: a Python file's in its strings, a script's in what it
    gives an element's style too (script_css), a stylesheet's as it stands."""
    if rel.endswith('.py'):
        return (colours_in('\n'.join(strings(src)), names=False, source=True) +
                colours_in('\n'.join(strings(src, scripts=False)), source=True) +
                colours_in(script_css('\n'.join(strings(src, only_scripts=True))), source=True))
    if rel.endswith('.js'):
        return colours_in(src, names=False, source=True) + colours_in(script_css(src), source=True)
    return colours_in(src, source=True)


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
    """What of an HTML page can hold a colour: the text of each <style>, each style="...", each colour attribute of an
    element (PROPERTY: fill, stroke, ...), and what each <script> gives an element's style (script_css)."""
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', html, flags=re.S)
    html = re.sub(r'<script\b.*?</script>', '', html, flags=re.S)
    out = re.findall(r'<style>(.*?)</style>', html, re.S)
    out += re.findall(r'\sstyle="([^"]*)"', html)
    out += ['%s:%s' % m for m in re.findall(r'\s(%s)="([^"]*)"' % PROPERTY, html, re.I)]
    out += [script_css(js) for js in scripts]
    return '\n'.join(out)


def colours_outside(html, *blocks):
    """The colours of html's styles and attributes, the palette's blocks taken out first."""
    for b in blocks:
        assert b in html, b[:80]
        html = html.replace(b, '')
    return colours_in(drawn_css(html))


def strings(src, scripts=True, only_scripts=False):
    """The strings of a Python source but its docstrings: its CSS, HTML and SVG, not its prose. scripts: with the
    strings of a name ending in JS (JS, FOCUS_JS, ...). only_scripts: those alone."""
    tree = ast.parse(src)
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr)}
    js = {id(c) for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AugAssign))
          and any(isinstance(t, ast.Name) and t.id.endswith('JS') for t in getattr(n, 'targets', None) or [n.target])
          for c in ast.walk(n.value)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs and (id(n) in js if only_scripts else scripts or id(n) not in js)]


def trial_values():
    """Each name of the palette a colour no other name and no value of TIA's native theme has."""
    out = {n: '#%02x%02x%02x' % (17 + i, 200 - i, 33 + (i * 7) % 200) for i, n in enumerate(theme.NAMES)}
    assert len(set(out.values())) == len(out)
    assert not {theme.colour(v) for v in out.values()} & set(theme.NATIVE.values())
    return out


def theme_file(folder, values, name='trial.css', head='--theme-format: 1;'):
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('.ldiff {\n  %s\n%s}\n' % (head, ''.join('  %s: %s;\n' % kv for kv in values.items())))
    return path


class NoColourOutsideThePalette(unittest.TestCase):
    """The page, the fragment and the viewer's page write no colour but in the palette's block (theme.css): none in
    any style, no colour attribute in the SVG and none a script gives. none, transparent, currentColor and inherit are
    no colours."""

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
        """The check finds a colour in each form a source could write one, in a rule for :hover too: by its property
        (a name the list does not hold, a system colour, a name of another palette) and in a shorthand by the list."""
        for put in ('color:#0a4f9e', 'fill="#1a1a1a"', 'background:rgba(0,0,0,.18)', 'border:1px solid gray',
                    'stroke:hsl(0 0% 50%)', 'style="background:white"', 'color:crimson', 'background-color:notaname',
                    'color:CanvasText', 'fill="tomato"', 'stroke:var(--vscode-editor-foreground)',
                    'color:var(--wire, red)', 'border:1px solid darkred', 'outline:2px dotted Highlight',
                    'background:lightblue', 'box-shadow:0 0 2px rebeccapurple', 'filter:drop-shadow(0 0 1px olive)',
                    'background-image:linear-gradient(papayawhip, var(--page))'):
            prop, value = re.split('[:=]', put.replace('"', ''), maxsplit=1)
            for rule in ('.ldiff a{%s:%s}', '.ldiff a:hover{%s:%s}', '.ldiff .fv b:focus-visible{%s:%s;cursor:auto}'):
                self.assertTrue(colours_outside('<style>%s</style>' % rule % (prop, value)), (rule, put))
            if prop == 'style' or re.fullmatch(PROPERTY, prop):                  # an attribute of an element
                self.assertTrue(colours_outside('<svg><rect %s="%s"/></svg>' % (prop, value)), put)
        for attr in ('lighting-color="#ff0000"', 'bgcolor="notaname"', 'fill="var(%s)"'):
            self.assertTrue(colours_outside('<svg><feDiffuseLighting %s/></svg>' % attr), attr)
        self.assertEqual(colours_outside('<p>&#8203;#inAuto 16#00FF, drawn white</p><style>.x{fill:none;'
                                         'stroke:currentColor;background:transparent;border-color:var(--grid)}'
                                         '.y:hover{color:inherit;border:1px solid var(--grid) !important;'
                                         'transition:background .1s}.ldiff-color:hover{x:y}</style>'
                                         '<svg><rect fill="none" stroke="var(--wire)"/></svg>'), [])

    def test_a_colour_a_script_gives_is_found(self):
        """A script's colour by each of its spellings, names too, on a page, in a Python source's script and in a .js
        source; what the report's scripts give a style today is none."""
        for put in ("e.style.color='crimson'", "e.style.backgroundColor='crimson'", "e.style.borderColor = 'red'",
                    "e.style.background='crimson'", "e.style.boxShadow='0 0 2px tomato'", 'e.style.color=c',
                    "e.style.outlineColor='#123'", "e.setAttribute('fill','crimson')",
                    "e.setAttribute('stroke', \"rgb(1,2,3)\")", "e.style.setProperty('background-color','crimson')",
                    "e.style.setProperty('--wire','red')", "e.style.cssText='background:crimson'",
                    "e.style.cssText+='color:var(--vscode-foo)'", "e.setAttribute('style','border:1px solid red')"):
            js = 'function f(e,c){var w=1;%s;e.style.height=w+"px"}' % put
            self.assertTrue(colours_outside('<script>%s</script>' % js), put)
            self.assertTrue(source_colours('x.py', 'FOCUS_JS = %r\n' % js), put)
            self.assertTrue(source_colours('x.js', js), put)
        clean = ("q.style.width=z?w*z+'px':'';q.style.maxWidth=z?'none':w+'px';e.style.color='var(--wire)';"
                 "s.style.setProperty('--mb','min('+g+'px,'+100*g/wide+'%)');lin.setAttribute('aria-label',c.ph);"
                 "de.style.overflow='hidden';var window=1,menu=window")
        self.assertEqual(colours_outside('<script>%s</script>' % clean), [])
        self.assertEqual(source_colours('x.js', clean), [])

    def test_each_source_file_holds_no_colour(self):
        """The files whose colours the palette took over (SOURCES), read as they are: a colour in one fails here even
        where no page draws it."""
        for rel in SOURCES:
            with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
                self.assertEqual(source_colours(rel, f.read()), [], rel)


class TheNames(unittest.TestCase):
    """One list of names, each used, each a plain colour, each able to take a host's value (a VS Code theme's
    var(--vscode-...))."""

    def css(self):
        return (page.CSS + page.RAIL_CSS + page.FOCUS_CSS + hmipart.css() + view.PAGE_CSS +
                page.render([], 'b', 'a'))

    def test_the_palette_reads_as_a_theme(self):
        self.assertEqual(theme.read(theme.rail.THEME_CSS, 'tia-theme.css', theme.NAMES), theme.NATIVE)
        self.assertGreater(len(theme.NAMES), 100)
        for name, c in theme.NATIVE.items():
            self.assertEqual(theme.colour(theme.written(c)), c, name)

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
        self.assertEqual(self.read(text), {'--wire': (0, 255, 0, 1.0), '--page': (10, 20, 30, 1.0)})

    def test_what_it_leaves_out_keeps_tias_value(self):
        css = theme.css(theme.Theme('my.css', {'--wire': (0, 255, 0, 1.0)}))
        native, screen = theme.css().splitlines(keepends=True)                 # TIA's whole block, a screen's own
        self.assertEqual(css, native + '@media screen{:where(.ldiff){--wire:rgba(0,255,0,1)}}\n' + screen)
        self.assertEqual(screen, '.ldiff svg.hs{color:rgba(0,0,0,1);fill:rgba(0,0,0,1);'
                                 'background-color:rgba(255,255,255,1)}\n')

    def test_each_form_of_colour(self):
        """Each read into numbers as the browser reads it: a percentage of 255, rounded half up, none 0, the alpha in
        full."""
        for value, c in (('#abc', (170, 187, 204, 1.0)), ('#abcd', (170, 187, 204, 221 / 255)),
                         ('#a1b2c3', (161, 178, 195, 1.0)), ('#A1B2C3D4', (161, 178, 195, 212 / 255)),
                         ('rgb(1,2,3)', (1, 2, 3, 1.0)), ('rgba(1, 2, 3, .5)', (1, 2, 3, .5)),
                         ('rgb(1 2 3 / 50%)', (1, 2, 3, .5)), ('RGB(10%, 20%, 50%)', (26, 51, 128, 1.0)),
                         ('rgb(none 2% 3 / none)', (0, 5, 3, 0.0)), ('rgb(1.5 -1 300 / 2)', (2, 0, 255, 1.0)),
                         ('rgba(0,0,0,.18)', (0, 0, 0, .18)), ('transparent', (0, 0, 0, 0.0)),
                         ('TRANSPARENT', (0, 0, 0, 0.0))):
            self.assertEqual(self.read('.ldiff{--theme-format:1;--wire:%s}' % value), {'--wire': c}, value)

    def test_the_page_holds_numbers_only(self):
        """What the page holds of a theme's value is written from its numbers, not the file's text."""
        for value, out in (('#ABC', 'rgba(170,187,204,1)'), ('rgba( 0 , 0 , 0 , .25 )', 'rgba(0,0,0,0.25)'),
                           ('rgb(1e2 50% none / 1e-7)', 'rgba(100,128,0,0.0000001)'), ('transparent', 'rgba(0,0,0,0)')):
            self.assertEqual(theme.written(theme.colour(value)), out, value)
        self.assertIn('--shadow:rgba(0,0,0,0.25);--backdrop:rgba(0,0,0,0.18);', theme.css())

    def test_another_form_is_refused(self):
        """Values the browser takes neither (TheFormsOfColour holds the two to one set), and NOT_TAKEN: the forms of
        CSS Color a theme does not take, a colour's name, hsl() and the rest."""
        for value in ('var(--vscode-editor-foreground)', '#12', 'rgb(1,2)', 'url(x.png)', '#fff</style>', 'rgb(a,b,c)',
                      '#ff00ff !important', 'hsl(1,2,3)', 'rgb(1%,2,3)', 'rgb(1 2,3)', 'rgb(10deg,2,3)', 'rgb(1/2/3)',
                      'rgb(1 2 3 4)', 'rgb(1., 2, 3)') + OTHER_SCRIPTS + NOT_TAKEN:
            self.refused('.ldiff {\n --theme-format: 1;\n --wire: %s;\n}' % value, 3,
                         '--wire: %r is not a form of colour a theme takes; those are #rgb, #rgba, #rrggbb, #rrggbbaa, '
                         'rgb(), rgba() or transparent, no colour names, no hsl() or var()' % value)
        self.refused('.ldiff {\n --theme-format: 1;\n --wire: ;\n}', 3, "--wire: '' is not a form of colour")

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
            self.assertEqual(theme.load(path).values, {'--wire': (0x12, 0x34, 0x56, 1.0)})
            with self.assertRaises(theme.ThemeError) as e:
                theme.load(os.path.join(d, 'none.css'))
            self.assertIn('no theme of that name (tia) and no theme file there', str(e.exception))
            latin = os.path.join(d, 'latin.css')
            with open(latin, 'wb') as f:
                f.write(b'.ldiff {\n  --theme-format: 1;\n  --wire: #f\xe9f;\n}\n')
            for path, why in ((latin, 'it is not UTF-8'), (d, 'it is a folder')):
                with self.assertRaises(theme.ThemeError) as e:
                    theme.load(path)
                self.assertIn('%s: the theme file cannot be read: %s' % (path, why), str(e.exception))
                self.assertNotIn('no theme file there', str(e.exception))


# Values of forms of CSS Color a theme does not take, each one the browser takes: a theme refuses them by their form.
NOT_TAKEN = ('green', 'white', 'currentColor', 'hsl(120, 50%, 50%)', 'hsl(120deg 50% 50%)', 'hwb(1 2% 3%)',
             'color-mix(in srgb, red, blue)', 'rgb(calc(1) 2 3)', 'rgb(from red r g b)')


# Values with a digit, a letter or a white space CSS does not have: its are ASCII, its white space no vertical tab.
# Neither the browser nor a theme takes them; Python's \d, \s and re.I would take some, float() the digits.
OTHER_SCRIPTS = ('rgb(\u0661,2,3)', 'rgb(\uff11 2 3)', 'rgb(1,\u07c2,3)', 'rgba(1,2,3,.\u0665)', 'rgb(1e\uff12 2 3)',
                 '#\uff46\uff46\uff46', '#ab\uff43', 'rgb(1\u00a02\u00a03)', 'rgb(1\u30002 3)', 'rgb(1\x0b2\x0b3)',
                 'rgb(1,2,3)\u2028', 'tran\u017fparent', 'rgb(1 2 3 \uff0f 1)')


def generated_values():
    """Values near the forms a theme takes, many a little off: hex of each length and with a letter that is no digit;
    rgb() and rgba() with numbers as CSS writes them and as it does not, percentages, an angle and none, in the comma
    form and the space form, their separators mixed, with an alpha and without; OTHER_SCRIPTS."""
    out = ['#' + '0aF9b1C2e'[:n] for n in range(10)] + ['#' + 'aF9b1C2e'[:n] + 'g' for n in (2, 3, 5, 7)]
    out += ['##fff', '#-12', 'transparent', 'Transparent', 'transparen', 'transparent0']
    first = ['1', '255', '300', '-1', '+1', '1.5', '.5', '1.', '1e2', '1E-1', '1e', '1%', '1.5%', '1deg', 'none', 'a']
    rest = ['2', '2%', 'none']
    gaps = [',', ' , ', ' ']
    alphas = ['', ',.5', ', 50%', ',none', ' / .5', '/50%', ' / none', ',', ' /', ', .5, 1', ' / 1.']
    out += ['%s(%s%s%s%s%s%s)' % (fn, a, g1, b, g2, c, alpha) for fn in ('rgb', 'rgba') for a in first for b in rest
            for c in rest for g1 in gaps for g2 in gaps for alpha in alphas]
    out += ['RGB(1, 2, 3)', 'Rgba(1 2 3 / 1)', 'rgb (1, 2, 3)', 'rgb( 1 , 2 , 3 )', 'rgb(1,2)', 'rgb(1,2,3,4,5)',
            'rgb()', 'rgb(1 2 3 4)', 'rgb(1 / 2 / 3)', 'rgba(1, 2, 3, 4%)', 'rgba(1%, 2%, 3%, .5)']
    out += [' rgb(1,2,3) ', '\t#fff\n', '\ftransparent\r', ' rgb(1,2,3)\n\n']
    return out + list(OTHER_SCRIPTS)


def tias_values():
    """The values of TIA's native theme as its file writes them."""
    return re.findall(r'^ *--(?!theme-format)[a-z0-9-]+: *([^;]+);', theme.rail.THEME_CSS, re.M)


class InEdge(unittest.TestCase):
    """A test that asks Edge about colours."""

    @classmethod
    def setUpClass(cls):
        cls.edge = host_styles.browser()
        if cls.edge is None:
            raise unittest.SkipTest('no Edge or Chrome')
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.edge.close(ignore_errors=True)
        cls.tmp.cleanup()

    def read_by_edge(self, values):
        """[(whether the browser takes the value as a colour, an element's computed color under it, the pixel
        [r, g, b, a] a canvas draws in it)] for each of values."""
        script = ('<canvas id="c" width="1" height="1"></canvas><script>var g=document.getElementById("c")'
                  '.getContext("2d",{willReadFrequently:true});var x=document.createElement("i");'
                  'document.body.appendChild(x);var o=%s.map(function(c){x.style.color="";x.style.color=c;'
                  'g.fillStyle="#000";g.fillStyle=c;g.clearRect(0,0,1,1);g.fillRect(0,0,1,1);'
                  'return [CSS.supports("color",c),getComputedStyle(x).color,Array.from(g.getImageData(0,0,1,1).data)]'
                  '});var p=document.createElement("pre");p.id="ok";p.textContent=JSON.stringify(o);'
                  'document.body.appendChild(p)</script>' % json.dumps(values).replace('</', '<\\/'))
        path = os.path.join(self.tmp.name, 'colours.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html><body>%s</body></html>' % script)
        m = re.search(r'<pre id="ok">(.*?)</pre>', self.edge.dump_dom(Path(path).as_uri(), size=(200, 200)), re.S)
        self.assertTrue(m, 'no answer from Edge')
        got = json.loads(unescape(m.group(1)))
        self.assertEqual(len(got), len(values))
        return got

    def supported(self, values):
        """[whether the browser takes each of values as a colour]."""
        return [ok for ok, _, _ in self.read_by_edge(values)]


class TheFormsOfColour(InEdge):
    """What a theme takes is what the browser takes, over values near the forms a theme takes (generated_values()),
    by Edge's CSS.supports('color', ...): a theme never refuses what a browser draws. NOT_TAKEN the browser takes and a
    theme refuses, by their form."""

    def test_a_theme_takes_what_the_browser_takes(self):
        values = generated_values()
        got = self.supported(values)
        differ = [(v, b) for v, b in zip(values, got) if theme.is_colour(v) != b]
        self.assertEqual(differ[:20], [], '%d of %d differ: (value, the browser takes it)' % (len(differ), len(values)))
        self.assertGreater(sum(got), 500)                                       # many taken, many refused
        self.assertGreater(len(got) - sum(got), 500)

    def test_the_forms_a_theme_does_not_take(self):
        self.assertEqual(self.supported(list(NOT_TAKEN)), [True] * len(NOT_TAKEN))
        self.assertEqual([v for v in NOT_TAKEN if theme.is_colour(v)], [])

    def test_tias_values(self):
        values = tias_values()
        self.assertEqual(len(values), len(theme.NAMES))
        self.assertEqual(self.supported(values), [True] * len(values))


class TheWrittenForm(InEdge):
    """The page holds a theme's colour as theme.written() writes it from the numbers read, never the file's text: so a
    value the browser would not draw cannot reach the page, whatever the reading lets through. The written form the
    browser takes in each case (red, green and blue each 0 to 255, an alpha of each of the browser's 256 steps, 0 and 1,
    one of many digits) and reads as the colour the value was: the same computed colour, or where the value has none
    (which the browser keeps as none in the computed colour) the same pixel drawn."""

    def values(self):
        """Every value of generated_values() a theme takes, TIA's own as its file writes them, and sweeps: hex of each
        red, green, blue and alpha 0 to 255, percentages in steps of .5, alphas of many digits."""
        out = [v for v in generated_values() if theme.is_colour(v)] + tias_values()
        out += ['#%02x%02x%02x%02x' % (k, 255 - k, (k * 7) % 256, k) for k in range(256)]
        out += ['rgb(%s%% %s%% 0%%)' % (k / 2, 100 - k / 2) for k in range(201)]
        out += ['rgba(1,2,3,%s)' % a for a in ('.25', '.18', '.08', '.123456', '.5019', '.0019', '.002', '1e-7', '5e-324',
                                               '.99999', '0', '1', '25%', '.5%')]
        return out

    def test_it_reads_as_the_colour_read(self):
        values = self.values()
        written = [theme.written(theme.colour(v)) for v in values]
        self.assertEqual({re.sub(r'[0-9.]+', 'n', w) for w in written}, {'rgba(n,n,n,n)'})
        got = self.read_by_edge(values + written)
        given, held = got[:len(values)], got[len(values):]
        self.assertEqual([w for w, (ok, _, _) in zip(written, held) if not ok], [])
        differ = [(v, w, a[1:], b[1:]) for v, w, a, b in zip(values, written, given, held)
                  if (a[2] != b[2] if 'none' in v.lower() else a[1] != b[1])]
        self.assertEqual(differ[:20], [], '%d of %d differ' % (len(differ), len(values)))
        self.assertGreater(sum('none' in v.lower() for v in values), 100)


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
            self.assertIn('@media screen{:where(:root){--wire:rgba(18,52,86,1)}}', good)

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
                self.assertIn('@media screen{:where(:root){--wire:rgba(18,52,86,1)}}', f.read())
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
                viewer_cli.main([JUMPS, '--html', out, '--theme', theme_file(d, {'--nope': '#000'}, 'bad.css')])
            self.assertEqual(e.exception.code, 2)
            self.assertIn('bad.css:3: --nope is no name of the palette', err.getvalue())


class TheDefaultTheme(unittest.TestCase):
    """%LOCALAPPDATA%\\tia-co-op\\theme.css (theme.user_theme(); the tests point it at a folder of their own through
    theme.ENV): the report and the viewer given no --theme draw in it when it is there; --theme tia draws without it;
    a faulty one stops them, named."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kept = os.environ[theme.ENV]
        self.path = os.environ[theme.ENV] = os.path.join(self.tmp.name, 'tia-co-op', 'theme.css')

    def tearDown(self):
        os.environ[theme.ENV] = self.kept
        self.tmp.cleanup()

    def put(self, values):
        os.makedirs(os.path.dirname(self.path))
        theme_file(os.path.dirname(self.path), values, 'theme.css')

    def test_the_place(self):
        self.assertEqual(theme.user_theme({'LOCALAPPDATA': r'C:\Users\u\AppData\Local'}),
                         r'C:\Users\u\AppData\Local\tia-co-op\theme.css')
        self.assertEqual(theme.user_theme({'LOCALAPPDATA': r'C:\Users\u\AppData\Local', theme.ENV: r'C:\t\theme.css'}),
                         r'C:\t\theme.css')
        self.assertEqual(theme.load().name, 'tia')                                   # not there: TIA's

    def test_a_child_process_reads_not_the_users_file(self):
        """The test package sets ENV, so a report a test starts as a child process reads no file of the user's: here
        a faulty one in the LOCALAPPDATA the child is given, which stops the report once ENV is gone."""
        self.put({'--wire': 'green'})
        local = os.path.join(self.tmp.name, 'local')
        shutil.copytree(os.path.dirname(self.path), os.path.join(local, 'tia-co-op'))
        out = os.path.join(self.tmp.name, 'child.html')
        run = lambda env: subprocess.run(                                               # noqa: E731
            [sys.executable, '-X', 'utf8', '-m', 'TiaChangeReports', os.path.join(PLANT, 'v1'),
             os.path.join(PLANT, 'v2'), '-o', out], cwd=ROOT, capture_output=True, text=True,
            env=dict(env, LOCALAPPDATA=local))
        r = run(dict(os.environ, **{theme.ENV: self.kept}))           # as the test package sets it
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            self.assertNotIn('@media screen', f.read())
        r = run({k: v for k, v in os.environ.items() if k != theme.ENV})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(os.path.join(local, 'tia-co-op', 'theme.css') + ':3: --wire: ', r.stderr)

    def test_the_report(self):
        self.put({'--wire': '#123456'})
        self.assertIn('@media screen{:where(:root){--wire:rgba(18,52,86,1)}}', report(self.tmp.name))
        self.assertNotIn('@media screen', report(self.tmp.name, '--theme', 'tia', name='tia.html'))

    def test_the_viewer(self):
        self.put({'--wire': '#123456'})
        out = os.path.join(self.tmp.name, 'v.html')
        quiet(viewer_cli.main, [JUMPS, '--html', out])
        with open(out, encoding='utf-8') as f:
            self.assertIn('@media screen{:where(:root){--wire:rgba(18,52,86,1)}}', f.read())

    def test_a_faulty_one(self):
        self.put({'--wire': 'green'})
        out, err = os.path.join(self.tmp.name, 'r.html'), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main([os.path.join(PLANT, 'v1'), os.path.join(PLANT, 'v2'), '-o', out])
        self.assertEqual(code, 2)
        self.assertIn('the default theme %s:3: --wire: ' % self.path, err.getvalue())
        self.assertIn('--theme tia draws without it', err.getvalue())
        self.assertFalse(os.path.exists(out))
        said = []
        self.assertEqual(viewer_cli.main([JUMPS], open_page=lambda p: self.fail('opened'), message=said.append), 2)
        self.assertIn('%s:3: --wire: ' % self.path, said[0])

    def test_a_faulty_one_with_html(self):
        """--html opens nothing, so the viewer runs from a console: a usage error on stderr, no message box."""
        self.put({'--wire': 'green'})
        out, err = os.path.join(self.tmp.name, 'v.html'), io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
            viewer_cli.main([JUMPS, '--html', out], message=lambda m: self.fail('a message box: %s' % m))
        self.assertEqual(e.exception.code, 2)
        self.assertIn('cannot read the default theme %s:3: --wire: ' % self.path, err.getvalue())
        self.assertIn('--theme tia draws without it', err.getvalue())
        self.assertFalse(os.path.exists(out))


# Every element's colours in the browser, its ::before and ::after too, the page's head and body with them.
PROPS = ['color', 'background-color', 'background-image', 'border-top-color', 'border-right-color',
         'border-bottom-color', 'border-left-color', 'outline-color', 'box-shadow', 'text-decoration-color', 'fill',
         'stroke', 'caret-color', 'column-rule-color']
# An HMI screen (svg.hs but its change outlines, .dl) and a colour value's swatch (.cs) take no theme: the project's
# colours, render.js's own marks on a screen in colours of their own, and TIA's text and background (theme.SCREEN;
# ATrialPalette.test_a_screen_takes_no_theme reads those). A moment after load, so that the HMI part has drawn the open
# object.
PROBE = """<script>addEventListener('load',function(){setTimeout(function(){var P=%s,o=[];
[].forEach.call(document.querySelectorAll('%s'),function(e){if(e.closest('script,style,.cs'))return;
 if(%s&&e.closest('svg.hs')&&!e.closest('.dl'))return;
 var svg=e instanceof SVGElement;
 [null,'::before','::after'].forEach(function(p){var c=getComputedStyle(e,p);if(p&&c.content=='none')return;
  P.forEach(function(k){if(!svg&&(k=='fill'||k=='stroke'))return;var v=c.getPropertyValue(k);o.push([e.tagName.toLowerCase()+'.'+(e.getAttribute('class')||'')+
   (p||''),k,v])})})});
var x=document.createElement('pre');x.id='colours';x.textContent=JSON.stringify(o);document.body.appendChild(x)},1000)})
</script>"""


def computed(edge, html, folder, name, inside='body', screen=False):
    """[(element, property, value)] of every element of html at or inside the selector inside; screen: an HMI
    screen's too."""
    probe = PROBE % (json.dumps(PROPS), '%s,%s *' % (inside, inside), 'false' if screen else 'true')
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

    def test_a_screen_takes_no_theme(self):
        """An HMI screen with no BackColor of its own and an object not drawn: its background and the label that says
        so are TIA's white and black under any theme, as on a page of TIA's; a change outline on it takes the theme."""
        from TiaChangeReports.tests.test_hmi_part import ROOT_ATTRS, rect, screen
        odd = ('<Hmi.Screen.NoSuchThing ID="3" CompositionName="ScreenItems"><AttributeList><Height>40</Height>'
               '<Left>100</Left><ObjectName>odd</ObjectName><Top>10</Top><Width>120</Width></AttributeList>'
               '</Hmi.Screen.NoSuchThing>')
        sides = []
        for side, items in (('b', rect('lamp')), ('a', rect('lamp', left=50) + odd)):
            folder = os.path.join(self.tmp.name, 'screen', side, 'hmi', 'screens')
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, 'Filler.xml'), 'w', encoding='utf-8') as f:
                f.write(screen('Filler', 10, items).replace(ROOT_ATTRS, ROOT_ATTRS.split('</BackColor>')[1]))
            sides.append(os.path.dirname(os.path.dirname(folder)))
        for spec in (self.trial.name, 'tia'):
            html = report(self.tmp.name, '--theme', spec, name='screen.html', sides=sides)
            got = computed(self.edge, html, self.tmp.name, 'screen-%s.html' % (spec != 'tia'), 'svg.hs', screen=True)
            self.assertEqual({v for el, k, v in got if el == 'svg.hs' and k == 'background-color'},
                             {'rgb(255, 255, 255)'}, spec)
            self.assertIn('text.line tag-label', {el for el, k, v in got}, spec)       # "not drawn: NoSuchThing"
            self.assertEqual({v for el, k, v in got if k == 'fill' and el.startswith('text.')}, {'rgb(0, 0, 0)'}, spec)
            self.assertEqual({v for el, k, v in got if k == 'color' and (el == 'svg.hs' or el.startswith('text.'))},
                             {'rgb(0, 0, 0)'}, spec)
            outlines = {v for el, k, v in got
                        if k == 'stroke' and re.match(r'(rect|circle)\.(added|changed|moved)', el)}
            self.assertTrue(outlines, spec)
            self.assertEqual(outlines <= self.allowed, spec != 'tia', (spec, outlines))

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
