"""python -m unittest discover -s TiaAgentStatus/tests -t .   (from the repo root)"""
import datetime
import os
import unittest

from TiaAgentStatus import state as st
from TiaAgentStatus.tests.fakes import NOW, FakeProcesses, iso, state, tempdir, write
from TiaAgentStatus.watch import Watcher

MIN = datetime.timedelta(minutes=1)


class FakeHerdr:
    def __init__(self):
        self.labels = {'w1:t1': 'Lead', 'w1:t3': '01 TIA status'}
        self.panes = {'w1:p1': 'w1:t1', 'w1:p3': 'w1:t3'}
        self.pids = {'w1:p1': [100], 'w1:p3': [110]}
        self.notes = []
        self.renames = []
        self.pane_reads = 0

    def tabs(self):
        return dict(self.labels)

    def pane_tabs(self):
        self.pane_reads += 1
        return dict(self.panes)

    def pane_pids(self, pane):
        return self.pids[pane]

    def rename(self, tab, label):
        self.renames.append((tab, label))
        self.labels[tab] = label

    def notify(self, title, body, sound='none'):
        self.notes.append((title, body, sound))


class Watch(unittest.TestCase):
    def setUp(self):
        self.root = tempdir(self)
        self.dir = st.sessions_dir(self.root)
        os.makedirs(self.dir)
        self.t = NOW
        self.p = (FakeProcesses().add(100, 1, 'claude.exe').add(110, 1, 'claude.exe')
                  .add(200, 100, 'powershell.exe').add(210, 110, 'powershell.exe'))
        self.h = FakeHerdr()
        self.w = Watcher(self.p, self.h, self.root, quiet_minutes=5, now=lambda: self.t)

    def bodies(self):
        return [b for _, b, _ in self.h.notes]

    def put(self, **kw):
        return write(self.dir, state(200, 100, **kw))

    def test_tab_label_follows_the_state_and_is_restored(self):
        self.put()
        self.w.round()
        self.assertEqual(self.h.labels['w1:t1'], 'Lead')
        self.p.add(5150, 1)
        self.put(tia=5150, window=False, operation={'name': 'export', 'since': iso(NOW), 'part': 'blocks', 'n': 3, 'of': 9})
        self.w.round()
        self.assertEqual(self.h.labels['w1:t1'], 'Lead · TIA export blocks 3/9')
        self.put(tia=5150, window=False)
        self.w.round()
        self.assertEqual(self.h.labels['w1:t1'], 'Lead · TIA idle')
        self.w.round()
        self.assertEqual(len(self.h.renames), 2)   # unchanged label: no rename
        self.p.kill(200)
        self.w.round()
        self.assertEqual(self.h.labels['w1:t1'], 'Lead')

    def test_tab_from_the_state_file_and_a_label_renamed_meanwhile(self):
        self.put(tia=4711, herdr={'tab': 'w1:t3', 'pane': 'w1:p3'})
        self.p.add(4711, 1)
        self.w.round()
        self.assertEqual(self.h.labels['w1:t3'], '01 TIA status · TIA idle')
        self.h.labels['w1:t3'] = 'renamed · TIA idle'
        self.put(tia=4711, herdr={'tab': 'w1:t3'}, operation={'name': 'list', 'since': iso(NOW)})
        self.w.round()
        self.assertEqual(self.h.labels['w1:t3'], 'renamed · TIA list')

    def test_background_tia_start_and_end(self):
        self.put()
        self.w.round()
        self.p.add(5150, 1)
        self.put(tia=5150, window=False, operation={'name': 'background_open', 'since': iso(NOW), 'step': 'open'})
        self.w.round()
        self.assertEqual(self.bodies(), ['TIA without window started (pid 5150)'])
        self.put(tia=5150, window=False)
        self.w.round()
        self.assertEqual(len(self.h.notes), 1)
        self.put()
        self.w.round()
        self.assertEqual(self.bodies()[-1], 'TIA without window ended (pid 5150)')

    def test_window_tia_is_not_announced_and_its_bridge_end_is_quiet(self):
        self.put()
        self.w.round()
        self.p.add(4711, 1)
        self.put(tia=4711)
        self.w.round()
        os.remove(os.path.join(self.dir, '200.json'))
        self.p.kill(200)
        self.w.round()
        self.assertEqual(self.h.notes, [])

    def test_bridge_ending_with_its_background_tia(self):
        self.p.add(5150, 1)
        self.put(tia=5150, window=False)
        self.w.round()
        self.assertEqual(self.h.notes, [])   # already running when the watcher started
        os.remove(os.path.join(self.dir, '200.json'))
        self.p.kill(200)
        self.p.kill(5150)
        self.w.round()
        self.assertEqual(self.h.notes, [('TIA zzPlant', 'bridge 200 ended, TIA 5150 without window ended', 'done')])

    def test_bridge_dying_while_its_background_tia_still_runs(self):
        self.p.add(5150, 1)
        self.put(tia=5150, window=False)
        self.w.round()
        self.p.kill(200)   # killed: the state file stays
        self.w.round()
        self.w.round()
        self.assertEqual(self.h.notes, [('TIA zzPlant', 'bridge 200 ended without cleanup, TIA 5150 without window'
                                                        ' still running', 'request')])

    def test_bridge_dying_with_its_background_tia_and_a_reused_tia_pid(self):
        self.p.add(5150, 1)
        self.put(tia=5150, window=False)
        self.w.round()
        self.p.kill(200)
        self.p.add(5150, 1, created=NOW)   # the TIA ended, another process got its pid
        self.w.round()
        self.assertEqual(self.bodies(), ['bridge 200 ended without cleanup, TIA 5150 without window ended'])

    def test_orphan_reported_once(self):
        self.w.round()
        write(self.dir, state(299, 100))
        self.w.round()
        self.w.round()
        self.assertEqual(self.bodies(), ['bridge 299 ended without cleanup'])

    def test_one_bridge_per_tab_the_newest(self):
        self.p.add(201, 100, 'powershell.exe').add(4711, 1).add(5150, 1)
        write(self.dir, state(200, 100, tia=4711, started=NOW - 60 * MIN))
        write(self.dir, state(201, 100, tia=5150, window=False, started=NOW - MIN,
                              operation={'name': 'export', 'since': iso(NOW), 'part': 'blocks', 'n': 3, 'of': 9}))
        for _ in range(3):
            self.w.round()
        self.assertEqual(self.h.renames, [('w1:t1', 'Lead · TIA export blocks 3/9')])
        os.remove(os.path.join(self.dir, '201.json'))
        self.p.kill(201)
        self.w.round()
        self.assertEqual(self.h.renames[1:], [('w1:t1', 'Lead · TIA idle')])   # the older bridge, not no suffix

    def test_panes_read_once_a_round_for_a_claude_in_no_pane(self):
        self.p.add(120, 1, 'claude.exe').add(220, 120, 'powershell.exe').add(230, 120, 'powershell.exe')
        write(self.dir, state(220, 120))
        write(self.dir, state(230, 120))
        self.w.round()
        self.w.round()
        self.assertEqual(self.h.pane_reads, 2)

    def test_tia_gone_while_the_bridge_runs(self):
        self.put(tia=5150, window=False)
        self.p.add(5150, 1)
        self.w.round()
        self.p.kill(5150)
        self.w.round()
        self.w.round()
        self.assertEqual(self.bodies(), ['TIA process 5150 is gone while the bridge runs'])

    def test_prompt_notified_once(self):
        self.p.add(5150, 1)
        self.put(tia=5150, window=False)
        self.w.round()
        asked = {'at': iso(NOW), 'kind': 'confirmation', 'caption': 'Import', 'text': 'Overwrite?', 'answer': 'No'}
        self.put(tia=5150, window=False, lastPrompt=asked)
        self.w.round()
        self.w.round()
        self.assertEqual(self.bodies(), ['TIA asked (confirmation): Import: Overwrite? -> No'])
        self.assertEqual(self.h.notes[0][2], 'request')

    def test_old_prompt_at_watcher_start_is_not_notified(self):
        self.p.add(5150, 1)
        self.put(tia=5150, window=False, lastPrompt={'at': iso(NOW - MIN), 'kind': 'notification', 'text': 'x'})
        self.w.round()
        self.assertEqual(self.h.notes, [])

    def test_no_cpu_for_the_quiet_minutes_during_a_call(self):
        op = {'name': 'export', 'since': iso(NOW), 'part': 'blocks', 'n': 3, 'of': 9}
        self.p.add(5150, 1, cpu=100.0)
        self.put(tia=5150, window=False, operation=op)
        self.w.round()
        for minute, cpu in ((2, 160.0), (4, 160.5), (6, 161.0)):
            self.t = NOW + minute * MIN
            self.p.procs[5150]['cpu'] = cpu
            self.w.round()
        self.assertEqual(self.h.notes, [])   # working until minute 2, then less than 2 s of CPU for 4 minutes
        self.t = NOW + 8 * MIN
        self.p.procs[5150]['cpu'] = 161.5
        self.w.round()
        self.assertEqual(self.bodies(), ['TIA used no CPU for 6 min during export blocks 3/9 (pid 5150): look for a message box'])
        self.t = NOW + 12 * MIN
        self.w.round()
        self.assertEqual(len(self.h.notes), 1)   # once per quiet spell
        self.p.procs[5150]['cpu'] = 200.0
        self.w.round()
        self.t = NOW + 18 * MIN
        self.w.round()
        self.assertEqual(len(self.h.notes), 2)   # it worked again, then went quiet again

    def test_idle_tia_without_cpu_is_fine(self):
        self.p.add(5150, 1, cpu=10.0)
        self.put(tia=5150, window=False)
        for minute in range(0, 30, 5):
            self.t = NOW + minute * MIN
            self.w.round()
        self.assertEqual(self.h.notes, [])

    def test_a_new_call_starts_a_new_quiet_spell(self):
        self.p.add(5150, 1, cpu=10.0)
        self.put(tia=5150, window=False, operation={'name': 'list', 'since': iso(NOW)})
        self.w.round()
        self.t = NOW + 4 * MIN
        self.put(tia=5150, window=False, operation={'name': 'export', 'since': iso(self.t)})
        self.w.round()
        self.t = NOW + 6 * MIN
        self.w.round()
        self.assertEqual(self.h.notes, [])

    def test_herdr_failures_do_not_stop_a_round(self):
        class Broken(FakeHerdr):
            def tabs(self):
                raise RuntimeError('no server')

            def notify(self, *a):
                raise RuntimeError('no server')

        w = Watcher(self.p, Broken(), self.root, now=lambda: self.t)
        self.put()
        w.round()
        self.p.add(5150, 1)
        self.put(tia=5150, window=False)
        w.round()


if __name__ == '__main__':
    unittest.main()
