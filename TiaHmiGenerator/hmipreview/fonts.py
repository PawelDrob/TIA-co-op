"""TrueType metrics with the standard library only: advance widths (cmap format 4 / 12 + hmtx) and the line
height (hhea), enough to measure a line of text. No kerning, no shaping.

  tahoma(bold=False) -> Font or None     C:\\Windows\\Fonts\\tahoma.ttf / tahomabd.ttf (cached); None if absent
  Font.width(text, size) -> px           size = WinCC FontSize, taken as the em size in pixels; each glyph
                                         advance rounded to whole pixels (matches Pillow on Tahoma)
  Font.line_height(size) -> px           ascender - descender + line gap
"""
import os
import struct

FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
TAHOMA = {False: 'tahoma.ttf', True: 'tahomabd.ttf'}


class Font:
    def __init__(self, path):
        with open(path, 'rb') as f:
            data = f.read()
        num_tables = struct.unpack_from('>H', data, 4)[0]
        tables = {}
        for i in range(num_tables):
            tag, _sum, off, length = struct.unpack_from('>4sIII', data, 12 + 16 * i)
            tables[tag.decode('latin-1')] = (off, length)
        head = tables['head'][0]
        self.units = struct.unpack_from('>H', data, head + 18)[0]
        hhea = tables['hhea'][0]
        asc, desc, gap = struct.unpack_from('>hhh', data, hhea + 4)
        self.line_units = asc - desc + gap
        n_metrics = struct.unpack_from('>H', data, hhea + 34)[0]
        hmtx = tables['hmtx'][0]
        self.advances = [struct.unpack_from('>H', data, hmtx + 4 * i)[0] for i in range(n_metrics)]
        self.cmap = _cmap(data, tables['cmap'][0])

    def advance(self, ch):
        g = self.cmap.get(ord(ch), 0)
        return self.advances[min(g, len(self.advances) - 1)]

    def width(self, text, size):
        """Each advance rounded to whole pixels, as hinted Windows text (GDI) and Pillow lay it out."""
        return sum(int(self.advance(c) * size / self.units + 0.5) for c in text)

    def line_height(self, size):
        return self.line_units * size / self.units


def _cmap(data, base):
    """Code point -> glyph id from the best Unicode subtable (format 12, else format 4)."""
    n = struct.unpack_from('>H', data, base + 2)[0]
    subs = {}
    for i in range(n):
        plat, enc, off = struct.unpack_from('>HHI', data, base + 4 + 8 * i)
        fmt = struct.unpack_from('>H', data, base + off)[0]
        subs[(plat, enc, fmt)] = base + off
    for key in ((3, 10, 12), (0, 4, 12), (3, 1, 4), (0, 3, 4), (0, 4, 4), (0, 3, 4)):
        if key in subs:
            return (_format12 if key[2] == 12 else _format4)(data, subs[key])
    for (plat, enc, fmt), off in subs.items():
        if fmt == 4:
            return _format4(data, off)
    return {}


def _format4(data, off):
    seg2 = struct.unpack_from('>H', data, off + 6)[0]
    segs = seg2 // 2
    ends = struct.unpack_from('>%dH' % segs, data, off + 14)
    starts = struct.unpack_from('>%dH' % segs, data, off + 16 + seg2)
    deltas = struct.unpack_from('>%dh' % segs, data, off + 16 + 2 * seg2)
    ro_base = off + 16 + 3 * seg2
    ranges = struct.unpack_from('>%dH' % segs, data, ro_base)
    out = {}
    for i in range(segs):
        for c in range(starts[i], ends[i] + 1):
            if c == 0xFFFF:
                continue
            if ranges[i] == 0:
                g = (c + deltas[i]) & 0xFFFF
            else:
                p = ro_base + 2 * i + ranges[i] + 2 * (c - starts[i])
                g = struct.unpack_from('>H', data, p)[0]
                if g:
                    g = (g + deltas[i]) & 0xFFFF
            out[c] = g
    return out


def _format12(data, off):
    n = struct.unpack_from('>I', data, off + 12)[0]
    out = {}
    for i in range(n):
        start, end, glyph = struct.unpack_from('>III', data, off + 16 + 12 * i)
        for c in range(start, end + 1):
            out[c] = glyph + c - start
    return out


_cache = {}


def tahoma(bold=False):
    """Tahoma regular or bold from the Windows font folder, or None when the file is absent."""
    if bold not in _cache:
        path = os.path.join(FONT_DIR, TAHOMA[bold])
        _cache[bold] = Font(path) if os.path.exists(path) else None
    return _cache[bold]
