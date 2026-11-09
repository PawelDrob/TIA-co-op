"""Tests of the archive compare runner (unittest, no TIA). From the repo root:
python -m unittest discover -s TiaArchiveCompare/runner/tests -t .

The runs use the fake exporter (speed 0) or the TiaBridge client against tests\\fake_bridge.py, a stand-in MCP
server. The exports are TiaChangeReports' made-up test plant (v1, v2), so the report step runs for real.
"""
import contextlib
import io
import json
import msvcrt
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from TiaArchiveCompare.runner import __main__ as cli
from TiaArchiveCompare.runner import cache, checks, errors, inputs, run as run_module
from TiaArchiveCompare.runner.bridge import BridgeExporter, parse_progress
from TiaArchiveCompare.runner.events import Commands, Events
from TiaArchiveCompare.runner.exporter import HMI_PARTS, PARTS, ExportFailed, Hooks, NeedsLogin
from TiaArchiveCompare.runner.fake import HMI_SAMPLES, PLANT, FakeExporter
from TiaArchiveCompare.runner.run import Options, Run, make_junction, pid_alive, remove_tree

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), 'samples')
FAKE_BRIDGE = os.path.join(HERE, 'fake_bridge.py')
PC_OK = {'tia': 'V20.00.00.07', 'problems': [], 'warnings': [], 'facts': ['TIA Portal V20.00.00.07']}


@contextlib.contextmanager
def holding(path):
    """Keeps the file's bytes from other readers, as a program that has it open and locked does."""
    with open(path, 'r+b') as f:
        size = os.path.getsize(path)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, size)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, size)


def rewrite_keeping_time(path, data):
    st = os.stat(path)
    with open(path, 'wb') as f:
        f.write(data)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return st


def pc_ok(_root):
    return dict(PC_OK)


def bridge_reads(folder, cases, setting):
    """Writes each case, bytes, to folder as NN.json, and returns what Get-BridgeSettings (TiaBridge\\Repo.ps1,
    dot-sourced: no bridge, no TIA) makes of the setting in each, by file name: '<refused>' where it stops."""
    os.makedirs(folder)
    for i, raw in enumerate(cases):
        with open(os.path.join(folder, '%02d.json' % i), 'wb') as f:
            f.write(raw)
    repo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), 'TiaBridge', 'Repo.ps1')
    script = ("$ErrorActionPreference = 'Stop'; . '%s'; [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
              "foreach ($f in Get-ChildItem -LiteralPath '%s' -Filter *.json) { "
              "try { $v = (Get-BridgeSettings $f.FullName).%s } catch { $v = '<refused>' }; "
              "[Console]::Out.WriteLine($f.Name + [char]9 + $v) }" % (repo, folder, setting))
    out = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                         capture_output=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = dict(x.split('\t', 1) for x in out.stdout.decode('utf-8-sig').splitlines())
    if len(lines) != len(cases):
        raise AssertionError('Get-BridgeSettings read %d of %d cases: %s' % (len(lines), len(cases), out.stderr))
    return lines


class Tmp(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='tac-')     # it deletes git's read-only files, rmtree does not
        self.addCleanup(folder.cleanup)
        self.tmp = folder.name

    def archive(self, name, cfg):
        p = os.path.join(self.tmp, 'in', name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        return p


class Cleanup(unittest.TestCase):
    def test_a_folder_with_read_only_files_goes_with_the_test(self):
        class Using(Tmp):
            def runTest(self):
                path = os.path.join(self.tmp, 'object')     # read-only, as git's object files are
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('made up')
                os.chmod(path, stat.S_IREAD)

        case = Using()
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual(result.errors, [])
        self.assertFalse(os.path.exists(case.tmp))

    def test_a_folder_that_cannot_go_fails_the_test(self):
        class Holding(Tmp):
            def runTest(self):
                self.held = open(os.path.join(self.tmp, 'held'), 'w', encoding='utf-8')

        case = Holding()
        result = unittest.TestResult()
        case.run(result)
        case.held.close()
        self.addCleanup(shutil.rmtree, case.tmp)
        self.assertIn('held', ''.join(text for _, text in result.errors))


class Recorder:
    """Collects the events; `on` reacts to one (the window's part: cancel, answer)."""

    def __init__(self):
        self.events = []
        self.on = None
        self.out = io.StringIO()

    def __call__(self, ev):
        self.events.append(ev)
        if self.on:
            self.on(ev)

    def of(self, t):
        return [e for e in self.events if e['t'] == t]

    def states(self):
        last = {}
        for e in self.of('step'):
            last[e['id']] = e['state']
        return last

    def end(self):
        return self.of('end')[-1]


class RunCase(Tmp):
    def run_compare(self, before, after, make=None, check=pc_ok, on=None, **kw):
        rec = Recorder()
        rec.on = on
        events = Events(rec.out, sink=rec)
        commands = Commands()
        self.commands = commands
        opts = Options(before, after, out_root=os.path.join(self.tmp, 'out'),
                       data_root=os.path.join(self.tmp, 'data'), **kw)
        self.exporters = []

        def factory(work):
            ex = make(work) if make else FakeExporter(speed=0, process=False)
            if work:
                self.exporters.append(ex)
            return ex
        self.runner = Run(opts, events, commands, factory, check_pc=check)
        self.code = self.runner.execute()
        return rec

    def bridge(self, work, **cfg):
        cfg.setdefault('export', os.path.join(PLANT, 'v1'))
        path = os.path.join(self.tmp, 'bridge-%d.json' % len(os.listdir(self.tmp)))
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        return BridgeExporter(work, [sys.executable, FAKE_BRIDGE, path, os.path.join(work, 'settings.json')])

    def files_text(self, rec):
        d = rec.end()['folder']
        # without the questions: the fake's hint names the sample password, which the answer then repeats
        text = '\n'.join(x for x in rec.out.getvalue().splitlines() if '"t": "ask"' not in x)
        for n in ('log.txt', 'run.json'):
            with open(os.path.join(d, n), encoding='utf-8') as f:
                text += f.read()
        return text


# ---------------------------------------------------------------------------- inputs, cache, events, errors

class InputsTest(Tmp):
    def test_kinds(self):
        a = self.archive('P.zap20', {})
        s = inputs.classify(a)
        self.assertEqual((s.kind, s.version, s.upgrade, s.name), ('archive', 20, False, 'P'))
        s = inputs.classify(self.archive('Old.zap19', {}))
        self.assertEqual((s.kind, s.upgrade), ('archive', True))
        proj = os.path.join(self.tmp, 'proj')
        os.makedirs(proj)
        open(os.path.join(proj, 'Line.ap20'), 'w').close()
        for given in (proj, os.path.join(proj, 'Line.ap20')):
            s = inputs.classify(given)
            self.assertEqual((s.kind, s.path, s.name), ('project', os.path.join(proj, 'Line.ap20'),
                                                        'proj' if given == proj else 'Line'))
        s = inputs.classify(os.path.join(PLANT, 'v1'))
        self.assertEqual(s.kind, 'exports')

    def test_problems(self):
        self.assertIn('was not found', inputs.classify(os.path.join(self.tmp, 'none.zap20')).problem)
        self.assertIn('V21', inputs.classify(self.archive('New.zap21', {})).problem)
        self.assertIn('not a TIA Portal archive', inputs.classify(self.archive('x.txt', {})).problem)
        empty = os.path.join(self.tmp, 'empty')
        os.makedirs(empty)
        self.assertIn('neither a TIA project nor block exports', inputs.classify(empty).problem)

    def test_safe_name(self):
        self.assertEqual(inputs.safe_name('a:b/c?. '), 'a_b_c_')
        self.assertEqual(len(inputs.safe_name('x' * 100, 40)), 40)

    def test_safe_pair_keeps_what_tells_them_apart(self):
        a = 'tool-plant-conveyor-line-seven-2026-10-19_161610'
        b = 'tool-plant-conveyor-line-seven-2026-10-22_125955'
        sa, sb = inputs.safe_pair(a, b, 40)
        self.assertEqual((sa, sb), ('tool-plant-conveyor-li~2026-10-19_161610',
                                    'tool-plant-conveyor-li~2026-10-22_125955'))
        self.assertEqual(inputs.safe_pair('Plant_A', 'Plant_B', 40), ('Plant_A', 'Plant_B'))     # short: as they are
        # different early: cut from the end
        self.assertEqual(inputs.safe_pair('A-' + 'x' * 60, 'B-' + 'x' * 60, 20), ('A-' + 'x' * 18, 'B-' + 'x' * 18))
        # the difference itself long: start, cut mark, the difference's start
        sa, sb = inputs.safe_pair('p' * 50 + '-old-' + 'y' * 40, 'p' * 50 + '-new-' + 'y' * 40, 40)
        self.assertEqual((len(sa), sa[10:15], sb[10:15]), (40, '~old-', '~new-'))
        sa, sb = inputs.safe_pair('Plant:' + 'x' * 50 + '1', 'Plant:' + 'x' * 50 + '2', 30)
        self.assertNotEqual(sa, sb)
        self.assertNotIn(':', sa)


class CacheTest(Tmp):
    def test_key_changes_with_each_part(self):
        base = ('d', 'V20.00.00.07', 'fake-1', ('blocks',), 'none')
        k = cache.make_key(*base)
        for i, other in enumerate(('e', 'V20.00.00.08', 'fake-2', ('blocks', 'dbs'), 'plc')):
            changed = list(base)
            changed[i] = other
            self.assertNotEqual(cache.make_key(*changed), k)

    def test_store_lookup_prune(self):
        c = cache.Cache(os.path.join(self.tmp, 'exports'), keep=2)
        self.assertIsNone(c.lookup('k0'))
        for i in range(4):
            built = os.path.join(self.tmp, 'work', 'b%d' % i)
            os.makedirs(os.path.join(built, 'export'))
            e = c.store(built, 'k%d' % i, {'n': i})
            self.assertFalse(os.path.exists(built))                 # moved, not copied
            self.assertEqual(e.meta['n'], i)
            t = time.time() - 100 + i
            os.utime(os.path.join(e.folder, 'meta.json'), (t, t))
        c.lookup('k0')                                              # used now: kept
        self.assertEqual(sorted(c.prune(keep_keys={'k1'})), ['k2'])
        self.assertEqual(sorted(os.listdir(c.root)), ['k0', 'k1', 'k3'])

    def test_store_replaces(self):
        c = cache.Cache(os.path.join(self.tmp, 'exports'))
        for n in (1, 2):
            built = os.path.join(self.tmp, 'b%d' % n)
            os.makedirs(os.path.join(built, 'export'))
            c.store(built, 'k', {'n': n})
        self.assertEqual(c.lookup('k').meta['n'], 2)
        self.assertEqual(os.listdir(c.root), ['k'])

    def test_file_digest_hashes_the_bytes(self):
        a = os.path.join(self.tmp, 'P.zap20')
        with open(a, 'wb') as f:
            f.write(b'abc')
        seen = []
        d = cache.file_digest(a, lambda done, total: seen.append(done), chunk=1)
        self.assertEqual(d, 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')    # FIPS 180-2
        self.assertTrue(seen)

    def project(self, files):
        folder = os.path.join(self.tmp, 'P')
        for name, data in files.items():
            p = os.path.join(folder, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(data)
        return folder

    def test_folder_digest_sees_a_same_size_change_with_its_time_kept(self):
        folder = self.project({'P.ap20': b'x', 'System\\PEData.plf': b'AAAA'})
        before = cache.folder_digest(folder)
        store = os.path.join(folder, 'System', 'PEData.plf')
        st = rewrite_keeping_time(store, b'BBBB')
        self.assertEqual((os.path.getsize(store), os.stat(store).st_mtime_ns), (4, st.st_mtime_ns))
        self.assertNotEqual(cache.folder_digest(folder), before)

    def test_folder_digest_is_the_contents_not_the_times(self):
        folder = self.project({'P.ap20': b'x', 'System\\PEData.plf': b'AAAA'})
        before = cache.folder_digest(folder)
        os.utime(os.path.join(folder, 'P.ap20'), (1, 1))
        self.assertEqual(cache.folder_digest(folder), before)
        os.rename(os.path.join(folder, 'P.ap20'), os.path.join(folder, 'Q.ap20'))
        self.assertNotEqual(cache.folder_digest(folder), before)

    def test_folder_digest_tells_apart_where_the_bytes_stand(self):
        one = self.project({'a': b'xy', 'b': b''})
        first = cache.folder_digest(one)
        shutil.rmtree(one)
        self.assertNotEqual(cache.folder_digest(self.project({'a': b'x', 'b': b'y'})), first)

    def test_folder_digest_progress_runs_over_the_whole_folder(self):
        folder = self.project({'a': b'x' * (3 << 20), 'b': b'y' * (2 << 20)})
        seen = []
        cache.folder_digest(folder, lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (5, 5))

    def test_folder_digest_refuses_a_folder_it_cannot_read(self):
        with self.assertRaises(FileNotFoundError):
            cache.folder_digest(os.path.join(self.tmp, 'gone'))

    def test_folder_digest_refuses_a_file_it_cannot_read(self):
        folder = self.project({'P.ap20': b'x', 'locked': b'AAAA'})
        with holding(os.path.join(folder, 'locked')):
            with self.assertRaises(OSError):
                cache.folder_digest(folder)


class CommandsTest(unittest.TestCase):
    def test_cancel_answer_eof(self):
        c = Commands()
        c.feed('{"t":"answer","id":"other","password":"x"}')
        c.feed('{"t":"answer","id":"A-1","password":"pw"}')
        self.assertEqual(c.wait_answer('A-1', lambda: False)['password'], 'pw')
        c.read_from(io.BytesIO(b'\xef\xbb\xbf{"t":"cancel"}\n'))
        c.eof.wait(2)
        self.assertTrue(c.cancel.is_set())
        self.assertIsNone(c.wait_answer('A-2', lambda: False))      # stdin ended: no answer

    def test_no_ask_answers_nothing_at_once_with_stdin_open(self):
        self.assertIsNone(Commands(no_ask=True).wait_answer('A-1', lambda: False))

    def test_bad_command_is_not_echoed(self):
        err = io.StringIO()
        old, sys.stderr = sys.stderr, err
        try:
            Commands().feed('{"t":"answer","password":"secret-xyz"')
        finally:
            sys.stderr = old
        self.assertNotIn('secret-xyz', err.getvalue())

    def test_broken_stdout(self):
        class Broken(io.StringIO):
            def write(self, s):
                raise OSError('pipe closed')
        ev = Events(Broken())
        ev.log('info', 'x')
        self.assertTrue(ev.broken)


class ErrorsTest(unittest.TestCase):
    def test_plain(self):
        cases = {'MissingProductsException': 'lacks software', 'LicenseNotFoundException': 'licence',
                 'is open in TIA (process 1) and locked there': 'open in TIA Portal',
                 'The project is protected.': 'UMC', 'not a member of Siemens TIA Openness': 'Openness',
                 "The entered path 'C:\\w\\x.xml' (270 characters) for the system file is too long.": 'too long for Windows',
                 "Retrieve failed\r\nThe specified path' C:\\w\\p' (159 character) is too long. A maximum of 143 characters is allowed.": 'allows 143 characters',
                 "Unable to retrieve the project. Retrieve failed: Could not access the path 'C:\\w'.": 'damaged',
                 'whatever': 'the log has its text'}
        for text, words in cases.items():
            self.assertIn(words, errors.plain({'type': 'X', 'message': text}), text)
        self.assertIn('ended unexpectedly', errors.plain({'type': 'X', 'message': 'y', 'tiaDisconnected': True}))
        self.assertTrue(errors.is_protected({'message': 'm', 'inner': [{'type': 'T', 'message': 'UMC login'}]}))

    def test_siemens_text_keeps_the_chain(self):
        s = errors.siemens({'type': 'A', 'message': 'm', 'details': ['d1'], 'inner': [{'type': 'B', 'message': 'n'}]})
        self.assertEqual(s, 'A: m | detail: d1 | inner B: n')

    def test_why_not_exported(self):
        self.assertIn('not compiled', errors.why_not_exported(
            'Inconsistent blocks and PLC data types (UDT) cannot be exported.'))
        self.assertIn('know-how', errors.why_not_exported(
            {'message': 'The block is know-how-protected and cannot be exported.'}))
        self.assertIn('F-system', errors.why_not_exported({'message': "The export of block 'FOB_1' is not permitted."}))
        self.assertIn('(odd)', errors.why_not_exported({'message': 'odd'}))


class JunctionTest(Tmp):
    def test_remove_tree_keeps_the_target(self):
        target = os.path.join(self.tmp, 'cache', 'k', 'export')
        os.makedirs(target)
        open(os.path.join(target, 'FB.s7dcl'), 'w').close()
        work = os.path.join(self.tmp, 'work')
        make_junction(target, os.path.join(work, 'compare', 'A name'))
        self.assertTrue(os.path.exists(os.path.join(work, 'compare', 'A name', 'FB.s7dcl')))
        remove_tree(work)
        self.assertFalse(os.path.exists(work))
        self.assertTrue(os.path.exists(os.path.join(target, 'FB.s7dcl')))


# ---------------------------------------------------------------------------- runs with the fake exporter

class FakeRunTest(RunCase):
    def setUp(self):
        super().setUp()
        self.a = self.archive('Plant_A.zap20', {'export': 'v1', 'fsystem': ['F_Sys'], 'protected': ['Secret'],
                                                'uncompiled': ['Calc', 'F_Guard'], 'safety': 'safe-1'})
        self.b = self.archive('Plant_B.zap20', {'export': 'v2', 'fsystem': ['F_Sys'], 'uncompiled': ['F_Guard'],
                                                'safety': 'safe-1', 'prompts': [{'phase': 'open', 'text': 'Update?',
                                                                                 'answer': 'No'}]})

    def test_full_run(self):
        rec = self.run_compare(self.a, self.b)
        self.assertEqual(self.code, 0)
        ev = rec.events
        self.assertEqual(ev[0]['t'], 'plan')
        self.assertEqual(ev[-1]['t'], 'end')
        ids = [s['id'] for s in ev[0]['steps']]
        self.assertEqual(ids, ['check', 'A.cache', 'A.start', 'A.open', 'A.export', 'A.close',
                               'B.cache', 'B.start', 'B.open', 'B.export', 'B.close', 'report'])
        self.assertEqual(set(rec.states().values()), {'done'})
        # every step: running once, then one final state, in plan order
        order = [e['id'] for e in rec.of('step') if e['state'] == 'running']
        self.assertEqual(order, ids)
        end = rec.end()
        self.assertTrue(end['ok'])
        self.assertTrue(os.path.isfile(end['report']))
        self.assertGreater(end['changed'], 0)
        nx = {x['name']: x['why'] for x in end['not_exported']}
        self.assertTrue(nx['F_Sys'].startswith('A and B: F-system'))
        self.assertTrue(nx['Calc'].startswith('A: not compiled'))
        self.assertTrue(nx['Secret'].startswith('A: know-how'))
        self.assertEqual(rec.of('prompt'), [{'t': 'prompt', 'text': 'Update?', 'answer': 'No'}])
        self.assertEqual({e['id'] for e in rec.of('progress')}, {'A.cache', 'A.export', 'B.cache', 'B.export'})
        # the report names the archives, not the cache folders
        with open(end['report'], encoding='utf-8') as f:
            page = f.read()
        self.assertIn('Plant_A', page)
        self.assertIn('Plant_B', page)
        with open(os.path.join(end['folder'], 'run.json'), encoding='utf-8') as f:
            run = json.load(f)
        self.assertEqual([i['cache'] for i in run['inputs']], ['stored', 'stored'])
        self.assertEqual(run['result'], {'ok': True})
        self.assertEqual(len(run['inputs'][0]['sha256']), 64)
        self.assertEqual(run['prompts'][0]['side'], 'B')
        self.assertTrue(os.path.basename(end['folder']).endswith(' Plant_A vs Plant_B'))
        self.assertEqual(os.listdir(os.path.join(self.tmp, 'data', 'work')), [])
        self.assertEqual(len(os.listdir(os.path.join(self.tmp, 'data', 'exports'))), 2)

    def test_cache_hit_second_run(self):
        self.run_compare(self.a, self.b)
        rec = self.run_compare(self.a, self.b)
        self.assertEqual(self.code, 0)
        st = rec.states()
        for x in ('start', 'open', 'export', 'close'):
            self.assertEqual((st['A.' + x], st['B.' + x]), ('skipped', 'skipped'))
        self.assertEqual(self.exporters, [])                       # no TIA at all
        self.assertTrue(any('using the export of Plant_A' in e['text'] for e in rec.of('log')))
        self.assertIn('last_ms', [e for e in rec.of('step') if e['id'] == 'report'][0])
        self.assertTrue(any(x['name'] == 'Calc' for x in rec.end()['not_exported']))   # kept with the entry
        rec = self.run_compare(self.a, self.b, no_cache=True)
        self.assertEqual(rec.states()['A.export'], 'done')

    def project_input(self):
        folder = os.path.join(self.tmp, 'in', 'Line')
        os.makedirs(os.path.join(folder, 'System'))
        with open(os.path.join(folder, 'Line.ap20'), 'w', encoding='utf-8') as f:
            json.dump({'export': 'v1'}, f)
        store = os.path.join(folder, 'System', 'PEData.plf')
        with open(store, 'wb') as f:
            f.write(b'AAAA')
        return folder, store

    def first_input(self, rec):
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            return json.load(f)['inputs'][0]

    def test_project_changed_with_size_and_time_kept_exports_again(self):
        folder, store = self.project_input()
        self.run_compare(folder, self.b)
        self.assertEqual(self.run_compare(folder, self.b).states()['A.export'], 'skipped')
        rewrite_keeping_time(store, b'BBBB')
        rec = self.run_compare(folder, self.b)
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.states()['A.export'], 'done')
        self.assertEqual(rec.states()['B.export'], 'skipped')            # the archive's entry stands

    def test_project_with_an_unreadable_file_does_not_use_the_cache(self):
        folder, store = self.project_input()
        self.run_compare(folder, self.b)
        exports = os.path.join(self.tmp, 'data', 'exports')
        entries = sorted(os.listdir(exports))
        with holding(store):
            rec = self.run_compare(folder, self.b)
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.states()['A.export'], 'done')                # not the entry of the run before
        self.assertTrue(any('PEData.plf' in e['text'] and 'could not be read' in e['text'] and e['level'] == 'warn'
                            for e in rec.of('log')))
        self.assertEqual(sorted(os.listdir(exports)), entries)            # nor a new one
        side = self.first_input(rec)
        self.assertEqual(side['cache'], 'not stored')
        self.assertNotIn('cacheKey', side)
        self.assertNotIn('contentSha256', side)

    def test_cancel_during_the_hashing_of_a_project(self):
        folder, _ = self.project_input()

        def on(ev):
            if ev['t'] == 'progress' and ev['id'] == 'A.cache':
                self.commands.cancel.set()
        rec = self.run_compare(folder, self.b, on=on)
        self.assertEqual(self.code, 1)
        self.assertEqual(rec.states()['A.cache'], 'cancelled')
        self.assertEqual(rec.end().get('cancelled'), True)
        self.assertEqual(self.exporters, [])                              # no TIA started
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'data', 'exports')))

    def test_cancel_during_export(self):
        def on(ev):
            if ev['t'] == 'progress' and ev['id'] == 'A.export':
                self.commands.cancel.set()
        rec = self.run_compare(self.a, self.b, on=on)
        self.assertEqual(self.code, 1)
        st = rec.states()
        self.assertEqual(st['A.export'], 'cancelled')
        self.assertEqual(st['A.close'], 'done')                      # TIA closed after a cancel too
        self.assertEqual({st[x] for x in ('B.cache', 'B.start', 'B.export', 'report')}, {'skipped'})
        self.assertEqual(self.exporters[0].calls, ['open', 'export', 'close'])
        end = rec.end()
        self.assertEqual((end['ok'], end.get('cancelled')), (False, True))
        self.assertNotIn('report', end)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'data', 'exports')))   # no half entry
        self.assertEqual(os.listdir(os.path.join(self.tmp, 'data', 'work')), [])

    def test_failure_in_plain_words(self):
        bad = self.archive('Broken.zap20', {'fail': {'open': 'missing_products'}})
        rec = self.run_compare(bad, self.b)
        self.assertEqual(self.code, 1)
        st = rec.states()
        self.assertEqual(st['A.open'], 'failed')
        self.assertEqual(st['A.close'], 'skipped')                   # TIA had ended with the failed open
        self.assertEqual(st['B.cache'], 'skipped')
        failed = [e for e in rec.of('step') if e['state'] == 'failed'][0]
        self.assertIn('lacks software', failed['error'])
        self.assertTrue(rec.end()['error'].startswith('A: unpack and open the archive: TIA Portal on this PC lacks'))
        self.assertTrue(any('MissingProductsException' in e['text'] for e in rec.of('log') if e['level'] == 'error'))

    def test_failed_check(self):
        rec = self.run_compare(os.path.join(self.tmp, 'missing.zap20'), self.b)
        self.assertEqual(rec.states()['check'], 'failed')
        self.assertIn('was not found', rec.end()['error'])

    def test_tia_problem_fails_at_start_but_not_with_the_cache(self):
        self.run_compare(self.a, self.b)
        no_tia = lambda _root: {'tia': 'V20.00.00.07', 'problems': ['TIA Portal V20 is not installed on this PC.'],
                                'warnings': [], 'facts': []}

        def needs_tia(work):
            ex = FakeExporter(speed=0, process=False)
            ex.needs_tia = True
            return ex
        rec = self.run_compare(self.a, self.b, make=needs_tia, check=no_tia)
        self.assertEqual(self.code, 0)                               # both from the cache
        c = self.archive('Plant_C.zap20', {'export': 'v2'})
        rec = self.run_compare(self.a, c, make=needs_tia, check=no_tia)
        self.assertEqual(rec.states()['B.start'], 'failed')
        self.assertIn('not installed', rec.end()['error'])

    def test_umc_login_wrong_then_right_and_never_logged(self):
        p = self.archive('Prot.zap20', {'export': 'v1', 'umc': {'user': 'eng', 'password': 'umc-secret-1'}})
        answers = iter([{'user': 'eng', 'password': 'wrong-pass-9'}, {'user': 'eng', 'password': 'umc-secret-1'}])

        def on(ev):
            if ev['t'] == 'ask':
                self.assertEqual((ev['kind'], ev['project']), ('umc_login', 'Prot'))
                self.commands.feed(json.dumps(dict(next(answers), t='answer', id=ev['id'])))
        rec = self.run_compare(p, self.b, on=on)
        self.assertEqual(self.code, 0)
        self.assertEqual(len(rec.of('ask')), 2)
        text = self.files_text(rec)
        for secret in ('umc-secret-1', 'wrong-pass-9'):
            self.assertNotIn(secret, text)
        self.assertIn('the project login was given', text)

    def test_umc_server_user(self):
        p = self.archive('Prot.zap20', {'export': 'v1', 'umc': {'user': 'srv', 'password': 'pw', 'global': True}})
        answers = iter([{'user': 'srv', 'password': 'pw'}, {'user': 'srv', 'password': 'pw', 'umc_global': True}])
        rec = self.run_compare(p, self.b, on=lambda ev: ev['t'] == 'ask' and self.commands.feed(
            json.dumps(dict(next(answers), t='answer', id=ev['id']))))
        self.assertEqual(self.code, 0)
        self.assertEqual(len(rec.of('ask')), 2)                 # without the box ticked, the login is refused
        self.assertEqual(rec.of('ask')[0]['hint'], 'Fake TIA: the sample login is srv / pw, with "UMC server user" ticked.')

    def test_umc_login_skipped(self):
        p = self.archive('Prot.zap20', {'export': 'v1', 'umc': 'pw'})
        rec = self.run_compare(p, self.b, on=lambda ev: ev['t'] == 'ask' and self.commands.feed(
            json.dumps({'t': 'answer', 'id': ev['id'], 'skip': True})))
        self.assertEqual(rec.states()['A.open'], 'failed')
        self.assertIn('no login was given', rec.end()['error'])

    def test_cancel_while_asking(self):
        p = self.archive('Prot.zap20', {'export': 'v1', 'umc': 'pw'})
        rec = self.run_compare(p, self.b, on=lambda ev: ev['t'] == 'ask' and self.commands.cancel.set())
        self.assertTrue(rec.end().get('cancelled'))
        self.assertEqual(rec.states()['A.open'], 'cancelled')

    def test_compile_with_safety(self):
        def on(ev):
            if ev['t'] == 'ask':
                self.assertEqual(ev['kind'], 'safety_password')
                self.assertEqual(ev['hint'], 'Fake TIA: the sample password is safe-1.')
                self.commands.feed(json.dumps({'t': 'answer', 'id': ev['id'], 'password': 'safe-1'}))
        rec = self.run_compare(self.a, self.b, on=on, compile=True, safety=True)
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.states()['A.compile'], 'done')
        names = [x['name'] for x in rec.end()['not_exported']]
        self.assertNotIn('Calc', names)
        self.assertNotIn('F_Guard', names)
        self.assertNotIn('safe-1', self.files_text(rec))
        # a second run takes the export made with the password from the cache: no question
        rec = self.run_compare(self.a, self.b, compile=True, safety=True)
        self.assertEqual((rec.states()['A.export'], rec.of('ask')), ('skipped', []))
        # skipped password: compiled without the safety program, the F-block stays out
        rec = self.run_compare(self.a, self.b, compile=True, safety=True, no_cache=True,
                               on=lambda ev: ev['t'] == 'ask' and self.commands.feed(
                                   json.dumps({'t': 'answer', 'id': ev['id'], 'skip': True})))
        self.assertEqual(rec.states()['A.export'], 'done')
        names = [x['name'] for x in rec.end()['not_exported']]
        self.assertIn('F_Guard', names)
        self.assertNotIn('Calc', names)

    def test_export_folder_input(self):
        rec = self.run_compare(self.a, os.path.join(PLANT, 'v2'))
        self.assertEqual(self.code, 0)
        self.assertIn('B.folder', rec.states())
        self.assertNotIn('B.start', rec.states())

    def test_same_names(self):
        b = os.path.join(self.tmp, 'other', 'Plant_A.zap20')
        os.makedirs(os.path.dirname(b))
        with open(b, 'w') as f:
            json.dump({'export': 'v2'}, f)
        rec = self.run_compare(self.a, b)
        self.assertEqual(self.code, 0)
        self.assertIn('Plant_A (A) vs Plant_A (B)', rec.end()['folder'])

    def test_long_names_of_one_project(self):
        a = self.archive('tool-plant-conveyor-line-seven-2026-10-19_161610.zap20', {'export': 'v1'})
        b = self.archive('tool-plant-conveyor-line-seven-2026-10-22_125955.zap20', {'export': 'v2'})
        rec = self.run_compare(a, b)
        self.assertEqual(self.code, 0)
        self.assertTrue(os.path.basename(rec.end()['folder']).endswith(
            ' tool-plant-conveyor-li~2026-10-19_161610 vs tool-plant-conveyor-li~2026-10-22_125955'))
        with open(rec.end()['report'], encoding='utf-8') as f:
            page = f.read()
        self.assertIn('2026-10-19_161610', page)                    # the report's side labels stay apart too
        self.assertIn('2026-10-22_125955', page)

    def test_stale_work_folder_removed(self):
        stale = os.path.join(self.tmp, 'data', 'work', '999999')
        os.makedirs(os.path.join(stale, 'A'))
        rec = self.run_compare(self.a, self.b)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(any('earlier run' in e['text'] for e in rec.of('log')))

    def test_hmi(self):
        a = self.archive('Plant_A.zap20', {'export': 'v1', 'hmi_failed': ['Alarm_Overview']})
        rec = self.run_compare(a, self.b, hmi=True)
        self.assertEqual(self.code, 0, rec.end())
        plan = {s['id']: s['text'] for s in rec.events[0]['steps']}
        self.assertIn('and the HMI', plan['A.export'])
        items = [e['item'] for e in rec.of('progress') if e['id'] == 'A.export']
        self.assertIn('HMI screens of Panel_1: Screen_064', items)        # the last of a part is always sent
        self.assertIn('project graphics: Graphic_080', items)
        end = rec.end()
        nx = {x['name']: x['why'] for x in end['not_exported']}
        self.assertTrue(nx['Alarm_Overview (HMI screen, Panel_1)'].startswith('A: TIA did not export it'))
        with open(os.path.join(end['folder'], 'run.json'), encoding='utf-8') as f:
            run = json.load(f)
        self.assertTrue(run['options']['hmi'])
        self.assertEqual(run['options']['scope'], list(PARTS + HMI_PARTS))
        # the samples' HMI: a screen changed, one new, the tag table changed
        self.assertEqual(run['report']['hmi'], 3)
        self.assertEqual(end['changed'], run['report']['blocks'] + 3)
        with open(end['report'], encoding='utf-8') as f:
            self.assertIn('Conveyor_Settings', f.read())
        self.assertTrue(any('and 3 HMI object(s) changed' in e['text'] for e in rec.of('log')))
        # the cache keeps a run with the HMI apart from one without
        rec = self.run_compare(a, self.b)
        self.assertEqual(rec.states()['A.export'], 'done')
        plan = {s['id']: s['text'] for s in rec.events[0]['steps']}
        self.assertNotIn('HMI', plan['A.export'])
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            self.assertNotIn('hmi', json.load(f)['report'])
        rec = self.run_compare(a, self.b, hmi=True)
        self.assertEqual(rec.states()['A.export'], 'skipped')
        self.assertTrue(any(x['name'] == 'Alarm_Overview (HMI screen, Panel_1)' for x in rec.end()['not_exported']))

    def test_end_carries_the_moved_count(self):
        self.assertEqual(run_module.end_counts({'path': 'r.html', 'changed': 2, 'moved': 3}),
                         {'report': 'r.html', 'changed': 2, 'moved': 3})

    def test_blocks_that_only_moved_are_counted_apart(self):
        res = {'blocks': [{'state': 'changed'}, {'state': 'moved'}, {'state': 'moved'}, {'state': 'deleted'}],
               'hmi': [{}]}
        self.assertEqual(run_module.report_counts(res), (2, 2, 1, 0))  # changed, new or deleted; moved; HMI; tag tables

    def test_plc_tag_tables_are_counted_and_one_only_moved_apart(self):
        res = {'blocks': [{'state': 'changed'}, {'state': 'moved'}],
               'plcTags': [{'state': 'changed'}, {'state': 'new'}, {'state': 'moved'}]}
        self.assertEqual(run_module.report_counts(res), (1, 2, 0, 2))

    def plc_tag_table(self, address):
        return ('<Document><SW.Tags.PlcTagTable ID="0"><AttributeList><Name>Plant</Name></AttributeList><ObjectList>'
                '<SW.Tags.PlcTag ID="1" CompositionName="Tags"><AttributeList><DataTypeName>Bool</DataTypeName>'
                '<LogicalAddress>%s</LogicalAddress><Name>Conveyor_Run</Name></AttributeList></SW.Tags.PlcTag>'
                '</ObjectList></SW.Tags.PlcTagTable></Document>' % address)

    def tag_export(self, name, address):
        """An export folder: the made-up plant's v1 and the tag table Plant with Conveyor_Run at address."""
        d = os.path.join(self.tmp, name)
        shutil.copytree(os.path.join(PLANT, 'v1'), d)
        os.makedirs(os.path.join(d, 'plc', 'tags'))
        with open(os.path.join(d, 'plc', 'tags', 'Plant.xml'), 'w', encoding='utf-8') as f:
            f.write(self.plc_tag_table(address))
        return d

    def test_two_export_folders_differing_in_a_tag_are_not_no_changes(self):
        rec = self.run_compare(self.tag_export('exports-a', '%M1.0'), self.tag_export('exports-b', '%M2.0'))
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.end()['changed'], 1)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            report = json.load(f)['report']
        self.assertEqual((report['blocks'], report['plcTags']), (0, 1))
        with open(rec.end()['report'], encoding='utf-8') as f:
            self.assertIn('Plant [PLC tag table]', f.read())

    def test_two_archives_differing_only_in_a_tag_show_the_tag_change(self):
        self.tag_export('exports-a', '%M1.0')
        self.tag_export('exports-b', '%M2.0')
        a = self.archive('Plant_A.zap20', {'export': '../exports-a'})
        b = self.archive('Plant_B.zap20', {'export': '../exports-b'})
        rec = self.run_compare(a, b)
        self.assertEqual(self.code, 0, rec.end())
        plan = {s['id']: s['text'] for s in rec.events[0]['steps']}
        self.assertIn('tag tables', plan['A.export'])
        items = [e['item'] for e in rec.of('progress') if e['id'] == 'A.export']
        self.assertIn('PLC tag tables: TagTable_012', items)    # the last of a part is always sent
        self.assertEqual(rec.end()['changed'], 1)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            run = json.load(f)
        self.assertIn('plc_tags', run['options']['scope'])           # and so in the cache key
        self.assertEqual((run['report']['blocks'], run['report']['plcTags']), (0, 1))
        with open(rec.end()['report'], encoding='utf-8') as f:
            page = f.read()
        self.assertIn('Conveyor_Run', page)
        self.assertIn('%M1.0 %M2.0', re.sub(r'<[^>]+>', '', page))     # the address before and after

    def test_an_export_folder_with_tag_tables_against_an_archive_with_the_same_compares_them(self):
        d = self.tag_export('exports', '%M1.0')
        a = self.archive('Plant_A.zap20', {'export': '../exports'})
        rec = self.run_compare(d, a)
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.end()['changed'], 0)
        with open(rec.end()['report'], encoding='utf-8') as f:
            self.assertNotIn('Plant [PLC tag table]', f.read())

    def test_two_export_folders_differing_in_a_file_the_report_does_not_read_are_not_no_changes(self):
        folders = []
        for v in ('a', 'b'):
            d = os.path.join(self.tmp, 'exports-' + v)
            shutil.copytree(os.path.join(PLANT, 'v1'), d)
            os.makedirs(os.path.join(d, 'plc', 'watchtables'))
            with open(os.path.join(d, 'plc', 'watchtables', 'Watch.dat'), 'w', encoding='utf-8') as f:
                f.write(v)
            os.makedirs(os.path.join(d, 'logs'))
            with open(os.path.join(d, 'logs', 'run.json'), 'w', encoding='utf-8') as f:     # the exporter's, not counted
                f.write(v)
            folders.append(d)
        rec = self.run_compare(*folders)
        self.assertEqual(self.code, 0)
        self.assertEqual(rec.end()['changed'], 1)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['report']['otherFiles'], ['plc/watchtables/Watch.dat'])

    def test_an_export_folder_without_tag_tables_against_an_archive_lists_them_new(self):
        d = os.path.join(self.tmp, 'exports')                        # as the guide says
        shutil.copytree(os.path.join(PLANT, 'v1'), d)
        self.tag_export('exports-b', '%M1.0')
        b = self.archive('Plant_B.zap20', {'export': '../exports-b'})
        rec = self.run_compare(d, b)
        self.assertEqual(self.code, 0)
        with open(rec.end()['report'], encoding='utf-8') as f:
            self.assertIn('Plant [PLC tag table]</b><span class="st new">new</span>', f.read())

    def test_export_folder_with_hmi(self):
        folders = []
        for v in ('v1', 'v2'):
            d = os.path.join(self.tmp, 'exports-' + v)
            shutil.copytree(os.path.join(PLANT, v), d)
            shutil.copytree(os.path.join(HMI_SAMPLES, v, 'hmi'), os.path.join(d, 'hmi'))
            folders.append(d)
        rec = self.run_compare(*folders)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            run = json.load(f)
        self.assertNotIn('hmi', run['report'])
        with open(rec.end()['report'], encoding='utf-8') as f:
            self.assertNotIn('Conveyor_Settings', f.read())          # without the HMI box: the PLC only
        rec = self.run_compare(*folders, hmi=True)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['report']['hmi'], 3)

    def test_hmi_without_hmi_device(self):
        a = self.archive('Plant_A.zap20', {'export': 'v1', 'hmi_devices': []})
        b = self.archive('Plant_B.zap20', {'export': 'v2', 'hmi_devices': []})
        rec = self.run_compare(a, b, hmi=True)
        self.assertEqual(self.code, 0)
        self.assertTrue(any('no HMI device' in e['text'] for e in rec.of('log')))
        self.assertFalse(any(e['item'].startswith('HMI') for e in rec.of('progress')))
        self.assertTrue(any('and 0 HMI object(s)' in e['text'] for e in rec.of('log')))

    def test_hmi_two_devices(self):
        a = self.archive('Plant_A.zap20', {'export': 'v1', 'hmi_devices': ['Panel_1', 'Panel_2']})
        b = self.archive('Plant_B.zap20', {'export': 'v2', 'hmi_devices': ['Panel_1', 'Panel_2']})
        rec = self.run_compare(a, b, hmi=True)
        self.assertEqual(self.code, 0)
        items = {e['item'] for e in rec.of('progress') if e['id'] == 'B.export'}
        self.assertTrue({'HMI tag tables of Panel_1: Tags_014', 'HMI tag tables of Panel_2: Tags_014'} <= items)
        with open(os.path.join(rec.end()['folder'], 'run.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['report']['hmi'], 6)          # hmi\Panel_1\ and hmi\Panel_2\

    def test_fake_tia_process(self):
        rec = self.run_compare(self.a, self.b, make=lambda w: FakeExporter(speed=0))
        pids = [e['pid'] for e in rec.of('tia')]
        self.assertEqual(len(pids), 2)
        for ex in self.exporters:
            self.assertIsNone(ex._child)                               # ended by close


class CliTest(Tmp):
    def test_usage_errors_end_with_an_event(self):
        out = io.StringIO()
        code = cli.main(['run', '--before', 'a.zap20', '--after', 'b.zap20', '--safety'], stdout=out,
                        stdin=io.BytesIO(b''))
        self.assertEqual(code, 2)
        self.assertIn('--safety needs --compile', json.loads(out.getvalue())['error'])
        out = io.StringIO()
        projects = os.path.join(cli.projects_roots()[0], 'x')
        code = cli.main(['run', '--before', 'a', '--after', 'b', '--out-root', projects], stdout=out,
                        stdin=io.BytesIO(b''))
        self.assertEqual(code, 2)
        self.assertIn('never writes there', out.getvalue())

    def test_projects_root_follows_the_bridge_settings(self):
        settings = os.path.join(self.tmp, 'settings.json')
        default = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects')
        self.assertEqual([default], cli.projects_roots(settings))               # no settings file
        for text in ('not json', '[]', '{"tiaRoot": "C:\\\\TIA"}'):
            with open(settings, 'w', encoding='utf-8') as f:
                f.write(text)
            self.assertEqual([default], cli.projects_roots(settings), text)
        elsewhere = os.path.join(self.tmp, 'Elsewhere')
        with open(settings, 'w', encoding='utf-8-sig') as f:                    # PowerShell writes a BOM
            json.dump({'projectsRoot': elsewhere}, f)
        self.assertEqual([elsewhere], cli.projects_roots(settings))
        saved = checks.BRIDGE_SETTINGS
        checks.BRIDGE_SETTINGS = settings
        self.addCleanup(setattr, checks, 'BRIDGE_SETTINGS', saved)
        out = io.StringIO()
        code = cli.main(['run', '--before', 'a', '--after', 'b', '--data-root', os.path.join(elsewhere, 'd')],
                        stdout=out, stdin=io.BytesIO(b''))
        self.assertEqual(code, 2)
        self.assertIn('is under %s; the tool never writes there' % elsewhere, json.loads(out.getvalue())['error'])

    def test_the_guard_holds_for_both_readings_of_a_file_without_a_bom(self):
        """A text editor's UTF-8: the bridge reads it as ANSI, garbled, and its repos go there; the folder as typed may
        hold repos too. The fake exporter and folders of this test only: a run that got through touches nothing else."""
        settings = os.path.join(self.tmp, 'settings.json')
        typed = os.path.join(self.tmp, 'M\u00fcller', 'Projects')
        garbled = typed.encode('utf-8').decode('mbcs')
        self.assertNotEqual(typed, garbled)
        with open(settings, 'wb') as f:
            f.write(json.dumps({'projectsRoot': typed}, ensure_ascii=False).encode('utf-8'))
        saved = checks.BRIDGE_SETTINGS
        checks.BRIDGE_SETTINGS = settings
        self.addCleanup(setattr, checks, 'BRIDGE_SETTINGS', saved)
        data = os.path.join(self.tmp, 'data')
        for root in (typed, garbled):
            under = os.path.join(root, 'x')
            for args in (['--out-root', under, '--data-root', data], ['--data-root', under]):
                out = io.StringIO()
                code = cli.main(['run', '--before', 'a', '--after', 'b', '--exporter', 'fake'] + args, stdout=out,
                                stdin=io.BytesIO(b''))
                self.assertEqual(2, code, (root, args))
                self.assertIn('is under %s; the tool never writes there' % root, json.loads(out.getvalue())['error'])

    def test_one_reading_only_where_the_file_has_one(self):
        settings = os.path.join(self.tmp, 'settings.json')
        folder = 'D:\\M\u00fcller\\Projects'
        text = json.dumps({'projectsRoot': folder}, ensure_ascii=False)
        for raw in (text.encode('utf-8-sig'), text.encode('utf-16'), text.encode('mbcs')):
            with open(settings, 'wb') as f:
                f.write(raw)
            self.assertEqual([folder], cli.projects_roots(settings), raw)

    def test_the_folder_is_the_one_the_bridge_reads(self):
        """Its parser takes more than JSON and refuses some JSON: the guard goes by what it reads, so a run does not
        write into the bridge's folder while the tool takes the default for it."""
        values = ['007', '+1', '.5', '1.', '5-', '1.5-', 'NaN', 'Infinity', '-Infinity', '1E+5', '-0', '9' * 32,
                  '79228162514264337593543950335-', 'null', 'false', '[]', "{'y': [1, {z: 'w'}]}", '0x10', '1e400',
                  '9' * 309, 'undefined', 'True', 'infinity', '+Infinity', '-NaN', '1_000', '1-2', '+5-', '1e5-',
                  '79228162514264337593543950336-', '.e5', '.', 'tr ue', '[1,2,]', '[,]', '[1 2]', '{"b": 1, "B": 2}',
                  '{"": 1}', '{"a": 1, "": 2}', '{,}', '{"K": 1, "K": 2}', '{"İ": 1, "i̇": 2}',
                  '{"ß": 1, "SS": 2}', '{"ı": 1, "I": 2}', '{"ſ": 1, "S": 2}', '{"é": 1, "É": 2}', '\u0663', "'\\x41'", "'\\q'", "'\\u00f'"]
        texts = ['{"x": %s, "projectsRoot": "D:\\\\Value %d"}' % (v, i) for i, v in enumerate(values)]
        texts += ["{'projectsRoot': 'D:\\\\Single'}", '{projectsRoot: "D:\\\\Unquoted"}',
                  "{'projectsRoot': 'D:\\\\it\\'s \"here\"'}", '{"Projectsroot": "D:\\\\Any case"}',
                  '{"projectsRoot": "D:\\\\First", "projectsRoot": "D:\\\\Last"}',
                  '{"projectsRoot": "D:\\\\Case", "PROJECTSROOT": "D:\\\\Twice"}', '{"projectsRoot": "D:\\\\Comma",}',
                  '{"projectsRoot": "D:\\\\Tail"} x', '{"projectsRoot": "D:\\\\Tab\there"}',
                  '{"projectsRoot": "D:\\\\\\u00fc\\u 0fc"}', '\u00a0{"projectsRoot": "D:\\\\Space"}\u2028',
                  '\x1c{"projectsRoot": "D:\\\\Separator"}', '{\u00fcber: 1, a-b.c+_1: 2, "projectsRoot": "D:\\\\Names"}',
                  '{a$b: 1, "projectsRoot": "D:\\\\Dollar"}', '{" ": 1, "projectsRoot": "D:\\\\Blank"}',
                  '{"x": %s%s, "projectsRoot": "D:\\\\Deep"}' % ('[' * 101, ']' * 101),
                  '{"x": %s%s, "projectsRoot": "D:\\\\Too deep"}' % ('[' * 102, ']' * 102),
                  '{}', '[{"projectsRoot": "D:\\\\Listed"}]', ' 5 ', '', '{"projectsRoot": "D:\\\\Open']
        lines = bridge_reads(os.path.join(self.tmp, 'cases'), [t.encode('utf-8-sig') for t in texts], 'projectsRoot')
        default = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects')
        self.assertEqual('D:\\Single', lines['%02d.json' % len(values)])        # the reader did read
        for name, read in sorted(lines.items()):
            text = texts[int(name[:-len('.json')])]
            path = os.path.join(self.tmp, 'cases', name)
            self.assertEqual([default if read == '<refused>' else read], cli.projects_roots(path), (text[:80], read))

    def test_no_ask_stops_at_the_login_with_stdin_open(self):
        """As an agent's host may leave stdin: open, and nothing on it. Without --no-ask this run would not end."""
        r, w = os.pipe()
        stdin = open(r, 'rb', buffering=0)
        # last in, first out: the writer goes first, which ends the reader's blocked read; a close during that read would hang
        self.addCleanup(stdin.close)
        self.addCleanup(os.close, w)
        out = io.StringIO()
        code = cli.main(['run', '--no-ask', '--before', os.path.join(SAMPLES, 'Plant_protected.zap20'), '--after',
                         os.path.join(SAMPLES, 'Plant_2026-09-01.zap20'), '--exporter', 'fake', '--fake-speed', '0',
                         '--out-root', os.path.join(self.tmp, 'o'), '--data-root', os.path.join(self.tmp, 'd')],
                        stdout=out, stdin=stdin)
        self.assertEqual(1, code)
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual('umc_login', [e for e in events if e['t'] == 'ask'][0]['kind'])
        self.assertIn('no login was given', events[-1]['error'])

    def test_process_with_samples(self):
        """The command line as the window starts it: events on stdout, a cancel on stdin."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
        cmd = [sys.executable, '-m', 'TiaArchiveCompare.runner', 'run',
               '--before', os.path.join(SAMPLES, 'Plant_2026-09-01.zap20'),
               '--after', os.path.join(SAMPLES, 'Plant_2026-10-28.zap20'), '--exporter', 'fake',
               '--fake-speed', '0.002',
               '--out-root', os.path.join(self.tmp, 'out'), '--data-root', os.path.join(self.tmp, 'data')]
        p = subprocess.Popen(cmd, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        events = []
        for line in p.stdout:
            ev = json.loads(line)
            events.append(ev)
            if ev['t'] == 'step' and ev['id'] == 'B.export' and ev['state'] == 'running':
                p.stdin.write(b'{"t":"cancel"}\n')
                p.stdin.flush()
        p.wait(60)
        for f in (p.stdin, p.stdout, p.stderr):
            f.close()
        self.assertEqual(p.returncode, 1)                     # not 0xC0000005 (stdin read at exit)
        self.assertTrue(events[-1].get('cancelled'))
        self.assertEqual([e['state'] for e in events if e['t'] == 'step' and e['id'] == 'A.export'],
                         ['running', 'done'])


# ---------------------------------------------------------------------------- where TIA is

class TiaRootCase(RunCase):
    """TiaBridge\\settings.json of this test, TIA in a folder of its own, a registry that says what the test wants."""

    def setUp(self):
        super().setUp()
        self.settings = os.path.join(self.tmp, 'bridge-settings.json')
        self.patch(checks, 'BRIDGE_SETTINGS', self.settings)
        self.patch(checks, 'in_openness_group', lambda: True)
        self.registry(None)
        self.no_tia = os.path.join(self.tmp, 'no TIA here')

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def registry(self, install):
        self.patch(checks, 'tia_install', lambda: install)

    def tia_folder(self):
        root = os.path.join(self.tmp, 'D Siemens Portal V20')
        api = os.path.join(root, 'PublicAPI', 'V20')
        os.makedirs(api)
        open(os.path.join(api, 'Siemens.Engineering.dll'), 'wb').close()
        return root

    def set_tia_root(self, root):
        with open(self.settings, 'w', encoding='utf-8-sig') as f:       # PowerShell writes a BOM
            json.dump({'tiaRoot': root}, f)

    def tia_problems(self):
        return [p for p in checks.check_pc(self.tmp)['problems'] if ' GB ' not in p]


class TiaRootCheckTest(TiaRootCase):
    def test_tia_root_is_the_bridge_setting_else_the_bridge_default(self):
        default = r'C:\Program Files\Siemens\Automation\Portal V20'
        self.assertEqual(default, checks.tia_root())                            # no settings file
        for text in ('not json', '[]', '{"projectsRoot": "C:\\\\P"}', '{"tiaRoot": ""}', '{"tiaRoot": 5}'):
            with open(self.settings, 'w', encoding='utf-8') as f:
                f.write(text)
            self.assertEqual(default, checks.tia_root(), text)
        self.set_tia_root(r'D:\TIA\Portal V20')
        self.assertEqual(r'D:\TIA\Portal V20', checks.tia_root())

    def test_tia_in_the_folder_of_the_setting_is_found(self):
        root = self.tia_folder()
        self.set_tia_root(root)
        self.registry({'version': 'V20.00.00.07', 'path': root, 'openness': True})
        self.assertEqual([], self.tia_problems())
        pc = checks.check_pc(self.tmp)
        self.assertEqual('V20.00.00.07', pc['tia'])
        self.assertIn('TIA Portal V20.00.00.07 in %s' % root, pc['facts'])

    def test_the_folder_decides_without_a_registry_entry(self):
        self.set_tia_root(self.tia_folder())
        self.assertEqual([], self.tia_problems())
        self.assertEqual('V20', checks.check_pc(self.tmp)['tia'])

    def test_a_wrong_folder_is_named(self):
        self.set_tia_root(self.no_tia)
        self.registry({'version': 'V20.00.00.07', 'path': '', 'openness': True})
        self.assertEqual(['TIA Portal V20 with TIA Openness was not found in %s. Install it with the TIA Openness '
                          'option; if it is in another folder, set tiaRoot in %s.' % (self.no_tia, self.settings)],
                         self.tia_problems())
        self.assertEqual('V20.00.00.07', checks.check_pc(self.tmp)['tia'])      # the cache still answers

    def test_a_wrong_folder_names_where_the_registry_has_it(self):
        there = self.tia_folder()
        self.set_tia_root(self.no_tia)
        self.registry({'version': 'V20.00.00.07', 'path': there, 'openness': True})
        self.assertEqual(['TIA Portal V20 with TIA Openness was not found in %s. It is installed in %s: set tiaRoot '
                          'to that folder in %s.' % (self.no_tia, there, self.settings)], self.tia_problems())

    def test_nothing_installed_names_the_default_folder(self):
        self.patch(checks, 'DEFAULT_TIA_ROOT', self.no_tia)                      # this PC may have TIA there
        self.assertIsNone(checks.check_pc(self.tmp)['tia'])
        self.assertIn('was not found in %s.' % self.no_tia, self.tia_problems()[0])

    def test_openness_not_installed_names_the_folder(self):
        self.set_tia_root(self.no_tia)
        self.registry({'version': 'V20.00.00.07', 'path': self.no_tia, 'openness': False})
        self.assertEqual(['TIA Portal V20 with TIA Openness was not found in %s. TIA Openness is not installed with '
                          'TIA Portal V20 (an option of its setup). Ask IT to add it.' % self.no_tia],
                         self.tia_problems())

    def test_settings_that_are_not_json_are_named_with_the_backslash_hint(self):
        root = self.tia_folder()
        self.patch(checks, 'DEFAULT_TIA_ROOT', root)                            # TIA stands in the default folder
        self.registry({'version': 'V20.00.00.07', 'path': root, 'openness': True})
        with open(self.settings, 'w', encoding='utf-8') as f:
            f.write('{"tiaRoot": "D:\\Siemens\\Portal V20"}')                   # single backslashes in the file
        problems = self.tia_problems()
        self.assertEqual(1, len(problems))
        self.assertIn('%s is not valid JSON, so the tool does not know where TIA Portal is' % self.settings, problems[0])
        self.assertIn('A path in it has each backslash doubled.', problems[0])
        self.assertEqual('V20.00.00.07', checks.check_pc(self.tmp)['tia'])      # the cache still answers

    def test_json_the_bridge_refuses_is_named_with_its_reason(self):
        """Valid JSON that Get-BridgeSettings refuses: the reason, and no hint about backslashes, which are not it."""
        root = self.tia_folder()
        self.patch(checks, 'DEFAULT_TIA_ROOT', root)
        self.registry({'version': 'V20.00.00.07', 'path': root, 'openness': True})
        for text, reason in (('{"tiaRoot": "D:\\\\TIA", "TIAROOT": "D:\\\\Other"}',
                              'two names that differ in case only: tiaRoot and TIAROOT'),
                             ('{"": 1}', 'an empty name'), ('{"x": {"a": 1, "": 2}}', 'an empty name'),
                             ('{"archivesKept": 1e400}', 'the number 1e400, too large for it'),
                             ('{"x": %s%s}' % ('[' * 102, ']' * 102), 'nesting over 102 levels')):
            with open(self.settings, 'w', encoding='utf-8') as f:
                f.write(text)
            problems = self.tia_problems()
            self.assertEqual(['The bridge refuses %s (%s), so the tool does not know where TIA Portal is.'
                              % (self.settings, reason)], problems, text[:60])
        with open(self.settings, 'w', encoding='utf-8') as f:
            f.write('{"tiaRoot": "D:\\\\TIA" "archivesKept": 3}')                # a comma left out: not the backslashes
        problems = self.tia_problems()
        self.assertIn('%s is not valid JSON, so the tool does not know where TIA Portal is' % self.settings, problems[0])
        self.assertNotIn('backslash', problems[0])

    def test_what_only_the_bridge_parses_is_read(self):
        """Single quotes and unquoted names, which JSON has not and Get-BridgeSettings takes."""
        root = self.tia_folder()
        for text in ("{'tiaRoot': '%s'}", '{tiaRoot: "%s"}'):
            with open(self.settings, 'w', encoding='utf-8') as f:
                f.write(text % root.replace('\\', '\\\\'))
            self.assertEqual(root, checks.tia_root(), text)
            self.assertEqual([], self.tia_problems(), text)

    def test_settings_that_cannot_be_opened_are_named_without_the_hint(self):
        self.patch(checks, 'DEFAULT_TIA_ROOT', self.tia_folder())
        os.makedirs(self.settings)                                              # opening a folder is an OSError
        problems = self.tia_problems()
        self.assertEqual(1, len(problems))
        self.assertIn('%s cannot be read, so the tool does not know where TIA Portal is' % self.settings, problems[0])
        self.assertNotIn('backslash', problems[0])

    def test_a_utf16_file_as_powershell_writes_it_is_read(self):
        root = self.tia_folder()
        with open(self.settings, 'w', encoding='utf-16') as f:                  # `>` in Windows PowerShell
            json.dump({'tiaRoot': root}, f)
        self.assertEqual(root, checks.tia_root())
        self.assertEqual([], self.tia_problems())

    def test_settings_are_read_as_the_bridge_reads_them(self):
        """Against Get-BridgeSettings itself (Repo.ps1, dot-sourced: no bridge, no TIA)."""
        folder = 'D:\\M\u00fcller\\Portal V20'
        text = json.dumps({'tiaRoot': folder}, ensure_ascii=False)
        ascii_text = json.dumps({'tiaRoot': r'D:\TIA'})
        cases = [text.encode('utf-8-sig'), text.encode('utf-8'), text.encode('mbcs', 'replace'), text.encode('utf-16'),
                 b'\xfe\xff' + text.encode('utf-16-be'), b'\xff\xfe\x00\x00' + text.encode('utf-32-le'),
                 b'\x00\x00\xfe\xff' + text.encode('utf-32-be'), text.encode('utf-16-le'),
                 ascii_text.replace('tiaRoot', 'TIAROOT').encode(), b'[]', b'5', b'null', b'', b'\xef\xbb\xbf', b'  \r\n',
                 b'not json', b'{"tiaRoot": "D:\\Siemens"}', b'{"tiaRoot": "D:\\\\TIA",}']
        folder_of_cases = os.path.join(self.tmp, 'cases')
        lines = bridge_reads(folder_of_cases, cases, 'tiaRoot')
        self.assertEqual(folder, lines['00.json'])                              # the reader did read: not all defaults
        for name, read in lines.items():
            with mock.patch.object(checks, 'BRIDGE_SETTINGS', os.path.join(folder_of_cases, name)):
                if read == '<refused>':
                    self.assertIsNotNone(checks.bridge_settings_problem(), name)
                else:
                    self.assertIsNone(checks.bridge_settings_problem(), name)
                    self.assertEqual(read, checks.tia_root(), name)

    def test_the_version_is_the_registrys_only_for_the_folder_it_names(self):
        root = self.tia_folder()
        self.set_tia_root(root)
        self.registry({'version': 'V20.00.00.07', 'path': os.path.join(self.tmp, 'Other Portal V20'), 'openness': True})
        pc = checks.check_pc(self.tmp)
        self.assertEqual('V20', pc['tia'])
        self.assertIn('TIA Portal V20 in %s' % root, pc['facts'])
        self.registry({'version': 'V20.00.00.07', 'path': root.upper() + '\\', 'openness': True})
        self.assertEqual('V20.00.00.07', checks.check_pc(self.tmp)['tia'])      # the same folder, spelt otherwise

    def test_the_openness_group_is_still_checked(self):
        self.set_tia_root(self.tia_folder())
        self.patch(checks, 'in_openness_group', lambda: False)
        self.assertIn("group 'Siemens TIA Openness'", self.tia_problems()[0])


class TiaRootRunTest(TiaRootCase):
    def open_bridge(self, ex, work):
        self.addCleanup(ex.kill)
        ex.open(inputs.classify(self.archive('P.zap20', {})), os.path.join(work, 'entry', 'export'), Hooks())

    def test_a_wrong_folder_ends_the_run_with_a_plain_message(self):
        self.set_tia_root(self.no_tia)
        self.registry({'version': 'V20.00.00.07', 'path': '', 'openness': True})
        started = []

        def make(work):
            ex = FakeExporter(speed=0, process=False)
            ex.needs_tia = True
            if work:
                started.append(work)
            return ex
        rec = self.run_compare(self.archive('A.zap20', {}), self.archive('B.zap20', {'x': 1}), make=make,
                               check=checks.check_pc)
        self.assertEqual(1, self.code)
        self.assertEqual('failed', rec.states()['A.start'])
        self.assertIn('was not found in %s.' % self.no_tia, rec.end()['error'])
        self.assertEqual([], started)                                           # no TIA was started

    def test_the_child_is_given_the_folder(self):
        root = self.tia_folder()
        self.set_tia_root(root)
        work = os.path.join(self.tmp, 'w')
        ex = self.bridge(work)
        self.open_bridge(ex, work)
        with open(os.path.join(work, 'settings.json'), encoding='utf-8') as f:
            self.assertEqual(root, json.load(f)['tiaRoot'])
        ex.close(Hooks())

    def test_the_bridge_reads_the_folder_from_that_file(self):
        """The bridge's own settings reader, not the bridge: a child that missed the folder would start a real TIA
        from the default one, on the PC running these tests."""
        self.set_tia_root(self.no_tia)
        work = os.path.join(self.tmp, 'w')
        ex = self.bridge(work)
        self.open_bridge(ex, work)
        ex.close(Hooks())
        repo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), 'TiaBridge', 'Repo.ps1')
        script = ". '%s'; [Console]::OutputEncoding = [Text.Encoding]::UTF8; (Get-BridgeSettings '%s').tiaRoot" \
                 % (repo, os.path.join(work, 'settings.json'))
        out = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                             capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(self.no_tia, out.stdout.decode('utf-8-sig').strip(), out.stderr)


# ---------------------------------------------------------------------------- the TiaBridge client

class BridgeTest(RunCase):
    def test_parse_progress(self):
        self.assertEqual(parse_progress('[tiabridge 12:00:00] progress {"event":"object","n":1,"of":2}'),
                         {'event': 'object', 'n': 1, 'of': 2})
        self.assertIsNone(parse_progress('[tiabridge 12:00:00] full_export blocks ...'))
        self.assertIsNone(parse_progress('progress {broken'))

    def test_run_cancelled_during_a_long_export(self):
        cfg = dict(export=os.path.join(PLANT, 'v1'), export_seconds=60)
        a, b = self.archive('A.zap20', {}), self.archive('B.zap20', {'b': 1})
        t0 = time.monotonic()
        rec = self.run_compare(a, b, make=lambda w: self.bridge(w, **cfg) if w else BridgeExporter(None),
                               on=lambda ev: ev.get('id') == 'A.export' and ev['t'] == 'progress' and
                               self.commands.cancel.set())
        self.assertLess(time.monotonic() - t0, 30)
        self.assertTrue(rec.end().get('cancelled'))
        st = rec.states()
        self.assertEqual((st['A.export'], st['A.close'], st['B.start']), ('cancelled', 'done', 'skipped'))
        self.assertFalse(any(e['level'] == 'warn' and 'did not close' in e['text'] for e in rec.of('log')))
        exports = os.path.join(self.tmp, 'data', 'exports')
        self.assertFalse(os.path.isdir(exports) and os.listdir(exports))     # nothing cached

    def test_run_over_mcp(self):
        cfgs = [dict(export=os.path.join(PLANT, 'v1'), failed=[{'name': 'Calc', 'error': {
                    'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
                    'message': 'Inconsistent blocks and PLC data types (UDT) cannot be exported.'}}], khp=['Secret'],
                     not_exportable={
                         'blocks': [{'name': 'FOB_Main', 'folder': 'Safety', 'reason': 'F-system blocks and the F-OB '
                                     'of the F-runtime group: TIA does not permit their export', 'message':
                                     "Error when calling method 'Export'.\r\n\r\nThe export of block 'FOB_Main' "
                                     "is not permitted."}],
                         'library_types': [{'name': 'Secret', 'folder': 'Lib', 'reason': 'know-how protected '
                                            'library types: no documents', 'message': 'The block is '
                                            'know-how-protected and cannot be exported.'}]}),
                dict(export=os.path.join(PLANT, 'v2'), prompts=[{'kind': 'confirmation', 'caption': 'TIA',
                                                                'text': 'Save?', 'answer': 'No'}])]
        a, b = self.archive('A.zap20', {}), self.archive('B.zap20', {'b': 1})
        rec = self.run_compare(a, b, make=lambda w: self.bridge(w, **cfgs[len(self.exporters)]) if w else
                               BridgeExporter(None))
        self.assertEqual(self.code, 0, rec.end())
        st = rec.states()
        self.assertEqual(set(st.values()), {'done'})
        self.assertEqual(len(rec.of('tia')), 2)
        prog = [e for e in rec.of('progress') if e['id'] == 'A.export']
        self.assertEqual(prog[0]['item'], 'blocks: blocks_1')
        self.assertEqual((prog[0]['done'], prog[0]['total']), (1, 3))
        nx = {x['name']: x['why'] for x in rec.end()['not_exported']}
        self.assertEqual(nx['Calc'], 'A: not compiled (inconsistent): compile the project and archive it again, or '
                                     'tick "Compile"')
        self.assertIn('know-how', nx['Secret'])
        self.assertEqual(nx['FOB_Main'], 'A: F-system block: TIA does not export it')
        self.assertEqual(nx['Secret (library type)'], 'A: know-how protected: TIA does not export its code')
        self.assertIn('A: exported 1 blocks', '\n'.join(e['text'] for e in rec.of('log')))   # Calc failed, FOB_Main left out
        self.assertEqual(rec.of('prompt')[0]['text'], 'TIA: Save?')
        # the settings point the bridge at the tool's folders, the git folder is not cached
        exports = os.path.join(self.tmp, 'data', 'exports')
        for k in os.listdir(exports):
            self.assertFalse(os.path.exists(os.path.join(exports, k, 'export', '.git')))
            self.assertTrue(os.path.isdir(os.path.join(exports, k, 'export', 'plc')))

    def open_with(self, login=None, **cfg):
        work = os.path.join(self.tmp, 'w')
        ex = self.bridge(work, **cfg)
        self.addCleanup(ex.kill)
        src = inputs.classify(self.archive('P.zap20', {}))
        return ex, lambda: ex.open(src, os.path.join(work, 'entry', 'export'), Hooks(), login)

    def test_settings(self):
        ex, do = self.open_with()
        do()
        with open(os.path.join(self.tmp, 'w', 'settings.json'), encoding='utf-8') as f:
            s = json.load(f)
        self.assertEqual(s['projectsRoot'], os.path.join(self.tmp, 'w', 'entry'))
        self.assertEqual(s['backgroundRoot'], os.path.join(self.tmp, 'w', 'copy'))
        ex.close(Hooks())
        self.assertIsNotNone(ex._p.poll())

    def test_archive_goes_as_a_short_named_copy(self):
        work = os.path.join(self.tmp, 'w')
        ex = self.bridge(work)
        self.addCleanup(ex.kill)
        given = self.archive('Plant_line_7_after_the_conveyor_rebuild_2026-10-28_with_a_long_name.zap20', {'x': 1})
        ex.open(inputs.classify(given), os.path.join(work, 'entry', 'export'), Hooks())
        ex.close(Hooks())
        with open(os.path.join(work, 'calls.jsonl'), encoding='utf-8') as f:
            path = json.loads(f.readline())['args']['path']
        self.assertEqual(path, os.path.join(work, 'p.zap20'))
        with open(path, 'rb') as a, open(given, 'rb') as b:
            self.assertEqual(a.read(), b.read())

    def test_plain_folder(self):
        ex, do = self.open_with()
        do()
        ex.close(Hooks())
        with open(os.path.join(self.tmp, 'w', 'calls.jsonl'), encoding='utf-8') as f:
            self.assertTrue(json.loads(f.readline())['args']['plain'])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'w', 'entry', 'export', '.git')))
        ex, do = self.open_with(plain=False)            # an older TiaBridge: no plain argument
        do()
        ex.close(Hooks())
        with open(os.path.join(self.tmp, 'w', 'calls.jsonl'), encoding='utf-8') as f:
            self.assertNotIn('plain', json.loads(f.readlines()[-2])['args'])

    def test_protected(self):
        _, do = self.open_with(protected={'user': 'u', 'password': 'p'})
        with self.assertRaises(NeedsLogin) as c:
            do()
        self.assertFalse(c.exception.wrong)
        _, do = self.open_with(login={'user': 'u', 'password': 'p'}, protected={'user': 'u', 'password': 'p'})
        with self.assertRaises(ExportFailed) as c:
            do()                                        # TiaBridge without the login arguments
        self.assertIn('cannot log on', c.exception.plain)
        _, do = self.open_with(login={'user': 'u', 'password': 'p'}, protected={'user': 'u', 'password': 'p'},
                               login_args=True)
        self.assertTrue(do().pid)
        _, do = self.open_with(login={'user': 'u', 'password': 'x'}, protected={'user': 'u', 'password': 'p'},
                               login_args=True)
        with self.assertRaises(NeedsLogin) as c:
            do()
        self.assertTrue(c.exception.wrong)

    def test_cancel_ends_tia_at_once(self):
        ex, do = self.open_with(export_seconds=60)
        tia = do().pid

        class Cancelling(Hooks):
            def __init__(self):
                self.t0 = time.monotonic()

            def cancelled(self):
                return time.monotonic() - self.t0 > 0.5
        t0 = time.monotonic()
        with self.assertRaises(ExportFailed) as c:
            ex.export(['blocks'], Cancelling())
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn('Cancelled', c.exception.plain)
        ex.close(Hooks())                               # the child is gone: no call
        self.assertFalse(pid_alive(tia))
        self.assertIsNotNone(ex._p.poll())

    def test_umc_global(self):
        prot = {'user': 'u', 'password': 'p', 'global': True}
        ex, do = self.open_with(login={'user': 'u', 'password': 'p', 'umc_global': True}, protected=prot,
                                login_args=True)
        self.assertTrue(do().pid)
        ex.close(Hooks())
        with open(os.path.join(self.tmp, 'w', 'calls.jsonl'), encoding='utf-8') as f:
            self.assertIs(json.loads(f.readline())['args']['umc_global'], True)
        _, do = self.open_with(login={'user': 'u', 'password': 'p'}, protected=prot, login_args=True)
        with self.assertRaises(NeedsLogin):
            do()                                        # a project user where a UMC user is needed
        _, do = self.open_with(login={'user': 'u', 'password': 'p', 'umc_global': True}, protected=prot,
                               login_args=True, global_arg=False)
        with self.assertRaises(ExportFailed) as c:
            do()                                        # TiaBridge without umc_global
        self.assertIn('UMC server user', c.exception.plain)

    def test_compile_refused_and_safety(self):
        ex, do = self.open_with()
        do()
        with self.assertRaises(ExportFailed) as c:
            ex.compile(Hooks())
        self.assertIn('cannot compile the copy yet', c.exception.plain)
        ex, do = self.open_with(compile='ok', login_args=True, safety='s1')
        do()
        with self.assertRaises(NeedsLogin):
            ex.compile(Hooks(), 'wrong')
        self.assertEqual(ex.compile(Hooks(), 's1'), [])

    def test_hmi_over_mcp(self):
        cfgs = [dict(export=os.path.join(PLANT, 'v1'), hmi_devices=['Panel_1'],
                     hmi_export=os.path.join(HMI_SAMPLES, 'v1'), hmi_failed=[{'name': 'Overview', 'error': {
                         'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
                         'message': 'The screen could not be exported.'}}]),
                dict(export=os.path.join(PLANT, 'v2'), hmi_devices=['Panel_1'],
                     hmi_export=os.path.join(HMI_SAMPLES, 'v2'))]
        a, b = self.archive('A.zap20', {}), self.archive('B.zap20', {'b': 1})
        rec = self.run_compare(a, b, hmi=True, make=lambda w: self.bridge(w, **cfgs[len(self.exporters)]) if w else
                               BridgeExporter(None))
        self.assertEqual(self.code, 0, rec.end())
        items = [e['item'] for e in rec.of('progress') if e['id'] == 'A.export']
        self.assertIn('HMI screens of Panel_1: hmi_screens_3', items)
        self.assertIn('project graphics: graphics_3', items)
        nx = {x['name']: x['why'] for x in rec.end()['not_exported']}
        self.assertEqual(nx['Overview (HMI screen, Panel_1)'],
                         'A: TIA did not export it (The screen could not be exported.)')
        log = '\n'.join(e['text'] for e in rec.of('log'))
        self.assertIn('Exported hmi_screens@Panel_1: 2/3', log)
        self.assertIn('and 3 HMI object(s) changed', log)
        self.assertNotIn('no HMI device', log)

    def test_hmi_parts_one_call_each_and_no_device(self):
        ex, do = self.open_with()
        do()
        hooks = LogHooks()
        ex.export(PARTS + HMI_PARTS, hooks)
        ex.close(Hooks())
        with open(os.path.join(self.tmp, 'w', 'calls.jsonl'), encoding='utf-8') as f:
            parts = [json.loads(x)['args']['parts'] for x in f if '"full_export"' in x]
        self.assertEqual(parts, [[p] for p in PARTS + HMI_PARTS])
        self.assertIn('The project has no HMI device: the report compares the PLC only.', hooks.lines)

    def test_bridge_dies(self):
        ex, do = self.open_with(die_on='full_export')
        do()
        with self.assertRaises(ExportFailed) as c:
            ex.export(['blocks'], Hooks())
        self.assertIn('ended unexpectedly', c.exception.plain)
        self.assertIn('dying in full_export', str(c.exception.err))

    def test_kill(self):
        ex, do = self.open_with()
        r = do()
        ex.kill()
        self.assertIsNotNone(ex._p.poll())
        self.assertFalse(_alive(r.pid))


class LogHooks(Hooks):
    def __init__(self):
        self.lines = []

    def log(self, level, text):
        self.lines.append(text)


def _alive(pid):
    from TiaArchiveCompare.runner.run import pid_alive
    for _ in range(50):
        if not pid_alive(pid):
            return False
        time.sleep(0.1)
    return True


if __name__ == '__main__':
    unittest.main()
