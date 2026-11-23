"""Headless Microsoft Edge, else Google Chrome (for a PC without Edge), shared by the PNG commands
(python -m hmipreview png, TiaChangeReports --png) and the browser tests. Standard library only. Both are Chromium:
the same flags, the same PNG.

  edge_path()                    -> msedge.exe, else chrome.exe (Program Files, x86, per user), or None
  Edge().dump_dom(url[, size=(w, h)]) -> str
                                 one `--headless --dump-dom` run: the DOM after the page has drawn
                                 (in a window of w x h CSS px when given)
  Edge().screenshot(url, out, width, height)
                                 one `--headless --screenshot` run with a window of width x height CSS px
                                 at device scale factor 1, so the PNG has exactly that size
  close()                        ends the browser processes of its runs and removes the temp profile

Every run uses the same temp profile (--user-data-dir) and kills the processes of the run afterwards: headless
children can outlive the parent. The browser starts in a Windows job object, held before it runs, so every process it
starts is in the job too; the end of the job ends them and waits until they have. Where Windows gives no job, the
processes are found by the profile on their command line, by a PowerShell of about 0.8 s a run. The preview page is
driven by its URL hooks (static/app.js); pass ?live=0, an open change stream keeps virtual time from running out and
the browser would never dump or shoot.
"""
import ctypes
import os
import shutil
import subprocess
import tempfile
import time

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)     # the server runs with no console: powershell would open a window

NOT_FOUND = ('neither Microsoft Edge (msedge.exe) nor Google Chrome (chrome.exe) found under Program Files or '
             '%LOCALAPPDATA%')

if os.name == 'nt':
    from ctypes import wintypes

    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)

    def _api(name, restype, *argtypes):
        f = getattr(_k32, name)
        f.restype, f.argtypes = restype, list(argtypes)
        return f

    class _BasicLimit(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', _BasicLimit), ('IoInfo', ctypes.c_uint64 * 6),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    class _ProcessIds(ctypes.Structure):
        _fields_ = [('NumberOfAssignedProcesses', wintypes.DWORD), ('NumberOfProcessIdsInList', wintypes.DWORD),
                    ('ProcessIdList', ctypes.c_size_t * 256)]

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ThreadID', wintypes.DWORD),
                    ('th32OwnerProcessID', wintypes.DWORD), ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD)]

    _CreateJobObject = _api('CreateJobObjectW', wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
    _SetInformationJobObject = _api('SetInformationJobObject', wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                                    wintypes.LPVOID, wintypes.DWORD)
    _QueryInformationJobObject = _api('QueryInformationJobObject', wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID)
    _AssignProcessToJobObject = _api('AssignProcessToJobObject', wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
    _TerminateJobObject = _api('TerminateJobObject', wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _OpenProcess = _api('OpenProcess', wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _OpenThread = _api('OpenThread', wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _ResumeThread = _api('ResumeThread', wintypes.DWORD, wintypes.HANDLE)
    _WaitForSingleObject = _api('WaitForSingleObject', wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
    _CreateToolhelp32Snapshot = _api('CreateToolhelp32Snapshot', wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
    _Thread32First = _api('Thread32First', wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_ThreadEntry))
    _Thread32Next = _api('Thread32Next', wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_ThreadEntry))
    _CloseHandle = _api('CloseHandle', wintypes.BOOL, wintypes.HANDLE)

    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _JOB_BASIC_PROCESS_ID_LIST, _JOB_EXTENDED_LIMIT_INFORMATION = 3, 9
    _JOB_KILL_ON_JOB_CLOSE = 0x2000                 # this process gone, its browsers go too
    _PROCESS_TERMINATE, _PROCESS_SET_QUOTA, _SYNCHRONIZE = 0x1, 0x100, 0x100000
    _THREAD_SUSPEND_RESUME = 0x2
    _TH32CS_SNAPTHREAD = 0x4


def _failed(what):
    return ctypes.WinError(ctypes.get_last_error(), '%s failed' % what)


def _resume(pid):
    """Let the threads of process pid run: started suspended, it has one."""
    snap = _CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap or snap == _INVALID_HANDLE:
        raise _failed('CreateToolhelp32Snapshot')
    resumed = 0
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = _Thread32First(snap, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = _OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if not thread:
                    raise _failed('OpenThread')
                try:
                    if _ResumeThread(thread) == 0xFFFFFFFF:
                        raise _failed('ResumeThread')
                finally:
                    _CloseHandle(thread)
                resumed += 1
            more = _Thread32Next(snap, ctypes.byref(entry))
    finally:
        _CloseHandle(snap)
    if not resumed:
        raise OSError('no thread of process %d to resume' % pid)


class _Job:
    """A Windows job object; OSError when Windows gives none."""

    def __init__(self):
        self.handle = _CreateJobObject(None, None)
        if not self.handle:
            raise _failed('CreateJobObject')
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_JOB_CLOSE
        if not _SetInformationJobObject(self.handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                        ctypes.sizeof(info)):
            error = _failed('SetInformationJobObject')
            _CloseHandle(self.handle)
            raise error

    def start(self, args, env):
        """subprocess.Popen(args) with no window and its output read, in this job before it runs: a process it starts is
        in the job from its start."""
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                # 0x4: CREATE_SUSPENDED, which subprocess does not name
                                creationflags=NO_WINDOW | 0x4)
        try:
            handle = _OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, proc.pid)
            if not handle:
                raise _failed('OpenProcess')
            try:
                if not _AssignProcessToJobObject(self.handle, handle):
                    raise _failed('AssignProcessToJobObject')
            finally:
                _CloseHandle(handle)
            _resume(proc.pid)
        except BaseException:
            proc.kill()
            proc.communicate()
            raise
        return proc

    def end(self, wait=10):
        """End every process of the job and wait, up to wait s, until each has: a process ended is one whose files
        are let go, the profile's too."""
        ids = _ProcessIds()
        _QueryInformationJobObject(self.handle, _JOB_BASIC_PROCESS_ID_LIST, ctypes.byref(ids), ctypes.sizeof(ids), None)
        held = [_OpenProcess(_SYNCHRONIZE, False, pid) for pid in ids.ProcessIdList[:ids.NumberOfProcessIdsInList]]
        try:
            _TerminateJobObject(self.handle, 1)
            until = time.monotonic() + wait
            for process in filter(None, held):
                _WaitForSingleObject(process, max(0, int((until - time.monotonic()) * 1000)))
        finally:
            for process in filter(None, held):
                _CloseHandle(process)
            _CloseHandle(self.handle)


def candidates():
    roots = [os.environ.get(v) for v in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
    roots = [r for r in roots if r] or [r'C:\Program Files (x86)', r'C:\Program Files']
    return ([os.path.join(r, 'Microsoft', 'Edge', 'Application', 'msedge.exe') for r in roots]
            + [os.path.join(r, 'Google', 'Chrome', 'Application', 'chrome.exe') for r in roots])


def edge_path():
    for p in candidates():
        if os.path.isfile(p):
            return p
    return None


class EdgeError(Exception):
    pass


class Edge:
    def __init__(self, path=None):
        self.path = path or edge_path()
        if not self.path:
            raise EdgeError(NOT_FOUND)
        self.profile = tempfile.mkdtemp(prefix='hmipreview-edge-')
        self._jobs = []
        self._outside_a_job = False      # a run Windows gave no job: kill() finds its processes by their command line

    def environment(self):
        """For a browser process: on some runs it leaves a folder in its temp folder, which here goes with the profile."""
        return dict(os.environ, TEMP=self.profile, TMP=self.profile)

    def _start(self, args):
        if os.name == 'nt':
            try:
                job = _Job()
            except OSError:
                pass
            else:
                try:
                    proc = job.start(args, self.environment())
                except OSError:
                    job.end()
                else:
                    self._jobs.append(job)
                    return proc
        self._outside_a_job = True
        return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment(),
                                creationflags=NO_WINDOW)

    def _run(self, extra, url, budget, timeout):
        args = [self.path, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                '--disable-extensions', '--hide-scrollbars', '--user-data-dir=' + self.profile]
        if budget is not None:
            args.append('--virtual-time-budget=%d' % budget)
        args += list(extra) + [url]
        proc = self._start(args)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except BaseException:
            self.kill()
            proc.kill()
            proc.communicate()
            raise
        finally:
            self.kill()
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)

    def dump_dom(self, url, budget=8000, timeout=40, size=None):
        """budget None: no virtual time budget, for a page that never lets virtual time run out (a live connection)."""
        extra = ['--dump-dom'] + (['--window-size=%d,%d' % size] if size else [])
        return self._run(extra, url, budget, timeout).stdout.decode('utf-8', 'replace')

    def screenshot(self, url, out, width, height, budget=8000, timeout=60):
        """Write a PNG of the page at width x height pixels to out; raise EdgeError when none is written."""
        out = os.path.abspath(out)
        if os.path.exists(out):
            os.remove(out)
        p = self._run(['--screenshot=' + out, '--window-size=%d,%d' % (width, height),
                       '--force-device-scale-factor=1'], url, budget, timeout)
        if not os.path.isfile(out):
            raise EdgeError('%s wrote no screenshot (exit %s): %s'
                            % (os.path.basename(self.path), p.returncode,
                               p.stderr.decode('utf-8', 'replace').strip()[-500:]))
        return out

    def kill(self):
        """End the processes of the runs so far: those of each job, and those on the profile after a run with no job."""
        while self._jobs:
            self._jobs.pop().end()
        if self._outside_a_job:
            self._outside_a_job = False
            flt = self.profile.replace("'", "''")
            exe = os.path.basename(self.path).replace("'", "''")
            subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
                            "Where-Object { $_.CommandLine -like '*%s*' } | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                            % (exe, flt)],
                           capture_output=True, timeout=60, creationflags=NO_WINDOW)

    def close(self, ignore_errors=False):
        """Stop the browser and remove its profile. A profile that cannot go raises, unless ignore_errors: a caller whose
        result is already written has nothing to gain from failing over a temp folder."""
        self.kill()
        if os.path.exists(self.profile):
            shutil.rmtree(self.profile, ignore_errors=ignore_errors)
