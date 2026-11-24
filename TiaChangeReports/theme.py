"""The report's colours: one palette of names, each a CSS custom property on .ldiff, and the themes that give them values.

The palette and TIA's native theme, its default, are one file: TiaHmiGenerator\\hmipreview\\static\\tia-theme.css (rail.
THEME_CSS), a line for each name. A theme of the user's own is a file in its format (read): one block .ldiff { ... },
first --theme-format: 1;, then --name: colour; lines. A name it leaves out keeps TIA's value; anything else is refused
with its line (ThemeError), so a theme is never drawn in part.

  load(spec)            -> Theme: 'tia' TIA's native theme, a path the theme file there, None the user's default
                           theme (USER_THEME) when that file is there, else TIA's
  USER_THEME            -> %LOCALAPPDATA%\\tia-co-op\\theme.css: a theme file in the user's profile, read by every
                           report and viewer page given no --theme, so that those the user does not start by hand
                           (the bridge's change_report, the dashboard's report run, Archive Compare, a double-click
                           in the Explorer) draw in it too
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
BUILT_IN = {'tia': os.path.join(rail.STATIC, 'tia-theme.css')}


def user_theme(env=os.environ):
    """Where the user's default theme is kept: tia-co-op\\theme.css in their local application data."""
    return os.path.join(env.get('LOCALAPPDATA') or os.path.expanduser('~'), 'tia-co-op', 'theme.css')


USER_THEME = user_theme()

_HEX = re.compile(r'#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
_NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:%|deg)?'
_FUNC = re.compile(r'(?:rgba?|hsla?)\(\s*%s(?:\s*[,/]?\s*%s){2,3}\s*\)$' % (_NUM, _NUM), re.I)
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
    return bool(_HEX.match(value) or _FUNC.match(value) or value.lower() == 'transparent')


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
                             % (where, line(at), name, BUILT_IN['tia']))
        elif not is_colour(value):
            raise ThemeError('%s:%d: %s: %r is no colour; a colour is #rgb, #rrggbb (with alpha #rgba, #rrggbbaa), '
                             'rgb(), rgba(), hsl(), hsla() of numbers, or transparent' % (where, line(at), name, value))
        else:
            values[name] = value
        seen[name] = line(at)
    if not seen:
        raise ThemeError('%s:%d: a theme starts with --theme-format: %d;' % (where, line(m.end()), FORMAT))
    return values


NATIVE = read(rail.THEME_CSS, BUILT_IN['tia'])
NAMES = list(NATIVE)


def load(spec=None):
    """The theme spec names: a built-in's name ('tia'), else a theme file; None: USER_THEME when it is a file, else
    TIA's. Raises ThemeError for a file that cannot be read or is no theme, OSError's text in it."""
    if spec is None:
        if not os.path.isfile(USER_THEME):
            return Theme('tia', {})
        spec = USER_THEME
    if spec in BUILT_IN:
        return Theme(spec, {})
    try:
        with open(spec, encoding='utf-8-sig') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as ex:
        raise ThemeError('%s: no theme of that name (%s) and no theme file there: %s'
                         % (spec, ', '.join(BUILT_IN), getattr(ex, 'strerror', None) or ex))
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
