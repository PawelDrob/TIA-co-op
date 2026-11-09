"""First setup of a clone, also its check: what is there stays as it is, what is missing it sets up or names.

    powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1 [--projects-root <path>]

Exit code 0 is done, 1 something is missing (a question may wait as well), 3 only the question about the projects root waits for an answer.
"""
import argparse
import json
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
# A parent's: git prefers them to -C
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')
COMMAND_SECONDS = 300
OUTPUT_HEAD_LINES = 20
OUTPUT_TAIL_LINES = 10
DEFAULT_TIA_ROOT = r'C:\Program Files\Siemens\Automation\Portal V20'  # as Get-BridgeSettings, TiaBridge\Repo.ps1
OPENNESS_GROUP = 'Siemens TIA Openness'
ARCHIVE_LIMIT = 143
ARCHIVE_PATH_AROUND_NAMES = 39  # around the project's name, which it holds twice: ConvertTo-ArchiveName, TiaBridge\Tools\Session.ps1
PROJECT_NAME_WANTED = 30


class Report:
    """What the run found, one line each in the order it found it, and at the end what is left for a person."""

    def __init__(self):
        self.missing = 0
        self.question = None
        self.person_steps = []

    def ok(self, text):
        print(f'ok       {text}')

    def done(self, text):
        print(f'done     {text}')

    def warn(self, text):
        print(f'warning  {text}')

    def lack(self, text):
        self.missing += 1
        print(f'missing  {text}')

    def lack_for_person(self, text, step):
        self.lack(text)
        self.person_steps.append(step)


def run(*command):
    """Exit code and output of a command; 127 when it could not run."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
    try:
        done = subprocess.run(command, cwd=CLONE, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              stdin=subprocess.DEVNULL, timeout=COMMAND_SECONDS)
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


def read_json(path, decode=lambda raw: raw.decode('utf-8-sig')):
    """A file's object, {} when there is no file. A file that cannot be read raises ValueError, naming it: it stays as it is."""
    if not path.exists():
        return {}
    try:
        data = json.loads(decode(path.read_bytes()))
    except (OSError, ValueError) as e:
        raise ValueError(f'{path} cannot be read ({e}); fix the file, then run this again') from e
    if not isinstance(data, dict):
        raise ValueError(f'{path} is not a JSON object; fix the file, then run this again')
    return data


def read_bridge_settings():
    """The bridge's settings, decoded as the bridge decodes them; Claude Code's files are UTF-8 (read_json)."""
    return read_json(BRIDGE_SETTINGS, as_windows_powershell_reads)


def write_json(path, data, ascii_only):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.setup')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=ascii_only) + '\n', encoding='utf-8', newline='\n')
    os.replace(temp, path)


def check_git(report):
    if shutil.which('git'):
        report.ok('git')
    else:
        report.lack('git: install it (https://git-scm.com/downloads/win), then run this again in a new terminal')


def set_hook_path(report):
    if not shutil.which('git'):
        return
    code, value = run('git', 'config', '--local', '--get', 'core.hooksPath')
    value = value.strip()
    if value == HOOKS:
        report.ok(f'commit hook: core.hooksPath is {HOOKS}')
    elif code == 0:
        report.lack(f'commit hook: core.hooksPath is {value}, so the checks in {HOOKS} do not run on a commit; left as it is. They run after: git config core.hooksPath {HOOKS}')
    else:
        code, output = run('git', 'config', '--local', 'core.hooksPath', HOOKS)
        if code:
            report.lack(f'commit hook: without core.hooksPath a commit skips the checks, and setting it failed:{output_lines(output)}')
        else:
            report.done(f'commit hook: core.hooksPath set to {HOOKS}')


def script_of(server):
    args = server.get('args') or []
    return next((args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() == '-file'), '')


def is_this_clone(server):
    script = script_of(server)
    return bool(script) and same_path(script, BRIDGE_SCRIPT)


def add_server(report, claude, scope, done_text):
    code, output = run(claude, 'mcp', 'add', '--scope', scope, 'tia', '--', *BRIDGE_COMMAND)
    if code:
        report.lack(f'MCP server tia: claude mcp add failed:{output_lines(output)}')
    else:
        report.done(done_text)


def register_bridge(report, claude):
    """User scope for the first clone. A second clone takes the name for its own folder: the first keeps its server, and no question stops the setup.
    With a stand-in server, `claude mcp list` started only the local definition in that folder and only the user one elsewhere; a real session has not been tried."""
    try:
        state = read_json(claude_state_file())
    except ValueError as e:
        report.lack(f'MCP server tia: {e}')
        return
    user = (state.get('mcpServers') or {}).get('tia')
    if not user:
        add_server(report, claude, 'user', 'MCP server tia registered, user scope')
        return
    if is_this_clone(user):
        report.ok('MCP server tia')
        return
    other = script_of(user) or 'another command'
    elsewhere = f'in other folders tia stays {other}. To make this clone the one for all: claude mcp remove --scope user tia, then run this again'
    projects = state.get('projects') or {}
    here = next((p for key, p in projects.items() if same_path(key, CLONE)), {})
    local = (here.get('mcpServers') or {}).get('tia')
    if not local:
        add_server(report, claude, 'local', f'MCP server tia registered for this folder; {elsewhere}')
    elif is_this_clone(local):
        report.ok(f'MCP server tia, for this folder; {elsewhere}')
    else:
        report.lack(f'MCP server tia: in this folder it is registered for {script_of(local) or "another command"}; left as it is. To move it here: claude mcp remove --scope local tia, then run this again')


def plugin_installed(claude):
    """Claude Code has been seen to add an entry of project scope for clones and worktrees where sessions ran: only one of user scope serves every clone."""
    code, output = run(claude, 'plugin', 'list', '--json')
    if code:
        return False
    try:
        return any(p.get('id') == PLUGIN and p.get('scope') == 'user' for p in json.loads(output))
    except (ValueError, AttributeError):
        return False


def install_plugin(report, claude):
    if plugin_installed(claude):
        report.ok(f'plugin {PLUGIN}')
        return
    for what, command in (('adding its marketplace', ('plugin', 'marketplace', 'add', MARKETPLACE)), ('installing it', ('plugin', 'install', PLUGIN, '--scope', 'user'))):
        code, output = run(claude, *command)
        if code:
            report.lack(f'plugin {PLUGIN}: {what} failed:{output_lines(output)}')
            return
    report.done(f'plugin {PLUGIN} installed, user scope')


def check_tracked_settings(report):
    """A plugin command of project scope rewrites this tracked file, and has been seen to empty it."""
    try:
        enabled = (read_json(TRACKED_SETTINGS).get('enabledPlugins') or {}).get(PLUGIN)
    except ValueError as e:
        report.lack(f'.claude/settings.json: {e}')
        return
    if not enabled:
        report.lack(f'.claude/settings.json does not enable {PLUGIN}, so a Claude Code session here goes without it. To bring it back: git restore .claude/settings.json')


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


def set_status_line(report):
    user_file = user_settings_file()
    try:
        user = read_json(user_file)
    except ValueError as e:
        report.lack(f'status line: {e}')
        return
    clone = clone_of(user.get('statusLine'))
    if clone and same_path(clone, CLONE):
        report.ok(f'status line: the TIA row, in {user_file}')
        return
    if clone:
        report.ok(f"status line: the TIA row of {clone}, left as it is. To make it this clone's: remove statusLine from {user_file}, then run this again")
        return
    if 'statusLine' in user:
        report.ok(f'status line: your own, left as it is. For the TIA row in it too, it can run {status_command(CLONE)}, '
                  f'which prints the row or nothing: "Status line" in {CLONE / "TiaAgentStatus" / "README.md"}')
        return
    user['statusLine'] = {'type': 'command', 'command': status_command(CLONE), 'refreshInterval': 5}
    try:
        write_json(user_file, user, ascii_only=False)
    except OSError as e:
        report.lack(f'status line: writing failed: {e}')
        return
    report.done(f'status line: the TIA row, in {user_file}')


def warn_on_long_path(report, root):
    room = (ARCHIVE_LIMIT - len(root.rstrip('\\')) - ARCHIVE_PATH_AROUND_NAMES) // 2
    if room < PROJECT_NAME_WANTED:
        report.warn(f'projectsRoot is long: TIA refuses an archive path over {ARCHIVE_LIMIT} characters, and this folder leaves room for a project name of {max(room, 0)} characters')


def settle_projects_root(report, answer):
    """Stores the answer and keeps the allow rules on the folder. Reads all first: a file that cannot be read stops it with nothing written."""
    user_file = user_settings_file()
    try:
        bridge = read_bridge_settings()
        user = read_json(user_file)
        allow = ensure_allow_list(user, user_file)
        stored = bridge.get('projectsRoot')
        root = normal_root(answer or stored) if answer or stored else None
    except ValueError as e:
        report.lack(f'projectsRoot: {e}')
        return
    if not root:
        report.question = (f'Where should the project repos live? The default is {Path.home() / "TIA-Projects"}. '
                           'Ask the user, then run this again with --projects-root "<path>", the default too.')
        return
    changed = not (stored and same_path(stored, root))
    if not changed:
        root = normal_root(stored)
    old_rules = allow_rules(normal_root(stored)) if changed and is_full_path(stored) else []
    kept = [r for r in allow if r not in old_rules]
    updated = kept + [r for r in allow_rules(root) if r not in kept]
    try:
        if changed:
            bridge['projectsRoot'] = root
            write_json(BRIDGE_SETTINGS, bridge, ascii_only=True)  # Windows PowerShell 5.1 reads a file with no byte order mark as ANSI
        if updated != allow:
            user['permissions']['allow'] = updated
            write_json(user_file, user, ascii_only=False)
    except OSError as e:
        report.lack(f'projectsRoot: writing failed: {e}')
        return
    if not changed:
        report.ok(f'projectsRoot {stored}. To change it: --projects-root "<path>"')
    elif stored:
        report.done(f'projectsRoot changed from {stored} to {root}. No repo moved: those in the old folder stay there. A bridge already running keeps the old value until it restarts. Another clone on the old folder loses these rules, as they are per user: run setup in it to bring them back')
    else:
        report.done(f'projectsRoot {root}, in {BRIDGE_SETTINGS}')
    print(f'         Setup makes no folder there: the bridge makes {root}\\_bridge\\sessions each time it starts; with Claude Code, in every new session and at claude mcp get tia.')
    git_form = f'git -C "{forward_slashes(root)}/<repo>"'
    (report.ok if updated == allow else report.done)(f'Claude Code allow rules for read, edit and git in that folder, in {user_file}. Git goes by {git_form}: with a backslash or a cd first it asks')
    warn_on_long_path(report, root)


def check_tia(report):
    """As the bridge finds it: tiaRoot of its settings, the Openness API of V20 under it (Import-Openness, TiaBridge\\Tia.ps1)."""
    try:
        tia_root = read_bridge_settings().get('tiaRoot') or DEFAULT_TIA_ROOT
    except ValueError:
        return  # settle_projects_root names the file
    if (Path(tia_root) / 'PublicAPI' / 'V20' / 'Siemens.Engineering.dll').exists():
        report.ok(f'TIA Portal V20 with TIA Openness, {tia_root}')
    else:
        report.lack_for_person(f'TIA Portal V20 with TIA Openness: not found in {tia_root}',
                               f'Install TIA Portal V20 with the TIA Openness option. If V20 is in another folder, set tiaRoot in {BRIDGE_SETTINGS}.')


def check_openness_group(report):
    """The groups of this logon, as the bridge's Test-OpennessGroup sees them: a user added since then counts only after logging on again."""
    # By its folder: in Git Bash the first whoami on the PATH is Git's own, which ignores these arguments.
    whoami = shutil.which('whoami', path=os.path.join(os.environ['SystemRoot'], 'System32'))
    code, output = run(whoami, '/groups', '/fo', 'csv', '/nh') if whoami else (127, '')
    if code == 0 and re.search(r'^"(?:[^"\\]*\\)?' + OPENNESS_GROUP + '"', output, re.IGNORECASE | re.MULTILINE):
        report.ok(f"the Windows group '{OPENNESS_GROUP}'")
    else:
        report.lack_for_person(f"the Windows group '{OPENNESS_GROUP}': TIA refuses Openness to a user outside it",
                               f"Join the Windows group '{OPENNESS_GROUP}' (an administrator or IT adds you), then log off and on.")


def main_tree_if_worktree():
    """The main working tree when this is a linked worktree of it, else None. Git absent or no repo: None, set_hook_path names those."""
    code, output = run('git', 'rev-parse', '--path-format=absolute', '--git-dir', '--git-common-dir')
    lines = output.split('\n')[:2]
    if code or len(lines) != 2 or same_path(lines[0], lines[1]):
        return None
    return str(Path(lines[1]).parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description='First setup of a clone, also its check.')
    parser.add_argument('--projects-root', metavar='path', help='the folder of the project repos (TiaBridge\\settings.json projectsRoot)')
    args = parser.parse_args(argv)
    main_tree = main_tree_if_worktree()
    if main_tree:
        print(f'refused  this is a worktree of {main_tree}. A worktree needs only uv sync; the server and the settings belong to the main tree, so run setup there.')
        return 1
    report = Report()
    check_git(report)
    set_hook_path(report)
    claude = shutil.which('claude')
    if claude:
        report.ok('Claude Code')
        register_bridge(report, claude)
        install_plugin(report, claude)
    check_tracked_settings(report)
    set_status_line(report)
    settle_projects_root(report, args.projects_root)
    check_tia(report)
    check_openness_group(report)
    print('\nA person does these, once:')
    agent_step = (f'If a session in {CLONE} ran this setup, end it and run claude --continue there: it comes back with that conversation and its task, now with the server, so tell it to go on. '
                  f'Otherwise start a new session in {CLONE}. Accept its trust prompt and approve the plugin if it asks: a session started before this run has neither the server nor the plugin. There, tia_status shows that the bridge starts.' if claude else
                  f'claude is not on the PATH, so this run did not register the MCP server tia or the plugin {PLUGIN}. To add them, install Claude Code (https://code.claude.com/docs), then run this again in a new terminal. '
                  f'Tested with Claude Code only: no other agent has been tried. To try one, give it this command to start the bridge: {subprocess.list2cmdline(BRIDGE_COMMAND)}')
    for step in report.person_steps + [agent_step, 'At the first connect, TIA asks whether to allow access: answer Yes.']:
        print(f'- {step}')
    if report.question:
        print(f'\nQuestion: {report.question}')
    if report.missing:
        return 1
    return 3 if report.question else 0


if __name__ == '__main__':
    sys.exit(main())
