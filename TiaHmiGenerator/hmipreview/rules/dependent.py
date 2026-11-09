"""Dependent-property rules: TIA can refuse an HMI import whose dependent property does not follow its
main property with Siemens.Engineering.NonRecoverableException, and that exception ends the TIA process. Generated
documents only; the table is catalogue/dependent.json (catalogue.dependent()). It is stricter than what TIA was seen
to refuse: each message gives its row's source, what TIA was seen to do with the row.

  dependent.value    error: a pair (the object has the main value, the dependent property differs from the value
                     the table expects) or a relation (Radius = Width / 2, a line's box from its start and end, ...)
                     does not hold
  dependent.device   warning: a value taken as not allowed on Comfort panels, no verdict from TIA; the project's own
                     device may take it
"""
import re

from .. import catalogue
from ..findings import error, warning
from ..model import attribute, object_name, objects, parent_map

_POINT = re.compile(r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)')


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _values(e, name):
    """The numbers of one 'of' entry: an attribute, or the x or y coordinates of Points ('Points.x')."""
    if name in ('Points.x', 'Points.y'):
        pts = _POINT.findall(attribute(e, 'Points') or '')
        return [float(p[0 if name.endswith('x') else 1]) for p in pts]
    n = _number(attribute(e, name))
    return [] if n is None else [n]


def _expected(rel, e):
    vals = [v for name in rel['of'] for v in _values(e, name)]
    if not vals:
        return None
    return {'equal': lambda: vals[0], 'half': lambda: vals[0] // 2, 'min': lambda: min(vals),
            'span': lambda: max(vals) - min(vals)}[rel['is']]()


def _holds(e, when):
    return all(attribute(e, k) == v for k, v in (when or {}).items())


def _show(n):
    return '%g' % n


def _because(when):
    return ' and '.join('%s is %s' % kv for kv in when.items())


def _of(rel):
    names = ' and '.join(rel['of'])
    return {'equal': 'equal to ' + names, 'half': 'half of %s, rounded down' % names, 'min': 'the smallest of ' + names,
            'span': 'the extent of ' + names}[rel['is']]


def _tail(row):
    return ' (dependent property; seen in TIA: %s). If TIA refuses it, the import ends TIA.' % row['source']


def check_object(e):
    """[(severity, rule, message)] of one object element."""
    table = catalogue.dependent()
    out = []
    for p in table['pairs']:
        if p['element'] != e.tag or not _holds(e, p['when']):
            continue
        for k, v in p['then'].items():
            have = attribute(e, k)
            if have is not None and have != v:
                out.append(('error', 'dependent.value',
                            '%s is %s; the rule table expects %s because %s%s'
                            % (k, have, v, _because(p['when']), _tail(p))))
    for r in table['relations']:
        if r['element'] != e.tag or not _holds(e, r.get('when')):
            continue
        have, want = _number(attribute(e, r['attribute'])), _expected(r, e)
        if have is None or want is None or abs(have - want) < 1e-6:
            continue
        cond = ' while %s' % _because(r['when']) if r.get('when') else ''
        out.append(('error', 'dependent.value',
                    '%s is %s; the rule table expects %s (%s)%s%s'
                    % (r['attribute'], _show(have), _show(want), _of(r), cond, _tail(r))))
    for d in table['deviceRefuses']:
        if d['element'] == e.tag and attribute(e, d['attribute']) == d['value']:
            out.append(('warning', 'dependent.device',
                        '%s %s is taken as not allowed on Comfort panels (TP1200, TP1900, outdoor TP1500; no verdict '
                        'from TIA in the test imports); if TIA refuses it, the import ends TIA. Use another value '
                        'unless the project\'s device is '
                        'known to take it.' % (d['attribute'], d['value'])))
    return out


def check(repo, ctx):
    for d in repo.generated:
        parents = parent_map(d.tree)
        for e in objects(d.tree):
            for severity, rule, message in check_object(e):
                yield (error if severity == 'error' else warning)(d.path, object_name(e, parents), rule, message)
