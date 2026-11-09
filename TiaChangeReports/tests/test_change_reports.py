"""Tests of TiaChangeReports (unittest, no TIA). From the repo root:
python -m unittest discover -s TiaChangeReports/tests -t .

The tests on whole exports read the made-up project in fixtures\\plant: v1 and v2, two versions of a filler (a
filling station) with its UDTs, a block that prepares its data, a bay that calls it and a safety DB with its logic.
"""
import copy
import msvcrt
import os
import random
import re
import tempfile
import unittest
from collections import Counter

from TiaChangeReports import iface, render_lad
from TiaChangeReports.compare import compare_blocks, pair_networks
from TiaChangeReports.diff import Graph, NetDiff, changed_params
from TiaChangeReports.page import _pair_lines, columns_html, render
from TiaChangeReports.render_lad import Layout
from TiaChangeReports.s7dcl import Element, SET_IN_IDB, parse_block, parse_interface
from TiaChangeReports.source import BlockSource, FolderSnapshot, LibVersion, from_file, pair_blocks
from TiaChangeReports.verify import check

PLANT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'plant')
V1, V2 = os.path.join(PLANT, 'v1'), os.path.join(PLANT, 'v2')
FILLER_V1 = os.path.join(V1, 'library', 'types', 'Bottling', 'Filler.released', 'Filler.s7dcl')   # released 1.0.5
FILLER_V2 = os.path.join(V2, 'library', 'types', 'Bottling', 'Filler', 'Filler.s7dcl')            # in work 1.0.6


def _exports():
    seen, out = set(), []
    for top in (V1, V2):
        for d, _, fs in os.walk(top):
            for f in fs:
                if f.endswith('.s7dcl'):
                    src = from_file(os.path.join(d, f))
                    if src.s7dcl not in seen:
                        seen.add(src.s7dcl)
                        out.append(src)
    return out


_BLOCKS = None


def blocks():
    global _BLOCKS
    if _BLOCKS is None:
        _BLOCKS = [parse_block(s) for s in _exports()]
    return _BLOCKS


def lad_networks():
    return [(b, n) for b in blocks() for n in b.networks if n.rungs]


def clone(rungs, tag):
    """Deep copy with new element ids (a second version of the same network)."""
    out = copy.deepcopy(rungs)
    for r in out:
        for it in r.items:
            if isinstance(it, Element):
                it.eid = tag + it.eid
    return out


def statuses(d, g):
    return Counter(d.status[e] for e in g.elements)


SRC = '''{ S7_Optimized := "TRUE" }
FUNCTION_BLOCK "T"
    VAR_INPUT
        { S7_MLC := "MLC_1" }
        a : Bool;
        b : Bool;
    END_VAR
    VAR
        s : STRUCT
            x : Bool;
        END_STRUCT;
    END_VAR
    VAR CONSTANT
        C1 : Int := 1;
    END_VAR
    {
        S7_Language := "LAD";
        S7_NetworkTitle := "MLC_2"
    }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            wire#w1
            I_Contact( #b )
            Coil( #s.x )
        END_RUNG
        RUNG wire#powerrail
            Contact( #s.x )
        END_RUNG wire#w1
    END_NETWORK
    { S7_Language := "SCL" }
    NETWORK
        #s.x := #a;
    END_NETWORK
END_FUNCTION_BLOCK
'''
RES = '''MultiLingualTexts:
  - id: MLC_1
    en-US: input a
  - id: MLC_2
    en-US: Seal-in
'''


def src(text=SRC, res=RES, name='T'):
    return BlockSource(name, text, res, name)


class Synthetic(unittest.TestCase):
    def test_parse(self):
        b = parse_block(src())
        self.assertEqual(b.kind, 'FUNCTION_BLOCK')
        self.assertEqual([n.lang for n in b.networks], ['LAD', 'SCL'])
        self.assertEqual(b.networks[0].title, 'Seal-in')
        self.assertEqual(b.interface.comment_of('#a'), 'input a')
        self.assertEqual(b.interface.constant('#C1').value, '1')
        self.assertEqual(list(b.interface.root.children['s'].children), ['x'])

    def test_rename_wires_is_no_change(self):
        t2 = SRC.replace('wire#w1', 'wire#w7')
        d = compare_blocks(src(), src(t2), all_=True)
        self.assertEqual(d.state, 'same')

    def test_one_contact_changed(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        d = compare_blocks(src(), src(t2))
        (p,) = d.nets
        self.assertEqual(statuses(p.lad, p.lad.a), Counter(same=3, changed=1))

    def test_contact_added(self):
        t2 = SRC.replace('            Coil( #s.x )', '            Contact( #a )\n            Coil( #s.x )')
        d = compare_blocks(src(), src(t2))
        (p,) = d.nets
        self.assertEqual(statuses(p.lad, p.lad.a), Counter(same=4, added=1))
        self.assertEqual(statuses(p.lad, p.lad.b), Counter(same=4))

    def test_interface_member_added_and_comment_changed(self):
        t2 = SRC.replace('        b : Bool;\n', '        b : Bool;\n        c : Int;\n')
        r2 = RES.replace('input a', 'input A')
        b, a = parse_block(src()), parse_block(src(t2, r2))
        rows = {'.'.join(r.path): (r.state, r.changes) for r in iface.rows(b.interface, a.interface)}
        self.assertEqual(rows['c'][0], 'added')
        self.assertEqual(rows['a'], ('changed', {'comment'}))
        self.assertEqual(rows['b'][0], 'same')

    def test_scl_line_pairing(self):
        b = ['x := 1;', 'IF a THEN', 'y := 2;']
        a = ['IF a THEN', 'y := 3;']
        rows = _pair_lines(b, a, 0, 3, 0, 2)
        self.assertIn((1, 0), rows)
        self.assertIn((2, 1), rows)
        self.assertIn((0, None), rows)

    def test_scl_mlc_by_text(self):
        """An `S7_MLC` pragma in an SCL body compares and shows by its text, not by TIA's key."""
        from TiaChangeReports.s7dcl import scl_lines
        def mlc(key, text):
            t = SRC.replace('        #s.x := #a;', '        REGION DESCRIPTION\n          { S7_MLC := "%s" }\n'
                                                   '        END_REGION DESCRIPTION\n        #s.x := #a;' % key)
            return src(t, RES + '  - id: %s\n    en-US: |-\n      %s\n' % (key, text.replace('\n', '\n      ')))
        b = mlc('MLC_4Xw', 'Note\nThe value is random.')
        self.assertEqual(compare_blocks(b, mlc('MLC_4tY', 'Note\nThe value is random.')).state, 'same')
        d = compare_blocks(b, mlc('MLC_4tY', 'Note\nThe value is not random.'))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        self.assertEqual(scl_lines(p.after.body)[:3], ['REGION DESCRIPTION', '  (/*Note',
                                                       '  The value is not random.*/)'])
        self.assertIn('MLC_9', scl_lines(parse_block(src(SRC.replace(
            '        #s.x := #a;', '        { S7_MLC := "MLC_9" }'))).networks[1].body)[0])

    def test_page_is_self_contained(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        html = render([compare_blocks(src(), src(t2))], 'b', 'a')
        urls = set(re.findall(r'(?:https?:)?//[\w.-]+[^\s"\'<>)]*', html)) - {'http://www.w3.org/2000/svg'}
        self.assertEqual(urls, set())
        self.assertNotRegex(html, r'<(?:link|img|iframe)\b|<script[^>]+src=|@import|url\(')

    def test_folder_pairing(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            for root, rel in ((d1, 'a/X.s7dcl'), (d1, 'b/Y.s7dcl'), (d2, 'a/X.s7dcl'), (d2, 'c/Y.s7dcl'),
                              (d2, 'Z.s7dcl')):
                os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
                with open(os.path.join(root, rel), 'w') as f:
                    f.write(SRC)
            pairs = pair_blocks(FolderSnapshot(d1), FolderSnapshot(d2))
            self.assertEqual(sorted(pairs, key=str), sorted([('a/X.s7dcl', 'a/X.s7dcl'), ('b/Y.s7dcl', 'c/Y.s7dcl'),
                                                             (None, 'Z.s7dcl')], key=str))


class FixtureNetworks(unittest.TestCase):
    """Every LAD network of fixtures\\plant: series, branches ending on other nodes, compares, boxes with
    logic-fed pins, SR, TON, R_TRIG, FB calls, ESTOP1."""

    def test_the_fixture_has_networks(self):
        self.assertGreaterEqual(len(lad_networks()), 15)

    def test_every_network_equals_itself(self):
        for b, n in lad_networks():
            d = NetDiff(Graph(n.rungs), Graph(clone(n.rungs, 'x')))
            self.assertFalse(d.changed, '%s NW%d' % (b.name, n.index))

    def test_renumbered_wires_and_reordered_branches_are_no_change(self):
        rnd = random.Random(1)
        for b, n in lad_networks():
            r2 = clone(n.rungs, 'y')
            names = sorted({x for r in r2 for x in [r.start, r.end] + [it[1] for it in r.items if isinstance(it, tuple)]
                            if x and x != 'powerrail'})
            new = names[:]
            rnd.shuffle(new)
            ren = dict(zip(names, ['q' + x for x in new]))
            for r in r2:
                r.start = ren.get(r.start, r.start)
                r.end = ren.get(r.end, r.end) if r.end else r.end
                r.items = [('node', ren[it[1]]) if isinstance(it, tuple) else it for it in r.items]
                for it in r.items:
                    if isinstance(it, Element):
                        it.params = [(p, d, 'wire#' + ren[v.strip()[5:].lower()] if v.strip().lower().startswith('wire#')
                                      else v) for p, d, v in it.params]
            r2 = r2[:1] + sorted(r2[1:], key=lambda r: rnd.random())
            d = NetDiff(Graph(n.rungs), Graph(r2))
            self.assertFalse(d.changed, '%s NW%d' % (b.name, n.index))

    def _mutations(self, kind):
        rnd = random.Random(2)
        bad = []
        count = 0
        for b, n in lad_networks():
            spots = [(ri, ii) for ri, r in enumerate(n.rungs) for ii, it in enumerate(r.items)
                     if isinstance(it, Element) and it.kind == 'contact'
                     and sum(isinstance(x, Element) for x in r.items) >= 2]
            if not spots:
                continue
            ri, ii = rnd.choice(spots)
            r2 = clone(n.rungs, 'z')
            it = r2[ri].items[ii]
            if kind == 'delete':
                del r2[ri].items[ii]
            elif kind == 'operand':
                it.params = [(None, None, '#zzOther')]
            else:
                r2[ri].items.insert(ii, Element('zznew', 'Contact', None, [(None, None, '#zzNew')], {}))
            d = NetDiff(Graph(n.rungs), Graph(r2))
            sb, sa = statuses(d, d.b), statuses(d, d.a)
            want = {'delete': (Counter(removed=1), Counter()), 'operand': (Counter(changed=1), Counter(changed=1)),
                    'insert': (Counter(), Counter(added=1))}[kind]
            got = (sb - Counter(same=sb['same']), sa - Counter(same=sa['same']))
            count += 1
            if got != want:
                bad.append('%s NW%d: %s' % (b.name, n.index, got))
        return count, bad

    def test_one_contact_deleted_is_one_removed(self):
        n, bad = self._mutations('delete')
        self.assertEqual(bad, [], '%d of %d' % (len(bad), n))

    def test_one_operand_changed_is_one_changed(self):
        n, bad = self._mutations('operand')
        self.assertEqual(bad, [], '%d of %d' % (len(bad), n))

    def test_one_contact_inserted_is_one_added(self):
        n, bad = self._mutations('insert')
        self.assertEqual(bad, [], '%d of %d' % (len(bad), n))

    def test_drawing_reads_back_as_the_code(self):
        bad = []
        for b, n in lad_networks():
            p = check(Layout(n.rungs, b.interface))
            if p:
                bad.append('%s NW%d: %s' % (b.name, n.index, p[:2]))
        self.assertEqual(bad, [])

    def test_filler_v1_to_v2(self):
        """A change as a change log describes it: networks changed, new and renamed, members added and one moved
        out of its struct, contacts given other operands, one contact added."""
        old, new = parse_block(from_file(FILLER_V1)), parse_block(from_file(FILLER_V2))
        changed = {p.title: p.state for p in pair_networks(old, new) if p.state != 'same'}
        self.assertEqual(changed, {
            'Lower the filling head': 'changed', 'Gross and net weight reached': 'new',
            'Coarse valve shut at the coarse weight': 'changed',
            'High probe wet before the fill weight': 'changed', 'Outputs': 'changed',
            'Clear the overfill flag when a batch starts': 'new'})
        rows = {'.'.join(r.path): r.state for r in iface.rows(old.interface, new.interface) if r.state != 'same'}
        self.assertEqual(rows, {'instBatchStart': 'added', 'statOverfill': 'added',
                                'statDrip.Late': 'removed', 'statDripLate': 'added',
                                'statWeighed': 'added', 'statWeighed.Gross': 'added',
                                'statWeighed.Net': 'added'})
        lw = [p for p in pair_networks(old, new) if p.title == 'Lower the filling head'][0]
        self.assertEqual(statuses(lw.lad, lw.lad.a), Counter(same=6, changed=4))
        cv = [p for p in pair_networks(old, new) if p.title == 'Coarse valve shut at the coarse weight'][0]
        added = [e.operand() for e in cv.lad.a.elements.values() if cv.lad.status[e.eid] == 'added']
        self.assertEqual(added, ['#statWeighed.Gross'])


def _git(repo, *args):
    import subprocess
    subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
                   + list(args), check=True, capture_output=True)


def _put(repo, files):
    """files: {relative path: text, or None to delete}"""
    for rel, text in files.items():
        p = os.path.join(repo, rel)
        if text is None:
            os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)


UDT_D = 'TYPE "D"\n    STRUCT\n        x : Bool;\n    END_STRUCT;\nEND_TYPE\n'   # not G renamed


def _locked(path, run):
    """run() while another program holds the file locked."""
    with open(path, 'r+b') as f:
        size = os.path.getsize(path)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, size)
        try:
            return run()
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, size)


class GitInput(unittest.TestCase):
    """Two commits of a small export: A changed, B unchanged, C only its .s7res, D new, E moved, G deleted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = r = self.tmp.name
        _git(r, 'init', '-q')
        _git(r, 'config', 'core.autocrlf', 'false')
        _put(r, {'plc/A.s7dcl': SRC.replace('\n', '\r\n'), 'plc/A.s7res': RES, 'plc/B.s7dcl': SRC,
                 'plc/C.s7dcl': SRC, 'plc/E.s7dcl': SRC, 'plc/G.s7dcl': SRC})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'one')
        _put(r, {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), 'plc/C.s7res': RES,
                 'plc/D.s7dcl': UDT_D, 'plc/E.s7dcl': None, 'plc2/E.s7dcl': SRC, 'plc/G.s7dcl': None,
                 'plc/A.libinfo': 'LibraryVersion: 1\n'})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'two')

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_of_a_revision(self):
        from TiaChangeReports.source import GitSnapshot
        self.assertEqual(GitSnapshot(self.repo, 'HEAD~1').paths(),
                         ['plc/A.s7dcl', 'plc/B.s7dcl', 'plc/C.s7dcl', 'plc/E.s7dcl', 'plc/G.s7dcl'])
        self.assertEqual(GitSnapshot(os.path.join(self.repo, 'plc'), 'HEAD').paths(),
                         ['A.s7dcl', 'B.s7dcl', 'C.s7dcl', 'D.s7dcl'])

    def test_load_and_read(self):
        from TiaChangeReports.source import GitSnapshot
        s = GitSnapshot(self.repo, 'HEAD~1')
        a = s.load('plc/A.s7dcl')
        self.assertEqual((a.name, a.s7dcl, a.s7res, a.label), ('A', SRC, RES, 'HEAD~1:plc/A.s7dcl'))
        self.assertIsNone(s.load('plc/B.s7dcl').s7res)
        self.assertIsNone(s.read('plc/A.libinfo'))
        self.assertEqual(GitSnapshot(self.repo, 'HEAD').read('plc/A.libinfo'), 'LibraryVersion: 1\n')
        self.assertIn('HEAD~1', s.label)

    def test_two_revisions_read_only_the_changed_blocks(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        before, after = git_snapshots(self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual(before.paths(), ['plc/A.s7dcl', 'plc/C.s7dcl', 'plc/E.s7dcl', 'plc/G.s7dcl'])
        self.assertEqual(after.paths(), ['plc/A.s7dcl', 'plc/C.s7dcl', 'plc/D.s7dcl', 'plc2/E.s7dcl'])
        got = {(d.path_b, d.path_a): d.state for d in compare_snapshots(before, after)}
        self.assertEqual(got, {('plc/A.s7dcl', 'plc/A.s7dcl'): 'changed', ('plc/C.s7dcl', 'plc/C.s7dcl'): 'changed',
                               (None, 'plc/D.s7dcl'): 'new', ('plc/G.s7dcl', None): 'deleted',
                               ('plc/E.s7dcl', 'plc2/E.s7dcl'): 'moved'})

    def test_a_revision_is_read_in_a_few_git_processes(self):
        """One git show per file took minutes for a full re-export; the number of git processes does
        not grow with the files, a file is read as before (BOM, CRLF, empty, a name with blanks and umlauts), one
        missing reads None, and an unrestricted copy (compare.Callees) reads unchanged blocks."""
        import copy
        import subprocess
        from unittest import mock
        from TiaChangeReports import source
        from TiaChangeReports.compare import compare_snapshots
        names = ['plc/N%02d' % i for i in range(30)] + ['plc/Grüße Ä']
        _put(self.repo, {n + x: t for n in names for x, t in (('.s7dcl', SRC), ('.s7res', RES))})
        _put(self.repo, {'plc/Empty.libinfo': '', 'plc/Bom.s7res': '\ufeffa\r\nb\rc\n'})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'three')
        _put(self.repo, {n + '.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )') for n in names})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'four')
        calls, run = [], subprocess.run

        def counted(cmd, *a, **k):
            calls.append(cmd)
            return run(cmd, *a, **k)
        with mock.patch.object(source.subprocess, 'run', counted):
            before, after = source.git_snapshots(self.repo, 'HEAD~1', 'HEAD')
            ds = compare_snapshots(before, after)
            self.assertEqual(sorted(d.path_a for d in ds), sorted(n + '.s7dcl' for n in names))
            self.assertEqual({d.state for d in ds}, {'changed'})
            self.assertEqual(after.load('plc/Grüße Ä.s7dcl').s7res, RES)
            self.assertLessEqual(len(calls), 12)
            whole = copy.copy(after)
            whole.only = None
            self.assertEqual(whole.load('plc/B.s7dcl').s7dcl, SRC)
            self.assertEqual((whole.read('plc/Empty.libinfo'), whole.read('plc/Bom.s7res')), ('', 'a\nb\nc\n'))
            self.assertIsNone(whole.read('plc/Nothing.s7res'))
            self.assertIsNone(source.GitSnapshot(self.repo, 'HEAD~2').read('plc/N00.s7dcl'))

    def test_revision_against_the_working_tree(self):
        from TiaChangeReports.source import git_snapshots
        _put(self.repo, {'plc/B.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), 'plc/F.s7dcl': SRC,
                         'plc/D.s7dcl': None})
        before, after = git_snapshots(self.repo, 'HEAD')
        self.assertEqual(before.paths(), ['plc/B.s7dcl', 'plc/D.s7dcl'])
        self.assertEqual(after.paths(), ['plc/B.s7dcl', 'plc/F.s7dcl'])
        b = after.load('plc/B.s7dcl')
        self.assertEqual(b.label, os.path.join(os.path.abspath(self.repo), 'plc', 'B.s7dcl'))
        self.assertIn('I_Contact( #a )', b.s7dcl)

    def test_an_edit_with_the_time_restored_reads_as_changed_against_the_working_tree(self):
        """Git's size and time are no proof of equal bytes."""
        import subprocess
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        full = os.path.join(self.repo, 'plc', 'B.s7dcl')
        long_ago = (1700000000, 1700000000)     # older than the index: git takes the file as unchanged by its time
        os.utime(full, long_ago)
        _git(self.repo, 'update-index', '--refresh')
        _put(self.repo, {'plc/B.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )')})
        os.utime(full, long_ago)
        status = subprocess.run(['git', '-C', self.repo, 'status', '--porcelain'], capture_output=True, check=True)
        self.assertEqual(status.stdout, b'')

        before, after = git_snapshots(self.repo, 'HEAD')

        self.assertEqual(after.paths(), ['plc/B.s7dcl'])
        self.assertEqual([(d.path_a, d.state) for d in compare_snapshots(before, after)], [('plc/B.s7dcl', 'changed')])

    def test_a_folder_inside_the_repo_against_its_working_tree(self):
        """Paths are relative to the folder, and only what changed is read."""
        from TiaChangeReports.source import git_snapshots
        _put(self.repo, {'plc/B.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )')})

        before, after = git_snapshots(os.path.join(self.repo, 'plc'), 'HEAD')

        self.assertEqual((before.paths(), after.paths()), (['B.s7dcl'], ['B.s7dcl']))

    def test_other_line_ends_in_the_working_tree_read_no_block(self):
        """core.autocrlf, as on Windows by default: a checkout with CRLF of what git holds with LF."""
        from TiaChangeReports.source import git_snapshots
        _git(self.repo, 'config', 'core.autocrlf', 'true')
        _put(self.repo, {'plc/B.s7dcl': SRC.replace('\n', '\r\n')})

        self.assertEqual(git_snapshots(self.repo, 'HEAD')[1].paths(), [])

    def test_a_locked_file_that_is_no_block_reads_no_block(self):
        """A log or an archive beside the exports: load() reads none, so a lock on one changes nothing."""
        from TiaChangeReports.source import git_snapshots
        _put(self.repo, {'logs/run.json': '{}', 'project.zap20': 'archive'})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'beside')

        paths = _locked(os.path.join(self.repo, 'project.zap20'), lambda: git_snapshots(self.repo, 'HEAD')[1].paths())

        self.assertEqual(paths, [])

    def test_a_locked_tag_table_is_named_and_not_read_as_deleted(self):
        from TiaChangeReports import plctags
        from TiaChangeReports.source import git_snapshots, skipped
        _put(self.repo, {'plc/tags/T.xml': '<Document><SW.Tags.PlcTagTable ID="0" /></Document>'})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'a table')

        def run():
            before, after = git_snapshots(self.repo, 'HEAD')
            return plctags.compare(before, after), skipped((before, after))
        tables, named = _locked(os.path.join(self.repo, 'plc/tags/T.xml'), run)

        self.assertEqual(tables, [])                                     # no state: nothing tells whether it changed
        self.assertEqual([p for p, _ in named], ['plc/tags/T.xml'])

    def test_a_locked_block_is_named_and_the_others_are_compared(self):
        """Its bytes are unknown, so it cannot pass as unchanged, and one file never stops the report."""
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots, skipped
        _put(self.repo, {'plc/C.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )')})

        def run():
            before, after = git_snapshots(self.repo, 'HEAD')
            return [(d.path_a, d.state) for d in compare_snapshots(before, after)], skipped((before, after))
        states, named = _locked(os.path.join(self.repo, 'plc/B.s7dcl'), run)

        self.assertEqual(states, [('plc/C.s7dcl', 'changed')])
        self.assertEqual([p for p, _ in named], ['plc/B.s7dcl'])
        self.assertIn('unreadable', named[0][1])

    def test_a_locked_simaticml_export_is_named_and_not_read_as_deleted(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots, skipped
        _put(self.repo, {'plc/Main.xml': _fixture()})
        _git(self.repo, 'add', '-A')
        _git(self.repo, 'commit', '-q', '-m', 'an OB')

        def run():
            before, after = git_snapshots(self.repo, 'HEAD')
            return compare_snapshots(before, after), skipped((before, after))
        diffs, named = _locked(os.path.join(self.repo, 'plc/Main.xml'), run)

        self.assertEqual(diffs, [])
        self.assertEqual([p for p, _ in named], ['plc/Main.xml'])

    def test_bad_revision(self):
        from TiaChangeReports.source import git_snapshots
        with self.assertRaises(ValueError):
            git_snapshots(self.repo, 'nosuchrev')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                git_snapshots(d, 'HEAD')

    def test_cli(self):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        out = os.path.join(self.repo, 'out.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', out]), 0)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('plc/A.s7dcl', html)
        self.assertIn('HEAD~1', html)
        self.assertIn('A change in TIA that was never exported and committed is not in it.', html)
        with contextlib.redirect_stdout(io.StringIO()):
            main(['--git', self.repo, 'HEAD', '-o', out])      # against the working tree: an export need not be committed
        with open(out, encoding='utf-8') as f:
            self.assertIn('A change in TIA that was never exported is not in it.', f.read())
        with contextlib.redirect_stdout(io.StringIO()):
            main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', out, '--fragment'])
        with open(out, encoding='utf-8') as f:
            self.assertNotIn('never exported', f.read())       # pasted into another report, that report says what it read
        with contextlib.redirect_stdout(io.StringIO()):
            main([self.repo, self.repo, '-o', out])
        with open(out, encoding='utf-8') as f:
            self.assertNotIn('never exported', f.read())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--git', self.repo, 'nosuchrev', '-o', out]), 2)
            self.assertEqual(main(['--git', self.repo, '-o', out]), 2)
            self.assertEqual(main(['-o', out]), 2)


# ---------------------------------------------------------------- call pins from the called interface

CALLEE = '''FUNCTION_BLOCK "Drive"
    VAR_INPUT
        start : Bool;
        speed : Int;
    END_VAR
    VAR_OUTPUT
        busy : Bool;
    END_VAR
    VAR_IN_OUT
        cmd : Int;
        data : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
CALLER = '''FUNCTION_BLOCK "Caller"
    VAR
        inst : _.Drive;
        a : Bool;
        b : Bool;
        c : Int;
        d : Int;
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            #inst(
                speed := 5,
                start := wire#w1,
                cmd := #c,
                data := #d,
                busy => #q
            )
        END_RUNG
        RUNG wire#powerrail
            Contact( #b )
        END_RUNG wire#w1
    END_NETWORK
END_FUNCTION_BLOCK
'''


def _write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)


def _call_view(lay):
    return next(v for v in lay.views.values() if v.el.instr == 'CALL')


class CallPins(unittest.TestCase):
    def test_without_the_called_block_pins_as_written(self):
        b = parse_block(src(CALLER, '', 'Caller'))
        v = _call_view(Layout(b.networks[0].rungs, b.interface))
        self.assertEqual([n for n, _ in v.lefts], ['EN', 'speed', 'start', 'cmd', 'data'])
        self.assertEqual([n for n, _ in v.rights], ['ENO', 'busy'])

    def test_called_interface_sets_order_and_sides(self):
        from TiaChangeReports.compare import Callees
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/Caller.s7dcl': CALLER, 'plc/Drive.s7dcl': CALLEE})
            callees = Callees(FolderSnapshot(d))
            b = parse_block(src(CALLER, '', 'Caller'))
            lay = Layout(b.networks[0].rungs, b.interface, callees)
        v = _call_view(lay)
        self.assertEqual([n for n, _ in v.lefts], ['EN', 'start', 'speed', 'cmd', 'data'])
        self.assertEqual([n for n, _ in v.rights], ['ENO', 'busy'])          # in-outs on the left only (TIA)
        self.assertEqual([s for s, _, _ in v.lefts[3][1]], ['#c'])
        self.assertEqual(v.inouts, {3, 4})
        self.assertEqual(v.wirepins, {1: ('start', 'w1')})
        self.assertEqual(check(lay), [])

    def test_instance_db_and_library_copies(self):
        from TiaChangeReports.compare import Callees
        other = CALLEE.replace('VAR_IN_OUT', 'VAR_OUTPUT')
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'library/types/Drive/Drive.released/Drive.s7dcl': other, 'plc/Drive.s7dcl': CALLEE,
                       'plc/DriveDb.s7dcl': 'DATA_BLOCK DriveDb : Drive\nEND_DATA_BLOCK\n'})
            callees = Callees(FolderSnapshot(d))
            self.assertEqual(callees('Drive').root.children['cmd'].section, 'IN_OUT')    # project block first
            self.assertIs(callees('DriveDb'), callees('Drive'))
            self.assertIsNone(callees('Nowhere'))

    def test_called_block_of_the_same_plc(self):
        """Two PLCs with a block of the same name: a call takes its own PLC's block, then the library's types; another
        PLC's blocks are not looked at."""
        from TiaChangeReports.compare import compare_snapshots
        other = CALLEE.replace('VAR_IN_OUT', 'VAR_OUTPUT')
        lib = 'TYPE "Pos"\nSTRUCT\n  x : Int;\nEND_STRUCT\nEND_TYPE\n'
        files = {'plc/PLC_A/blocks/Drive.s7dcl': CALLEE, 'plc/PLC_B/blocks/Drive.s7dcl': other,
                 'plc/PLC_A/blocks/Only.s7dcl': CALLEE, 'library/types/Pos/Pos/Pos.s7dcl': lib}
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            _write(d1, dict(files, **{'plc/PLC_B/blocks/Caller.s7dcl': CALLER}))
            _write(d2, dict(files, **{'plc/PLC_B/blocks/Caller.s7dcl':
                                      CALLER.replace('Contact( #b )', 'I_Contact( #b )')}))
            (diff,) = compare_snapshots(FolderSnapshot(d1), FolderSnapshot(d2), blocks={'Caller'})
            for blk in (diff.before, diff.after):
                self.assertEqual(blk.callees('Drive').root.children['cmd'].section, 'OUTPUT')    # PLC_B's
                self.assertIsNotNone(blk.callees('Pos'))
                self.assertIsNone(blk.callees('Only'))                                           # PLC_A's only
            vb = _call_view(Layout(diff.before.networks[0].rungs, diff.before.interface, diff.before.callees))
        self.assertEqual([n for n, _ in vb.rights], ['ENO', 'busy', 'cmd', 'data'])

    def test_library_type_calls_the_library_first(self):
        """A library type's call takes the library's type first, of its own version (in work: the type in work,
        released: the released one), then a project block."""
        from TiaChangeReports.compare import Callees
        work, released = CALLEE.replace('VAR_IN_OUT', 'VAR_OUTPUT'), CALLEE.replace('VAR_IN_OUT', 'VAR')
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/blocks/Drive.s7dcl': CALLEE, 'library/types/Drive/Drive/Drive.s7dcl': work,
                       'library/types/Drive/Drive.released/Drive.s7dcl': released,
                       'library/types/Only/Only/Only.s7dcl': work.replace('Drive', 'Only')})
            callees = Callees(FolderSnapshot(d))
            section = lambda c, n='Drive': c(n).root.children['cmd'].section
            self.assertEqual(section(callees.at('plc/blocks/Caller.s7dcl')), 'IN_OUT')                      # project
            self.assertEqual(section(callees.at('library/types/Caller/Caller/Caller.s7dcl')), 'OUTPUT')    # in work
            self.assertEqual(section(callees.at('library/types/Caller/Caller.released/Caller.s7dcl')), 'STAT')
            self.assertEqual(section(callees.at('library/types/Caller/Caller.released/Caller.s7dcl'), 'Only'),
                             'OUTPUT')                                     # no released version: the one in work

    def test_snapshots_give_their_blocks_the_called_interfaces(self):
        from TiaChangeReports.compare import compare_snapshots
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            _write(d1, {'Caller.s7dcl': CALLER, 'Drive.s7dcl': CALLEE})
            _write(d2, {'Caller.s7dcl': CALLER.replace('Contact( #b )', 'I_Contact( #b )'),
                        'Drive.s7dcl': CALLEE.replace('VAR_IN_OUT', 'VAR_OUTPUT')})
            (diff,) = compare_snapshots(FolderSnapshot(d1), FolderSnapshot(d2), blocks={'Caller'})
            html = render([diff], 'b', 'a')
            vb = _call_view(Layout(diff.before.networks[0].rungs, diff.before.interface, diff.before.callees))
            va = _call_view(Layout(diff.after.networks[0].rungs, diff.after.interface, diff.after.callees))
        self.assertEqual([n for n, _ in vb.rights], ['ENO', 'busy'])
        self.assertEqual([n for n, _ in va.rights], ['ENO', 'busy', 'cmd', 'data'])         # each side its version
        self.assertEqual(html.count('>⇌cmd</text>'), 1)                              # before: in-out, left
        self.assertEqual(html.count('>cmd</text>'), 1)                                     # after: output, right

    def test_git_input_finds_an_unchanged_called_block(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, {'plc/Caller.s7dcl': CALLER, 'plc/Drive.s7dcl': CALLEE})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {'plc/Caller.s7dcl': CALLER.replace('Contact( #b )', 'I_Contact( #b )')})
            before, after = git_snapshots(r, 'HEAD')
            (diff,) = compare_snapshots(before, after)
            self.assertIsNotNone(diff.before.callees('Drive'))
            self.assertIsNotNone(diff.after.callees('Drive'))

    def test_calls_in_a_group(self):
        """The filler called by its bay (a library type, found in library/types of the folder)."""
        from TiaChangeReports.compare import Callees
        callees = Callees(FolderSnapshot(V1))
        group = parse_block(from_file(os.path.join(V1, 'plc/blocks/Lines/Bay4.s7dcl')))
        filler = callees('Filler').root.children.values()
        order = [m.name for s in ('INPUT', 'IN_OUT') for m in filler if m.section == s]
        ios = [m.name for m in filler if m.section == 'IN_OUT']
        n = 0
        for net in group.networks:
            if not net.rungs:
                continue
            lay = Layout(net.rungs, group.interface, callees)
            for v in lay.views.values():
                if v.el.instr == 'CALL' and v.title == '"Filler"':
                    n += 1
                    self.assertEqual([x for x, _ in v.lefts[1:]], order)
                    self.assertEqual(v.inouts, set(range(len(v.lefts) - len(ios), len(v.lefts))))
                    self.assertEqual(len(v.rights), 4)                          # ENO and the 3 outputs
            self.assertEqual(check(lay), [], 'NW%d' % net.index)
        self.assertGreater(n, 0)


def _text(html):
    return re.sub(r'<[^>]+>', '', html)


LIBINFO = '\ufeffLibraryType:\n  Guid: test-guid\nLibraryVersion:\n  VersionNumber: %s\n  Author: %s\n  %s: true\n'


class LibraryVersions(unittest.TestCase):
    """The version of a library type from the <Type>.libinfo beside its .s7dcl."""

    def test_every_snapshot_reads_the_version(self):
        from TiaChangeReports.source import FileSnapshot, GitSnapshot, LibVersion
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'T/T.s7dcl': SRC, 'T/T.libinfo': LIBINFO % ('3.0.6', 'author2', 'InWork'), 'U.s7dcl': SRC})
            want = LibVersion('3.0.6', 'author2', in_work=True)
            self.assertEqual(from_file(os.path.join(d, 'T/T.s7dcl')).version, want)
            self.assertEqual(FileSnapshot(os.path.join(d, 'T/T.s7dcl')).load('T.s7dcl').version, want)
            self.assertEqual(FolderSnapshot(d).load('T/T.s7dcl').version, want)
            self.assertIsNone(FolderSnapshot(d).load('U.s7dcl').version)
            _git(d, 'init', '-q')
            _git(d, 'add', '-A')
            _git(d, 'commit', '-q', '-m', 'one')
            _write(d, {'T/T.libinfo': LIBINFO % ('3.0.6', 'author2', 'IsDefault')})
            self.assertEqual(GitSnapshot(d, 'HEAD').load('T/T.s7dcl').version, want)
            self.assertEqual(GitSnapshot(d).load('T/T.s7dcl').version, LibVersion('3.0.6', 'author2', default=True))

    def test_unreadable_libinfo_is_no_version(self):
        from TiaChangeReports.source import lib_version
        for text in (None, '', 'LibraryVersion: 1\n', 'a: [', 'LibraryVersion:\n  Author: x\n'):
            self.assertIsNone(lib_version(text), repr(text))

    def test_header_and_summary_show_before_and_after(self):
        from TiaChangeReports.source import LibVersion
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        b, a = src(), src(t2)
        b.version, a.version = LibVersion('3.0.5', 'author1', default=True), LibVersion('3.0.6', 'author2', True)
        d = compare_blocks(b, a)
        self.assertEqual((d.ver_b, d.ver_a), (b.version, a.version))
        other = compare_blocks(src(), src(t2.replace('#s.x := #a;', '#s.x := #b;'), name='N'))
        html = render([d, other], 'b', 'a')
        head = re.search(r'<div class="bh" id="blk-T">.*?</div>', html).group(0)
        self.assertIn('3.0.5 → 3.0.6 in work', _text(head))
        self.assertIn('<th>Version</th>', html)
        rows = re.findall(r'<tr><td><a href="#blk-(\w+)">.*?</tr>', html)
        self.assertEqual(rows, ['T', 'N'])
        self.assertIn('3.0.5 → 3.0.6 in work', _text(re.search(r'<tr><td><a href="#blk-T">.*?</tr>', html).group(0)))

    def test_one_side_or_one_number(self):
        from TiaChangeReports.page import version_html
        from TiaChangeReports.source import LibVersion
        v6 = LibVersion('3.0.6', 'x', in_work=True)
        self.assertEqual(version_html(None, None), '')
        self.assertEqual(_text(version_html(v6, LibVersion('3.0.6', 'x', in_work=True))), '3.0.6 in work')
        self.assertEqual(_text(version_html(None, v6)), '3.0.6 in work')        # a project block vs. its type
        self.assertEqual(_text(version_html(LibVersion('3.0.6', 'x', default=True), v6)), '3.0.6 → 3.0.6 in work')
        self.assertEqual(_text(version_html(v6, LibVersion('3.0.6', 'x', default=True))),
                         '3.0.6 in work → 3.0.6 released')
        self.assertEqual(_text(version_html(v6, LibVersion('3.0.7', 'x', default=True))),
                         '3.0.6 in work → 3.0.7 released')
        self.assertEqual(_text(version_html(LibVersion('3.0.5', 'x', default=True), LibVersion('3.0.6', 'x', default=True))),
                         '3.0.5 → 3.0.6')                               # only after an in-work version
        self.assertEqual(_text(version_html(v6, LibVersion('3.0.7', 'x'))), '3.0.6 in work → 3.0.7')    # the export says neither
        self.assertEqual(_text(version_html(v6, LibVersion('3.0.5', 'x', default=True))),
                         '3.0.6 in work → 3.0.5')                       # a discard: back to an older one, nothing released
        self.assertEqual(_text(version_html(LibVersion('3.0.10', 'x', in_work=True), LibVersion('3.0.9', 'x', default=True))),
                         '3.0.10 in work → 3.0.9')                      # numbers, not text
        self.assertEqual(_text(version_html(LibVersion('3.0.9', 'x', in_work=True), LibVersion('3.0.10', 'x', default=True))),
                         '3.0.9 in work → 3.0.10 released')

    def test_released_stands_in_the_head_and_the_summary_row(self):
        from TiaChangeReports.source import LibVersion
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        b, a = src(), src(t2)
        b.version, a.version = LibVersion('0.0.3', 'x', in_work=True), LibVersion('0.0.3', 'y', default=True)
        other = compare_blocks(src(), src(t2.replace('#s.x := #a;', '#s.x := #b;'), name='N'))
        html = render([compare_blocks(b, a), other], 'b', 'a')
        self.assertIn('0.0.3 in work → 0.0.3 released', _text(re.search(r'<div class="bh" id="blk-T">.*?</div>', html).group(0)))
        self.assertIn('0.0.3 in work → 0.0.3 released', _text(re.search(r'<tr><td><a href="#blk-T">.*?</tr>', html).group(0)))

    def test_version_change_alone_is_listed(self):
        from TiaChangeReports.source import LibVersion
        b, a = src(), src()
        b.version, a.version = LibVersion('3.0.5', 'x', default=True), LibVersion('3.0.6', 'x', in_work=True)
        d = compare_blocks(b, a)
        self.assertEqual((d.state, d.nets, d.itf_changed), ('version', [], False))
        a.version = LibVersion('3.0.5', 'x', default=True)
        self.assertIsNone(compare_blocks(b, a))                       # same version, same code
        b.version = LibVersion('3.0.5', 'x', in_work=True)
        self.assertEqual(compare_blocks(b, a).state, 'version')        # released
        b.version = None
        self.assertIsNone(compare_blocks(b, a))                       # a project block vs. its type, same code
        b.version = LibVersion('3.0.4', 'x')
        a2 = src(SRC.replace('I_Contact( #b )', 'I_Contact( #a )'))
        a2.version = a.version
        self.assertEqual(compare_blocks(b, a2).state, 'changed')

    def test_version_only_on_the_page(self):
        from TiaChangeReports.source import LibVersion
        b, a = src(), src()
        b.version, a.version = LibVersion('3.0.5', 'x', default=True), LibVersion('3.0.6', 'x', in_work=True)
        other = compare_blocks(src(name='N'), src(SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), name='N'))
        html = render([compare_blocks(b, a), other], 'b', 'a')
        row = _text(re.search(r'<tr><td><a href="#blk-T">.*?</tr>', html).group(0))
        self.assertEqual(row, 'TFB3.0.5 → 3.0.6 in workversion only')
        sec = re.search(r'<section class="blk"><div class="bh" id="blk-T">.*?</section>', html).group(0)
        self.assertIn('version only', _text(sec))
        self.assertNotIn('class="nw', sec)

    def test_folders_list_a_version_change_alone(self):
        from TiaChangeReports.compare import compare_snapshots
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            _write(d1, {'T/T.s7dcl': SRC, 'T/T.libinfo': LIBINFO % ('3.0.6', 'x', 'InWork'), 'U.s7dcl': SRC})
            _write(d2, {'T/T.s7dcl': SRC, 'T/T.libinfo': LIBINFO % ('3.0.6', 'x', 'IsDefault'), 'U.s7dcl': SRC})
            self.assertEqual([(x.block.name, x.state) for x in compare_snapshots(FolderSnapshot(d1),
                                                                                 FolderSnapshot(d2))],
                             [('T', 'version')])

    def test_without_versions_no_column(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        html = render([compare_blocks(src(), src(t2)), compare_blocks(src(name='N'), src(t2, name='N'))], 'b', 'a')
        self.assertNotIn('Version', html)

    def test_released_vs_in_work(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import snapshot
        (d,) = compare_snapshots(snapshot(FILLER_V1), snapshot(FILLER_V2))
        self.assertEqual((d.ver_b.number, d.ver_b.in_work, d.ver_a.number, d.ver_a.in_work),
                         ('1.0.5', False, '1.0.6', True))
        self.assertIn('1.0.5 → 1.0.6 in work', _text(render([d], 'b', 'a')))


# ---------------------------------------------------------------- operand comments of UDT members

USER = '''FUNCTION_BLOCK "User"
    VAR
        { S7_MLC := "MLC_1" }
        io : _.Cmd_UDT;
        { S7_MLC := "MLC_2" }
        arr : Array[0..3] of _.Cmd_UDT;
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #io.Handover )
            Contact( #io.plain )
            Contact( #io.sub.y )
            Contact( #arr[1].Handover )
            Coil( #q )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
USER_RES = 'MultiLingualTexts:\n  - id: MLC_1\n    en-US: bay commands\n  - id: MLC_2\n    en-US: one per bay\n'
CMD_UDT = '''TYPE
    Cmd_UDT : STRUCT
        { S7_MLC := "MLC_a" }
        Handover : Bool;
        plain : Bool;
        { S7_MLC := "MLC_b" }
        sub : _.Sub_UDT;
    END_STRUCT;
END_TYPE
'''
CMD_RES = 'MultiLingualTexts:\n  - id: MLC_a\n    en-US: Hand over to the next bay\n  - id: MLC_b\n    en-US: sub data\n'
SUB_UDT = 'TYPE\n    Sub_UDT : STRUCT\n        y : Bool;\n    END_STRUCT;\nEND_TYPE\n'


def _comments(lay):
    """operand -> its comment as drawn above it."""
    from TiaChangeReports.render_lad import C_CMT
    return {v.el.operand(): ' '.join(s for s, c, _ in v.top if c == C_CMT)
            for v in lay.views.values() if v.el.kind in ('contact', 'coil')}


class UdtMemberComments(unittest.TestCase):
    """The comment of a member inside a UDT, through the UDT export in the same snapshot."""

    FILES = {'plc/User.s7dcl': USER, 'plc/User.s7res': USER_RES, 'plc/types/Cmd_UDT.s7dcl': CMD_UDT,
             'plc/types/Cmd_UDT.s7res': CMD_RES, 'plc/types/Sub_UDT.s7dcl': SUB_UDT}

    def test_member_comment_from_the_udt(self):
        from TiaChangeReports.compare import Callees
        with tempfile.TemporaryDirectory() as d:
            _write(d, self.FILES)
            snap = FolderSnapshot(d)
            b = parse_block(snap.load('plc/User.s7dcl'))
            got = _comments(Layout(b.networks[0].rungs, b.interface, Callees(snap)))
        self.assertEqual(got, {'#io.Handover': 'Hand over to the next bay',
                               '#io.plain': 'bay commands',     # no comment in the UDT: the enclosing member
                               '#io.sub.y': 'sub data',              # a UDT in a UDT, enclosing member inside it
                               '#arr[1].Handover': 'Hand over to the next bay',  # an array of the UDT
                               '#q': ''})

    def test_without_the_udt_the_enclosing_member(self):
        from TiaChangeReports.compare import Callees
        b = parse_block(src(USER, USER_RES, 'User'))
        self.assertEqual(_comments(Layout(b.networks[0].rungs, b.interface))['#io.Handover'], 'bay commands')
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/User.s7dcl': USER, 'plc/User.s7res': USER_RES})
            got = _comments(Layout(b.networks[0].rungs, b.interface, Callees(FolderSnapshot(d))))
        self.assertEqual((got['#io.Handover'], got['#arr[1].Handover']), ('bay commands', 'one per bay'))

    def test_member_of_a_multi_instance(self):
        from TiaChangeReports.compare import Callees
        drive = CALLEE.replace('        busy : Bool;', '        { S7_MLC := "MLC_d" }\n        busy : Bool;')
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'Drive.s7dcl': drive, 'Drive.s7res': 'MultiLingualTexts:\n  - id: MLC_d\n    en-US: drive busy\n'})
            itf = parse_block(src(CALLER, '', 'Caller')).interface
            self.assertEqual(itf.comment_of('#inst.busy', Callees(FolderSnapshot(d))), 'drive busy')

    def test_before_and_after_each_their_udt_version(self):
        from TiaChangeReports.compare import compare_snapshots
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            _write(d1, self.FILES)
            _write(d2, dict(self.FILES, **{
                'plc/User.s7dcl': USER.replace('Contact( #io.plain )', 'I_Contact( #io.plain )'),
                'plc/types/Cmd_UDT.s7res': CMD_RES.replace('Hand over to the next bay', 'Hand over to the previous bay')}))
            (diff,) = compare_snapshots(FolderSnapshot(d1), FolderSnapshot(d2), blocks={'User'})
            html = render([diff], 'b', 'a')
        self.assertEqual(html.count('Hand over to the next bay'), 2)
        self.assertEqual(html.count('Hand over to the previous bay'), 2)

    def test_git_input_finds_an_unchanged_udt(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, self.FILES)
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {'plc/User.s7dcl': USER.replace('Contact( #io.plain )', 'I_Contact( #io.plain )')})
            before, after = git_snapshots(r, 'HEAD')
            (diff,) = compare_snapshots(before, after)
            html = render([diff], 'b', 'a')
        self.assertEqual(html.count('Hand over to the next bay'), 4)

    def test_udt_of_a_library_type(self):
        from TiaChangeReports.compare import Callees
        filler = parse_block(from_file(FILLER_V2))
        callees = Callees(FolderSnapshot(V2))
        op = '#statHead.Infeed.Bottle'
        self.assertEqual(filler.interface.comment_of(op, callees), 'Infeed sensors in front of the filling head')
        self.assertEqual(filler.interface.comment_of(op), filler.interface.comment_of('#statHead'))


# ---------------------------------------------------------------- operand comments of global DB members

GLOBAL_USER = '''FUNCTION_BLOCK "GUser"
    VAR
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( "ShaftData".Shaft[3].IO.West )
            Contact( "ShaftData".Shaft[3].IO.plain )
            Contact( "ShaftData".Mode )
            Contact( "SysData".FG[11].Maint )
            Contact( "DrvDb".busy )
            Contact( "Plc/Comm".ok )
            Contact( "Missing".x )
            Contact( "Tag" )
            Coil( #q )
        END_RUNG
        RUNG wire#powerrail
            #inst(
                faults := "HmiAlarmBuffer"
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
SHAFT_DATA = '''{
    S7_BlockNumber := "900";
    S7_Optimized := "TRUE"
}
DATA_BLOCK ShaftData
    VAR
        { S7_MLC := "MLC_h" }
        Shaft : Array[1..4] of _.Shaft_UDT;
        { S7_MLC := "MLC_m" }
        Mode : Bool;
    END_VAR

END_DATA_BLOCK
'''
SHAFT_RES = 'MultiLingualTexts:\n  - id: MLC_h\n    en-US: per shaft\n  - id: MLC_m\n    en-US: shaftmode\n'
SHAFT_UDT = '''TYPE
    Shaft_UDT : STRUCT
        IO : STRUCT
            { S7_MLC := "MLC_w" }
            West : Bool;
            plain : Bool;
        END_STRUCT;
    END_STRUCT;
END_TYPE
'''
SHAFT_UDT_RES = 'MultiLingualTexts:\n  - id: MLC_w\n    en-US: TRUE if blocked, FALSE if free\n'
SYS_UDT = '''TYPE
    Sys_UDT : STRUCT
        FG : Array[1..12] of STRUCT
            { S7_MLC := "MLC_s" }
            Maint : Bool;
        END_STRUCT;
    END_STRUCT;
END_TYPE
'''
GLOBAL_FILES = {
    'plc/GUser.s7dcl': GLOBAL_USER,
    'plc/ShaftData.s7dcl': SHAFT_DATA, 'plc/ShaftData.s7res': SHAFT_RES,
    'plc/types/Shaft_UDT.s7dcl': SHAFT_UDT, 'plc/types/Shaft_UDT.s7res': SHAFT_UDT_RES,
    'plc/SysData.s7dcl': '{\n    S7_BlockNumber := "11"\n}\nDATA_BLOCK SysData : Sys_UDT\nEND_DATA_BLOCK\n',
    'plc/types/Sys_UDT.s7dcl': SYS_UDT,
    'plc/types/Sys_UDT.s7res': 'MultiLingualTexts:\n  - id: MLC_s\n    en-US: maintenance mode\n',
    'plc/Drive.s7dcl': '''FUNCTION_BLOCK "Drive"\n    VAR_OUTPUT\n        { S7_MLC := "MLC_d" }\n        busy : Bool;
    END_VAR\nEND_FUNCTION_BLOCK\n''',
    'plc/Drive.s7res': 'MultiLingualTexts:\n  - id: MLC_d\n    en-US: drive busy\n',
    'plc/DrvDb.s7dcl': 'DATA_BLOCK DrvDb : Drive\nEND_DATA_BLOCK\n',
    'plc/Plc_Comm.s7dcl': 'DATA_BLOCK "Plc/Comm"\n    VAR\n        { S7_MLC := "MLC_c" }\n        ok : Bool;\n'
                          '    END_VAR\n\nEND_DATA_BLOCK\n',
    'plc/Plc_Comm.s7res': 'MultiLingualTexts:\n  - id: MLC_c\n    en-US: link ok\n',
    'plc/HmiAlarmBuffer.s7dcl': '{\n    S7_BlockNumber := "901"\n}\nDATA_BLOCK HmiAlarmBuffer\n    VAR\n'
                                   '        x : Bool;\n    END_VAR\n\nEND_DATA_BLOCK\n',
}


def _numbers(lay):
    """operand -> the block number drawn above it (contacts and box pins)."""
    from TiaChangeReports.render_lad import C_NUM, C_OP
    out = {}
    for v in lay.views.values():
        if v.el.kind in ('contact', 'coil'):
            sides = [v.top]
        else:
            sides = [L for _, L in v.lefts + v.rights if L]
        for L in sides:
            op = ''.join(s for s, c, _ in L if c == C_OP)
            out[op] = ' '.join(s for s, c, _ in L if c == C_NUM)
    return out


class GlobalDbComments(unittest.TestCase):
    """The comment of a global DB member through the DB export in the same snapshot; above a whole DB
    its number (TIA: %DB901 above "HmiAlarmBuffer")."""

    def _layout(self, files=GLOBAL_FILES, callees=True):
        from TiaChangeReports.compare import Callees
        with tempfile.TemporaryDirectory() as d:
            _write(d, files)
            snap = FolderSnapshot(d)
            b = parse_block(snap.load('plc/GUser.s7dcl'))
            return Layout(b.networks[0].rungs, b.interface, Callees(snap) if callees else None)

    def test_member_comments_from_the_db(self):
        got = _comments(self._layout())
        self.assertEqual(got, {'"ShaftData".Shaft[3].IO.West': 'TRUE if blocked, FALSE if free',   # through its UDT
                               '"ShaftData".Shaft[3].IO.plain': 'per shaft',     # no comment: the enclosing member
                               '"ShaftData".Mode': 'shaftmode',                 # declared in the DB
                               '"SysData".FG[11].Maint': 'maintenance mode',     # a DB of a UDT
                               '"DrvDb".busy': 'drive busy',                     # an instance DB: its FB
                               '"Plc/Comm".ok': 'link ok',                       # file Plc_Comm (TiaBridge's name)
                               '"Missing".x': '',                                # DB not exported
                               '"Tag"': '',                                      # a PLC tag
                               '#q': ''})

    def test_number_above_a_whole_db_only(self):
        lay = self._layout()
        nums = _numbers(lay)
        self.assertEqual(nums['"HmiAlarmBuffer"'], '%DB901')
        self.assertEqual(nums['"ShaftData".Mode'], '')                   # a member: no number (optimized DB)
        self.assertEqual(nums['"Tag"'], '')
        self.assertEqual(check(lay), [])

    def test_without_the_snapshot_no_comment(self):
        got = _comments(self._layout(callees=False))
        self.assertEqual(set(got.values()), {''})
        self.assertEqual(_numbers(self._layout(callees=False))['"HmiAlarmBuffer"'], '')

    def test_before_and_after_each_their_db_version(self):
        from TiaChangeReports.compare import compare_snapshots
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            _write(d1, GLOBAL_FILES)
            _write(d2, dict(GLOBAL_FILES, **{
                'plc/GUser.s7dcl': GLOBAL_USER.replace('Contact( "Tag" )', 'I_Contact( "Tag" )'),
                'plc/ShaftData.s7res': SHAFT_RES.replace('shaftmode', 'shaftauto mode')}))
            (diff,) = compare_snapshots(FolderSnapshot(d1), FolderSnapshot(d2), blocks={'GUser'})
            html = render([diff], 'b', 'a')
        self.assertEqual(html.count('shaftmode'), 1)
        self.assertEqual(html.count('shaftauto mode'), 1)

    def test_git_input_finds_an_unchanged_db(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, GLOBAL_FILES)
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {'plc/GUser.s7dcl': GLOBAL_USER.replace('Contact( "Tag" )', 'I_Contact( "Tag" )')})
            before, after = git_snapshots(r, 'HEAD')
            (diff,) = compare_snapshots(before, after)
            html = render([diff], 'b', 'a')
        self.assertEqual(html.count('TRUE if blocked, FALSE if free'), 2)
        self.assertEqual(html.count('%DB901'), 2)

    def test_quoted_members_of_a_safety_db(self):
        from TiaChangeReports.compare import Callees
        b = parse_block(from_file(os.path.join(V1, 'plc/blocks/Safety/HatchLogic.s7dcl')))
        callees = Callees(FolderSnapshot(V1))
        self.assertEqual(b.interface.comment_of('"HatchDb"."K02+FS01-BG03"', callees), 'Filler hatch locked')
        self.assertEqual(b.interface.comment_of('"HatchDb"."K02+FS01-BG03".q', callees), 'Hatch 1=Free')  # typeHatch
        self.assertIsNone(b.interface.comment_of('"HatchDb"."K02+FS01-BG03".q'))


# ---------------------------------------------------------------- a merge of two wire nodes is one change

MERGE = '''FUNCTION_BLOCK "M"
    VAR
        t : Bool; c : Bool; x : Bool; y : Bool; z : Bool; n : Bool; m : Bool; q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #t )
            wire#w4
            Contact( #c )
            S_Coil( #x )
        END_RUNG
        RUNG wire#w4
            R_Coil( #x )
            Coil( #y )
        END_RUNG
        RUNG wire#powerrail
            Contact( #t )
            S_Coil( #x )
            Coil( #z )
        END_RUNG
        RUNG wire#powerrail
            I_Contact( #n )
            wire#w8
            Coil( #q )
        END_RUNG
        RUNG wire#powerrail
            I_Contact( #m )
        END_RUNG wire#w8
    END_NETWORK
END_FUNCTION_BLOCK
'''
MERGED = MERGE.replace('            I_Contact( #n )\n', '')     # the rail and w8 become one node


def _lad(before, after):
    (p,) = compare_blocks(src(before, '', 'M'), src(after, '', 'M')).nets
    return p.lad


class MergedNodes(unittest.TestCase):
    def test_contact_deleted_between_two_wire_nodes_is_one_removed(self):
        d = _lad(MERGE, MERGED)
        self.assertEqual(statuses(d, d.b), Counter(same=10, removed=1))
        self.assertEqual(statuses(d, d.a), Counter(same=10))

    def test_contact_inserted_between_them_is_one_added(self):
        d = _lad(MERGED, MERGE)
        self.assertEqual(statuses(d, d.b), Counter(same=10))
        self.assertEqual(statuses(d, d.a), Counter(same=10, added=1))

    def test_a_contact_moved_to_another_branch_stays_moved(self):
        after = MERGE.replace('            Contact( #c )\n', '').replace('I_Contact( #m )', 'I_Contact( #m )\n            Contact( #c )')
        d = _lad(MERGE, after)
        moved = [e.operand() for e in d.b.elements.values() if d.status[e.eid] == 'moved']
        self.assertEqual(moved, ['#c'])
        self.assertEqual(statuses(d, d.b), Counter(same=10, moved=1))

    def test_same_result_every_run(self):
        """Nothing in the diff depends on set order: the same report under any PYTHONHASHSEED."""
        import subprocess
        import sys
        code = ('from TiaChangeReports.tests.test_change_reports import MERGE, MERGED, _lad\n'
                'd = _lad(MERGE, MERGED)\nprint(sorted(d.status.items()), sorted(d.pair.items()))')
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        outs = {subprocess.run([sys.executable, '-c', code], cwd=root, capture_output=True, text=True, check=True,
                               env=dict(os.environ, PYTHONHASHSEED=str(s))).stdout for s in range(4)}
        self.assertEqual(len(outs), 1, outs)

    def test_every_contact_deleted_in_the_fixture(self):
        """Every contact between two nodes of the fixture networks, deleted one at a time; among them the Filler's
        "Fine valve by recipe" network, where a deletion shows neighbours as moved without the merge step."""
        bad, count, without = [], 0, set()
        for b, n in lad_networks():
            for ri, r in enumerate(n.rungs):
                for ii, it in enumerate(r.items):
                    node_before = ii == 0 or isinstance(r.items[ii - 1], tuple)
                    node_after = isinstance(r.items[ii + 1], tuple) if ii + 1 < len(r.items) else bool(r.end)
                    if not (isinstance(it, Element) and it.kind == 'contact' and node_before and node_after
                            and sum(isinstance(x, Element) for x in r.items) >= 2):
                        continue
                    r2 = clone(n.rungs, 'z')
                    del r2[ri].items[ii]
                    d = NetDiff(Graph(n.rungs), Graph(r2))
                    sb, sa = statuses(d, d.b), statuses(d, d.a)
                    count += 1
                    if (sb - Counter(same=sb['same']), sa - Counter(same=sa['same'])) != (Counter(removed=1), Counter()):
                        bad.append('%s NW%d rung %d item %d: %s %s' % (b.label, n.index, ri, ii, dict(sb), dict(sa)))
                    if NetDiff(Graph(n.rungs), Graph(r2), merge=False).status != d.status:
                        without.add((b.name, n.index))
        self.assertGreater(count, 10)
        self.assertEqual(bad, [], '%d of %d' % (len(bad), count))
        self.assertIn(('Filler', 3), without)                     # the fixture holds the case the merge step is for


# ---------------------------------------------------------------- the result as JSON (for TiaBridge)

class JsonResult(unittest.TestCase):
    """--json prints the result as one object; the change log is no part of the tool."""

    def _repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = os.path.join(tmp.name, 'Plant')
        os.makedirs(r)
        _git(r, 'init', '-q')
        _git(r, 'config', 'core.autocrlf', 'false')
        _put(r, {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES, 'plc/B.s7dcl': SRC})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'one')
        _put(r, {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )')})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'two')
        return r

    def _main(self, args):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(args)
        return code, (json.loads(out.getvalue()) if code == 0 else None)

    def test_fragment_and_its_result(self):
        r = self._repo()
        frag = os.path.join(r, 'changes', 'reports', 'f.html')
        code, res = self._main(['--git', r, 'HEAD~1', 'HEAD', '-o', frag, '--fragment', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(res), ['after', 'before', 'blocks', 'page'])
        self.assertEqual(res['page'], frag)
        self.assertEqual([(b['name'], b['state'], b['networks']) for b in res['blocks']],
                         [('A', 'changed', [{'state': 'changed', 'lang': 'LAD', 'before': 1, 'after': 1,
                                             'title': 'Seal-in'}])])
        self.assertIn('HEAD~1', res['before'])
        with open(frag, encoding='utf-8') as f:
            self.assertTrue(f.read().startswith('<div class="ldiff">'))

    def test_no_change_log_option(self):
        r = self._repo()
        with self.assertRaises(SystemExit):
            self._main(['--git', r, 'HEAD~1', 'HEAD', '-o', os.path.join(r, 'p.html'), '--changelog', 'x.html'])


class ListingEncoding(unittest.TestCase):
    """The list printed into a pipe holds any title: on Windows a pipe is cp1252."""

    def test_title_outside_cp1252_into_a_pipe(self):
        import subprocess
        import sys
        title = 'Precondition ≥ 2 → Δ 起動'
        with tempfile.TemporaryDirectory() as d:
            _put(d, {'v1/T.s7dcl': SRC, 'v1/T.s7res': RES, 'v2/T.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                     'v2/T.s7res': RES.replace('Seal-in', title)})
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8')}
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            run = subprocess.run([sys.executable, 'TiaChangeReports', os.path.join(d, 'v1', 'T.s7dcl'),
                                  os.path.join(d, 'v2', 'T.s7dcl'), '--all', '-o', os.path.join(d, 'x.html')],
                                 cwd=root, capture_output=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', 'replace'))
        self.assertIn('was "Seal-in"', run.stdout.decode('utf-8'))
        self.assertIn(title, run.stdout.decode('utf-8'))


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'Main.xml')

# The fixture's LAD networks as the SD export writes them (the same model from both formats).
FIXTURE_SD = '''{ S7_PreferredLanguage := "LAD" }
ORGANIZATION_BLOCK "Main"
    VAR_TEMP
        latch : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #start )
            wire#w1
            I_Contact( #stop )
            Coil( #latch )
        END_RUNG
        RUNG wire#powerrail
            Contact( #latch )
        END_RUNG wire#w1
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "SrcType := Int" }
            GT_Contact(
                in1 := #count,
                in2 := 10
            )
            wire#w1
            Contact( "Tags".run )
            { S7_Templates := "time_type := Time" }
            "DelayDb".TON(
                pt := T#5s,
                et =>
            )
            Coil( #delayed )
        END_RUNG
        RUNG wire#w1
            Coil( #big )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            "Helper"(
                enable := wire#w1,
                target := "Data".cell[1, #count]."to",
                done => #b
            )
        END_RUNG
        RUNG wire#powerrail
            Contact( #a )
        END_RUNG wire#w1
    END_NETWORK
END_ORGANIZATION_BLOCK
'''


def _fixture(**repl):
    with open(FIXTURE, encoding='utf-8-sig') as f:
        text = f.read()
    for old, new in repl.items():
        assert old in text, old
        text = text.replace(old, new)
    return text


def _xml_src(text=None, name='Main'):
    return BlockSource(name, '', None, name + '.xml', xml=text if text is not None else _fixture())


class OrOfLegsWithBranchesInside(unittest.TestCase):
    """An OR of legs with a branch inside them, all closing at one node. TIA's export has one O for all of
    them, the legs' ends on its first inputs and the inner branches after them, so its input order is not the order of
    the rungs: as the SD export, each inner branch follows its own leg. Else the drawing joins the inner nodes."""

    @staticmethod
    def network(legs, branches=1, long_branches=False):
        """'in' on the rail, then legs: leg k is a{k} and, closing at one node, x{k}_0 and its branches x{k}_1.. from the
        node after a{k}, with long_branches each with a second contact y{k}_1... The O's inputs as TIA writes them: every
        leg's x{k}_0, then the branches."""
        parts, wires, names = [], [], {}
        def contact(name):
            uid = 100 + 2 * len(names)
            names[name] = uid
            parts.append('<Access Scope="LocalVariable" UId="%d"><Symbol><Component Name="%s" /></Symbol></Access>'
                         '<Part Name="Contact" UId="%d" />' % (uid, name, uid + 1))
            wires.append('<IdentCon UId="%d" /><NameCon UId="%d" Name="operand" />' % (uid, uid + 1))
            return uid + 1
        def wire(a, b):
            wires.append(NegatedPins.flow(a, 'out', b, 'in'))
        first = contact('in')
        wires.append('<Powerrail /><NameCon UId="%d" Name="in" />' % first)
        ends = {k: [] for k in range(branches + 1)}
        heads = []
        for leg in range(1, legs + 1):
            a = contact('a%d' % leg)
            heads.append(a)
            xs = [contact('x%d_%d' % (leg, k)) for k in range(branches + 1)]
            wires.append(''.join('<NameCon UId="%d" Name="%s" />' % c for c in [(a, 'out')] + [(x, 'in') for x in xs]))
            for k, x in enumerate(xs):
                if long_branches and k:
                    y = contact('y%d_%d' % (leg, k))
                    wire(x, y)
                    x = y
                ends[k].append(x)
        wires.append(''.join(['<NameCon UId="%d" Name="out" />' % first] + ['<NameCon UId="%d" Name="in" />' % a for a in heads]))
        parts.append('<Access Scope="LocalVariable" UId="98"><Symbol><Component Name="q" /></Symbol></Access><Part Name="Coil" UId="99" />')
        wires.append('<IdentCon UId="98" /><NameCon UId="99" Name="operand" />')
        inputs = [x for k in range(branches + 1) for x in ends[k]]
        parts.append('<Part Name="O" UId="97"><TemplateValue Name="Card" Type="Cardinality">%d</TemplateValue></Part>' % len(inputs))
        for n, x in enumerate(inputs, 1):
            wires.append(NegatedPins.flow(x, 'out', 97, 'in%d' % n))
        wires.append(NegatedPins.flow(97, 'out', 99, 'in'))
        flg = ('<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"><Parts>' + ''.join(parts)
               + '</Parts><Wires>' + ''.join('<Wire UId="%d">%s</Wire>' % (1000 + k, w) for k, w in enumerate(wires)) + '</Wires></FlgNet>')
        return parse_block(_xml_src(re.sub(r'<FlgNet .*?</FlgNet>', lambda m: flg, _fixture(), count=1, flags=re.S)))

    @staticmethod
    def order(block):
        return [[it.operand().lstrip('#') for it in r.items if not isinstance(it, tuple)] for r in block.networks[0].rungs]

    def test_each_inner_branch_follows_its_own_leg(self):
        self.assertEqual(self.order(self.network(3)),
                         [['in', 'a1', 'x1_0', 'q'], ['x1_1'], ['a2', 'x2_0'], ['x2_1'], ['a3', 'x3_0'], ['x3_1']])

    def test_two_branches_inside_a_leg(self):
        self.assertEqual(self.order(self.network(3, branches=2)),
                         [['in', 'a1', 'x1_0', 'q'], ['x1_1'], ['x1_2'], ['a2', 'x2_0'], ['x2_1'], ['x2_2'], ['a3', 'x3_0'], ['x3_1'], ['x3_2']])

    def test_an_inner_branch_of_two_contacts(self):
        self.assertEqual(self.order(self.network(3, long_branches=True)),
                         [['in', 'a1', 'x1_0', 'q'], ['x1_1', 'y1_1'], ['a2', 'x2_0'], ['x2_1', 'y2_1'], ['a3', 'x3_0'], ['x3_1', 'y3_1']])

    def test_the_drawing_keeps_the_nodes_after_the_legs_apart(self):
        for legs in (2, 3, 4, 5):
            for long_branches in (False, True):
                block = self.network(legs, long_branches=long_branches)
                self.assertEqual(check(Layout(block.networks[0].rungs, block.interface)), [], (legs, long_branches))


class SimaticML(unittest.TestCase):
    """OBs (SimaticML only) and other SimaticML block exports, read into the model of the .s7dcl parser."""

    def test_lad_networks_as_the_sd_export_writes_them(self):
        from TiaChangeReports.simaticml import rungs_text
        xb, sb = parse_block(_xml_src()), parse_block(src(FIXTURE_SD, ''))
        lad = [n for n in xb.networks if n.lang == 'LAD']
        self.assertEqual([n.title for n in xb.networks], ['Seal-in', 'Delay', 'Helper', 'Cell text'])
        self.assertEqual(len(lad), len(sb.networks))
        for x, s in zip(lad, sb.networks):
            self.assertEqual(rungs_text(x.rungs), rungs_text(s.rungs))
            self.assertFalse(NetDiff(Graph(x.rungs), Graph(s.rungs)).changed)
        timer = lad[1].rungs[0].items[3]
        self.assertEqual((timer.instr, timer.instance, timer.templates), ('TON', '"DelayDb"', {'time_type': 'Time'}))

    def test_scl_network_text(self):
        from TiaChangeReports.s7dcl import scl_lines
        scl = parse_block(_xml_src()).networks[3]
        self.assertEqual(scl.lang, 'SCL')
        self.assertEqual(scl_lines(scl.body), ['// Text of the cell',
                                               "#text := CONCAT_STRING(IN1 := 'cell ', IN2 := \"Data\".\"to\".name);",
                                               '#count := "Count"(#text);'])

    def test_ob_header_and_interface(self):
        b = parse_block(_xml_src())
        self.assertEqual((b.kind, b.decl), ('ORGANIZATION_BLOCK', '"Main"'))
        self.assertEqual((b.props['S7_BlockNumber'], b.props['Event class'], b.props['S7_BlockTitle']),
                         ('1', 'ProgramCycle', 'Main program sweep (cycle)'))
        latch = b.interface.root.children['latch']
        self.assertEqual((latch.section, latch.type, latch.comment), ('TEMP', 'Bool', 'Motor latched on'))
        self.assertEqual(b.interface.comment_of('#Initial_Call'), 'Initial call of this OB')

    def test_one_operand_changed_in_one_network(self):
        after = _fixture(**{'<Component Name="stop" />': '<Component Name="halt" />'})
        d = compare_blocks(_xml_src(), _xml_src(after))
        self.assertEqual((d.state, d.kind, [p.title for p in d.nets]), ('changed', 'OB', ['Seal-in']))
        st = Counter(d.nets[0].lad.status.values())
        self.assertEqual((st['changed'], st['added'], st['removed']), (2, 0, 0))   # before and after side

    def test_a_new_export_of_the_same_block_is_no_change(self):
        again = _fixture(**{'2026-10-22T17:35:50.4361467Z': '2026-10-28T09:00:00.0000000Z'})
        self.assertIsNone(compare_blocks(_xml_src(), _xml_src(again)))
        renumbered = _fixture(**{'<Wire UId="37">': '<Wire UId="97">'})                 # TIA numbers anew
        d = compare_blocks(_xml_src(), _xml_src(renumbered))
        self.assertEqual(d.state, 'same')

    def test_drawing_reads_back_as_the_code(self):
        b = parse_block(_xml_src())
        for n in b.networks:
            if n.rungs:
                self.assertEqual(check(Layout(n.rungs, b.interface)), [], n.title)

    def test_an_empty_lad_network(self):
        text = _fixture()
        i, j = text.index('<NetworkSource><FlgNet'), text.index('</FlgNet></NetworkSource>') + 25
        d = compare_blocks(_xml_src(), _xml_src(text[:i] + '<NetworkSource />' + text[j:]))
        self.assertEqual(d.nets[0].before.rungs and d.nets[0].after.rungs, [])
        self.assertEqual((d.nets[0].title, d.nets[0].state), ('Seal-in', 'changed'))

    def test_folder_lists_block_exports_not_hmi_and_prefers_the_sd_export(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/blocks/00_OBs/Main.xml': _fixture(),
                       'plc/blocks/FG/Mode01.xml': _fixture(), 'plc/blocks/FG/Mode01.s7dcl': SRC,
                       'hmi/screens/Start.xml': '<Document><Hmi.Screen.Screen ID="0" /></Document>',
                       'plc/tags/Tags.xml': '<Document><SW.Tags.PlcTagTable ID="0" /></Document>'})
            snap = FolderSnapshot(d)
            self.assertEqual(snap.paths(), ['plc/blocks/00_OBs/Main.xml', 'plc/blocks/FG/Mode01.s7dcl'])
            src_ = snap.load('plc/blocks/00_OBs/Main.xml')
            self.assertEqual((src_.name, src_.s7dcl), ('Main', ''))
            self.assertTrue(src_.xml.lstrip('\ufeff').startswith('<?xml'))
            self.assertEqual(from_file(os.path.join(d, 'plc/blocks/00_OBs/Main.xml')).xml, src_.xml)

    def test_a_block_that_changed_format_pairs_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'a/plc/blocks/X/Main.xml': _fixture(), 'b/plc/blocks/X/Main.s7dcl': FIXTURE_SD,
                       'a/plc/blocks/Y/Main2.xml': _fixture(), 'b/plc/blocks/Z/Main2.s7dcl': FIXTURE_SD})
            pairs = pair_blocks(FolderSnapshot(os.path.join(d, 'a')), FolderSnapshot(os.path.join(d, 'b')))
            self.assertEqual(sorted(pairs), [('plc/blocks/X/Main.xml', 'plc/blocks/X/Main.s7dcl'),
                                             ('plc/blocks/Y/Main2.xml', 'plc/blocks/Z/Main2.s7dcl')])

    def test_git_revisions_compare_an_ob(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, {'plc/blocks/OB/Main.xml': _fixture(), 'hmi/screens/S.xml': '<Document><Hmi.Screen.Screen/></Document>'})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {'plc/blocks/OB/Main.xml': _fixture(**{'<Component Name="stop" />': '<Component Name="halt" />'}),
                     'hmi/screens/S.xml': '<Document><Hmi.Screen.Screen ID="1"/></Document>'})
            _git(r, 'commit', '-q', '-am', 'two')
            before, after = git_snapshots(r, 'HEAD~1', 'HEAD')
            self.assertEqual(after.paths(), ['plc/blocks/OB/Main.xml'])
            ds = compare_snapshots(before, after)
            self.assertEqual([(d.block.name, d.kind, [p.title for p in d.nets]) for d in ds],
                             [('Main', 'OB', ['Seal-in'])])
            wt = git_snapshots(r, 'HEAD~1')[1]
            self.assertEqual(wt.paths(), ['plc/blocks/OB/Main.xml'])

    def test_verify_covers_simaticml_exports(self):
        import io
        from contextlib import redirect_stdout
        from TiaChangeReports.verify import main
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'OB/Main.xml': _fixture(), 'hmi/S.xml': '<Document><Hmi.Screen.Screen/></Document>'})
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([d])
        self.assertEqual((code, out.getvalue().splitlines()[0]), (0, '3 LAD networks, 0 with problems'))

    def test_verify_usage(self):
        """--help prints the usage; no path or a missing one: one line on stderr, exit 2."""
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from TiaChangeReports.verify import main
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ex:
            main(['--help'])
        self.assertEqual(ex.exception.code, 0)
        self.assertIn('python -m TiaChangeReports.verify <export.s7dcl | export.xml | folder> ...', out.getvalue())
        missing = os.path.join(PLANT, 'no such folder')
        for argv, msg in (([], 'nothing to check: give export files or folders'),
                          ([PLANT, missing],'neither an export file nor a folder: %s' % missing)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
            self.assertEqual((code, out.getvalue(), err.getvalue()), (2, '', msg + '\n'))

    def test_s7dcl_quoted_pins_and_instances_of_system_blocks(self):
        b = parse_block(src('''FUNCTION_BLOCK "F"
    VAR
        "instE" : ESTOP1;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            #"instE".ESTOP1(
                E_STOP := #x,
                Q => #y
            )
            "RcvDb".RCVDP(
                ACK_REI := #x
            )
            "Drive"(
                "iSq01/05" := #x
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
''', ''))
        e, r, c = b.networks[0].rungs[0].items
        labelled = parse_block(src(SRC.replace('NETWORK\n        RUNG', 'NETWORK\n        Label(Skip)\n        RUNG', 1)))
        self.assertEqual(len(labelled.networks[0].rungs), len(parse_block(src()).networks[0].rungs))  # a jump label
        self.assertEqual(labelled.networks[0].label, 'Skip')
        self.assertEqual((e.instr, e.instance), ('ESTOP1', '#"instE"'))
        self.assertEqual((r.instr, r.instance), ('RCVDP', '"RcvDb"'))
        self.assertEqual((c.instr, c.call, c.params), ('CALL', 'Drive', [('iSq01/05', ':=', '#x')]))


# ---------------------------------------------------------------- renamed members and member order

ORD = '''FUNCTION_BLOCK "O"
    VAR
        { S7_MLC := "MLC_1" }
        run : Bool;
        { S7_MLC := "MLC_2" }
        speed : Int;
        s : STRUCT
            { S7_MLC := "MLC_3" }
            x : Bool;
            y : Bool;
        END_STRUCT;
        z : Bool;
    END_VAR
END_FUNCTION_BLOCK
'''
ORD_RES = ('MultiLingualTexts:\n  - id: MLC_1\n    en-US: drive runs\n  - id: MLC_2\n    en-US: set speed\n'
           '  - id: MLC_3\n    en-US: x flag\n')


def _rows(t_b, t_a, r_b=ORD_RES, r_a=ORD_RES):
    b, a = parse_block(src(t_b, r_b, 'O')), parse_block(src(t_a, r_a, 'O'))
    return {'.'.join(r.path): r for r in iface.rows(b.interface, a.interface)}


class InterfaceRenamesOrder(unittest.TestCase):
    def test_same_type_and_comment_in_the_same_struct_is_a_rename(self):
        rs = _rows(ORD, ORD.replace('run : Bool', 'running : Bool').replace('x : Bool', 'xx : Bool'))
        self.assertNotIn('run', rs)
        self.assertEqual((rs['running'].state, rs['running'].changes, rs['running'].bpath),
                         ('changed', {'name'}, ('run',)))
        self.assertEqual((rs['s.xx'].state, rs['s.xx'].bpath), ('changed', ('s', 'x')))

    def test_other_comment_or_no_comment_in_the_same_place_is_a_rename(self):
        """The place decides; before, these were left removed + added."""
        for old, new, res, path, changes in (
                ('run : Bool', 'running : Bool', ORD_RES.replace('drive runs', 'drive on'), 'running',
                 {'name', 'comment'}),
                ('speed : Int', 'v : DInt', ORD_RES, 'v', {'name', 'type'}),          # same comment, other type
                ('z : Bool', 'w : Bool', ORD_RES, 'w', {'name'}),                     # no comment: the place
                ('y : Bool', 'yy : Bool', ORD_RES, 's.yy', {'name'})):
            rs = _rows(ORD, ORD.replace(old, new), r_a=res)
            self.assertEqual({p: (r.state, r.changes) for p, r in rs.items() if r.state != 'same'},
                             {path: ('changed', changes)}, old)

    def test_other_type_and_other_comment_is_removed_and_added(self):
        rs = _rows(ORD, ORD.replace('speed : Int', 'v : DInt'), r_a=ORD_RES.replace('set speed', 'velocity'))
        self.assertEqual({p: r.state for p, r in rs.items() if r.state != 'same'}, {'speed': 'removed', 'v': 'added'})

    def test_member_moved_out_of_a_struct_is_removed_and_added(self):
        """As statWaiting.Here -> statWaitingHere."""
        t2 = ORD.replace('            { S7_MLC := "MLC_3" }\n            x : Bool;\n', '').replace(
            '        z : Bool;', '        z : Bool;\n        { S7_MLC := "MLC_3" }\n        sx : Bool;')
        rs = _rows(ORD, t2)
        self.assertEqual((rs['s.x'].state, rs['sx'].state), ('removed', 'added'))

    def test_two_candidates_of_one_comment_pair_by_place(self):
        """The same comment twice is no evidence; each pairs in its own place."""
        t1 = ORD.replace('        z : Bool;', '        { S7_MLC := "MLC_1" }\n        run2 : Bool;')
        t2 = t1.replace('run : Bool', 'a1 : Bool').replace('run2 : Bool', 'a2 : Bool')
        rs = _rows(t1, t2)
        self.assertEqual({p: r.bpath for p, r in rs.items() if r.state != 'same'}, {'a1': ('run',), 'a2': ('run2',)})

    def test_renamed_struct_keeps_its_members(self):
        t1 = ORD.replace('        s : STRUCT', '        { S7_MLC := "MLC_2" }\n        s : STRUCT')
        t2 = t1.replace('s : STRUCT', 'st : STRUCT')
        rs = _rows(t1, t2)
        self.assertEqual(rs['st'].changes, {'name'})
        self.assertEqual({p: r.state for p, r in rs.items() if p.startswith('st.')}, {'st.x': 'same', 'st.y': 'same'})

    def test_member_order(self):
        t2 = ORD.replace('        { S7_MLC := "MLC_1" }\n        run : Bool;\n', '').replace(
            '        z : Bool;', '        z : Bool;\n        { S7_MLC := "MLC_1" }\n        run : Bool;')
        rs = _rows(ORD, t2)
        self.assertEqual({p: r.state for p, r in rs.items() if r.state != 'same'}, {'run': 'moved'})
        self.assertEqual(rs['run'].order, ('first', 'last'))

    def test_added_removed_or_renamed_members_are_no_reorder(self):
        t2 = ORD.replace('run : Bool', 'running : Bool').replace('        z : Bool;\n', '').replace(
            '            y : Bool;', '            w : Bool;\n            y : Bool;')
        rs = _rows(ORD, t2)
        self.assertEqual({p: r.state for p, r in rs.items() if r.state != 'same'},
                         {'running': 'changed', 'z': 'removed', 's.w': 'added'})

    def test_page_shows_rename_and_move(self):
        t2 = ORD.replace('run : Bool', 'running : Bool').replace(
            '            { S7_MLC := "MLC_3" }\n            x : Bool;\n            y : Bool;',
            '            y : Bool;\n            { S7_MLC := "MLC_3" }\n            x : Bool;')
        html = iface.html(parse_block(src(ORD, ORD_RES, 'O')), parse_block(src(t2, ORD_RES, 'O')))
        self.assertIn('<span class="tx del"><span>run</span></span> <span class="tx ins"><span>running</span></span>', html)
        self.assertRegex(html, r'<tr class="mov"><td class="nm"[^>]*><span class="tw"></span>x<div class="ex">order: was first, now last<')
        self.assertTrue(compare_blocks(src(ORD, ORD_RES, 'O'), src(t2, ORD_RES, 'O')).itf_changed)

    def test_each_changed_property_once(self):
        got = iface.props_rows({'S7_Version': '0.1', 'S7_BlockNumber': '5', 'S7_Other': 'a'},
                               {'S7_Version': '0.2', 'S7_BlockNumber': '6', 'S7_Other': 'b'})
        self.assertEqual(got, [('Version', '0.1', '0.2'), ('Number', '5', '6'), ('S7_Other', 'a', 'b')])

    def test_udt_member_moved_to_the_top(self):
        rel = 'library/types/Bottling/FillerHw_UDT/FillerHw_UDT.s7dcl'
        old, new = (parse_block(from_file(os.path.join(r, rel))) for r in (V1, V2))
        rs = {'.'.join(r.path): r for r in iface.rows(old.interface, new.interface)}
        moved = [p for p, r in rs.items() if 'order' in r.changes]
        self.assertEqual(moved, ['Probe.High'])
        self.assertEqual(rs['Probe.High'].order, ('last', 'first'))


# ---------------------------------------------------------------- interface edits as TIA users make them

EDITS = '''FUNCTION_BLOCK "E"
    VAR
        k0 : Bool;
        a : Int;
        b : Int;
        k1 : Bool;
        { S7_MLC := "MLC_1" }
        gone : Int;
        { S7_MLC := "MLC_2" }
        kept : Int;
        k2 : Bool;
        st : STRUCT
            p : Bool;
            q : Int;
        END_STRUCT;
        k3 : Bool;
        instT : TON_TIME;
        k4 : Bool;
        last : Bool;
    END_VAR
    VAR_TEMP
        calc2 : DInt;
        calc3 : DInt;
        calc4 : DInt;
        idxCase : USInt;
    END_VAR
    VAR CONSTANT
        LIMIT : Int := 10;
    END_VAR
END_FUNCTION_BLOCK
'''
EDITS_RES = ('MultiLingualTexts:\n  - id: MLC_1\n    en-US: to delete\n  - id: MLC_2\n    en-US: counter kept\n')


def _edits(*repl, before=EDITS, res_a=EDITS_RES):
    after = before
    for old, new in repl:
        assert old in after, old
        after = after.replace(old, new)
    rs = _rows(before, after, EDITS_RES, res_a)
    return {p: (r.state, r.bpath and '.'.join(r.bpath)) for p, r in rs.items() if r.state != 'same'}


class InterfaceEditsLikeTia(unittest.TestCase):
    """Renames found by the place in the interface, as TIA users rename."""

    def test_temps_renamed_in_place_without_comments(self):
        """OB1 as first seen: three uncommented temps renamed in one gap, one added at the end."""
        got = _edits(('calc2 :', 'calc2222 :'), ('calc3 :', 'calc3312 :'), ('calc4 :', 'calc4123 :'),
                     ('        idxCase : USInt;\n', '        idxCase : USInt;\n        test1 : Bool;\n'))
        self.assertEqual(got, {'calc2222': ('changed', 'calc2'), 'calc3312': ('changed', 'calc3'),
                               'calc4123': ('changed', 'calc4'), 'test1': ('added', None)})

    def test_simaticml_temps_renamed_in_place(self):
        b = parse_block(_xml_src())
        a = parse_block(_xml_src(_fixture(**{'<Member Name="count" Datatype="Int" />':
                                             '<Member Name="counter" Datatype="Int" />'})))
        rs = {'.'.join(r.path): r for r in iface.rows(b.interface, a.interface) if r.state != 'same'}
        self.assertEqual({p: (r.changes, r.bpath) for p, r in rs.items()}, {'counter': ({'name'}, ('count',))})

    def test_deleted_member_beside_a_renamed_one_goes_by_the_comment(self):
        """Pairing in order would take the deleted member (first, same type); its comment says otherwise."""
        got = _edits(('        { S7_MLC := "MLC_1" }\n        gone : Int;\n', ''), ('kept : Int', 'renamed : Int'))
        self.assertEqual(got, {'gone': ('removed', 'gone'), 'renamed': ('changed', 'kept')})

    def test_more_removed_than_added_pairs_none(self):
        """'a, b : Int' -> 'c : Int' stays removed + added, as does a renamed last member with a new one
        after it."""
        self.assertEqual(_edits(('        a : Int;\n        b : Int;\n', '        c : Int;\n')),
                         {'a': ('removed', 'a'), 'b': ('removed', 'b'), 'c': ('added', None)})
        self.assertEqual(_edits(('        last : Bool;\n', '        lastNew : Bool;\n        newLast : Bool;\n')),
                         {'last': ('removed', 'last'), 'lastNew': ('added', None), 'newLast': ('added', None)})

    def test_same_count_pairs_only_members_of_one_type(self):
        got = _edits(('        a : Int;\n        b : Int;\n', '        x : Int;\n        y : Real;\n'))
        self.assertEqual(got, {'x': ('changed', 'a'), 'b': ('removed', 'b'), 'y': ('added', None)})

    def test_struct_renamed_without_comment_keeps_its_members(self):
        got = _edits(('st : STRUCT', 'stNew : STRUCT'), ('            q : Int;', '            qNew : Int;'))
        self.assertEqual(got, {'stNew': ('changed', 'st'), 'stNew.qNew': ('changed', 'st.q')})

    def test_struct_filled_with_other_members_is_removed_and_added(self):
        got = _edits(('st : STRUCT\n            p : Bool;\n            q : Int;',
                      'other : STRUCT\n            r : Real;'))
        self.assertEqual({p: s for p, (s, _) in got.items()},
                         {'st': 'removed', 'st.p': 'removed', 'st.q': 'removed', 'other': 'added', 'other.r': 'added'})

    def test_multi_instance_and_constant_renamed(self):
        self.assertEqual(_edits(('instT : TON_TIME', 'instDelay : TON_TIME'), ('LIMIT : Int', 'MAX_COUNT : Int')),
                         {'instDelay': ('changed', 'instT'), 'MAX_COUNT': ('changed', 'LIMIT')})

    def test_renamed_and_changed_shows_both(self):
        rs = _rows(EDITS, EDITS.replace('        b : Int;', '        bb : Int := 5;'))
        self.assertEqual((rs['bb'].changes, rs['bb'].bpath), ({'name', 'value'}, ('b',)))

    def test_udt_member_renamed(self):
        t = 'TYPE\n    "U" : STRUCT\n        m1 : Bool;\n        m2 : Int;\n        m3 : Int;\n    END_STRUCT;\nEND_TYPE\n'
        rs = _rows(t, t.replace('m2 :', 'm2New :'), None, None)
        self.assertEqual({p: r.bpath for p, r in rs.items() if r.state != 'same'}, {'m2New': ('m2',)})

    def test_global_db_member_renamed_keeps_its_start_values(self):
        t = ('DATA_BLOCK "D"\n    VAR\n        d1 : Int;\n        dSp : Bool;\n        d2 : STRUCT\n'
             '            m3 : Int;\n        END_STRUCT;\n    END_VAR\n\n    d1 := 3;\n    d2.m3 := 4;\n\nEND_DATA_BLOCK\n')
        a = t.replace('d1 :', 'd1New :').replace('d1 :=', 'd1New :=').replace('d2', 'd2New')
        rs = _rows(t, a, None, None)
        self.assertEqual({p: r.bpath for p, r in rs.items() if r.state != 'same'},
                         {'d1New': ('d1',), 'd2New': ('d2',)})
        self.assertEqual((rs['d1New'].changes, rs['d2New.m3'].state, rs['d2New.m3'].a.value), ({'name'}, 'same', '4'))

    def test_array_renamed_keeps_its_elements(self):
        """An element's key carries its array's name: 'arr[1]' under 'list' is 'list[1]', not removed + added."""
        t = EDITS.replace('        k2 : Bool;\n', '        k2 : Bool;\n        arr : Array[1..2] of STRUCT\n'
                          '            ep : Bool;\n            eq : Int;\n        END_STRUCT;\n        k5 : Bool;\n')
        rs = _rows(t, t.replace('arr :', 'list :'))
        self.assertEqual({p: (r.state, r.changes) for p, r in rs.items() if r.state != 'same'},
                         {'list': ('changed', {'name'})})
        self.assertEqual(rs['list.list[1].eq'].bpath, ('arr', 'arr[1]', 'eq'))
        d = ('DATA_BLOCK "D"\n    VAR\n        arr : Array[0..3] of Int;\n        k : Bool;\n    END_VAR\n\n'
             '    arr[2] := 7;\n\nEND_DATA_BLOCK\n')
        rs = _rows(d, d.replace('arr', 'vals'), None, None)
        self.assertEqual({p: (r.state, r.changes) for p, r in rs.items() if r.state != 'same'},
                         {'vals': ('changed', {'name'})})
        self.assertEqual(rs['vals.vals[2]'].a.value, '7')

    def test_member_moved_out_of_or_into_a_struct_keeps_its_name_is_moved(self):
        """Not renamed, moved; renamed, removed + added (test_member_moved_out_of_a_struct_is_removed_and_added)."""
        out = _edits(('            q : Int;\n', ''), ('        k3 : Bool;\n', '        k3 : Bool;\n        q : Int;\n'))
        self.assertEqual(out, {'q': ('moved', 'st.q')})
        into = _edits(('        k4 : Bool;\n', ''), ('            q : Int;\n', '            q : Int;\n            k4 : Bool;\n'))
        self.assertEqual(into, {'st.k4': ('moved', 'k4')})
        rs = _rows(EDITS, EDITS.replace('            q : Int;\n', '').replace(
            '        k3 : Bool;\n', '        k3 : Bool;\n        q : Int;\n'))
        self.assertEqual(rs['q'].changes, {'parent'})
        html = iface.html(parse_block(src(EDITS, EDITS_RES, 'E')), parse_block(src(EDITS.replace(
            '            q : Int;\n', '').replace('        k3 : Bool;\n', '        k3 : Bool;\n        q : Int;\n'),
            EDITS_RES, 'E')))
        self.assertRegex(html, r'<tr class="mov"><td class="nm"[^>]*><span class="tw"></span>q<div class="ex">'
                               r'moved: st\.q → q<')

    def test_member_moved_to_another_section_is_moved_renamed_is_removed_and_added(self):
        t = EDITS.replace('        k4 : Bool;\n', '')
        moved = _rows(EDITS, t.replace('        idxCase : USInt;\n', '        idxCase : USInt;\n        k4 : Bool;\n'))
        self.assertEqual((moved['k4'].state, moved['k4'].changes), ('moved', {'section'}))
        renamed = _edits(('        k4 : Bool;\n', ''),
                         ('        idxCase : USInt;\n', '        idxCase : USInt;\n        t4 : Bool;\n'))
        self.assertEqual(renamed, {'k4': ('removed', 'k4'), 't4': ('added', None)})

    def test_function_return_type(self):
        """A changed return type was no change at all: TIA's Return section, one row named as the block."""
        fc = ('FUNCTION "F" : Int\n    VAR_INPUT\n        inX : Int;\n    END_VAR\n\n    { S7_Language := "SCL" }\n'
              '    NETWORK\n        #F := #inX;\n    END_NETWORK\nEND_FUNCTION\n')
        b, a = src(fc, None, 'F'), src(fc.replace('"F" : Int', '"F" : DInt'), None, 'F')
        self.assertTrue(compare_blocks(b, a).itf_changed)
        rs = {'.'.join(r.path): r for r in iface.block_rows(parse_block(b), parse_block(a))}
        self.assertEqual((rs['F'].state, rs['F'].changes, rs['F'].a.section), ('changed', {'type'}, 'RETURN'))
        html = iface.html(parse_block(b), parse_block(a))
        self.assertIn('Return</td>', html)
        self.assertIn('<span class="tx del"><span>Int</span></span> <span class="tx ins"><span>DInt</span></span>', html)
        self.assertFalse(iface.changed(parse_block(b), parse_block(b)))
        void = src(fc.replace('"F" : Int', '"F" : Void'), None, 'F')
        self.assertNotIn('F', {'.'.join(r.path) for r in iface.block_rows(parse_block(void), parse_block(void))})

    def test_edits_as_tias_editor_writes_them(self):
        """Edits made in TIA's editor as its export showed them (an experiment in TIA, made-up names): a row
        inserted where one was deleted, also with the old comment typed again and other boxes; cut, pasted further
        down and renamed; a temp pasted into Static (not accessible there); an output cut into InOut (first there);
        renamed with retain and Accessible unticked."""
        t = '''FUNCTION_BLOCK "X"
    VAR_OUTPUT
        oA : Bool;
        oB : Int;
    END_VAR
    VAR_IN_OUT
        ioA : Int;
    END_VAR
    VAR
        k0 : Bool;
        old1 : Bool;
        k1 : Bool;
        { S7_MLC := "MLC_1" }
        old2 : Bool;
        k2 : Bool;
        { S7_MLC := "MLC_2" }
        mover : Bool;
        k3 : Bool;
        { S7_MLC := "MLC_3" }
        level : Int;
        k4 : Bool;
        land1 : Bool;
        land2 : Bool;
    END_VAR
    VAR_TEMP
        tmp : Int;
        tKeep : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
        res = ('MultiLingualTexts:\n  - id: MLC_1\n    en-US: typed again\n  - id: MLC_2\n    en-US: cut and renamed\n'
               '  - id: MLC_3\n    en-US: level\n')
        a = '''FUNCTION_BLOCK "X"
    VAR_OUTPUT
        oA : Bool;
    END_VAR
    VAR_IN_OUT
        oB : Int;
        ioA : Int;
    END_VAR
    VAR
        k0 : Bool;
        new1 : Bool;
        k1 : Bool;
        {
            S7_Access := "ReadOnly := External";
            S7_MLC := "MLC_1";
            S7_Visibility := "Hidden := External"
        }
        new2 : Bool;
        k2 : Bool;
        k3 : Bool;
    END_VAR
    VAR RETAIN
        {
            S7_Access := "ReadOnly := External";
            S7_MLC := "MLC_3";
            S7_Visibility := "Hidden := External"
        }
        levelNew : Int;
    END_VAR
    VAR
        k4 : Bool;
        land1 : Bool;
        { S7_MLC := "MLC_2" }
        moved : Bool;
        land2 : Bool;
        {
            S7_Access := "ReadOnly := External";
            S7_Visibility := "Hidden := External"
        }
        tmp : Int;
    END_VAR
    VAR_TEMP
        tKeep : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
        rs = _rows(t, a, res, res)
        got = {p: (r.state, r.bpath and '.'.join(r.bpath), sorted(r.changes)) for p, r in rs.items() if r.state != 'same'}
        self.assertEqual(got, {
            'oB': ('moved', 'oB', ['section']),
            'new1': ('changed', 'old1', ['name']),
            'new2': ('changed', 'old2', ['attrs', 'name']),           # deleted + inserted in place: reads as renamed
            'moved': ('changed', 'mover', ['name', 'order']),
            'levelNew': ('changed', 'level', ['attrs', 'name', 'retain']),
            'tmp': ('changed', 'tmp', ['attrs', 'section'])})

    def test_page_shows_a_rename_by_place(self):
        t2 = EDITS.replace('calc3 :', 'calc3312 :')
        html = iface.html(parse_block(src(EDITS, EDITS_RES, 'E')), parse_block(src(t2, EDITS_RES, 'E')))
        self.assertIn('<span class="tx del"><span>calc3</span></span> <span class="tx ins"><span>calc3312</span></span>', html)
        self.assertNotIn('class="ins"', html)
        self.assertNotIn('class="del"', html)


# ---------------------------------------------------------------- interface tables like TIA

ESTOP = 'TYPE\n    typeStopSw : STRUCT\n        { S7_MLC := "MLC_e" }\n        q : Bool;\n    END_STRUCT;\nEND_TYPE\n'
DB = '''{ S7_Optimized := "TRUE" }
DATA_BLOCK StopDb
    VAR
        { S7_MLC := "MLC_1" }
        a : Bool;
        { S7_MLC := "MLC_2" }
        e : _.typeStopSw;
        arr : Array[0..3] of Int;
        z : Bool;
    END_VAR

END_DATA_BLOCK
'''
DB_RES = ('MultiLingualTexts:\n  - id: MLC_1\n    en-US: flag a\n  - id: MLC_2\n    en-US: estop\n'
          '  - id: MLC_Q\n    en-US: 1 = released\n')
DB_START = DB.replace('    END_VAR\n', '    END_VAR\n\n        { S7_MLC := "MLC_Q" }\n        "e".q := ();\n'
                      '        arr[2] := 5;\n')


def _types(**itfs):
    """A Callees stand-in: name -> interface."""
    parsed = {k: parse_block(src(v, 'MultiLingualTexts:\n  - id: MLC_e\n    en-US: estop ok\n', k)).interface
              for k, v in itfs.items()}
    return lambda name: parsed.get(name)


def _trs(html):
    """The rows of the interface table: [(class, [cell texts])]."""
    out = []
    for cls, body in re.findall(r'<tr(?: class="([^"]*)")?>(.*?)</tr>', html, re.S):
        cells = [re.sub(r'<[^>]+>', '', re.sub(r'<span class="tw">(.*?)</span>', r'\1 ', c)).strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', body, re.S)]
        out.append((cls, cells))
    return out


class InterfaceLikeTia(unittest.TestCase):
    def test_data_types_as_tia_names_them(self):
        for sd, tia in (('_.typeStopSw', '"typeStopSw"'), ('_."Plc/Comm"', '"Plc/Comm"'), ('STRUCT', 'Struct'),
                        ('Array[0.._.MAX] of _.X', 'Array[0.."MAX"] of "X"'),
                        ('Array[*, *, *] of _.FillData_UDT', 'Array[*, *, *] of "FillData_UDT"'),
                        ('Array[0..3] of STRUCT', 'Array[0..3] of Struct'), ('"$"ControlA12Unit$""', '"ControlA12Unit"'),
                        ('IEC_TIMER', 'IEC_TIMER'), ('REF_TO "typeLink"', 'REF_TO "typeLink"'),
                        ('Bool', 'Bool'), ('String[40]', 'String[40]')):
            self.assertEqual(iface.tia_type(sd), tia)

    def test_type_spelled_otherwise_is_no_change(self):
        """SimaticML gives _.a/b where the SD export writes _."a/b"."""
        t1 = DB.replace('_.typeStopSw', '_."type/StopSw"')
        rs = {'.'.join(r.path): r for r in iface.rows(parse_block(src(t1, DB_RES, 'D')).interface,
                                                      parse_block(src(DB.replace('_.typeStopSw', '_.type/StopSw'),
                                                                      DB_RES, 'D')).interface)}
        self.assertEqual(rs['e'].state, 'same')

    def test_start_value_of_a_udt_member_goes_under_its_member(self):
        b, a = parse_block(src(DB, DB_RES, 'D')), parse_block(src(DB_START, DB_RES, 'D'))
        rs = iface.rows(b.interface, a.interface, (_types(typeStopSw=ESTOP),) * 2)
        paths = [r.path for r in rs]
        self.assertEqual(paths, [('a',), ('e',), ('e', 'q'), ('arr',), ('arr', 'arr[2]'), ('z',)])
        q, el = rs[2], rs[4]                              # in the type on both sides: changed
        self.assertEqual((q.state, q.changes, q.a.type, q.a.comment, q.a.value),
                         ('changed', {'comment'}, 'Bool', '1 = released', None))
        self.assertEqual((el.state, el.changes, el.a.type, el.a.value), ('changed', {'value'}, 'Int', '5'))
        self.assertEqual(rs[1].state, 'same')

    def test_start_value_comment_changed_is_a_changed_member(self):
        b = parse_block(src(DB_START, DB_RES, 'D'))
        a = parse_block(src(DB_START, DB_RES.replace('1 = released', '1 = released and acknowledged'), 'D'))
        rs = {'.'.join(r.path): r for r in iface.rows(b.interface, a.interface)}
        self.assertEqual((rs['e.q'].state, rs['e.q'].changes), ('changed', {'comment'}))

    def test_one_tree_in_place_with_the_parent_first(self):
        b, a = parse_block(src(DB, DB_RES, 'D')), parse_block(src(DB_START, DB_RES, 'D'))
        trs = _trs(iface.html(b, a))
        head = trs[0][1]
        self.assertEqual(head[:3], ['Name', 'Data type', 'Start value'])
        self.assertEqual(head[-1], 'Comment')
        self.assertNotIn('Start value', [c for _, cs in trs[1:] for c in cs])      # no table of its own
        names = [cs[0] for _, cs in trs[1:]]
        self.assertEqual(names[0], '▼ Static')
        k = names.index('▼ e')
        self.assertEqual(names[k + 1], 'q')
        self.assertEqual(trs[1 + k][0], '')                                     # e unchanged, shown as the parent
        self.assertEqual(trs[2 + k][0], 'chg')                                  # q is in the UDT before too

    def test_unchanged_siblings_fold_where_they_are(self):
        t2 = DB.replace('        z : Bool;\n', '        z : Bool;\n        w : Int;\n')
        trs = _trs(iface.html(parse_block(src(DB, DB_RES, 'D')), parse_block(src(t2, DB_RES, 'D'))))
        shown = [(c, cs[0]) for c, cs in trs[1:] if not c.endswith('ctx')]
        self.assertEqual([x[1] for x in shown], ['▼ Static', '⋯ 4 unchanged members (click to show all)', 'w'])

    def test_udt_and_array_members_fold_like_tia(self):
        t2 = DB.replace('        z : Bool;\n', '        w : Int;\n')
        html = iface.html(parse_block(src(DB, DB_RES, 'D')), parse_block(src(t2, DB_RES, 'D')))
        names = [cs[0] for _, cs in _trs(html)[1:]]
        self.assertIn('▶ e', names)                       # a UDT member, its members not in the block
        self.assertIn('▶ arr', names)
        self.assertIn('"typeStopSw"', html)
        self.assertNotIn('_.typeStopSw', html)

    def test_sections_are_tree_rows_and_defaults_gray(self):
        t2 = ORD.replace('        z : Bool;\n', '        z : Bool;\n        w : Int;\n')
        trs = _trs(iface.html(parse_block(src(ORD, ORD_RES, 'O')), parse_block(src(t2, ORD_RES, 'O'))))
        self.assertEqual(trs[0][1][:4], ['Name', 'Data type', 'Default value', 'Retain'])
        self.assertEqual(trs[1][1][0], '▼ Static')
        w = next(cs for c, cs in trs if cs[0] == 'w')
        self.assertEqual(w[1:4], ['Int', '0', 'Non-retain'])
        self.assertIn('<span class="dflt">0</span>', iface.html(parse_block(src(ORD, ORD_RES, 'O')),
                                                                 parse_block(src(t2, ORD_RES, 'O'))))

    def test_attribute_columns(self):
        t1 = ORD.replace('        { S7_MLC := "MLC_2" }\n        speed : Int;',
                         '        { S7_MLC := "MLC_2"; S7_Access := "ReadOnly := External" }\n        speed : Int;')
        t2 = ORD.replace('        { S7_MLC := "MLC_2" }\n        speed : Int;',
                         '        { S7_MLC := "MLC_2"; S7_Visibility := "Hidden := External" }\n        speed : Int;')
        html = iface.html(parse_block(src(t1, ORD_RES, 'O')), parse_block(src(t2, ORD_RES, 'O')))
        head = _trs(html)[0][1]
        self.assertEqual(head[4:8], ['Accessible from HMI/OPC UA', 'Writable from HMI/OPC UA',
                                     'Visible in HMI engineering', 'Setpoint'])
        row = re.search(r'<tr class="chg">(.*?)</tr>', html, re.S).group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        self.assertEqual(cells[4], '<span class="tx del"><span class="cb on"></span></span><span class="tx ins"><span class="cb"></span></span>')
        self.assertEqual(cells[5], '<span class="tx del"><span class="cb"></span></span><span class="tx ins"><span class="cb dis"></span></span>')
        self.assertNotIn('attributes:', html)

    def test_udt_table_has_no_section_row_and_no_retain(self):
        t2 = ESTOP.replace('        q : Bool;\n', '        q : Bool;\n        r : Bool;\n')
        trs = _trs(iface.html(parse_block(src(ESTOP, '', 'typeStopSw')), parse_block(src(t2, '', 'typeStopSw'))))
        self.assertEqual(trs[0][1][:3], ['Name', 'Data type', 'Default value'])
        self.assertNotIn('Retain', trs[0][1])
        self.assertEqual([cs[0] for c, cs in trs[1:] if not c.endswith('ctx')],
                         ['⋯ 1 unchanged member (click to show all)', 'r'])

    def test_safety_db_q_comment_under_its_instance(self):
        from TiaChangeReports.compare import compare_snapshots
        d = compare_snapshots(FolderSnapshot(V1), FolderSnapshot(V2), blocks=['HatchDb'])[0]
        trs = _trs(iface.html(d.before, d.after))
        names = [cs[0] for _, cs in trs]
        k = names.index('▼ K02+FS01-SF09')
        self.assertEqual((names[k + 1], trs[k + 1][1][1]), ('q', 'Bool'))
        self.assertEqual(trs[k + 1][0], 'chg')                                  # in the UDT on both sides
        self.assertEqual(trs[k][1][1], '"typeHatch"')


# ---------------------------------------------------------------- Setpoint default per type

SETP = '''FUNCTION_BLOCK "P"
    VAR
        n : Int;
        e : _.typeStopSw;
        t : TON_TIME;
        { S7_Setpoint := "True" }
        on : Int;
        { S7_Setpoint := "False" }
        off : _.typeStopSw;
    END_VAR
END_FUNCTION_BLOCK
'''


# ---------------------------------------------------------------- inner member comment not 'added'

ESTOP2 = ESTOP.replace('        q : Bool;\n', '        q : Bool;\n        r : Bool;\n')


class TextMarksPrint(unittest.TestCase):
    """The marks of a changed text print, the browser's "Background graphics" or not."""

    def test_marks_print(self):
        from TiaChangeReports.page import CSS
        css = re.search(r'@media print\{([^{}]*)\{print-color-adjust:exact', CSS)
        self.assertTrue(css and all(x in css.group(1) for x in ('.tx', '.ti.del', '.cf.ins', 'table.scl td',
                                                                 'table.hd td')))


class InnerMemberChanged(unittest.TestCase):
    """A member of a UDT / FB instance or array in the type on both sides is 'changed' when only one side names
    it with a start value line (its comment or start value set or cleared); a member added to the UDT or an
    instance added stays 'added'."""

    def _rows(self, bt, at, btypes=None, atypes=None, bres=DB_RES, ares=DB_RES):
        b, a = parse_block(src(bt, bres, 'D')), parse_block(src(at, ares, 'D'))
        return {'.'.join(r.path): r for r in iface.rows(b.interface, a.interface, (btypes, atypes))}

    def test_comment_set(self):
        rs = self._rows(DB, DB_START, _types(typeStopSw=ESTOP), _types(typeStopSw=ESTOP))
        q = rs['e.q']
        self.assertEqual((q.state, q.changes), ('changed', {'comment'}))
        self.assertEqual((q.b.type, q.b.comment, q.b.inherited, q.a.comment), ('Bool', None, 'estop ok', '1 = released'))
        self.assertEqual((rs['arr.arr[2]'].state, rs['arr.arr[2]'].changes), ('changed', {'value'}))

    def test_comment_cleared(self):
        rs = self._rows(DB_START, DB, _types(typeStopSw=ESTOP), _types(typeStopSw=ESTOP))
        q = rs['e.q']
        self.assertEqual((q.state, q.changes, q.b.comment, q.a.comment), ('changed', {'comment'}, '1 = released', None))
        self.assertEqual(rs['arr.arr[2]'].state, 'changed')

    def test_comment_changed(self):
        rs = self._rows(DB_START, DB_START, ares=DB_RES.replace('1 = released', '1 = released and acknowledged'))
        self.assertEqual((rs['e.q'].state, rs['e.q'].changes), ('changed', {'comment'}))

    def test_only_the_comment_cell_is_marked(self):
        b, a = parse_block(src(DB, DB_RES, 'D')), parse_block(src(DB_START, DB_RES, 'D'))
        for blk in (b, a):
            blk.callees = _types(typeStopSw=ESTOP)
        row = next(x for x in re.findall(r'<tr[^>]*>.*?</tr>', iface.html(b, a), re.S) if '>q</td>' in x)
        self.assertIn('class="chg"', row)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        self.assertEqual([k for k, c in enumerate(cells) if 'class="tx' in c], [len(cells) - 1])
        self.assertIn('<span class="tx ins">1 = released</span>', cells[-1])

    def test_changed_comment_marks_its_changed_words(self):
        """A changed text as a changed network title, before light red, after light green, the changed
        words stronger; a gray inherited text (above) or boxes are tinted whole."""
        b = parse_block(src(DB_START, DB_RES, 'D'))
        a = parse_block(src(DB_START, DB_RES.replace('1 = released', '2 = released and acknowledged'), 'D'))
        for blk in (b, a):
            blk.callees = _types(typeStopSw=ESTOP)
        row = next(x for x in re.findall(r'<tr[^>]*>.*?</tr>', iface.html(b, a), re.S) if '>q</td>' in x)
        self.assertIn('<td><span class="tx del"><span>1</span> = released</span> <span class="tx ins"><span>2</span> = '
                      'released <span>and</span> <span>acknowledged</span></span></td>', row)


    def test_without_the_udt_in_the_input_the_same_type_has_it(self):
        rs = self._rows(DB, DB_START)
        self.assertEqual(rs['e.q'].state, 'changed')
        other = DB.replace('e : _.typeStopSw;', 'e : _.typeOther;')        # another type: cannot tell
        self.assertEqual(self._rows(other, DB_START)['e.q'].state, 'added')

    def test_member_added_to_the_udt_stays_added(self):
        old = ESTOP.replace('        q : Bool;\n', '        r : Bool;\n')
        rs = self._rows(DB, DB_START, _types(typeStopSw=old), _types(typeStopSw=ESTOP))
        self.assertEqual(rs['e.q'].state, 'added')
        rs = self._rows(DB_START, DB, _types(typeStopSw=ESTOP), _types(typeStopSw=old))
        self.assertEqual(rs['e.q'].state, 'removed')

    def test_instance_added_stays_added(self):
        bare = DB.replace('        { S7_MLC := "MLC_2" }\n        e : _.typeStopSw;\n', '')
        rs = self._rows(bare, DB_START, _types(typeStopSw=ESTOP), _types(typeStopSw=ESTOP))
        self.assertEqual((rs['e'].state, rs['e.q'].state), ('added', 'added'))

    def test_member_goes_in_its_place_not_moved(self):
        only_r = DB.replace('    END_VAR\n', '    END_VAR\n\n        "e".r := TRUE;\n')
        both = DB.replace('    END_VAR\n', '    END_VAR\n\n        { S7_MLC := "MLC_Q" }\n        "e".q := ();\n'
                                             '        "e".r := TRUE;\n')
        b, a = parse_block(src(only_r, DB_RES, 'D')), parse_block(src(both, DB_RES, 'D'))
        rs = iface.rows(b.interface, a.interface, (_types(typeStopSw=ESTOP2),) * 2)
        self.assertEqual([('.'.join(r.path), r.state) for r in rs if r.path[0] == 'e'],
                         [('e', 'same'), ('e.q', 'changed'), ('e.r', 'same')])


def _xml_member(setpoint=None, typ='"typeStopSw"'):
    import xml.etree.ElementTree as ET
    attr = ('<AttributeList><BooleanAttribute Name="SetPoint" SystemDefined="true">%s</BooleanAttribute>'
            '</AttributeList>' % setpoint) if setpoint else ''
    return ET.fromstring('<Member Name="m" Datatype=\'%s\'>%s</Member>' % (typ, attr))


class SetpointDefault(unittest.TestCase):
    """On shots of 2026-11-04 and both formats' exports of one project: the SD export writes
    Setpoint only where it differs from what TIA shows without one, and the SimaticML reader writes the same. Ticked
    on a UDT or FB instance, empty on anything else; a struct has none. Replaces an earlier rule, no setting is empty
    for every type, drawn from shots of a project no longer here (A_1), not checked again."""
    ON = '<span class="cb on"></span>'

    def ticked(self, text, *names, safety=False):
        ch = parse_block(src(text, '', 'P')).interface.root.children
        return [iface._boxes(ch[n], safety)[3] == self.ON for n in names]

    def test_shot_of_an_fb_instances_ticked_elementary_empty(self):
        """zzBenTimers."""
        text = ('FUNCTION_BLOCK "P"\n    VAR\n        instCtu : CTU_INT;\n        instTonA : TON_TIME;\n'
                '        statEdge : Bool;\n        statElapsed : Time;\n        statStep : Int;\n'
                '    END_VAR\nEND_FUNCTION_BLOCK\n')
        self.assertEqual(self.ticked(text, 'instCtu', 'instTonA', 'statEdge', 'statElapsed', 'statStep'),
                         [True, True, False, False, False])

    def test_shot_of_an_fb_instances_set_false(self):
        """zzLadTimer."""
        text = ('FUNCTION_BLOCK "P"\n    VAR\n        { S7_Setpoint := "False" }\n        instTON : TON_TIME;\n'
                '    END_VAR\nEND_FUNCTION_BLOCK\n')
        self.assertEqual(self.ticked(text, 'instTON'), [False])

    def test_shot_of_a_udt(self):
        """zzLibB."""
        text = 'TYPE "P"\n    STRUCT\n        a : _.zzLibA;\n        flag : Bool;\n    END_STRUCT;\nEND_TYPE\n'
        self.assertEqual(self.ticked(text, 'a', 'flag'), [True, False])

    def test_shot_of_a_global_db(self):
        """zzE2eDb."""
        text = 'DATA_BLOCK "P"\n    VAR\n        speed : Int;\n        dev1 : _.zzE2eUdtA;\n    END_VAR\nEND_DATA_BLOCK\n'
        self.assertEqual(self.ticked(text, 'speed', 'dev1'), [False, True])

    def test_exports_what_stays_empty_and_a_quoted_instance(self):
        """SimaticML writes false on an array of elementary and a DTL, true on an FB of the project."""
        text = ('FUNCTION_BLOCK "P"\n    VAR\n        inst : _.Other;\n        arr : Array[0..9] of Int;\n'
                '        arrU : Array[0..1] of _.Other;\n        d : DTL;\n        s : STRUCT\n            x : Bool;\n'
                '        END_STRUCT;\n    END_VAR\nEND_FUNCTION_BLOCK\n')
        self.assertEqual(self.ticked(text, 'inst', 'arr', 'arrU', 'd', 's'), [True, False, False, False, False])

    def test_a_setting_wins(self):
        self.assertEqual(self.ticked(SETP, 'n', 'e', 't', 'on', 'off'), [False, True, True, True, False])

    def plain_number(self, typ):
        """A type TIA keeps as a number in a global DB: box empty, enabled, its start value 0 gray text in a white cell;
        in SimaticML false is no setting."""
        from TiaChangeReports.simaticml import _attrs
        text = 'DATA_BLOCK "P"\n    VAR\n        x : %s;\n    END_VAR\nEND_DATA_BLOCK\n' % typ
        m = parse_block(src(text, '', 'P')).interface.root.children['x']
        self.assertEqual(iface._boxes(m)[3], '<span class="cb"></span>')
        self.assertNotIn('value', iface._off(m))
        self.assertEqual(iface._value_html(m), '<span class="dflt">0</span>')
        self.assertEqual(_attrs(_xml_member('false', typ), typ, 'STAT'), {})

    def test_shot_of_a_global_db_db_www(self):
        """zzInvCom db_www_1."""
        self.plain_number('DB_WWW')

    def test_shot_of_a_global_db_port(self):
        """zzInvCom port_1."""
        self.plain_number('PORT')

    def test_db_dyn_by_name_only(self):
        """Of DB_WWW's kind by its name; on no shot."""
        self.plain_number('DB_DYN')

    def test_pip_by_name_only(self):
        """Of PORT's kind by its name; on no shot."""
        self.plain_number('PIP')

    def test_rtm_by_name_only(self):
        """Of PORT's kind by its name; on no shot."""
        self.plain_number('RTM')

    def test_shot_of_a_global_db_system_types_ticked(self):
        """zzInvCom tcon_param_1, opc_ua_sessionconnectinfo_1."""
        text = ('DATA_BLOCK "P"\n    VAR\n        t : TCON_Param;\n        o : OPC_UA_SessionConnectInfo;\n'
                '    END_VAR\nEND_DATA_BLOCK\n')
        self.assertEqual(self.ticked(text, 't', 'o'), [True, True])

    def test_an_input_or_output_stays_empty(self):
        """The exports write nothing there, SimaticML no SetPoint."""
        text = ('FUNCTION_BLOCK "P"\n    VAR_INPUT\n        i : _.Other;\n    END_VAR\n    VAR_OUTPUT\n'
                '        o : _.Other;\n    END_VAR\nEND_FUNCTION_BLOCK\n')
        self.assertEqual(self.ticked(text, 'i', 'o'), [False, False])

    def test_f_block_no_setting_is_empty(self):
        """An F-DB or F-FB carries no setting, its XML says false on the instances."""
        self.assertEqual(self.ticked(SETP, 'n', 'e', 't', 'on', 'off', safety=True), [False, False, False, True, False])

    def test_f_block_on_the_page(self):
        for kind in ('FUNCTION_BLOCK', 'DATA_BLOCK'):
            text = '{ S7_Safety := "True" }\n' + SETP.replace('FUNCTION_BLOCK', kind)
            other = text.replace(': _.typeStopSw;', ': _.typeStopSw2;', 1)
            page = iface.html(parse_block(src(text, '', 'P')), parse_block(src(other, '', 'P')))
            row = re.search(r'<tr[^>]*><td class="nm"[^>]*><span class="tw">[^<]*</span>e<.*?</tr>', page).group(0)
            self.assertEqual(row.count('cb on'), 3, row)                   # accessible, writable, visible; setpoint empty

    def test_simaticml_writes_what_the_sd_export_writes(self):
        from TiaChangeReports.simaticml import _attrs, _type
        for sp, typ, out in [(None, '"typeStopSw"', {}), ('true', '"typeStopSw"', {}),
                             ('false', '"typeStopSw"', {'S7_Setpoint': 'False'}),
                             ('true', 'TON_TIME', {}), ('false', 'TON_TIME', {'S7_Setpoint': 'False'}),
                             (None, 'Int', {}), ('false', 'Int', {}), ('true', 'Int', {'S7_Setpoint': 'True'}),
                             ('false', 'DTL', {}), ('false', 'Array[0..9] of Int', {}),
                             ('false', 'Array[0..1] of "typeStopSw"', {}),
                             ('true', 'Array[0..1] of "typeStopSw"', {'S7_Setpoint': 'True'})]:
            self.assertEqual(_attrs(_xml_member(sp, typ), _type(typ), 'STAT'), out, (sp, typ))

    def test_simaticml_f_block(self):
        from TiaChangeReports.simaticml import _attrs, _type
        for sp, typ, out in [(None, '"typeStopSw"', {}), ('false', '"typeStopSw"', {}), ('false', 'TON', {}),
                             ('true', '"typeStopSw"', {'S7_Setpoint': 'True'}),
                             ('false', 'Int', {}), ('true', 'Int', {'S7_Setpoint': 'True'})]:
            self.assertEqual(_attrs(_xml_member(sp, typ), _type(typ), 'STAT', True), out, (sp, typ))

    def test_both_formats_draw_one_box(self):
        from TiaChangeReports.simaticml import _attrs
        ch = parse_block(src(SETP, '', 'P')).interface.root.children
        for n, sp, typ in [('e', 'true', '_.typeStopSw'), ('t', 'true', 'TON_TIME'), ('off', 'false', '_.typeStopSw'),
                           ('n', 'false', 'Int'), ('on', 'true', 'Int')]:
            self.assertEqual(ch[n].attrs, _attrs(_xml_member(sp, typ), typ, 'STAT'), n)

    def test_a_change_of_the_box_shows_on_an_instance(self):
        """No setting against "False" is a ticked box against an empty one."""
        on, off = (parse_block(src('FUNCTION_BLOCK "P"\n    VAR\n%s        t : TON_TIME;\n    END_VAR\n'
                                   'END_FUNCTION_BLOCK\n' % pragma, '', 'P'))
                   for pragma in ('', '        { S7_Setpoint := "False" }\n'))
        self.assertTrue(iface.changed(off, on))
        page = iface.html(off, on)
        self.assertIn('<span class="tx del"><span class="cb"></span></span>', page)
        self.assertIn('<span class="tx ins"><span class="cb on"></span></span>', page)


class SetpointOfAReleasedType(unittest.TestCase):
    """A released library type's document writes no Setpoint, where its version in work and the project block write
    one: there no setting says nothing of the box. A release draws no box changed, and as the two exports
    cannot tell whether one did, the block says its file differs in what the report does not show."""
    TYPE_ = 'TYPE "T"\n    STRUCT\n        %ssig : _.A;\n    END_STRUCT;\nEND_TYPE\n'
    SET = '{ S7_Setpoint := "False" }\n        '
    ACCESS = '{ S7_Access := "ReadOnly := External" }\n        '
    BOOL = 'TYPE "T"\n    STRUCT\n        %sflag : Bool;\n    END_STRUCT;\nEND_TYPE\n'
    TWO = 'TYPE "T"\n    STRUCT\n        %ssig : _.A;\n        %sother : Bool;\n    END_STRUCT;\nEND_TYPE\n'

    def compare(self, before, after, vb=None, va=None, pb='T.s7dcl', pa='T.s7dcl', type_=None):
        def one(text, ver):
            s = src((type_ or self.TYPE_) % text, '', 'T')
            s.version = ver
            return s
        return compare_blocks(one(before, vb), one(after, va), pb, pa)

    def says_it_differs(self, d):
        self.assertEqual((d.itf_changed, d.not_shown, d.state), (False, True, 'changed'))

    def test_a_release_draws_no_box_changed_and_says_the_file_differs(self):
        self.says_it_differs(self.compare(self.SET, '', LibVersion('1.0.0', in_work=True), LibVersion('1.0.0')))

    def test_a_true_on_an_instance_against_a_release_is_not_dropped(self):
        d = self.compare('', '{ S7_Setpoint := "True" }\n        ', LibVersion('1.0.0'), LibVersion('1.0.1', in_work=True))
        self.says_it_differs(d)

    def test_a_setting_on_a_bool_against_a_release_is_not_dropped(self):
        d = self.compare('', '{ S7_Setpoint := "True" }\n        ', LibVersion('1.0.0'), LibVersion('1.0.1', in_work=True),
                         type_=self.BOOL)
        self.says_it_differs(d)

    def test_a_release_with_nothing_set_on_either_side_is_only_its_version(self):
        d = self.compare('', '', LibVersion('1.0.0', in_work=True), LibVersion('1.0.0'))
        self.assertEqual((d.itf_changed, d.not_shown, d.state), (False, False, 'version'))

    def test_a_release_with_another_setting_beside_it(self):
        both = '{\n            S7_Access := "ReadOnly := External";\n            S7_Setpoint := "False"\n        }\n        '
        self.says_it_differs(self.compare(both, '{ S7_Access := "ReadOnly := External" }\n        ',
                                          LibVersion('1.0.0', in_work=True), LibVersion('1.0.0')))

    def test_another_attribute_of_the_same_member_changed_too_keeps_the_note(self):
        d = self.compare(self.SET, self.ACCESS, LibVersion('1.0.0', in_work=True), LibVersion('1.0.0'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_another_member_changed_too_keeps_the_note(self):
        d = self.compare((self.SET, ''), ('', self.ACCESS), LibVersion('1.0.0', in_work=True), LibVersion('1.0.0'),
                         type_=self.TWO)
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_put_in_work_again_draws_no_box_changed(self):
        self.says_it_differs(self.compare('', self.SET, LibVersion('1.0.0'), LibVersion('1.0.1', in_work=True)))

    def test_a_folder_name_says_nothing(self):
        """The version its export writes tells a release, not a name only the bridge gives a folder."""
        self.assertTrue(self.compare(self.SET, '', pa='library/types/F/T.released/T.s7dcl').itf_changed)

    def test_in_work_a_change_of_the_box_shows(self):
        d = self.compare(self.SET, '', LibVersion('1.0.0', in_work=True), LibVersion('1.0.0', in_work=True))
        self.assertTrue(d.itf_changed)

    def test_a_block_that_is_no_library_type_shows_it(self):
        self.assertTrue(self.compare(self.SET, '').itf_changed)

    def test_a_simaticml_export_of_a_released_type_writes_it(self):
        """So there it counts (test_setpoint_in_a_simaticml_export_counts)."""
        def xml(sp):
            return BlockSource('Main', '', None, 'Main', LibVersion('1.0.0'), xml=_fixture().replace(
                '<Member Name="big" Datatype="Bool" />',
                '<Member Name="big" Datatype="Bool"><AttributeList><BooleanAttribute Name="SetPoint">%s'
                '</BooleanAttribute></AttributeList></Member>' % sp))
        self.assertTrue(compare_blocks(xml('false'), xml('true'), 'Main.xml', 'Main.xml').itf_changed)


class ArrayElementSetpoint(unittest.TestCase):
    """An array element is ticked as its array, whatever its own type's rule."""

    def test_element_of_an_array_of_a_udt_empty_as_its_array(self):
        rs = DisabledCellsLikeTia._cells(self, DIS_ARR, 'A')
        self.assertEqual(rs['arr'][7][1], 'o')
        self.assertEqual(rs['arr[1]'][7][1], 'o~')

    def test_a_ticked_array_ticks_its_elements(self):
        text = DIS_ARR.replace('        arr : Array[0..2] of _.typeStopSw;\n',
                               '        { S7_Setpoint := "True" }\n        arr : Array[0..2] of _.typeStopSw;\n')
        self.assertEqual(DisabledCellsLikeTia._cells(self, text, 'A')['arr[1]'][7][1], 'x~')


# ---------------------------------------------------------------- inner rows with TIA's disabled boxes

ESTOP_ATTRS = ('TYPE\n    typeStopSw : STRUCT\n        {\n            S7_Access := "ReadOnly := External";\n'
               '            S7_MLC := "MLC_e"\n        }\n        q : Bool := TRUE;\n'
               '        { S7_Setpoint := "True" }\n        r : Bool;\n    END_STRUCT;\nEND_TYPE\n')
DB_XML = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
  <Section Name="Static">
    <Member Name="a" Datatype="Bool" Remanence="NonRetain">
      <Comment><MultiLanguageText Lang="en-US">flag a</MultiLanguageText></Comment>
    </Member>
    <Member Name="e" Datatype="&quot;typeStopSw&quot;" Remanence="NonRetain">
      <Comment><MultiLanguageText Lang="en-US">estop</MultiLanguageText></Comment>
      <Sections>
        <Section Name="None">
          <Member Name="q" Datatype="Bool">
            <Comment><MultiLanguageText Lang="en-US">1 = released</MultiLanguageText></Comment>
          </Member>
          <Member Name="r" Datatype="Bool" />
        </Section>
      </Sections>
    </Member>
    <Member Name="arr" Datatype="Array[0..3] of Int" Remanence="NonRetain">
      <Subelement Path="2"><StartValue>5</StartValue></Subelement>
    </Member>
    <Member Name="z" Datatype="Bool" Remanence="NonRetain" />
  </Section>
</Sections></Interface>
      <MemoryLayout>Optimized</MemoryLayout>
      <Name>StopDb</Name>
      <Number>1</Number>
      <ProgrammingLanguage>DB</ProgrammingLanguage>
    </AttributeList>
  </SW.Blocks.GlobalDB>
</Document>
'''


def _cbs(cell):
    """The boxes of a cell: 'x' ticked, 'o' empty, '~' disabled."""
    return ' '.join(('x' if on else 'o') + ('~' if dis else '')
                    for on, dis in re.findall(r'<span class="cb( on)?( dis)?"></span>', cell))


class InnerRowBoxes(unittest.TestCase):
    """A member inside a UDT instance or array that a DB start value names shows TIA's boxes disabled,
    ticked from the UDT's settings (an array element: the array's) as far as its parent allows; its start value and
    comment gray when they come from the type; the type's other members under it, folded."""

    def _rows(self, bt=DB, at=DB_START, types=ESTOP_ATTRS, safety=False):
        b, a = (parse_block(src(('{ S7_Safety := "True" }\n' if safety else '') + t, DB_RES, 'D')) for t in (bt, at))
        for blk in (b, a):
            blk.callees = _types(typeStopSw=types) if types else None
        out = {}
        for cls, body in re.findall(r'<tr(?: class="([^"]*)")?>(.*?)</tr>', iface.html(b, a), re.S):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', body, re.S)
            if len(cells) == 9:
                out[re.sub(r'<[^>]+>', '', cells[0]).strip().lstrip('▼▶')] = (cls, cells)
        return out

    def test_boxes_from_the_udt_disabled(self):
        rs = self._rows()
        q, r = rs['q'][1], rs['r'][1]
        self.assertEqual([_cbs(c) for c in q[3:8]], ['o~', 'x~', 'o~', 'x~', 'o~'])     # ReadOnly in the UDT
        self.assertEqual([_cbs(c) for c in r[3:8]], ['o~', 'x~', 'x~', 'x~', 'x~'])     # Setpoint in the UDT
        self.assertEqual([_cbs(c) for c in rs['e'][1][3:8]], ['o', 'x', 'x', 'x', 'x'])  # the instance: enabled
        self.assertEqual(q[2], '<span class="dflt">TRUE</span>')                        # the UDT's default, gray
        self.assertIn('class="inh">estop ok', q[8])

    def test_the_parent_limits_them(self):
        hidden = '        {\n            S7_Access := "ReadOnly := External";\n            S7_MLC := "MLC_2";\n' \
                 '            S7_Visibility := "Hidden := External"\n        }\n        e : _.typeStopSw;\n'
        bt, at = (t.replace('        { S7_MLC := "MLC_2" }\n        e : _.typeStopSw;\n', hidden) for t in (DB, DB_START))
        rs = self._rows(bt, at, safety=True)                                            # as project C's StopDb
        self.assertEqual([_cbs(c) for c in rs['q'][1][3:8]], ['o~'] * 5)
        self.assertEqual([_cbs(c) for c in rs['r'][1][3:8]], ['o~'] * 4 + ['x~'])       # Setpoint set in the UDT
        unlisted = hidden.replace('Hidden', 'Unlisted').replace('"ReadOnly := External";\n', '"";\n')
        bt, at = (t.replace('        { S7_MLC := "MLC_2" }\n        e : _.typeStopSw;\n', unlisted) for t in (DB, DB_START))
        self.assertEqual([_cbs(c) for c in self._rows(bt, at)['r'][1][3:8]], ['o~', 'x~', 'x~', 'o~', 'x~'])

    def test_retain_of_the_top_level_member(self):
        bt, at = (t.replace('    VAR\n', '    VAR RETAIN\n') for t in (DB, DB_START))
        rs = self._rows(bt, at)
        self.assertEqual((_cbs(rs['e'][1][3]), _cbs(rs['q'][1][3]), _cbs(rs['arr[2]'][1][3])), ('x', 'x~', 'x~'))

    def test_array_element_from_the_array(self):
        ro = '        {\n            S7_Access := "ReadOnly := External";\n            S7_Setpoint := "True"\n' \
             '        }\n        arr : Array[0..3] of Int;\n'
        bt, at = (t.replace('        arr : Array[0..3] of Int;\n', ro) for t in (DB, DB_START))
        rs = self._rows(bt, at)
        self.assertEqual([_cbs(c) for c in rs['arr[2]'][1][3:8]], ['o~', 'x~', 'o~', 'x~', 'x~'])
        self.assertEqual(_cbs(rs['arr'][1][7]), 'x')                    # an array: Setpoint enabled

    def test_other_members_of_the_type_folded_under_it(self):
        rs = self._rows()
        self.assertEqual(list(rs)[list(rs).index('e'):][:3], ['e', 'q', 'r'])
        self.assertEqual((rs['q'][0], rs['r'][0]), ('chg', 'ctx'))
        self.assertNotIn('r', self._rows(types=None))                                  # the type not in the input
        self.assertNotIn('arr[0]', self._rows())                                        # no array elements added

    def test_simaticml_db_same_as_the_sd_export(self):
        """The SimaticML export writes a comment or start value only on the members an instance sets: these are the
        start value lines of the SD export, so both formats give the same tree and boxes."""
        sd = parse_block(src(DB_START, DB_RES, 'D'))
        xml = parse_block(_xml_src(DB_XML, 'StopDb'))
        self.assertEqual(sorted(iface._start_keys(k) for k in xml.interface.start),
                         sorted(iface._start_keys(k) for k in sd.interface.start))
        types = (_types(typeStopSw=ESTOP_ATTRS),) * 2
        rows = iface.rows(sd.interface, xml.interface, types)
        self.assertEqual([('.'.join(r.path), r.state) for r in rows if r.state != 'same'], [])
        for blk in (sd, xml):
            blk.callees = types[0]
        boxes = [[_cbs(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', iface.html(None, blk), re.S)] for blk in (sd, xml)]
        self.assertEqual(boxes[0], boxes[1])
        self.assertIn('x~', ' '.join(boxes[1]))


# ---------------------------------------------------------------- disabled cells and boxes as TIA draws them

DIS_FB = '''FUNCTION_BLOCK "G"
    VAR_INPUT
        { S7_Visibility := "Hidden := External" }
        hid : Bool;
        cfg : _.typeStopSw;
    END_VAR
    VAR_IN_OUT
        io : _.typeStopSw;
        ioArr : Array[0..3] of _.typeStopSw;
        ioInt : Int;
    END_VAR
    VAR
        s : STRUCT
            x : Bool;
        END_STRUCT;
        t : TON_TIME;
        b : Bool;
    END_VAR
    VAR_TEMP
        tmp : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
DIS_DB = '''DATA_BLOCK "S"
    VAR
        { S7_Visibility := "Hidden := External" }
        hid : Bool;
        e : _.typeStopSw;
    END_VAR
BEGIN
END_DATA_BLOCK
'''


class DisabledCellsLikeTia(unittest.TestCase):
    """TIA's disabled cells gray and its disabled boxes drawn disabled, not blank, as in an FB and an F-DB."""

    def _cells(self, text, name):
        """name -> [(gray?, boxes or text)] of a new block's interface table (every row shown)."""
        out = {}
        for body in re.findall(r'<tr[^>]*>(.*?)</tr>', iface.html(None, parse_block(src(text, '', name))), re.S):
            cells = re.findall(r'<td([^>]*)>(.*?)</td>', body, re.S)
            if len(cells) > 1:
                key = re.sub(r'<[^>]+>', '', cells[0][1]).strip().lstrip('▼▶')
                out[key] = [('dis' in re.sub(r'style="[^"]*"', '', a),
                             _cbs(c) if 'class="cb' in c else re.sub(r'<[^>]+>', '', c)) for a, c in cells]
        return out

    def test_fb_cells(self):
        rs = self._cells(DIS_FB, 'G')
        gray = {k: ''.join('g' if g else '.' for g, _ in v) for k, v in rs.items()}
        boxes = {k: [c for _, c in v[4:8]] for k, v in rs.items()}
        # name, type, value, retain, accessible, writable, visible, setpoint, comment
        self.assertEqual(gray['hid'], '.....ggg.')                                      # not accessible
        self.assertEqual(boxes['hid'], ['o', 'o~', 'o~', 'o~'])
        self.assertEqual((gray['cfg'], boxes['cfg']), ('..g......', ['x', 'x', 'x', 'o']))  # a UDT input: no value
        for io in ('io', 'ioArr'):                                    # structured in-out: empty, as in TIA
            self.assertEqual((gray[io], boxes[io], rs[io][3][1]), ('..gggggg.', ['o~'] * 4, ''))
        self.assertEqual((gray['ioInt'], boxes['ioInt']), ('.........', ['x', 'x', 'x', 'o']))
        self.assertEqual((gray['s'], boxes['s']), ('..g....g.', ['x', 'x', 'x', 'o~']))    # a struct: no setpoint
        self.assertEqual((gray['t'], boxes['t']), ('..g......', ['x', 'x', 'x', 'x']))     # an FB instance
        self.assertEqual((gray['b'], rs['b'][3][1]), ('.........', 'Non-retain'))
        self.assertEqual((gray['tmp'], boxes['tmp']), ('.........', ['', '', '', '']))     # temp: not seen, as before
        self.assertEqual([c for _, c in rs['Input'][1:]], ['', '', '', 'o~', 'o~', 'o~', 'o~', ''])  # section row

    def test_f_db_retain_and_setpoint_disabled(self):
        for safety in (True, False):
            text = ('{ S7_Safety := "True" }\n' if safety else '') + DIS_DB
            rs = self._cells(text, 'S')
            self.assertEqual([c for _, c in rs['hid'][3:8]], ['o~' if safety else 'o', 'o', 'o~', 'o~', 'o~'])
            self.assertEqual([g for g, _ in rs['hid'][3:8]], [safety, False, True, True, True])
            self.assertEqual([c for _, c in rs['e'][3:8]], ['o~' if safety else 'o', 'x', 'x', 'x', 'o' if safety else 'x'])
            self.assertTrue(rs['e'][2][0])                                              # a UDT: no start value
            self.assertEqual([c for _, c in rs['Static'][3:8]], ['o~'] * 5)

    def test_gray_cells_keep_the_diff_colour(self):
        from TiaChangeReports import page
        with open(page.__file__, encoding='utf-8') as f:
            css = f.read()
        self.assertIn('td.dis{background-color:var(--field)}', css)
        self.assertIn('tr.chg td.dis', css)


DIS_FFB = '''{ S7_Safety := "True" }
FUNCTION_BLOCK "F"
    VAR_INPUT
        i : Bool;
    END_VAR
    VAR
        inst : ESTOP1;
        b : Bool;
    END_VAR
END_FUNCTION_BLOCK
'''
DIS_ARR = '''DATA_BLOCK "A"
    VAR
        arr : Array[0..2] of _.typeStopSw;
        { S7_Setpoint := "True" }
        arrB : Array[0..1] of Bool;
        s : STRUCT
            x : Bool;
        END_STRUCT;
    END_VAR
BEGIN
    arr[1].q := TRUE;
END_DATA_BLOCK
'''


class DisabledCellsMoreKinds(unittest.TestCase):
    """The rule checked on screenshots of a global DB, an instance DB, a UDT, an FC and an F-FB (project A_1)."""
    _cells = DisabledCellsLikeTia._cells

    def test_f_fb_retain_disabled(self):
        """F-FB: Retain gray on every row ('Non-retain'), blank on an FB instance; the boxes as in an FB."""
        rs = self._cells(DIS_FFB, 'F')
        self.assertEqual([(rs[n][3][0], rs[n][3][1]) for n in ('i', 'inst', 'b')],
                         [(True, 'Non-retain'), (True, ''), (True, 'Non-retain')])
        self.assertEqual([c for _, c in rs['inst'][4:8]], ['x', 'x', 'x', 'o'])
        self.assertEqual(self._cells(DIS_FB, 'G')['b'][3], (False, 'Non-retain'))      # a standard FB as before

    def test_array_setpoint_enabled_struct_disabled(self):
        """Global DB: the Setpoint of an array (of a UDT, seen; of elementary types the export sets it) is an
        enabled box, of a struct a disabled one."""
        rs = self._cells(DIS_ARR, 'A')
        self.assertEqual([rs[n][7] for n in ('arr', 'arrB', 's')], [(False, 'o'), (False, 'x'), (True, 'o~')])

    def test_inner_structured_start_value_gray(self):
        """An array element or member of a UDT type inside a DB: its start value gray, an elementary one's not."""
        rs = self._cells(DIS_ARR, 'A')
        self.assertEqual((rs['arr[1]'][2][0], rs['q'][2][0]), (True, False))
        self.assertEqual([c for _, c in rs['arr[1]'][3:8]], ['o~', 'x~', 'x~', 'x~', 'o~'])

    def test_disabled_ticked_box_as_tia(self):
        """TIA's disabled ticked box: near-white, gray border, dark gray tick, as in a global DB."""
        from TiaChangeReports import page
        with open(page.__file__, encoding='utf-8') as f:
            css = f.read()
        self.assertIn('.cb.dis.on{background:#f7f9fb;border-color:#7e7e7e}', css)
        self.assertIn('.cb.dis.on::after{border-color:#666}', css)


# ---------------------------------------------------------------- TIA network titles, no paths, panning

LAD_SCL = SRC.replace('I_Contact( #b )', 'I_Contact( #a )').replace('#s.x := #a;', '#s.x := #b;')
INSERTED = LAD_SCL.replace('    {\n        S7_Language := "LAD";',
                           '    { S7_Language := "SCL" }\n    NETWORK\n        #s.x := #b;\n    END_NETWORK\n'
                           '    {\n        S7_Language := "LAD";', 1)


def _nets(html):
    """The title bars of a page's networks, tags as |."""
    return [re.sub(r'<[^>]+>', '|', re.search(r'<div class="nwt">(.*?)</div>', part).group(1))
            for part in html.split('<div class="nw">')[1:]]


class PageLook(unittest.TestCase):
    def test_network_title_like_tia(self):
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        self.assertIn('<span class="no">Network 1:</span><span class="ti">Seal-in</span>', html)
        self.assertIn('<div class="nwc"><span class="side"><span class="cf none">Comment</span></span>'
                      '<span class="side"><span class="cf none">Comment</span></span></div>', html)  # TIA's empty field
        self.assertNotIn('before NW', html)
        self.assertNotRegex(html, r'class="tag">(LAD|SCL)<')

    def test_comment_row_shows_the_comment_and_its_change(self):
        t2 = LAD_SCL.replace('        S7_NetworkTitle := "MLC_2"', '        S7_NetworkTitle := "MLC_2";\n'
                             '        S7_NetworkComment := "MLC_9"')
        html = render([compare_blocks(src(), src(t2, RES + '  - id: MLC_9\n    en-US: keeps x on\n'))], 'b', 'a')
        self.assertIn('<div class="nwc"><span class="side"><span class="cf none">Comment</span></span>'
                      '<span class="side"><span class="cf ins"><span>keeps</span> <span>x</span> <span>on</span>'
                      '</span></span></div>', html)

    def test_one_column_header_names_both_sources(self):
        """No label per pane or SCL table; one sticky header at the top, Before and After with their
        source, in the page and in the fragment."""
        d = compare_blocks(src(), src(LAD_SCL))
        head = ('<div class="cols"><div class="side"><b>Before</b>Plant @ HEAD~1 (e734b6f)</div>'
                '<div class="side"><b>After</b>Plant @ HEAD (bb7c4a3)</div></div>')
        for fragment in (False, True):
            html = render([d], 'Plant @ HEAD~1 (e734b6f)', 'Plant @ HEAD (bb7c4a3)', fragment=fragment)
            body = _flow(html)
            self.assertEqual(body.count('<div class="cols">'), 1)
            self.assertTrue(body.startswith(head), body[:200])            # the very top of the report
            self.assertEqual(body.count('Before'), 1)
            self.assertNotIn('class="ph"', html)
            self.assertNotIn('<th', body)
            self.assertNotIn('class="src"', html)
        self.assertIn('.ldiff .cols{position:sticky;top:0;', html)
        self.assertEqual(columns_html('<x>', 'y'), '<div class="cols"><div class="side"><b>Before</b>&lt;x&gt;</div>'
                                                   '<div class="side"><b>After</b>y</div></div>')

    def test_legend_is_the_four_swatches(self):
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        self.assertEqual(re.sub(r'<[^>]+>', '|', re.search(r'<div class="bar">(.*?)</div>', html).group(1)),
                         '|||added||||removed||||changed||||moved|')
        for gone in ('Click a ladder', 'drag to move', 'same element connected differently', 'Minimap<'):
            self.assertNotIn(gone, html)

    def test_each_side_of_the_title_bar_has_its_own_number(self):
        html = render([compare_blocks(src(), src(INSERTED))], 'b', 'a')
        self.assertEqual(_nets(html), [
            '||||Network 1:||||new||',                                     # new: only the after side
            '||Network 1:||Seal-in||||Network 2:||Seal-in||changed||',
            '||Network 2:||||||Network 3:||||changed||'])

    def test_zoomed_ladder_pans_by_drag_and_has_a_minimap(self):
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        self.assertIn('.ldiff .nw.zoom .pb{', html)
        self.assertIn('cursor:grab', html)
        for hook in ("'mousedown'", "'mousemove'", "'mouseup'", "'mm'"):
            self.assertIn(hook, html)

    def test_minimap_cannot_be_turned_off(self):
        """No Minimap button, no x on the minimap, nothing in the browser's storage (only the project
        tree's open / closed keeps a value there)."""
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        for gone in ('mmt', 'mmx', 'nomm'):
            self.assertNotIn(gone, html)
        from TiaChangeReports import page
        self.assertNotIn("createElement('button')", page.JS)                    # the focus button is the page's
        self.assertNotIn('localStorage', page.JS)
        self.assertNotIn('localStorage', render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a', fragment=True))

    def test_no_minimap_on_a_frame_lower_than_120_px(self):
        """On a low frame the minimap covered the spot just clicked and the next drag there jumped the
        view; no minimap there. A fixed height, not 3x the minimap: that ratio follows the pane's width (about
        2.75 for every wide ladder at 1400 px) and took the minimap off nearly every network."""
        from TiaChangeReports import page
        self.assertIn("if(!zm||p.clientHeight<120||", page.JS)

    def test_a_wide_interface_table_scrolls_in_its_frame(self):
        """At a 1000 px window with the tree open (report about 700 px) the interface table ran out of the
        report and the page scrolled sideways. Box columns as narrow as their headings' words; a table still wider
        scrolls sideways inside the Interface frame, its header staying; printed as before (nothing clipped)."""
        html = render([compare_blocks(src(ORD, ORD_RES, 'O'),
                                      src(ORD.replace('        z : Bool;\n', '        z : Bool;\n        w : Int;\n'),
                                          ORD_RES, 'O'))], 'b', 'a')
        self.assertIn('<div class="nw itfw"><div class="nwh"><b>Interface</b>', html)
        self.assertIn('.ldiff .itfw{overflow-x:auto}', html)
        self.assertIn('@media print{.ldiff .itfw{overflow:visible}}', html)
        self.assertIn('.ldiff table.itf td.c{text-align:center;width:56px;padding:2px 4px}', html)

    def test_the_picture_zooms_inside_its_frame_like_an_image_viewer(self):
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        self.assertIn('.ldiff .pb{overflow:hidden;', html)               # plain wheel scrolls the page
        self.assertIn("q.style.height=q.parentNode.getBoundingClientRect().bottom-q.getBoundingClientRect().top+'px'",
                      html)                                              # frame locked when the zoom starts
        self.assertIn("q.style.marginRight=z?Math.max(0,(wide-w)*z+o._bx)+'px'", html)   # one scroll range for both
        self.assertIn("q.style.marginBottom=z?Math.max(0,(tall-h)*z+o._by)+'px'", html)  # margins per frame (53)
        self.assertFalse('window.scroll' in html.split("querySelector('button.top')")[0])   # the page never moves
        self.assertNotIn('max-height:80vh', html)
        self.assertIn("p.scrollLeft=p.scrollLeft+b.left+fx*b.width-e.clientX", html)   # point under the mouse
        self.assertIn('set(z?0:2*fit(),p,e)', html)                      # click: 2x, zoomed: back to fit
        self.assertIn("if(!e.ctrlKey)return;e.preventDefault();", html)  # every ladder, never the page zoom
        self.assertIn('v=Math.max(f,Math.min(4*f,v))', html)
        self.assertIn('{passive:false}', html)
        self.assertNotIn('fits', html)


class NoPaths(unittest.TestCase):
    """Labels name the project, the revision and repo-relative paths, never a directory of the machine."""
    setUp = GitInput.setUp
    tearDown = GitInput.tearDown

    def test_snapshot_labels(self):
        from TiaChangeReports.source import FileSnapshot, GitSnapshot
        name = os.path.basename(self.repo)
        head = _out(self.repo, 'rev-parse', '--short', 'HEAD~1')
        self.assertEqual(FolderSnapshot(self.repo).label, name)
        self.assertEqual(FolderSnapshot(os.path.join(self.repo, 'plc')).label, name + '/plc')
        self.assertEqual(FileSnapshot(os.path.join(self.repo, 'plc', 'A.s7dcl')).label, name + '/plc/A.s7dcl')
        self.assertEqual(GitSnapshot(self.repo, 'HEAD~1').label, '%s @ HEAD~1 (%s)' % (name, head))
        self.assertEqual(GitSnapshot(os.path.join(self.repo, 'plc'), head).label, '%s/plc @ %s' % (name, head))
        self.assertEqual(GitSnapshot(self.repo).label, name + ' (working tree)')
        with tempfile.TemporaryDirectory() as d:
            _put(d, {'x/B.s7dcl': SRC})
            self.assertEqual(FolderSnapshot(os.path.join(d, 'x')).label, 'x')
            self.assertEqual(FileSnapshot(os.path.join(d, 'x', 'B.s7dcl')).label, 'B.s7dcl')

    def test_pages_hold_no_directory(self):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        out, frag, out2 = (os.path.join(self.repo, p) for p in ('out.html', 'frag.html', 'out2.html'))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', out]), 0)
            self.assertEqual(main(['--git', self.repo, 'HEAD~1', 'HEAD', '-o', frag, '--fragment']), 0)
            self.assertEqual(main([os.path.join(self.repo, 'plc'), os.path.join(self.repo, 'plc2'), '-o', out2,
                                   '--all']), 0)
        parent = os.path.dirname(os.path.abspath(self.repo))
        for path in (out, frag, out2):
            with open(path, encoding='utf-8') as f:
                text = f.read()
            for form in (parent, parent.replace('\\', '/'), parent.replace('\\', '\\\\')):
                self.assertNotIn(form, text, path)


def _out(repo, *args):
    import subprocess
    return subprocess.run(['git', '-C', repo] + list(args), check=True, capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- LAD marks like the SCL diff

MARK = '''FUNCTION_BLOCK "K"
    VAR
        inst : _.Drive;
        a : Bool;
        b : Bool;
        c : Int;
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            #inst(
                start := wire#w1,
                speed := 5,
                cmd := #c,
                state => #c
            )
            Coil( #q )
        END_RUNG
        RUNG wire#powerrail
            Contact( #b )
        END_RUNG wire#w1
    END_NETWORK
END_FUNCTION_BLOCK
'''


def _marked(before, after):
    """(diff, before layout, after layout) of the one network of two versions of MARK."""
    bd = compare_blocks(src(before, '', 'K'), src(after, '', 'K'))
    (p,) = bd.nets
    return (p.lad, Layout(p.before.rungs, bd.before.interface), Layout(p.after.rungs, bd.after.interface))


def _box(g):
    return next(e for e in g.elements.values() if e.kind == 'box')


def _svg_items(svg):
    """Drawn items in paint order: ('line', x1, y1, x2, y2) and ('hl', x, y, w, h, the rect's markup)."""
    out = []
    for m in re.finditer(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"|<rect class="hl[^>]*>', svg):
        if m.group(1):
            out.append(('line',) + tuple(float(v) for v in m.groups()))
        else:
            r = m.group(0)
            v = [float(re.search(r'\b%s="([-\d.]+)"' % k, r).group(1)) for k in ('x', 'y', 'width', 'height')]
            out.append(('hl', v[0], v[1], v[2], v[3], r))
    return out


class LadMarks(unittest.TestCase):
    def test_changed_box_marks_only_the_changed_pin(self):
        d, lb, la = _marked(MARK, MARK.replace('speed := 5', 'speed := 6'))
        for g, lay in ((d.b, lb), (d.a, la)):
            box = _box(g)
            self.assertEqual(d.status[box.eid], 'changed')
            self.assertEqual(changed_params(box, d.other[box.eid]), {'speed'})
            v = lay.views[box.eid]
            k = next(k for k, i in enumerate(lay.info) if any(p[0] is box for p in i['placed']))
            rung = lay.ys[k]
            row = rung + v.rowy[[n for n, _ in v.lefts].index('speed')]
            marks = [m for m in lay.marks(d.status, d.other) if m[0] == box.eid]
            self.assertTrue(marks)
            for _, st, _, x, y, w, h in marks:
                self.assertEqual(st, 'changed')
                self.assertTrue(y < row < y + h, (y, row, h))
                self.assertFalse(y < rung < y + h)                      # not the box head, not the EN row
                self.assertLess(h, 3 * 13 + 10)

    def test_changed_contact_marks_its_operand(self):
        d, lb, la = _marked(MARK, MARK.replace('Contact( #b )', 'Contact( #q )'))
        (eid,) = [e for e in d.b.elements if d.status[e] == 'changed']
        k = next(k for k, i in enumerate(lb.info) if any(not isinstance(p[0], str) and p[0].eid == eid
                                                          for p in i['placed']))
        (m,) = [m for m in lb.marks(d.status, d.other) if m[0] == eid]
        self.assertLess(m[4] + m[6], lb.ys[k] - 8)                       # above the contact's bars

    def test_marks_are_square_unoutlined_and_cut_no_wire(self):
        """A contact added on the rung wired to a box input, a box pin changed."""
        after = MARK.replace('Contact( #b )', 'Contact( #b )\n            Contact( #a )').replace('cmd := #c', 'cmd := 7')
        d, lb, la = _marked(MARK, after)
        self.assertEqual(statuses(d, d.a), Counter(same=3, added=1, changed=1))
        items = _svg_items(la.svg(d.status, d.other))
        hls = [it for it in items if it[0] == 'hl']
        self.assertEqual(len(hls), 2)                                    # the contact; the variable at cmd
        for k, it in enumerate(items):
            if it[0] != 'hl':
                continue
            self.assertNotIn('rx', it[5])
            self.assertNotIn('stroke', it[5])
            _, x, y, w, h, _ = it
            for ln in items[:k]:                                         # lines drawn before: not covered
                if ln[0] != 'line':
                    continue
                x1, x2, y1, y2 = min(ln[1], ln[3]), max(ln[1], ln[3]), min(ln[2], ln[4]), max(ln[2], ln[4])
                self.assertFalse(x1 < x + w and x < x2 + .5 and y1 < y + h and y < y2 + .5, (it, ln))

    def test_no_hover_partner(self):
        d = compare_blocks(src(MARK, '', 'K'), src(MARK.replace('speed := 5', 'speed := 6'), '', 'K'))
        html = render([d], 'b', 'a')
        for s in ('data-p=', '.peer', 'onmouseenter', 'partner'):
            self.assertNotIn(s, html)

    def test_estop_with_only_ack_changed(self):
        from TiaChangeReports.compare import compare_snapshots
        (blk,) = [x for x in compare_snapshots(FolderSnapshot(V1), FolderSnapshot(V2), {'HatchLogic'}, None, False)]
        n = 0
        for p in blk.nets:
            for eid, st in p.lad.status.items():
                if st == 'changed':
                    n += 1
                    self.assertEqual(changed_params(p.lad._el(eid), p.lad.other[eid]), {'ack'})
        self.assertEqual(n, 4)                                          # two ESTOP1 boxes, before and after


# ---------------------------------------------------------------- neutral TIA look, full width

class NeutralLook(unittest.TestCase):
    """Greys and white as TIA's editor; the diff colours stay the tool's own."""

    def pages(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')
        diffs = [compare_blocks(src(), src(t2)), compare_blocks(src(name='N'), src(t2, name='N'))]
        return render(diffs, 'b', 'a'), render(diffs, 'b', 'a', fragment=True)

    def test_no_uppercase_text(self):
        for html in self.pages():
            self.assertNotIn('uppercase', html.lower())

    def test_full_window_width(self):
        page, _ = self.pages()
        self.assertNotRegex(page, r'(main|body|\.ldiff)\{[^}]*max-width')

    def test_a_narrow_ladder_keeps_tias_scale(self):
        page, _ = self.pages()
        svgs = re.findall(r'<svg [^>]*class="lad"[^>]*>', page)
        self.assertTrue(svgs)
        for s in svgs:
            width = re.search(r' width="(\d+)"', s).group(1)
            self.assertIn('max-width:%spx' % width, s)

    def test_legend_swatches_have_a_border(self):
        _, frag = self.pages()
        rule = re.search(r'\.ldiff \.sw\{([^}]*)\}', frag).group(1)
        self.assertIn('border:', rule)

    def test_fragment_rules_scoped(self):
        _, frag = self.pages()
        css = re.search(r'<style>(.*?)</style>', frag, re.S).group(1)
        for rule in css.split('}'):
            sel = re.sub(r'^\s*@media[^{]*\{', '', rule).split('{')[0].strip()     # the rules inside an @media
            if sel:
                for part in sel.split(','):
                    self.assertTrue(part.strip().startswith('.ldiff'), part)


class ScrollToTop(unittest.TestCase):
    """A fixed button bottom right, hidden until scrolled down; a fragment scrolls to its own top."""

    def pages(self):
        diffs = [compare_blocks(src(), src(LAD_SCL))]
        return render(diffs, 'b', 'a'), render(diffs, 'b', 'a', fragment=True)

    def test_one_button_fixed_bottom_right_hidden_at_first(self):
        for html in self.pages():
            self.assertEqual(html.count('class="top"'), 1)
            rule = re.search(r'\.ldiff \.top\{([^}]*)\}', html).group(1)
            for prop in ('display:none', 'position:fixed', 'right:', 'bottom:'):
                self.assertIn(prop, rule)
            self.assertIn('.ldiff .top.show{display:block}', html)

    def test_page_to_its_top_fragment_to_the_report(self):
        page, frag = self.pages()
        self.assertTrue(frag.startswith('<div class="ldiff"><style>'))
        self.assertIn('<div class="ldiff" data-page>', page)
        self.assertIn("window.scrollTo({top:0", frag)
        self.assertIn("r.scrollIntoView(", frag)

    def test_block_header_name_and_number_as_tia(self):
        page, _ = self.pages()
        head = re.search(r'<div class="bh" id="blk-T">.*?</div>', page).group(0)
        self.assertTrue(_text(head).startswith('T [FB]'), _text(head))
        numbered = SRC.replace('{ S7_Optimized := "TRUE" }', '{\n    S7_Optimized := "TRUE";\n    S7_BlockNumber := "834"\n}')
        html = render([compare_blocks(src(numbered), src(numbered.replace('I_Contact( #b )', 'I_Contact( #a )')))],
                      'b', 'a')
        head = re.search(r'<div class="bh" id="blk-T">.*?</div>', html).group(0)
        self.assertTrue(_text(head).startswith('T [FB834]'), _text(head))


# ---------------------------------------------------------------- a renamed network pairs by content

FAULTS = ['#f[%d] := #a AND NOT #b;' % i for i in range(1, 7)]
FAULTS_EDITED = FAULTS[:4] + ['#f[5] := #a AND #b;', '#f[6] := NOT #a;']
TIMERS = ['#t%d := #a OR #b;' % i for i in range(1, 4)]
REWRITTEN = ['IF #a THEN', '    #s.x := TRUE;', 'ELSE', '    #s.x := FALSE;', 'END_IF;']
RUNGS = ('        RUNG wire#powerrail\n            Contact( #a )\n            I_Contact( #b )\n'
         '            Coil( #s.x )\n        END_RUNG')


def fb(*nets):
    """An FB of networks (lang, title, body: SCL lines or LAD rung text), a network titled "Fixed" first."""
    texts, parts = ['  - id: MLC_1\n    en-US: Fixed\n'], [
        '    {\n        S7_Language := "SCL";\n        S7_NetworkTitle := "MLC_1"\n    }\n'
        '    NETWORK\n        #s.x := #a;\n    END_NETWORK\n']
    for k, (lang, title, body) in enumerate(nets, 2):
        texts.append('  - id: MLC_%d\n    en-US: %s\n' % (k, title))
        if lang == 'SCL':
            body = '\n'.join('        ' + l for l in body)
        parts.append('    {\n        S7_Language := "%s";\n        S7_NetworkTitle := "MLC_%d"\n    }\n'
                     '    NETWORK\n%s\n    END_NETWORK\n' % (lang, k, body))
    head = SRC[:SRC.index('    {\n        S7_Language')]
    return src(head + ''.join(parts) + 'END_FUNCTION_BLOCK\n', 'MultiLingualTexts:\n' + ''.join(texts))


def _pairs(b, a):
    return [(p.state, p.before.title if p.before else None, p.after.title if p.after else None)
            for p in pair_networks(parse_block(b), parse_block(a)) if p.state != 'same']


class RenamedNetworks(unittest.TestCase):
    """Networks left over in a replaced stretch of the title alignment pair in order when their content is alike
    (compare.similarity >= RENAMED_MIN); a network rewritten from scratch stays deleted + new."""

    def test_renamed_and_edited(self):
        got = _pairs(fb(('SCL', 'Alarms 1..6', FAULTS)), fb(('SCL', 'Valve alarms', FAULTS_EDITED)))
        self.assertEqual(got, [('changed', 'Alarms 1..6', 'Valve alarms')])

    def test_renamed_only(self):
        b, a = parse_block(fb(('LAD', 'Seal-in', RUNGS))), parse_block(fb(('LAD', 'Hold x', RUNGS)))
        (p,) = [p for p in pair_networks(b, a) if p.state != 'same']
        self.assertEqual((p.state, p.renamed, p.lad.changed), ('changed', True, False))

    def test_rewritten_stays_apart(self):
        got = _pairs(fb(('SCL', 'Alarms 1..6', FAULTS)), fb(('SCL', 'Set x', REWRITTEN)))
        self.assertEqual(got, [('deleted', 'Alarms 1..6', None), ('new', None, 'Set x')])

    def test_two_renames_in_one_stretch(self):
        got = _pairs(fb(('SCL', 'Alarms', FAULTS), ('SCL', 'Timers', TIMERS)),
                     fb(('SCL', 'Valve alarms', FAULTS_EDITED), ('SCL', 'Delays', TIMERS)))
        self.assertEqual(got, [('changed', 'Alarms', 'Valve alarms'), ('changed', 'Timers', 'Delays')])

    def test_a_new_network_between_two_renames(self):
        got = _pairs(fb(('SCL', 'Alarms', FAULTS), ('SCL', 'Timers', TIMERS)),
                     fb(('SCL', 'Valve alarms', FAULTS), ('SCL', 'Set x', REWRITTEN), ('SCL', 'Delays', TIMERS)))
        self.assertEqual(got, [('changed', 'Alarms', 'Valve alarms'), ('new', None, 'Set x'),
                               ('changed', 'Timers', 'Delays')])

    def test_language_differs_stays_apart(self):
        got = _pairs(fb(('LAD', 'Seal-in', RUNGS)), fb(('SCL', 'Hold x', ['#s.x := #a AND NOT #b;'])))
        self.assertEqual(got, [('deleted', 'Seal-in', None), ('new', None, 'Hold x')])

    def test_page_shows_the_title_change_and_the_diff(self):
        d = compare_blocks(fb(('SCL', 'Alarms 1..6', FAULTS)), fb(('SCL', 'Valve alarms', FAULTS_EDITED)))
        html = render([d], 'b', 'a')
        bar, = [n for n in _nets(html) if 'alarms' in n.lower()]
        self.assertEqual(bar, '||Network 2:|||Alarms| |1||.||.||6|||||Network 2:|||Valve| |alarms|||changed||')
        self.assertIn('<span class="ti del"><span>Alarms</span> <span>1</span>', html)
        self.assertIn('<span class="ti ins"><span>Valve</span> <span>alarms</span></span>', html)
        self.assertIn('<td class="b del">', html)                                 # the normal line diff

    def test_network_filter_takes_either_title(self):
        b, a = fb(('SCL', 'Alarms 1..6', FAULTS)), fb(('SCL', 'Valve alarms', FAULTS_EDITED))
        for title in ('Alarms 1..6', 'Valve alarms'):
            d = compare_blocks(b, a, networks={title})
            self.assertEqual([(p.before.title, p.after.title) for p in d.nets], [('Alarms 1..6', 'Valve alarms')])

    def test_filler_network_renamed_and_edited_pairs(self):
        b, a = parse_block(from_file(FILLER_V1)), parse_block(from_file(FILLER_V2))
        (p,) = [p for p in pair_networks(b, a) if p.renamed]
        self.assertEqual((p.before.index, p.before.title, p.after.index, p.after.title),
                         (5, 'Close the coarse valve at the high probe', 6, 'High probe wet before the fill weight'))


# ---------------------------------------------------------------- title and comment as before | after

def _net(index, title, comment='', body=''):
    from TiaChangeReports.s7dcl import Network
    return Network(index, 'SCL', title, comment, body)


class TitleAndCommentSides(unittest.TestCase):
    """The title bar and the comment row are split over the panes; a changed text is marked as a changed SCL line."""

    def _bar(self, b, a):
        from TiaChangeReports.compare import NetPair
        from TiaChangeReports.page import _comment, _title_bar
        p = NetPair(b, a)
        return _title_bar(p), _comment(p)

    def test_same_title_and_comment_unmarked_on_both_sides(self):
        bar, com = self._bar(_net(3, 'Seal-in', 'keeps x', '#x := #a;'), _net(4, 'Seal-in', 'keeps x', '#x := #b;'))
        self.assertEqual(bar, '<div class="nwt"><span class="side"><span class="no">Network 3:</span>'
                              '<span class="ti">Seal-in</span></span><span class="side"><span class="no">Network 4:'
                              '</span><span class="ti">Seal-in</span><span class="st changed">changed</span></span>'
                              '</div>')
        self.assertEqual(com, '<div class="nwc"><span class="side"><span class="cf">keeps x</span></span>'
                              '<span class="side"><span class="cf">keeps x</span></span></div>')

    def test_changed_title_marks_the_changed_words(self):
        bar, _ = self._bar(_net(2, 'Alarms 1..6'), _net(2, 'Alarms 1..12'))
        self.assertIn('<span class="ti del">Alarms 1..<span>6</span></span>', bar)
        self.assertIn('<span class="ti ins">Alarms 1..<span>12</span></span>', bar)

    def test_changed_comment_marks_the_changed_words(self):
        _, com = self._bar(_net(2, 'A', 'stop at\nthe end'), _net(2, 'A', 'stop at\nthe slow sensor'))
        self.assertEqual(com, '<div class="nwc"><span class="side"><span class="cf del">stop at\nthe <span>end</span>'
                              '</span></span><span class="side"><span class="cf ins">stop at\nthe <span>slow</span> '
                              '<span>sensor</span></span></span></div>')

    def test_comment_cleared_leaves_tia_s_empty_field(self):
        _, com = self._bar(_net(2, 'A', 'old'), _net(2, 'A', ''))
        self.assertEqual(com, '<div class="nwc"><span class="side"><span class="cf del"><span>old</span></span></span>'
                              '<span class="side"><span class="cf none">Comment</span></span></div>')

    def test_new_and_deleted_network_only_on_its_own_side(self):
        bar, com = self._bar(None, _net(5, 'Set x', 'new one'))
        self.assertEqual(bar, '<div class="nwt"><span class="side"></span><span class="side"><span class="no">'
                              'Network 5:</span><span class="ti">Set x</span><span class="st new">new</span></span></div>')
        self.assertEqual(com, '<div class="nwc"><span class="side"></span>'
                              '<span class="side"><span class="cf">new one</span></span></div>')
        bar, com = self._bar(_net(5, 'Set x'), None)
        self.assertEqual(bar, '<div class="nwt"><span class="side"><span class="no">Network 5:</span><span class="ti">'
                              'Set x</span><span class="st deleted">removed</span></span><span class="side"></span></div>')
        self.assertEqual(com, '<div class="nwc"><span class="side"><span class="cf none">Comment</span></span>'
                              '<span class="side"></span></div>')

    def test_title_bar_still_folds_in_page_and_fragment(self):
        d = compare_blocks(fb(('SCL', 'Alarms 1..6', FAULTS)), fb(('SCL', 'Valve alarms', FAULTS_EDITED)))
        for html in (render([d], 'b', 'a'), render([d], 'b', 'a', fragment=True)):
            self.assertIn("var t=n.querySelector('.nwt');if(t)t.addEventListener('click'", html)
            self.assertIn('.ldiff .nw.fold>:not(.nwt){display:none}', html)
            self.assertIn('<span class="ti ins">', html)


# ---------------------------------------------------------------- network tags, collapse / expand all

class NetworkTagsAndFoldAll(unittest.TestCase):
    """A network's state tag in its title bar in the legend's colours (changed, removed, new; none when unchanged);
    collapse all / expand all in the block header, page and fragment."""

    def test_tag_per_state(self):
        from TiaChangeReports.compare import NetPair
        from TiaChangeReports.page import _title_bar
        same = _net(3, 'Seal-in', '', '#x := #a;')
        got = [re.findall(r'<span class="st (\w+)">(\w+)</span>', _title_bar(NetPair(b, a)))
               for b, a in ((same, _net(3, 'Seal-in', '', '#x := #b;')), (same, None), (None, same), (same, same))]
        self.assertEqual(got, [[('changed', 'changed')], [('deleted', 'removed')], [('new', 'new')], []])

    def test_tags_in_the_legend_colours(self):
        html = render([compare_blocks(fb(('SCL', 'A', FAULTS)), fb(('SCL', 'A', FAULTS_EDITED)))], 'b', 'a')
        for state, colour in (('new', 'add'), ('deleted', 'del'), ('changed', 'chg')):
            self.assertIn('.ldiff .nwt .st.%s{background:var(--%s-bg)}' % (state, colour), html)
        self.assertIn('.ldiff .sw.chg{background:var(--chg-bg)}', html)

    def test_buttons_in_the_header_of_a_block_with_networks(self):
        d = compare_blocks(fb(('SCL', 'A', FAULTS), ('SCL', 'B', TIMERS)), fb(('SCL', 'A', FAULTS_EDITED), ('SCL', 'B', TIMERS)))
        for html in (render([d], 'b', 'a'), render([d], 'b', 'a', fragment=True)):
            head = re.search(r'<div class="bh".*?</div>', html).group(0)
            self.assertIn('<span class="fa"><button type="button" title="Collapse every network of this block">'
                          'Collapse all</button><button type="button" title="Expand every network of this block">'
                          'Expand all</button></span></div>', head)
            self.assertIn("n.classList.toggle('fold',!k)", html)
            self.assertIn('@media print{.ldiff .bh .fa{display:none}}', html)

    def test_no_buttons_without_networks(self):
        new = compare_blocks(None, fb(('SCL', 'A', FAULTS)))
        self.assertNotIn('class="fa"', render([new], 'b', 'a', draw_added_removed=False))     # listed only
        self.assertIn('class="fa"', render([new], 'b', 'a', full=True))
        same = compare_blocks(fb(('SCL', 'A', FAULTS)), fb(('SCL', 'A', FAULTS)), all_=True)
        self.assertEqual(bool(same.nets), 'class="fa"' in render([same], 'b', 'a', full=True))


# ---------------------------------------------------------------- print, networks across pages

def _print_css(html):
    return ''.join(s.split('</style>', 1)[0] for s in html.split('@media print{')[1:])


class PrintPages(unittest.TestCase):
    """In print a block header and a network's title bar and comment row stay with what follows, a LAD network that
    fits a page is not split; the fold rows without "(click to show all)"; the page asks for A4 landscape, the
    fragment leaves the paper to its host."""

    def diffs(self):
        return [compare_blocks(src(MARK, '', 'K'), src(MARK.replace('speed := 5', 'speed := 6'), '', 'K'))]

    def test_heads_stay_with_the_body(self):
        for html in (render(self.diffs(), 'b', 'a'), render(self.diffs(), 'b', 'a', fragment=True)):
            self.assertIn('<div class="panes">', html)
            prn = _print_css(html)
            self.assertIn('.ldiff .bh,.ldiff .nwh,.ldiff .nwt,.ldiff .nwc{break-inside:avoid;break-after:avoid}', prn)
            self.assertIn('.ldiff .nw:has(>.panes:not(.txt)){break-inside:avoid}', prn)   # not SCL's halves, made in focus

    def test_fold_rows_without_the_click_hint(self):
        from TiaChangeReports import page
        rows =re.findall(r'<tr class="skip">.*?</tr>', page.scl_table(['x'] * 20, ['x'] * 19 + ['y']))
        self.assertEqual(rows, ['<tr class="skip"><td colspan="4">⋯ 16 unchanged lines<span class="hint"> (click to '
                                'show all)</span></td></tr>'])
        self.assertIn('unchanged members<span class="hint"> (click to show all)</span></td>', iface._skip(4, 5, 0))
        self.assertIn('.ldiff tr.skip .hint{display:none}', _print_css(render(self.diffs(), 'b', 'a', fragment=True)))

    def test_page_asks_for_a4_landscape_the_fragment_not(self):
        self.assertIn('@page{size:A4 landscape}', render(self.diffs(), 'b', 'a'))
        self.assertNotIn('@page', render(self.diffs(), 'b', 'a', fragment=True))


# ---------------------------------------------------------------- project tree, one object at a time

class ProjectTree(unittest.TestCase):
    """The page: a rail with the project tree (TIA's names for the top folders), one object shown at a time, each
    an address; the fragment and print: every object in a row with the summary, as before."""

    def diffs(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')

        def d(name, pb, pa, before=SRC, after=t2):
            return compare_blocks(src(before, name=name) if pb else None, src(after, name=name) if pa else None, pb, pa)
        return [d('Filler', 'library/types/Fillers/Filler/Filler.s7dcl', 'library/types/Fillers/Filler/Filler.s7dcl'),
                d('Filler', 'library/types/Fillers/Filler.released/Filler.s7dcl', None),
                d('Filler', 'plc/blocks/700_Fill/710_Filler/Filler.s7dcl', 'plc/blocks/700_Fill/710_Filler/Filler.s7dcl'),
                d('Prep data', None, 'plc/blocks/700_Fill/710_Filler/Prep data.s7dcl'),
                d('Alpha', 'plc/blocks/Alpha.s7dcl', 'plc/blocks/Alpha.s7dcl'),
                d('Filler_UDT', 'plc/types/Filler_UDT.s7dcl', 'plc/types/Filler_UDT.s7dcl')]

    def tree(self, html):
        nav = re.search(r'<nav class="rail".*?</nav>', html).group(0)
        return [(len(re.findall(r'<ul>', nav[:m.start()])) - len(re.findall(r'</ul>', nav[:m.start()])),
                 m.group(1) or m.group(3), m.group(2) or m.group(4))
                for m in re.finditer(r'<span class="fn"><span class="nm">([^<]*)</span><span class="n">(\d+)</span>'
                                     r'|<a class="obj \w+" href="#[^"]*" data-i="\d+" data-key="[^"]*" title="[^"]*">'
                                     r'<span class="mk"></span><span class="nm">([^<]*)</span><span class="k">([^<]*)',
                                     nav)]

    def test_tree_with_tias_names_folders_first(self):
        html = render(self.diffs(), 'b', 'a')
        self.assertEqual(self.tree(html), [
            (0, 'Program blocks', '3'), (1, '700_Fill', '2'), (2, '710_Filler', '2'), (3, 'Filler', '[FB]'),
            (3, 'Prep data', '[FB]'), (1, 'Alpha', '[FB]'),
            (0, 'PLC data types', '1'), (1, 'Filler_UDT', '[FB]'),
            (0, 'Types', '2'), (1, 'Fillers', '2'), (2, 'Filler', '[FB]'), (2, 'Filler', '[FB] released')])

    def test_each_object_an_address_of_its_section(self):
        diffs = self.diffs()
        html = render(diffs, 'b', 'a')
        links = re.findall(r'<a class="obj (\w+)" href="#([^"]*)" data-i="(\d+)" data-key="([^"]*)"', html)
        self.assertEqual(sorted((int(i), k, h, s) for s, h, i, k in links), [
            (0, 'Filler', 'Filler', 'changed'), (1, 'Filler~2', 'Filler~2', 'deleted'), (2, 'Filler~3', 'Filler~3', 'changed'),
            (3, 'Prep data', 'Prep%20data', 'new'), (4, 'Alpha', 'Alpha', 'changed'), (5, 'Filler_UDT', 'Filler_UDT', 'changed')])
        self.assertEqual(html.count('<section class="blk">'), len(diffs))           # every object still in the file

    def test_device_folders_under_the_device(self):
        t2 = SRC.replace('I_Contact( #b )', 'I_Contact( #a )')

        def d(name, path):
            return compare_blocks(src(SRC, name=name), src(t2, name=name), path, path)
        diffs = [d('Filler', 'library/types/Fillers/Filler/Filler.s7dcl'),
                 d('Filler', 'plc/PLC_B/blocks/700_Fill/Filler.s7dcl'),
                 d('Filler_UDT', 'plc/PLC_B/types/Filler_UDT.s7dcl'),
                 d('F_TRIG', 'plc/PLC_B/systemblocks/System blocks/Program resources/F_TRIG.xml'),
                 d('Alpha', 'plc/PLC_A/blocks/Alpha.s7dcl'),
                 d('Odd', 'plc/PLC_A/watchtables/Odd.xml')]
        self.assertEqual(self.tree(render(diffs, 'b', 'a')), [
            (0, 'PLC_A', '2'), (1, 'Program blocks', '1'), (2, 'Alpha', '[FB]'), (1, 'watchtables', '1'),
            (2, 'Odd', '[FB]'),
            (0, 'PLC_B', '3'), (1, 'Program blocks', '2'), (2, '700_Fill', '1'), (3, 'Filler', '[FB]'),
            (2, 'System blocks', '1'), (3, 'Program resources', '1'), (4, 'F_TRIG', '[FB]'),
            (1, 'PLC data types', '1'), (2, 'Filler_UDT', '[FB]'),
            (0, 'Types', '1'), (1, 'Fillers', '1'), (2, 'Filler', '[FB]')])
        one = d('F_TRIG', 'plc/systemblocks/System blocks/Program resources/F_TRIG.xml')    # one PLC: no device
        self.assertEqual(self.tree(render([one, d('Alpha', 'plc/blocks/Alpha.s7dcl')], 'b', 'a')), [
            (0, 'Program blocks', '2'), (1, 'System blocks', '1'), (2, 'Program resources', '1'), (3, 'F_TRIG', '[FB]'),
            (1, 'Alpha', '[FB]')])

    def test_single_files_a_flat_list(self):
        d = compare_blocks(src(), src(LAD_SCL), 'T.s7dcl', 'T.s7dcl')
        self.assertEqual(self.tree(render([d], 'b', 'a')), [(0, 'T', '[FB]')])
        self.assertEqual(self.tree(render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')), [(0, 'T', '[FB]')])

    def test_fragment_as_before_every_object_with_the_summary(self):
        from TiaChangeReports import page
        frag = render(self.diffs(), 'b', 'a', fragment=True)
        for gone in ('class="rail"', 'ldiff-rail', '.ldiff .rail', 'class="pn"'):
            self.assertNotIn(gone, frag)
        self.assertIn('<table class="sum">', frag)
        self.assertEqual(frag, '<div class="ldiff"><style>%s</style>%s<script>%s</script></div>' % (
            page.CSS, frag.split('</style>', 1)[1].rsplit('<script>', 1)[0], page.JS))
        self.assertNotIn('class="rail"', render([], 'b', 'a'))                      # nothing to show: no tree

    def test_page_one_object_summary_and_every_object_in_print(self):
        html = render(self.diffs(), 'b', 'a')
        self.assertIn('<table class="sum">', html)                                  # the table of contents in print
        self.assertIn('.ldiff.one section.blk{display:none} .ldiff.one section.blk.on{display:block}', html)
        self.assertIn('.ldiff.one table.sum{display:none}', html)
        prn = ''.join(s.split('</style>', 1)[0] for s in html.split('@media print{')[1:])
        for rule in ('.ldiff .rail', '.ldiff.one section.blk{display:block}', '.ldiff.one table.sum{display:table}'):
            self.assertIn(rule, prn)
        self.assertIn('main:has(>.ldiff>.rail){margin-left:260px}main:has(>.ldiff.rail-off){margin-left:28px}', html)
        self.assertTrue(_flow(html).startswith('<div class="cols">'))               # the column header on top

    def test_keys_history_and_the_rail_kept(self):
        html = render(self.diffs(), 'b', 'a')
        for hook in ("window.addEventListener('hashchange'", "location.hash=a.getAttribute('href')",
                     "keys:['Alt+ArrowUp']", "keys:['Alt+ArrowDown']", "keys:['Ctrl+b']", "localStorage.setItem('ldiff-rail'",
                     "r.classList.add('one')", "r.classList.add('flat')", 'title="Previous object (Alt+Up)"',
                     'title="Next object (Alt+Down)"', 'r.ldiffOpen=go'):
            self.assertIn(hook, html)

    def test_png_shows_every_object(self):
        import inspect
        from TiaChangeReports import __main__ as cli
        self.assertIn("+ '?all&png'", inspect.getsource(cli.shoot))

    def test_search_box_above_the_tree(self):
        nav = re.search(r'<nav class="rail".*?</nav>', render(self.diffs(), 'b', 'a')).group(0)
        self.assertRegex(nav, r'</button></div><div class="rs"><input type="search" placeholder="Search" '
                              r'aria-label="Search objects" [^>]*></div><div class="nf">No object found</div>'
                              r'<ul class="tree">')
        self.assertNotIn('class="rs"', render(self.diffs(), 'b', 'a', fragment=True))

    def test_search_fuzzy_ranked_marked_keys(self):
        from TiaChangeReports import page
        js = page.RAIL_JS
        for hook in ("box.addEventListener('input',search)", "v.toLowerCase().replace(/\\s+/g,'')", "query(box.value)",
                     "l.charAt(j)==q.charAt(i)",                                     # letters in order
                     "found.sort(function(x,y){return y[0]-x[0]||x[1]-y[1]||x[2]-y[2]})",   # best first, then short
                     "Math.min(k,200)", "'<mark>'", "f.cnt.textContent!==t", "rail.classList.toggle('none'",
                     "k=='Escape'", "box.value=''", "box.blur()", "k=='Enter'", "go(act)", "k=='ArrowDown'"):
            self.assertIn(hook, js)
        for rule in ('.ldiff .tree.find li.miss{display:none}', '.ldiff .tree.find .shut>ul{display:flex}',
                     '.ldiff .tree,.ldiff .tree ul{display:flex;flex-direction:column}', '.ldiff .tree mark,'):
            self.assertIn(rule, page.RAIL_CSS)
        self.assertNotRegex(js + page.RAIL_CSS, r'https?:|fetch\(|import\(|<script src')   # offline, in the file

    def test_the_tree_is_shared_with_the_hmi_preview(self):
        from TiaChangeReports import page
        from hmipreview import rail
        self.assertEqual(page.RAIL_CSS, rail.CSS)
        self.assertTrue(page.RAIL_JS.startswith(rail.JS))
        self.assertTrue(page.RAIL_JS.endswith("ldiffRail(document.currentScript&&document.currentScript.closest('.ldiff'));\n"))
        self.assertTrue(page.CSS.startswith('\n' + rail.BASE_CSS))
        self.assertEqual(page.LAUNCHER, rail.LAUNCHER)
        self.assertIs(page._tree_items, rail.tree_items)
        html = render(self.diffs(), 'b', 'a')
        self.assertIn(rail.JS, html)


class ObjectLauncher(unittest.TestCase):
    """Ctrl+K, or / outside a text field, opens a box over the page listing the objects ranked by the
    tree's search; the page only."""

    def test_on_the_page_outside_the_rail_not_in_fragment_or_print(self):
        from TiaChangeReports import page
        diffs = ProjectTree().diffs()
        html = render(diffs, 'b', 'a')
        self.assertIn('</ul></nav>' + page.LAUNCHER + '<div class="ld"', html)   # after the rail, not inside it
        self.assertRegex(page.LAUNCHER, r'^<div class="lch" hidden><div class="lb" role="dialog"[^>]*><input '
                                        r'type="text"[^>]*><ul role="listbox"></ul></div></div>$')
        self.assertNotIn('class="lch"', render(diffs, 'b', 'a', fragment=True))
        self.assertNotIn('class="lch"', render([], 'b', 'a'))
        self.assertIn('.ldiff .top,.ldiff .lch,.ldiff .ld{display:none!important}',
                      page.RAIL_CSS.split('@media print{')[-1])
        self.assertRegex(html, r'title="[^"]*Ctrl\+K or / opens this search over the page, \? lists every key"')

    def test_help_button_opens_the_list_of_keys(self):
        from TiaChangeReports import page
        html = render(ProjectTree().diffs(), 'b', 'a')
        head = re.search(r'<div class="rh">.*?</div>', html).group(0)
        self.assertRegex(head, r'<button type="button" class="rq" title="List every key \(\?\)" '
                               r'aria-label="List every key">\?</button>')
        self.assertIn("if(e.target.closest('.rq')){lookup(help);return}if(r.classList.contains('rail-off'))", page.RAIL_JS)
        self.assertNotIn('class="rq"', render(ProjectTree().diffs(), 'b', 'a', fragment=True))
        self.assertIn('.ldiff .rail,', page.RAIL_CSS.split('@media print{')[-1])     # print: gone with the rail
        self.assertIn('.ldiff.flat .rail{display:none}', page.RAIL_CSS)              # ?all, --png: gone with the rail

    def test_keys_and_the_trees_ranking(self):
        from TiaChangeReports import page
        js = page.RAIL_JS
        for hook in ("keys:['Ctrl+k','/'],run:function(){lookup(blocks)}", "ph:'Lookup program blocks...'",
                     "/^(INPUT|TEXTAREA|SELECT)$/", "isContentEditable",
                     "lin.addEventListener('input',lfill)", "q?rank(q,s):", "marked(t,h[4])",
                     "lrows=found.slice(0,100)", "No object found", "k=='Escape'){e.preventDefault();lclose()}",
                     "k=='Enter'){e.preventDefault();lgo(lat)}", "lclose();c.go(h[3])", "!e.target.closest('.lb'))lclose()",
                     "f.join(' / ')", "a.classList[1]"):
            self.assertIn(hook, js)
        self.assertEqual(js.count('function fuzzy('), 1)                            # one matcher, one ranking
        self.assertEqual(js.count('.sort(function(x,y){return y[0]-x[0]'), 1)
        self.assertIn('found=rank(q)', js)
        self.assertNotIn('Alt+Space', page.tree_html(ProjectTree().diffs()))
        for rule in ('.ldiff .lch .new .mk{background:var(--add)}', '.ldiff .tree mark,.ldiff .lch mark{',
                     '.ldiff .lch li.act{', '.ldiff .lch .pt{'):
            self.assertIn(rule, page.RAIL_CSS)


class FocusNetwork(unittest.TestCase):
    """A button in every network's title bar shows that network over the whole window (column header on
    top, zoom as on the page); Esc or the button again puts it back; #Name/59 opens straight into focus, a middle
    click in a new window. The page only."""

    def test_page_only_not_in_fragment_print_or_all(self):
        from TiaChangeReports import page
        diffs = ProjectTree().diffs()
        html = render(diffs, 'b', 'a')
        self.assertIn(page.FOCUS_CSS, html)
        self.assertIn(page.FOCUS_JS, html)
        self.assertTrue(html.split('<script>')[-1].endswith(page.FOCUS_JS + '</script></div></main></body></html>'))
        frag = render(diffs, 'b', 'a', fragment=True)
        for gone in ('class="fx"', "'fx'", '.ldiff .fcs', 'fxs'):
            self.assertNotIn(gone, frag)
        self.assertNotIn("'fx'", render([], 'b', 'a'))
        self.assertNotIn('class="fx"', html)                                      # the script adds the buttons
        self.assertRegex(page.FOCUS_JS, r"if\(r\.classList\.contains\('flat'\)\)\{[^\n]*\n[^\n]*\}\);return\}\nvar secs=")
        # not in ?all (--png: only the wide networks stacked)
        prn = page.FOCUS_CSS.split('@media print{')[1]
        self.assertIn('.ldiff .nwt .fx,.ldiff .fcs{display:none!important}', prn)
        self.assertIn("addEventListener('beforeprint'", page.FOCUS_JS)

    def test_over_the_window_with_the_column_header_and_back(self):
        from TiaChangeReports import page
        js, css = page.FOCUS_JS, page.FOCUS_CSS
        self.assertIn('.ldiff .fcs{position:fixed;inset:0;z-index:35;overflow:auto;', css)   # over the rail (30),
        self.assertIn('z-index:40', page.RAIL_CSS.split('.ldiff .lch{')[1].split('}')[0])     # under the launcher
        for hook in ("fc.appendChild(cols.cloneNode(true))",                       # column header
                     "n.parentNode.replaceChild(ph,n)", "fc.appendChild(n)",        # the network itself moves
                     "ph.style.height=n.offsetHeight+'px'", "c.ph.parentNode.replaceChild(n,c.ph)",
                     "window.scrollTo(0,c.url?", ":c.y)",                           # back where it was
                     "e.key=='Escape'&&!e.defaultPrevented", "if(cur&&cur.n==n)close();else open(n)",
                     "if(n.ldiffFit)n.ldiffFit()", "de.style.overflow='hidden'"):
            self.assertIn(hook, js)
        self.assertIn("n.ldiffFit=function(){if(z)set(0,", page.JS)                # zoom back to fit

    def test_the_button_does_not_fold_the_network(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        self.assertIn("b.onclick=function(e){e.stopPropagation();", js)
        self.assertIn("if(e.button!=1)return;e.preventDefault();e.stopPropagation();pop(n)", js)
        self.assertIn("b.onmousedown=function(e){if(e.button==1)e.preventDefault()}", js)   # no autoscroll
        self.assertIn('.ldiff.fxs .nwt .side+.side{padding-right:34px}', page.FOCUS_CSS)    # room beside the tag

    def test_address_opens_focus_middle_click_a_new_window(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        for hook in ("n.addr=a.getAttribute('href')+'/'+n.num",
                     "a?a.textContent.replace(/\\D/g,''):b?'b'+b.textContent.replace(/\\D/g,''):''",   # after, else b
                     "history.replaceState(history.state,'',n.addr)",
                     "window.addEventListener('hashchange'", "var t=target();if(t)open(t,true)",
                     "window.open(u,'_blank','popup,", "if(!w)window.open(u,'_blank')"):
            self.assertIn(hook, js)
        self.assertIn(".replace(/\\/b?\\d+$/,'')", page.RAIL_JS)                    # #Name/59 finds Name

    def test_address_numbers(self):
        """The after side's number; a deleted network the before side's with b."""
        html = render([compare_blocks(src(), src(LAD_SCL))], 'b', 'a')
        bars = re.findall(r'<div class="nwt">(.*?)</div>', html)
        nums = []
        for bar in bars:
            sides = re.findall(r'<span class="side">(.*?)</span>(?=<span class="side">|$)', bar)
            no = [re.search(r'Network (\d+):', s) for s in sides]
            nums.append(no[1].group(1) if no[1] else 'b' + no[0].group(1))
        self.assertTrue(nums)
        self.assertEqual(len(set(nums)), len(nums))                                # one address per network


class FocusStacked(unittest.TestCase):
    """A network in focus shows before above after, each pane the full width, its label at its left
    edge instead of the column header; a button in the title bar or S switches to side by side and back, kept in
    the browser; the page itself unchanged. An SCL network the same (FocusStackedScl)."""

    def test_stacked_is_a_class_of_the_focus_overlay(self):
        from TiaChangeReports import page
        css, js = page.FOCUS_CSS, page.FOCUS_JS
        self.assertIn('.ldiff :is(.fcs.stk,.nw.stk) .panes{grid-template-columns:1fr}', css)   # one column, full width
        self.assertIn('.ldiff .fcs.stk>.cols{display:none}', css)                  # labels instead of the header
        self.assertIn("fc.classList.toggle('lad',lad);fc.classList.toggle('stk',lad&&stk)", js)
        self.assertIn("t=!!w&&w.classList.contains('txt'),lad=!!w&&(!t||stk)", js)   # SCL side by side: its table
        for rule in css.split('}'):                # nothing stacked on the page (.nw.stk: the PNG only)
            for sel in re.split(r',(?![^(]*\))', rule.split('{')[0]):
                if 'stk' in sel or ('.sl' in sel and 'display:none' not in rule):
                    self.assertTrue(sel.strip().startswith(('.ldiff .fcs.stk', '.ldiff :is(.fcs.stk,.nw.stk)',
                                                            '.ldiff .nw.stk', '.ldiff .fcs.lad:not(.stk)',
                                                            '.ldiff .fcs.txt:not(.stk)')), sel)
        self.assertIn('.ldiff .pane>.sl{display:none}', css)

    def test_labels_at_the_left_edge_from_the_column_header(self):
        from TiaChangeReports import page
        js, css = page.FOCUS_JS, page.FOCUS_CSS
        self.assertIn("var d=cols&&cols.children[i]", js)                          # Before / After with the source
        self.assertIn("l.className='sl';l.innerHTML=d.innerHTML", js)
        self.assertIn('writing-mode:vertical-rl', css.split('.ldiff :is(.fcs.stk,.nw.stk) .pane>.sl{')[1].split('}')[0])
        self.assertIn('.ldiff :is(.fcs.stk,.nw.stk) .pane{min-height:64px;padding-left:22px;', css)
        self.assertIn('.ldiff :is(.fcs.stk,.nw.stk) .empty{padding:4px 10px;font-size:11.5px}', css)   # "no network" small

    def test_toggle_button_and_key_kept_in_the_browser(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        self.assertIn("var stk=keep()!='0'", js)                                   # stacked by default
        self.assertIn("localStorage.setItem('ldiff-stack',v)", js)
        self.assertIn("sb.onclick=function(e){e.stopPropagation();stack(!stk)}", js)   # no fold
        self.assertIn("keys:['s'],\n when:function(){return !!cur&&!!cur.n.querySelector(':scope>.panes')},run:function(){stack(!stk)}", js)
        self.assertIn("typing(e.target)", page.RAIL_JS)                            # typing in the lookup
        self.assertIn("function stack(v){stk=v;keep(v?'1':'0');if(cur&&cur.n.ldiffFit)cur.n.ldiffFit();lay();fc.scrollTop=0}", js)
        self.assertIn('.ldiff .fcs.lad .nwt .fl{display:flex}', page.FOCUS_CSS)   # only in focus
        self.assertIn('.ldiff .fcs.txt .nwt .fl{display:flex}', page.FOCUS_CSS)   # SCL side by side has no class lad
        self.assertIn('.ldiff .nwt .fl{position:absolute;right:33px;', page.FOCUS_CSS)
        frag = render(ProjectTree().diffs(), 'b', 'a', fragment=True)
        self.assertNotIn('ldiff-stack', frag)

    def test_fit_and_room_to_pan_per_frame(self):
        """Both halves at one scale, fitted to the frame's own width (the label strip left out); the room to pan
        per frame, so a short and a tall half keep one scroll range."""
        from TiaChangeReports import page
        self.assertIn("return Math.min(1,(p.clientWidth-parseFloat(c.paddingLeft)", page.JS)
        self.assertIn("q._by=Math.max(0,l-parseFloat(c.paddingTop)", page.JS)
        self.assertNotIn('bx=0,by=0', page.JS)


class FocusFillsTheWindow(unittest.TestCase):
    """A LAD network in focus fills the window, stacked one half each, side by side one column each; a
    network taller than its frame scrolls inside it, one scroll range for both; stacked, a network with one side takes
    the window but for the missing half's strip; a resize keeps it. SCL side by side and the page stay as they were."""

    def rules(self):
        from TiaChangeReports import page
        return {r.split('{')[0].strip(): r.split('{', 1)[1] for r in page.FOCUS_CSS.split('}') if '{' in r}

    def test_the_overlay_does_not_scroll_and_the_network_fills_it(self):
        rules = self.rules()
        self.assertEqual(rules['.ldiff .fcs.lad'], 'display:flex;flex-direction:column;overflow:hidden;padding:0')
        self.assertEqual(rules['.ldiff .fcs.lad>.nw'], 'flex:1 1 0;min-height:0;display:flex;flex-direction:column;margin:0')

    def test_two_equal_halves_whatever_the_network(self):
        rules = self.rules()
        self.assertEqual(rules['.ldiff .fcs.lad .panes'], 'flex:1 1 0;min-height:0;grid-template-rows:minmax(0,1fr)')
        self.assertEqual(rules['.ldiff .fcs.stk .panes'], 'grid-template-rows:minmax(0,1fr) minmax(0,1fr)')
        self.assertEqual(rules['.ldiff .fcs.lad .pane'], 'display:flex;flex-direction:column;min-height:0')

    def test_a_tall_network_scrolls_in_its_frame_at_one_scale(self):
        rule = self.rules()['.ldiff .fcs.lad .pane>.pb']
        self.assertIn('flex:1 1 0;min-height:0;overflow:auto', rule)   # the height a zoom locks does not count here
        self.assertIn('scrollbar-gutter:stable', rule)                 # a scrollbar on one half only: the same width

    def test_a_long_comment_never_takes_the_frame_away(self):
        self.assertEqual(self.rules()['.ldiff .fcs.stk .pane>.sh'], 'flex:none;max-height:45%;overflow:auto')
        self.assertEqual(self.rules()['.ldiff .fcs.lad .nw>.nwc'], 'flex:0 1 auto;min-height:0;max-height:35%;overflow:auto')

    def test_a_network_with_one_side_takes_the_window(self):
        rules = self.rules()
        self.assertEqual(rules['.ldiff .fcs.stk .panes:has(>.pane:first-child>.pb>.empty)'],
                         'grid-template-rows:64px minmax(0,1fr)')
        self.assertEqual(rules['.ldiff .fcs.stk .panes:has(>.pane:last-child>.pb>.empty)'],
                         'grid-template-rows:minmax(0,1fr) 64px')
        html = render([compare_blocks(None, src())], 'b', 'a', draw_added_removed=True)
        self.assertIn('<div class="pane"><div class="pb"><div class="empty">no network</div></div></div>', html)

    def test_a_change_of_a_frame_redoes_the_room_to_pan_only_in_focus(self):
        from TiaChangeReports import page
        self.assertIn("var sized=new ResizeObserver(function(){if(cur&&fc.classList.contains('lad'))cur.n.ldiffResize()})",
                      page.FOCUS_JS)
        self.assertIn("sized.disconnect();if(lad)cur.n.querySelectorAll('.panes .pb').forEach(function(q){sized.observe(q)})",
                      page.FOCUS_JS)
        self.assertIn("if(!above(z)){set(0,p,{clientX:o.left+o.width/2,clientY:o.top+o.height/2});return}\n"
                      "  room();draw();n.dispatchEvent(new Event('ldiffzoom'))}", page.JS)

    def test_one_scroll_range_for_a_tall_and_a_short_half(self):
        from TiaChangeReports import page
        self.assertIn("s.style.setProperty('--mb','min('+g+'px,'+100*g/wide+'%)')", page.JS)   # (tall-h) at the fit scale
        self.assertEqual(self.rules()['.ldiff .fcs.lad .nw:not(.zoom) .pb svg.lad'],
                         'margin-bottom:calc(var(--mb,0px) + var(--fh,0px))')
        self.assertIn("s.style.setProperty('--fh',s.closest('.pb').clientHeight-l+'px')", page.JS)   # a higher frame
        self.assertIn("tall*f)+q.getBoundingClientRect().height-l", page.JS)                          # the same, zoomed

    def test_the_keys_scroll_the_frames(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        self.assertIn("fc.ldiffFrame=function(){return cur&&fc.classList.contains('lad')?cur.n.ldiffLead():null}", js)
        # only a key that scrolls takes the lead: Shift or a letter in mid-drag leaves the sync alone
        head = js.split("fc.addEventListener('keydown',function(e){")[1].split('var p=fc.ldiffFrame()')[0]
        self.assertIn("!(sp||/^(Arrow(Up|Down|Left|Right)|Page(Up|Down)|Home|End)$/.test(k)))return;", head)
        self.assertIn("((f.ldiffFrame&&f.ldiffFrame())||f).scrollTo({top:0,behavior:'smooth'})", page.RAIL_JS)   # T
        for key in ('ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'PageDown', 'PageUp', 'Home', 'End'):
            self.assertIn(key + ':[', js)
        self.assertIn("sp=k==' '&&!e.target.closest('button')", js)        # Space on a button is the button's
        self.assertIn("n.ldiffLead=function(){return lead=ss[0].closest('.pb')}", page.JS)   # the other half follows

    def test_back_to_fit_keeps_the_spot_and_leaving_goes_to_the_start(self):
        from TiaChangeReports import page
        self.assertIn("p.scrollTop=p.scrollTop+b.top+fy*b.height-e.clientY", page.JS)
        self.assertNotIn('p.scrollTop=z?', page.JS)
        self.assertIn("n.ldiffFit=function(){if(z)set(0,ss[0].closest('.pb'),{clientX:0,clientY:0});"
                      "pb.forEach(function(q){q.scrollLeft=q.scrollTop=0})}", page.JS)

    def test_a_press_on_a_scrollbar_is_no_drag(self):
        from TiaChangeReports import page
        self.assertIn("if(e.clientX>=o.left+p.clientLeft+p.clientWidth||e.clientY>=o.top+p.clientTop+p.clientHeight)return;"
                      "e.preventDefault();p._moved=false;", page.JS)

    def test_the_buttons_stand_at_one_place_in_both_layouts(self):
        rules = self.rules()
        self.assertEqual(rules['.ldiff .fcs.lad:not(.stk) .nw>.nwt .fx,.ldiff .fcs.lad:not(.stk) .nw>.nwt .fl'],
                         'position:fixed;top:12px;z-index:11')
        self.assertEqual(rules['.ldiff .fcs.lad:not(.stk)>.cols .side+.side'], 'padding-right:62px')

    def test_scl_and_the_page_keep_their_rules(self):
        from TiaChangeReports import page
        rules = self.rules()
        self.assertEqual(rules['.ldiff .fcs'],
                         'position:fixed;inset:0;z-index:35;overflow:auto;overscroll-behavior:contain;background:#fff;'
                         'padding:0 16px 16px')
        self.assertIn('.ldiff .pb{overflow:hidden;padding:4px 2px;box-sizing:border-box}', page.CSS)
        for sel in rules:
            if 'grid-template-rows' in rules[sel] or 'scrollbar-gutter' in rules[sel]:
                self.assertTrue(sel.startswith(('.ldiff .fcs.lad', '.ldiff .fcs.stk')), sel)   # never .nw.stk (the PNG) nor the page


class FocusStackedTitles(unittest.TestCase):
    """Stacked, each half's title line and comment right above its render, no split title bar on top;
    a missing half leaves its title out ("no network" alone); side by side and the page unchanged."""

    def test_each_half_gets_its_title_and_comment(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        self.assertIn("var t=n.querySelectorAll(':scope>.nwt>.side'),c=n.querySelectorAll(':scope>.nwc>.side')", js)
        self.assertIn("if(t[i]&&t[i].firstChild){var h=document.createElement('div');h.className='sh';", js)  # missing: none
        self.assertIn("[t[i],c[i]].forEach(function(x,k){var w=document.createElement('div');w.className=k?'nwc':'nwt';", js)
        self.assertIn("p.insertBefore(h,p.querySelector('.pb'))", js)            # below the strip, above the render

    def test_title_bar_on_top_only_side_by_side(self):
        from TiaChangeReports import page
        css = page.FOCUS_CSS
        self.assertIn('.ldiff .pane>.sh{display:none}', css)                      # page and side by side
        self.assertIn('.ldiff :is(.fcs.stk,.nw.stk) .pane>.sh{display:block}', css)
        self.assertIn('.ldiff .fcs.stk .nw>.nwt>.side,.ldiff .fcs.stk .nw>.nwc{display:none}', css)
        self.assertIn('.ldiff .fcs.stk .nw>.nwt{z-index:5;display:block;height:0;', css)  # the buttons
        self.assertNotIn('position:sticky', css)                                   # the overlay of a LAD network does not scroll
        self.assertNotIn('.ldiff .fcs.stk .nwt{', css)                            # not the halves' title lines
        self.assertIn('.ldiff .fcs.lad .nwt .side+.side{padding-right:8px}', css)  # the buttons stand on the column header
        for rule in css.split('}'):
            for sel in re.split(r',(?![^(]*\))', rule.split('{')[0]):
                if '.sh' in sel and 'display:none' not in rule:
                    self.assertTrue(sel.strip().startswith(('.ldiff .fcs.stk', '.ldiff :is(.fcs.stk,.nw.stk)')), sel)

    def test_page_unchanged(self):
        html = render(ProjectTree().diffs(), 'b', 'a')
        self.assertNotIn('class="sh"', html)


class KeysAndLookups(unittest.TestCase):
    """One lookup window for the program blocks and the networks of the open object (and the list of
    keys), on the tree's ranking; a key for every button, named in its tooltip; ? lists them. The page only."""

    def scripts(self):
        from TiaChangeReports import page
        return page.RAIL_JS + page.FOCUS_JS

    def test_one_window_one_matcher(self):
        from TiaChangeReports import page
        js = self.scripts()
        html = render(ProjectTree().diffs(), 'b', 'a')
        self.assertEqual(html.count('class="lch"'), 1)
        for once in ('function fuzzy(', 'function rank(', 'function lookup(', 'function lfill(', "querySelector('.lch')"):
            self.assertEqual(js.count(once), 1, once)
        self.assertNotIn('function fuzzy(', page.FOCUS_JS)
        for hook in ('r.ldiffLookup=lookup', 'r.ldiffSource=source', 'r.ldiffKey=key',
                     "ph:'Lookup program blocks...'", "ph:'Lookup networks...'", 'r.ldiffLookup(nets)',
                     'r.ldiffSource(ns.map(function(n){return n.lk.t}),ns.map(function(n){return n.lk.n}),ns)'):
            self.assertIn(hook, js)
        self.assertNotIn('placeholder=', page.LAUNCHER)                             # set per lookup

    def test_networks_by_title_or_number(self):
        from TiaChangeReports import page
        js = page.RAIL_JS
        self.assertIn("var d=q.replace(/^(network|nw)/,''),v=0;if(!/^\\d+$/.test(d))return 0;", js)   # "59", "nw59"
        self.assertIn("if(x==d)v=1e4;else if(!v&&x.indexOf(d)==0)v=5e3", js)      # 59 before 590
        self.assertIn("if(u&&(!f||u>f[0]))f=[u,null]", js)                          # a number before a title
        self.assertIn("found.push([f[0],f[1]?l.length:0,k,s.o[k],f[1]])", js)      # number matches in page order
        fj = page.FOCUS_JS
        self.assertIn("k:'Network '+(no[0]&&no[1]&&no[0]!=no[1]?no[0]+' | '+no[1]:no[1]||no[0])", fj)   # both sides
        self.assertIn("g:g.length?[g[0].classList[1],[].map.call(g,function(x){return x.textContent}).join(', ')]:null",
                      fj)                                                         # the network's tags
        self.assertIn("go:function(n){if(!cur||cur.n!=n)open(n)}", fj)             # Enter: into focus
        self.assertIn("row:function(k){var l=ns[k].lk;return ['net',l.k,'',l.g]}", fj)
        self.assertIn('.ldiff .lch .st.deleted{background:var(--del-bg)}', page.RAIL_CSS)

    def test_a_key_for_every_button_in_its_tooltip(self):
        from TiaChangeReports import page
        js = self.scripts()
        keys = re.findall(r"show:'([^']*)',text:'[^']*',keys:\[([^\]]*)\]", js)
        self.assertEqual([k for k, _ in keys], ['Ctrl+B', 'Alt+Up', 'Alt+Down', 'C', 'E', 'T', 'Ctrl+K or /', '?', 'Esc',
                                                 'F', 'S', 'Ctrl+G or G'])
        combos = [c.strip("'") for _, ks in keys for c in ks.split(',') if c]
        for c in combos:                                                            # what the browsers keep
            self.assertNotIn(c.lower(), ('ctrl+n', 'ctrl+t', 'ctrl+w', 'alt+ ', 'ctrl+tab'))
        self.assertEqual(len(combos), len(set(combos)))
        tree = page.tree_html(ProjectTree().diffs())
        self.assertIn('title="Hide or show the project tree (Ctrl+B)"', tree)
        for tip in ("title=\"Previous object (Alt+Up)\"", "title=\"Next object (Alt+Down)\"", "b.title+=k?' (E)':' (C)'",
                    "top.title+=' (T)'", "Focus: this network over the whole window (F;", "'Back to the page (Esc or F)'",
                    "'Before beside after (S)'"):
            self.assertIn(tip, js)

    def test_keys_reach_nothing_while_typing_and_list_themselves(self):
        js = self.scripts()
        self.assertIn("if(e.defaultPrevented||typing(e.target)||!lch.hidden)return;", js)
        self.assertIn("(e.shiftKey&&(m||e.altKey||k.length>1)?'Shift+':'')", js)  # ? and S without Shift+
        self.assertIn("help={ph:'Keys...'", js)
        self.assertIn("source(keys.map(function(x){return x.text}),null,keys.slice())", js)
        self.assertEqual(js.count("document.addEventListener('keydown'"), 2)       # the dispatcher, Esc of focus
        frag = render(ProjectTree().diffs(), 'b', 'a', fragment=True)
        for gone in ('ldiffKey', 'Lookup program blocks', 'Lookup networks'):
            self.assertNotIn(gone, frag)


# ---------------------------------------------------------------- renamed blocks

PREP = os.path.join(V1, 'plc', 'blocks', 'Bottling', 'PrepareFillData')


def _prep(name='PrepareFillData', edit=False, keys='', number='743', setpoint=False, folder='plc/blocks/Bottling/'):
    """PrepareFillData's export under another name: {path: text}. edit: network 1 changed; keys: appended to every
    MLC key (TIA renumbers them per copy); number None: no S7_BlockNumber; setpoint: S7_Setpoint := "False" on an
    input (the project block writes it, the released library version not)."""
    with open(PREP + '.s7dcl', encoding='utf-8') as f:
        sd = f.read()
    with open(PREP + '.s7res', encoding='utf-8') as f:
        res = f.read()
    sd = sd.replace('FUNCTION_BLOCK "PrepareFillData"', 'FUNCTION_BLOCK "%s"' % name)
    if edit:
        sd = sd.replace('#ioFillData.Supply.AirOK;', '#ioFillData.Supply.AirOK AND #iPhase > 0;')
    if keys:
        sd, res = (re.sub(r'MLC_(\w+)', r'MLC_\g<1>' + keys, x) for x in (sd, res))
    sd = sd.replace('    S7_BlockNumber := "743";\n', '') if number is None else sd.replace('"743"', '"%s"' % number)
    if setpoint:
        sd = sd.replace('        iPhase : Int;', '        {\n            S7_Setpoint := "False"\n        }\n'
                                                  '        iPhase : Int;')
    return {folder + name + '.s7dcl': sd, folder + name + '.s7res': res}


BAY4 = os.path.join(V1, 'plc', 'blocks', 'Lines', 'Bay4')


def _bay4(name='Bay4'):
    with open(BAY4 + '.s7dcl', encoding='utf-8') as f:
        sd = f.read()
    return {'plc/blocks/Lines/%s.s7dcl' % name: sd.replace('"Bay4"', '"%s"' % name)}


def _rewritten(name='PrepareFillData', number='743'):
    """PrepareFillData with network 1 kept and the others replaced by Bay4's networks: 0.43 alike, between
    source.NUMBER_BLOCK_MIN and RENAMED_BLOCK_MIN."""
    files = _prep(name, number=number)
    sd = next(p for p in files if p.endswith('.s7dcl'))
    with open(BAY4 + '.s7dcl', encoding='utf-8') as f:
        b4 = f.read()
    files[sd] = files[sd][:files[sd].index('END_NETWORK\n') + 12] + b4[b4.index('    {\n        S7_Language'):]
    return files


class RenamedBlocks(unittest.TestCase):
    """A block deleted on one side and new on the other is one renamed block (source.pair_blocks): same kind and
    number, else similar content; a PLC block only with a PLC block, a library type only with a library type."""

    def folders(self, before, after):
        """Two export folders, the UDT D unchanged in both (one block on each side would pair as it is)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _write(os.path.join(tmp.name, 'b'), {**before, 'plc/types/D.s7dcl': UDT_D})
        _write(os.path.join(tmp.name, 'a'), {**after, 'plc/types/D.s7dcl': UDT_D})
        return FolderSnapshot(os.path.join(tmp.name, 'b')), FolderSnapshot(os.path.join(tmp.name, 'a'))

    def states(self, before, after, **kw):
        from TiaChangeReports.compare import compare_snapshots
        return [(d.state, d.name) for d in compare_snapshots(*self.folders(before, after), **kw)]

    def test_renamed_and_edited_as_folders(self):
        from TiaChangeReports.compare import compare_snapshots
        b, a = self.folders(_prep('PrepareFillData_1'), _prep(edit=True, keys='x'))
        self.assertEqual(pair_blocks(b, a), [('plc/types/D.s7dcl', 'plc/types/D.s7dcl'),
                                             ('plc/blocks/Bottling/PrepareFillData_1.s7dcl',
                                              'plc/blocks/Bottling/PrepareFillData.s7dcl')])
        (d,) = compare_snapshots(b, a)
        self.assertEqual((d.state, d.renamed, d.name, d.itf_changed), ('changed', True,
                                                                       'PrepareFillData_1 → PrepareFillData', False))
        self.assertEqual([(p.state, p.title) for p in d.nets], [('changed', 'Air pressure low')])

    def test_renamed_and_edited_as_git_revisions(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, {**_prep('PrepareFillData_1'), **_bay4()})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {p: None for p in _prep('PrepareFillData_1')})
            _put(r, _prep(edit=True, keys='x'))
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'two')
            for blocks in (None, {'PrepareFillData_1'}, {'PrepareFillData'}):     # --block: either name
                ds = compare_snapshots(*git_snapshots(r, 'HEAD~1', 'HEAD'), blocks=blocks)
                self.assertEqual([(d.state, d.name, len(d.nets)) for d in ds],
                                 [('changed', 'PrepareFillData_1 → PrepareFillData', 1)])
            self.assertEqual(compare_snapshots(*git_snapshots(r, 'HEAD~1', 'HEAD'), blocks={'Bay4'}), [])

    def test_renamed_only_is_changed(self):
        self.assertEqual(self.states(_prep('PrepareFillData_1'), _prep()),
                         [('changed', 'PrepareFillData_1 → PrepareFillData')])

    def test_without_numbers_by_content(self):
        self.assertEqual(self.states(_prep('PrepareFillData_1', number=None), _prep(edit=True, number=None)),
                         [('changed', 'PrepareFillData_1 → PrepareFillData')])

    def test_other_content_stays_apart(self):
        self.assertEqual(self.states(_prep('PrepareFillData_1', number=None), _bay4('Bay5')),
                         [('deleted', 'PrepareFillData_1'), ('new', 'Bay5')])

    def test_another_kind_with_the_number_stays_apart(self):
        db = {'plc/blocks/FillerDb.s7dcl': '{ S7_BlockNumber := "743" }\nDATA_BLOCK "FillerDb"\n    VAR\n'
                                         '        x : Bool;\n    END_VAR\nBEGIN\nEND_DATA_BLOCK\n'}
        self.assertEqual(self.states(_prep('PrepareFillData_1'), db),
                         [('deleted', 'PrepareFillData_1'), ('new', 'FillerDb')])

    def test_number_before_content(self):
        """Bay5 (number 743, 0.43 alike) is PrepareFillData_1 renamed and rewritten; the copy of the old content
        under another number is a new block."""
        got = self.states(_prep('PrepareFillData_1'),
                          {**_rewritten('Bay5'), **_prep('PrepareFillData', number='746')})
        self.assertEqual(sorted(got), [('changed', 'PrepareFillData_1 → Bay5'), ('new', 'PrepareFillData')])

    def test_same_number_edited_pairs(self):
        """0.43 alike: by the number, not by content alone."""
        self.assertEqual(self.states(_prep('PrepareFillData_1'), _rewritten()),
                         [('changed', 'PrepareFillData_1 → PrepareFillData')])
        self.assertEqual(sorted(self.states(_prep('PrepareFillData_1', number=None), _rewritten(number=None))),
                         [('deleted', 'PrepareFillData_1'), ('new', 'PrepareFillData')])

    def test_same_number_other_content_stays_apart(self):
        """TIA may give a deleted block's number to an unrelated new block: Bay5 0.25 alike."""
        g8 = {p: t.replace('"351"', '"743"') for p, t in _bay4('Bay5').items()}
        self.assertEqual(sorted(self.states(_prep('PrepareFillData_1'), g8)),
                         [('deleted', 'PrepareFillData_1'), ('new', 'Bay5')])
        got = self.states(_prep('PrepareFillData_1'), {**g8, **_prep('PrepareFillData', number='746')})
        self.assertEqual(sorted(got), [('changed', 'PrepareFillData_1 → PrepareFillData'), ('new', 'Bay5')])

    def test_a_project_block_never_pairs_with_a_library_type(self):
        lib = _prep(folder='library/types/Bottling/PrepareFillData/')
        self.assertEqual(sorted(self.states(_prep('PrepareFillData_1'), lib)),
                         [('deleted', 'PrepareFillData_1'), ('new', 'PrepareFillData')])

    def test_compared_without_name_mlc_keys_and_setpoint_false(self):
        from TiaChangeReports.source import content_lines, from_file
        lines = []
        for files in (_prep('PrepareFillData_1'), _prep(keys='x', setpoint=True)):
            with tempfile.TemporaryDirectory() as d:
                _write(d, files)
                s = from_file(os.path.join(d, next(p for p in files if p.endswith('.s7dcl'))))
                lines.append(content_lines(s, parse_block(s)))
        self.assertEqual(lines[0], lines[1])
        self.assertIn('FUNCTION_BLOCK "#"', lines[0])
        self.assertIn('S7_NetworkTitle := "Air pressure low"', lines[0])

    def test_page_and_result_name_both(self):
        b, a = self.folders(_prep('PrepareFillData_1'), _prep(edit=True))
        from TiaChangeReports.compare import compare_snapshots
        html = render(compare_snapshots(b, a), b.label, a.label)
        self.assertIn('<b>PrepareFillData_1 → PrepareFillData [FB743]</b>', html)
        out = os.path.join(os.path.dirname(b.root), 'r.html')
        code, res = JsonResult._main(self, [b.root, a.root, '-o', out, '--json'])
        self.assertEqual((code, [(x['name'], x.get('was'), x['state']) for x in res['blocks']]),
                         (0, [('PrepareFillData', 'PrepareFillData_1', 'changed')]))



# ---------------------------------------------------------------- a program block that is a library type

LIB = 'library/types/Bottling/PrepareFillData/'


def _lib(version, state='IsDefault', **kw):
    """PrepareFillData as a library type (its .libinfo beside it)."""
    return {**_prep(folder=LIB, **kw), LIB + 'PrepareFillData.libinfo': LIBINFO % (version, 'x', state)}


class LibraryInstances(unittest.TestCase):
    """A program block and the library type of its name and kind: one object when both carry the same change,
    compared without name, MLC keys and S7_Setpoint := "False" (as for renamed blocks); both, the program block
    noted, when not."""

    def run_(self, before, after, **kw):
        from TiaChangeReports.compare import compare_snapshots
        b, a = RenamedBlocks.folders(self, before, after)
        return b, a, compare_snapshots(b, a, **kw)

    def tree_names(self, html):
        rail = re.search(r'<ul class="tree">.*?</nav>', html).group(0)
        return [_text(x) for x in re.findall(r'<span class="fn"><span class="nm">[^<]*</span>|<a class="obj.*?</a>',
                                             rail)]

    def test_same_change_shows_the_program_block_only(self):
        b, a, ds = self.run_({**_prep(keys='p', setpoint=True), **_lib('1.0.0')},
                             {**_prep(edit=True, keys='p', setpoint=True), **_lib('1.0.1', 'InWork', edit=True)})
        (d,) = ds
        self.assertEqual((d.path_a, d.state, d.library.path_a, d.library_differs),
                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'changed', LIB + 'PrepareFillData.s7dcl', False))
        html = render(ds, b.label, a.label)
        head = _text(re.search(r'<div class="bh" id="blk-PrepareFillData">.*?</div>', html).group(0))
        self.assertIn('library type PrepareFillData 1.0.0 → 1.0.1 in work', head)
        self.assertNotIn('differs', head)
        self.assertNotIn('Types', self.tree_names(html))
        self.assertIn('library type PrepareFillData 1.0.0 → 1.0.1 in work',
                      re.search(r'<a class="obj [^>]*title="([^"]*)"', html).group(1))
        frag = render(ds + ds, b.label, a.label, fragment=True)        # two rows: the summary with its Version column
        self.assertIn('<th>Version</th>', frag)
        self.assertIn('library type PrepareFillData 1.0.0 → 1.0.1 in work',
                      _text(re.search(r'<tr><td><a href="#blk-PrepareFillData">.*?</tr>', frag).group(0)))

    def test_another_change_shows_both(self):
        """The type released and edited, the instance not updated (only its own edit): both, the block noted."""
        b, a, ds = self.run_({**_prep(), **_lib('1.0.0', 'InWork')},
                             {**_prep(keys='p', setpoint=True, number='746'), **_lib('1.0.0', edit=True)})
        self.assertEqual([(d.path_a, d.state, bool(d.library), d.library_differs) for d in ds],
                         [(LIB + 'PrepareFillData.s7dcl', 'changed', False, False),
                          ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'changed', True, True)])
        html = render(ds, b.label, a.label)
        self.assertIn('differs from library type PrepareFillData 1.0.0 in work → 1.0.0 released', _text(html))
        self.assertEqual(self.tree_names(html), ['Program blocks', 'Bottling', 'PrepareFillData[FB746] differs', 'Types',
                                                 'Bottling', 'PrepareFillData[FB743]'])

    def test_renamed_program_block(self):
        _, _, ds = self.run_({**_prep('PrepareFillData_1'), **_lib('1.0.0')},
                             {**_prep(edit=True), **_lib('1.0.1', 'InWork', edit=True)})
        self.assertEqual([(d.name, d.library.name, d.library_differs) for d in ds],
                         [('PrepareFillData_1 → PrepareFillData', 'PrepareFillData', False)])

    def test_type_without_instance_or_of_another_kind(self):
        _, _, ds = self.run_(_lib('1.0.0'), _lib('1.0.1', 'InWork', edit=True))
        self.assertEqual([(d.path_a, d.library) for d in ds], [(LIB + 'PrepareFillData.s7dcl', None)])
        udt = UDT_D.replace('"D"', '"PrepareFillData"')
        _, _, ds = self.run_({**_lib('1.0.0'), 'plc/types/PrepareFillData.s7dcl': udt},
                             {**_lib('1.0.1', 'InWork', edit=True),
                              'plc/types/PrepareFillData.s7dcl': udt.replace('x : Bool', 'y : Bool')})
        self.assertEqual(sorted((d.path_a, d.library) for d in ds),
                         [(LIB + 'PrepareFillData.s7dcl', None), ('plc/types/PrepareFillData.s7dcl', None)])

    def test_version_only_with_all(self):
        """--all: the instance unchanged, the type released: the program block, version only; without --all the
        type alone, as before."""
        _, _, ds = self.run_({**_prep(), **_lib('1.0.1', 'InWork')}, {**_prep(), **_lib('1.0.1')}, all_=True)
        d = next(d for d in ds if d.block.name == 'PrepareFillData')
        self.assertEqual((d.path_a, d.state, d.library_differs),
                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'version', False))
        self.assertFalse(any(x.path_a.startswith('library/') for x in ds))
        _, _, ds = self.run_({**_prep(), **_lib('1.0.1', 'InWork')}, {**_prep(), **_lib('1.0.1')})
        self.assertEqual([(d.path_a, d.state, d.library) for d in ds],
                         [(LIB + 'PrepareFillData.s7dcl', 'version', None)])

    def test_git_revisions_text_and_json(self):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, {**_prep(), **_lib('1.0.0'), **_bay4()})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, {**_prep(edit=True), **_lib('1.0.1', 'InWork', edit=True)})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'two')
            out = os.path.join(r, 'r.html')
            code, res = JsonResult._main(self, ['--git', r, 'HEAD~1', 'HEAD', '-o', out, '--json'])
            self.assertEqual((code, [(x['name'], x['state'], x.get('libraryType')) for x in res['blocks']]),
                             (0, [('PrepareFillData', 'changed', {
                                 'name': 'PrepareFillData', 'path': LIB + 'PrepareFillData.s7dcl',
                                 'before': {'number': '1.0.0', 'inWork': False},
                                 'after': {'number': '1.0.1', 'inWork': True}, 'differs': False})]))
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                main(['--git', r, 'HEAD~1', 'HEAD', '-o', out])
            self.assertIn('PrepareFillData  (library type PrepareFillData)', text.getvalue())

    def test_keyword_lines_tell_changes_apart(self):
        """content_lines(syntax=True) keeps END_VAR and the like, which the similarity leaves out."""
        from TiaChangeReports.source import content_lines
        s = src()
        blk = parse_block(s)
        self.assertNotIn('END_VAR', content_lines(s, blk))
        self.assertIn('END_VAR', [l.strip() for l in content_lines(s, blk, syntax=True)])


# ---------------------------------------------------------------- files that are no block export

# TiaBridge's export of a global library type: its version metadata only, the data type further down (Openness limit)
LIB_META = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V20" />
  <SW.Types.PlcTypeLibraryTypeVersion ID="0">
    <AttributeList><VersionNumber>0.0.1</VersionNumber></AttributeList>
    <ObjectList>
      <SW.Types.PlcStruct ID="3" CompositionName="ContentObject">
        <AttributeList><Name>typePosition</Name></AttributeList>
      </SW.Types.PlcStruct>
    </ObjectList>
  </SW.Types.PlcTypeLibraryTypeVersion>
</Document>
'''
META = 'library/global/From_D/types/UDT/typePosition_V0.0.1.xml'
NO_BLOCK = 'no block export: SW.Types.PlcTypeLibraryTypeVersion holding a block'


class NoBlockExports(unittest.TestCase):
    """A folder or revision input skips a file that is no block export but holds one (a global library type's version
    metadata), and a block that does not parse, and names each once; the rest of the report is written."""

    def _repo(self, extra=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = tmp.name
        _git(r, 'init', '-q')
        _git(r, 'config', 'core.autocrlf', 'false')
        _put(r, {'plc/A.s7dcl': SRC, META: LIB_META, 'plc/tags/T.xml': '<Document><SW.Tags.PlcTagTable ID="0" />'
                 '</Document>'})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'one')
        _put(r, {'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                 META: LIB_META.replace('0.0.1<', '0.0.2<'), 'plc/tags/T.xml': '<Document><SW.Tags.PlcTagTable '
                 'ID="1" /></Document>', **(extra or {})})
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'two')
        return r

    def test_simaticml_block_is_the_first_element(self):
        from TiaChangeReports.simaticml import is_block
        self.assertTrue(is_block(_fixture()))
        self.assertFalse(is_block(LIB_META))
        self.assertFalse(is_block('<Document><SW.Tags.PlcTagTable ID="0" /></Document>'))

    def test_folder(self):
        r = self._repo()
        snap = FolderSnapshot(r)
        self.assertEqual(snap.paths(), ['plc/A.s7dcl'])
        self.assertEqual(snap.skipped, [(META, NO_BLOCK)])              # not the tag table: no block in it

    def test_revisions_and_working_tree(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        r = self._repo()
        before, after = git_snapshots(r, 'HEAD~1', 'HEAD')
        self.assertEqual(after.paths(), ['plc/A.s7dcl'])
        self.assertEqual([d.block.name for d in compare_snapshots(before, after)], ['A'])
        self.assertEqual((before.skipped, after.skipped), ([(META, NO_BLOCK)], [(META, NO_BLOCK)]))
        _put(r, {META: LIB_META.replace('0.0.1<', '0.0.3<')})
        wt = git_snapshots(r, 'HEAD')[1]
        self.assertEqual((wt.paths(), wt.skipped), ([], [(META, NO_BLOCK)]))

    def test_a_block_that_does_not_parse_is_skipped(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        r = self._repo({'plc/B.xml': '<Document><SW.Blocks.FB ID="0"><AttributeList>'})
        before, after = git_snapshots(r, 'HEAD~1', 'HEAD')
        self.assertEqual([d.block.name for d in compare_snapshots(before, after)], ['A'])
        self.assertEqual([p for p, _ in after.skipped], [META, 'plc/B.xml'])

    def test_cli_names_each_skipped_file_once(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        r = self._repo()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--git', r, 'HEAD~1', 'HEAD', '-o', os.path.join(r, 'r.html'), '--json'])
        self.assertEqual(code, 0)
        res = json.loads(out.getvalue())
        self.assertEqual(([b['name'] for b in res['blocks']], res['skipped']),
                         (['A'], [{'path': META, 'reason': NO_BLOCK}]))
        self.assertEqual(err.getvalue().splitlines(), ['skipped %s: %s' % (META, NO_BLOCK)])
        self.assertTrue(os.path.isfile(os.path.join(r, 'r.html')))


class OutputPaths(unittest.TestCase):
    """-o or --png that cannot be written (a folder, a read-only file) is a usage error named in one line, before the
    inputs are read."""

    def _main(self, args):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(args)
        return code, err.getvalue().splitlines()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.missing = [os.path.join(self.d, 'no', 'v1'), os.path.join(self.d, 'no', 'v2')]   # read after the check

    def test_folder(self):
        for opt in ('-o', '--png'):
            out = os.path.join(self.d, 'out')
            os.makedirs(out, exist_ok=True)
            args = self.missing + (['-o', out] if opt == '-o' else ['-o', os.path.join(self.d, 'p.html'), '--png', out])
            code, err = self._main(args)
            self.assertEqual((code, len(err)), (2, 1), err)
            self.assertIn(opt, err[0])
            self.assertIn(out, err[0])

    def test_read_only_file(self):
        import stat
        out = os.path.join(self.d, 'r.html')
        _put(self.d, {'r.html': 'old'})
        os.chmod(out, stat.S_IREAD)
        self.addCleanup(os.chmod, out, stat.S_IWRITE | stat.S_IREAD)
        code, err = self._main(self.missing + ['-o', out])
        self.assertEqual((code, len(err)), (2, 1), err)
        self.assertIn(out, err[0])

    def test_new_file_in_a_new_folder_is_not_left_behind(self):
        out = os.path.join(self.d, 'new', 'r.html')
        code, err = self._main(self.missing + ['-o', out])
        self.assertEqual(code, 2)
        self.assertNotIn(out, err[0])                                  # the input's error, not the output's
        self.assertFalse(os.path.exists(out))
        code, _ = self._main([os.path.join(V1, 'plc'), os.path.join(V2, 'plc'), '-o', out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out))


class UnmatchedFilters(unittest.TestCase):
    """A --block name or --network title found nowhere in the inputs (changed or not) is named on stderr and in the
    JSON (`unmatched`); exit 0, the page still written."""

    def _main(self, *opts):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            page = os.path.join(d, 'r.html')
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main([V1, V2, '-o', page, '--json'] + list(opts))
            self.assertTrue(os.path.isfile(page))
        return code, json.loads(out.getvalue()), err.getvalue().splitlines()

    def test_block_found_nowhere(self):
        code, res, err = self._main('--block', 'NoSuchBlock', '--block', 'Filler')
        self.assertEqual(code, 0)
        self.assertEqual(err, ['--block NoSuchBlock: no block of that name'])
        self.assertEqual(res['unmatched'], {'blocks': ['NoSuchBlock'], 'networks': []})
        self.assertEqual([b['name'] for b in res['blocks']], ['Filler'])

    def test_network_found_nowhere(self):
        code, res, err = self._main('--network', 'No such network', '--network', 'Lower the filling head')
        self.assertEqual(code, 0)
        self.assertEqual(err, ['--network "No such network": no network of that title'])
        self.assertEqual(res['unmatched'], {'blocks': [], 'networks': ['No such network']})

    def test_network_of_another_block(self):
        code, res, err = self._main('--block', 'Filler', '--network', 'Filler[4] / pick the bay')    # a Bay4 title
        self.assertEqual(err, ['--network "Filler[4] / pick the bay": no network of that title in the given blocks'])
        self.assertEqual(res['unmatched'], {'blocks': [], 'networks': ['Filler[4] / pick the bay']})

    def test_unchanged_names_are_no_typo(self):
        code, res, err = self._main('--block', 'FillerCmd_UDT', '--block', 'Filler', '--network', 'Ready to fill', '--network',
                                    'Close the coarse valve at the high probe')                  # the old title of a renamed one
        self.assertEqual((code, err), (0, []))
        self.assertNotIn('unmatched', res)


class NetworkFilter(unittest.TestCase):
    """--network keeps only the blocks holding a named network (the interface changes of the others left out); a
    named network or block shows also when unchanged, without --all; an unchanged named block with all its networks."""

    def _main(self, *opts, before=V1, after=V2):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            page = os.path.join(d, 'r.html')
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([before, after, '-o', page, '--json'] + list(opts)), 0)
            with open(page, encoding='utf-8') as f:
                html = f.read()
        return [(b['name'], b['state'], [(n['state'], n['title']) for n in b['networks']])
                for b in json.loads(out.getvalue())['blocks']], html

    def _two(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _put(tmp.name, files)
        return {'before': os.path.join(tmp.name, 'v1'), 'after': os.path.join(tmp.name, 'v2')}

    def test_only_blocks_holding_the_network(self):
        got, html = self._main('--network', 'Close the coarse valve at the high probe')    # HatchLogic: no section left
        self.assertEqual(got, [('Filler', 'changed', [('changed', 'High probe wet before the fill weight')])])
        self.assertNotIn('blk-HatchLogic', html)

    def test_unchanged_network(self):
        got, _ = self._main('--network', 'Ready to fill')
        self.assertEqual(got, [('Filler', 'changed', [('same', 'Ready to fill')])])

    def test_unchanged_block(self):
        got, html = self._main('--block', 'FillerCmd_UDT')
        self.assertEqual(got, [('FillerCmd_UDT', 'same', [])])
        self.assertIn('id="blk-FillerCmd_UDT"', html)

    def test_unchanged_block_with_its_networks(self):
        u = SRC.replace('"T"', '"U"')
        two = self._two({'v1/T.s7dcl': SRC, 'v1/T.s7res': RES, 'v2/T.s7dcl': SRC, 'v2/T.s7res': RES,
                         'v1/U.s7dcl': u, 'v1/U.s7res': RES, 'v2/U.s7res': RES,
                         'v2/U.s7dcl': u.replace('I_Contact( #b )', 'I_Contact( #a )')})
        self.assertEqual(self._main('--block', 'T', **two)[0], [('T', 'same', [('same', 'Seal-in'), ('same', '')])])
        self.assertEqual(self._main('--block', 'U', **two)[0], [('U', 'changed', [('changed', 'Seal-in')])])
        self.assertEqual(self._main('--network', 'Seal-in', **two)[0],
                         [('T', 'same', [('same', 'Seal-in')]), ('U', 'changed', [('changed', 'Seal-in')])])

    def test_network_of_a_new_block_is_drawn(self):
        two = self._two({'v1/U.s7dcl': SRC.replace('"T"', '"U"'), 'v1/U.s7res': RES,
                         'v2/U.s7dcl': SRC.replace('"T"', '"U"'), 'v2/U.s7res': RES, 'v2/T.s7dcl': SRC, 'v2/T.s7res': RES})
        got, html = self._main('--network', 'Seal-in', **two)
        self.assertEqual(got, [('U', 'same', [('same', 'Seal-in')]), ('T', 'new', [('new', 'Seal-in')])])
        self.assertEqual(html.count('<div class="nwt">'), 2)


class DeclaredNames(unittest.TestCase):
    """A library type's file is named after the type; its block may be declared under another name (PrepareFillData.s7dcl
    declaring "PrepareFillData_1"). The list, --json (name, was) and --block use the
    declared names, as the page header does."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lib = _prep(folder=LIB)
        old = {p: t.replace('FUNCTION_BLOCK "PrepareFillData"', 'FUNCTION_BLOCK "PrepareFillData_1"')
               for p, t in lib.items()}
        self.b, self.a = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(self.b, {**old, **_prep('PrepareFillData_1'), **_prep(edit=True)})   # 2 program blocks, deleted after
        _write(self.a, lib)

    def _main(self, *opts, json_=True):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        out, err = io.StringIO(), io.StringIO()
        page = os.path.join(os.path.dirname(self.b), 'r.html')
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([self.b, self.a, '-o', page] + (['--json'] if json_ else []) + list(opts))
        self.assertEqual((code, err.getvalue()), (0, ''))
        return json.loads(out.getvalue()) if json_ else out.getvalue().splitlines()

    def test_json_names_and_was(self):
        got = {(b['name'], b.get('was'), b['state']): b.get('libraryType') for b in self._main()['blocks']}
        self.assertEqual(set(got), {('PrepareFillData', None, 'deleted'), ('PrepareFillData', 'PrepareFillData_1',
                                    'changed'), ('PrepareFillData_1', None, 'deleted')})
        self.assertIsNone(got['PrepareFillData', None, 'deleted'])  # a deleted program block: no link to the type

    def test_listing(self):
        heads = [l for l in self._main(json_=False) if l[:1] != ' ' and not l.endswith('r.html')]
        self.assertIn('changed  FB          PrepareFillData  (was "PrepareFillData_1")', heads)
        self.assertIn('deleted  FB          PrepareFillData  (interface)', heads)

    def test_block_by_declared_name(self):
        """The type is found by its old declared name as well as by its file name; the program block of that name
        too."""
        got = [(b['name'], b.get('was'), b['state']) for b in self._main('--block', 'PrepareFillData_1')['blocks']]
        self.assertEqual(sorted(got), [('PrepareFillData', 'PrepareFillData_1', 'changed'),
                                       ('PrepareFillData_1', None, 'deleted')])
        res = self._main('--block', 'PrepareFillData')
        self.assertNotIn('unmatched', res)
        self.assertNotIn(('PrepareFillData_1', None, 'deleted'),
                         [(b['name'], b.get('was'), b['state']) for b in res['blocks']])

    def test_block_by_declared_name_in_git_revisions(self):
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import git_snapshots
        with tempfile.TemporaryDirectory() as r:
            _git(r, 'init', '-q')
            _put(r, {p: t.replace('"PrepareFillData"', '"PrepareFillData_1"') for p, t in _prep(folder=LIB).items()})
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'one')
            _put(r, _prep(folder=LIB, edit=True))
            _git(r, 'add', '-A')
            _git(r, 'commit', '-q', '-m', 'two')
            found = {'blocks': set(), 'networks': set()}
            ds = compare_snapshots(*git_snapshots(r, 'HEAD~1', 'HEAD'), blocks={'PrepareFillData_1', 'X'}, found=found)
            self.assertEqual([(d.state, d.name) for d in ds], [('changed', 'PrepareFillData_1 → PrepareFillData')])
            self.assertEqual(found['blocks'], {'PrepareFillData_1'})


class NoBlockFiles(unittest.TestCase):
    """A file named on the command line that is no block export (another file, a .s7res, an empty or broken .s7dcl,
    a tag table or a library type's version metadata) is a usage error named in one line, on either side: exit 2, no
    page. In a folder, a broken .s7dcl is skipped as unreadable."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.hatch = os.path.join(V2, 'plc', 'blocks', 'Safety', 'HatchLogic.s7dcl')

    def _main(self, before, after):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        out, err = io.StringIO(), io.StringIO()
        page = os.path.join(self.d, 'r.html')
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([before, after, '-o', page])
        return code, err.getvalue().splitlines(), os.path.exists(page)

    def test_files_that_are_no_block(self):
        _put(self.d, {'notes.txt': 'just text\n', 'Empty.s7dcl': '', 'Broken.s7dcl': 'FUNCTION_BLOCK "Broken"\n'
                      'this is { not s7dcl\n', 'T.xml': '<Document><SW.Tags.PlcTagTable ID="0" /></Document>',
                      'typePosition_V0.0.1.xml': LIB_META})
        cases = {'notes.txt': 'not a block export', 'Empty.s7dcl': 'not a SIMATIC SD block export: empty',
                 'Broken.s7dcl': 'not a SIMATIC SD block export: no END_FUNCTION_BLOCK',
                 'T.xml': 'not a SimaticML block export', 'typePosition_V0.0.1.xml': NO_BLOCK,
                 os.path.join(V2, 'plc', 'blocks', 'Safety', 'HatchDb.s7res'): 'not a block export'}
        for name, why in cases.items():
            path = os.path.join(self.d, name)
            for args in ((path, self.hatch), (self.hatch, path)):
                code, err, written = self._main(*args)
                self.assertEqual((code, written), (2, False), (name, err))
                self.assertEqual(len(err), 1, err)
                self.assertTrue(err[0].startswith('%s: %s' % (path, why)), err[0])

    def test_a_locked_simaticml_export_says_why(self):
        _put(self.d, {'M.xml': _fixture()})
        path = os.path.join(self.d, 'M.xml')
        code, err, written = _locked(path, lambda: self._main(path, self.hatch))
        self.assertEqual((code, written, len(err)), (2, False, 1), err)
        self.assertTrue(err[0].startswith('%s: unreadable: ' % path), err[0])

    def test_two_empty_files(self):
        _put(self.d, {'a/Empty.s7dcl': '', 'b/Empty.s7dcl': ''})
        code, err, written = self._main(os.path.join(self.d, 'a', 'Empty.s7dcl'), os.path.join(self.d, 'b', 'Empty.s7dcl'))
        self.assertEqual((code, written, len(err)), (2, False, 1))

    def test_broken_s7dcl_does_not_parse(self):
        with self.assertRaisesRegex(ValueError, r'^X: not a SIMATIC SD block export: no END_FUNCTION_BLOCK$'):
            parse_block(src('FUNCTION_BLOCK "X"\nthis is { not s7dcl\n', None, 'X'))

    def test_folder_skips_a_broken_s7dcl(self):
        from TiaChangeReports.compare import compare_snapshots
        _put(self.d, {'a/plc/T.s7dcl': SRC, 'b/plc/T.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                      'b/plc/Broken.s7dcl': 'FUNCTION_BLOCK "Broken"\nthis is { not s7dcl\n'})
        before, after = FolderSnapshot(os.path.join(self.d, 'a')), FolderSnapshot(os.path.join(self.d, 'b'))
        self.assertEqual([d.block.name for d in compare_snapshots(before, after)], ['T'])
        self.assertEqual(after.skipped, [('plc/Broken.s7dcl', 'unreadable: not a SIMATIC SD block export: '
                                                              'no END_FUNCTION_BLOCK')])

    def test_folder_names_a_locked_xml_and_does_not_read_it_as_deleted(self):
        from TiaChangeReports import plctags
        from TiaChangeReports.compare import compare_snapshots
        from TiaChangeReports.source import skipped
        files = {'plc/blocks/Main.xml': _fixture(), 'plc/tags/T.xml': '<Document><SW.Tags.PlcTagTable ID="0" /></Document>'}
        _put(self.d, {side + '/' + p: text for side in 'ab' for p, text in files.items()})
        for rel in files:
            before, after = FolderSnapshot(os.path.join(self.d, 'a')), FolderSnapshot(os.path.join(self.d, 'b'))

            def run():
                return (compare_snapshots(before, after),
                        [(bool(t.before), bool(t.after)) for t in plctags.compare(before, after)],
                        skipped((before, after)))
            diffs, tables, named = _locked(os.path.join(self.d, 'b', rel), run)

            self.assertEqual(diffs, [], rel)
            self.assertEqual(tables, [] if rel.startswith('plc/tags/') else [(True, True)], rel)
            self.assertEqual([p for p, _ in named], [rel])
            self.assertIn('unreadable', named[0][1])


class FileAgainstFolder(unittest.TestCase):
    """A file paired with a folder, either way round and in any pair, is a usage error named in one line: exit 2, no
    page."""

    def test_refused(self):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        page = os.path.join(tmp.name, 'r.html')
        hatch = os.path.join(V1, 'plc', 'blocks', 'Safety', 'HatchLogic.s7dcl')
        for paths in ([hatch, V2], [V1, hatch], [V1, V2, hatch, V2]):
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = main(paths + ['-o', page])
            err = err.getvalue().splitlines()
            self.assertEqual((code, os.path.exists(page), len(err)), (2, False, 1), (paths, err))
            self.assertIn('a file and a folder: give two files or two folders', err[0])
            self.assertIn(hatch, err[0])


# ---------------------------------------------------------------- start values of a DB of a type

TYPED_DB_FILES = {
    'plc/SubFb.s7dcl': 'FUNCTION_BLOCK "SubFb"\n    VAR_INPUT\n        inValue : Int;\n        inOn : Bool;\n'
                       '    END_VAR\nEND_FUNCTION_BLOCK\n',
    'plc/types/Data_UDT.s7dcl': 'TYPE "Data_UDT"\n    STRUCT\n        "limit" : Int := 10;\n        x : Bool;\n'
                                '    END_STRUCT;\nEND_TYPE\n',
    'plc/SubFb_DB.s7dcl': '{\n    S7_Optimized := "TRUE"\n}\nDATA_BLOCK SubFb_DB : SubFb\nEND_DATA_BLOCK\n',
    'plc/UdtDb.s7dcl': '{\n    S7_Optimized := "TRUE"\n}\nDATA_BLOCK UdtDb : Data_UDT\nEND_DATA_BLOCK\n',
}


class TypedDbStartValues(unittest.TestCase):
    """An instance DB and a DB of a UDT hold their start values as lines without a VAR section (seen between two
    commits of repo A_e2e): a start value set, changed or cleared is a changed member, the DB a changed block."""

    def _diffs(self, before, after):
        from TiaChangeReports.compare import compare_snapshots
        with tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as a:
            _write(b, dict(TYPED_DB_FILES, **before))
            _write(a, dict(TYPED_DB_FILES, **after))
            return {d.name: d for d in compare_snapshots(FolderSnapshot(b), FolderSnapshot(a), all_=True)}

    def _rows(self, d):
        return {'.'.join(r.path): r for r in iface.block_rows(d.before, d.after) if r.state != 'same'}

    def test_parsed_as_start_values(self):
        b = parse_block(src('DATA_BLOCK UdtDb : Data_UDT\n    "limit" := 3;\n    x := TRUE;\nEND_DATA_BLOCK\n', '',
                            'UdtDb'))
        self.assertEqual(b.interface.start, {'"limit"': ('3', None), 'x': ('TRUE', None)})
        self.assertEqual(b.networks, [])

    def test_start_value_set(self):
        ds = self._diffs({}, {
            'plc/SubFb_DB.s7dcl': TYPED_DB_FILES['plc/SubFb_DB.s7dcl'].replace('\nEND', '\n    inValue := 5;\nEND'),
            'plc/UdtDb.s7dcl': TYPED_DB_FILES['plc/UdtDb.s7dcl'].replace('\nEND', '\n    "limit" := 3;\nEND')})
        self.assertEqual((ds['SubFb_DB'].state, ds['UdtDb'].state), ('changed', 'changed'))
        r = self._rows(ds['SubFb_DB'])
        self.assertEqual(list(r), ['inValue'])
        self.assertEqual((r['inValue'].state, r['inValue'].changes, r['inValue'].b.value, r['inValue'].a.value),
                         ('changed', {'value'}, None, '5'))
        self.assertEqual((r['inValue'].b.section, r['inValue'].a.section), ('INPUT', 'INPUT'))   # as in the FB
        secs = [c[0] for cls, c in _trs(iface.html(ds['SubFb_DB'].before, ds['SubFb_DB'].after)) if cls == 'sec']
        self.assertEqual(secs, ['▼ Input'])
        r = self._rows(ds['UdtDb'])
        self.assertEqual(list(r), ['limit'])
        self.assertEqual((r['limit'].changes, r['limit'].b.dflt, r['limit'].a.value), ({'value'}, '10', '3'))
        self.assertIn('<span class="tx ins">3</span>', iface.html(ds['UdtDb'].before, ds['UdtDb'].after))

    def test_start_value_changed_and_cleared(self):
        db = TYPED_DB_FILES['plc/UdtDb.s7dcl']
        ds = self._diffs({'plc/UdtDb.s7dcl': db.replace('\nEND', '\n    "limit" := 3;\n    x := TRUE;\nEND')},
                         {'plc/UdtDb.s7dcl': db.replace('\nEND', '\n    "limit" := 4;\nEND')})
        r = self._rows(ds['UdtDb'])
        self.assertEqual({k: (v.state, v.b.value, v.a.value) for k, v in r.items()},
                         {'limit': ('changed', '3', '4'), 'x': ('changed', 'TRUE', None)})

    def test_unchanged_stays_same(self):
        db = TYPED_DB_FILES['plc/SubFb_DB.s7dcl'].replace('\nEND', '\n    inValue := 5;\nEND')
        ds = self._diffs({'plc/SubFb_DB.s7dcl': db}, {'plc/SubFb_DB.s7dcl': db})
        self.assertEqual(ds['SubFb_DB'].state, 'same')

    def test_kind_label(self):
        """A DB of a UDT is a global DB (Openness: GlobalDB), labelled as one; an instance DB of an FB as before."""
        ds = self._diffs({}, {})
        self.assertEqual((ds['SubFb_DB'].kind, ds['UdtDb'].kind), ('Instance DB', 'DB'))


# ---------------------------------------------------------------- a moved network is one pair, tagged

MOVE = ('SCL', 'Network to move', ['#m := #a;'])
STAY = [('SCL', 'A', FAULTS), ('SCL', 'B', TIMERS), ('SCL', 'C', REWRITTEN)]


def _moves(b, a):
    return [(p.state, p.moved, p.before.index if p.before else None, p.after.index if p.after else None, p.title)
            for p in pair_networks(parse_block(b), parse_block(a)) if p.state != 'same' or p.moved]


class MovedNetworks(unittest.TestCase):
    """A network of the same title deleted at one place and new at another is one pair, moved, at its new place;
    shown also unchanged and in a block with other changes. Moved: the networks out of the longest common
    order (both of a swap); an untitled or renamed network moved pairs when it has one candidate of the same logic."""

    def test_moved_unchanged_is_one_pair(self):
        got = _moves(fb(MOVE, *STAY), fb(*STAY, MOVE))
        self.assertEqual(got, [('same', True, 2, 5, 'Network to move')])

    def test_moved_and_changed(self):
        edited = ('SCL', 'Network to move', ['#m := #b;'])
        self.assertEqual(_moves(fb(MOVE, *STAY), fb(*STAY, edited)), [('changed', True, 2, 5, 'Network to move')])

    def test_numbers_shifted_by_a_new_network_are_no_move(self):
        got = _moves(fb(MOVE, *STAY), fb(('SCL', 'Set x', ['#x := #a;']), MOVE, *STAY))
        self.assertEqual(got, [('new', False, None, 2, 'Set x')])

    def test_on_the_page_also_with_other_changes(self):
        d = compare_blocks(fb(MOVE, *STAY), fb(*STAY, MOVE))
        self.assertEqual((d.state, [(p.title, p.moved) for p in d.nets]), ('changed', [('Network to move', True)]))
        b = fb(MOVE, *STAY)
        a = fb(('SCL', 'A', FAULTS_EDITED), *STAY[1:], MOVE)
        d = compare_blocks(b, a)
        self.assertEqual([(p.state, p.title, p.moved) for p in d.nets],
                         [('changed', 'A', False), ('same', 'Network to move', True)])
        self.assertEqual([(p.title, p.moved) for p in compare_blocks(b, a, all_=True).nets if p.moved],
                         [('Network to move', True)])
        self.assertEqual([p.moved for p in compare_blocks(b, a, networks={'Network to move'}).nets], [True])

    def test_swap_moves_both(self):
        got = _moves(fb(*STAY), fb(STAY[1], STAY[0], STAY[2]))
        self.assertEqual(got, [('same', True, 3, 2, 'B'), ('same', True, 2, 3, 'A')])
        self.assertEqual(compare_blocks(fb(*STAY), fb(STAY[1], STAY[0], STAY[2])).state, 'changed')

    def test_networks_jumped_over_are_no_move(self):
        got = _moves(fb(*STAY, MOVE), fb(MOVE, *STAY))
        self.assertEqual(got, [('same', True, 5, 2, 'Network to move')])

    def test_untitled_moved_pairs_by_content(self):
        net = ('SCL', '', ['#m := #a;'])
        self.assertEqual(_moves(fb(net, *STAY), fb(*STAY, net)), [('same', True, 2, 5, '')])

    def test_renamed_and_moved_pairs_by_content(self):
        (p,) = [p for p in pair_networks(parse_block(fb(MOVE, *STAY)),
                                         parse_block(fb(*STAY, ('SCL', 'Moved net', MOVE[2])))) if p.state != 'same']
        self.assertEqual((p.state, p.moved, p.renamed, p.before.index, p.after.index), ('changed', True, True, 2, 5))

    UNTITLED = [('SCL', '', ['#m := #a;']), ('SCL', '', ['#n := #b;']), ('SCL', '', ['#o := #c;'])]

    def test_an_untitled_network_added_or_removed_shifts_no_other(self):
        """Untitled networks align also by their content, not each onto its neighbour."""
        new = ('SCL', '', ['#x := #d;'])
        self.assertEqual(_moves(fb(*self.UNTITLED), fb(new, *self.UNTITLED)), [('new', False, None, 2, '')])
        self.assertEqual(_moves(fb(*self.UNTITLED), fb(*self.UNTITLED[1:])), [('deleted', False, 2, None, '')])

    def test_an_untitled_network_rewritten_in_place_is_still_changed(self):
        rewritten = ('SCL', '', ['#q := #r AND #s;'])
        self.assertEqual(_moves(fb(*self.UNTITLED), fb(rewritten, *self.UNTITLED[1:])), [('changed', False, 2, 2, '')])

    RUNG = 'RUNG wire#powerrail\n            %sContact( #%s )\n            Coil( #s.x )\n        END_RUNG'

    def lad(self, operand, pragma=''):
        return 'LAD', '', self.RUNG % (pragma, operand)

    def test_an_untitled_network_edited_among_alike_ones_is_changed_in_place(self):
        """Alike copies around it do not split it into a new and a deleted network."""
        a, b = self.lad('a'), self.lad('b')
        self.assertEqual(_moves(fb(a, a, a), fb(a, b, a)), [('changed', False, 3, 3, '')])
        self.assertEqual(_moves(fb(a, a, a), fb(b, a, a)), [('changed', False, 2, 2, '')])
        s = ('SCL', '', ['#m := #a;'])
        self.assertEqual(_moves(fb(s, s, s), fb(s, ('SCL', '', ['#n := #b;']), s)), [('changed', False, 3, 3, '')])

    def test_an_untitled_network_moved_beside_one_edited(self):
        a, b, c, d = (('SCL', '', [x]) for x in ('#m := #a;', '#n := #b;', '#o := #c;', '#p := #d;'))
        got = _moves(fb(a, b, c, d), fb(b, ('SCL', '', ['#o := #c OR #e;']), d, a))
        self.assertEqual(got, [('changed', False, 4, 3, ''), ('same', True, 2, 5, '')])

    def test_a_pragma_beside_an_operand_of_an_untitled_network_among_alike_ones(self):
        z = '{ Zz := "%s" }\n            '
        a = self.lad('a')
        for before, after in (((a, self.lad('a', z % 1), a), (a, self.lad('b', z % 2), a)),
                              ((a, a, a), (a, self.lad('b', z % 1), a))):
            d = compare_blocks(fb(*before), fb(*after))
            self.assertEqual([(p.state, p.after.index, p.not_shown) for p in d.nets], [('changed', 3, True)])

    def test_an_edit_in_place_is_not_read_as_another_network_changed(self):
        """A network of the same lines in another order, or the same elements wired otherwise, is changed as much as
        one with a line or an operand edited; the edit stays in place, the other is deleted."""
        l1, l2, l3 = '#m := #a;', '#n := #b;', '#o := #c;'
        ser = 'RUNG wire#powerrail\n            Contact( #%s )\n            Contact( #%s )\n            Coil( #s.x )\n        END_RUNG'
        par = ('RUNG wire#powerrail\n            Contact( #%s )\n            Coil( #s.x )\n        END_RUNG\n'
               '        RUNG wire#powerrail\n            Contact( #%s )\n            Coil( #s.x )\n        END_RUNG')
        for before, after in ((fb(('SCL', '', [l1, l2, '#o := #x;']), ('SCL', '', [l3, l2, l1])), fb(('SCL', '', [l1, l2, l3]))),
                              (fb(('SCL', '', [l2, '#m := #x;']), ('SCL', '', [l1, l2])), fb(('SCL', '', [l2, l1]))),
                              (fb(('LAD', '', ser % ('a', 'c')), ('LAD', '', par % ('a', 'b'))), fb(('LAD', '', ser % ('a', 'b'))))):
            self.assertEqual(_moves(before, after), [('changed', False, 2, 2, ''), ('deleted', False, 3, None, '')])

    def test_at_a_tie_the_earlier_untitled_ones_pair(self):
        """Where no pairing lists fewer networks, the one by title stands."""
        s1, s2 = ('SCL', '', ['#m := #a;']), ('SCL', '', ['#n := #b;'])
        a, b = self.lad('a'), self.lad('b')
        pragma = self.lad('a', '{ Zz := "1" }\n            ')
        for before, after, want in ((fb(s1, s1), fb(s2), [('changed', False, 2, 2, ''), ('deleted', False, 3, None, '')]),
                                    (fb(s1, s1), fb(s1), [('deleted', False, 3, None, '')]),
                                    (fb(a, a), fb(a), [('deleted', False, 3, None, '')]),
                                    (fb(pragma, a), fb(b), [('changed', False, 2, 2, ''), ('deleted', False, 3, None, '')])):
            self.assertEqual(_moves(before, after), want)

    def test_moved_and_edited_untitled_stays_removed_and_new(self):
        got = _moves(fb(('SCL', '', ['#m := #a;', '#n := #b;']), *STAY), fb(*STAY, ('SCL', '', ['#m := #a;', '#n := #c;'])))
        self.assertEqual(got, [('deleted', False, 2, None, ''), ('new', False, None, 5, '')])

    def test_two_candidates_stay_removed_and_new(self):
        net = ('SCL', '', ['#m := #a;'])
        got = _moves(fb(net, *STAY), fb(*STAY, ('SCL', 'X', net[2]), ('SCL', 'Y', net[2])))
        self.assertEqual(got, [('deleted', False, 2, None, ''), ('new', False, None, 5, 'X'), ('new', False, None, 6, 'Y')])

    def test_tag_moved_on_both_sides(self):
        """Both halves say moved, the before half where it went, the after half where it came from; the
        state tag (changed) on the after half as for every network."""
        from TiaChangeReports.compare import NetPair
        from TiaChangeReports.page import _title_bar
        before, after = _net(11, 'Network to move', '', '#m := #a;'), _net(13, 'Network to move', '', '#m := #a;')
        tags = r'<span class="st (\w+)">([\w ]+)</span>'

        def halves(bar):
            return [re.findall(tags, h) for h in bar.split('<span class="side">')[1:]]
        bar = _title_bar(NetPair(before, after, moved=True))
        self.assertEqual(halves(bar), [[('moved', 'moved to 13')], [('moved', 'moved from 11')]])
        self.assertIn('Network 11:</span><span class="ti">Network to move</span><span class="st moved">', bar)
        self.assertIn('Network 13:</span><span class="ti">Network to move</span><span class="st moved">', bar)
        changed = _title_bar(NetPair(before, _net(13, 'Network to move', '', '#m := #b;'), moved=True))
        self.assertEqual(halves(changed), [[('moved', 'moved to 13')], [('changed', 'changed'), ('moved', 'moved from 11')]])
        self.assertNotIn('removed', bar + changed)

    def test_page_lookup_and_summary(self):
        from TiaChangeReports.page import summary_html
        d = compare_blocks(fb(MOVE, *STAY), fb(*STAY, MOVE))
        html = render([d], 'b', 'a')
        self.assertIn('.ldiff .nwt .st.moved{background:var(--mov-bg)}', html)
        self.assertIn('.ldiff .lch .st.moved{background:var(--mov-bg)}', html)
        self.assertIn("g=s[no[1]?1:0].querySelectorAll('.st')", html)            # the lookup: the tags of one half (99)
        self.assertNotIn('<td class="b del">', html)                             # not drawn removed / added
        self.assertIn('<td>changed</td><td></td><td></td><td>1</td></tr>', summary_html([d]))    # + Properties

    def test_json_and_listing(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for side, s in (('b', fb(MOVE, *STAY)), ('a', fb(*STAY, MOVE))):
            os.makedirs(os.path.join(tmp.name, side, 'plc'))
            for ext, text in (('s7dcl', s.s7dcl), ('s7res', s.s7res)):
                with open(os.path.join(tmp.name, side, 'plc', 'X.' + ext), 'w', encoding='utf-8') as f:
                    f.write(text)
        args = [os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a'), '-o', os.path.join(tmp.name, 'p.html')]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(args + ['--json'])
        (net,) = json.loads(out.getvalue())['blocks'][0]['networks']
        self.assertEqual(net, {'state': 'same', 'lang': 'SCL', 'before': 2, 'after': 5, 'title': 'Network to move',
                               'moved': True})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(args)
        self.assertIn('same     SCL     2 -> 5     Network to move  (moved)', out.getvalue())


# ---------------------------------------------------------------- a long page in several PNGs

class PngParts(unittest.TestCase):
    """A page taller than a PNG part gives several PNGs, cut between blocks; a block taller than a part between its
    networks, its header repeated. Measurements: block [top, bottom, header bottom, [tops of the header's
    siblings]]; `sum` the summary's top (shown in the first part only)."""

    def _parts(self, m, part):
        from TiaChangeReports.__main__ import _parts
        got = _parts(m, part)
        self.assertEqual(got[0][0], 0)
        self.assertEqual(got[-1][1], m['h'])
        self.assertEqual([y1 for _, y1, _ in got[:-1]], [y0 for y0, _, _ in got[1:]])   # no gap, no overlap
        return got

    def test_a_page_that_fits_is_one_part(self):
        m = {'h': 900, 'sum': None, 'blocks': [[100, 500, 130, [130, 300]], [520, 880, 550, [550]]]}
        self.assertEqual(self._parts(m, 16000), [(0, 900, 900)])

    def test_cut_between_blocks_title_and_legend_repeated(self):
        m = {'h': 2200, 'sum': None, 'blocks': [[y, y + 400, y + 30, [y + 30, y + 200]] for y in (100, 520, 940, 1360, 1780)]}
        self.assertEqual(self._parts(m, 1000), [(0, 940, 940), (940, 1780, 940), (1780, 2200, 520)])

    def test_summary_in_the_first_part_only(self):
        m = {'h': 2700, 'sum': 60, 'blocks': [[y, y + 400, y + 30, [y + 30]] for y in (600, 1020, 1440, 1860, 2280)]}
        self.assertEqual(self._parts(m, 1000), [(0, 600, 600), (600, 1440, 900), (1440, 2280, 900), (2280, 2700, 480)])

    def test_tall_block_cut_between_networks_its_header_repeated(self):
        m = {'h': 3440, 'sum': None, 'blocks': [[100, 3100, 130, [130, 700, 1300, 1900, 2500]], [3120, 3400, 3150, [3150]]]}
        self.assertEqual(self._parts(m, 1000), [(0, 700, 700), (700, 1300, 730), (1300, 1900, 730), (1900, 2500, 730),
                                                (2500, 3120, 750), (3120, 3440, 420)])

    def test_a_network_taller_than_a_part_is_one_part(self):
        m = {'h': 5040, 'sum': None, 'blocks': [[100, 5000, 130, [130, 300, 4800]]]}
        self.assertEqual(self._parts(m, 1000), [(0, 300, 300), (300, 4800, 4630), (4800, 5040, 370)])

    def test_names(self):
        from TiaChangeReports.__main__ import _png_names
        self.assertEqual(_png_names(os.path.join('x', 'big.png'), 1), [os.path.join('x', 'big.png')])
        self.assertEqual(_png_names(os.path.join('x', 'big.png'), 3), [os.path.join('x', 'big-%d.png' % k) for k in (1, 2, 3)])

    def test_headless_edge(self):
        import contextlib
        import io
        import json
        from unittest import mock
        from TiaChangeReports import __main__ as cli
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(cli.HERE), 'TiaHmiGenerator'))
        try:
            import PIL.Image
            from hmipreview.edge import edge_path
        except ImportError:
            self.skipTest('Pillow or hmipreview missing')
        if not edge_path():
            self.skipTest('no Microsoft Edge or Google Chrome')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        png = os.path.join(tmp.name, 'p.png')
        _put(tmp.name, {'p.png': 'stale'})
        out = io.StringIO()
        with mock.patch.object(cli, 'PART', 1500), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([V1, V2, '-o', os.path.join(tmp.name, 'p.html'), '--png', png, '--json']), 0)
        pngs = json.loads(out.getvalue())['png']
        self.assertGreater(len(pngs), 1)
        self.assertEqual(pngs, cli._png_names(png, len(pngs)))
        self.assertFalse(os.path.exists(png))                                   # the stale single PNG removed
        for p in pngs:
            with PIL.Image.open(p) as im:
                self.assertEqual(im.width, 1400)
                self.assertLessEqual(im.height, 1500, p)


class PngStacked(unittest.TestCase):
    """In the PNG a LAD network drawn below 70 % side by side shows before above after, each half the full width,
    like stacked focus (the halves' titles and the Before / After strip); the others stay side by side; the page,
    `?all` and focus unchanged."""

    # per LAD network: [stacked, strips, halves' title lines, own title bar shown, columns, scale of the wider svg,
    # sides holding a network (a new or deleted network one: the other side has no title to carry)]
    REPORT = ("<script>addEventListener('load',function(){setTimeout(function(){var o=[];"
              "document.querySelectorAll('.ldiff .nw').forEach(function(n){var ss=n.querySelectorAll('.pb svg.lad');"
              "if(!ss.length)return;var w=0,s=null;ss.forEach(function(q){if(+q.getAttribute('width')>w){w=+q.getAttribute('width');s=q}});"
              "o.push([n.classList.contains('stk'),n.querySelectorAll('.pane>.sl').length,n.querySelectorAll('.pane>.sh').length,"
              "getComputedStyle(n.querySelector(':scope>.nwt')).display!='none',"
              "getComputedStyle(n.querySelector('.panes')).gridTemplateColumns.split(' ').length,"
              "s.getBoundingClientRect().width/w,[].filter.call(n.querySelectorAll(':scope>.nwt>.side'),"
              "function(x){return x.firstChild}).length])});"
              "document.body.setAttribute('data-nets',JSON.stringify(o))},100)})</script>")

    def test_shoot_opens_the_png_layout(self):
        import inspect
        from TiaChangeReports import __main__ as cli
        self.assertIn("+ '?all&png'", inspect.getsource(cli.shoot))

    def test_wide_lad_networks_only_with_the_png_flag(self):
        from TiaChangeReports import page
        js = page.FOCUS_JS
        self.assertIn("if(/[?&]png(&|=|$)/.test(location.search))", js)
        self.assertIn("n.querySelector('.panes svg.lad')&&n.ldiffScale()<.7){n.classList.add('stk');labels(n)}", js)
        self.assertIn('n.ldiffScale=fit;', page.JS)                              # the zoom's fit, side by side

    def test_stacked_layout_shared_with_focus(self):
        from TiaChangeReports import page
        css = page.FOCUS_CSS
        for rule in ('.ldiff :is(.fcs.stk,.nw.stk) .panes{grid-template-columns:1fr}',
                     '.ldiff :is(.fcs.stk,.nw.stk) .pane>.sh{display:block}',
                     '.ldiff :is(.fcs.stk,.nw.stk) .pane>.sl{display:block;',
                     '.ldiff .nw.stk>.nwt,.ldiff .nw.stk>.nwc{display:none}'):
            self.assertIn(rule, css)
        self.assertIn('.ldiff .fcs.stk>.cols{display:none}', css)                # the column header stays in the PNG
        self.assertIn('.ldiff .fcs.stk .pane:first-child .sh .nwt .side{padding-right:62px}', css)  # focus buttons

    def test_headless_edge(self):
        import contextlib
        import io
        import json
        import pathlib
        import sys
        from html import unescape
        from TiaChangeReports import __main__ as cli
        sys.path.insert(0, os.path.join(os.path.dirname(cli.HERE), 'TiaHmiGenerator'))
        try:
            from hmipreview.edge import Edge, edge_path
        except ImportError:
            self.skipTest('hmipreview missing')
        if not edge_path():
            self.skipTest('no Microsoft Edge or Google Chrome')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, 'p.html')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([V1, V2, '-o', out]), 0)
        with open(out, encoding='utf-8') as f:
            text = f.read()
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text.replace('</body>', self.REPORT + '</body>'))
        e = Edge()
        self.addCleanup(e.close)
        url = pathlib.Path(out).as_uri()

        def nets(query):
            dom = e.dump_dom(url + query, timeout=120, size=(1400, 1000))
            return json.loads(unescape(re.search(r'data-nets="([^"]*)"', dom).group(1)))
        side, png = nets('?all'), nets('?all&png')
        self.assertEqual(len(side), len(png))
        self.assertFalse(any(n[0] for n in side))                                # ?all alone: side by side
        wide = [n[5] < .7 for n in side]
        self.assertTrue(any(wide) and not all(wide), [n[5] for n in side])
        for (_, _, _, _, cols, before, _), (stk, sl, sh, bar, cols2, after, titled), w in zip(side, png, wide):
            self.assertEqual(cols, 2)
            self.assertEqual(stk, w)
            if w:                                               # full width, about twice the scale, at most 100 %
                self.assertEqual((sl, sh, bar, cols2), (2, titled, False, 1))
                self.assertGreater(after, min(.999, 1.9 * before))
            else:
                self.assertEqual((sl, sh, bar, cols2, after), (0, 0, True, 2, before))


class OneObjectShown(unittest.TestCase):
    """The page opened without ?all shows one object, the address's or the first in the tree (the
    rail is shared with the HMI preview; its index must not take the loading script's selection as already shown)."""

    def test_headless_edge(self):
        import contextlib
        import io
        import pathlib
        import sys
        from TiaChangeReports import __main__ as cli
        sys.path.insert(0, os.path.join(os.path.dirname(cli.HERE), 'TiaHmiGenerator'))
        try:
            from hmipreview.edge import Edge, edge_path
        except ImportError:
            self.skipTest('hmipreview missing')
        if not edge_path():
            self.skipTest('no Microsoft Edge or Google Chrome')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, 'p.html')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([V1, V2, '-o', out]), 0)
        e = Edge()
        self.addCleanup(e.close)
        url = pathlib.Path(out).as_uri()
        keys = None
        for hash_ in ('', None):
            dom = e.dump_dom(url + (hash_ if hash_ is not None else '#' + keys[-1]), timeout=120, size=(1400, 1000))
            keys = keys or re.findall(r'<a class="obj[^"]*" href="[^"]*" data-i="\d+" data-key="([^"]+)"', dom)
            self.assertGreater(len(keys), 1)
            on = re.findall(r'<section class="blk[^"]*\bon\b[^"]*"', dom)
            self.assertEqual(1, len(on), hash_)                                 # one object shown
            sel = re.search(r'<a class="obj [^"]*\bsel\b[^"]*" href="[^"]*" data-i="\d+" data-key="([^"]+)"', dom)
            self.assertEqual(keys[0] if hash_ == '' else keys[-1], sel.group(1))
            self.assertNotRegex(re.search(r'<div class="ldiff[^"]*"', dom).group(0), r'\bwait\b')


# ---------------------------------------------------------------- properties apart from the interface

def _versioned(version, text=SRC):
    return text.replace('{ S7_Optimized := "TRUE" }', '{\n    S7_Optimized := "TRUE";\n    S7_Version := "%s"\n}' % version)


class PropertiesApart(unittest.TestCase):
    """The interface is marked only for a declaration change; a block property (the version TIA raises on every edit)
    gets its own mark: a Properties column, (properties) in the listing, "properties" in --json."""

    def test_version_alone_is_no_interface_change(self):
        d = compare_blocks(src(_versioned('0.1')), src(_versioned('0.2', SRC.replace('I_Contact( #b )',
                                                                                     'I_Contact( #a )'))))
        self.assertEqual((d.state, d.itf_changed, d.props_changed), ('changed', False, True))
        html = render([d], 'b', 'a')
        self.assertNotIn('<b>Interface</b>', html)
        self.assertIn('<div class="nw itfw"><div class="nwh"><b>Properties</b></div>', html)
        self.assertIn('<span class="tx del"><span>0.1</span></span> <span class="tx ins"><span>0.2</span></span>', html)

    def test_version_alone_still_a_changed_block(self):
        d = compare_blocks(src(_versioned('0.1')), src(_versioned('0.2')))
        self.assertEqual((d.state, d.nets, d.itf_changed, d.props_changed), ('changed', [], False, True))

    def test_declaration_and_version(self):
        d = compare_blocks(src(_versioned('0.1')), src(_versioned('0.2', SRC.replace('b : Bool;', 'b : Int;'))))
        self.assertEqual((d.itf_changed, d.props_changed), (True, True))
        html = render([d], 'b', 'a')
        self.assertLess(html.index('<b>Properties</b>'), html.index('<b>Interface</b>'))
        self.assertNotIn('Block properties', iface.html(d.before, d.after))

    def test_declaration_alone(self):
        d = compare_blocks(src(), src(SRC.replace('b : Bool;', 'b : Int;')))
        self.assertEqual((d.itf_changed, d.props_changed), (True, False))
        self.assertNotIn('<b>Properties</b>', render([d], 'b', 'a'))

    def test_summary_columns(self):
        from TiaChangeReports.page import summary_html
        d = compare_blocks(src(_versioned('0.1')), src(_versioned('0.2')))
        html = summary_html([d])
        self.assertIn('<th>State</th><th>Interface</th><th>Properties</th><th>Networks changed</th>', html)
        self.assertIn('<td>changed</td><td></td><td>changed</td><td>0</td></tr>', html)

    def test_listing_and_json(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _put(os.path.join(tmp.name, 'b'), {'plc/T.s7dcl': _versioned('0.1'), 'plc/T.s7res': RES,
                                           'plc/U.s7dcl': SRC.replace('"T"', '"U"')})
        _put(os.path.join(tmp.name, 'a'), {'plc/T.s7dcl': _versioned('0.2'), 'plc/T.s7res': RES,
                                           'plc/U.s7dcl': _versioned('0.2', SRC.replace('"T"', '"U"')
                                                                     .replace('b : Bool;', 'b : Int;'))})
        args = [os.path.join(tmp.name, s) for s in 'ba'] + ['-o', os.path.join(tmp.name, 'p.html')]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(args + ['--json'])
        got = {b['name']: (b['interface'], b['properties']) for b in json.loads(out.getvalue())['blocks']}
        self.assertEqual(got, {'T': (False, True), 'U': (True, True)})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(args)
        heads = [l.rstrip() for l in out.getvalue().splitlines() if l[:1] != ' ']
        self.assertIn('changed  FB          T  (properties)', heads)
        self.assertIn('changed  FB          U  (interface)  (properties)', heads)


# What host pages commonly set on bare elements (a CMS theme, a reset, boxes and a grid on every cell)
HOSTILE = ('body{font:16px/1.7 Georgia,serif;color:#333;text-align:justify;text-transform:uppercase;letter-spacing:.03em;'
           'word-spacing:2px;text-indent:1em;white-space:pre-line;text-shadow:0 0 1px #888}'
           'section{display:flex;background:#fafafa;border:2px solid red;border-radius:8px;padding:20px;margin:30px 0;'
           'box-shadow:0 0 4px #000;max-width:600px}'
           'table{border-collapse:separate;border-spacing:4px;border:1px solid #000;margin:12px 0;font-size:18px;'
           'background:#eee;box-shadow:0 0 2px #000}'
           'tr{background:#ffe;vertical-align:bottom}tr:nth-child(even){background:#eef}'
           'th,td{border:1px solid #888;padding:10px;text-align:right;vertical-align:bottom;color:#a00;'
           'background:#ddf;font-weight:bold;font-style:italic;white-space:nowrap}'
           'th{color:#fff;background:#036;text-transform:uppercase}'
           'a{color:#c00;text-decoration:none;font-weight:bold;border-bottom:1px dotted;padding:2px}'
           'button{border-radius:12px;margin:4px;padding:8px 20px;text-transform:uppercase;letter-spacing:.1em;'
           'box-shadow:0 2px 3px #000;min-width:120px}'
           'svg{display:block;max-width:100%;overflow:visible;vertical-align:middle;fill:currentColor}')


class InAnyHostPage(unittest.TestCase):
    """The fragment looks the same inside a page that styles bare elements as on a bare page."""

    def test_host_rules_on_bare_elements_stop_at_the_fragment(self):
        from TiaChangeReports.tests import host_styles
        edge = host_styles.browser()
        if not edge:
            self.skipTest('no Microsoft Edge, Google Chrome or hmipreview')
        self.addCleanup(edge.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        frag = host_styles.plant_fragment(tmp.name)
        width, host = host_styles.styles(
            edge, '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>%s</style></head><body><main>'
            '<section><h2>Code</h2>%s</section></main></body></html>' % (HOSTILE, frag), tmp.name, 'host.html')
        _, alone = host_styles.styles(edge, host_styles.bare(frag, width), tmp.name, 'bare.html')
        self.assertGreater(len(alone), 500)
        d = host_styles.differences(alone, host)
        self.assertFalse(d, host_styles.summary(d))


class BlockIds(unittest.TestCase):
    """A block header's id is unique in its report (the tree's key: name, name~2, ...), the summary
    row links its own block; a second report on the page with the same block keeps its links in its own report."""

    def ids(self, html):
        from urllib.parse import unquote
        return (re.findall(r'<div class="bh" id="([^"]*)">', html),
                [unquote(h) for h in re.findall(r'<tr><td><a href="#([^"]*)">', html)])

    def test_same_name_blocks_each_their_own_id(self):
        diffs = ProjectTree().diffs()
        for html in (render(diffs, 'b', 'a'), render(diffs, 'b', 'a', fragment=True)):
            heads, rows = self.ids(html)
            self.assertEqual(heads, ['blk-Filler', 'blk-Filler~2', 'blk-Filler~3', 'blk-Prep data', 'blk-Alpha', 'blk-Filler_UDT'])
            self.assertEqual(rows, heads)                                  # each row to its own block
        keys = dict((int(i), k) for i, k in re.findall(r'data-i="(\d+)" data-key="([^"]*)"', render(diffs, 'b', 'a')))
        self.assertEqual(['blk-' + keys[i] for i in range(len(diffs))], heads)    # the tree's key

    def test_program_block_and_library_type_that_differ(self):          # the "differs" case of a library type
        b, a, ds = LibraryInstances.run_(self, {**_prep(), **_lib('1.0.0', 'InWork')},
                                         {**_prep(keys='p', setpoint=True, number='746'), **_lib('1.0.0', edit=True)})
        for html in (render(ds, b.label, a.label), render(ds, b.label, a.label, fragment=True)):
            heads, rows = self.ids(html)
            self.assertEqual(heads, ['blk-PrepareFillData', 'blk-PrepareFillData~2'])
            self.assertEqual(rows, heads)

    def test_summary_link_stays_in_its_own_report(self):
        from TiaChangeReports import page
        for hook in ("r.querySelectorAll('table.sum a[href^=\"#blk-\"]')", 'document.getElementById(id)===h',
                     'e.preventDefault()', 'history.pushState', 'h.scrollIntoView()'):
            self.assertIn(hook, page.JS)
        self.assertIn(page.JS, render(ProjectTree().diffs(), 'b', 'a', fragment=True))

    def test_summary_address_opens_its_object_on_the_page(self):
        from TiaChangeReports import page
        self.assertIn(".replace(/^blk-/,'')", page.RAIL_JS)                # #blk-Filler~2 as #Filler~2


def _flow(html):
    """The report in the page's flow: after the style, without the fixed parts (tree, lookup, loading line) and the
    scripts."""
    body = html.split('</style>')[-1]
    for fixed in (r'<nav class="rail".*?</nav>', r'<div class="lch" hidden>.*?</ul></div></div>',
                  r'<div class="ld"[^>]*>[^<]*</div>', r'<script>.*?</script>'):
        body = re.sub(fixed, '', body, flags=re.S)
    return body


# ---------------------------------------------------------------- a big page usable while it loads

class BigPageLoading(unittest.TestCase):
    """A whole-project page (36 MB) parses for seconds; from its first bytes it shows the tree and one
    object, a loading line until its script ran, no flat view first and no jump."""

    def test_tree_and_wait_script_before_the_report(self):
        from TiaChangeReports import page
        html = render(ProjectTree().diffs(), 'b', 'a')
        at = [html.index(x) for x in ('<nav class="rail"', '<div class="ld" role="status">', '<script>%s</script>'
                                      % page.WAIT_JS, '<div class="cols">', '<section class="blk">')]
        self.assertEqual(at, sorted(at))
        self.assertTrue(_flow(html).startswith('<div class="cols">'))

    def test_wait_shows_the_object_of_the_address_until_the_script_ran(self):
        from TiaChangeReports import page
        for hook in ("r.classList.add('one','wait')", "section.blk:nth-of-type(", "addEventListener('hashchange'",
                     "localStorage.getItem('ldiff-rail')", "r.classList.add('flat')", ".replace(/^blk-/,'')"):
            self.assertIn(hook, page.WAIT_JS)
        self.assertIn("r.classList.remove('wait')", page.RAIL_JS)
        self.assertIn('.ldiff .ld{display:none}', page.RAIL_CSS)
        self.assertIn('.ldiff.wait .ld{display:block;position:fixed', page.RAIL_CSS)
        self.assertIn('.ldiff .ld', _print_css(render(ProjectTree().diffs(), 'b', 'a')))

    def test_fragment_without_wait(self):
        frag = render(ProjectTree().diffs(), 'b', 'a', fragment=True)
        for gone in ('class="ld"', "'wait'", '.ldiff.wait'):
            self.assertNotIn(gone, frag)


EMPTY_NW = '''FUNCTION_BLOCK "E"
    VAR
        a : Bool; q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''


class EmptyNetwork(unittest.TestCase):
    """An empty LAD network is drawn as TIA does, its power rail and an empty rung, not as a text."""

    def test_rail_and_an_empty_rung(self):
        from TiaChangeReports.render_lad import X0
        (n,) = parse_block(src(EMPTY_NW, '', 'E')).networks
        lay = Layout(n.rungs, None)
        segs, terms = lay.wiring()
        rail, rung = segs
        self.assertEqual((rail[0], rail[2]), (X0, X0))                  # the rail
        self.assertEqual((rung[0], rung[1], rung[3]), (X0, lay.ys[0], lay.ys[0]))
        self.assertEqual(rung[2], lay.right)                            # across the network, as a rung of coils
        self.assertTrue(rail[1] < rung[1] < rail[3])
        self.assertEqual(terms, [])
        self.assertEqual(check(lay), [])

    def test_simaticml_empty_network_the_same(self):
        """SimaticML's empty network (<NetworkSource />) has no rung at all: drawn as the empty rung of .s7dcl."""
        (n,) = parse_block(src(EMPTY_NW, '', 'E')).networks
        self.assertEqual(Layout([], None).svg(), Layout(n.rungs, None).svg())

    def test_page_draws_it_on_both_sides(self):
        after = EMPTY_NW.replace('    END_NETWORK\n', '    END_NETWORK\n    { S7_Language := "LAD" }\n    NETWORK\n'
                                 '        RUNG wire#powerrail\n            Contact( #a )\n            Coil( #q )\n'
                                 '        END_RUNG\n    END_NETWORK\n', 1)
        html = render([compare_blocks(src(EMPTY_NW, '', 'E'), src(after, '', 'E'), all_=True)], 'b', 'a', full=True)
        self.assertNotIn('(empty network)', html)
        self.assertEqual(html.count('class="lad"'), 3)                  # the empty one twice, the new one once


# ---------------------------------------------------------------- structs inside a UDT in inner rows

MACH_UDT = ('TYPE "Mach_UDT"\n    STRUCT\n        Exists : Bool;\n        Coordinate : STRUCT\n'
            '            Column : Int := 1;\n            Line : Int;\n            Deep : STRUCT\n'
            '                z : Real;\n            END_STRUCT;\n        END_STRUCT;\n'
            '        Pts : Array[1..2] of STRUCT\n            p : Int;\n            q : Bool;\n        END_STRUCT;\n'
            '    END_STRUCT;\nEND_TYPE\n')
CART_UDT = 'TYPE "Cart_UDT"\n    STRUCT\n        Config : _.Mach_UDT;\n    END_STRUCT;\nEND_TYPE\n'
MACH_DB = ('DATA_BLOCK MDb\n    VAR\n        m : _.Mach_UDT;\n        c : Array[0..1] of _.Cart_UDT;\n'
           '    END_VAR\n\n%sEND_DATA_BLOCK\n')
MACH_START = ('        m.Coordinate.Column := 2;\n        m.Coordinate.Deep.z := 1.5;\n        m.Pts[1].p := 3;\n'
              '        c[0].Config.Coordinate.Column := 4;\n')
MACH_UDT_XML = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Types.PlcStruct ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
  <Section Name="None">
    <Member Name="Exists" Datatype="Bool" />
    <Member Name="Coordinate" Datatype="Struct">
      <Member Name="Column" Datatype="Int"><StartValue>1</StartValue></Member>
      <Member Name="Line" Datatype="Int" />
      <Member Name="Deep" Datatype="Struct">
        <Member Name="z" Datatype="Real" />
      </Member>
    </Member>
    <Member Name="Pts" Datatype="Array[1..2] of Struct">
      <Member Name="p" Datatype="Int" />
      <Member Name="q" Datatype="Bool" />
    </Member>
  </Section>
</Sections></Interface>
      <Name>Mach_UDT</Name>
    </AttributeList>
  </SW.Types.PlcStruct>
</Document>
'''
# a struct inside a UDT instance: its members are Member elements of the struct, as in project B's GxxInterfaceData
MACH_DB_XML = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
  <Section Name="Static">
    <Member Name="m" Datatype="&quot;Mach_UDT&quot;" Remanence="NonRetain">
      <Sections>
        <Section Name="None">
          <Member Name="Exists" Datatype="Bool" />
          <Member Name="Coordinate" Datatype="Struct">
            <Member Name="Column" Datatype="Int"><StartValue>2</StartValue></Member>
            <Member Name="Line" Datatype="Int" />
            <Member Name="Deep" Datatype="Struct">
              <Member Name="z" Datatype="Real"><StartValue>1.5</StartValue></Member>
            </Member>
          </Member>
        </Section>
      </Sections>
    </Member>
  </Section>
</Sections></Interface>
      <MemoryLayout>Optimized</MemoryLayout>
      <Name>MDb</Name>
      <Number>1</Number>
      <ProgrammingLanguage>DB</ProgrammingLanguage>
    </AttributeList>
  </SW.Blocks.GlobalDB>
</Document>
'''


class StructInUdtInnerRows(unittest.TestCase):
    """The members of a struct declared in a UDT (also a struct in it, an array of struct, a UDT in an
    array of UDT) show their data type and default value in the inner rows, as TIA does;
    the struct's other members under it, folded. The same from the SimaticML exports."""

    def _types(self, before='', after=MACH_START, types=None):
        b, a = (parse_block(src(MACH_DB % s, '', 'MDb')).interface for s in (before, after))
        types = types or _types(Mach_UDT=MACH_UDT, Cart_UDT=CART_UDT)
        return {'.'.join(r.path): (iface.tia_type(r.m.type), r.state, getattr(r.m, 'dflt', None))
                for r in iface.rows(b, a, (types, types))}

    def test_types_of_the_struct_members(self):
        rs = self._types()
        self.assertEqual({k: v[0] for k, v in rs.items() if k.startswith('m.')}, {
            'm.Exists': 'Bool', 'm.Coordinate': 'Struct', 'm.Coordinate.Column': 'Int', 'm.Coordinate.Line': 'Int',
            'm.Coordinate.Deep': 'Struct', 'm.Coordinate.Deep.z': 'Real', 'm.Pts': 'Array[1..2] of Struct',
            'm.Pts.Pts[1]': 'Struct', 'm.Pts.Pts[1].p': 'Int', 'm.Pts.Pts[1].q': 'Bool'})
        self.assertEqual(rs['c.c[0].Config.Coordinate.Column'][0], 'Int')                 # a UDT in an array of UDT
        self.assertEqual(rs['c.c[0].Config.Coordinate.Line'][0], 'Int')

    def test_states_and_default_from_the_struct(self):
        rs = self._types()
        self.assertEqual(rs['m.Coordinate.Column'][1:], ('changed', '1'))               # the UDT's default
        self.assertEqual((rs['m.Coordinate.Line'][1], rs['m.Pts.Pts[1].q'][1]), ('same', 'same'))
        rs = self._types(MACH_START.replace(':= 2', ':= 5'))                              # named on both sides
        self.assertEqual([k for k, v in rs.items() if v[1] != 'same'], ['m.Coordinate.Column'])

    def test_simaticml_udt_and_db_as_the_sd_export(self):
        types = (lambda xml: (lambda name: xml if name == 'Mach_UDT' else None))(
            parse_block(_xml_src(MACH_UDT_XML, 'Mach_UDT')).interface)
        sd = parse_block(src(MACH_DB % MACH_START.split('        m.Pts')[0], '', 'MDb'))
        xml = parse_block(_xml_src(MACH_DB_XML, 'MDb'))
        self.assertEqual(sorted(xml.interface.start), ['m.Coordinate.Column', 'm.Coordinate.Deep.z'])
        rs = {'.'.join(r.path): (iface.tia_type(r.m.type), r.state) for r in iface.rows(sd.interface, xml.interface,
                                                                                   (types, types))}
        self.assertEqual(rs['m.Coordinate.Column'], ('Int', 'same'))
        self.assertEqual(rs['m.Coordinate.Deep.z'], ('Real', 'same'))



AOS = '        a : Array[%s] of Struct\n            p : Int;\n            q : Bool;\n        END_STRUCT;\n        x : Int;\n'
AOS_DB = 'DATA_BLOCK D\n    VAR\n%s    END_VAR\n\n%sEND_DATA_BLOCK\n'
AOS_FB = 'FUNCTION_BLOCK "F"\n    VAR\n%s    END_VAR\nEND_FUNCTION_BLOCK\n'
AOS_UDT = 'TYPE "U"\n    STRUCT\n%s    END_STRUCT;\nEND_TYPE\n'


class ArrayOfStructRows(unittest.TestCase):
    """An array of struct declared in a DB, an FB or a UDT shows its elements, each with the struct's
    members, as TIA does, not the members directly under the array: the first element always (it carries the
    declaration), the others when a start value names them."""

    def _rows(self, before, after):
        b, a = (parse_block(src(t, '', 'D')).interface for t in (before, after))
        return [('.'.join(r.path), iface.tia_type(r.m.type), r.state, sorted(r.changes)) for r in iface.rows(b, a)]

    def test_db_without_start_values(self):
        db = AOS_DB % (AOS % '1..2', '')
        self.assertEqual([r[:3] for r in self._rows(db, db)], [
            ('a', 'Array[1..2] of Struct', 'same'), ('a.a[1]', 'Struct', 'same'), ('a.a[1].p', 'Int', 'same'),
            ('a.a[1].q', 'Bool', 'same'), ('x', 'Int', 'same')])

    def test_db_start_values_under_their_elements(self):
        rs = self._rows(AOS_DB % (AOS % '1..2', ''),
                        AOS_DB % (AOS % '1..2', '        a[1].p := 3;\n        a[2].q := TRUE;\n'))
        self.assertEqual([r[:3] for r in rs], [
            ('a', 'Array[1..2] of Struct', 'same'), ('a.a[1]', 'Struct', 'same'), ('a.a[1].p', 'Int', 'changed'),
            ('a.a[1].q', 'Bool', 'same'), ('a.a[2]', 'Struct', 'same'), ('a.a[2].p', 'Int', 'same'),
            ('a.a[2].q', 'Bool', 'changed'), ('x', 'Int', 'same')])

    def test_declaration_change_on_the_first_element(self):
        decl = AOS % '1..2'
        rs = self._rows(AOS_DB % (decl, '        a[2].p := 1;\n'),
                        AOS_DB % (decl.replace('p : Int', 'p : DInt').replace('q : Bool;\n', 'q : Bool;\n'
                                                                                '            r : Real;\n'),
                                  '        a[2].p := 1;\n'))
        self.assertEqual([r for r in rs if r[2] != 'same'], [
            ('a.a[1].p', 'DInt', 'changed', ['type']), ('a.a[1].r', 'Real', 'added', []),
            ('a.a[2].r', 'Real', 'added', [])])

    def test_fb_static_and_udt(self):
        for t in (AOS_FB, AOS_UDT):
            self.assertEqual([r[0] for r in self._rows(t % (AOS % '0..9'), t % (AOS % '0..9'))],
                             ['a', 'a.a[0]', 'a.a[0].p', 'a.a[0].q', 'x'], t)

    def test_element_in_the_section_of_its_array(self):
        for t, sec in ((AOS_UDT, 'UDT'), (AOS_FB.replace('VAR\n', 'VAR_TEMP\n'), 'TEMP')):
            itf = parse_block(src(t % (AOS % '1..2'), '', 'D')).interface
            self.assertEqual({r.m.section for r in iface.rows(itf, itf)}, {sec}, t)

    def test_bounds(self):
        for bounds, elem in (('0..1, 1..3', 'a[0,1]'), ('*', 'a[*]'), ('_.first.._.last', 'a["first"]'),
                             ('-1..1', 'a[-1]')):
            rs = self._rows(AOS_FB % (AOS % bounds), AOS_FB % (AOS % bounds))
            self.assertEqual([r[0] for r in rs][1:3], ['a.' + elem, 'a.%s.p' % elem], bounds)

    def test_nested(self):
        decl = ('        a : Array[1..2] of Struct\n            s : Struct\n                b : Array[0..1] of Struct\n'
                '                    z : Int;\n                END_STRUCT;\n            END_STRUCT;\n        END_STRUCT;\n'
                '        x : Int;\n')                              # one member only: the parser shows its members
        self.assertEqual([r[0] for r in self._rows(AOS_UDT % decl, AOS_UDT % decl)], [
            'a', 'a.a[1]', 'a.a[1].s', 'a.a[1].s.b', 'a.a[1].s.b.b[0]', 'a.a[1].s.b.b[0].z', 'x'])

    def test_array_of_struct_in_a_udt_instance_unchanged(self):
        rs = StructInUdtInnerRows()._types()                     # those tests' elements, no members under Pts
        self.assertEqual([k for k in rs if k.startswith('m.Pts')], ['m.Pts', 'm.Pts.Pts[1]', 'm.Pts.Pts[1].p',
                                                                   'm.Pts.Pts[1].q'])

    def test_simaticml_udt(self):
        rs = [('.'.join(r.path), iface.tia_type(r.m.type)) for r in iface.rows(
            *(parse_block(_xml_src(MACH_UDT_XML, 'Mach_UDT')).interface,) * 2)]
        self.assertEqual([r for r in rs if r[0].startswith('Pts')], [
            ('Pts', 'Array[1..2] of Struct'), ('Pts.Pts[1]', 'Struct'), ('Pts.Pts[1].p', 'Int'),
            ('Pts.Pts[1].q', 'Bool')])

    def test_page_row_names(self):
        b, a = (parse_block(src(AOS_DB % (AOS % '1..2', s), '', 'D')) for s in ('', '        a[1].p := 3;\n'))
        names = [c[0].lstrip('▼ ') for _, c in _trs(iface.html(b, a))]
        self.assertEqual(names[names.index('a'):names.index('x')], ['a', 'a[1]', 'p', '⋯ 2 unchanged members '
                                                                    '(click to show all)', 'q'])


INIT_RES = 'MultiLingualTexts:\n' + ''.join('  - id: MLC_%s\n    en-US: %s\n' % (k, v) for k, v in (
    ('e', 'level exists'), ('s', 'sensor'), ('t10', 'level 10'), ('t20', 'level 20'), ('b1', 'flat'), ('b2', 'lower'),
    ('b3', 'main'), ('m', 'first of the second row')))
INIT_UDT = '''TYPE
    Init_UDT : STRUCT
        active : Bool;
        "Z" : Array[0..99] of STRUCT
            Exists : Bool;
            Sensor : Bool;
            slot : Array[1..3] of _.Slot_UDT;
        END_STRUCT := [
            (
                { S7_MLC := "MLC_e" }
                Exists := (),
                { S7_MLC := "MLC_s" }
                Sensor := TRUE,
                slot := [
                    3((select := (),home := ()
                    ))
                ]
            ),
            9(()),
            { S7_MLC := "MLC_t10" }
            (),
            9(()),
            { S7_MLC := "MLC_t20" }
            ()
        ];
        flags : Array[1..3] of Bool := [
            { S7_MLC := "MLC_b1" }
            (),
            { S7_MLC := "MLC_b2" }
            (),
            { S7_MLC := "MLC_b3" }
            ()
        ];
        resp : Array[0..3] of Bool := [
            4(FALSE)
        ];
        grid : Array[0..1, 0..2] of Int := [
            3(()),
            { S7_MLC := "MLC_m" }
            ()
        ];
        cmd : _.Cmd_UDT := (
            OrderNo := 0,
            Recipe := 2
        );
    END_STRUCT;
END_TYPE
'''
INIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Types.PlcStruct ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
  <Section Name="None">
    <Member Name="flags" Datatype="Array[1..3] of Bool">
%s    </Member>
  </Section>
</Sections></Interface>
      <Name>Flags_UDT</Name>
    </AttributeList>
  </SW.Types.PlcStruct>
</Document>
""" % ''.join('      <Subelement Path="%d"><Comment><MultiLanguageText Lang="en-US">%s</MultiLanguageText></Comment>'
              '</Subelement>\n' % (k, v) for k, v in ((1, 'flat'), (2, 'lower'), (3, 'main')))


class StructuredInitializers(unittest.TestCase):
    """The initializer TIA writes after a declaration over several lines (an array of struct's
    'END_STRUCT := [...]', an array's or a UDT instance's ':= [...]' / ':= (...)') holds the comments and start values
    of elements and members: read into the start values, not as members of their own."""

    def itf(self):
        return parse_block(src(INIT_UDT, INIT_RES, 'Init_UDT')).interface

    def test_no_members_from_the_initializer(self):
        itf = self.itf()
        self.assertEqual(list(itf.root.children), ['active', 'Z', 'flags', 'resp', 'grid', 'cmd'])
        self.assertEqual([m.value for m in itf.root.children.values()], [None] * 6)

    def test_start_values_and_comments(self):
        self.assertEqual(self.itf().start, {
            'Z[0].Exists': ('()', 'level exists'), 'Z[0].Sensor': ('TRUE', 'sensor'), 'Z[10]': ('()', 'level 10'),
            'Z[20]': ('()', 'level 20'), 'flags[1]': ('()', 'flat'), 'flags[2]': ('()', 'lower'),
            'flags[3]': ('()', 'main'), 'resp[0]': ('FALSE', None), 'resp[1]': ('FALSE', None),
            'resp[2]': ('FALSE', None), 'resp[3]': ('FALSE', None), 'grid[1,0]': ('()', 'first of the second row'),
            'cmd.OrderNo': ('0', None), 'cmd.Recipe': ('2', None)})

    def test_bounds_not_known_here(self):
        txt = INIT_UDT.replace('Array[0..1, 0..2] of Int', 'Array[0..1, 0.._.MAX] of Int').replace(
            'flags : Array[1..3]', 'flags : Array[_.first.._.last]')
        st = parse_block(src(txt, INIT_RES, 'Init_UDT')).interface.start
        self.assertEqual(sorted(k for k in st if k[:4] in ('grid', 'flag')), ['flags["first"]'])

    def test_rows(self):
        itf = self.itf()
        rs = {'.'.join(r.path): (iface.tia_type(r.m.type), r.m.comment, r.m.value) for r in iface.rows(itf, itf)}
        self.assertEqual(rs['Z.Z[0].Exists'], ('Bool', 'level exists', None))
        self.assertEqual(rs['Z.Z[0].Sensor'], ('Bool', 'sensor', 'TRUE'))
        self.assertEqual(rs['Z.Z[10]'][:2], ('Struct', 'level 10'))
        self.assertEqual([k for k in rs if k.startswith('Z.Z[10]')], ['Z.Z[10]', 'Z.Z[10].Exists', 'Z.Z[10].Sensor',
                                                                     'Z.Z[10].slot'])  # an element with its members
        self.assertEqual(rs['flags.flags[2]'], ('Bool', 'lower', None))
        self.assertNotIn('Exists', rs)

    def test_simaticml_element_comments_as_the_sd_export(self):
        sd = parse_block(src(INIT_UDT.replace('Init_UDT', 'Flags_UDT'), INIT_RES, 'Flags_UDT')).interface
        sd.root.children = {'flags': sd.root.children['flags']}
        sd.start = {k: v for k, v in sd.start.items() if k.startswith('flags')}
        xml = parse_block(_xml_src(INIT_XML, 'Flags_UDT')).interface
        self.assertEqual(xml.start, sd.start)
        self.assertEqual({r.state for r in iface.rows(sd, xml)}, {'same'})


# ---------------------------------------------------------------- JumpList, Switch and Calculate

JUMPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'Jumps.xml')

# The networks of Jumps.xml in an FB as the SD export writes them (made-up names, in the form of a V20 Update 7
# export of these networks, 2026-10-30).
JUMPS_SD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'Jumps.s7dcl')


def _jumps_sd(*repl):
    """Jumps.s7dcl (with its .s7res) with replacements."""
    s = from_file(JUMPS_SD)
    text = s.s7dcl
    for old, new in repl:
        assert old in text, old
        text = text.replace(old, new)
    return BlockSource('Jumps', text, s.s7res, 'Jumps.s7dcl')


def _jumps(*repl, last=()):
    """Jumps.xml with replacements; `last` only in its last network."""
    with open(JUMPS, encoding='utf-8-sig') as f:
        text = f.read()
    for old, new in repl:
        assert old in text, old
        text = text.replace(old, new)
    i = text.rindex('<SW.Blocks.CompileUnit')
    for old, new in last:
        assert old in text[i:], old
        text = text[:i] + text[i:].replace(old, new)
    return text


def _jump_box(blk, k):
    (el,) = [it for r in blk.networks[k].rungs for it in r.items if isinstance(it, Element)]
    return el


class JumpListSwitchCalculate(unittest.TestCase):
    """The three boxes drawn as TIA does (TIA's shots of them), from SimaticML and from the SD export."""

    def test_simaticml_parts(self):
        b = parse_block(_xml_src(_jumps(), 'Jumps'))
        sw, calc, jl = (_jump_box(b, k) for k in range(3))
        self.assertEqual((sw.instr, sw.templates), ('Switch', {'CASE0': '==', 'CASE1': '==', 'SrcType': 'USInt'}))
        self.assertEqual(sw.params, [('k', ':=', '#selector'), ('case0', ':=', '#caseA'), ('case1', ':=', '#caseB'),
                                     ('else', '=>', 'stepA'), ('dst0', '=>', 'stepA'), ('dst1', '=>', 'stepB')])
        self.assertEqual((calc.instr, calc.expression, calc.no_eno, calc.templates),
                         ('Calculate', '(IN1 + IN2) * (IN1 - IN2)', True, {'SrcType': 'DInt'}))
        self.assertEqual([n for n, _, _ in calc.params], ['in1', 'in2', 'in3', 'out'])
        self.assertEqual((jl.instr, jl.params), ('JumpList', [('k', ':=', '#selector'), ('dst0', '=>', 'stepA'),
                                                              ('dst1', '=>', 'stepB')]))
        self.assertFalse(sw.no_eno or jl.no_eno)

    def test_every_pin_of_the_cardinality(self):
        """A destination without a label is a pin all the same, as TIA draws it."""
        card = '<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>\n    </Part>'
        b = parse_block(_xml_src(_jumps((card, card.replace('>2<', '>3<'))), 'Jumps'))
        self.assertEqual(_jump_box(b, 2).params[-1], ('dst2', '=>', ''))

    def test_the_sd_export_is_the_same_logic(self):
        from TiaChangeReports.s7dcl import parse_lad
        from TiaChangeReports.simaticml import rungs_text
        xb, sb = parse_block(_xml_src(_jumps(), 'Jumps')), parse_block(_jumps_sd())
        self.assertEqual([n.title for n in sb.networks], [n.title for n in xb.networks])
        for x, s in zip(xb.networks, sb.networks):
            self.assertFalse(NetDiff(Graph(x.rungs), Graph(s.rungs)).changed, x.title)
            self.assertEqual([e.sig() for r in s.rungs for e in r.items if isinstance(e, Element)],
                             [e.sig() for r in x.rungs for e in r.items if isinstance(e, Element)])
            back = parse_lad(rungs_text(x.rungs), 'r')                 # the text written reads back the same
            self.assertEqual([e.sig() for r in back for e in r.items if isinstance(e, Element)],
                             [e.sig() for r in x.rungs for e in r.items if isinstance(e, Element)])
        self.assertIn('{ S7_Templates := "SrcType := USInt"; CASE0 := "=="; CASE1 := "==" }',
                      rungs_text(xb.networks[0].rungs))
        self.assertTrue(_jump_box(sb, 1).no_eno)                       # no S7_GenerateENO: ENO gray, as in TIA
        gen = parse_block(_jumps_sd(('S7_Expression := "(IN1 + IN2) * (IN1 - IN2)"',
                                     'S7_Expression := "IN1";\n S7_GenerateENO := TRUE')))
        self.assertFalse(_jump_box(gen, 1).no_eno)

    def test_sd_export_diff(self):
        before = _jumps_sd()
        after = _jumps_sd(('CASE1 := "=="', 'CASE1 := "<>"'), ('dst0 => stepA', 'dst0 => stepX'),
                          ('(IN1 + IN2) * (IN1 - IN2)', '(IN1 + IN2) * IN3'), ('in2 := #valB', 'in2 := #valC'))
        d = compare_blocks(before, after)
        got = {}
        for p in d.nets:
            el = next(iter(Graph(p.after.rungs).elements.values()))
            got[p.after.title] = changed_params(el, p.lad.other[el.eid])
        self.assertEqual(got, {'Switch': {'case1', 'dst0'}, 'Calculate': {'expression', 'in2'},
                               'Jump list': {'dst0'}})

    def test_drawn_as_tia(self):
        from TiaChangeReports.render_lad import C_OFF, C_OP, EXPR_ROW
        b = parse_block(_xml_src(_jumps(), 'Jumps'))
        for n in b.networks:
            self.assertEqual(check(Layout(n.rungs, b.interface)), [], n.title)
        sw, calc, jl = (Layout(b.networks[k].rungs, b.interface) for k in range(3))
        v = next(iter(sw.views.values()))
        self.assertEqual((v.title, v.sub), ('SWITCH', 'USInt'))
        self.assertEqual([n for n, _ in v.lefts], ['EN', 'K', '==', '=='])
        self.assertEqual(v.rights, [('DEST0', [('stepA', C_OP, False)]), ('DEST1', [('stepB', C_OP, False)]),
                                    ('ELSE', [('stepA', C_OP, False)])])
        self.assertEqual(v.rowy_r[0], 0)                                # DEST0 on the rung, no ENO
        svg = sw.svg()
        self.assertNotIn('>ENO<', svg)
        self.assertEqual(svg.count('>==</text>'), 2)
        v = next(iter(jl.views.values()))
        self.assertEqual((v.title, [n for n, _ in v.rights]), ('JMP_LIST', ['DEST0', 'DEST1']))
        v = next(iter(calc.views.values()))
        self.assertEqual((v.title, v.sub, v.expr), ('CALCULATE', 'DInt', 'OUT :=  (IN1 + IN2) * (IN1 - IN2)'))
        self.assertGreaterEqual(v.rowy[1], EXPR_ROW + 18)              # IN1 below the expression row
        self.assertEqual(v.rowy[1], v.rowy_r[1])                        # OUT on the IN1 row
        self.assertIn('fill="%s" text-anchor="end" font-size="11">ENO<' % C_OFF, calc.svg())
        sd = parse_block(_jumps_sd())
        for k, n in enumerate(sd.networks):                           # the SD export drawn the same
            lay = Layout(n.rungs, sd.interface)
            self.assertEqual(check(lay), [], n.title)
            if k < 3:
                x, s = (next(iter(l.views.values())) for l in ((sw, calc, jl)[k], lay))
                self.assertEqual((s.title, s.sub, s.expr, s.lefts, s.rights, s.rowy, s.rowy_r),
                                 (x.title, x.sub, x.expr, x.lefts, x.rights, x.rowy, x.rowy_r))

    def _diff(self, after, k):
        d = compare_blocks(_xml_src(_jumps(), 'Jumps'), _xml_src(after, 'Jumps'))
        (p,) = [p for p in d.nets if p.after.index == k + 1]
        el = next(iter(Graph(p.after.rungs).elements.values()))
        lay = Layout(p.after.rungs, d.after.interface)
        return p, el, lay, [m for m in lay.marks(p.lad.status, p.lad.other) if m[0] == el.eid]

    def test_renamed_operands_and_labels(self):
        """The kinds of change of the second reference version: Calculate operands, a jump label (where it is
        declared, network 4, and where it is jumped to), a coil operand in one label network, a network
        title."""
        after = _jumps(('Name="valB"', 'Name="valB2"'), ('Name="valC"', 'Name="valC2"'),
                       ('Name="result"', 'Name="result2"'), ('<Label Name="stepA" />', '<Label Name="stepX" />'),
                       last=(('Name="done"', 'Name="done2"'), ('<Text>Step label</Text>', '<Text>Step B</Text>')))
        d = compare_blocks(_xml_src(_jumps(), 'Jumps'), _xml_src(after, 'Jumps'))
        self.assertEqual([p.after.title for p in d.nets], ['Switch', 'Calculate', 'Jump list', 'Step label', 'Step B'])
        self.assertEqual([p.label_state for p in d.nets], ['same', 'same', 'same', 'changed', 'same'])
        for k, keys in ((0, {'dst0', 'else'}), (1, {'in2', 'in3', 'out'}), (2, {'dst0'})):
            p, el, lay, marks = self._diff(after, k)
            self.assertEqual(p.lad.status[el.eid], 'changed')
            self.assertEqual(changed_params(el, p.lad.other[el.eid]), keys)
            self.assertTrue(marks)
        p, el, lay, marks = self._diff(after, 0)
        v, y = lay.views[el.eid], lay.ys[0]
        x = lay._elx(el.eid) + v.lw + v.bw                              # right edge of the box: DEST0 on the rung
        self.assertTrue(any(m[3] <= x + 12 <= m[3] + m[5] and m[4] <= y <= m[4] + m[6] for m in marks))

    def test_changed_case_expression_and_eno(self):
        after = _jumps(('<TemplateValue Name="CASE1" Type="Operation">EQ',
                        '<TemplateValue Name="CASE1" Type="Operation">GT'))
        p, el, lay, marks = self._diff(after, 0)
        self.assertEqual(changed_params(el, p.lad.other[el.eid]), {'case1'})
        self.assertIn('>&gt;</text>', lay.svg())
        v, y = lay.views[el.eid], lay.ys[0]
        row = y + v.rowy[3]
        self.assertTrue(marks and all(m[4] < row < m[4] + m[6] for m in marks))
        after = _jumps(('(IN1 + IN2) * (IN1 - IN2)', '(IN1 + IN2) * IN3'), (' DisabledENO="true"', ''))
        p, el, lay, marks = self._diff(after, 1)
        self.assertEqual(changed_params(el, p.lad.other[el.eid]), {'expression', 'eno'})
        v, y = lay.views[el.eid], lay.ys[0]
        self.assertIn(('box',) + v._expr_box(lay._elx(el.eid) + v.lw, y), [m[2:] for m in marks])
        self.assertEqual(len(marks), 2)


# ---------------------------------------------------------------- box details as TIA draws them

BOXES_CALLEE = '''FUNCTION_BLOCK "Pump"
    VAR_INPUT
        run : Bool;
        speed : Int;
        limit : Int;
    END_VAR
    VAR_IN_OUT
        cmd : DInt;
    END_VAR
END_FUNCTION_BLOCK
'''
BOXES = '''FUNCTION_BLOCK "Boxes"
    VAR
        pump : _.Pump;
    END_VAR
    VAR_TEMP
        a : Bool;
        n : Int;
        big : DInt;
        arr : Array[0..3] of DInt;
        line : Int;
        k : DInt;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Move(
                in := 3,
                out1 => #line
            )
        END_RUNG
        RUNG wire#powerrail
            Contact( #a )
            #pump(
                run := #a,
                speed := #big,
                limit := #arr[1],
                cmd := #n
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "SrcType := Int" }
            Calculate(
                in1 := #n,
                in2 := #k,
                out => #line
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
MUXES = '''FUNCTION_BLOCK "Sel"
    VAR_TEMP
        i : Int;
        r : Real;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "SrcType := Real" }
            Mux(
                k := #i,
                in0 := #r,
                in1 := #i,
                out => #r
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "SrcType := Real" }
            Demux(
                k := #i,
                in := #r,
                out0 => #r,
                out1 => #r
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''


class BoxDetailsLikeTia(unittest.TestCase):
    """The type in the head, the open ENO (in the top rung and below it) and the conversion mark, as TIA draws
    them; no add-pin star (the editor's handle, not for a report)."""

    def _boxes(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (('Boxes', BOXES), ('Pump', BOXES_CALLEE)):
                with open(os.path.join(d, name + '.s7dcl'), 'w', encoding='utf-8') as f:
                    f.write(text)
            from TiaChangeReports.compare import Callees
            callees = Callees(FolderSnapshot(d))
            callees('Pump')                                            # load while the folder exists
            b = parse_block(BlockSource('Boxes', BOXES, '', 'Boxes.s7dcl'))
            return b, [Layout(n.rungs, b.interface, callees) for n in b.networks]

    @staticmethod
    def _view(lay, instr):
        return next(v for v in lay.views.values() if v.el.instr == instr)

    def test_no_add_pin_star(self):
        b = parse_block(_jumps_sd())
        _, (net, _) = self._boxes()
        for lay in [Layout(n.rungs, b.interface) for n in b.networks] + [net]:
            self.assertNotIn('#ffff00', lay.svg())

    def test_type_bold_in_a_cell_of_its_own(self):
        b = parse_block(_jumps_sd())
        svg = Layout(b.networks[0].rungs, b.interface).svg()
        self.assertIn('font-size="11" font-weight="bold">USInt</text>', svg)

    def test_open_eno_runs_on_in_the_top_rung_and_stops_short_below(self):
        from TiaChangeReports.render_lad import STUB
        _, (net, calc) = self._boxes()
        self.assertEqual(check(net), [])
        mv, call = self._view(net, 'Move'), self._view(net, 'CALL')
        segs, _ = net.wiring()
        ymove = net.ys[0]
        self.assertTrue(any(s[1] == s[3] == ymove and s[2] == net.right for s in segs))   # to the network's end
        self.assertGreater(net.right, net._elx(mv.el.eid) + mv.w)
        self.assertTrue(call.eno_stub and not mv.eno_stub)
        x = net._elx(call.el.eid) + call.lw + call.bw
        self.assertIn('x1="%.1f" y1="%.1f" x2="%.1f"' % (x, net.ys[1], x + STUB), net.svg())
        self.assertEqual(check(calc), [])

    def test_conversion_mark_where_the_operand_type_differs(self):
        from TiaChangeReports.render_lad import C_CONV, converted, operand_type
        b, (net, calc) = self._boxes()
        call = self._view(net, 'CALL')
        rows = {n: r for r, (n, _) in enumerate(call.lefts)}
        self.assertEqual(call.conv, {rows['speed'], rows['limit']})      # DInt and an element of DInt at Int pins;
        self.assertEqual(self._view(calc, 'Calculate').conv, {2})        # not Bool at Bool, not the in-out, IN2 DInt
        self.assertEqual((operand_type(b.interface, '#arr[1]'), operand_type(b.interface, '#arr')),
                         ('DInt', 'Array[0..3] of DInt'))
        self.assertIsNone(operand_type(b.interface, '#n.%X0'))
        self.assertFalse(converted('Array[0..3] of DInt', 'DInt'))
        jb = parse_block(_jumps_sd())
        jl, sw = (self._view(Layout(jb.networks[k].rungs, jb.interface), i) for k, i in ((2, 'JumpList'), (0, 'Switch')))
        self.assertEqual((jl.conv, sw.conv), ({1}, set()))              # USInt at JMP_LIST's K (UInt), as TIA shows it
        self.assertEqual(Layout(jb.networks[2].rungs, jb.interface).svg().count('fill="%s"' % C_CONV), 1)

    def test_no_conversion_mark_at_the_index_of_mux_and_demux(self):
        """MUX / DEMUX K is an index, not of the box's type: no mark for an Int there; IN<n> is of the type."""
        b = parse_block(BlockSource('Sel', MUXES, '', 'Sel.s7dcl'))
        mux, demux = (self._view(Layout(n.rungs, b.interface), i) for n, i in zip(b.networks, ('Mux', 'Demux')))
        rows = {n.lower(): r for r, (n, _) in enumerate(mux.lefts)}
        self.assertEqual(mux.conv, {rows['in1']})                        # #i at IN1 (Real), not at K
        self.assertEqual(demux.conv, set())

    def test_one_type_by_two_names_is_no_conversion(self):
        from TiaChangeReports.render_lad import converted
        for a, b in (('TOD', 'Time_Of_Day'), ('DT', 'Date_And_Time'), ('LTOD', 'LTime_Of_Day'), ('tod', 'TOD')):
            self.assertFalse(converted(a, b), (a, b))
            self.assertFalse(converted(b, a), (b, a))
        self.assertTrue(converted('TOD', 'LTOD'))
        self.assertTrue(converted('DT', 'LDT'))


# ---------------------------------------------------------------- network jump labels

class NetworkJumpLabels(unittest.TestCase):
    """A network's jump label read from both formats; renamed, added or removed, a change of the network; drawn
    over it as TIA does and marked."""

    DECL = '<LabelDeclaration UId="21">\n      <Label Name="stepA" />'      # network 4's own label, not the jumps

    def test_read_from_both_formats(self):
        xb, sb = parse_block(_xml_src(_jumps(), 'Jumps')), parse_block(_jumps_sd())
        self.assertEqual([n.label for n in xb.networks], ['', '', '', 'stepA', 'stepB'])
        self.assertEqual([n.label for n in sb.networks], [n.label for n in xb.networks])

    def test_a_label_alone_changes_the_network(self):
        """The reference pair: network 5 of Main, only its label renamed, was not reported."""
        xml = (_xml_src(_jumps(), 'Jumps'), _xml_src(_jumps((self.DECL, self.DECL.replace('stepA', 'stepX'))), 'Jumps'))
        sd = (_jumps_sd(), _jumps_sd(('Label(stepA)', 'Label(stepX)')))
        dropped = _jumps_sd(('        Label(stepB)\n', ''))
        for (b, a), state in ((xml, 'changed'), (sd, 'changed'), ((sd[0], dropped), 'removed'),
                              ((dropped, sd[0]), 'added')):
            (p,) = compare_blocks(b, a).nets
            self.assertEqual((p.state, p.label_state), ('changed', state))
            self.assertFalse(p.lad.changed)                             # the logic is the same
        p = compare_blocks(sd[0], sd[0], all_=True).nets[3]
        self.assertEqual((p.state, p.label_state), ('same', 'same'))

    def test_fbd_label_in_the_text(self):
        """An FBD network is shown as text: its label is the first line, from SimaticML as in the SD export (audit)."""
        from TiaChangeReports.page import network_html
        from TiaChangeReports.s7dcl import scl_lines
        lang = ('<ProgrammingLanguage>LAD</ProgrammingLanguage>', '<ProgrammingLanguage>FBD</ProgrammingLanguage>')
        xb = parse_block(_xml_src(_jumps(last=(lang,)), 'Jumps'))
        sb = parse_block(_jumps_sd(('S7_Language := "LAD";\n        S7_NetworkTitle := "MLC_J5"',
                                    'S7_Language := "FBD";\n        S7_NetworkTitle := "MLC_J5"')))
        x, s = xb.networks[4], sb.networks[4]
        self.assertEqual((x.lang, s.lang, x.label), ('FBD', 'FBD', 'stepB'))
        self.assertEqual(scl_lines(x.body), scl_lines(s.body))
        self.assertEqual(scl_lines(x.body)[0], 'Label(stepB)')
        after = _jumps(last=(lang, ('<Label Name="stepB" />', '<Label Name="stepY" />')))
        d = compare_blocks(_xml_src(_jumps(last=(lang,)), 'Jumps'), _xml_src(after, 'Jumps'))
        (p,) = d.nets
        self.assertEqual((p.state, p.label_state), ('changed', 'changed'))
        html = network_html(p, d.before, d.after)
        self.assertIn('stepB', html)
        self.assertIn('stepY', html)

    def test_drawn_over_the_network(self):
        from TiaChangeReports.render_lad import C_LABEL, CELL, FILL, LABEL_H, X0
        b = parse_block(_xml_src(_jumps(), 'Jumps'))
        n = b.networks[3]
        plain = Layout(n.rungs, b.interface)
        lay = Layout(n.rungs, b.interface, label=n.label)
        self.assertEqual(check(lay), [])
        self.assertEqual((lay.wiring(), lay.ys), (plain.wiring(), plain.ys))      # the logic's coordinates kept
        svg = lay.svg()
        box = '<rect x="%d" y="2" width="%d" height="%d" fill="%%s"/>' % (X0 - 1, CELL, LABEL_H)
        self.assertIn(box % C_LABEL, svg)
        self.assertIn('text-anchor="middle" font-size="11">stepA</text></g><g transform="translate(0,%d)">'
                      % (LABEL_H), svg)                                 # the rail starts under the box
        height = re.compile(r' height="(\d+)"')
        self.assertEqual(int(height.search(svg).group(1)), int(height.search(plain.svg()).group(1)) + LABEL_H)
        self.assertNotIn('class="jl"', plain.svg())
        for mark in ('changed', 'added', 'removed'):
            self.assertIn(box % FILL[mark], Layout(n.rungs, b.interface, label='stepA', mark=mark).svg())

    def test_on_the_page(self):
        from TiaChangeReports.page import network_html
        from TiaChangeReports.render_lad import FILL
        d = compare_blocks(_jumps_sd(), _jumps_sd(('Label(stepA)', 'Label(stepX)')))
        html = network_html(d.nets[0], d.before, d.after)
        self.assertEqual(html.count('fill="%s"/>' % FILL['removed']) + html.count('fill="%s"/>' % FILL['added']), 2)
        self.assertIn('>stepA</text>', html)
        self.assertIn('>stepX</text>', html)

# ---------------------------------------------------------------- findings of real archive compares

def _call_net(*calls):
    """A LAD network: a contact, then each call of `calls` ((block, {pin: operand}), ...) in series."""
    boxes = ''.join('            "%s"(\n%s\n            )\n' % (
        name, ',\n'.join('                %s := %s' % kv for kv in pins.items())) for name, pins in calls)
    return ('FUNCTION_BLOCK "Caller"\n    VAR\n        a : Bool;\n        c : Int;\n        e : Int;\n    END_VAR\n'
            '    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            Contact( #a )\n'
            + boxes + '        END_RUNG\n    END_NETWORK\nEND_FUNCTION_BLOCK\n')


def _call_diff(before, after):
    bb, ab = parse_block(src(before, '', 'Caller')), parse_block(src(after, '', 'Caller'))
    (p,) = pair_networks(bb, ab)
    p.lad = NetDiff(Graph(p.before.rungs), Graph(p.after.rungs))
    return bb, ab, p


class RenamedCalledBlock(unittest.TestCase):
    """A call of a renamed block: one changed box, its name marked as a changed operand, not a box
    deleted and a box added with the name inside the unmarked box."""

    def boxes(self, p):
        return ([e for e in p.lad.b.elements.values() if e.instr == 'CALL'],
                [e for e in p.lad.a.elements.values() if e.instr == 'CALL'])

    def test_box_is_changed_and_names_the_call_as_what_changed(self):
        _, _, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('ScaleValue', {'value': '#c'})))
        (x,), (y,) = self.boxes(p)
        self.assertEqual((p.lad.status[x.eid], p.lad.status[y.eid]), ('changed', 'changed'))
        self.assertEqual(changed_params(x, y), {'#call'})

    def test_mark_lies_on_the_name_red_before_green_after(self):
        bb, ab, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('ScaleValue', {'value': '#c'})))
        for blk, net, box, side in ((bb, p.before, self.boxes(p)[0][0], 'removed'),
                                    (ab, p.after, self.boxes(p)[1][0], 'added')):
            lay = Layout(net.rungs, blk.interface)
            (m,) = [m for m in lay.marks(p.lad.status, p.lad.other, side) if m[0] == box.eid]
            st, layer, x, y, w, h = m[1:]
            view = lay.views[box.eid]
            self.assertEqual((st, layer), (side, 'box'))     # on the box's fill, below its texts
            self.assertLess(w, view.bw)                      # the name, not the whole head
            self.assertGreaterEqual(w, render_lad.tw(view.title, render_lad.FONT, True))
            self.assertIn('<rect class="hl %s"' % side, lay.svg(p.lad.status, p.lad.other, side=side))

    def test_changed_pin_of_a_renamed_call_in_the_colour_of_its_side(self):
        bb, _, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('ScaleValue', {'value': '#e'})))
        box = self.boxes(p)[0][0]
        lay = Layout(p.before.rungs, bb.interface)
        got = [m[1] for m in lay.marks(p.lad.status, p.lad.other, 'removed') if m[0] == box.eid]
        self.assertEqual(got, ['removed'] * 2)               # the variable at the pin; the block's name

    def test_page_marks_the_name_by_its_pane(self):
        from TiaChangeReports import page
        bb, ab, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('ScaleValue', {'value': '#c'})))
        lb, la = Layout(p.before.rungs, bb.interface), Layout(p.after.rungs, ab.interface)
        self.assertIn('<rect class="hl removed"', page._lad_pane(lb, la, p.lad, 'removed'))
        self.assertIn('<rect class="hl added"', page._lad_pane(la, lb, p.lad, 'added'))

    def test_changed_pin_of_a_renamed_call_marked_too(self):
        _, _, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('ScaleValue', {'value': '#e'})))
        (x,), (y,) = self.boxes(p)
        self.assertEqual(changed_params(x, y), {'#call', 'value'})

    def test_another_block_with_other_pins_stays_removed_and_added(self):
        _, _, p = _call_diff(_call_net(('Scale', {'value': '#c'})), _call_net(('Limit', {'high': '#c', 'low': '#e'})))
        (x,), (y,) = self.boxes(p)
        self.assertEqual((p.lad.status[x.eid], p.lad.status[y.eid]), ('removed', 'added'))

    def test_the_same_call_goes_before_a_rename(self):
        """Scale deleted in front of Limit: Limit keeps its box, Scale is deleted and not taken for a rename."""
        pins = {'value': '#c'}
        _, _, p = _call_diff(_call_net(('Scale', pins), ('Limit', pins)), _call_net(('Limit', pins)))
        b, (y,) = self.boxes(p)
        self.assertEqual({e.call: p.lad.status[e.eid] for e in b}, {'Scale': 'removed', 'Limit': 'same'})
        self.assertEqual(p.lad.status[y.eid], 'same')


class HmiStyleLeavesLadMarks(unittest.TestCase):
    """The HMI part's pane label and the LAD marks share the class hl: its rule hid every LAD mark of a
    report with HMI objects. The rules for the label name the element."""

    def rules(self):
        from TiaChangeReports import hmi
        css = hmi.css()
        return [r.strip() for r in re.findall(r'([^{}]+)\{[^{}]*\}', css) if re.search(r'\.hl\b', r)]

    def test_no_rule_reaches_a_mark_outside_the_hmi_panes(self):
        rules = [s.strip() for r in self.rules() for s in r.split(',')]
        self.assertTrue(rules)
        for sel in rules:
            self.assertRegex(sel, r'div\.hl\b|\.hps\b', sel)

    def test_marks_are_rects_of_that_class(self):
        """What the rule must leave alone."""
        d, lb, _ = _marked(MARK, MARK.replace('speed := 5', 'speed := 6'))
        self.assertIn('<rect class="hl ', lb.svg(d.status, d.other))


class ChangedOperandsAsCode(unittest.TestCase):
    """What changed in a LAD network is marked as a changed SCL line: red before, green after."""

    def test_contact_operand(self):
        d, lb, la = _marked(MARK, MARK.replace('Contact( #b )', 'Contact( #q )'))
        for lay, side in ((lb, 'removed'), (la, 'added')):
            got = {m[1] for m in lay.marks(d.status, d.other, side)}
            self.assertEqual(got, {side})
            self.assertIn('<rect class="hl %s"' % side, lay.svg(d.status, d.other, side=side))
            self.assertNotIn('<rect class="hl changed"', lay.svg(d.status, d.other, side=side))

    def test_box_pin_keeps_its_place(self):
        """The same marks as before, only in another colour."""
        d, lb, _ = _marked(MARK, MARK.replace('speed := 5', 'speed := 6'))
        self.assertEqual([m[2:] for m in lb.marks(d.status, d.other, 'removed')],
                         [m[2:] for m in lb.marks(d.status, d.other)])

    def test_moved_element_stays_moved(self):
        for st in ('moved',):
            d, lb, _ = _marked(MARK, MARK.replace('speed := 5', 'speed := 6'))
            status = {k: st for k in d.status}
            self.assertEqual({m[1] for m in lb.marks(status, d.other, 'removed')}, {st})

    def test_jump_label_renamed_on_the_page(self):
        from TiaChangeReports.page import network_html
        from TiaChangeReports.render_lad import FILL
        d = compare_blocks(_jumps_sd(), _jumps_sd(('Label(stepA)', 'Label(stepX)')))
        html = network_html(d.nets[0], d.before, d.after)
        self.assertEqual((html.count('fill="%s"/>' % FILL['removed']), html.count('fill="%s"/>' % FILL['added']),
                          html.count('fill="%s"/>' % FILL['changed'])), (1, 1, 0))


class OnlyTheVariableAtAPin(unittest.TestCase):
    """Only the variable at a pin changed: only the variable is marked; the pin name, its line and the box
    stay as they are."""

    def box_marks(self, before, after):
        d, lb, _ = _marked(before, after)
        box = _box(d.b)
        view = lb.views[box.eid]
        k = next(k for k, i in enumerate(lb.info) if any(p[0] is box for p in i['placed']))
        ex = next(p[1] for p in lb.info[k]['placed'] if p[0] is box)
        return [m[2:] for m in lb.marks(d.status, d.other) if m[0] == box.eid], view, ex + view.lw

    def test_input_pin(self):
        marks, view, bx = self.box_marks(MARK, MARK.replace('speed := 5', 'speed := 6'))
        (layer, x, y, w, h), = marks
        self.assertEqual(layer, 'under')                     # no mark on the box
        self.assertLessEqual(x + w, bx - 8)                  # ends before the pin's line, which starts 8 before the box

    def test_output_pin(self):
        marks, view, bx = self.box_marks(MARK, MARK.replace('state => #c', 'state => #q'))
        (layer, x, y, w, h), = marks
        self.assertEqual(layer, 'under')
        self.assertGreaterEqual(x, bx + view.bw + 8)         # starts after the pin's line

    def test_pin_without_a_variable_marks_its_name(self):
        """Nothing else to mark: the pin changed from a variable to a wire shows on the side that has no variable."""
        from TiaChangeReports.render_lad import View
        d, lb, _ = _marked(MARK, MARK.replace('speed := 5', 'speed := 6'))
        box = _box(d.b)
        view = lb.views[box.eid]
        r = view.pinrow['speed'][1]
        view.lefts[r] = (view.lefts[r][0], [])
        self.assertEqual([m[0] for m in View.marks(view, 0, 0, 'changed', {'speed'})], ['box'])


class ProgramBlockAndTypeNotCompared(unittest.TestCase):
    """A deleted or new block has no change to hold against its type's: no link, no "differs"; each
    stays on the page under its own heading. The link and the merged object stay where the change is the same."""

    def run_(self, before, after):
        return LibraryInstances.run_(self, before, after)

    def link(self, ds):
        return sorted((d.path_a or d.path_b, d.state, bool(d.library), d.library_differs) for d in ds)

    def test_deleted_block_whose_type_changed(self):
        b, a, ds = self.run_({**_prep(), **_lib('1.0.0')}, _lib('1.0.1', edit=True))
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'changed', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'deleted', False, False)])
        html = render(ds, b.label, a.label)
        self.assertNotIn('library type', _text(html))

    def test_deleted_block_whose_type_only_changed_version(self):
        _, _, ds = self.run_({**_prep(), **_lib('1.0.0')}, _lib('1.0.1'))
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'version', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'deleted', False, False)])

    def test_new_block_whose_type_changed(self):
        _, _, ds = self.run_(_lib('1.0.0'), {**_prep(edit=True), **_lib('1.0.1', edit=True)})
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'changed', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'new', False, False)])

    def test_changed_block_whose_type_is_new_or_deleted(self):
        _, _, ds = self.run_(_prep(), {**_prep(edit=True), **_lib('1.0.0')})
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'new', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'changed', False, False)])
        _, _, ds = self.run_({**_prep(), **_lib('1.0.0')}, _prep(edit=True))
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'deleted', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'changed', False, False)])

    def test_deleted_with_its_type_is_each_its_own_removal(self):
        """An instance deleted says so and nothing else; a type removed from the project says so."""
        b, a, ds = self.run_({**_prep(), **_lib('1.0.0')}, {})
        self.assertEqual(self.link(ds), [(LIB + 'PrepareFillData.s7dcl', 'deleted', False, False),
                                         ('plc/blocks/Bottling/PrepareFillData.s7dcl', 'deleted', False, False)])
        self.assertNotIn('library type', _text(render(ds, b.label, a.label)))

    def test_new_with_its_type_stays_one_object(self):
        _, _, ds = self.run_({}, {**_prep(), **_lib('1.0.0')})
        self.assertEqual(self.link(ds), [('plc/blocks/Bottling/PrepareFillData.s7dcl', 'new', True, False)])

    def removal(self, *args):
        """(--json result, page, list) of a removed type and its deleted block, with args."""
        import json
        from TiaChangeReports.__main__ import main
        import contextlib
        import io
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        before, after = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(before, {**_prep(), **_lib('1.0.0'), 'plc/types/D.s7dcl': UDT_D})
        _write(after, {'plc/types/D.s7dcl': UDT_D})
        page = os.path.join(tmp.name, 'r.html')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', page, '--json', *args])
        res = json.loads(out.getvalue())
        with open(page, encoding='utf-8') as f:
            html = f.read()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', page, *args])
        return res, html, [l for l in out.getvalue().splitlines() if not l.endswith('r.html')]

    def test_removal_shows_its_content(self):
        """A removed type or deleted block, as a new one: its interface and networks, in the page, the list, --json;
        each its own object, not linked."""
        res, html, listing = self.removal()
        nets = [[n['state'] for n in b['networks']] for b in res['blocks']]
        self.assertTrue(nets[0] and nets[0] == nets[1] and set(nets[0]) == {'deleted'}, nets)
        self.assertEqual(sorted((b['state'], b['interface'], 'libraryType' in b) for b in res['blocks']),
                         [('deleted', True, False)] * 2)
        self.assertEqual(len(re.findall(r'<section class="blk">', html)), 2)
        self.assertEqual(html.count('<b>Interface</b>'), 2)
        self.assertEqual(len(re.findall(r'<span class="st deleted">removed</span>', html)), 2 * len(nets[0]))
        self.assertEqual(listing.count('deleted  FB          PrepareFillData  (interface)'), 2)
        self.assertEqual(sum(l.startswith('    deleted ') for l in listing), 2 * len(nets[0]))

    def test_removal_listed_shows_no_content(self):
        """--new-blocks-listed: its header, no interface, no networks, in the page, the list, --json."""
        res, html, listing = self.removal('--new-blocks-listed')
        self.assertEqual(sorted((b['state'], b['interface'], b['networks'], 'libraryType' in b) for b in res['blocks']),
                         [('deleted', False, [], False)] * 2)
        self.assertEqual(len(re.findall(r'<section class="blk">', html)), 2)
        self.assertEqual(re.findall(r'<div class="nw[ "]', html), [])
        self.assertEqual(listing, ['deleted  FB          PrepareFillData'] * 2)

    def test_removal_named_by_block_still_shows_its_content(self):
        """--block asks for the block itself: as on the page."""
        import json
        from TiaChangeReports.__main__ import main
        import contextlib
        import io
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        before, after = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(before, {**_prep(), 'plc/types/D.s7dcl': UDT_D})
        _write(after, {'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', os.path.join(tmp.name, 'r.html'), '--json', '--block', 'PrepareFillData'])
        (b,) = json.loads(out.getvalue())['blocks']
        self.assertTrue(b['networks'])


class MovedWithItsType(unittest.TestCase):
    """A block moved to another folder together with its library type: the name is not unique among
    all files, it is among the program blocks and among the types; one moved block each, not deleted and new."""

    OLD, NEW = 'plc/types/Old/Tank.s7dcl', 'plc/types/New/Tank.s7dcl'
    LOLD, LNEW = 'library/types/Old/Tank/Tank.s7dcl', 'library/types/New/Tank/Tank.s7dcl'
    UDT = UDT_D.replace('"D"', '"Tank"').replace('x : Bool', 'level : Int;\n        full : Bool')

    def pairs(self, before, after):
        b, a = RenamedBlocks.folders(self, dict.fromkeys(before, self.UDT), dict.fromkeys(after, self.UDT))
        return [x for x in pair_blocks(b, a) if 'D.s7dcl' not in (x[0] or x[1])]

    def test_program_block_and_type_moved(self):
        self.assertEqual(sorted(self.pairs((self.OLD, self.LOLD), (self.NEW, self.LNEW))),
                         sorted([(self.OLD, self.NEW), (self.LOLD, self.LNEW)]))

    def test_moved_with_other_content(self):
        """Not alike enough for the pairing by content: the name alone pairs them."""
        b, a = RenamedBlocks.folders(self, {self.OLD: UDT_D.replace('"D"', '"Tank"'), self.LOLD: self.UDT},
                                     {self.NEW: 'TYPE "Tank"\n    STRUCT\n        other : Real;\n    END_STRUCT;\n'
                                                'END_TYPE\n', self.LNEW: self.UDT})
        self.assertIn((self.OLD, self.NEW), pair_blocks(b, a))

    def test_program_block_moved_its_type_new(self):
        self.assertEqual(sorted(self.pairs((self.OLD,), (self.NEW, self.LNEW)), key=str),
                         sorted([(self.OLD, self.NEW), (None, self.LNEW)], key=str))

    def test_program_block_and_library_type_are_not_paired_by_name(self):
        self.assertEqual(sorted(self.pairs((self.OLD,), (self.LNEW,)), key=str),
                         sorted([(self.OLD, None), (None, self.LNEW)], key=str))

    def test_same_name_in_two_plcs_is_not_paired_by_name(self):
        """Other content in each folder, not alike: which is which cannot be told by a name that is not unique."""
        b, a = RenamedBlocks.folders(self, {'plc/A/Tank.s7dcl': self.UDT, 'plc/B/Tank.s7dcl': self.UDT},
                                     {'plc/A/x/Tank.s7dcl': UDT_D.replace('"D"', '"Tank"').replace('x : Bool', 'r : Real'),
                                      'plc/B/x/Tank.s7dcl': UDT_D.replace('"D"', '"Tank"').replace('x : Bool', 's : Real')})
        got = [x for x in pair_blocks(b, a) if 'D.s7dcl' not in (x[0] or x[1])]
        self.assertEqual(sorted(got, key=str), sorted([('plc/A/Tank.s7dcl', None), ('plc/B/Tank.s7dcl', None),
                                                       (None, 'plc/A/x/Tank.s7dcl'), (None, 'plc/B/x/Tank.s7dcl')],
                                                      key=str))


class SameChangeAcrossExports(unittest.TestCase):
    """What only the two exports tell apart is no other change: a program block and its library type
    with one edit are one object, whatever each export writes around it."""

    LIB_UDT, PLC_UDT = 'library/types/Tank/Tank.s7dcl', 'plc/types/Tank.s7dcl'
    LIB_XML, PLC_XML = 'library/types/Main/Main.xml', 'plc/blocks/Main.xml'

    def udt(self, *members):
        return 'TYPE "Tank"\n    STRUCT\n%s\n    END_STRUCT;\nEND_TYPE\n' % '\n'.join('        ' + m for m in members)

    def one_object(self, before, after):
        ds = [d for d in LibraryInstances.run_(self, before, after)[2] if 'D.s7dcl' not in (d.path_a or d.path_b)]
        self.assertEqual([(d.path_a, bool(d.library), d.library_differs) for d in ds],
                         [(self.PLC_XML if ds[0].path_a.endswith('.xml') else self.PLC_UDT, True, False)])

    def udts(self, plc_before, plc_after, lib_before, lib_after):
        return ({self.PLC_UDT: self.udt(*plc_before), self.LIB_UDT: self.udt(*lib_before)},
                {self.PLC_UDT: self.udt(*plc_after), self.LIB_UDT: self.udt(*lib_after)})

    def test_member_added_with_setpoint_false_on_one_line(self):
        """Taking the setting out of the program block's pragma must not leave an empty one behind."""
        self.one_object(*self.udts(['a : Int;'], ['a : Int;', '{ S7_Setpoint := "False" }', 'b : Bool;'],
                                   ['a : Int;'], ['a : Int;', 'b : Bool;']))

    def test_member_added_with_setpoint_true(self):
        """A library type's .s7dcl export writes no Setpoint at all: the program block's says nothing of the change."""
        self.one_object(*self.udts(['a : Int;'], ['a : Int;', '{ S7_Setpoint := "True" }', 'b : Bool;'],
                                   ['a : Int;'], ['a : Int;', 'b : Bool;']))

    def test_pragma_written_over_several_lines(self):
        """The setting gone, the same pragma on one line in the type and over three in the program block."""
        self.one_object(*self.udts(
            ['a : Int;'],
            ['a : Int;', '{', '    S7_Access := "ReadOnly";', '    S7_Setpoint := "True"', '}', 'b : Bool;'],
            ['a : Int;'],
            ['a : Int;', '{ S7_Access := "ReadOnly" }', 'b : Bool;']))

    def test_another_pragma_is_another_change(self):
        (d,) = [d for d in LibraryInstances.run_(self, *self.udts(
            ['a : Int;'], ['a : Int;', '{ S7_Access := "ReadOnly" }', 'b : Bool;'],
            ['a : Int;'], ['a : Int;', 'b : Bool;']))[2] if d.library]
        self.assertTrue(d.library_differs)

    def xml(self, created='2026-01-01T00:00:00.0000000Z', edit=False, cultures=False, offset=0):
        text = _fixture()
        text = re.sub(r'<Created>[^<]*</Created>', '<Created>%s</Created>' % created, text)
        if edit:
            text = text.replace('Member Name="big"', 'Member Name="large"').replace('#big', '#large')
        if offset:                                          # TIA numbers the objects per export
            text = re.sub(r'\bID="(\w+)"', lambda m: 'ID="%X"' % (int(m.group(1), 16) + offset), text)
        if cultures:                                        # the other order, one more language
            text = re.sub(r'( *)<MultilingualTextItem ID="(\w+)" CompositionName="Items">(.*?)</MultilingualTextItem>',
                          lambda m: ('%s<MultilingualTextItem ID="%s9" CompositionName="Items"><AttributeList>'
                                     '<Culture>de-DE</Culture><Text /></AttributeList>'
                                     '</MultilingualTextItem>\n' % (m.group(1), m.group(2))) + m.group(0),
                          text, flags=re.S)
        return text

    def test_xml_differing_in_the_export_time_only(self):
        self.one_object({self.PLC_XML: self.xml('2026-01-01T00:00:01.0000000Z'),
                         self.LIB_XML: self.xml('2026-01-01T00:00:02.0000000Z')},
                        {self.PLC_XML: self.xml('2026-01-01T00:00:03.0000000Z', edit=True),
                         self.LIB_XML: self.xml('2026-01-01T00:00:04.0000000Z', edit=True)})

    def test_xml_with_other_numbers_and_languages(self):
        """The report shows one language, and TIA numbers and orders the rest per export."""
        self.one_object({self.PLC_XML: self.xml(), self.LIB_XML: self.xml(offset=16, cultures=True)},
                        {self.PLC_XML: self.xml(edit=True), self.LIB_XML: self.xml(edit=True, offset=32)})

    def test_xml_with_another_edit_differs(self):
        ds = LibraryInstances.run_(self, {self.PLC_XML: self.xml(), self.LIB_XML: self.xml()},
                                   {self.PLC_XML: self.xml(edit=True),
                                    self.LIB_XML: self.xml().replace('Member Name="stop"', 'Member Name="halt"')
                                                            .replace('#stop', '#halt')})[2]
        (d,) = [d for d in ds if d.library]
        self.assertTrue(d.library_differs)


class RealDifferencesStayListed(unittest.TestCase):
    """A block and its type are one entry only when their change is really the same: no rule about how a
    name is written. Anything else keeps both entries, the block labelled: hiding a real change is the worst failure."""

    PLC, LIB_FC = 'plc/blocks/Job.s7dcl', 'library/types/Job/Job.s7dcl'
    PLC_T, LIB_T = 'plc/types/Tank.s7dcl', 'library/types/Tank/Tank.s7dcl'

    def job(self, call='Scale', limit='1', head='', tail='', member='x'):
        return ('FUNCTION "Job" : Void\n    VAR_INPUT\n        a : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n'
                '    NETWORK\n%s        "%s"(value := #a);\n        #a := %s;\n        "Data".%s := 1;\n%s    END_NETWORK\n'
                'END_FUNCTION\n' % (head, call, limit, member, tail))

    def run_fc(self, plc, lib):
        """plc, lib: (before kwargs, after kwargs) of Job."""
        return LibraryInstances.run_(self, {self.PLC: self.job(**plc[0]), self.LIB_FC: self.job(**lib[0])},
                                     {self.PLC: self.job(**plc[1]), self.LIB_FC: self.job(**lib[1])})

    def state(self, ds):
        return sorted((d.path_a, bool(d.library), d.library_differs) for d in ds if 'D.s7dcl' not in d.path_a)

    def both(self, ds):
        self.assertEqual(self.state(ds), [(self.LIB_FC, False, False), (self.PLC, True, True)])

    def test_called_name_with_a_colon_in_the_type(self):
        self.both(self.run_fc(({'call': 'LibScale'}, {'call': 'LibScale', 'limit': '2'}),
                              ({'call': 'Lib:Scale'}, {'call': 'LibScale', 'limit': '2'}))[2])

    def test_type_still_writes_the_old_called_name(self):
        self.both(self.run_fc(({'call': 'Lib:Scale'}, {'call': 'LibScale', 'limit': '2'}),
                              ({'call': 'Lib:Scale'}, {'call': 'Lib:Scale', 'limit': '2'}))[2])

    def test_data_type_with_a_project_suffix(self):
        def tank(of, count='1'):
            return ('TYPE "Tank"\n    STRUCT\n        deck : Array[0..%s] of %s;\n        full : Bool;\n    END_STRUCT;\n'
                    'END_TYPE\n' % (count, of))
        ds = LibraryInstances.run_(self, {self.PLC_T: tank('_.Deck_2'), self.LIB_T: tank('_.Deck')},
                                   {self.PLC_T: tank('_.Deck', '2'), self.LIB_T: tank('_.Deck', '2')})[2]
        self.assertEqual(self.state(ds), [(self.LIB_T, False, False), (self.PLC_T, True, True)])

    def test_member_in_another_case(self):
        self.both(self.run_fc(({}, {'limit': '2', 'member': 'FG'}), ({}, {'limit': '2', 'member': 'fg'}))[2])

    def test_another_block_called(self):
        self.both(self.run_fc(({}, {'limit': '2'}), ({}, {'call': 'Limit', 'limit': '2'}))[2])

    def test_same_line_added_at_another_place(self):
        """The same lines removed and added, but not the same text after it."""
        line = '        #a := 9;\n'
        self.both(self.run_fc(({}, {'head': line}), ({}, {'tail': line}))[2])

    def test_same_line_added_after_another_of_two_equal_lines(self):
        """Even the line in front of it is the same."""
        same, new = '        #a := 7;\n', '        #a := 9;\n'
        self.both(self.run_fc(({'tail': same + same}, {'tail': same + new + same}),
                              ({'tail': same + same}, {'tail': same + same + new}))[2])

    def test_same_edit_with_a_lasting_difference_elsewhere_is_one_entry(self):
        """Block and type differ on both sides in one line; the change itself is the same."""
        (d,) = [d for d in self.run_fc(({'call': 'A'}, {'call': 'A', 'limit': '2'}),
                                       ({'call': 'B'}, {'call': 'B', 'limit': '2'}))[2] if d.library]
        self.assertFalse(d.library_differs)

    def test_indentation_blank_line_and_semicolon_a_user_changed(self):
        """Only the two exports' own differences are ignored, not what a user typed."""
        same = '        #a := 9;\n'
        for name, line in (('indentation', '            #a := 9;\n'), ('blank line', '\n' + same),
                           ('semicolon', '        #a := 9\n')):
            with self.subTest(name):
                self.both(self.run_fc(({}, {'limit': '2', 'tail': same}), ({}, {'limit': '2', 'tail': line}))[2])

    def test_setpoint_in_a_simaticml_export_counts(self):
        """Both exports write it there, so it can be compared."""
        plc, lib = 'plc/blocks/Main.xml', 'library/types/Main/Main.xml'
        on = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                '<Member Name="big" Datatype="Bool"><AttributeList><BooleanAttribute Name="SetPoint">'
                                'true</BooleanAttribute></AttributeList></Member>')
        self.assertNotEqual(on, _fixture())
        ds = LibraryInstances.run_(self, {plc: _fixture(), lib: _fixture()}, {plc: on, lib: _fixture()})[2]
        self.assertEqual([(d.path_a, d.state) for d in ds if d.block.name == 'Main'], [(plc, 'changed')])
        edit = 'Member Name="stop"', 'Member Name="halt"'
        ds = LibraryInstances.run_(self, {plc: _fixture(), lib: _fixture()},
                                   {plc: on.replace(*edit), lib: _fixture().replace(*edit)})[2]
        (d,) = [d for d in ds if d.library]
        self.assertTrue(d.library_differs)

    def test_setpoint_a_user_changed_in_the_program_block_stays_on_its_entry(self):
        """The .s7dcl of a type writes no Setpoint, so it is left out of the comparison; the block's own entry shows it."""
        def tank(mark=''):
            return 'TYPE "Tank"\n    STRUCT\n        %sfull : Bool;\n    END_STRUCT;\nEND_TYPE\n' % mark
        b, a, ds = LibraryInstances.run_(self, {self.PLC_T: tank('{ S7_Setpoint := "False" }\n        '), self.LIB_T: tank()},
                                         {self.PLC_T: tank('{ S7_Setpoint := "True" }\n        '), self.LIB_T: tank()})
        (d,) = [d for d in ds if 'D.s7dcl' not in d.path_a]
        self.assertEqual((d.path_a, d.state, bool(d.itf_changed)), (self.PLC_T, 'changed', True))
        self.assertIn('<span class="cb on', render(ds, b.label, a.label))

    def test_label_says_what_differs(self):
        b, a, ds = self.run_fc(({}, {'limit': '2'}), ({}, {'limit': '3'}))
        html = render(ds, b.label, a.label)
        self.assertIn('differs from library type Job', _text(html))
        self.assertNotIn('changed differently', _text(html))
        self.assertRegex(html, r'<span class="lib differs" title="This block&#x27;s text is not the same as library type '
                               r'Job&#x27;s\. Compare the two entries in this report\.">')


class ComparisonSeesWhatAUserChanged(unittest.TestCase):
    """What a user can change counts when a block and its type are compared, so the type's entry
    does not go while its change is not the block's."""

    PLC, LIB = 'plc/blocks/Main.xml', 'library/types/Main/Main.xml'

    def fc(self, ret='Void'):
        return _fixture().replace('SW.Blocks.OB', 'SW.Blocks.FC').replace(
            '<Section Name="Temp">', '<Section Name="Return"><Member Name="Ret_Val" Datatype="%s" /></Section>\n'
                                     '  <Section Name="Temp">' % ret)

    def edit(self, text):
        """An edit both make: the two then have a change to compare."""
        return text.replace('Member Name="stop"', 'Member Name="halt"')

    def differs(self, before, plc, lib):
        ds = LibraryInstances.run_(self, {self.PLC: before, self.LIB: before}, {self.PLC: plc, self.LIB: lib})[2]
        (d,) = [d for d in ds if d.library]
        self.assertTrue(d.library_differs)
        self.assertIn(self.LIB, [x.path_a for x in ds])       # the type's entry stays

    def test_return_type_of_a_function(self):
        self.differs(self.fc(), self.edit(self.fc()), self.edit(self.fc('Int')))

    def test_type_of_an_instance_db(self):
        from TiaChangeReports.source import _shown_lines
        from TiaChangeReports.s7dcl import Block, Interface
        def lines(of):
            return _shown_lines(Block('Inst', '', Interface(), [], 'DATA_BLOCK', 'Inst : %s' % of, {}), {'Inst'})
        self.assertNotEqual(lines('Filler'), lines('Pump'))
        self.assertIn('# : Filler', lines('Filler')[0])

    def test_start_value_of_an_element(self):
        def text(v):
            return _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                      '<Member Name="arr" Datatype="Array[0..1] of Int"><Subelement Path="1"><StartValue>'
                                      '%s</StartValue></Subelement></Member>' % v)
        self.differs(text('5'), self.edit(text('5')), self.edit(text('6')))

    def test_indentation_in_a_simaticml_network(self):
        spaced = _fixture().replace('<NewLine UId="23" />', '<NewLine UId="23" /><Blank Num="4" UId="9023" />')
        self.assertNotEqual(spaced, _fixture())
        self.differs(_fixture(), self.edit(_fixture()), self.edit(spaced))

    def test_blank_line_in_a_simaticml_network(self):
        spaced = _fixture().replace('<NewLine UId="23" />', '<NewLine Num="2" UId="23" />')
        self.assertNotEqual(spaced, _fixture())
        self.differs(_fixture(), self.edit(_fixture()), self.edit(spaced))

    def test_own_name_in_a_string_counts(self):
        """Only the declaration holds the name that tells a block from its type."""
        def fc(name, text, limit='1'):
            return ('FUNCTION "%s" : Void\n    VAR_INPUT\n        a : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n'
                    "    NETWORK\n        #s := '%s';\n        #a := %s;\n    END_NETWORK\nEND_FUNCTION\n" % (name, text, limit))
        plc, lib = 'plc/blocks/Foo.s7dcl', 'library/types/Foo/Foo.s7dcl'
        ds = LibraryInstances.run_(self, {plc: fc('Foo', 'Foo'), lib: fc('Foo', 'Foo')},
                                   {'plc/blocks/Bar.s7dcl': fc('Bar', 'Bar', '2'), lib: fc('Foo', 'Foo', '2')})[2]
        (d,) = [d for d in ds if d.library]
        self.assertTrue(d.library_differs)

    def test_own_name_in_the_declaration_tells_nothing(self):
        """A type's block can be declared otherwise than the type."""
        def fc(name, limit='1'):
            return ('FUNCTION "%s" : Void\n    VAR_INPUT\n        a : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n'
                    '    NETWORK\n        #a := %s;\n    END_NETWORK\nEND_FUNCTION\n' % (name, limit))
        plc, lib = 'plc/blocks/Foo.s7dcl', 'library/types/Foo/Foo.s7dcl'
        ds = LibraryInstances.run_(self, {plc: fc('Foo'), lib: fc('Foo_1')}, {plc: fc('Foo', '2'), lib: fc('Foo_1', '2')})[2]
        (d,) = [d for d in ds if 'D.s7dcl' not in d.path_a]
        self.assertEqual((d.path_a, d.library_differs), (plc, False))

    def test_two_copies_one_differs_keeps_the_type(self):
        """The label says to compare the two entries: the type's stays while any copy differs."""
        def fc(limit='1', tail=''):
            return ('FUNCTION "Job" : Void\n    VAR_INPUT\n        a : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n'
                    '    NETWORK\n        #a := %s;\n%s    END_NETWORK\nEND_FUNCTION\n' % (limit, tail))
        one, two, lib = 'plc/PLC_A/blocks/Job.s7dcl', 'plc/PLC_B/blocks/Job.s7dcl', 'library/types/Job/Job.s7dcl'
        ds = LibraryInstances.run_(self, {one: fc(), two: fc(), lib: fc()},
                                   {one: fc('2'), two: fc('2', '        #a := 9;\n'), lib: fc('2')})[2]
        self.assertEqual(sorted((d.path_a, d.library_differs) for d in ds if 'D.s7dcl' not in d.path_a),
                         [(lib, False), (one, False), (two, True)])


class UdtInTheShapeOfARealExport(unittest.TestCase):
    """A real UDT export writes its name on the line after TYPE, so the declaration line holds none."""

    def udt(self, name, member='full'):
        return 'TYPE\n    %s : STRUCT\n        level : Int;\n        %s : Bool;\n    END_STRUCT;\n\nEND_TYPE\n' % (name, member)

    def test_renamed_udt_is_listed(self):
        """Paired by content; nothing else changed. It used to count as unchanged and was on no list."""
        b, a, ds = LibraryInstances.run_(self, {'plc/types/Old/Tank.s7dcl': self.udt('Tank')},
                                         {'plc/types/New/Vessel.s7dcl': self.udt('Vessel')})
        (d,) = [d for d in ds if 'D.s7dcl' not in d.path_a]
        self.assertEqual((d.state, d.names), ('changed', ('Vessel', 'Tank')))
        self.assertIn('Tank → Vessel', _text(render(ds, b.label, a.label)))

    def test_own_name_after_type_tells_nothing(self):
        plc, lib = 'plc/types/Tank.s7dcl', 'library/types/Tank/Tank.s7dcl'
        ds = LibraryInstances.run_(self, {plc: self.udt('Tank'), lib: self.udt('Tank_1')},
                                   {plc: self.udt('Tank', 'empty'), lib: self.udt('Tank_1', 'empty')})[2]
        (d,) = [d for d in ds if 'D.s7dcl' not in d.path_a]
        self.assertEqual((d.path_a, d.library_differs), (plc, False))

    def test_moved_unchanged(self):
        _, _, ds = LibraryInstances.run_(self, {'plc/types/Old/Tank.s7dcl': self.udt('Tank')},
                                         {'plc/types/New/Tank.s7dcl': self.udt('Tank')})
        self.assertEqual([d.state for d in ds if 'D.s7dcl' not in d.path_a], ['moved'])


class MovedToAnotherFolder(unittest.TestCase):
    """A block that only moved to another folder: tagged moved, with its old and new folder, in the tree and
    the report, collapsed, without content, counted apart."""

    OLD, NEW = 'plc/types/Old/Tank.s7dcl', 'plc/types/New/Tank.s7dcl'
    LOLD, LNEW = 'library/types/Old/Tank/Tank.s7dcl', 'library/types/New/Tank/Tank.s7dcl'
    UDT = 'TYPE "Tank"\n    STRUCT\n        level : Int;\n        full : Bool;\n    END_STRUCT;\nEND_TYPE\n'
    OTHER = UDT.replace('full', 'empty')

    def run_(self, before, after, **kw):
        return LibraryInstances.run_(self, before, after, **kw)

    def states(self, ds):
        return sorted(((d.path_b, d.path_a, d.state) for d in ds if 'D.s7dcl' not in (d.path_a or d.path_b)), key=str)

    def test_identical_in_another_folder(self):
        _, _, ds = self.run_({self.OLD: self.UDT}, {self.NEW: self.UDT})
        self.assertEqual(self.states(ds), [(self.OLD, self.NEW, 'moved')])
        self.assertEqual((ds[-1].nets, ds[-1].itf_changed), ([], False))

    def test_same_folder_is_not_listed(self):
        _, _, ds = self.run_({self.OLD: self.UDT}, {self.OLD: self.UDT})
        self.assertEqual(self.states(ds), [])

    def test_moved_and_changed_is_changed(self):
        _, _, ds = self.run_({self.OLD: self.UDT}, {self.NEW: self.OTHER})
        self.assertEqual(self.states(ds), [(self.OLD, self.NEW, 'changed')])

    def test_type_moved_with_a_new_version_is_version(self):
        info = 'library/types/%s/Tank/Tank.libinfo'
        _, _, ds = self.run_({self.LOLD: self.UDT, info % 'Old': LIBINFO % ('1.0.0', 'x', 'IsDefault')},
                             {self.LNEW: self.UDT, info % 'New': LIBINFO % ('2.0.0', 'x', 'IsDefault')})
        self.assertEqual(self.states(ds), [(self.LOLD, self.LNEW, 'version')])

    def test_identical_type_moved(self):
        _, _, ds = self.run_({self.LOLD: self.UDT}, {self.LNEW: self.UDT})
        self.assertEqual(self.states(ds), [(self.LOLD, self.LNEW, 'moved')])

    def test_program_block_gone_and_a_library_type_new_are_each_listed(self):
        _, _, ds = self.run_({self.OLD: self.UDT}, {self.LNEW: self.UDT})
        self.assertEqual(self.states(ds), sorted([(self.OLD, None, 'deleted'), (None, self.LNEW, 'new')], key=str))

    def test_renamed_is_not_a_move(self):
        _, _, ds = self.run_({self.OLD: self.UDT},
                             {'plc/types/New/Vessel.s7dcl': self.UDT.replace('"Tank"', '"Vessel"')})
        self.assertEqual([d.state for d in ds if 'D.s7dcl' not in d.path_a], ['changed'])

    def test_moved_block_and_its_type_are_not_linked(self):
        """The block has no change to merge into: the type's own entry stays."""
        _, _, ds = self.run_({self.OLD: self.UDT, self.LOLD: self.UDT}, {self.NEW: self.UDT, self.LNEW: self.OTHER})
        self.assertEqual(self.states(ds), [(self.LOLD, self.LNEW, 'changed'), (self.OLD, self.NEW, 'moved')])
        self.assertTrue(all(d.library is None for d in ds))

    def test_changed_block_with_a_moved_type_is_not_labelled(self):
        _, _, ds = self.run_({self.OLD: self.UDT, self.LOLD: self.UDT}, {self.OLD: self.OTHER, self.LNEW: self.UDT})
        self.assertEqual(self.states(ds), [(self.LOLD, self.LNEW, 'moved'), (self.OLD, self.OLD, 'changed')])
        self.assertTrue(all(d.library is None for d in ds))

    def test_moved_come_last(self):
        _, _, ds = self.run_({self.OLD: self.UDT, 'plc/types/Z.s7dcl': self.UDT.replace('Tank', 'Z')},
                             {self.NEW: self.UDT, 'plc/types/Z.s7dcl': self.OTHER.replace('Tank', 'Z')})
        self.assertEqual([d.state for d in ds], ['changed', 'moved'])

    def page(self, before, after):
        b, a, ds = self.run_(before, after)
        return render(ds, b.label, a.label)

    def test_section_says_moved_and_where_without_content(self):
        html = self.page({self.OLD: self.UDT}, {self.NEW: self.UDT})
        (sec,) = [s for s in re.findall(r'<section class="blk[^"]*">.*?</section>', html, re.S) if 'blk-Tank' in s]
        self.assertIn('<section class="blk mvd">', sec)
        self.assertIn('<span class="st moved">moved</span>', sec)
        self.assertIn('plc/types/Old/Tank.s7dcl → plc/types/New/Tank.s7dcl', sec)
        self.assertNotIn('class="nw', sec)

    def test_tree_tags_it_and_counts_it_apart(self):
        html = self.page({self.OLD: self.UDT}, {self.NEW: self.UDT})
        rail = re.search(r'<ul class="tree">.*?</nav>', html, re.S).group(0)
        self.assertRegex(rail, r'<a class="obj moved"[^>]*title="PLC data types/Old → PLC data types/New: moved"')
        self.assertIn('<span class="k">[UDT] moved</span>', rail)
        self.assertRegex(rail, r'<span class="nm">New</span><span class="n">1 moved</span>')

    def test_folder_with_only_moved_blocks_starts_collapsed(self):
        html = self.page({self.OLD: self.UDT, 'plc/types/Mix/Z.s7dcl': self.UDT.replace('Tank', 'Z')},
                         {self.NEW: self.UDT, 'plc/types/Mix/Z.s7dcl': self.OTHER.replace('Tank', 'Z')})
        rail = re.search(r'<ul class="tree">.*?</nav>', html, re.S).group(0)
        self.assertRegex(rail, r'<li class="fd shut"><span class="fn"><span class="nm">New</span>')
        self.assertRegex(rail, r'<li class="fd"><span class="fn"><span class="nm">Mix</span><span class="n">1</span>')
        self.assertRegex(rail, r'<span class="nm">PLC data types</span><span class="n">1 \+ 1 moved</span>')

    def test_summary_lists_them_apart_collapsed(self):
        html = self.page({self.OLD: self.UDT, 'plc/types/Mix/Z.s7dcl': self.UDT.replace('Tank', 'Z')},
                         {self.NEW: self.UDT, 'plc/types/Mix/Z.s7dcl': self.OTHER.replace('Tank', 'Z')})
        main = re.search(r'<table class="sum">.*?</table>', html, re.S).group(0)
        self.assertNotIn('Tank', main)
        det = re.search(r'<details class="mvd">.*?</details>', html, re.S).group(0)
        self.assertIn('<summary>Only moved to another folder: 1</summary>', det)
        self.assertEqual(re.findall(r'<td>([^<]*)</td>', det)[4:],
                         ['Tank', 'UDT', 'PLC data types/Old', 'PLC data types/New'])

    def test_style_hides_the_sections_in_the_flow(self):
        from TiaChangeReports import page
        self.assertIn('.ldiff section.blk.mvd.mvd{display:none}', page.CSS)
        self.assertIn('.ldiff .bh .st.moved{', page.CSS)
        self.assertIn('.ldiff .tree a.obj.moved .mk', page.RAIL_CSS)

    def test_page_opens_on_a_change_and_steps_within_its_group(self):
        """Not on a moved block, which would open its collapsed folder; next and previous keep the two groups apart."""
        from TiaChangeReports import page
        self.assertIn("function list(a){var m=a.classList.contains('moved')", page.RAIL_JS)
        self.assertIn('show(find(location.hash)||first())', page.RAIL_JS)
        self.assertNotIn('show(find(location.hash)||objs[0])', page.RAIL_JS)
        self.assertIn("!x.classList.contains('moved')", page.WAIT_JS)

    def test_only_moved_blocks_on_the_page(self):
        html = self.page({self.OLD: self.UDT}, {self.NEW: self.UDT})
        self.assertNotIn('<table class="sum">', html)
        self.assertIn('Only moved to another folder: 1', html)

    def main_(self, *opts):
        import contextlib
        import io
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b, a = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(b, {self.OLD: self.UDT, 'plc/types/D.s7dcl': UDT_D})
        _write(a, {self.NEW: self.UDT, 'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([b, a, '-o', os.path.join(tmp.name, 'r.html')] + list(opts))
        return out.getvalue()

    def test_listing(self):
        self.assertIn('moved    UDT         Tank  (from plc/types/Old to plc/types/New)', self.main_())

    def test_json(self):
        import json
        (b,) = json.loads(self.main_('--json'))['blocks']
        self.assertEqual((b['state'], b['networks'], b['interface'], b['movedFrom'], b['movedTo']),
                         ('moved', [], False, self.OLD, self.NEW))

    def test_named_block_shows_its_content(self):
        import json
        (b,) = json.loads(self.main_('--json', '--block', 'Tank', '--all'))['blocks']
        self.assertEqual(b['state'], 'moved')


class KindAndDeclarationCount(unittest.TestCase):
    """A block's kind and a DB's type are what a user changed: the block is changed, old and new
    shown, at the same path or in another folder."""

    PATH, NEW = 'plc/blocks/Store.s7dcl', 'plc/blocks/Other/Store.s7dcl'

    def db(self, of):
        return 'DATA_BLOCK Store : %s\nEND_DATA_BLOCK\n' % of

    def fx(self, kind):
        end = {'FUNCTION': 'FUNCTION "Store" : Void', 'FUNCTION_BLOCK': 'FUNCTION_BLOCK "Store"'}[kind]
        return ('%s\n    VAR_INPUT\n        a : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n    NETWORK\n'
                '        #a := 1;\n    END_NETWORK\nEND_%s\n' % (end, kind))

    def one(self, before, after):
        return [d for d in LibraryInstances.run_(self, before, after)[2] if 'D.s7dcl' not in (d.path_a or d.path_b)]

    def test_db_of_another_type_at_the_same_path(self):
        (d,) = self.one({self.PATH: self.db('typeOld')}, {self.PATH: self.db('typeNew')})
        self.assertEqual((d.state, d.declaration), ('changed', ('DB Store : typeOld', 'DB Store : typeNew')))

    def test_db_of_another_type_in_another_folder_is_no_move(self):
        (d,) = self.one({self.PATH: self.db('typeOld')}, {self.NEW: self.db('typeNew')})
        self.assertEqual(d.state, 'changed')

    def test_fc_becoming_fb_at_the_same_path(self):
        (d,) = self.one({self.PATH: self.fx('FUNCTION')}, {self.PATH: self.fx('FUNCTION_BLOCK')})
        self.assertEqual((d.state, d.declaration[0][:2], d.declaration[1][:2]), ('changed', 'FC', 'FB'))

    def test_fc_becoming_fb_in_another_folder_is_no_move(self):
        (d,) = self.one({self.PATH: self.fx('FUNCTION')}, {self.NEW: self.fx('FUNCTION_BLOCK')})
        self.assertEqual(d.state, 'changed')

    def test_page_shows_old_and_new(self):
        b, a, ds = LibraryInstances.run_(self, {self.PATH: self.db('typeOld')}, {self.PATH: self.db('typeNew')})
        html = _text(render(ds, b.label, a.label))
        self.assertIn('Declaration', html)
        self.assertIn('typeOld', html)
        self.assertIn('typeNew', html)

    def test_listing_and_json_name_it(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        before, after = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(before, {self.PATH: self.db('typeOld'), 'plc/types/D.s7dcl': UDT_D})
        _write(after, {self.PATH: self.db('typeNew'), 'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', os.path.join(tmp.name, 'r.html')])
        self.assertIn('(declaration: DB Store : typeOld -> DB Store : typeNew)', out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', os.path.join(tmp.name, 'r.html'), '--json'])
        (b,) = json.loads(out.getvalue())['blocks']
        self.assertEqual(b['declaration'], {'before': 'DB Store : typeOld', 'after': 'DB Store : typeNew'})

    def test_same_declaration_is_nothing(self):
        self.assertEqual(self.one({self.PATH: self.db('typeOld')}, {self.PATH: self.db('typeOld')}), [])

    def test_a_rename_alone_is_no_declaration_change(self):
        (d,) = self.one({self.PATH: self.fx('FUNCTION')},
                        {'plc/blocks/Store2.s7dcl': self.fx('FUNCTION').replace('"Store"', '"Store2"')})
        self.assertEqual((d.state, d.declaration), ('changed', None))

    def test_quotes_alone_are_no_declaration_change(self):
        (d,) = self.one({self.PATH: 'DATA_BLOCK Store : typeOld\n    VAR\n        x : Int;\n    END_VAR\nEND_DATA_BLOCK\n'},
                        {self.PATH: 'DATA_BLOCK "Store" : "typeOld"\n    VAR\n        y : Int;\n    END_VAR\nEND_DATA_BLOCK\n'})
        self.assertIsNone(d.declaration)


class FileDiffersInWhatTheReportCannotRead(unittest.TestCase):
    """A block whose file differs only in what the report does not read is listed, not collapsed, moved or not, with a
    note: it may be a real change. What only the exports write differently is not."""

    NOTE = 'the file differs in something this report does not show'
    PATH, NEW = 'plc/blocks/Main.xml', 'plc/blocks/Other/Main.xml'
    SD, SDNEW = 'plc/blocks/Job.s7dcl', 'plc/blocks/Other/Job.s7dcl'

    def job(self, key='MLC_1'):
        return ('FUNCTION "Job" : Void\n    VAR_INPUT\n        a : Int;\n    END_VAR\n'
                '    { S7_Language := "SCL"; S7_NetworkTitle := "%s" }\n    NETWORK\n        #a := 1;\n    END_NETWORK\n'
                'END_FUNCTION\n' % key)

    def res(self, key='MLC_1', **languages):
        lines = ''.join('    %s: %s\n' % kv for kv in languages.items())
        return 'MultiLingualTexts:\n  - id: %s\n%s' % (key, lines.replace('    ', '    ', 1))

    def one(self, before, after):
        return [d for d in LibraryInstances.run_(self, before, after)[2] if 'D.s7dcl' not in (d.path_a or d.path_b)]

    def english(self):
        return self.res(**{'en-US': 'Title'})

    def german_too(self, text='Titel'):
        return self.res(**{'en-US': 'Title', 'de-DE': text})

    def test_text_in_another_language_at_the_same_path(self):
        (d,) = self.one({self.SD: self.job(), 'plc/blocks/Job.s7res': self.english()},
                        {self.SD: self.job(), 'plc/blocks/Job.s7res': self.german_too()})
        self.assertEqual((d.state, d.not_shown, d.nets), ('changed', True, []))

    def test_text_in_another_language_in_another_folder_is_no_move(self):
        (d,) = self.one({self.SD: self.job(), 'plc/blocks/Job.s7res': self.english()},
                        {self.SDNEW: self.job(), 'plc/blocks/Other/Job.s7res': self.german_too()})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def accessibility(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="Bool" Accessibility="Public" />')
        self.assertNotEqual(text, _fixture())
        return text

    def test_xml_field_the_reader_does_not_read(self):
        (d,) = self.one({self.PATH: _fixture()}, {self.PATH: self.accessibility()})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_xml_field_in_another_folder_is_no_move(self):
        (d,) = self.one({self.PATH: _fixture()}, {self.NEW: self.accessibility()})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_page_lists_it_with_the_note_not_collapsed(self):
        b, a, ds = LibraryInstances.run_(self, {self.PATH: _fixture()}, {self.NEW: self.accessibility()})
        html = render(ds, b.label, a.label)
        (sec,) = [s for s in re.findall(r'<section class="blk[^"]*">.*?</section>', html, re.S) if 'blk-Main' in s]
        self.assertTrue(sec.startswith('<section class="blk">'))     # not hidden in the flow
        self.assertIn(self.NOTE, _text(sec))
        self.assertIn('<span class="st moved">moved</span>', sec)
        main = re.search(r'<table class="sum">.*?</table>', html, re.S)
        self.assertIsNone(main)                                      # one block: no summary
        rail = re.search(r'<ul class="tree">.*?</nav>', html, re.S).group(0)
        self.assertIn('not shown', _text(rail))
        self.assertIn(self.NOTE, rail)
        self.assertNotIn('Only moved', html)

    def test_summary_says_it(self):
        other = {'plc/blocks/Z.s7dcl': self.job().replace('Job', 'Z')}
        b, a, ds = LibraryInstances.run_(self, {self.PATH: _fixture(), **other},
                                         {self.PATH: self.accessibility(),
                                          'plc/blocks/Z.s7dcl': self.job().replace('Job', 'Z').replace('#a := 1', '#a := 2')})
        main = re.search(r'<table class="sum">.*?</table>', render(ds, b.label, a.label), re.S).group(0)
        self.assertIn('not shown', _text(main))

    def test_listing_and_json(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        before, after = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(before, {self.PATH: _fixture(), 'plc/types/D.s7dcl': UDT_D})
        _write(after, {self.PATH: self.accessibility(), 'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', os.path.join(tmp.name, 'r.html')])
        self.assertIn('(%s)' % self.NOTE, out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([before, after, '-o', os.path.join(tmp.name, 'r.html'), '--json'])
        (b,) = json.loads(out.getvalue())['blocks']
        self.assertTrue(b['notShown'])

    # what only the exports write differently stays out
    def same(self, before, after, moved=False):
        ds = self.one(before, after)
        if moved:
            self.assertEqual([(d.state, d.not_shown) for d in ds], [('moved', False)])
        else:
            self.assertEqual(ds, [])

    def noise(self, created=False, ids=False, cultures=False, sections=False):
        text = _fixture()
        if created:
            text = re.sub(r'<Created>[^<]*</Created>', '<Created>2030-01-01T00:00:00.0000000Z</Created>', text)
        if ids:
            text = re.sub(r'\bID="(\w+)"', lambda m: 'ID="%X"' % (int(m.group(1), 16) + 16), text)
        if cultures:
            text = re.sub(r'( *)(<MultilingualTextItem ID="\w+" CompositionName="Items">.*?</MultilingualTextItem>)',
                          lambda m: m.group(1) + '<MultilingualTextItem ID="F0" CompositionName="Items"><AttributeList>'
                                    '<Culture>de-DE</Culture><Text /></AttributeList></MultilingualTextItem>\n' + m.group(0),
                          text, flags=re.S)
        if sections:
            text = text.replace('<Member Name="big" Datatype="Bool" />',
                                '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="in" '
                                'Datatype="Bool" /></Section></Sections></Member>')
        self.assertNotEqual(text, _fixture())
        return text

    def test_xml_export_time(self):
        self.same({self.PATH: _fixture()}, {self.NEW: self.noise(created=True)}, moved=True)

    def test_xml_object_numbers(self):
        self.same({self.PATH: _fixture()}, {self.PATH: self.noise(ids=True)})
        self.same({self.PATH: _fixture()}, {self.NEW: self.noise(ids=True)}, moved=True)

    def test_xml_language_order(self):
        with_german = self.noise(cultures=True)
        def swapped(text):
            return re.sub(r'(<MultilingualTextItem ID="F0".*?</MultilingualTextItem>)(\s*)'
                          r'(<MultilingualTextItem ID="\w+" CompositionName="Items">.*?</MultilingualTextItem>)',
                          r'\3\2\1', text, flags=re.S)
        self.assertNotEqual(swapped(with_german), with_german)
        self.same({self.PATH: with_german}, {self.NEW: swapped(with_german)}, moved=True)

    def test_xml_nested_member_with_more_than_tia_writes_is_not_noise(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="in" '
                                  'Datatype="Bool"><AttributeList><BooleanAttribute Name="SetPoint">true</BooleanAttribute>'
                                  '</AttributeList></Member></Section></Sections></Member>')
        self.assertNotEqual(text, _fixture())
        (d,) = self.one({self.PATH: _fixture()}, {self.PATH: text})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_xml_struct_nested_in_the_expansion_is_tia_expansion(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="s" '
                                  'Datatype="Struct"><Member Name="in" Datatype="Int" /></Member></Section></Sections></Member>')
        self.assertNotEqual(text, _fixture())
        self.same({self.PATH: _fixture()}, {self.NEW: text}, moved=True)

    def test_xml_struct_nested_with_more_than_tia_writes_is_not_noise(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="s" '
                                  'Datatype="Struct"><Member Name="in" Datatype="Int" Accessibility="Public" /></Member>'
                                  '</Section></Sections></Member>')
        (d,) = self.one({self.PATH: _fixture()}, {self.PATH: text})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_xml_nested_member_with_a_version_is_tia_expansion(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="in" '
                                  'Datatype="Int" Version="1.0" /></Section></Sections></Member>')
        self.assertNotEqual(text, _fixture())
        self.same({self.PATH: _fixture()}, {self.NEW: text}, moved=True)

    def test_xml_language_without_a_text(self):
        self.same({self.PATH: _fixture()}, {self.NEW: self.noise(cultures=True)}, moved=True)

    def test_xml_language_with_a_text_is_not_noise(self):
        text = self.noise(cultures=True).replace('<Culture>de-DE</Culture><Text />', '<Culture>de-DE</Culture><Text>Hallo</Text>', 1)
        (d,) = self.one({self.PATH: _fixture()}, {self.PATH: text})
        self.assertEqual(d.state, 'changed')

    def test_xml_expansion_of_a_udt_member(self):
        self.same({self.PATH: _fixture()}, {self.NEW: self.noise(sections=True)}, moved=True)

    def test_text_keys_renumbered(self):
        self.same({self.SD: self.job(), 'plc/blocks/Job.s7res': self.german_too()},
                  {self.SD: self.job('MLC_7'), 'plc/blocks/Job.s7res': self.res('MLC_7', **{'de-DE': 'Titel', 'en-US': 'Title'})})

    def test_equal_files_moved(self):
        self.same({self.SD: self.job()}, {self.SDNEW: self.job()}, moved=True)


class PairedWithinOneDevice(unittest.TestCase):
    """A block going from one PLC to another was removed from one and added to the other."""

    UDT = 'TYPE "Tank"\n    STRUCT\n        level : Int;\n        full : Bool;\n    END_STRUCT;\nEND_TYPE\n'
    ONE, TWO = 'plc/PLC_1/types/Tank.s7dcl', 'plc/PLC_2/types/Tank.s7dcl'

    def states(self, before, after):
        return sorted((str(d.path_b), str(d.path_a), d.state) for d in LibraryInstances.run_(self, before, after)[2]
                      if 'D.s7dcl' not in (d.path_a or d.path_b))

    def test_same_name_in_another_plc(self):
        self.assertEqual(self.states({self.ONE: self.UDT}, {self.TWO: self.UDT}),
                         sorted([(self.ONE, 'None', 'deleted'), ('None', self.TWO, 'new')]))

    def test_alike_under_another_name_in_another_plc(self):
        two = 'plc/PLC_2/types/Vessel.s7dcl'
        self.assertEqual(self.states({self.ONE: self.UDT}, {two: self.UDT.replace('"Tank"', '"Vessel"')}),
                         sorted([(self.ONE, 'None', 'deleted'), ('None', two, 'new')]))

    def test_another_folder_of_one_plc_is_a_move(self):
        new = 'plc/PLC_1/types/Sub/Tank.s7dcl'
        self.assertEqual(self.states({self.ONE: self.UDT}, {new: self.UDT}), [(self.ONE, new, 'moved')])


def _rungs(*rungs, name='K'):
    """A LAD block with one network: each rung (start, [elements], end or None)."""
    body = ''.join('        RUNG wire#%s\n%s        END_RUNG%s\n' % (
        s, ''.join('            %s\n' % e for e in els), ' wire#%s' % e if e else '') for s, els, e in rungs)
    return ('FUNCTION_BLOCK "%s"\n    VAR\n        a : Bool;\n        b : Bool;\n        m : Bool;\n        x : Bool;\n'
            '        r : Bool;\n        p : Bool;\n        q : Bool;\n    END_VAR\n    { S7_Language := "LAD" }\n'
            '    NETWORK\n%s    END_NETWORK\nEND_FUNCTION_BLOCK\n' % (name, body))


def _rungs_with_nodes(*rungs):
    """As _rungs, an item ('node', name) a wire in the rung."""
    return _rungs(*[(s, [('wire#%s' % e[1] if isinstance(e, tuple) else e) for e in els], end) for s, els, end in rungs])


class RewiredNetwork(unittest.TestCase):
    """A network with the same elements connected otherwise is another logic: changed, the elements
    connected otherwise marked as moved. Wire names are not logic."""

    A = ('Contact( #a )',)
    RAIL = 'powerrail'

    def net(self, before, after):
        d = compare_blocks(src(_rungs(*before), '', 'K'), src(_rungs(*after), '', 'K'), all_=True)
        return d

    def changed(self, before, after):
        d = self.net(before, after)
        (p,) = d.nets
        self.assertEqual((d.state, p.state), ('changed', 'changed'))
        self.assertIn('moved', p.lad.status.values())
        self.assertNotIn('added', p.lad.status.values())
        return p

    def same(self, before, after):
        d = self.net(before, after)
        self.assertEqual([p.state for p in d.nets], ['same'])

    def test_contact_now_also_gates_a_branch(self):
        """A or (M and x) or (R and B), to A or (((M and x) or R) and B)."""
        r = self.RAIL
        p = self.changed(
            [(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #m )', 'Contact( #x )'], 'w1'),
             (r, ['Contact( #r )', 'Contact( #b )'], 'w1'), ('w1', ['Coil( #q )'], None)],
            [(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #m )', 'Contact( #x )'], 'w2'),
             (r, ['Contact( #r )'], 'w2'), ('w2', ['Contact( #b )'], 'w1'), ('w1', ['Coil( #q )'], None)])
        got = {e.operand(): p.lad.status[eid] for eid, e in p.lad.b.elements.items()}
        self.assertEqual(got['#b'], 'moved')                # it left its rung
        self.assertEqual((got['#a'], got['#x'], got['#m'], got['#r']), ('same', 'same', 'same', 'same'))

    def test_contact_ored_into_another_coil(self):
        r = self.RAIL
        self.changed([(r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None),
                      (r, ['Contact( #b )'], 'w2'), ('w2', ['Coil( #q )'], None), (r, ['Contact( #m )'], 'w1')],
                     [(r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None),
                      (r, ['Contact( #b )'], 'w2'), ('w2', ['Coil( #q )'], None), (r, ['Contact( #m )'], 'w2')])

    def test_two_coils_swap_their_wires(self):
        r = self.RAIL
        self.changed([(r, ['Contact( #a )', 'Coil( #p )'], None), (r, ['Contact( #b )', 'Coil( #q )'], None)],
                     [(r, ['Contact( #a )', 'Coil( #q )'], None), (r, ['Contact( #b )', 'Coil( #p )'], None)])

    def test_box_pin_fed_by_another_wire(self):
        one = MARK.replace('RUNG wire#powerrail\n            Contact( #b )\n        END_RUNG wire#w1',
                           'RUNG wire#powerrail\n            Contact( #b )\n        END_RUNG wire#w1\n'
                           '        RUNG wire#powerrail\n            Contact( #q )\n        END_RUNG wire#w2')
        self.assertNotEqual(one, MARK)
        d = compare_blocks(src(one, '', 'K'), src(one.replace('start := wire#w1', 'start := wire#w2'), '', 'K'), all_=True)
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')

    def marked(self, p):
        return sorted(e.operand() for g in (p.lad.b,) for eid, e in g.elements.items() if p.lad.status[eid] == 'moved')

    def test_a_contact_moved_into_a_branch_is_the_one_marked(self):
        """The rung it left and the rung it joined tell which it is, not the contact whose wire happens to differ."""
        d = compare_blocks(
            src(_rungs_with_nodes(('powerrail', ['Contact( #a )', ('node', 'w1'), 'Contact( #x )', 'Coil( #q )'], None),
                                  ('powerrail', ['Contact( #b )'], 'w1')), '', 'K'),
            src(_rungs_with_nodes(('powerrail', ['Contact( #a )', ('node', 'w1'), 'Coil( #q )'], None),
                                  ('powerrail', ['Contact( #b )', 'Contact( #x )'], 'w1')), '', 'K'))
        (p,) = d.nets
        self.assertEqual(self.marked(p), ['#x'])

    def test_two_coils_swapped_are_the_ones_marked(self):
        r = self.RAIL
        p = self.changed([(r, ['Contact( #a )', 'Coil( #p )'], None), (r, ['Contact( #b )', 'Coil( #q )'], None)],
                         [(r, ['Contact( #a )', 'Coil( #q )'], None), (r, ['Contact( #b )', 'Coil( #p )'], None)])
        self.assertEqual(self.marked(p), ['#p', '#q'])

    def test_same_rungs_otherwise_wired_marks_by_the_wire(self):
        """Nothing left its rung: the contact ORed into another wire."""
        r = self.RAIL
        p = self.changed([(r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None),
                          (r, ['Contact( #b )'], 'w2'), ('w2', ['Coil( #q )'], None), (r, ['Contact( #m )'], 'w1')],
                         [(r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None),
                          (r, ['Contact( #b )'], 'w2'), ('w2', ['Coil( #q )'], None), (r, ['Contact( #m )'], 'w2')])
        self.assertIn('#m', self.marked(p))

    def test_page_shows_it_on_the_list(self):
        r = self.RAIL
        d = compare_blocks(src(_rungs((r, ['Contact( #a )', 'Coil( #p )'], None), (r, ['Contact( #b )', 'Coil( #q )'], None)), '', 'K'),
                           src(_rungs((r, ['Contact( #a )', 'Coil( #q )'], None), (r, ['Contact( #b )', 'Coil( #p )'], None)), '', 'K'))
        self.assertEqual((d.state, len(d.nets)), ('changed', 1))
        self.assertIn('class="hl moved"', render([d], 'b', 'a'))

    def test_wire_names_are_no_change(self):
        r = self.RAIL
        self.same([(r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None)],
                  [(r, ['Contact( #a )'], 'w7'), ('w7', ['Coil( #p )'], None)])

    def test_trailing_comma_of_a_simaticml_export_is_no_change(self):
        """An XML export writes a comma after the last parameter, an .s7dcl none: connections are compared, not text."""
        def box(comma):
            return ('FUNCTION_BLOCK "K"\n    VAR\n        a : Bool;\n        c : Int;\n    END_VAR\n    { S7_Language := "LAD" }\n'
                    '    NETWORK\n        RUNG wire#powerrail\n            Contact( #a )\n            "Scale"(\n'
                    '                value := #c%s\n            )\n        END_RUNG\n    END_NETWORK\nEND_FUNCTION_BLOCK\n' % comma)
        d = compare_blocks(src(box(','), '', 'K'), src(box(''), '', 'K'), all_=True)
        self.assertEqual([p.state for p in d.nets], ['same'])

    def test_trailing_space_of_an_empty_output_is_no_change(self):
        def box(tail):
            return ('FUNCTION_BLOCK "K"\n    VAR\n        a : Bool;\n    END_VAR\n    { S7_Language := "LAD" }\n'
                    '    NETWORK\n        RUNG wire#powerrail\n            Contact( #a )\n            "Scale"(\n'
                    '                et =>%s\n            )\n        END_RUNG\n    END_NETWORK\nEND_FUNCTION_BLOCK\n' % tail)
        d = compare_blocks(src(box(' ,'), '', 'K'), src(box(''), '', 'K'), all_=True)
        self.assertEqual([p.state for p in d.nets], ['same'])


class OrderOfTheRungs(unittest.TestCase):
    """The order of the rungs is a real change: a write in one and a read in another, two calls in
    parallel, depend on it. The network is changed, tagged, shown, whatever else changed in the block."""

    R = 'powerrail'

    def swapped(self, one, two, rest=()):
        d = compare_blocks(src(_rungs(one, two, *rest), '', 'K'), src(_rungs(two, one, *rest), '', 'K'))
        self.assertEqual(d.state, 'changed')
        (p,) = d.nets
        self.assertEqual((p.state, p.reordered), ('changed', True))
        self.assertFalse(p.lad.changed)
        self.assertIn('moved', p.lad.status.values())
        return d

    def test_contacts_in_parallel(self):
        self.swapped((self.R, ['Contact( #a )'], 'w1'), (self.R, ['Contact( #b )'], 'w1'), [('w1', ['Coil( #p )'], None)])

    def test_a_write_in_one_rung_read_in_the_other(self):
        self.swapped((self.R, ['Contact( #a )', 'Coil( #x )'], None), (self.R, ['Contact( #x )', 'Coil( #q )'], None))

    def test_two_calls_in_parallel(self):
        self.swapped((self.R, ['Contact( #a )', '"First"(\n                value := #a\n            )'], None),
                     (self.R, ['Contact( #b )', '"Second"(\n                value := #b\n            )'], None))

    def test_equal_contacts_swapped(self):
        self.swapped((self.R, ['Contact( #a )', 'Contact( #b )'], 'w1'), (self.R, ['Contact( #a )', 'Contact( #m )'], 'w1'),
                     [('w1', ['Coil( #p )'], None)])

    def test_with_another_change_in_the_block(self):
        one, two = (self.R, ['Contact( #a )', 'Coil( #x )'], None), (self.R, ['Contact( #x )', 'Coil( #q )'], None)
        def block(*rungs, limit='1'):
            return _rungs(*rungs).replace('END_FUNCTION_BLOCK', '    { S7_Language := "SCL" }\n    NETWORK\n        #a := %s;\n'
                                                                '    END_NETWORK\nEND_FUNCTION_BLOCK' % limit)
        d = compare_blocks(src(block(one, two), '', 'K'), src(block(two, one, limit='2'), '', 'K'))
        self.assertEqual([p.state for p in d.nets], ['changed', 'changed'])
        self.assertEqual([p.reordered for p in d.nets], [True, False])

    def test_wire_names_in_another_case_are_no_change(self):
        r = self.R
        d = compare_blocks(src(_rungs((r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None)), '', 'K'),
                           src(_rungs((r, ['Contact( #a )'], 'W1'), ('W1', ['Coil( #p )'], None)), '', 'K'), all_=True)
        self.assertEqual([p.state for p in d.nets], ['same'])

    # another difference the logic does not see is no order
    def unread(self, before, after):
        d = compare_blocks(src(_rungs(*before), '', 'K'), src(_rungs(*after), '', 'K'))
        (p,) = d.nets
        self.assertEqual((p.state, p.reordered, p.not_shown), ('changed', False, True))
        return d

    def test_a_pragma_the_report_does_not_read(self):
        r = self.R
        self.unread([(r, ['{ f_user_card := "1" }', 'Contact( #a )', 'Coil( #q )'], None)],
                    [(r, ['{ f_user_card := "2" }', 'Contact( #a )', 'Coil( #q )'], None)])

    def test_spaces_inside_a_line(self):
        r = self.R
        self.unread([(r, ['Contact( #a )', 'Coil( #q )'], None)], [(r, ['Contact(  #a )', 'Coil( #q )'], None)])

    def test_the_note_is_on_the_network_not_the_order_tag(self):
        r = self.R
        d = self.unread([(r, ['{ f_user_card := "1" }', 'Contact( #a )', 'Coil( #q )'], None)],
                        [(r, ['{ f_user_card := "2" }', 'Contact( #a )', 'Coil( #q )'], None)])
        html = render([d], 'b', 'a')
        self.assertNotIn('other order', html)
        self.assertIn('differs in something this report does not show', re.search(r'<div class="nwt">.*?</div>', html, re.S).group(0))

    def test_network_note_in_listing_and_json(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        r = self.R
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b, a = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(b, {'plc/K.s7dcl': _rungs((r, ['{ f_user_card := "1" }', 'Contact( #a )'], None)), 'plc/types/D.s7dcl': UDT_D})
        _write(a, {'plc/K.s7dcl': _rungs((r, ['{ f_user_card := "2" }', 'Contact( #a )'], None)), 'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([b, a, '-o', os.path.join(tmp.name, 'r.html')])
        self.assertIn('(differs in something this report does not show)', out.getvalue())
        self.assertNotIn('other order', out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([b, a, '-o', os.path.join(tmp.name, 'r.html'), '--json'])
        (n,) = json.loads(out.getvalue())['blocks'][0]['networks']
        self.assertTrue(n['notShown'])
        self.assertNotIn('reordered', n)

    def test_page_tags_it(self):
        d = self.swapped((self.R, ['Contact( #a )', 'Coil( #x )'], None), (self.R, ['Contact( #x )', 'Coil( #q )'], None))
        self.assertIn('<span class="st moved">other order</span>', render([d], 'b', 'a'))

    def test_listing_and_json(self):
        import contextlib
        import io
        import json
        from TiaChangeReports.__main__ import main
        one, two = (self.R, ['Contact( #a )', 'Coil( #x )'], None), (self.R, ['Contact( #x )', 'Coil( #q )'], None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b, a = os.path.join(tmp.name, 'b'), os.path.join(tmp.name, 'a')
        _write(b, {'plc/K.s7dcl': _rungs(one, two), 'plc/types/D.s7dcl': UDT_D})
        _write(a, {'plc/K.s7dcl': _rungs(two, one), 'plc/types/D.s7dcl': UDT_D})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([b, a, '-o', os.path.join(tmp.name, 'r.html')])
        self.assertIn('(other order)', out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([b, a, '-o', os.path.join(tmp.name, 'r.html'), '--json'])
        (blk,) = json.loads(out.getvalue())['blocks']
        self.assertTrue(blk['networks'][0]['reordered'])

    def test_no_note_it_is_shown(self):
        d = self.swapped((self.R, ['Contact( #a )'], 'w1'), (self.R, ['Contact( #b )'], 'w1'), [('w1', ['Coil( #p )'], None)])
        self.assertFalse(d.not_shown)


class FileCheckSeesTheWiring(unittest.TestCase):
    """Wires and UIds numbered by first appearance, not left out: a rewiring is no export's quirk."""

    def test_wires_renumbered_are_alike(self):
        from TiaChangeReports.compare import files_alike
        r = 'powerrail'
        self.assertTrue(files_alike(
            src(_rungs((r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None)), '', 'K'),
            src(_rungs((r, ['Contact( #a )'], 'w5'), ('w5', ['Coil( #p )'], None)), '', 'K')))

    def test_wires_connected_otherwise_are_not_alike(self):
        from TiaChangeReports.compare import files_alike
        r = 'powerrail'
        self.assertFalse(files_alike(
            src(_rungs((r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w2'), ('w1', ['Coil( #p )'], None), ('w2', ['Coil( #q )'], None)), '', 'K'),
            src(_rungs((r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w2'), ('w2', ['Coil( #p )'], None), ('w1', ['Coil( #q )'], None)), '', 'K')))

    def test_numbers_start_again_in_each_network(self):
        from TiaChangeReports.compare import _resolved
        def two(w, v):
            return ('FUNCTION_BLOCK "K"\n    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#%s\n        END_RUNG\n    END_NETWORK\n'
                    '    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#%s\n        END_RUNG\n    END_NETWORK\nEND_FUNCTION_BLOCK\n' % (w, v))
        self.assertEqual(_resolved(src(two('w1', 'w1'), '', 'K')), _resolved(src(two('w1', 'w2'), '', 'K')))

    def test_xml_uids_renumbered_are_alike(self):
        from TiaChangeReports.simaticml import alike_exports
        uid = re.compile(r'\bUId="(\d+)"')
        self.assertTrue(alike_exports(_fixture(), uid.sub(lambda m: 'UId="%d"' % (int(m.group(1)) + 100), _fixture())))

    def test_xml_wire_to_another_part_is_not_alike(self):
        from TiaChangeReports.simaticml import alike_exports
        text = _fixture()
        m = re.search(r'<NameCon UId="(\d+)" Name="[^"]*" />', text)
        other = next(x for x in re.findall(r'<NameCon UId="(\d+)"', text) if x != m.group(1))
        changed = text[:m.start()] + m.group(0).replace('UId="%s"' % m.group(1), 'UId="%s"' % other) + text[m.end():]
        self.assertFalse(alike_exports(text, changed))


class PairWithOtherPathsNeverVanishes(unittest.TestCase):
    """A pair whose paths differ and is no move is listed as changed, both paths shown."""

    def fc(self, name='Inner'):
        return ('FUNCTION "%s" : Void\n    VAR_INPUT\n        a : Int;\n        b : Int;\n    END_VAR\n    { S7_Language := "SCL" }\n'
                '    NETWORK\n        #a := 1;\n        #b := 2;\n        #a := 3;\n    END_NETWORK\nEND_FUNCTION\n' % name)

    def one(self, before, after):
        return [(d.path_b, d.path_a, d.state) for d in LibraryInstances.run_(self, before, after)[2]
                if 'D.s7dcl' not in (d.path_a or d.path_b)]

    def test_library_type_renamed_with_the_block_inside_keeping_its_name(self):
        old, new = 'library/types/G/Old/Old.s7dcl', 'library/types/G/New/New.s7dcl'
        self.assertEqual(self.one({old: self.fc()}, {new: self.fc()}), [(old, new, 'changed')])

    def test_type_in_work_to_released_without_version_files(self):
        work, rel = 'library/types/G/T/T.s7dcl', 'library/types/G/T.released/T.s7dcl'
        self.assertEqual(self.one({work: self.fc('T')}, {rel: self.fc('T')}), [(work, rel, 'changed')])

    def single(self, pb, pa):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _write(os.path.join(tmp.name, 'b'), {pb: self.fc()})
        _write(os.path.join(tmp.name, 'a'), {pa: self.fc()})
        from TiaChangeReports.compare import compare_snapshots
        return [(d.path_b, d.path_a, d.state) for d in compare_snapshots(
            FolderSnapshot(os.path.join(tmp.name, 'b')), FolderSnapshot(os.path.join(tmp.name, 'a')))]

    def test_one_file_each_from_one_plc_to_another(self):
        pb, pa = 'plc/PLC_1/blocks/Inner.s7dcl', 'plc/PLC_2/blocks/Inner.s7dcl'
        self.assertEqual(self.single(pb, pa), [(pb, pa, 'changed')])

    def test_one_file_each_program_to_library(self):
        pb, pa = 'plc/blocks/Inner.s7dcl', 'library/types/Inner/Inner.s7dcl'
        self.assertEqual(self.single(pb, pa), [(pb, pa, 'changed')])

    def test_same_path_stays_off_the_list(self):
        p = 'plc/blocks/Inner.s7dcl'
        self.assertEqual(self.single(p, p), [])


class NoteWheneverALanguageDiffers(unittest.TestCase):
    """The note also when something else changed, and a type with it stays on the page."""

    SD, RES = 'plc/blocks/Job.s7dcl', 'plc/blocks/Job.s7res'
    LIB, LRES = 'library/types/Job/Job.s7dcl', 'library/types/Job/Job.s7res'

    def job(self, limit='1', setpoint=False):
        pin = '{ S7_Setpoint := "True" }\n        ' if setpoint else ''
        return ('FUNCTION "Job" : Void\n    VAR_INPUT\n        %sa : Int;\n    END_VAR\n'
                '    { S7_Language := "SCL"; S7_NetworkTitle := "MLC_1" }\n    NETWORK\n        #a := %s;\n    END_NETWORK\n'
                'END_FUNCTION\n' % (pin, limit))

    def res(self, **languages):
        return 'MultiLingualTexts:\n  - id: MLC_1\n' + ''.join('    %s: %s\n' % kv for kv in languages.items())

    EN = {'en-US': 'Title'}
    BOTH = {'en-US': 'Title', 'es-ES': 'Titulo'}

    def blocks(self, before, after):
        return [d for d in LibraryInstances.run_(self, before, after)[2] if 'D.s7dcl' not in (d.path_a or d.path_b)]

    def test_code_edit_and_a_language_removed(self):
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.res(**self.BOTH)},
                           {self.SD: self.job('2'), self.RES: self.res(**self.EN)})
        self.assertEqual((d.state, d.not_shown), ('changed', True))
        self.assertTrue(d.nets)

    def test_code_edit_and_the_same_languages(self):
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.res(**self.BOTH)},
                           {self.SD: self.job('2'), self.RES: self.res(**self.BOTH)})
        self.assertEqual((d.state, d.not_shown), ('changed', False))

    def test_code_edit_and_the_report_language_alone(self):
        """What the report shows is no note."""
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.res(**self.EN)},
                           {self.SD: self.job('2'), self.RES: self.res(**{'en-US': 'Other'})})
        self.assertEqual((d.state, d.not_shown), ('changed', False))

    def test_xml_edit_and_a_language_added(self):
        plc = 'plc/blocks/Main.xml'
        edit = 'Member Name="stop"', 'Member Name="halt"'
        added = _fixture().replace(*edit).replace(
            '<Member Name="big" Datatype="Bool" />',
            '<Member Name="big" Datatype="Bool"><Comment><MultiLanguageText Lang="de-DE">Gross</MultiLanguageText></Comment></Member>')
        (d,) = self.blocks({plc: _fixture()}, {plc: added})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def two(self, one, other):
        return ('MultiLingualTexts:\n  - id: MLC_1\n    en-US: Title\n    es-ES: %s\n'
                '  - id: MLC_2\n    en-US: Other\n    es-ES: %s\n' % (one, other))

    def test_texts_swapped_between_two_entries_with_a_code_edit(self):
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.two('Uno', 'Dos')},
                           {self.SD: self.job('2'), self.RES: self.two('Dos', 'Uno')})
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_keys_renumbered_with_a_code_edit(self):
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.two('Uno', 'Dos')},
                           {self.SD: self.job('2'), self.RES: self.two('Uno', 'Dos').replace('MLC_1', 'MLC_9').replace('MLC_2', 'MLC_8')})
        self.assertEqual((d.state, d.not_shown), ('changed', False))

    def test_report_language_edited_the_translation_kept(self):
        """What the report shows changed; no text in another language differs."""
        (d,) = self.blocks({self.SD: self.job(), self.RES: self.res(**self.BOTH)},
                           {self.SD: self.job('2'), self.RES: self.res(**{'en-US': 'New title', 'es-ES': 'Titulo'})})
        self.assertEqual((d.state, d.not_shown), ('changed', False))

    def test_type_with_a_tagged_network_stays(self):
        """Block and type with one edit in common, the type's other network holds what the report does not read."""
        plc, lib = 'plc/blocks/Main.xml', 'library/types/Main/Main.xml'
        edit = 'Member Name="stop"', 'Member Name="halt"'
        tagged = _fixture().replace('<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" Version="1.0" />')
        ds = self.blocks({plc: _fixture(), lib: _fixture()}, {plc: _fixture().replace(*edit), lib: tagged.replace(*edit)})
        self.assertIn(lib, [d.path_a for d in ds])
        (t_,) = [d for d in ds if d.path_a == lib]
        self.assertEqual([p.not_shown for p in t_.nets], [True])

    def test_type_without_a_tag_still_merges(self):
        plc, lib = 'plc/blocks/Main.xml', 'library/types/Main/Main.xml'
        edit = 'Member Name="stop"', 'Member Name="halt"'
        ds = self.blocks({plc: _fixture(), lib: _fixture()}, {plc: _fixture().replace(*edit), lib: _fixture().replace(*edit)})
        self.assertEqual([d.path_a for d in ds], [plc])

    def test_type_with_the_note_stays_when_the_block_only_changed_a_setpoint(self):
        ds = self.blocks({self.SD: self.job(), self.RES: self.res(**self.BOTH), self.LIB: self.job(), self.LRES: self.res(**self.BOTH)},
                         {self.SD: self.job(setpoint=True), self.RES: self.res(**self.BOTH), self.LIB: self.job(), self.LRES: self.res(**self.EN)})
        self.assertEqual(sorted((d.path_a, d.state, d.not_shown) for d in ds),
                         [(self.LIB, 'changed', True), (self.SD, 'changed', False)])

    def test_type_with_the_note_stays_when_the_block_made_the_same_edit(self):
        ds = self.blocks({self.SD: self.job(), self.RES: self.res(**self.BOTH), self.LIB: self.job(), self.LRES: self.res(**self.BOTH)},
                         {self.SD: self.job('2'), self.RES: self.res(**self.BOTH), self.LIB: self.job('2'), self.LRES: self.res(**self.EN)})
        self.assertIn(self.LIB, [d.path_a for d in ds])


class ComparedPerPart(unittest.TestCase):
    """What the report does not read is told per part: a network called same whose source differs
    gets the network's tag, an interface or block attribute the note, whatever else changed. A raised version, which TIA
    writes on every edit, must not silence them."""

    PATH = 'plc/blocks/Main.xml'
    VERSION = '<HeaderVersion>0.1</HeaderVersion>', '<HeaderVersion>0.2</HeaderVersion>'
    NOTE = 'differs in something this report does not show'

    def d(self, before, after):
        (d,) = [x for x in LibraryInstances.run_(self, {self.PATH: before}, {self.PATH: after})[2]
                if 'D.s7dcl' not in (x.path_a or x.path_b)]
        return d

    def network_tagged(self, edit):
        """The edit alone and with the version raised: the network it is in is shown and tagged."""
        text = edit(_fixture())
        self.assertNotEqual(text, _fixture())
        for after in (text, text.replace(*self.VERSION)):
            d = self.d(_fixture(), after)
            self.assertEqual(d.state, 'changed')
            self.assertEqual([p.not_shown for p in d.nets], [True])

    def block_noted(self, edit):
        text = edit(_fixture())
        self.assertNotEqual(text, _fixture())
        for after in (text, text.replace(*self.VERSION)):
            d = self.d(_fixture(), after)
            self.assertEqual((d.state, d.not_shown), ('changed', True), after == text)

    # in a network
    def test_a_part_version(self):
        self.network_tagged(lambda x: x.replace('<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" Version="1.0" />'))

    def test_a_template_value(self):
        self.network_tagged(lambda x: x.replace('<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>',
                                                '<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>'
                                                '<TemplateValue Name="f_user_card" Type="Cardinality">3</TemplateValue>', 1))

    def test_an_access_scope(self):
        self.network_tagged(lambda x: x.replace('<Access Scope="LocalVariable" UId="21">', '<Access Scope="GlobalVariable" UId="21">')
                            if False else x.replace('<Symbol>', '<Symbol Hint="x">', 1))

    def fbd(self, operand='c'):
        """As first seen: A feeding O, O feeding the assignment; the operand on O is what the text leaves out."""
        def access(uid, name):
            return ('<Access Scope="LocalVariable" UId="%d"><Symbol><Component Name="%s" /></Symbol></Access>' % (uid, name))
        net = ('<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"><Parts>'
               + access(21, 'start') + access(22, 'stop') + access(23, operand) + access(24, 'latch')
               + '<Part Name="A" UId="25"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue></Part>'
                 '<Part Name="O" UId="26"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue></Part>'
                 '<Part Name="Coil" UId="27" /></Parts><Wires>'
                 '<Wire UId="28"><IdentCon UId="21" /><NameCon UId="25" Name="in1" /></Wire>'
                 '<Wire UId="29"><IdentCon UId="22" /><NameCon UId="25" Name="in2" /></Wire>'
                 '<Wire UId="30"><NameCon UId="25" Name="out" /><NameCon UId="26" Name="in1" /></Wire>'
                 '<Wire UId="31"><IdentCon UId="23" /><NameCon UId="26" Name="in2" /></Wire>'
                 '<Wire UId="32"><NameCon UId="26" Name="out" /><NameCon UId="27" Name="in" /></Wire>'
                 '<Wire UId="33"><IdentCon UId="24" /><NameCon UId="27" Name="operand" /></Wire></Wires></FlgNet>')
        text = re.sub(r'<FlgNet .*?</FlgNet>', lambda m: net, _fixture(), count=1, flags=re.S)
        return text.replace('<ProgrammingLanguage>LAD</ProgrammingLanguage>\n        </AttributeList>',
                            '<ProgrammingLanguage>FBD</ProgrammingLanguage>\n        </AttributeList>', 1)

    def test_an_operand_on_a_chained_gate(self):
        for after in (self.fbd('big'), self.fbd('big').replace(*self.VERSION)):
            d = self.d(self.fbd('count'), after)
            self.assertEqual(d.state, 'changed')
            self.assertEqual([p.not_shown for p in d.nets], [False])
            self.assertIn('in2 := #count,', d.nets[0].before.body)
            self.assertIn('in2 := #big,', d.nets[0].after.body)

    def test_only_the_network_it_is_in(self):
        """The other networks stay unshown."""
        d = self.d(_fixture(), _fixture().replace('<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" Version="1.0" />'))
        self.assertEqual(len(d.nets), 1)
        self.assertEqual(d.nets[0].before.index, 1)

    def test_page_tags_the_network(self):
        d = self.d(_fixture(), _fixture().replace('<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" Version="1.0" />'))
        self.assertIn(self.NOTE, re.search(r'<div class="nwt">.*?</div>', render([d], 'b', 'a'), re.S).group(0))

    # in the interface and the block's attributes
    def test_a_member_field_the_reader_does_not_read(self):
        self.block_noted(lambda x: x.replace('<Member Name="big" Datatype="Bool" />',
                                             '<Member Name="big" Datatype="Bool" Accessibility="Public" />'))

    def test_a_member_field_beside_another_member_changed(self):
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />', '<Member Name="big" Datatype="Bool" Accessibility="Public" />') \
            .replace('<Member Name="count" Datatype="Int" />', '<Member Name="count" Datatype="DInt" />')
        d = self.d(_fixture(), text)
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_a_member_changed_alone_is_no_note(self):
        d = self.d(_fixture(), _fixture().replace('<Member Name="count" Datatype="Int" />', '<Member Name="count" Datatype="DInt" />'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_a_member_added_and_removed_are_no_note(self):
        d = self.d(_fixture(), _fixture().replace('<Member Name="count" Datatype="Int" />',
                                                  '<Member Name="count" Datatype="Int" /><Member Name="more" Datatype="Int" />'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_a_nested_member_with_more_than_tia_writes(self):
        self.block_noted(lambda x: x.replace('<Member Name="big" Datatype="Bool" />',
                                             '<Member Name="big" Datatype="Bool"><Sections><Section Name="None"><Member Name="in" '
                                             'Datatype="Int" Accessibility="Public" /></Section></Sections></Member>'))

    def test_a_start_value_s_constant_name(self):
        before = _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                    '<Member Name="big" Datatype="Int"><StartValue ConstantName="One">1</StartValue></Member>')
        after = before.replace('ConstantName="One"', 'ConstantName="Uno"')
        self.assertNotEqual(after, before)
        for text in (after, after.replace(*self.VERSION)):
            self.assertTrue(self.d(before, text).not_shown)

    def test_an_stl_token_in_a_network(self):
        stl = '<StlToken Text="A" UId="90" />'
        before = _fixture().replace('<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" />' + stl)
        after = before.replace(stl, stl.replace('"A"', '"O"'))
        d = self.d(before, after.replace(*self.VERSION))
        self.assertEqual([p.not_shown for p in d.nets], [True])

    def test_a_block_attribute_the_reader_does_not_read(self):
        self.block_noted(lambda x: x.replace('<MemoryLayout>Optimized</MemoryLayout>',
                                             '<MemoryLayout>Optimized</MemoryLayout><MemoryReserve>100</MemoryReserve>'))

    def test_a_shown_attribute_alone_is_no_note(self):
        d = self.d(_fixture(), _fixture().replace(*self.VERSION))
        self.assertEqual((bool(d.props_changed), d.not_shown), (True, False))

    # field by field: an unread field on a member whose row is changed
    def member(self, attrs='', kids='', typ='Int'):
        return _fixture().replace('<Member Name="big" Datatype="Bool" />',
                                  '<Member Name="big" Datatype="%s"%s>%s</Member>' % (typ, attrs, kids))

    def test_an_unread_field_on_a_member_with_its_type_changed(self):
        d = self.d(self.member(), self.member(' Accessibility="Public"', typ='DInt'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_an_unread_attribute_of_a_comment_with_the_type_changed(self):
        before = self.member(kids='<Comment><MultiLanguageText Lang="en-US">x</MultiLanguageText></Comment>')
        after = self.member(typ='DInt', kids='<Comment Unread="true"><MultiLanguageText Lang="en-US">x</MultiLanguageText></Comment>')
        self.assertTrue(self.d(before, after).not_shown)

    def test_a_constant_name_beside_the_member_s_type(self):
        before = self.member(kids='<StartValue ConstantName="One">1</StartValue>')
        after = self.member(typ='DInt', kids='<StartValue ConstantName="Uno">1</StartValue>')
        self.assertTrue(self.d(before, after).not_shown)

    def test_read_fields_changed_together_are_no_note(self):
        """Each field that differs is one the report shows differing."""
        before = self.member(' Remanence="NonRetain"', '<Comment><MultiLanguageText Lang="en-US">x</MultiLanguageText></Comment>'
                                                       '<StartValue>1</StartValue>')
        after = self.member(' Remanence="Retain"', '<Comment><MultiLanguageText Lang="en-US">y</MultiLanguageText></Comment>'
                                                   '<StartValue>2</StartValue>', typ='DInt')
        d = self.d(before, after)
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def in_section(self, section, attrs=''):
        return self.at(section, '', attrs)

    @staticmethod
    def at(section, inner, attrs=''):
        """The member big in InOut or Static; both sections there, as TIA writes every section of a block."""
        text = _fixture().replace('<Member Name="big" Datatype="Bool" />', '')
        member = '<Member Name="big" Datatype="Bool"%s>%s</Member>' % (attrs, inner)
        return text.replace('<Section Name="Constant" />', ''.join(
            '<Section Name="%s">%s</Section>' % (x, member if x == section else '') for x in ('InOut', 'Static'))
            + '<Section Name="Constant" />')

    def test_a_member_gone_to_another_section_with_its_defaults(self):
        """Temp has no retain or accessibility, Static writes the defaults. The report shows the section."""
        d = self.d(self.in_section('InOut'), self.in_section('Static', ' Remanence="NonRetain" Accessibility="Public"'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_a_member_gone_to_another_section_with_something_else(self):
        d = self.d(self.in_section('InOut'), self.in_section('Static', ' Remanence="NonRetain" Accessibility="Private"'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_a_member_gone_to_another_section_with_a_comment_added(self):
        """A field that is a list of children, beside the defaults."""
        d = self.d(self.at('InOut', ''), self.at('Static', '<Comment><MultiLanguageText Lang="en-US">x</MultiLanguageText></Comment>',
                                                 ' Remanence="NonRetain" Accessibility="Public"'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_a_default_written_in_the_same_section_is_a_field_that_differs(self):
        d = self.d(self.in_section('Static'), self.in_section('Static', ' Accessibility="Public"'))
        self.assertTrue(d.not_shown)

    def test_a_remanence_the_report_reads_alike(self):
        """A value it does not know reads as not retained."""
        d = self.d(self.member(' Remanence="NonRetain"'), self.member(' Remanence="SomeOther"', typ='DInt'))
        self.assertTrue(d.not_shown)

    def test_set_in_idb_is_shown(self):
        """As the SimaticML export writes it."""
        b, a, ds = LibraryInstances.run_(self, {self.PATH: self.member(' Remanence="NonRetain"')},
                                         {self.PATH: self.member(' Remanence="SetInIDB"')})
        (d,) = [x for x in ds if 'D.s7dcl' not in (x.path_a or x.path_b)]
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))
        self.assertIn('Set in IDB', _text(render(ds, b.label, a.label)))

    # by name: which attribute a shown property accounts for
    RESERVE = '<MemoryLayout>Optimized</MemoryLayout>', '<MemoryLayout>Optimized</MemoryLayout><MemoryReserve>100</MemoryReserve>'

    def test_a_shown_number_does_not_account_for_another_attribute(self):
        """An OB shows its number though numbered automatically."""
        d = self.d(_fixture(), _fixture().replace('<Number>1</Number>', '<Number>9</Number>').replace(*self.RESERVE))
        self.assertTrue(d.not_shown)

    def test_a_shown_property_is_no_note(self):
        off = _fixture().replace('<AutoNumber>true</AutoNumber>', '<AutoNumber>false</AutoNumber>')
        d = self.d(off, off.replace('<Number>1</Number>', '<Number>9</Number>').replace(*self.VERSION))
        self.assertEqual((bool(d.props_changed), d.not_shown), (True, False))

    def test_a_shown_version_does_not_account_for_another_attribute(self):
        d = self.d(_fixture(), _fixture().replace(*self.VERSION).replace(*self.RESERVE))
        self.assertTrue(d.not_shown)

    # .s7dcl
    def sd(self, section='VAR_INPUT', inp='', code='1', pragma='', member='        inP : Bool;\n', title=''):
        return ('FUNCTION_BLOCK "F"\n    %s\n%s%s    END_VAR\n    VAR\n        s : Int;\n    END_VAR\n'
                '    { S7_Language := "SCL"%s }\n    NETWORK\n        #s := %s;\n    END_NETWORK\nEND_FUNCTION_BLOCK\n'
                % (section, member, inp, pragma, code))

    def sd_d(self, before, after):
        (d,) = [x for x in LibraryInstances.run_(self, {'plc/F.s7dcl': before}, {'plc/F.s7dcl': after})[2]
                if 'D.s7dcl' not in (x.path_a or x.path_b)]
        return d

    D = 'VAR_INPUT SOME_WORD'         # a section the reader does not know

    def test_a_member_added_in_an_unknown_section(self):
        d = self.sd_d(self.sd(self.D), self.sd(self.D, '        inQ : Int;\n'))
        self.assertEqual((d.state, d.not_shown), ('changed', True))

    def test_a_member_added_in_an_unknown_section_with_a_code_edit(self):
        d = self.sd_d(self.sd(self.D), self.sd(self.D, '        inQ : Int;\n', code='2'))
        self.assertEqual((d.state, d.not_shown, len(d.nets)), ('changed', True, 1))

    def test_s7dcl_with_a_shown_member_changed_too(self):
        d = self.sd_d(self.sd(self.D, member='        inP : Bool;\n') + '', self.sd(self.D, '        inQ : Int;\n').replace('s : Int', 's : DInt'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def test_s7dcl_a_member_pragma_is_shown_in_the_interface(self):
        b, a, ds = LibraryInstances.run_(self, {'plc/F.s7dcl': self.sd()},
                                         {'plc/F.s7dcl': self.sd(code='2', member='        { S7_Unknown := "x" }\n        inP : Bool;\n')})
        (d,) = [x for x in ds if 'D.s7dcl' not in (x.path_a or x.path_b)]
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))
        self.assertIn('Unknown', _text(render(ds, b.label, a.label)))

    def test_s7dcl_a_member_changed_is_no_note(self):
        d = self.sd_d(self.sd(), self.sd(inp='        inQ : Int;\n'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))
        d = self.sd_d(self.sd(), self.sd().replace('inP : Bool', 'inP : Int'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_s7dcl_setpoint_changed_is_shown_no_note(self):
        d = self.sd_d(self.sd(member='        { S7_Setpoint := "False" }\n        inP : Bool;\n'),
                      self.sd(member='        { S7_Setpoint := "True" }\n        inP : Bool;\n'))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_s7dcl_a_network_setting_the_reader_does_not_read(self):
        before, after = self.sd(), self.sd(pragma='; S7_Unknown := "x"')
        d = self.sd_d(before, after)
        self.assertEqual((d.state, [p.not_shown for p in d.nets]), ('changed', [True]))

    def test_s7dcl_text_keys_renumbered_are_silent(self):
        """Per copy; the text stays."""
        def fc(key):
            return self.sd().replace('{ S7_Language := "SCL" }', '{ S7_Language := "SCL"; S7_NetworkTitle := "%s" }' % key)
        res = 'MultiLingualTexts:\n  - id: %s\n    en-US: Title\n'
        (d,) = [x for x in LibraryInstances.run_(self, {'plc/F.s7dcl': fc('MLC_1'), 'plc/F.s7res': res % 'MLC_1'},
                                                 {'plc/F.s7dcl': fc('MLC_9').replace('#s := 1', '#s := 2'), 'plc/F.s7res': res % 'MLC_9'})[2]
                if 'D.s7dcl' not in (x.path_a or x.path_b)]
        self.assertEqual([p.not_shown for p in d.nets], [False])

    # what stays silent
    def silent(self, text):
        self.assertNotEqual(text, _fixture())
        d = self.d(_fixture(), text.replace(*self.VERSION))
        self.assertEqual(([p.not_shown for p in d.nets], d.not_shown), ([], False))

    def test_export_time(self):
        self.silent(re.sub(r'<Created>[^<]*</Created>', '<Created>2030-01-01T00:00:00.0000000Z</Created>', _fixture()))

    def test_object_numbers(self):
        self.silent(re.sub(r'\bID="(\w+)"', lambda m: 'ID="%X"' % (int(m.group(1), 16) + 16), _fixture()))

    def test_uids_renumbered(self):
        self.silent(re.sub(r'\bUId="(\d+)"', lambda m: 'UId="%d"' % (int(m.group(1)) + 100), _fixture()))

    def test_a_number_while_automatic_numbering_is_on(self):
        self.silent(_fixture().replace('<Number>1</Number>', '<Number>9</Number>'))

    def test_a_number_with_automatic_numbering_off_counts(self):
        off = _fixture().replace('<AutoNumber>true</AutoNumber>', '<AutoNumber>false</AutoNumber>')
        self.assertNotEqual(off, _fixture())
        d = self.d(off, off.replace('<Number>1</Number>', '<Number>9</Number>'))
        self.assertEqual(d.state, 'changed')
        self.assertTrue(d.props_changed or d.not_shown)

    def test_automatic_numbering_switched_off_counts(self):
        d = self.d(_fixture(), _fixture().replace('<AutoNumber>true</AutoNumber>', '<AutoNumber>false</AutoNumber>'))
        self.assertEqual(d.state, 'changed')
        self.assertTrue(d.props_changed or d.not_shown)

    def test_s7dcl_a_start_value_over_several_lines_is_one_member(self):
        def udt(value):
            return ('TYPE\n    Tank : STRUCT\n        pos : Array[0..1] of Int := [\n            %s,\n            2\n        ];\n'
                    '        full : Bool;\n    END_STRUCT;\n\nEND_TYPE\n' % value)
        (d,) = [x for x in LibraryInstances.run_(self, {'plc/types/Tank.s7dcl': udt('1')}, {'plc/types/Tank.s7dcl': udt('5')})[2]
                if 'D.s7dcl' not in (x.path_a or x.path_b)]
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))

    def test_the_export_settings(self):
        """How it was exported, by which installation: nothing of the project."""
        self.silent(_fixture().replace('<ExportSetting>WithDefaults</ExportSetting>', '<ExportSetting>None</ExportSetting>'
                                       '<InstalledProducts />'))

    def test_a_language_is_the_block_note_not_the_network_tag(self):
        text = re.sub(r'( *)(<MultilingualTextItem ID="\w+" CompositionName="Items">.*?</MultilingualTextItem>)',
                      lambda m: m.group(1) + '<MultilingualTextItem ID="F0" CompositionName="Items"><AttributeList><Culture>de-DE'
                                '</Culture><Text>Hallo</Text></AttributeList></MultilingualTextItem>\n' + m.group(0),
                      _fixture(), flags=re.S)
        d = self.d(re.sub(r'<Text />', '<Text>Title</Text>', _fixture()), re.sub(r'<Text />', '<Text>Title</Text>', text))
        self.assertEqual(([p.not_shown for p in d.nets], d.not_shown), ([], True))


class TaggedBesideAChange(unittest.TestCase):
    """What the report does not read, changed in a network or block that also shows another change, keeps the
    tag there; no field is named. A change that only moves with what is shown is no tag."""

    PATH = 'plc/blocks/Main.xml'
    OPERAND = '<Component Name="stop" />', '<Component Name="halt" />'
    VERSION = '<Part Name="Contact" UId="25" />', '<Part Name="Contact" UId="25" Version="1.0" />'

    def d(self, before, after):
        return ComparedPerPart.d(self, before, after)

    def tags(self, before, after):
        return [p.not_shown for p in self.d(before, after).nets]

    def test_a_part_s_field_beside_an_operand(self):
        self.assertEqual(self.tags(_fixture(), _fixture().replace(*self.OPERAND).replace(*self.VERSION)), [True])

    def test_the_operand_alone_is_no_tag(self):
        self.assertEqual(self.tags(_fixture(), _fixture().replace(*self.OPERAND)), [False])

    def branch(self, card):
        """A third leg on the O of network 1: a contact from the rail on its in3, the O's pin count as given."""
        return _fixture().replace(
            '<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>\n    </Part>',
            '<TemplateValue Name="Card" Type="Cardinality">%s</TemplateValue>\n    </Part>'
            '<Access Scope="LocalVariable" UId="39"><Symbol><Component Name="big" /></Symbol></Access>'
            '<Part Name="Contact" UId="40" />' % card, 1).replace(
            '<NameCon UId="26" Name="in" />\n    </Wire>',
            '<NameCon UId="26" Name="in" /><NameCon UId="40" Name="in" />\n    </Wire>'
            '<Wire UId="41"><IdentCon UId="39" /><NameCon UId="40" Name="operand" /></Wire>'
            '<Wire UId="42"><NameCon UId="40" Name="out" /><NameCon UId="27" Name="in3" /></Wire>', 1)

    def test_a_pin_count_that_moves_with_its_pins_is_no_tag(self):
        self.assertEqual(self.tags(_fixture(), self.branch(3)), [False])

    def test_a_pin_count_with_the_same_pins_beside_an_operand(self):
        before = self.branch(3)
        self.assertEqual(self.tags(before, before.replace(*self.OPERAND).replace('>3</TemplateValue>', '>4</TemplateValue>')), [True])

    def test_a_field_on_a_wire_beside_an_operand(self):
        self.assertEqual(self.tags(_fixture(), _fixture().replace(*self.OPERAND).replace('<Wire UId="35">', '<Wire UId="35" Hint="x">', 1)),
                         [True])

    def test_a_field_on_the_network_beside_an_operand(self):
        cu = '<SW.Blocks.CompileUnit ID="3" CompositionName="CompileUnits">'
        self.assertEqual(self.tags(_fixture(), _fixture().replace(*self.OPERAND).replace(cu, cu[:-1] + ' Hint="x">')), [True])

    def test_a_network_comment_gone_beside_an_operand(self):
        """A title or comment TIA writes empty, one version without it: the text reads the same."""
        title = '</MultilingualText>\n        </ObjectList>\n      </SW.Blocks.CompileUnit>'
        before = _fixture().replace(title, '</MultilingualText><MultilingualText ID="9" CompositionName="Comment"><ObjectList />'
                                           '</MultilingualText>' + title[len('</MultilingualText>'):], 1)
        self.assertNotEqual(before, _fixture())
        self.assertEqual(self.tags(before, _fixture().replace(*self.OPERAND)), [True])

    def test_an_open_end_gone_beside_an_operand(self):
        before = _fixture().replace('<NameCon UId="29" Name="operand" />', '<NameCon UId="29" Name="operand" />'
                                    '<OpenCon UId="50" />', 1)
        self.assertEqual(self.tags(before, _fixture().replace(*self.OPERAND)), [True])

    def test_a_part_added_with_its_fields_is_no_tag(self):
        """Its fields come with it: the drawing shows the part."""
        after = self.branch(3).replace('<Part Name="Contact" UId="40" />', '<Part Name="Contact" UId="40" Version="1.0" />')
        self.assertEqual(self.tags(_fixture(), after), [False])

    # .s7dcl
    F_PINS = '{ f_user_card := "%s" }\n            '

    def sd(self, before, after):
        d = compare_blocks(src(before), src(after))
        return [p.not_shown for p in d.nets]

    def with_pins(self, n, operand='#a'):
        return SRC.replace('Contact( #a )', self.F_PINS % n + 'Contact( %s )' % operand)

    def test_an_f_pin_count_beside_an_operand(self):
        self.assertEqual(self.sd(self.with_pins(1), self.with_pins(2, '#b')), [True])

    def test_an_f_pin_count_alone(self):
        self.assertEqual(self.sd(self.with_pins(1), self.with_pins(2)), [True])

    def test_an_operand_beside_the_same_pragma_is_no_tag(self):
        self.assertEqual(self.sd(self.with_pins(1), self.with_pins(1, '#b')), [False])

    def test_a_pragma_before_the_end_of_a_network_beside_an_operand(self):
        before = SRC.replace('        END_RUNG wire#w1\n', '        END_RUNG wire#w1\n        { Zz := "1" }\n')
        after = before.replace('Contact( #a )', 'Contact( #b )').replace('Zz := "1"', 'Zz := "2"')
        self.assertEqual(self.sd(before, after), [True])

    def test_a_pin_count_that_moves_with_a_pin_is_no_tag(self):
        box = '{ f_user_card := "%s" }\n            F_Box( in1 := #a%s, out => #s.x )\n            '
        before = SRC.replace('Coil( #s.x )', box % (1, '') + 'Coil( #s.x )')
        after = SRC.replace('Coil( #s.x )', box % (2, ', in2 := #b') + 'Coil( #s.x )')
        self.assertEqual(self.sd(before, after), [False])

    ZZ = '{ Zz := "1" }\n            '
    BESIDE = 'Contact( #s.x )', 'Contact( #b )'

    def test_a_pragma_added_beside_an_operand(self):
        after = SRC.replace('I_Contact( #b )', self.ZZ + 'I_Contact( #b )').replace(*self.BESIDE)
        self.assertEqual(self.sd(SRC, after), [True])

    def test_a_pragma_removed_beside_an_operand(self):
        before = SRC.replace('I_Contact( #b )', self.ZZ + 'I_Contact( #b )')
        self.assertEqual(self.sd(before, SRC.replace(*self.BESIDE)), [True])

    def test_an_instruction_added_with_its_pragma_is_no_tag(self):
        after = SRC.replace('Coil( #s.x )', self.ZZ + 'F_Box( in1 := #a, out => #s.x )\n            Coil( #s.x )')
        self.assertEqual(self.sd(SRC, after), [False])

    # the block
    MEMBER = '<Member Name="count" Datatype="Int" />', '<Member Name="count" Datatype="DInt" />'

    def noted(self, edit):
        """The edit beside a member's type changed: the block's note."""
        after = edit(_fixture()).replace(*self.MEMBER)
        self.assertNotEqual(after, _fixture().replace(*self.MEMBER))
        d = self.d(_fixture(), after)
        return bool(d.itf_changed), d.not_shown

    def test_the_member_alone_is_no_note(self):
        self.assertEqual(self.noted(lambda x: x + ' '), (True, False))

    def test_a_field_on_the_block_element(self):
        self.assertEqual(self.noted(lambda x: x.replace('<SW.Blocks.OB ID="0">', '<SW.Blocks.OB ID="0" Hint="x">')), (True, True))

    def test_a_field_on_a_section(self):
        self.assertEqual(self.noted(lambda x: x.replace('<Section Name="Temp">', '<Section Name="Temp" Hint="x">')), (True, True))

    def test_a_section_s_name(self):
        self.assertEqual(self.noted(lambda x: x.replace('<Section Name="Constant" />', '<Section Name="Other" />')), (True, True))

    def test_the_block_s_name_element_gone(self):
        """The name read is the file's then, alike: that the export holds none is the note."""
        self.assertEqual(self.noted(lambda x: x.replace('<Name>Main</Name>', '')), (True, True))

    def test_the_engineering_version_only_alone(self):
        """The export's own: the note when nothing else changed, none beside a change (the maintainer's to overrule)."""
        self.assertEqual(self.noted(lambda x: x.replace('<Engineering version="V20" />', '<Engineering version="V21" />')),
                         (True, False))

    def test_a_network_without_its_texts_before(self):
        """Nowhere to try the title in the version before: no try, the report goes on."""
        start = _fixture().index('<ObjectList>', _fixture().index('<SW.Blocks.CompileUnit ID="3"'))
        end = _fixture().index('</ObjectList>\n      </SW.Blocks.CompileUnit>', start) + len('</ObjectList>')
        before = _fixture()[:start] + _fixture()[end:]
        d = self.d(before, _fixture().replace(*self.OPERAND))
        self.assertEqual([p.state for p in d.nets], ['changed'])

    def test_the_comment_of_a_function_s_return(self):
        def fc(comment):
            ret = ('<Section Name="Return"><Member Name="Ret_Val" Datatype="Void"><Comment><MultiLanguageText Lang="en-US">%s'
                   '</MultiLanguageText></Comment></Member></Section>' % comment)
            return _fixture().replace('<Section Name="Constant" />', '<Section Name="Constant" />' + ret)
        d = self.d(fc('one'), fc('two').replace(*self.MEMBER))
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, True))

    def sd_block(self, before, after):
        d = compare_blocks(src(before), src(after))
        return bool(d.itf_changed), d.not_shown

    def test_a_pragma_before_the_end_of_a_section_beside_a_member(self):
        before = SRC.replace('        b : Bool;\n    END_VAR', '        b : Bool;\n        { Zz := "1" }\n    END_VAR')
        after = before.replace('Zz := "1"', 'Zz := "2"').replace('C1 : Int := 1;', 'C1 : Int := 2;')
        self.assertEqual(self.sd_block(before, after), (True, True))

    TEMP = '    VAR CONSTANT', '    VAR_TEMP\n        t : Int;\n    END_VAR\n    VAR CONSTANT'

    def test_a_section_added_with_a_member_is_no_note(self):
        self.assertEqual(self.sd_block(SRC, SRC.replace(*self.TEMP)), (True, False))

    def test_a_pragma_before_the_end_of_a_section_beside_a_section_added(self):
        """One END_VAR more: the pragma's line is not as often on both sides, its pragma still differs."""
        before = SRC.replace('        b : Bool;\n    END_VAR', '        b : Bool;\n        { Zz := "1" }\n    END_VAR')
        self.assertEqual(self.sd_block(before, before.replace('Zz := "1"', 'Zz := "2"').replace(*self.TEMP)), (True, True))

    def test_a_section_added_with_the_same_pragma_elsewhere_is_no_note(self):
        before = SRC.replace('        b : Bool;\n    END_VAR', '        b : Bool;\n        { Zz := "1" }\n    END_VAR')
        self.assertEqual(self.sd_block(before, before.replace(*self.TEMP)), (True, False))

    def test_a_section_added_with_a_pragma_of_its_own_is_no_note(self):
        """The pragma comes with the section, which the table shows."""
        temp = '    VAR CONSTANT', '    VAR_TEMP\n        t : Int;\n        { Zz := "1" }\n    END_VAR\n    VAR CONSTANT'
        self.assertEqual(self.sd_block(SRC, SRC.replace(*temp)), (True, False))
        self.assertEqual(self.sd_block(SRC.replace(*temp), SRC), (True, False))

    def test_a_struct_added_with_a_pragma_of_its_own_is_no_note(self):
        struct = '        END_STRUCT;\n', ('        END_STRUCT;\n        s2 : STRUCT\n            y : Bool;\n'
                                          '            { Zz := "1" }\n        END_STRUCT;\n')
        self.assertEqual(self.sd_block(SRC, SRC.replace(*struct)), (True, False))
        self.assertEqual(self.sd_block(SRC.replace(*struct), SRC), (True, False))

    def test_a_pragma_before_the_first_network_beside_a_member(self):
        first = '    {\n        S7_Language := "LAD";'
        before = SRC.replace(first, '    { Zz := "1" }\n' + first)
        after = before.replace('Zz := "1"', 'Zz := "2"').replace('C1 : Int := 1;', 'C1 : Int := 2;')
        self.assertNotEqual(before, SRC)
        self.assertEqual(self.sd_block(before, after), (True, True))

    def test_a_pragma_before_the_end_of_the_block_beside_a_member(self):
        before = SRC.replace('END_FUNCTION_BLOCK', '{ Zz := "1" }\nEND_FUNCTION_BLOCK')
        after = before.replace('Zz := "1"', 'Zz := "2"').replace('C1 : Int := 1;', 'C1 : Int := 2;')
        self.assertEqual(self.sd_block(before, after), (True, True))


class PragmaSweep(unittest.TestCase):
    """The classes the pragma sweep (each pragma position of real blocks, added, removed and
    changed, alone and beside each kind of shown change) found. A pragma belongs to what follows it: told when it differs
    and nothing shown brings it, never otherwise."""

    I = '            '
    ZZ = '{ Zz := "1" }\n' + I
    OPERAND = 'Contact( #s.x )', 'Contact( #b )'
    COIL = 'Coil( #s.x )'
    SECOND = '    { S7_Language := "SCL" }\n    NETWORK\n        #s.x := #a;'
    NET = '    { S7_Language := "SCL" }\n    NETWORK\n        #s.x := #b;\n    END_NETWORK\n'
    PRE = '    { Zz := "1" }\n'

    def nets(self, before, after):
        d = compare_blocks(src(before), src(after))
        return [p.not_shown for p in d.nets], d.not_shown

    def box(self, pins, pragma=''):
        """A Calculate written over several lines, as real exports write it."""
        return (pragma + 'Calculate(\n' + ''.join(self.I + '    %s,\n' % p for p in pins[:-1]) + self.I + '    %s\n' % pins[-1]
                + self.I + ')\n' + self.I)

    # in a LAD network
    def test_a_pin_added_to_a_box_over_several_lines_with_its_pin_count(self):
        card = '{ f_user_card := "%s" }\n' + self.I
        before = SRC.replace(self.COIL, self.box(['in1 := #a', 'out => #s.x'], card % 2) + self.COIL)
        after = SRC.replace(self.COIL, self.box(['in1 := #a', 'in2 := #b', 'out => #s.x'], card % 3) + self.COIL)
        self.assertEqual(self.nets(before, after), ([False], False))

    def test_a_pragma_at_the_end_of_a_network_beside_an_operand(self):
        end = '        END_RUNG wire#w1\n', '        END_RUNG wire#w1\n        { Zz := "1" }\n'
        self.assertEqual(self.nets(SRC, SRC.replace(*end).replace(*self.OPERAND)), ([True], False))
        self.assertEqual(self.nets(SRC.replace(*end), SRC.replace(*self.OPERAND)), ([True], False))

    def test_a_pragma_added_before_a_call_whose_instance_changed(self):
        call = '#inst.TON( pt := #t )\n' + self.I
        before = SRC.replace(self.COIL, call + self.COIL)
        after = SRC.replace(self.COIL, self.ZZ + call.replace('#inst.', '#other.') + self.COIL)
        self.assertEqual(self.nets(before, after), ([True], False))

    def test_a_pragma_added_before_an_instruction_beside_a_contact_put_in_front_of_it(self):
        after = SRC.replace('Contact( #a )', 'Contact( #zz )\n' + self.I + self.ZZ + 'Contact( #a )')
        self.assertEqual(self.nets(SRC, after), ([True], False))

    # around the networks
    def test_a_network_added_or_removed_beside_an_unchanged_pragma(self):
        alone = SRC.replace(self.SECOND, self.PRE + self.SECOND)
        for net in (self.NET + self.PRE, self.PRE + self.NET):          # the network in front of the pragma, after it
            other = SRC.replace(self.SECOND, net + self.SECOND)
            self.assertEqual(self.nets(alone, other)[1], False, 'added')
            self.assertEqual(self.nets(other, alone)[1], False, 'removed')

    def test_untitled_networks_beside_one_added_in_front(self):
        """A pragma of an untitled network stays with it when one is added in front: alike, no tag; added, the tag."""
        fc = 'FUNCTION "F" : Void\n    VAR_TEMP\n        x : Bool;\n        y : Bool;\n    END_VAR\n%sEND_FUNCTION\n'
        lad = ('    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            %s%s( #%s )\n'
               '        END_RUNG\n%s    END_NETWORK\n')
        end = '        { Zz := "1" }\n'

        def nets(before, after):
            d = compare_blocks(src(fc % before, name='F'), src(fc % after, name='F'))
            return [p.not_shown for p in d.nets], d.not_shown
        new = lad % ('', 'Contact', 'y', '')
        before = lad % ('', 'Coil', 'x', end) + lad % ('', 'Coil', 'y', '')
        self.assertEqual(nets(before, new + before), ([False], False))
        before = lad % ('', 'Coil', 'x', '') + lad % ('', 'Coil', 'y', '')
        after = new + lad % ('{ Zz := "1" }\n            ', 'Coil', 'x', '') + lad % ('', 'Coil', 'y', '')
        self.assertEqual(nets(before, after), ([False, True], False))

    def test_a_pragma_of_an_untitled_network_beside_one_added_or_removed(self):
        """A network not alike added or removed beside the only other untitled one lists as many networks paired by
        title as by content; the pragma stays with its network and is told."""
        fc = 'FUNCTION "F" : Void\n    VAR_TEMP\n        x : Bool;\n        y : Bool;\n    END_VAR\n%sEND_FUNCTION\n'
        lad = ('    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            %sCoil( #%s )\n'
               '        END_RUNG\n    END_NETWORK\n')
        zz = '{ Zz := "1" }\n            '

        def pairs(before, after):
            d = compare_blocks(src(fc % before, name='F'), src(fc % after, name='F'))
            return [(p.state, p.before and p.before.index, p.after and p.after.index, p.not_shown) for p in d.nets]
        new = lad.replace('%sCoil( #%s )', 'Contact( #y )')
        for b, a in (('', zz), (zz, ''), (zz, zz.replace('1', '2'))):
            self.assertEqual(pairs(lad % (b, 'x'), new + lad % (a, 'x')),
                             [('new', None, 1, False), ('changed', 1, 2, True)], 'added in front')
            self.assertEqual(pairs(new + lad % (b, 'x'), lad % (a, 'x')),
                             [('deleted', 1, None, False), ('changed', 2, 1, True)], 'removed in front')

    def test_a_pragma_of_an_untitled_network_moved_past_one_edited(self):
        """The edited network as alike to the moved one as to its own; the moved one is paired as moved, tagged, and
        the edited one changed in place."""
        fc = ('FUNCTION "F" : Void\n    VAR_TEMP\n        w : Bool;\n        x : Bool;\n        y : Bool;\n        z : Bool;\n'
              '    END_VAR\n%sEND_FUNCTION\n')
        lad = ('    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            %sCoil( #%s )\n'
               '        END_RUNG\n    END_NETWORK\n')
        d = compare_blocks(src(fc % (lad % ('', 'x') + lad % ('', 'y') + lad % ('', 'z')), name='F'),
                           src(fc % (lad % ('', 'w') + lad % ('', 'z') + lad % ('{ Zz := "1" }\n            ', 'x')),
                               name='F'))
        self.assertEqual([(p.state, p.moved, p.before and p.before.index, p.after and p.after.index, p.not_shown)
                          for p in d.nets],
                         [('changed', False, 2, 1, False), ('changed', True, 1, 3, True)])

    def test_a_pragma_of_an_untitled_network_swapped_beside_one_edited(self):
        """Networks of one coil each, alike; swapped beside one edited they list as many read in place as moved, and
        a move costs a deleted and a new network, so they read in place as on main. The pragma is told, not left on a
        network shown new beside its old version changed into the edited one."""
        fc = ('FUNCTION "F" : Void\n    VAR_TEMP\n        w : Bool;\n        x : Bool;\n        y : Bool;\n        z : Bool;\n'
              '    END_VAR\n%sEND_FUNCTION\n')
        lad = ('    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            %sCoil( #%s )\n'
               '        END_RUNG\n    END_NETWORK\n')
        d = compare_blocks(src(fc % (lad % ('', 'x') + lad % ('', 'y') + lad % ('', 'z')), name='F'),
                           src(fc % (lad % ('{ Zz := "1" }\n            ', 'y') + lad % ('', 'x') + lad % ('', 'w')),
                               name='F'))
        self.assertEqual([(p.state, p.moved, p.before and p.before.index, p.after and p.after.index, p.not_shown)
                          for p in d.nets],
                         [('changed', False, 1, 1, True), ('changed', False, 2, 2, False), ('changed', False, 3, 3, False)])

    def test_a_network_added_with_a_pragma_in_front_of_it(self):
        self.assertEqual(self.nets(SRC, SRC.replace(self.SECOND, self.PRE + self.NET + self.SECOND))[1], False)
        end = 'END_FUNCTION_BLOCK'
        self.assertEqual(self.nets(SRC, SRC.replace(end, self.PRE + self.NET + end))[1], False)

    def test_the_first_network_removed_beside_an_unchanged_pragma_in_front_of_it(self):
        first = SRC.index('    {\n        S7_Language := "LAD";')
        before = SRC[:first] + self.PRE + SRC[first:]
        after = before[:first + len(self.PRE)] + before[before.index(self.SECOND):]
        self.assertEqual(self.nets(before, after)[1], False)

    def test_a_first_network_added_with_its_pragma_to_a_block_without_networks(self):
        fc = 'FUNCTION "F" : Void\n    VAR_TEMP\n        x : Bool;\n    END_VAR\n%sEND_FUNCTION\n'
        net = self.PRE + ('    { S7_Language := "LAD" }\n    NETWORK\n        RUNG wire#powerrail\n            Contact( #x )\n'
                          '        END_RUNG\n    END_NETWORK\n')
        self.assertFalse(compare_blocks(src(fc % '', name='F'), src(fc % net, name='F')).not_shown)

    def test_a_pragma_before_the_end_of_a_block_without_networks_beside_a_member(self):
        udt = 'TYPE "U"\n    STRUCT\n        x : %s;\n    END_STRUCT;\n    { Zz := "%s" }\nEND_TYPE\n'
        self.assertTrue(compare_blocks(src(udt % ('Bool', 1), name='U'), src(udt % ('Int', 2), name='U')).not_shown)

    # the interface
    def test_a_section_added_in_front_of_one_of_its_name_with_its_own_pragma(self):
        temp = '    VAR_TEMP\n        t%s : Int;\n%s    END_VAR\n'
        before = SRC.replace('    VAR CONSTANT', temp % (1, '') + '    VAR CONSTANT')
        after = SRC.replace('    VAR CONSTANT', temp % (2, '        { Zz := "1" }\n') + temp % (1, '') + '    VAR CONSTANT')
        self.assertEqual(self.nets(before, after)[1], False)

    def test_the_first_of_two_pragmas_before_a_member_beside_a_member(self):
        two = '        { Zz := "%s" }\n        { S7_MLC := "MLC_1" }\n        a : Bool;'
        before = SRC.replace('        { S7_MLC := "MLC_1" }\n        a : Bool;', two % 1)
        after = before.replace(two % 1, two % 2).replace('C1 : Int := 1;', 'C1 : Int := 2;')
        self.assertEqual(self.nets(before, after)[1], True)


class DbSpecificSections(unittest.TestCase):
    """A DB_SPECIFIC section is its members with TIA's retain "Set in IDB". TIA writes the word itself when
    an FB's optimized access is switched off."""

    def fb(self, inp='VAR_INPUT', out='VAR_OUTPUT', more='', typ='Bool', code='#outP := #inP;', stat=''):
        return ('FUNCTION_BLOCK "F"\n    %s \n        inP : %s;\n%s    END_VAR\n    %s \n        outP : Bool;\n'
                '    END_VAR\n%s    { S7_Language := "SCL" }\n    NETWORK\n        %s\n    END_NETWORK\n'
                'END_FUNCTION_BLOCK\n' % (inp, typ, more, out, stat, code))

    I, O = 'VAR_INPUT DB_SPECIFIC', 'VAR_OUTPUT DB_SPECIFIC'

    def report(self, before, after):
        """The block's comparison, its rows that are not 'same' by path, the page's text."""
        b, a, ds = LibraryInstances.run_(self, {'plc/F.s7dcl': before}, {'plc/F.s7dcl': after})
        (d,) = [x for x in ds if 'D.s7dcl' not in (x.path_a or x.path_b)]
        rows = {'.'.join(r.path): r for r in iface.block_rows(d.before, d.after) if r.state != 'same'}
        return d, rows, _text(render(ds, b.label, a.label))

    def test_every_section_with_a_retain_is_read(self):
        for word, section in (('VAR_INPUT', 'INPUT'), ('VAR_OUTPUT', 'OUTPUT'), ('VAR_IN_OUT', 'IN_OUT'), ('VAR', 'STAT')):
            itf = parse_interface('%s DB_SPECIFIC\n    m : Bool;\nEND_VAR\n' % word, {})
            m = itf.root.children['m']
            self.assertEqual((m.section, m.retain), (section, SET_IN_IDB), word)

    def test_the_word_changing_is_the_members_retain_not_a_removal(self):
        """The end to end case: optimized access switched off."""
        d, rows, text = self.report(self.fb(), self.fb(self.I, self.O))
        self.assertEqual({p: (r.state, r.changes) for p, r in rows.items()},
                         {'inP': ('changed', {'retain'}), 'outP': ('changed', {'retain'})})
        self.assertEqual((bool(d.itf_changed), d.not_shown), (True, False))
        self.assertEqual(text.count('Non-retain'), 2)
        self.assertEqual(text.count('Set in IDB'), 2)

    def test_from_retain(self):
        _, rows, text = self.report(self.fb('VAR_INPUT RETAIN'), self.fb(self.I))
        self.assertEqual((rows['inP'].changes, rows['inP'].b.retain, rows['inP'].a.retain), ({'retain'}, True, SET_IN_IDB))
        self.assertIn('Set in IDB', text)

    def test_nothing_changed_in_the_section_is_no_row(self):
        d, rows, _ = self.report(self.fb(self.I, self.O), self.fb(self.I, self.O, code='#outP := NOT #inP;'))
        self.assertEqual((rows, bool(d.itf_changed), d.not_shown, len(d.nets)), ({}, False, False, 1))

    def test_a_member_added_is_in_the_table(self):
        d, rows, text = self.report(self.fb(self.I, self.O), self.fb(self.I, self.O, '        inQ : Int;\n'))
        self.assertEqual({p: r.state for p, r in rows.items()}, {'inQ': 'added'})
        self.assertEqual(d.not_shown, False)
        self.assertIn('inQ', text)

    def test_a_member_added_beside_a_code_edit(self):
        d, rows, _ = self.report(self.fb(self.I, self.O),
                                 self.fb(self.I, self.O, '        inQ : Int;\n', code='#outP := NOT #inP;'))
        self.assertEqual(({p: r.state for p, r in rows.items()}, d.not_shown, len(d.nets)), ({'inQ': 'added'}, False, 1))

    def test_a_member_changed_in_the_section(self):
        d, rows, text = self.report(self.fb(self.I, self.O), self.fb(self.I, self.O, typ='Int'))
        self.assertEqual((rows['inP'].changes, d.not_shown), ({'type'}, False))
        self.assertIn('Set in IDB', text)

    def test_a_member_removed_is_still_a_removal(self):
        before = self.fb(self.I, self.O, '        inQ : Int;\n')
        _, rows, _ = self.report(before, self.fb(self.I, self.O))
        self.assertEqual({p: r.state for p, r in rows.items()}, {'inQ': 'removed'})

    def test_a_struct_is_one_change(self):
        """TIA shows retain on the top-level member only: the members of a struct have nothing to mark."""
        struct = '        s : Struct\n            x : Bool;\n        END_STRUCT;\n'
        _, rows, _ = self.report(self.fb(more=struct), self.fb(self.I, more=struct))
        self.assertEqual({p: r.changes for p, r in rows.items()}, {'inP': {'retain'}, 's': {'retain'}})

    def test_a_static_section(self):
        stat = '    %s\n        s : Int;\n    END_VAR\n'
        _, rows, text = self.report(self.fb(stat=stat % 'VAR'), self.fb(stat=stat % 'VAR DB_SPECIFIC'))
        self.assertEqual({p: r.changes for p, r in rows.items()}, {'s': {'retain'}})
        self.assertIn('Set in IDB', text)


class OtherOrderWithWiresNumberedOtherwise(unittest.TestCase):
    """Rungs swapped so that the wires number differently are still only another order."""

    def test_tagged_other_order(self):
        r = 'powerrail'
        one = (r, ['Contact( #a )'], 'w1')
        two = (r, ['Contact( #b )'], 'w2')
        rest = [('w1', ['Coil( #p )'], None), ('w2', ['Coil( #q )'], None)]
        d = compare_blocks(src(_rungs(one, two, *rest), '', 'K'), src(_rungs(two, one, *rest), '', 'K'))
        (p,) = d.nets
        self.assertEqual((p.reordered, p.not_shown), (True, False))


class RungOrderMarks(unittest.TestCase):
    """Rungs in another order: what changed places is marked moved on both sides, by the rule of moved
    networks, both of two swapped; what stays in place is not. An element already marked keeps its mark."""

    R = 'powerrail'

    def pair(self, before, after):
        d = compare_blocks(src(_rungs_with_nodes(*before), '', 'K'), src(_rungs_with_nodes(*after), '', 'K'))
        (p,) = d.nets
        return p

    def marks(self, p, status='moved'):
        def side(g):
            return sorted(e.operand() for eid, e in g.elements.items() if p.lad.status[eid] == status)
        return side(p.lad.b), side(p.lad.a)

    def assertMarked(self, p, *operands):
        self.assertEqual(self.marks(p), (sorted(operands), sorted(operands)))

    def test_two_branches_swapped(self):
        """Row 13 of the end to end run: the branches between two wires, the rung through them stays."""
        r = self.R
        main = (r, ['Contact( #b )', ('node', 'w1'), 'Contact( #c )', ('node', 'w2'), 'Coil( #q )'], None)
        d, e = ('w1', ['Contact( #d )'], 'w2'), ('w1', ['Contact( #e )'], 'w2')
        p = self.pair([main, d, e], [main, e, d])
        self.assertMarked(p, '#d', '#e')
        self.assertEqual((p.state, p.reordered, p.not_shown), ('changed', True, False))

    def test_two_branches_of_coils_swapped_the_contact_before_them_stays(self):
        """Row 13b: the rung through the first branch runs through the other one now; #a is in both and stays."""
        r = self.R
        p = self.pair([(r, ['Contact( #a )', ('node', 'w1'), 'Contact( #b )', 'Coil( #q4 )'], None),
                       ('w1', ['Contact( #c )', 'Coil( #q3 )'], None)],
                      [(r, ['Contact( #a )', ('node', 'w1'), 'Contact( #c )', 'Coil( #q3 )'], None),
                       ('w1', ['Contact( #b )', 'Coil( #q4 )'], None)])
        self.assertMarked(p, '#b', '#c', '#q3', '#q4')
        self.assertTrue(p.reordered)

    def test_parallel_contacts_as_exported_the_coil_after_them_stays(self):
        """In the text the coil stands between the two contacts: only what starts at one node has an order."""
        r = self.R
        p = self.pair([(r, ['Contact( #a )', ('node', 'w1'), 'Coil( #q )'], None), (r, ['Contact( #b )'], 'w1')],
                      [(r, ['Contact( #b )', ('node', 'w1'), 'Coil( #q )'], None), (r, ['Contact( #a )'], 'w1')])
        self.assertMarked(p, '#a', '#b')

    def test_two_rungs_swapped_are_both_marked_whatever_their_length(self):
        r = self.R
        one, two = (r, ['Contact( #a )', 'Contact( #b )', 'Coil( #p )'], None), (r, ['Contact( #x )', 'Coil( #q )'], None)
        self.assertMarked(self.pair([one, two], [two, one]), '#a', '#b', '#p', '#x', '#q')

    def test_a_rung_moved_past_two_is_the_one_marked(self):
        r = self.R
        one, two, three = [(r, ['Contact( #%s )' % c, 'Coil( #%s1 )' % c], None) for c in 'abm']
        self.assertMarked(self.pair([one, two, three], [three, one, two]), '#m', '#m1')

    def test_wire_numbers_do_not_tell_which_rung_is_which(self):
        """The same two rungs swapped, the wires numbered by their new order: the contacts swapped are marked, the coils
        behind them in their own rungs are not."""
        r = self.R
        p = self.pair([(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w2'),
                       ('w1', ['Coil( #p )'], None), ('w2', ['Coil( #q )'], None)],
                      [(r, ['Contact( #b )'], 'w1'), (r, ['Contact( #a )'], 'w2'),
                       ('w2', ['Coil( #p )'], None), ('w1', ['Coil( #q )'], None)])
        self.assertMarked(p, '#a', '#b')
        self.assertTrue(p.reordered)

    def test_wires_renamed_only_is_no_order(self):
        r = self.R
        d = compare_blocks(src(_rungs_with_nodes((r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'),
                                                 ('w1', ['Coil( #p )'], None)), '', 'K'),
                           src(_rungs_with_nodes((r, ['Contact( #a )'], 'w7'), (r, ['Contact( #b )'], 'w7'),
                                                 ('w7', ['Coil( #p )'], None)), '', 'K'), all_=True)
        self.assertEqual(([x.state for x in d.nets], d.nets[0].reordered), (['same'], False))

    def test_the_marks_are_no_change_of_the_logic(self):
        """changed tells the logic: pairing networks by their logic (_same_logic) does not see the order."""
        r = self.R
        one, two, coil = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'), ('w1', ['Coil( #p )'], None)
        p = self.pair([one, two, coil], [two, one, coil])
        self.assertFalse(p.lad.changed)

    # duplicates
    def test_a_duplicate_rung_in_its_place_marks_nothing(self):
        r = self.R
        same = [(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'),
                ('w1', ['Coil( #p )'], None)]
        d = compare_blocks(src(_rungs_with_nodes(*same), '', 'K'), src(_rungs_with_nodes(*same), '', 'K'), all_=True)
        self.assertEqual(d.nets[0].state, 'same')
        self.assertEqual(self.marks(d.nets[0]), ([], []))

    def test_a_duplicate_rung_swapped_with_another_marks_the_two(self):
        r = self.R
        a, b, coil = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'), ('w1', ['Coil( #p )'], None)
        p = self.pair([a, a, b, coil], [a, b, a, coil])
        self.assertMarked(p, '#a', '#b')                    # the first #a is in its place
        self.assertTrue(p.reordered)

    def test_duplicates_with_a_change_elsewhere_mark_nothing(self):
        r = self.R
        a, coil = (r, ['Contact( #a )', 'Contact( #b )'], 'w1'), ('w1', ['Coil( #p )'], None)
        p = self.pair([a, a, (r, ['Contact( #m )'], 'w1'), coil], [a, a, (r, ['Contact( #x )'], 'w1'), coil])
        self.assertEqual(self.marks(p), ([], []))
        self.assertFalse(p.reordered)

    # with another change in the network
    def test_a_swap_and_a_contact_added(self):
        r = self.R
        one, two = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1')
        p = self.pair([one, two, ('w1', ['Coil( #p )'], None)],
                      [two, one, ('w1', ['Contact( #m )', 'Coil( #p )'], None)])
        self.assertMarked(p, '#a', '#b')
        self.assertEqual(self.marks(p, 'added'), ([], ['#m']))
        self.assertEqual((p.state, p.reordered), ('changed', True))

    def test_a_changed_element_keeps_its_mark(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )', 'Contact( #x )'], 'w1'), (r, ['Contact( #b )'], 'w1'),
                       ('w1', ['Coil( #p )'], None)],
                      [(r, ['Contact( #b )'], 'w1'), (r, ['Contact( #a )', 'Contact( #m )'], 'w1'),
                       ('w1', ['Coil( #p )'], None)])
        self.assertMarked(p, '#a', '#b')
        self.assertEqual(self.marks(p, 'changed'), (['#x'], ['#m']))
        self.assertTrue(p.reordered)

    def test_a_removed_element_keeps_its_mark(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )', 'Contact( #x )'], 'w1'), (r, ['Contact( #b )'], 'w1'),
                       ('w1', ['Coil( #p )'], None)],
                      [(r, ['Contact( #b )'], 'w1'), (r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None)])
        self.assertMarked(p, '#a', '#b')
        self.assertEqual(self.marks(p, 'removed'), (['#x'], []))
        self.assertTrue(p.reordered)

    def test_two_changed_branches_swapped_are_still_told(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )', 'Contact( #x )'], 'w1'), (r, ['Contact( #b )', 'Contact( #m )'], 'w1'),
                       ('w1', ['Coil( #p )'], None)],
                      [(r, ['Contact( #b )', 'Contact( #r )'], 'w1'), (r, ['Contact( #a )', 'Contact( #q )'], 'w1'),
                       ('w1', ['Coil( #p )'], None)])
        self.assertTrue(p.reordered)

    # no order
    def test_a_change_without_a_swap_is_no_order(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'), ('w1', ['Coil( #p )'], None)],
                      [(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #m )'], 'w1'), ('w1', ['Coil( #p )'], None)])
        self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])))

    def test_a_rung_added_or_deleted_shifts_the_others_only(self):
        r = self.R
        one, two, new = [(r, ['Contact( #%s )' % c, 'Coil( #%s1 )' % c], None) for c in 'abm']
        for before, after in (([one, two], [new, one, two]), ([new, one, two], [one, two]), ([one, two], [one, new, two])):
            p = self.pair(before, after)
            self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])))

    def test_coils_swapped_between_branches_is_a_rewiring_not_an_order(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )', 'Coil( #p )'], None), (r, ['Contact( #b )', 'Coil( #q )'], None)],
                      [(r, ['Contact( #a )', 'Coil( #q )'], None), (r, ['Contact( #b )', 'Coil( #p )'], None)])
        self.assertMarked(p, '#p', '#q')
        self.assertFalse(p.reordered)

    def test_a_contact_moved_into_a_branch_is_no_order(self):
        r = self.R
        p = self.pair([(r, ['Contact( #a )', ('node', 'w1'), 'Contact( #x )', 'Coil( #q )'], None),
                       (r, ['Contact( #b )'], 'w1')],
                      [(r, ['Contact( #a )', ('node', 'w1'), 'Coil( #q )'], None),
                       (r, ['Contact( #b )', 'Contact( #x )'], 'w1')])
        self.assertMarked(p, '#x')
        self.assertFalse(p.reordered)

    def test_contacts_swapped_between_two_box_pins_is_a_rewiring_not_an_order(self):
        """Row 12: each pin keeps its wire, the contacts on them changed places; both rungs end elsewhere now."""
        r = self.R
        box = '"Scale"(\n                in1 := wire#w1,\n                in2 := wire#w2\n            )'
        p = self.pair([(r, ['Contact( #a )', box], None), (r, ['Contact( #d )'], 'w1'), (r, ['Contact( #e )'], 'w2')],
                      [(r, ['Contact( #a )', box], None), (r, ['Contact( #e )'], 'w1'), (r, ['Contact( #d )'], 'w2')])
        self.assertMarked(p, '#d', '#e')
        self.assertFalse(p.reordered)

    # one of two equal rungs changed, deleted or added: nothing changed places
    def parallel(self, *contacts):
        """Contacts in parallel into one wire, the coil behind them."""
        return [(self.R, ['Contact( #%s )' % c], 'w1') for c in contacts] + [('w1', ['Coil( #p )'], None)]

    def test_one_of_two_equal_rungs_changed_is_no_order(self):
        for before, after in (('aba', 'xba'), ('aba', 'abx')):
            p = self.pair(self.parallel(*before), self.parallel(*after))
            self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])), (before, after))
            self.assertEqual(self.marks(p, 'changed'), (['#a'], ['#x']), (before, after))

    def test_one_of_two_equal_rungs_deleted_is_no_order(self):
        for before, after in (('aba', 'ba'), ('aba', 'ab')):
            p = self.pair(self.parallel(*before), self.parallel(*after))
            self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])), (before, after))
            self.assertEqual(self.marks(p, 'removed'), (['#a'], []), (before, after))

    def test_a_second_equal_rung_added_is_no_order(self):
        for before, after in (('ba', 'aba'), ('ab', 'aba')):
            p = self.pair(self.parallel(*before), self.parallel(*after))
            self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])), (before, after))
            self.assertEqual(self.marks(p, 'added'), ([], ['#a']), (before, after))

    # a contact that also stands at another node: equal parts at other wires are not one part
    def stages(self, first, second=('a', 'c')):
        """Two stages of contacts in parallel, the coil behind them."""
        r = self.R
        return ([(r, ['Contact( #%s )' % c], 'w1') for c in first] + [('w1', ['Contact( #%s )' % c], 'w2') for c in second]
                + [('w2', ['Coil( #p )'], None)])

    def test_a_swap_with_a_contact_that_also_stands_on_the_next_stage(self):
        p = self.pair(self.stages('ab'), self.stages('ba'))
        self.assertEqual(self.marks(p), (['#a', '#b'], ['#a', '#b']))
        self.assertEqual((p.state, p.reordered), ('changed', True))

    def test_the_same_swap_beside_a_change_elsewhere(self):
        old, new = self.OTHER
        p = self.pair(self.stages('ab') + [old], self.stages('ba') + [new])
        self.assertEqual(self.marks(p), (['#a', '#b'], ['#a', '#b']))
        self.assertEqual(self.marks(p, 'changed'), (['#m'], ['#n']))
        self.assertEqual((p.state, p.reordered), ('changed', True))

    def test_the_same_swap_as_exported(self):
        """The main rung runs through the first branch of each stage."""
        r = self.R
        def net(x, y):
            return [(r, ['Contact( #%s )' % x, ('node', 'w1'), 'Contact( #a )', ('node', 'w2'), 'Coil( #p )'], None),
                    (r, ['Contact( #%s )' % y], 'w1'), ('w1', ['Contact( #c )'], 'w2')]
        p = self.pair(net('a', 'b'), net('b', 'a'))
        self.assertEqual(self.marks(p), (['#a', '#b'], ['#a', '#b']))
        self.assertTrue(p.reordered)

    def test_a_swap_on_the_next_stage_marks_only_that_stage(self):
        p = self.pair(self.stages('ab', 'ac'), self.stages('ab', 'ca'))
        self.assertEqual(self.marks(p), (['#a', '#c'], ['#a', '#c']))
        self.assertTrue(p.reordered)

    def test_every_stage_of_equal_contacts_keeps_its_swap_apart(self):
        """Every part stands twice, the wires are told from the rail inward."""
        p = self.pair(self.stages('ab', 'ab'), self.stages('ba', 'ab'))
        self.assertEqual(self.marks(p), (['#a', '#b'], ['#a', '#b']))
        self.assertTrue(p.reordered)

    def test_equal_rungs_on_two_stages_changed_is_no_order(self):
        """One of two equal rungs changed, a copy on the next stage: still nothing crossed."""
        for before, after in (('aba', 'xba'), ('aba', 'ba'), ('ba', 'aba')):
            p = self.pair(self.stages(before), self.stages(after))
            self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])), (before, after))

    # two equal branches at the same wires are never swapped: no one could see it in TIA
    def exported(self, first, second='tu'):
        """Two stages as TIA exports them: the main rung through the first branch of each, the other branches behind it."""
        r = self.R
        return ([(r, ['Contact( #%s )' % first[0], ('node', 'w1'), 'Contact( #%s )' % second[0], ('node', 'w2'), 'Coil( #p )'], None)]
                + [(r, ['Contact( #%s )' % c], 'w1') for c in first[1:]]
                + [('w1', ['Contact( #%s )' % c], 'w2') for c in second[1:]])

    def test_the_branch_above_two_equal_ones_deleted_is_no_order(self):
        p = self.pair(self.exported('abb'), self.exported('bb'))
        self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])))
        self.assertEqual(self.marks(p, 'removed'), (['#a'], []))

    def test_a_branch_added_above_two_equal_ones_is_no_order(self):
        p = self.pair(self.exported('ccd'), self.exported('zccd'))
        self.assertEqual((p.reordered, self.marks(p)), (False, ([], [])))
        self.assertEqual(self.marks(p, 'added'), ([], ['#z']))

    def test_a_true_swap_with_two_equal_branches_is_still_told(self):
        """One #b changes places with #a, the other stays: one of each marked."""
        p = self.pair(self.exported('abb'), self.exported('bab'))
        self.assertEqual(self.marks(p), (['#a', '#b'], ['#a', '#b']))
        self.assertTrue(p.reordered)

    def test_random_stages_with_one_true_swap_are_always_told(self):
        """Contacts from five names, stages of two or three: a swap of two different ones, alone and beside a change."""
        rnd = random.Random(41)
        r = self.R
        for _ in range(300):
            stages = [[rnd.choice('abcdx') for _ in range(rnd.randint(2, 3))] for _ in range(rnd.randint(2, 3))]
            swapped = [list(s) for s in stages]
            s = rnd.choice(swapped)
            i, j = rnd.sample(range(len(s)), 2)
            if s[i] == s[j]:
                continue
            s[i], s[j] = s[j], s[i]
            def net(st):
                wires = [r] + ['w%d' % k for k in range(1, len(st) + 1)]
                return ([(wires[k], ['Contact( #%s )' % c], wires[k + 1]) for k, cs in enumerate(st) for c in cs]
                        + [(wires[-1], ['Coil( #p )'], None)])
            for extra in (([], []), ([self.OTHER[0]], [self.OTHER[1]])):
                p = self.pair(net(stages) + extra[0], net(swapped) + extra[1])
                self.assertTrue(self.marks(p)[0], (stages, swapped, extra))
                self.assertTrue(p.reordered, (stages, swapped, extra))

    # a rewiring beside another change is no order: the marks stay, the tag would read as cosmetic
    OTHER = (('powerrail', ['Contact( #m )', 'Coil( #z )'], None), ('powerrail', ['Contact( #n )', 'Coil( #z )'], None))

    def test_contacts_swapped_between_two_coils_beside_another_change_is_no_order(self):
        """#a drives #q now: the wires do not map one to one (w1 is w2 through #a, w1 through #p)."""
        r, (old, new) = self.R, self.OTHER
        coils = [('w1', ['Coil( #p )'], None), ('w2', ['Coil( #q )'], None)]
        p = self.pair([(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w2')] + coils + [old],
                      [(r, ['Contact( #b )'], 'w1'), (r, ['Contact( #a )'], 'w2')] + coils + [new])
        self.assertMarked(p, '#a', '#b')
        self.assertEqual((p.state, p.reordered), ('changed', False))

    def test_contacts_swapped_between_two_box_pins_beside_another_change_is_no_order(self):
        """Row 12 with a rung added: each pin keeps its wire, so the contacts' wires do not map one to one."""
        r = self.R
        box = '"Scale"(\n                in1 := wire#w1,\n                in2 := wire#w2\n            )'
        p = self.pair([(r, ['Contact( #a )', box], None), (r, ['Contact( #d )'], 'w1'), (r, ['Contact( #e )'], 'w2')],
                      [(r, ['Contact( #a )', box], None), (r, ['Contact( #e )'], 'w1'), (r, ['Contact( #d )'], 'w2'),
                       (r, ['Contact( #m )', 'Coil( #z )'], None)])
        self.assertMarked(p, '#d', '#e')
        self.assertEqual((p.state, p.reordered), ('changed', False))

    def test_a_true_swap_beside_another_change_keeps_the_tag_with_wires_renumbered(self):
        """Each wire keeps one partner, whatever its number."""
        r, (old, new) = self.R, self.OTHER
        p = self.pair([(r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w2'),
                       ('w1', ['Coil( #p )'], None), ('w2', ['Coil( #q )'], None), old],
                      [(r, ['Contact( #b )'], 'w1'), (r, ['Contact( #a )'], 'w2'),
                       ('w2', ['Coil( #p )'], None), ('w1', ['Coil( #q )'], None), new])
        self.assertMarked(p, '#a', '#b')
        self.assertTrue(p.reordered)

    def test_a_true_swap_of_branches_on_box_pins_beside_another_change_keeps_the_tag(self):
        """Two branches into one pin swapped: the pin's wire keeps its partner."""
        r = self.R
        box = '"Scale"(\n                in1 := wire#w1\n            )'
        one, two = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1')
        p = self.pair([(r, ['Contact( #m )', box], None), one, two],
                      [(r, ['Contact( #m )', box], None), two, one, (r, ['Contact( #x )', 'Coil( #z )'], None)])
        self.assertMarked(p, '#a', '#b')
        self.assertTrue(p.reordered)

    # other shapes
    def test_branches_feeding_a_box_pin(self):
        r = self.R
        box = '"Scale"(\n                in1 := wire#w1\n            )'
        one, two = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1')
        p = self.pair([one, two, (r, ['Contact( #m )', box], None)], [two, one, (r, ['Contact( #m )', box], None)])
        self.assertMarked(p, '#a', '#b')

    def test_a_branch_without_elements_swapped_is_told(self):
        r = self.R
        p = self.pair([(r, [], 'w1'), (r, ['Contact( #a )'], 'w1'), ('w1', ['Coil( #p )'], None)],
                      [(r, ['Contact( #a )'], 'w1'), (r, [], 'w1'), ('w1', ['Coil( #p )'], None)])
        self.assertEqual(p.state, 'changed')
        self.assertTrue(p.reordered)

    def test_two_rungs_of_every_fixture_network_swapped(self):
        """No crash; the logic stays unchanged; what is marked is the same on both sides."""
        rnd = random.Random(3)
        for b, n in lad_networks():
            if len(n.rungs) < 2:
                continue
            r2 = clone(n.rungs, 'o')
            i, j = rnd.sample(range(len(r2)), 2)
            r2[i], r2[j] = r2[j], r2[i]
            d = NetDiff(Graph(n.rungs), Graph(r2))
            self.assertFalse(d.changed, '%s NW%d' % (b.name, n.index))
            moved = [Counter(g.elements[e].sig() for e in g.elements if d.status[e] == 'moved') for g in (d.b, d.a)]
            self.assertEqual(moved[0], moved[1], '%s NW%d' % (b.name, n.index))

    # what the reader sees
    def test_the_drawing_has_the_blue_fill_on_both_sides_and_the_tag(self):
        r = self.R
        one, two, coil = (r, ['Contact( #a )'], 'w1'), (r, ['Contact( #b )'], 'w1'), ('w1', ['Coil( #p )'], None)
        d = compare_blocks(src(_rungs_with_nodes(one, two, coil), '', 'K'), src(_rungs_with_nodes(two, one, coil), '', 'K'))
        html = render([d], 'b', 'a')
        panes = re.findall(r'<svg [^>]*class="lad".*?</svg>', html, re.S)
        self.assertEqual([x.count('class="hl moved"') for x in panes], [2, 2])
        self.assertIn('<span class="st moved">other order</span>', html)
        tips = re.findall(r'<g class="el"><title>([^<]*)</title>', html)
        self.assertEqual(tips, ['Contact #a\nmoved', 'Contact #b\nmoved', 'Coil #p',
                                'Contact #b\nmoved', 'Contact #a\nmoved', 'Coil #p'])
        self.assertNotIn('connected differently', html)

    def test_an_order_and_something_not_read_are_both_told(self):
        """The order is no reason to drop the note: lines that differ otherwise stay told."""
        r = self.R
        d = compare_blocks(
            src(_rungs((r, ['{ f_user_card := "1" }', 'Contact( #a )', 'Coil( #p )'], None),
                       (r, ['Contact( #b )', 'Coil( #q )'], None)), '', 'K'),
            src(_rungs((r, ['Contact( #b )', 'Coil( #q )'], None),
                       (r, ['{ f_user_card := "2" }', 'Contact( #a )', 'Coil( #p )'], None)), '', 'K'))
        (p,) = d.nets
        self.assertEqual((p.state, p.reordered, p.not_shown), ('changed', True, True))
        bar = re.search(r'<div class="nwt">.*?</div>', render([d], 'b', 'a'), re.S).group(0)
        self.assertIn('other order', bar)
        self.assertIn('differs in something this report does not show', bar)


class DeclaredName(unittest.TestCase):
    def test_quoted_name_holding_a_colon(self):              # a library type's name may hold one
        from TiaChangeReports.names import decl_name
        self.assertEqual(decl_name('"Lib:Valve"'), 'Lib:Valve')
        self.assertEqual(decl_name('"FillerDb" : "Filler"'), 'FillerDb')
        self.assertEqual(decl_name('FillerDb : Filler'), 'FillerDb')
        self.assertEqual(decl_name('"Lib:Valve" : Void'), 'Lib:Valve')


class NegatedPins(unittest.TestCase):
    """A negated pin is logic: it reads NOT in an FBD network's text, on any part, a gate an operand feeds, logic feeds
    or the rung passes through, and the report names the network as changed, not as "does not show". An AND gate's
    rung-in and output read as TIA's own FBD text; a named pin has no real example and reads 'in2 := NOT #x'. TIA has no negated
    pin in LAD, only the schema allows one: should an export hold it, the drawing has no NOT and the pin is marked."""

    PATH = 'plc/blocks/Main.xml'
    VERSION = ComparedPerPart.VERSION

    def d(self, before, after):
        (d,) = [x for x in LibraryInstances.run_(self, {self.PATH: before}, {self.PATH: after})[2]
                if 'D.s7dcl' not in (x.path_a or x.path_b)]
        return d

    def net(self, parts, wires, lang='FBD'):
        """The fixture with its first network replaced. Operands: 21 #start, 22 #stop, 23 #big, 24 #latch."""
        def access(uid, name):
            return '<Access Scope="LocalVariable" UId="%d"><Symbol><Component Name="%s" /></Symbol></Access>' % (uid, name)
        flg = ('<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"><Parts>'
               + access(21, 'start') + access(22, 'stop') + access(23, 'big') + access(24, 'latch') + parts + '</Parts><Wires>'
               + ''.join('<Wire UId="%d">%s</Wire>' % (100 + k, w) for k, w in enumerate(wires)) + '</Wires></FlgNet>')
        text = re.sub(r'<FlgNet .*?</FlgNet>', lambda m: flg, _fixture(), count=1, flags=re.S)
        return text.replace('<ProgrammingLanguage>LAD</ProgrammingLanguage>\n        </AttributeList>',
                            '<ProgrammingLanguage>%s</ProgrammingLanguage>\n        </AttributeList>' % lang, 1)

    @staticmethod
    def op(uid, part, pin):
        return '<IdentCon UId="%d" /><NameCon UId="%d" Name="%s" />' % (uid, part, pin)

    @staticmethod
    def flow(a, pin_a, b, pin_b):
        return '<NameCon UId="%d" Name="%s" /><NameCon UId="%d" Name="%s" />' % (a, pin_a, b, pin_b)

    @staticmethod
    def negs(pins):
        return ''.join('<Negated Name="%s" />' % n for n in pins)

    def gate(self, negated=(), coil=(), lang='FBD'):
        """A(#start, #stop) -> assignment to #latch."""
        return self.net('<Part Name="A" UId="25"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>%s</Part>'
                        '<Part Name="Coil" UId="26">%s</Part>' % (self.negs(negated), self.negs(coil)),
                        [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.flow(25, 'out', 26, 'in'),
                         self.op(24, 26, 'operand')], lang)

    def changed(self, before, after):
        """The network, changed, no note or tag: the report shows the change; (before, after) of its text."""
        d = self.d(before, after)
        self.assertEqual((d.state, d.not_shown), ('changed', False))
        self.assertEqual([(p.state, p.not_shown) for p in d.nets], [('changed', False)])
        return d.nets[0].before.body, d.nets[0].after.body

    def test_an_input_fed_by_an_operand(self):
        before, after = self.changed(self.gate(), self.gate(['in2']))
        self.assertIn('in2 := #stop,', before)
        self.assertIn('in2 := NOT #stop,', after)
        self.assertIn('in1 := #start,', after)
        self.assertNotIn('NOT', before)

    def test_with_the_version_raised(self):
        self.changed(self.gate(), self.gate(['in2']).replace(*self.VERSION))

    def test_with_another_change_in_the_same_network(self):
        _, after = self.changed(self.gate(), self.gate(['in2']).replace('Component Name="start"', 'Component Name="count"'))
        self.assertIn('in1 := #count,', after)
        self.assertIn('in2 := NOT #stop,', after)

    def test_taken_away(self):
        before, after = self.changed(self.gate(['in2']), self.gate())
        self.assertIn('in2 := NOT #stop,', before)
        self.assertNotIn('NOT', after)

    def test_moved_to_another_input(self):
        before, after = self.changed(self.gate(['in1']), self.gate(['in2']))
        self.assertIn('NOT A(', before)
        self.assertIn('RUNG #start', before)
        self.assertIn('in2 := NOT #stop,', after)

    def test_negated_on_both_sides_is_no_change(self):
        d = self.d(self.gate(['in2']), self.gate(['in2']).replace(*self.VERSION))
        self.assertEqual([(p.state, p.not_shown) for p in d.nets if p.state != 'same'], [])

    def test_an_output_the_rung_goes_on_from(self):
        _, after = self.changed(self.gate(), self.gate(['out']))
        self.assertIn('RUNG #start\n    A( in2 := #stop ) NOT\n', after)

    def test_an_input_the_rung_comes_in_on(self):
        _, after = self.changed(self.gate(), self.gate(coil=['in']))
        self.assertIn('Coil(', after)
        self.assertIn('#latch,', after)
        self.assertIn('in := NOT,', after)
        self.assertNotIn('None', after)

    def test_an_assignment_negated_on_its_operand_stays_an_inverted_coil(self):
        _, after = self.changed(self.gate(), self.gate(coil=['operand']))
        self.assertIn('I_Coil( #latch )', after)
        self.assertNotIn('NOT', after)

    def input_fed_by_logic(self, negated=()):
        """X fed by A: the wire stays a wire."""
        return self.net('<Part Name="A" UId="25"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue></Part>'
                        '<Part Name="X" UId="26"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>%s</Part>'
                        '<Part Name="Coil" UId="27" />' % self.negs(negated),
                        [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.flow(25, 'out', 26, 'in1'),
                         self.op(23, 26, 'in2'), self.flow(26, 'out', 27, 'in'), self.op(24, 27, 'operand')])

    def test_an_input_fed_by_logic(self):
        before, after = self.changed(self.input_fed_by_logic(), self.input_fed_by_logic(['in1']))
        self.assertRegex(before, r'in1 := wire#\w+,')
        self.assertRegex(after, r'in1 := NOT wire#\w+,')

    def or_gate(self, negated=()):
        """A -> O (with #big on its other input) -> assignment."""
        return self.net('<Part Name="A" UId="25"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue></Part>'
                        '<Part Name="O" UId="26"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>%s</Part>'
                        '<Part Name="Coil" UId="27" />' % self.negs(negated),
                        [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.flow(25, 'out', 26, 'in1'),
                         self.op(23, 26, 'in2'), self.flow(26, 'out', 27, 'in'), self.op(24, 27, 'operand')])

    def test_an_or_gate_input_fed_by_an_operand(self):
        _, after = self.changed(self.or_gate(), self.or_gate(['in2']))
        self.assertIn('in2 := NOT #big,', after)

    def test_an_or_gate_input_fed_by_logic(self):
        _, after = self.changed(self.or_gate(), self.or_gate(['in1']))
        self.assertRegex(after, r'in1 := NOT wire#\w+,')

    def test_an_or_gate_output(self):
        _, after = self.changed(self.or_gate(), self.or_gate(['out']))
        self.assertIn('out => NOT,', after)

    def test_a_block_call_pin(self):
        def call(neg=''):
            return self.net('<Call UId="25"><CallInfo Name="Helper" BlockType="FC"><Parameter Name="go" Section="Input" Type="Bool" />'
                            '<Parameter Name="done" Section="Output" Type="Bool" /></CallInfo>%s</Call>' % neg,
                            [self.op(21, 25, 'go'), self.op(24, 25, 'done')])
        _, after = self.changed(call(), call('<Negated Name="go" />'))
        self.assertIn('go := NOT #start,', after)

    def test_a_pin_of_a_system_instruction(self):
        def timer(neg=''):
            return self.net('<Part Name="TON" UId="25" Version="1.0"><Instance Scope="LocalVariable" UId="26"><Component Name="t" />'
                            '</Instance>%s</Part>' % neg, [self.op(21, 25, 'IN'), self.op(22, 25, 'PT'), self.op(24, 25, 'Q')])
        _, after = self.changed(timer(), timer('<Negated Name="IN" />'))
        self.assertIn('NOT #start', after)

    def test_two_gates_negated_as_tia_draws_them(self):
        """A negated output feeding the next gate, a negated input fed by an operand, a negated open output."""
        def chain(first='', second=''):
            card = '<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>'
            return self.net('<Part Name="A" UId="25">%s%s</Part><Part Name="A" UId="26">%s%s</Part>' % (card, first, card, second),
                            [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.op(21, 26, 'in1'), self.flow(25, 'out', 26, 'in2')])
        _, after = self.changed(chain(), chain(self.negs(['out']), self.negs(['in1', 'out'])))
        self.assertEqual(after.splitlines(), ['RUNG #start', '    NOT A( in2 := wire#w1 ) NOT', 'END_RUNG',
                                              'RUNG #start', '    A( in2 := #stop ) NOT', 'END_RUNG wire#w1'])

    def test_a_gate_reads_the_same_from_either_export(self):
        """The network of a real .s7dcl export of two negated gates (names made up), against the text from the XML."""
        from TiaChangeReports.s7dcl import lad_lines
        def chain(first, second):
            card = '<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>'
            return self.net('<Part Name="A" UId="25">%s%s</Part><Part Name="A" UId="26">%s%s</Part>' % (card, first, card, second),
                            [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.op(21, 26, 'in1'), self.flow(25, 'out', 26, 'in2')])
        real = """        RUNG #start
            NOT A( in2 := wire#w1 ) NOT
        END_RUNG
        RUNG #start
            A( in2 := #stop ) NOT
        END_RUNG wire#w1
"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/Main.xml': chain(self.negs(['out']), self.negs(['in1', 'out']))})
            xml = parse_block(FolderSnapshot(d).load('plc/Main.xml')).networks[0].body
        self.assertEqual(lad_lines(xml), lad_lines(real))

    def test_a_gate_only_where_a_real_export_shows_it(self):
        """A named pin keeps what it reads (a rung-in fed by logic: test_an_input_fed_by_logic); an unnegated gate reads
        as before."""
        before, after = self.changed(self.gate(), self.gate(['in2']))
        self.assertIn('    A(\n        in1 := #start,\n        in2 := #stop,\n', before)
        self.assertIn('    A(\n        in1 := #start,\n        in2 := NOT #stop,\n', after)
        self.assertNotIn('RUNG #start', after)

    def test_a_pin_without_a_wire_is_still_told(self):
        _, after = self.changed(self.gate(), self.gate(['in3']))
        self.assertIn('in3 := NOT', after)

    def test_a_set_coil_operand(self):
        def coil(neg=''):
            return self.net('<Part Name="SCoil" UId="25">%s</Part>' % neg,
                            ['<Powerrail /><NameCon UId="25" Name="in" />', self.op(24, 25, 'operand')], 'LAD')
        _, after = self.changed(coil(), coil('<Negated Name="operand" />'))
        self.assertIn('S_Coil( NOT #latch )', after)

    # a LAD network is drawn
    def lad_contact(self, neg=''):
        return self.net('<Part Name="Contact" UId="25">%s</Part><Part Name="Coil" UId="26" />' % neg,
                        ['<Powerrail /><NameCon UId="25" Name="in" />', self.op(21, 25, 'operand'),
                         self.flow(25, 'out', 26, 'in'), self.op(24, 26, 'operand')], 'LAD')

    def lad_marked_without_not(self, before, after):
        """Changed and marked in both panes, no NOT anywhere on the page, its tooltips included: the after pane."""
        self.changed(before, after)
        html = render([self.d(before, after)], 'b', 'a')
        self.assertNotIn('NOT', html)
        panes = re.findall(r'<div class="pane">.*?</svg>', html, re.S)
        self.assertEqual(len(panes), 2)
        for pane in panes:
            self.assertIn('class="hl ', pane)
        return panes[-1]

    def test_lad_a_contact_pin_the_rung_comes_in_on(self):
        self.lad_marked_without_not(self.lad_contact(), self.lad_contact('<Negated Name="in" />'))

    def test_lad_a_contact_pin_the_rung_goes_on_from(self):
        self.lad_marked_without_not(self.lad_contact(), self.lad_contact('<Negated Name="out" />'))

    def lad_box(self, neg=''):
        """A box with an operand on one input and a contact's logic on the other."""
        return self.net('<Part Name="Contact" UId="27" /><Part Name="Rs" UId="25" Version="1.0">%s</Part>' % neg,
                        ['<Powerrail /><NameCon UId="27" Name="in" />', self.op(21, 27, 'operand'), self.flow(27, 'out', 25, 'R1'),
                         self.op(22, 25, 'S'), self.op(24, 25, 'operand')], 'LAD')

    def test_lad_a_box_pin_fed_by_an_operand(self):
        pane = self.lad_marked_without_not(self.lad_box(), self.lad_box('<Negated Name="S" />'))
        self.assertIn('stop', _text(pane))

    def test_lad_a_box_pin_the_rung_runs_through_adds_no_row(self):
        pane = self.lad_marked_without_not(self.lad_box(), self.lad_box('<Negated Name="Q" />'))
        self.assertEqual(len(re.findall(r'>Q</text>', pane)), 1)

    def test_lad_a_compare_input(self):
        def compare(neg=''):
            return self.net('<Part Name="Eq" UId="25"><TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>%s</Part>' % neg,
                            ['<Powerrail /><NameCon UId="25" Name="pre" />', self.op(21, 25, 'in1'), self.op(22, 25, 'in2')], 'LAD')
        self.assertIn('stop', _text(self.lad_marked_without_not(compare(), compare('<Negated Name="in2" />'))))

    def test_lad_the_signal_of_an_edge_contact(self):
        def edge(neg=''):
            return self.net('<Part Name="PContact" UId="25">%s</Part>' % neg,
                            ['<Powerrail /><NameCon UId="25" Name="pre" />', self.op(21, 25, 'operand'), self.op(22, 25, 'bit')], 'LAD')
        self.assertIn('start', _text(self.lad_marked_without_not(edge(), edge('<Negated Name="operand" />'))))

    def test_lad_a_box_pin_fed_by_logic_stays_wired(self):
        from TiaChangeReports.diff import Graph
        before, after = self.lad_box(), self.lad_box('<Negated Name="R1" />')
        self.changed(before, after)
        d = self.d(before, after)
        self.assertEqual([n for _, n, _ in Graph(d.nets[0].after.rungs).pins],
                         [n for _, n, _ in Graph(d.nets[0].before.rungs).pins])
        self.assertIn('R1', _text(self.lad_marked_without_not(before, after)))

    def test_the_page_carries_no_tag(self):
        d = self.d(self.gate(), self.gate(['in2']))
        html = render([d], 'b', 'a')
        self.assertNotIn(ComparedPerPart.NOTE, html)
        self.assertIn('NOT', _text(html))


class ChainedGates(unittest.TestCase):
    """Every gate of an FBD network and every operand on it is in the network's text, also a gate another gate feeds,
    and a change on one shows the network as changed. An O in LAD with nothing but wires on it stays a
    junction: that is how LAD draws and writes it."""

    PATH = NegatedPins.PATH
    d, net, changed = NegatedPins.d, NegatedPins.net, NegatedPins.changed
    op, flow = staticmethod(NegatedPins.op), staticmethod(NegatedPins.flow)
    negs = staticmethod(NegatedPins.negs)

    def gate(self, name, uid, negated=()):
        return ('<Part Name="%s" UId="%d"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>%s</Part>'
                % (name, uid, self.negs(negated)))

    def chain(self, a=(21, 22), o=23, negated=()):
        """A(a) -> O(in2 := o) -> assignment to #latch. Operands: 21 #start, 22 #stop, 23 #big, 24 #latch."""
        return self.net(self.gate('A', 25) + self.gate('O', 26, negated) + '<Part Name="Coil" UId="27" />',
                        [self.op(a[0], 25, 'in1'), self.op(a[1], 25, 'in2'), self.flow(25, 'out', 26, 'in1'),
                         self.op(o, 26, 'in2'), self.flow(26, 'out', 27, 'in'), self.op(24, 27, 'operand')])

    def two_gates(self, negated=()):
        """A(#start, #stop) and A(#big, #start) -> O -> assignment: nothing but gates on the O."""
        return self.net(self.gate('A', 25) + self.gate('A', 26) + self.gate('O', 27, negated)
                        + '<Part Name="Coil" UId="28" />',
                        [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.op(23, 26, 'in1'), self.op(21, 26, 'in2'),
                         self.flow(25, 'out', 27, 'in1'), self.flow(26, 'out', 27, 'in2'),
                         self.flow(27, 'out', 28, 'in'), self.op(24, 28, 'operand')])

    def text(self, xml):
        """The text of the network, read through a change from the fixture."""
        return next(p.after.body for p in self.d(_fixture(), xml).nets if p.after.index == 1)

    def test_the_gate_and_its_operand_are_in_the_text(self):
        text = self.text(self.chain())
        self.assertRegex(text, r'A\(\s+in1 := #start,\s+in2 := #stop,\s+\)')
        self.assertRegex(text, r'O\(\s+in2 := #big,\s+in1 := wire#w1,\s+\)\s+Coil\( #latch \)')
        self.assertIn('END_RUNG wire#w1', text)

    def test_a_changed_operand_on_the_gate(self):
        before, after = self.changed(self.chain(), self.chain(o=22))
        self.assertIn('in2 := #big,', before)
        self.assertIn('in2 := #stop,', after)

    def test_an_operand_moved_between_gates(self):
        before, after = self.changed(self.chain(a=(21, 22), o=23), self.chain(a=(21, 23), o=22))
        self.assertRegex(before, r'O\(\s+in2 := #big,')
        self.assertRegex(before, r'A\(\s+in1 := #start,\s+in2 := #stop,')
        self.assertRegex(after, r'O\(\s+in2 := #stop,')
        self.assertRegex(after, r'A\(\s+in1 := #start,\s+in2 := #big,')

    def test_a_gate_with_only_operands(self):
        def only(o):
            return self.net(self.gate('O', 25) + '<Part Name="Coil" UId="26" />',
                            [self.op(21, 25, 'in1'), self.op(o, 25, 'in2'), self.flow(25, 'out', 26, 'in'),
                             self.op(24, 26, 'operand')])
        before, after = self.changed(only(22), only(23))
        self.assertRegex(before, r'O\(\s+in1 := #start,\s+in2 := #stop,')
        self.assertIn('in2 := #big,', after)

    def test_a_gate_with_only_gates_on_it(self):
        text = self.text(self.two_gates())
        self.assertRegex(text, r'O\(\s+in1 := wire#\w+,\s+in2 := wire#\w+,\s+\)\s+Coil\( #latch \)')
        self.assertEqual(len(re.findall(r'\bA\(', text)), 2)

    def test_a_chain_of_the_same_gate(self):
        text = self.text(self.net(self.gate('O', 25) + self.gate('O', 26) + '<Part Name="Coil" UId="27" />',
                                  [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.flow(25, 'out', 26, 'in1'),
                                   self.op(23, 26, 'in2'), self.flow(26, 'out', 27, 'in'), self.op(24, 27, 'operand')]))
        self.assertRegex(text, r'O\(\s+in2 := #big,\s+in1 := wire#w1,')
        self.assertRegex(text, r'O\(\s+in1 := #start,\s+in2 := #stop,')

    # a negated gate fed by a gate: both sides hold the gate, only the pin differs
    def only_the_line_differs(self, before, after, old, new):
        b, a = self.changed(before, after)
        self.assertEqual([x.strip() for x in b.splitlines() if x not in a.splitlines()], [old])
        self.assertEqual([x.strip() for x in a.splitlines() if x not in b.splitlines()], [new])

    def test_negated_input_fed_by_a_gate(self):
        self.only_the_line_differs(self.chain(), self.chain(negated=['in1']), 'in1 := wire#w1,', 'in1 := NOT wire#w1,')

    def test_negated_input_fed_by_an_operand(self):
        self.only_the_line_differs(self.chain(), self.chain(negated=['in2']), 'in2 := #big,', 'in2 := NOT #big,')

    def test_negated_input_with_only_gates_on_it(self):
        self.only_the_line_differs(self.two_gates(), self.two_gates(['in2']), 'in2 := wire#w2,', 'in2 := NOT wire#w2,')

    def test_negation_taken_away(self):
        self.only_the_line_differs(self.chain(negated=['in1']), self.chain(), 'in1 := NOT wire#w1,', 'in1 := wire#w1,')

    # LAD
    def test_lad_an_or_of_wires_stays_a_junction(self):
        text = self.text(self.net('<Part Name="Contact" UId="25" /><Part Name="Contact" UId="26" />' + self.gate('O', 27)
                                  + '<Part Name="Coil" UId="28" />',
                                  ['<Powerrail /><NameCon UId="25" Name="in" /><NameCon UId="26" Name="in" />',
                                   self.op(21, 25, 'operand'), self.op(22, 26, 'operand'),
                                   self.flow(25, 'out', 27, 'in1'), self.flow(26, 'out', 27, 'in2'),
                                   self.flow(27, 'out', 28, 'in'), self.op(24, 28, 'operand')], 'LAD'))
        self.assertNotRegex(text, r'\bO\(')
        self.assertIn('wire#w1', text)

    def test_lad_an_or_with_an_operand_is_drawn(self):
        def lad(o):
            return self.net('<Part Name="Contact" UId="25" />' + self.gate('O', 26) + '<Part Name="Coil" UId="27" />',
                            ['<Powerrail /><NameCon UId="25" Name="in" />', self.op(21, 25, 'operand'),
                             self.flow(25, 'out', 26, 'in1'), self.op(o, 26, 'in2'), self.flow(26, 'out', 27, 'in'),
                             self.op(24, 27, 'operand')], 'LAD')
        texts, marks = EdgeOperands.pane(self, lad(22), lad(23))
        self.assertTrue(EdgeOperands.marked(self, marks, EdgeOperands.y(self, texts, '#big')))
        self.assertEqual(len(marks), 1)

    def test_a_negated_and_feeding_the_gate(self):
        """TIA's form of an AND with a negated rung-in and output, on a gate that feeds another."""
        text = self.text(self.net(self.gate('A', 25, ['in1', 'out']) + self.gate('O', 26) + '<Part Name="Coil" UId="27" />',
                                  [self.op(21, 25, 'in1'), self.op(22, 25, 'in2'), self.flow(25, 'out', 26, 'in1'),
                                   self.op(23, 26, 'in2'), self.flow(26, 'out', 27, 'in'), self.op(24, 27, 'operand')]))
        self.assertRegex(text, r'RUNG #start\s+NOT A\( in2 := #stop \) NOT\s+END_RUNG wire#w1')
        self.assertRegex(text, r'O\(\s+in2 := #big,\s+in1 := wire#w1,\s+\)\s+Coil\( #latch \)')


class WiredPinsOffTheList(unittest.TestCase):
    """A call lists its pins in its CallInfo, a Calc, Switch or JmpList by its Card, neither with EN or ENO. What is wired
    on those is logic: it is in the text, negated too, and a change on it is told, also beside another changed pin.
    The rung through EN and ENO is told by the rung."""

    PATH = NegatedPins.PATH
    d, net, changed = NegatedPins.d, NegatedPins.net, NegatedPins.changed
    op, flow = staticmethod(NegatedPins.op), staticmethod(NegatedPins.flow)
    negs = staticmethod(NegatedPins.negs)
    text = ChainedGates.text
    INFO = ('<CallInfo Name="Helper" BlockType="FC"><Parameter Name="go" Section="Input" Type="Bool" />'
            '<Parameter Name="done" Section="Output" Type="Bool" /></CallInfo>')

    def call(self, en=21, go=22, negated=(), lang='FBD', info=None, extra=()):
        """Operands: 21 #start, 22 #stop, 23 #big, 24 #latch."""
        return self.net('<Call UId="25">%s%s</Call>' % (info or self.INFO, self.negs(negated)),
                        [self.op(en, 25, 'en'), self.op(go, 25, 'go'), self.op(24, 25, 'done')] + list(extra), lang)

    def test_the_operand_is_in_the_text(self):
        self.assertRegex(self.text(self.call()), r'"Helper"\(\s+en := #start,\s+go := #stop,\s+done => #latch,\s+\)')

    def test_a_change_on_it_alone(self):
        before, after = self.changed(self.call(en=21), self.call(en=23))
        self.assertIn('en := #start,', before)
        self.assertIn('en := #big,', after)

    def test_a_change_on_it_beside_another_changed_pin(self):
        before, after = self.changed(self.call(en=21, go=22), self.call(en=23, go=21))
        self.assertIn('en := #start,', before)
        self.assertIn('go := #stop,', before)
        self.assertIn('en := #big,', after)
        self.assertIn('go := #start,', after)

    def test_negated(self):
        before, after = self.changed(self.call(), self.call(negated=['en']))
        self.assertIn('en := #start,', before)
        self.assertIn('en := NOT #start,', after)
        self.assertNotRegex(after, r'en := NOT,')

    def test_negated_beside_another_changed_pin(self):
        before, after = self.changed(self.call(), self.call(go=23, negated=['en']))
        self.assertIn('en := NOT #start,', after)
        self.assertIn('go := #big,', after)

    def test_on_a_call_with_an_instance(self):
        info = ('<CallInfo Name="Helper" BlockType="FB"><Instance Scope="LocalVariable" UId="30"><Component Name="inst" />'
                '</Instance><Parameter Name="go" Section="Input" Type="Bool" />'
                '<Parameter Name="done" Section="Output" Type="Bool" /></CallInfo>')
        self.assertRegex(self.text(self.call(info=info)), r'#inst\(\s+en := #start,')

    def test_an_operand_on_eno(self):
        text = self.text(self.call(extra=['<NameCon UId="25" Name="eno" /><IdentCon UId="23" />']))     # a wire starts at an output
        self.assertRegex(text, r'done => #latch,\s+eno => #big,')

    def fed_by_a_gate(self, negated=()):
        return self.net('<Part Name="A" UId="26"><TemplateValue Name="Card" Type="Cardinality">2</TemplateValue></Part>'
                        '<Call UId="25">%s%s</Call>' % (self.INFO, self.negs(negated)),
                        [self.op(21, 26, 'in1'), self.op(23, 26, 'in2'), self.flow(26, 'out', 25, 'en'),
                         self.op(22, 25, 'go'), self.op(24, 25, 'done')])

    def test_the_rung_through_en_stays_the_rung(self):
        self.assertNotIn('en :=', self.text(self.fed_by_a_gate()))

    def test_negated_with_the_rung_through_en(self):
        _, after = self.changed(self.fed_by_a_gate(), self.fed_by_a_gate(['en']))
        self.assertIn('en := NOT,', after)

    def test_an_open_en_is_not_told(self):
        xml = self.net('<Call UId="25">%s</Call>' % self.INFO,
                       ['<OpenCon UId="30" /><NameCon UId="25" Name="en" />', self.op(22, 25, 'go'), self.op(24, 25, 'done')])
        self.assertNotIn('en :=', self.text(xml))

    def test_parts_sized_by_their_card(self):
        for part, pins in (('Calc', ['in1', 'in2', 'out']), ('Switch', ['k', 'case0', 'dest0']), ('JmpList', ['k', 'dest0'])):
            with self.subTest(part):
                def sized(en, negated=()):
                    return self.net('<Part Name="%s" UId="25"><TemplateValue Name="Card" Type="Cardinality">%d</TemplateValue>%s'
                                    '</Part>' % (part, 2 if part == 'Calc' else 1, self.negs(negated)),
                                    [self.op(en, 25, 'en')] + [self.op(22, 25, p) for p in pins])
                before, after = self.changed(sized(21), sized(23))
                self.assertIn('en := #start,', before)
                self.assertIn('en := #big,', after)
                self.assertIn('en := NOT #start,', self.text(sized(21, ['en'])))

    def test_a_part_with_its_own_list_keeps_it(self):
        xml = self.net('<Part Name="Move" UId="25"><TemplateValue Name="Card" Type="Cardinality">1</TemplateValue></Part>',
                       [self.op(21, 25, 'en'), self.op(22, 25, 'in'), self.op(24, 25, 'out1')])
        self.assertEqual(self.text(xml).count('en := #start'), 1)

    # a LAD network is drawn
    def test_lad_it_is_drawn_and_marked(self):
        texts, marks = EdgeOperands.pane(self, self.call(en=21, lang='LAD'), self.call(en=23, lang='LAD'))
        self.assertTrue(EdgeOperands.marked(self, marks, EdgeOperands.y(self, texts, '#big')))
        self.assertFalse(EdgeOperands.marked(self, marks, EdgeOperands.y(self, texts, '#stop')))

    def test_lad_negated_is_marked(self):
        """LAD draws no NOT (TIA has no negated pin there): the operand is drawn and marked."""
        texts, marks = EdgeOperands.pane(self, self.call(lang='LAD'), self.call(negated=['en'], lang='LAD'))
        self.assertNotIn('NOT', [t for _, t in texts])
        self.assertTrue(EdgeOperands.marked(self, marks, EdgeOperands.y(self, texts, '#start')))
        self.assertFalse(EdgeOperands.marked(self, marks, EdgeOperands.y(self, texts, '#stop')))


class EdgeOperands(unittest.TestCase):
    """A P / N contact or coil has two operands: the signal above the element, the edge memory (bit) below it, as TIA
    draws them; a timer coil its timer and its time. A changed bit is drawn and marked there. The forms are
    the ones real exports hold, the names made up."""

    PATH = NegatedPins.PATH
    # part, the pin the rung comes in on
    PARTS = (('PContact', 'pre'), ('NContact', 'pre'), ('PCoil', 'in'), ('NCoil', 'in'))

    def sample(self, part, rung_in, neg='', bit_first=False, bit=22, signal=21):
        n = NegatedPins('test_taken_away')
        wires = [n.op(signal, 25, 'operand'), n.op(bit, 25, 'bit')]
        return n.net('<Part Name="%s" UId="25">%s</Part>' % (part, neg),
                     ['<Powerrail /><NameCon UId="25" Name="%s" />' % rung_in] + (wires[::-1] if bit_first else wires), 'LAD')

    def pane(self, before, after, k=-1):
        """(texts as [(y, text)], the marks as [(y, height)]) of one pane of the network's drawing, and the network."""
        d = NegatedPins.d(self, before, after)
        self.assertEqual((d.state, d.not_shown), ('changed', False))
        self.assertEqual([(p.state, p.not_shown) for p in d.nets], [('changed', False)])
        svg = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)[k]
        texts = [(float(y), s) for y, s in re.findall(r'<text [^>]*?y="([\d.]+)"[^>]*>([^<]*)</text>', svg)]
        marks = [(float(y), float(h)) for y, h in re.findall(r'<rect class="hl [^"]*" x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"', svg)]
        return texts, marks

    def y(self, texts, s):
        (y,) = [y for y, t in texts if t == s]
        return y

    def marked(self, marks, y):
        return any(top <= y <= top + h for top, h in marks)

    def test_the_bit_is_below_and_the_signal_above(self):
        for part, rung_in in self.PARTS:
            for first in (False, True):                       # whichever wire comes first in the export
                texts, _ = self.pane(self.sample(part, rung_in, bit_first=first), self.sample(part, rung_in, bit_first=first, bit=23))
                self.assertLess(self.y(texts, '#start'), self.y(texts, '#big'), part)
                self.assertNotIn('#stop', [t for _, t in texts], part)

    def test_a_changed_bit_is_marked_and_the_signal_is_not(self):
        for part, rung_in in self.PARTS:
            before, after = self.sample(part, rung_in), self.sample(part, rung_in, bit=23)
            texts, marks = self.pane(before, after)
            self.assertTrue(self.marked(marks, self.y(texts, '#big')), part)
            self.assertFalse(self.marked(marks, self.y(texts, '#start')), part)
            texts, marks = self.pane(before, after, 0)            # and the before side
            self.assertTrue(self.marked(marks, self.y(texts, '#stop')), part)
            self.assertFalse(self.marked(marks, self.y(texts, '#start')), part)

    def test_a_changed_signal_is_marked_and_the_bit_is_not(self):
        for part, rung_in in self.PARTS:
            texts, marks = self.pane(self.sample(part, rung_in), self.sample(part, rung_in, signal=23))
            self.assertTrue(self.marked(marks, self.y(texts, '#big')), part)
            self.assertFalse(self.marked(marks, self.y(texts, '#stop')), part)

    def view(self, instr, params):
        return render_lad.View(Element('e', instr, None, params, {}), parse_block(_xml_src()).interface)

    def test_the_row_makes_room_for_what_is_below_the_element(self):
        one = self.view('Contact', [(None, None, '#a')])
        two = self.view('P_Contact', [('operand', ':=', '#a'), ('bit', ':=', '#b')])
        self.assertEqual(one.below, 12)
        self.assertGreater(two.below, one.below)
        # the last line and its mark stay inside the row
        self.assertGreaterEqual(two.below, two.marks(0, 0, 'changed', {'bit'})[0][2] + two.marks(0, 0, 'changed', {'bit'})[0][4])

    def test_the_export_format_of_the_same_contact(self):
        """.s7dcl names both operands, the signal first."""
        for instr in ('P_Contact', 'N_Contact', 'P_Coil', 'N_Coil'):
            v = self.view(instr, [('operand', ':=', '#a'), ('bit', ':=', '#b')])
            self.assertEqual(([s for s, _, _ in v.top], [s for s, _, _ in v.bot]), (['#a'], ['#b']), instr)

    def test_a_timer_coil_draws_its_timer_above_and_its_time_below(self):
        """As the real exports write it: TP_Coil( timer => #t, pt := T#200ms ), also TOF_Coil."""
        for instr in ('TP_Coil', 'TOF_Coil'):
            v = self.view(instr, [('timer', '=>', '#t'), ('pt', ':=', 'T#200ms')])
            self.assertEqual(([s for s, _, _ in v.top], [s for s, _, _ in v.bot]), (['#t'], ['T#200ms']), instr)
            below, above = v.marks(0, 0, 'changed', {'pt'}), v.marks(0, 0, 'changed', {'timer'})
            self.assertEqual((len(below), len(above)), (1, 1), instr)
            self.assertGreater(below[0][2], 0, instr)
            self.assertLess(above[0][2], 0, instr)

    def test_the_operand_above_a_coil_whatever_the_order(self):
        for instr, above, below in (('PT_Coil', 'timer', 'pt'), ('SC_Coil', 'counter', 'pv'), ('R_BitfieldCoil', 'operand', 'n')):
            v = self.view(instr, [(below, ':=', '#b'), (above, ':=', '#a')])
            self.assertEqual(([s for s, _, _ in v.top], [s for s, _, _ in v.bot]), (['#a'], ['#b']), instr)

    def test_a_coil_written_on_its_instance(self):
        v = render_lad.View(Element('e', 'TP_Coil', '#t', [(None, None, 'T#5s')], {}), parse_block(_xml_src()).interface)
        self.assertEqual(([s for s, _, _ in v.top], [s for s, _, _ in v.bot]), (['#t'], ['T#5s']))

    TIMER_USER = """FUNCTION_BLOCK "TimerUser"
    VAR
        go : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "time_type := Time" }
            "%s".%s(
                PT := T#5s,
                ET =>
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""

    def timer_view(self, instr='TON', db='TimerDb', number='7', kind=': IEC_TIMER'):
        """A timer box, its instance DB of a type no snapshot holds, as TIA's IEC_Timer_0_DB."""
        from TiaChangeReports.compare import Callees
        files = {'plc/TimerUser.s7dcl': self.TIMER_USER % (db, instr)}
        if number:
            files['plc/%s.s7dcl' % db] = '{\n    S7_BlockNumber := "%s"\n}\nDATA_BLOCK %s %s\nEND_DATA_BLOCK\n' % (number, db, kind)
        with tempfile.TemporaryDirectory() as d:
            _write(d, files)
            snap = FolderSnapshot(d)
            b = parse_block(snap.load('plc/TimerUser.s7dcl'))
            lay = Layout(b.networks[0].rungs, b.interface, Callees(snap))
            (v,) = lay.views.values()
            return v, b.interface

    def test_a_timer_box_has_its_db_number_above_its_instance(self):
        for instr in ('TOF', 'TON', 'TP'):
            v, _ = self.timer_view(instr)
            above, _, _ = v._above(0, 100)
            self.assertEqual([s for s, _, _ in above], ['%DB7', '"TimerDb"'], instr)
            self.assertEqual(above[0][1], render_lad.C_NUM, instr)
            ys = {s.replace('&quot;', '"'): float(y)
                  for y, s in re.findall(r'<text [^>]*?y="([\d.]+)"[^>]*>([^<]*)</text>', ''.join(v.draw(0, 100)))}
            self.assertLess(ys['%DB7'], ys['"TimerDb"'], instr)
            self.assertGreaterEqual(min(ys.values()), 100 - v.above, instr)

    def test_a_timer_box_with_its_db_numbered_automatically_in_an_xml_export(self):
        """Most real instance DBs: TIA draws the number, and the comparison of the DB's properties leaves it out."""
        from TiaChangeReports.compare import Callees
        db = ('<Document><SW.Blocks.InstanceDB ID="0"><AttributeList><AutoNumber>%s</AutoNumber><InstanceOfName>IEC_TIMER</InstanceOfName>'
              '<Name>TimerDb</Name><Number>16</Number><ProgrammingLanguage>DB</ProgrammingLanguage></AttributeList></SW.Blocks.InstanceDB></Document>')
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/TimerUser.s7dcl': self.TIMER_USER % ('TimerDb', 'TP'), 'plc/TimerDb.xml': db % 'true'})
            snap = FolderSnapshot(d)
            b = parse_block(snap.load('plc/TimerUser.s7dcl'))
            (v,) = Layout(b.networks[0].rungs, b.interface, Callees(snap)).views.values()
            self.assertEqual([s for s, _, _ in v.instnum], ['%DB16'])
            auto = parse_block(snap.load('plc/TimerDb.xml'))
            self.assertEqual((auto.auto_number, auto.props.get('S7_BlockNumber')), ('16', None))
            _write(d, {'plc/TimerDb.xml': db % 'false'})
            manual = parse_block(FolderSnapshot(d).load('plc/TimerDb.xml'))
            self.assertEqual((manual.auto_number, manual.props.get('S7_BlockNumber')), (None, '16'))

    def test_a_timer_box_without_its_db_in_the_snapshot_has_no_number(self):
        v, _ = self.timer_view(number='')
        self.assertEqual([s for s, _, _ in v._above(0, 100)[0]], ['"TimerDb"'])

    def test_another_db_number_is_marked_above_the_box(self):
        one, _ = self.timer_view(number='7')
        two, _ = self.timer_view(number='8')
        self.assertEqual(one.drawn_otherwise(two), {'#inst'})
        self.assertEqual(one.drawn_otherwise(self.timer_view(number='7')[0]), set())
        (mark,) = one.marks(0, 100, 'changed', {'#inst'})
        self.assertLess(mark[2], 100 - one.head)

    def test_the_text_inside_a_coil(self):
        """As TIA in a network of the coils; the timer coils without a type in the export: their kind alone."""
        for instr, text in (('P_Coil', 'P'), ('N_Coil', 'N'), ('PT_Coil', 'PT'), ('RT_Coil', 'RT'), ('SC_Coil', 'SC'), ('CU_Coil', 'CU'),
                            ('CD_Coil', 'CD'), ('R_BitfieldCoil', 'RESET_BF'), ('S_BitfieldCoil', 'SET_BF'), ('S_Coil', 'S'), ('R_Coil', 'R'),
                            ('I_Coil', '/'), ('Coil', ''), ('TP_Coil', 'TP'), ('TOF_Coil', 'TOF'), ('TOf_Coil', 'TOF'), ('TOn_Coil', 'TON'),
                            ('TOnr_Coil', 'TONR'), ('JumpCoil', 'JMP'), ('ReturnCoil', 'RET')):
            svg = ''.join(self.view(instr, [('operand', ':=', '#a')]).draw(0, 100))
            inside = [s for y, s in re.findall(r'<text [^>]*?y="([\d.]+)"[^>]*>([^<]*)</text>', svg) if abs(float(y) - 104) < 1]
            self.assertEqual(inside, [text] if text else [], instr)

    def xml_coil(self, part, rung_in, pins):
        """A coil as a real SimaticML export writes it: its second operand's wire first. pins: [(pin, access uid)]."""
        n = NegatedPins('test_taken_away')
        return n.net('<Part Name="%s" UId="25" />' % part, ['<Powerrail /><NameCon UId="25" Name="%s" />' % rung_in]
                     + [n.op(uid, 25, pin) for pin, uid in pins], 'LAD')

    def test_the_coils_of_a_simaticml_export_are_coils_with_their_text_and_operands(self):
        for part, rung_in, second, text in (('PtCoil', 'in', 'pt', 'PT'), ('ScCoil', 'in', 'value', 'SC'), ('RBitfield', 'en', 'n', 'RESET_BF'),
                                            ('SBitfield', 'en', 'n', 'SET_BF'), ('PCoil', 'in', 'bit', 'P'), ('NCoil', 'in', 'bit', 'N')):
            texts, marks = self.pane(self.xml_coil(part, rung_in, [(second, 22), ('operand', 21)]),
                                     self.xml_coil(part, rung_in, [(second, 23), ('operand', 21)]))
            self.assertEqual([t for _, t in sorted(texts)], ['#start', text, '#big'], part)    # no EN, ENO or pin name: no box
            self.assertTrue(self.marked(marks, self.y(texts, '#big')), part)
            self.assertFalse(self.marked(marks, self.y(texts, '#start')), part)

    def test_the_coils_of_one_operand_of_a_simaticml_export(self):
        for part, text in (('CuCoil', 'CU'), ('CdCoil', 'CD'), ('ResetIECTimerCoil', 'RT'), ('SCoil', 'S'), ('RCoil', 'R')):
            texts, marks = self.pane(self.xml_coil(part, 'in', [('operand', 21)]), self.xml_coil(part, 'in', [('operand', 23)]))
            self.assertEqual([t for _, t in sorted(texts)], ['#big', text], part)
            self.assertTrue(self.marked(marks, self.y(texts, '#big')), part)

    def timer_coil(self, instr='TP_Coil', kind='Time', pt='T#200ms'):
        templates = {'time_type': kind} if kind else {}
        return render_lad.View(Element('e', instr, None, [('timer', '=>', '#t'), ('pt', ':=', pt)], templates),
                               parse_block(_xml_src()).interface)

    @staticmethod
    def texts(v, y=100):
        return [(float(a), s) for a, s in re.findall(r'<text [^>]*?y="([\d.]+)"[^>]*>([^<]*)</text>', ''.join(v.draw(0, y)))]

    def test_a_timer_coil_has_its_kind_over_its_type_in_one_tall_coil(self):
        for instr, kind in (('TP_Coil', 'TP'), ('TOF_Coil', 'TOF'), ('TOf_Coil', 'TOF'), ('TOn_Coil', 'TON'), ('TOnr_Coil', 'TONR')):
            v = self.timer_coil(instr)
            ys = {s: a for a, s in self.texts(v)}
            self.assertLess(ys['#t'], ys[kind], instr)
            self.assertLess(ys[kind], ys['Time'], instr)
            self.assertLess(ys['Time'], ys['T#200ms'], instr)
            arcs = re.findall(r'<path d="M[\d.]+ ([\d.]+) A \d+ \d+ 0 0 \d [\d.]+ ([\d.]+)"', ''.join(v.draw(0, 100)))
            self.assertEqual(len(arcs), 2, instr)                    # one coil, not two stacked
            for top, bottom in arcs:
                self.assertLess(float(top), ys[kind] - 8, instr)     # the arcs reach past both lines
                self.assertGreater(float(bottom), ys['Time'], instr)
                self.assertGreater(float(top), ys['#t'], instr)      # and stay clear of the operands
                self.assertLess(float(bottom), ys['T#200ms'] - 8, instr)
            self.assertGreaterEqual(100 + v.below, ys['T#200ms'], instr)
            self.assertGreaterEqual(ys['#t'] - 10, 100 - v.above, instr)

    def test_the_type_inside_a_timer_coil_is_the_exports(self):
        self.assertEqual({s for _, s in self.texts(self.timer_coil(kind='LTime', pt='LT#1s'))}, {'#t', 'TP', 'LTime', 'LT#1s'})
        self.assertEqual({s for _, s in self.texts(self.timer_coil(kind=''))}, {'#t', 'TP', 'T#200ms'})

    def test_a_timer_coil_read_from_an_export(self):
        src = """FUNCTION_BLOCK "TimerUser"
    VAR
        t : IEC_TIMER;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "time_type := Time" }
            TOF_Coil(
                timer => #t,
                pt := T#3s
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'plc/TimerUser.s7dcl': src})
            b = parse_block(FolderSnapshot(d).load('plc/TimerUser.s7dcl'))
        (v,) = Layout(b.networks[0].rungs, b.interface, None).views.values()
        self.assertEqual({s for _, s in self.texts(v)}, {'#t', 'TOF', 'Time', 'T#3s'})

    def test_another_type_inside_a_timer_coil_is_marked_on_the_coil(self):
        x, y = self.timer_coil(kind='Time').el, self.timer_coil(kind='LTime').el
        self.assertEqual(changed_params(x, y), {'templates'})
        v = self.timer_coil()
        (mark,) = v.marks(0, 100, 'changed', {'templates'})
        ys = {s: a for a, s in self.texts(v)}
        self.assertLess(mark[2], ys['TP'] - 8)
        self.assertGreater(mark[2] + mark[4], ys['Time'])
        self.assertGreater(mark[2], ys['#t'])                         # the operands are not marked
        self.assertLess(mark[2] + mark[4], ys['T#200ms'] - 8)

    def test_a_coil_of_one_line_keeps_its_height(self):
        for instr in ('Coil', 'PT_Coil', 'R_BitfieldCoil'):
            v = self.view(instr, [('operand', ':=', '#a')])
            self.assertEqual((v.tall, v.above, v.below), (0, 14 + render_lad.LINE, 12), instr)

    def test_the_reset_timer_coil_is_square_and_the_others_round(self):
        def paths(instr):
            return re.findall(r'<path d="([^"]+)"', ''.join(self.view(instr, [(None, None, '#t')]).draw(0, 100)))
        square = paths('RT_Coil')
        self.assertEqual(len(square), 2)
        left, right = [[float(n) for n in re.findall(r'[\d.]+', d)] for d in square]
        self.assertTrue(all(' A ' not in d for d in square))
        c = render_lad.CELL / 2
        self.assertEqual(left[2], c - 11)                             # a vertical bar each side of the text,
        self.assertEqual(right[2], c + 11)
        self.assertEqual((left[1], left[3]), (91, 109))               # as high as a round coil, its ticks inwards
        self.assertGreater(left[0], left[2])
        self.assertLess(right[0], right[2])
        for instr in ('Coil', 'S_Coil', 'R_Coil', 'PT_Coil', 'CU_Coil', 'SC_Coil', 'R_BitfieldCoil', 'TP_Coil'):
            self.assertTrue(all(' A ' in d for d in paths(instr)), instr)

    def test_the_wire_ends_at_the_bars_of_the_square_coil(self):
        svg = ''.join(self.view('RT_Coil', [(None, None, '#t')]).draw(0, 100))
        c = render_lad.CELL / 2
        self.assertIn('x2="%.1f"' % (c - 11), svg)
        self.assertIn('x1="%.1f"' % (c + 11), svg)

    def test_a_long_text_widens_the_coil_and_a_short_one_does_not(self):
        def arcs(instr):
            svg = ''.join(self.view(instr, [('operand', ':=', '#a')]).draw(0, 100))
            return [float(x) for x in re.findall(r'<path d="M([\d.]+) ', svg)]
        self.assertEqual(arcs('Coil'), [render_lad.CELL / 2 - 5, render_lad.CELL / 2 + 5])
        self.assertEqual(arcs('P_Coil'), arcs('Coil'))
        left, right = arcs('R_BitfieldCoil')
        self.assertGreaterEqual(right - left + 2 * 4.6, render_lad.tw('RESET_BF', 9, True))

    def test_any_further_operand_of_a_contact_or_coil_is_below(self):
        """Not only edges: nothing a contact or coil holds is left out of the drawing."""
        v = self.view('R_BitfieldCoil', [('operand', ':=', '#a'), ('n', ':=', '3')])
        self.assertEqual(([s for s, _, _ in v.top], [s for s, _, _ in v.bot]), (['#a'], ['3']))
        keys = {'n'}
        self.assertEqual(len(v.marks(0, 0, 'changed', keys)), 1)
        self.assertGreater(v.marks(0, 0, 'changed', keys)[0][2], 0)

    def test_a_plain_contact_draws_as_before(self):
        v = self.view('Contact', [(None, None, '#a')])
        self.assertEqual(([s for s, _, _ in v.top], v.bot), (['#a'], []))
        self.assertEqual((v.above, v.below), (14 + render_lad.LINE, 12))


if __name__ == '__main__':
    unittest.main()
