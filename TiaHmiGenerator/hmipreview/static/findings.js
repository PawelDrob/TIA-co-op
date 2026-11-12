// The findings list below the screen, laid out as the change list below the screen in the change report
// (TiaChangeReports hmi.js): the open planned items first, then a box per document (errors first, the project's
// own findings last) with its rules and their findings in sentences, from /api/findingspage (findingspage.py).
// Several objects about the same other object fold into one line. A click on a finding opens its document, with the
// object selected where the preview can select it; C and E fold and unfold every box and fold (the maintainer,
// 2026-11-05). Only the document the preview draws opens: not an export a generated document replaces.
//
//   KIND_TEXT               {kind: 'Pop-up screen' ...}, also the view title's (app.js)
//   draw(box, data, open)   fills box; open({device, kind, name}, object or null) is called on a click
//   foldAll(box, shut)      C (shut) and E (open): every box and fold
//   select(box, view, name) marks the rows of the object selected on the screen
// What is folded stays across redraws (a live reload): kept by the box's and the fold's key.
'use strict';

export const KIND_TEXT = {screen: 'Screen', popup: 'Pop-up screen', template: 'Template', textlist: 'Text list',
  tagtable: 'Tag table', cycle: 'Cycle', project: 'The project'};
const shutBoxes = new Set();     // keys of the boxes closed by a click or C
const openFolds = new Set();     // keys of the folds opened by a click or E

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
}

// Sets the class cls ('shut' of a box, 'open' of a fold) of el, its key kept in the set kept while it is on.
function setFold(el, cls, on, kept) {
  el.classList.toggle(cls, on);
  if (on) kept.add(el.getAttribute('data-key')); else kept.delete(el.getAttribute('data-key'));
}

function plural(n, word) {
  return n + ' ' + word + (n === 1 ? '' : 's');
}

function counts(errors, warnings) {
  return h('span', {class: 'fcn'}, errors ? h('span', {class: 'error'}, plural(errors, 'error')) : null,
    errors && warnings ? ', ' : null, warnings ? h('span', {class: 'warning'}, plural(warnings, 'warning')) : null);
}

// A box with a title bar that folds it, as the change report's change list.
function box(key, head, body) {
  const b = h('div', {class: 'fbx' + (shutBoxes.has(key) ? ' shut' : ''), 'data-key': key});
  b.append(h('div', {class: 'fbh', onclick: () => setFold(b, 'shut', !b.classList.contains('shut'), shutBoxes)},
    h('span', {class: 'ftw'}), head), h('div', {class: 'fbb'}, body));
  return b;
}

function viewOf(s) {
  return {device: s.device, kind: s.kind, name: s.name};
}

function findingRow(s, it, open) {
  const go = s.opens;
  return h('div', {class: 'finding ' + it.severity + (go ? ' go' : ''), 'data-rule': it.rule,
    'data-object': it.object || '', 'data-document': s.path, 'data-device': s.device,
    title: go ? `Open ${s.name}` + (it.select ? ` with ${it.object} selected` : '') : null,
    onclick: go ? () => open(viewOf(s), it.select ? it.object : null) : null},
  h('span', {class: 'mk ' + it.severity}), h('span', {class: 'ftx'}, it.text));
}

function foldRow(s, rule, row, open) {
  const key = [s.device, s.path, row.key].join('|');
  const f = h('div', {class: 'ffold ' + row.severity + (openFolds.has(key) ? ' open' : ''), 'data-key': key,
    'data-rule': rule.rule});
  f.append(h('div', {class: 'ffh', onclick: () => setFold(f, 'open', !f.classList.contains('open'), openFolds)},
  h('span', {class: 'ht'}), h('span', {class: 'mk ' + row.severity}), h('span', {class: 'ftx'}, row.fold),
  h('span', {class: 'k'}, `${row.items.length} findings`)),
  h('div', {class: 'ffb'}, row.items.map(it => findingRow(s, it, open))));
  return f;
}

function section(s, open, multi) {
  const where = s.kind === 'project' ? s.files.join(', ') : KIND_TEXT[s.kind] || s.kind;
  const head = [h('b', {}, s.kind === 'project' ? KIND_TEXT.project : s.name), h('span', {class: 'k'}, where),
    multi && s.device ? h('span', {class: 'k'}, s.device) : null, counts(s.errors, s.warnings)];
  const body = s.rules.map(r => h('div', {class: 'frule', 'data-rule': r.rule},
    h('div', {class: 'frh'}, h('span', {class: 'mk ' + r.severity}), r.title, h('span', {class: 'k'}, r.rule)),
    r.rows.map(row => row.fold ? foldRow(s, r, row, open) : findingRow(s, row.items[0], open))));
  const b = box('doc|' + s.device + '|' + s.path, head, body);
  b.classList.add('fdoc');
  b.setAttribute('data-document', s.path);
  b.setAttribute('data-device', s.device);
  return b;
}

function plannedBox(items, open, multi) {
  const rows = items.map(p => h('div', {class: 'planned-item', 'data-kind': p.kind, 'data-name': p.name},
    h('span', {class: 'mk planned'}), h('span', {class: 'k'}, p.kind), h('b', {}, p.name),
    multi && p.device ? h('span', {class: 'k'}, p.device) : null,
    p.note ? h('span', {class: 'k'}, p.note) : null,
    h('span', {class: 'fused'}, p.usedBy.length ? 'used by ' : 'not used yet',
      p.usedBy.flatMap((u, k) => {
        const label = u.object ? `${u.object} (${u.name})` : u.name;
        const a = u.kind ? h('a', {href: '#', title: `Open ${u.name}`, onclick: ev => {
          ev.preventDefault();
          open({device: u.device, kind: u.kind, name: u.name}, u.object);
        }}, label) : label;
        return k ? [', ', a] : [a];
      }))));
  const b = box('planned', [h('b', {}, 'Open planned items'), h('span', {class: 'k'}, 'not in TIA yet: an error at import'),
    h('span', {class: 'fcn'}, plural(items.length, 'item'))], rows);
  b.id = 'planned';
  return b;
}

export function draw(el, data, open) {
  const sections = data ? data.sections : [];
  const planned = data ? data.planned : [];
  const devices = new Set([...sections.map(s => s.device), ...planned.map(p => p.device)]);
  const multi = devices.size > 1;
  let errors = 0, warnings = 0;
  for (const s of sections) { errors += s.errors; warnings += s.warnings; }
  el.replaceChildren(
    h('div', {class: 'fhd'}, h('b', {}, 'Findings'), ' ',
      !errors && !warnings && !planned.length ? h('span', {class: 'k'}, 'none') : counts(errors, warnings),
      planned.length ? h('span', {class: 'k'}, ' and ' + plural(planned.length, 'open planned item')) : null,
      h('span', {class: 'k fkeys'}, 'C collapses, E expands every box')),
    planned.length ? plannedBox(planned, open, multi) : '',
    ...sections.map(s => section(s, open, multi)));
}

export function foldAll(el, shut) {
  for (const b of el.querySelectorAll('.fbx')) setFold(b, 'shut', shut, shutBoxes);
  for (const f of el.querySelectorAll('.ffold')) setFold(f, 'open', !shut, openFolds);
}

// view {device, path} of the open document; name the selected object or null
export function select(el, view, name) {
  for (const r of el.querySelectorAll('.finding')) {
    r.classList.toggle('sel', !!view && name !== null && r.getAttribute('data-object') === name &&
      r.getAttribute('data-document') === view.path && r.getAttribute('data-device') === view.device);
  }
}
