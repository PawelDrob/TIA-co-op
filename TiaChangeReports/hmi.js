// HMI part of the change report (hmi.py): one view per HMI object section, drawn when the section opens (the page's
// one object at a time) or all at once on a flat page (?all, print, --png, a fragment). X and R are the HMI
// preview's simaticml.js and render.js (hmipreview.jsbundle), bound inside this function so that two reports on
// one page do not collide. Data: <script class="hmidata"> in the report, gzip + base64 of
// {lang, parts: [{before, after, data}], docs: {id: SimaticML}, objects: [{key, part, device, kind, name, state,
// changes, bdoc, adoc, ...}]} (hmipreview.changes); a section <section class="blk hmi" data-o="index"> holds an
// empty <div class="hv"> that the view fills.
(function () {
const S = document.currentScript, r = S && S.closest('.ldiff'), DATA = r && r.querySelector('script.hmidata');
if (!DATA) return;
/*BUNDLE*/
const DRAWN = new Set(['screen', 'template', 'popup', 'slidein', 'global']);
const KIND_TEXT = {screen: 'Screen', template: 'Template', popup: 'Pop-up screen', slidein: 'Slide-in screen',
  global: 'Global screen', textlist: 'Text list', graphiclist: 'Graphic list', tagtable: 'HMI tag table',
  cycle: 'Cycle', connection: 'Connection', script: 'Script', graphic: 'Graphic'};
const CHANGE_CLASS = {added: 'new', removed: 'deleted', moved: 'moved', changed: 'changed'};
const LAYOUTS = ['side', 'stack', 'toggle'];
let M = null;
const BY = new Map(), ROOTS = new Map(), shown = new Set();
const ui = {mode: keep('mode') || 'side', fit: keep('fit') !== '0', show: 'after', lines: keep('lines') !== '0'};
const FOLD_TEXT = {export: 'absent in a minimal export (the default value in TIA) or in the whole document on one side',
  quiet: 'no visible effect'};

function keep(k, v) {
  try { if (v !== undefined) localStorage.setItem('ldiff-hmi-' + k, v); return localStorage.getItem('ldiff-hmi-' + k); }
  catch (e) { return null; }
}

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
}

async function decode() {
  const bin = atob(DATA.textContent.trim()), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}

const id3 = (part, device, kind, name) => [part, device, kind, name].join('\u0001');
function find(o, kind, name) { return BY.get(id3(o.part, o.device, kind, name)) || null; }
function docId(o, side) { return o ? (side === 'before' ? o.bdoc : o.adoc) : null; }
function present(o, side) { return !!o && (side === 'before' ? o.state !== 'new' : o.state !== 'deleted'); }
function rootOf(id) {
  if (!id) return null;
  if (!ROOTS.has(id)) ROOTS.set(id, X.rootObject(X.parseXml(M.docs[id])));
  return ROOTS.get(id);
}
function sideData(o, side) { return (M.parts[o.part].data[side] || {})[o.device] || {}; }
function label(o, side) { return M.parts[o.part][side]; }
function link(o, kind, name, device) {
  const t = find(device === undefined ? o : {part: o.part, device}, kind, name), a = t && r.querySelector('.tree a.obj[data-key="' + CSS.escape(t.key) + '"]');
  return a ? h('a', {href: a.getAttribute('href')}, name) : h('span', {}, name);
}

// --- drawing --------------------------------------------------------------------------------------------------

function itemsBox(root) {
  let w = 0, hh = 0;
  for (const it of X.flatItems(X.screenItems(root))) {
    const b = X.box(it.el);
    if (b) { w = Math.max(w, b.x + b.w); hh = Math.max(hh, b.y + b.h); }
  }
  return [w || 1, hh || 1];
}

// Size of a drawn document: its Width / Height, else the side's declared panel, else what its objects cover.
function sizeOf(o, side, root) {
  const w = X.num(root, 'Width'), hh = X.num(root, 'Height');
  if (w !== undefined && hh !== undefined) return [w, hh];
  const p = sideData(o, side).panel;
  return p && p.width && p.height ? [p.width, p.height] : itemsBox(root);
}

function textlists(o, side, roots) {
  const out = {};
  for (const root of roots) {
    if (!root) continue;
    for (const l of root.getElementsByTagName('TextList')) {
      const n = l.parentElement && l.parentElement.tagName === 'LinkList' ? X.child(l, 'Name') : null;
      if (!n || !n.textContent || n.textContent in out) continue;
      const tl = find(o, 'textlist', n.textContent);
      const entry = present(tl, side) && docId(tl, side) ? X.textListEntry(rootOf(docId(tl, side)), 0) : null;
      if (entry) out[n.textContent] = entry;
    }
  }
  return out;
}

// name -> data URI of the project graphic on that side (the report embeds the pictures the screens use), or null.
function pictures(o, side) {
  const map = (M.parts[o.part].pictures || {})[side] || {};
  return name => (map[name] && M.docs[map[name]]) || null;
}

// ObjectNames on the layers of o's document on that side that are hidden in the editor (not drawn, decision 5).
function hiddenNames(o, side) {
  const key = side === 'before' ? 'hidb' : 'hida';
  if (!o[key]) {
    o[key] = new Set();
    const root = present(o, side) ? rootOf(docId(o, side)) : null;
    const layers = X.kids(X.child(root, 'ObjectList'),
      c => c.getAttribute('CompositionName') === 'Layers' && X.attr(c, 'VisibleES') === 'false');
    for (const l of layers) {
      for (const e of l.getElementsByTagName('*')) {
        if (e.getAttribute('CompositionName') === 'ScreenItems') o[key].add(X.attr(e, 'ObjectName', ''));
      }
    }
  }
  return o[key];
}

// Width of a side that fills its pane: its share of the wider side, so that both are drawn at one scale.
function widthInPane(o, w) {
  const sides = ['before', 'after'].filter(side => present(o, side));
  return 100 * w / Math.max(...sides.map(side => sizeOf(o, side, rootOf(docId(o, side)))[0])) + '%';
}

function templateOf(root) { return (X.links(root).find(l => l.kind === 'Template') || {}).name || null; }

// One side of o as <svg>: the template faded underneath, the document, hand-built placeholders, the change outlines.
function drawSide(o, side, view) {
  const root = rootOf(docId(o, side));
  const [w, hh] = sizeOf(o, side, root);
  const svg = R.svgEl('svg', {xmlns: R.SVG, viewBox: `0 0 ${w} ${hh}`, width: w, height: hh, class: 'hs'});
  svg.style.setProperty('--width-in-pane', widthInPane(o, w));
  R.defs(svg);
  R.svgEl('rect', {x: 0, y: 0, width: w, height: hh, fill: R.rootFill(root)}, svg);
  const tplName = o.kind === 'screen' ? templateOf(root) : null;
  const tpl = tplName ? find(o, 'template', tplName) : null;
  const troot = present(tpl, side) ? rootOf(docId(tpl, side)) : null;
  const lists = textlists(o, side, [root, troot]);
  if (troot) R.drawItems(R.svgEl('g', {class: 'layer tpl', opacity: R.TEMPLATE_OPACITY}, svg), X.screenItems(troot),
    {lang: M.lang, source: 'template', textlists: lists, picture: pictures(o, side)});
  R.drawItems(R.svgEl('g', {class: 'layer doc'}, svg), X.screenItems(root),
    {lang: M.lang, source: o.kind, textlists: lists, picture: pictures(o, side)});
  const hb = (sideData(o, side).handbuilt || []).filter(e => e && (e.screen === o.name || e.screen === tplName));
  if (hb.length) R.drawHandbuilt(R.svgEl('g', {class: 'layer hb'}, svg), hb);
  const dl = R.svgEl('g', {class: 'dl' + (ui.lines ? '' : ' off')}, svg);
  const hidden = hiddenNames(o, side);
  for (const c of o.changes || []) {
    if (c.fold || hidden.has(c.object)) continue;     // not drawn here: no outline (the change row says why)
    if (c.object === null) {
      R.svgEl('rect', {class: 'root', x: 3, y: 3, width: w - 6, height: hh - 6, 'data-name': ''}, dl);
      continue;
    }
    const b = side === 'before' ? c.old : c.new;
    if (!b || (c.kind === 'removed' && side === 'after') || (c.kind === 'added' && side === 'before')) continue;
    const cls = c.kind === 'moved' ? 'moved' + (side === 'before' ? ' old' : '') : c.kind;
    const e = R.svgEl('rect', {class: cls, x: b.x - 2, y: b.y - 2, width: b.w + 4, height: b.h + 4, 'data-name': c.object}, dl);
    R.svgEl('title', {}, e).textContent = `${c.type} ${c.object}: ${kindText(c)}`;
    const pts = (c.attributes || []).find(a => a.points && !a.fold);   // the points this side holds and the other not
    for (const [x, y] of pts ? pts.points[side === 'before' ? 'old' : 'new'] : []) {
      R.svgEl('circle', {class: cls, cx: x, cy: y, r: 4, 'data-name': c.object}, dl);
    }
  }
  svg.addEventListener('click', ev => {
    const g = ev.target.closest('.obj');
    if (g && g.dataset.source !== 'template') select(view, g.dataset.name, true);
  });
  svg.addEventListener('dblclick', ev => {
    const g = ev.target.closest('.obj');
    if (g && g.dataset.source !== 'template') follow(o, side, g.dataset.name);
  });
  return svg;
}

// Double click on a button: open the screen or pop-up its events activate, when it is on the page.
function follow(o, side, name) {
  const it = X.flatItems(X.screenItems(rootOf(docId(o, side)))).find(i => i.name === name);
  for (const ev of it ? X.events(it.el) : []) {
    for (const fn of ev.functions) {
      const kind = fn.name === 'ActivateScreen' ? 'screen' : fn.name === 'ShowPopupScreen' ? 'popup' : null;
      const p = fn.params.find(q => q.link);
      const t = kind && p ? find(o, kind, p.link) : null;
      const a = t && r.querySelector('.tree a.obj[data-key="' + CSS.escape(t.key) + '"]');
      if (a) { location.hash = a.getAttribute('href'); return; }
    }
  }
}

// --- the view of one object -----------------------------------------------------------------------------------

function pane(o, side, view) {
  const lab = h('div', {class: 'hl'}, h('b', {}, side === 'before' ? 'Before' : 'After'), label(o, side));
  if (!present(o, side)) {
    return h('div', {class: 'hp ' + side}, lab, h('div', {class: 'empty'}, side === 'before' ? 'not there before' : 'deleted'));
  }
  const body = h('div', {class: 'hb'}, drawSide(o, side, view));
  return h('div', {class: 'hp ' + side}, lab, body);
}

function toolbar() {
  const b = (text, title, on, run) => h('button', {type: 'button', class: on ? 'on' : null, title, onclick: run}, text);
  return h('div', {class: 'htb'},
    b('Side by side', 'Before left, after right (L switches the layout)', ui.mode === 'side', () => setMode('side')),
    b('Stacked', 'Before above after (L)', ui.mode === 'stack', () => setMode('stack')),
    b('Toggle', 'One screen at a time; Space switches before / after (L)', ui.mode === 'toggle', () => setMode('toggle')),
    b(ui.fit ? 'Fit' : '1:1', 'Fit to the pane or 1:1 (Z)', ui.fit, () => setFit(!ui.fit)),
    b('Outlines', 'Show or hide the change outlines, e.g. on a redesigned screen (O)', ui.lines, () => setLines(!ui.lines)),
    h('span', {class: 'hn'}, 'Click an object or a change to mark it in both; double click a button to open the screen it calls.'));
}

function setMode(m) { ui.mode = m; keep('mode', m); redraw(); }
function setFit(f) { ui.fit = f; keep('fit', f ? '1' : '0'); redraw(); }
function setLines(v) { ui.lines = v; keep('lines', v ? '1' : '0'); redraw(); }
function redraw() { for (const s of shown) build(s); }

function val(v) {
  if (v === null || v === undefined) return '';
  const m = /^(\d{1,3}), (\d{1,3}), (\d{1,3})$/.exec(v);
  return m ? [h('span', {class: 'cs', style: `background:rgb(${m[1]},${m[2]},${m[3]})`}), v] : v;
}

// The old and the new value of a changed text as a changed network title: the words of each, the changed
// ones in a <span> (spaces never; a number with points one word, as page._inline), from a longest common
// subsequence of words, signs and spaces; a colour, a number or a text too long for it whole.
function marked(b, a) {
  const tok = s => s.match(/\d+(?:\.\d+)+|[\p{L}\p{N}_]+|\s+|[^\p{L}\p{N}_\s]/gu) || [];
  if ([b, a].some(v => typeof v !== 'string' || /^\d{1,3}, \d{1,3}, \d{1,3}$/.test(v))) return [val(b), val(a)];
  const tb = tok(b), ta = tok(a), n = tb.length, m = ta.length;
  if (n * m > 250000) return [b, a];
  const L = Array.from({length: n + 1}, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = tb[i] === ta[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const ob = [], oa = [], mark = t => /^\s+$/.test(t) ? t : h('span', {}, t);
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && tb[i] === ta[j]) { ob.push(tb[i++]); oa.push(ta[j++]); }
    else if (j === m || (i < n && L[i + 1][j] >= L[i][j + 1])) ob.push(mark(tb[i++]));
    else oa.push(mark(ta[j++]));
  }
  return [ob, oa];
}

function rect(b) { return `(${b.x}, ${b.y}) ${b.w} x ${b.h}`; }

// What a 'moved' change did to the object's box: [the word for it, the name of its row].
function placeChange(c) {
  const at = c.old.x !== c.new.x || c.old.y !== c.new.y, size = c.old.w !== c.new.w || c.old.h !== c.new.h;
  return at && size ? ['moved and resized', 'Position and size'] : size ? ['resized', 'Size'] : ['moved', 'Position'];
}

function kindText(c) { return c.kind === 'moved' && c.old && c.new ? placeChange(c)[0] : c.kind; }

function used(o, list) {
  return list.flatMap((u, k) => {
    const l = link(o, u.kind, u.name, u.device), dev = u.device && u.device !== o.device ? [' (', u.device, ')'] : [];
    return (k ? [', ', l] : [l]).concat(dev);
  });
}

function changeRow(o, c, view) {
  const rows = [];
  if (c.kind === 'moved') rows.push(c.old && c.new ? [placeChange(c)[1], rect(c.old), rect(c.new)]
    : ['Position and size', c.old && rect(c.old), c.new && rect(c.new)]);
  for (const a of c.attributes || []) if (!a.fold || c.fold) rows.push([a.name, a.old, a.new]);
  for (const t of c.texts || []) rows.push([t.part + (t.culture ? ' [' + t.culture + ']' : ''), t.old, t.new]);
  for (const l of c.links || []) rows.push([l.kind + ' link', l.old, l.new]);
  for (const p of c.parts || []) for (const f of p.facts || []) rows.push([f.path, f.old, f.new]);
  for (const f of c.facts || []) {
    const i = f.indexOf(' = ');
    rows.push(i < 0 ? [f, null, null] : [f.slice(0, i), c.kind === 'removed' ? f.slice(i + 3) : null,
      c.kind === 'added' ? f.slice(i + 3) : null]);
  }
  for (const [k, n] of Object.entries(c.counts || {})) rows.push([k, c.kind === 'removed' ? n : null, c.kind === 'added' ? n : null]);
  const extra = [];
  const folded = c.fold ? 0 : (c.attributes || []).filter(a => a.fold).length;
  if (folded) extra.push(h('div', {class: 'hu'}, `and ${folded} folded attribute${folded === 1 ? '' : 's'}: ` +
    (c.attributes || []).filter(a => a.fold).map(a => a.name).join(', ')));
  if (c.stillUsed) extra.push(h('div', {class: 'hu warn'}, 'Deleted, still used by ', used(o, c.usedAfter)));
  else if (c.usedAfter && c.usedAfter.length) extra.push(h('div', {class: 'hu'}, 'Used by ', used(o, c.usedAfter)));
  else if (c.usedBefore && c.usedBefore.length) extra.push(h('div', {class: 'hu'}, 'Used before by ', used(o, c.usedBefore)));
  const name = c.object === null ? '' : c.object;
  return h('div', {class: 'hc' + (c.kind === 'added' ? ' added' : '') + (c.shut ? ' shut' : ''), 'data-name': name,
    onclick: () => view && select(view, name, false)},
    c.kind === 'added' && rows.length ? h('span', {class: 'ht', onclick: e => {
      e.stopPropagation();
      c.shut = !c.shut;
      e.currentTarget.parentNode.classList.toggle('shut', c.shut);
    }}) : null,
    h('div', {class: 'hw'}, h('span', {class: 'mk ' + CHANGE_CLASS[c.kind]}),
      h('b', {}, c.object === null ? (KIND_TEXT[o.kind] || o.kind) + ' itself' : c.object),
      h('span', {class: 'k'}, c.type), h('span', {class: 'k'}, kindText(c)),
      DRAWN.has(o.kind) && c.object !== null && hiddenNames(o, c.kind === 'removed' ? 'before' : 'after').has(c.object)
        ? h('span', {class: 'k'}, '(on a layer hidden in the editor: not drawn)') : null),
    rows.length ? h('table', {class: 'hd'}, rows.map(x => {
      const has = v => v !== null && v !== undefined;
      const [vb, va] = has(x[1]) && has(x[2]) ? marked(x[1], x[2]) : [val(x[1]), val(x[2])];
      return h('tr', {}, h('td', {class: 'p'}, x[0]), h('td', {class: has(x[1]) ? 'o' : ''}, vb),
        h('td', {class: has(x[2]) ? 'w' : ''}, va));
    })) : null,
    extra);
}

// No change rows (a graphic added, deleted or only moved): no head, as its badge, panes and notes tell what changed.
function changeList(o, view) {
  const all = o.changes || [], shown = all.filter(c => !c.fold), folded = all.filter(c => c.fold);
  const n = shown.length;
  return h('div', {class: 'hcl'}, all.length ? h('div', {class: 'hh'}, n ? n + (n === 1 ? ' change' : ' changes') :
      'Only folded changes') : null,
    shown.map(c => changeRow(o, c, view)),
    folded.length ? h('details', {class: 'hf'}, h('summary', {}, `${folded.length} folded change${folded.length === 1 ? '' : 's'}: ` +
      [...new Set(folded.map(c => FOLD_TEXT[c.fold]))].join('; ')), folded.map(c => changeRow(o, c, view))) : null);
}

function notes(o) {
  const out = [];
  if (o.exportSetting) out.push(h('div', {class: 'hn'}, `Export setting: ${o.exportSetting.before} before, ` +
    `${o.exportSetting.after} after`));
  for (const x of o.exportNoise || []) {
    out.push(h('div', {class: 'hn'}, `${x.name} absent ${x.missing} in ${x.count} object${x.count === 1 ? '' : 's'}: ` +
      'a minimal export leaves out values equal to the default in TIA, so this need not be a change in TIA (folded)'));
  }
  if (o.from) out.push(h('div', {class: 'hn'}, 'Was ', h('b', {}, (o.from.folder ? o.from.folder + '/' : '') + o.from.name)));
  if (o.origin.before !== o.origin.after && o.origin.before && o.origin.after) {
    out.push(h('div', {class: 'hn'}, `Before: ${o.origin.before} document, after: ${o.origin.after} document`));
  }
  if (o.usedBy) {
    const u = o.usedBy.after.length ? o.usedBy.after : o.usedBy.before;
    if (u.length) out.push(h('div', {class: 'hn'}, o.usedBy.after.length ? 'Used by ' : 'Used before by ', used(o, u)));
  }
  if (DRAWN.has(o.kind)) {
    const root = rootOf(present(o, 'after') ? o.adoc : o.bdoc);
    const hid = X.hiddenLayers(root), n = hid.reduce((t, l) => t + l.count, 0);
    if (hid.length) {
      out.push(h('div', {class: 'hn'}, `Layer${hid.length === 1 ? '' : 's'} ` +
        hid.map(l => l.index + (l.name ? ' (' + l.name + ')' : '')).join(', ') +
        ` hidden in the editor: ${n} object${n === 1 ? '' : 's'} not drawn, as in the editor (shown at runtime)`));
    }
  }
  if (o.kind === 'screen') {
    const tb = present(o, 'before') ? templateOf(rootOf(o.bdoc)) : null, ta = present(o, 'after') ? templateOf(rootOf(o.adoc)) : null;
    const t = ta || tb, tpl = t ? find(o, 'template', t) : null;
    if (tpl && tpl.state !== 'same') out.push(h('div', {class: 'hn'}, 'Template ', link(o, 'template', t), ' changed too (drawn faded underneath)'));
  }
  return out;
}

function listTable(o) {
  const root = present(o, 'after') ? rootOf(o.adoc) : null;
  const entries = root ? Array.from(root.getElementsByTagName('Hmi.TextGraphicList.TextListEntry')) : [];
  if (!entries.length) return '';
  return h('table', {class: 'sum hlt'}, h('tr', {}, h('th', {}, 'Value'), h('th', {}, `Text (${M.lang})`)),
    entries.map(e => {
      const t = X.pickCulture(X.texts(e, ['Text']), M.lang), from = X.attr(e, 'From', ''), to = X.attr(e, 'To', from);
      return h('tr', {}, h('td', {}, from === to ? from : from + '..' + to), h('td', {}, t ? t.join(' / ') : ''));
    }));
}

// A graphic: its image before | after (or "no image" when the export has none: exported before the bridge kept them).
function images(o) {
  const one = side => {
    const id = side === 'before' ? o.bimg : o.aimg;
    const lab = h('div', {class: 'hl'}, h('b', {}, side === 'before' ? 'Before' : 'After'), label(o, side));
    return h('div', {class: 'hp ' + side}, lab, present(o, side) && id
      ? h('div', {class: 'hb hg'}, h('img', {src: M.docs[id], alt: o.name}))
      : h('div', {class: 'empty'}, present(o, side) ? 'no image in the export, or one a browser cannot draw (EMF, WMF)' : side === 'before' ? 'not there before' : 'deleted'));
  };
  return h('div', {class: 'hps side'}, one('before'), one('after'));
}

function build(sec) {
  const o = M.objects[+sec.getAttribute('data-o')], hv = sec.querySelector('.hv');
  const view = {o, hv, sel: hv.view ? hv.view.sel : null};
  hv.view = view;
  if (!DRAWN.has(o.kind)) {
    hv.replaceChildren(...notes(o), o.kind === 'graphic' ? images(o) : '',
      o.state === 'same' ? h('div', {class: 'hn'}, 'Unchanged.') : changeList(o, null),
      o.kind === 'textlist' ? listTable(o) : '');
    hv.setAttribute('data-drawn', '1');
    return;
  }
  const mode = r.classList.contains('flat') || !r.classList.contains('one') ? 'side' : ui.mode;
  const panes = h('div', {class: 'hps ' + mode + (ui.fit ? ' fit' : '')}, pane(o, 'before', view), pane(o, 'after', view));
  if (mode === 'toggle') {
    const showing = present(o, ui.show) ? ui.show : ui.show === 'after' ? 'before' : 'after';
    panes.querySelector('.hp.' + (showing === 'after' ? 'before' : 'after')).classList.add('hide');
  }
  sync(panes);
  hv.replaceChildren(r.classList.contains('one') ? toolbar() : '', ...notes(o), panes,
    o.state === 'same' ? '' : changeList(o, view));
  hv.setAttribute('data-drawn', '1');
  if (view.sel !== null) select(view, view.sel, false);
}

// 1:1: the panes scroll in step, led by the one scrolled.
function sync(panes) {
  let lead = null;
  for (const b of panes.querySelectorAll('.hb')) {
    b.addEventListener('pointerenter', () => { lead = b; });
    b.addEventListener('scroll', () => {
      if (lead && lead !== b) return;
      for (const o of panes.querySelectorAll('.hb')) if (o !== b) { o.scrollLeft = b.scrollLeft; o.scrollTop = b.scrollTop; }
    });
  }
}

// Mark an object in both screens and its change in the list; the rest dims.
function select(view, name, fromScreen) {
  view.sel = name;
  const hv = view.hv;
  for (const e of hv.querySelectorAll('.dl rect, .dl circle')) e.classList.toggle('sel', e.getAttribute('data-name') === name);
  for (const e of hv.querySelectorAll('.dl')) e.classList.toggle('dim', name !== null);
  for (const e of hv.querySelectorAll('svg .obj')) e.classList.toggle('sel', e.dataset.name === name && e.dataset.source !== 'template');
  let row = null;
  for (const e of hv.querySelectorAll('.hc')) {
    const on = e.getAttribute('data-name') === name;
    e.classList.toggle('sel', on);
    if (on && !row) row = e;
  }
  if (fromScreen && row) row.scrollIntoView({block: 'nearest'});
  if (!fromScreen && !ui.fit) {
    const e = hv.querySelector('.hp.after .dl rect.sel') || hv.querySelector('.dl rect.sel');
    if (e) e.scrollIntoView({block: 'center', inline: 'center'});
  }
}

// --- when to draw ---------------------------------------------------------------------------------------------

function open(sec) {
  if (shown.has(sec)) return;
  shown.add(sec);
  build(sec);
}

function current() { return r.querySelector('section.blk.hmi.on'); }

// C / E: the rows of the added objects of the object on show. The state stays on each change, as a click on its
// triangle sets it: a redraw builds the list anew.
function shutAdded(v) {
  const s = current();
  for (const c of M.objects[+s.getAttribute('data-o')].changes || []) if (c.kind === 'added') c.shut = v;
  for (const e of s.querySelectorAll('.hc.added')) e.classList.toggle('shut', v);
}

async function main() {
  M = await decode();
  for (const o of M.objects) BY.set(id3(o.part, o.device, o.kind, o.name), o);
  const secs = Array.from(r.querySelectorAll('section.blk.hmi'));
  if (!r.classList.contains('one')) secs.forEach(open);
  else {
    const mo = new MutationObserver(() => { const s = current(); if (s) open(s); });
    secs.forEach(s => mo.observe(s, {attributes: true, attributeFilter: ['class']}));
    const s = current();
    if (s) open(s);
    window.addEventListener('beforeprint', () => secs.forEach(open));
  }
  r.setAttribute('data-hmi', 'ready');
}

if (r.ldiffKey) {
  const on = () => !!current();
  // Before the rail's C and E (4, 5), which fold the networks of a block: the first key that applies runs.
  r.ldiffKey({o: 3.5, show: 'C', text: 'HMI: collapse the rows of the added objects', keys: ['c'], when: on,
    run: () => shutAdded(true)});
  r.ldiffKey({o: 3.6, show: 'E', text: 'HMI: expand the rows of the added objects', keys: ['e'], when: on,
    run: () => shutAdded(false)});
  r.ldiffKey({o: 13, show: 'L', text: 'HMI: side by side, stacked or toggle', keys: ['l'], when: on,
    run: () => setMode(LAYOUTS[(LAYOUTS.indexOf(ui.mode) + 1) % LAYOUTS.length])});
  r.ldiffKey({o: 14, show: 'Z', text: 'HMI: fit to the pane or 1:1', keys: ['z'], when: on, run: () => setFit(!ui.fit)});
  r.ldiffKey({o: 16, show: 'O', text: 'HMI: change outlines on or off', keys: ['o'], when: on, run: () => setLines(!ui.lines)});
  r.ldiffKey({o: 15, show: 'Space', text: 'HMI, toggle layout: before or after', keys: [' '],
    when: () => on() && ui.mode === 'toggle', run: () => { ui.show = ui.show === 'after' ? 'before' : 'after'; build(current()); }});
}
main();
})();
