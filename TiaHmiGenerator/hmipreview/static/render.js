// SVG drawing of SimaticML screens, templates and pop-ups. One <g class="obj"> per screen object, carrying
// data-name (ObjectName), data-type (element type without "Hmi.Screen."), data-source (template | screen | popup)
// and data-x/-y/-w/-h (absolute box). The shape with the object's geometry has class "body"; text lines class "line";
// borders class "border" (drawn inside the box, as TIA does).
// Types without a drawing are a labelled "not drawn" box, never skipped.
//
// Full exports only (decided 2026-10-06): an object is drawn from the attributes it carries and nothing else. An
// attribute the drawing needs and the document leaves out is not replaced by a TIA default: that part is not drawn
// (no fill, no border, text in the marker colour), and the object gets class "incomplete", data-missing (the names,
// space-separated) and a dashed magenta outline (class "incomplete-mark"). The validator reports the same objects
// (document.incomplete). What is drawn and what is not: docs/agent/wincc-screen-objects.md.
'use strict';
import * as X from './simaticml.js';

export const SVG = 'http://www.w3.org/2000/svg';
const MARK = 'rgb(255, 0, 255)';               // incomplete marker, text without ForeColor

export function svgEl(tag, attrs, parent) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

let clipSeq = 0;
let defSeq = 0;

function frame(g, b, fill, stroke, width, extra) {
  return svgEl('rect', Object.assign({class: 'body', x: b.x, y: b.y, width: b.w, height: b.h,
    fill: fill || 'none', stroke: stroke || 'none', 'stroke-width': stroke ? (width || 1) : undefined}, extra || {}), g);
}

function label(g, b, text, cls) {
  const t = svgEl('text', {class: 'line ' + (cls || 'tag-label'), x: b.x + 3, y: b.y + 12,
    'font-family': 'Tahoma, sans-serif', 'font-size': 10}, g);
  t.textContent = text;
  return t;
}

// Attribute access that records what a drawing needed and the document did not carry.
function reader(el) {
  const a = X.attrs(el), missing = [];
  const str = k => { if (a[k] === undefined) missing.push(k); return a[k]; };
  return {
    a, missing, str,
    num: k => { const v = str(k); const n = Number(v); return v === undefined || v === '' || !Number.isFinite(n) ? undefined : n; },
    color: k => { const v = str(k); return v === undefined ? null : X.color(v, null); },
  };
}

// BackFillStyle Transparent: no fill; otherwise BackColor. Without BackFillStyle or BackColor: no fill.
function fillOf(r) {
  const style = r.str('BackFillStyle');
  if (style === undefined || style === 'Transparent') return 'none';
  return r.color('BackColor') || 'none';
}

// Button gradient (BackFillStyle Gradient...: the editor draws BackColor for Solid, whatever UseFirstGradient says): a
// vertical gradient FirstGradientColor (top), MiddleGradientColor, SecondGradientColor (bottom). The offsets are not
// drawn (meaning not documented).
function gradientFill(g, r) {
  const id = 'grad' + (++defSeq);
  const lg = svgEl('linearGradient', {id, x1: 0, y1: 0, x2: 0, y2: 1}, svgEl('defs', {}, g));
  [['FirstGradientColor', 0], ['MiddleGradientColor', 0.5], ['SecondGradientColor', 1]].forEach(([k, o]) => {
    const c = r.color(k);
    if (c) svgEl('stop', {offset: o, 'stop-color': c}, lg);
  });
  return `url(#${id})`;
}

function inset(b, d) {
  return {x: b.x + d, y: b.y + d, w: Math.max(0, b.w - 2 * d), h: Math.max(0, b.h - 2 * d)};
}

// Border inside the box: BorderWidth in BorderColor; EdgeStyle Double from 2 px on: the outer half in BorderColor,
// the inner half in BorderBackColor. Style3D is drawn as Solid. BorderWidth 0: no border.
function border(g, b, r, radius) {
  const w = r.num('BorderWidth');
  if (!w) return;
  const edge = r.str('EdgeStyle');
  const parts = edge === 'Double' && w >= 2
    ? [[Math.ceil(w / 2), 'BorderColor'], [w - Math.ceil(w / 2), 'BorderBackColor']] : [[w, 'BorderColor']];
  let off = 0;
  for (const [pw, key] of parts) {
    const c = r.color(key);
    const bb = inset(b, off + pw / 2);
    const rx = radius ? Math.max(0, radius - off - pw / 2) : undefined;
    if (c) svgEl('rect', {class: 'border', x: bb.x, y: bb.y, width: bb.w, height: bb.h, fill: 'none', stroke: c,
      'stroke-width': pw, rx: rx || undefined, ry: rx || undefined}, g);
    off += pw;
  }
}

// Flashing other than None: a dotted amber outline (the preview does not animate).
function flashing(g, b, r) {
  const f = r.str('Flashing');
  if (f !== undefined && f !== 'None') {
    svgEl('rect', {class: 'flash-mark', x: b.x - 2, y: b.y - 2, width: b.w + 4, height: b.h + 4, fill: 'none',
      stroke: 'rgb(255, 170, 0)', 'stroke-width': 1.5, 'stroke-dasharray': '2 2'}, g);
  }
}

// Lines of text in a box: font, colour, alignment and margins from the object; baseline = line top + font size
// (Tahoma ascent ~1 em). prefix: '' (LeftMargin, ...) or 'TextArea' (button).
function textBlock(g, b, lines, r, font, prefix) {
  if (!lines || !lines.length || (lines.length === 1 && lines[0] === '')) return;
  if (!font) { r.missing.push('Font'); return; }
  const color = r.color('ForeColor') || MARK;
  const ha = r.str('HorizontalAlignment'), va = r.str('VerticalAlignment');
  const m = k => r.num(prefix + k + 'Margin') || 0;
  const ml = m('Left'), mr = m('Right'), mt = m('Top'), mb = m('Bottom');
  const id = 'clip' + (++clipSeq);
  const cp = svgEl('clipPath', {id}, g);
  svgEl('rect', {x: b.x, y: b.y, width: b.w, height: b.h}, cp);
  const lh = Math.round(font.size * 1.21);
  const th = lh * lines.length;
  let top = b.y + mt;
  if (va === 'Middle') top = b.y + mt + (b.h - mt - mb - th) / 2;
  else if (va === 'Bottom') top = b.y + b.h - mb - th;
  let x = b.x + ml, anchor = 'start';
  if (ha === 'Center') { x = b.x + ml + (b.w - ml - mr) / 2; anchor = 'middle'; }
  else if (ha === 'Right') { x = b.x + b.w - mr; anchor = 'end'; }
  lines.forEach((l, i) => {
    const t = svgEl('text', {class: 'line', x, y: top + i * lh + font.size, 'text-anchor': anchor,
      'font-family': font.family + ', Tahoma, sans-serif', 'font-size': font.size,
      'font-weight': font.bold ? 'bold' : 'normal', fill: color, 'clip-path': `url(#${id})`,
      'xml:space': 'preserve'}, g);
    t.textContent = l;
  });
}

// The text of an I/O field from its format pattern, and how sure it is.
// Seen in an editor shot (S8 to S10, S2b): a zero per position, a leading s as the sign +: ???? -> 0000, 9999 -> 0000,
// FFFF -> 0000, s999 -> +000.
// Inferred, no shot: the same rule with a decimal point or separator: 99.9 -> 00.0, s9,999 -> +0,000.
// Anything else (1111, 123, FAULT) is written as it is, and could read as a value.
// The last two get a visible mark on the object (patternMark). Patterns with a decimal point occur in a project repo;
// patterns written as they are occur in none of the repos checked (2026-11-03).
const IO_SEEN = /^(\?+|F+|s?9+)$/, IO_INFERRED = /^s?[9.,]+$/;

export function ioText(pattern) {
  if (!IO_SEEN.test(pattern) && !IO_INFERRED.test(pattern)) return pattern;
  return pattern.replace(/^s/, '+').replace(/[?9F]/g, '0');
}

// A pattern with no editor shot behind it: a dashed violet outline with the reason as its tooltip; data-pattern on the
// object says inferred or unknown.
function patternMark(g, b, pattern) {
  if (IO_SEEN.test(pattern)) return;
  const inferred = IO_INFERRED.test(pattern);
  g.setAttribute('data-pattern', inferred ? 'inferred' : 'unknown');
  const m = svgEl('rect', {class: 'pattern-mark', x: b.x - 3, y: b.y - 3, width: b.w + 6, height: b.h + 6, fill: 'none',
    stroke: 'rgb(130, 60, 200)', 'stroke-width': 1.5, 'stroke-dasharray': '5 3'}, g);
  svgEl('title', {}, m).textContent = 'Format pattern ' + pattern + ': ' + (inferred
    ? 'no editor shot, the text is inferred' : 'no editor shot, written as it is: not a value');
}

// The sample date and time the editor shows in clocks and date/time fields.
const SAMPLE_DATE = '12/31/2000', SAMPLE_TIME = '10:59:39 AM', SAMPLE_TIME_SHORT = '10:59 AM';

// Box with fill, corner radius, border and flashing marker: rectangle, text field, I/O fields.
function boxed(g, b, r, fill, radius) {
  frame(g, b, fill, null, 0, {rx: radius || undefined, ry: radius || undefined});
  border(g, b, r, radius);
  flashing(g, b, r);
}

// Line ends: StartStyle / EndStyle other than NoEnd draw an arrowhead (FilledArrow seen; other arrow styles are
// drawn alike). LineEndShapeStyle: Round, Flat, Square -> SVG round, butt, square.
function lineAttrs(g, r) {
  const color = r.color('Color') || 'none';
  const cap = {Round: 'round', Flat: 'butt', Square: 'square'}[r.str('LineEndShapeStyle')];
  const out = {stroke: color, 'stroke-width': r.num('LineWidth'), 'stroke-linecap': cap};
  for (const [k, attr] of [['StartStyle', 'marker-start'], ['EndStyle', 'marker-end']]) {
    const s = r.str(k);
    if (s === undefined || s === 'NoEnd') continue;
    const id = 'arrow' + (++defSeq);
    const mk = svgEl('marker', {id, viewBox: '0 0 10 10', refX: 5, refY: 5, markerWidth: 4, markerHeight: 4,
      orient: 'auto-start-reverse'}, svgEl('defs', {}, g));
    svgEl('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: color}, mk);
    out[attr] = `url(#${id})`;
  }
  return out;
}

// The picture of a graphic view or graphic button: ctx.picture(name) gives its URL (the change report embeds the
// project graphics; without it, or without the image, the caller labels the box with the name). AutoSizing
// StretchPicture fills the box (the only value in the exports so far); another value is not drawn, as it is not known
// how TIA places it. TransparentColor is not applied. pictureUrl: the URL, or null when it is not drawn.
function pictureUrl(name, sizing, ctx) {
  const url = name && ctx.picture ? ctx.picture(name) : null;
  return url && sizing === 'StretchPicture' ? url : null;
}

function picture(g, b, url) {
  svgEl('image', {class: 'picture', href: url, x: b.x, y: b.y, width: b.w, height: b.h, preserveAspectRatio: 'none'}, g);
}

// The inside of a bar with its scale on the left, going up, as the editor draws it (S10, one sample: Bar 64 x 498,
// range 0 to 100, font size 11). Limit ranges: their values are not in the export; the editor drew them at 5, 20, 80 and
// 95 % of the range, a range filling the box's width out to its edge, with BackColor where a range is not enabled.
// Ten major ticks with labels, CountSubDivisions minor ticks between two; the process value is a marker at the middle.
function barScale(g, b, r, font) {
  const min = r.num('MinimumValue'), max = r.num('MaximumValue'), subs = r.num('CountSubDivisions');
  if (min === undefined || max === undefined || !(max > min)) return;
  const top = b.y + 8, bottom = b.y + b.h - 9;
  const at = v => bottom - (v - min) / (max - min) * (bottom - top);
  const inner = inset(b, 1);
  const zone = (from, to, key) => {
    const c = r.a[key + 'Enabled'] === 'true' ? r.color(key + 'Color') : null;
    if (!c) return;
    svgEl('rect', {class: 'bar-range', x: inner.x, y: from, width: inner.w, height: Math.max(0, to - from), fill: c}, g);
  };
  const span = max - min, lim = f => at(min + f * span);
  const number = v => String(Number(v.toPrecision(10)));     // no 0.19999999999999996 from the floating point sums
  if (r.a.ShowLimitRanges === 'true') {
    zone(inner.y, lim(0.95), 'RangeUpper2');
    zone(lim(0.95), lim(0.8), 'RangeUpper1');
    zone(lim(0.8), lim(0.2), 'RangeNormal');
    zone(lim(0.2), lim(0.05), 'RangeLower1');
    zone(lim(0.05), inner.y + inner.h, 'RangeLower2');
  }
  const color = r.color('ScaleColor') || MARK, right = b.x + b.w - 13;
  const tick = (y, len, cls) => svgEl('line', {class: cls, x1: right - len, y1: y, x2: right, y2: y, stroke: color,
    'stroke-width': 1, 'shape-rendering': 'crispEdges'}, g);
  const fontAttrs = font ? {'font-family': font.family + ', Tahoma, sans-serif', 'font-size': font.size,
    'font-weight': font.bold ? 'bold' : 'normal'} : null;
  if (!font) r.missing.push('Font');
  for (let i = 0; i <= 10; i++) {
    const y = at(min + i * span / 10);
    tick(y, 23, 'bar-major');
    if (fontAttrs && r.a.ShowTickLabels === 'true') {
      const t = svgEl('text', Object.assign({class: 'line', x: b.x + 23, y: y + 4, 'text-anchor': 'end', fill: color},
        fontAttrs), g);
      t.textContent = number(min + i * span / 10);
    }
    if (i < 10) {
      for (let k = 1; k <= (subs || 0); k++) tick(y - k * (at(min) - at(min + span / 10)) / (subs + 1), 12, 'bar-minor');
    }
  }
  if (r.a.ShowProcessValue === 'true') {
    const y = at(min + span / 2), x = b.x + b.w - 1;
    svgEl('path', {class: 'bar-value', fill: color,
      d: `M ${x - 27} ${y} L ${x - 21} ${y - 7} L ${x} ${y - 7} L ${x} ${y + 7} L ${x - 21} ${y + 7} z`}, g);
    if (fontAttrs) {
      const t = svgEl('text', Object.assign({class: 'line', x: x - 10, y: y + 4, 'text-anchor': 'middle',
        fill: 'rgb(255, 255, 255)'}, fontAttrs), g);
      t.textContent = number(min + span / 2);
    }
  }
}

// Draw one screen item into g. Returns false when the type is not drawn.
function drawItem(g, it, b, ctx, r) {
  const el = it.el, t = X.shortType(it.type);
  switch (t) {
    case 'Rectangle': {
      const rx = r.num('RoundCornerWidth'), ry = r.num('RoundCornerHeight');
      frame(g, b, fillOf(r), null, 0, {rx: rx || undefined, ry: ry || undefined});
      border(g, b, r, rx || 0);
      flashing(g, b, r);
      return true;
    }
    case 'TextField': {
      boxed(g, b, r, fillOf(r), r.num('CornerRadius'));
      textBlock(g, b, X.pickCulture(X.texts(el, ['Text']), ctx.lang), r, X.font(el, ctx.lang), '');
      return true;
    }
    case 'IOField':
    case 'SymbolicIOField': {
      boxed(g, b, r, fillOf(r), r.num('CornerRadius'));
      // Text: the format pattern as the editor shows it (ioText); a symbolic field the text list entry a tag at 0
      // selects (no tag values here), or [list name] when the list is not in the repo.
      let lines;
      if (t === 'IOField') {
        const p = r.str('FormatPattern');
        lines = p === undefined ? null : [ioText(p)];
        if (p !== undefined) patternMark(g, b, p);
      } else {
        const tl = X.links(el).find(l => l.kind === 'TextList');
        const entry = tl && tl.name ? (ctx.textlists || {})[tl.name] : null;
        lines = entry ? X.pickCulture(entry, ctx.lang) : ['[' + (tl && tl.name ? tl.name : 'text list') + ']'];
      }
      textBlock(g, b, lines, r, X.font(el, ctx.lang), '');
      return true;
    }
    case 'Button': {
      const mode = r.str('Mode');
      if (mode === 'Invisible') {
        // The editor shows it: a black 1 px frame with dots 8 px apart inside (S2), over what lies under it. In Run mode
        // app.css takes frame and dots away, as on the panel.
        const id = 'invisible' + (++defSeq);
        const dots = svgEl('pattern', {id, x: b.x, y: b.y + 4, width: 8, height: 8, patternUnits: 'userSpaceOnUse'},
          svgEl('defs', {}, g));
        svgEl('rect', {width: 1, height: 1, fill: 'rgb(0, 0, 0)'}, dots);
        frame(g, b, `url(#${id})`, null, 0, {class: 'body invisible-button'});
        const e = inset(b, 0.5);
        svgEl('rect', {class: 'border invisible-frame', x: e.x, y: e.y, width: e.w, height: e.h, fill: 'none',
          stroke: 'rgb(0, 0, 0)', 'stroke-width': 1}, g);
        return true;
      }
      const grad = (r.a.BackFillStyle || '').startsWith('Gradient');
      const radius = r.str('CornerStyle') === 'Round' ? r.num('CornerRadius') : 0;
      boxed(g, b, r, grad ? gradientFill(g, r) : fillOf(r), radius);
      if (mode === 'Graphic') {
        const pic = X.links(el).find(l => l.kind.startsWith('Picture'));
        const m = k => r.num('PictureArea' + k + 'Margin') || 0;
        const pb = {x: b.x + m('Left'), y: b.y + m('Top'), w: Math.max(0, b.w - m('Left') - m('Right')),
          h: Math.max(0, b.h - m('Top') - m('Bottom'))};
        const url = pictureUrl(pic && pic.name, r.str('PictureAutoSizing'), ctx);
        if (url) picture(g, pb, url);
        else label(g, b, pic && pic.name ? pic.name : 'graphic');
      } else {
        textBlock(g, b, X.pickCulture(X.texts(el, ['TextOff']), ctx.lang), r, X.font(el, ctx.lang), 'TextArea');
      }
      return true;
    }
    case 'Clock': {
      // A digital clock: the dial colour and the sample date and short time, no border (S4); an analog clock has no
      // editor shot yet, so it stays labelled.
      if (r.str('Analog') !== 'false') {
        frame(g, b, 'none', 'rgb(120, 120, 200)', 1);
        label(g, b, 'clock');
        return true;
      }
      frame(g, b, r.color('DialColor') || 'none', null, 0);
      flashing(g, b, r);
      const f = X.font(el, ctx.lang);
      if (!f) { r.missing.push('Font'); return true; }
      const t = svgEl('text', {class: 'line', x: b.x + 1, y: b.y + f.size,
        'font-family': f.family + ', Tahoma, sans-serif', 'font-size': f.size,
        'font-weight': f.bold ? 'bold' : 'normal', fill: r.color('NeedleBorderColor') || MARK}, g);
      t.textContent = SAMPLE_DATE + ' ' + SAMPLE_TIME_SHORT;
      return true;
    }
    case 'Bar': {
      frame(g, b, r.color('BackColor') || 'none', null, 0);
      // A scale going up on the left is drawn as the editor draws it (S10); another orientation has no editor shot.
      const scaled = r.str('BarOrientation') === 'Up' && r.str('ScalePosition') === 'LeftUp'
        && r.str('ShowScale') === 'true';
      if (scaled) barScale(g, b, r, X.font(el, ctx.lang));
      border(g, b, r, r.num('CornerRadius'));
      flashing(g, b, r);
      if (!scaled) label(g, b, 'bar');
      return true;
    }
    case 'DateTimeField': {
      boxed(g, b, r, fillOf(r), r.num('CornerRadius'));
      // The long format has no editor shot yet, so it stays labelled.
      if (r.str('LongDateTimeFormat') !== 'false') { label(g, b, 'date/time'); return true; }
      const parts = [r.str('ShowDate') === 'true' ? SAMPLE_DATE : '', r.str('ShowTime') === 'true' ? SAMPLE_TIME : ''];
      textBlock(g, b, [parts.filter(Boolean).join(' ')], r, X.font(el, ctx.lang), '');
      return true;
    }
    case 'GraphicView': {
      const pic = X.links(el).find(l => l.kind === 'Picture');
      const url = pictureUrl(pic && pic.name, r.str('AutoSizing'), ctx);
      frame(g, b, fillOf(r), url ? null : 'rgb(120, 120, 200)', 1);
      if (url) picture(g, b, url);
      border(g, b, r, 0);
      flashing(g, b, r);
      if (!url) label(g, b, pic && pic.name ? pic.name : '(no picture)');
      return true;
    }
    case 'FaceplateInstance':
      frame(g, b, 'none', 'rgb(72, 116, 160)', 1);
      label(g, b, (r.a.FaceplateTypeName || '').split('@$@').pop(), 'tag-label faceplate');
      return true;
    case 'Polyline':
    case 'Polygon': {
      const pts = X.points(el) || [];
      const attrs = t === 'Polygon'
        ? {fill: fillOf(r), stroke: r.num('BorderWidth') ? r.color('BorderColor') || 'none' : 'none',
          'stroke-width': r.num('BorderWidth') || undefined}
        : Object.assign({fill: 'none'}, lineAttrs(g, r));
      svgEl(t === 'Polygon' ? 'polygon' : 'polyline',
        Object.assign({class: 'body', points: pts.map(p => p.join(',')).join(' ')}, attrs), g);
      flashing(g, b, r);
      return true;
    }
    case 'Line':
      svgEl('line', Object.assign({class: 'body', x1: r.a.StartLeft, y1: r.a.StartTop, x2: r.a.EndLeft,
        y2: r.a.EndTop}, lineAttrs(g, r)), g);
      flashing(g, b, r);
      return true;
    case 'Circle': {
      const bw = r.num('BorderWidth') || 0;
      const stroke = bw ? r.color('BorderColor') : null;
      svgEl('ellipse', {class: 'body', cx: b.x + b.w / 2, cy: b.y + b.h / 2, rx: Math.max(0, (b.w - bw) / 2),
        ry: Math.max(0, (b.h - bw) / 2), fill: fillOf(r), stroke: stroke || 'none',
        'stroke-width': stroke ? bw : undefined}, g);
      flashing(g, b, r);
      return true;
    }
    default:
      return false;
  }
}

function objGroup(parent, attrs) {
  return svgEl('g', Object.assign({class: 'obj'}, attrs), parent);
}

function badge(g, b, text, cls) {
  const w = 6 * text.length + 8;
  const bg = svgEl('g', {class: 'badge ' + cls}, g);
  svgEl('rect', {x: b.x + b.w - w, y: b.y - 7, width: w, height: 14, rx: 3}, bg);
  const t = svgEl('text', {x: b.x + b.w - w / 2, y: b.y + 3, 'text-anchor': 'middle',
    'font-family': 'Tahoma, sans-serif', 'font-size': 10}, bg);
  t.textContent = text;
}

// Draw the items of one document into layer. ctx: {lang, source, planned: Set of ObjectNames, register(g, info),
// picture(name) -> URL of a project graphic or null (optional)}.
export function drawItems(layer, list, ctx) {
  for (const it of list) {
    if (it.group) {
      const gg = svgEl('g', {class: 'group', 'data-name': it.name}, layer);
      drawItems(gg, it.children, ctx);
      continue;
    }
    const b = X.box(it.el);
    const t = X.shortType(it.type);
    const g = objGroup(layer, {'data-name': it.name, 'data-type': t, 'data-source': ctx.source});
    const bb = b || {x: 0, y: 0, w: 120, h: 20};     // placeholder size of the "not drawn" label, not a TIA value
    for (const [k, v] of [['x', bb.x], ['y', bb.y], ['w', bb.w], ['h', bb.h]]) g.setAttribute('data-' + k, v);
    const r = reader(it.el);
    if (!b || !drawItem(g, it, bb, ctx, r)) {
      g.classList.add('not-drawn');
      frame(g, bb, 'url(#hatch-grey)', 'rgb(160, 0, 0)', 1, {'stroke-dasharray': '4 3'});
      label(g, bb, 'not drawn: ' + t);
    } else {
      const missing = [...new Set([...(b.missing || []), ...r.missing])].sort();
      if (missing.length) {
        g.classList.add('incomplete');
        g.setAttribute('data-missing', missing.join(' '));
        svgEl('rect', {class: 'incomplete-mark', x: bb.x - 1, y: bb.y - 1, width: bb.w + 2, height: bb.h + 2,
          fill: 'none', stroke: MARK, 'stroke-width': 1, 'stroke-dasharray': '6 2'}, g);
      }
    }
    if (X.hasVisibilityAnimation(it.el)) {
      svgEl('line', {class: 'vis-anim', x1: bb.x, y1: bb.y + 1, x2: bb.x + bb.w, y2: bb.y + 1,
        stroke: 'rgb(200, 16, 46)', 'stroke-width': 2, 'stroke-dasharray': '3 3'}, g);
    }
    if (ctx.planned && ctx.planned.has(it.name)) badge(g, bb, 'planned', 'planned');
    if (ctx.register) ctx.register(g, it, bb);
  }
}

// Hand-built placeholders: [{screen, kind, x, y, w, h}].
export function drawHandbuilt(layer, entries) {
  for (const e of entries) {
    const b = {x: Number(e.x) || 0, y: Number(e.y) || 0, w: Number(e.w) || 0, h: Number(e.h) || 0};
    const g = objGroup(layer, {class: 'obj handbuilt', 'data-name': String(e.kind), 'data-type': 'handbuilt',
      'data-source': 'handbuilt', 'data-screen': e.screen, 'data-x': b.x, 'data-y': b.y, 'data-w': b.w, 'data-h': b.h});
    frame(g, b, 'url(#hatch)', 'rgb(90, 90, 90)', 1, {'stroke-dasharray': '6 3'});
    label(g, {x: b.x + 4, y: b.y + 4, w: b.w, h: b.h}, e.kind + ' (hand-built in TIA)', 'handbuilt-label');
  }
}

export function defs(svg) {
  const d = svgEl('defs', {}, svg);
  for (const [id, c] of [['hatch', 'rgba(60, 60, 60, 0.35)'], ['hatch-grey', 'rgba(160, 0, 0, 0.25)']]) {
    const p = svgEl('pattern', {id, width: 8, height: 8, patternUnits: 'userSpaceOnUse',
      patternTransform: 'rotate(45)'}, d);
    svgEl('rect', {width: 8, height: 8, fill: 'rgba(255, 255, 255, 0.6)'}, p);
    svgEl('line', {x1: 0, y1: 0, x2: 0, y2: 8, stroke: c, 'stroke-width': 3}, p);
  }
}

// The template's objects under a screen: the editor draws them at half strength over the screen's BackColor (measured on
// S1 and S11: 255 -> 240 on a 224 screen, 192 -> 218 on a 244 screen). The template's own view is drawn in full, and
// in Run mode app.css sets it to full strength, as on the panel.
export const TEMPLATE_OPACITY = 0.5;

// Background of a screen, template or pop-up root: its BackColor, else none (the page shows through).
export function rootFill(root) {
  return X.color(X.attr(root, 'BackColor'), 'none');
}
