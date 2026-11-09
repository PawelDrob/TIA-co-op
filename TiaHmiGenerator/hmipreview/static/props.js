// The object's properties laid out like TIA's Properties window: a title "name [type]", the tabs
// Properties, Animations, Events and Texts, and below the title the preview's own lines (where the object is, style
// preset, copied from, links, findings, overlaps).
//
// The layout comes from the screen object catalogue (GET /api/catalogue?element=, hmipreview/catalogueapi.py; schema in
// docs/agent/wincc-screen-objects.md section 3): TIA's groups in TIA's order and its display names, the export name
// in italics where TIA's name is not known and on hover; a value as TIA shows it (colour swatch and "r, g, b", a
// check box, an enum's TIA text where the catalogue knows it, a font as "Tahoma, 13px, Bold"); a row grey only where
// the catalogue knows TIA greys it for the object's values; a row the document does not carry grey "not set", TIA's
// default on hover. No mark for a value that differs from the default. The attributes TIA's Properties window does
// not show and those the catalogue does not know go into a last group "Other" (the maintainer's name for it,
// 2026-11-05); without a catalogue type (an unknown element) every attribute is in it. A search box over the tabs
// filters every tab by its names (the maintainer, 2026-11-05: the rail's fuzzy matching, rail.js ldiffFuzzy):
// Properties and Texts by the row's TIA name and export name, Animations by the animation's name and its rows', Events
// by the event's name and its functions'. A hit on an animation's or event's own name keeps all of it.
//
// panel(info) -> <div class="tia-props">; info {el, type, name, catalogue (the type or null), lang, links
// (the document's resolved links of this object), head: [[label, value, cls?]] (lines under the title), extra:
// [elements] (appended under the head)}.
//
// Markup for the tests: tr.row[data-attr=<export name>] > td.n, td.v (the value's text); .tab[data-tab]; section
// .pane[data-tab]; tr.grp[data-group]; tr.row.grey; .anim[data-animation]; .ev[data-event] > li.fn[data-function];
// tr.txt[data-text]; input.psearch; while searching, what has no hit is hidden, the marked letters are <mark>s and
// each tab says its hits in .tab > .tcount.
'use strict';
import * as X from './simaticml.js';

const TABS = [['properties', 'Properties'], ['animations', 'Animations'], ['events', 'Events'], ['texts', 'Texts']];
const OTHER = 'Other';         // without a TIA group in the catalogue, or not in the catalogue
const KEPT = 'hmipreview-props';                  // localStorage: {tab, shut: [group names]}
// The columns of TIA's range table (Animations > Appearance); other attributes keep their export names.
const RANGE_TEXT = {BackColor: 'Background color', ForeColor: 'Foreground color', FlashingType: 'Flashing'};
let searchText = '';               // the search of the Properties tab, kept from one object to the next

// The search of the Properties tab, set before the panel is drawn (URL hook ?prop=).
export function setSearch(text) {
  searchText = text || '';
}

// TIA's names for what the Animations tab holds (the Animations tab of TIA's Properties window); others by element.
const ANIMATION_TEXT = {
  'Hmi.Dynamic.RangeAppearanceAnimation': 'Appearance',
  'Hmi.Dynamic.VisibilityAnimation': 'Visibility',
  'Hmi.Dynamic.SingleBitVisibilityAnimation': 'Visibility (single bit)',
};

function animationKey(element) {
  return element.replace(/^Hmi\.Dynamic\./, '');
}

function animationText(element) {
  return ANIMATION_TEXT[element] || animationKey(element);
}

export function el(tag, text, cls, attrs) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null) e.setAttribute(k, v);
  return e;
}

function kept() {
  try {
    const k = JSON.parse(localStorage.getItem(KEPT) || '{}');
    return {tab: k.tab || 'properties', shut: new Set(k.shut || [])};
  } catch (err) {
    return {tab: 'properties', shut: new Set()};
  }
}

function keep(k) {
  try { localStorage.setItem(KEPT, JSON.stringify({tab: k.tab, shut: [...k.shut]})); } catch (err) { /* private */ }
}

// --- values ---------------------------------------------------------------------------------------------------

// Font of a composition ('Font', 'CaptionFont' ...) for a culture as TIA shows it: "Tahoma, 13px, Bold", the style
// left out when Regular. null when the object has none.
function fontText(obj, comp, lang) {
  for (const c of X.kids(X.child(obj, 'ObjectList'))) {
    if (c.getAttribute('CompositionName') !== comp) continue;
    const items = Array.from(c.getElementsByTagName('*')).filter(e => e.tagName.endsWith('FontItem'));
    const it = items.find(i => X.attr(i, 'Culture') === lang) || items[0];
    if (!it) return null;
    const style = X.attr(it, 'FontStyle', '');
    return [X.attr(it, 'FontFamily', '?'), X.attr(it, 'FontSize', '?') + 'px',
      style && style !== 'Regular' ? style.replace(/,\s*/g, ' ') : ''].filter(Boolean).join(', ');
  }
  return null;
}

// The tag of a dynamized property (Hmi.Screen.Property Name=prop with a TagConnectionDynamic), or null.
function propertyTag(obj, prop) {
  for (const p of X.kids(X.child(obj, 'ObjectList'), c => c.tagName === 'Hmi.Screen.Property')) {
    if (X.attr(p, 'Name') !== prop) continue;
    for (const d of p.getElementsByTagName('Hmi.Dynamic.TagConnectionDynamic')) {
      const l = X.links(d)[0];
      if (l) return l.name;
    }
  }
  return null;
}

// The layer of an object as TIA's Miscellaneous > Layer shows it: "0 - Layer_0", the index alone when the layer has
// no name; null outside a layer.
function layerText(obj) {
  for (let p = obj.parentElement; p; p = p.parentElement) {
    if (p.tagName === 'Hmi.Screen.ScreenLayer') {
      const n = X.attr(p, 'Name', '');
      return X.attr(p, 'Index', '0') + (n ? ' - ' + n : '');
    }
  }
  return null;
}

function linkOf(obj, kind) {
  return X.links(obj).find(l => l.kind === kind) || null;
}

// The value of a catalogue row on the object: {text, raw, colour, bool} or null when the object does not carry it.
// raw is what greyedWhen compares (the export spelling).
function valueOf(obj, a, lang) {
  const name = a.name;
  if (!name) return null;
  if (name.startsWith('link:')) {
    const l = linkOf(obj, name.slice(5));
    return l ? {text: l.self ? '(own)' : l.name, raw: l.name, link: name.slice(5)} : null;
  }
  if (name.startsWith('tag:')) {
    const t = propertyTag(obj, name.slice(4));
    return t ? {text: t, raw: t, tag: true} : null;
  }
  if (name.startsWith('@')) {
    const comp = name.slice(1);
    if (a.kind === 'font') {
      const f = fontText(obj, comp, lang);
      return f ? {text: f, raw: f} : null;
    }
    const t = X.pickCulture(X.texts(obj, [comp]), lang);
    return t ? {text: t.join(' / '), raw: t.join('\n')} : null;
  }
  const v = X.attr(obj, name);
  if (v === undefined) return null;
  return displayValue(a, v);
}

// An attribute's export text as TIA shows it.
function displayValue(a, v) {
  const kind = a ? a.kind : guessKind(v);
  if (kind === 'colour' && X.color(v, null)) return {text: v, raw: v, colour: X.color(v)};
  if (kind === 'bool' && (v === 'true' || v === 'false')) return {text: v === 'true' ? 'Yes' : 'No', raw: v, bool: v === 'true'};
  if (kind === 'list') {
    const n = (v.match(/<Item>/g) || []).length;
    return {text: n + (n === 1 ? ' item' : ' items'), raw: v, title: v.replace(/<\/?Item>/g, ' ').replace(/\s+/g, ' ').trim()};
  }
  if (kind === 'blob') return {text: '(binary)', raw: v};
  if (a && a.shown && v === a.default) return {text: a.shown, raw: v};
  return {text: v, raw: v};
}

// A catalogue default as TIA shows it; a font's "Tahoma, 13px, style=Bold" (the catalogue's spelling) as fontText
// writes it: "Tahoma, 13px, Bold".
function defaultText(a) {
  if (a.shown) return a.shown;
  const m = a.kind === 'font' && /^(.*), style=(.*)$/.exec(a.default);
  return m ? `${m[1]}, ${m[2].replace(/,\s*/g, ' ')}` : a.default;
}

function guessKind(v) {
  if (/^\d{1,3}, \d{1,3}, \d{1,3}$/.test(v)) return 'colour';
  if (v === 'true' || v === 'false') return 'bool';
  return null;
}

// Whether TIA greys the row for the object's values (the catalogue's greyedWhen: any one condition greys). A value
// the object does not carry counts as the catalogue's default.
function greyed(a, current) {
  for (const c of a.greyedWhen || []) {
    if (c.always) return true;
    const v = current(c.attribute);
    if (v === null || v === undefined) continue;
    const vals = (c.values || []).map(String);
    if ((c.op === 'eq' || c.op === 'in') && vals.includes(v)) return true;
    if (c.op === 'ne' && !vals.includes(v)) return true;
  }
  return false;
}

// --- the Properties tab ---------------------------------------------------------------------------------------

function swatch(colour) {
  return el('span', null, 'sw', {style: 'background:' + colour});
}

function valueCell(v, state) {
  const td = el('td', null, 'v');
  if (!v) {
    td.classList.add('unset');
    return td;
  }
  if (v.colour) td.append(swatch(v.colour));
  if (v.bool !== undefined) {
    td.append(el('span', null, 'cb' + (v.bool ? ' on' : ''), {role: 'img', 'aria-label': v.text}));
    td.append(el('span', v.text, 'cbt'));
  } else {
    td.append(el('span', v.text, 't'));
  }
  if (v.title) td.title = v.title;
  if (state) {
    td.classList.add('state-' + state.state);
    td.title = `${state.kind} ${state.name}: ${state.state}${state.note ? ' (' + state.note + ')' : ''}`;
  }
  return td;
}

function nameCell(a, exportName) {
  const known = a && a.displayKnown;
  const td = el('td', known ? a.display : exportName, 'n' + (known ? '' : ' export'));
  td.title = [exportName || 'not in the export', a && a.description].filter(Boolean).join(': ');
  return td;
}

// [{group, rows: [{a, name, v}]}] in TIA's order: the catalogue's groups as it lists them, then "Other": the rows
// without a group, then the object's attributes the catalogue does not know.
function groups(info) {
  const obj = info.el, cat = info.catalogue, lang = info.lang;
  const out = [], byName = new Map();
  const add = (g, row) => {
    if (!byName.has(g)) { byName.set(g, {group: g, rows: []}); out.push(byName.get(g)); }
    byName.get(g).rows.push(row);
  };
  const seen = new Set();
  const later = [];
  for (const a of cat ? cat.attributes : []) {
    if (a.name) seen.add(a.name);
    let v = valueOf(obj, a, lang);
    if (!a.name && a.display === 'Layer') {
      const layer = layerText(obj);
      if (layer !== null) v = {text: layer, raw: layer};
    }
    const row = {a, name: a.name, v};
    if (a.group) add(a.group, row); else later.push(row);
  }
  for (const row of later) add(OTHER, row);
  const own = X.attrs(obj);
  for (const k of Object.keys(own).sort()) {
    if (!seen.has(k)) add(OTHER, {a: null, name: k, v: displayValue(null, own[k])});
  }
  return out;
}

// A grid table with TIA's two columns (name 48 %, value) or the given widths.
function grid(cls, widths) {
  const t = el('table', null, 'grid' + (cls ? ' ' + cls : ''));
  const cg = el('colgroup');
  for (const w of widths || ['48%', null]) cg.append(el('col', null, null, w ? {style: 'width:' + w} : {}));
  t.append(cg);
  return t;
}

function propertiesPane(info, k) {
  const obj = info.el, cat = info.catalogue;
  const byName = new Map((cat ? cat.attributes : []).filter(a => a.name).map(a => [a.name, a]));
  const current = n => {
    const v = X.attr(obj, n);
    if (v !== undefined) return v;
    const a = byName.get(n);
    return a ? a.default : null;
  };
  // The checked state of a link's or tag's target (valueOf resolved the name into the row's value).
  const linkState = v => v && (v.link || v.tag) ? (info.links || []).find(l => l.name === v.raw) || null : null;
  const t = grid();
  const head = el('tr', null, 'colhead');
  head.append(el('th', 'Name'), el('th', 'Static value'));
  t.append(head);
  const parts = [];
  for (const g of groups(info)) {
    const shut = k.shut.has(g.group);
    const gr = el('tr', null, 'grp' + (shut ? ' shut' : ''), {'data-group': g.group});
    const th = el('th', g.group, null, {colspan: 2});
    gr.append(th);
    t.append(gr);
    const rows = [];
    for (const r of g.rows) {
      const tr = el('tr', null, 'row', {'data-attr': r.name || r.a.display});
      if (r.a && greyed(r.a, current)) tr.classList.add('grey');
      if (!r.v) tr.title = !r.name ? 'TIA shows this row; the export does not carry it'
        : 'Not in the document' + (r.a && r.a.default !== null && r.a.default !== undefined
          ? '; TIA takes ' + defaultText(r.a) : '');
      const n = nameCell(r.a, r.name);
      tr.append(n, valueCell(r.v, linkState(r.v)));
      tr.hidden = shut;
      rows.push({tr, n, label: n.textContent, exportName: r.name || ''});
      t.append(tr);
    }
    parts.push({box: gr, rows, shut: () => gr.classList.contains('shut')});
    th.addEventListener('click', () => {
      if (searchText.trim()) return;                   // while searching every group with a hit stays open
      const now = !gr.classList.contains('shut');
      gr.classList.toggle('shut', now);
      for (const r of rows) r.tr.hidden = now;
      if (now) k.shut.add(g.group); else k.shut.delete(g.group);
      keep(k);
    });
  }
  return {node: t, parts};
}

// --- the search -----------------------------------------------------------------------------------------------
//
// A tab's searchable parts: [{box (hidden when nothing in it hits, or null), head (the cell of the part's own name,
// searched and marked, or null), label (head's text), rows: [{tr, n (the cell to mark), label, exportName}], shut
// (whether the part is folded while not searching; absent: never)}].

// One name against a search: the matched positions in the name, or null (the rail's fuzzy matching, rail.js).
function matchName(q, name) {
  if (!name) return null;
  const src = window.ldiffFuzzy.source([name]);
  const f = window.ldiffFuzzy.fuzzy(q, src.l[0], src.b[0]);
  return f ? f[1] : null;
}

function mark(cell, label, at) {
  if (at) cell.innerHTML = window.ldiffFuzzy.marked(label, at);
  else if (cell.firstElementChild) cell.textContent = label;
}

// Filter a tab's parts by a query (ldiffFuzzy.query; '' shows all again, folded parts as they were) over TIA's names
// and the export names. A hit on a part's own name keeps all of it. -> {hits, total}: names with a hit, names searched.
function filter(parts, q) {
  let hits = 0, total = 0;
  for (const g of parts) {
    const headAt = q && g.head ? matchName(q, g.label) : null;
    if (g.head) { total++; mark(g.head, g.label, headAt); }
    let n = headAt ? 1 : 0;
    const shut = !!g.shut && g.shut();
    for (const r of g.rows) {
      total++;
      const at = q ? matchName(q, r.label) : null;
      const hit = !!(at || q && r.exportName && r.exportName !== r.label && matchName(q, r.exportName));
      mark(r.n, r.label, at);
      r.tr.hidden = q ? !hit && !headAt : shut;
      if (hit) n++;
    }
    if (g.box) g.box.hidden = !!q && !n;
    hits += n;
  }
  return {hits, total};
}

// A section of the Animations or Events tab under its name; its part of the search goes into parts.
function section(cls, attrs, name, parts) {
  const s = el('section', null, cls, attrs);
  const head = el('h4', name);
  s.append(head);
  const part = {box: s, head, label: name, rows: []};
  parts.push(part);
  return [s, part];
}

// --- the Animations tab ---------------------------------------------------------------------------------------

// An animation's own attributes, each row also into rows (the search).
function attrRows(e, rows) {
  const t = grid('small');
  for (const [n, v] of Object.entries(X.attrs(e))) {
    if (n === 'Name') continue;
    const tr = el('tr', null, 'row', {'data-attr': n});
    const nc = el('td', n, 'n export');
    tr.append(nc, valueCell(displayValue(null, v)));
    rows.push({tr, n: nc, label: n, exportName: n});
    t.append(tr);
  }
  return t;
}

function animationsPane(info) {
  const obj = info.el, cat = info.catalogue;
  const box = el('div', null, 'anims');
  const parts = [];
  const tagged = X.kids(X.child(obj, 'ObjectList'), c => c.tagName === 'Hmi.Screen.Property')
    .map(p => [X.attr(p, 'Name', ''), propertyTag(obj, X.attr(p, 'Name', ''))]).filter(p => p[1]);
  const [conn, cp] = section('anim', {'data-animation': 'TagConnections'}, 'Tag connections', parts);
  if (tagged.length) {
    const t = grid('small');
    for (const [prop, tag] of tagged) {
      const a = cat && cat.attributes.find(x => x.name === 'tag:' + prop);
      const tr = el('tr', null, 'row', {'data-attr': prop});
      const n = nameCell(a, prop);
      tr.append(n, valueCell({text: tag}));
      cp.rows.push({tr, n, label: n.textContent, exportName: prop});
      t.append(tr);
    }
    conn.append(t);
  } else {
    conn.append(el('p', 'None', 'none'));
  }
  box.append(conn);
  const own = X.kids(X.child(obj, 'ObjectList'), c => c.getAttribute('CompositionName') === 'Animations');
  const types = new Set(own.map(a => a.tagName));
  for (const a of own) {
    const [s, sp] = section('anim', {'data-animation': animationKey(a.tagName)}, animationText(a.tagName), parts);
    for (const trig of X.kids(X.child(a, 'ObjectList'), c => !c.tagName.endsWith('.Range'))) {
      const l = X.links(trig)[0];
      if (l) s.append(el('p', `Tag: ${l.name}`, 'tag'));
    }
    const ranges = X.kids(X.child(a, 'ObjectList'), c => c.tagName === 'Hmi.Dynamic.Range');
    if (ranges.length) s.append(rangeTable(ranges));
    const rest = attrRows(a, sp.rows);
    if (rest.children.length > 1) s.append(rest);        // more than its colgroup
    box.append(s);
  }
  for (const name of cat ? cat.animations || [] : []) {
    if (types.has(name)) continue;
    const [s] = section('anim off', {'data-animation': animationKey(name)}, animationText(name), parts);
    s.append(el('p', 'Not used', 'none'));
    box.append(s);
  }
  return {node: box, parts};
}

function rangeTable(ranges) {
  const t = el('table', null, 'grid ranges');
  const cols = [...new Set(ranges.flatMap(r => Object.keys(X.attrs(r))))]
    .filter(c => c !== 'LowerLimit' && c !== 'UpperLimit');
  const head = el('tr', null, 'colhead');
  head.append(el('th', 'Range'), ...cols.map(c => el('th', RANGE_TEXT[c] || c, null, {title: c})));
  t.append(head);
  for (const r of ranges) {
    const lo = X.attr(r, 'LowerLimit'), hi = X.attr(r, 'UpperLimit');
    const tr = el('tr', null, 'range');
    tr.append(el('td', lo === hi ? lo : `${lo} - ${hi}`), ...cols.map(c => {
      const v = X.attr(r, c);
      return valueCell(v === undefined ? null : displayValue(null, v));
    }));
    t.append(tr);
  }
  return t;
}

// --- the Events tab -------------------------------------------------------------------------------------------

function paramText(p) {
  if (p.self) return '(own)';
  if (p.link !== null) return p.link;
  return p.value;
}

function eventsPane(info) {
  const box = el('div', null, 'events');
  const parts = [];
  const evs = X.events(info.el);
  const names = [...new Set([...(info.catalogue ? info.catalogue.events || [] : []), ...evs.map(e => e.name)])];
  for (const name of names) {
    const fns = evs.filter(e => e.name === name).flatMap(e => e.functions);
    const [s, sp] = section('ev' + (fns.length ? '' : ' off'), {'data-event': name}, name, parts);
    if (!fns.length) {
      s.append(el('p', 'No function', 'none'));
    } else {
      const ol = el('ol', null, 'fns');
      for (const fn of fns) {
        const li = el('li', null, 'fn', {'data-function': fn.name});
        const fname = el('span', fn.name, 'fname');
        li.append(fname);
        sp.rows.push({tr: li, n: fname, label: fn.name, exportName: fn.name});
        const t = grid('small', ['40%', null]);
        for (const p of fn.params) {
          const tr = el('tr', null, 'param');
          tr.append(el('td', p.name, 'n'), el('td', paramText(p), 'v'));
          t.append(tr);
        }
        if (fn.params.length) li.append(t);
        ol.append(li);
      }
      s.append(ol);
    }
    box.append(s);
  }
  if (!names.length) box.append(el('p', 'This object has no events.', 'none'));
  return {node: box, parts};
}

// --- the Texts tab --------------------------------------------------------------------------------------------

function textsPane(info) {
  const obj = info.el, cat = info.catalogue;
  const comps = X.kids(X.child(obj, 'ObjectList'), c => c.tagName === 'MultilingualText')
    .map(c => c.getAttribute('CompositionName'));
  const all = comps.map(c => [c, X.texts(obj, [c]) || {}]);
  const cultures = [...new Set(all.flatMap(([, m]) => Object.keys(m)))];
  if (!all.length) return {node: el('p', 'This object has no texts.', 'none'), parts: []};
  const t = el('table', null, 'grid texts');
  const head = el('tr', null, 'colhead');
  head.append(el('th', 'Text'), ...cultures.map(c => el('th', c)));
  t.append(head);
  const rows = [];
  for (const [comp, m] of all) {
    const a = cat && cat.attributes.find(x => x.name === '@' + comp);
    const tr = el('tr', null, 'txt', {'data-text': comp});
    const n = nameCell(a, comp);
    tr.append(n, ...cultures.map(c => el('td', m[c] ? m[c].join(' / ') : '', 'v')));
    rows.push({tr, n, label: n.textContent, exportName: comp});
    t.append(tr);
  }
  return {node: t, parts: [{box: null, head: null, rows}]};
}

// --- the panel ------------------------------------------------------------------------------------------------

export function panel(info) {
  const k = kept();
  const root = el('div', null, 'tia-props');
  const typeName = info.catalogue && info.catalogue.toolbox ? info.catalogue.toolbox.name : X.shortType(info.type);
  const title = el('div', null, 'ptitle');
  title.append(el('b', info.name), el('span', ` [${typeName}]`, 'ptype'));
  if (!info.catalogue) title.append(el('span', ' not in the catalogue', 'muted'));
  root.append(title);
  if (info.head && info.head.length) {
    const t = el('table', null, 'phead props');
    for (const [label, value, cls] of info.head) {
      const tr = el('tr', null, 'prop', {'data-prop': label});
      tr.append(el('td', label), el('td', value, cls));
      t.append(tr);
    }
    root.append(t);
  }
  for (const e of info.extra || []) root.append(e);
  const tabs = el('div', null, 'tabs', {role: 'tablist'});
  const panes = {
    properties: () => propertiesPane(info, k), animations: () => animationsPane(info),
    events: () => eventsPane(info), texts: () => textsPane(info),
  };
  const body = el('div', null, 'panes');
  const searched = [];                                   // [[tab button, its parts]]
  const box = el('input', null, 'psearch', {type: 'search', placeholder: 'Search names',
    'aria-label': 'Search the names in every tab', title: "TIA's names and the export names, fuzzy, in every tab"});
  const count = el('span', null, 'pcount');
  const search = () => {
    const q = window.ldiffFuzzy.query(searchText);
    for (const [b, parts] of searched) {
      const {hits, total} = filter(parts, q);
      b.lastChild.textContent = q ? String(hits) : '';
      if (b.classList.contains('on')) count.textContent = q ? `${hits} of ${total}` : '';
    }
  };
  box.value = searchText;
  box.addEventListener('input', () => { searchText = box.value; search(); });
  box.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && box.value) { ev.stopPropagation(); box.value = searchText = ''; search(); }
  });
  const open = key => {
    k.tab = key;
    keep(k);
    for (const b of tabs.children) b.classList.toggle('on', b.getAttribute('data-tab') === key);
    for (const p of body.children) p.hidden = p.getAttribute('data-tab') !== key;
    search();
  };
  for (const [key, label] of TABS) {
    const b = el('button', label, 'tab', {'data-tab': key, role: 'tab', type: 'button'});
    b.append(el('span', null, 'tcount'));
    b.addEventListener('click', () => open(key));
    tabs.append(b);
    const p = el('section', null, 'pane', {'data-tab': key});
    const {node, parts} = panes[key]();
    p.append(node);
    searched.push([b, parts]);
    body.append(p);
  }
  const bar = el('div', null, 'psearchbar');
  bar.append(box, count);
  root.append(bar, tabs, body);
  open(TABS.some(t => t[0] === k.tab) ? k.tab : 'properties');
  return root;
}
