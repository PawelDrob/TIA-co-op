"""python -X utf8 -m TiaArchiveCompare.package.check ZIP [--visible] [--keep]    (from the repo folder)

Proves a download as a person gets it: unpacked into a new folder whose path has a space and an umlaut, with a PATH
that holds no Python (System32 and Windows PowerShell only) and no PYTHON* variables, it
1. runs the runner's samples with the fake exporter, HMI included, with the download's own python.exe, to a report;
2. starts "TIA Archive Compare.exe", which starts the window with no runner named, so it finds the download's
   Python itself. The before archive comes as a file dropped on the launcher does, the first argument, and must stand
   in Before. The window runs the same comparison with no one at it (--snap) and must end on "Done", its title
   carrying the version. On a hidden desktop of its own unless --visible: it opens a window and takes the focus;
3. makes the shortcut with the download's Python: it must start the launcher of the unpacked folder;
4. finds the launcher a Windows program (no console) with the version in its file version;
5. starts the download's TiaBridge as the runner does, with no TIA, and finds the tools the runner calls.
build.py runs it after each build. --keep leaves the unpacked folder and the runs, and prints where.
Exit code 0 when all hold.
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from ctypes import wintypes
from dataclasses import dataclass

from TiaArchiveCompare.package.build import LAUNCHER, PYTHON_DIR, package_name
from TiaArchiveCompare.runner.bridge import POWERSHELL
from TiaArchiveCompare.window.runner_process import _kill_tree

NO_WINDOW = subprocess.CREATE_NO_WINDOW
SAMPLES = os.path.join('TiaArchiveCompare', 'runner', 'samples')
BEFORE, AFTER = 'Plant_2026-09-01.zap20', 'Plant_2026-10-28.zap20'
BRIDGE_TOOLS = {'background_open', 'full_export', 'background_close', 'compile', 'safety_login'}   # runner\bridge.py
WINDOW_SECONDS = 180

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p),
                ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD),
                ('dwThreadId', wintypes.DWORD)]


_user32.CreateDesktopW.restype = wintypes.HANDLE
_user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p]
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                                     wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                     ctypes.POINTER(PROCESS_INFORMATION)]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
GENERIC_ALL = 0x10000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_TIMEOUT = 0x102


class Results:
    """Records each finding and prints it as it comes."""

    def __init__(self):
        self.failed = []

    def record(self, holds, what):
        print('  %s %s' % ('ok  ' if holds else 'FAIL', what))
        if not holds:
            self.failed.append(what)
        return holds


@dataclass
class Download:
    """An unpacked download and the folder the check works in."""
    version: str
    root: str
    work: str
    env: dict

    @property
    def python(self):
        return os.path.join(self.root, PYTHON_DIR, 'python.exe')

    @property
    def launcher(self):
        return os.path.join(self.root, LAUNCHER)

    def sample(self, name):
        return os.path.join(self.root, SAMPLES, name)


def clean_env():
    """What a PC with no Python gives a program: System32 and Windows PowerShell on the PATH, no PYTHON* variables, no
    uv. Not the Windows folder: the Python launcher py.exe may stand there."""
    system = os.environ.get('SystemRoot', r'C:\Windows')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'UV_', 'VIRTUAL_ENV', 'CONDA'))}
    env['PATH'] = os.pathsep.join([os.path.join(system, 'System32'), os.path.dirname(POWERSHELL)])
    return env


def json_objects(text):
    """The JSON objects of the lines of text that hold one."""
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield value


def powershell_value(script, **env):
    """The output of a PowerShell command line that reads its input from environment variables."""
    done = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command',
                           '[Console]::OutputEncoding = [Text.Encoding]::UTF8; ' + script], capture_output=True,
                          encoding='utf-8', env=dict(os.environ, **env), creationflags=NO_WINDOW)
    return done.stdout.strip()


def run_on_desktop(command, cwd, env, desktop, seconds):
    """Starts command (a list) on the named desktop and waits for it; its exit code, or None after seconds (then
    its process tree is ended)."""
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = desktop
    pi = PROCESS_INFORMATION()
    block = ctypes.create_unicode_buffer(''.join('%s=%s\0' % kv for kv in sorted(env.items())) + '\0')
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
    if not _kernel32.CreateProcessW(None, line, None, None, False, CREATE_UNICODE_ENVIRONMENT, block, cwd,
                                    ctypes.byref(si), ctypes.byref(pi)):
        raise OSError('CreateProcess failed: %d' % ctypes.get_last_error())
    try:
        if _kernel32.WaitForSingleObject(pi.hProcess, seconds * 1000) == WAIT_TIMEOUT:
            _kill_tree(pi.dwProcessId)
            return None
        code = wintypes.DWORD()
        _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        return code.value
    finally:
        _kernel32.CloseHandle(pi.hThread)
        _kernel32.CloseHandle(pi.hProcess)


def run_window(command, cwd, env, visible):
    """Its exit code, or None when it did not end in time."""
    if visible:
        try:
            return subprocess.run(command, cwd=cwd, env=env, timeout=WINDOW_SECONDS).returncode
        except subprocess.TimeoutExpired:
            return None
    name = 'tia-compare-check-%d' % os.getpid()
    desktop = _user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not desktop:
        raise OSError('CreateDesktop failed: %d' % ctypes.get_last_error())
    try:
        return run_on_desktop(command, cwd, env, name, WINDOW_SECONDS)
    finally:
        _user32.CloseDesktop(desktop)


def pe_subsystem(path):
    """2: a Windows program, 3: a console program."""
    with open(path, 'rb') as f:
        data = f.read(4096)
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    return struct.unpack_from('<H', data, pe + 24 + 68)[0]


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def unpack(zip_path, work, results):
    """The Download, or None when the zip is not one."""
    name = re.search(r'^TIA-Archive-Compare-(\d+\.\d+\.\d+)\.zip$', os.path.basename(zip_path))
    if not results.record(bool(name), 'the zip is named by its version'):
        return None
    version = name.group(1)
    with zipfile.ZipFile(zip_path) as z:
        tops = {n.split('/')[0] for n in z.namelist()}
        z.extractall(work)
    if not results.record(tops == {package_name(version)}, 'the zip holds one folder, named as the zip: %s' % sorted(tops)):
        return None
    env = clean_env()
    results.record(shutil.which('python', path=env['PATH']) is None and shutil.which('py', path=env['PATH']) is None,
                   'no Python on the PATH of the check')
    return Download(version, os.path.join(work, package_name(version)), work, env)


def the_runner(d, results):
    cmd = [d.python, '-X', 'utf8', '-m', 'TiaArchiveCompare.runner', 'run', '--before', d.sample(BEFORE),
           '--after', d.sample(AFTER), '--exporter', 'fake', '--fake-speed', '0', '--hmi', '--no-ask',
           '--data-root', os.path.join(d.work, 'data'), '--out-root', os.path.join(d.work, 'runs')]
    done = subprocess.run(cmd, cwd=d.root, env=d.env, capture_output=True, encoding='utf-8', errors='replace',
                          stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=300)
    end = ([e for e in json_objects(done.stdout) if e.get('t') == 'end'] or [{}])[-1]
    report = end.get('report') or ''
    if not results.record(done.returncode == 0 and end.get('ok') and os.path.isfile(report),
                          'the runner compares the samples to a report: %s' % (report or done.stderr.strip()[-1500:])):
        print(done.stdout[-1500:])
        return
    with open(report, encoding='utf-8') as f:
        page = f.read()
    results.record('Filler' in page and 'Conveyor_Settings' in page,
                   'the report holds the PLC and the HMI of the samples (block Filler, the new screen Conveyor_Settings)')


def the_window(d, results, visible):
    snap = os.path.join(d.work, 'window')
    runner_args = subprocess.list2cmdline(['-X', 'utf8', '-m', 'TiaArchiveCompare.runner', 'run', '--exporter', 'fake',
                                           '--fake-speed', '0', '--data-root', os.path.join(d.work, 'data2'),
                                           '--out-root', os.path.join(d.work, 'runs2')])
    code = run_window([d.launcher, d.sample(BEFORE), '--snap', snap, '--after', d.sample(AFTER), '--hmi',
                       '--runner-args', runner_args, '--settings', os.path.join(d.work, 'window.json'),
                       '--timeout', '150'], d.root, d.env, visible)
    result = ''
    if os.path.isfile(os.path.join(snap, 'result.txt')):
        with open(os.path.join(snap, 'result.txt'), encoding='utf-8') as f:
            result = f.read()
    results.record(code == 0 and 'result: Done in' in result,
                   'the launcher starts the window, which compares the samples with the Python of the download '
                   '(exit %s): %s' % (code, result.splitlines()[0] if result else 'no result'))
    results.record('title: TIA Archive Compare %s\n' % d.version in result, 'the window\'s title carries the version')
    results.record('before: %s\n' % d.sample(BEFORE) in result, 'a file dropped on the launcher stands in Before')


def the_shortcut(d, results):
    links = os.path.join(d.work, 'links')
    os.makedirs(links)
    made = subprocess.run([d.python, '-X', 'utf8', '-m', 'TiaArchiveCompare.window.shortcut', '--folder', links],
                          cwd=d.root, env=d.env, capture_output=True, encoding='utf-8', errors='replace',
                          creationflags=NO_WINDOW)
    target = []
    if made.returncode == 0:
        target = powershell_value('$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); '
                                  '$l.TargetPath; $l.WorkingDirectory', LINK=made.stdout.strip()).splitlines()
    results.record(len(target) == 2 and same_path(target[0], d.launcher) and same_path(target[1], d.root),
                   'the shortcut starts the launcher of the unpacked folder: %s' % (target or made.stderr.strip()))


def the_launcher(d, results):
    results.record(pe_subsystem(d.launcher) == 2, 'the launcher is a Windows program: no console')
    version = powershell_value('(Get-Item -LiteralPath $env:EXE).VersionInfo.FileVersion', EXE=d.launcher)
    results.record(version == d.version, 'the launcher\'s file version is %s: %s' % (d.version, version))


def the_bridge(d, results):
    """The download's TiaBridge, started as runner\\bridge.py starts it, lists the tools the runner calls; no TIA is
    opened."""
    settings = os.path.join(d.work, 'bridge-settings.json')
    with open(settings, 'w', encoding='utf-8') as f:
        json.dump({'projectsRoot': os.path.join(d.work, 'bridge-projects')}, f)
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'check'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}]
    done = subprocess.run([POWERSHELL, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
                           os.path.join(d.root, 'TiaBridge', 'TiaBridge.ps1'), '-SettingsPath', settings],
                          input=''.join(json.dumps(m) + '\n' for m in messages), capture_output=True, encoding='utf-8',
                          errors='replace', env=d.env, cwd=d.work, creationflags=NO_WINDOW, timeout=120)
    listed = [m for m in json_objects(done.stdout) if m.get('id') == 2]
    tools = {t.get('name') for t in (listed[0].get('result') or {}).get('tools', [])} if listed else set()
    missing = BRIDGE_TOOLS - tools
    why = ''
    if not tools:
        why = ': ' + done.stderr.strip()[-1500:]
    elif missing:
        why = ': missing %s' % ', '.join(sorted(missing))
    results.record(not missing,
                   'the download\'s TiaBridge starts and lists %s%s' % (', '.join(sorted(BRIDGE_TOOLS)), why))


def check(zip_path, visible=False, keep=False):
    work = tempfile.mkdtemp(prefix='tia compare check ä-')
    results = Results()
    print('Check of %s' % zip_path)
    try:
        d = unpack(zip_path, work, results)
        if d:
            the_runner(d, results)
            the_window(d, results, visible)
            the_shortcut(d, results)
            the_launcher(d, results)
            the_bridge(d, results)
    finally:
        if keep:
            print('Kept: %s' % work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    print('%d failed' % len(results.failed) if results.failed else 'all ok')
    return 1 if results.failed else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m TiaArchiveCompare.package.check', description=__doc__.splitlines()[2])
    p.add_argument('zip')
    p.add_argument('--visible', action='store_true', help='the window on this desktop, not on a hidden one')
    p.add_argument('--keep', action='store_true', help='keep the unpacked folder and the runs')
    a = p.parse_args(argv)
    return check(os.path.abspath(a.zip), a.visible, a.keep)


if __name__ == '__main__':
    sys.exit(main())
