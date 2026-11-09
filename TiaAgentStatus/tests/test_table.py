"""python -m unittest discover -s TiaAgentStatus/tests -t .   (from the repo root)"""
import argparse
import datetime
import io
import os
import unittest

from TiaAgentStatus import state as st
from TiaAgentStatus import table, watch
from TiaAgentStatus.tests.fakes import NOW, FakeProcesses, iso, state, tempdir, write
from TiaAgentStatus.tests.test_watch import FakeHerdr

MIN = datetime.timedelta(minutes=1)
SEC = datetime.timedelta(seconds=1)
GB = 2**30


class Pane(unittest.TestCase):
    """The watcher's rows rendered: claude 100 in tab Lead, claude 110 in tab "01 TIA status", claude 120 in no
    herdr pane."""

    def setUp(self):
        self.root = tempdir(self)
        self.dir = st.sessions_dir(self.root)
        os.makedirs(self.dir)
        self.t = NOW
        self.p = (FakeProcesses().add(100, 1, 'claude.exe').add(110, 1, 'claude.exe').add(120, 1, 'claude.exe')
                  .add(200, 100, 'powershell.exe').add(210, 110, 'powershell.exe').add(220, 120, 'powershell.exe'))
        self.h = FakeHerdr()
        self.w = Watcher(self)

    def lines(self, width=120, height=None, plain=True):
        return table.render(self.w.view, width, height, plain)

    def rows(self, width=120):
        """The table rows as lists of cells (split at two spaces)."""
        return [[c.strip() for c in x.split('  ') if c.strip()] for x in self.lines(width)[3:] if x and
                not x.startswith('Last notifications')][:len(self.w.view['rows'])]

    def round(self, seconds=0):
        self.t += seconds * SEC
        self.w.round()

    def test_background_call_with_step_time_memory_and_cpu_per_minute(self):
        self.p.add(5150, 1, cpu=100.0, memory=int(3.1 * GB))
        write(self.dir, state(200, 100, project='zzPlant copy', tia=5150, window=False,
                              operation={'name': 'export', 'since': iso(NOW - 2 * MIN), 'part': 'blocks', 'n': 31,
                                         'of': 115}))
        self.round()
        self.assertEqual(self.rows(), [['Lead', 'zzPlant copy', 'no', 'export blocks 31/115', '2:00', '3.1GB']])
        for _ in range(3):
            self.p.procs[5150]['cpu'] += 4.5   # nine-tenths of one core
            self.round(5)
        self.assertEqual(self.rows(), [['Lead', 'zzPlant copy', 'no', 'export blocks 31/115', '2:15', '3.1GB',
                                        '90%']])
        head = self.lines()[1:3]
        self.assertEqual(head[0].split(), ['Agent', 'Project', 'Win', 'Call', 'Time', 'Mem', 'CPU%'])
        self.assertTrue(set(head[1]) <= {'-', ' '})

    def test_cpu_percent_of_one_core_over_the_last_minute_only(self):
        self.p.add(5150, 1, cpu=0.0, memory=GB)
        write(self.dir, state(200, 100, tia=5150, window=False, operation={'name': 'compile', 'since': iso(NOW)}))
        self.round()
        for _ in range(12):
            self.p.procs[5150]['cpu'] += 5.0
            self.round(5)
        self.assertEqual(self.rows()[0][-1], '100%')
        for _ in range(12):   # a quiet minute: the working one is out of the window
            self.round(5)
        self.assertEqual(self.rows()[0][-1], '0%')

    def test_idle_window_tia_with_its_last_prompt(self):
        self.p.add(4711, 1, memory=900 * 2**20)
        asked = {'at': iso(NOW - MIN), 'kind': 'confirmation', 'caption': 'Import', 'text': 'Overwrite?',
                 'answer': 'No'}
        write(self.dir, state(210, 110, project='zzLine', tia=4711, lastPrompt=asked))
        self.round()
        at = (NOW - MIN).astimezone().strftime('%H:%M')
        self.assertEqual(self.rows(), [['01 TIA status', 'zzLine', 'yes', 'idle', '900MB',
                                        f'{at} Import: Overwrite? -> No']])
        self.assertIn('Last prompt', self.lines()[1])

    def test_bridge_without_tia_and_claude_in_no_pane(self):
        write(self.dir, state(220, 120, project=None))
        self.round()
        self.assertEqual(self.rows(), [['-', '-', '-', 'idle']])

    def test_tia_gone_while_the_bridge_runs(self):
        write(self.dir, state(200, 100, tia=5150, window=False))
        self.round()
        self.assertEqual(self.rows(), [['Lead', 'zzPlant', 'no', 'idle', 'gone']])

    def test_tab_label_without_the_watchers_suffix(self):
        self.p.add(4711, 1)
        write(self.dir, state(200, 100, tia=4711))
        self.round()
        self.assertEqual(self.h.labels['w1:t1'], 'Lead · TIA idle')
        self.round()
        self.assertEqual(self.rows()[0][0], 'Lead')

    def test_orphan_left_by_a_killed_bridge_while_its_tia_runs(self):
        self.p.add(6000, 1, memory=int(2.4 * GB))
        write(self.dir, state(220, 120, project='zzOld', tia=6000, window=False))
        self.round()
        self.p.kill(220)
        self.round(5)
        self.assertEqual(self.rows(), [['-', 'zzOld', 'no', 'orphan (bridge 220 gone)', '2.4GB', '0%']])
        self.assertEqual(self.lines()[0][8:], '  0 bridges, 1 orphaned TIA')
        self.p.kill(6000)
        self.round(5)
        self.assertEqual(self.w.view['rows'], [])

    def test_orphan_stays_when_the_next_bridge_deletes_the_file_left_behind(self):
        self.p.add(6000, 1, memory=int(2.4 * GB))
        write(self.dir, state(220, 120, project='zzOld', tia=6000, window=False))
        self.round()
        self.p.kill(220)
        self.round(5)
        os.remove(os.path.join(self.dir, '220.json'))   # TiaBridge State.ps1: a starting bridge removes orphan files
        write(self.dir, state(200, 100))
        self.round(5)
        self.assertEqual(self.rows(), [['Lead', 'zzPlant', '-', 'idle'],
                                       ['-', 'zzOld', 'no', 'orphan (bridge 220 gone)', '2.4GB', '0%']])
        self.p.kill(6000)
        self.round(5)
        self.assertEqual(len(self.w.view['rows']), 1)

    def test_orphan_of_a_bridge_that_ended_cleanly_leaving_its_tia(self):
        self.p.add(6000, 1, memory=GB)
        write(self.dir, state(200, 100, tia=6000, window=False))
        self.round()
        os.remove(os.path.join(self.dir, '200.json'))
        self.p.kill(200)
        self.round(5)
        self.assertEqual(self.rows(), [['Lead', 'zzPlant', 'no', 'orphan (bridge 200 gone)', '1.0GB', '0%']])
        self.p.add(6000, 1, created=self.t)   # the TIA ended, another process got its pid
        self.round(5)
        self.assertEqual(self.w.view['rows'], [])

    def test_no_orphan_row_for_a_reused_tia_pid_or_a_bridge_without_tia(self):
        write(self.dir, state(230, 120, tia=6000, updated=iso(NOW - 10 * MIN)))
        write(self.dir, state(231, 120))
        self.p.add(6000, 1, created=NOW - 5 * MIN)   # started after the dead bridge's last write
        self.round()
        self.assertEqual(self.w.view['rows'], [])

    def test_empty_state_names_the_folder(self):
        self.round()
        lines = self.lines()
        self.assertEqual(lines[0], f'{table.local(NOW)}  0 bridges')
        self.assertTrue(lines[1].startswith('Agent  Project  Win  Call'))
        self.assertTrue(set(lines[2]) <= {'-', ' '})
        self.assertEqual(self.lines(width=1000)[3], f'no TIA bridge running; watching {self.dir}')

    def test_an_empty_last_prompt_is_no_prompt(self):
        self.p.add(4711, 1)
        empty = {'at': iso(NOW - MIN), 'kind': None, 'caption': None, 'text': None, 'answer': None}
        write(self.dir, state(210, 110, project='zzLine', tia=4711, lastPrompt=empty))
        self.round()
        self.assertNotIn('Last prompt', self.lines()[1])
        self.assertFalse(any('asked' in line for line in self.lines()))

    def test_last_ten_notifications_below_the_table_repeats_counted(self):
        write(self.dir, state(200, 100))
        self.round()
        for i in range(12):
            self.w.log(f'note {i}')
        self.w.log('note 11')
        lines = self.lines()
        at = lines.index('Last notifications')
        self.assertEqual(lines[at - 1], '')
        self.assertEqual(lines[at + 1:], [f'{table.local(NOW)}  note {i}' for i in range(2, 11)]
                         + [f'{table.local(NOW)}  note 11 (x2)'])

    def test_notifications_give_way_to_the_height(self):
        write(self.dir, state(200, 100))
        self.round()
        for i in range(10):
            self.w.log(f'note {i}')
        lines = self.lines(height=10)
        self.assertEqual(len(lines), 9)
        self.assertTrue(lines[-1].endswith('note 9'))
        self.assertEqual(len(self.lines(height=5)), 4)   # the table only

    def test_rows_cut_at_the_height_never_scroll(self):
        for i in range(8):
            self.p.add(300 + i, 100, 'powershell.exe')
            write(self.dir, state(300 + i, 100, started=NOW - (10 - i) * MIN))
        self.round()
        self.w.log('note')
        lines = self.lines(height=8)
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[0][8:], '  8 bridges')
        self.assertEqual(lines[-1], '+5 more')
        self.assertEqual(lines[3:6], [self.lines()[i] for i in (3, 4, 5)])
        self.assertEqual(self.lines(height=4), self.lines()[:3])   # header, rule and nothing else fit
        self.assertEqual(self.lines(height=5)[-1], '+8 more')

    def test_narrow_panes_cut_fields_and_leave_columns_out(self):
        self.p.add(5150, 1, memory=int(3.1 * GB)).add(4711, 1, memory=GB)
        write(self.dir, state(200, 100, project='zzPlant copy', tia=5150, window=False,
                              operation={'name': 'export', 'since': iso(NOW), 'part': 'blocks', 'n': 31, 'of': 115}))
        write(self.dir, state(210, 110, project='zzLine', tia=4711,
                              lastPrompt={'at': iso(NOW), 'kind': 'notification', 'text': 'Compile finished ' * 4}))
        self.round()
        self.w.log('TIA zzPlant copy: TIA without window started (pid 5150), a long notification text')
        for width in (120, 70, 50, 30):
            for x in self.lines(width):
                self.assertLessEqual(len(x), width - 1, (width, x))
        self.assertIn('Last prompt', self.lines(120)[1])
        self.assertEqual(self.lines(70)[1].split(), ['Agent', 'Project', 'Win', 'Call', 'Time', 'Mem', 'CPU%'])
        self.assertEqual(self.rows(70)[0][:4], ['Lead', 'zzPlant co~', 'no', 'export blocks 31/115'])
        self.assertEqual(self.lines(50)[1].split(), ['Agent', 'Win', 'Call', 'Time', 'Mem', 'CPU%'])
        self.assertEqual(self.rows(50)[1][:2], ['01 TIA~', 'yes'])
        self.assertTrue(self.lines(50)[-1].endswith('~'))

    def test_plain_is_ascii_the_console_marks_cuts_and_orphans(self):
        self.p.add(6000, 1, memory=GB)
        write(self.dir, state(220, 120, project='zzAnlage für Öl und Wasser', tia=6000, window=False))
        self.round()
        self.p.kill(220)
        self.round(5)
        plain = self.lines(40)
        self.assertTrue(all(x.isascii() for x in plain))
        console = self.lines(40, plain=False)
        self.assertIn('…', console[3])
        self.assertTrue(console[3].startswith('\x1b[33m'))   # the orphan row
        self.assertTrue(console[1].startswith('\x1b[1m'))    # the header

    def test_watch_once_prints_one_plain_table(self):
        self.p.add(5150, 1, memory=GB)
        write(self.dir, state(200, 100, tia=5150, window=False))
        out = io.StringIO()
        a = argparse.Namespace(root=self.root, every=5.0, quiet_minutes=5.0, once=True)
        self.assertEqual(watch.main(a, out, self.p, self.h), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0][8:], '  1 bridge')
        self.assertEqual(lines[1].split()[:2], ['Agent', 'Project'])
        self.assertEqual(lines[3].split()[:4], ['Lead', 'zzPlant', 'no', 'idle'])
        self.assertNotIn('\x1b', out.getvalue())

    def test_screen_redraws_in_place(self):
        out = io.StringIO()
        s = table.Screen(out)
        s.draw(['a', 'b'])
        s.close()
        self.assertEqual(out.getvalue(), '\x1b[?25l\x1b[2J' + '\x1b[Ha\x1b[K\nb\x1b[K\x1b[J' + '\x1b[?25h\n')


def Watcher(test):
    return watch.Watcher(test.p, test.h, test.root, quiet_minutes=5, now=lambda: test.t)


if __name__ == '__main__':
    unittest.main()
