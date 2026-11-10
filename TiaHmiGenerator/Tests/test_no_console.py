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
RULE = ('RULE', 'rule_of', 'names_and_strings', 'reads_flags', 'ASYNC_STARTS', 'STARTERS', 'NO_FLAGS', 'THE_FLAG', 'NO_WINDOW',
        'DETACHED', 'takes_no_flags', 'dotted', 'enclosing_function', 'assigned', 'binds', 'binds_any_name', 'unseen_binding', 'stores_the_flag',
        'class_body_nodes', 'values_of', 'pooled_names', 'flag_names', 'not_the_flag', 'unread_note', 'other_names', 'read_as_values',
        'console_starts', 'count_starts', 'RuleTest')


def rule_of(path):
    """{name: its code} of what of RULE the file at path has at its top level."""
    def name(n):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            return n.name
        return n.targets[0].id if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) else None
    return {name(n): ast.dump(n) for n in ast.parse(path.read_text(encoding='utf-8')).body if name(n) in RULE}


def names_and_strings(node):
    """Each name, attribute name and string in node."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


ASYNC_STARTS = ('create_subprocess_exec', 'create_subprocess_shell')
STARTERS = {'subprocess': ('run', 'Popen', 'call', 'check_call', 'check_output'), 'asyncio': ASYNC_STARTS,
            'asyncio.subprocess': ASYNC_STARTS}
NO_FLAGS = {'subprocess': ('getoutput', 'getstatusoutput'), 'os': ('system', 'popen')}     # no way to pass the flag
THE_FLAG = 'CREATE_NO_WINDOW'     # gives a program a console no one sees
NO_WINDOW = ('NO_WINDOW', THE_FLAG)     # the names code gives the flag
DETACHED = 'DETACHED_PROCESS'     # the flag that gives a program no console: each console program it starts opens one


def reads_flags(tree, test):
    """True when tree has the test class.method and its code names what a reader of the flags names: CREATE_NO_WINDOW
    and DETACHED_PROCESS as names, creationflags as a name or a string. Its docstring is no code."""
    def reads(method):
        code = [n for s in method.body[ast.get_docstring(method) is not None:] for n in ast.walk(s)]
        names = {getattr(n, 'id', None) or getattr(n, 'attr', None) for n in code}
        return {THE_FLAG, DETACHED} <= names and any('creationflags' in names_and_strings(n) for n in code)
    cls, method = test.split('.')
    return any(reads(m) for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
               for m in c.body if isinstance(m, ast.FunctionDef) and m.name == method)


def takes_no_flags(module, name):
    return name in NO_FLAGS.get(module, ()) or (module == 'os' and name.startswith(('spawn', 'exec')))


def dotted(node):
    """'a.b' of a name or a chain of attributes on one, None of anything else."""
    if isinstance(node, ast.Name):
        return node.id
    head = dotted(node.value) if isinstance(node, ast.Attribute) else None
    return head and '%s.%s' % (head, node.attr)


def enclosing_function(tree, written=False):
    """{node: the innermost function it runs in}: its arguments and its body. A function's own node, its decorators,
    and the defaults and annotations of its arguments run in the scope around it. With written, {node: the innermost
    function it is written in}: a decorator, default or annotation then counts as its def's, and only the def's own
    node as the scope's around. ast.walk goes outside in, so an inner function overwrites."""
    inside = {}
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = f.args
            inside.update((x, f) for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if x)
            inside.update((n, f) for part in ([f] if written else f.body) for n in ast.walk(part) if n is not f)
    return inside


def assigned(node):
    """What a statement sets to a value: its targets, none of any other node."""
    if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) or node.value is None:
        return []
    return getattr(node, 'targets', None) or [node.target]


def binds(node):
    """The name a node gives a value in the scope it stands in, None of a node that gives none: a name stored to, an
    argument, an import, a def or class, except ... as, a capture of match, a type parameter; del makes a name the
    scope's own too. Of the * of from x import * it is '*', as ast names it: no name, and any (binds_any_name)."""
    if isinstance(node, ast.Name):
        return None if isinstance(node.ctx, ast.Load) else node.id
    if isinstance(node, ast.alias):
        return node.asname or node.name.split('.')[0]
    if isinstance(node, ast.MatchMapping):
        return node.rest
    for kind, field in ((ast.arg, 'arg'), ((ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler,
                                            ast.MatchAs, ast.MatchStar, ast.TypeVar, ast.TypeVarTuple, ast.ParamSpec), 'name')):
        if isinstance(node, kind):
            return getattr(node, field)
    return None


def binds_any_name(node):
    """True of import *, and of globals under any spelling the file gives it: either may bind any name of a module."""
    return binds(node) == '*' or 'globals' in (getattr(node, 'id', None), getattr(node, 'attr', None), getattr(node, 'name', None))


def unseen_binding(name, nodes):
    """True when import * or globals among nodes may bind name: any name but a builtin."""
    return not hasattr(builtins, name) and any(binds_any_name(n) for n in nodes)


def stores_the_flag(node):
    """True of a node that binds one of NO_WINDOW's names, or stores to an attribute spelled like one."""
    return binds(node) in NO_WINDOW or isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and node.attr in NO_WINDOW


def class_body_nodes(tree, inside):
    """The nodes of each class body that run in it: not those in a method's arguments or body."""
    return {n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for s in c.body for n in ast.walk(s)
            if inside.get(n) is inside.get(c)}


def values_of(name, scope, inside, tree):
    """([(what name is set to in scope, scope)], whether those are all it can be there). scope: the function a start is
    in, None for the module; a class body is no scope of its methods. Not all, when:
    - scope also binds it where this cannot read a value (binds, but for a plain assignment and import of a module);
    - import * or globals in scope, for the module globals anywhere in the file, may bind it: any name but a builtin
      or one scope imports as a module. Strict for a function, whose own names globals does not reach;
    - a global or nonlocal statement names it, and then every function's values count;
    - scope is a function that does not bind it, and the file binds it elsewhere, other than by the import of a
      module, or may (import *, globals): a name of a scope around is not followed, as it can be set there in ways
      no reading of one file sees."""
    def sets(n):
        return any(isinstance(t, ast.Name) and t.id == name for t in assigned(n))
    nodes = list(ast.walk(tree))
    if any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names for n in nodes):
        return [(n.value, inside.get(n)) for n in nodes if sets(n)], False
    in_class_body = class_body_nodes(tree, inside)
    module_imports = {a for n in nodes if isinstance(n, ast.Import) for a in n.names}
    here = [n for n in nodes if inside.get(n) is scope and n not in in_class_body]
    values = [(n.value, scope) for n in here if sets(n)]
    binders = [n for n in here if binds(n) == name]
    if scope is not None and not binders:
        around = [n for n in nodes if binds(n) == name]
        return [], not (any(n not in module_imports for n in around) or not around and unseen_binding(name, nodes))
    some_unread = sum(n not in module_imports for n in binders) > len(values) \
        or not any(n in module_imports for n in binders) and unseen_binding(name, here if scope is not None else nodes)
    return values, not some_unread


def pooled_names(expr, scope):
    """The names in expr and in what any assignment written in scope sets a name in it to, whichever function or class
    of scope it stands in: scope is the function a start is written in, or the file. No scope stops this reading, so
    it finds a name set in a function or class inside, where values_of reads the one scope of the start."""
    names, followed, todo = set(), set(), [expr]
    while todo:
        value = todo.pop()
        names.update(names_and_strings(value))
        for name in sorted({n.id for n in ast.walk(value) if isinstance(n, ast.Name)} - followed):
            followed.add(name)
            todo += [a.value for a in ast.walk(scope) if any(isinstance(t, ast.Name) and t.id == name for t in assigned(a))]
    return names


def flag_names(expr, node, inside, tree):
    """(the names in a creationflags expression of node, getattr's strings among them, and those in what a name in it is
    set to, each read in the scope it stands in; the names among them with a binding the scan cannot read: values_of).
    The object of an attribute is a name like any other. Not among the second: a name of the flag, which other_names
    holds to it, and the object it is an attribute of (watch.NO_WINDOW), which is followed all the same. In a class
    body no name is followed: it is the class's first, which values_of does not read, so each name the file binds is
    unread. The same in a default, decorator or annotation of a def: written in it, run around it. DETACHED_PROCESS
    is among the first also when only pooled_names finds it: set to a name of that spelling in a function or class
    inside the one of the start, it flags the call though that name is another one."""
    def held(value):
        of_the_flag = {n.value for n in ast.walk(value) if isinstance(n, ast.Attribute) and n.attr in NO_WINDOW}
        return {n.id for n in ast.walk(value) if isinstance(n, ast.Name) and n not in of_the_flag} - set(NO_WINDOW)
    written_in = enclosing_function(tree, written=True).get(node)
    names = {DETACHED} & pooled_names(expr, written_in or tree)
    if node in class_body_nodes(tree, inside) or written_in is not inside.get(node):
        nodes = list(ast.walk(tree))
        bound_in_file = {binds(n) for n in nodes}
        return names | set(names_and_strings(expr)), {name for name in held(expr)
                                                      if name in bound_in_file or unseen_binding(name, nodes)}
    unread, all_read, todo = set(), {}, [(expr, inside.get(node))]
    while todo:
        value, at = todo.pop()
        names.update(names_and_strings(value))
        for name in sorted({n.id for n in ast.walk(value) if isinstance(n, ast.Name)}):
            if (name, at) not in all_read:
                values, all_read[name, at] = values_of(name, at, inside, tree)
                todo += values
            if not all_read[name, at] and name in held(value):
                unread.add(name)
    return names, unread


def not_the_flag(names, unread, spellings=NO_WINDOW):
    """True when what flag_names gives of an expression is not the flag: a name the scan cannot read in every binding,
    DETACHED_PROCESS, or none of the spellings of the flag."""
    return bool(unread) or DETACHED in names or not names & set(spellings)


def unread_note(unread):
    """The end of a message that names the unread names of flag_names; nothing with none."""
    return unread and ', with no name the scan cannot read in every binding (%s)' % ', '.join(sorted(unread)) or ''


def other_names(tree, inside):
    """(line, what is wrong) of each place that gives one of NO_WINDOW's names a value that is not the flag. It is the
    flag when set with = to what names CREATE_NO_WINDOW and never DETACHED_PROCESS, and by no operator (|=), or
    imported from another file by that name."""
    readable = {t for n in ast.walk(tree) for t in assigned(n)}
    readable.update(a for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if not a.asname)
    for node in ast.walk(tree):
        if any(stores_the_flag(t) for t in assigned(node)):
            if isinstance(node, ast.AugAssign):
                yield node.lineno, '%s: a name of the flag is set by an operator: set it with =, to all it holds' % ast.unparse(node)
                continue
            names, unread = flag_names(node.value, node, inside, tree)
            if not_the_flag(names, unread, (THE_FLAG,)):
                yield node.lineno, '%s: a name of the flag is set to what names CREATE_NO_WINDOW and never ' \
                    'DETACHED_PROCESS%s' % (ast.unparse(node), unread_note(unread))
        elif node not in readable and stores_the_flag(node):
            yield node.lineno, 'a name of the flag bound where the scan cannot read its value: set it to CREATE_NO_WINDOW'


def read_as_values(tree):
    """(line, what is wrong) of each place that names a module of the rule, or a starter of one, as a value: assigned,
    passed on or kept, it can get a name the scan does not follow, which reads <module>.<name>(...) alone. Where it
    is only named, in an annotation or isinstance, it is flagged too. No such place: a module as the object of an
    attribute, or of getattr or hasattr with a string that names no starter and no module of the rule. Not read: what reaches a
    module or a starter by a string or by its __dict__ (sys.modules, __import__)."""
    above = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def is_starter(module, name):
        return name in STARTERS.get(module, ()) or takes_no_flags(module, name) or '%s.%s' % (module, name) in STARTERS
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(node.ctx, ast.Load):
            continue
        name, parent = dotted(node), above[node]
        if name in STARTERS or name in NO_FLAGS:
            args = parent.args if isinstance(parent, ast.Call) and dotted(parent.func) in ('getattr', 'hasattr') else []
            by_string = len(args) > 1 and args[0] is node and isinstance(args[1], ast.Constant) \
                and isinstance(args[1].value, str) and not is_starter(name, args[1].value)
            if not isinstance(parent, ast.Attribute) and not by_string:
                yield node.lineno, '%s read as a value, which can give it another name: write %s.<name>, or getattr with ' \
                    'the name in a string' % (name, name)
        elif isinstance(node, ast.Attribute) and is_starter(dotted(node.value), node.attr) \
                and not (isinstance(parent, ast.Call) and parent.func is node):
            yield node.lineno, '%s read as a value, which can give it another name: call it where it is named, ' \
                '%s(...)' % (name, name)


def console_starts(tree, read_by=()):
    """(line, what is wrong) of each start of a program in tree that may open a console window. Its creationflags name
    NO_WINDOW or CREATE_NO_WINDOW, and never DETACHED_PROCESS, and hold no name the scan cannot read in every binding
    (flag_names); a name spelled like the flag is set to it (other_names); a module of the rule and its starters have
    no other name (the imports here, read_as_values).
    read_by: the functions with one start written in them whose flags, or **kw, a test reads (FLAGS_READ_BY)."""
    inside, written_in = enclosing_function(tree), enclosing_function(tree, written=True)
    yield from other_names(tree, inside)
    yield from read_as_values(tree)
    let_through = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and (a.name in STARTERS or a.name in NO_FLAGS):
                    yield node.lineno, '%s imported as %s: the scan reads %s.<name>' % (a.name, a.asname, a.name)
        elif isinstance(node, ast.ImportFrom):
            if any(a.name in STARTERS.get(node.module, ()) or takes_no_flags(node.module, a.name)
                   or '%s.%s' % (node.module, a.name) in STARTERS
                   or a.name == '*' and (node.module in STARTERS or node.module in NO_FLAGS) for a in node.names):
                yield node.lineno, 'a starter imported by name: import %s, and call %s.<name>' % (node.module, node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and dotted(node.func.value):
            module, name = dotted(node.func.value), node.func.attr
            function = written_in.get(node)
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
                if not_the_flag(names, unread):
                    yield node.lineno, '%s.%s with creationflags=%s: they name %s and never DETACHED_PROCESS%s, or a test reads ' \
                        'them (FLAGS_READ_BY)' % (module, name, ast.unparse(flags[0]), ' or '.join(NO_WINDOW), unread_note(unread))
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
                     'def f[NO_WINDOW](): pass', 'class C[*CREATE_NO_WINDOW]: pass', 'type T[**NO_WINDOW] = int',
                     'with f() as w.NO_WINDOW: pass', '[w.CREATE_NO_WINDOW, *x] = 0, 1'):
            self.assertEqual([len(code.splitlines())], self.found(code), code)
        self.assertEqual([2], self.found('def f():\n    NO_WINDOW: int = 0'))
        for code in ('NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)', 'FLAG = subprocess.CREATE_NO_WINDOW\nNO_WINDOW = FLAG',
                     'from board import NO_WINDOW', 'from subprocess import CREATE_NO_WINDOW', 'match m:\n    case _: pass'):
            self.assertEqual([], self.found(code + start), code)

    def test_a_flags_name_is_read_in_the_scope_of_the_start_alone(self):
        """A function that reads a name it does not set is flagged: no name of a scope around is followed."""
        start = '    subprocess.Popen(a, creationflags=flags)'
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        self.assertEqual([], self.found('def spawn():\n    flags = subprocess.CREATE_NO_WINDOW\n' + start))
        self.assertEqual([], self.found(module + start.strip()))
        self.assertEqual([3], self.found(module + 'def spawn():\n' + start))     # the strict side: fine, and flagged
        self.assertEqual([4], self.found('def detach():\n    flags = subprocess.CREATE_NO_WINDOW\n    def start():\n    ' + start))
        # the flag in a name of its own of a function inside this one is not this one's
        self.assertEqual([5], self.found('def spawn():\n    flags = 0\n    def other():\n'
                                         '        flags = subprocess.CREATE_NO_WINDOW\n' + start))
        self.assertEqual([4], self.found(module + 'def spawn():\n    flags = 0\n' + start))
        # nor a class's name of that spelling
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
        # a name in what it is set to is read in that scope too
        self.assertEqual([], self.found('def spawn():\n    x = subprocess.CREATE_NO_WINDOW\n    flags = x\n' + start))
        self.assertEqual([4], self.found('x = subprocess.CREATE_NO_WINDOW\ndef spawn():\n    flags = x | NO_WINDOW\n' + start))
        self.assertEqual([6], self.found('x = 0\ndef detach():\n    flags = x\n    def start():\n'
                                         '        x = subprocess.CREATE_NO_WINDOW\n    ' + start))

    def test_a_name_of_a_scope_around_flags_the_call_whatever_it_is_set_to(self):
        """A name the function does not set may be anything by the time it runs."""
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        reads = 'def f():\n    subprocess.Popen(a, creationflags=flags)'
        for code in (module + 'flags = 0\n' + reads, module + 'vars()["flags"] = 0\n' + reads, module + 'exec("flags = 0")\n' + reads,
                     module + 'setattr(sys.modules[__name__], "flags", 0)\n' + reads, 'import flags\n' + module + 'from x import *\n' + reads,
                     'flags = 0 * subprocess.CREATE_NO_WINDOW\n' + reads, module + 'import builtins\nbuiltins.globals()["flags"] = 0\n' + reads,
                     module + 'from builtins import globals as g\ng()["flags"] = 0\n' + reads,
                     # though they name the flag too
                     'flags = subprocess.DETACHED_PROCESS\ndef f():\n    subprocess.Popen(a, creationflags=flags | NO_WINDOW)',
                     'def f():\n    flags = subprocess.DETACHED_PROCESS\n    def g():\n'
                     '        subprocess.Popen(a, creationflags=flags | subprocess.CREATE_NO_WINDOW)',
                     'from x import *\ndef f():\n    subprocess.Popen(a, creationflags=flags | NO_WINDOW)'):
            self.assertEqual([len(code.splitlines())], self.found(code), code)
        # globals under another name, for a start of the module
        start = 'subprocess.Popen(a, creationflags=flags)'
        self.assertEqual([4], self.found('import builtins\n' + module + 'builtins.globals()["flags"] = 0\n' + start))
        self.assertEqual([4], self.found('from builtins import globals as g\n' + module + 'g()["flags"] = 0\n' + start))
        self.assertEqual([4], self.found('import builtins\nbuiltins.globals()["flags"] = 0\nclass C:\n'
                                         '    p = subprocess.Popen(a, creationflags=flags | NO_WINDOW)'))
        # not such names: a name of the flag, a module, a builtin, a name the file binds nowhere
        for code in ('NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)\ndef f():\n    subprocess.run(a, creationflags=NO_WINDOW)',
                     'from board import NO_WINDOW\ndef f():\n    subprocess.run(a, creationflags=NO_WINDOW | h(1))',
                     'import subprocess\ndef f():\n    subprocess.run(a, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))'):
            self.assertEqual([], self.found(code), code)

    def test_an_annotation_runs_in_the_scope_around_its_def(self):
        module = 'flags = subprocess.CREATE_NO_WINDOW\n'
        start = 'subprocess.Popen(a, creationflags=flags)'
        for g in ('def g(x: (flags := 0) = 1): pass', 'def g(*args: (flags := 0)): pass', 'def g(**kw: (flags := 0)): pass',
                  'def g(*, x: (flags := 0)): pass', 'def g() -> (flags := 0): pass'):
            self.assertEqual([3], self.found(module + g + '\n' + start), g)
        self.assertEqual([4], self.found(module + 'class C:\n    flags = 0\n    def m(self, p: ' + start + ' = None): pass'))
        self.assertEqual([], self.found(module + 'def g(x: int = 1): pass\n' + start))
        # a start that stands there itself follows no name, as in a class body
        for g in ('def g(p=%s): pass', 'def g(p: %s = 1): pass', '@d(%s)\n    def g(): pass'):
            code = 'def f():\n    flags = 0 * subprocess.CREATE_NO_WINDOW\n    ' + g % start
            self.assertEqual([n for n, line in enumerate(code.splitlines(), 1) if 'Popen' in line], self.found(code), code)
        self.assertEqual([], self.found('def f():\n    def g(p=subprocess.Popen(a, creationflags=NO_WINDOW | subprocess.CREATE_NO_WINDOW)): pass'))

    def test_a_flags_name_bound_where_no_value_is_read_flags_the_call(self):
        """Though the flags name the flag too: it is the binding that flags each of these."""
        start = '    subprocess.Popen(a, creationflags=flags | NO_WINDOW)'
        self.assertEqual([], self.found('def spawn():\n' + start))
        self.assertEqual([2], self.found('def spawn(flags):\n' + start))
        self.assertEqual([3], self.found('def detach(*, flags=0):\n    def start():\n    ' + start))
        self.assertEqual([], self.found('def detach():\n    def start():\n    ' + start))
        for bound in ('flags, x = 0, 1', 'for flags in (0,): pass', 'with f() as flags: pass', 'f(flags := 0)', 'from x import flags',
                      'flags = subprocess.CREATE_NO_WINDOW\n    flags, x = 0, 1', 'del flags',
                      'try: pass\n    except E as flags: pass', 'def flags(): pass', 'class flags: pass',
                      'match m:\n        case {"f": flags}: pass', 'match m:\n        case [*flags]: pass',
                      'match m:\n        case {**flags}: pass', 'match m:\n        case C() as flags: pass',
                      'flags = subprocess.CREATE_NO_WINDOW\n    def g[flags](): pass', 'type flags = int'):
            code = 'def spawn():\n    %s\n' % bound + start
            self.assertEqual([len(code.splitlines())], self.found(code), bound)
        # an imported module is no such binding: a module is no flags, and a call whose flags name it alone is flagged
        for bound in ('import x as flags', 'import flags.x'):
            self.assertEqual([], self.found('def spawn():\n    %s\n' % bound + start), bound)
            self.assertEqual([3], self.found('def spawn():\n    %s\n    subprocess.Popen(a, creationflags=flags)' % bound), bound)
        self.assertEqual([1], self.found('spawn = lambda flags: subprocess.Popen(a, creationflags=flags | NO_WINDOW)'))
        self.assertEqual([], self.found('spawn = lambda: subprocess.Popen(a, creationflags=flags | NO_WINDOW)'))
        # a global or nonlocal statement lets another function set the name: the scope's own value is not all it can be
        flag = 'flags = subprocess.CREATE_NO_WINDOW\n'
        self.assertEqual([5], self.found(flag + 'def g():\n    global flags\n    flags = 0\nsubprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([6], self.found('def f():\n    ' + flag + '    def g():\n        nonlocal flags\n        flags = 0\n'
                                         '    subprocess.Popen(a, creationflags=flags)'))
        self.assertEqual([], self.found(flag + 'def g():\n    flags = 0\nsubprocess.Popen(a, creationflags=flags)'))

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
                     # globals may bind a name the file binds nowhere
                     'globals()["flags"] = 0\ndef f():\n    ' + start,
                     'def g():\n    globals().update(flags=0)\ndef f():\n    def h():\n        ' + start,
                     # a def's defaults and decorators run in the scope around it
                     module + 'class C:\n    flags = 0\n    def m(self, p=subprocess.Popen(a, creationflags=flags)): pass',
                     module + 'class C:\n    flags = 0\n    @d(subprocess.Popen(a, creationflags=flags))\n    def m(self): pass',
                     module + 'def g(x=(flags := 0)): pass\nsubprocess.Popen(a, creationflags=flags)',
                     'def f():\n    ' + detached + '    def g(p=' + start + '): pass'):
            self.assertEqual([n for n, line in enumerate(code.splitlines(), 1) if 'Popen' in line], self.found(code), code)
        # without the line that binds, each of the last cases passes
        for code in ('def f():\n    ' + start, 'def f():\n    def h():\n        ' + start,
                     module + 'def g(x=0): pass\nsubprocess.Popen(a, creationflags=flags)'):
            self.assertEqual([], self.found(code), code)
        for code in ('import subprocess\ndef f():\n    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)\n    ' + start,
                     'from board import NO_WINDOW\nsubprocess.run(a, creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)',
                     'import subprocess\nimport x as flags\nfrom json import *\nsubprocess.run(a, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))',
                     'def f(a, cwd):\n    flags = 0\n    ' + start):
            self.assertEqual([], self.found(code), code)

    def test_detached_process_in_a_function_or_class_inside_flags_the_call(self):
        """Every assignment to a name written in the function of the start, or in the file for a start of the module,
        is read for DETACHED_PROCESS: one that names it flags the call, though the name there may be another one."""
        module = 'flags = 0 * subprocess.CREATE_NO_WINDOW\n'
        start = 'subprocess.Popen(a, creationflags=flags)'
        for code in ('class K:\n    flags = subprocess.DETACHED_PROCESS\n' + module + start,
                     module + 'def g():\n    flags = subprocess.DETACHED_PROCESS\n' + start,
                     'class K:\n    flags = subprocess.DETACHED_PROCESS\nvars()["flags"] = 0\n'
                     'subprocess.Popen(a, creationflags=flags | NO_WINDOW)',
                     'def f():\n    flags = 0 * subprocess.CREATE_NO_WINDOW\n    def g():\n        flags = subprocess.DETACHED_PROCESS\n    ' + start,
                     'def f():\n    flags = subprocess.CREATE_NO_WINDOW\n    class K:\n        flags = subprocess.DETACHED_PROCESS\n    ' + start,
                     'class C:\n    def m(self):\n        flags = subprocess.DETACHED_PROCESS\n'
                     '    p = subprocess.Popen(a, creationflags=NO_WINDOW | flags)'):
            self.assertEqual([len(code.splitlines())], self.found(code), code)
        # not from another function beside the one of the start
        self.assertEqual([], self.found('def g():\n    flags = subprocess.DETACHED_PROCESS\ndef f():\n'
                                        '    flags = subprocess.CREATE_NO_WINDOW\n    ' + start))

    def test_the_object_of_an_attribute_is_read_like_any_name(self):
        """What the object is set to counts, and an object the scope cannot read flags the call."""
        for code in ('cfg = types.SimpleNamespace(flags=0)\ndef setup():\n    global cfg\n'
                     '    cfg = types.SimpleNamespace(flags=subprocess.CREATE_NO_WINDOW)\ndef f():\n'
                     '    subprocess.Popen(a, creationflags=cfg.flags)',
                     'flags = subprocess.DETACHED_PROCESS\nclass C:\n'
                     '    p = subprocess.Popen(a, creationflags=flags.real | subprocess.CREATE_NO_WINDOW)',
                     'class K:\n    flags = subprocess.DETACHED_PROCESS\nflags = K.flags | subprocess.CREATE_NO_WINDOW\n'
                     'subprocess.Popen(a, creationflags=flags)',
                     # an object the scope cannot read, though the flags name the flag
                     'def f(o):\n    subprocess.Popen(a, creationflags=o.flags | subprocess.CREATE_NO_WINDOW)',
                     'def f(self):\n    subprocess.Popen(a, creationflags=self.flags | NO_WINDOW)',
                     'from x import cfg\nsubprocess.Popen(a, creationflags=cfg.flags | NO_WINDOW)',
                     'cfg = C()\ndef f():\n    subprocess.Popen(a, creationflags=cfg.flags.real | NO_WINDOW)',
                     # the object of a name of the flag is followed, and DETACHED_PROCESS in it counts
                     'ns = types.SimpleNamespace(NO_WINDOW=subprocess.DETACHED_PROCESS)\nsubprocess.Popen(a, creationflags=ns.NO_WINDOW)'):
            self.assertEqual([n for n, line in enumerate(code.splitlines(), 1) if 'Popen' in line], self.found(code), code)
        # a module, and the object of a name of the flag: the flag by its dotted name
        for code in ('import subprocess\ndef f():\n    subprocess.run(a, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)',
                     'import subprocess\nfrom pkg import watch\ndef f():\n'
                     '    flags = watch.NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)\n'
                     '    subprocess.Popen(a, creationflags=flags)',
                     'def f():\n    import subprocess\n    subprocess.run(a, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)',
                     'cfg = types.SimpleNamespace(flags=subprocess.CREATE_NO_WINDOW)\nsubprocess.Popen(a, creationflags=cfg.flags)'):
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
        # a relative import too: a file of the package by that name may hand the starter on
        for code in ('from .asyncio import subprocess', 'from .subprocess import run', 'from ..os import system', 'from .subprocess import *'):
            self.assertEqual([1], self.found(code), code)
        self.assertEqual([], self.found('from . import subprocess_tools\nfrom .gitenv import NO_WINDOW, git_env'))
        self.assertEqual(2, count_starts(ast.parse('asyncio.subprocess.create_subprocess_exec("git")\nsubprocess.run(a)\nx.y.run(a)')))

    def test_a_module_of_the_rule_under_another_name_is_seen(self):
        for code in ('from subprocess import *', 'from os import *', 'run = subprocess', 'self.sub = os'):
            self.assertEqual([1], self.found(code), code)
        self.assertEqual([], self.found('from json import *\nx = y.subprocess'))

    def test_a_module_or_a_starter_read_as_a_value_is_seen(self):
        """Each of these can give it a name the scan does not follow: the first line is flagged, whatever calls it later."""
        for code in ('sp, n = subprocess, 1\nsp.run(a)', '(sp := subprocess).run(a)', 'run = subprocess.Popen\nrun(a)',
                     'start(subprocess.run, a)', 'f = functools.partial(subprocess.Popen, a)', 'def f(run=subprocess.run): pass',
                     'getattr(subprocess, "Popen")(a)', 'getattr(os, name)(a)',
                     'spawn = os.spawnl', 'starts = [asyncio.create_subprocess_exec]', 'modules = {"os": os}',
                     'for m in (asyncio.subprocess,): pass', 'vars(subprocess)["run"](a)',
                     'sub = getattr(asyncio, "subprocess")\nsub.create_subprocess_exec("git")',
                     'def f(p: subprocess.Popen): pass', 'isinstance(p, subprocess.Popen)'):
            self.assertEqual([1], self.found(code), code)
        for code in ('NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)', 'x = os.path.join(a, b)',
                     'if hasattr(os, "startfile"): pass', 'x = os.environ',
                     'e = subprocess.CalledProcessError', 'run = asyncio.run', 'x = y.subprocess.run', 'def f(subprocess): pass'):
            self.assertEqual([], self.found(code), code)

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
        # a start in a default of a def inside it is that def's
        self.assertEqual([2], self.found('def start():\n    def g(p=subprocess.Popen(a, creationflags=0)): pass', ('start',)))
        self.assertEqual([3], self.found('def start(**kw):\n    def g(p=subprocess.Popen(a, **kw)): pass\n'
                                         '    subprocess.Popen(a, **kw)', ('g',)))


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
