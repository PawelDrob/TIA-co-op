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
  close()                        kills every browser process still using the temp profile and removes it

Every run uses the same temp profile (--user-data-dir) and kills the processes on it afterwards: headless
children can outlive the parent. The preview page is driven by its URL hooks (static/app.js); pass ?live=0, an
open change stream keeps virtual time from running out and the browser would never dump or shoot.
"""
import os
import shutil
import subprocess
import tempfile

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)     # the server runs with no console: powershell would open a window

NOT_FOUND = ('neither Microsoft Edge (msedge.exe) nor Google Chrome (chrome.exe) found under Program Files or '
             '%LOCALAPPDATA%')


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

    def environment(self):
        """For a browser process: on some runs it leaves a folder in its temp folder, which here goes with the profile."""
        return dict(os.environ, TEMP=self.profile, TMP=self.profile)

    def _run(self, extra, url, budget, timeout):
        args = [self.path, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                '--disable-extensions', '--hide-scrollbars', '--user-data-dir=' + self.profile,
                '--virtual-time-budget=%d' % budget] + list(extra) + [url]
        try:
            return subprocess.run(args, capture_output=True, timeout=timeout, env=self.environment(), creationflags=NO_WINDOW)
        finally:
            self.kill()

    def dump_dom(self, url, budget=8000, timeout=40, size=None):
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
        """Stop every browser process still running on this profile."""
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
