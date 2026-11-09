"""python -m unittest discover -s TiaAgentStatus/tests -t .   (from the repo root)"""
import datetime
import json
import os
import subprocess
import sys
import time
import unittest

from TiaAgentStatus import state as st
from TiaAgentStatus import statusline
from TiaAgentStatus.procs import WinProcesses
from TiaAgentStatus.tests.fakes import NOW, FakeProcesses, iso, state, tempdir, write

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN = datetime.timedelta(minutes=1)


def tree():
    """herdr -> shell -> claude 100 -> bash -> python 300 (the status line); claude 100 -> bridge 200;
    another claude 110 -> bridge 210."""
    return (FakeProcesses().add(1, 0, 'herdr.exe').add(2, 1, 'powershell.exe').add(100, 2, 'claude.exe')
            .add(101, 100, 'bash.exe').add(300, 101, 'python.exe').add(200, 100, 'powershell.exe')
            .add(110, 2, 'claude.exe').add(210, 110, 'powershell.exe'))


class Row(unittest.TestCase):
    def test_background_export_with_n_of_m_elapsed_and_memory(self):
        p = tree().add(5150, 1, 'Siemens.Automation.Portal.exe', memory=int(3.1 * 2**30))
        s = state(200, 100, project='zzPlant copy', tia=5150, window=False,
                  operation={'name': 'export', 'since': iso(NOW - 2 * MIN - datetime.timedelta(seconds=10)),
                             'part': 'blocks', 'n': 31, 'of': 115})
        self.assertEqual(statusline.row(s, p, NOW),
                         'TIA: zzPlant copy \u00b7 no window \u00b7 export blocks 31/115 \u00b7 2:10 \u00b7 3.1 GB')

    def test_idle_window_session(self):
        p = tree().add(4711, 1, 'Siemens.Automation.Portal.exe', memory=900 * 2**20)
        self.assertEqual(statusline.row(state(200, 100, tia=4711), p, NOW), 'TIA: zzPlant \u00b7 idle \u00b7 900 MB')

    def test_step_of_a_background_open_and_hours(self):
        p = tree().add(5150, 1, memory=2**30)
        s = state(200, 100, tia=5150, window=False,
                  operation={'name': 'background_open', 'since': iso(NOW - 65 * MIN), 'step': 'retrieve'})
        self.assertEqual(statusline.row(s, p, NOW),
                         'TIA: zzPlant \u00b7 no window \u00b7 background_open retrieve \u00b7 1:05:00 \u00b7 1.0 GB')

    def test_call_before_any_tia(self):
        s = state(200, 100, project=None, operation={'name': 'tia_status', 'since': iso(NOW - MIN)})
        self.assertEqual(statusline.row(s, tree(), NOW), 'TIA: (no project) \u00b7 tia_status \u00b7 1:00')

    def test_tia_gone(self):
        self.assertEqual(statusline.row(state(200, 100, tia=9999), tree(), NOW), 'TIA: zzPlant \u00b7 idle \u00b7 TIA gone')

    def test_nothing_without_tia_and_call(self):
        self.assertEqual(statusline.row(state(200, 100), tree(), NOW), '')
        self.assertEqual(statusline.row(None, tree(), NOW), '')

    def test_prompt_of_the_running_call_only(self):
        p = tree().add(5150, 1, memory=2**30)
        op = {'name': 'import', 'since': iso(NOW - MIN)}
        asked = {'at': iso(NOW - datetime.timedelta(seconds=20)), 'kind': 'confirmation', 'caption': 'Overwrite object',
                 'text': 'Replace it?', 'answer': 'No'}
        self.assertTrue(statusline.row(state(200, 100, tia=5150, operation=op, lastPrompt=asked), p, NOW)
                        .endswith('\u00b7 asked: Overwrite object'))
        older = dict(asked, at=iso(NOW - 5 * MIN))
        self.assertNotIn('asked', statusline.row(state(200, 100, tia=5150, operation=op, lastPrompt=older), p, NOW))
        self.assertNotIn('asked', statusline.row(state(200, 100, tia=5150, lastPrompt=asked), p, NOW))

    def test_short_label(self):
        op = {'name': 'export', 'since': iso(NOW), 'part': 'blocks', 'n': 3, 'of': 9}
        self.assertEqual(statusline.short(state(200, 100, tia=1, operation=op)), 'TIA export blocks 3/9')
        self.assertEqual(statusline.short(state(200, 100, tia=1)), 'TIA idle')
        self.assertEqual(statusline.short(state(200, 100)), '')


class FindBridge(unittest.TestCase):
    def setUp(self):
        self.dir = tempdir(self)

    def test_the_bridge_of_its_own_claude_process(self):
        p = tree().add(5150, 1, memory=2**30).add(6000, 1, memory=2**30)
        root = tempdir(self)
        write(st.sessions_dir(root), state(200, 100, project='Mine', tia=5150))
        write(st.sessions_dir(root), state(210, 110, project='Other', tia=6000))
        self.assertTrue(statusline.main(p, 300, root, env={}).startswith('TIA: Mine'))

    def test_the_folder_of_the_bridge_settings_in_any_case_of_the_name(self):
        p = tree().add(5150, 1, memory=2**30)
        root = tempdir(self)
        settings = os.path.join(self.dir, 'settings.json')
        with open(settings, 'w') as f:
            json.dump({'PROJECTSROOT': root}, f)
        write(st.sessions_dir(root), state(200, 100, project='Mine', tia=5150))
        self.assertTrue(statusline.main(p, 300, env={}, settings=settings).startswith('TIA: Mine'))

    def test_settings_it_cannot_read_are_said(self):
        """The bridge reads more than JSON: its folder is then not the default one, and the row would show nothing."""
        settings = os.path.join(self.dir, 'settings.json')
        with open(settings, 'w') as f:
            f.write("{'projectsRoot': 'D:/Projects'}")
        row = statusline.main(tree(), 300, env={}, settings=settings)
        self.assertTrue(row.startswith(f'TIA: {settings} is not strict JSON'), row)
        self.assertNotIn('\n', row)

    def test_settings_it_cannot_read_do_not_matter_with_a_root(self):
        p = tree().add(5150, 1, memory=2**30)
        root = tempdir(self)
        settings = os.path.join(self.dir, 'settings.json')
        with open(settings, 'w') as f:
            f.write('{ not json')
        write(st.sessions_dir(root), state(200, 100, project='Mine', tia=5150))
        self.assertTrue(statusline.main(p, 300, root, env={}, settings=settings).startswith('TIA: Mine'))

    def test_claude_pid_from_env_first_then_ancestors(self):
        self.assertEqual(st.claude_pid(tree(), 300, env={'CLAUDE_PID': '110'}), 110)
        self.assertEqual(st.claude_pid(tree(), 300, env={}), 100)
        self.assertIsNone(st.claude_pid(tree(), 2, env={}))

    def test_skips_orphans_dead_or_reused_pid(self):
        p = tree()
        write(self.dir, state(200, 100))
        self.assertEqual(len(st.live_states(self.dir, p)), 1)
        p.add(200, 100, created=NOW)   # started after the file: a reused pid
        write(self.dir, state(200, 100, started=NOW - 30 * MIN))
        self.assertEqual(st.live_states(self.dir, p), [])
        p.kill(200)
        self.assertEqual(st.live_states(self.dir, p), [])

    def test_skips_unreadable_and_foreign_files(self):
        write(self.dir, state(200, 100))
        with open(os.path.join(self.dir, '201.json'), 'w') as f:
            f.write('{"pid": 2')
        with open(os.path.join(self.dir, '200.json.tmp'), 'w') as f:
            f.write('{}')
        with open(os.path.join(self.dir, '202.json'), 'w') as f:
            json.dump({'pid': 999}, f)
        self.assertEqual([s['pid'] for _, s in st.read_states(self.dir)], [200])

    def test_newest_bridge_wins(self):
        a = state(200, 100, project='Old', started=NOW - 60 * MIN)
        b = state(201, 100, project='New', started=NOW - MIN)
        self.assertEqual(st.bridge_of([a, b], 100)['project'], 'New')
        self.assertIsNone(st.bridge_of([a, b], 110))


class Windows(unittest.TestCase):
    """The real process table (no TIA, no bridge)."""

    def test_own_process(self):
        w = WinProcesses()
        t = w.tree()
        self.assertIn(os.getpid(), t)
        self.assertEqual(t[os.getpid()][0], os.getppid())
        i = w.info(os.getpid())
        self.assertGreater(i['memory'], 0)
        self.assertLess(i['created'], datetime.datetime.now(datetime.timezone.utc))
        self.assertIsNone(w.info(0))

    def test_dead_process(self):
        c = subprocess.Popen([sys.executable, '-c', ''])
        c.wait()
        self.assertIsNone(WinProcesses().info(c.pid))


class CommandLine(unittest.TestCase):
    def run_statusline(self, root, env_more):
        env = dict(os.environ, **env_more)
        r = subprocess.run([sys.executable, os.path.join(REPO, 'TiaAgentStatus'), 'statusline', '--root', root],
                           input='{"session_id": "x", "cwd": "C:\\\\"}', capture_output=True, text=True,
                           encoding='utf-8', env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_nothing_without_bridges(self):
        self.assertEqual(self.run_statusline(tempdir(self), {'CLAUDE_PID': '4242'}), '')

    def test_row_of_a_live_bridge(self):
        # this test process stands in for the bridge and its TIA
        root = tempdir(self)
        started = datetime.datetime.now(datetime.timezone.utc) + MIN
        write(st.sessions_dir(root), state(os.getpid(), 4242, project='zzPlant', tia=os.getpid(), window=False,
                                           started=started))
        out = self.run_statusline(root, {'CLAUDE_PID': '4242'})
        self.assertRegex(out, r'^TIA: zzPlant \u00b7 no window \u00b7 idle \u00b7 \d+ MB$')


class RealBridge(unittest.TestCase):
    """TiaBridge.ps1 (no tools, no TIA) writes the file this package reads."""

    def test_live_bridge_found_by_its_claude_process(self):
        root = tempdir(self)
        settings = os.path.join(root, 'settings.json')
        with open(settings, 'w') as f:
            json.dump({'projectsRoot': root}, f)
        ps = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        env = dict(os.environ, CLAUDE_PID='4242')
        b = subprocess.Popen([ps, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
                              os.path.join(REPO, 'TiaBridge', 'TiaBridge.ps1'), '-NoTools', '-SettingsPath', settings],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            path = os.path.join(st.sessions_dir(root), f'{b.pid}.json')
            deadline = datetime.datetime.now() + datetime.timedelta(seconds=30)
            while not os.path.exists(path) and datetime.datetime.now() < deadline:
                b.poll()
                self.assertIsNone(b.returncode, 'bridge ended')
                time.sleep(0.1)
            states = st.live_states(st.sessions_dir(root), WinProcesses())
            self.assertEqual([s['pid'] for s in states], [b.pid])
            self.assertEqual(st.bridge_of(states, 4242)['pid'], b.pid)
            self.assertIsNotNone(st.parse_time(states[0]['started']))
        finally:
            b.stdin.close()
            b.wait(30)
        self.assertFalse(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
