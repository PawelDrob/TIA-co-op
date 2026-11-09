"""Self-check of the drawing: read the logic back from what is drawn and compare it with the parsed network.

check(layout) -> [problem text]:
- connectivity: the nets formed by the drawn lines (a line ending on another line joins it; a terminal on a line
  joins it) must correspond one to one with the nodes of the parsed graph, for every element input, output and
  logic-fed box pin;
- crossing: two lines crossing without a junction (TIA never draws that; it would read as a connection);
- dangling: a drawn line that connects to no element;
- overlap: two elements (with their texts) overlapping; a line running through an element.

python -m TiaChangeReports.verify <export.s7dcl | export.xml | folder> ...   (from the repo root) checks every LAD network,
OBs and other SimaticML exports included.
"""
import argparse
import os
import sys

from .diff import RAIL, SINK
from .render_lad import Layout


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _on(px, py, s, eps=0.6):
    x1, y1, x2, y2 = s
    if abs(y1 - y2) < eps:                                         # horizontal
        return abs(py - y1) < eps and min(x1, x2) - eps <= px <= max(x1, x2) + eps
    return abs(px - x1) < eps and min(y1, y2) - eps <= py <= max(y1, y2) + eps


def _interior(px, py, s, eps=0.6):
    x1, y1, x2, y2 = s
    if abs(y1 - y2) < eps:
        return abs(py - y1) < eps and min(x1, x2) + eps < px < max(x1, x2) - eps
    return abs(px - x1) < eps and min(y1, y2) + eps < py < max(y1, y2) - eps


def check(lay):
    probs = []
    segs, terms = lay.wiring()
    segs = [s for s in segs if abs(s[0] - s[2]) > 0.01 or abs(s[1] - s[3]) > 0.01]
    uf = _UF()
    for k, s in enumerate(segs):
        uf.find(('s', k))
    for a in range(len(segs)):
        sa = segs[a]
        for b in range(a + 1, len(segs)):
            sb = segs[b]
            ends_a = [(sa[0], sa[1]), (sa[2], sa[3])]
            ends_b = [(sb[0], sb[1]), (sb[2], sb[3])]
            if any(_on(px, py, sb) for px, py in ends_a) or any(_on(px, py, sa) for px, py in ends_b):
                uf.union(('s', a), ('s', b))
                continue
            ha, hb = abs(sa[1] - sa[3]) < .01, abs(sb[1] - sb[3]) < .01
            if ha != hb:
                h, v = (sa, sb) if ha else (sb, sa)
                if _interior(v[0], h[1], h) and _interior(v[0], h[1], v):
                    probs.append('crossing without junction at (%.0f, %.0f)' % (v[0], h[1]))
    for t in terms:
        kind, eid, pin, px, py = t
        key = ('t', kind, eid, pin)
        uf.find(key)
        for k, s in enumerate(segs):
            if _on(px, py, s):
                uf.union(key, ('s', k))
        for t2 in terms:
            if t2 is not t and abs(t2[3] - px) < .6 and abs(t2[4] - py) < .6:
                uf.union(key, ('t', t2[0], t2[1], t2[2]))
    # expected: graph node of every terminal
    g = lay.g
    nodes = _UF()
    for e, s, d in g.edges:
        if e is None:
            nodes.union(g.find(s), g.find(d))                       # bare wire: one net
    expect = {}
    for e, s, d in g.edges:
        if e is not None:
            expect[('t', 'in', e.eid, None)] = nodes.find(g.find(s))
            expect[('t', 'out', e.eid, None)] = nodes.find(g.find(d))
    for e, pin, n in g.pins:
        expect[('t', 'pin', e.eid, pin)] = nodes.find(g.find(n))
    rail = nodes.find(g.find(RAIL))
    sink = nodes.find(g.find(SINK))
    node_nets, net_nodes = {}, {}
    rail_net = uf.find(('s', 0))
    node_nets.setdefault(rail, set()).add(rail_net)
    net_nodes.setdefault(rail_net, set()).add(rail)
    for key, node in expect.items():
        if key not in uf.p:
            probs.append('terminal not drawn: %s' % (key,))
            continue
        net = uf.find(key)
        node_nets.setdefault(node, set()).add(net)
        net_nodes.setdefault(net, set()).add(node)
    names = {e.eid: e for e in g.elements.values()}

    def who(node):
        return 'rail' if node == rail else ('end of rung' if node == sink else 'wire#%s' % node)
    for node, nets in node_nets.items():
        if node != sink and len(nets) > 1:
            probs.append('%s drawn as %d separate pieces' % (who(node), len(nets)))
    for net, ns in net_nodes.items():
        if len(ns) > 1 and not (ns <= {sink}):
            probs.append('drawing joins %s' % ' + '.join(sorted(who(n) for n in ns)))
    used = {uf.find(k) for k in expect if k in uf.p} | {rail_net}
    for k in range(len(segs)):
        if uf.find(('s', k)) not in used:
            probs.append('dangling line (%.0f,%.0f)-(%.0f,%.0f)' % segs[k])
    # overlaps
    rects = []
    for k, i in enumerate(lay.info):
        y = lay.ys[k]
        for p in i['placed']:
            if not isinstance(p[0], str):
                v = lay.views[p[0].eid]
                rects.append((p[1] + 1, y - v.above + 1, p[1] + v.w - 1, y + v.below - 1, p[0].eid, y))
    for a in range(len(rects)):
        for b in range(a + 1, len(rects)):
            ra, rb = rects[a], rects[b]
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                probs.append('overlap: %s / %s' % (_name(names[ra[4]]), _name(names[rb[4]])))
    pins = {(t[3], t[4]) for t in terms if t[0] == 'pin'}
    for s in segs:
        if (s[0], s[1]) in pins or (s[2], s[3]) in pins:
            continue
        for x1, y1, x2, y2, eid, ey in rects:
            if abs(s[1] - s[3]) < .01:                               # horizontal
                if abs(s[1] - ey) > .6 and y1 + 2 < s[1] < y2 - 2 and min(s[0], s[2]) < x2 - 2 and max(s[0], s[2]) > x1 + 2:
                    probs.append('line through %s' % _name(names[eid]))
            elif x1 + 2 < s[0] < x2 - 2 and min(s[1], s[3]) < y2 - 2 and max(s[1], s[3]) > y1 + 2:
                probs.append('line through %s' % _name(names[eid]))
    return probs


def _name(e):
    op = e.operand() if e.kind in ('contact', 'coil') else (e.call or e.instance or '')
    return '%s(%s)' % (e.instr, op[:40])


def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from TiaChangeReports.s7dcl import parse_block
    from TiaChangeReports.compare import Callees
    from TiaChangeReports.source import FolderSnapshot, from_file
    p = argparse.ArgumentParser(prog='python -m TiaChangeReports.verify',
                                usage='%(prog)s <export.s7dcl | export.xml | folder> ...',
                                description='Checks every LAD network: the drawing read back against the code.')
    p.add_argument('paths', nargs='*', help='export file or folder (SimaticML exports included)')
    argv = p.parse_args(argv).paths
    if not argv:
        print('nothing to check: give export files or folders', file=sys.stderr)
        return 2
    for a in argv:
        if not os.path.exists(a):
            print('neither an export file nor a folder: %s' % a, file=sys.stderr)
            return 2
    files = []                                                        # (file, interfaces of the blocks it calls)
    for a in argv:
        if os.path.isdir(a):
            snap = FolderSnapshot(a)                                  # .s7dcl and SimaticML (OB) exports
            callees = Callees(snap)
            files += [(os.path.join(snap.root, p), callees.at(p)) for p in snap.paths()]
        else:
            files.append((a, None))
    seen = set()
    total = bad = 0
    kinds = {}
    for f, callees in sorted(files, key=lambda fc: fc[0]):
        src = from_file(f)
        if (src.s7dcl, src.xml) in seen:
            continue
        seen.add((src.s7dcl, src.xml))
        try:
            blk = parse_block(src)
        except Exception as ex:                                       # noqa: BLE001 - report and go on
            print('PARSE %s: %s' % (f, ex))
            continue
        for n in blk.networks:
            if n.rungs is None:
                continue
            total += 1
            try:
                probs = check(Layout(n.rungs, blk.interface, callees))
            except Exception as ex:                                   # noqa: BLE001
                probs = ['layout failed: %r' % ex]
            if probs:
                bad += 1
                for p in sorted(set(probs)):
                    kinds.setdefault(p.split(':')[0].split(' at ')[0].split(' (')[0], []).append(
                        '%s NW%d %s' % (os.path.basename(f), n.index, p))
    print('%d LAD networks, %d with problems' % (total, bad))
    for k, v in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
        print('  %4d  %s' % (len(v), k))
        for line in v[:4]:
            print('          ' + line)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')   # a pipe on Windows is cp1252
    sys.exit(main(sys.argv[1:]))
