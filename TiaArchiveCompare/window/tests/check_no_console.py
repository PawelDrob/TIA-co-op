"""By hand, not in the hook: it opens the real window on the desktop, for seconds, and a console for the control.
    <py> TiaArchiveCompare\\window\\tests\\check_no_console.py [--out FOLDER]

Measures whether a console window comes up when the window starts as a double click starts it (ShellExecuteEx, what
Explorer calls), and during a comparison. Two measures, side by side, for the whole time of each case:
- every window of the desktop as it is created or shown (a WinEvent hook), by its class;
- the processes started below the one launched, polled: a console program gets a conhost.exe as its child.
Controls come first: a .cmd of the shape start.cmd had, by ShellExecuteEx and through explorer.exe, and one that only
exits. Each measure must see each of those consoles as belonging to what was started, or the check fails: on a PC whose
default terminal hides the console from these measures it fails there, rather than pass on nothing. No TIA starts: the
comparison is the real runner with its fake exporter. On a PC in use, run it on a hidden desktop; Explorer
cannot run there, so the rows through explorer.exe need a desktop nobody is using, or a person's own double click.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

from TiaArchiveCompare.window import shortcut      # noqa: E402
from TiaArchiveCompare.window.model import TITLE   # noqa: E402

CONSOLE_CLASSES = {'ConsoleWindowClass', 'PseudoConsoleWindow', 'CASCADIA_HOSTING_WINDOW_CLASS'}
CONSOLE_PROGRAMS = {'cmd.exe', 'conhost.exe', 'openconsole.exe', 'powershell.exe', 'pwsh.exe', 'windowsterminal.exe'}
SAMPLES = os.path.join(ROOT, 'TiaArchiveCompare', 'runner', 'samples')
PLANT_A, PLANT_B = os.path.join(SAMPLES, 'Plant_2026-09-01.zap20'), os.path.join(SAMPLES, 'Plant_2026-10-28.zap20')

EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW = 0x8000, 0x8002
OBJID_WINDOW = 0
WM_QUIT, WM_CLOSE = 0x0012, 0x0010
TH32CS_SNAPPROCESS = 2
SEE_MASK_NOCLOSEPROCESS, SEE_MASK_FLAG_NO_UI = 0x40, 0x400
SW_SHOWNORMAL = 1
PE_SUBSYSTEM = {2: 'windows', 3: 'console'}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
HOLD_SECONDS = 2.0
WINDOW_WAIT_SECONDS = 30

WindowEvent = collections.namedtuple('WindowEvent', 'kind window_class pid exe')
Seen = collections.namedtuple('Seen', 'parent exe')

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.SetWinEventHook.restype = wt.HANDLE
user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD]
user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.GetProcessId.argtypes = [wt.HANDLE]
kernel32.GetProcessId.restype = wt.DWORD
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD),
                ('szExeFile', wt.WCHAR * 260)]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('fMask', wt.ULONG), ('hwnd', wt.HWND), ('lpVerb', wt.LPCWSTR),
                ('lpFile', wt.LPCWSTR), ('lpParameters', wt.LPCWSTR), ('lpDirectory', wt.LPCWSTR), ('nShow', ctypes.c_int),
                ('hInstApp', wt.HINSTANCE), ('lpIDList', ctypes.c_void_p), ('lpClass', wt.LPCWSTR), ('hkeyClass', wt.HKEY),
                ('dwHotKey', wt.DWORD), ('hIcon', wt.HANDLE), ('hProcess', wt.HANDLE)]


shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]


def class_of(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def pid_of(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def exe_path(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    size = wt.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
    kernel32.CloseHandle(handle)
    return buffer.value if ok else None


class WindowWatch(threading.Thread):
    """Every window created or shown on this desktop. The events are handled on this thread, after the fact: a window
    already gone by then has no class, and is counted as such."""

    def __init__(self):
        super().__init__(daemon=True)
        self.events = []
        self.ready = threading.Event()

    def _on_event(self, _hook, event, hwnd, id_object, id_child, _thread, _time):
        if id_object == OBJID_WINDOW and id_child == 0 and hwnd:
            kind, name, pid = 'shown' if event == EVENT_OBJECT_SHOW else 'created', class_of(hwnd), pid_of(hwnd)
            self.events.append(WindowEvent(kind, name, pid, exe_path(pid) if name in CONSOLE_CLASSES else None))

    def run(self):
        self.callback = WINEVENTPROC(self._on_event)
        self.thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWinEventHook(EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, None, self.callback, 0, 0, 0)
        message = wt.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)      # this thread has a queue before anyone posts to it
        self.ready.set()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWinEvent(hook)

    def stop(self):
        user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.join(5)


class ProcessWatch(threading.Thread):
    """Every process seen while this runs. Polled, as a process event needs an administrator."""

    def __init__(self):
        super().__init__(daemon=True)
        self.seen = {}
        self.before = self.snapshot()
        self.keep_going = True
        self.polls = 0

    @staticmethod
    def snapshot():
        found = {}
        handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            found[entry.th32ProcessID] = Seen(entry.th32ParentProcessID, entry.szExeFile)
            more = kernel32.Process32NextW(handle, ctypes.byref(entry))
        kernel32.CloseHandle(handle)
        return found

    def run(self):
        while self.keep_going:
            self.seen.update(self.snapshot())
            self.polls += 1

    def stop(self):
        self.keep_going = False
        self.join(5)

    def below(self, roots):
        """Those roots and all they started, also what has ended since. Only processes new since the start count: an old
        one may name as its parent a process long gone whose number one of ours now has."""
        tree, grown = set(roots), True
        while grown:
            more = {pid for pid, seen in self.seen.items() if seen.parent in tree and pid not in tree and pid not in self.before}
            tree |= more
            grown = bool(more)
        return tree

    def first_started_above(self, pid):
        """The first process of the chain that ends in pid and is new since the start: all a start made stands below it,
        what has ended too. One that ended before a poll saw it has no entry, but its number still finds what it started."""
        chain = {pid}
        while pid in self.seen and pid not in self.before:
            parent = self.seen[pid].parent
            if parent in self.before or parent in chain:
                break
            chain.add(parent)
            pid = parent
        return pid


def double_click(path, folder=None):
    """As Explorer does; without SEE_MASK_NO_CONSOLE a console program gets a console of its own. Returns the handle of
    the process started."""
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI,
                             lpFile=path, lpDirectory=folder, nShow=SW_SHOWNORMAL)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise OSError('ShellExecuteEx of %s failed: %s' % (path, ctypes.get_last_error()))
    return info.hProcess


def windows_titled(title):
    found = []

    def visit(hwnd, _):
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buffer, 256)
        if buffer.value == title and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(ENUMPROC(visit), 0)
    return found


def subsystem(path):
    """What the file asks of Windows: 'console' gets a console when started with none, 'windows' never."""
    with open(path, 'rb') as f:
        head = f.read(4096)
    offset = struct.unpack_from('<I', head, 0x3c)[0]
    return PE_SUBSYSTEM.get(struct.unpack_from('<H', head, offset + 0x5c)[0], 'other')


class Measure:
    """Runs one case between the two measures and says what they saw of it."""

    def __init__(self):
        self.windows, self.processes = WindowWatch(), ProcessWatch()

    def __enter__(self):
        self.windows.start()
        self.windows.ready.wait(5)
        self.processes.start()
        return self

    def __exit__(self, *_):
        self.processes.stop()
        self.windows.stop()

    def findings(self, roots):
        tree = self.processes.below(roots)
        names = {pid: self.processes.seen[pid].exe for pid in tree if pid in self.processes.seen}
        consoles = [e for e in self.windows.events if e.window_class in CONSOLE_CLASSES]
        ours = [e for e in consoles if e.pid in tree or (e.exe or '').lower().startswith(ROOT.lower())]
        return {'tree': sorted(names.values(), key=str.lower),
                'console_programs': sorted(n for n in names.values() if n.lower() in CONSOLE_PROGRAMS),
                'console_windows_here': ours,
                'console_windows_elsewhere': [e.exe or e.pid for e in consoles if e not in ours],
                'windows_with_no_class': sum(1 for e in self.windows.events if not e.window_class),
                'events': len(self.windows.events), 'polls': self.processes.polls}


def wait_for_window(known, is_ours):
    """A window of the tool that was not there before, once it stands."""
    end = time.time() + WINDOW_WAIT_SECONDS
    while time.time() < end:
        for hwnd in windows_titled(TITLE):
            if hwnd not in known and is_ours(pid_of(hwnd)):
                return hwnd
        time.sleep(0.05)
    return None


def start_and_close(path, folder=None):
    """A window that came up, then closed by its own message. Returns the findings and whether it stood."""
    known = windows_titled(TITLE)
    with Measure() as measure:
        handle = double_click(path, folder)
        root = kernel32.GetProcessId(handle)
        hwnd = wait_for_window(known, lambda pid: pid in measure.processes.below([root]))
        time.sleep(HOLD_SECONDS)
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        kernel32.WaitForSingleObject(handle, 15000)
        kernel32.CloseHandle(handle)
        time.sleep(0.5)
        return measure.findings([root]), hwnd is not None


def found_by_title(start):
    """A start that leaves nothing to follow below us: the window by its title, and up from it to what the start made."""
    known = windows_titled(TITLE)
    with Measure() as measure:
        start()
        hwnd = wait_for_window(known, lambda pid: True)
        pid = pid_of(hwnd) if hwnd else 0
        time.sleep(HOLD_SECONDS)
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        time.sleep(2)
        return measure.findings([measure.processes.first_started_above(pid)] if hwnd else []), hwnd is not None


def by_explorer(path):
    """explorer.exe takes the file and starts it itself: the same road as a click on the Desktop."""
    return found_by_title(lambda: subprocess.Popen(['explorer.exe', path]))


def compare_run(out, settings):
    """A whole comparison, through a shortcut: the window, the real runner, its fake exporter, the report. --snap makes
    the window transparent and ends it by itself."""
    folder = os.path.join(out, 'run-shortcut')
    os.makedirs(folder)
    snap = os.path.join(out, 'run-snap')
    os.makedirs(snap)
    arguments = ('%s --snap "%s" --settings "%s" --timeout 60 --before "%s" --after "%s" --runner-args '
                 '"-X utf8 -m TiaArchiveCompare.runner run --exporter fake --fake-speed 0.02 --out-root %s --data-root %s"'
                 % (shortcut.WINDOW_ARGUMENTS, snap, settings, PLANT_A, PLANT_B, os.path.join(out, 'o'), os.path.join(out, 'd')))
    link = shortcut.make(folder, ROOT, arguments)
    with Measure() as measure:
        handle = double_click(link)
        root = kernel32.GetProcessId(handle)
        kernel32.WaitForSingleObject(handle, 120000)
        kernel32.CloseHandle(handle)
        time.sleep(0.5)
        findings = measure.findings([root])
    result = os.path.join(snap, 'result.txt')
    text = open(result, encoding='utf-8').read() if os.path.exists(result) else ''
    return findings, text


failed = 0


def check(name, ok):
    global failed
    print('  %s %s' % ('ok  ' if ok else 'FAIL', name))
    failed += 0 if ok else 1


def show(name, findings):
    print('%s\n  %d window events, %d process polls, processes: %s' % (name, findings['events'], findings['polls'], ', '.join(findings['tree'])))
    print('  console windows of it: %s' % (findings['console_windows_here'] or 'none'))
    print('  console windows of others in that time: %s' % (findings['console_windows_elsewhere'] or 'none'))
    print('  windows gone before they could be read: %d' % findings['windows_with_no_class'])


def no_console_seen(findings):
    return not findings['console_windows_here'] and not findings['console_programs']


def shortest_console(out):
    """A console with nothing to do, gone as soon as it can be: what "for a frame" means. Without it, a run that keeps a
    conhost of its own (the comparison) rests on a window measure not known to see one so short."""
    path = os.path.join(out, 'shortest.cmd')
    with open(path, 'w', encoding='ascii') as f:
        f.write('@exit\r\n')
    with Measure() as measure:
        handle = double_click(path)
        root = kernel32.GetProcessId(handle)
        kernel32.WaitForSingleObject(handle, 15000)
        kernel32.CloseHandle(handle)
        time.sleep(0.5)
        return measure.findings([root])


def check_start(name, started):
    findings, stood = started
    show(name, findings)
    check('the window came up', stood)
    check('no console', no_console_seen(findings))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out')
    a = p.parse_args()
    out = a.out or tempfile.mkdtemp(prefix='no-console-')
    os.makedirs(out, exist_ok=True)
    python = shortcut.window_python(ROOT)
    print('%s: %s subsystem' % (python, subsystem(python)))
    check('the shortcut\'s program is of the windows subsystem', subsystem(python) == 'windows')

    control = os.path.join(out, 'control.cmd')
    with open(control, 'w', encoding='ascii') as f:
        f.write('@echo off\r\ncd /d "%s"\r\nstart "" "%s" %s\r\n' % (ROOT, python, shortcut.WINDOW_ARGUMENTS))
    findings, stood = start_and_close(control)
    show('control: a .cmd of the shape start.cmd had', findings)
    check('the window came up', stood)
    check('the process measure sees its console', bool(findings['console_programs']))
    check('the window measure sees its console, as its own', bool(findings['console_windows_here']))

    findings, stood = by_explorer(control)
    show('control: the same .cmd, through explorer.exe', findings)
    check('the window came up', stood)
    check('the process measure sees its console', bool(findings['console_programs']))
    check('the window measure sees its console, as its own', bool(findings['console_windows_here']))

    findings = shortest_console(out)
    show('control: the shortest console, a .cmd that only exits', findings)
    check('the process measure sees it', bool(findings['console_programs']))
    check('the window measure sees it, as its own', bool(findings['console_windows_here']))

    link = shortcut.make(out, ROOT)
    check_start('the shortcut, double click', start_and_close(link))

    other = os.path.join(out, 'another folder ä')
    os.makedirs(other)
    copied = os.path.join(other, shortcut.NAME)
    shutil.copy(link, copied)
    os.chdir(other)
    check_start('a copy of the shortcut in another folder', start_and_close(copied, other))
    os.chdir(ROOT)

    check_start('the shortcut, through explorer.exe', by_explorer(link))

    settings = os.path.join(out, 'window.json')
    findings, result = compare_run(out, settings)
    show('a comparison from the shortcut: window, real runner, fake exporter', findings)
    check('it ran to its report', 'report: ' in result or 'Done in' in result)
    check('no console window (a runner has a conhost with no window: CREATE_NO_WINDOW)', not findings['console_windows_here'])
    print('\n%s' % ('passed' if not failed else '%d FAILED' % failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
