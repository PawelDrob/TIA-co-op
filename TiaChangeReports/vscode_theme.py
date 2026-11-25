"""A VS Code color theme as the report's theme: the file read as VS Code reads it, its kind told, and its colours put
onto the palette's names (theme.NAMES) by TABLE and the rules below, every pair to keep readable (theme.PAIRS) then
moved until it reads as well as in TIA's native theme.

  read(path)            -> Source: the theme's name, kind, colors {id: (red, green, blue, alpha)} and token rules,
                           its include followed. ThemeError, with the file and the line, for a file that is no color
                           theme or holds a value that is no colour
  palette(src)          -> ({name: (red, green, blue, alpha)} for every name, {name: where it came from})
  contrast(a, b)        -> WCAG's contrast ratio of two opaque colours
  bound(pair)           -> the contrast a pair is held to: TIA's own, at most 4.5 to 1 (WCAG's floor for text)

  python -m TiaChangeReports.vscode_theme <tia|file>   writes the theme's block alone (theme.block), for a host that
                                                      lays it over fragments drawn in --theme tia

The file: JSON with // and /* */ comments and trailing commas. Read of it: name, type, colors, tokenColors (a list, or
the path of a .tmTheme), include (a theme file, from this one's folder or by a full path: its colors under this one's,
its tokenColors before this one's). A token rule with no scope gives editor.background and editor.foreground where colors does not.
semanticTokenColors and the rest are not read: the report has no semantic tokens.

The kind (KINDS): the type of the file or of a file it includes, else uiTheme of a package.json beside one of those
or up to two folders above that names that file (an installed theme's), else light or dark by the page's luminance.

A name takes, in order: the theme's own tia.<name> (refused with alpha 0 for a line, a text or a mark, VISIBLE; never
moved), else the first of TABLE's ids or token scopes (a source ending in .scl) the theme gives, a value with alpha 0
passed over, else TABLE's rule. Every name but ALPHA's is then laid over its ground (GROUND, else the page) as the
browser lays a colour with alpha, so that what is drawn is opaque and its contrast is known.
"""
import json
import math
import os
import plistlib
import re
import sys

from TiaChangeReports import theme

ThemeError = theme.ThemeError

KINDS = {'light': 'light', 'vs': 'light', 'dark': 'dark', 'vs-dark': 'dark', 'hc': 'hcDark', 'hcDark': 'hcDark',
         'hc-black': 'hcDark', 'hcLight': 'hcLight', 'hc-light': 'hcLight'}
HIGH_CONTRAST = ('hcDark', 'hcLight')
# The page and the text of a theme that gives none, by kind. Dark's are Dark (Visual Studio)'s, the theme VS Code's
# built-in dark themes include.
KIND_PAGE = {'light': ('#ffffff', '#000000'), 'dark': ('#1e1e1e', '#d4d4d4'), 'hcDark': ('#000000', '#ffffff'),
             'hcLight': ('#ffffff', '#000000')}

# The rules, for a name no id or scope of the theme gives:
#   axis   TIA's value moved onto the theme's axis from its page to its text (on_axis): where it stands between
#          TIA's white page and black text, there between the theme's, with TIA's own hue and chroma
#   line   a line: in a high contrast theme contrastBorder, else the theme's text, as such a theme frames every part;
#          in another, axis
#   text   the theme's text (--text): what VS Code draws a word in that no token rule colours
#   kind   the kind's page and text (KIND_PAGE)
#   tia    TIA's value as it is: a shadow is dark in any theme
# A source ending in .scl is a token scope, as a TextMate grammar of SCL would give the word; the others are ids of
# the theme's colors.
TABLE = {
    '--page': (('editor.background',), 'kind'),
    '--text': (('editor.foreground', 'foreground'), 'kind'),
    '--muted': (('descriptionForeground',), 'axis'),
    '--faint': (('editorLineNumber.foreground',), 'axis'),
    '--empty-field-text': (('input.placeholderForeground',), 'axis'),
    '--viewer-note': (('descriptionForeground',), 'axis'),
    '--link': (('textLink.foreground',), 'axis'),
    '--link-underline': ((), 'axis'),
    '--match': (('list.highlightForeground',), 'axis'),
    '--page-head': ((), 'axis'),
    '--page-head-line': ((), 'line'),
    '--band': ((), 'axis'),
    '--field': ((), 'axis'),
    '--row': ((), 'axis'),
    '--network-number': ((), 'axis'),
    '--line': ((), 'line'),
    '--grid': ((), 'line'),
    '--edge': ((), 'line'),
    '--divider': ((), 'line'),
    '--no-line': ((), 'axis'),
    '--opened-member': ((), 'axis'),
    '--added': (('gitDecoration.addedResourceForeground', 'editorGutter.addedBackground'), 'axis'),
    '--added-fill': (('diffEditor.insertedLineBackground',), 'axis'),
    '--added-word': (('diffEditor.insertedTextBackground',), 'axis'),
    '--removed': (('gitDecoration.deletedResourceForeground', 'editorGutter.deletedBackground'), 'axis'),
    '--removed-fill': (('diffEditor.removedLineBackground',), 'axis'),
    '--removed-word': (('diffEditor.removedTextBackground',), 'axis'),
    '--changed': (('gitDecoration.modifiedResourceForeground', 'editorGutter.modifiedBackground'), 'axis'),
    '--changed-fill': ((), 'axis'),
    '--changed-row': ((), 'axis'),
    '--moved': (('gitDecoration.renamedResourceForeground',), 'axis'),
    '--moved-fill': ((), 'axis'),
    '--moved-row': ((), 'axis'),
    '--same': ((), 'axis'),
    '--same-mark': ((), 'axis'),
    '--version': ((), 'axis'),
    '--badge-text': ((), 'axis'),
    '--mark-line': ((), 'line'),
    '--off-over-mark': ((), 'axis'),
    '--button': (('button.secondaryBackground',), 'axis'),
    '--button-hover': (('button.secondaryHoverBackground',), 'axis'),
    '--button-line': (('button.border',), 'line'),
    '--button-text': (('button.secondaryForeground',), 'axis'),
    '--button-off-text': (('disabledForeground',), 'axis'),
    '--switch': ((), 'axis'),
    '--switch-on': ((), 'axis'),
    '--input': (('input.background',), 'axis'),
    '--input-text': (('input.foreground',), 'axis'),
    '--focus': (('focusBorder',), 'axis'),
    '--hover': (('list.hoverBackground',), 'axis'),
    '--selected': (('list.activeSelectionBackground',), 'axis'),
    '--change-hover': (('list.hoverBackground',), 'axis'),
    '--icon': (('icon.foreground',), 'axis'),
    '--tree-icon': (('icon.foreground',), 'axis'),
    '--window-line': (('editorWidget.border', 'widget.border'), 'line'),
    '--shadow': (('widget.shadow',), 'tia'),
    '--backdrop': ((), 'tia'),
    '--minimap-view': (('minimapSlider.background',), 'axis'),
    '--minimap-view-line': ((), 'axis'),
    '--error-fill': (('inputValidation.errorBackground',), 'axis'),
    '--error-line': (('inputValidation.errorBorder',), 'axis'),
    '--checkbox': (('checkbox.background',), 'axis'),
    '--checkbox-line': (('checkbox.border',), 'line'),
    '--checkbox-on': (('button.background',), 'axis'),
    '--checkbox-on-line': (('button.background',), 'axis'),
    '--checkbox-tick': (('button.foreground',), 'axis'),
    '--checkbox-off': ((), 'axis'),
    '--checkbox-off-line': ((), 'line'),
    '--checkbox-off-on': ((), 'axis'),
    '--checkbox-off-on-line': ((), 'line'),
    '--checkbox-off-tick': ((), 'axis'),
    '--wire': ((), 'axis'),
    '--lad-text': (('editor.foreground', 'foreground'), 'axis'),
    '--lad-comment': (('comment.line.double-slash.scl',), 'text'),
    '--lad-value': (('constant.numeric.scl',), 'text'),
    '--lad-constant': (('constant.language.scl',), 'text'),
    '--lad-default': (('editorInlayHint.foreground',), 'axis'),
    '--lad-number': (('entity.name.type.scl',), 'text'),
    '--eno-off': (('disabledForeground',), 'axis'),
    '--pin-open': ((), 'axis'),
    '--box': ((), 'axis'),
    '--box-line': ((), 'line'),
    '--box-head': ((), 'axis'),
    '--box-cell-line': ((), 'line'),
    '--compare-type': ((), 'axis'),
    '--expression': ((), 'axis'),
    '--calculator': ((), 'axis'),
    '--calculator-line': ((), 'axis'),
    '--conversion': ((), 'axis'),
    '--conversion-light': ((), 'axis'),
    '--jump-label': ((), 'axis'),
    '--jump-label-line': ((), 'axis'),
    '--scl-keyword': (('keyword.control.scl',), 'text'),
    '--scl-region': (('meta.preprocessor.region.scl',), 'text'),
    '--scl-constant': (('constant.numeric.scl',), 'text'),
    '--scl-comment': (('comment.line.double-slash.scl',), 'text'),
    '--scl-operand': (('variable.other.scl',), 'text'),
    '--scl-local-constant': (('variable.other.constant.scl',), 'text'),
    '--scl-block-call': (('entity.name.function.scl',), 'text'),
    '--scl-instruction': (('support.function.scl',), 'text'),
    '--scl-parameter': (('variable.parameter.scl',), 'text'),
    '--scl-operator': (('keyword.operator.scl',), 'text'),
    '--screen-surround': ((), 'axis'),
    '--screen-edge': ((), 'line'),
    '--object-selected': (('focusBorder',), 'axis'),
    '--checker': ((), 'axis'),
    '--checker-light': ((), 'axis'),
    '--swatch-line': ((), 'line'),
}
RULES = ('axis', 'line', 'text', 'kind', 'tia')

# The names drawn with their alpha, over what they lie on: no ground.
ALPHA = ('--shadow', '--backdrop', '--minimap-view', '--off-over-mark')
# What a name with an alpha is laid over where it is not the page: a changed word's mark over its line's.
GROUND = {'--added-word': '--added-fill', '--removed-word': '--removed-fill'}
# The names that draw a line, a text or a change mark: a tia.* value of alpha 0 for one would take it off the page.
VISIBLE = (
    # text
    '--text', '--muted', '--faint', '--empty-field-text', '--viewer-note', '--link', '--match', '--badge-text',
    '--button-text', '--button-off-text', '--input-text', '--icon', '--tree-icon', '--checkbox-tick',
    '--checkbox-off-tick', '--lad-text', '--lad-comment', '--lad-value', '--lad-constant', '--lad-default',
    '--lad-number', '--eno-off', '--scl-keyword', '--scl-region', '--scl-constant', '--scl-comment', '--scl-operand',
    '--scl-local-constant', '--scl-block-call', '--scl-instruction', '--scl-parameter', '--scl-operator',
    # lines
    '--link-underline', '--page-head-line', '--line', '--grid', '--edge', '--divider', '--mark-line', '--button-line',
    '--focus', '--window-line', '--minimap-view-line', '--error-line', '--checkbox-line', '--checkbox-on-line',
    '--checkbox-off-line', '--checkbox-off-on-line', '--wire', '--pin-open', '--box-line', '--box-cell-line',
    '--calculator-line', '--jump-label-line', '--screen-edge', '--object-selected', '--swatch-line',
    # the change marks
    '--added', '--added-fill', '--added-word', '--removed', '--removed-fill', '--removed-word', '--changed',
    '--changed-fill', '--changed-row', '--moved', '--moved-fill', '--moved-row',
)
HEX_FORMS = '#RGB, #RGBA, #RRGGBB or #RRGGBBAA'
NAMES_DOC = r'docs\dev\tools\tia-change-reports.md'        # the table of the names, their tia.* ids and TIA's values


# --- the file: JSON with comments and trailing commas, each object's keys with their lines

class Obj(dict):
    """A JSON object; lines: {key: the line it stands on}; line: the line of its {."""
    lines = {}
    line = 1


_TOKEN = re.compile(r'''[ \t\r\n]+|//[^\n]*|/\*.*?\*/|"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"
                    |-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null|[{}\[\]:,]''', re.S | re.X)


def parse(text, where):
    """The value of a JSON text with comments and trailing commas, its objects Obj. where: the file, for the
    messages."""
    toks, pos, line = [], 0, 1
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ThemeError('%s:%d: not JSON: %r' % (where, line, text[pos:pos + 20]))
        t = m.group()
        if not (t.startswith('/*') or t.startswith('//') or not t.strip()):
            toks.append((t, line))
        line += t.count('\n')
        pos = m.end()
    i = 0

    def fail(what):
        line = toks[i][1] if i < len(toks) else text.count('\n') + 1
        raise ThemeError('%s:%d: not JSON: %s' % (where, line, what))

    def value():
        nonlocal i
        if i >= len(toks):
            fail('the text ends where a value should be')
        t, line = toks[i]
        i += 1
        if t == '{':
            obj, obj.lines, obj.line = Obj(), {}, line
            while True:
                if i < len(toks) and toks[i][0] == '}':
                    i += 1
                    return obj
                if i >= len(toks) or not toks[i][0].startswith('"'):
                    fail('a key in quotes or } expected')
                key, kline = _string(toks[i][0]), toks[i][1]
                i += 1
                if i >= len(toks) or toks[i][0] != ':':
                    fail(': expected after %r' % key)
                i += 1
                obj[key], obj.lines[key] = value(), kline
                if i < len(toks) and toks[i][0] == ',':
                    i += 1
                elif i >= len(toks) or toks[i][0] != '}':
                    fail(', or } expected')
        if t == '[':
            arr = []
            while True:
                if i < len(toks) and toks[i][0] == ']':
                    i += 1
                    return arr
                arr.append(value())
                if i < len(toks) and toks[i][0] == ',':
                    i += 1
                elif i >= len(toks) or toks[i][0] != ']':
                    fail(', or ] expected')
        if t.startswith('"'):
            return _string(t)
        if t in ('true', 'false', 'null'):
            return {'true': True, 'false': False, 'null': None}[t]
        if t[0] in '-0123456789':
            return float(t) if any(c in t for c in '.eE') else int(t)
        i -= 1
        fail('%r where a value should be' % t)

    v = value()
    if i < len(toks):
        fail('%r after the value' % toks[i][0])
    return v


_string = json.loads


# --- what a theme gives

class Source:
    """A theme as read: name (or None), kind (or None), colors {id: colour}, where {id: 'file:line'} of each, rules
    [(selectors, foreground, background)] of tokenColors in order, path, files: path and the files it includes, in
    order."""

    def __init__(self, path):
        self.path, self.name, self.kind, self.colors, self.where, self.rules = path, None, None, {}, {}, []
        self.files = [path]


def _colour(value, where, what):
    c = theme.colour(value) if isinstance(value, str) else None
    if c is None:
        raise ThemeError('%s: %s: %s is not a colour; VS Code writes one as %s'
                         % (where, what, _show(value), HEX_FORMS))
    return c


def _show(value):
    return json.dumps(value)


def read(path, _seen=()):
    """The theme of the file at path, its include followed. Raises ThemeError for a file that does not read, is no
    color theme, holds a value that is no colour, includes a file that is not there or itself."""
    path = os.path.abspath(path)
    if os.path.normcase(path) in _seen:
        raise ThemeError('%s: includes itself, through %s' % (path, ' -> '.join(_seen)))
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read()
    except UnicodeDecodeError as ex:
        raise ThemeError('%s: the theme file cannot be read: it is not UTF-8 (%s)' % (path, ex))
    except OSError as ex:
        raise ThemeError('%s: the theme file cannot be read: %s' % (path, ex.strerror or ex))
    j = parse(text, path)
    if not isinstance(j, Obj) or not ({'colors', 'tokenColors', 'include'} & set(j)):
        raise ThemeError('%s:%d: not a VS Code color theme: it holds none of "colors", "tokenColors" and "include"'
                         % (path, j.line if isinstance(j, Obj) else 1))
    at = lambda key: '%s:%d' % (path, j.lines[key])                      # noqa: E731
    src = Source(path)
    if 'include' in j:
        inc = j['include']
        if not isinstance(inc, str):
            raise ThemeError('%s: "include": %s is not the path of a theme file' % (at('include'), _show(inc)))
        full = os.path.join(os.path.dirname(path), inc)
        if not os.path.isfile(full):
            raise ThemeError('%s: "include": %s is no file' % (at('include'), full))
        base = read(full, _seen + (os.path.normcase(path),))
        src.name, src.kind, src.colors, src.where, src.rules = (base.name, base.kind, dict(base.colors),
                                                                dict(base.where), list(base.rules))
        src.files += base.files
    if isinstance(j.get('name'), str):
        src.name = j['name']
    if isinstance(j.get('type'), str) and j['type'] in KINDS:
        src.kind = KINDS[j['type']]
    colors = j.get('colors')
    if colors is not None:
        if not isinstance(colors, Obj):
            raise ThemeError('%s: "colors" is not an object of colour ids' % at('colors'))
        for key, value in colors.items():
            if value is None:
                continue
            where = '%s:%d' % (path, colors.lines[key])
            src.colors[key] = _colour(value, where, '"colors": "%s"' % key)
            src.where[key] = where
    tokens = j.get('tokenColors')
    if isinstance(tokens, str):
        src.rules += _tm_theme(os.path.join(os.path.dirname(path), tokens), at('tokenColors'))
    elif isinstance(tokens, list):
        src.rules += _token_rules(tokens, path, j.lines['tokenColors'])
    elif tokens is not None:
        raise ThemeError('%s: "tokenColors" is neither a list of rules nor the path of a .tmTheme' % at('tokenColors'))
    return src


def _token_rules(entries, path, line):
    """[(selectors, foreground, background)] of tokenColors' entries."""
    out = []
    for k, e in enumerate(entries):
        where = '%s:%d' % (path, e.line if isinstance(e, Obj) else line)
        if not isinstance(e, dict):
            raise ThemeError('%s: "tokenColors" [%d] is not a rule {"scope": ..., "settings": {...}}' % (where, k))
        settings = e.get('settings') or {}
        if not isinstance(settings, dict):
            raise ThemeError('%s: "tokenColors" [%d]: "settings" is not an object' % (where, k))
        scope = e.get('scope')
        if isinstance(scope, str):
            sels = [s.strip() for s in scope.split(',')]
        elif isinstance(scope, list) and all(isinstance(s, str) for s in scope):
            sels = [p.strip() for s in scope for p in s.split(',')]
        elif scope is None:
            sels = None
        else:
            raise ThemeError('%s: "tokenColors" [%d]: "scope" is neither a string nor a list of strings' % (where, k))
        got = []
        for prop in ('foreground', 'background'):
            v = settings.get(prop)
            got.append(None if v is None else _colour(v, '%s:%d' % (path, settings.lines.get(prop, line))
                                                      if isinstance(settings, Obj) else where,
                                                      '"tokenColors" [%d]: "%s"' % (k, prop)))
        out.append((sels, got[0], got[1]))
    return out


def _tm_theme(path, where):
    """The token rules of a .tmTheme (a plist: settings, a list of {scope, settings})."""
    if not os.path.isfile(path):
        raise ThemeError('%s: "tokenColors": %s is no file' % (where, path))
    try:
        with open(path, 'rb') as f:
            pl = plistlib.load(f)
    except Exception as ex:                                             # noqa: BLE001 - any fault of the plist
        raise ThemeError('%s: the .tmTheme cannot be read: %s' % (path, ex))
    entries = pl.get('settings') if isinstance(pl, dict) else None
    if not isinstance(entries, list):
        raise ThemeError('%s: not a .tmTheme: no list "settings"' % path)
    out = []
    for k, e in enumerate(entries):
        if not isinstance(e, dict) or not isinstance(e.get('settings', {}), dict):
            raise ThemeError('%s: settings [%d] is not a rule' % (path, k))
        scope = e.get('scope')
        sels = [s.strip() for s in scope.split(',')] if isinstance(scope, str) else None
        got = [None if e.get('settings', {}).get(p) is None else
               _colour(e['settings'][p], path, 'settings [%d] %s' % (k, p)) for p in ('foreground', 'background')]
        out.append((sels, got[0], got[1]))
    return out


def token_colour(rules, scope):
    """The foreground the rules give a word of scope, as VS Code matches: a selector matches a scope it is equal to
    or a dot-prefix of, the one of most parts wins, a later rule over an earlier one of as many. A selector of
    several scopes (a parent and its child) or an exclusion is not matched: a word of the report has one scope.
    None when no rule gives one."""
    best, parts = None, 0
    for sels, fg, _ in rules:
        if fg is None or not sels:
            continue
        for s in sels:
            if not s or ' ' in s or s.startswith('-'):
                continue
            if (scope == s or scope.startswith(s + '.')) and s.count('.') + 1 >= parts:
                best, parts = fg, s.count('.') + 1
    return best


def kind_of(src):
    """light, dark, hcDark or hcLight: a type in the file or a file it includes, else the uiTheme a package.json gives
    one of those files, else by the page."""
    if src.kind:
        return src.kind
    for path in src.files:
        folder = os.path.dirname(path)
        for _ in range(3):
            pkg = os.path.join(folder, 'package.json')
            if os.path.isfile(pkg):
                k = _ui_theme(pkg, path)
                if k:
                    return k
                break
            folder = os.path.dirname(folder)
    page = _page_text(src)[0]
    return 'dark' if page and luminance(page) < 0.1791 else 'light'


def _ui_theme(pkg, path):
    """The kind package.json's contributes.themes gives the theme at path, else None. A package.json that does not
    read is none: it is not the theme."""
    try:
        with open(pkg, encoding='utf-8-sig') as f:
            j = parse(f.read(), pkg)
        themes = j['contributes']['themes']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for t in themes if isinstance(themes, list) else []:
        if isinstance(t, dict) and isinstance(t.get('path'), str) and os.path.normcase(
                os.path.normpath(os.path.join(os.path.dirname(pkg), t['path']))) == os.path.normcase(path):
            return KINDS.get(t.get('uiTheme'))
    return None


def _page_text(src):
    """(page, text) the theme gives: editor.background and editor.foreground, else a scope-less token rule's."""
    page, text = src.colors.get('editor.background'), src.colors.get('editor.foreground')
    for sels, fg, bg in src.rules:
        if sels is None:
            page, text = page or bg, text or fg
    return page, text


# --- colours: WCAG's luminance and contrast, OKLab for moving a colour

def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(c):
    return 0.2126 * _lin(c[0]) + 0.7152 * _lin(c[1]) + 0.0722 * _lin(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def oklab(c):
    r, g, b = (_lin(x) for x in c[:3])
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _srgb_linear(lab):
    L, a, b = lab
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, \
        L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _gamma(x):
    x = min(1.0, max(0.0, x))
    return 255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)


def from_oklab(L, a, b, alpha=1.0):
    """The colour at lightness L with as much of the chroma (a, b) as sRGB holds, its hue kept."""
    L = min(1.0, max(0.0, L))
    lo, hi = 0.0, 1.0
    if not all(-1e-6 <= v <= 1 + 1e-6 for v in _srgb_linear((L, a, b))):
        for _ in range(30):
            mid = (lo + hi) / 2
            if all(-1e-6 <= v <= 1 + 1e-6 for v in _srgb_linear((L, a * mid, b * mid))):
                lo = mid
            else:
                hi = mid
        a, b = a * lo, b * lo
    return tuple(int(math.floor(_gamma(v) + 0.5)) for v in _srgb_linear((L, a, b))) + (alpha,)


def on_axis(tia, page, text):
    """TIA's colour tia moved onto the theme's axis from page to text: TIA's page is white (lightness 1), its text
    black (0); a colour at lightness L stands 1 - L of the way from page to text, and goes as far from the theme's
    page towards its text, with TIA's own hue and chroma added. Its alpha is kept."""
    c, p, t = oklab(tia), oklab(page), oklab(text)
    k = 1 - c[0]
    return from_oklab(p[0] + k * (t[0] - p[0]), p[1] + k * (t[1] - p[1]) + c[1], p[2] + k * (t[2] - p[2]) + c[2],
                      tia[3])


def over(c, ground):
    """c laid over the opaque ground, as the browser draws a colour with an alpha."""
    a = c[3]
    return tuple(int(math.floor(a * c[k] + (1 - a) * ground[k] + 0.5)) for k in range(3)) + (1.0,)


def lighter(c, d):
    """c with its OKLab lightness moved by d, its hue kept."""
    L, a, b = oklab(c)
    return from_oklab(L + d, a, b)


# --- the palette of a theme

def bound(pair):
    return min(4.5, contrast(theme.NATIVE[pair[0]], theme.NATIVE[pair[1]]))


def palette(src, rules=RULES, move=True):
    """({name: colour} for every name of the palette, {name: 'tia.<name>', an id, a scope or a rule}) of the theme
    src. rules, move: the rules taken (the tests take one out to see the pairs fail)."""
    for key in src.colors:
        if key.startswith('tia.') and '--' + key[4:] not in theme.NATIVE:
            raise ThemeError('%s: "colors": "%s" is no name of the palette (the names: %s)'
                             % (src.where[key], key, NAMES_DOC))
    kind = kind_of(src)
    page0, text0 = (theme.colour(v) for v in KIND_PAGE[kind])
    given_page, given_text = _page_text(src)
    values, origin, fixed = {}, {}, set()
    for name in ['--page', '--text'] + [n for n in theme.NAMES if n not in ('--page', '--text')]:
        sources, rule = TABLE[name]
        own = 'tia.' + name[2:]
        if own in src.colors:
            c = src.colors[own]
            if c[3] == 0 and name in VISIBLE:
                raise ThemeError('%s: "colors": "%s" is fully transparent: it would take %s off the page'
                                 % (src.where[own], own, _what(name)))
            got, fixed = (c, own), fixed | {name}
        else:
            got = next(((c, s) for s in sources
                        for c in [token_colour(src.rules, s) if s.endswith('.scl') else src.colors.get(s)]
                        if c is not None and c[3] > 0), None)
            if got is None and name == '--page' and given_page and given_page[3] > 0:
                got = (given_page, 'tokenColors')
            if got is None and name == '--text' and given_text and given_text[3] > 0:
                got = (given_text, 'tokenColors')
            if got is None:
                got = (_rule(rule if rule in rules else 'tia', name, kind, values, src, page0, text0), rule)
        c, origin[name] = got
        if name not in ALPHA and c[3] < 1:
            c = over(c, page0 if name == '--page' else values[GROUND.get(name, '--page')])
        values[name] = c
    if move:
        _hold_pairs(values, origin, fixed | {'--page'})
    return values, origin


def _what(name):
    return ('a text' if VISIBLE.index(name) < VISIBLE.index('--link-underline') else
            'a line' if VISIBLE.index(name) < VISIBLE.index('--added') else 'a change mark')


def _rule(rule, name, kind, values, src, page0, text0):
    tia = theme.NATIVE[name]
    if rule == 'kind':
        return page0 if name == '--page' else text0
    if rule == 'text':
        return values['--text']
    if rule == 'line' and kind in HIGH_CONTRAST:
        c = src.colors.get('contrastBorder')
        return c if c is not None and c[3] > 0 else values['--text']
    if rule in ('axis', 'line'):
        return on_axis(tia, values['--page'], values['--text'])
    return tia


TEXTS = VISIBLE[:VISIBLE.index('--link-underline')]
STEP = 0.005                    # OKLab lightness: one step of a move


def _holds(pair, b, values):
    return contrast(values[pair[0]], values[pair[1]]) >= b - 1e-9


def _hold_pairs(values, origin, fixed):
    """Moves names, by lightness alone, until each pair holds its bound. First the parts that are no text (a mark's
    fill, a box, a band, a line) away from what they lie on, so that the grounds stand; then every pair, by the move
    that is smallest, a rule's value weighed before a value the theme gave, and breaks none of the name's pairs that
    held; where no move breaks none, the drawn side moves. fixed: never moved."""
    pairs = [(p, bound(p)) for p in theme.PAIRS]
    parts = [(p, b) for p, b in pairs if p[0] not in TEXTS]
    for group, sides in ((parts, 1), (pairs, 2)):
        of = {}                 # a name's pairs a move of it keeps: first where it is drawn, then all
        for p, b in group:
            for n in p[:sides]:
                of.setdefault(n, []).append((p, b))
        for _ in range(20):
            moved = False
            for p, b in group:
                if _holds(p, b, values):
                    continue
                best = None
                for n in p[:sides]:
                    if n in fixed:
                        continue
                    kept = [(q, bq) for q, bq in of[n] if _holds(q, bq, values)]
                    found = _move(n, p, b, values, kept)
                    if found:
                        key = (found[0], found[1] * (1 if origin[n] in RULES else 3))
                        if best is None or key < best[0]:
                            best = (key, n, found[2])
                if best:
                    values[best[1]] = best[2]
                    moved = True
            if not moved:
                break


def _move(n, pair, b, values, kept):
    """(how many of kept it breaks, how far, the colour) of the move of n's lightness that makes pair hold b and breaks
    the fewest of kept, the smallest of those; None when no move makes pair hold."""
    def holds(q, bq, c):
        return contrast(c if q[0] == n else values[q[0]], c if q[1] == n else values[q[1]]) >= bq - 1e-9
    best, (L, a, bb) = None, oklab(values[n])
    for step in range(1, int(1 / STEP) + 1):
        for sign in (1, -1):
            if not 0 <= L + sign * (step - 1) * STEP <= 1:
                continue                                              # this way is at black or white already
            c = from_oklab(L + sign * step * STEP, a, bb)
            if not holds(pair, b, c):
                continue
            broken = sum(not holds(q, bq, c) for q, bq in kept)
            if best is None or broken < best[0]:
                best = (broken, step * STEP, c)
            if broken == 0:
                return best
    return best


def main(argv=None):
    """python -m TiaChangeReports.vscode_theme <tia|file>: the theme's block alone on stdout (theme.block)."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] in ('-h', '--help'):
        print('usage: python -m TiaChangeReports.vscode_theme <tia|theme file>\n'
              "writes the theme's block alone, @media screen{.ldiff{...}}: laid after a fragment drawn in --theme tia, "
              'it draws the fragment in the theme', file=sys.stderr if len(argv) != 1 else sys.stdout)
        return 0 if argv in (['-h'], ['--help']) else 2
    try:
        t = theme.load(argv[0])
    except ThemeError as ex:
        print(ex, file=sys.stderr)
        return 2
    sys.stdout.write(theme.block(t))
    return 0


if __name__ == '__main__':
    sys.exit(main())
