"""What keeps a dashboard with no console from flashing one, tells a person what stopped it, and names it on its icon's tooltip and menu. Here since the hook runs these tests
when TiaAgentStatus\\ or tools\\dashboard\\ changes: a new call in either folder is read on its own commit."""
import ast
import contextlib
import io
import runpy
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'tools' / 'dashboard'))

import tray  # noqa: E402

# The calls whose flags this scan cannot read, by file and the function they are in, each with the test that reads them
# (its file in the repo, class.method). review_page.start_server: CREATE_NO_WINDOW on Windows, start_new_session
# elsewhere, in **flags.
FLAGS_READ_BY = {'tools/dashboard/review_page.py': {
    'start_server': ('tools/dashboard/tests/test_tray.py', 'NoConsoleTest.test_a_session_starts_the_server_with_no_console_window')}}
OTHER_SCAN = REPO / 'TiaHmiGenerator' / 'Tests' / 'test_no_console.py'


# The rule: these constants and functions are the same in the other scan, which a test of each checks.
RULE = ('RULE', 'rule_of', 'has_test', 'STARTERS', 'NO_FLAGS', 'NO_WINDOW', 'takes_no_flags', 'enclosing_function',
        'flag_names', 'console_starts', 'count_starts')


def rule_of(path):
    """{name: its code} of what of RULE the file at path has at its top level."""
    def name(n):
        if isinstance(n, ast.FunctionDef):
            return n.name
        return n.targets[0].id if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) else None
    return {name(n): ast.dump(n) for n in ast.parse(path.read_text(encoding='utf-8')).body if name(n) in RULE}


def has_test(path, test):
    """True when the file at path has the test class.method."""
    cls, method = test.split('.')
    return any(isinstance(c, ast.ClassDef) and c.name == cls
               and any(isinstance(m, ast.FunctionDef) and m.name == method for m in c.body)
               for c in ast.parse(path.read_text(encoding='utf-8')).body)


STARTERS = {'subprocess': ('run', 'Popen', 'call', 'check_call', 'check_output'),
            'asyncio': ('create_subprocess_exec', 'create_subprocess_shell')}
NO_FLAGS = {'subprocess': ('getoutput', 'getstatusoutput'), 'os': ('system', 'popen')}     # no way to pass the flag
NO_WINDOW = ('NO_WINDOW', 'CREATE_NO_WINDOW')     # names of the flag that gives a program a console no one sees


def takes_no_flags(module, name):
    return name in NO_FLAGS.get(module, ()) or (module == 'os' and name.startswith(('spawn', 'exec')))


def enclosing_function(tree):
    """{node: the innermost function it is in}. ast.walk goes outside in, so an inner function overwrites."""
    inside = {}
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside.update((n, f) for n in ast.walk(f))
    return inside


def flag_names(expr, scope):
    """The names in a creationflags expression, getattr's strings among them, and those in what a name in it is set to
    in scope: the function the call is in, or the module."""
    names, todo = set(), [expr]
    while todo:
        for n in ast.walk(todo.pop()):
            if isinstance(n, ast.Name) and n.id not in names:
                names.add(n.id)
                todo += [a.value for a in ast.walk(scope) if isinstance(a, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                         and a.value is not None and any(isinstance(t, ast.Name) and t.id == n.id
                                                         for t in getattr(a, 'targets', [getattr(a, 'target', None)]))]
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                names.add(n.value)
    return names


def console_starts(tree, read_by=()):
    """(line, what is wrong) of each start of a program in tree that may open a console window. Its creationflags name
    NO_WINDOW or CREATE_NO_WINDOW, and never DETACHED_PROCESS. read_by: the functions whose flags, or **kw, a test reads
    (FLAGS_READ_BY)."""
    inside = enclosing_function(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and (a.name in STARTERS or a.name in NO_FLAGS):
                    yield node.lineno, '%s imported as %s: the scan reads %s.<name>' % (a.name, a.asname, a.name)
        elif isinstance(node, ast.ImportFrom) \
                and any(a.name in STARTERS.get(node.module, ()) or takes_no_flags(node.module, a.name) for a in node.names):
            yield node.lineno, 'a starter imported by name: import %s, and call %s.<name>' % (node.module, node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            module, name = node.func.value.id, node.func.attr
            function = inside.get(node)
            flags = [k.value for k in node.keywords if k.arg == 'creationflags']
            passes_kw = None in [k.arg for k in node.keywords]
            if takes_no_flags(module, name):
                yield node.lineno, '%s.%s takes no creationflags' % (module, name)
            elif name not in STARTERS.get(module, ()):
                continue
            elif (flags or passes_kw) and function is not None and function.name in read_by:
                continue
            elif flags:
                names = flag_names(flags[0], function or tree)
                if 'DETACHED_PROCESS' in names or not names & set(NO_WINDOW):
                    yield node.lineno, '%s.%s with creationflags=%s: they name %s and never DETACHED_PROCESS, or a test ' \
                        'reads them (FLAGS_READ_BY)' % (module, name, ast.unparse(flags[0]), ' or '.join(NO_WINDOW))
            elif passes_kw:
                yield node.lineno, '%s.%s with **kw: its flags are not read here (FLAGS_READ_BY)' % (module, name)
            else:
                yield node.lineno, '%s.%s with no creationflags' % (module, name)


def count_starts(tree):
    return sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
               and n.func.attr in STARTERS.get(n.func.value.id, ()) for n in ast.walk(tree))


def sources():
    """The code of both dashboards, subfolders too, without their tests: those run in a console."""
    for top in (REPO / 'TiaAgentStatus', REPO / 'tools' / 'dashboard'):
        yield from (f for f in sorted(top.rglob('*.py')) if 'tests' not in f.relative_to(top).parts)


class NoConsoleScanTest(unittest.TestCase):
    def test_nothing_a_dashboard_runs_can_flash_a_console(self):
        """With no console of its own, every console program a server starts would open a window."""
        calls = 0
        for f in sources():
            tree = ast.parse(f.read_text(encoding='utf-8'))
            calls += count_starts(tree)
            for line, what in console_starts(tree, FLAGS_READ_BY.get(f.relative_to(REPO).as_posix(), {})):
                self.fail(f'{f.relative_to(REPO)}, line {line}: {what}')
        self.assertGreaterEqual(calls, 4)     # the scan found the calls it is there to read

    def test_the_rule_is_the_one_of_the_other_scan(self):
        mine, other = rule_of(Path(__file__)), rule_of(OTHER_SCAN)
        self.assertEqual(sorted(RULE), sorted(mine))
        self.assertEqual([], [n for n in RULE if mine[n] != other.get(n)], OTHER_SCAN)

    def test_each_function_on_the_list_has_its_call(self):
        """A name in FLAGS_READ_BY that no longer has its call would let a new one through unread."""
        for rel, readers in FLAGS_READ_BY.items():
            tree = ast.parse((REPO / rel).read_text(encoding='utf-8'))
            for name in readers:
                self.assertGreater(len(list(console_starts(tree, set(readers) - {name}))),
                                   len(list(console_starts(tree, readers))), f'{rel}: {name}')

    def test_each_reader_on_the_list_is_there(self):
        for rel, readers in FLAGS_READ_BY.items():
            for name, (path, test) in readers.items():
                self.assertTrue(has_test(REPO / path, test), f'{rel}: {name} is read by {path} {test}')

    def test_a_reader_that_is_gone_is_seen(self):
        path, test = FLAGS_READ_BY['tools/dashboard/review_page.py']['start_server']
        cls, method = test.split('.')
        self.assertTrue(has_test(REPO / path, test))
        self.assertFalse(has_test(REPO / path, cls + '.test_no_such_test'))
        self.assertFalse(has_test(REPO / path, 'NoSuchClass.' + method))

    def test_the_scan_sees_what_it_is_there_for(self):
        code = '\n'.join(['import subprocess, os', 'import subprocess as sp', 'from subprocess import run',
                          'subprocess.run(["git"])', 'subprocess.run(["git"], creationflags=0)', 'subprocess.Popen(a, **kw)',
                          'subprocess.getoutput("git")', 'os.system("git")', 'os.spawnl(0, "git")',
                          'asyncio.create_subprocess_exec("git")', 'from asyncio import create_subprocess_shell',
                          'from os import spawnl', 'from os import execv', 'from os import path',
                          'def start_server(**kw):', '    subprocess.Popen(a, **kw)'])
        self.assertEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                         sorted(line for line, _ in console_starts(ast.parse(code), read_by=('start_server',))))

    def test_the_flags_name_no_window_and_never_detached_process(self):
        flagged = ['subprocess.run(a, creationflags=0)',
                   'subprocess.Popen(a, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)',
                   'subprocess.Popen(a, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | NO_WINDOW)',
                   'def spawn():\n    flags = getattr(subprocess, "DETACHED_PROCESS", 0)\n    flags |= NO_WINDOW\n'
                   '    subprocess.Popen(a, creationflags=flags)',
                   'def ends_on_close(creationflags):\n    subprocess.run(a, creationflags=creationflags)']
        let_through = ['subprocess.run(a, creationflags=NO_WINDOW)', 'subprocess.run(a, creationflags=watch.NO_WINDOW)',
                       'subprocess.run(a, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))',
                       'def spawn():\n    flags = subprocess.CREATE_NEW_PROCESS_GROUP\n    flags |= subprocess.CREATE_NO_WINDOW\n'
                       '    subprocess.Popen(a, creationflags=flags)']
        for code in flagged:
            self.assertEqual(1, len(list(console_starts(ast.parse(code)))), code)
        for code in let_through:
            self.assertEqual([], list(console_starts(ast.parse(code))), code)

    def test_an_alias_of_each_module_of_the_rule_is_seen(self):
        for module in sorted(set(STARTERS) | set(NO_FLAGS)):
            self.assertEqual(1, len(list(console_starts(ast.parse(f'import {module} as m')))), module)
        self.assertEqual([], list(console_starts(ast.parse('import os.path as p\nimport json as j'))))

    def test_the_list_lets_through_the_flags_a_test_reads(self):
        code = ast.parse('def ends_on_close(creationflags):\n    subprocess.run(a, creationflags=creationflags)\n'
                         'def start(**kw):\n    subprocess.Popen(a, **kw)\n'
                         'def other():\n    subprocess.run(a)')
        self.assertEqual([6], [line for line, _ in console_starts(code, ('ends_on_close', 'start'))])


class NameInTooltipAndMenuTest(unittest.TestCase):
    """What the tooltip and the menu call each dashboard: the letter on the icon alone cannot say whose it is."""

    def named(self, start):
        with mock.patch.object(tray, 'serve') as serve, contextlib.redirect_stdout(io.StringIO()):
            start()
        return serve.call_args.args[1]

    def test_the_development_dashboard(self):
        import review_server
        # patch.multiple with their own values: main() sets these globals, and this puts them back
        with tempfile.TemporaryDirectory() as root, mock.patch.object(sys, 'argv', ['review_server', '--root', root]), \
                mock.patch.object(review_server.live, 'Server'), \
                mock.patch.multiple(review_server, SCRATCH=review_server.SCRATCH, ROOT=review_server.ROOT, ANSWERS=review_server.ANSWERS):
            self.assertEqual(self.named(review_server.main), 'TIA-co-op: development dashboard')

    def test_the_tia_dashboard(self):
        from TiaAgentStatus import dashboard
        with mock.patch.object(dashboard, 'Dashboard'), mock.patch.object(dashboard, 'make_server'), mock.patch.object(dashboard, 'threading'), \
                mock.patch('TiaAgentStatus.procs.WinProcesses'):
            name = self.named(lambda: dashboard.main(Namespace(root=Path('.'), quiet_minutes=1, port=1, every=1.0)))
        self.assertEqual(name, 'TIA-co-op: TIA dashboard')


class WrongOptionTest(unittest.TestCase):
    def start(self, *argv):
        """TiaAgentStatus as started from its folder; returns its exit code and the box."""
        with mock.patch.object(sys, 'argv', ['TiaAgentStatus', *argv]), mock.patch.object(tray, 'show_box') as box:
            try:
                runpy.run_path(str(REPO / 'TiaAgentStatus' / '__main__.py'), run_name='__main__')
            except SystemExit as e:
                return e.code, box
        self.fail('it did not end')

    def test_with_no_console_a_wrong_option_comes_up_in_a_box(self):
        with mock.patch.object(sys, 'stderr', None), mock.patch.object(sys, 'stdout', None):     # pythonw has neither
            code, box = self.start('dashboard', '--no-such-option')
        self.assertEqual(code, 1)
        self.assertIn('python.exe', box.call_args[0][1])

    def test_with_a_console_it_says_so_there_and_opens_no_box(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, box = self.start('dashboard', '--no-such-option')
        self.assertEqual(code, 2)
        self.assertIn('--no-such-option', err.getvalue())
        box.assert_not_called()


if __name__ == '__main__':
    unittest.main()
