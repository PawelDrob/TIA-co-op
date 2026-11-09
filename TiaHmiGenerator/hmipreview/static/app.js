// HMI preview browser app: project tree, header, run mode, inspect mode, findings, planned items, event log, live
// reload.
//
// The project tree is the change report's (rail.js, markup from /api/tree) over every HMI device, the
// header holds the view, the modes, the diff, the device's panel and start screen, the live state and the findings
// count. A view is {device, kind, name}: the endpoints answer for its device (?device=), the header follows it.
// The event log is a strip along the bottom in Run mode, newest first, each entry a sentence.
// The findings and the open planned items of every device in a list below the screen (findings.js), as
// the change report lists its changes below the screen; the count in the header scrolls to it; objects with
// findings carry a corner mark in Inspect mode.
// The panel on the right shows the selected object laid out like TIA's Properties window (props.js, from
// the catalogue); with nothing selected the diff's change list while the diff is on, else the view's own properties.
//
// URL hooks (also used by the headless tests, Tests/browser.py):
//   ?screen=<name> | ?popup=<name> | ?template=<name> | ?textlist=<name>   view to open (default: the start screen)
//   ?device=<folder> the HMI device of that view (default: the server's)
//   ?live=0          no change stream (headless --dump-dom waits for open connections)
//   ?live=once       change stream closed after the first change (live reload test)
//   ?click=<obj>,..  run-mode press, release and click on each object in turn, after the first draw
//   ?keys=<key>,..   keys pressed in turn after the clicks, as on the keyboard (key names: i, r, l, f, c, e)
//   ?inspect=<obj>   opens in inspect mode, with that object selected
//   ?prop=<text>     the search over the property names of the panel (props.js)
//   ?change=<obj>    a click on that object's line in the diff's change list, once the list shows it
//   ?fit=1           zoom to fit;   ?lang=<culture> text culture (default en-US, else the first in the text)
//   ?png=1           screen only at 0, 0 (no sidebar, no view bar): python -m hmipreview png shoots this page
//   ?diff=commit|export  diff toggle preset (diff.js)
//   ?finding=<obj>   a click on the first finding of that object in the findings list, after the other hooks
// <html data-ready="1"> is set once the page is drawn and the hooks have run.
//
// Extension API for the diff (diff.js): window.hmiPreview, see the bottom of this file.
'use strict';
import * as X from './simaticml.js';
import * as R from './render.js';
import * as F from './findings.js';
import * as P from './props.js';
import {el} from './props.js';

const params = new URLSearchParams(location.search);
const LANG = params.get('lang') || 'en-US';
const $ = id => document.getElementById(id);

const KINDS = ['screen', 'popup', 'template', 'textlist'];
const KIND_TEXT = F.KIND_TEXT;
const LOOKUP = 'Lookup screens, pop-ups, templates, text lists';
const FOLDS = 'hmipreview-shut';     // localStorage: the closed folders of the tree (their paths)
const EVENTS = 'hmipreview-events';  // localStorage: 'shut' while the event log is closed

const state = {
  tree: null,            // /api/tree (without the markup)
  device: params.get('device') || '',  // the device folder of the view ('' one-device layout or the server's)
  against: ['commit', 'export'].includes(params.get('diff')) ? params.get('diff') : 'off',  // the diff (diff.js); the
                                                                                         // tree's marks follow it
  list: null,            // /api/screens of the device
  findings: [],          // /api/findings of every device
  findingsPage: null,    // /api/findingspage: the findings list below the screen, every device
  handbuilt: [],         // /api/handbuilt of the device
  pictures: {},          // /api/pictures: graphic name -> URL of its image
  typenames: {},         // /api/typenames: export element -> toolbox name ('Hmi.Screen.IOField' -> 'I/O field')
  view: null,            // {device, kind, name}
  history: [],           // previous views (ActivatePreviousScreen)
  popups: [],            // open pop-ups [{name, x, y}]
  mode: 'run',
  fit: params.get('fit') === '1',
  selected: null,        // {source, name}
  drawn: null,           // {doc, root, template, popups: [{name, doc}], objects: [info]}
  catalogue: {},         // element -> its /api/catalogue entry, or null when the catalogue does not know it
};
const listeners = {render: [], refresh: []};
let busy = Promise.resolve();

function enqueue(fn) {
  busy = busy.then(fn).catch(err => logEntry('Error: ' + (err && err.message || err), 'missing'));
  return busy;
}

function emit(name, arg) {
  for (const fn of listeners[name]) {
    try { fn(arg); } catch (err) { console.error(err); }
  }
}

async function getJson(url) {
  const r = await fetch(url, {cache: 'no-store'});
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(url + ': HTTP ' + r.status);
  return r.json();
}

// The query of an endpoint for the device of the view: ?device= when the repo has device folders.
function q(args) {
  const p = new URLSearchParams(args || {});
  if (state.device) p.set('device', state.device);
  return '?' + p;
}

function fetchDoc(kind, name) {
  return getJson('/api/document' + q({kind, name}));
}

// --- data, project tree, header, panels -----------------------------------------------------------------------

// Everything of the repo the page shows: the tree (all devices, marks of the diff), the device's lists, planned
// items and hand-built objects, the findings of every device.
async function refreshData() {
  await refreshTree();
  await refreshDevice();
}

async function refreshDevice() {
  const devices = state.tree && state.tree.devices.length ? state.tree.devices : [state.device];
  const [list, page, handbuilt, pictures, ...findings] = await Promise.all([
    getJson('/api/screens' + q()), getJson('/api/findingspage'), getJson('/api/handbuilt' + q()),
    getJson('/api/pictures'),
    ...devices.map(d => getJson('/api/findings' + (d ? '?' + new URLSearchParams({device: d}) : '')))]);
  Object.assign(state, {list, findingsPage: page, handbuilt: handbuilt || [], pictures: pictures || {},
    findings: [].concat(...findings.map(f => f || []))});
  drawHeader();
  drawFindings();
}

function entryOf(kind, name) {
  if (!state.list) return null;
  const lists = {screen: state.list.screens, popup: state.list.popups, template: state.list.templates,
    textlist: state.list.textlists};
  return (lists[kind] || []).find(e => e.name === name) || null;
}

function railRoot() {
  return $('app');
}

function folderPath(li) {
  const parts = [];
  for (let p = li; p && p.classList && p.classList.contains('fd'); p = p.parentElement.closest('li.fd')) {
    parts.unshift(p.firstElementChild.querySelector('.nm').textContent);
  }
  return parts.join('/');
}

function keptFolds() {
  try { return new Set(JSON.parse(localStorage.getItem(FOLDS) || '[]')); } catch (err) { return new Set(); }
}

function keepFolds(tree) {
  const shut = [...tree.querySelectorAll('li.fd.shut')].map(folderPath);
  try { localStorage.setItem(FOLDS, JSON.stringify(shut)); } catch (err) { /* private window */ }
}

function applyFolds(tree, shut) {
  for (const li of tree.querySelectorAll('li.fd')) li.classList.toggle('shut', shut.has(folderPath(li)));
}

function viewOf(a) {
  return {device: a.getAttribute('data-device') || '', kind: a.getAttribute('data-kind'), name: a.getAttribute('data-name')};
}

// The project tree: the rail's markup from /api/tree, the rail's script (rail.js) run once on it; later answers
// replace the tree's items (the closed folders and the search kept). Not in ?png=1.
async function refreshTree() {
  if (params.get('png') === '1') return;
  const data = await getJson('/api/tree?' + new URLSearchParams({against: state.against}));
  const root = railRoot();
  const box = document.createElement('div');
  box.innerHTML = data.rail;
  const fresh = box.firstElementChild;
  let tree = root.querySelector('.rail .tree');
  if (!tree) {
    box.insertAdjacentHTML('beforeend', data.launcher);
    root.insertBefore(fresh, root.firstChild);
    root.append(box.lastElementChild);
    tree = fresh.querySelector('.tree');
    applyFolds(tree, keptFolds());
    window.ldiffRail(root, {go: a => enqueue(() => navigate(viewOf(a), true)), lookup: LOOKUP});
    fresh.addEventListener('click', ev => { if (ev.target.closest('.fn')) keepFolds(tree); });
    addKeys(root);
  } else {
    const shut = new Set([...tree.querySelectorAll('li.fd.shut')].map(folderPath));
    tree.innerHTML = fresh.querySelector('.tree').innerHTML;
    applyFolds(tree, shut);
    root.ldiffReindex();
  }
  if (!state.device && data.device) state.device = data.device;
  state.tree = {devices: data.devices, device: data.device, against: data.against};
  markTree();
}

// The open view's entry in the tree: selected, its folders open.
function markTree() {
  const root = railRoot(), v = state.view;
  if (!root.ldiffSelect || !v) return;
  for (const a of root.querySelectorAll('.rail .tree a.obj')) {
    const w = viewOf(a);
    if (w.kind === v.kind && w.name === v.name && w.device === v.device) {
      root.ldiffSelect(a);
      return;
    }
  }
}

function addKeys(root) {
  const key = (o, show, text, keys, run) => root.ldiffKey({o, show, text, keys, run});
  key(20, 'R', 'Run mode: click buttons as on the panel', ['r'], () => setMode('run'));
  key(21, 'I', 'Inspect mode: click an object to see it', ['i'], () => setMode('inspect'));
  key(22, 'F', '1:1 or fit to the window', ['f'], () => $('zoom').click());
  key(23, 'D', 'Diff off or against the last commit', ['d'], () => { if (api.toggleDiff) api.toggleDiff(); });
  key(24, 'Backspace', 'Back (ActivatePreviousScreen)', ['Backspace'], () => $('back').click());
  key(25, 'L', 'Show or hide the event log', ['l'], () => { if (state.mode === 'run') $('events-toggle').click(); });
  key(26, 'C', 'Findings: collapse every box and fold', ['c'], () => F.foldAll($('findings'), true));
  key(27, 'E', 'Findings: expand every box and fold', ['e'], () => F.foldAll($('findings'), false));
}

function panelText(p) {
  return `${p.panel || p.orderNumber || 'Panel'} ${p.width} x ${p.height}${p.portrait ? ' portrait' : ''}`;
}

function drawHeader() {
  const d = state.list && state.list.device;
  const dev = $('device');
  dev.className = d && d.hardware ? 'mismatch' : '';
  if (d) {
    dev.textContent = panelText(d) + (d.hardware ? ' (TIA: ' + panelText(d.hardware) + ')' : '');
    dev.title = (d.declared ? 'Declared in panel.json' : 'The HMI device in TIA') +
      (d.hardware ? '; the HMI device in TIA is a ' + panelText(d.hardware) + ' (resolution.mismatch)' : '');
  } else {
    dev.textContent = 'Panel unknown';
    dev.title = 'Declare it: python -m hmipreview panel; drawn at the screen size';
  }
  $('start-screen').textContent = state.list && state.list.startScreen || '';
  const errors = state.findings.filter(f => f.severity === 'error').length;
  const warnings = state.findings.length - errors;
  const n = (k, w) => k + ' ' + w + (k === 1 ? '' : 's');
  const fc = $('findings-count');
  fc.textContent = !state.findings.length ? 'No findings'
    : [errors ? n(errors, 'error') : '', warnings ? n(warnings, 'warning') : ''].filter(Boolean).join(', ');
  fc.className = 'fc' + (errors ? ' error' : warnings ? ' warning' : '');
  fc.setAttribute('data-errors', errors);
  fc.setAttribute('data-warnings', warnings);
}

// --- findings list below the screen (findings.js) ---------------------------------------------------------------

function drawFindings() {
  F.draw($('findings'), state.findingsPage, openFinding);
  markFindingRows();
}

// The rows of the object selected on the screen, marked in the list.
function markFindingRows() {
  const doc = state.drawn && state.drawn.doc;
  F.select($('findings'), doc ? {device: state.device, path: doc.path} : null, state.selected ? state.selected.name : null);
}

// A click on a finding or on a user of a planned item: its document, Inspect mode, the object of that document
// selected (not one of the same name in the template or a pop-up), the screen in sight again (the list lies below).
function openFinding(view, object) {
  return enqueue(async () => {
    const v = state.view;
    if (!v || v.kind !== view.kind || v.name !== view.name || (view.device || '') !== state.device) {
      await navigate(view, true);
    }
    if (object) {
      setMode('inspect');
      selectByName(object, view.kind);
    }
    $('main').scrollTop = 0;
  });
}

function scrollToFindings() {
  $('main').scrollTop = $('findings').offsetTop - $('main').offsetTop;
}

// Inspect mode: a corner in the colour of its worst finding on each object with findings (hidden in Run mode, which
// looks as the panel).
function drawFindingMarks(objects) {
  const fl = layer($('screen'), 'layer-findings');
  for (const o of objects) {
    const found = (o.doc.findings || []).filter(f => f.object === o.name);
    if (!found.length) continue;
    const sev = found.some(f => f.severity === 'error') ? 'error' : 'warning';
    const [dx, dy] = o.offset || [0, 0];
    // in the screen when the object reaches outside it (geometry.outside)
    const svg = $('screen'), sw = Number(svg.getAttribute('width')) || Infinity;
    const sh = Number(svg.getAttribute('height')) || Infinity, s = Math.min(12, o.box.w, o.box.h) || 12;
    const x = Math.max(s, Math.min(o.box.x + o.box.w + dx, sw)), y = Math.max(0, Math.min(o.box.y + dy, sh - s));
    R.svgEl('path', {class: 'finding-mark ' + sev, 'data-name': o.name, 'data-source': o.source,
      d: `M${x - s},${y} h${s} v${s} z`}, fl);
  }
}

// --- event log ------------------------------------------------------------------------------------------------

// An entry is a sentence, "<who>, <event>: <what it does>", put on top (newest first). Nothing is scrolled into view
// and the strip keeps its height, so nothing on the page moves when it logs. data: the entry's data-* attributes.
function logEntry(say, cls, data) {
  const li = el('li', null, 'log-entry ' + (cls || ''), data);
  li.append(el('time', new Date().toLocaleTimeString()), el('span', say, 'say'));
  const log = $('event-log');
  log.prepend(li);
  $('events-n').textContent = log.children.length;
  $('events-last').textContent = say;
}

function clearLog() {
  $('event-log').replaceChildren();
  $('events-n').textContent = '';
  $('events-last').textContent = '';
}

function setLogClosed(shut) {
  $('events').classList.toggle('shut', shut);
  try { localStorage.setItem(EVENTS, shut ? 'shut' : 'open'); } catch (err) { /* private window */ }
  if (state.fit) applyZoom();
}

function logClosedBefore() {
  try { return localStorage.getItem(EVENTS) === 'shut'; } catch (err) { return false; }
}

// Where a function comes from, for the log: {who, event, object}: "Button btnSilo", "Click", "btnSilo". The object
// is named as TIA does, by its toolbox name ("I/O field ioSpeed").
function sourceOf(info, event) {
  return {who: `${state.typenames[info.it.type] || X.shortType(info.it.type)} ${info.name}`, event, object: info.name};
}

// One entry for a function of an event: "<who>, <event>: <what>".
function logFunction(src, fn, what, cls) {
  logEntry(`${src.who}${src.event ? ', ' + src.event : ''}: ${what}`, cls,
    {'data-function': fn.name, 'data-object': src.object, 'data-event': src.event});
}

function paramText(p) {
  return p.self ? '(own)' : p.link !== null ? p.link : p.value;
}

// What a function the preview does not run would do, as a sentence.
function would(fn) {
  const tagParam = param(fn, 'Tag') || fn.params.find(p => p.link !== null);
  const tag = tagParam && tagParam.link !== null ? 'tag ' + tagParam.link : null;
  const valueParam = param(fn, 'Value'), bitParam = param(fn, 'Bit');
  const value = valueParam ? paramText(valueParam) : null;
  const bit = bitParam ? bitParam.value : null;
  switch (fn.name) {
    case 'SetTag': if (tag && value !== null) return `would set ${tag} to ${value}`; break;
    case 'SetBit': if (tag) return `would set ${tag} to 1`; break;
    case 'ResetBit': if (tag) return `would set ${tag} to 0`; break;
    case 'InvertBit': if (tag) return `would invert ${tag}`; break;
    case 'IncreaseTag': if (tag && value !== null) return `would add ${value} to ${tag}`; break;
    case 'DecreaseTag': if (tag && value !== null) return `would subtract ${value} from ${tag}`; break;
    case 'SetBitWhileKeyPressed':
      if (bit !== null) return `would set bit ${bit}${tag ? ' of ' + tag : ''} while pressed`;
      break;
  }
  return 'would call ' + fn.name +
    (fn.params.length ? ' with ' + fn.params.map(p => `${p.name} = ${paramText(p)}`).join(', ') : '');
}

// --- drawing --------------------------------------------------------------------------------------------------

// Canvas size: the device resolution for screens and templates; else the document's own Width x Height. A document
// without them (incomplete; the validator reports it) and the "not found" page get the CANVAS size, which is the
// size of the drawing area only, not a value of the document.
const CANVAS = [1280, 800];

function screenSize(kind, root) {
  const d = state.list && state.list.device;
  if (kind !== 'popup' && d) return [d.width, d.height];
  const w = root ? X.num(root, 'Width') : undefined, h = root ? X.num(root, 'Height') : undefined;
  return w !== undefined && h !== undefined ? [w, h] : CANVAS;
}

function layer(svg, cls, attrs) {
  return R.svgEl('g', Object.assign({class: 'layer ' + cls}, attrs || {}), svg);
}

// Text lists the objects under root link, added to into as {name: {culture: [lines]}} of the entry for 0
// (render.js draws symbolic I/O fields with it). Lists not in the repo stay out.
async function addTextlists(into, ...roots) {
  const names = new Set();
  for (const root of roots) {
    if (!root) continue;
    for (const l of root.getElementsByTagName('TextList')) {
      const n = l.parentElement && l.parentElement.tagName === 'LinkList' ? X.child(l, 'Name') : null;
      if (n && n.textContent && !(n.textContent in into)) names.add(n.textContent);
    }
  }
  await Promise.all([...names].map(async name => {
    const d = await fetchDoc('textlist', name);
    const entry = d ? X.textListEntry(X.rootObject(X.parseXml(d.xml)), 0) : null;
    if (entry) into[name] = entry;
  }));
}

function plannedNames(doc) {
  return new Set((doc.links || []).filter(l => l.state === 'planned' && l.object).map(l => l.object));
}

// A text list: its entries as a table, value (From, or From..To) and text in the culture of ?lang= (else the first).
function drawTextlist(root) {
  const rows = [...root.getElementsByTagName('Hmi.TextGraphicList.TextListEntry')].map(e => {
    const from = X.attr(e, 'From'), to = X.attr(e, 'To');
    const lines = X.pickCulture(X.texts(e, ['Text']), LANG);
    return [from === to || to === undefined ? from : `${from}..${to}`, lines ? lines.join(' / ') : ''];
  });
  const t = el('table');
  const head = el('tr');
  head.append(el('th', 'Value'), el('th', 'Text (' + LANG + ')'));
  t.append(head);
  for (const [value, text] of rows) {
    const tr = el('tr', null, 'entry', {'data-value': value});
    tr.append(el('td', value), el('td', text));
    t.append(tr);
  }
  $('textlist').replaceChildren(t);
  $('textlist').hidden = false;
}

// The catalogue entries of the elements, fetched once each (props.js lays the panel out by them).
async function loadCatalogue(elements) {
  const missing = [...new Set(elements)].filter(e => e && !(e in state.catalogue));
  const got = await Promise.all(missing.map(e => getJson('/api/catalogue?' + new URLSearchParams({element: e}))));
  missing.forEach((e, i) => { state.catalogue[e] = got[i]; });
}

async function draw() {
  const svg = $('screen');
  svg.replaceChildren();
  R.defs(svg);
  const v = state.view;
  $('notice').textContent = '';
  $('origin').textContent = '';
  $('origin').className = '';
  $('origin').title = '';
  const objects = [];
  state.drawn = {doc: null, template: null, popups: [], objects};
  if (!v) {
    svg.setAttribute('data-state', 'empty');
    $('view-title').textContent = 'No screens in this project';
    finishDraw(svg);
    return;
  }
  $('view-title').textContent = `${v.kind === 'screen' ? '' : KIND_TEXT[v.kind] + ' '}${v.name}`;
  $('view-device').textContent = state.tree && state.tree.devices.length ? v.device : '';
  $('textlist').hidden = true;
  svg.setAttribute('data-screen', v.name);
  svg.setAttribute('data-kind', v.kind);
  const doc = await fetchDoc(v.kind, v.name);
  if (!doc) {
    const [w, h] = screenSize('screen', null);
    setSize(svg, w, h);
    svg.setAttribute('data-state', 'not-found');
    svg.removeAttribute('data-origin');
    const t = R.svgEl('text', {class: 'not-found-text', x: w / 2, y: h / 2, 'text-anchor': 'middle'}, svg);
    t.textContent = `${v.kind === 'popup' ? 'Pop-up' : v.kind === 'screen' ? 'Screen' : KIND_TEXT[v.kind]} not found: ${v.name}`;
    $('notice').textContent = t.textContent;
    finishDraw(svg);
    return;
  }
  state.drawn.doc = doc;
  const root = X.rootObject(X.parseXml(doc.xml));
  state.drawn.root = root;
  svg.setAttribute('data-origin', doc.origin);
  // Where the document comes from, in the maintainer's words: Exported (from TIA) or Generated
  const origin = $('origin');
  if (doc.origin === 'tia') {
    origin.textContent = 'Exported';
    origin.className = 'tia';
    origin.title = 'Exported from TIA, read-only: ' + doc.path;
  } else {
    origin.textContent = 'Generated';
    origin.className = 'generated';
    origin.title = (doc.replaces ? 'Generated, replaces the TIA export at import: ' : 'Generated, not in TIA yet: ') +
      doc.path;
  }
  if (v.kind === 'textlist') {
    drawTextlist(root);
    svg.setAttribute('data-state', 'textlist');
    finishDraw(svg);
    return;
  }
  const [w, h] = screenSize(v.kind, root);
  setSize(svg, w, h);
  svg.setAttribute('data-state', 'ok');
  R.svgEl('rect', {class: 'screen-bg', x: 0, y: 0, width: w, height: h,
    fill: R.rootFill(root)}, svg);

  const register = (source, docJson, extra) => (g, it, box) => {
    const info = Object.assign({g, it, box, source, doc: docJson, name: it.name}, extra || {});
    if (X.events(it.el).length) g.classList.add('has-events');
    objects.push(info);
  };

  // Template under the screen
  const tplName = v.kind === 'screen' ? (X.links(root).find(l => l.kind === 'Template') || {}).name : null;
  const handbuiltFor = new Set([v.name]);
  const notices = [];
  const textlists = {};
  const picture = n => state.pictures[n] || null;
  const tdoc = tplName ? await fetchDoc('template', tplName) : null;
  const troot = tdoc ? X.rootObject(X.parseXml(tdoc.xml)) : null;
  await addTextlists(textlists, root, troot);
  if (tdoc) {
    state.drawn.template = tdoc;
    handbuiltFor.add(tplName);
    const tl = layer(svg, 'layer-template', {'data-template': tplName, opacity: R.TEMPLATE_OPACITY});
    R.drawItems(tl, X.screenItems(troot), {lang: LANG, source: 'template', textlists, picture, planned: plannedNames(tdoc),
      register: register('template', tdoc)});
  } else if (tplName) {
    notices.push('Template not found: ' + tplName);
  }
  const sl = layer(svg, 'layer-' + v.kind);
  R.drawItems(sl, X.screenItems(root),
    {lang: LANG, source: v.kind, textlists, picture, planned: plannedNames(doc), register: register(v.kind, doc)});
  R.drawHandbuilt(layer(svg, 'layer-handbuilt'), state.handbuilt.filter(e => handbuiltFor.has(e.screen)));

  // Open pop-ups at their coordinates
  const pl = layer(svg, 'layer-popups');
  for (const p of [...state.popups]) {
    const pdoc = await fetchDoc('popup', p.name);
    if (!pdoc) {
      notices.push('Pop-up not found: ' + p.name);
      state.popups = state.popups.filter(q => q !== p);
      continue;
    }
    const proot = X.rootObject(X.parseXml(pdoc.xml));
    await addTextlists(textlists, proot);
    const pg = R.svgEl('g', {class: 'popup', 'data-popup': p.name, transform: `translate(${p.x},${p.y})`}, pl);
    const [pw, ph] = [X.num(proot, 'Width'), X.num(proot, 'Height')];
    if (pw === undefined || ph === undefined) notices.push('Pop-up ' + p.name + ' has no Width / Height');
    R.svgEl('rect', {class: 'popup-frame', x: 0, y: 0, width: pw || 0, height: ph || 0, fill: R.rootFill(proot)}, pg);
    R.drawItems(pg, X.screenItems(proot), {lang: LANG, source: 'popup', textlists, picture, planned: plannedNames(pdoc),
      register: register('popup', pdoc, {popup: p.name, offset: [p.x, p.y]})});
    state.drawn.popups.push({name: p.name, doc: pdoc});
  }
  drawFindingMarks(objects);
  layer(svg, 'layer-overlay', {id: 'overlay-layer'});
  layer(svg, 'layer-diff', {id: 'diff-layer'});          // diff.js draws its outlines here
  $('notice').textContent = notices.join('; ');
  await loadCatalogue([root.tagName, ...objects.map(o => o.it.type)]);
  finishDraw(svg);
}

function finishDraw(svg) {
  applyZoom();
  if (state.mode === 'inspect') drawOverlaps();
  if (state.selected) {                                 // the object again, or none when a reload removed it
    const info = topmost(state.selected.name, state.selected.source);
    if (info) select(info); else unselect();
  }
  markFindingRows();
  drawSide();
  markTree();
  emit('render', api.view);
}

function setSize(svg, w, h) {
  svg.setAttribute('width', w);
  svg.setAttribute('height', h);
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('data-width', w);
  svg.setAttribute('data-height', h);
}

function applyZoom() {
  const svg = $('screen');
  const w = Number(svg.getAttribute('width')) || 1, h = Number(svg.getAttribute('height')) || 1;
  if (state.fit) {
    // the canvas is as high as the screen in it, at most the view; the findings list lies below
    const c = $('canvas'), m = $('main');
    const s = Math.min((c.clientWidth - 24) / w, (m.clientHeight - 24) / h) || 1;
    svg.style.width = Math.max(1, w * s) + 'px';
    svg.style.height = Math.max(1, h * s) + 'px';
    svg.setAttribute('data-zoom', 'fit');
  } else {
    svg.style.width = w + 'px';
    svg.style.height = h + 'px';
    svg.setAttribute('data-zoom', '1');
  }
  $('zoom').classList.toggle('active', state.fit);
}

// --- navigation and run mode ----------------------------------------------------------------------------------

function updateUrl() {
  const q = new URLSearchParams();
  if (state.view && state.device && state.tree && state.tree.devices.length) q.set('device', state.device);
  if (state.view) q.set(state.view.kind, state.view.name);
  for (const k of ['live', 'lang']) if (params.has(k)) q.set(k, params.get(k));
  history.replaceState(null, '', '?' + q);
}

// view {device, kind, name}; a view of another device first loads that device's lists (the header follows).
async function navigate(view, push) {
  if (push && state.view) state.history.push(state.view);
  if (view && view.device !== undefined && view.device !== state.device) {
    state.device = view.device;
    await refreshDevice();
  }
  if (view) view = Object.assign({}, view, {device: state.device});
  state.view = view;
  state.popups = [];
  unselect();
  await draw();
  updateUrl();
  logScreenEvents();
}

// The screen's own events (Loaded) as the panel fires them: in Run mode only, as every event.
function logScreenEvents() {
  const doc = state.drawn && state.drawn.doc;
  if (!doc || state.mode !== 'run') return;
  const v = state.view;
  for (const ev of X.events(X.rootObject(X.parseXml(doc.xml)))) {
    const src = {who: `${KIND_TEXT[v.kind]} ${v.name}`, event: ev.name, object: v.name};
    for (const fn of ev.functions) logFunction(src, fn, would(fn));
  }
}

function param(fn, name, index) {
  return fn.params.find(p => p.name === name) || fn.params[index] || null;
}

// Run a function of an event. src: where it comes from, for the log (sourceOf); popup: the pop-up the object is on.
async function exec(fn, src, popup) {
  const log = (what, cls) => logFunction(src, fn, what, cls);
  const missing = ', not in the project';
  switch (fn.name) {
    case 'ActivateScreen': {
      const p = param(fn, 'Screen name', 0);
      const name = p && p.self ? state.view.name : p && p.link;
      if (!name) { log('open a screen, but none is set', 'missing'); return; }
      const exists = !!entryOf('screen', name);
      log(`open screen ${name}${exists ? '' : missing}`, exists ? 'nav' : 'missing');
      await navigate({kind: 'screen', name}, true);
      return;
    }
    case 'ActivatePreviousScreen': {
      const prev = state.history.pop();
      if (!prev) { log('back, but there is no previous screen', 'missing'); return; }
      log(`back to ${KIND_TEXT[prev.kind].toLowerCase()} ${prev.name}`, 'nav');
      await navigate(prev, false);
      return;
    }
    case 'ShowPopupScreen': {
      const p = param(fn, 'Name of the screen', 0);
      const name = p && p.self ? popup : p && p.link;
      if (!name) { log('open a pop-up, but none is set', 'missing'); return; }
      const num = (n, i, d) => { const q = param(fn, n, i); const v = q ? Number(q.value) : NaN; return Number.isFinite(v) ? v : d; };
      const x = num('X coordinate', 1, 0), y = num('Y coordinate', 2, 0), mode = num('Display mode', 3, -1);
      const open = state.popups.find(q => q.name === name);
      const exists = !!entryOf('popup', name);
      let what;
      if (mode === 0 || (mode === -1 && open)) {
        state.popups = state.popups.filter(q => q.name !== name);
        what = `close pop-up ${name}`;
      } else {
        state.popups = state.popups.filter(q => q.name !== name).concat([{name, x, y}]);
        what = `open pop-up ${name} at ${x}, ${y}`;
      }
      log(what + (exists ? '' : missing), exists ? 'nav' : 'missing');
      await draw();
      return;
    }
    default:
      log(would(fn));
  }
}

async function runEvent(info, evName) {
  const src = sourceOf(info, evName);
  for (const ev of X.events(info.it.el)) {
    if (ev.name !== evName) continue;
    for (const fn of ev.functions) {
      await exec(fn, src, info.popup);
      if (!info.g.isConnected) return;          // the screen changed under the object
    }
  }
}

function infoOf(target) {
  const g = target && target.closest ? target.closest('.obj') : null;
  if (!g || !state.drawn) return null;
  return state.drawn.objects.find(o => o.g === g) || null;
}

function onPointer(evName) {
  return ev => {
    const info = infoOf(ev.target);
    if (state.mode === 'run') { if (info) enqueue(() => runEvent(info, evName)); }
    else if (evName === 'Click') { if (info) select(info); else if (state.selected) unselect(); }
  };
}

// Run-mode press, release and click on an object, as a click with the mouse (hook ?click=).
async function clickObject(name) {
  const info = topmost(name);
  if (!info) { logEntry(`Click on ${name}: no such object on this screen`, 'missing'); return; }
  for (const type of ['mousedown', 'mouseup', 'click']) {
    if (!info.g.isConnected) break;
    info.g.dispatchEvent(new MouseEvent(type, {bubbles: true}));
    await busy;
  }
}

function topmost(name, source) {
  const objs = state.drawn ? state.drawn.objects : [];
  for (let i = objs.length - 1; i >= 0; i--) {
    if (objs[i].name === name && (!source || objs[i].source === source)) return objs[i];
  }
  return null;
}

// --- inspect mode ---------------------------------------------------------------------------------------------

function setMode(mode) {
  state.mode = mode;
  document.body.classList.toggle('run', mode === 'run');
  document.body.classList.toggle('inspect', mode === 'inspect');
  $('mode-run').classList.toggle('active', mode === 'run');
  $('mode-inspect').classList.toggle('active', mode === 'inspect');
  const ov = $('overlay-layer');
  if (ov) ov.replaceChildren();
  if (mode === 'inspect') drawOverlaps();
  else unselect();
  if (state.fit) applyZoom();                         // the strip shows in Run only: the canvas changed its height
}

function intersects(a, b) {
  return Math.min(a.x + a.w, b.x + b.w) > Math.max(a.x, b.x) && Math.min(a.y + a.h, b.y + b.h) > Math.max(a.y, b.y);
}

function overlapsOf(info) {
  if (!state.drawn) return [];
  const other = info.source === 'template' ? state.view.kind : 'template';
  if (info.source === 'popup') return [];
  return state.drawn.objects.filter(o => o !== info && o.source === other && intersects(o.box, info.box));
}

// Inspect mode: template objects that a screen object overlaps are outlined on top, so both stay visible.
function drawOverlaps() {
  const ov = $('overlay-layer');
  if (!ov || !state.drawn) return;
  ov.replaceChildren();
  const done = new Set();
  for (const o of state.drawn.objects.filter(o => o.source === 'template')) {
    const over = state.drawn.objects.filter(s => s.source === 'screen' && intersects(s.box, o.box));
    if (!over.length || done.has(o)) continue;
    done.add(o);
    R.svgEl('rect', {class: 'overlap-outline', 'data-name': o.name, 'data-over': over.map(s => s.name).join(','),
      x: o.box.x, y: o.box.y, width: o.box.w, height: o.box.h}, ov);
  }
}

// What the panel on the right shows: the selected object; with none the diff's change list while the diff is on;
// else the view's own properties (the screen, template or pop-up, as TIA shows them with nothing selected).
function drawSide() {
  const show = state.selected && $('inspect').hasAttribute('data-name') ? 'object'
    : state.against !== 'off' ? 'diff' : 'view';
  $('side').setAttribute('data-show', show);
  $('inspect-section').hidden = show !== 'object';
  $('diff-slot').hidden = show !== 'diff';
  const box = $('view-props');
  const root = state.drawn && state.drawn.root, v = state.view;
  if (show !== 'view' || !root || !v || v.kind === 'textlist') {
    box.replaceChildren();
    $('view-section').hidden = true;
    return;
  }
  $('view-section').hidden = false;
  if (box.firstChild && box.firstChild.hmiRoot === root) return;
  const p = P.panel({el: root, type: root.tagName, name: v.name, catalogue: state.catalogue[root.tagName] || null,
    lang: LANG, links: (state.drawn.doc.links || []).filter(l => !l.object)});
  p.hmiRoot = root;
  box.replaceChildren(p);
}

function selectByName(name, source, quiet) {
  const info = topmost(name, source) || topmost(name);
  if (info) select(info);
  else if (!quiet) addNotice(`Inspect ${name}: no such object on this screen`);
}

// A notice after the draw's own (draw() writes the line anew).
function addNotice(text) {
  const n = $('notice');
  n.textContent = n.textContent ? n.textContent + '; ' + text : text;
}

function select(info) {
  state.selected = {name: info.name, source: info.source};
  for (const g of document.querySelectorAll('.obj.selected')) g.classList.remove('selected');
  info.g.classList.add('selected');
  markFindingRows();
  const doc = info.doc;
  const box = $('inspect');
  box.setAttribute('data-name', info.name);
  box.setAttribute('data-type', X.shortType(info.it.type));
  box.setAttribute('data-source', info.source);
  // presets: {ObjectName: {preset, source, document}} from generated.json; source / document null when not recorded
  const preset = (doc.presets || {})[info.name];
  const notRecorded = doc.origin === 'tia' ? 'not recorded (export)' : 'not recorded';
  const resolved = (doc.links || []).filter(l => l.object === info.name);
  const extra = [];

  extra.push(el('h3', 'Links'));
  const ul = el('ul', null, 'links');
  for (const l of resolved) {
    ul.append(el('li', `${l.kind} ${l.name}: ${l.state}${l.note ? ' (' + l.note + ')' : ''}`,
      'link state-' + l.state, {'data-kind': l.kind, 'data-name': l.name, 'data-state': l.state}));
  }
  for (const l of X.links(info.it.el)) {
    if (resolved.some(r => r.name === l.name)) continue;
    ul.append(el('li', `${l.kind} ${l.self ? '(own)' : l.name}: not checked`, 'link',
      {'data-kind': l.kind, 'data-name': l.name, 'data-state': 'not-checked'}));
  }
  if (!ul.children.length) ul.append(el('li', 'none'));
  extra.push(ul);

  const own = (doc.findings || []).filter(f => f.object === info.name);
  if (own.length) {
    extra.push(el('h3', 'Findings'));
    const fl = el('ul', null, 'findings');
    for (const f of own) fl.append(el('li', `[${f.rule}] ${f.message}`, 'finding ' + f.severity, {'data-rule': f.rule}));
    extra.push(fl);
  }

  const over = overlapsOf(info);
  if (over.length) {
    extra.push(el('h3', info.source === 'template' ? 'Screen objects over it' : 'Template objects under it'));
    const ol = el('ul', null, 'overlaps');
    for (const o of over) {
      const li = el('li', `${o.name} (${X.shortType(o.it.type)})`, 'overlap', {'data-name': o.name, 'data-source': o.source});
      li.addEventListener('click', () => select(o));
      ol.append(li);
    }
    extra.push(ol);
  }

  const where = info.source === 'popup' ? info.popup : info.source === 'template' && state.drawn.template
    ? state.drawn.template.name : doc.name;
  box.replaceChildren(P.panel({
    el: info.it.el, type: info.it.type, name: info.name, catalogue: state.catalogue[info.it.type] || null,
    lang: LANG, links: resolved, extra,
    head: [
      ['In', `${KIND_TEXT[info.source] || info.source} ${where} (${doc.origin === 'tia' ? 'Exported' : 'Generated'})`],
      ['Style preset', preset ? preset.preset : notRecorded],
      ['Copied from', preset && preset.source ? preset.source + (preset.document ? ' in ' + preset.document : '') : notRecorded],
    ],
  }));
  drawSide();
}

// Nothing selected: the panel goes back to the change list or the view's properties.
function unselect() {
  state.selected = null;
  $('inspect').removeAttribute('data-name');
  $('inspect').replaceChildren();
  for (const g of document.querySelectorAll('.obj.selected')) g.classList.remove('selected');
  F.select($('findings'), null, null);
  drawSide();
}

// --- live reload ----------------------------------------------------------------------------------------------

// once: close the stream at the first change (headless tests: virtual time stands still while it is open).
function startLive(once) {
  let timer = null, changed = [];
  const es = new EventSource('/api/events');
  es.addEventListener('change', ev => {
    try { changed.push(JSON.parse(ev.data).path); } catch (err) { /* ignore */ }
    if (once) es.close();
    clearTimeout(timer);
    timer = setTimeout(() => {
      const paths = changed;
      changed = [];
      enqueue(async () => {
        await refreshData();
        await draw();
        status('live', 'reloaded ' + new Date().toLocaleTimeString(), 'Reloaded after a change of ' + paths.join(', '));
        emit('refresh', paths);
      });
    }, 150);
  });
  es.addEventListener('ready', () => status('live', 'live', 'Live: redraws when a file under hmi/ or project/graphics/ changes'));
  es.onerror = () => status('lost', 'reconnecting', 'The change stream was lost; retrying');
}

function status(cls, text, title) {
  const s = $('status');
  s.className = cls;
  s.textContent = text;
  s.title = title || '';
}

// --- start ----------------------------------------------------------------------------------------------------

function initialView() {
  for (const kind of KINDS) if (params.has(kind)) return {kind, name: params.get(kind)};
  return state.list.startScreen ? {kind: 'screen', name: state.list.startScreen} : null;
}

async function main() {
  if (params.get('png') === '1') document.body.classList.add('png');
  setMode('run');
  const svg = $('screen');
  svg.addEventListener('mousedown', onPointer('Press'));
  svg.addEventListener('mouseup', onPointer('Release'));
  svg.addEventListener('click', onPointer('Click'));
  $('mode-run').addEventListener('click', () => setMode('run'));
  $('mode-inspect').addEventListener('click', () => setMode('inspect'));
  $('zoom').addEventListener('click', () => { state.fit = !state.fit; applyZoom(); });
  $('back').addEventListener('click', () => enqueue(() => exec({name: 'ActivatePreviousScreen', params: []},
    {who: 'Back button'})));
  $('events').classList.toggle('shut', logClosedBefore());
  $('events-toggle').addEventListener('click', () => setLogClosed(!$('events').classList.contains('shut')));
  $('log-clear').addEventListener('click', clearLog);
  $('start-screen').addEventListener('click', ev => {
    ev.preventDefault();
    if (state.list && state.list.startScreen) enqueue(() => navigate({kind: 'screen', name: state.list.startScreen}, true));
  });
  // A change in the diff's list selects its object (inspect mode); a removed one is not drawn and stays unselected.
  $('diff-list').addEventListener('click', ev => {
    const li = ev.target.closest('li[data-object]');
    if (!li || !li.getAttribute('data-object')) return;
    setMode('inspect');
    selectByName(li.getAttribute('data-object'), state.view ? state.view.kind : undefined, true);
  });
  $('findings-count').addEventListener('click', scrollToFindings);
  window.addEventListener('resize', () => { if (state.fit) applyZoom(); });

  state.typenames = await getJson('/api/typenames') || {};
  await refreshData();
  if (params.get('inspect')) setMode('inspect');
  await enqueue(() => navigate(initialView(), false));
  if (params.get('click')) {
    for (const name of params.get('click').split(',')) await clickObject(name);
  }
  if (params.get('keys')) {
    for (const key of params.get('keys').split(',')) {
      document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true}));
      await busy;
    }
  }
  if (params.get('prop')) P.setSearch(params.get('prop'));
  if (params.get('change')) await clickChange(params.get('change'));
  if (params.get('inspect')) selectByName(params.get('inspect'));
  if (params.get('finding')) {
    const row = [...$('findings').querySelectorAll('.finding.go')]
      .find(r => r.getAttribute('data-object') === params.get('finding'));
    if (row) { row.click(); await busy; } else addNotice(`Finding ${params.get('finding')}: no such finding in the list`);
  }
  status('', 'loaded ' + new Date().toLocaleTimeString(), params.get('live') === '0' ? 'Not live (?live=0)' : '');
  if (params.get('live') !== '0') startLive(params.get('live') === 'once');
  document.documentElement.setAttribute('data-ready', '1');
}

// Hook ?change=: click the change list's line of an object as soon as diff.js has listed it.
function clickChange(name) {
  const list = $('diff-list');
  const find = () => [...list.querySelectorAll('li[data-object]')].find(li => li.getAttribute('data-object') === name);
  return new Promise(done => {
    const go = li => { li.click(); done(); };
    const hit = find();
    if (hit) { go(hit); return; }
    const watch = new MutationObserver(() => { const li = find(); if (li) { watch.disconnect(); go(li); } });
    watch.observe(list, {childList: true});
  });
}

// --- extension API (diff.js: diff toggle and outlines) --------------------------------------------------------
//   hmiPreview.view            {device, kind, name, origin, path, doc}  the view drawn now (doc = /api/document)
//   hmiPreview.on('render', fn)  after every draw (navigation, pop-up, live reload); fn(view)
//   hmiPreview.on('refresh', fn) after a live reload, fn([changed repo paths])
//   hmiPreview.diffLayer       <g id="diff-layer"> on top of the drawing, emptied on every draw
//   hmiPreview.diffSlot        <section id="diff-slot"> in the panel (#diff-list); #diff-controls in the header
//   hmiPreview.objectBox(name, source='screen') -> {x, y, w, h} absolute box of a drawn object, or null
//   hmiPreview.redraw()        queue a redraw;  hmiPreview.log(sentence) adds an event log entry on top
//   hmiPreview.setAgainst(a)   the diff changed (off, commit, export): the tree's marks follow it
//   hmiPreview.toggleDiff      set by diff.js: key D
const api = {
  get view() {
    const v = state.view, d = state.drawn && state.drawn.doc;
    return v ? {device: v.device, kind: v.kind, name: v.name, origin: d ? d.origin : null, path: d ? d.path : null,
      doc: d} : null;
  },
  setAgainst(against) {
    if (against === state.against) return null;
    state.against = against;
    drawSide();
    return enqueue(refreshTree);
  },
  toggleDiff: null,
  on(name, fn) { listeners[name].push(fn); },
  get diffLayer() { return $('diff-layer'); },
  get diffSlot() { return $('diff-slot'); },
  objectBox(name, source) {
    const o = topmost(name, source || (state.view ? state.view.kind : 'screen'));
    return o ? Object.assign({}, o.box) : null;
  },
  redraw() { return enqueue(draw); },
  log(text) { logEntry(text); },
};
window.hmiPreview = api;

main().catch(err => {
  $('status').textContent = String(err);
  document.documentElement.setAttribute('data-ready', 'error');
});
