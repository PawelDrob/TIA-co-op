// HMI preview diff: toggle off / against the last commit / against the TIA export in the header, what is compared
// ("Comparing: export vs generated"), outlines on the canvas and the change list in words; the project
// tree's marks follow the toggle (hmiPreview.setAgainst). Data: GET /api/diff (hmipreview/diffapi.py). Hook:
// ?diff=commit|export.
//
// What is compared, per document:
//   last commit  a generated document: generated vs generated (at HEAD, on disk); an export: export vs export
//   TIA export   a generated document: export vs generated (what the import changes); an export: itself
//
// Outlines in g#diff-layer: rect.diff-outline[data-name][data-change][data-part=new|old]
//   added    green, new rectangle            removed  red ghost at the old rectangle (part old)
//   moved    light blue at the new rectangle and a dashed light blue one at the old (part old)
//   changed  amber (attribute, text, link or event change, same rectangle)
// A group is outlined by the box around its members. The screen itself and a group with no member that has
// geometry are listed only.
'use strict';
import {svgEl} from './render.js';

const api = window.hmiPreview;
const params = new URLSearchParams(location.search);
const MODES = [['off', 'Off'], ['commit', 'Last commit'], ['export', 'TIA export']];
const LABEL = {commit: 'the last commit', export: 'the TIA export'};
let against = MODES.some(m => m[0] === params.get('diff')) ? params.get('diff') : 'off';
let seq = 0;

const slot = document.getElementById('diff-slot');
const controls = document.getElementById('diff-controls');
const list = document.getElementById('diff-list');
const comparing = document.getElementById('comparing');

function li(text, cls, attrs) {
  const e = document.createElement('li');
  e.textContent = text;
  e.className = cls;
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) e.setAttribute(k, v);
  return e;
}

function setAgainst(key) {
  against = key;
  if (api && api.setAgainst) api.setAgainst(key);
  update();
}

function drawControls() {
  controls.replaceChildren(...MODES.map(([key, label]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = key === against ? 'active' : '';
    b.setAttribute('data-against', key);
    b.title = key === 'off' ? 'No diff' : 'Outline what changed against ' + LABEL[key] + (key === 'commit' ? ' (D)' : '');
    b.addEventListener('click', () => setAgainst(key));
    return b;
  }));
  slot.setAttribute('data-against', against);
}

// The header's "Comparing: ..." for the view: [text, tooltip], or null with the diff off.
function compared(view) {
  if (against === 'off' || !view || !view.doc) return null;
  const gen = view.origin === 'generated';
  if (against === 'commit') {
    return gen ? ['generated vs generated', 'The generated document at the last commit against the one on disk']
      : ['export vs export', 'The TIA export at the last commit against the one on disk'];
  }
  return gen ? ['export vs generated', 'The TIA export against the generated document that replaces it at import']
    : ['export vs export', 'Nothing generated for it: the TIA export is what TIA has'];
}

function drawComparing(view) {
  const c = compared(view);
  comparing.textContent = c ? 'Comparing: ' + c[0] : '';
  comparing.title = c ? c[1] : '';
  comparing.setAttribute('data-compared', c ? c[0] : '');
}

function outline(layer, change, part, box) {
  const r = svgEl('rect', {class: `diff-outline diff-${change.kind}${part === 'old' ? ' diff-old' : ''}`,
    'data-name': change.object, 'data-change': change.kind, 'data-part': part,
    x: box.x, y: box.y, width: box.w, height: box.h}, layer);
  const t = svgEl('title', {}, r);
  t.textContent = `${change.type} ${change.object}: ${change.kind}${part === 'old' ? ' (before)' : ''}`;
}

function drawOutlines(changes) {
  const layer = api.diffLayer;
  if (!layer) return;
  layer.replaceChildren();
  for (const c of changes) {
    if (c.object === null) continue;
    if (c.kind === 'removed') { if (c.old) outline(layer, c, 'old', c.old); continue; }
    if (c.kind === 'moved' && c.old) outline(layer, c, 'old', c.old);
    if (c.new) outline(layer, c, 'new', c.new);
  }
}

async function update() {
  const my = ++seq;
  drawControls();
  const layer = api.diffLayer;
  if (layer) layer.replaceChildren();
  const view = api.view;
  drawComparing(view);
  slot.removeAttribute('data-state');
  if (against === 'off') { list.replaceChildren(); slot.setAttribute('data-state', 'off'); return; }
  if (!view || !view.doc) { list.replaceChildren(li('Nothing to compare.', 'diff-note')); return; }
  const q = new URLSearchParams({name: view.name, kind: view.kind, against});
  if (view.device) q.set('device', view.device);
  let data;
  try {
    const r = await fetch('/api/diff?' + q, {cache: 'no-store'});
    data = await r.json();
    if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
  } catch (err) {
    if (my === seq) list.replaceChildren(li('Diff failed: ' + (err && err.message || err), 'diff-note error'));
    return;
  }
  if (my !== seq) return;                      // a newer draw or toggle took over
  if (view.kind !== 'textlist') drawOutlines(data.changes);
  const kinds = {};
  for (const c of data.changes) kinds[c.object === null ? '' : c.object] = c.kind;
  const items = data.lines.map((line, i) => {
    const obj = (data.lineObjects || [])[i];
    const e = li(line, 'diff-line diff-' + (kinds[obj === null || obj === undefined ? '' : obj] || 'changed'),
      {'data-object': obj});
    return e;
  });
  if (!items.length) items.push(li(`No changes against ${LABEL[against]}.`, 'diff-note'));
  if (data.base && data.base.path === null) {
    items.unshift(li(against === 'commit' ? 'Not committed yet: everything is new.' : 'Not in TIA yet: everything is new.',
      'diff-note'));
  }
  list.replaceChildren(...items);
  slot.setAttribute('data-state', data.origin === 'tia' ? 'tia' : 'ok');
}

if (api) {
  api.on('render', () => { update(); });
  api.toggleDiff = () => setAgainst(against === 'off' ? 'commit' : 'off');
  drawControls();
  if (api.view) update();
}
