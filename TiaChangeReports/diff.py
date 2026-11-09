"""Logic diff of two LAD networks, independent of wire names.

A network is a graph: elements are edges between nodes (wire#wN, anonymous points between series elements, the power
rail, and one virtual sink where rungs end in their last element). Series-parallel reduction turns it into a tree (S =
series list, P = parallel set, leaf = element). Two trees are compared recursively: series children aligned in order
(dynamic programming), parallel branches paired by the elements they share. Result per element: same / changed (same
instruction, other operands) / added / removed, and a pair id that links an element of the before network to its partner
in the after network. The same elements connected otherwise are another logic: those elements are moved: both wires
whole in a plain swap of two wires between pins (_swapped_wires), else the fewest that leave every node a partner,
beside other changes too (_reconnected); wire names and the order of the rungs do not count. The order of the branches
is no logic but it shows in TIA: the branches out of the common order are marked moved too, see NetDiff._order.

Box inputs fed by logic ('clk := wire#w1') are sinks of their own: the logic that reaches such a pin node is reduced
to its own tree, and the trees of a pin are compared when the two boxes pair up.
"""
import itertools
import re
from collections import Counter

from .s7dcl import _norm, norm_expression, wire_of

RAIL, SINK = 'powerrail', '#sink'
PAIRS = 12          # NetDiff._reconnected tries any two of at most this many items, or exchanges, at once


class Graph:
    def __init__(self, rungs):
        self.parent = {}
        self.edges = []          # (element, src, dst) with raw node keys; resolve with find()
        self.elements = {}
        self.pins = []           # (element, pin name, raw node) for inputs fed by logic
        self.rung_of = {}        # element id -> its rung
        self.rung_texts = []     # per rung: its start, elements and wires and end as text, wire names included
        self.place_of = {}       # element id -> (its rung's start, its rung's end, its number among the rung's elements)
        self.rung_shapes = []    # per rung: (from the rail, the wires on its way, ends at a wire), no wire named
        self.parts = []          # [element ids]: the runs of elements between two wires, in the order of the text
        anon = 0
        for k, r in enumerate(rungs):
            self.rung_texts.append(repr((r.start, [it[1] if isinstance(it, tuple) else it.sig() for it in r.items], r.end)))
            self.rung_shapes.append((r.start == RAIL, sum(isinstance(it, tuple) for it in r.items), bool(r.end)))
            cur = r.start
            has_el = False
            part = None                                       # a wire, or the rung's start, opens a new one
            for it in r.items:
                if isinstance(it, tuple):
                    self.union(cur, it[1])
                    cur = it[1]
                    part = None
                else:
                    if part is None:
                        part = []
                        self.parts.append(part)
                    part.append(it.eid)
                    anon += 1
                    a = '#a%d' % anon
                    self.edges.append((it, cur, a))
                    self.elements[it.eid] = it
                    self.rung_of[it.eid] = k
                    self.place_of[it.eid] = (r.start, r.end, sum(1 for x in self.rung_of.values() if x == k))
                    for n, d, v in it.params:
                        if wire_of(v) is not None:
                            self.pins.append((it, n, wire_of(v)))
                    cur = a
                    has_el = True
            if r.end and not has_el and cur == r.start:
                self.edges.append((None, cur, r.end))            # bare wire: a branch without elements
            elif r.end:
                self.union(cur, r.end)
            elif has_el or cur != r.start:
                self.union(cur, SINK)

    def find(self, x):
        p = self.parent.get(x, x)
        if p == x:
            return x
        r = self.find(p)
        self.parent[x] = r
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # keep the meaningful name as representative: rail / sink > named wire > anonymous
        def rank(n):
            return 3 if n in (RAIL, SINK) else (1 if n.startswith('#a') else 2)
        if rank(ra) < rank(rb):
            ra, rb = rb, ra
        self.parent[rb] = ra


def _reduce(edges, keep):
    """Series-parallel reduction of [(src, dst, tree)]; nodes in `keep` are never merged away."""
    changed = True
    while changed and len(edges) > 1:
        changed = False
        groups = {}
        for i, (s, d, t) in enumerate(edges):
            groups.setdefault((s, d), []).append(i)
        for key, idx in groups.items():
            if len(idx) > 1:
                kids = []
                for i in idx:
                    t = edges[i][2]
                    kids.extend(t[1] if t[0] == 'P' else [t])
                edges = [e for i, e in enumerate(edges) if i not in idx] + [(key[0], key[1], ('P', kids))]
                changed = True
                break
        if changed:
            continue
        indeg, outdeg = Counter(d for _, d, _ in edges), Counter(s for s, _, _ in edges)
        for v in dict.fromkeys(n for s, d, _ in edges for n in (s, d)):      # in edge order: same result every run
            if v in keep or indeg[v] != 1 or outdeg[v] != 1:
                continue
            i = next(k for k, e in enumerate(edges) if e[1] == v)
            j = next(k for k, e in enumerate(edges) if e[0] == v)
            a, b = edges[i][2], edges[j][2]
            kids = (a[1] if a[0] == 'S' else [a]) + (b[1] if b[0] == 'S' else [b])
            new = (edges[i][0], edges[j][1], ('S', kids))
            edges = [e for k, e in enumerate(edges) if k not in (i, j)] + [new]
            changed = True
            break
    if not edges:
        return ('S', [])
    if len(edges) == 1:
        return edges[0][2]
    return ('P', [t for _, _, t in edges])          # not series-parallel: what is left, side by side


def sp_forest(g):
    """(tree of the rung flow, {(eid, pin): tree of the logic feeding that pin}).

    Trees: ('L', eid) | ('S', [..]) | ('P', [..]) | ('E',) (bare wire). Each sink takes the edges that reach it and
    that no earlier sink took: first the end of the rungs, then the box pins in order."""
    all_edges = [(g.find(s), g.find(d), ('L', e.eid) if e else ('E',)) for e, s, d in g.edges]
    rail = g.find(RAIL)
    pin_nodes = [(e.eid, pin, g.find(n)) for e, pin, n in g.pins]
    sinks = [(None, None, g.find(SINK))] + pin_nodes
    keep = {rail} | {t for _, _, t in sinks}
    taken = set()
    main, pins = ('S', []), {}
    for eid, pin, t in sinks:
        reach, grow = {t}, True
        while grow:
            grow = False
            for s, d, _ in all_edges:
                if d in reach and s not in reach:
                    reach.add(s)
                    grow = True
        idx = [i for i, (s, d, _) in enumerate(all_edges) if d in reach and i not in taken]
        taken.update(idx)
        tree = _reduce([all_edges[i] for i in idx], keep)
        if eid is None:
            main = tree
        else:
            pins[eid, pin] = tree
    return main, pins


def sp_tree(g):
    return sp_forest(g)[0]


def _without(g, eid):
    """g with the element eid deleted from its rung: the nodes on its two sides become one."""
    h = Graph.__new__(Graph)
    h.parent = dict(g.parent)
    h.edges = [x for x in g.edges if not (x[0] and x[0].eid == eid)]
    h.elements = {k: v for k, v in g.elements.items() if k != eid}
    h.pins = list(g.pins)
    h.rung_of = {k: v for k, v in g.rung_of.items() if k != eid}
    h.rung_texts, h.place_of, h.rung_shapes = g.rung_texts, g.place_of, g.rung_shapes
    (_, s, d), = [x for x in g.edges if x[0] and x[0].eid == eid]
    h.union(s, d)
    return h


def more_differs(x, y):
    """A type template of a SimaticML export that both elements hold and that differs. One holding it alone says nothing: a
    .s7dcl does not write them."""
    return any(x.more[k] != y.more[k] for k in x.more if k in y.more)


def changed_params(x, y):
    """What differs between two paired elements: pin names (lower case), '#k' for the k-th unnamed parameter (the
    operand of a contact or coil), 'templates' when their templates differ (the relation of a Switch case: that
    case's pin, 'case1'), 'expression' (Calculate), 'eno' (ENO generated or not), '#call' (the called block: a pin
    cannot be named so), '#instr' (another instruction: the relation of a compare, the kind of a contact or coil).
    Wire names do not count."""
    def keyed(e):
        return {(n.lower() if n else '#%d' % k): (d or '', _norm(v)) for k, (n, d, v) in enumerate(e.params)}
    kx, ky = keyed(x), keyed(y)
    out = {k for k in list(kx) + list(ky) if kx.get(k) != ky.get(k)}
    for t in set(x.templates) | set(y.templates):
        if x.templates.get(t) != y.templates.get(t):
            out.add(t.lower() if re.match(r'CASE\d+$', t) else 'templates')
    if norm_expression(x.expression) != norm_expression(y.expression):
        out.add('expression')
    if x.no_eno != y.no_eno:
        out.add('eno')
    if x.call != y.call:
        out.add('#call')
    if x.instr != y.instr:
        out.add('#instr')
    if more_differs(x, y):
        out.add('templates')
    return out


def renamed_call(x, y):
    """Two elements that can be one call of a renamed block: calls of another name, of the same instance if any,
    with at least half of their pins in common (another block with other pins is a call replaced)."""
    if x.instr != 'CALL' or y.instr != 'CALL' or x.instance != y.instance or x.call == y.call:
        return False
    px, py = ({(n or '').lower() for n, _, _ in e.params if n} for e in (x, y))
    return 2 * len(px & py) >= max(len(px), len(py))


def _joined(g):
    """The nodes of a network with each bare wire as one node."""
    uf = Graph.__new__(Graph)
    uf.parent = dict(g.parent)
    for e, s, d in g.edges:
        if e is None:
            uf.union(s, d)
    return uf


def _nodes(g, exchange={}):
    """{node: [(element id, its end there)]} of a network, the rail and the end of the rungs marked, bare wires as one
    node: what is connected to what, whatever the wires are named and the rungs' order. exchange: {(box id, pin in lower
    case): the pin that stands there instead}."""
    uf = _joined(g)
    nodes = {uf.find(RAIL): [('#rail', '')], uf.find(SINK): [('#sink', '')]}
    for e, s, d in g.edges:
        if e is not None:
            nodes.setdefault(uf.find(s), []).append((e.eid, 'in'))
            nodes.setdefault(uf.find(d), []).append((e.eid, 'out'))
    for e, pin, n in g.pins:
        box, name = exchange.get((e.eid, (pin or '').lower()), (e.eid, (pin or '').lower()))
        nodes.setdefault(uf.find(n), []).append((box, 'pin ' + name))
    return nodes


def _feeds(g, key):
    """{element id: {(key(box id), pin)}}: the box pins each element of a network feeds, on the way from the rail to the
    pin, also through the pins of a box on that way; pin in lower case. key names a box the same way in the two versions
    compared."""
    uf = _joined(g)
    ends = [(e.eid, uf.find(s), uf.find(d)) for e, s, d in g.edges if e is not None]
    inputs = _pin_nodes(g, uf)
    out = {e: set() for e, _, _ in ends}
    for e, pin, n in g.pins:
        for x in _before_node(ends, inputs, uf.find(n)):
            out[x].add((key(e.eid), (pin or '').lower()))
    return out


def _pin_nodes(g, uf):
    """{box id: [the nodes of its pins]}."""
    out = {}
    for e, _, n in g.pins:
        out.setdefault(e.eid, []).append(uf.find(n))
    return out


def _before_node(ends, inputs, node):
    """The elements on the way from the rail to a node, through the pins of a box as through its rung. ends: [(element id,
    node it starts at, node it ends at)]; inputs: _pin_nodes."""
    reach, todo = set(), [node]
    while todo:
        n = todo.pop()
        if n not in reach:
            reach.add(n)
            for x, s, d in ends:
                if d == n:
                    todo.append(s)
                    todo.extend(inputs.get(x, ()))
    return [x for x, _, d in ends if d in reach]


def _stays(g, feeds, swapped):
    """The elements that do not move with a wire they feed: what stands before a tap whose rung goes on past it to something
    other than a pin, of whatever kind, and what feeds a pin of such a box. So what feeds no pin, the boxes in swapped, whose
    pins they are, and all that stands before these or before the end of the rungs. A wire whose every way ends at a pin moves
    whole, with its contacts, calls, edges and boxes. The pins of the boxes in swapped are the wires themselves: what feeds
    them does not stay for that box's sake. _feeds gives feeds."""
    uf = _joined(g)
    ends = [(e.eid, uf.find(s), uf.find(d)) for e, s, d in g.edges if e is not None]
    inputs = _pin_nodes(g, uf)
    stays = {e for e, _, _ in ends if not feeds[e]} | set(swapped)
    grew = True
    while grew:
        starts = {s for e, s, _ in ends if e in stays} | {uf.find(SINK)}
        starts.update(n for e in stays - swapped if feeds[e] for n in inputs.get(e, ()))
        more = {e for e, _, d in ends if d in starts} - stays
        stays |= more
        grew = bool(more)
    return stays


def _wire(g, feeds, stays, pin, other_pin):
    """The elements of the wire of a pin, in the order of the text, as a swap with other_pin moves it: those that feed the
    pin, not what feeds both and not what stays (_stays)."""
    return [e for e in g.elements if pin in feeds[e] and other_pin not in feeds[e] and e not in stays]


def _wiring(g, names, exchange={}):
    """The connections of a network as a value to compare, by what the elements are, not by their ids: each element and
    node in turn takes on what it touches (equal elements in equal places are equal; which is which is no connection).
    names: {text: number}, shared by the two networks compared. exchange: as in _nodes."""
    nodes = _nodes(g, exchange)
    color = {e: names.setdefault(repr(el.sig()), len(names)) for e, el in g.elements.items()}
    color.update({'#rail': -1, '#sink': -2})
    for _ in range(min(len(g.elements) + 1, 12)):
        ncolor = {n: names.setdefault(repr(sorted((color[e], end) for e, end in items)), len(names))
                  for n, items in nodes.items()}
        touched = {e: [] for e in color}
        for n, items in nodes.items():
            for e, end in items:
                touched[e].append((end, ncolor[n]))
        color = {e: names.setdefault(repr((color[e], sorted(t))), len(names)) for e, t in touched.items()}
    return Counter(color.values())


def _left_over(left, right, weigh=lambda x, y, shared: len(shared)):
    """What is not shared between two lists of groups, each group paired with the one it shares most with: weigh(place
    left, place right, shared items) tells how much a pair counts."""
    left, right = list(left), list(right)
    out = set()
    for x, y in sorted(((x, y) for x in range(len(left)) for y in range(len(right))),
                       key=lambda c: -weigh(c[0], c[1], left[c[0]] & right[c[1]])):
        if left[x] is not None and right[y] is not None:
            out |= left[x] ^ right[y]
            left[x] = right[y] = None
    return out | {i for side in (left, right) for items in side if items for i in items}


def out_of_order(places):
    """places: where each item stands in the other version, in this version's order. For each item: is it out of the
    longest common order, i.e. not in every longest run in the same order on both sides? Moved past others, both of two
    swapped, not those whose numbers only shift."""
    n = len(places)
    up, down = [1] * n, [1] * n                               # longest run ending at k, ... starting at k
    for k in range(n):
        up[k] += max((up[i] for i in range(k) if places[i] < places[k]), default=0)
    for k in range(n - 1, -1, -1):
        down[k] += max((down[i] for i in range(k + 1, n) if places[i] > places[k]), default=0)
    longest = max(up, default=0)
    on = [k for k in range(n) if up[k] + down[k] - 1 == longest]       # in some longest run
    at = Counter(up[k] for k in on)
    return [not (k in on and at[up[k]] == 1) for k in range(n)]


def _common_order(n, m, same):
    """[(i, j)]: a longest run in the same order in two lists of n and m items, same(i, j) telling which are one."""
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1], best[i + 1][j + 1] + 1 if same(i, j) else 0)
    out, i, j = [], 0, 0
    while i < n and j < m:
        if same(i, j) and best[i][j] == best[i + 1][j + 1] + 1:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def _part_ends(g):
    """[(the node a part starts at, the node it ends at)] of g.parts: per version, no wire's name is compared."""
    uf = _joined(g)
    at = {e.eid: (s, d) for e, s, d in g.edges if e is not None}
    return [(uf.find(at[p[0]][0]), uf.find(at[p[-1]][1])) for p in g.parts]


def leaves(t):
    if t[0] == 'L':
        return [t[1]]
    if t[0] in ('S', 'P'):
        return [x for k in t[1] for x in leaves(k)]
    return []


class NetDiff:
    """status[eid] in same / changed / added / removed / moved; pair[eid] = pair id shared by both partners;
    other[eid] = the partner element (for 'changed' tooltips). changed: the logic differs; reordered: branches stand in
    another order (_order), which is no change of the logic."""

    def __init__(self, before, after, merge=True):
        self.b, self.a = before, after          # Graph or None
        self.status, self.pair, self.other = {}, {}, {}
        self._n = 0
        self.pins_b = self.pins_a = {}
        self.reordered = False
        if before and after:
            mb, self.pins_b = sp_forest(before)
            ma, self.pins_a = sp_forest(after)
            self._diff(mb, ma)
            self._repair()
        self._unpaired()
        if merge and before and after:
            self._merge()
        if before and after:
            if not merge:                                     # a try of _merge, no network of its own: as before 192
                self._rewired(merge)
                self._other_settings()
            elif self._swapped_wires():
                self._other_settings()
            else:
                self._other_settings()
                if any(s != 'same' for s in self.status.values()):
                    self._reconnected(self._left_their_rung())
                else:
                    self._rewired()
        self.changed = any(s != 'same' for s in self.status.values())
        if merge and before and after:
            self._order()

    def _other_settings(self):
        """Alike but for a type setting: another setting is a change."""
        for e, o in self.other.items():
            if self.status.get(e) == 'same' and more_differs(self._el(e), o):
                self.status[e] = 'changed'

    def _unpaired(self):
        for g, st in ((self.b, 'removed'), (self.a, 'added')):
            if g:
                for eid in g.elements:
                    self.status.setdefault(eid, st)

    def _rewired(self, merge=True):
        """Every element paired and alike, but not connected alike: the moved elements _reconnected finds, the elements that
        left their rung tried among them. Where it finds none, as before it: the elements that left their rung, or else those
        whose end left the node it shares most with in the other network. merge=False: a try of _merge, which compares the
        cost of its tries without _reconnected."""
        if any(s != 'same' for s in self.status.values()) or len(self.b.elements) != len(self.a.elements):
            return
        names = {}
        if _wiring(self.b, names) == _wiring(self.a, names):
            return
        def after(item):
            return (self.other[item[0]].eid, item[1]) if item[0] in self.other else item
        left = self._left_their_rung(placed=merge)
        if merge and self._reconnected(left):
            return
        eids = {self.other[e].eid for e in left}
        if not eids:
            ends = _left_over([{after(i) for i in items} for items in _nodes(self.b).values()],
                              [set(items) for items in _nodes(self.a).values()])
            eids = {i[0] for i in ends if i[0] in self.a.elements} or set(self.a.elements)
        for e in eids:
            self.status[e] = self.status[self.other[e].eid] = 'moved'

    def _left_their_rung(self, placed=True):
        """The paired elements (ids before) that left their rung: each rung of paired elements matched with the rung after
        that shares the most of them, on a tie by what the two hold: the same shape (from the rail or a wire, the wires on
        its way, the end at a wire), then the same place. Rungs stand as one group where two share most with one rung
        only, each with the other, or where one is printed as rungs that hold its paired elements and no others. A rung's
        place is its group, or else the nearest group before it (or the start) and the paired elements in the rungs since,
        not counting those of that group. So a rung of elements of one version only does not shift it, nor one printed as
        rungs that hold its paired elements, wherever they stand; a contact moved between rungs before it does. Those not
        shared (_left_over). Elements of one version only do not count. placed=False: no tie, as without _reconnected."""
        def rungs(g, key):
            out = {}
            for e, k in g.rung_of.items():
                if e in self.pair:
                    out.setdefault(k, set()).add(key(e))
            return list(out.items())
        before, after = rungs(self.b, lambda e: self.other[e].eid), rungs(self.a, lambda e: e)
        shares = [[len(b & a) for _, a in after] for _, b in before]
        def most(row):
            top = max(row, default=0)
            return row.index(top) if top and row.count(top) == 1 else None
        ties = [(('b', x), ('a', y)) for x, row in enumerate(shares)        # rungs that share most with one rung
                if (y := most(row)) is not None and most([r[y] for r in shares]) == x]   # only, each with the other
        for side, other, mine, theirs, share in (('b', 'a', before, after, lambda x, y: shares[x][y]),
                                                 ('a', 'b', after, before, lambda x, y: shares[y][x])):
            for x, (_, items) in enumerate(mine):              # a rung printed as rungs that hold its elements alone
                halves = [y for y, (_, its) in enumerate(theirs) if its and share(x, y) == len(its)]
                if len(halves) > 1 and set().union(*(theirs[y][1] for y in halves)) == items:
                    ties += [((side, x), (other, y)) for y in halves]
        tied, parent = {k for pair in ties for k in pair}, {}
        def group(k):
            while k in parent:
                k = parent[k]
            return k
        for one, two in ties:
            if group(one) != group(two):
                parent[group(two)] = group(one)
        held = {}                                              # group -> the elements of its rungs, both versions
        for side, listed in (('b', before), ('a', after)):
            for x, (_, items) in enumerate(listed):
                if (side, x) in tied:
                    held.setdefault(group((side, x)), set()).update(items)
        def places(side, listed):              # (its group, -1), or (the group before it, paired elements since)
            out, last, since = [], None, 0
            for x, (_, items) in enumerate(listed):
                if (side, x) in tied:
                    if group((side, x)) != last:
                        last, since = group((side, x)), 0
                    out.append((last, -1))
                else:
                    out.append((last, since))
                    since += len(items - held.get(last, set()))
            return out
        place_b, place_a = places('b', before), places('a', after)
        def weigh(x, y, shared):
            return len(shared) + placed * (0.5 * (self.b.rung_shapes[before[x][0]] == self.a.rung_shapes[after[y][0]])
                                           + 0.25 * (place_b[x] == place_a[y]))
        left = _left_over([r for _, r in before], [r for _, r in after], weigh)
        return {self.other[e].eid for e in left if e in self.other}

    def _reconnected(self, reading=()):
        """Paired elements that stand at other nodes, beside other changes or not: the cheapest set of them, and of the
        pins of paired boxes, that taken out leaves every node one partner in the other version (_unexplained; a set is
        made whole by _explained). An element counts one, none if marked moved already, half more if it feeds the same
        pins after and they read the same logic (_pin_logic), on a tie less if it left its place (_kept); an input pin
        more than all elements (the wires of two pins exchanged are marked, not the box), three times that if it reads
        the same logic, whatever its wire's name, which an edit renumbers; an output pin half. Where reading, the
        elements that left their rung, leaves every node a partner with the pairs as found, it loses what the rest of it
        does not need (a rung printed as two moves nothing); if it then costs no more than what _repaired finds with
        equal elements paired otherwise, priced on _repaired's pairs, it is the set and nothing else is tried: these
        moved, as the text shows. Else, with _repaired's pairs, tried: what the matching of the nodes leaves beside what
        is marked moved already; reading with what it leaves, less what it does not need; items added one by one while
        that costs less; any two near a node left; each run of elements between two wires as one (_runs); each of these
        with the wires it moves whole (_whole). Then two pins whose wires the text exchanges as their wires' elements
        (_as_wires), the box for elements that stay by the rule of a plain swap (_by_pins), not for those of a reading
        that tells it all, and earlier moved marks that the rest makes needless go back to same (_needless), also when
        every node has its partner already; there the wires of what is marked move whole only where a stem goes with
        them (the maintainer's stem rule), a plain wire keeping the smaller reading. The elements found are marked
        moved, a box for its pin, and with them what moves with their wires (_whole). False if every node has its
        partner."""
        tie = 1 / (1 + len(self.b.elements))
        logic = self._pin_logic()
        read = lambda i: logic(i) is not None and logic(i)[0] == logic(i)[1]
        feeds, feeds_a = _feeds(self.b, lambda e: e), _feeds(self.a, lambda e: e)
        def steady(e):                       # it feeds the same pins after, and they read the same logic
            o = self.other.get(e)
            after = {(self.other[x].eid, pin) for x, pin in feeds_a[o.eid] if x in self.other} if o else None
            return bool(feeds[e]) and feeds[e] == after and all(read(pin + (False,)) for pin in feeds[e])
        def cost(items):
            return sum((self.status[i] != 'moved') * (1.5 if steady(i) else 1) + tie * self._kept(i, tie)
                       if not isinstance(i, tuple)
                       else 0.5 if i[2] else (1 + len(self.b.elements)) * (3 if read(i) else 1) for i in items)
        start = {e for e in self.b.elements if self.status[e] == 'moved'}
        links = self._links()
        reading = {e for e in reading if e in self.other}
        def trim(items, links):               # less what of reading the rest does not need: a rung printed as two
            for e in sorted(items & reading, key=list(self.b.elements).index):                  # moves nothing
                if not self._unexplained(links, items - {e}):
                    items = items - {e}
            return items
        told = bool(reading) and self._explained(links, start | reading) == start | reading   # with these pairs
        if told:
            reading = trim(start | reading, links) - start
        kept = dict(self.other), dict(self.pair), dict(self.status), links
        links, best = self._repaired(cost, start)
        if told and cost(start | reading) <= cost(best):     # the elements that left their rung tell it all, for no more
            self.other, self.pair, self.status, links = kept  # than other pairs would: they moved, nothing else is tried
            best = start | reading
        else:
            told = False
            reading = {e for e in reading if e in self.other}  # one of them may have lost its partner in _repaired
        if best == start:                     # every node has its partner: the wires of what is marked move whole
            best = self._needless(links, best, start)          # where a stem goes with them, by the maintainer's
            whole = self._whole(best)                          # stem rule; a plain wire keeps the smaller reading
            if any(len(feeds[e]) > 1 for e in whole):
                for e in whole:
                    if self.status[e] == 'same':
                        self.status[e] = self.status[self.other[e].eid] = 'moved'
            return False
        def total(gone):
            return self._explained(links, gone)
        def near(gone):
            nodes = self._unexplained(links, gone, nodes=True)
            return sorted({i for x, y, _, i in links if x in nodes[0] or y in nodes[1]} - gone, key=repr)
        pool = near(start)
        if not told:
            if reading:
                tried = trim(total(start | reading), links)
                if cost(tried) <= cost(best):
                    best = tried
            chosen = set(start)
            while True:
                step = min(((cost(total(chosen | {i})), k, i) for k, i in enumerate(near(chosen))), default=None)
                if step is None or step[0] >= cost(total(chosen)):
                    break
                chosen.add(step[2])
            if cost(total(chosen)) < cost(best):
                best = total(chosen)
            if len(pool) <= PAIRS:
                for items in itertools.combinations(pool, 2):
                    tried = total(start | set(items))
                    if cost(tried) < cost(best):
                        best = tried
            for run in self._runs():
                tried = total(start | run)
                if cost(tried) < cost(best):
                    best = tried
            for seed in (best, self._unexplained(links, start), reading):     # wires whole, which no single step reaches
                elements = start | {i for i in seed if not isinstance(i, tuple)}
                tried = elements | self._whole(elements)
                if total(tried) == tried and cost(tried) < cost(best):
                    best = tried
        best = self._as_wires(links, best, self._pin_wires(), logic)
        best = self._needless(links, self._by_pins(links, best, start | reading if told else start, pool), start)
        moved = {i[0] if isinstance(i, tuple) else i for i in best}
        for e in moved | self._whole(moved):
            if self.status[e] == 'same':
                self.status[e] = self.status[self.other[e].eid] = 'moved'
        return True

    def _pin_logic(self):
        """logic(pin item): (what feeds the pin before, what feeds it after) by the text, whatever its wire's name, at
        the box's partner then (_repaired may change it); None for a box with no partner. A pin that reads the same
        logic seldom moved."""
        def fed(g):
            out = {}
            for e, pins in _feeds(g, lambda e: e).items():
                for pin in pins:
                    out.setdefault(pin, Counter())[repr(g.elements[e].sig())] += 1
            return out
        before, after = fed(self.b), fed(self.a)
        def logic(item):
            o = self.other.get(item[0])
            return None if o is None else (before.get(item[:2], Counter()), after.get((o.eid, item[1]), Counter()))
        return logic

    def _pin_wires(self):
        """{(box id before, pin): (the wire it reads before, after)} by the text, for the pins of paired boxes."""
        def wires(e):
            return {(n or '').lower(): wire_of(v) for n, _, v in e.params if wire_of(v) is not None}
        out = {}
        for e in self.b.elements:
            o = self.other.get(e)
            if e in self.pair and o is not None:
                after = wires(o)
                for pin, w in wires(self.b.elements[e]).items():
                    out[e, pin] = (w, after.get(pin))
        return out

    def _as_wires(self, links, best, wired, logic):
        """best with two pins whose wires the text exchanges, of one box or of two, told as a plain swap tells them:
        by the elements of those wires, what stays by _stays left out; the two pins where each wire has
        elements of its own, and a pin left over that reads the same logic as before (logic: what feeds it, before and
        after), stay unmarked. Where these with the rest leave another
        node without a partner, as for a wire with nothing of its own, the pins stay too and the box is marked beside
        them."""
        pins = [i for i in best if isinstance(i, tuple) and not i[2]]
        feeds = _feeds(self.b, lambda e: e)
        for p, q in itertools.combinations(pins, 2):
            wp, wq = wired.get(p[:2]), wired.get(q[:2])
            if not wp or not wq or wp[0] == wq[0] or (wp[0], wq[0]) != (wq[1], wp[1]):
                continue
            stay = _stays(self.b, feeds, {p[0], q[0]})
            wires = {e for e in self.b.elements if e not in stay and feeds[e] & {p[:2], q[:2]}
                     and not {p[:2], q[:2]} <= feeds[e]}
            tried = (best - {p, q}) | wires
            left = self._explained(links, tried) - tried
            own = all(any(feeds[e] & {pin[:2]} for e in wires) for pin in (p, q))      # each wire has elements of its own
            if wires and all(i in (p, q) and own or isinstance(i, tuple) and not i[2] and logic(i)
                             and logic(i)[0] == logic(i)[1] for i in left):
                return tried
            return best | wires
        return best

    def _by_pins(self, links, best, kept, pool):
        """best with the box in place of its elements that stay by the rule of a plain swap (_stays: what stands before a
        tap that goes on to something other than a pin, what feeds a pin of such a box, what feeds no pin), where the
        input pins of pool with the rest of best leave every node a partner: as _swapped_wires marks the box for a wire
        with nothing of its own. Only the pins needed stay in; kept, what is marked moved already and a reading that
        tells it all, stays as it is."""
        stay = _stays(self.b, _feeds(self.b, lambda e: e), set())
        staying = {i for i in best if not isinstance(i, tuple) and i in stay and i not in kept}
        pins = [i for i in pool if isinstance(i, tuple) and not i[2]]
        if not staying or not pins:
            return best
        tried = (best - staying) | set(pins)
        if self._unexplained(links, tried):
            return best
        for pin in pins:
            if not self._unexplained(links, tried - {pin}):
                tried = tried - {pin}
        return tried

    def _needless(self, links, best, start):
        """best without the earlier moved marks (start) that the rest of it makes needless: of an element that kept its
        place and has no equal, the rest of best leaving every node a partner. Each one goes back to same."""
        alone = Counter(self._sig(e) for e in self.b.elements)
        for e in sorted(start, key=list(self.b.elements).index):
            if (e in best and self.status[e] == 'moved' and self.b.place_of[e] == self.a.place_of[self.other[e].eid]
                    and alone[self._sig(e)] == 1 and not self._unexplained(links, best - {e})):
                best = best - {e}
                self.status[e] = self.status[self.other[e].eid] = 'same'
        return best

    def _runs(self):
        """The runs of more than one paired element between two wires, of either version, as sets of ids before: a run
        that moved whole is told only with all of it taken out, which adding items one or two at a time does not
        reach."""
        runs = [{e for e in part if e in self.other} for part in self.b.parts]
        runs += [{self.other[e].eid for e in part if e in self.other} for part in self.a.parts]
        return [run for k, run in enumerate(runs) if len(run) > 1 and run not in runs[:k]]

    def _kept(self, e, tie):
        """How much of its place e keeps, to tell a tie of two readings: 1 for its place in its rung (start, end and number
        among the elements) as its partner's, and tie more for its rung's text as that of its partner's; wire names
        included, which an edit renumbers. The caller weighs it by tie, so all of it stays below one element."""
        o = self.other.get(e)
        if o is None:
            return 0
        g, h = self.b, self.a
        return ((g.place_of[e] == h.place_of[o.eid])
                + tie * (g.rung_texts[g.rung_of[e]] == h.rung_texts[h.rung_of[o.eid]]))

    def _repaired(self, cost, start):
        """(links, start made whole) with equal elements paired otherwise where that costs less: each round the best of
        one or two exchanges at once between equal elements at the nodes left, one of them maybe deleted or added
        (_exchange). A pair whose two rungs read alike stays a pair."""
        def total():
            links = self._links()
            return links, self._explained(links, start)
        links, best = total()
        if best == start:
            return links, best
        near = self._unexplained(links, start, nodes=True)
        moves = []
        for side, g in enumerate((self.b, self.a)):
            uf = self._joined_both()[side]
            at = {e.eid for e, s, d in g.edges if e is not None and (uf.find(s) in near[side] or uf.find(d) in near[side])}
            free = ('same', 'moved', ('removed', 'added')[side])
            h = (self.a, self.b)[side]
            settled = {e for e in g.elements if e in self.other                    # a pair whose two rungs read alike
                       and g.rung_texts[g.rung_of[e]] == h.rung_texts[h.rung_of[self.other[e].eid]]}   # stays a pair
            moves += [(g, x, x2) for x, x2 in itertools.combinations(g.elements, 2)
                      if (x in at or x2 in at) and self.status[x] in free and self.status[x2] in free
                      and {self.status[x], self.status[x2]} not in ({free[2]}, {free[2], 'moved'})
                      and not {x, x2} & settled and self._sig(x) == self._sig(x2)]
        moves, least = moves[:PAIRS], cost(best)
        for _ in range(len(moves)):                           # each round takes the best of one exchange or two
            if best == start:
                break
            pick = None
            for size in (1, 2):
                for tried in itertools.combinations(moves, size):
                    if not self._exchangeable(tried):
                        continue
                    for move in tried:
                        self._exchange(*move)
                    found = total()
                    price = cost(found[1])                    # read now, as an exchange moves the statuses it counts
                    if price < least and (pick is None or price < pick[0]):
                        pick = price, tried, found
                    for move in reversed(tried):
                        self._exchange(*move)
            if pick is None:
                break
            least, tried, (links, best) = pick
            for move in tried:
                self._exchange(*move)
        return links, best

    def _explained(self, links, gone):
        """gone with what it leaves unexplained, again until nothing is left: a set that leaves every node a partner.
        The elements left are taken first, pins only when no element is left."""
        gone = set(gone)
        while True:
            left = self._unexplained(links, gone) - gone
            if not left:
                return gone
            gone |= {i for i in left if not isinstance(i, tuple)} or left

    def _exchangeable(self, moves):
        """Exchanges that _exchange can make at once: of distinct elements, each with a partner on one side at least."""
        elements = [(g, e) for g, x, x2 in moves for e in (x, x2)]
        return len(set(elements)) == len(elements) and all(x in self.other or x2 in self.other for _, x, x2 in moves)

    def _exchange(self, g, x, x2):
        """Two equal elements of g take each other's partner, a partner taking the status of its new one; one of them may have
        none (deleted or added). Its own inverse."""
        alone = 'removed' if g is self.b else 'added'
        if self.status[x] == alone:
            x, x2 = x2, x
        y = self.other[x].eid
        if self.status[x2] == alone:
            self.other[x2], self.other[y], self.pair[x2] = self._el(y), self._el(x2), self.pair.pop(x)
            self.status[x2], self.status[x] = self.status[x], alone
            del self.other[x]
            return
        y2 = self.other[x2].eid
        self.other[x], self.other[x2], self.other[y], self.other[y2] = self._el(y2), self._el(y), self._el(x2), self._el(x)
        self.pair[y], self.pair[y2] = self.pair[x2], self.pair[x]
        self.status[y], self.status[y2] = self.status[x2], self.status[x]

    def _inner_points(self):
        """(before, after): the nodes inside a series of elements, where two element ends meet and nothing else: no pin,
        not the rail or the end of the rungs. An element taken out at such a node joins its two ends; one between two
        other nodes, as a branch alone, does not."""
        out = []
        for g, uf in zip((self.b, self.a), self._joined_both()):
            count = Counter(uf.find(n) for e, s, d in g.edges if e is not None for n in (s, d))
            other = {uf.find(n) for _, _, n in g.pins} | {uf.find(RAIL), uf.find(SINK)}
            out.append({n for n, k in count.items() if k == 2 and n not in other})
        return out

    def _joined_both(self):
        """_joined of the two versions, made once per diff."""
        if not hasattr(self, '_joined_pair'):
            self._joined_pair = _joined(self.b), _joined(self.a)
        return self._joined_pair

    def _links(self):
        """[(node before, node after, weight, item)]: each end of a paired element joins the node it stands at to the node its
        partner's end stands at (item: its id before), each pin of a paired box the node of its wire to that of its partner's
        (item: (box id before, pin, an output or not)); a pin weighs more than all the ends."""
        ub, ua = self._joined_both()
        at_a = {e.eid: (ua.find(s), ua.find(d)) for e, s, d in self.a.edges if e is not None}
        links = []
        for e, s, d in self.b.edges:
            if e is not None and e.eid in self.pair:
                y = self.other[e.eid].eid
                links += [(ub.find(s), at_a[y][0], 1, e.eid), (ub.find(d), at_a[y][1], 1, e.eid)]
        pins_a = {(e.eid, (p or '').lower()): ua.find(n) for e, p, n in self.a.pins}
        for e, p, n in self.b.pins:
            key = (self.other[e.eid].eid, (p or '').lower()) if e.eid in self.pair else None
            if key in pins_a:
                out = any(d == '=>' and (m or '').lower() == key[1] for m, d, _ in e.params)
                links.append((ub.find(n), pins_a[key], 1 + 2 * len(self.b.elements), (e.eid, key[1], out)))
        return links

    def _unexplained(self, links, gone, nodes=False):
        """The items of links that join two nodes that are no partners, with the items in gone taken out. Each node
        takes as its partner the node of the other version it shares the most weight with; the rail and the end of the
        rungs are partners. An element taken out, marked already, deleted or added is no item: its two ends are one node
        where taking it out made them one, that is where both reach one node of the other version, or one reaches none;
        the rail and the end of the rungs never become one node. An element taken out of both versions joins its ends in
        both where they stand inside a series, at no node a pin reads, and in each version an end reaches one of its
        partner's ends and the other that or an end of another taken out: the elements before and after it meet. It also
        joins them where its ends' links cross, inside a series or not: each end in one version goes only to the other
        end in the other, or, at the rail or the end of the rungs, to it among others (a contact moved off a tap).
        nodes: instead, ({nodes before}, {nodes after}) of the items left."""
        ub, ua = self._joined_both()
        links = [link for link in links if link[3] not in gone]
        merged = (Graph.__new__(Graph), Graph.__new__(Graph))
        merged[0].parent, merged[1].parent = {}, {}
        gone_a = {self.other[e].eid for e in gone if not isinstance(e, tuple)}
        at_a = {e.eid: (ua.find(s), ua.find(d)) for e, s, d in self.a.edges if e is not None}
        taken = ([(ub.find(s), ub.find(d)) for e, s, d in self.b.edges
                  if e is not None and (e.eid in gone or e.eid not in self.pair)],
                 [(ua.find(s), ua.find(d)) for e, s, d in self.a.edges
                  if e is not None and (e.eid in gone_a or e.eid not in self.pair)])
        inner = self._inner_points()
        read = ({ub.find(n) for _, _, n in self.b.pins}, {ua.find(n) for _, _, n in self.a.pins})   # nodes a pin reads
        both = [((ub.find(s), ub.find(d)), at_a[self.other[e.eid].eid]) for e, s, d in self.b.edges
                if e is not None and e.eid in gone]
        fixed = ((ub.find(RAIL), ub.find(SINK)), (ua.find(RAIL), ua.find(SINK)))
        def reach(side, x):
            return {merged[1 - side].find(link[1 - side]) for link in links if merged[side].find(link[side]) == x}
        def ends_of(side):
            return {merged[side].find(fixed[side][0]), merged[side].find(fixed[side][1])}
        def only(side, x, y):                     # x's links in side go to y alone; at the rail or the end of the
            r = reach(side, x)                    # rungs, to y among others
            return y in r if x in ends_of(side) else r == {y}
        grew = True
        while grew:
            grew = False
            for side in (0, 1):
                ends = ends_of(side)                      # the rail and the end of the rungs stay two
                for s, d in taken[side]:
                    x, y = merged[side].find(s), merged[side].find(d)
                    if x != y and {x, y} != ends:
                        rx, ry = reach(side, x), reach(side, y)
                        if not rx or not ry or rx & ry:
                            merged[side].union(x, y)
                            grew = True
            gone_ends = ({merged[0].find(n) for ends_b, _ in both for n in ends_b},
                         {merged[1].find(n) for _, ends_a in both for n in ends_a})
            for (s, d), (s_a, d_a) in both:
                x, y, x_a, y_a = merged[0].find(s), merged[0].find(d), merged[1].find(s_a), merged[1].find(d_a)
                def joins(side, one, two, ends):
                    r1, r2 = reach(side, one), reach(side, two)
                    return (r1 | r2) & ends and r1 & gone_ends[1 - side] and r2 & gone_ends[1 - side]
                if ((x != y or x_a != y_a) and {s, d} & inner[0] and {s_a, d_a} & inner[1]
                        and not {s, d} & read[0] and not {s_a, d_a} & read[1]
                        and joins(0, x, y, {x_a, y_a}) and joins(1, x_a, y_a, {x, y})):
                    merged[0].union(x, y)
                    merged[1].union(x_a, y_a)
                    grew = True
                elif (x != y and x_a != y_a and {x, y} != ends_of(0) and {x_a, y_a} != ends_of(1)
                      and only(0, x, y_a) and only(0, y, x_a) and only(1, x_a, y) and only(1, y_a, x)):   # crosswise
                    merged[0].union(x, y)
                    merged[1].union(x_a, y_a)
                    grew = True
        weight = Counter()
        for x, y, w, _ in links:
            weight[merged[0].find(x), merged[1].find(y)] += w
        partner = {merged[0].find(x): merged[1].find(y) for x, y in zip(*fixed)}
        for (x, y), _ in sorted(weight.items(), key=lambda c: -c[1]):
            if x not in partner and y not in partner.values():
                partner[x] = y
        left = [link for link in links if partner.get(merged[0].find(link[0])) != merged[1].find(link[1])]
        if nodes:
            return {x for x, _, _, _ in left}, {y for _, y, _, _ in left}
        return {i for _, _, _, i in left}

    def _whole(self, moved):
        """The elements that move with the wires of moved, before and after, as a plain swap moves them (_stays):
        one that feeds one pin of those wires, and, if it feeds more (a stem), other pins after than before and a
        wire that moved whole, every element that feeds that pin alone moved; and whose every way goes on through moved,
        or else to pins of other wires only, not on past a tap to something else. So a wire moves whole, and a stem with
        it that also feeds a pin that stayed (the maintainer, 2026-11-06), not a stem of two of those wires, and no stem
        where a contact only went from one pin's OR to another's. An element that feeds the pins it fed, and kept its
        number among its rung's elements or what ends where it starts, goes with no wire (contacts exchanged within the
        OR of one pin, the rung printed as two or not), unless an equal one feeds other pins: then the pairs do not tell
        which moved. A changed element on the way is passed as one of moved; only those alike are marked by the caller."""
        out = set()
        joined = self._joined_both()
        sides, starts = [], []
        for side, g in enumerate((self.b, self.a)):
            uf = joined[side]
            key = (lambda e: e) if side == 0 else (lambda e: self.other[e].eid if e in self.other else e)
            feeds = _feeds(g, key)
            nexts = {}
            for e, start, _ in g.edges:
                if e is not None:
                    nexts.setdefault(uf.find(start), []).append(e.eid)
            pins_at = {}
            for box, pin, n in g.pins:
                pins_at.setdefault(uf.find(n), set()).add((key(box.eid), (pin or '').lower()))
            sink = uf.find(SINK)
            ways = {e.eid: (None if uf.find(d) == sink else nexts.get(uf.find(d), []), pins_at.get(uf.find(d), set()))
                    for e, _, d in g.edges if e is not None}
            sides.append((g, key, feeds, ways))
            ending = {uf.find(RAIL): {RAIL}}             # node -> what ends there: the rail, elements (ids before)
            for e, _, d in g.edges:
                if e is not None:
                    ending.setdefault(uf.find(d), set()).add(key(e.eid) if e.eid in self.other else (side, e.eid))
            starts.append({e.eid: ending.get(uf.find(s), set()) for e, s, _ in g.edges if e is not None})
        partner = lambda e: self.other[e].eid if e in self.other else None
        rewired = {self._sig(x) for x in self.b.elements                 # equal elements of these may have taken
                   if sides[0][2][x] != sides[1][2].get(partner(x), set())}   # each other's partner
        wires = ({pin for e in moved for pin in sides[0][2].get(e, ())},
                 {pin for e in moved for pin in sides[1][2].get(partner(e), ())})
        stays = [_stays(g, feeds, {e for e in g.elements if key(e) in {box for box, _ in wires[side]}})
                 for side, (g, key, feeds, _) in enumerate(sides)]
        grew = True
        while grew:
            grew = False
            done = moved | out
            for e in self.b.elements:
                fed = sides[0][2][e]
                if e in done or self.status[e] in ('moved', 'removed'):
                    continue
                if (fed == sides[1][2][partner(e)] and self._sig(e) not in rewired
                        and (self.b.place_of[e][2] == self.a.place_of[partner(e)][2]
                             or starts[0][e] == starts[1][partner(e)])):   # it stayed and feeds the pins it fed
                    continue
                if len(fed) > 1 and any(x not in done for x in self.b.elements    # a stem whose wire did not move
                                        if sides[0][2][x] and sides[0][2][x] <= fed & wires[0]):   # whole stays
                    continue
                if all(self._goes_with(at, ways[at], feeds, key, done, wire, stay)
                       for at, (g, key, feeds, ways), wire, stay in zip((e, partner(e)), sides, wires, stays)):
                    out.add(e)
                    grew = True
                    break
        return out

    @staticmethod
    def _goes_with(e, way, feeds, key, done, wire, stay):
        """e of one version moves with the wires (_whole): wire, the pins of those wires in that version, and stay, what
        stays there by _stays; way, (the elements after e, None at the end of the rungs; the pins at its end). It feeds
        one of those pins, not at its own end, and its every way goes on through done or to other pins only."""
        way, ends_at = way
        if e in stay or len(feeds.get(e, set()) & wire) != 1 or not way or ends_at & wire:
            return False
        return (any(key(x) in done for x in way)
                and all(key(x) in done or (not feeds.get(x, set()) & wire and x not in stay) for x in way))

    def _swapped_wires(self):
        """Two pins that read each other's wire, and nothing else in the network changed: every element alike, and the
        network before with these two pins exchanged is the network after. Both wires are marked moved whole, and the
        box of each of the two pins (two when they are on two calls) where a wire has nothing of its own and the other's
        elements do not tell the move; told from each side's own feeds (_wire), not from the pairs, as equal elements on
        other wires may be paired with them. True if so. Two wires that differ by one contact (the rest of them alike,
        at most one contact of its own on each) are not this: the text is the same as that of the contact moved, which
        is the smaller reading, and _rewired tells that."""
        if (not self.b.pins or len(self.b.elements) != len(self.a.elements)
                or any(s not in ('same', 'moved') for s in self.status.values())):
            return False
        to = {e: o.eid for e, o in self.other.items() if e in self.b.elements}
        back = {y: x for x, y in to.items()}
        feeds_b, feeds_a = _feeds(self.b, to.get), _feeds(self.a, lambda e: e)
        def held(feeds):
            out = {}
            for e, pins in feeds.items():
                for pin in pins:
                    out.setdefault(pin, Counter())[repr(self._sig(e))] += 1
            return out
        was, now = held(feeds_b), held(feeds_a)
        other = [pin for pin in set(was) | set(now) if was.get(pin) != now.get(pin)]
        if len(other) != 2:
            return False
        first, second = other
        exchange = {(back[first[0]], first[1]): (back[second[0]], second[1]),
                    (back[second[0]], second[1]): (back[first[0]], first[1])}
        names = {}
        if _wiring(self.b, names, exchange) != _wiring(self.a, names):
            return False
        stays_b = _stays(self.b, feeds_b, {back[first[0]], back[second[0]]})
        stays_a = _stays(self.a, feeds_a, {first[0], second[0]})
        wires = ((_wire(self.b, feeds_b, stays_b, first, second), _wire(self.a, feeds_a, stays_a, second, first)),
                 (_wire(self.b, feeds_b, stays_b, second, first), _wire(self.a, feeds_a, stays_a, first, second)))
        def sigs(wire):
            return Counter(repr(self._sig(e)) for e in wire)
        if any(sigs(wire) != sigs(place) for wire, place in wires):
            return False
        x, y = sigs(wires[0][0]), sigs(wires[1][0])
        if (not x and not y) or (x & y and max(sum((x - y).values()), sum((y - x).values())) <= 1):
            return False
        moved, kept = self._pairs_of_wires(wires, to)
        if any(more_differs(self.b.elements[e], self.a.elements[o]) for e, o in {**moved, **kept}.items()):
            return False
        self.status = dict.fromkeys(self.status, 'same')
        for pairs, status in ((moved, 'moved'), (kept, 'same')):
            for e, partner in pairs.items():
                self._link(e, partner, status)
        if (not x or not y) and self._unexplained(self._links(), set(moved)):   # a wire with nothing of its own, and
            for box in {back[first[0]], back[second[0]]}:                       # the other's elements tell no move
                self.status[box] = self.status[self.other[box].eid] = 'moved'
        return True

    def _pairs_of_wires(self, wires, to):
        """({before: after} of the elements of a swap's wires, each paired in its order with those of the wire's place after;
        {before: after} of the others, one whose partner is now of a wire taking one left free, the rest keeping theirs)."""
        moved = {}
        for before, after in wires:
            free = list(after)
            for e in before:
                moved[e] = next(y for y in free if self._sig(y) == self._sig(e))
                free.remove(moved[e])
        taken = set(moved.values())
        rest = [e for e in to if e not in moved]
        kept = {e: to[e] for e in rest if to[e] not in taken}
        free = [y for y in self.a.elements if y not in taken and y not in set(kept.values())]
        for e in rest:
            if e not in kept:
                kept[e] = next(y for y in free if self._sig(y) == self._sig(e))
                free.remove(kept[e])
        return moved, kept

    # ---------------------------------------------------------------- the order of the branches
    def _at_the_same_wires(self, tb, ta, ends_b, ends_a):
        """same(part before, part after): the two are alike and stand at the same wires as far as known. The partner of a
        wire is known from the rail, the end of the rungs and the parts with one candidate, in turn; numbers do not count.
        Several partners stay possible: a rewiring is told by _wires_alike, not here."""
        ub, ua = _joined(self.b), _joined(self.a)
        partners = {ub.find(RAIL): {ua.find(RAIL)}, ub.find(SINK): {ua.find(SINK)}}
        taken = {ua.find(RAIL), ua.find(SINK)}

        def same(i, j):
            return tb[i] == ta[j] and all(y in partners[x] if x in partners else y not in taken
                                          for x, y in zip(ends_b[i], ends_a[j]))
        grew = True
        while grew:
            grew = False
            candidates = [(i, j) for i in range(len(tb)) for j in range(len(ta)) if same(i, j)]
            ci, cj = Counter(i for i, _ in candidates), Counter(j for _, j in candidates)
            for i, j in candidates:
                if ci[i] == cj[j] == 1:
                    for x, y in zip(ends_b[i], ends_a[j]):
                        if y not in partners.get(x, ()):
                            partners.setdefault(x, set()).add(y)
                            taken.add(y)
                            grew = True
        return same

    def _paired_parts(self, ends_b, ends_a):
        """[(part before, part after)] by their place in g.parts: the alike at the same wires in their longest common order,
        so that one of two equal parts changed, deleted or added crosses nothing and a copy at another node is another
        part; those left in turn, then the alike wherever they stand. Equal parts at the same wires take their places in
        ascending order: two of them are never swapped, no one could see it in TIA. Then those that share most elements,
        by the logic's pairs, a tie to the one in the same place."""
        bp, ap = self.b.parts, self.a.parts
        tb = [[self.b.elements[e].sig() for e in part] for part in bp]
        ta = [[self.a.elements[e].sig() for e in part] for part in ap]
        at_wires = self._at_the_same_wires(tb, ta, ends_b, ends_a)
        out = _common_order(len(bp), len(ap), at_wires)
        free_b = [i for i in range(len(bp)) if i not in {c[0] for c in out}]
        free_a = [j for j in range(len(ap)) if j not in {c[1] for c in out}]
        for same in (at_wires, lambda i, j: tb[i] == ta[j]):
            for j in list(free_a):
                i = next((i for i in free_b if same(i, j)), None)
                if i is not None:
                    free_b.remove(i)
                    free_a.remove(j)
                    out.append((i, j))
        equal = {}
        for i, j in out:
            equal.setdefault((tuple(tb[i]), ends_b[i], ends_a[j]), []).append((i, j))
        out = [c for s in equal.values() for c in zip(sorted(i for i, _ in s), sorted(j for _, j in s))]
        partner = {e: o.eid for e, o in self.other.items()}
        shared = {(i, j): len({partner.get(e) for e in bp[i]} & set(ap[j])) for i in free_b for j in free_a}
        for i, j in sorted((c for c in shared if shared[c]), key=lambda c: (-shared[c], abs(c[0] - c[1]), c)):
            if i in free_b and j in free_a:
                free_b.remove(i)
                free_a.remove(j)
                out.append((i, j))
        return out

    def _wires_alike(self, pairs, ends_b, ends_a):
        """Each wire has one partner in the other version, through the ends of the paired parts and the pins of the paired
        boxes (its number may differ, an order renumbers). Not so: something is connected otherwise."""
        ub, ua = _joined(self.b), _joined(self.a)
        seen = {(ub.find(RAIL), ua.find(RAIL)), (ub.find(SINK), ua.find(SINK))}
        for i, j in pairs:
            seen.update(zip(ends_b[i], ends_a[j]))
        pins = {(e.eid, (pin or '').lower()): n for e, pin, n in self.a.pins}
        for e, pin, n in self.b.pins:
            o = self.other.get(e.eid)
            n_a = pins.get((o.eid, (pin or '').lower())) if o else None
            if n_a:
                seen.add((ub.find(n), ua.find(n_a)))
        return len({b for b, _ in seen}) == len({a for _, a in seen}) == len(seen)

    def _order(self):
        """Branches that leave one node, or reach one node, in both versions have an order; those out of the common order
        are marked moved on both sides, an element marked otherwise keeps its mark. Not the order of the whole text: the
        coil after two parallel contacts stands between them there. Wire numbers follow the order and are not compared.
        A part already moved is connected otherwise, which is no order (two contacts swapped between two box pins). With
        another change _rewired does not tell that: reordered then needs _wires_alike, the marks stay; a rewiring must not
        read as an order."""
        ends_b, ends_a = _part_ends(self.b), _part_ends(self.a)
        paired = self._paired_parts(ends_b, ends_a)
        found = False
        pairs = sorted((c for c in paired
                        if not any(self.status[e] == 'moved' for e in self.b.parts[c[0]] + self.a.parts[c[1]])),
                       key=lambda c: c[1])
        for end in (0, 1):
            groups = {}
            for i, j in pairs:
                groups.setdefault((ends_b[i][end], ends_a[j][end]), []).append((i, j))
            for group in groups.values():
                for (i, j), out in zip(group, out_of_order([i for i, _ in group])):
                    if out:
                        found = True
                        for e in self.b.parts[i] + self.a.parts[j]:
                            if self.status[e] == 'same':
                                self.status[e] = 'moved'
        self.reordered = found and (not self.changed or self._wires_alike(paired, ends_b, ends_a))

    # ---------------------------------------------------------------- merged nodes
    def _merge(self):
        """Deleting an element that sits between two wire nodes makes them one node (inserting one splits a node).
        The logic around that node is then shaped differently and identical neighbours can come out 'moved'. While
        anything is 'moved', take each removed (added) element out of the before (after) graph, joining its two nodes
        as the deletion did, and keep the diff with the fewest changes: the merge is one change, its neighbours stay
        unmarked. A real move of an element stays: it is paired, so it is never taken out."""
        def cost(d):
            taken = len(self.b.elements) - len(d.b.elements) + len(self.a.elements) - len(d.a.elements)
            return taken + sum(1 for s in d.status.values() if s != 'same')
        cur = self
        while any(s == 'moved' for s in cur.status.values()):
            best = None
            for side, st in ((0, 'removed'), (1, 'added')):
                g = (cur.b, cur.a)[side]
                for e, s_, d in g.edges:
                    if (e is None or cur.status.get(e.eid) != st or g.find(s_) == g.find(d)
                            or any(p[0] is e for p in g.pins)):
                        continue
                    gs = [cur.b, cur.a]
                    gs[side] = _without(g, e.eid)
                    alt = NetDiff(*gs, merge=False)
                    if best is None or cost(alt) < cost(best):
                        best = alt
            if best is None or cost(best) >= cost(cur):
                break
            cur = best
        if cur is not self:
            self.status, self.pair, self.other = cur.status, cur.pair, cur.other
            self.pins_b, self.pins_a = cur.pins_b, cur.pins_a
            self._unpaired()                                      # the elements taken out: removed / added

    # ---------------------------------------------------------------- repair by connections
    def _context(self, g):
        """eid -> (predecessors, successors): neighbouring element ids, or the tokens RAIL / END / (PIN, box, pin)."""
        uf = _joined(g)
        rail, sink = uf.find(RAIL), uf.find(SINK)
        ins, outs = {}, {}
        ends = [(e, uf.find(s_), uf.find(d)) for e, s_, d in g.edges if e is not None]
        for e, s_, d in ends:
            outs.setdefault(s_, []).append(e.eid)
            ins.setdefault(d, []).append(e.eid)
        pins = {}
        for e, pin, n in g.pins:
            pins.setdefault(uf.find(n), []).append(('PIN', e.eid, pin))
        ctx = {}
        for e, s_, d in ends:
            pred = set(ins.get(s_, [])) | ({'RAIL'} if s_ == rail else set())
            succ = set(outs.get(d, [])) | ({'END'} if d == sink else set()) | set(pins.get(d, []))
            ctx[e.eid] = (pred, succ)
        return ctx

    def _anchored(self, x, y):
        """(pred, succ) neighbours of x whose partner is the matching neighbour of y."""
        px, sx = self._cb[x]
        py, sy = self._ca[y]

        def same(u, v):
            if isinstance(u, tuple) and isinstance(v, tuple):
                return u[0] == v[0] == 'PIN' and u[2] == v[2] and self._partner.get(u[1]) == v[1]
            if isinstance(u, str) and isinstance(v, str) and u in ('RAIL', 'END'):
                return u == v
            return self._partner.get(u) == v
        return (sum(1 for u in px if any(same(u, v) for v in py)),
                sum(1 for u in sx if any(same(u, v) for v in sy)))

    def _ctxsig(self, ids, g):
        return Counter(i if isinstance(i, str) else ('PIN', i[2]) if isinstance(i, tuple) else g.elements[i].sig()
                       for i in ids)

    def _repair(self):
        """The tree diff pairs by position in the series-parallel structure; a change that merges two wire nodes
        reshapes that structure. Re-check its pairs against the connections and pair what it left over."""
        self._cb, self._ca = self._context(self.b), self._context(self.a)
        self._partner = {}
        for e, o in self.other.items():
            if e in self.pair:
                self._partner[e] = o.eid
        bset, aset = list(self.b.elements), list(self.a.elements)          # lists: ties go the same way every run
        # 1. undo the pairs the structure alone decided: 'changed' ones, and identical ones without any paired
        #    neighbour (duplicates paired crosswise); the connection phases below pair them again
        tree_changed = {e: self._partner[e] for e in bset if self.status.get(e) == 'changed'}
        loose = [e for e in bset if self.status.get(e) == 'changed'
                 or (self.status.get(e) == 'same' and sum(self._anchored(e, self._partner[e])) == 0)]
        for x in loose:
            y = self._partner[x]
            for e in (x, y):
                self.status.pop(e, None)
                self.pair.pop(e, None)
                self.other.pop(e, None)
                self._partner.pop(e, None)
        # 2. identical leftovers, best connected first
        self._pair_phase(bset, aset, 'same')
        # 3. the tree's 'changed' pairs where both are still free and a neighbour is paired alike (repeated: a chain
        #    of changed contacts anchors itself one by one)
        grew = True
        while grew:
            grew = False
            for x, y in tree_changed.items():
                if x not in self._partner and y not in self._partner and sum(self._anchored(x, y)):
                    self._link(x, y, 'changed')
                    self._partner[x], self._partner[y] = y, x
                    grew = True
        # 4. other leftovers with the same instruction and a neighbour paired alike
        self._pair_phase(bset, aset, 'changed')
        self._pair_phase(bset, aset, 'renamed')
        # 5. identical but connected nowhere alike: moved to another place in the logic
        for x in [e for e in bset if self.status.get(e) == 'same']:
            y = self._partner[x]
            if sum(self._anchored(x, y)) == 0 and (self._cb[x][0] or self._cb[x][1]):
                self.status[x] = self.status[y] = 'moved'

    def _pair_phase(self, bset, aset, phase):
        """Pair leftovers greedily, best score first: 'same' = identical, 'changed' = same instruction with other
        operands and at least one neighbour paired alike, 'renamed' = as changed, a call of a renamed block (linked
        as changed)."""
        while True:
            lb = [e for e in bset if e not in self._partner]
            la = [e for e in aset if e not in self._partner]
            best = None
            for x in lb:
                ex = self.b.elements[x]
                for y in la:
                    ey = self.a.elements[y]
                    if phase == 'same' and ex.sig() != ey.sig():
                        continue
                    if phase == 'changed' and not (ex.instr == ey.instr and ex.instance == ey.instance
                                                   and ex.call == ey.call and ex.sig() != ey.sig()):
                        continue
                    if phase == 'renamed' and not renamed_call(ex, ey):
                        continue
                    ap, asucc = self._anchored(x, y)
                    if phase != 'same' and not (ap or asucc):
                        continue
                    loose = sum(sum((self._ctxsig(self._cb[x][k], self.b)
                                     & self._ctxsig(self._ca[y][k], self.a)).values()) for k in (0, 1))
                    score = (ap + asucc) * 10 + loose
                    if best is None or score > best[0]:
                        best = (score, x, y)
            if best is None:
                return
            _, x, y = best
            self._link(x, y, 'same' if phase == 'same' else 'changed')
            self._partner[x], self._partner[y] = y, x

    def _sig(self, eid):
        e = self.b.elements.get(eid) or self.a.elements.get(eid)
        return e.sig()

    def _el(self, eid):
        return self.b.elements.get(eid) or self.a.elements.get(eid)

    def _link(self, x, y, st):
        self._n += 1
        for e, o in ((x, y), (y, x)):
            self.status[e] = st
            self.pair[e] = 'p%d' % self._n
            self.other[e] = self._el(o)

    def _sim(self, x, y):
        if x[0] == 'E' or y[0] == 'E':
            return 1.0 if x[0] == y[0] else 0.0
        if x[0] == 'L' and y[0] == 'L':
            ex, ey = self._el(x[1]), self._el(y[1])
            if ex.sig() == ey.sig():
                return 1.0
            if ex.instr == ey.instr and ex.instance == ey.instance and ex.call == ey.call:
                return 0.4
            if renamed_call(ex, ey):
                return 0.3
            if ex.kind == ey.kind and ex.kind in ('contact', 'compare', 'coil'):
                return 0.2
            return 0.0
        cx = Counter(self._sig(e) for e in leaves(x))
        cy = Counter(self._sig(e) for e in leaves(y))
        common = sum((cx & cy).values())
        return common / max(1, max(sum(cx.values()), sum(cy.values()))) + (0.01 * common)

    def _diff(self, x, y):
        if x[0] == 'E' or y[0] == 'E':
            return
        if x[0] == 'L' and y[0] == 'L':
            ex, ey = self._el(x[1]), self._el(y[1])
            if ex.sig() == ey.sig():
                self._link(x[1], y[1], 'same')
            elif self._sim(x, y) > 0:
                self._link(x[1], y[1], 'changed')
            else:
                return
            for (eid, pin), tb in self.pins_b.items():         # logic feeding the pins of a paired box
                if eid == x[1] and (y[1], pin) in self.pins_a:
                    self._diff(tb, self.pins_a[y[1], pin])
            return
        if x[0] != y[0]:
            if 'S' in (x[0], y[0]):
                x = x if x[0] == 'S' else ('S', [x])
                y = y if y[0] == 'S' else ('S', [y])
            else:
                x = x if x[0] == 'P' else ('P', [x])
                y = y if y[0] == 'P' else ('P', [y])
        if x[0] == 'S':
            for i, j in self._align(x[1], y[1]):
                self._diff(x[1][i], y[1][j])
        else:
            pairs = sorted(((self._sim(p, q), i, j) for i, p in enumerate(x[1]) for j, q in enumerate(y[1])),
                           reverse=True)
            ui, uj = set(), set()
            for s, i, j in pairs:
                if s <= 0 or i in ui or j in uj:
                    continue
                ui.add(i)
                uj.add(j)
                self._diff(x[1][i], y[1][j])

    def _align(self, xs, ys):
        """Order-preserving pairing of two series lists with the highest total similarity."""
        n, m = len(xs), len(ys)
        sim = [[self._sim(p, q) for q in ys] for p in xs]
        best = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            for j in range(m - 1, -1, -1):
                best[i][j] = max(best[i + 1][j], best[i][j + 1],
                                 (best[i + 1][j + 1] + sim[i][j]) if sim[i][j] > 0 else -1)
        out, i, j = [], 0, 0
        while i < n and j < m:
            if sim[i][j] > 0 and best[i][j] == best[i + 1][j + 1] + sim[i][j]:
                out.append((i, j))
                i, j = i + 1, j + 1
            elif best[i][j] == best[i + 1][j]:
                i += 1
            else:
                j += 1
        return out
