"""Start, watch and close the agent sessions that work on tickets. Needs git and claude; herdr when you run inside it.

    python -X utf8 tools/session/session.py start <ticket file> --coordinator <who> [--beside <text>] [--allow-tia] [--allow-browser] [-- <claude args>]
    python -X utf8 tools/session/session.py audit <name> [--allow-tia] [--allow-browser] [-- <claude args>]
    python -X utf8 tools/session/session.py watch [--effort <folder>] [--first] [--timeout <seconds>]
    python -X utf8 tools/session/session.py prompt <name> <text> | --file <file> | --implement
    python -X utf8 tools/session/session.py read <name> [--lines <n>]
    python -X utf8 tools/session/session.py list [--resume]
    python -X utf8 tools/session/session.py close <name> [--session-only] [--remove-tree]
    python -X utf8 tools/session/session.py merge <name> [--keep-tree]
    python -X utf8 tools/session/session.py check [file ...]

Run the main working tree's tool with its .venv, from there. `<name>` is <prefix><NN> by the `Sessions:` line of the effort's map, or <effort><NN>. Each
command's --help has its options. Exit code 0 is done, 1 refused or failed, 3 a session is not ready for what comes next.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'dashboard'))    # the board reads a ticket's head

from board import read_ticket
from control_chars import describe, scan
from store import SessionError, Store, record_hook, record_in, write_json, write_state
from terminals import ADAPTERS, NOT_READ, choose, report_resume
from watching import NO_GUARDS_TEXT, Watcher, not_asked, status_of

CLOSED = {'done', 'resolved', 'wontfix'}
BASE = 'main'
READY_SECONDS = 900
LOOK_SECONDS = 5
# Every name git reads a repo from, as git rev-parse --local-env-vars lists them (a test holds this list to git's).
# Left by a parent, git prefers them to -C: it would act on the parent's repo.
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')
ASK_BY_TURN_END = 'AskUserQuestion'
BRIDGE = 'mcp__tia__*'
BROWSER_SERVER = {'type': 'stdio', 'command': 'npx', 'args': ['@playwright/mcp@latest']}
IMPLEMENT = '/mattpocock-skills:implement'
REVIEW_PAGE = HERE.parent / 'dashboard' / 'review_page.py'
ENVIRONMENT_FILES = ('uv.lock', 'pyproject.toml')    # what uv sync makes the .venv from
HOOK_TAIL = 15    # lines of a failed hook's output that merge shows
LEFT_BY_TOOLS = ('.playwright-mcp', 'TiaArchiveCompare/window/bin')    # a browser's output; an old build of the window
# The guard on pushing, three per shell tool. It matches a command's text: see .claude/skills/coordinate/SESSIONS.md.
PUSH_RULES = [f'{tool}({rule})' for tool in ('Bash', 'PowerShell') for rule in ('git push:*', 'git * push *', 'git * push')]


class NotReady(SessionError):
    """The session is there, but not ready for the prompt that comes next."""


def git_env():
    """The environment without what git gives a hook: with it, git -C <another repo> would act on this one."""
    return {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}


def run_git(*args, cwd):
    done = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', env=git_env())
    return done.returncode, done.stdout, done.stderr


def folder_key(path):
    """One spelling per folder, to compare them."""
    return os.path.normcase(os.path.abspath(path))


def inside(path, folder):
    """Whether path is this folder or lies under it."""
    return Path(folder_key(path)).is_relative_to(folder_key(folder))


def stamp_now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def ticket_status(path):
    return status_of(Path(path).read_bytes().decode('utf-8', 'replace'))


def running_executables():
    """The path of the program of every running process Windows shows to this user, as Win32_Process has it."""
    command = ('[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = "Stop"; '
               'Get-CimInstance Win32_Process | ForEach-Object { $_.ExecutablePath } | Where-Object { $_ }')
    try:
        done = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SessionError(f'the process list could not be read, nothing of the tree removed: {error}') from None
    paths = done.stdout.split('\n') if done.stdout else []
    paths = [path.strip() for path in paths if path.strip()]
    if done.returncode or not paths:
        raise SessionError(f'the process list could not be read, nothing of the tree removed: {done.stderr.strip()}')
    return paths


def folder_held(folder):
    """Whether a process stands in the folder, holds a file under it or runs a program from it. git worktree remove finds out only after
    deleting what it can. The process list shows a program running from it, which a rename does not: Windows lets a folder be renamed
    under a running image. A rename shows the others, also in a subfolder; it deletes nothing and is put back at once. A process this
    user may not read (an elevated one) can still go unseen: the remove then stops half way, and close says what is left."""
    folder = Path(folder)
    if not folder.exists():
        return False
    if any(inside(path, folder) for path in running_executables()):
        return True
    probe =folder.with_name(folder.name + '.close-check')
    try:
        os.rename(folder, probe)
    except PermissionError:
        return True
    except OSError as error:
        raise SessionError(f'{folder} could not be checked, nothing done: {error}') from None
    for attempt in range(20):
        try:
            os.rename(probe, folder)
            return False
        except OSError as error:
            if attempt == 19:
                raise SessionError(f'{folder} now stands at {probe}: it could not be put back: {error}') from None
            time.sleep(0.1)


def status_path(status_line):
    """The path a line of git status --porcelain names, without quotes or a slash at its end."""
    return status_line[3:].strip('"').rstrip('/')


def made_again(ignored_line):
    """Whether a line of git status --ignored names what uv sync and Python make again."""
    parts = status_path(ignored_line).split('/')
    return parts[0] == '.venv' or parts[-1] == '__pycache__'


def untracked_under(status_line, folders):
    """Whether a line of git status --ignored names an untracked or ignored file in one of the folders."""
    path = status_path(status_line)
    return status_line[:2] in ('??', '!!') and any(path == folder or path.startswith(folder + '/') for folder in folders)


def folder_as_written(tree, folder):
    """Whether tree/folder leads to that folder in the tree: each part on the way a real folder, no link or junction, named in the
    case written. Windows ignores case, so .../Bin would pass for .../bin."""
    path = Path(tree)
    for part in folder.split('/'):
        try:
            if part not in os.listdir(path):
                return False
        except OSError:    # a tree already gone
            return False
        path = path / part
        if path.is_symlink() or path.is_junction() or not path.is_dir():
            return False
    return os.path.realpath(path) == os.path.join(os.path.realpath(tree), *folder.split('/'))


def hook_settings(folder):
    """The session's hooks, as a settings file for claude --settings. Forward slashes: Claude Code runs them through a shell."""
    command = f'"{Path(sys.executable).as_posix()}" -X utf8 "{Path(__file__).resolve().as_posix()}" hook "{Path(folder).as_posix()}"'
    entry = [{'hooks': [{'type': 'command', 'command': command}]}]
    return {'hooks': {event: entry for event in ('SessionStart', 'UserPromptSubmit', 'Stop', 'StopFailure', 'Notification')}}


def mangled_by_git_bash(text, env=os.environ):
    """Git Bash turns an argument that starts with / into a Windows path before Python sees it."""
    return bool(env.get('MSYSTEM')) and bool(re.match(r'^[A-Za-z]:[\\/]([^ ]*[\\/])?(Program Files[\\/])?Git[\\/]', text))


class Sessions:
    def __init__(self, main_tree, terminal_for=None, sleep=time.sleep):
        self.main = Path(main_tree)
        self.scratch = self.main / '.scratch'
        self.store = Store(self.scratch)
        self.terminal_for = terminal_for or (lambda kind: ADAPTERS[kind]())
        self.sleep = sleep

    def git(self, *args, cwd=None):
        return run_git(*args, cwd=cwd or self.main)

    def must_git(self, *args, cwd=None):
        code, out, err = self.git(*args, cwd=cwd)
        if code:
            raise SessionError(f'git {" ".join(args)}: {(err or out).strip()}')
        return out

    # --- what a ticket's path says

    def ticket_parts(self, ticket):
        """(effort, number, slug) of a ticket at <.scratch>/<effort>/issues/<NN>-<slug>.md"""
        path = Path(os.path.abspath(ticket))
        match = re.match(r'^(\d+)-(.+)\.md$', path.name)
        if not match or path.parent.name != 'issues' or path.parent.parent.parent != Path(os.path.abspath(self.scratch)):
            raise SessionError(f'{path} is not a ticket: they are at {self.scratch}\\<effort>\\issues\\<NN>-<slug>.md')
        return path.parent.parent.name, match.group(1), match.group(2)

    def session_name(self, effort, number):
        try:
            text = (self.scratch / effort / 'map.md').read_text(encoding='utf-8').replace('**', '')
            prefix = re.search(r'(?m)^Sessions:\s*(\S+)', text).group(1)
        except (OSError, AttributeError):
            prefix = effort
        return prefix + number

    def worktrees(self):
        """{folder: branch} of every worktree."""
        found, folder = {}, None
        for line in self.must_git('worktree', 'list', '--porcelain').splitlines():
            if line.startswith('worktree '):
                folder = folder_key(line[len('worktree '):])
                found[folder] = ''
            elif line.startswith('branch refs/heads/'):
                found[folder] = line[len('branch refs/heads/'):]
        return found

    def ensure_tree(self, tree, branch):
        """Makes the worktree, or finds it on its branch: (whether this call made the tree, and the branch)."""
        known = self.worktrees().get(folder_key(tree))
        if known is not None:
            if known != branch:
                raise SessionError(f'{tree} is on branch {known or "(no branch)"}, not {branch}: nothing started')
            return False, False
        if Path(tree).exists():
            raise SessionError(f'{tree} is in the way and is not a worktree of this clone: nothing started')
        has_branch = self.git('rev-parse', '--verify', '--quiet', f'refs/heads/{branch}')[0] == 0
        self.must_git('worktree', 'add', str(tree), *([branch] if has_branch else ['-b', branch, BASE]))
        return True, not has_branch

    # --- start

    def mcp_servers(self, allow_tia, allow_browser):
        """The MCP servers a session asked for, by name. The bridge is always this clone's, started as first setup registers it
        (tools/setup/setup.py); a plain claude may have another clone's registered."""
        bridge = {'type': 'stdio', 'command': 'powershell.exe',
                  'args': ['-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(self.main / 'TiaBridge' / 'TiaBridge.ps1')]}
        return {**({'tia': bridge} if allow_tia else {}), **({'playwright': BROWSER_SERVER} if allow_browser else {})}

    def agent_args(self, folder, servers, extra):
        """With --strict-mcp-config, only what --mcp-config names starts: tried with a real claude, for a server of a plugin, of the user
        and of claude.ai. Only Claude in Chrome stays listed in a session with a terminal, with no process of its own, so --no-chrome.
        The servers go in a file, as settings do: a restart repeats these arguments, so they stay short and need no quoting."""
        settings = Path(folder) / 'settings.json'
        write_json(settings, hook_settings(folder))
        mcp_args = ['--strict-mcp-config', '--no-chrome']
        if servers:
            config = Path(folder) / 'mcp.json'
            write_json(config, {'mcpServers': servers})
            mcp_args += ['--mcp-config', str(config)]
        denied = [ASK_BY_TURN_END, *([] if 'tia' in servers else [BRIDGE]), *PUSH_RULES]
        return ['--add-dir', str(self.main), *mcp_args, '--settings', str(settings), '--disallowedTools', *denied, *extra]

    def open_session(self, record, prompt, servers, extra):
        """Opens the terminal, and only then does the record count as open: a watcher has nothing to look at before. Until then it
        reads closed, which is also what a start that fails or dies leaves. The tree stays, and the record knows who made it."""
        folder = self.store.folder(record['name'])
        record['folder'] = str(folder)
        write_state(folder, 'sent')
        args = self.agent_args(folder, servers, extra)
        record['args'] = args    # its first prompt's hook reads them, while the terminal is still opening
        self.store.save({**record, 'closed': 'did not start'})
        record.update(self.terminal(record).open(record, args, prompt) or {})
        self.store.save(record)
        return record

    def terminal(self, record):
        return self.terminal_for(record['terminal'])

    def restore_said(self, record):
        """What a start says of a command its terminal will not take for a restart: the session starts all the same."""
        refused = self.terminal(record).restore_refused(record['args'])
        return [f'herdr will refuse the command that brings it back after a restart ({refused}): after one it runs without its '
                'guards, and list says so'] if refused else []

    def check_free(self, name):
        if self.store.exists(name) and not self.store.load(name).get('closed'):
            raise SessionError(f'{name} is open: `prompt` it, or `close` it first')

    def start(self, ticket, coordinator, terminal=None, name=None, branch=None, worktree=None, beside=None,
              allow_tia=False, allow_browser=False, extra=(), implement=True, timeout=READY_SECONDS):
        ticket = Path(os.path.abspath(ticket))
        effort, number, slug = self.ticket_parts(ticket)
        status = ticket_status(ticket)
        if status in CLOSED:
            raise SessionError(f'{ticket.name} is {status}: nothing started')
        name = name or self.session_name(effort, number)
        self.check_free(name)
        branch = branch or f'feat/{effort}-{number}-{slug}'
        if worktree and not os.path.isabs(worktree):
            raise SessionError(f'--worktree {worktree} is not absolute: a relative path has landed inside the clone. Nothing started')
        tree = Path(worktree or self.main.parent / f'{self.main.name}-worktrees' / f'{effort}-{number}')
        if inside(tree, self.main):
            raise SessionError(f'{tree} is inside the clone: nothing started')
        made_tree, made_branch = self.ensure_tree(tree, branch)
        if self.store.exists(name):    # the same session again: what it made earlier stays its own
            earlier = self.store.load(name)
            made_tree = made_tree or bool(earlier.get('made_tree') and folder_key(earlier['worktree']) == folder_key(tree))
            made_branch = made_branch or bool(earlier.get('made_branch') and earlier['branch'] == branch)
        terminal = terminal or choose()
        prompt = f'/ticket {ticket} worktree {tree} branch {branch} coordinator {coordinator}'
        if beside:
            prompt += f' beside {beside}'
        record = self.open_session({
            'name': name, 'ticket': str(ticket), 'effort': effort, 'worktree': str(tree), 'branch': branch,
            'terminal': terminal, 'made_tree': made_tree, 'made_branch': made_branch, 'extra': list(extra), 'started': stamp_now()},
            prompt, self.mcp_servers(allow_tia, allow_browser), list(extra))
        said = [f'{name}: {terminal}, in {tree}, on {branch}', *self.restore_said(record)]
        if terminal == 'print':
            said.append(f'Once it reports ready, type: {self.implement_prompt(record)}')
        elif implement:
            self.wait_ready(record, timeout)
            self.implement(name)
            said.append('it reported ready and has its implement prompt')
        return '\n'.join(said)

    def wait_ready(self, record, timeout):
        """Until the turn has ended with the ticket claimed and the session naming its implement prompt, as the ticket skill has it
        do. A ticket claimed earlier says nothing alone. Anything else stops the wait, with what the session said."""
        name, waited = record['name'], 0
        terminal = self.terminal(record)
        next_step = f'When it is settled: prompt {name} --implement'
        while True:
            state = self.store.state(name)
            ended = state['state'] == 'ended' and not state.get('background')
            if ended and ticket_status(record['ticket']) == 'claimed' and IMPLEMENT in state['message']:
                return
            if ended:
                raise NotReady(f'{name} ended its turn without reporting ready. It said:\n{state["message"]}\n{next_step}')
            if state['state'] in ('asking', 'failed'):
                raise NotReady(f'{name} {state["state"]}: {state["message"]}\n{next_step}')
            if terminal.alive(record) is False:
                raise NotReady(f'{name} no longer runs, last state {state["state"]}. Read it: read {name}')
            if waited >= timeout:
                raise NotReady(f'{name} is not ready after {timeout} seconds, state {state["state"]}.\n{next_step}')
            self.sleep(1)
            waited += 1

    # --- use

    def open_record(self, name):
        """The record of an open session of exactly this name, or a refusal."""
        record = self.store.load(name)
        if record.get('closed'):
            raise SessionError(f'{name} is closed: nothing sent')
        return record

    def audit(self, name, terminal=None, extra=(), allow_tia=False, allow_browser=False):
        """A fresh session in the ticket's tree, with what came after -- for the ticket session unless given its own, and only the servers
        it asks for. Works from a closed record too: only its session has ended."""
        ticket_session = self.store.load(name)
        audit_name = 'audit' + name
        self.check_free(audit_name)
        extra = list(extra) or ticket_session.get('extra', [])
        terminal = terminal or choose()
        prompt = f'/audit {ticket_session["ticket"]} {ticket_session["branch"]} {ticket_session["worktree"]}'
        record = {k: ticket_session[k] for k in ('ticket', 'effort', 'worktree', 'branch', 'made_tree', 'made_branch')}
        record.update(name=audit_name, terminal=terminal, extra=extra, started=stamp_now())
        self.open_session(record, prompt, self.mcp_servers(allow_tia, allow_browser), extra)
        return '\n'.join([f'{audit_name}: {terminal}, in {record["worktree"]}', *self.restore_said(record)])

    def prompt(self, name, text):
        record = self.open_record(name)
        before = self.store.state(name)['mark']
        record.update(self.terminal(record).send(record, text) or {})
        self.store.save(record)
        if self.store.state(name)['mark'] == before:    # the session's own hook may already have answered
            write_state(self.store.folder(name), 'sent')
        return f'sent to {name}'

    @staticmethod
    def implement_prompt(record):
        return f'{IMPLEMENT} {record["ticket"]}'

    def implement(self, name):
        return self.prompt(name, self.implement_prompt(self.open_record(name)))

    def read(self, name, lines=60):
        record = self.store.load(name)
        state = self.store.state(name)
        shown = self.terminal(record).read(record, lines) if not record.get('closed') else '(closed)'
        return f'{shown}\n--- state {state["state"]}. Last message:\n{state["message"]}'

    def look_at(self, records):
        """What the terminals say of these sessions: ({name: (alive, guarded)}, {kind: why it was asked nothing more}). A kind is asked
        nothing more on this look once a question found it hung or down, and a pane that is no longer the session's says nothing of its guards."""
        terminals = {kind: self.terminal_for(kind) for kind in {record['terminal'] for record in records}}
        looks = {}
        for record in records:
            terminal = terminals[record['terminal']]
            lives = None if terminal.stopped else terminal.alive(record)
            looks[record['name']] = (lives, terminal.guarded(record) if lives and not terminal.stopped else None)
        return looks, {kind: terminal.stopped for kind, terminal in terminals.items() if terminal.stopped}

    def listing(self, resume=False):
        """A row per open session; with resume, under each the command that brings it back with its guards after a restart."""
        rows = []
        records = self.store.open_sessions()
        looks, stopped = self.look_at(records)
        signs = {False: f', RUNS WITHOUT ITS GUARDS: {NO_GUARDS_TEXT}', NOT_READ: ', its arguments could not be read'}
        for record in records:
            state = self.store.state(record['name'])['state']
            status = ticket_status(record['ticket']) if Path(record['ticket']).exists() else 'no ticket'
            sign = signs.get(looks[record['name']][1], '')
            rows.append(f'{record["name"]}: {state}, ticket {status}, {record["terminal"]}, {record["worktree"]}{sign}')
            if resume:
                rows += ['  ' + line for line in self.resume_lines(record)]
        rows += [not_asked(kind, why) for kind, why in sorted(stopped.items())]
        return '\n'.join(rows) or 'no open sessions'

    def resume_lines(self, record):
        """From its record and the id its hook last wrote down, so they hold with herdr down."""
        if not record.get('args'):
            return ['it COMES BACK WITHOUT ITS GUARDS: its record holds no arguments, so start it again with the command it was started with']
        return self.terminal(record).resume(record, self.store.session_id(record['name']))

    def watcher(self, efforts=()):
        for effort in efforts:
            if not (self.scratch / effort / 'issues').is_dir():
                raise SessionError(f'no effort {effort}: no folder {self.scratch / effort / "issues"}')
        return Watcher(self.scratch, self.store, self.look_at, efforts)

    # --- close

    def plan_tree(self, record, remove_tree):
        """Why the tree stays, or '' when it can go. Raises when going would lose something; nothing has been ended by then."""
        tree = Path(record['worktree'])
        others = [r['name'] for r in self.store.open_sessions()
                  if r['name'] != record['name'] and folder_key(r['worktree']) == folder_key(tree)]
        if others:
            return f'tree kept: {", ".join(others)} still works in it'
        if not (record.get('made_tree') or remove_tree):
            return f'tree and branch kept: `session start` did not make {tree}. Close with --remove-tree to remove them'
        if folder_key(tree) == folder_key(self.main):
            raise SessionError(f'{tree} is the main working tree: it is never removed')
        if any(inside(path, tree) for path in (Path.cwd(), sys.executable, __file__)):
            raise SessionError(f'this command runs from {tree}, which it would remove: its folder, Python or script. Run the main '
                               'working tree\'s tool with its .venv, from there')
        if not tree.exists() or folder_key(tree) not in self.worktrees():    # what an earlier close left: clear_tree says what it does
            return ''
        lost = self.lost(tree)
        if lost:
            raise SessionError(f'{tree} holds uncommitted changes or ignored files that git would delete unasked, nothing done. Commit '
                               'or move them, or close --session-only to end the session and keep the tree:\n' + '\n'.join(lost[:20]))
        branch = record['branch']
        if self.git('merge-base', '--is-ancestor', branch, BASE)[0]:
            raise SessionError(f'{branch} is not merged into {BASE}, nothing done. Merge it, or close --session-only to end the '
                               'session and keep the tree')
        if self.git('merge-base', '--is-ancestor', 'HEAD', BASE, cwd=tree)[0]:
            raise SessionError(f'HEAD of {tree} holds commits not merged into {BASE}, nothing done. Merge them, or close --session-only '
                               'to end the session and keep the tree')
        return ''

    def remove_tree(self, record, asked):
        """The tree, of a missing folder too (its entry and no other), and the branch when `start` made it or it was asked for."""
        return self.clear_tree(record) + ', ' + self.clear_branch(record, asked)

    def free_soon(self, tree):
        """Whether the folder is free, or gets so: a process that has just ended can still hold it."""
        for attempt in range(5):
            if not folder_held(tree):
                return True
            if attempt < 4:
                self.sleep(2)
        return False

    def what_is_left(self, record):
        tree, branch = Path(record['worktree']), record['branch']
        folder = f'folder {tree} with {len(list(tree.iterdir()))} entries' if tree.exists() else 'no folder'
        entry = 'worktree entry still listed' if folder_key(tree) in self.worktrees() else 'no worktree entry'
        there = self.git('rev-parse', '--verify', '--quiet', f'refs/heads/{branch}')[0] == 0
        return f'{folder}, {entry}, branch {branch} {"still there" if there else "gone"}'

    def clear_tree(self, record):
        """Removes the tree or says why not. A folder git no longer knows, as a remove that failed half way leaves it, goes only empty."""
        tree = Path(record['worktree'])
        existed = tree.exists()
        if folder_key(tree) in self.worktrees():
            if not self.free_soon(tree):
                raise SessionError(f'session ended, nothing of the tree removed: a process stands in {tree}. End it, then close again')
            lost = self.lost(tree) if existed else []    # what the session wrote as it ended
            if lost:
                raise SessionError(f'session ended, nothing of the tree removed: {tree} now holds uncommitted changes or ignored files. '
                                   'Commit or move them, then close again:\n' + '\n'.join(lost[:20]))
            cleared = self.clear_left_by_tools(record)
            code, out, err = self.git('worktree', 'remove', str(tree))
            if code:
                raise SessionError(f'session ended, git worktree remove failed: {(err or out).strip()}\nLeft: {self.what_is_left(record)}. '
                                   'End what holds it, then close again')
            if not existed:
                return f'folder {tree} was already gone, its entry removed'
            return f'removed {tree}' + (f', with what tools left in it: {", ".join(cleared)}' if cleared else '')
        if not existed:
            return 'tree already gone'
        entries = len(list(tree.iterdir()))
        if entries:
            return f'{tree} is no longer a worktree and holds {entries} entries: left alone, delete it by hand'
        try:
            tree.rmdir()
        except OSError as error:
            return f'{tree} is no longer a worktree and is empty, but could not be removed: {error}'
        return f'removed the empty folder {tree}'

    def left_by_tools(self, tree):
        """The folders of LEFT_BY_TOOLS in the tree that close deletes itself: found as written, with no link on the way, and holding
        no tracked file in any case of its name."""
        return [folder for folder in LEFT_BY_TOOLS
                if folder_as_written(tree, folder) and not self.must_git('ls-files', '--', f':(icase){folder}', cwd=tree).strip()]

    def lost(self, tree):
        """The lines of git status that removing the tree would lose: not what uv sync and Python make again, nor what close deletes."""
        to_delete = self.left_by_tools(tree)
        return [line for line in self.must_git('status', '--porcelain', '--ignored=matching', cwd=tree).splitlines()
                if not (made_again(line) or untracked_under(line, to_delete))]

    def clear_left_by_tools(self, record):
        """Deletes left_by_tools, and nothing else: git worktree remove refuses an untracked one. rmtree goes through no link in them."""
        tree, cleared = Path(record['worktree']), []
        for folder in self.left_by_tools(tree):
            path = tree / folder
            try:
                shutil.rmtree(path)
            except OSError as error:
                raise SessionError(f'session ended, {path} could not be deleted: {error}\nLeft: {self.what_is_left(record)}. '
                                   'End what holds it, then close again') from None
            cleared.append(folder)
        return cleared

    def clear_branch(self, record, asked):
        branch = record['branch']
        if not (record.get('made_branch') or asked):
            return f'branch {branch} kept: `session start` did not make it. Close with --remove-tree to remove it'
        if self.git('rev-parse', '--verify', '--quiet', f'refs/heads/{branch}')[0]:
            return f'branch {branch} already gone'
        code, out, err = self.git('branch', '-d', branch)
        return f'branch {branch} removed' if not code else f'branch {branch} kept: {(err or out).strip()}'

    def close(self, name, session_only=False, remove_tree=False):
        record = self.store.load(name)
        stays = 'tree and branch kept, as asked' if session_only else self.plan_tree(record, remove_tree)
        session_stands_there = not record.get('closed') and self.terminal(record).holds_tree(record)
        if not stays and not session_stands_there and folder_held(record['worktree']):
            raise SessionError(f'a process stands in {record["worktree"]}, nothing done. End it (a session of its own terminal ends '
                               'there), then close again, or close --session-only to end the session and keep the tree')
        said = [f'{name}: already closed'] if record.get('closed') else [f'{name}: ' + self.terminal(record).end(record)]
        record['closed'] = stamp_now()
        self.store.save(record)
        said.append(stays or self.remove_tree(record, remove_tree))
        return '\n'.join(said)

    # --- merge

    def merge(self, name, keep_tree=False):
        """The coordinator's merge of a ticket the audit passed: rebase, hook, fast-forward, record, pages down, close. It forces
        nothing and stops at the first step that fails, with tree and branch kept; a step after the merge that fails names what is
        left to do. keep_tree ends the sessions and keeps tree and branch, as close --session-only does."""
        record = self.store.load(name)
        tree, branch, ticket = Path(record['worktree']), record['branch'], Path(record['ticket'])
        stopped = lambda why: SessionError(f'merge {name} stopped: {why}. Tree and branch kept')
        self.merge_ready(record, stopped, keep_tree)
        said = []
        for attempt in (1, 2):
            said += self.rebase(tree, stopped)
            said.append(self.branch_hook(name, tree, stopped))
            code, out, err = self.git('merge', '--ff-only', branch)
            if not code:
                break
            if not self.git('merge-base', '--is-ancestor', BASE, branch)[0]:
                raise stopped(f'git merge --ff-only {branch} in {self.main}: {(err or out).strip()}')
            if attempt == 2:
                raise stopped(f'{BASE} moved again during the second hook run')
            said.append(f'{BASE} moved during the hook: once more')
        merged = self.must_git('rev-parse', '--short', BASE).strip()
        said.append(f'merged {name}: {merged} on {BASE}')
        closing = self.sessions_in(tree, last=name)
        flag = ' --session-only' if keep_tree else ''
        steps = [(f'Status: done in {ticket}, and "{merge_entry(merged)}" under ## Comments',
                  lambda: record_merge(ticket, merged) or f'{ticket.name}: done')]
        steps += [(f'review_page.py --done "{title}"', lambda title=title: self.take_down(title))
                  for title in pages_of(ticket, [*closing, 'audit' + name])]
        steps += [(f'session.py close {other}{flag}', lambda other=other: self.close(other, session_only=keep_tree)) for other in closing]
        for index, (step, run) in enumerate(steps):
            try:
                done = run()
            except (SessionError, OSError, UnicodeError) as error:    # a ticket not in UTF-8 is left as it is
                left = '\n'.join(f'  {later}' for later, _ in steps[index:])
                raise SessionError('\n'.join(said) + f'\nmerge {name}: {step} failed: {error}\nLeft to do, from the main working '
                                   f'tree:\n{left}') from None
            if done:
                said.append(done)
        return '\n'.join(said)

    def take_down(self, title):
        """review_page.py --done: what it says when a page of that title was up, '' when there is none."""
        done = subprocess.run([sys.executable, '-X', 'utf8', str(REVIEW_PAGE), '--done', title, '--root', str(self.scratch)],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        if done.returncode and done.stderr.startswith('No review page named'):
            return ''
        if done.returncode:
            raise SessionError((done.stderr or done.stdout).strip())
        return f'page {title} taken down'

    def sessions_in(self, tree, last):
        """The open sessions in the tree, and last at the end, open or not: its close takes the tree, as the others' leave it."""
        return [r['name'] for r in self.store.open_sessions() if folder_key(r['worktree']) == folder_key(tree) and r['name'] != last] + [last]

    def merge_ready(self, record, stopped, keep_tree):
        """What the merge needs before its first step, so that a refusal changes nothing."""
        tree, branch, ticket = Path(record['worktree']), record['branch'], Path(record['ticket'])
        status = ticket_status(ticket) if ticket.exists() else 'missing'
        if status != 'in-review':
            raise stopped(f'ticket {ticket.name} is {status}, not in-review')
        here = self.must_git('branch', '--show-current').strip()
        if here != BASE:
            raise stopped(f'the main working tree {self.main} is on {here or "no branch"}, not {BASE}')
        if self.worktrees().get(folder_key(tree)) != branch:
            raise stopped(f'{tree} is not a worktree on {branch}')
        if self.must_git('status', '--porcelain', '--untracked-files=no', cwd=tree).strip():
            raise stopped(f'{tree} holds uncommitted changes')
        if not keep_tree and any(inside(path, tree) for path in (Path.cwd(), sys.executable, __file__)):
            raise stopped(f'this command runs from {tree}, which close removes: run the main working tree\'s tool, from there')

    def rebase(self, tree, stopped):
        """Onto main, as the audit's step 2: a conflict is undone and named, and a change to the environment synced."""
        before = self.must_git('rev-parse', 'HEAD', cwd=tree).strip()
        code, out, err = self.git('rebase', BASE, cwd=tree)
        if code:
            conflicts = self.git('diff', '--name-only', '--diff-filter=U', cwd=tree)[1].split()
            self.git('rebase', '--abort', cwd=tree)
            found = f'conflicts in {", ".join(conflicts)}' if conflicts else (err or out).strip()
            raise stopped(f'rebase onto {BASE} failed and was undone, {found}. Rebase it as the audit does, then merge again')
        rebased = self.must_git('rev-parse', 'HEAD', cwd=tree).strip()
        if rebased == before:
            return [f'already on {BASE}']
        if self.git('diff', '--quiet', before, rebased, '--', *ENVIRONMENT_FILES, cwd=tree)[0]:
            return [f'rebased onto {BASE}', self.sync_environment(tree, stopped)]
        return [f'rebased onto {BASE}']

    def sync_environment(self, tree, stopped):
        """uv sync in the tree, whose .venv the hook runs on, as the audit runs it after its rebase."""
        uv = shutil.which('uv')
        if not uv:
            raise stopped(f'the rebase changed {" or ".join(ENVIRONMENT_FILES)}, and no uv is on the PATH: run uv sync in {tree}, '
                          'then merge again')
        done = subprocess.run([uv, 'sync'], cwd=tree, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if done.returncode:
            raise stopped(f'uv sync in {tree} failed: {(done.stderr or done.stdout).strip()}')
        return 'uv sync: the rebase changed the environment'

    def branch_hook(self, name, tree, stopped):
        """sh .githooks/pre-commit main in the tree, as the audit runs it: its stamp from the audit's pass skips the suites."""
        log = self.store.folder(name) / 'merge-hook.log'
        with open(log, 'w', encoding='utf-8', errors='replace') as out:
            done = subprocess.run([git_sh(), '.githooks/pre-commit', BASE], cwd=tree, env=git_env(), stdout=out, stderr=subprocess.STDOUT)
        lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
        if done.returncode:
            raise stopped(f'the hook failed, its output in {log}:\n' + '\n'.join(lines[-HOOK_TAIL:]))
        return f'hook passed: {lines[-1] if lines else "(no output)"}'


def git_sh():
    """Git's own sh: Git for Windows puts only git on the PATH of a PowerShell, sh stays in its bin folder."""
    found = shutil.which('sh')
    if found:
        return found
    code, out, err = run_git('--exec-path', cwd=HERE)
    git_root = Path(out.strip()).parents[2] if not code else None    # <Git>/mingw64/libexec/git-core
    for candidate in ([git_root / 'bin' / 'sh.exe', git_root / 'usr' / 'bin' / 'sh.exe'] if git_root else []):
        if candidate.is_file():
            return str(candidate)
    raise SessionError('no sh found, on the PATH or beside git: the hook needs it')


def pages_of(ticket, session_names):
    """The titles a ticket's review page may have: its Review page: line, read as the dashboard reads it, and its sessions' names."""
    ticket = Path(ticket)
    named = read_ticket(ticket, ticket.parent)['review']    # the second argument only places the ticket for the board's link
    return list(dict.fromkeys(title for title in [named, *session_names] if title))


def merge_entry(merged):
    return f'merge, {datetime.now().date().isoformat()}: {merged} on {BASE}.'


def record_merge(ticket, merged):
    """Status: done in the ticket's head, and the commit main points at as the newest entry under ## Comments."""
    text = Path(ticket).read_bytes().decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    text = re.sub(r'(?m)^Status:[^\r\n]*', 'Status: done', text, count=1)
    entry = merge_entry(merged)
    if not re.search(r'(?m)^## Comments\s*$', text):
        text = text.rstrip() + f'{newline}{newline}## Comments{newline}'
    Path(ticket).write_bytes((text.rstrip() + f'{newline}{newline}{entry}{newline}').encode('utf-8'))


def main_tree():
    """The main working tree of the clone this tool is in, which its worktrees share .scratch with."""
    code, out, err = run_git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=HERE)
    if code:
        raise SessionError(f'not in a git clone: {err.strip()}')
    return Path(out.strip()).parent


def text_of(args):
    if args.file:
        return Path(args.file).read_text(encoding='utf-8-sig')    # PowerShell 5.1 writes a byte order mark
    if not args.text:
        raise SessionError('give the text, --file or --implement')
    if mangled_by_git_bash(args.text):
        raise SessionError(f'Git Bash turned the leading / into a path: {args.text}\nPut the prompt in a file and use --file')
    return args.text


def watch(sessions, args, out=print):
    """--timeout counts the time of its looks too: on a herdr that does not answer, each takes seconds."""
    started = time.monotonic()
    watcher = sessions.watcher(args.effort or [])
    out(f'watching: {len(watcher.sessions())} sessions, their tickets, review answers, answers on ticket pages')
    out(sessions.listing())
    while True:
        events = watcher.look()
        for event in events:
            out(event)
        sys.stdout.flush()
        if events and args.first:
            return 0
        left = None if args.timeout is None else args.timeout - (time.monotonic() - started)
        if left is not None and left <= 0:
            out('no event' if args.first else 'watch ended')
            return 0
        time.sleep(LOOK_SECONDS if left is None else min(LOOK_SECONDS, left))


def check(sessions, args, out=print):
    missing = [f for f in args.files if not Path(f).is_file()]
    if missing:
        raise SessionError('no such file: ' + ', '.join(missing))
    found = scan(sessions.scratch, args.files or None)
    for path, finding in found:
        out(describe(path, finding))
    out(f'{len(found)} control characters' if found else 'no control characters')
    return 1 if found else 0


def parser():
    top = argparse.ArgumentParser(prog='session', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = top.add_subparsers(dest='command', required=True)

    start = commands.add_parser('start', help='make the worktree, open a session, send /ticket and then implement')
    start.add_argument('ticket')
    start.add_argument('--coordinator', required=True, help='who the session reports to')
    start.add_argument('--beside', help='the sessions beside it and their files')
    start.add_argument('--name', help='session name instead of the one from the map')
    start.add_argument('--branch', help='branch instead of feat/<effort>-<NN>-<slug>')
    start.add_argument('--worktree', help='folder instead of <clone>-worktrees\\<effort>-<NN>')
    start.add_argument('--terminal', choices=sorted(ADAPTERS), help='default: herdr inside a herdr pane, otherwise headless')
    start.add_argument('--allow-tia', action='store_true', help='start the bridge: only for a ticket that grants a background session')
    start.add_argument('--allow-browser', action='store_true', help='start Playwright: for a ticket that needs a browser')
    start.add_argument('--no-implement', action='store_true', help='send /ticket only, do not wait')
    start.add_argument('--timeout', type=int, default=READY_SECONDS, help='seconds to wait for it to report ready')

    audit = commands.add_parser('audit', help='a fresh session audit<name> in the same tree, sent /audit')
    audit.add_argument('name')
    audit.add_argument('--terminal', choices=sorted(ADAPTERS))
    audit.add_argument('--allow-tia', action='store_true', help='start the bridge; the ticket session having it gives the audit nothing')
    audit.add_argument('--allow-browser', action='store_true', help='start Playwright; the ticket session having it gives the audit nothing')

    watching = commands.add_parser('watch', help='one line per event; keeps its baseline, so re-arming loses nothing')
    watching.add_argument('--effort', action='append', help='only this effort, with all its tickets; repeat for more')
    watching.add_argument('--first', action='store_true', help='exit after the first events')
    watching.add_argument('--timeout', type=int, help='exit after these seconds')

    prompt = commands.add_parser('prompt', help='send a session a prompt; a typed name that is not open sends nothing')
    prompt.add_argument('name')
    prompt.add_argument('text', nargs='?')
    prompt.add_argument('--file', help='the prompt in a file: for double quotes in PowerShell, or a leading / in Git Bash')
    prompt.add_argument('--implement', action='store_true', help='send the ticket its /mattpocock-skills:implement')

    read = commands.add_parser('read', help='what a session shows, its state and last message')
    read.add_argument('name')
    read.add_argument('--lines', type=int, default=60)

    listed = commands.add_parser('list', help='the open sessions')
    listed.add_argument('--resume', action='store_true', help='under each, the command that brings it back with its guards after a restart')

    closing = commands.add_parser('close', help='end a session; after the merge also remove its tree and branch')
    closing.add_argument('name')
    closing.add_argument('--session-only', action='store_true', help='end the session, keep tree and branch')
    closing.add_argument('--remove-tree', action='store_true', help='also a tree and branch `start` did not make; never one with uncommitted changes')

    merging = commands.add_parser('merge', help='after the audit passed: rebase, hook, fast-forward main, ticket done, page down, close')
    merging.add_argument('name', help='the ticket session; its audit session is closed with it')
    merging.add_argument('--keep-tree', action='store_true', help='end the sessions, keep tree and branch: for a ticket that owes a real run')

    checking = commands.add_parser('check', help='control characters in tickets and notes; only reports')
    checking.add_argument('files', nargs='*', help='default: every .md under .scratch')

    hook = commands.add_parser('hook', help=argparse.SUPPRESS)    # what a session's hooks run
    hook.add_argument('folder')
    return top


def run_hook(folder):
    """A hook must never get in a session's way: whatever goes wrong here, it exits 0."""
    try:
        payload = json.load(sys.stdin)
        record_hook(folder, payload)
        report_resume(record_in(folder), payload)
    except Exception as error:
        print(f'session hook: {error}', file=sys.stderr)
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in argv:    # what follows goes to the agent as it is
        extra = argv[argv.index('--') + 1:]
        argv = argv[:argv.index('--')]
    args = parser().parse_args(argv)
    if args.command == 'hook':
        return run_hook(args.folder)
    try:
        sessions = Sessions(main_tree())
        if args.command == 'start':
            print(sessions.start(args.ticket, args.coordinator, terminal=args.terminal, name=args.name, branch=args.branch,
                                 worktree=args.worktree, beside=args.beside, allow_tia=args.allow_tia, allow_browser=args.allow_browser, extra=extra,
                                 implement=not args.no_implement, timeout=args.timeout))
        elif args.command == 'audit':
            print(sessions.audit(args.name, terminal=args.terminal, extra=extra, allow_tia=args.allow_tia, allow_browser=args.allow_browser))
        elif args.command == 'watch':
            return watch(sessions, args)
        elif args.command == 'prompt':
            print(sessions.implement(args.name) if args.implement else sessions.prompt(args.name, text_of(args)))
        elif args.command == 'read':
            print(sessions.read(args.name, args.lines))
        elif args.command == 'list':
            print(sessions.listing(resume=args.resume))
        elif args.command == 'close':
            print(sessions.close(args.name, session_only=args.session_only, remove_tree=args.remove_tree))
        elif args.command == 'merge':
            print(sessions.merge(args.name, keep_tree=args.keep_tree))
        elif args.command == 'check':
            return check(sessions, args)
    except NotReady as error:
        print(f'session: {error}', file=sys.stderr)
        return 3
    except (SessionError, OSError) as error:
        print(f'session: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
