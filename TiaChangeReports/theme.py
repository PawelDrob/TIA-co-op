"""The report's colours: one palette of names, each a CSS custom property on .ldiff, and the theme a page is drawn in.

The palette, TIA's native theme and the pairs a theme must keep readable are one file:
TiaHmiGenerator\\hmipreview\\static\\tia-theme.css (rail.THEME_CSS), a line for each name. A theme of the user's own is
a VS Code color theme, read onto the names by vscode_theme.py. A faulty one raises ThemeError naming its file and line,
and one that is not there or cannot be read raises it saying why, so a theme is never drawn in part.

  load(spec)            -> Theme: 'tia' TIA's native theme, a path the VS Code color theme there, None the user's
                           default theme (user_theme()) when that file is there, else TIA's
  user_theme()          -> %LOCALAPPDATA%\\tia-co-op\\theme.json: a theme file in the user's profile, read by every
                           report and viewer page given no --theme, so that those the user does not start by hand
                           (the bridge's change_report, the dashboard's report run, Archive Compare, a double-click
                           in the Explorer) draw in it too. The environment variable ENV, when set, is its path
                           instead: the test packages set it, so that no report a test starts, as a child process
                           too, reads the user's file
  colour(value)         -> (red, green, blue, alpha) of a value in one of VS Code's forms, #RGB, #RGBA, #RRGGBB and
                           #RRGGBBAA, else None
  written(c)            -> rgba(r,g,b,alpha): the one form the page holds a colour in, written from those numbers, so
                           that no character of a theme file reaches the page (test_theme.TheWrittenForm)
  css(theme, page)      -> the palette's block for a page's <style>: TIA's values, then the theme's for the screen,
                           then an HMI screen's own colours, TIA's (SCREEN)
  block(theme)          -> the theme's values alone, @media screen{.ldiff{...}}, for a host to lay over fragments
                           drawn in TIA's
  note(theme, tag)      -> the line a page not drawn in TIA's colours says so in; '' for TIA's
  NATIVE, NAMES, PAIRS  -> {name: TIA's colour (red, green, blue, alpha)}, the names in the file's order, the pairs to
                           keep readable [(drawn, ground)] from the file's head

What the renderer writes holds names and no colour, so the theme is only this block. It is written :where(.ldiff),
specificity 0: a host page's own .ldiff { --name: ... } (a VS Code webview's) wins wherever its stylesheet stands.
A theme of the user's own is for the screen (@media screen): print takes TIA's values, paper being white. page=True
(a page of its own, not a fragment): the block is on :root, so that the page's own head and body take it too.
"""
import os
import re
import sys
from decimal import Decimal
from html import escape

WINCC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'TiaHmiGenerator')
if WINCC not in sys.path:
    sys.path.insert(0, WINCC)
from hmipreview import rail   # noqa: E402  the palette's file, shared with the HMI preview

NATIVE_FILE = os.path.join(rail.STATIC, 'tia-theme.css')
HELP = ("the colours: tia, TIA's native look, or a VS Code color theme file (.json); "     # argparse: %% is %
        "default: your theme file %%LOCALAPPDATA%%\\tia-co-op\\theme.json when there, else tia")


ENV = 'TIA_CR_USER_THEME'


def user_theme(env=os.environ):
    """Where the user's default theme is kept: ENV's path when set, else tia-co-op\\theme.json in their local
    application data."""
    return env.get(ENV) or os.path.join(env.get('LOCALAPPDATA') or os.path.expanduser('~'), 'tia-co-op', 'theme.json')


_HEX = re.compile(r'#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})', re.I | re.A)
# The palette's own file writes rgba() too, for the shadows: their alpha as TIA's, not rounded to 8 bits.
_PALETTE_RGBA = re.compile(r'rgba\(([0-9]+),([0-9]+),([0-9]+),(0?\.[0-9]+)\)', re.A)


class ThemeError(ValueError):
    """A theme file that is no theme: str() is '<file>:<line>: <what>'; one that is not there or does not read:
    '<file>: <what>'."""


class Theme:
    """name: 'tia' or the file's path; values: {name: (red, green, blue, alpha)} for every name, TIA's native theme
    none of its own; label: what the page calls it (the theme's name, else its file's), None for TIA's; kind: light,
    dark, hcDark or hcLight."""

    def __init__(self, name, values, label=None, kind='light'):
        self.name, self.values, self.label, self.kind = name, values, label, kind

    def __repr__(self):
        return 'Theme(%r, %d values)' % (self.name, len(self.values))


def colour(value):
    """(red, green, blue, alpha) of value in one of VS Code's hex forms, alpha 0 to 1; None for any other value."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    h = value[1:] if len(value) > 5 else ''.join(c * 2 for c in value[1:])
    n = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    return (n[0], n[1], n[2], n[3] / 255 if len(n) == 4 else 1.0)


def written(c):
    """The colour c, (red, green, blue, alpha), as the page holds it: rgba() of whole numbers and the alpha in full,
    with no exponent, so that TIA's .25 is 0.25 and not rounded to 8 bits as a hex pair would be."""
    alpha = format(Decimal(repr(float(c[3]))), 'f')
    return 'rgba(%d,%d,%d,%s)' % (c[0], c[1], c[2], alpha[:-2] if alpha.endswith('.0') else alpha)


def palette_colour(value):
    """A value of the palette's own file: a hex form or rgba(r,g,b,.a)."""
    m = _PALETTE_RGBA.fullmatch(value)
    return (int(m[1]), int(m[2]), int(m[3]), float(m[4])) if m else colour(value)


def read_palette(text):
    """{name: colour} of tia-theme.css, in its order; ValueError for a value of no form it takes."""
    body = re.sub(r'/\*.*?\*/', '', text[text.index('.ldiff {'):], flags=re.S)
    out = {}
    for name, value in re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', body):
        c = palette_colour(value.strip())
        if c is None or name in out:
            raise ValueError('%s: %s: %r is no colour or given twice' % (NATIVE_FILE, name, value))
        out[name] = c
    return out


def read_pairs(text, names):
    """[(drawn, ground)] of the head's lines '- --a, --b over --c, --d (where)'; --x-* is every name that starts
    --x-."""
    head = text[:text.index('*/')].replace('\r', '')
    out = []

    def each(names_text):
        got = []
        for n in names_text.split(', '):
            got += [m for m in names if m.startswith(n[:-1])] if n.endswith('*') else [n]
        return got
    for drawn, ground in re.findall(r'^ *- (--.*?) over (--.*?)(?: \(.*\))?$', head, re.M):
        out += [(a, b) for a in each(drawn) for b in each(ground)]
    unknown = {n for p in out for n in p} - set(names)
    if unknown:
        raise ValueError('%s: the pairs name what is no name: %s' % (NATIVE_FILE, sorted(unknown)))
    return out


NATIVE = read_palette(rail.THEME_CSS)
NAMES = list(NATIVE)
PAIRS = read_pairs(rail.THEME_CSS, NAMES)


def load(spec=None):
    """The theme spec names: 'tia', else a VS Code color theme file; None: user_theme() when it is a file, else TIA's.
    Raises ThemeError for a file that is not there, does not read (a folder, not UTF-8, a lock: why in it) or is no
    theme."""
    from . import vscode_theme
    if spec is None:
        spec = user_theme()
        if not os.path.isfile(spec):
            return Theme('tia', {})
    if spec == 'tia':
        return Theme(spec, {})
    if not os.path.exists(spec):
        raise ThemeError('%s: no theme of that name (tia) and no theme file there' % (spec or "''"))
    if os.path.isdir(spec):
        raise ThemeError('%s: the theme file cannot be read: it is a folder' % spec)
    src = vscode_theme.read(spec)
    values, _ = vscode_theme.palette(src)
    return Theme(os.path.abspath(spec), values, src.name or os.path.basename(spec), vscode_theme.kind_of(src))


def _block(sel, values):
    return '%s{%s}' % (sel, ';'.join('%s:%s' % (name, written(c)) for name, c in values.items()))


# An HMI screen takes no theme (tia-theme.css's head). What it would take from the page is held in TIA's values here,
# whatever the theme and whatever a host sets: the fill and colour of its text (render.js's labels have no fill of their
# own) and the background a screen with no BackColor shows. The line round it (--screen-edge), its change outlines
# (.dl) and the frame of the object picked (.obj.sel>.body) take the theme.
SCREEN = '.ldiff svg.hs'
SCREEN_COLOURS = (('color', '--text'), ('fill', '--text'), ('background-color', '--page'))


def css(theme=None, page=False):
    """The palette's block for a <style>: TIA's values, then the values of theme (a Theme; None: TIA's) for
    @media screen, then an HMI screen's own colours (SCREEN), TIA's."""
    sel = ':where(:root)' if page else ':where(.ldiff)'
    out = _block(sel, NATIVE) + '\n'
    if theme is not None and theme.values:
        out += '@media screen{%s}\n' % _block(sel, theme.values)
    return out + _block(SCREEN, {p: NATIVE[n] for p, n in SCREEN_COLOURS}) + '\n'


def block(theme):
    """The values of theme alone, every name, for the screen and on .ldiff (specificity 0,1,0): laid after a fragment
    drawn in TIA's theme, wherever, it draws the fragment as one drawn in theme. TIA's own values for TIA's theme."""
    return '@media screen{%s}\n' % _block('.ldiff', theme.values or NATIVE)


# The line of a page not drawn in TIA's colours: under the title, in the viewer's bar. Not in print, which takes
# TIA's colours, and not in a fragment, whose host chooses its colours.
NOTE_CSS = '.theme-note{color:var(--muted)}@media print{.theme-note{display:none}}'


def note(theme, tag='p'):
    if theme is None or not theme.values:
        return ''
    return '<%s class="theme-note">Colours of the VS Code theme %s, not TIA\'s</%s>' % (tag, escape(theme.label), tag)


# Every name a pair names is drawn opaque: its contrast is that of its value.
if any(NATIVE[n][3] < 1 for p in PAIRS for n in p):
    raise ValueError('%s: a pair names a colour with an alpha' % NATIVE_FILE)
