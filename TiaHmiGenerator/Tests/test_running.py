"""The records of running preview servers that the TIA dashboard links to (hmipreview\running.py):
written while a server listens, gone when it stops or its process is gone, and /api/about to check one."""
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

from hmipreview import running, server
from Tests.fixture import FixtureRepo, document
from Tests.test_server import PACKAGE_ROOT, ServerCase


def records(where):
    try:
        names = sorted(os.listdir(where))
    except OSError:
        return []
    out = []
    for n in names:
        with open(os.path.join(where, n), encoding='utf-8') as f:
            out.append(json.load(f))
    return out


class Folder(unittest.TestCase):
    def setUp(self):
        self.where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.where, True)

    def test_the_folder_is_the_users_unless_told(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Users\x\AppData\Local'}):
            os.environ.pop(running.FOLDER_ENV, None)
            self.assertEqual(os.path.join(r'C:\Users\x\AppData\Local', 'hmipreview', 'running'), running.folder())
        with mock.patch.dict(os.environ, {running.FOLDER_ENV: self.where}):
            self.assertEqual(self.where, running.folder())

    def test_a_record_is_written_whole_and_removed(self):
        running.write(self.where, running.record('repo', 'http://127.0.0.1:8765/', pid=42))
        self.assertEqual(['42.json'], os.listdir(self.where))
        r = records(self.where)[0]
        self.assertEqual((os.path.abspath('repo'), 'http://127.0.0.1:8765/', 42), (r['repo'], r['url'], r['pid']))
        self.assertRegex(r['started'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        running.remove(self.where, 42)
        running.remove(self.where, 42)
        self.assertEqual([], os.listdir(self.where))

    def test_prune_removes_the_records_of_processes_that_are_gone(self):
        for pid in (1, 2):
            running.write(self.where, running.record('repo', 'http://127.0.0.1:1/', pid=pid))
        with open(os.path.join(self.where, 'notes.txt'), 'w') as f:
            f.write('not a record')
        running.prune(self.where, alive=lambda pid: pid == 2)
        self.assertEqual(['2.json', 'notes.txt'], sorted(os.listdir(self.where)))

    def test_a_process_is_alive_while_it_runs(self):
        self.assertTrue(running.is_alive(os.getpid()))
        p = subprocess.Popen([sys.executable, '-c', 'pass'])
        p.wait()
        self.assertFalse(running.is_alive(p.pid))

    def test_the_link_from_this_machine(self):
        self.assertEqual('http://127.0.0.1:8765/', running.local_url('127.0.0.1', 8765))
        self.assertEqual('http://127.0.0.1:8765/', running.local_url('0.0.0.0', 8765))
        self.assertEqual('http://[::1]:8765/', running.local_url('::', 8765))
        self.assertEqual('http://192.168.56.10:8765/', running.local_url('192.168.56.10', 8765))


class About(ServerCase):
    def test_about_says_which_server_this_is(self):
        self.serve()
        with urllib.request.urlopen(self.base + '/api/about', timeout=10) as r:
            got = json.loads(r.read())
        self.assertEqual({'app': 'hmipreview', 'repo': os.path.abspath(self.repo.path), 'pid': os.getpid(), 'devices': []},
                         got)

    def test_about_is_told_to_this_machine_only(self):
        self.serve()
        with mock.patch.object(server, 'on_this_machine', return_value=False):
            self.assertEqual(403, self.get_error('/api/about'))
            self.assertEqual(200, self.get('/api/screens')[0])     # the rest answers the host network as before

    def test_this_machine_is_loopback_and_the_bound_address(self):
        for client, bound, mine in (('127.0.0.1', '0.0.0.0', True), ('::1', '::', True), ('::ffff:127.0.0.1', '::', True),
                                    ('192.168.56.10', '192.168.56.10', True), ('192.168.56.11', '192.168.56.10', False),
                                    ('192.168.56.11', '0.0.0.0', False), ('nonsense', '0.0.0.0', False)):
            with self.subTest(client=client, bound=bound):
                self.assertEqual(mine, server.on_this_machine(client, bound))


class Serve(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Main', document('screen', 'Main', Number=1))
        self.where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.where, True)
        patcher = mock.patch.dict(os.environ, {running.FOLDER_ENV: self.where})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_serve_keeps_its_record_while_it_listens_and_removes_it_when_it_stops(self):
        seen = []
        real = server.make_server

        def make(*a, **kw):
            httpd = real(*a, **kw)

            def until_stopped(*_):
                seen.extend(records(self.where))
                raise KeyboardInterrupt
            httpd.serve_forever = until_stopped
            return httpd
        with mock.patch.object(server, 'make_server', make):
            server.serve(self.repo.path, '0.0.0.0', 0, out=io.StringIO())
        self.assertEqual(1, len(seen))
        self.assertEqual((os.path.abspath(self.repo.path), os.getpid()), (seen[0]['repo'], seen[0]['pid']))
        self.assertRegex(seen[0]['url'], r'^http://127\.0\.0\.1:\d+/$')
        self.assertEqual([], records(self.where))

    def test_a_server_ended_by_stop_process_leaves_a_record_the_next_one_removes(self):
        """The pid of a record is the server's: the python.exe of a venv is a launcher with a pid of its own."""
        def start():
            p = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hmipreview', 'serve', self.repo.path, '--host',
                                  '127.0.0.1', '--port', '0'], cwd=PACKAGE_ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, encoding='utf-8')
            self.addCleanup(p.stdout.close)
            self.addCleanup(p.wait)
            url = p.stdout.readline().strip()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                mine = [r for r in records(self.where) if r['url'] == url]
                if mine:
                    self.addCleanup(stop, mine[0]['pid'])
                    return mine[0]['pid'], url
                time.sleep(0.05)
            self.fail('no record of %s' % url)

        def stop(pid):
            try:
                os.kill(pid, signal.SIGTERM)      # TerminateProcess, as Stop-Process
            except OSError:
                pass
            deadline = time.monotonic() + 10
            while running.is_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
        first = start()
        stop(first[0])
        self.assertEqual([first], [(r['pid'], r['url']) for r in records(self.where)])
        second = start()
        self.assertEqual([second], [(r['pid'], r['url']) for r in records(self.where)])

if __name__ == '__main__':
    unittest.main()
