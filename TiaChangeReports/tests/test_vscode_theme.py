"""A VS Code color theme as the report's theme (vscode_theme.py): the file read as VS Code writes them, comments,
trailing commas, include and a .tmTheme among it, and refused with its file and line where it is no color theme or
holds no colour (TheFile); its kind (TheKind); a word's colour by its scope (TokenColours); the table against the dev
doc (TheTable); a colour with an alpha laid over its ground, alpha 0 passed over or refused (Alpha); the theme's own
tia.<name> ids (TiaIds); and every pair to keep readable over the fixture themes, each kind, which fail with a rule
taken out (EasyToRead). The fixture themes (fixtures\\themes\\) are written for the tests."""
import json
import math
import os
import re
import tempfile
import unittest

from TiaChangeReports import theme
from TiaChangeReports import vscode_theme as vt

HERE = os.path.dirname(os.path.abspath(__file__))
THEMES = os.path.join(HERE, 'fixtures', 'themes')
ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURES = {
    'night': os.path.join(THEMES, 'night.json'),                                 # dark, an include, alphas
    'paper': os.path.join(THEMES, 'paper.json'),                                 # light, no type, faint words
    'contrast-dark': os.path.join(THEMES, 'contrast-ext', 'themes', 'contrast-dark.json'),
    'contrast-light': os.path.join(THEMES, 'contrast-ext', 'themes', 'contrast-light.json'),
    'teal': os.path.join(THEMES, 'teal.json'),                                   # tinted, a .tmTheme
    'grey': os.path.join(THEMES, 'grey.json'),                                   # a mid-grey page
}


def fails(values):
    """The pairs under their bound in values."""
    return [p for p in theme.PAIRS if vt.contrast(values[p[0]], values[p[1]]) < vt.bound(p) - 1e-9]


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def refused(self, text, line, what, name='t.json'):
        path = self.put(name, text)
        with self.assertRaises(theme.ThemeError) as e:
            vt.palette(vt.read(path))
        self.assertTrue(str(e.exception).startswith('%s:%d: ' % (path, line)), str(e.exception))
        self.assertIn(what, str(e.exception))


class TheFile(Files):
    """A theme file as VS Code's are: JSON with comments and trailing commas; its include followed, its own colors
    over the included ones, its tokenColors after theirs; a .tmTheme for tokenColors. What is no color theme or holds
    a value that is no colour is refused with the file and the line."""

    def test_comments_trailing_commas_and_an_include(self):
        src = vt.read(FIXTURES['night'])
        self.assertEqual(src.name, 'Night (test)')
        self.assertEqual(src.colors['editor.background'], (0x16, 0x18, 0x1d, 1.0))          # the included file's
        self.assertEqual(src.colors['editor.foreground'], (0xc8, 0xc8, 0xc8, 1.0))          # over it, its own
        self.assertNotIn('editor.lineHighlightBackground', src.colors)                     # null: none given
        self.assertEqual(vt.token_colour(src.rules, 'comment.line.double-slash.scl'), (0x4f, 0x6f, 0x4f, 1.0))
        self.assertEqual(src.files, [FIXTURES['night'], os.path.join(THEMES, 'night-base.json')])

    def test_a_tm_theme(self):
        src = vt.read(FIXTURES['teal'])
        self.assertEqual(vt.token_colour(src.rules, 'keyword.control.scl'), (0x85, 0x99, 0x00, 1.0))
        values, origin = vt.palette(src, move=False)
        self.assertEqual((values['--page'], origin['--page']), ((0, 0x2b, 0x36, 1.0), 'tokenColors'))
        self.assertEqual(values['--text'], (0x83, 0x94, 0x96, 1.0))

    def test_the_lines_of_a_json_text(self):
        j = vt.parse('// a\n{\n  "a": 1, /* b\n */ "b": [1, 2,],\n  "c": {"d": null,},\n}\n', 'x')
        self.assertEqual(j, {'a': 1, 'b': [1, 2], 'c': {'d': None}})
        self.assertEqual((j.lines, j['c'].lines, j.line), ({'a': 3, 'b': 4, 'c': 5}, {'d': 5}, 2))

    def test_what_is_no_json(self):
        self.refused('{\n  "colors": {\n    "editor.background": #fff\n  }\n}', 3, 'not JSON')
        self.refused('{\n  "colors": {}\n}\n}', 4, 'not JSON')
        self.refused('{\n  "colors": {\n', 3, 'not JSON: a key in quotes or } expected')
        self.refused('.ldiff {\n  --wire: #000;\n}\n', 1, 'not JSON', 'theme.css')

    def test_what_is_no_color_theme(self):
        self.refused('[1, 2]', 1, 'not a VS Code color theme')
        self.refused('{\n  "name": "x"\n}', 1, 'none of "colors", "tokenColors" and "include"')
        self.refused('{\n  "colors": [1]\n}', 2, '"colors" is not an object')
        self.refused('{\n  "tokenColors": 5\n}', 2, '"tokenColors" is neither a list of rules nor')
        self.refused('{\n  "tokenColors": [\n    {"scope": 1, "settings": {}}\n  ]\n}', 3, '"scope" is neither')

    def test_a_value_that_is_no_colour(self):
        for value in ('"blue"', '"#12"', '"rgb(1, 2, 3)"', '"transparent"', '"#fff "', '12', '"var(--x)"'):
            self.refused('{\n  "colors": {\n    "editor.background": %s\n  }\n}' % value, 3,
                         '"colors": "editor.background": %s is not a colour; VS Code writes one as #RGB, #RGBA, '
                         '#RRGGBB or #RRGGBBAA' % value)
        self.refused('{\n  "tokenColors": [\n    {"scope": "comment",\n     "settings": {"foreground": "green"}}\n  ]'
                     '\n}', 4, '"tokenColors" [0]: "foreground": "green" is not a colour')

    def test_an_include_that_is_not_there_or_itself(self):
        self.refused('{\n  "include": "./nope.json"\n}', 2, '"include": ')
        a = self.put('a.json', '{"include": "./b.json"}')
        self.put('b.json', '{\n  "include": "./a.json"\n}')
        with self.assertRaises(theme.ThemeError) as e:
            vt.read(a)
        self.assertIn('includes itself', str(e.exception))

    def test_an_include_of_an_absolute_path(self):
        """The user's theme.json as {"include": "<the theme's file>"}: the name and kind are the included theme's."""
        path = self.put('theme.json', json.dumps({'include': FIXTURES['contrast-dark']}))
        src = vt.read(path)
        self.assertEqual((src.name, vt.kind_of(src)), ('Contrast Dark (test)', 'hcDark'))

    def test_the_rest_is_not_read(self):
        """semanticTokenColors, $schema and an unknown type are no fault."""
        src = vt.read(self.put('t.json', '{"type": "neon", "semanticTokenColors": {"x": 1}, "colors": {}}'))
        self.assertIsNone(src.kind)


class TheKind(Files):
    def test_the_type(self):
        self.assertEqual(vt.kind_of(vt.read(FIXTURES['night'])), 'dark')
        for t, k in (('light', 'light'), ('vs-dark', 'dark'), ('hc', 'hcDark'), ('hc-black', 'hcDark'),
                     ('hcLight', 'hcLight'), ('hc-light', 'hcLight')):
            self.assertEqual(vt.kind_of(vt.read(self.put('t.json', json.dumps({'type': t, 'colors': {}})))), k, t)

    def test_a_package_json_beside_it(self):
        """An installed theme says its kind as uiTheme in its extension's package.json."""
        self.assertEqual(vt.kind_of(vt.read(FIXTURES['contrast-dark'])), 'hcDark')
        self.assertEqual(vt.kind_of(vt.read(FIXTURES['contrast-light'])), 'hcLight')

    def test_by_the_page(self):
        self.assertEqual(vt.kind_of(vt.read(FIXTURES['paper'])), 'light')
        self.assertEqual(vt.kind_of(vt.read(FIXTURES['teal'])), 'dark')
        self.assertEqual(vt.kind_of(vt.read(self.put('t.json', '{"colors": {}}'))), 'light')

    def test_the_kinds_page_and_text(self):
        """A theme that gives no page and no text: its kind's."""
        values, origin = vt.palette(vt.read(FIXTURES['contrast-light']), move=False)
        self.assertEqual((values['--page'], values['--text'], origin['--page']),
                         ((255, 255, 255, 1.0), (0, 0, 0, 1.0), 'kind'))
        values, _ = vt.palette(vt.read(self.put('t.json', '{"type": "dark", "colors": {}}')), move=False)
        self.assertEqual((values['--page'], values['--text']), ((0x1e, 0x1e, 0x1e, 1.0), (0xd4, 0xd4, 0xd4, 1.0)))

    def test_a_high_contrast_themes_lines(self):
        values, origin = vt.palette(vt.read(FIXTURES['contrast-dark']))
        for name in ('--grid', '--box-line', '--button-line'):
            self.assertEqual(values[name], (0x6f, 0xc3, 0xdf, 1.0), name)
        values, _ = vt.palette(vt.read(FIXTURES['contrast-light']))
        self.assertEqual(values['--grid'], values['--text'])                         # no contrastBorder: the text


class TokenColours(unittest.TestCase):
    """As VS Code matches a scope: a selector matches a scope it is equal to or a dot-prefix of, the one of most parts
    wins, a later rule over an earlier one of as many; a rule with no foreground and a selector of two scopes give
    none."""

    def rules(self, *rs):
        return [(sels, theme.colour(fg) if fg else None, None) for sels, fg in rs]

    def test_matching(self):
        rules = self.rules((['keyword'], '#000001'), (['keyword.control'], '#000002'), (['keyword.control'], '#000003'),
                           (['keyword.control.directive'], None), (['source.scl keyword.control.scl'], '#000004'),
                           (['keywords'], '#000005'), (['-keyword'], '#000006'))
        self.assertEqual(vt.token_colour(rules, 'keyword.control.scl'), (0, 0, 3, 1.0))
        self.assertEqual(vt.token_colour(rules, 'keyword.control.directive.scl'), (0, 0, 3, 1.0))
        self.assertEqual(vt.token_colour(rules, 'keyword.operator.scl'), (0, 0, 1, 1.0))
        self.assertIsNone(vt.token_colour(rules, 'variable.other.scl'))
        self.assertIsNone(vt.token_colour(rules, 'keywordx.scl'))

    def test_no_rule_the_text(self):
        """A word no rule colours is drawn in the theme's text, as in VS Code."""
        values, origin = vt.palette(vt.read(FIXTURES['grey']), move=False)
        self.assertEqual((values['--scl-operand'], origin['--scl-operand']), (values['--text'], 'text'))


class TheTable(unittest.TestCase):
    """TABLE has a row for each name, in the palette's order, each id or scope a string and each rule one of RULES;
    the dev doc's table says the same, with each name's tia.* id and TIA's value."""

    def test_each_name_once(self):
        self.assertEqual(list(vt.TABLE), theme.NAMES)
        for name, (sources, rule) in vt.TABLE.items():
            self.assertIn(rule, vt.RULES, name)
            self.assertTrue(all(re.fullmatch(r'[a-zA-Z][a-zA-Z0-9.-]*', s) for s in sources), name)
        self.assertTrue(set(vt.ALPHA) | set(vt.VISIBLE) <= set(theme.NAMES))
        self.assertFalse(set(vt.ALPHA) & set(vt.VISIBLE))
        self.assertEqual(len(vt.VISIBLE), len(set(vt.VISIBLE)))

    def test_the_dev_docs_table(self):
        with open(os.path.join(ROOT, 'docs', 'dev', 'tools', 'tia-change-reports.md'), encoding='utf-8') as f:
            rows = re.findall(r'^\| `(--[a-z0-9-]+)` \| `(tia\.[a-z0-9-]+)` \| `(#[0-9a-f]{3,8}|rgba\([^)]*\))` \| '
                              r'(.*?) \| (\w+) \|$', f.read(), re.M)
        self.assertEqual([r[0] for r in rows], theme.NAMES)
        for name, tia_id, value, sources, rule in rows:
            self.assertEqual(tia_id, 'tia.' + name[2:])
            self.assertEqual(theme.palette_colour(value), theme.NATIVE[name], name)
            self.assertEqual((tuple(re.findall(r'`([^`]+)`', sources)), rule), vt.TABLE[name], name)


class Alpha(Files):
    """A theme's colour with an alpha is laid over what it stands on: a changed word's mark over its line's, the
    rest over the page, as VS Code draws them; ALPHA's names keep it. A colour of alpha 0 from the theme's own ids is
    passed over."""

    def test_laid_over_the_ground(self):
        src = vt.read(FIXTURES['night'])
        values, origin = vt.palette(src, move=False)
        page = values['--page']
        line = vt.over(src.colors['diffEditor.insertedLineBackground'], page)
        self.assertEqual(values['--added-fill'], line)
        self.assertEqual(values['--added-word'], vt.over(src.colors['diffEditor.insertedTextBackground'], line))
        self.assertEqual(values['--hover'], vt.over(src.colors['list.hoverBackground'], page))
        self.assertEqual(values['--shadow'], (0, 0, 0, 128 / 255))
        self.assertEqual({n for n, c in values.items() if c[3] < 1}, set(vt.ALPHA))

    def test_alpha_0_passed_over(self):
        """editorWidget.border is #00000000: the window's line takes widget.border, the next of the table; a button
        with no colour takes the rule."""
        values, origin = vt.palette(vt.read(FIXTURES['night']), move=False)
        self.assertEqual((values['--window-line'], origin['--window-line']), ((0x3a, 0x3a, 0x3a, 1.0), 'widget.border'))
        self.assertEqual(origin['--button'], 'axis')

    def test_a_tia_value_of_alpha_0(self):
        """Refused for a line, a text or a mark; taken for the rest, a shadow as it is."""
        for name, what in (('wire', 'a line'), ('lad-text', 'a text'), ('moved-fill', 'a change mark')):
            self.refused('{\n  "colors": {\n    "tia.%s": "#0000"\n  }\n}' % name, 3,
                         '"colors": "tia.%s" is fully transparent: it would take %s off the page' % (name, what))
        path = self.put('ok.json', '{"colors": {"tia.shadow": "#0000", "tia.band": "#ff000000"}}')
        values, _ = vt.palette(vt.read(path))
        self.assertEqual(values['--shadow'], (0, 0, 0, 0.0))
        self.assertEqual(values['--band'], values['--page'])


class TiaIds(Files):
    def test_they_win_and_are_not_moved(self):
        """tia.<name> wins over the table and is drawn as written, even where a pair under it does not hold."""
        path = self.put('t.json', '{"include": %s, "colors": {"tia.lad-text": "#20242c", "tia.box": "#123"}}'
                        % json.dumps(FIXTURES['night']))
        values, origin = vt.palette(vt.read(path))
        self.assertEqual((values['--lad-text'], origin['--lad-text']), ((0x20, 0x24, 0x2c, 1.0), 'tia.lad-text'))
        self.assertEqual(values['--box'], (0x11, 0x22, 0x33, 1.0))
        self.assertIn(('--lad-text', '--page'), fails(values))

    def test_an_id_that_is_no_name(self):
        self.refused('{\n  "colors": {\n    "tia.wires": "#000"\n  }\n}', 3,
                     '"colors": "tia.wires" is no name of the palette (the names: docs\\dev\\tools\\tia-change-reports.md)')


class EasyToRead(unittest.TestCase):
    """Every pair at the head of tia-theme.css holds its bound, TIA's own contrast at most 4.5 to 1, under every
    fixture theme; with the moves taken out, or the axis rule, some do not."""

    @classmethod
    def setUpClass(cls):
        cls.src = {k: vt.read(p) for k, p in FIXTURES.items()}

    def test_the_kinds(self):
        self.assertEqual({vt.kind_of(s) for s in self.src.values()}, {'light', 'dark', 'hcDark', 'hcLight'})

    def test_the_bound(self):
        self.assertEqual(vt.bound(('--text', '--page')), 4.5)
        self.assertAlmostEqual(vt.bound(('--faint', '--page')), vt.contrast(theme.NATIVE['--faint'], (255, 255, 255)))
        self.assertLess(vt.bound(('--faint', '--page')), 4.5)

    def test_every_pair_under_every_theme(self):
        for k, s in self.src.items():
            values, _ = vt.palette(s)
            self.assertEqual(fails(values), [], k)

    def test_tias_own_holds(self):
        self.assertEqual(fails(theme.NATIVE), [])

    def test_without_the_moves(self):
        for k in ('night', 'paper', 'teal', 'grey'):
            self.assertTrue(fails(vt.palette(self.src[k], move=False)[0]), k)

    def test_without_the_axis_rule(self):
        """TIA's own values where the theme has no colour: TIA's light boxes and bands on a dark page."""
        rules = tuple(r for r in vt.RULES if r != 'axis')
        self.assertTrue(fails(vt.palette(self.src['teal'], rules=rules)[0]))
        values, _ = vt.palette(self.src['teal'], rules=rules, move=False)
        self.assertEqual(values['--band'], theme.NATIVE['--band'])

    def test_the_marks_keep_their_hue(self):
        """The four marks stay apart in every theme, as in TIA's: each mark's colour and fill stands from the page in
        TIA's hue (OKLab, within 45 degrees), green, red, yellow and blue, in a dark or tinted theme too."""
        def hue(c, page):
            (_, a, b), (_, a0, b0) = vt.oklab(c), vt.oklab(page)
            return math.degrees(math.atan2(b - b0, a - a0))
        for k, s in self.src.items():
            values, _ = vt.palette(s)
            for name in ('--added', '--added-fill', '--removed', '--removed-fill', '--changed', '--changed-fill',
                         '--moved', '--moved-fill'):
                d = hue(values[name], values['--page']) - hue(theme.NATIVE[name], theme.NATIVE['--page'])
                self.assertLess(abs((d + 180) % 360 - 180), 45, (k, name, values[name]))

if __name__ == '__main__':
    unittest.main()
