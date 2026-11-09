"""Processes of this Windows machine through kernel32 (ctypes, no psutil): the process tree, and for one process its
start time, CPU time and memory. Tests use a fake with the same two methods (tests/fakes.py)."""
import ctypes
import datetime
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
EPOCH_AS_FILETIME = 116444736000000000   # 1970-01-01 in 100 ns since 1601-01-01


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


def _filetime(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class WinProcesses:
    def __init__(self):
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        self._k = k

    def tree(self):
        """{pid: (parent pid, exe name)} of every process."""
        k = self._k
        snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID_HANDLE_VALUE:
            return {}
        out = {}
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
                ok = k.Process32NextW(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        return out

    def info(self, pid):
        """{created (UTC datetime), cpu (s, kernel + user), memory (working set bytes)} of a running process, else
        None (gone, or not readable)."""
        k = self._k
        if not pid or pid <= 0:
            return None
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
                return None
            c, x, kt, ut = (wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(kt), ctypes.byref(ut)):
                return None
            created = datetime.datetime.fromtimestamp((_filetime(c) - EPOCH_AS_FILETIME) / 1e7, datetime.timezone.utc)
            m = PROCESS_MEMORY_COUNTERS()
            m.cb = ctypes.sizeof(m)
            memory = m.WorkingSetSize if k.K32GetProcessMemoryInfo(h, ctypes.byref(m), m.cb) else None
            return {'created': created, 'cpu': (_filetime(kt) + _filetime(ut)) / 1e7, 'memory': memory}
        finally:
            k.CloseHandle(h)
