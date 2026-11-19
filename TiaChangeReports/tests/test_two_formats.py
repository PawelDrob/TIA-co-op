"""The bed of the two formats (twoformats.py) on real pairs from the two-format benchmark run: a repo of three commits,
each holding .s7dcl under plc/ and SimaticML of the same objects under simaticml/, as that run's repo does.

1-before: the files of each object at the parent of the row that changes it, both formats: zzBenTimers at 55261f5
  (B057 undone, B058's parent); zzE2eFbI and its instance DB zzE2eFbI_DB at 5b253ff (D008, D009's parent); zzE2eUdtA
  at 5b253ff, the same files as at the start state bf6a976.
2-B058: zzBenTimers at 9c27dcb, the run's row B058, pin PV of a CTU reads another operand.
3-D009: zzE2eFbI_DB at eb1fe5e, the run's row D009, a member made retain (TIA moved the .s7dcl only)."""
import os
import shutil
import subprocess
import tempfile
import unittest

from TiaChangeReports import twoformats
from TiaChangeReports.s7dcl import Element

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twoformats')
TIMERS, UDT = 'plc/blocks/zzBenchmark/zzBenTimers', 'plc/types/zzE2e/zzE2eUdtA'
FB, IDB = 'plc/blocks/zzE2e/zzE2eFbI', 'plc/blocks/zzE2e/zzE2eFbI_DB'


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                    '-c', 'core.autocrlf=false', *args], check=True, capture_output=True, env=env)


class RunRepo(unittest.TestCase):
    """The three commits in a repo of their own."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = cls.tmp.name
        git(cls.repo, 'init', '-q')
        for step in sorted(os.listdir(FIXTURES)):
            shutil.copytree(os.path.join(FIXTURES, step), cls.repo, dirs_exist_ok=True)
            git(cls.repo, 'rm', '-r', '-q', '--cached', '--ignore-unmatch', '.')   # a copy keeps its file time
            git(cls.repo, 'add', '-A')
            git(cls.repo, 'commit', '-q', '-m', step)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_nothing_changed_lists_each_object_with_its_causes(self):
        got = {(x['object'], tuple(x['network']) if x['network'] else None): x['causes']
               for x in twoformats.nothing_changed(self.repo, 'HEAD~2')}
        self.assertEqual({
            (TIMERS, None): ['note: files'],
            (FB, None): ['ENO'],
            (FB, (1, 1, '')): ['ENO'],
            (IDB, None): ['DB retain', 'instance DB access', 'instance DB start values'],
            (UDT, None): ['declaration'],
        }, got)

    def test_the_same_change_where_pins_are_written_in_another_case_and_order(self):
        """B058's CTU: r, pv, cv in .s7dcl, PV, CV, R in SimaticML."""
        self.assertEqual([], twoformats.same_change(self.repo, 'HEAD~2', 'HEAD~1'))

    def test_a_field_one_format_moved_alone(self):
        got = twoformats.same_change(self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual([(IDB, ['DB retain'])], [(x['object'], x['causes']) for x in got])
        self.assertEqual([], got[0]['xml'], 'the SimaticML report holds nothing of it')

    def test_counts_name_every_cause_and_its_kind(self):
        result = twoformats.run(self.repo, None, None, ('nothing', 'same'))
        text = '\n'.join(twoformats.counts(result))
        self.assertIn('Nothing changed: 3 commits', text)
        self.assertIn('The same change: 2 commits, 1 whose two reports differ', text)
        self.assertRegex(text, r'DB retain\s+a field only one format writes')
        self.assertNotIn('unknown', text)


class DefaultStart(unittest.TestCase):
    """With no --since, the run starts at the first commit with a file under simaticml/: a repo's first commits may
    hold no export (the benchmark run's repo starts with its bridge's files)."""

    def test_commits_before_simaticml_are_left_out(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q')
            with open(os.path.join(repo, 'tiabridge.json'), 'w', encoding='utf-8') as f:
                f.write('{}')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-q', '-m', 'repo')
            shutil.copytree(os.path.join(FIXTURES, '1-before'), repo, dirs_exist_ok=True)
            git(repo, 'add', '-A')
            git(repo, 'commit', '-q', '-m', 'both formats')
            self.assertEqual(1, len(twoformats.commits(repo)))
            text = '\n'.join(twoformats.counts(twoformats.run(repo, None, None, ('nothing',))))
            self.assertIn('Nothing changed: 1 commits', text)


class UnknownWhereFactsDiffer(unittest.TestCase):
    """A state, kind or language both reports list otherwise, and a network title or comment that differs, has no
    cause the bed names: it is unknown, never dropped beside another cause."""

    O, N = 'plc/blocks/zzBenchmark/zzBenTimers', (1, 1, '14 Counter with fed pins')

    def block(self, sd, xml):
        from collections import Counter
        return twoformats._block_part(self.O, None, None, Counter(sd), Counter(xml), None)

    def network(self, sd, xml):
        from collections import Counter
        return twoformats._net_part(self.N, None, Counter(sd), Counter(xml))

    def test_another_state(self):
        o = self.O
        self.assertEqual({'unknown: state changed / new'},
                         self.block([(o, 'state', 'changed'), (o, 'kind', 'FB')], [(o, 'state', 'new'), (o, 'kind', 'FB')]))

    def test_another_kind(self):
        o = self.O
        self.assertEqual({'unknown: kind DB / Instance DB'},
                         self.block([(o, 'state', 'changed'), (o, 'kind', 'DB')],
                                    [(o, 'state', 'changed'), (o, 'kind', 'Instance DB')]))

    def test_another_language(self):
        o, n = self.O, self.N
        self.assertEqual({'unknown: network changed LAD / changed FBD'},
                         self.network([(o, 'network', n, 'changed', 'LAD')], [(o, 'network', n, 'changed', 'FBD')]))

    def test_a_title_beside_another_cause(self):
        o, n = self.O, self.N
        net = (o, 'network', n, 'changed', 'LAD')
        tag = (o, 'network tag', n, 'other order')
        self.assertEqual({'unknown: network title', 'rung order'},
                         self.network([net, (o, 'network title', n, 'a', 'b'), tag], [net]))


class ElementCauses(unittest.TestCase):
    """What makes two readings of one element unequal, as compared (Element.sig)."""

    SD = ('CTU', '#instCtu', '', (('cv', '=>', '#statStep'), ('pv', ':=', '#inSpeed'), ('r', ':=', 'wire#')),
          (('value_type', 'Int'),), '', False)

    def test_pins_in_another_case_and_order_are_no_reading(self):
        """The CTU of zzBenTimers as each reader reads it: r, pv, cv from .s7dcl, PV, CV, R from SimaticML."""
        xml = Element('e', 'CTU', '#instCtu', [('PV', ':=', '#inSpeed'), ('CV', '=>', '#statStep'),
                                               ('R', ':=', 'wire#w1')], {'value_type': 'Int'}).sig()
        self.assertEqual(set(), twoformats.element_causes(self.SD, xml))

    def test_unnamed_operands_in_another_order(self):
        x = ('Box', '', '', (('', '', '#a'), ('', '', '#b')), (), '', False)
        self.assertEqual({'pin order'}, twoformats.element_causes(x, x[:3] + ((('', '', '#b'), ('', '', '#a')),) + x[4:]))

    def test_another_operand_is_no_reading(self):
        pins = (('cv', '=>', '#statStep'), ('pv', ':=', '#inLevel'), ('r', ':=', 'wire#'))
        other = self.SD[:3] + (pins,) + self.SD[4:]
        self.assertEqual({'unknown: element CTU'}, twoformats.element_causes(self.SD, other))

    def test_quoted_member_names(self):
        x = ('Contact', '', '', (('', '', '"zzInvBenF"."a"'),), (), '', False)
        y = ('Contact', '', '', (('', '', '"zzInvBenF".a'),), (), '', False)
        self.assertEqual({'quoted names'}, twoformats.element_causes(x, y))

    def test_a_block_calls_pin_in_another_case(self):
        """A pin of a block call compares as written: the bed names it, as a user may rename it in case."""
        x = ('CALL', '', 'Helper', (('go', ':=', '#a'),), (), '', False)
        self.assertEqual({'pin case'}, twoformats.element_causes(x, x[:3] + ((('Go', ':=', '#a'),),) + x[4:]))

    def test_eno_alone(self):
        """The Move of zzBenBoxes network 1: no S7_GenerateENO in .s7dcl, DisabledENO="true" in SimaticML."""
        x = ('Move', '', '', (('in', ':=', '#outValue'), ('out1', '=>', '"zzInvBen".val[4]')), (), '', False)
        self.assertEqual({'ENO'}, twoformats.element_causes(x, x[:6] + (True,)))


if __name__ == '__main__':
    unittest.main()
