"""The viewer's window: the page written to a temp file and opened by Microsoft Edge as an app window (--app=), which
has no tabs and no address bar; Google Chrome where Edge is missing. Edge is on every Windows 11, so nothing is
installed. Standard library only.

  write_page(html, name)   -> the path of the page in %TEMP%\\TiaChangeReports-viewer, pages older than a day removed
  app_command(browser, path[, profile]) -> the browser's arguments
  open_window(path[, browser, profile, start]) -> starts the browser and returns, without waiting for its window
  message(text)            -> a Windows message box: the one thing said when no browser is found or the viewer fails

The browser runs with the person's own profile: a running Edge opens the window in its own process. profile: another
profile folder, for a check on a hidden desktop, where the window must come from a process of that desktop.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
WINCC = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'TiaHmiGenerator')
if WINCC not in sys.path:
    sys.path.insert(0, WINCC)
from hmipreview.edge import NOT_FOUND, edge_path  # noqa: E402  Edge, else Chrome: the report's PNG uses the same

PAGES = 'TiaChangeReports-viewer'
KEEP = 24 * 3600                       # s: a page the browser may still be reading stays this long
TITLE = 'Block viewer'
NO_BROWSER = 'The block viewer opens its window with Microsoft Edge or Google Chrome: ' + NOT_FOUND


def pages_folder():
    return os.path.join(tempfile.gettempdir(), PAGES)


def write_page(html, name, folder=None, now=None):
    """Write the page as <name>-<time>.html in folder (default pages_folder()); remove the pages there older than KEEP.
    Returns its path."""
    folder = folder or pages_folder()
    now = time.time() if now is None else now
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        try:
            if f.endswith('.html') and now - os.path.getmtime(p) > KEEP:
                os.remove(p)
        except OSError:
            pass                                         # open in another program: next time
    safe = re.sub(r'[^\w.-]+', '_', name)[:60] or 'block'
    path = os.path.join(folder, '%s-%d-%d.html' % (safe, int(now * 1000), os.getpid()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def app_command(browser, path, profile=None):
    """The browser's arguments for the page at path as an app window."""
    args = [browser, '--app=' + Path(os.path.abspath(path)).as_uri()]
    if profile:
        args[1:1] = ['--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check']
    return args


def open_window(path, browser=None, profile=None, start=None):
    """Start the browser on the page; raise LookupError(NO_BROWSER) when there is none. start: stands in for
    subprocess.Popen in a test."""
    browser = browser or edge_path()
    if not browser:
        raise LookupError(NO_BROWSER)
    (start or subprocess.Popen)(app_command(browser, path, profile), close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def message(text, title=TITLE):
    """A message box, for pythonw.exe, which has no console to print to; stderr as well."""
    if sys.stderr:                                       # None under pythonw.exe
        print(text, file=sys.stderr)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)       # MB_ICONERROR
    except (AttributeError, OSError):
        pass
