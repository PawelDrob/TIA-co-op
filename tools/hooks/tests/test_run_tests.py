"""tools/hooks/run_tests.py on made-up suites: tests in two workers, a class with setUpClass in one, failures and errors as
unittest writes them, a module that does not import, a worker that dies."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / 'run_tests.py'


def run_runner(folder, *extra):
    """The runner on folder, its output into files as the hook's logs: a pipe would wait on a child a test left."""
    out, err = Path(folder) / 'out.txt', Path(folder) / 'err.txt'
    with out.open('w', encoding='utf-8') as o, err.open('w', encoding='utf-8') as e:
        code = subprocess.run([sys.executable, '-X', 'utf8', str(RUNNER), '-s', str(folder), '-t', str(folder), *extra],
                              stdout=o, stderr=e, timeout=60).returncode
    return subprocess.CompletedProcess([], code, out.read_text(encoding='utf-8'), err.read_text(encoding='utf-8'))


class ParallelRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='run-tests-')
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def put(self, name, body):
        (self.dir / name).write_text(body, encoding='utf-8')

    def test_runs_passing_classes_in_parallel_and_keeps_setupclass_once(self):
        self.put('test_sample.py', '''import unittest
from pathlib import Path

LOG = Path(%r)


class Plain(unittest.TestCase):
    def test_a(self):
        self.assertEqual(1 + 1, 2)

    def test_b(self):
        self.assertEqual(2 + 2, 4)


class Shared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with LOG.open('a', encoding='utf-8') as f:
            f.write('setup\\n')
        cls.value = 42

    def test_one(self):
        self.assertEqual(self.value, 42)

    def test_two(self):
        self.assertEqual(self.value, 42)
''' % str(self.dir / 'cls.log'))
        r = run_runner(self.dir, '-j', '2')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Ran 4 tests in ', r.stderr)
        self.assertIn('\nOK\n', r.stderr)
        self.assertEqual((self.dir / 'cls.log').read_text(encoding='utf-8').splitlines(), ['setup'])

    def test_reports_failures_and_errors_in_unittest_format(self):
        self.put('test_bad.py', '''import unittest


class Bad(unittest.TestCase):
    def test_ok(self):
        pass

    def test_fail(self):
        self.assertEqual(1, 2)

    def test_err(self):
        raise RuntimeError('boom')
''')
        r = run_runner(self.dir, '-j', '2')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAIL: test_fail ', r.stderr)
        self.assertIn('ERROR: test_err ', r.stderr)
        self.assertIn('Ran 3 tests in ', r.stderr)
        self.assertIn('FAILED (failures=1, errors=1)', r.stderr)

    def test_a_worker_that_dies_ends_the_run_though_a_child_of_its_test_lives_on(self):
        pid = self.dir / 'child.pid'
        self.put('test_dies.py', '''import os
import subprocess
import sys
import unittest


class Dies(unittest.TestCase):
    def test(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])     # stdout as the worker's
        with open(%r, 'w') as f:
            f.write(str(child.pid))
        os._exit(3)


class Lives(unittest.TestCase):
    def test(self):
        pass
''' % str(pid))
        try:
            r = run_runner(self.dir, '-j', '2')
        finally:
            if pid.exists():
                subprocess.run(['taskkill', '/F', '/PID', pid.read_text()], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('worker exited early (code 3) while running test_dies.Dies.test', r.stderr)

    def test_import_error_during_discovery_fails(self):
        self.put('test_broken.py', 'import no_such_module_xyz_123\n')
        r = run_runner(self.dir, '-j', '2')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no_such_module_xyz_123', r.stderr)
