"""pythonw -X utf8 -m tools.setup.window [--page N | --settings] [--snap DIR [--snap-changes] [--snap-folder F]]
                                     [--viewer-key KEY] [--ports DEV,TIA] [--first-run FILE]

(from the clone's folder; Setup.wsf at its top starts it so, with no console at any moment)

The first setup of the clone, page by page, until Finish; after that a menu that opens each page. It runs first setup's
own steps (tools\\setup\\setup.py).
--page N opens page N, --settings the menu, whether the first run is done or not.
--snap DIR: no one at the window: a picture of each page and of the menu, in DIR, then it ends (tests\\check_window.py).
  Only with --first-run. --snap-changes also presses every button that changes something and pictures the outcome: only
  with --viewer-key and CLAUDE_CONFIG_DIR in the temp folder, a test's (refusal()). --snap-folder F: F typed in the Bridge
  page's folder field first, as a person changing the folder does.
--viewer-key KEY: register the block viewer under HKEY_CURRENT_USER\\KEY\\Classes, not for real (a test's key).
--ports DEV,TIA: the dashboards' ports, for a test. --first-run FILE: where the end of the first run is kept, for a test.
"""
import argparse
import ctypes
import os
import sys
import tempfile
import traceback

TITLE = 'TIA-co-op setup'


def parse(argv):
    p = argparse.ArgumentParser(prog='python -m tools.setup.window')
    where = p.add_mutually_exclusive_group()
    where.add_argument('--page', type=int)
    where.add_argument('--settings', action='store_true')
    p.add_argument('--snap')
    p.add_argument('--snap-changes', action='store_true')
    p.add_argument('--snap-folder')
    p.add_argument('--viewer-key')
    p.add_argument('--ports')
    p.add_argument('--first-run')
    return p.parse_args(argv)


def refusal(a, environ=os.environ):
    """Why a run with no one at the window would touch what is the person's own, '' when it would not: --snap finishes
    the first run, so it keeps that in --first-run; --snap-changes presses every button, so it registers the viewer under
    --viewer-key and needs a Claude config in the temp folder, a test's (CLAUDE_CONFIG_DIR)."""
    if a.snap and not a.first_run:
        return '--snap needs --first-run: it finishes the first run, which would otherwise count as yours'
    if a.snap_changes:
        config = environ.get('CLAUDE_CONFIG_DIR', '')
        if not a.viewer_key:
            return '--snap-changes needs --viewer-key: it registers the viewer'
        if not (config and os.path.normcase(os.path.abspath(config)).startswith(os.path.normcase(tempfile.gettempdir()) + os.sep)):
            return '--snap-changes needs CLAUDE_CONFIG_DIR in the temp folder: it registers the server, installs the plugin and writes the status line'
    return ''


def main(argv=None):
    a = parse(argv)
    refused = refusal(a)
    if refused:
        raise SystemExit(refused)
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
        window.walking = False
        window.go(None)
    if a.snap:
        from tools.setup.window.snapshot import Snapshot
        return Snapshot(window, a.snap, a.snap_changes, a.snap_folder).run()
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
