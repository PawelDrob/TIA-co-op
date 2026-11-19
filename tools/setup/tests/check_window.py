"""Check by hand, not in the hook: it opens windows, on a desktop of its own that nobody sees, so it may run on a PC in use.

    python tools\\setup\\tests\\check_window.py --out <folder>

A fresh clone of this tree (with its changes not yet committed) in a temp folder, with a temp home, Claude config and
local app data, fake claude on the PATH: the first double-click (wscript.exe Setup.wsf) makes the .venv with uv sync and
opens page 1; the window pictures every page, presses every button that changes something (the viewer under a test key,
the dashboards on free ports: the development dashboard's port held by another program, the TIA dashboard started for
real from the temp clone) and finishes. The second double-click must open the settings; a third, with no claude on the
PATH, pictures what a PC without Claude Code sees. All the while it watches the
hidden desktop for console windows: the first run's uv sync may have one, the second run none. Pictures and done.txt of
each run go to <folder>\\first and <folder>\\second. It starts no TIA, writes nothing of the real user's, and ends the
dashboard it started by its Windows process number.
"""
import argparse
import ctypes
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from TiaChangeReports.viewer import register  # noqa: E402
from tools.setup.window import dashboards as dash  # noqa: E402

WINDOW_SECONDS = 300
CONSOLE_CLASSES = ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS', 'PseudoConsoleWindow')
NO_WINDOW = subprocess.CREATE_NO_WINDOW
GENERIC_ALL = 0x10000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ENUM, wintypes.LPARAM]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
                ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD), ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
                ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class Desktop:
    """A desktop of its own; Watch records each console window that shows on it."""

    def __init__(self):
        self.name = f'setup-window-check-{os.getpid()}'
        self.handle = user32.CreateDesktopW(self.name, None, None, 0, GENERIC_ALL, None)
        if not self.handle:
            raise OSError(f'CreateDesktop failed: {ctypes.get_last_error()}')
        self.consoles = []
        self.watching = False

    def start(self, command, cwd, env):
        si = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW), lpDesktop=self.name)
        pi = PROCESS_INFORMATION()
        block = ctypes.create_unicode_buffer(''.join(f'{k}={v}\0' for k, v in sorted(env.items())) + '\0')
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not kernel32.CreateProcessW(None, line, None, None, False, CREATE_UNICODE_ENVIRONMENT, block, str(cwd), ctypes.byref(si), ctypes.byref(pi)):
            raise OSError(f'CreateProcess failed: {ctypes.get_last_error()}')
        kernel32.CloseHandle(pi.hThread)
        return pi.hProcess

    def wait(self, process, seconds):
        try:
            return kernel32.WaitForSingleObject(process, int(seconds * 1000)) == 0
        finally:
            kernel32.CloseHandle(process)

    def _look(self):
        def each(hwnd, _):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if name.value in CONSOLE_CLASSES and user32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                seen = (name.value, title.value)
                if seen not in self.consoles:
                    self.consoles.append(seen)
            return True
        user32.EnumDesktopWindows(self.handle, ENUM(each), 0)

    def watch(self):
        self.consoles, self.watching = [], True

        def loop():
            while self.watching:
                self._look()
                time.sleep(0.02)
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread

    def close(self):
        user32.CloseDesktop(self.handle)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def git(*args, cwd=REPO):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout


def fresh_clone(temp):
    """A clone of this tree's branch, with the tree's changes and new files copied over it."""
    clone = temp / 'clone'
    subprocess.run(['git', 'clone', '-q', '--local', str(REPO), str(clone)], check=True, creationflags=NO_WINDOW)
    changed = git('ls-files', '-m', '-o', '--exclude-standard').splitlines()
    for name in changed:
        source = REPO / name
        if source.is_file():
            (clone / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, clone / name)
    return clone


def environment(temp):
    """A temp home, Claude config and local app data; fake claude, git and uv on the PATH; uv's cache of this user, so
    that uv sync downloads nothing again."""
    fakes = temp / 'fakes'
    fakes.mkdir()
    shutil.copy(HERE / 'fake_claude.py', fakes)
    (fakes / 'claude.cmd').write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\n')
    for folder in ('home', 'config', 'local'):
        (temp / folder).mkdir()
    uv = shutil.which('uv')
    cache = subprocess.run([uv, 'cache', 'dir'], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    path = [str(fakes), str(Path(shutil.which('git')).parent), str(Path(uv).parent), os.path.join(os.environ['SystemRoot'], 'System32'),
            os.environ['SystemRoot']]
    keep = ('SystemRoot', 'SystemDrive', 'ComSpec', 'PATHEXT', 'TEMP', 'TMP', 'APPDATA', 'ProgramData', 'ProgramFiles',
            'ProgramFiles(x86)', 'windir', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'USERNAME', 'USERDOMAIN', 'COMPUTERNAME')
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(PATH=os.pathsep.join(path), USERPROFILE=str(temp / 'home'), HOME=str(temp / 'home'), CLAUDE_CONFIG_DIR=str(temp / 'config'),
               LOCALAPPDATA=str(temp / 'local'), UV_CACHE_DIR=cache)
    return env


def run(desktop, clone, env, out, options, report):
    """One double-click on the hidden desktop, as Explorer does it: wscript.exe on Setup.wsf, its arguments for the snap."""
    watcher = desktop.watch()
    started = time.monotonic()
    wscript = desktop.start(['wscript.exe', str(clone / 'Setup.wsf'), '--snap', str(out), *options], clone, env)
    ended = desktop.wait(wscript, WINDOW_SECONDS)
    while ended and not (out / 'done.txt').exists() and time.monotonic() - started < WINDOW_SECONDS:
        time.sleep(0.2)
    time.sleep(0.5)
    desktop.watching = False
    watcher.join()
    report.append(f'{out.name}: {"ended" if (out / "done.txt").exists() else "did not end"} in {time.monotonic() - started:.0f} s; '
                  f'console windows: {desktop.consoles or "none"}')
    if (out / 'done.txt').exists():
        report.append((out / 'done.txt').read_text(encoding='utf-8').strip())
    return desktop.consoles


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', required=True)
    a = p.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = []
    key = r'Software\TiaCoopSetupWindowCheck-%s' % uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='setup-window-check-', ignore_cleanup_errors=True) as folder:
        temp = Path(folder)
        clone = fresh_clone(temp)
        env = environment(temp)
        development, tia = free_port(), free_port()
        options = ['--viewer-key', key, '--ports', f'{development},{tia}', '--first-run', str(temp / 'local' / 'first-run.json')]
        holder = subprocess.Popen([sys.executable, str(HERE / 'stub_dashboard.py'), '', str(development)], creationflags=NO_WINDOW,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        desktop = Desktop()
        try:
            run(desktop, clone, env, out / 'first', ['--snap-changes', *options], report)
            report.append(f'.venv made: {(clone / ".venv" / "Scripts" / "pythonw.exe").exists()}')
            consoles = run(desktop, clone, env, out / 'second', options, report)
            report.append('no console on the second double-click' if not consoles else 'FAILED: a console on the second double-click')
            # claude's installer puts it beside uv's, which the .venv no longer needs
            away = (str(temp / 'fakes'), str(Path(shutil.which('uv')).parent))
            without_claude = dict(env, PATH=os.pathsep.join(p for p in env['PATH'].split(os.pathsep) if p not in away))
            if shutil.which('claude', path=without_claude['PATH']):
                raise SystemExit(f'claude is still on the PATH of the run without it: {without_claude["PATH"]}')
            run(desktop, clone, without_claude, out / 'without-claude', [*options, '--page', '1'], report)
        finally:
            holder.kill()
            pid = dash.listener(tia).split('process ')[-1].rstrip(')')
            if pid.isdigit():
                os.kill(int(pid), signal.SIGTERM)
                report.append(f'stopped the TIA dashboard it started, process {pid}')
            register.delete_tree('Software', key.split('\\', 1)[1])
            desktop.close()
            time.sleep(1)
        (out / 'report.txt').write_text('\n'.join(report) + '\n', encoding='utf-8')
        print('\n'.join(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
