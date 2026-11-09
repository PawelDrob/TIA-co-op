"""Where a session runs. Each adapter opens a session, sends it a prompt, tells whether it lives, reads it and ends it.

    Herdr      a tab in the running herdr: a person can look on and step in. Used inside a herdr pane.
    Headless   no window: each turn is one detached `claude -p`, the next resumes it. Needs nothing but claude.
    Printed    a person's own terminal: prints what to run and type, and runs nothing.

Commands go as argument lists, with no shell between: quoting and path conversion do not come into it.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from store import SessionError, read_json

AGENT_START_SECONDS = 60
EXIT_SECONDS = 60
HOOK_HERDR_SECONDS = 10
ANSWER_SECONDS = 10    # for a question about a session, which herdr answers well within a second: list, watch and the wait of start ask them
NOT_READ = 'not read'
NO_ID = 'no session id recorded'    # its hooks write it: one that ran bare since, after a restart, has none and may never
DOWN = {'server_not_running', 'not_on_path'}    # no herdr to ask
RESUME_SOURCE = 'session-tool'
RESUME_MOST_ARGUMENTS, RESUME_MOST_BYTES = 64, 8192    # herdr 0.9.5 refuses a longer resume command, and one with an apostrophe or a control character
CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
YES_CHOSEN = re.compile(r'(?m)^\s*[\u276f>]\s*(\d+\.\s*)?Yes')


class HerdrFailed(SessionError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def run_herdr(args, timeout=90):
    """The result of a herdr command, parsed when it is JSON."""
    exe = shutil.which('herdr')
    if not exe:
        raise HerdrFailed('not_on_path', 'herdr is not on the PATH')
    try:
        done = subprocess.run([exe, *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HerdrFailed('no_answer', f'herdr {" ".join(args[:2])} did not answer') from None
    try:
        answer = json.loads(done.stdout or done.stderr)
    except ValueError:
        if done.returncode:
            raise HerdrFailed('', (done.stderr or done.stdout).strip()) from None
        return done.stdout
    if done.returncode or 'error' in answer:
        error = answer.get('error') or {}
        raise HerdrFailed(error.get('code', ''), error.get('message', str(answer)))
    return answer.get('result', answer)


def same_folder(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def squeezed(text):
    """Text with no white space and one kind of slash, to find a path that a narrow pane wrapped."""
    return re.sub(r'\s+', '', text).replace('/', '\\').casefold()


def resume_command(session_id, args):
    """What herdr runs to bring a session back after a restart, as report_resume tells it."""
    return ['claude', '--resume', session_id, *args]


def typed(arg):
    """One argument as a person types it in PowerShell or Git Bash: single quotes keep $, ( and * from either. An apostrophe has no
    single quoting that both read, so double quotes then."""
    return f'"{arg}"' if "'" in arg else f"'{arg}'"


def resume_typed(session_id, args):
    """What follows claude to bring the session back, typed; <id> while its hook has reported none."""
    return ' '.join(['--resume', session_id or '<id>', *(typed(arg) for arg in args)])


def report_resume(record, payload, env=os.environ, run=None):
    """Tells herdr, on each start, prompt and turn end of a session in one of its panes, what brings it back after a restart: left to
    itself herdr runs `claude --resume <id>`, with no denied tools and no hooks. It keeps this until the process ends, so a new process
    reports it again. A start comes with /clear too, under a new id. A record with no arguments, of a session started before they were
    kept, reports nothing."""
    pane, session_id, args = env.get('HERDR_PANE_ID'), payload.get('session_id'), record.get('args')
    if payload.get('hook_event_name') not in ('SessionStart', 'UserPromptSubmit', 'Stop') or not (pane and session_id and args):
        return
    run = run or (lambda command: run_herdr(command, timeout=HOOK_HERDR_SECONDS))
    run(['pane', 'report-agent-session', pane, '--source', RESUME_SOURCE, '--agent', 'claude', '--seq', str(time.time_ns() // 1000),
         '--', *resume_command(session_id, args)])


class Herdr:
    def __init__(self, run=run_herdr, workspace=None, sleep=time.sleep):
        self.run, self.sleep = run, sleep
        self.stopped = ''    # why a look asks nothing more of this one: a hung herdr costs its timeout each time, and one that is down knows nothing
        self.workspace = workspace or os.environ.get('HERDR_WORKSPACE_ID')

    def open(self, record, args, prompt):
        name, worktree = record['name'], record['worktree']
        created = self.run(['tab', 'create', *(['--workspace', self.workspace] if self.workspace else []),
                            '--cwd', worktree, '--label', name, '--no-focus'])
        tab, pane = created['tab']['tab_id'], created['root_pane']['pane_id']
        try:
            cwd = self.run(['pane', 'get', pane])['pane'].get('cwd', '')
            if not same_folder(cwd, worktree):
                raise SessionError(f'the tab opened in {cwd}, not in {worktree}: nothing started')
            try:
                self.run(['agent', 'start', name, '--kind', 'claude', '--pane', pane, '--timeout', str(AGENT_START_SECONDS * 1000), '--', *args])
            except HerdrFailed as failed:
                if failed.code != 'agent_not_ready':
                    raise
                self.pass_trust_prompt(name, worktree, failed)
            self.run(['agent', 'prompt', name, prompt])
        except Exception:
            self.close_quietly(tab)
            raise
        return {'tab': tab, 'pane': pane}

    def close_quietly(self, tab):
        """The tab this start made, on the way out of a failed start: the failure is what gets reported."""
        try:
            self.run(['tab', 'close', tab])
        except HerdrFailed:
            pass

    def pass_trust_prompt(self, name, worktree, failed):
        """A session stuck at startup may ask to trust its folder: yes for its own worktree, nothing else ever. Enter confirms what
        is chosen, and "No, exit" is chosen first, so it confirms only once the screen shows yes chosen."""
        screen = self.visible(name)
        if 'trust' not in screen.lower() or squeezed(worktree.rstrip('\\/')) not in squeezed(screen):
            raise SessionError(f'the session is not ready ({failed}). Its screen:\n{screen}')
        if not YES_CHOSEN.search(screen):
            self.run(['agent', 'send-keys', name, 'Down'])
            self.sleep(1)
            screen = self.visible(name)
            if not YES_CHOSEN.search(screen):
                raise SessionError(f'the session is not ready ({failed}): yes could not be chosen. Its screen:\n{screen}')
        self.run(['agent', 'send-keys', name, 'Enter'])
        status = '?'
        for _ in range(AGENT_START_SECONDS):
            self.sleep(1)
            status = self.run(['agent', 'get', name])['agent'].get('agent_status')
            if status in ('idle', 'done'):
                return
        raise SessionError(f'the session did not get ready after its trust prompt: {status}')

    def visible(self, name):
        return str(self.run(['agent', 'read', name, '--source', 'visible']))

    def send(self, record, text):
        name = record['name']
        pane = self.run(['agent', 'get', name])['agent'].get('pane_id')
        if pane != record['pane']:
            raise SessionError(f'the agent named {name} is in pane {pane}, its session in {record["pane"]}: nothing sent')
        self.run(['agent', 'prompt', name, text])
        return {}

    def restore_refused(self, args):
        """Why herdr will refuse the command that brings a session of these arguments back, or '': it then comes back without them, and
        only a restart shows it. Herdr 0.9.5's rule; its bytes are counted here as the command joined by spaces."""
        command = resume_command(str(uuid.UUID(int=0)), args)
        if any("'" in arg for arg in command):
            return 'an apostrophe in an argument'
        if any(CONTROL.search(arg) for arg in command):
            return 'a control character in an argument'
        if len(command) > RESUME_MOST_ARGUMENTS:
            return f'{len(command)} arguments, herdr takes {RESUME_MOST_ARGUMENTS}'
        size = len(' '.join(command).encode('utf-8'))
        if size > RESUME_MOST_BYTES:
            return f'{size} bytes, herdr takes {RESUME_MOST_BYTES}'
        return ''

    def resume(self, record, session_id):
        """The command that starts it again in its pane with its guards, for a person to type once the bare one has exited."""
        pane = record.get('pane', '<pane>')
        lines = [f'herdr agent start {record["name"]} --kind claude --pane {pane} -- {resume_typed(session_id, record["args"])}']
        if not session_id:
            lines.append(f'{NO_ID}: read it from agent_session.value of herdr pane get {pane}')
        refused = self.restore_refused(record['args'])
        if refused:
            lines.append(f'after a restart it COMES BACK WITHOUT ITS GUARDS again: herdr refuses to keep this command ({refused})')
        return lines

    def ask(self, args):
        """A question about a session. An error about the session is an answer; a timeout, or no herdr to ask, stops the look."""
        try:
            return self.run(args, timeout=ANSWER_SECONDS)
        except HerdrFailed as failed:
            if failed.code == 'no_answer':
                self.stop('did not answer')
            elif failed.code in DOWN:
                self.stop(f'could not be asked ({failed})')
            raise
        except OSError as error:
            self.stop(f'could not be asked ({error})')
            raise

    def stop(self, why):
        """The first reason stands."""
        self.stopped = self.stopped or why

    def alive(self, record):
        try:
            return self.ask(['agent', 'get', record['name']])['agent'].get('pane_id') == record.get('pane')
        except HerdrFailed as failed:
            return False if failed.code == 'agent_not_found' else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def guarded(self, record):
        """Whether the session's process has its arguments; None when no such process shows. NOT_READ when herdr does not say what they
        are, which accuses nobody: it leaves an argv out where Windows does not give one."""
        try:
            shown = self.ask(['pane', 'process-info', '--pane', record.get('pane')])['process_info']['foreground_processes']
            argvs = [process.get('argv') for process in shown if Path(process.get('name') or '').stem.lower() == 'claude']
        except (HerdrFailed, OSError, ValueError, KeyError, TypeError, AttributeError):
            return NOT_READ
        if any(argv and '--settings' in argv for argv in argvs):
            return True
        if not argvs:
            return None
        return False if all(argvs) else NOT_READ

    def read(self, record, lines):
        return str(self.run(['agent', 'read', record['name'], '--lines', str(lines)]))

    def holds_tree(self, record):
        """Its tab's shell stands in the tree, with or without an agent, until the tab closes."""
        return True

    def end(self, record):
        """Closes the tab it made, once its pane shows that this is still that tab: ids can start over with a new herdr server."""
        tab = record['tab']
        try:
            pane = self.run(['pane', 'get', record['pane']])['pane']
        except HerdrFailed as failed:
            if failed.code != 'pane_not_found':
                raise
            return f'tab {tab} already gone'
        if pane.get('tab_id') != tab or not same_folder(pane.get('cwd', ''), record['worktree']):
            raise SessionError(f'pane {record["pane"]} is in tab {pane.get("tab_id")}, folder {pane.get("cwd")}, not the session\'s '
                               f'tab {tab} in {record["worktree"]}: nothing closed. Close it by hand')
        self.run(['tab', 'close', tab])
        return f'closed tab {tab}'


def child_environment(env):
    """The environment of a session with no herdr: a child that keeps HERDR_PANE_ID reports its state as the caller's pane's."""
    clean = {k: v for k, v in env.items() if not k.upper().startswith('HERDR_')}
    for key in clean:
        if key.upper() == 'PATH':
            clean[key] = os.pathsep.join(p for p in clean[key].split(os.pathsep) if '.herdr' not in p.lower())
    return clean


def process_stamp(pid):
    """What tells this process from a later one with the same number; None when it has ended."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    handle = ctypes.c_void_p(handle)
    try:
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        if code.value != 259:    # STILL_ACTIVE
            return None
        created, ended, kernel_time, user_time = (ctypes.c_ulonglong() for _ in range(4))
        ok = kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel_time), ctypes.byref(user_time))
        return created.value if ok else None
    finally:
        kernel.CloseHandle(handle)


def spawn_detached(command, cwd, prompt_file, log_file, env):
    """Starts a turn that outlives this process: (pid, stamp)."""
    with open(prompt_file, 'rb') as stdin, open(log_file, 'ab') as log:
        process = subprocess.Popen(command, cwd=cwd, stdin=stdin, stdout=log, stderr=subprocess.STDOUT, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    return process.pid, process_stamp(process.pid)


def kill_tree(pid):
    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)


class Headless:
    stopped = ''    # it asks nobody

    def __init__(self, spawn=spawn_detached, alive=lambda pid, stamp: stamp is not None and process_stamp(pid) == stamp,
                 kill=kill_tree, claude=None, env=None, sleep=time.sleep):
        self.spawn, self.process_alive, self.kill, self.sleep = spawn, alive, kill, sleep
        self.claude = claude
        self.env = os.environ if env is None else env

    def turn(self, record, flags, args, prompt):
        claude = self.claude or shutil.which('claude')
        if not claude:
            raise SessionError('claude is not on the PATH')
        folder = Path(record['folder'])
        folder.mkdir(parents=True, exist_ok=True)
        prompt_file = folder / 'prompt.txt'
        prompt_file.write_text(prompt, encoding='utf-8')
        pid, stamp = self.spawn([claude, '-p', *flags, *args], record['worktree'], prompt_file, folder / 'output.log',
                                child_environment(self.env))
        return {'pid': pid, 'stamp': stamp}

    def open(self, record, args, prompt):
        session_id = str(uuid.uuid4())
        return {'session_id': session_id, 'args': args, **self.turn(record, ['--session-id', session_id], args, prompt)}

    def alive(self, record):
        return self.process_alive(record.get('pid'), record.get('stamp'))

    def wait_for_exit(self, record):
        """The Stop hook fires before the process exits, and a resume beside a running turn would fork the session."""
        reported = read_json(Path(record['folder']) / 'state.json') or {}
        state = reported.get('state')
        if reported.get('background'):
            raise SessionError(f'{record["name"]} ended its turn with background tasks running, and takes up again when they end: '
                               'send this after that')
        if state not in ('ended', 'failed'):
            raise SessionError(f'{record["name"]} is still working on its turn: send this when the turn has ended')
        for _ in range(EXIT_SECONDS):
            self.sleep(1)
            if not self.alive(record):
                return
        raise SessionError(f'{record["name"]} ended its turn but has not exited after {EXIT_SECONDS} seconds: read it, or close it')

    def send(self, record, text):
        if self.alive(record):
            self.wait_for_exit(record)
        return self.turn(record, ['--resume', record['session_id']], record['args'], text)

    def guarded(self, record):
        """Each turn starts with the record's arguments, so nothing brings one back without them."""
        return None

    def restore_refused(self, args):
        """Nothing brings it back after a restart."""
        return ''

    def resume(self, record, session_id):
        return ['its next prompt resumes it with its guards: nothing to type']

    def holds_tree(self, record):
        return self.alive(record)

    def read(self, record, lines):
        try:
            return '\n'.join((Path(record['folder']) / 'output.log').read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
        except OSError:
            return ''

    def end(self, record):
        if self.alive(record):
            self.kill(record['pid'])
            return 'stopped its running turn'
        return 'no turn running'


def quoted(arg):
    """One argument for a person to paste, in PowerShell or Git Bash alike."""
    return arg if re.fullmatch(r'[\w./:=-]+', arg) else '"' + arg + '"'


class Printed:
    stopped = ''    # it asks nobody

    def __init__(self, out=print):
        self.out = out

    def open(self, record, args, prompt):
        self.out('Start it in a terminal of your own:')
        self.out(f'  cd {quoted(record["worktree"])}')
        self.out('  claude ' + ' '.join(quoted(a) for a in args))
        self.out(f'Accept a trust prompt for {record["worktree"]} only, the home folder never.')
        self.out('Then type:')
        self.out('  ' + prompt)
        return {}

    def send(self, record, text):
        raise SessionError(f'{record["name"]} runs in a terminal of its own: type it there:\n  {text}')

    def alive(self, record):
        return None

    def guarded(self, record):
        return None

    def restore_refused(self, args):
        """Nothing brings it back after a restart."""
        return ''

    def resume(self, record, session_id):
        """In a terminal of a person's own, from its tree."""
        lines = [f'cd {typed(record["worktree"])}; claude {resume_typed(session_id, record["args"])}']
        if not session_id:
            lines.append(f'{NO_ID}: it is the name of its transcript, <id>.jsonl, in the folder for its tree under ~\\.claude\\projects\\')
        return lines

    def holds_tree(self, record):
        """Closing cannot end it, so whatever stands in the tree counts against closing."""
        return False

    def read(self, record, lines):
        return 'it runs in a terminal of its own, this is the last message it reported'

    def end(self, record):
        return 'end it in its own terminal'


def choose(env=None, which=shutil.which):
    """herdr only from inside one of its panes: from outside it, its commands would act on whatever a person has in focus."""
    env = os.environ if env is None else env
    return 'herdr' if env.get('HERDR_ENV') == '1' and which('herdr') else 'headless'


ADAPTERS = {'herdr': Herdr, 'headless': Headless, 'print': Printed}
