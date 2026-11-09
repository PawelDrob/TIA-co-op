"""The preview servers running on this machine, for the TIA dashboard (TiaAgentStatus\\dashboard.py) to link to.

One record per server process, <folder()>\\<pid>.json: {repo, url, pid, started}. A server writes it once it listens and
removes it when it stops. One ended by Stop-Process leaves it behind: the next server to start removes the records of
processes that are gone, and a reader trusts a record only while GET <url>api/about answers with its repo and pid.
Standard library only: the dashboard reads the same folder without importing this package.
"""
import datetime
import json
import os
import tempfile

FOLDER_ENV = 'HMIPREVIEW_RUNNING'     # another folder, as the tests give one


def folder():
    """%LOCALAPPDATA%\\hmipreview\\running, else under the temp folder; HMIPREVIEW_RUNNING when set."""
    return os.environ.get(FOLDER_ENV) or os.path.join(
        os.environ.get('LOCALAPPDATA') or tempfile.gettempdir(), 'hmipreview', 'running')


def local_url(host, port):
    """The link to a server bound to host:port from this machine: loopback for all interfaces, else the host."""
    if host in ('', '0.0.0.0'):
        host = '127.0.0.1'
    elif host == '::':
        host = '::1'
    return 'http://%s:%d/' % ('[%s]' % host if ':' in host else host, port)


def record(repo_path, url, pid=None):
    return {'repo': os.path.abspath(repo_path), 'url': url, 'pid': os.getpid() if pid is None else pid,
            'started': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}


def path_of(where, pid):
    return os.path.join(where, '%d.json' % pid)


def write(where, rec):
    """Writes rec as the record of its pid, whole or not at all: a reader never sees half a file."""
    os.makedirs(where, exist_ok=True)
    final = path_of(where, rec['pid'])
    part = final + '.part'
    with open(part, 'w', encoding='utf-8') as f:
        json.dump(rec, f)
    os.replace(part, final)


def remove(where, pid):
    try:
        os.remove(path_of(where, pid))
    except OSError:
        pass


def prune(where, alive=None):
    """Removes the records whose process is gone (a server ended by Stop-Process leaves its record)."""
    alive = alive or is_alive
    try:
        names = os.listdir(where)
    except OSError:
        return
    for n in names:
        stem, ext = os.path.splitext(n)
        if ext == '.json' and stem.isdigit() and not alive(int(stem)):
            remove(where, int(stem))


def is_alive(pid):
    """True while a process of this number runs. A number Windows gave again to another process counts as running: the
    reader's check of the URL tells them apart."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    QUERY_LIMITED_INFORMATION, STILL_ACTIVE, ACCESS_DENIED = 0x1000, 259, 5
    h = k.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ctypes.get_last_error() == ACCESS_DENIED     # another user's process runs; a gone one is not found
    try:
        code = wintypes.DWORD()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        k.CloseHandle(h)
