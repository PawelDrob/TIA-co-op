"""The preview server runs with no console (serve --detach): every console program it starts, git and powershell among
them, would open a window of its own unless the call says not to. Here, not beside the dashboard's scan in
TiaAgentStatus\\tests (the same rule): the hook runs these tests when TiaHmiGenerator\\ changes, so a new call is read
on its own commit."""
import ast
import builtins
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HMIPREVIEW = TESTS.parent / 'hmipreview'
OTHER_SCAN = TESTS.parent.parent / 'TiaAgentStatus' / 'tests' / 'test_no_console.py'
# The calls whose flags this scan cannot read, by file and the function they are in, one call in each, with the test
# that reads them (its file in Tests\, class.method). server.detach's start(): its callers pass creationflags on Windows,
# start_new_session elsewhere. ends_on_close(creationflags): detach passes the flags it started the server with. The
# test's patch of subprocess.Popen sees both: subprocess.run calls it.
READER = ('test_server.py', 'ServeCommandTest.test_detach_opens_no_console_window')
FLAGS_READ_BY = {'server.py': {'start': READER, 'ends_on_close': READER}}
LISTED, READERS = HMIPREVIEW, TESTS     # where the list's files are, and its readers


# The rule: these constants, functions and tests are the same in the other scan, which a test of each checks.
RULE = ('RULE', 'rule_of', 'words', 'reads_flags', 'ASYNC_STARTS', 'STARTERS', 'NO_FLAGS', 'NO_WINDOW', 'takes_no_flags', 'dotted',
        'enclosing_function', 'assigned', 'binds', 'class_level', 'set_to', 'flag_names', 'not_read', 'other_names', 'console_starts', 'count_starts', 'RuleTest')


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
    """True when tree has the test class.method and its code names what a reader of the flags names: CREATE_NO_WINDOW
    and DETACHED_PROCESS as names, creationflags as a name or a string. Its docstring is no code."""
    def reads(method):
        code = [n for s in method.body[ast.get_docstring(method) is not None:] for n in ast.walk(s)]
        names = {getattr(n, 'id', None) or getattr(n, 'attr', None) for n in code}
        return {'CREATE_NO_WINDOW', 'DETACHED_PROCESS'} <= names and any('creationflags' in words(n) for n in code)
    cls, method = test.split('.')
    return any(reads(m) for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
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
    """{node: the innermost function it is in}: in its arguments or its body. A function's own node, its decorators
    and the defaults of its arguments are in the scope around it, where they run. ast.walk goes outside in, so an
    inner function overwrites."""
    inside = {}
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = f.args
            own = [x for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if x] + f.body
            inside.update((n, f) for part in own for n in ast.walk(part))
    return inside


def assigned(node):
    """What a statement sets to a value: its targets, none of any other node."""
    if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) or node.value is None:
        return []
    return getattr(node, 'targets', None) or [node.target]


def binds(node):
    """The name a node gives a value in the scope it stands in, None of a node that gives none: a name stored to, an
    argument, an import, a def or class, except ... as, a capture of match; del makes a name the scope's own too."""
    if isinstance(node, ast.Name):
        return None if isinstance(node.ctx, ast.Load) else node.id
    if isinstance(node, ast.alias):
        return node.asname or node.name.split('.')[0]
    if isinstance(node, ast.MatchMapping):
        return node.rest
    for kind, field in ((ast.arg, 'arg'), ((ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler,
                                            ast.MatchAs, ast.MatchStar), 'name')):
        if isinstance(node, kind):
            return getattr(node, field)
    return None


def class_level(tree, inside):
    """The nodes of each class body that run in it: not those in a method's arguments or body."""
    return {n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for s in c.body for n in ast.walk(s)
            if inside.get(n) is inside.get(c)}


def set_to(name, scope, inside, tree):
    """([(what name is set to, the scope that sets it)], whether those are all it can be) in the nearest scope that
    binds it: scope (the function a call is in, None for the module), then each function around it, then the module; a
    class body is no scope of its methods. Not all: the scope also binds it where this cannot read a value (binds, but
    for a plain assignment and import of a module; import *, and globals() in the file for the module, may bind any name
    but a builtin), or a global or nonlocal statement names it, and then every function's values count."""
    def sets(n):
        return any(isinstance(t, ast.Name) and t.id == name for t in assigned(n))
    nodes = list(ast.walk(tree))
    if any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names for n in nodes):
        return [(n.value, inside.get(n)) for n in nodes if sets(n)], False
    of_a_class = class_level(tree, inside)
    modules = {a for n in nodes if isinstance(n, ast.Import) for a in n.names}
    while True:
        here = [n for n in ast.walk(scope or tree) if inside.get(n) is scope and n not in of_a_class]
        values = [(n.value, scope) for n in here if sets(n)]
        bound = [n for n in here if binds(n) == name]
        any_name = any(binds(n) == '*' for n in here) or scope is None and any(getattr(n, 'id', None) == 'globals' for n in nodes)
        unread = sum(n not in modules for n in bound) > len(values) \
            or any_name and not hasattr(builtins, name) and not any(n in modules for n in bound)
        if bound or unread or scope is None:
            return values, not unread
        scope = inside.get(scope)


def flag_names(expr, node, inside, tree):
    """(the names in a creationflags expression of node, getattr's strings among them, and those in what a name in it is
    set to, each read in the scope it stands in; the names among them with a binding the scan cannot read: set_to).
    Not among the second: a name of the flag, which other_names holds to it, and the object of an attribute. In a class
    body no name is followed: it is the class's first, which set_to does not read, so each name the file binds is
    unread."""
    def bare(value):
        objects = {n.value for n in ast.walk(value) if isinstance(n, ast.Attribute)}
        return {n.id for n in ast.walk(value) if isinstance(n, ast.Name) and n not in objects} - set(NO_WINDOW)
    if node in class_level(tree, inside):
        bound = {binds(n) or getattr(n, 'id', None) == 'globals' and '*' for n in ast.walk(tree)}
        return set(words(expr)), {name for name in bare(expr) if name in bound or '*' in bound and not hasattr(builtins, name)}
    names, unread, all_read, todo = set(), set(), {}, [(expr, inside.get(node))]
    while todo:
        value, at = todo.pop()
        names.update(words(value))
        for name in sorted({n.id for n in ast.walk(value) if isinstance(n, ast.Name)}):
            if (name, at) not in all_read:
                values, all_read[name, at] = set_to(name, at, inside, tree)
                todo += values
            if not all_read[name, at] and name in bare(value):
                unread.add(name)
    return names, unread


def not_read(unread):
    return unread and ', with no name the scan cannot read in every binding (%s)' % ', '.join(sorted(unread)) or ''


def other_names(tree, inside):
    """(line, what is wrong) of each place that gives a module of the rule another name by assignment, or one of
    NO_WINDOW's names a value that is not the flag: set with = to what names CREATE_NO_WINDOW and never
    DETACHED_PROCESS, or imported from another file by that name."""
    readable = {t for n in ast.walk(tree) for t in assigned(n)}
    readable.update(a for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if not a.asname)
    for node in ast.walk(tree):
        targets = assigned(node)
        if targets and (dotted(node.value) in STARTERS or dotted(node.value) in NO_FLAGS):
            yield node.lineno, '%s under another name: the scan reads %s.<name>' % (dotted(node.value), dotted(node.value))
        elif any(getattr(t, 'id', None) in NO_WINDOW or getattr(t, 'attr', None) in NO_WINDOW for t in targets):
            names, unread = flag_names(node.value, node, inside, tree)
            if isinstance(node, ast.AugAssign) or unread or 'DETACHED_PROCESS' in names or 'CREATE_NO_WINDOW' not in names:
                yield node.lineno, '%s: a name of the flag is set with = to what names CREATE_NO_WINDOW and never ' \
                    'DETACHED_PROCESS%s' % (ast.unparse(node), not_read(unread))
        elif node not in readable and (binds(node) in NO_WINDOW or isinstance(node, ast.Attribute)
                                       and isinstance(node.ctx, ast.Store) and node.attr in NO_WINDOW):
            yield node.lineno, 'a name of the flag bound where the scan cannot read its value: set it to CREATE_NO_WINDOW'


def console_starts(tree, read_by=()):
    """(line, what is wrong) of each start of a program in tree that may open a console window. Its creationflags name
    NO_WINDOW or CREATE_NO_WINDOW, and never DETACHED_PROCESS, and hold no name the scan cannot read in every binding
    (flag_names); a name spelled like the flag is set to it (other_names).
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
                names, unread = flag_names(flags[0], node, inside, tree)
                if unread or 'DETACHED_PROCESS' in names or not names & set(NO_WINDOW):
                    yield node.lineno, '%s.%s with creationflags=%s: they name %s and never DETACHED_PROCESS%s, or a test reads ' \
                        'them (FLAGS_READ_BY)' % (module, name, ast.unparse(flags[0]), ' or '.join(NO_WINDOW), not_read(unread))
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
        tree = ast.parse('class T:\n    def test_reads(self):\n        %s\n    def test_starts(self):\n        server.detach()\n'
                         '    def test_says(self):\n        """creationflags: CREATE_NO_WINDOW, not DETACHED_PROCESS."""\n'
                         '        "creationflags", "CREATE_NO_WINDOW", "DETACHED_PROCESS"\n        server.detach()' % reads)
        self.assertTrue(reads_flags(tree, 'T.test_reads'))
        self.assertFalse(reads_flags(tree, 'T.test_starts'))
        self.assertFalse(reads_flags(tree, 'T.test_says'))     # its docstring and strings are no reading
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
        flag = 'NO_WINDOW = subprocess.CREATE_NO_WINDOW\n'
        for code in ('NO_WINDOW = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS', 'watch.NO_WINDOW = 0',
                     'def f(NO_WINDOW=0): pass', flag + 'NO_WINDOW |= subprocess.DETACHED_PROCESS', flag + 'NO_WINDOW &= 0',
                     flag + 'NO_WINDOW |= subprocess.CREATE_NEW_PROCESS_GROUP', 'NO_WINDOW |= 0', flag + 'watch.NO_WINDOW ^= NO_WINDOW',
                     'try: pass\nexcept E as NO_WINDOW: pass', 'def NO_WINDOW(): pass', 'class NO_WINDOW: pass', 'import NO_WINDOW',
                     'import NO_WINDOW.x', 'match m:\n    case {"f": NO_WINDOW}: pass', 'match m:\n    case [*CREATE_NO_WINDOW]: pass',
                     'match m:\n    case {**NO_WINDOW}: pass', 'w.NO_WINDOW, x = 0, 1', 'for w.NO_WINDOW in (0,): pass',
                     'with f() as w.NO_WINDOW: pass', '[w.CREATE_NO_WINDOW, *x] = 0, 1'):
            self.assertEqual([len(code.splitlines())], self.found(code), code)
        self.assertEqual([2], self.found('def f():\n    NO_WINDOW: int = 0'))
        for code in ('NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)', 'FLAG = subprocess.CREATE_NO_WINDOW\nNO_WINDOW = FLAG',
                     'from board import NO_WINDOW', 'from subprocess import CREATE_NO_WINDOW', 'match m:\n    case _: pass'):
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
        # a start in a class body: its names are the class's first, which this does not read
        self.assertEqual([4], self.found(module + 'class C:\n    flags = 0\n    p = subprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([3], self.found(module + 'class C:\n    p = subprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([], self.found('class C:\n    p = subprocess.Popen(a, creationflags=subprocess.CREATE_NO_WINDOW | NO_WINDOW)'))
        # a method below a statement of a class body is read like any other
        method = 'class C:\n    if True:\n        def spawn(self):\n            flags = %s\n        ' + start
        self.assertEqual([6], self.found(module + method % '0'))
        self.assertEqual([], self.found(method % 'subprocess.CREATE_NO_WINDOW'))
        self.assertEqual([6], self.found('class C:\n    try:\n        flags = subprocess.CREATE_NO_WINDOW\n    finally:\n'
                                         '        def spawn(self):\n        ' + start))
        # a name in what it is set to is read where that stands
        self.assertEqual([6], self.found('x = 0\ndef detach():\n    flags = x\n    def start():\n'
                                         '        x = subprocess.CREATE_NO_WINDOW\n    ' + start))

    def test_a_flags_name_bound_where_no_value_is_read_is_not_the_module_s(self):
        start = '    subprocess.Popen(a, creationflags=flags)'
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        self.assertEqual([3], self.found(module + 'def spawn(flags):\n' + start))
        self.assertEqual([4], self.found(module + 'def detach(*, flags=0):\n    def start():\n    ' + start))
        for bound in ('flags, x = 0, 1', 'for flags in (0,): pass', 'with f() as flags: pass', 'f(flags := 0)', 'from x import flags',
                      'import x as flags', 'flags = subprocess.CREATE_NO_WINDOW\n    flags, x = 0, 1', 'import flags.x', 'del flags',
                      'try: pass\n    except E as flags: pass', 'def flags(): pass', 'class flags: pass',
                      'match m:\n        case {"f": flags}: pass', 'match m:\n        case [*flags]: pass',
                      'match m:\n        case {**flags}: pass', 'match m:\n        case C() as flags: pass'):
            code = module + 'def spawn():\n    %s\n' % bound + start
            self.assertEqual([len(code.splitlines())], self.found(code), bound)
        self.assertEqual([2], self.found(module + 'spawn = lambda flags: subprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([4], self.found(module + 'from x import *\ndef spawn():\n' + start))     # it may bring a flags
        self.assertEqual([], self.found(module + 'from x import y\ndef spawn():\n' + start))
        self.assertEqual([6], self.found(module + 'def other():\n    global flags\n    flags = subprocess.DETACHED_PROCESS\n'
                                                  'def spawn():\n' + start))
        self.assertEqual([6], self.found('def detach():\n    flags = subprocess.CREATE_NO_WINDOW\n    def other():\n        nonlocal flags\n'
                                         '        flags = 0\n' + start))

    def test_a_name_not_read_in_every_binding_flags_the_call(self):
        """Whatever else the flags name: what the scan cannot read may be DETACHED_PROCESS."""
        start = 'subprocess.Popen(a, creationflags=flags | subprocess.CREATE_NO_WINDOW)'
        detached = 'flags = subprocess.DETACHED_PROCESS\n'
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        for code in ('def f(flags=None):\n    if flags is None:\n        flags = subprocess.DETACHED_PROCESS\n    ' + start,
                     'def f(extra=0):\n    extra = subprocess.DETACHED_PROCESS\n    flags = extra | subprocess.CREATE_NO_WINDOW\n'
                     '    subprocess.Popen(a, creationflags=flags)',
                     'def f():\n    ' + detached + '    subprocess.Popen(a, creationflags=flags | NO_WINDOW)\n    del flags',
                     'from json import *\n' + detached + start,
                     'def g():\n    global flags\ndef f():\n    ' + detached + '    ' + start,
                     'def g():\n    global flags\n    ' + detached + 'def f():\n    ' + start,
                     'def f():\n    ' + detached + '    def g():\n        nonlocal flags\n    ' + start,
                     'def f(flags):\n    ' + start, 'from x import flags\n' + start, 'for flags in (0,): pass\n' + start,
                     'class C:\n    ' + detached + '    p = ' + start, 'from x import *\nclass C:\n    p = ' + start,
                     'globals()["flags"] = 0\nclass C:\n    p = ' + start,
                     module + 'globals()["flags"] = 0\ndef f():\n    subprocess.Popen(a, creationflags=flags)',
                     module + 'def g():\n    globals().update(flags=0)\ndef f():\n    def h():\n        ' + start,
                     # a def's defaults and decorators run in the scope around it
                     module + 'class C:\n    flags = 0\n    def m(self, p=subprocess.Popen(a, creationflags=flags)): pass',
                     module + 'class C:\n    flags = 0\n    @d(subprocess.Popen(a, creationflags=flags))\n    def m(self): pass',
                     module + 'def g(x=(flags := 0)): pass\ndef f():\n    subprocess.Popen(a, creationflags=flags)',
                     'def f():\n    ' + detached + '    def g(p=' + start + '): pass'):
            self.assertEqual([n for n, line in enumerate(code.splitlines(), 1) if 'Popen' in line], self.found(code), code)
        for code in ('import subprocess\ndef f():\n    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)\n    ' + start,
                     'from board import NO_WINDOW\nsubprocess.run(a, creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)',
                     'import subprocess\nimport x as flags\nfrom json import *\nsubprocess.run(a, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))',
                     'def f(a, cwd):\n    flags = 0\n    ' + start,
                     # an attribute is no flags name: its object is not read, on main neither
                     'def f(o):\n    subprocess.run(a, creationflags=o.flags | subprocess.CREATE_NO_WINDOW)'):
            self.assertEqual([], self.found(code), code)

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


class NoConsoleScanTest(unittest.TestCase):
    def test_nothing_the_preview_runs_can_flash_a_console(self):
        calls = 0
        for f in sorted(HMIPREVIEW.rglob('*.py')):
            tree = ast.parse(f.read_text(encoding='utf-8'))
            calls += count_starts(tree)
            for line, what in console_starts(tree, FLAGS_READ_BY.get(f.relative_to(HMIPREVIEW).as_posix(), {})):
                self.fail('%s, line %d: %s' % (f.relative_to(HMIPREVIEW), line, what))
        self.assertGreaterEqual(calls, 7)     # the scan found the calls it is there to read


if __name__ == '__main__':
    unittest.main()
