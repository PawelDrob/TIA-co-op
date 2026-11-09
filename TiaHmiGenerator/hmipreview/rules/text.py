"""Text fit. Generated documents only.

  text.fit   warning: a text field or button text (TextOff / TextOn) that does not fit its box in one of the
             project languages: a line wider than the box, or more lines than its height holds.

Measured with Tahoma (the font family of the exports) at the FontSize and FontStyle of the object's FontItem for
that culture (else the first FontItem); FontSize is taken as pixels, a style containing "Bold" uses tahomabd.ttf.
The box is Width x Height minus twice BorderWidth and minus the margins (text field: LeftMargin, RightMargin,
TopMargin, BottomMargin; button: TextAreaLeftMargin, ...). Nothing is assumed for an attribute the document leaves
out (full exports only, 2026-10-06): an object lacking a margin, BorderWidth or the FontSize of a FontItem is not
measured, and document.incomplete reports it. Not measured either: text fields with FitToLargest true (TIA sizes the
box to the text), invisible and graphic buttons. Without Tahoma installed the rule measures nothing.
"""
import re

from .. import fonts
from ..findings import warning
from ..geometry import items
from ..model import attribute

MARGINS = {
    'Hmi.Screen.TextField': ('LeftMargin', 'RightMargin', 'TopMargin', 'BottomMargin'),
    'Hmi.Screen.Button': ('TextAreaLeftMargin', 'TextAreaRightMargin', 'TextAreaTopMargin', 'TextAreaBottomMargin'),
}
TEXTS = {'Hmi.Screen.TextField': ('Text',), 'Hmi.Screen.Button': ('TextOff', 'TextOn')}


def _num(elem, name):
    """The attribute as a number, None when absent or not a number."""
    try:
        return float(attribute(elem, name))
    except (TypeError, ValueError):
        return None


def _field_text(info):
    """Every value of a <fieldinfo> in words, without its number and link ids:
    '{HMICommonTextList, HmiTextList:Modes, HmiTag:modeNow, length 5}'."""
    out = [v for k, v in sorted(info.attrib.items()) if k != 'name']
    for e in info.iter():
        if e is info:
            continue
        out += ['%s %s' % kv for kv in sorted(e.attrib.items()) if kv[0] != 'TargetID']
        text = (e.text or '').strip()
        if text:                        # a link's name: the object's type and name, without the type's namespace
            out.append(re.sub(r'^[\w.]*\.(?=\w+:)', '', text))
    return '{%s}' % ', '.join(out)


def told_lines(text_elem):
    """The lines of a Text attribute for a comparison: each tag or list field in its place as _field_text, by what it
    refers to (its number is not compared), a field's <fieldinfo> that no field names as a line of its own."""
    infos = {i.get('name'): i for i in text_elem.iterfind('fieldinfos/fieldinfo')}
    named = set()

    def field(f):
        ref = f.get('ref')
        named.add(ref)
        return _field_text(infos[ref]) if ref in infos else '{no field %s}' % ref

    lines = _lines(text_elem, field)
    return lines + [_field_text(i) for n, i in infos.items() if n not in named]


def _lines(text_elem, field=None):
    """Lines of a Text attribute: rich text <body><p>a<br />b</p></body>, else plain text. field(element): what a
    <field> reads as; without it, nothing."""
    body = text_elem.find('body')
    if body is None:
        return (text_elem.text or '').split('\n')
    lines = []
    for p in body.iter('p'):
        cur = [p.text or '']
        for c in p.iter():
            if c is p:
                continue
            if c.tag == 'br':
                lines.append(''.join(cur))
                cur = []
            elif c.tag == 'field' and field:
                cur.append(field(c))
            else:
                cur.append(c.text or '')
            cur.append(c.tail or '')
        lines.append(''.join(cur))
    return lines


def _texts(elem, comps):
    """[(culture, lines)] of the given MultilingualText compositions of a screen item."""
    out = []
    for mt in elem.iter('MultilingualText'):
        if mt.get('CompositionName') not in comps:
            continue
        for it in mt.iter('MultilingualTextItem'):
            al = it.find('AttributeList')
            t = al.find('Text') if al is not None else None
            if t is not None:
                out.append((al.findtext('Culture') or '', _lines(t)))
    return out


def _fonts(elem):
    """{culture: (size, bold)} and the first one, from the FontItems of the item's Font composition; None instead
    when there is no FontItem or one lacks a FontSize."""
    by_culture, first = {}, None
    for f in elem.iter():
        if f.get('CompositionName') != 'Font':
            continue
        for fi in f.iter():
            if not fi.tag.endswith('FontItem'):
                continue
            size = _num(fi, 'FontSize')
            if size is None:
                return None
            spec = (size, 'bold' in (attribute(fi, 'FontStyle') or '').lower())
            by_culture[attribute(fi, 'Culture') or ''] = spec
            first = first or spec
        break
    return (by_culture, first) if first is not None else None


def _measured(it):
    if it.type not in TEXTS:
        return False
    if it.type == 'Hmi.Screen.TextField':           # absent: incomplete, not measured
        return (attribute(it.elem, 'FitToLargest') or 'true').lower() != 'true'
    return attribute(it.elem, 'Mode') == 'Text'


def check(repo, ctx):
    if fonts.tahoma(False) is None:
        return
    for doc in repo.generated:
        if doc.kind not in ('screen', 'template', 'popup'):
            continue
        for it in items(doc):
            if not _measured(it):
                continue
            problem = _misfit(it)
            if problem:
                yield warning(doc.path, it.name, 'text.fit', problem)


def _misfit(it):
    e = it.elem
    left, right, top, bottom, border = (_num(e, n) for n in MARGINS[it.type] + ('BorderWidth',))
    fonts_ = _fonts(e)
    if None in (left, right, top, bottom, border) or fonts_ is None:
        return None                                   # incomplete: document.incomplete reports it
    avail_w = it.box.w - left - right - 2 * border
    avail_h = it.box.h - top - bottom - 2 * border
    by_culture, first = fonts_
    for culture, lines in _texts(e, TEXTS[it.type]):
        size, bold = by_culture.get(culture, first)
        font = fonts.tahoma(bold) or fonts.tahoma(False)
        style = 'bold ' if bold else ''
        for line in lines:
            w = font.width(line, size)
            if w > avail_w:
                return ("%s text '%s' is %.0f px wide in Tahoma %s%gpx, the box has %.0f px."
                        % (culture, line, w, style, size, avail_w))
        h = len(lines) * font.line_height(size)
        if h > avail_h:
            return ('%s text has %d lines, %.0f px high in Tahoma %s%gpx, the box has %.0f px.'
                    % (culture, len(lines), h, style, size, avail_h))
    return None
