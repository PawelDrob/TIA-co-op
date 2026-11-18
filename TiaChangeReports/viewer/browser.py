"""Where the viewer's page opens: written to a temp file and opened in the default browser, as Windows opens any .html
file. Standard library only.

  write_page(html, name)   -> the path of the page in %TEMP%\\TiaChangeReports-viewer, pages older than a day removed
  open_page(path[, start]) -> the page in the default browser, without waiting for it
  message(text)            -> a Windows message box: what is said when the page cannot be opened or the viewer fails
"""
import os
import re
import sys
import tempfile
import time

PAGES = 'TiaChangeReports-viewer'
KEEP = 24 * 3600                       # s: a page the browser may still be reading stays this long
TITLE = 'Block viewer'


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


def open_page(path, start=None):
    """The page in the default browser (ShellExecute's open, as a double-click on an .html file). start: stands in
    for os.startfile in a test. Raises OSError when Windows cannot open it."""
    (start or os.startfile)(os.path.abspath(path))


def message(text, title=TITLE):
    """A message box, for pythonw.exe, which has no console to print to; stderr as well."""
    if sys.stderr:                                       # None under pythonw.exe
        print(text, file=sys.stderr)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)       # MB_ICONERROR
    except (AttributeError, OSError):
        pass
