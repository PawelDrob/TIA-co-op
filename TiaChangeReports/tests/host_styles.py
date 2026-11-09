"""The computed styles of every element of a report fragment, on a bare page and inside a host page, by one
headless Edge run per page (TiaHmiGenerator\\hmipreview\\edge.py). Shared by the TiaChangeReports tests;
not a test module itself.

  browser()                         -> Edge (else Chrome), or None without either or hmipreview (the tests skip)
  styles(edge, page, folder)        -> (width of the .ldiff, {element: [computed value of each of PROPS]} of the
                                       .ldiff and its elements)
  bare(fragment, width)             -> the fragment alone on a page, that wide (auto margins depend on the width)
  differences(a, b)                 -> {element: {property: (a, b)}}
"""
import json
import os
import re
import sys
from html import unescape
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# What a host page sets on its own elements and the fragment's elements would take over (not the widths: the
# fragment is narrower inside a host page)
PROPS = ['color', 'background-color', 'background-image', 'font-family', 'font-size', 'font-weight', 'font-style',
         'line-height', 'text-transform', 'letter-spacing', 'word-spacing', 'text-indent', 'text-align',
         'text-decoration-line', 'text-shadow', 'white-space', 'word-break', 'vertical-align', 'display', 'position',
         'box-sizing', 'border-top-width', 'border-top-style', 'border-top-color', 'border-right-width',
         'border-right-style', 'border-right-color', 'border-bottom-width', 'border-bottom-style',
         'border-bottom-color', 'border-left-width', 'border-left-style', 'border-left-color',
         'border-top-left-radius', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'margin-top',
         'margin-right', 'margin-bottom', 'margin-left', 'max-width', 'max-height', 'overflow-x', 'overflow-y',
         'box-shadow', 'border-collapse', 'border-spacing', 'cursor', 'opacity', 'fill', 'stroke', 'outline-style',
         'float', 'visibility']

PROBE = """<script>addEventListener('load',function(){setTimeout(function(){var P=%s,o={};
[].forEach.call(document.querySelectorAll('.ldiff,.ldiff *'),function(e,k){var c=getComputedStyle(e);
 o[k+' '+e.tagName.toLowerCase()+(e.getAttribute('class')?'.'+e.getAttribute('class').trim().split(/\\s+/).join('.'):'')]=
 P.map(function(p){return c.getPropertyValue(p)})});
var x=document.createElement('pre');x.id='ldiff-styles';
x.textContent=JSON.stringify([document.querySelector('.ldiff').getBoundingClientRect().width,o]);document.body.appendChild(x)},0)})
</script>""" % json.dumps(PROPS)


def browser():
    sys.path.insert(0, os.path.join(ROOT, 'TiaHmiGenerator'))
    try:
        from hmipreview.edge import Edge, edge_path
    except ImportError:
        return None
    return Edge() if edge_path() else None


def plant_fragment(folder):
    """The fragment of fixtures\\plant v1 -> v2: summary, interface tables, LAD and SCL networks."""
    import contextlib
    import io
    from TiaChangeReports import __main__ as cli
    plant = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'plant')
    out = os.path.join(folder, 'plant.fragment.html')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cli.main([os.path.join(plant, 'v1'), os.path.join(plant, 'v2'), '-o', out, '--fragment'])
    with open(out, encoding='utf-8') as f:
        return f.read()


def bare(fragment, width):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>bare</title></head><body>'
            '<div style="width:%spx">%s</div></body></html>' % (width, fragment))


def styles(edge, page, folder, name='page.html'):
    """page: HTML with one .ldiff, written to folder/name and opened in a 1400 x 900 window."""
    i = page.rfind('</body>')
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page[:i] + PROBE + page[i:] if i >= 0 else page + PROBE)
    dom = edge.dump_dom(Path(path).as_uri(), size=(1400, 900))
    m = re.search(r'<pre id="ldiff-styles">(.*?)</pre>', dom, re.S)
    if not m:
        raise AssertionError('no styles from Edge for %s' % path)
    return tuple(json.loads(unescape(m.group(1))))


def differences(a, b):
    out = {}
    for k in sorted(set(a) | set(b), key=lambda k: int(k.split(' ')[0])):
        if k not in a or k not in b:
            out[k] = 'only in %s' % ('the first' if k in a else 'the second')
            continue
        d = {p: (x, y) for p, x, y in zip(PROPS, a[k], b[k]) if x != y}
        if d:
            out[k] = d
    return out


def summary(diffs):
    """The differences per element kind (tag and classes), the first seen of each property: a readable failure."""
    kinds = {}
    for k, d in diffs.items():
        kind = kinds.setdefault(k.split(' ', 1)[-1], {})
        for p, v in (d.items() if isinstance(d, dict) else [('-', d)]):
            kind.setdefault(p, v)
    return json.dumps(kinds, indent=1)[:4000]
