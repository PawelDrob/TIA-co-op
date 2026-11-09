"""Manual check, outside the suites: the preview server with no console opens no console window while it shows diffs.
Run it from TiaHmiGenerator\\:

    python -X utf8 -m Tests.console_check

It makes a fixture repo with a changed screen, makes a desktop of its own, and runs there what an agent runs
(.claude/skills/tia-change/hmi.md): the venv's python.exe -m hmipreview serve <repo> --detach, with a console and no
window, as in an agent's shell. The server it leaves behind has no console, so each console program it runs would get a
window of its own. The check then asks for the diff against the last commit and the project tree with the diff on,
changes the screen and asks for both again (a reload), and asks for the findings. All the while it looks for console
windows on that desktop, visible or not, and for new ones on yours: with Windows Terminal as the default terminal, a
console started on the other desktop opens on yours. It only reads your desktop; another program may open a console there
meanwhile, so it names the owner of any it sees. Exit code 0 when no console window came up and every request was
answered with the diff.

It refuses to run while server.detach starts the server with DETACHED_PROCESS: the venv's python.exe is a launcher, and
started so it hands its child a console window of its own, which may open on your desktop.
"""
import ast
import ctypes
import inspect
import json
import msvcrt
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from ctypes import wintypes
from pathlib import Path

from Tests.fixture import FixtureRepo, document, rect

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PACKAGE_ROOT.parent / '.venv' / 'Scripts' / 'python.exe'     # <py> of AGENTS.md
CONSOLE_CLASSES = ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS')
GENERIC_ALL, PROCESS_TERMINATE, PROCESS_QUERY_LIMITED_INFORMATION = 0x10000000, 0x1, 0x1000
CREATE_NO_WINDOW, STARTF_USESTDHANDLES = 0x08000000, 0x100

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ENUM, wintypes.LPARAM]
user32.EnumWindows.argtypes = [ENUM, wintypes.LPARAM]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype, kernel32.OpenProcess.argtypes = wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR)] + \
               [(n, wintypes.DWORD) for n in ('dwX', 'dwY', 'dwXSize', 'dwYSize', 'dwXCountChars', 'dwYCountChars', 'dwFillAttribute', 'dwFlags')] + \
               [('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p)] + \
               [(n, wintypes.HANDLE) for n in ('hStdInput', 'hStdOutput', 'hStdError')]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


failed = []


def check(ok, what):
    print(('ok    ' if ok else 'FAIL  ') + what, flush=True)
    if not ok:
        failed.append(what)
    return ok


def consoles(desktop=None, visible_only=False):
    """{hwnd: owner's program} of the console windows on desktop (a handle), or on this process's desktop."""
    found = {}

    def note_console(hwnd, _):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in CONSOLE_CLASSES and (user32.IsWindowVisible(hwnd) or not visible_only):
            found[hwnd] = owner(hwnd)
        return True

    if desktop is None:
        user32.EnumWindows(ENUM(note_console), 0)
    else:
        user32.EnumDesktopWindows(desktop, ENUM(note_console), 0)
    return found


def owner(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return 'process %d' % pid.value
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return os.path.basename(buf.value) if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else 'process %d' % pid.value
    finally:
        kernel32.CloseHandle(h)


class ConsoleWatch(threading.Thread):
    """Console windows that come up on the server's desktop, also for a moment and hidden ones, and new visible ones on
    this one."""

    def __init__(self, desktop):
        super().__init__(daemon=True)
        self.desktop = desktop
        self.before = set(consoles(visible_only=True))
        self.on_its_desktop, self.on_this_desktop = {}, {}
        self.ending = False

    def run(self):
        while not self.ending:
            self.on_its_desktop.update(consoles(self.desktop))
            self.on_this_desktop.update({h: o for h, o in consoles(visible_only=True).items() if h not in self.before})
            time.sleep(0.01)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def get(port, path, **params):
    url = 'http://127.0.0.1:%d%s?%s' % (port, path, urllib.parse.urlencode(params))
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode('utf-8')


def answers(port):
    for _ in range(300):
        try:
            get(port, '/api/screens')
            return True
        except OSError:
            time.sleep(0.1)
    return False


def fixture():
    """Screen Silo generated, then exported and committed after: the staleness rule asks git log for the commit."""
    repo = FixtureRepo()
    path = repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
    repo.write('hmi/generated/generated.json', json.dumps({path: {'generated': '2026-10-06T10:00:00+00:00'}}))
    repo.export('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=40)], Number=2))
    repo.commit(date='2026-10-06T12:00:00+00:00')
    repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=20)], Number=2))
    return repo


def requests(repo, port):
    diff = json.loads(get(port, '/api/diff', name='Silo'))
    check(diff['base']['ref'] == 'HEAD' and diff['lines'] == ['Rectangle r1: moved (10, 90) 100x50 -> (20, 90) 100x50'],
          'the diff against the last commit (git show): %s' % diff['lines'])
    check('changed' in get(port, '/api/tree', against='commit'), 'the tree with the diff on (git cat-file)')
    repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=30)], Number=2))
    time.sleep(1.5)     # past the server's look at the files
    diff = json.loads(get(port, '/api/diff', name='Silo'))
    check(diff['lines'] == ['Rectangle r1: moved (10, 90) 100x50 -> (30, 90) 100x50'], 'the diff after a reload: %s' % diff['lines'])
    check('changed' in get(port, '/api/tree', against='commit'), 'the tree with the diff on after a reload')
    stale = [f['document'] for f in json.loads(get(port, '/api/findings')) if f['rule'] == 'staleness.export-newer']
    check(stale == ['hmi/generated/screens/Silo.xml'], 'the findings, the export newer by git log: %s' % stale)


def detach(desktop_name, repo, port, lines_file):
    """serve --detach of the repo on port, run by the venv's python.exe on desktop_name with a console and no window; its
    lines go to the file lines_file. The pid of the server it started, or None."""
    si = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW), lpDesktop=desktop_name, dwFlags=STARTF_USESTDHANDLES)
    pi = PROCESS_INFORMATION()
    line = ctypes.create_unicode_buffer('"%s" -X utf8 -m hmipreview serve "%s" --port %d --detach' % (VENV_PYTHON, repo.path, port))
    with open(lines_file, 'wb') as out, open(os.devnull, 'rb') as nothing:
        for f in (out, nothing):
            os.set_handle_inheritable(msvcrt.get_osfhandle(f.fileno()), True)
        si.hStdInput = msvcrt.get_osfhandle(nothing.fileno())
        si.hStdOutput = si.hStdError = msvcrt.get_osfhandle(out.fileno())
        if not kernel32.CreateProcessW(None, line, None, None, True, CREATE_NO_WINDOW, None, str(PACKAGE_ROOT),
                                       ctypes.byref(si), ctypes.byref(pi)):
            return None
        kernel32.WaitForSingleObject(pi.hProcess, 60000)
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)
    text = Path(lines_file).read_text(encoding='utf-8', errors='replace')
    pid = [int(w.split()[1]) for w in text.splitlines() if w.startswith('pid ')]
    return pid[0] if pid else None


def stop(pid):
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if h:
        kernel32.TerminateProcess(h, 0)
        kernel32.CloseHandle(h)


def main():
    from hmipreview import server
    names = {n.attr if isinstance(n, ast.Attribute) else n.value for n in ast.walk(ast.parse(inspect.getsource(server.detach)))
             if isinstance(n, ast.Attribute) or isinstance(n, ast.Constant) and isinstance(n.value, str)}     # getattr's too
    if 'DETACHED_PROCESS' in names:
        print('server.detach still starts the server with DETACHED_PROCESS, and a console window may open on your desktop: '
              'not run')
        return 2
    repo = fixture()
    name = 'zz-hmipreview-%d' % os.getpid()
    desktop = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not check(bool(desktop), 'a desktop of its own could be made'):
        return 1
    port = free_port()
    lines_file = os.path.join(repo.path, '..', 'zz-hmipreview-%d.txt' % os.getpid())
    watch = ConsoleWatch(desktop)
    watch.start()
    try:
        pid = detach(name, repo, port, lines_file)
        if check(pid is not None, 'python.exe -m hmipreview serve --detach started the server on that desktop: pid %s' % pid):
            try:
                if check(answers(port), 'it answers on %d' % port):
                    requests(repo, port)
                time.sleep(0.5)
            finally:
                stop(pid)
    finally:
        watch.ending = True
        watch.join()
        user32.CloseDesktop(desktop)
        time.sleep(0.5)     # the server's handles on the repo go with it
        repo.cleanup()
        if os.path.exists(lines_file):
            os.remove(lines_file)
    check(not watch.on_its_desktop, 'no console window on the server\'s desktop: %s' % sorted(watch.on_its_desktop.values()))
    check(not watch.on_this_desktop, 'no new console window on this desktop: %s' % sorted(watch.on_this_desktop.values()))
    print('%d failed' % len(failed) if failed else 'all ok')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
