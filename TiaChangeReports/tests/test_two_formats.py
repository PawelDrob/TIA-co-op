"""The bed of the two formats (twoformats.py) on real pairs from the two-format benchmark run: a repo of three commits,
each holding .s7dcl under plc/ and SimaticML of the same objects under simaticml/, as that run's repo does.

1-start: zzBenTimers, zzE2eUdtA, zzE2eFbI and its instance DB zzE2eFbI_DB as the run exported them.
2-B058: the run's row B058, pin PV of a CTU reads another operand (zzBenTimers, both formats).
3-D009: the run's row D009, a member of zzE2eFbI_DB made retain (TIA moved the .s7dcl only)."""
import os
import shutil
import subprocess
import tempfile
import unittest

from TiaChangeReports import twoformats

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
            (TIMERS, None): ['pin case', 'pin order'],
            (TIMERS, (1, 1, '14 Counter with fed pins')): ['pin case', 'pin order'],
            (TIMERS, (5, 5, '14a Counter at the end of an open branch')): ['pin case'],
            (FB, None): ['ENO'],
            (FB, (1, 1, '')): ['ENO'],
            (IDB, None): ['DB retain', 'instance DB access', 'instance DB start values'],
            (UDT, None): ['declaration'],
        }, got)

    def test_the_same_change_differs_where_pins_are_read_otherwise(self):
        got = twoformats.same_change(self.repo, 'HEAD~2', 'HEAD~1')
        self.assertEqual([(TIMERS, ['pin case', 'pin order'])], [(x['object'], x['causes']) for x in got])
        self.assertTrue(got[0]['sd'] and got[0]['xml'], 'the facts each report alone holds')

    def test_a_field_one_format_moved_alone(self):
        got = twoformats.same_change(self.repo, 'HEAD~1', 'HEAD')
        self.assertEqual([(IDB, ['DB retain'])], [(x['object'], x['causes']) for x in got])
        self.assertEqual([], got[0]['xml'], 'the SimaticML report holds nothing of it')

    def test_counts_name_every_cause_and_its_kind(self):
        result = twoformats.run(self.repo, None, None, ('nothing', 'same'))
        text = '\n'.join(twoformats.counts(result))
        self.assertIn('Nothing changed: 3 commits', text)
        self.assertIn('The same change: 2 commits, 2 whose two reports differ', text)
        self.assertRegex(text, r'DB retain\s+a field only one format writes')
        self.assertNotIn('unknown', text)


class ElementCauses(unittest.TestCase):
    """What makes two readings of one element unequal, from the CTU of zzBenTimers as each reader reads it."""

    SD = ('CTU', '#instCtu', '', (('r', ':=', 'wire#'), ('pv', ':=', '#inSpeed'), ('cv', '=>', '#statStep')),
          (('value_type', 'Int'),), '')
    XML = ('CTU', '#instCtu', '', (('PV', ':=', '#inSpeed'), ('CV', '=>', '#statStep'), ('R', ':=', 'wire#')),
           (('value_type', 'Int'),), '')

    def test_the_fewest_steps_each_needed(self):
        self.assertEqual({'pin case', 'pin order'}, twoformats.element_causes(self.SD, self.XML))

    def test_another_operand_is_no_reading(self):
        other = self.XML[:3] + ((('PV', ':=', '#inLevel'), ('CV', '=>', '#statStep'), ('R', ':=', 'wire#')),) + self.XML[4:]
        self.assertEqual({'unknown: element CTU'}, twoformats.element_causes(self.SD, other))

    def test_quoted_member_names(self):
        x = ('Contact', '', '', (('', '', '"zzInvBenF"."a"'),), (), '')
        y = ('Contact', '', '', (('', '', '"zzInvBenF".a'),), (), '')
        self.assertEqual({'quoted names'}, twoformats.element_causes(x, y))


if __name__ == '__main__':
    unittest.main()
