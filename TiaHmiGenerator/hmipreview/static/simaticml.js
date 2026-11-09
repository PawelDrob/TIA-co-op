// SimaticML reading for the browser app: the shapes of docs/agent/wincc-comfort-openness.md section 4.
// An object element is any element with an ID; its attributes are the children of its own AttributeList.
'use strict';

export function parseXml(text) {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error('XML parse error');
  return doc;
}

export function kids(el, pred) {
  return el ? Array.from(el.children).filter(c => !pred || pred(c)) : [];
}

export function child(el, tag) {
  return kids(el, c => c.tagName === tag)[0] || null;
}

// The root object of a document (Hmi.Screen.Screen, ScreenTemplate, ScreenPopup): first child of Document with an ID.
export function rootObject(xmlDoc) {
  return kids(xmlDoc.documentElement, c => c.hasAttribute('ID'))[0] || null;
}

// Leaf attributes of an object: {name: text}. Attributes with children (rich Text, typed Value) are left out.
export function attrs(el) {
  const out = {};
  for (const a of kids(child(el, 'AttributeList'))) {
    if (a.children.length === 0) out[a.tagName] = a.textContent;
  }
  return out;
}

export function attr(el, name, dflt) {
  const a = child(child(el, 'AttributeList'), name);
  return a ? a.textContent : dflt;
}

export function num(el, name, dflt) {
  const v = attr(el, name);
  if (v === undefined || v === '') return dflt;
  const n = Number(v);
  return Number.isFinite(n) ? n : dflt;
}

export function shortType(tag) {
  return tag.replace(/^Hmi\.Screen\./, '');
}

// Colour 'r, g, b' -> css rgb(); dflt when absent.
export function color(s, dflt) {
  if (!s) return dflt;
  const p = s.split(',').map(v => parseInt(v, 10));
  return p.length === 3 && p.every(Number.isFinite) ? `rgb(${p[0]}, ${p[1]}, ${p[2]})` : dflt;
}

// A layer hidden in the editor (VisibleES false): its objects are not drawn, as the TIA editor shows the screen
// (at runtime they show).
function hiddenInEditor(layer) {
  return attr(layer, 'VisibleES') === 'false';
}

// [{index, name, count}] of the layers of root hidden in the editor that hold objects.
export function hiddenLayers(root) {
  return kids(child(root, 'ObjectList'), c => c.getAttribute('CompositionName') === 'Layers' && hiddenInEditor(c))
    .map(l => ({index: attr(l, 'Index', ''), name: attr(l, 'Name', ''),
      count: kids(child(l, 'ObjectList'), c => c.getAttribute('CompositionName') === 'ScreenItems').length}))
    .filter(l => l.count);
}

// Screen items in document order, groups kept as {group: true, children}; the layers hidden in the editor left out.
export function screenItems(root) {
  const out = [];
  const walk = (el, into) => {
    for (const c of kids(el)) {
      if (c.getAttribute('CompositionName') === 'ScreenItems') {
        const it = {el: c, type: c.tagName, name: attr(c, 'ObjectName', '')};
        if (c.tagName === 'Hmi.Screen.Group') {
          it.group = true;
          it.children = [];
          walk(child(c, 'ObjectList') || c, it.children);
        }
        into.push(it);
      } else if (c.tagName === 'ObjectList' || (c.getAttribute('CompositionName') === 'Layers' && !hiddenInEditor(c))) {
        walk(c, into);
      }
    }
  };
  if (root) walk(root, out);
  return out;
}

export function flatItems(list) {
  const out = [];
  const walk = l => { for (const it of l) { if (it.group) walk(it.children); else out.push(it); } };
  walk(list);
  return out;
}

export function points(el) {
  const s = attr(el, 'Points');
  if (!s) return null;
  const pts = [];
  const re = /<Item>\s*([-\d.]+)\s*,\s*([-\d.]+)\s*<\/Item>/g;
  let m;
  while ((m = re.exec(s))) pts.push([Number(m[1]), Number(m[2])]);
  return pts.length ? pts : null;
}

// Bounding box as hmipreview.geometry.box_of: Points, then Start/End (of a Line any end written, one left out counting
// 0; of another object all four), then Left/Top/Width/Height (Radius).
// Nothing is guessed (full exports only, 2026-10-06): a coordinate the document leaves out counts 0 and is listed in
// missing, so the renderer can mark the object; null when the object has no size at all.
export function box(el) {
  const pts = points(el);
  if (pts) {
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const x = Math.min(...xs), y = Math.min(...ys);
    return {x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y, missing: []};
  }
  const ends = ['StartLeft', 'StartTop', 'EndLeft', 'EndTop'];
  const hasEnds = el.tagName === 'Hmi.Screen.Line'
    ? ends.some(k => attr(el, k) !== undefined) && !ends.some(k => attr(el, k) && num(el, k) === undefined)
    : ends.every(k => num(el, k) !== undefined);
  if (hasEnds) {
    const [sx, sy, ex, ey] = ends.map(k => num(el, k, 0));
    return {x: Math.min(sx, ex), y: Math.min(sy, ey), w: Math.abs(ex - sx), h: Math.abs(ey - sy),
      missing: ends.filter(k => attr(el, k) === undefined)};
  }
  let w = num(el, 'Width'), h = num(el, 'Height');
  const r = num(el, 'Radius');
  if ((w === undefined || h === undefined) && r !== undefined) w = h = 2 * r;
  if (w === undefined && h === undefined) return null;
  const x = num(el, 'Left'), y = num(el, 'Top');
  const missing = [['Left', x], ['Top', y], ['Width', w], ['Height', h]].filter(p => p[1] === undefined).map(p => p[0]);
  return {x: x || 0, y: y || 0, w: w || 0, h: h || 0, missing};
}

function textLines(t) {
  const body = child(t, 'body');
  if (!body) return (t.textContent || '').split('\n');
  const lines = [];
  for (const p of body.getElementsByTagName('p')) {
    let cur = '';
    for (const n of p.childNodes) {
      if (n.nodeType === 3) cur += n.nodeValue;
      else if (n.tagName === 'br') { lines.push(cur); cur = ''; }
      else cur += n.textContent;
    }
    lines.push(cur);
  }
  return lines;
}

// {culture: [lines]} of the first MultilingualText with one of the composition names.
export function texts(el, comps) {
  for (const mt of el.getElementsByTagName('MultilingualText')) {
    if (!comps.includes(mt.getAttribute('CompositionName'))) continue;
    if (mt.parentElement && mt.parentElement.parentElement !== el) continue;   // own text, not a member's
    const out = {};
    for (const it of mt.getElementsByTagName('MultilingualTextItem')) {
      const al = child(it, 'AttributeList');
      const t = child(al, 'Text');
      if (t) out[(child(al, 'Culture') || {}).textContent || ''] = textLines(t);
    }
    return out;
  }
  return null;
}

// {culture: [lines]} of the text list entry that value selects (From <= value <= To), else of the first entry;
// null when the list has none. root: the Hmi.TextGraphicList.TextList element.
export function textListEntry(root, value) {
  const entries = root ? Array.from(root.getElementsByTagName('Hmi.TextGraphicList.TextListEntry')) : [];
  const hit = entries.find(e => num(e, 'From', NaN) <= value && value <= num(e, 'To', num(e, 'From', NaN)));
  const e = hit || entries[0];
  return e ? texts(e, ['Text']) : null;
}

export function pickCulture(map, lang) {
  if (!map) return null;
  if (lang in map) return map[lang];
  const keys = Object.keys(map);
  return keys.length ? map[keys[0]] : null;
}

// Font of an item for a culture: {size, bold, family} of its FontItem for lang (else the first one); null when the
// item has no FontItem or it lacks FontSize / FontFamily (an incomplete document: the renderer marks it).
export function font(el, lang) {
  for (const c of kids(child(el, 'ObjectList'))) {
    if (c.getAttribute('CompositionName') !== 'Font') continue;
    const items = Array.from(c.getElementsByTagName('*')).filter(e => e.tagName.endsWith('FontItem'));
    const pick = items.find(i => attr(i, 'Culture') === lang) || items[0];
    const size = pick ? num(pick, 'FontSize') : undefined, family = pick ? attr(pick, 'FontFamily') : undefined;
    if (size === undefined || !family) return null;
    return {size, bold: /bold/i.test(attr(pick, 'FontStyle', '')), family};
  }
  return null;
}

// Links of an object's own LinkList: [{kind, name, self}].
export function links(el) {
  return kids(child(el, 'LinkList')).map(l => ({
    kind: l.tagName, name: (child(l, 'Name') || {}).textContent || null,
    self: l.getAttribute('TargetID') === '#0',
  }));
}

export function hasVisibilityAnimation(el) {
  return kids(child(el, 'ObjectList'), c => c.tagName === 'Hmi.Dynamic.VisibilityAnimation').length > 0;
}

// Events of an object: [{name, functions: [{name, params: [{name, value, link, self}]}]}].
export function events(el) {
  const out = [];
  for (const ev of kids(child(el, 'ObjectList'), c => c.tagName === 'Hmi.Event.Event')) {
    const fns = [];
    for (const fe of ev.getElementsByTagName('Hmi.Event.FunctionListEntry')) {
      const params = [];
      for (const p of fe.getElementsByTagName('Hmi.Event.FunctionListEntryParameter')) {
        const l = links(p)[0];
        const v = child(child(p, 'AttributeList'), 'Value');
        params.push({name: attr(p, 'Name', ''), value: v ? v.textContent : null,
                     link: l ? l.name : null, self: l ? l.self : false});
      }
      fns.push({name: attr(fe, 'Name', ''), params});
    }
    out.push({name: attr(ev, 'Name', ''), functions: fns});
  }
  return out;
}
