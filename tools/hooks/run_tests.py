"""A suite's tests in worker processes at once, for the hook; standard library only. It finds them as
`python -m unittest discover` does, with its options:

    <py> tools/hooks/run_tests.py -s <start folder> [-t <top folder>] [-p <pattern>] [-j <workers>]

Workers: -j, else PRE_COMMIT_WORKERS, else 6, no more than the cores. A class with setUpClass or tearDownClass goes whole
to one worker, any other test on its own, the biggest classes first. With one worker, one class or test, or a module
that does not import, the suite runs in this process as unittest runs it. The summary has unittest's lines (Ran, OK,
FAIL:, ERROR:, FAILED), which the hook reads.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import unittest

MARKER = '__RUN_TESTS_JSON__'


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _default_workers():
    env = os.environ.get('PRE_COMMIT_WORKERS', '').strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return min(6, os.cpu_count() or 1)


def _results_channel():
    """The worker's stdout as a handle of its own for the results, which no process a test starts inherits; stdout itself
    then goes to stderr. A child that outlives its test would else hold the pipe, and the reader would wait for it,
    after the worker itself ended."""
    sys.stdout.flush()
    channel = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n')     # os.dup: not inheritable
    os.dup2(2, 1)
    if os.name == 'nt':     # what a child gets for stdout=None
        import ctypes
        import msvcrt
        from ctypes import wintypes
        set_std_handle = ctypes.WinDLL('kernel32', use_last_error=True).SetStdHandle
        set_std_handle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        set_std_handle.restype = wintypes.BOOL
        if not set_std_handle(wintypes.DWORD(-11 & 0xFFFFFFFF), msvcrt.get_osfhandle(2)):     # STD_OUTPUT_HANDLE
            raise ctypes.WinError(ctypes.get_last_error())
    return channel


def _run_worker(top_dir):
    if top_dir not in sys.path:
        sys.path.insert(0, top_dir)
    results = _results_channel()
    loader = unittest.TestLoader()
    for line in sys.stdin:
        target = line.strip()
        if not target:
            continue
        result = unittest.TestResult()
        try:
            loader.loadTestsFromName(target).run(result)
        except BaseException:       # a name that does not load, or a test that ends the run (SystemExit): an error of it
            result.errors.append((target, traceback.format_exc()))
            result.testsRun = max(result.testsRun, 1)
        payload = {'ran': result.testsRun,
                   'failures': [[str(test), text] for test, text in result.failures],
                   'errors': [[str(test), text] for test, text in result.errors],
                   'skipped': len(result.skipped),
                   'expected_failures': len(result.expectedFailures),
                   'unexpected_successes': [str(test) for test in result.unexpectedSuccesses]}
        results.write('\n' + MARKER + json.dumps(payload) + '\n')
        results.flush()


def _run_parallel(targets, top_dir, workers):
    work = queue.Queue()
    for target in targets:
        work.put(target)
    results = []
    results_lock = threading.Lock()
    procs = []
    procs_lock = threading.Lock()
    worker_errors = []

    def worker_loop():
        proc = subprocess.Popen(
            [sys.executable, '-X', 'utf8', os.path.abspath(__file__), '--worker', '-t', top_dir],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        with procs_lock:
            procs.append(proc)
        try:
            while True:
                try:
                    target = work.get_nowait()
                except queue.Empty:
                    break
                try:
                    proc.stdin.write(target + '\n')
                    proc.stdin.flush()
                    result = None
                    for out_line in proc.stdout:
                        if out_line.startswith(MARKER):
                            result = json.loads(out_line[len(MARKER):])
                            break
                        elif out_line.strip():
                            sys.stderr.write(out_line)
                    if result is None:
                        code = proc.wait()
                        with results_lock:
                            worker_errors.append((target, f'worker exited early (code {code}) while running {target}\n'))
                        break
                    with results_lock:
                        results.append(result)
                finally:
                    work.task_done()
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    threads = [threading.Thread(target=worker_loop, daemon=True) for _ in range(min(workers, len(targets)))]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        with procs_lock:
            for proc in procs:
                try:
                    proc.kill()
                except OSError:
                    pass
        raise
    return results, worker_errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--start-directory', default='.')
    parser.add_argument('-t', '--top-level-directory', default='.')
    parser.add_argument('-p', '--pattern', default='test*.py')
    parser.add_argument('-j', '--jobs', type=int, default=0)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args(argv)

    top_dir = os.path.abspath(args.top_level_directory)
    if args.worker:
        _run_worker(top_dir)
        return 0

    if top_dir not in sys.path:
        sys.path.insert(0, top_dir)

    start = time.perf_counter()
    loader = unittest.TestLoader()
    suite = loader.discover(args.start_directory, pattern=args.pattern, top_level_dir=top_dir)

    counts = {}
    discovery_failures = []
    for test in _iter_tests(suite):
        cls = test.__class__
        if cls.__module__ == 'unittest.loader' and cls.__name__ == '_FailedTest':
            discovery_failures.append(test)
            continue
        has_cls_fixture = (
            cls.setUpClass.__func__ is not unittest.TestCase.setUpClass.__func__
            or cls.tearDownClass.__func__ is not unittest.TestCase.tearDownClass.__func__
        )
        if has_cls_fixture:
            key = f'{cls.__module__}.{cls.__qualname__}'
        else:
            key = f'{cls.__module__}.{cls.__qualname__}.{test._testMethodName}'
        counts[key] = counts.get(key, 0) + 1

    workers = args.jobs if args.jobs > 0 else _default_workers()

    if discovery_failures or workers <= 1 or len(counts) <= 1:
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() and result.testsRun > 0 else 1

    # the classes run whole first, the biggest first, as they take longest; then the tests run on their own
    targets = [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    results, worker_errors = _run_parallel(targets, top_dir, workers)
    elapsed = time.perf_counter() - start

    ran = sum(r['ran'] for r in results)
    skipped = sum(r['skipped'] for r in results)
    expected_failures = sum(r['expected_failures'] for r in results)
    failures = [item for r in results for item in r['failures']]
    errors = [item for r in results for item in r['errors']] + worker_errors
    unexpected_successes = [item for r in results for item in r['unexpected_successes']]

    out = sys.stderr
    for kind, items in (('ERROR', errors), ('FAIL', failures)):     # as unittest writes them
        for label, text in items:
            out.write('=' * 70 + '\n' + f'{kind}: {label}\n' + '-' * 70 + '\n' + text + ('' if text.endswith('\n') else '\n'))
    for label in unexpected_successes:
        out.write(f'UNEXPECTED SUCCESS: {label}\n')

    out.write('-' * 70 + '\n')
    out.write(f'Ran {ran} test{"" if ran == 1 else "s"} in {elapsed:.3f}s\n\n')
    ok = not failures and not errors and not unexpected_successes and ran > 0
    infos = []
    if failures:
        infos.append(f'failures={len(failures)}')
    if errors:
        infos.append(f'errors={len(errors)}')
    if skipped:
        infos.append(f'skipped={skipped}')
    if expected_failures:
        infos.append(f'expected failures={expected_failures}')
    if unexpected_successes:
        infos.append(f'unexpected successes={len(unexpected_successes)}')
    status = 'OK' if ok else 'FAILED'
    if infos:
        status += f' ({", ".join(infos)})'
    out.write(status + '\n')
    out.flush()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
