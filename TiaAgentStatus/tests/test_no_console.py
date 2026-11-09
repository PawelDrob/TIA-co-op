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

# The calls whose flags this scan cannot read, by file and the function they are in, one call in each, with the test
# that reads them (its file in the repo, class.method). review_page.start_server: CREATE_NO_WINDOW on Windows, start_new_session
# elsewhere, in **flags.
FLAGS_READ_BY = {'tools/dashboard/review_page.py': {
    'start_server': ('tools/dashboard/tests/test_tray.py', 'NoConsoleTest.test_a_session_starts_the_server_with_no_console_window')}}
LISTED = READERS = REPO     # where the list's files are, and its readers
OTHER_SCAN = REPO / 'TiaHmiGenerator' / 'Tests' / 'test_no_console.py'


# The rule: these constants, functions and tests are the same in the other scan, which a test of each checks.
RULE = ('RULE', 'rule_of', 'words', 'reads_flags', 'ASYNC_STARTS', 'STARTERS', 'NO_FLAGS', 'NO_WINDOW', 'takes_no_flags', 'dotted',
        'enclosing_function', 'assigned', 'set_to', 'flag_names', 'other_names', 'console_starts', 'count_starts', 'RuleTest')


def rule_of(path):
    """{name: its code} of what of RULE the file at path has at its top level."""
    def name(n):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            return n.name
        return n.targets[0].id if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) else None
    return {name(n): ast.dump(n) for n in ast.parse(path.read_text(encoding='utf-8')).body if name(n) in RULE}


def words(node):
    """Each name, attribute name and string in node."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def reads_flags(tree, test):
    """True when tree has the test class.method and it names what a reader of the flags names: creationflags,
    CREATE_NO_WINDOW and DETACHED_PROCESS."""
    cls, method = test.split('.')
    return any({'creationflags', 'CREATE_NO_WINDOW', 'DETACHED_PROCESS'} <= set(words(m))
               for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
               for m in c.body if isinstance(m, ast.FunctionDef) and m.name == method)


ASYNC_STARTS = ('create_subprocess_exec', 'create_subprocess_shell')
STARTERS = {'subprocess': ('run', 'Popen', 'call', 'check_call', 'check_output'), 'asyncio': ASYNC_STARTS,
            'asyncio.subprocess': ASYNC_STARTS}
NO_FLAGS = {'subprocess': ('getoutput', 'getstatusoutput'), 'os': ('system', 'popen')}     # no way to pass the flag
NO_WINDOW = ('NO_WINDOW', 'CREATE_NO_WINDOW')     # names of the flag that gives a program a console no one sees


def takes_no_flags(module, name):
    return name in NO_FLAGS.get(module, ()) or (module == 'os' and name.startswith(('spawn', 'exec')))


def dotted(node):
    """'a.b' of a name or a chain of attributes on one, None of anything else."""
    if isinstance(node, ast.Name):
        return node.id
    head = dotted(node.value) if isinstance(node, ast.Attribute) else None
    return head and '%s.%s' % (head, node.attr)


def enclosing_function(tree):
    """{node: the innermost function it is in}, a function's own node in the one around it. ast.walk goes outside in,
    so an inner function overwrites."""
    inside = {}
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside.update((n, f) for n in ast.walk(f) if n is not f)
    return inside


def assigned(node):
    """What a statement sets to a value: its targets, none of any other node."""
    if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) or node.value is None:
        return []
    return getattr(node, 'targets', None) or [node.target]


def set_to(name, scope, inside, tree):
    """[(what name is set to, the scope that sets it)] of the nearest scope that binds it: scope (the function a call is
    in, None for the module), then each function around it, then the module; a class body is no scope of its methods.
    Nothing when a scope on the way binds it where this cannot read a value (an argument, a loop, with, an import,
    unpacking, :=), or when a global or nonlocal statement names it: another function sets it then."""
    if any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names for n in ast.walk(tree)):
        return []
    of_a_class = {n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for s in c.body
                  if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(s)}
    while True:
        here = [n for n in ast.walk(scope or tree) if inside.get(n) is scope and n not in of_a_class]
        values = [n.value for n in here if any(isinstance(t, ast.Name) and t.id == name for t in assigned(n))]
        bound = sum(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == name
                    or isinstance(n, ast.arg) and n.arg == name
                    or isinstance(n, ast.alias) and (n.asname or n.name) == name for n in here)
        if bound > len(values):
            return []
        if values or scope is None:
            return [(value, scope) for value in values]
        scope = inside.get(scope)


def flag_names(expr, scope, inside, tree):
    """The names in a creationflags expression, getattr's strings among them, and those in what a name in it is set
    to (set_to), each read in the scope it stands in."""
    names, followed, todo = set(), set(), [(expr, scope)]
    while todo:
        value, at = todo.pop()
        names.update(words(value))
        for n in ast.walk(value):
            if isinstance(n, ast.Name) and (n.id, at) not in followed:
                followed.add((n.id, at))
                todo += set_to(n.id, at, inside, tree)
    return names


def other_names(tree, inside):
    """(line, what is wrong) of each place that gives a module of the rule another name by assignment, or one of
    NO_WINDOW's names a value that is not the flag."""
    plain = {t for n in ast.walk(tree) for t in assigned(n)}
    for node in ast.walk(tree):
        targets = assigned(node)
        if targets and (dotted(node.value) in STARTERS or dotted(node.value) in NO_FLAGS):
            yield node.lineno, '%s under another name: the scan reads %s.<name>' % (dotted(node.value), dotted(node.value))
        elif any(getattr(t, 'id', None) in NO_WINDOW or getattr(t, 'attr', None) in NO_WINDOW for t in targets):
            names = flag_names(node.value, inside.get(node), inside, tree)
            if 'DETACHED_PROCESS' in names or not (isinstance(node, ast.AugAssign) or 'CREATE_NO_WINDOW' in names):
                yield node.lineno, '%s set to %s: it names CREATE_NO_WINDOW and never DETACHED_PROCESS' \
                    % (ast.unparse(targets[0]), ast.unparse(node.value))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in NO_WINDOW and node not in plain \
                or isinstance(node, ast.arg) and node.arg in NO_WINDOW or isinstance(node, ast.alias) and node.asname in NO_WINDOW:
            yield node.lineno, 'a name of the flag bound where the scan cannot read its value: set it to CREATE_NO_WINDOW'


def console_starts(tree, read_by=()):
    """(line, what is wrong) of each start of a program in tree that may open a console window. Its creationflags name
    NO_WINDOW or CREATE_NO_WINDOW, and never DETACHED_PROCESS; a name spelled so is set to the flag (other_names).
    read_by: the functions with one start whose flags, or **kw, a test reads (FLAGS_READ_BY)."""
    inside = enclosing_function(tree)
    yield from other_names(tree, inside)
    let_through = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and (a.name in STARTERS or a.name in NO_FLAGS):
                    yield node.lineno, '%s imported as %s: the scan reads %s.<name>' % (a.name, a.asname, a.name)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if any(a.name in STARTERS.get(node.module, ()) or takes_no_flags(node.module, a.name)
                   or '%s.%s' % (node.module, a.name) in STARTERS
                   or a.name == '*' and (node.module in STARTERS or node.module in NO_FLAGS) for a in node.names):
                yield node.lineno, 'a starter imported by name: import %s, and call %s.<name>' % (node.module, node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and dotted(node.func.value):
            module, name = dotted(node.func.value), node.func.attr
            function = inside.get(node)
            flags = [k.value for k in node.keywords if k.arg == 'creationflags']
            passes_kw = None in [k.arg for k in node.keywords]
            if takes_no_flags(module, name):
                yield node.lineno, '%s.%s takes no creationflags' % (module, name)
            elif name not in STARTERS.get(module, ()):
                continue
            elif (flags or passes_kw) and function is not None and function.name in read_by:
                if function.name in let_through:
                    yield node.lineno, 'a second %s.%s in %s: the list (FLAGS_READ_BY) lets one through' % (module, name, function.name)
                let_through.add(function.name)
            elif flags:
                names = flag_names(flags[0], function, inside, tree)
                if 'DETACHED_PROCESS' in names or not names & set(NO_WINDOW):
                    yield node.lineno, '%s.%s with creationflags=%s: they name %s and never DETACHED_PROCESS, or a test ' \
                        'reads them (FLAGS_READ_BY)' % (module, name, ast.unparse(flags[0]), ' or '.join(NO_WINDOW))
            elif passes_kw:
                yield node.lineno, '%s.%s with **kw: its flags are not read here (FLAGS_READ_BY)' % (module, name)
            else:
                yield node.lineno, '%s.%s with no creationflags' % (module, name)


def count_starts(tree):
    return sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in STARTERS.get(dotted(n.func.value), ()) for n in ast.walk(tree))


class RuleTest(unittest.TestCase):
    """The rule on code written here, and this scan's list (FLAGS_READ_BY: its files under LISTED, its readers under
    READERS) held to it."""

    def found(self, code, read_by=()):
        return sorted(line for line, _ in console_starts(ast.parse(code), read_by))

    def test_the_rule_is_the_one_of_the_other_scan(self):
        mine, other = rule_of(Path(__file__)), rule_of(OTHER_SCAN)
        self.assertEqual(sorted(RULE), sorted(mine))
        self.assertEqual([], [n for n in RULE if mine[n] != other.get(n)], OTHER_SCAN)

    def test_each_function_on_the_list_has_its_call(self):
        """A name in FLAGS_READ_BY that no longer has its call would let a new one through unread."""
        for rel, readers in FLAGS_READ_BY.items():
            tree = ast.parse((LISTED / rel).read_text(encoding='utf-8'))
            for name in readers:
                self.assertGreater(len(list(console_starts(tree, set(readers) - {name}))),
                                   len(list(console_starts(tree, readers))), '%s: %s' % (rel, name))

    def test_each_reader_on_the_list_reads_the_flags(self):
        for rel, readers in FLAGS_READ_BY.items():
            for name, (path, test) in readers.items():
                self.assertTrue(reads_flags(ast.parse((READERS / path).read_text(encoding='utf-8')), test),
                                '%s: %s is read by %s %s' % (rel, name, path, test))

    def test_a_reader_that_is_gone_or_reads_no_flags_is_seen(self):
        reads = "flags = started.call_args.kwargs['creationflags']\n        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)\n" \
                "        self.assertFalse(flags & subprocess.DETACHED_PROCESS)"
        tree = ast.parse('class T:\n    def test_reads(self):\n        %s\n    def test_starts(self):\n        server.detach()' % reads)
        self.assertTrue(reads_flags(tree, 'T.test_reads'))
        self.assertFalse(reads_flags(tree, 'T.test_starts'))
        self.assertFalse(reads_flags(tree, 'T.test_no_such_test'))
        self.assertFalse(reads_flags(tree, 'NoSuchClass.test_reads'))

    def test_the_scan_sees_what_it_is_there_for(self):
        code = '\n'.join(['import subprocess, os', 'import subprocess as sp', 'from subprocess import run',
                          'subprocess.run(["git"])', 'subprocess.run(["git"], creationflags=0)', 'subprocess.Popen(a, **kw)',
                          'subprocess.getoutput("git")', 'os.system("git")', 'os.spawnl(0, "git")',
                          'asyncio.create_subprocess_exec("git")', 'from asyncio import create_subprocess_shell',
                          'from os import spawnl', 'from os import execv', 'from os import path',
                          'def start(**kw):', '    subprocess.Popen(a, **kw)'])
        self.assertEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], self.found(code, read_by=('start',)))

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
            self.assertEqual(1, len(self.found(code)), code)
        for code in let_through:
            self.assertEqual([], self.found(code), code)

    def test_a_name_spelled_no_window_is_set_to_the_flag(self):
        start = '\nsubprocess.run(a, creationflags=NO_WINDOW)'
        for code in ('NO_WINDOW = 0', 'NO_WINDOW = subprocess.CREATE_NEW_PROCESS_GROUP', 'NO_WINDOW, x = 0, 1',
                     'for NO_WINDOW in (0,): pass', 'if (NO_WINDOW := 0): pass', 'from signal import SIGTERM as NO_WINDOW',
                     'CREATE_NO_WINDOW = 0', 'NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)\nNO_WINDOW = 0'):
            self.assertEqual([len(code.splitlines())], self.found(code + start), code)
        for code in ('NO_WINDOW = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS', 'watch.NO_WINDOW = 0',
                     'def f(NO_WINDOW=0): pass', 'NO_WINDOW = subprocess.CREATE_NO_WINDOW\nNO_WINDOW |= subprocess.DETACHED_PROCESS'):
            self.assertEqual([len(code.splitlines())], self.found(code), code)
        self.assertEqual([2], self.found('def f():\n    NO_WINDOW: int = 0'))
        for code in ('NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)', 'FLAG = subprocess.CREATE_NO_WINDOW\nNO_WINDOW = FLAG',
                     'from board import NO_WINDOW', 'NO_WINDOW = subprocess.CREATE_NO_WINDOW\nNO_WINDOW |= subprocess.CREATE_NEW_PROCESS_GROUP'):
            self.assertEqual([], self.found(code + start), code)

    def test_a_flags_name_is_read_in_the_nearest_scope_that_sets_it(self):
        start = '    subprocess.Popen(a, creationflags=flags)'
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        self.assertEqual([], self.found(module + 'def spawn():\n' + start))
        self.assertEqual([], self.found('def detach():\n    flags = subprocess.CREATE_NO_WINDOW\n    def start():\n    ' + start))
        # not what another function, or one inside this one, sets a name of its own to
        self.assertEqual([], self.found('def spawn():\n    flags = subprocess.CREATE_NO_WINDOW\n    def other():\n'
                                        '        flags = subprocess.DETACHED_PROCESS\n' + start))
        self.assertEqual([5], self.found('def spawn():\n    flags = 0\n    def other():\n'
                                         '        flags = subprocess.CREATE_NO_WINDOW\n' + start))
        self.assertEqual([4], self.found(module + 'def spawn():\n    flags = 0\n' + start))
        # nor a class's name of that spelling: a method reads the module's
        self.assertEqual([4], self.found('class C:\n    flags = subprocess.CREATE_NO_WINDOW\n    def spawn(self):\n    ' + start))
        # a name in what it is set to is read where that stands
        self.assertEqual([6], self.found('x = 0\ndef detach():\n    flags = x\n    def start():\n'
                                         '        x = subprocess.CREATE_NO_WINDOW\n    ' + start))

    def test_a_flags_name_bound_where_no_value_is_read_is_not_the_module_s(self):
        start = '    subprocess.Popen(a, creationflags=flags)'
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        self.assertEqual([3], self.found(module + 'def spawn(flags):\n' + start))
        self.assertEqual([4], self.found(module + 'def detach(*, flags=0):\n    def start():\n    ' + start))
        for bound in ('flags, x = 0, 1', 'for flags in (0,): pass', 'with f() as flags: pass', 'f(flags := 0)', 'from x import flags',
                      'import x as flags', 'flags = subprocess.CREATE_NO_WINDOW\n    flags, x = 0, 1'):
            code = module + 'def spawn():\n    %s\n' % bound + start
            self.assertEqual([len(code.splitlines())], self.found(code), bound)
        self.assertEqual([2], self.found(module + 'spawn = lambda flags: subprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([6], self.found(module + 'def other():\n    global flags\n    flags = subprocess.DETACHED_PROCESS\n'
                                                  'def spawn():\n' + start))
        self.assertEqual([6], self.found('def detach():\n    flags = subprocess.CREATE_NO_WINDOW\n    def other():\n        nonlocal flags\n'
                                         '        flags = 0\n' + start))

    def test_a_name_followed_twice_is_read_each_time(self):
        """A name spelled like an attribute already seen is still followed."""
        self.assertEqual([5], self.found('def spawn(o):\n    b = subprocess.DETACHED_PROCESS\n    c = b\n    x = o.b | c\n'
                                         '    subprocess.Popen(a, creationflags=x | NO_WINDOW)'))
        self.assertEqual([3], self.found('def spawn():\n    flags = flags | 1\n    subprocess.Popen(a, creationflags=flags)'))

    def test_asyncio_subprocess_is_seen(self):
        self.assertEqual([2], self.found('import asyncio.subprocess\nasyncio.subprocess.create_subprocess_exec("git")'))
        self.assertEqual([], self.found('asyncio.subprocess.create_subprocess_shell("git", creationflags=NO_WINDOW)'))
        for code in ('import asyncio.subprocess as sub', 'from asyncio import subprocess', 'from asyncio.subprocess import *',
                     'from asyncio.subprocess import create_subprocess_exec', 'sub = asyncio.subprocess'):
            self.assertEqual([1], self.found(code), code)
        self.assertEqual([], self.found('from .asyncio import subprocess'))
        self.assertEqual(2, count_starts(ast.parse('asyncio.subprocess.create_subprocess_exec("git")\nsubprocess.run(a)\nx.y.run(a)')))

    def test_a_module_of_the_rule_under_another_name_is_seen(self):
        for code in ('from subprocess import *', 'from os import *', 'run = subprocess', 'self.sub = os'):
            self.assertEqual([1], self.found(code), code)
        self.assertEqual([], self.found('from json import *\nx = y.subprocess'))

    def test_an_alias_of_each_module_of_the_rule_is_seen(self):
        for module in sorted(set(STARTERS) | set(NO_FLAGS)):
            self.assertEqual([1], self.found('import %s as m' % module), module)
        self.assertEqual([], self.found('import os.path as p\nimport json as j'))

    def test_the_list_lets_through_the_flags_a_test_reads(self):
        code = 'def ends_on_close(creationflags):\n    subprocess.run(a, creationflags=creationflags)\n' \
               'def start(**kw):\n    subprocess.Popen(a, **kw)\n' \
               'def other():\n    subprocess.run(a)'
        self.assertEqual([6], self.found(code, ('ends_on_close', 'start')))

    def test_the_list_lets_one_start_through_in_a_function(self):
        code = 'def start(**kw):\n    subprocess.Popen(a, **kw)\n    subprocess.run(b, **kw)\n    subprocess.run(c, creationflags=kw["f"])'
        self.assertEqual([3, 4], self.found(code, ('start',)))


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
