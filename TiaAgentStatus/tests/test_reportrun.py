"""A report run of the TIA dashboard on made-up project repos (real git), against a stand-in for the bridge it starts: what
it commits, what it refuses, what its record says, and that it puts the repo back when the export fails."""
import json
import os
import subprocess
import sys
import time
import unittest

from TiaAgentStatus import reportrun
from TiaAgentStatus import state as st
from TiaAgentStatus.tests.fakes import FakeProcesses, state, tempdir, write

PROJECT = r'C:\P\zzLine\zzLine.ap20'
RUNNER, BRIDGE, TIA = 5000, 5001, 7000


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def make_repo(root, name='zzLine', path=PROJECT):
    """A project repo as connect leaves one: tiabridge.json with the project's path, a block, one commit."""
    repo = os.path.join(root, name)
    os.makedirs(os.path.join(repo, 'plc', 'blocks'))
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Someone')
    git(repo, 'config', 'user.email', 'someone@example.com')
    with open(os.path.join(repo, 'tiabridge.json'), 'w') as f:
        json.dump({'projectPath': path}, f)
    put(repo, 'plc/blocks/Main.s7dcl', 'old')
    with open(os.path.join(repo, '.gitignore'), 'w') as f:
        f.write('changes/reports/\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'first')
    return repo


def put(repo, rel, text):
    path = os.path.join(repo, *rel.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


class FakeBridge:
    """The bridge in its report-run mode as the run talks to it: the tools' results, and what they do to the repo."""

    def __init__(self, repo, export=None, processes=None, connect=None, report=None):
        self.repo, self.pid, self.calls, self.closed = repo, BRIDGE, [], False
        self.export = export if export is not None else (lambda: put(repo, 'plc/blocks/Main.s7dcl', 'new') or {'ok': True})
        self.processes = processes if processes is not None else [{'processId': TIA, 'path': PROJECT, 'mode': 'WithUserInterface'}]
        self.connect = connect or {'ok': True, 'unsavedChanges': False}
        self.report = report

    def call(self, name, args):
        self.calls.append((name, args))
        put(self.repo, f'logs/2026110{len(self.calls)}_120000_{name}.json', '{}')     # the log of every call, as the bridge writes it
        if name == 'tia_status':
            return {'ok': True, 'processes': self.processes}
        if name == 'connect':     # connect writes tiabridge.json anew, its time of this connect with it (Initialize-ProjectRepo)
            with open(os.path.join(self.repo, 'tiabridge.json'), 'w') as f:
                json.dump({'projectPath': PROJECT, 'lastConnect': f'2026-11-06T12:00:0{len(self.calls)}'}, f)
            return self.connect() if callable(self.connect) else self.connect
        if name == 'full_export':
            return self.export()
        if name == 'change_report':
            if self.report:
                return self.report
            put(self.repo, f'changes/reports/2026-11-06_{args["rev2"]}.html', 'page')
            return {'ok': True, 'page': f'changes\\reports\\2026-11-06_{args["rev2"]}.html'}
        raise AssertionError(name)

    def close(self):
        self.closed = True


class Run(unittest.TestCase):
    def setUp(self):
        self.root = tempdir(self)
        self.repo = make_repo(self.root)
        self.procs = FakeProcesses().add(RUNNER, 1, 'python.exe').add(BRIDGE, RUNNER, 'powershell.exe').add(TIA, 1, 'Siemens.Automation.Portal.exe')
        self.bridge = None

    def run_it(self, **bridge):
        self.bridge = FakeBridge(self.repo, **bridge)
        reportrun.run(self.repo, self.root, lambda: self.bridge, self.procs, pid=RUNNER)
        return reportrun.read_record(self.root, 'zzLine')

    def head(self):
        return git(self.repo, 'log', '-1', '--format=%h %s')

    def test_commits_the_export_and_reports_that_commit(self):
        r = self.run_it()
        sha, subject = self.head().split(' ', 1)
        self.assertEqual(subject, 'TIA dashboard: zzLine as TIA holds it')
        self.assertEqual(r['outcome'], 'done')
        self.assertEqual(r['commit'], sha)
        self.assertEqual(r['page'], f'2026-11-06_{sha}.html')
        self.assertIn(f'Committed {sha}', r['text'])
        self.assertTrue(r['ended'])
        self.assertEqual([c[0] for c in self.bridge.calls], ['tia_status', 'connect', 'full_export', 'change_report'])
        self.assertEqual(self.bridge.calls[1][1], {'project': PROJECT, 'repo': 'zzLine'})
        self.assertEqual(self.bridge.calls[3][1], {'rev2': sha, 'title': 'TIA dashboard: zzLine as TIA holds it'})
        self.assertTrue(self.bridge.closed)
        self.assertEqual(git(self.repo, 'show', '--format=', '--name-only', 'HEAD').split('\n'),
                         ['logs/20261101_120000_tia_status.json', 'logs/20261102_120000_connect.json',
                          'logs/20261103_120000_full_export.json', 'plc/blocks/Main.s7dcl'])
        self.assertEqual(git(self.repo, 'show', 'HEAD:plc/blocks/Main.s7dcl'), 'new')

    def test_an_export_that_did_not_hold_every_object_commits_nothing_and_puts_the_repo_back(self):
        def export():
            put(self.repo, 'plc/blocks/Main.s7dcl', 'new')
            put(self.repo, 'plc/blocks/Added.s7dcl', 'added')
            os.remove(os.path.join(self.repo, '.gitignore'))
            return {'ok': False, 'failed': ['blocks@PLC_1: Pumps/Pump_1: Siemens.Engineering.EngineeringTargetInvocationException: '
                                            'Inconsistent blocks and PLC data types (UDT) cannot be exported.']}
        before = self.head()
        r = self.run_it(export=export)
        self.assertEqual(r['outcome'], 'failed')
        self.assertEqual(r['text'], 'Failed at full_export: 1 object did not export: blocks@PLC_1: Pumps/Pump_1: '
                                    'Siemens.Engineering.EngineeringTargetInvocationException: Inconsistent blocks and PLC data '
                                    'types (UDT) cannot be exported. Nothing was committed; the repo is as it was.')
        self.assertEqual(self.head(), before)
        self.assertEqual(reportrun.uncommitted(self.repo), [])
        self.assertTrue(os.path.exists(os.path.join(self.repo, 'logs', '20261103_120000_full_export.json')))
        self.assertNotIn('change_report', [c[0] for c in self.bridge.calls])

    def test_an_export_that_stopped_with_tia_names_tias_words(self):
        r = self.run_it(export=lambda: {'ok': False, 'stopped': 'The export stopped at part blocks, and no folder was mirrored.',
                                        'tiaEnded': True})
        self.assertEqual(r['text'], 'Failed at full_export: The export stopped at part blocks, and no folder was mirrored. '
                                    'Nothing was committed; the repo is as it was.')

    def test_with_nothing_changed_in_tia_commits_nothing_and_makes_no_report(self):
        before = self.head()
        r = self.run_it(export=lambda: {'ok': True})
        self.assertEqual((r['outcome'], r['text']), ('same', 'TIA holds what the last commit holds: nothing to report.'))
        self.assertEqual(self.head(), before)
        self.assertNotIn('change_report', [c[0] for c in self.bridge.calls])

    def test_says_when_tia_had_unsaved_edits_in_the_commit_the_report_and_the_line(self):
        r = self.run_it(connect={'ok': True, 'unsavedChanges': True})
        self.assertEqual(self.head().split(' ', 1)[1], 'TIA dashboard: zzLine as TIA holds it, unsaved edits included')
        self.assertEqual(self.bridge.calls[3][1]['title'], 'TIA dashboard: zzLine as TIA holds it, unsaved edits included')
        self.assertTrue(r['unsaved'])
        self.assertIn('unsaved edits included', r['text'])

    def test_commits_only_the_export_not_what_connect_writes_of_its_own(self):
        self.run_it()
        self.assertNotIn('tiabridge.json', git(self.repo, 'show', '--format=', '--name-only', 'HEAD'))
        self.assertEqual(reportrun.uncommitted(self.repo), [])

    def test_a_bridge_that_ends_during_the_export_leaves_the_repo_as_it_was(self):
        def export():
            put(self.repo, 'plc/blocks/Main.s7dcl', 'half')
            put(self.repo, 'plc/blocks/Half.s7dcl', 'half')
            raise RuntimeError('the bridge ended (exit 1)')
        before = self.head()
        r = self.run_it(export=export)
        self.assertEqual((r['outcome'], r['text']), ('failed', 'Failed at full_export: the bridge ended (exit 1). '
                                                                'Nothing was committed; the repo is as it was.'))
        self.assertEqual(self.head(), before)
        self.assertEqual(reportrun.uncommitted(self.repo), [])

    def test_refuses_a_repo_with_files_not_committed_before_it_starts_the_bridge_and_names_them(self):
        put(self.repo, 'plc/blocks/Main.s7dcl', 'edited')
        put(self.repo, 'docs/notes.md', 'mine')
        put(self.repo, 'logs/20261105_090000_compile.json', '{}')     # an agent's last log goes with the next commit
        r = self.run_it()
        self.assertEqual(r['outcome'], 'refused')
        self.assertEqual(r['text'], 'Not run: the repo has files not committed: docs/notes.md, plc/blocks/Main.s7dcl. '
                                    'Commit or remove them first: the report would hold them.')
        self.assertEqual(self.bridge.calls, [])

    def test_refuses_a_tia_or_repo_a_bridge_is_connected_to_before_connect(self):
        for s in (state(4100, 4000, tia=TIA), state(4100, 4000, repo=self.repo)):
            with self.subTest(s=s):
                self.procs.add(4100, 4000, 'powershell.exe')
                write(st.sessions_dir(self.root), s)
                r = self.run_it()
                self.assertEqual((r['outcome'], r['text']), ('refused', 'Not now: a bridge is connected to this TIA.'))
                self.assertNotIn('connect', [c[0] for c in self.bridge.calls])
                os.remove(os.path.join(st.sessions_dir(self.root), '4100.json'))

    def test_its_own_bridge_does_not_count(self):
        self.procs.add(BRIDGE, RUNNER, 'powershell.exe')
        write(st.sessions_dir(self.root), state(BRIDGE, RUNNER, tia=TIA, client='report-run'))
        self.assertEqual(self.run_it()['outcome'], 'done')

    def test_refuses_a_project_not_open_in_tia_or_open_without_a_window(self):
        r = self.run_it(processes=[{'processId': TIA, 'path': r'C:\P\zzOther\zzOther.ap20', 'mode': 'WithUserInterface'}])
        self.assertEqual(r['text'], f'Not now: {PROJECT} is not open in TIA. Open it in TIA, then press again.')
        r = self.run_it(processes=[{'processId': TIA, 'path': PROJECT, 'mode': 'WithoutUserInterface'}])
        self.assertEqual(r['outcome'], 'refused')
        self.assertIn('without a window', r['text'])
        self.assertNotIn('connect', [c[0] for c in self.bridge.calls])

    def test_a_connect_that_fails_after_it_wrote_to_the_repo_leaves_the_repo_as_it_was(self):
        def connect():      # Initialize-ProjectRepo wrote tiabridge.json (the fake's own) and a doc it makes when missing
            put(self.repo, 'docs/project.md', 'made by connect')
            return {'ok': False, 'error': {'type': 'EngineeringTargetInvocationException', 'message': 'TIA refused the attach.'}}
        before = self.head()
        r = self.run_it(connect=connect)
        self.assertEqual((r['outcome'], r['text']), ('failed', 'Failed at connect: EngineeringTargetInvocationException: '
                                                                'TIA refused the attach. Nothing was committed; the repo is as it was.'))
        self.assertEqual(self.head(), before)
        self.assertEqual(reportrun.uncommitted(self.repo), [])
        self.assertEqual(self.run_it()['outcome'], 'done')      # the next press is not refused over what the run wrote

    def test_a_refusal_of_connect_is_a_refusal_in_its_own_words(self):
        r = self.run_it(connect={'ok': False, 'refused': 'Not now: a program is connected to this TIA: C:\\x.exe (process 9). Two programs on one TIA have hung it.'})
        self.assertEqual(r['outcome'], 'refused')
        self.assertTrue(r['text'].startswith('Not now: a program is connected to this TIA'))

    def test_refuses_a_run_of_the_same_repo_another_dashboard_started_at_the_same_moment(self):
        # another dashboard's run of this repo, its own process, held between its checks and its record
        other = subprocess.Popen([sys.executable, '-c', 'import sys; from TiaAgentStatus import reportrun; '
                                  f'h = reportrun.hold({self.root!r}, "zzLine"); print("held" if h else "not held", flush=True); sys.stdin.read()'],
                                 cwd=reportrun.TOOLS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(other.wait, 30)
        self.assertEqual(other.stdout.readline().strip(), 'held')
        self.bridge = FakeBridge(self.repo)
        r = reportrun.run(self.repo, self.root, lambda: self.bridge, self.procs, pid=RUNNER)
        self.assertEqual((r['outcome'], r['text']), ('refused', 'Not now: a report run of zzLine is going on.'))
        self.assertIsNone(reportrun.read_record(self.root, 'zzLine'))     # none written over the other's
        self.assertEqual(self.bridge.calls, [])
        other.stdin.close()
        other.wait(30)
        other.stdout.close()
        self.assertEqual(self.run_it()['outcome'], 'done')      # a run's process gone, its hold goes with it

    def test_refuses_while_another_run_runs_and_leaves_its_record(self):
        other = make_repo(self.root, 'zzOther', r'C:\P\zzOther\zzOther.ap20')
        self.procs.add(6000, 1, 'python.exe')
        os.makedirs(reportrun.runs_dir(self.root), exist_ok=True)
        reportrun.Record(self.root, 'zzOther', pid=6000, project='zzOther', repo=other)
        self.bridge = FakeBridge(self.repo)
        r = reportrun.run(self.repo, self.root, lambda: self.bridge, self.procs, pid=RUNNER)
        self.assertEqual((r['outcome'], r['text']), ('refused', 'Not now: a report run of zzOther is going on.'))
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(reportrun.read_record(self.root, 'zzOther')['pid'], 6000)

    def test_a_record_counts_as_running_while_its_process_runs_and_it_has_not_ended(self):
        rec = reportrun.Record(self.root, 'zzLine', pid=RUNNER)
        self.assertTrue(reportrun.is_running(rec.data, self.procs))
        self.assertFalse(reportrun.is_running(dict(rec.data, ended='2026-11-06T12:00:00+01:00'), self.procs))
        self.procs.kill(RUNNER)
        self.assertFalse(reportrun.is_running(rec.data, self.procs))

    def test_a_run_whose_process_is_gone_runs_on_while_its_bridge_does(self):
        """A killed run leaves its bridge in the export it is in: that bridge is still on the TIA."""
        rec = reportrun.Record(self.root, 'zzLine', pid=RUNNER)
        self.procs.kill(RUNNER)
        self.procs.add(BRIDGE, RUNNER, 'powershell.exe', created=reportrun.st.parse_time(rec.data['started']))
        rec.write(bridge=BRIDGE)
        self.assertTrue(reportrun.is_running(rec.data, self.procs))
        self.procs.kill(BRIDGE)
        self.assertFalse(reportrun.is_running(rec.data, self.procs))


class TheCommand(unittest.TestCase):
    def test_the_dashboard_starts_a_run_that_outlives_it_and_writes_its_record(self):
        from TiaAgentStatus import dashboard
        root = tempdir(self)
        repo = make_repo(root, path='')         # a repo no connect made: the run ends at its first check, with no bridge
        dashboard.spawn_run(root)(repo)
        for _ in range(300):
            r = reportrun.read_record(root, 'zzLine')
            if r and r.get('ended'):
                break
            time.sleep(0.1)
        else:
            self.fail('no record of an ended run')
        self.assertEqual(r['outcome'], 'refused')
        self.assertEqual(r['text'], 'Not run: zzLine records no TIA project. The button works on a project an agent has connected to.')


class RealBridge(unittest.TestCase):
    """TiaBridge.ps1 -ReportRun (stand-ins for its tools, no TIA) as the run starts and calls it."""

    def test_the_run_talks_to_the_bridge_in_its_report_run_mode(self):
        root = tempdir(self)
        repo = make_repo(root)
        tools = os.path.join(root, 'tools.ps1')
        with open(tools, 'w', encoding='utf-8') as f:
            f.write(STAND_INS)
        r = reportrun.run(repo, root, lambda: reportrun.McpBridge(root, 'zzLine', ('-NoTools', '-ToolScript', tools)), FakeProcesses())
        self.assertEqual(r['outcome'], 'failed')
        # import is no tool of a report run: the bridge refuses it before its handler would write the file
        self.assertEqual(r['text'], 'Failed at full_export: import is refused in a report run of the TIA dashboard: it runs '
                                    'tia_status, connect, full_export, change_report only. Nothing was committed; the repo is as it was.')
        self.assertFalse(os.path.exists(os.path.join(root, 'imported')))
        self.assertTrue(os.path.exists(os.path.join(reportrun.runs_dir(root), 'zzLine.log')))


# Stand-ins for the bridge's tools: tia_status names the project open, connect binds it, and full_export calls import
# through the bridge's own dispatch, which a report run refuses.
STAND_INS = r"""
Register-McpTool -Name 'tia_status' -Description 'x' -Schema @{ type = 'object' } -Handler {
    param($a) @{ ok = $true; processes = @(@{ processId = 7000; path = 'C:\P\zzLine\zzLine.ap20'; mode = 'WithUserInterface' }) } }
Register-McpTool -Name 'connect' -Description 'x' -Schema @{ type = 'object' } -Handler {
    param($a) @{ ok = ($script:Bridge.reportRun -eq $true) } }
Register-McpTool -Name 'import' -Description 'x' -Schema @{ type = 'object' } -Handler {
    param($a) Set-Content (Join-Path $script:Bridge.settings.projectsRoot 'imported') 'x'; @{ ok = $true } }
Register-McpTool -Name 'full_export' -Description 'x' -Schema @{ type = 'object' } -Handler {
    param($a) (Invoke-BridgeTool 'import' $script:McpTools['import'].handler $a).result }
"""


class GitsOwnList(unittest.TestCase):
    """GIT_CONTEXT holds every name git reads a repo from: a git that knows one more fails this."""

    def test_every_name_of_git_is_dropped(self):
        names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn('GIT_DIR', names)
        self.assertEqual([name for name in names if name not in reportrun.GIT_CONTEXT], [])


if __name__ == '__main__':
    unittest.main()
