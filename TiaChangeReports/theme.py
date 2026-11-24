"""The report's colours: one palette of names, each a CSS custom property on .ldiff, and the themes that give them values.

The palette and TIA's native theme, its default, are one file: TiaHmiGenerator\\hmipreview\\static\\tia-theme.css (rail.
THEME_CSS), a line for each name. A theme of the user's own is a file in its format (read; the format and what is
refused: that file's head). A faulty one raises ThemeError with its line, so a theme is never drawn in part.

  load(spec)            -> Theme: 'tia' TIA's native theme, a path the theme file there, None the user's default
                           theme (user_theme()) when that file is there, else TIA's
  user_theme()          -> %LOCALAPPDATA%\\tia-co-op\\theme.css: a theme file in the user's profile, read by every
                           report and viewer page given no --theme, so that those the user does not start by hand
                           (the bridge's change_report, the dashboard's report run, Archive Compare, a double-click
                           in the Explorer) draw in it too. The environment variable ENV, when set, is its path
                           instead: the test packages set it, so that no report a test starts, as a child process
                           too, reads the user's file
  is_colour(value)      -> whether a theme takes the value: #rgb, #rgba, #rrggbb, #rrggbbaa, rgb() and rgba() as CSS
                           Color writes them, or transparent. Each such value the browser takes too
                           (test_theme.TheFormsOfColour): one it refused would draw nothing where it stands
  css(theme, page)      -> the palette's block for a page's <style>: TIA's values, then the theme's for the screen
  NATIVE, NAMES         -> {name: TIA's value}, the names in the file's order

What the renderer writes holds names and no colour, so the theme is only this block. It is written :where(.ldiff),
specificity 0: a host page's own .ldiff { --name: ... } (a VS Code webview's) wins wherever its stylesheet stands.
A theme of the user's own is for the screen (@media screen): print takes TIA's values, paper being white. page=True
(a page of its own, not a fragment): the block is on :root, so that the page's own head and body take it too.
"""
import os
import re
import sys

WINCC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'TiaHmiGenerator')
if WINCC not in sys.path:
    sys.path.insert(0, WINCC)
from hmipreview import rail   # noqa: E402  the palette's file, shared with the HMI preview

FORMAT = 1                      # the format this report reads; a name renamed or removed makes the next one
NATIVE_FILE = os.path.join(rail.STATIC, 'tia-theme.css')
HELP = ("the colours: tia, TIA's native look, or a theme file in tia-theme.css's format; "     # argparse: %% is %
        "default: your theme file %%LOCALAPPDATA%%\\tia-co-op\\theme.css when there, else tia")


ENV = 'TIA_CR_USER_THEME'


def user_theme(env=os.environ):
    """Where the user's default theme is kept: ENV's path when set, else tia-co-op\\theme.css in their local
    application data."""
    return env.get(ENV) or os.path.join(env.get('LOCALAPPDATA') or os.path.expanduser('~'), 'tia-co-op', 'theme.css')


# The forms of CSS Color 4 a theme takes. A number as CSS writes it ("1." is none); rgb() and rgba() alike, either with
# commas, three numbers or three percentages and an alpha after a comma, or with spaces, numbers, percentages and none
# mixed and an alpha after /.
_HEX = re.compile(r'#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$', re.I)
_N = r'[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?'
_P = _N + '%'
_A = '(?:%s|%s)' % (_P, _N)
_C = '(?:%s|%s|none)' % (_P, _N)
_RGB = re.compile(r'rgba?\(\s*(?:(?:{N}\s*,\s*{N}\s*,\s*{N}|{P}\s*,\s*{P}\s*,\s*{P})(?:\s*,\s*{A})?'
                  r'|{C}\s+{C}\s+{C}(?:\s*/\s*(?:{A}|none))?)\s*\)$'.format(N=_N, P=_P, A=_A, C=_C), re.I)
FORMS = '#rgb, #rgba, #rrggbb, #rrggbbaa, rgb(), rgba() or transparent'
_DECL = re.compile(r'(--[a-z0-9-]+)\s*:\s*(.*)$', re.S)


class ThemeError(ValueError):
    """A theme file that cannot be read: str() is '<file>:<line>: <what>'."""


class Theme:
    """name: 'tia' or the file's path; values: {name: colour} the theme gives, TIA's native theme none of its own."""

    def __init__(self, name, values):
        self.name, self.values = name, values

    def __repr__(self):
        return 'Theme(%r, %d values)' % (self.name, len(self.values))


def is_colour(value):
    return bool(_HEX.match(value) or _RGB.match(value) or value.lower() == 'transparent')


def _blank_comments(text, where):
    """The text with each /* ... */ as spaces, its line breaks kept, so that lines still count."""
    out, i = [], 0
    while True:
        j = text.find('/*', i)
        if j < 0:
            return ''.join(out) + text[i:]
        k = text.find('*/', j + 2)
        if k < 0:
            raise ThemeError('%s:%d: a comment /* is not closed' % (where, text.count('\n', 0, j) + 1))
        out += [text[i:j], re.sub(r'[^\n]', ' ', text[j:k + 2])]
        i = k + 2


def read(text, where, names=None):
    """{name: value} of a theme's text, in its order, '--theme-format' left out. names: the palette's names (None: any,
    for the palette's own file). where: the file, for the messages."""
    text = _blank_comments(text, where)
    line = lambda pos: text.count('\n', 0, pos) + 1                       # noqa: E731
    m = re.match(r'\s*\.ldiff\s*\{', text)
    if not m:
        start = len(text) - len(text.lstrip())
        raise ThemeError('%s:%d: a theme is one block: .ldiff { --theme-format: %d; --name: colour; ... }'
                         % (where, line(start), FORMAT))
    end = text.find('}', m.end())
    if end < 0:
        raise ThemeError('%s:%d: the block .ldiff { is not closed with }' % (where, line(m.start())))
    rest = text[end + 1:]
    if rest.strip():
        raise ThemeError('%s:%d: nothing may follow the block: a theme is one .ldiff { ... }'
                         % (where, line(end + 1 + len(rest) - len(rest.lstrip()))))
    values, seen, pos = {}, {}, m.end()
    for piece in text[m.end():end].split(';'):
        at = pos + len(piece) - len(piece.lstrip())
        pos += len(piece) + 1
        if not piece.strip():
            continue
        d = _DECL.match(piece.strip())
        if not d:
            raise ThemeError('%s:%d: not a line of a theme: %r; each is --name: colour;' % (where, line(at), piece.strip()))
        name, value = d.group(1), ' '.join(d.group(2).split())
        if not seen:
            if name != '--theme-format':
                raise ThemeError('%s:%d: a theme starts with --theme-format: %d;' % (where, line(at), FORMAT))
            if value != str(FORMAT):
                raise ThemeError('%s:%d: --theme-format %s is not one this report reads: it reads %d'
                                 % (where, line(at), value, FORMAT))
        elif name in seen:
            raise ThemeError('%s:%d: %s is given twice (line %d)' % (where, line(at), name, seen[name]))
        elif names is not None and name not in names:
            raise ThemeError('%s:%d: %s is no name of the palette (the names: %s)'
                             % (where, line(at), name, NATIVE_FILE))
        elif not is_colour(value):
            raise ThemeError('%s:%d: %s: %r is not a form of colour a theme takes; those are %s, no colour names, '
                             'no hsl() or var()' % (where, line(at), name, value, FORMS))
        else:
            values[name] = value
        seen[name] = line(at)
    if not seen:
        raise ThemeError('%s:%d: a theme starts with --theme-format: %d;' % (where, line(m.end()), FORMAT))
    return values


NATIVE = read(rail.THEME_CSS, NATIVE_FILE)
NAMES = list(NATIVE)


def load(spec=None):
    """The theme spec names: 'tia', else a theme file; None: user_theme() when it is a file, else TIA's. Raises
    ThemeError for a file that cannot be read or is no theme, OSError's text in it."""
    if spec is None:
        spec = user_theme()
        if not os.path.isfile(spec):
            return Theme('tia', {})
    if spec == 'tia':
        return Theme(spec, {})
    try:
        with open(spec, encoding='utf-8-sig') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as ex:
        raise ThemeError('%s: no theme of that name (%s) and no theme file there: %s'
                         % (spec, 'tia', getattr(ex, 'strerror', None) or ex))
    return Theme(os.path.abspath(spec), read(text, spec, NAMES))


def _block(sel, values):
    return '%s{%s}' % (sel, ';'.join('%s:%s' % kv for kv in values.items()))


def css(theme=None, page=False):
    """The palette's block for a <style>: TIA's values, then the values of theme (a Theme; None: TIA's) for the
    screen."""
    sel = ':where(:root)' if page else ':where(.ldiff)'
    out = _block(sel, NATIVE) + '\n'
    if theme is not None and theme.values:
        out += '@media screen{%s}\n' % _block(sel, theme.values)
    return out
