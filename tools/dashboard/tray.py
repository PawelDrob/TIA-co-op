"""A dashboard's icon in the Windows notification area: its name and address as the tooltip, a left click opens the page in the
default browser, a right click a menu with Open and Stop.

serve() is what a dashboard calls in place of serve_forever. It knows the server only by serve_forever, shutdown and server_close,
and the icon is all in tray_icon.py, so the dashboards and their tests run without a desktop; here only guarded opens a box, and only
with no stderr. A session with no desktop gets no icon and goes on serving. Tests set DASHBOARD_NO_ICON, or a test run would put its
icons on the desktop of the person.

ctypes on Shell_NotifyIconW rather than pystray: no new dependency and no licence to list, for one icon and two menu items.
"""
import ctypes
import os
import sys
import traceback
import webbrowser
from pathlib import Path

NO_ICON = 'DASHBOARD_NO_ICON'
ICONS = Path(__file__).resolve().parent / 'icons'
DEVELOPMENT_NAME, DEVELOPMENT_ICON, DEVELOPMENT_ID = 'TIA-co-op: development dashboard', ICONS / 'development.ico', 1
TIA_NAME, TIA_ICON, TIA_ID = 'TIA-co-op: TIA dashboard', ICONS / 'tia.ico', 2     # both run on one pythonw.exe: Windows tells their taskbar settings apart by the id

MB_ICONERROR = 0x10


def say_on_stderr(text):
    """pythonw has none."""
    if sys.stderr is not None:
        print(text, file=sys.stderr, flush=True)


def show_box(title, text):
    ctypes.WinDLL('user32').MessageBoxW(None, text, title, MB_ICONERROR)


def guarded(title, main):
    """Runs a dashboard's start. With no console (pythonw by hand) what stops it comes up in a box, or a person sees nothing at
    all. With a stderr nothing changes: a session starts the server with one, also on the null device, and opens no box."""
    if sys.stderr is not None:
        return main()
    try:
        return main()
    except SystemExit as e:
        if not e.code:
            return 0
        show_box(title, e.code if isinstance(e.code, str) else f'It did not start (exit {e.code}). Run the same line with python.exe to read why.')
    except Exception:
        show_box(title, traceback.format_exc())
    return 1


def serve(server, name, url, icon_file, icon_id, make_icon=None):
    """Serves until Stop on the icon, a close of its window from outside or Ctrl+C, then takes the icon away. A page's open connection does not hold it up: its
    thread is a daemon. No icon comes up in a session with no desktop, and the server does not mind."""
    icon = None
    if not os.environ.get(NO_ICON) and os.name == 'nt':
        try:
            if not make_icon:
                from tray_icon import Icon as make_icon
            icon = make_icon(name, url, icon_file, icon_id, webbrowser.open, server.shutdown)
            icon.start()
        except Exception as e:
            say_on_stderr(f'{name}: no icon: {e}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if icon:
            icon.close()
        server.server_close()
