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

STARTERS = {'subprocess': ('run', 'Popen', 'call', 'check_call', 'check_output'),
            'asyncio': ('create_subprocess_exec', 'create_subprocess_shell')}
NO_FLAGS = {'subprocess': ('getoutput', 'getstatusoutput'), 'os': ('system', 'popen')}     # no way to pass the flag
# The calls whose flags come in **kw, by file and the function they are in, each named with the reader of its flags.
# review_page.start_server: CREATE_NO_WINDOW on Windows, start_new_session elsewhere; read by
# test_tray.NoConsoleTest.test_a_session_starts_the_server_with_no_console_window.
KW_READ = {'tools/dashboard/review_page.py': ('start_server',)}


def takes_no_flags(module, name):
    return name in NO_FLAGS.get(module, ()) or (module == 'os' and name.startswith(('spawn', 'exec')))


def functions(tree):
    """{node: name of the innermost function it is in}. ast.walk goes outside in, so an inner function overwrites."""
    inside = {}
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside.update((n, f.name) for n in ast.walk(f))
    return inside


def console_starts(tree, kw_read=()):
    """(line, what is wrong) of each start of a program in tree that may open a console window. kw_read: the functions
    whose call with **kw is read elsewhere (KW_READ). The same rule reads hmipreview in
    TiaHmiGenerator\\Tests\\test_no_console.py."""
    inside = functions(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'subprocess' and a.asname:
                    yield node.lineno, f'subprocess imported as {a.asname}: the scan reads subprocess.<name>'
        elif isinstance(node, ast.ImportFrom) \
                and any(a.name in STARTERS.get(node.module, ()) or takes_no_flags(node.module, a.name) for a in node.names):
            yield node.lineno, f'a starter imported by name: import {node.module}, and call {node.module}.<name>'
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            module, name = node.func.value.id, node.func.attr
            named = [k.arg for k in node.keywords]     # None: **kw
            if name in STARTERS.get(module, ()) and 'creationflags' not in named:
                if None not in named:
                    yield node.lineno, f'{module}.{name} with no creationflags'
                elif inside.get(node) not in kw_read:
                    yield node.lineno, f'{module}.{name} with **kw: its flags are not read here (KW_READ)'
            elif takes_no_flags(module, name):
                yield node.lineno, f'{module}.{name} takes no creationflags'


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
            for line, what in console_starts(tree, KW_READ.get(f.relative_to(REPO).as_posix(), ())):
                self.fail(f'{f.relative_to(REPO)}, line {line}: {what}')
        self.assertGreaterEqual(calls, 4)     # the scan found the calls it is there to read

    def test_each_call_let_through_with_kw_is_there(self):
        """A name in KW_READ that no longer has its call would let a new one through unread."""
        for rel, names in KW_READ.items():
            tree = ast.parse((REPO / rel).read_text(encoding='utf-8'))
            inside = functions(tree)
            found = {inside.get(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and None in [k.arg for k in n.keywords]
                     and isinstance(n.func, ast.Attribute) and n.func.attr in STARTERS['subprocess']}
            self.assertEqual(set(names), found & set(names), rel)

    def test_the_scan_sees_what_it_is_there_for(self):
        code = '\n'.join(['import subprocess, os', 'import subprocess as sp', 'from subprocess import run',
                          'subprocess.run(["git"])', 'subprocess.run(["git"], creationflags=0)', 'subprocess.Popen(a, **kw)',
                          'subprocess.getoutput("git")', 'os.system("git")', 'os.spawnl(0, "git")',
                          'asyncio.create_subprocess_exec("git")', 'from asyncio import create_subprocess_shell',
                          'from os import spawnl', 'from os import execv', 'from os import path',
                          'def start_server(**kw):', '    subprocess.Popen(a, **kw)'])
        self.assertEqual([2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13],
                         sorted(line for line, _ in console_starts(ast.parse(code), kw_read=('start_server',))))


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
            self.assertEqual(self.named(review_server.main), 'Tia co-op: development dashboard')

    def test_the_tia_dashboard(self):
        from TiaAgentStatus import dashboard
        with mock.patch.object(dashboard, 'Dashboard'), mock.patch.object(dashboard, 'make_server'), mock.patch.object(dashboard, 'threading'), \
                mock.patch('TiaAgentStatus.procs.WinProcesses'):
            name = self.named(lambda: dashboard.main(Namespace(root=Path('.'), quiet_minutes=1, port=1, every=1.0)))
        self.assertEqual(name, 'Tia co-op: TIA dashboard')


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
