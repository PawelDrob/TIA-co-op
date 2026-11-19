"""pythonw -X utf8 -m tools.setup.window [--page N | --settings] [--snap DIR [--snap-changes]]
                                     [--viewer-key KEY] [--ports DEV,TIA] [--first-run FILE]

(from the clone's folder; Setup.wsf at its top starts it so, with no console at any moment)

The first setup of the clone as pages, one question each, until Finish; after that the settings: what is registered and
where, the dashboards, and every page again. It runs first setup's own steps (tools\\setup\\setup.py).
--page N opens page N, --settings the settings, whether the first run is done or not.
--snap DIR: no one at the window: a picture of each page and of the settings, in DIR, then it ends (tests\\check_window.py).
  --snap-changes also presses every button that changes something, on the pages that have one, and pictures the outcome:
  only with --viewer-key and an environment of a test (a temp Claude config, a temp home).
--viewer-key KEY: register the block viewer under HKEY_CURRENT_USER\\KEY\\Classes, not for real (a test's key).
--ports DEV,TIA: the dashboards' ports, for a test. --first-run FILE: where the end of the first run is kept, for a test.
"""
import argparse
import ctypes
import sys
import traceback

TITLE = 'TIA-co-op setup'


def parse(argv):
    p = argparse.ArgumentParser(prog='python -m tools.setup.window')
    where = p.add_mutually_exclusive_group()
    where.add_argument('--page', type=int)
    where.add_argument('--settings', action='store_true')
    p.add_argument('--snap')
    p.add_argument('--snap-changes', action='store_true')
    p.add_argument('--viewer-key')
    p.add_argument('--ports')
    p.add_argument('--first-run')
    return p.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    if a.snap_changes and not a.viewer_key:
        raise SystemExit('--snap-changes needs --viewer-key: it registers the viewer')
    from tools.setup import setup
    from tools.setup.window import model
    from tools.setup.window.main_window import Context, SetupWindow

    keys = (a.viewer_key + r'\Classes', a.viewer_key + r'\UserChoice') if a.viewer_key else ()
    ports = tuple(int(p) for p in a.ports.split(',')) if a.ports else None
    context = Context(setup, model.FirstRun(a.first_run), keys, ports)
    ctypes.windll.shcore.SetProcessDpiAwareness(1)     # sharp text on a scaled screen
    page = a.page - 1 if a.page else None
    window = SetupWindow(context, page)
    if a.settings:
        window.go(None)
    if a.snap:
        from tools.setup.window.snapshot import Snapshot
        return Snapshot(window, a.snap, a.snap_changes).run()
    window.mainloop()
    return 0


def show_failure():
    """pythonw has no console: without this a window that cannot start says nothing."""
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), TITLE, 0x10)
    return 1


def start(argv=None):
    try:
        return main(argv)
    except SystemExit as e:
        return show_failure() if e.code else 0      # --help ends with 0, a wrong argument with 2
    except Exception:
        return show_failure()


if __name__ == '__main__':
    sys.exit(start())
