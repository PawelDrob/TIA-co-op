"""Pair the networks of two block versions by title (numbers shift when networks are inserted) and decide
which pairs changed."""
import copy
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .beside import align, unread_beside
from .diff import Graph, NetDiff, out_of_order
from .names import decl_name, decl_type, file_safe
from .s7dcl import Network, _norm, lad_lines as _lad_lines, numbered as _numbered, scl_lines, texts_for_keys, wire_of
from .simaticml import same_export
from .source import UNREADABLE, stem


@dataclass
class NetPair:
    before: Optional[Network]
    after: Optional[Network]
    lad: Optional[NetDiff] = None
    moved: bool = False               # out of the common order of the others (_mark_moved)
    _not_shown: Optional[bool] = field(default=None, repr=False, compare=False)    # not_shown, once worked out

    @property
    def title(self):
        return (self.after or self.before).title

    @property
    def renamed(self):
        """Both versions there under other titles (paired by content)."""
        return bool(self.before and self.after and self.before.title != self.after.title)

    @property
    def lang(self):
        return (self.after or self.before).lang

    def _unseen(self):
        """The two versions' lines of a LAD network whose text differs though its elements and connections are alike, else
        None."""
        b, a = self.before, self.after
        if not (b and a and self.lad is not None and b.rungs is not None and a.rungs is not None) or self.lad.changed:
            return None
        lines = _lad_lines(b.body), _lad_lines(a.body)
        return lines if lines[0] != lines[1] else None

    def _same_lines(self):
        """Nothing but the order of the lines differs. Which wire is which number follows the order, so the numbers do not
        count."""
        lines = self._unseen()
        def blank(x):
            return sorted(re.sub(r'\bwire#\d+', 'wire#', l) for l in x)
        return bool(lines) and blank(lines[0]) == blank(lines[1])

    @property
    def reordered(self):
        """The rungs in another order, whatever else changed: what runs first can differ."""
        return bool(self.lad is not None and self.lad.reordered) or self._same_lines()

    def _read_same(self):
        """Both versions there and nothing differs in what the report reads of the network."""
        b, a = self.before, self.after
        if not (b and a) or b.lang != a.lang or b.title != a.title or b.comment != a.comment or b.label != a.label:
            return False
        if a.lang == 'LAD':
            return not self.lad.changed and not self._unseen()
        return scl_lines(b.body) == scl_lines(a.body)

    @property
    def not_shown(self):
        """Its part of the file differs in what no drawing shows (a pragma, a part's field), the order of its rungs aside;
        also beside a change the report shows (beside.py)."""
        b, a = self.before, self.after
        lines = self._unseen()
        if lines:
            return not self._same_lines()
        src_b, src_a = getattr(b, 'source', None), getattr(a, 'source', None)
        if not (src_b and src_a and src_b[0] == src_a[0] and src_b != src_a):
            return False
        if self._not_shown is None:
            self._not_shown = self._read_same() or unread_beside(b, a, _reads_same)
        return self._not_shown

    @property
    def label_state(self):
        """The diff mark of the jump label (render_lad): same, changed (renamed), added or removed."""
        b, a = self.before.label if self.before else '', self.after.label if self.after else ''
        return 'same' if b == a else 'added' if not b else 'removed' if not a else 'changed'

    @property
    def state(self):
        if not self.before:
            return 'new'
        if not self.after:
            return 'deleted'
        if self.not_shown:
            return 'changed'
        b, a = self.before, self.after
        if b.lang != a.lang or b.title != a.title:
            return 'changed'
        if b.comment != a.comment or b.label != a.label:
            return 'changed'
        if a.lang == 'LAD':
            return 'changed' if self.lad.changed or self._unseen() else 'same'
        return 'changed' if scl_lines(b.body) != scl_lines(a.body) else 'same'


def _reads_same(b, other):
    """What the report reads of two versions of a network is alike. The lines of an .s7dcl LAD network also hold what its
    drawing does not read: there the drawing alone."""
    p = NetPair(b, other)
    if b.lang == 'LAD' and other.lang == 'LAD':
        p.lad = NetDiff(Graph(b.rungs), Graph(other.rungs))
        if b.source[0] == 'sd':
            return (b.title, b.comment, b.label) == (other.title, other.comment, other.label) and not p.lad.changed
    return p._read_same()


# Content similarity from which a deleted and a new network of one replaced stretch are one renamed network (from
# the samples: pairs made at 0.54 to 0.71, the closest refused 0.48).
RENAMED_MIN = 0.5


def similarity(b, a, atleast=0.0):
    """How alike two networks are, 0 to 1, without their titles and comments. LAD: the instructions and operands
    (wire names left out) both have, of all. SCL (and any text language): the mean of the share of equal lines and
    the share of equal words and signs in order; lines alone miss a network whose names changed on most lines,
    words alone find the fault list of other devices written from the same template. 0 when the languages differ,
    one is empty, or the value cannot reach atleast (not computed to the end)."""
    if b.lang != a.lang:
        return 0.0
    if b.lang == 'LAD':
        cb, ca = _lad_tokens(b), _lad_tokens(a)
        n = sum(cb.values()) + sum(ca.values())
        return 2.0 * sum((cb & ca).values()) / n if n else 0.0
    lb = [l.strip() for l in scl_lines(b.body) if l.strip()]
    la = [l.strip() for l in scl_lines(a.body) if l.strip()]
    if not lb or not la:
        return 0.0
    lines = difflib.SequenceMatcher(None, lb, la, autojunk=False).ratio()
    sm = difflib.SequenceMatcher(None, _words(lb), _words(la), autojunk=False)
    if (lines + sm.real_quick_ratio()) / 2 < atleast or (lines + sm.quick_ratio()) / 2 < atleast:
        return 0.0
    return (lines + sm.ratio()) / 2


def _words(lines):
    return re.findall(r'\w+|[^\w\s]', '\n'.join(lines))


def _lad_tokens(n):
    c = Counter()
    for r in n.rungs or []:
        for it in r.items:
            if isinstance(it, tuple):
                continue
            c['@', it.instr, it.call or '', it.instance or ''] += 1
            for name, _, v in it.params:
                if wire_of(v) is None:
                    c[name or '', _norm(v)] += 1
    return c


def _pair_renamed(bs, as_, minsim=RENAMED_MIN):
    """The networks left on both sides of a replaced stretch, paired one-for-one in order where their content is
    alike (best total similarity): [(i, j)]."""
    sim = {(i, j): s for i, b in enumerate(bs) for j, a in enumerate(as_)
           for s in (similarity(b, a, minsim),) if s >= minsim}
    nb, na = len(bs), len(as_)
    best = {}
    for i in range(nb, -1, -1):
        for j in range(na, -1, -1):
            if i == nb or j == na:
                best[i, j] = 0.0
                continue
            v = max(best[i + 1, j], best[i, j + 1])
            if (i, j) in sim:
                v = max(v, best[i + 1, j + 1] + sim[i, j])
            best[i, j] = v
    out, i, j = [], 0, 0
    while i < nb and j < na:
        if (i, j) in sim and best[i, j] == best[i + 1, j + 1] + sim[i, j]:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif best[i, j] == best[i + 1, j]:
            i += 1
        else:
            j += 1
    return out


_STEP = 100000                  # a network new or deleted


def _cost(b, a, minsim):
    """What a pair costs an alignment: nothing for the same text; a step for any change of two networks alike
    (similarity() >= minsim, as a renamed network pairs), however alike, so an edit in place costs no more than
    reading it as deleted and another changed; two steps for two networks not alike, as much as one
    deleted and one new."""
    if b.source == a.source:
        return 0
    return _STEP if similarity(b, a, minsim) >= minsim else 2 * _STEP


def _untitled_pairs(bn, an, xs, ys, minsim):
    """([(i, j)], [(i, j)]) of xs (indices of bn) and ys (of an), in order: the untitled networks of one language
    aligned at least cost, each a network the report lists: a new or deleted network one step, a pair as _cost. So an
    edit stays in place among alike copies, and one added or deleted shifts no other. At a tie of cost the earlier ones
    pair in the first, the later ones in the second."""
    memo, parts = {}, {}

    def bound(n):
        """Counters whose overlap is at least similarity(), and for LAD is it: LAD its tokens, SCL its lines and its
        words (SequenceMatcher finds no more in order than both have)."""
        if id(n) not in parts:
            if n.lang == 'LAD':
                parts[id(n)] = (_lad_tokens(n),)
            else:
                lines = [l.strip() for l in scl_lines(n.body) if l.strip()]
                parts[id(n)] = (Counter(lines), Counter(_words(lines)))
        return parts[id(n)]

    def cost(i, j):
        if (i, j) not in memo:
            b, a = bn[i], an[j]
            if b.title or a.title or b.lang != a.lang:
                memo[i, j] = None
            elif b.source == a.source:
                memo[i, j] = 0
            else:
                most = sum(_dice(x, y) for x, y in zip(bound(b), bound(a))) / len(bound(b))
                if most < minsim:
                    memo[i, j] = 2 * _STEP          # cannot reach minsim: not alike, as _cost reads it
                else:
                    memo[i, j] = _STEP if b.lang == 'LAD' else _cost(b, a, minsim)
        return memo[i, j]
    nb, na = len(xs), len(ys)
    best = [[0] * (na + 1) for _ in range(nb + 1)]
    for i in range(nb, -1, -1):
        for j in range(na, -1, -1):
            if i == nb or j == na:
                best[i][j] = _STEP * (nb - i + na - j)
                continue
            c = cost(xs[i], ys[j])
            best[i][j] = min([best[i + 1][j] + _STEP, best[i][j + 1] + _STEP]
                             + ([best[i + 1][j + 1] + c] if c is not None else []))
    traces = []
    for late in (False, True):
        out, i, j = [], 0, 0
        while i < nb and j < na:
            c = cost(xs[i], ys[j])
            if late and best[i][j] == best[i + 1][j] + _STEP:
                i += 1
            elif late and best[i][j] == best[i][j + 1] + _STEP:
                j += 1
            elif c is not None and best[i][j] == best[i + 1][j + 1] + c:
                out.append((xs[i], ys[j]))
                i, j = i + 1, j + 1
            elif best[i][j] == best[i + 1][j] + _STEP:
                i += 1
            else:
                j += 1
        traces.append(out)
    return traces


def _dice(x, y):
    """The share of two Counters both have, 0 to 1."""
    n = sum(x.values()) + sum(y.values())
    if len(x) > len(y):
        x, y = y, x
    return 2.0 * sum(min(v, y[k]) for k, v in x.items() if k in y) / n if n else 0.0


def _aligned(bn, an, by_title, minsim):
    """[(pairs, stretches)] as _by_title (its pairs by_title), the untitled networks between two titled pairs aligned
    again by _untitled_pairs: at a tie of cost the earlier ones paired, then the later ones."""
    anchors = [(i, j) for i, j in by_title if bn[i].title]
    out = [([], []), ([], [])]
    bounds = [(-1, -1)] + anchors + [(len(bn), len(an))]
    for (i0, j0), (i1, j1) in zip(bounds, bounds[1:]):
        traces = _untitled_pairs(bn, an, range(i0 + 1, i1), range(j0 + 1, j1), minsim)
        for (pairs, stretches), inner in zip(out, traces):
            marks = [(i0, j0)] + inner + [(i1, j1)]
            for (p, q), (r, s) in zip(marks, marks[1:]):
                if r > p + 1 or s > q + 1:
                    stretches.append((list(range(p + 1, r)), list(range(q + 1, s))))
            pairs += inner + ([(i1, j1)] if i1 < len(bn) else [])
    return out


def _same_logic(b, a):
    """Titles and comments aside, the same logic, not empty: no LAD element differs, the same SCL lines."""
    if similarity(b, a, 1.0) < 1.0:
        return False
    if b.lang == 'LAD':
        return not NetDiff(Graph(b.rungs), Graph(a.rungs)).changed
    return scl_lines(b.body) == scl_lines(a.body)


def _mark_moved(pairs):
    """moved: a pair (both versions there) out of the longest common order of the two versions, i.e. not in every
    longest run of pairs in the same order on both sides: a network moved past others, both of two
    swapped, not those whose numbers only shift (a network added, deleted or moved past them)."""
    ps = sorted((p for p in pairs if p.before and p.after), key=lambda p: p.after.index)
    for p, out in zip(ps, out_of_order([p.before.index for p in ps])):
        p.moved = out


def pair_networks(before, after, minsim=RENAMED_MIN):
    """Align the network lists by title (sequence alignment, so duplicate titles pair in order). In a replaced
    stretch, a title kept with another language still pairs; the networks left on both sides pair in order when
    their content is alike (a renamed network, similarity() >= minsim); the rest are new or deleted networks. A title
    left in one stretch and in another is one network, paired before the renames; a deleted and a new
    network left after them are one when each is the other's only candidate of the same logic (an untitled or renamed
    network moved; the maintainer: a lower similarity paired two small unrelated networks of the E2E
    block). Moved: the pairs out of the longest common order, see _mark_moved. Untitled networks between two titled
    pairs align again by what they do (_untitled_pairs), at a tie of cost once by the earlier and once by the later
    ones; such a pairing is taken where it reads better than the one by title (_reading), so one added or deleted
    shifts no other onto its neighbour. At a tie the one by title stands, then the earlier ones."""
    bn, an = before.networks, after.networks
    by_title = _by_title(bn, an)
    out = _paired(bn, an, *by_title, minsim)
    tried = [by_title]
    for again in _aligned(bn, an, by_title[0], minsim):
        if again not in tried:
            tried.append(again)
            other = _paired(bn, an, *again, minsim)
            if _reading(other, minsim) < _reading(out, minsim):
                out = other
    return out


def _reading(pairs, minsim):
    """How a pairing reads, the less the better: the networks the report lists, then those of them new or deleted,
    then what they cost (_cost; a moved one as much as the deleted and new network it is read from)."""
    return (sum(p.state != 'same' or p.moved for p in pairs), sum(not (p.before and p.after) for p in pairs),
            sum(2 * _STEP if p.moved else _cost(p.before, p.after, minsim) if p.before and p.after else _STEP
                for p in pairs))


def _by_title(bn, an):
    """([(i, j)] the pairs, [(is, js)] the stretches between them): aligned by title and language."""
    sm = difflib.SequenceMatcher(None, [(n.title, n.lang) for n in bn], [(n.title, n.lang) for n in an], autojunk=False)
    pairs, spans = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            pairs += list(zip(range(i1, i2), range(j1, j2)))
        else:
            spans.append((list(range(i1, i2)), list(range(j1, j2))))
    return pairs, spans


def _paired(bn, an, pairs, spans, minsim):
    """[NetPair]: the pairs of an alignment and the stretches between them paired as pair_networks says."""
    out = [NetPair(bn[i], an[j]) for i, j in pairs]
    stretches = []
    for xs, ys in spans:
        bs, as_ = [bn[i] for i in xs], [an[j] for j in ys]
        # same title in a replaced stretch (title kept, language changed): still a pair
        used, left = set(), []
        for b in bs:
            j = next((k for k, a in enumerate(as_) if k not in used and a.title == b.title and b.title), None)
            if j is None:
                left.append(b)
            else:
                used.add(j)
                out.append(NetPair(b, as_[j]))
        stretches.append((left, [a for k, a in enumerate(as_) if k not in used]))
    gone = set()
    for b in (b for left, _ in stretches for b in left):
        a = next((a for _, rest in stretches for a in rest if id(a) not in gone and a.title == b.title and b.title),
                 None)
        if a is not None:
            gone |= {id(a), id(b)}
            out.append(NetPair(b, a))
    deleted, new = [], []
    for left, rest in stretches:
        left, rest = [b for b in left if id(b) not in gone], [a for a in rest if id(a) not in gone]
        paired = _pair_renamed(left, rest, minsim)
        out += [NetPair(left[i], rest[j]) for i, j in paired]
        deleted += [b for i, b in enumerate(left) if i not in {p[0] for p in paired}]
        new += [a for j, a in enumerate(rest) if j not in {p[1] for p in paired}]
    sim = {(i, j) for i, b in enumerate(deleted) for j, a in enumerate(new) if _same_logic(b, a)}
    ci, cj = Counter(i for i, _ in sim), Counter(j for _, j in sim)
    once = {(i, j) for i, j in sim if ci[i] == cj[j] == 1}
    out += [NetPair(deleted[i], new[j]) for i, j in once]
    out += [NetPair(b, None) for i, b in enumerate(deleted) if i not in {p[0] for p in once}]
    out += [NetPair(None, a) for j, a in enumerate(new) if j not in {p[1] for p in once}]
    _mark_moved(out)
    for p in out:
        if p.lang == 'LAD' and (not p.before or p.before.lang == 'LAD') and (not p.after or p.after.lang == 'LAD'):
            p.lad = NetDiff(Graph(p.before.rungs) if p.before else None, Graph(p.after.rungs) if p.after else None)
    out.sort(key=lambda p: (p.after.index if p.after else p.before.index - 0.5))
    return out


# ---------------------------------------------------------------- blocks of two snapshots

KINDS = {'FUNCTION_BLOCK': 'FB', 'FUNCTION': 'FC', 'ORGANIZATION_BLOCK': 'OB', 'DATA_BLOCK': 'DB', 'TYPE': 'UDT'}


@dataclass
class BlockDiff:
    path_b: Optional[str]
    path_a: Optional[str]
    before: Optional[object]          # s7dcl.Block
    after: Optional[object]
    nets: list                        # [NetPair] to show
    itf_changed: bool
    state: str                        # changed / new / deleted / same / version (only the library version) /
                                      # moved (only to another folder)
    ver_b: Optional[object] = None    # source.LibVersion of a library type
    ver_a: Optional[object] = None
    library: Optional['BlockDiff'] = None   # a program block: the library type of its name and kind
    library_differs: bool = False           # ... whose change is another (then also on the page under Types)
    props_changed: bool = False             # a block property (S7_Version, ...), apart from the interface
    not_shown: bool = False                 # its file differs in what the report does not read

    @property
    def block(self):
        return self.after or self.before

    @property
    def declaration(self):
        """(before, after) of its kind and declaration when they changed but for its own name (a DB of another type, an
        FC become an FB), else None."""
        b, a = self.before, self.after
        if not b or not a or _decl_key(b) == _decl_key(a):
            return None
        return tuple(('%s %s' % (KINDS.get(x.kind, x.kind), x.decl)).strip() for x in (b, a))

    @property
    def moved(self):
        return _moved(self.path_b, self.path_a)

    @property
    def renamed(self):
        """Both versions there under other names (a renamed block, paired by content: source.pair_blocks)."""
        return renamed(self.before, self.after)

    @property
    def name(self):
        """The block's name for the page: "Old -> New" (an arrow) when renamed."""
        new, was = self.names
        return '%s → %s' % (was, new) if was else new

    @property
    def names(self):
        """(name, was) of the page header, for the list and --json too: renamed, the declared names (a
        library type's file is named after the type, not its block); else the block's name and None."""
        if self.renamed:
            return _block_name(self.after), _block_name(self.before)
        return self.block.name, None

    @property
    def kind(self):
        b = self.block
        k = KINDS.get(b.kind, b.kind or '?')
        if k == 'DB' and decl_type(b.decl):                 # a DB of a UDT is a global DB
            cal = getattr(b, 'callees', None)
            typ = cal(decl_type(b.decl)) if cal else None
            if getattr(getattr(typ, 'block', None), 'kind', '') != 'TYPE':
                k = 'Instance DB'
        return k


def _decl_key(blk):
    """A block's kind and declaration as compared: without its own name and the quotes."""
    from .source import _masked
    masked = _masked(blk.decl, {blk.name, decl_name(blk.decl)} - {''})
    return blk.kind, re.sub(r'\s+', ' ', masked.replace('"', '')).strip()


def _block_name(blk):
    """A block's declared name; a real UDT export writes it on the line after TYPE, parse_block's name then holds it."""
    return decl_name(blk.decl) or blk.name


def renamed(bb, ab):
    return bool(bb and ab and _block_name(bb) != _block_name(ab))


def _empty(block):
    from .s7dcl import Block, Interface
    return Block(block.name, '', Interface(), [], block.kind, block.decl, {})


@dataclass
class GlobalDb:     # interface None: its type is not in the snapshot (a system type: the instance DB of a timer)
    number: Optional[str]             # its number as TIA draws it, None when the export has none (an .s7dcl under
                                      # automatic numbering)
    interface: object                 # s7dcl.Interface: the DB's own, or that of its UDT or FB


class Callees:
    """Interfaces of the blocks and UDTs of a snapshot by name, for the call boxes of its LAD (pin sides and order)
    and the comments of members inside a UDT or multi-instance. Loaded when asked for. Several files of one name:
    the project block before a library type, the type in work before its released version. An instance DB stands
    for its FB. None when the snapshot has no such FB / FC / UDT. A snapshot restricted to the changed blocks (source.GitSnapshot.only) is searched unrestricted: the
    called block is mostly unchanged. db(name): a global DB (GlobalDb), for the comments of its members and its
    number. A name is found under its file's name (names.file_safe). at(path): the lookup for a block
    of path; with several PLCs (plc/<device>/) its own PLC's blocks, then the rest (the library's types) as above,
    no other PLC's; a library type's: the library's types first, of its own version (in work or released), then the
    project's blocks. Without at(), the whole snapshot as above."""

    def __init__(self, snap, device=None, byname=None, library=None):
        if byname is None:
            snap = copy.copy(snap)                           # its paths() leaves the snapshot's skipped alone
            snap.only = None
        self.snap = snap
        self.device = device
        self.library = library                               # None, or a library type's version: 'work' / 'released'
        self._byname = byname if byname is not None else {}  # filled when first asked, shared with at()'s lookups
        self._at = {(device, library): self}
        self._itf = {}
        self._dbs = {}

    def at(self, path):
        from .source import _is_library, plc_device
        at = (path and plc_device(path),
              ('released' if '.released/' in path else 'work') if path and _is_library(path) else None)
        if at not in self._at:
            self._at[at] = Callees(self.snap, at[0], self._byname, at[1])
            self._at[at]._at = self._at
        return self._at[at]

    def __call__(self, name):
        key = _key(name)
        if key not in self._itf:
            self._itf[key] = None                            # an instance DB naming itself ends here
            self._itf[key] = self._load(key)
        return self._itf[key]

    def instance_of(self, name):
        """The block a DB is the instance of, as its document writes it, quoted when it is a block of the project; None for anything else."""
        blk = next((b for b in self._blocks(_key(name)) if b.kind == 'DATA_BLOCK' and decl_type(b.decl)), None)
        return decl_type(blk.decl) if blk else None

    def db(self, name):
        key = _key(name)
        if key not in self._dbs:
            blk = next((b for b in self._blocks(key) if b.kind == 'DATA_BLOCK'), None)
            itf = None
            if blk is not None:
                itf = self(decl_type(blk.decl)) if decl_type(blk.decl) else blk.interface
            self._dbs[key] = GlobalDb(blk.props.get('S7_BlockNumber') or blk.auto_number, itf) if blk is not None else None
        return self._dbs[key]

    def _blocks(self, key):
        """Parsed blocks of the files named key, in the order of preference."""
        from .s7dcl import parse_block
        from .source import _is_library, plc_device
        if not self._byname:
            for p in self.snap.paths():
                self._byname.setdefault(stem(p).rsplit('/', 1)[-1].lower(), []).append(p)
        paths = [p for p in self._byname.get(key, []) if self.device is None or plc_device(p) in (None, self.device)]
        lib = self.library
        for p in sorted(paths, key=lambda p: (_is_library(p) != bool(lib), ('.released/' in p) != (lib == 'released'),
                                              p)):
            try:
                yield parse_block(self.snap.load(p))
            except Exception:                                # noqa: BLE001 - an unreadable file: try the next
                continue

    def _load(self, key):
        for blk in self._blocks(key):
            if blk.kind in ('FUNCTION_BLOCK', 'FUNCTION', 'TYPE'):
                blk.interface.block = blk                    # number and comment for the call box (render_lad)
                return blk.interface
            if blk.kind == 'DATA_BLOCK' and decl_type(blk.decl):
                return self(decl_type(blk.decl))
        return None


def _key(name):
    return file_safe((name or '').strip().strip('"')).lower()


def versions_differ(vb, va):
    """Two versions (source.LibVersion), both there: another number, or released / put in work."""
    return bool(vb and va and (vb.number, vb.in_work) != (va.number, va.in_work))


def version_changed(bsrc, asrc):
    """Both sides library types, another version number or released / put in work."""
    return versions_differ(bsrc and bsrc.version, asrc and asrc.version)


def _moved(path_b, path_a):
    """The same file name in another folder of one PLC, or of the library's types of one kind (a type against its
    released version, a project block against its type: no move)."""
    from .source import _is_library, plc_device
    if not path_b or not path_a or path_b == path_a:
        return False
    return (path_b.rsplit('/', 1)[-1] == path_a.rsplit('/', 1)[-1] and _is_library(path_b) == _is_library(path_a)
            and plc_device(path_b) == plc_device(path_a) and ('.released/' in path_b) == ('.released/' in path_a))


def _resolved(src):
    """An .s7dcl's text with every language's text in place of its MLC keys and its wires numbered in each network (TIA
    numbers both per copy; which wire connects what stays)."""
    from .s7dcl import all_texts
    res = all_texts(src.s7res)
    text = re.sub(r'"([^"\n]*)"', lambda m: repr(res.get(m.group(1), m.group(1))), src.s7dcl)
    return ''.join(_numbered(p) for p in re.split(r'(?<=END_NETWORK)', text))


def _item_name(line):
    """The member a line of an interface names, or None (a section, an END_...)."""
    m = re.match(r'"?([^":=\s.]+)', line)
    return m.group(1).lower() if m and (':' in line) else None


_SECTION = re.compile(r'(VAR(_INPUT|_OUTPUT|_IN_OUT|_TEMP)?( (CONSTANT|RETAIN|NON_RETAIN|DB_SPECIFIC))?|END_\w+|STRUCT|BEGIN)$')


def _interface_items(src, blk):
    """An .s7dcl's interface as items, each line with the settings of the pragmas in front of it; the keys in its texts,
    the layout, the block's own name and its END_ line left out. Pragmas after its last line stand before the first
    network or the block's end (_around_networks)."""
    from .s7dcl import _KIND, _NET, parse_res
    from .source import _masked, _PRAGMA
    text = src.s7dcl
    res = parse_res(src.s7res)
    start = _KIND.search(text)
    first = _NET.search(text)
    head = text[start.start():first.start() if first else len(text)]
    head = texts_for_keys(head, res)
    items, pending = [], []
    names = {src.name, blk.name, decl_name(blk.decl)} - {''}
    lines = _PRAGMA.split(head)                                  # code, a pragma's settings, code, ...
    open_, depth = None, 0                                       # a start value over several lines is one item
    for k, part in enumerate(lines):
        if k % 2:
            if not depth:                                        # two in a row: both
                pending = sorted(pending + [x.strip() for x in part.split(';') if x.strip()])
            continue
        for line in part.splitlines():
            line = line.strip().rstrip(';').rstrip()
            if not line or (not depth and _END_BLOCK.fullmatch(line)):   # the block's end: its kind tells it
                continue
            bare = re.sub(r"'[^']*'|\"[^\"]*\"", '', line)
            opened = depth + sum(bare.count(c) for c in '([') - sum(bare.count(c) for c in ')]')
            if depth:
                open_[0] += ' ' + line
            else:
                open_ = [_masked(line, names), tuple(pending)]
                items.append(open_)
                pending = []
            depth = max(opened, 0)
    items = [tuple(i) for i in items]
    return items[1:] if blk.kind != 'TYPE' else items            # the declaration: compared apart


def _section_lines(items):
    """([((section line, what holds it), pragmas)], [(a section's first line, [its members])]) of _interface_items'
    section lines: an END_VAR by its section, an END_STRUCT by its struct member, a section line by those around it; a
    section by its number among the sections (_section_pragmas_differ pairs them)."""
    out, held, sections = [], [], []
    for line, pragmas in items:
        name = _item_name(line)
        if name is None and line:
            out.append(((line, tuple(held)), pragmas))
            if line.startswith('END_'):
                held = held[:-1]
            else:
                if not held:
                    sections.append((line, []))
                held = held + [len(sections) - 1 if not held else line]
        elif name is not None:
            if held:
                sections[held[0]][1].append(name)
            if re.search(r'\bSTRUCT$', line):
                held = held + [name]
    return out, sections


def _section_pragmas_differ(bitems, aitems):
    """A pragma in front of a section line differs, of the sections and structs both versions have, the sections paired
    in order by their first lines and members, then by their first lines: one added or removed brings its own, which
    comes with what the table shows."""
    (lb, sb), (la, sa) = _section_lines(bitems), _section_lines(aitems)
    pair_b, pair_a = {}, {}
    for i, j in align(sb, sa, lambda s: (s[0], tuple(s[1])), lambda s: s[0]):
        pair_b[i] = pair_a[j] = (i, j)

    def keyed(lines, pair, side):
        return [((line, tuple(pair.get(h, (side, h)) if isinstance(h, int) else h for h in held)), p)
                for (line, held), p in lines]
    kb, ka = keyed(lb, pair_b, 'b'), keyed(la, pair_a, 'a')
    both = {k for k, _ in kb} & {k for k, _ in ka}
    return Counter(x for x in kb if x[0] in both and x[1]) != Counter(x for x in ka if x[0] in both and x[1])


def _released_sd(src):
    """An .s7dcl of a released library type, by the version its export writes beside it."""
    return src.xml is None and src.version is not None and not src.version.in_work


def _unread_interface_sd(bsrc, asrc, bb, ab):
    """An .s7dcl's interface differs in a line no changed row of the report's table accounts for."""
    from . import iface
    lb, la = _interface_items(bsrc, bb), _interface_items(asrc, ab)
    ib, ia = Counter(lb), Counter(la)
    if ib == ia:
        return False
    if _section_pragmas_differ(lb, la):
        return True
    names = set()
    for r in iface.block_rows(bb, ab):
        if r.state != 'same':
            names |= {str(s).strip('"').lower() for p in (r.path, r.bpath or ()) for s in p}
    for line, _ in list((ib - ia).elements()) + list((ia - ib).elements()):
        name = _item_name(line)
        if name is None:
            if not _SECTION.match(line) or not names:            # a section the reader does not know
                return True
        elif name != '#' and name not in names:
            return True
    return False


def _unread_differs(bsrc, asrc, bb, ab, pairs=()):
    """The interface or the attributes differ in what the report does not read, whatever else changed. Two formats
    cannot be compared part by part. pairs: the block's NetPairs, which networks are one."""
    from .simaticml import unread_differs
    if bsrc.xml is not None and asrc.xml is not None:
        return unread_differs(bsrc.xml, asrc.xml, bb, ab)
    if bsrc.xml is None and asrc.xml is None:
        return _unread_interface_sd(bsrc, asrc, bb, ab) or _around_networks_differ(bsrc, asrc, pairs)
    return False


_END_BLOCK = re.compile(r'END_(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)')


def _around_networks(src, ids):
    """An .s7dcl's networks and what stands around them, in order: ('net', its text, its pair), each pragma block
    ('pragma', settings) and line ('line', text) before the first network after the interface's last line, between
    networks and after the last; the texts for their keys, without the layout and the block's END_ line, which its kind
    tells. ids: {network number: its pair}."""
    from .s7dcl import _NET, _pragmas, parse_res
    from .source import _PRAGMA
    res = parse_res(src.s7res)
    text = src.s7dcl
    nets = list(_NET.finditer(text))

    def tokens(part, last_only=False):
        out = []
        pieces = _PRAGMA.split(part)
        for k, piece in enumerate(pieces):
            if k % 2:
                out.append(('pragma', tuple(sorted((n, res.get(v, v)) for n, v in _pragmas('{%s}' % piece).items()))))
            else:
                lines = [texts_for_keys(x.strip(), res) for x in piece.splitlines() if x.strip()]
                lines = [x for x in lines if not _END_BLOCK.fullmatch(x)]
                if last_only and lines:
                    out = []                                     # the interface's lines: only the pragmas after them
                else:
                    out += [('line', x) for x in lines]
        return out
    seq = tokens(text[:nets[0].start() if nets else len(text)], last_only=True)
    for k, m in enumerate(nets):
        body = '\n'.join(x.strip() for x in texts_for_keys(m.group(0), res).splitlines() if x.strip())
        seq.append(('net', body, ids.get(k + 1, ('only', k))))
        seq += tokens(text[m.end():nets[k + 1].start() if k + 1 < len(nets) else len(text)])
    return seq


def _around_networks_differ(bsrc, asrc, pairs):
    """What stands around the networks differs. The two orders are aligned by what they hold, a network by
    its text. Where they differ, the pragmas right in front of a network are its own: compared with those of its pair
    when the pair stands in the same stretch, else they come with it, as a network added, removed or moved does."""
    idb = {p.before.index: k for k, p in enumerate(pairs) if p.before and p.after}
    ida = {p.after.index: k for k, p in enumerate(pairs) if p.before and p.after}
    sb, sa = _around_networks(bsrc, idb), _around_networks(asrc, ida)
    if [x[:2] for x in sb] == [x[:2] for x in sa]:
        return False

    def split(xs, others):
        """(Counter of what is not a network's own, {pair: the pragmas in front of it}) of a stretch; others: the pairs
        of the other side's networks in it."""
        rest, own, run = [], {}, []
        for x in xs:
            if x[0] == 'pragma':
                run.append(x)
                continue
            if x[0] == 'net':
                if x[2] in others:
                    own[x[2]] = run
            else:
                rest += run + [x]
            run = []
        return Counter(rest + run), own
    sm = difflib.SequenceMatcher(None, [x[:2] for x in sb], [x[:2] for x in sa], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        xs, ys = sb[i1:i2], sa[j1:j2]
        nb, na = {x[2] for x in xs if x[0] == 'net'}, {x[2] for x in ys if x[0] == 'net'}
        (rb, ob), (ra, oa) = split(xs, na), split(ys, nb)
        if rb != ra or ob != oa:
            return True
    return False


def _other_texts_differ(bsrc, asrc):
    """A text in a language other than the report's differs between two files: one more or less of them, or another one
    beside the same text in the report's language. A text of the report's language edited, its translations kept, is
    no such difference: the report shows it. Per text, not by key: TIA renumbers the keys per copy."""
    from . import s7dcl, simaticml
    b, a = ((simaticml.text_entries(s.xml) if s.xml is not None else s7dcl.text_entries(s.s7res)) for s in (bsrc, asrc))
    def flat(entries):
        return Counter(x for _, others in entries for x in others)
    if flat(b) != flat(a):
        return True
    cb, ca = Counter(b), Counter(a)
    shown = {t for t, _ in b} & {t for t, _ in a}
    return any(+Counter({k: v for k, v in cb.items() if k[0] == t}) != +Counter({k: v for k, v in ca.items() if k[0] == t})
               for t in shown)


def files_alike(bsrc, asrc):
    """Two versions' files differ at most in what the exports write differently, not in what a user can change."""
    from .simaticml import alike_exports
    if bsrc.xml is not None or asrc.xml is not None:
        return bsrc.xml is not None and asrc.xml is not None and alike_exports(bsrc.xml, asrc.xml)
    return (bsrc.s7dcl == asrc.s7dcl and (bsrc.s7res or '') == (asrc.s7res or '')) or _resolved(bsrc) == _resolved(asrc)


def compare_blocks(bsrc, asrc, path_b=None, path_a=None, networks=None, all_=False, callees=(None, None),
                   named=False):
    """callees: (before, after) Callees of the snapshots the two versions come from. Code unchanged but the
    library version changed: state 'version'. A renamed block is 'changed', as is one whose networks only moved
    (a moved network is shown). Nothing the report reads changed but the file differs in what a user
    can change: 'changed', not_shown; not_shown too when a text in a language other than the report's differs, whatever
    else changed. Nothing changed but its folder: state 'moved'; other paths without that never 'same', a pair stays on
    the list. named: a block --block names, also when unchanged, then with all its networks."""
    from . import iface
    from .s7dcl import parse_block
    if bsrc and asrc and bsrc.s7dcl == asrc.s7dcl and (bsrc.s7res or '') == (asrc.s7res or '') \
            and same_export(bsrc.xml, asrc.xml) and not all_ \
            and not networks and not named and not version_changed(bsrc, asrc) and path_b == path_a:
        return None                                          # identical files: nothing to parse
    bb = parse_block(bsrc) if bsrc else None
    ab = parse_block(asrc) if asrc else None
    for blk, c, p in ((bb, callees[0], path_b), (ab, callees[1], path_a)):
        if blk:
            blk.callees = c.at(p) if c else None
    setpoint_unknown = False
    if bb and ab:
        setpoint_unknown = (_released_sd(bsrc) and iface.take_setpoints(bb, ab)) or \
            (_released_sd(asrc) and iface.take_setpoints(ab, bb))
    pairs = pair_networks(bb or _empty(ab), ab or _empty(bb))
    ich, pch = iface.changed(bb, ab), iface.props_changed(bb, ab)
    state = 'new' if bb is None else ('deleted' if ab is None else
                                      ('changed' if ich or pch or renamed(bb, ab) or _decl_key(bb) != _decl_key(ab)
                                       or any(p.state != 'same' or p.moved for p in pairs) else 'same'))
    not_shown = bool(bsrc and asrc) and (setpoint_unknown or (state == 'same' and not files_alike(bsrc, asrc))
                                         or _other_texts_differ(bsrc, asrc)
                                         or _unread_differs(bsrc, asrc, bb, ab, pairs))
    if not_shown:
        state = 'changed'
    if state == 'same' and version_changed(bsrc, asrc):
        state = 'version'
    if state == 'same' and path_b and path_a and path_b != path_a:
        state = 'moved' if _moved(path_b, path_a) else 'changed'
    if networks:
        pairs = [p for p in pairs if {n.title for n in (p.before, p.after) if n} & set(networks)]
    elif not all_ and not (named and state in ('same', 'version', 'moved')):
        pairs = [p for p in pairs if p.state != 'same' or p.moved]    # a moved network always shown
    return BlockDiff(path_b, path_a, bb, ab, pairs, ich, state, bsrc.version if bsrc else None,
                     asrc.version if asrc else None, props_changed=pch, not_shown=not_shown)


def compare_snapshots(before, after, blocks=None, networks=None, all_=False, found=None):
    """found: {'blocks': set, 'networks': set}, given to collect the names of `blocks` and the titles of `networks`
    the inputs hold, changed or not (a title in the blocks `blocks` selects; the rest are typos).
    With `networks` only the blocks holding one of them; a named block or network also when unchanged."""
    from .source import pair_blocks
    out, srcs = [], {}
    callees = (Callees(before), Callees(after))
    for pb, pa in pair_blocks(before, after):
        hit = {stem(p).rsplit('/', 1)[-1] for p in (pb, pa) if p} & set(blocks or ())
        if blocks and not hit:
            hit, maybe = _declared(((before, pb), (after, pa)), set(blocks))
            if found is not None:                            # in a file named as unread: no typo to name
                found['blocks'] |= maybe
        if blocks and not hit:
            continue                                         # a renamed block: either name, file or declared
        if found is not None:
            found['blocks'] |= hit
        try:
            bsrc, asrc = before.load(pb) if pb else None, after.load(pa) if pa else None
            d = compare_blocks(bsrc, asrc, pb, pa, networks, all_, callees, bool(hit))
        except Exception as ex:                              # noqa: BLE001 - re-raised unless a file is unreadable
            if not _skip_unreadable(((before, pb), (after, pa))):
                raise
            continue
        if found is not None and d is not None:              # named by its file: its declared names found too
            found['blocks'] |= {_block_name(b) for b in (d.before, d.after) if b} & set(blocks or ())
        if found is not None and d is not None and networks:
            found['networks'] |= {n.title for x in d.nets for n in (x.before, x.after) if n} & set(networks)
        if d is not None and (d.nets if networks else all_ or hit or d.state != 'same'):
            out.append(d)
            srcs[id(d)] = (bsrc, asrc)
    return sorted(link_library_types(out, srcs), key=lambda d: d.state == 'moved')     # moved last: the rest opens first


def _declared(sides, names):
    """(the names of `names` a file of the pair declares its block under, though its file is named otherwise; those a
    file it cannot tell of may declare). A library type's file is named after the type: project A's
    PrepareTrolleyData.s7dcl declares "PrepareTrolleyData_1". Only a file holding one of the names as text
    is loaded. A file that cannot be read, or holds a name and does not parse, is added to its snapshot's skipped, as it
    is loaded no further. sides: ((snapshot, path | None), ...)."""
    from xml.sax.saxutils import escape
    from .s7dcl import declared_name, parse_block
    out, maybe = set(), set()
    for snap, p in sides:
        src, held = None, names
        try:
            text = p and snap.read(p) or ''
            held = {n for n in names if n in text or escape(n) in text}
            if not held:
                continue
            src = snap.load(p)
            name = decl_name(parse_block(src).decl) if src.xml is not None else declared_name(src.s7dcl)
        except Exception as ex:                              # noqa: BLE001 - any error of this file
            _note_unreadable(snap, p, src, ex)
            maybe |= held
            continue
        out |= {name} & names
    return out, maybe


def _skip_unreadable(sides):
    """The files of a pair that do not load or parse, each added to its snapshot's skipped (one never stops
    the report); False when both do (an error of the tool, not of the input). sides: ((snapshot, path | None), ...)."""
    from .s7dcl import parse_block
    bad = False
    for snap, p in sides:
        src = None
        try:
            if p:
                src = snap.load(p)
                parse_block(src)
        except Exception as ex:                              # noqa: BLE001 - any error of this file
            _note_unreadable(snap, p, src, ex)
            bad = True
    return bad


def _note_unreadable(snap, p, src, ex):
    """p in snap's skipped as unreadable, why without its label (src: what loaded of it, else None)."""
    why = str(ex)
    if src is not None and why.startswith(src.label + ': '):
        why = why[len(src.label) + 2:]
    snap.skipped.append((p, '%s: %s' % (UNREADABLE, why)))


def _names(d):
    """Its names, both when renamed: not its files', as Ns:Block and a block Ns_Block have one file name."""
    return {b.name.lower() for b in (d.before, d.after) if b}


def _change(d, srcs):
    """What changed between the two versions of a block, in order: (where, the lines removed, the lines added), where
    being the line of the version before. Compared without what only the two exports write differently
    (source.content_lines). Two blocks with this the same made one change, at the same place."""
    from .source import content_lines
    lb, la = ([] if blk is None else content_lines(s, blk, syntax=True)
              for s, blk in zip(srcs[id(d)], (d.before, d.after)))
    return [(i1, lb[i1:i2], la[j1:j2])
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lb, la, autojunk=False).get_opcodes() if op != 'equal']


def link_library_types(diffs, srcs):
    """A program block (or PLC data type) that is the project instance of a library type is exported twice, under
    plc/ and under library/ (the .s7dcl names no library link). Each program block on the page
    is linked to the library type of the same kind and name (a renamed block: either name; the type in work before
    its released version). The same change (_change): the program block alone shows it, its header naming the type
    and its versions, and the type leaves the page; a program block unchanged but for the type's version is
    'version'. Another change: both stay, the program block noted (library_differs). A deleted block is an instance
    deleted and nothing else, its type stays on the page as it is, removed too or not; a moved block or type changed
    nothing to link; a type with its note or a network's tag (not_shown) stays on the page; a new block or a new or deleted
    type has no change to hold against the other's unless both went the same way: no link. srcs:
    {id(diff): (before BlockSource, after BlockSource)}."""
    from .source import _is_library
    libs = [d for d in diffs if _is_library(d.path_a or d.path_b) and d.state != 'moved']
    if not libs:
        return diffs
    same, other = set(), set()
    for d in diffs:
        if _is_library(d.path_a or d.path_b) or d.after is None or d.state == 'moved':
            continue
        names, after = _names(d), d.block.name.lower()
        cand = [x for x in libs if x.block.kind == d.block.kind and _names(x) & names]
        if not cand:
            continue
        lib = min(cand, key=lambda x: (after not in _names(x), '.released/' in (x.path_a or x.path_b),
                                       x.path_a or x.path_b))
        differs = _change(d, srcs) != _change(lib, srcs)
        if differs and not (d.before and d.after and lib.before and lib.after):
            continue
        d.library, d.library_differs = lib, differs
        if differs or lib.not_shown or any(p.not_shown for p in lib.nets):    # its note or tag stays with the type
            other.add(id(lib))
        else:
            same.add(id(lib))
        if not differs:
            if d.state == 'same' and lib.state == 'version':
                d.state = 'version'
    return [d for d in diffs if id(d) not in same - other]     # while a copy differs, the type stays to compare with
