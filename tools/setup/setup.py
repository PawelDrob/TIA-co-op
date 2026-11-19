"""First setup of a clone, also its check: what is there stays as it is, what is missing it sets up or names.

    powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1 [--projects-root <path>]

Exit code 0 is done, 1 something is missing (a question may wait as well), 3 only the question about the projects root waits for an answer.

Each step looks first and returns its findings; a change it would make is a finding of its own, made when its make() is
called: here at once, in the setup window (tools\\setup\\window, Setup.wsf) when its button is pressed.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CLONE = Path(__file__).resolve().parents[2]
BRIDGE_SCRIPT = CLONE / 'TiaBridge' / 'TiaBridge.ps1'
BRIDGE_COMMAND = ('powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(BRIDGE_SCRIPT))
BRIDGE_SETTINGS = CLONE / 'TiaBridge' / 'settings.json'
TRACKED_SETTINGS = CLONE / '.claude' / 'settings.json'
HOOKS = '.githooks'
PLUGIN = 'mattpocock-skills@claude-plugins-official'
MARKETPLACE = 'anthropics/claude-plugins-official'
# Every name git reads a repo from, as git rev-parse --local-env-vars lists them (a test holds this list to git's).
# Left by a parent, git prefers them to -C: it would act on the parent's repo.
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')
COMMAND_SECONDS = 300
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
OUTPUT_HEAD_LINES = 20
OUTPUT_TAIL_LINES = 10
DEPTH_LIMIT = 102  # of ConvertFrom-Json, as TiaArchiveCompare\runner\powershell_json.py has it
TOO_DEEP = f'nesting over {DEPTH_LIMIT} levels'
DEFAULT_TIA_ROOT = r'C:\Program Files\Siemens\Automation\Portal V20'  # as Get-BridgeSettings, TiaBridge\Repo.ps1
OPENNESS_GROUP = 'Siemens TIA Openness'
ARCHIVE_LIMIT = 143
ARCHIVE_PATH_AROUND_NAMES = 39  # around the project's name, which it holds twice: ConvertTo-ArchiveName, TiaBridge\Tools\Session.ps1
PROJECT_NAME_WANTED = 30


# What a finding is about: the window groups and finds them by it.
TOPIC_GIT, TOPIC_HOOK, TOPIC_CLAUDE, TOPIC_SERVER, TOPIC_PLUGIN, TOPIC_TRACKED, TOPIC_STATUS, TOPIC_ROOT, TOPIC_TIA, TOPIC_GROUP, TOPIC_UV = (
    'git', 'commit hook', 'Claude Code', 'MCP server tia', 'plugin', 'tracked settings', 'status line', 'projectsRoot',
    'TIA Portal', 'Openness group', 'uv')
PREFIXES = {'ok': 'ok       ', 'done': 'done     ', 'warning': 'warning  ', 'missing': 'missing  ', 'note': '         '}


class Finding:
    """One thing a step found. kind: ok, done, warning, missing, note (a line under the one before it), question, or
    change: a change not made yet, its text saying what it changes and where; make() makes it, from what is there then,
    and gives the findings of that. A step looks only, and changes nothing until make() is called: setup calls it at
    once, the window when the person says so. shown: what the window shows in place of text, where the line printed
    here speaks of the command or only names its topic; '' to show text."""

    def __init__(self, kind, text, topic, make=None, person_step=None, shown=''):
        self.kind, self.text, self.topic, self.make, self.person_step, self.shown = kind, text, topic, make, person_step, shown

    def __repr__(self):
        return f'Finding({self.kind!r}, {self.text!r}, {self.topic!r})'


class Report:
    """What the run found, one line each in the order it found it, and at the end what is left for a person."""

    def __init__(self):
        self.missing = 0
        self.question = None
        self.person_steps = []

    def show(self, finding):
        """Prints a finding; a change is made first, and its outcome printed."""
        if finding.kind == 'change':
            for made in finding.make():
                self.show(made)
            return
        if finding.kind == 'question':
            self.question = finding.text
            return
        if finding.kind == 'missing':
            self.missing += 1
        if finding.person_step:
            self.person_steps.append(finding.person_step)
        print(PREFIXES[finding.kind] + finding.text)


def run(*command):
    """Exit code and output of a command; 127 when it could not run."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
    try:
        # no console of its own: from the window, which has none, a console program would open one
        done = subprocess.run(command, cwd=CLONE, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              stdin=subprocess.DEVNULL, timeout=COMMAND_SECONDS, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return done.returncode, done.stdout + done.stderr


def output_lines(output):
    """A failed command's output, indented under the line that names it: its cause can stand anywhere, and a retry's words come last.
    A real clone failure ran to some 900 lines of one error, so a long one keeps its head and tail and says how much went."""
    lines = output.strip().splitlines()
    if len(lines) > OUTPUT_HEAD_LINES + OUTPUT_TAIL_LINES:
        lines = [*lines[:OUTPUT_HEAD_LINES], f'... {len(lines) - OUTPUT_HEAD_LINES - OUTPUT_TAIL_LINES} lines left out ...', *lines[-OUTPUT_TAIL_LINES:]]
    return ''.join(f'\n         {line}' for line in lines) or ' no message'


def user_settings_file():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'settings.json'


def claude_state_file():
    """Where Claude Code keeps its servers. Read without starting them: `claude mcp get` starts a bridge to check it."""
    config = os.environ.get('CLAUDE_CONFIG_DIR')
    return Path(config) / '.claude.json' if config else Path.home() / '.claude.json'


BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'),
        (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))


def as_windows_powershell_reads(raw):
    """Get-Content of Windows PowerShell 5.1, which the bridge reads its settings with: by the BOM, else ANSI. Its twins,
    as setup runs before the Python environment: TiaAgentStatus\\state.py and TiaArchiveCompare\\runner\\checks.py."""
    for bom, encoding in BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding, 'replace')
    return raw.decode('mbcs', 'replace')


def read_json(path):
    """A file's object, {} when there is no file. A file that cannot be read raises ValueError, naming it: it stays as it is."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError) as e:
        raise ValueError(f'{path} cannot be read ({e}); fix the file, then run this again') from e
    if not isinstance(data, dict):
        raise ValueError(f'{path} is not a JSON object; fix the file, then run this again')
    return data


def folded(name):
    """A name as the bridge compares the names of its settings, without case (StringComparison.OrdinalIgnoreCase): each
    character's own upper case, where that is one character and not an ASCII one for a character outside ASCII. Its
    twins: TiaAgentStatus\\state.py and TiaArchiveCompare\\runner\\powershell_json.py."""
    def upper(c):
        u = c.upper()
        return u if len(u) == 1 and (u >= '\x80' or c < '\x80') else c
    return ''.join(upper(c) for c in name)


def spelled(settings, name):
    """The name as the settings spell it, whatever its case, else as given."""
    return next((n for n in settings if folded(n) == folded(name)), name)


def refused_in(value, depth=1):
    """Why the bridge refuses a parsed JSON value, '' when it takes it: nesting over DEPTH_LIMIT levels, an empty name,
    or two names that differ in case only, in the value or anywhere inside it. Its twin: TiaAgentStatus\\state.py."""
    if depth > DEPTH_LIMIT:
        return TOO_DEEP
    if isinstance(value, list):
        return next(filter(None, (refused_in(item, depth + 1) for item in value)), '')
    if not isinstance(value, dict):
        return ''
    seen = {}
    for name in value:
        first = seen.setdefault(folded(name), name)
        if first != name:
            return f'two names that differ in case only, {first} and {name}'
        if name == '':
            return 'an empty name'
    return next(filter(None, (refused_in(member, depth + 1) for member in value.values())), '')


def blank(text):
    """A text the bridge takes for an empty file. The four separators U+001C to U+001F are white space to Python and
    not to .NET, which refuses a file of them. Its twin: TiaAgentStatus\\state.py."""
    return not text.strip() and not any('\x1c' <= c <= '\x1f' for c in text)


class TooLarge(ValueError):
    """A number of the settings that overflows a double, which the bridge refuses the file for."""


def number(token):
    """A JSON number as json.loads makes it, TooLarge where it makes infinity of it. Its twin: TiaAgentStatus\\state.py."""
    if math.isinf(float(token)):
        raise TooLarge(f'the number {token}, too large for it')
    return int(token) if token.lstrip('-').isdigit() else float(token)


def read_bridge_settings():
    """The bridge's settings, decoded as the bridge decodes them; Claude Code's files are UTF-8 (read_json). {} without a
    file, and for an empty file or a value that is no object, where the bridge runs on its defaults. Strict JSON only:
    what else the bridge takes (single quotes, names without quotes) stops setup with ValueError, as does what the
    bridge refuses in strict JSON: a number too large for a double (number), deep nesting and names (refused_in). A
    name has one value then, whatever its case (spelled). Its twin: bridge_settings, TiaAgentStatus\\state.py."""
    if not BRIDGE_SETTINGS.exists():
        return {}
    try:
        text = as_windows_powershell_reads(BRIDGE_SETTINGS.read_bytes())
        settings = json.loads(text, parse_float=number, parse_int=number) if not blank(text) else None
        refused = refused_in(settings)
    except TooLarge as e:
        refused = str(e)
    except RecursionError:      # deeper than Python parses
        refused = TOO_DEEP
    except (OSError, ValueError) as e:
        raise ValueError(f'{BRIDGE_SETTINGS} cannot be read ({e}); fix the file, then run this again') from e
    if refused:
        raise ValueError(f'{BRIDGE_SETTINGS} holds {refused}, which the bridge refuses; fix the file, then run this again')
    return settings if isinstance(settings, dict) else {}


def write_json(path, data, ascii_only):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.setup')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=ascii_only) + '\n', encoding='utf-8', newline='\n')
    os.replace(temp, path)


def uv_path():
    """uv as a double-click finds it: on the PATH, else where its installer puts it, which a PATH read before the install
    lacks. setup.ps1 and Setup.wsf look for it themselves, as they run before this Python does."""
    found = shutil.which('uv')
    if found:
        return found
    installed = Path(os.environ.get('USERPROFILE') or Path.home()) / '.local' / 'bin' / 'uv.exe'
    return str(installed) if installed.exists() else None


def uv_step():
    if uv_path():
        return [Finding('ok', 'uv', TOPIC_UV, shown='Found.')]
    return [Finding('missing', 'uv, which makes the Python environment of this repo: install it (https://docs.astral.sh/uv/)', TOPIC_UV)]


def git_step():
    if shutil.which('git'):
        return [Finding('ok', 'git', TOPIC_GIT, shown='On the PATH.')]
    return [Finding('missing', 'git: install it (https://git-scm.com/downloads/win), then run this again in a new terminal', TOPIC_GIT)]


def hook_step(write=False):
    if not shutil.which('git'):
        return []
    code, value = run('git', 'config', '--local', '--get', 'core.hooksPath')
    value = value.strip()
    if value == HOOKS:
        return [Finding('ok', f'commit hook: core.hooksPath is {HOOKS}', TOPIC_HOOK)]
    if code == 0:
        return [Finding('missing', f'commit hook: core.hooksPath is {value}, so the checks in {HOOKS} do not run on a commit; left as it is. They run after: git config core.hooksPath {HOOKS}', TOPIC_HOOK)]
    if not write:
        return [Finding('change', f'commit hook: sets core.hooksPath to {HOOKS} in the git settings of {CLONE} (git config core.hooksPath {HOOKS}), so a commit runs the checks in {HOOKS}',
                        TOPIC_HOOK, lambda: hook_step(write=True))]
    code, output = run('git', 'config', '--local', 'core.hooksPath', HOOKS)
    if code:
        return [Finding('missing', f'commit hook: without core.hooksPath a commit skips the checks, and setting it failed:{output_lines(output)}', TOPIC_HOOK)]
    return [Finding('done', f'commit hook: core.hooksPath set to {HOOKS}', TOPIC_HOOK)]


def script_of(server):
    args = server.get('args') or []
    return next((args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() == '-file'), '')


def is_this_clone(server):
    script = script_of(server)
    return bool(script) and same_path(script, BRIDGE_SCRIPT)


def add_server(claude, scope, done_text):
    code, output = run(claude, 'mcp', 'add', '--scope', scope, 'tia', '--', *BRIDGE_COMMAND)
    if code:
        return [Finding('missing', f'MCP server tia: claude mcp add failed:{output_lines(output)}', TOPIC_SERVER)]
    return [Finding('done', done_text, TOPIC_SERVER)]


def server_change(claude, scope, plan, write, done_text):
    if write:
        return add_server(claude, scope, done_text)
    command = subprocess.list2cmdline(['claude', 'mcp', 'add', '--scope', scope, 'tia', '--', *BRIDGE_COMMAND])
    return [Finding('change', f'MCP server tia: registers it {plan}: {command}. Claude Code keeps it in {claude_state_file()}', TOPIC_SERVER,
                    lambda: server_step(claude, write=True))]


def server_step(claude, write=False):
    """User scope for the first clone. A second clone takes the name for its own folder: the first keeps its server, and no question stops the setup.
    With a stand-in server, `claude mcp list` started only the local definition in that folder and only the user one elsewhere; a real session has not been tried."""
    try:
        state = read_json(claude_state_file())
    except ValueError as e:
        return [Finding('missing', f'MCP server tia: {e}', TOPIC_SERVER)]
    user = (state.get('mcpServers') or {}).get('tia')
    if not user:
        return server_change(claude, 'user', 'for your Windows user', write, 'MCP server tia registered, user scope')
    if is_this_clone(user):
        return [Finding('ok', 'MCP server tia', TOPIC_SERVER, shown='Registered for your Windows user: it starts the bridge of this clone.')]
    other = script_of(user) or 'another command'
    elsewhere = f'in other folders tia stays {other}. To make this clone the one for all: claude mcp remove --scope user tia, then run this again'
    projects = state.get('projects') or {}
    here = next((p for key, p in projects.items() if same_path(key, CLONE)), {})
    local = (here.get('mcpServers') or {}).get('tia')
    if not local:
        return server_change(claude, 'local', f'for this folder only, as {other} has it for your Windows user', write,
                             f'MCP server tia registered for this folder; {elsewhere}')
    if is_this_clone(local):
        return [Finding('ok', f'MCP server tia, for this folder; {elsewhere}', TOPIC_SERVER)]
    return [Finding('missing', f'MCP server tia: in this folder it is registered for {script_of(local) or "another command"}; left as it is. To move it here: claude mcp remove --scope local tia, then run this again', TOPIC_SERVER)]


def plugin_installed(claude):
    """Claude Code has been seen to add an entry of project scope for clones and worktrees where sessions ran: only one of user scope serves every clone."""
    code, output = run(claude, 'plugin', 'list', '--json')
    if code:
        return False
    try:
        return any(p.get('id') == PLUGIN and p.get('scope') == 'user' for p in json.loads(output))
    except (ValueError, AttributeError):
        return False


PLUGIN_COMMANDS = (('adding its marketplace', ('plugin', 'marketplace', 'add', MARKETPLACE)), ('installing it', ('plugin', 'install', PLUGIN, '--scope', 'user')))


def plugin_step(claude, write=False):
    """Looking asks claude plugin list; the change does not ask again, and installing an installed plugin is no harm."""
    if not write:
        if plugin_installed(claude):
            return [Finding('ok', f'plugin {PLUGIN}', TOPIC_PLUGIN, shown=f'{PLUGIN}, installed for your Windows user.')]
        commands = ' and '.join(subprocess.list2cmdline(['claude', *command]) for _, command in PLUGIN_COMMANDS)
        return [Finding('change', f'plugin {PLUGIN}: installs it for your Windows user: {commands}', TOPIC_PLUGIN, lambda: plugin_step(claude, write=True))]
    for what, command in PLUGIN_COMMANDS:
        code, output = run(claude, *command)
        if code:
            return [Finding('missing', f'plugin {PLUGIN}: {what} failed:{output_lines(output)}', TOPIC_PLUGIN)]
    return [Finding('done', f'plugin {PLUGIN} installed, user scope', TOPIC_PLUGIN)]


def tracked_settings_step():
    """A plugin command of project scope rewrites this tracked file, and has been seen to empty it."""
    try:
        settings = read_json(TRACKED_SETTINGS)
    except ValueError as e:
        return [Finding('missing', f'.claude/settings.json: {e}', TOPIC_TRACKED)]
    found = []
    if not (settings.get('enabledPlugins') or {}).get(PLUGIN):
        found.append(Finding('missing', f'.claude/settings.json does not enable {PLUGIN}, so a Claude Code session here goes without it. To bring it back: git restore .claude/settings.json', TOPIC_TRACKED))
    if not str((settings.get('env') or {}).get('LANG', '')).upper().replace('-', '').endswith('UTF8'):
        found.append(Finding('missing', '.claude/settings.json sets no LANG of UTF-8 for a Claude Code session here, and without one the grep of Git Bash aborts '
                             'on -i with fixed strings. To bring it back: git restore .claude/settings.json', TOPIC_TRACKED))
    return found


def is_full_path(text):
    return isinstance(text, str) and '"' not in text and bool(re.match(r'^[A-Za-z]:[\\/]', text))


def normal_root(text):
    """The folder as it is stored: with an upper-case drive letter and one kind of slash."""
    if not is_full_path(text):
        raise ValueError(f'{text} is not a full path on a drive. Give one such as --projects-root "C:\\TIA-Projects"')
    path = os.path.normpath(text)
    return path[0].upper() + path[1:]


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def forward_slashes(root):
    return root.replace('\\', '/').rstrip('/')


def allow_rules(root):
    """Read, edit and git under the folder. Claude Code takes one rule per tool, so "the rule" is these together."""
    forward = forward_slashes(root)
    posix = '/' + forward[0].lower() + forward[2:]
    rules = [f'Read(/{posix}/**)', f'Edit(/{posix}/**)']
    for tool in ('Bash', 'PowerShell'):
        rules += [f'{tool}(git -C {forward}/*)', f'{tool}(git -C "{forward}/*)']
    return rules


def ensure_allow_list(user, user_file):
    permissions = user.setdefault('permissions', {})
    allow = permissions.setdefault('allow', []) if isinstance(permissions, dict) else None
    if not isinstance(allow, list):
        raise ValueError(f'{user_file} holds no list at permissions.allow; fix the file, then run this again')
    return allow


STATUS_PYTHON = '/.venv/Scripts/python.exe'
STATUS_TOOL = '/TiaAgentStatus'
# A word Git Bash reads as written: in double quotes, with a backslash before each $, backtick, " and \ it holds; or bare, of
# characters bash leaves alone.
BASH_WORD = r'"(?:[^"\\$`]|\\.)*"|[\w/.:-]+'
STATUS_PATTERN = re.compile(rf'(?P<python>{BASH_WORD}) -X utf8 (?P<tool>{BASH_WORD}) statusline')


def bash_quoted(text):
    return '"' + re.sub(r'([$`"\\])', r'\\\1', text) + '"'


def bash_word(word):
    return re.sub(r'\\([$`"\\])', r'\1', word[1:-1]) if word.startswith('"') else word


def status_command(clone):
    """In double quotes, escaped where bash needs it, with forward slashes: Claude Code runs it through Git Bash on Windows. clone_of reads it back."""
    forward = forward_slashes(str(clone))
    return f'{bash_quoted(forward + STATUS_PYTHON)} -X utf8 {bash_quoted(forward + STATUS_TOOL)} statusline'


def clone_of(status_line):
    """The clone whose TIA row a statusLine entry runs, as Git Bash reads it: as status_command writes it, or as the README had
    it by hand, without quotes. Its python must be of the same clone. None for another command or one Git Bash changes."""
    command = status_line.get('command') if isinstance(status_line, dict) else None
    found = STATUS_PATTERN.fullmatch(command.strip()) if isinstance(command, str) else None
    if not found:
        return None
    python, tool = (bash_word(found[word]).replace('\\', '/') for word in ('python', 'tool'))  # only a quoted word holds a backslash
    if not (python.endswith(STATUS_PYTHON) and tool.endswith(STATUS_TOOL)):
        return None
    # with the slash before the tail: D: alone is the folder in use on that drive, D:/ its root
    python_clone = os.path.normpath(python[:len(python) - len(STATUS_PYTHON) + 1])
    clone = os.path.normpath(tool[:len(tool) - len(STATUS_TOOL) + 1])
    return clone if same_path(python_clone, clone) else None


def status_line_step(write=False):
    user_file = user_settings_file()
    try:
        user = read_json(user_file)
    except ValueError as e:
        return [Finding('missing', f'status line: {e}', TOPIC_STATUS)]
    clone = clone_of(user.get('statusLine'))
    if clone and same_path(clone, CLONE):
        return [Finding('ok', f'status line: the TIA row, in {user_file}', TOPIC_STATUS)]
    if clone:
        return [Finding('ok', f"status line: the TIA row of {clone}, left as it is. To make it this clone's: remove statusLine from {user_file}, then run this again", TOPIC_STATUS)]
    if 'statusLine' in user:
        return [Finding('ok', f'status line: your own, left as it is. For the TIA row in it too, it can run {status_command(CLONE)}, '
                        f'which prints the row or nothing: "Status line" in {CLONE / "TiaAgentStatus" / "README.md"}', TOPIC_STATUS)]
    if not write:
        return [Finding('change', f'status line: adds the TIA row to Claude Code, as statusLine in {user_file}: {status_command(CLONE)}', TOPIC_STATUS,
                        lambda: status_line_step(write=True))]
    user['statusLine'] = {'type': 'command', 'command': status_command(CLONE), 'refreshInterval': 5}
    try:
        write_json(user_file, user, ascii_only=False)
    except OSError as e:
        return [Finding('missing', f'status line: writing failed: {e}', TOPIC_STATUS)]
    return [Finding('done', f'status line: the TIA row, in {user_file}', TOPIC_STATUS)]


def default_projects_root():
    return str(Path.home() / 'TIA-Projects')


def long_path_warning(root):
    """The warning on a folder that leaves little room for a project's name in an archive path, '' for one that does not."""
    room = (ARCHIVE_LIMIT - len(root.rstrip('\\')) - ARCHIVE_PATH_AROUND_NAMES) // 2
    if room < PROJECT_NAME_WANTED:
        return f'projectsRoot is long: TIA refuses an archive path over {ARCHIVE_LIMIT} characters, and this folder leaves room for a project name of {max(room, 0)} characters'
    return ''


def projects_root_step(answer=None, write=False):
    """Stores the answer and keeps the allow rules on the folder. Reads all first: a file that cannot be read stops it with nothing written."""
    user_file = user_settings_file()
    try:
        bridge = read_bridge_settings()
        user = read_json(user_file)
        allow = ensure_allow_list(user, user_file)
        name = spelled(bridge, 'projectsRoot')
        stored = bridge.get(name)
        # no text, or an empty one: the bridge takes it over its default, so it is said and an answer replaces it
        no_folder = json.dumps(stored) if name in bridge and not (stored and isinstance(stored, str)) else ''
        if no_folder:
            stored = None
        root = normal_root(answer or stored) if answer or stored else None
    except ValueError as e:
        return [Finding('missing', f'projectsRoot: {e}', TOPIC_ROOT)]
    if not root:
        question = ((f'{BRIDGE_SETTINGS} holds {no_folder} as projectsRoot, which names no folder. ' if no_folder else '')
                    + f'Where should the project repos live? The default is {default_projects_root()}.')
        return [Finding('question', question + ' Ask the user, then run this again with --projects-root "<path>", the default too.', TOPIC_ROOT,
                        shown='Not set yet. ' + question)]
    changed = not (stored and same_path(stored, root))
    if not changed:
        root = normal_root(stored)
    old_rules = allow_rules(normal_root(stored)) if changed and is_full_path(stored) else []
    kept = [r for r in allow if r not in old_rules]
    updated = kept + [r for r in allow_rules(root) if r not in kept]
    if (changed or updated != allow) and not write:
        plan = ([f'projectsRoot: sets it to {root} in {BRIDGE_SETTINGS}' + (f', in place of {stored}' if stored else f', in place of {no_folder}' if no_folder else '') + '.']
                if changed else [f'projectsRoot {stored} stays.'])
        plan.append(f'Claude Code allow rules for read, edit and git in that folder, in {user_file}:')
        plan += [f'    adds {r}' for r in updated if r not in allow] + [f'    takes away {r}' for r in allow if r not in updated]
        return [Finding('change', '\n'.join(plan), TOPIC_ROOT, lambda: projects_root_step(answer, write=True))]
    try:
        if changed:
            bridge[spelled(bridge, 'projectsRoot')] = root      # never a second spelling: the bridge refuses two
            write_json(BRIDGE_SETTINGS, bridge, ascii_only=True)  # Windows PowerShell 5.1 reads a file with no byte order mark as ANSI
        if updated != allow:
            user['permissions']['allow'] = updated
            write_json(user_file, user, ascii_only=False)
    except OSError as e:
        return [Finding('missing', f'projectsRoot: writing failed: {e}', TOPIC_ROOT)]
    if not changed:
        found = [Finding('ok', f'projectsRoot {stored}. To change it: --projects-root "<path>"', TOPIC_ROOT, shown=stored)]
    elif stored:
        found = [Finding('done', f'projectsRoot changed from {stored} to {root}. No repo moved: those in the old folder stay there. A bridge already running keeps the old value until it restarts. Another clone on the old folder loses these rules, as they are per user: run setup in it to bring them back', TOPIC_ROOT)]
    else:
        found = [Finding('done', f'projectsRoot {root}, in {BRIDGE_SETTINGS}' + (f', in place of {no_folder}, which named no folder' if no_folder else ''), TOPIC_ROOT)]
    found.append(Finding('note', f'Setup makes no folder there: the bridge makes {root}\\_bridge\\sessions each time it starts; with Claude Code, in every new session and at claude mcp get tia.', TOPIC_ROOT))
    git_form = f'git -C "{forward_slashes(root)}/<repo>"'
    found.append(Finding('ok' if updated == allow else 'done', f'Claude Code allow rules for read, edit and git in that folder, in {user_file}. Git goes by {git_form}: with a backslash or a cd first it asks', TOPIC_ROOT))
    warning = long_path_warning(root)
    return found + ([Finding('warning', warning, TOPIC_ROOT)] if warning else [])


def tia_step():
    """As the bridge finds it: tiaRoot of its settings, the Openness API of V20 under it (Import-Openness, TiaBridge\\Tia.ps1)."""
    try:
        bridge = read_bridge_settings()
    except ValueError:
        return []  # projects_root_step names the file
    name = spelled(bridge, 'tiaRoot')
    tia_root = bridge.get(name, DEFAULT_TIA_ROOT)
    if not (tia_root and isinstance(tia_root, str)):    # the bridge takes it over its default
        return [Finding('missing', f'TIA Portal V20 with TIA Openness: {BRIDGE_SETTINGS} holds {json.dumps(tia_root)} as tiaRoot, which names no folder', TOPIC_TIA,
                        person_step=f'Set tiaRoot in {BRIDGE_SETTINGS} to the folder of TIA Portal V20, or take it out for the default, {DEFAULT_TIA_ROOT}.')]
    if (Path(tia_root) / 'PublicAPI' / 'V20' / 'Siemens.Engineering.dll').exists():
        return [Finding('ok', f'TIA Portal V20 with TIA Openness, {tia_root}', TOPIC_TIA)]
    return [Finding('missing', f'TIA Portal V20 with TIA Openness: not found in {tia_root}', TOPIC_TIA,
                    person_step=f'Install TIA Portal V20 with the TIA Openness option. If V20 is in another folder, set tiaRoot in {BRIDGE_SETTINGS}.')]


def openness_step():
    """The groups of this logon, as the bridge's Test-OpennessGroup sees them: a user added since then counts only after logging on again."""
    # By its folder: in Git Bash the first whoami on the PATH is Git's own, which ignores these arguments.
    whoami = shutil.which('whoami', path=os.path.join(os.environ['SystemRoot'], 'System32'))
    code, output = run(whoami, '/groups', '/fo', 'csv', '/nh') if whoami else (127, '')
    if code == 0 and re.search(r'^"(?:[^"\\]*\\)?' + OPENNESS_GROUP + '"', output, re.IGNORECASE | re.MULTILINE):
        return [Finding('ok', f"the Windows group '{OPENNESS_GROUP}'", TOPIC_GROUP)]
    return [Finding('missing', f"the Windows group '{OPENNESS_GROUP}': TIA refuses Openness to a user outside it", TOPIC_GROUP,
                    person_step=f"Join the Windows group '{OPENNESS_GROUP}' (an administrator or IT adds you), then log off and on.")]


def claude_step():
    """Claude Code itself: on the PATH or not. Without it setup prints no line, as it is no failure, and says so in the list for a person."""
    claude = shutil.which('claude')
    if claude:
        return [Finding('ok', 'Claude Code', TOPIC_CLAUDE, shown='On the PATH.')]
    return [Finding('warning', 'Claude Code: not on the PATH, so no MCP server tia and no plugin are registered. It is what this repo was tested with, '
                    'not a requirement: install it (https://code.claude.com/docs) to work with agents here', TOPIC_CLAUDE)]


def main_tree_if_worktree():
    """The main working tree when this is a linked worktree of it, else None. Git absent or no repo: None, hook_step names those."""
    code, output = run('git', 'rev-parse', '--path-format=absolute', '--git-dir', '--git-common-dir')
    lines = output.split('\n')[:2]
    if code or len(lines) != 2 or same_path(lines[0], lines[1]):
        return None
    return str(Path(lines[1]).parent)


def worktree_refusal(main_tree):
    return f'this is a worktree of {main_tree}. A worktree needs only uv sync; the server and the settings belong to the main tree, so run setup there.'


def steps(claude, answer=None):
    """Setup's steps in the order it runs them, each a call that looks when it is made, so a change made before it counts.
    Without claude, its three steps are left out."""
    with_claude = [claude_step, lambda: server_step(claude), lambda: plugin_step(claude)] if claude else []
    return [git_step, hook_step, *with_claude, tracked_settings_step, status_line_step, lambda: projects_root_step(answer), tia_step, openness_step]


def last_steps(claude):
    """What a person does once, after what the steps named for a person."""
    agent_step = (f'If a session in {CLONE} ran this setup, end it and run claude --continue there: it comes back with that conversation and its task, now with the server, so tell it to go on. '
                  f'Otherwise start a new session in {CLONE}. Accept its trust prompt and approve the plugin if it asks: a session started before this run has neither the server nor the plugin. There, tia_status shows that the bridge starts.' if claude else
                  f'claude is not on the PATH, so this run did not register the MCP server tia or the plugin {PLUGIN}. To add them, install Claude Code (https://code.claude.com/docs), then run this again in a new terminal. '
                  f'Tested with Claude Code only: no other agent has been tried. To try one, give it this command to start the bridge: {subprocess.list2cmdline(BRIDGE_COMMAND)}')
    return [agent_step, 'At the first connect, TIA asks whether to allow access: answer Yes.']


def main(argv=None):
    parser = argparse.ArgumentParser(description='First setup of a clone, also its check.')
    parser.add_argument('--projects-root', metavar='path', help='the folder of the project repos (TiaBridge\\settings.json projectsRoot)')
    args = parser.parse_args(argv)
    main_tree = main_tree_if_worktree()
    if main_tree:
        print(f'refused  {worktree_refusal(main_tree)}')
        return 1
    report = Report()
    claude = shutil.which('claude')
    for step in steps(claude, args.projects_root):
        for finding in step():
            report.show(finding)
    print('\nA person does these, once:')
    for step in report.person_steps + last_steps(claude):
        print(f'- {step}')
    if report.question:
        print(f'\nQuestion: {report.question}')
    if report.missing:
        return 1
    return 3 if report.question else 0


if __name__ == '__main__':
    sys.exit(main())
