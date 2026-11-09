"""Spelling round trip of the screen object catalogue: zz test screens that set every documented enum value whose
export spelling no export has confirmed yet, one value per object, on objects copied from the fixture. They are
imported into TIA and exported again (only the coordinator's bridge touches TIA); the exports go into
roundtrip/back/ and build.py reads them: a value that came back is confirmed, one that came back different is
lost.

Run from TiaHmiGenerator:
  python catalogue\\roundtrip.py <out folder>     writes <out folder>\\zzTestSpellings.xml (and zzTestSpellings2.xml)
                                                  and roundtrip\\sent.json, prints the values set per object
  (after the round trip) copy TIA's export of each screen to roundtrip\\back\\, strip the
  DocumentInfo/InstalledProducts, then python catalogue\\build.py

The values sent are the documented ones with a spelling from TIA's enum (catalogue values.documented[].spelling),
not confirmed and not lost. Help names without a member of TIA's enum are left out: TIA cannot read them.

A refused import ends TIA's process (Siemens.Engineering.NonRecoverableException) and TIA stops at the first error,
so what is known about TIA's checks is applied before sending. The table is catalogue/dependent.json, which the
validator reads as well (hmipreview/rules/dependent.py):
  DEPENDENT       its pairs with one main value: the dependent properties are set on the object with the value
  DEVICE_REFUSES  its deviceRefuses: values taken as not allowed on Comfort panels; not sent
  SECOND_SCREEN   values one panel may not allow: sent on zzTestSpellings2, so the first screen can pass
"""
import argparse
import copy
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import hmixml                                        # noqa: E402
from hmipreview import catalogue                     # noqa: E402

NAME = 'zzTestSpellings'
SENT = os.path.join(HERE, 'roundtrip', 'sent.json')
SCREEN_W, SCREEN_H = 1280, 800
CELL, MARGIN = 90, 8                                 # objects 82 x 82: even, so a radius is exactly half the box

# (element, attribute, value) -> {dependent attribute: value}: main property set -> dependents the table expects.
DEPENDENT = {(p['element'],) + next(iter(p['when'].items())): p['then']
             for p in catalogue.dependent()['pairs'] if len(p['when']) == 1}
DEVICE_REFUSES = {(d['element'], d['attribute'], d['value']) for d in catalogue.dependent()['deviceRefuses']}
# One panel may not allow these (TP1900; the round trip's device took them): line styles and ends beyond Solid / Dash and
# NoEnd / FilledArrow, border dash styles beyond Solid / Dash.
_DASHES = ('Dot', 'DashDot', 'DashDotDot')
_ENDS = ('Arrow', 'FilledArrowReversed', 'Line', 'Circle', 'FilledCircle')
_LINES = ('Hmi.Screen.Line', 'Hmi.Screen.Polyline')
SECOND_SCREEN = ({(k, 'Style', v) for k in _LINES for v in _DASHES}
                 | {(k, a, v) for k in _LINES for a in ('StartStyle', 'EndStyle') for v in _ENDS}
                 | {('Hmi.Screen.' + k, 'EdgeStyle', v) for k in ('Polygon', 'Ellipse', 'Circle', 'Rectangle')
                    for v in _DASHES})


def to_send():
    """[(type, attribute, spelling)] for the toolbox types that go through Openness, in catalogue order: the
    documented values with a spelling, not confirmed, not lost."""
    out = []
    for t in catalogue.toolbox():
        if not t.get('openness') or t['element'] not in catalogue.fixture_objects():
            continue
        for a in t['attributes']:
            v = a.get('values') or {}
            if a.get('kind') != 'enum' or not v.get('enum'):
                continue
            vals = [d['spelling'] for d in v.get('documented', [])
                    if not d['confirmed'] and d.get('spelling') and d['spelling'] not in v.get('lost', {})]
            out += [(t, a['name'], s) for s in dict.fromkeys(vals)]
    return out


def _cultures():
    root = ET.parse(os.path.join(catalogue.FIXTURE, sorted(os.listdir(catalogue.FIXTURE))[0])).getroot()
    return list(dict.fromkeys(c.text for c in root.iter('Culture')))


def _place(e, tag, x, y, w, h):
    """Box of one object in its cell; lines and polylines get their points, circles and ellipses their radii."""
    have = {a.tag for a in e.find('AttributeList')}
    sets = {'Left': x, 'Top': y, 'Width': w, 'Height': h}
    if tag == 'Hmi.Screen.Line':
        sets.update(StartLeft=x, StartTop=y, EndLeft=x + w, EndTop=y + h)
    if 'Points' in have:
        sets['Points'] = '\ufeff' + ''.join('<Item>%d, %d</Item>' % p for p in ((x, y), (x + w, y), (x + w, y + h)))
    if tag == 'Hmi.Screen.Circle':
        sets['Radius'] = w // 2
    if tag == 'Hmi.Screen.Ellipse':
        sets.update(RadiusWidth=w // 2, RadiusHeight=h // 2)
    for k, v in sets.items():
        if k in have:
            hmixml.setattr_(e, k, v)


def _screen(name, number, items):
    root = hmixml.blank('Hmi.Screen.Screen')
    for k, v in (('Name', name), ('Number', number), ('Width', SCREEN_W), ('Height', SCREEN_H)):
        hmixml.setattr_(root, k, v)
    layer = hmixml.blank('Hmi.Screen.ScreenLayer', 'Layers')
    ET.SubElement(root, 'ObjectList').append(layer)
    layer_ol = ET.SubElement(layer, 'ObjectList')
    for e in items:
        layer_ol.append(e)
    doc = ET.Element('Document')
    ET.SubElement(doc, 'Engineering', {'version': 'V20'})
    fx = ET.parse(os.path.join(catalogue.FIXTURE, sorted(os.listdir(catalogue.FIXTURE))[0])).getroot()
    doc.append(copy.deepcopy(fx.find('DocumentInfo')))
    doc.append(root)
    hmixml.renumber(doc)
    return doc


def build():
    """([(screen name, document)], sent values [{screen, element, object, attribute, value, also}]): one object per
    value, its dependents set with it."""
    cultures = _cultures()
    cols, rows = (SCREEN_W - MARGIN) // CELL, (SCREEN_H - MARGIN) // CELL
    screens = {NAME: [], NAME + '2': []}
    sent, count = [], {}
    for t, attr, value in to_send():
        key = (t['element'], attr, value)
        if key in DEVICE_REFUSES:
            continue
        screen = NAME + '2' if key in SECOND_SCREEN else NAME
        items = screens[screen]
        n = len(items)
        if n >= cols * rows:
            raise SystemExit('more objects than %s holds' % screen)
        count[t['key']] = count.get(t['key'], 0) + 1
        name = 'zz%s%d' % (t['key'], count[t['key']])
        x, y = MARGIN + (n % cols) * CELL, MARGIN + (n // cols) * CELL
        e = hmixml.shape_item(t['element'], name, x, y, CELL - MARGIN, CELL - MARGIN, cultures)
        _place(e, t['element'], x, y, CELL - MARGIN, CELL - MARGIN)
        hmixml.setattr_(e, attr, value)
        also = DEPENDENT.get(key, {})
        for k, v in also.items():
            hmixml.setattr_(e, k, v)
        items.append(e)
        s = {'screen': screen, 'element': t['element'], 'object': name, 'attribute': attr, 'value': value}
        if also:
            s['also'] = also
        sent.append(s)
    docs = [(name, _screen(name, 23 + i, items)) for i, (name, items) in enumerate(screens.items()) if items]
    return docs, sent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out', help='folder for the screens')
    args = ap.parse_args(argv)
    docs, sent = build()
    os.makedirs(args.out, exist_ok=True)
    for name, doc in docs:
        with open(os.path.join(args.out, name + '.xml'), 'wb') as f:
            f.write(hmixml.serialize(doc))
    os.makedirs(os.path.dirname(SENT), exist_ok=True)
    with open(SENT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'about': 'Values the spelling round trip screens set, one per object (roundtrip.py).',
                            'values': sent}, indent=1, ensure_ascii=False) + '\n')
    for s in sent:
        also = ', '.join('%s=%s' % kv for kv in s.get('also', {}).items())
        print('%-17s %-20s %s=%s%s' % (s['screen'], s['object'], s['attribute'], s['value'],
                                       ' (with %s)' % also if also else ''))
    for name, _ in docs:
        print('%s: %d values' % (name, sum(1 for s in sent if s['screen'] == name)))
    skipped = sorted((e.split('.')[-1], a, v) for e, a, v in DEVICE_REFUSES)
    print('not sent (not allowed on Comfort panels): ' + ', '.join('%s.%s=%s' % k for k in skipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
