"""The preview server runs with no console (serve --detach): every console program it starts, git and powershell among
them, would open a window of its own unless the call says not to. Here, not beside the dashboard's scan in
TiaAgentStatus\\tests (the same rule): the hook runs these tests when TiaHmiGenerator\\ changes, so a new call is read
on its own commit."""
import ast
import unittest
from pathlib import Path

HMIPREVIEW = Path(__file__).resolve().parent.parent / 'hmipreview'
STARTERS = {'subprocess': ('run', 'Popen', 'call', 'check_call', 'check_output'),
            'asyncio': ('create_subprocess_exec', 'create_subprocess_shell')}
NO_FLAGS = {'subprocess': ('getoutput', 'getstatusoutput'), 'os': ('system', 'popen')}     # no way to pass the flag
# The calls whose flags come in **kw, by file and the function they are in, each named with the reader of its flags.
# server.detach's start(): its callers pass creationflags on Windows, start_new_session elsewhere; read by
# test_server.ServeCommandTest.test_detach_opens_no_console_window.
KW_READ = {'server.py': ('start',)}


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
    whose call with **kw is read elsewhere (KW_READ)."""
    inside = functions(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'subprocess' and a.asname:
                    yield node.lineno, 'subprocess imported as %s: the scan reads subprocess.<name>' % a.asname
        elif isinstance(node, ast.ImportFrom) \
                and any(a.name in STARTERS.get(node.module, ()) or takes_no_flags(node.module, a.name) for a in node.names):
            yield node.lineno, 'a starter imported by name: import %s, and call %s.<name>' % (node.module, node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            module, name = node.func.value.id, node.func.attr
            named = [k.arg for k in node.keywords]     # None: **kw
            if name in STARTERS.get(module, ()) and 'creationflags' not in named:
                if None not in named:
                    yield node.lineno, '%s.%s with no creationflags' % (module, name)
                elif inside.get(node) not in kw_read:
                    yield node.lineno, '%s.%s with **kw: its flags are not read here (KW_READ)' % (module, name)
            elif takes_no_flags(module, name):
                yield node.lineno, '%s.%s takes no creationflags' % (module, name)


def count_starts(tree):
    return sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
               and n.func.attr in STARTERS.get(n.func.value.id, ()) for n in ast.walk(tree))


class NoConsoleScanTest(unittest.TestCase):
    def test_nothing_the_preview_runs_can_flash_a_console(self):
        calls = 0
        for f in sorted(HMIPREVIEW.rglob('*.py')):
            tree = ast.parse(f.read_text(encoding='utf-8'))
            calls += count_starts(tree)
            for line, what in console_starts(tree, KW_READ.get(f.relative_to(HMIPREVIEW).as_posix(), ())):
                self.fail('%s, line %d: %s' % (f.relative_to(HMIPREVIEW), line, what))
        self.assertGreaterEqual(calls, 7)     # the scan found the calls it is there to read

    def test_each_call_let_through_with_kw_is_there(self):
        """A name in KW_READ that no longer has its call would let a new one through unread."""
        for rel, names in KW_READ.items():
            tree = ast.parse((HMIPREVIEW / rel).read_text(encoding='utf-8'))
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
                          'def start(**kw):', '    subprocess.Popen(a, **kw)'])
        self.assertEqual([2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13],
                         sorted(line for line, _ in console_starts(ast.parse(code), kw_read=('start',))))


if __name__ == '__main__':
    unittest.main()
