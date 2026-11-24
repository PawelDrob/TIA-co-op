"""The report's colours: one palette of names, each a CSS custom property on .ldiff, and the themes that give them values.

The palette and TIA's native theme, the value of each name no theme gives, are one file:
TiaHmiGenerator\\hmipreview\\static\\tia-theme.css (rail.THEME_CSS), a line for each name. A theme of the user's own is
a file in its format (read; the format and what is refused: that file's head). A faulty one raises ThemeError with its
line, so a theme is never drawn in part.

  load(spec)            -> Theme: 'tia' TIA's native theme, a path the theme file there, None the user's default
                           theme (user_theme()) when that file is there, else TIA's
  user_theme()          -> %LOCALAPPDATA%\\tia-co-op\\theme.css: a theme file in the user's profile, read by every
                           report and viewer page given no --theme, so that those the user does not start by hand
                           (the bridge's change_report, the dashboard's report run, Archive Compare, a double-click
                           in the Explorer) draw in it too. The environment variable ENV, when set, is its path
                           instead: the test packages set it, so that no report a test starts, as a child process
                           too, reads the user's file
  colour(value)         -> (red, green, blue, alpha) of a value a theme takes, as the browser reads it, else None. A
                           theme takes #rgb, #rgba, #rrggbb, #rrggbbaa, rgb() and rgba() as CSS Color writes them, or
                           transparent: what the browser takes of those forms (test_theme.TheFormsOfColour)
  written(c)            -> rgba(r,g,b,alpha): the one form the page holds a colour in, written from those numbers, so
                           that no character of a theme file reaches the page; the browser takes each case of it and
                           reads the colour it was read from (TheWrittenForm)
  is_colour(value)      -> whether a theme takes the value
  css(theme, page)      -> the palette's block for a page's <style>: TIA's values, then the theme's for the screen
  NATIVE, NAMES         -> {name: TIA's colour (red, green, blue, alpha)}, the names in the file's order

What the renderer writes holds names and no colour, so the theme is only this block. It is written :where(.ldiff),
specificity 0: a host page's own .ldiff { --name: ... } (a VS Code webview's) wins wherever its stylesheet stands.
A theme of the user's own is for the screen (@media screen): print takes TIA's values, paper being white. page=True
(a page of its own, not a fragment): the block is on :root, so that the page's own head and body take it too.
"""
import math
import os
import re
import sys
from decimal import Decimal

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


# The forms of CSS Color 4 a theme takes, in ASCII alone, as CSS has them: its digits 0 to 9, its white space (no
# vertical tab, no other script's). A number as CSS writes it ("1." is none); rgb() and rgba() alike, either with commas,
# three numbers or three percentages and an alpha after a comma, or with spaces, numbers, percentages and none mixed and
# an alpha after /.
_HEX = re.compile(r'#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})', re.I | re.A)
_N = r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:e[+-]?[0-9]+)?'
_P = _N + '%'
_A = '(?:%s|%s)' % (_P, _N)
_C = '(?:%s|%s|none)' % (_P, _N)
_WS = ' \t\n\r\f'
_S = '[%s]' % _WS
_RGB = re.compile(r'rgba?\({S}*(?:(?:{N}{S}*,{S}*{N}{S}*,{S}*{N}|{P}{S}*,{S}*{P}{S}*,{S}*{P})(?:{S}*,{S}*{A})?'
                  r'|{C}{S}+{C}{S}+{C}(?:{S}*/{S}*(?:{A}|none))?){S}*\)'.format(N=_N, P=_P, A=_A, C=_C, S=_S),
                  re.I | re.A)
FORMS = '#rgb, #rgba, #rrggbb, #rrggbbaa, rgb(), rgba() or transparent'
_DECL = re.compile(r'(--[a-z0-9-]+){S}*:{S}*(.*)'.format(S=_S), re.S)


class ThemeError(ValueError):
    """A theme file that is no theme: str() is '<file>:<line>: <what>'; one that is not there or does not read:
    '<file>: <what>'."""


class Theme:
    """name: 'tia' or the file's path; values: {name: (red, green, blue, alpha)} the theme gives, TIA's native theme
    none of its own."""

    def __init__(self, name, values):
        self.name, self.values = name, values

    def __repr__(self):
        return 'Theme(%r, %d values)' % (self.name, len(self.values))


def _number(text, whole):
    """A part of rgb() as a number: none 0, a percentage of whole."""
    if text == 'none':
        return 0.0
    return float(text[:-1]) * whole / 100 if text.endswith('%') else float(text)


def colour(value):
    """(red, green, blue, alpha) of value as the browser reads it: red, green and blue whole numbers 0 to 255, rounded
    half up, alpha 0 to 1 kept in full, not rounded to 8 bits; None for a value a theme does not take."""
    v = value.strip(_WS).lower()
    if not v.isascii():
        return None
    if v == 'transparent':
        return (0, 0, 0, 0.0)
    if _HEX.fullmatch(v):
        h = v[1:] if len(v) > 5 else ''.join(c * 2 for c in v[1:])
        n = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
        return (n[0], n[1], n[2], n[3] / 255 if len(n) == 4 else 1.0)
    if not _RGB.fullmatch(v):
        return None
    parts = re.split(r'{S}*[,/]{S}*|{S}+'.format(S=_S), v[v.index('(') + 1:v.rindex(')')].strip(_WS))
    rgb = [math.floor(min(255.0, max(0.0, _number(p, 255))) + 0.5) for p in parts[:3]]
    alpha = min(1.0, max(0.0, _number(parts[3], 1))) if len(parts) == 4 else 1.0
    return (rgb[0], rgb[1], rgb[2], alpha)


def written(c):
    """The colour c, (red, green, blue, alpha), as the page holds it: rgba() of whole numbers and the alpha in full,
    with no exponent, so that TIA's .25 is 0.25 and not rounded to 8 bits as a hex pair would be."""
    alpha = format(Decimal(repr(float(c[3]))), 'f')
    return 'rgba(%d,%d,%d,%s)' % (c[0], c[1], c[2], alpha[:-2] if alpha.endswith('.0') else alpha)


def is_colour(value):
    return colour(value) is not None


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
    """{name: (red, green, blue, alpha)} of a theme's text, in its order, '--theme-format' left out. names: the
    palette's names (None: any, for the palette's own file). where: the file, for the messages. White space is CSS's
    alone: a space of another script is a character, as in the browser."""
    text = _blank_comments(text, where)
    line = lambda pos: text.count('\n', 0, pos) + 1                       # noqa: E731
    m = re.match(r'{S}*\.ldiff{S}*\{{'.format(S=_S), text)
    if not m:
        start = len(text) - len(text.lstrip(_WS))
        raise ThemeError('%s:%d: a theme is one block: .ldiff { --theme-format: %d; --name: colour; ... }'
                         % (where, line(start), FORMAT))
    end = text.find('}', m.end())
    if end < 0:
        raise ThemeError('%s:%d: the block .ldiff { is not closed with }' % (where, line(m.start())))
    rest = text[end + 1:]
    if rest.strip(_WS):
        raise ThemeError('%s:%d: nothing may follow the block: a theme is one .ldiff { ... }'
                         % (where, line(end + 1 + len(rest) - len(rest.lstrip(_WS)))))
    values, seen, pos = {}, {}, m.end()
    for piece in text[m.end():end].split(';'):
        at = pos + len(piece) - len(piece.lstrip(_WS))
        pos += len(piece) + 1
        if not piece.strip(_WS):
            continue
        d = _DECL.fullmatch(piece.strip(_WS))
        if not d:
            raise ThemeError('%s:%d: not a line of a theme: %r; each is --name: colour;'
                             % (where, line(at), piece.strip(_WS)))
        name, value = d.group(1), re.sub(_S + '+', ' ', d.group(2))
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
        elif (c := colour(value)) is None:
            raise ThemeError('%s:%d: %s: %r is not a form of colour a theme takes; those are %s, no colour names, '
                             'no hsl() or var()' % (where, line(at), name, value, FORMS))
        else:
            values[name] = c
        seen[name] = line(at)
    if not seen:
        raise ThemeError('%s:%d: a theme starts with --theme-format: %d;' % (where, line(m.end()), FORMAT))
    return values


NATIVE = read(rail.THEME_CSS, NATIVE_FILE)
NAMES = list(NATIVE)


def load(spec=None):
    """The theme spec names: 'tia', else a theme file; None: user_theme() when it is a file, else TIA's. Raises
    ThemeError for a file that is not there, does not read (a folder, not UTF-8, a lock: why in it) or is no theme."""
    if spec is None:
        spec = user_theme()
        if not os.path.isfile(spec):
            return Theme('tia', {})
    if spec == 'tia':
        return Theme(spec, {})
    if not os.path.exists(spec):
        raise ThemeError('%s: no theme of that name (tia) and no theme file there' % spec)
    if os.path.isdir(spec):
        raise ThemeError('%s: the theme file cannot be read: it is a folder' % spec)
    try:
        with open(spec, encoding='utf-8-sig') as f:
            text = f.read()
    except UnicodeDecodeError as ex:
        raise ThemeError('%s: the theme file cannot be read: it is not UTF-8 (%s)' % (spec, ex))
    except OSError as ex:
        raise ThemeError('%s: the theme file cannot be read: %s' % (spec, ex.strerror or ex))
    return Theme(os.path.abspath(spec), read(text, spec, NAMES))


def _block(sel, values):
    return '%s{%s}' % (sel, ';'.join('%s:%s' % (name, written(c)) for name, c in values.items()))


def css(theme=None, page=False):
    """The palette's block for a <style>: TIA's values, then the values of theme (a Theme; None: TIA's) for the
    screen."""
    sel = ':where(:root)' if page else ':where(.ldiff)'
    out = _block(sel, NATIVE) + '\n'
    if theme is not None and theme.values:
        out += '@media screen{%s}\n' % _block(sel, theme.values)
    return out
