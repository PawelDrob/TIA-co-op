"""The preview server runs with no console (serve --detach): every console program it starts, git and powershell among
them, would open a window of its own unless the call says not to. Here, not beside the dashboard's scan in
TiaAgentStatus\\tests (the same rule): the hook runs these tests when TiaHmiGenerator\\ changes, so a new call is read
on its own commit."""
import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HMIPREVIEW = TESTS.parent / 'hmipreview'
OTHER_SCAN = TESTS.parent.parent / 'TiaAgentStatus' / 'tests' / 'test_no_console.py'
# The calls whose flags this scan cannot read, by file and the function they are in, each with the test that reads them
# (its file in Tests\, class.method). server.detach's start(): its callers pass creationflags on Windows,
# start_new_session elsewhere. ends_on_close(creationflags): detach passes the flags it started the server with. The
# test's patch of subprocess.Popen sees both: subprocess.run calls it.
READER = ('test_server.py', 'ServeCommandTest.test_detach_opens_no_console_window')
FLAGS_READ_BY = {'server.py': {'start': READER, 'ends_on_close': READER}}


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


class NoConsoleScanTest(unittest.TestCase):
    def test_nothing_the_preview_runs_can_flash_a_console(self):
        calls = 0
        for f in sorted(HMIPREVIEW.rglob('*.py')):
            tree = ast.parse(f.read_text(encoding='utf-8'))
            calls += count_starts(tree)
            for line, what in console_starts(tree, FLAGS_READ_BY.get(f.relative_to(HMIPREVIEW).as_posix(), {})):
                self.fail('%s, line %d: %s' % (f.relative_to(HMIPREVIEW), line, what))
        self.assertGreaterEqual(calls, 7)     # the scan found the calls it is there to read

    def test_the_rule_is_the_one_of_the_other_scan(self):
        mine, other = rule_of(Path(__file__)), rule_of(OTHER_SCAN)
        self.assertEqual(sorted(RULE), sorted(mine))
        self.assertEqual([], [n for n in RULE if mine[n] != other.get(n)], OTHER_SCAN)

    def test_each_function_on_the_list_has_its_call(self):
        """A name in FLAGS_READ_BY that no longer has its call would let a new one through unread."""
        for rel, readers in FLAGS_READ_BY.items():
            tree = ast.parse((HMIPREVIEW / rel).read_text(encoding='utf-8'))
            for name in readers:
                self.assertGreater(len(list(console_starts(tree, set(readers) - {name}))),
                                   len(list(console_starts(tree, readers))), '%s: %s' % (rel, name))

    def test_each_reader_on_the_list_is_there(self):
        for rel, readers in FLAGS_READ_BY.items():
            for name, (path, test) in readers.items():
                self.assertTrue(has_test(TESTS / path, test), '%s: %s is read by %s %s' % (rel, name, path, test))

    def test_a_reader_that_is_gone_is_seen(self):
        path, test = READER
        cls, method = test.split('.')
        self.assertTrue(has_test(TESTS / path, test))
        self.assertFalse(has_test(TESTS / path, cls + '.test_no_such_test'))
        self.assertFalse(has_test(TESTS / path, 'NoSuchClass.' + method))

    def test_the_scan_sees_what_it_is_there_for(self):
        code = '\n'.join(['import subprocess, os', 'import subprocess as sp', 'from subprocess import run',
                          'subprocess.run(["git"])', 'subprocess.run(["git"], creationflags=0)', 'subprocess.Popen(a, **kw)',
                          'subprocess.getoutput("git")', 'os.system("git")', 'os.spawnl(0, "git")',
                          'asyncio.create_subprocess_exec("git")', 'from asyncio import create_subprocess_shell',
                          'from os import spawnl', 'from os import execv', 'from os import path',
                          'def start(**kw):', '    subprocess.Popen(a, **kw)'])
        self.assertEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                         sorted(line for line, _ in console_starts(ast.parse(code), read_by=('start',))))

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
            self.assertEqual(1, len(list(console_starts(ast.parse('import %s as m' % module)))), module)
        self.assertEqual([], list(console_starts(ast.parse('import os.path as p\nimport json as j'))))

    def test_the_list_lets_through_the_flags_a_test_reads(self):
        code = ast.parse('def ends_on_close(creationflags):\n    subprocess.run(a, creationflags=creationflags)\n'
                         'def start(**kw):\n    subprocess.Popen(a, **kw)\n'
                         'def other():\n    subprocess.run(a)')
        self.assertEqual([6], [line for line, _ in console_starts(code, ('ends_on_close', 'start'))])


if __name__ == '__main__':
    unittest.main()
