"""python -m TiaArchiveCompare.window [FILE [FILE]] [--before P] [--after P] [--git REPO] [--title T] [--compile] [--safety] [--hmi] [--no-cache]
                                   [--runner EXE] [--runner-args "ARGUMENTS BEFORE --before"] [--settings PATH]
                                   [--snap DIR [--shots MS,MS] [--cancel-at MS] [--stop-now-after S]
                                    [--answer skip|PW|USER:PW] [--umc-global] [--details] [--drop PATH] [--timeout S]]

(from the repo root; the shortcut of shortcut.py does that for a user, with pythonw so no console opens)

Shows the window. FILE: a file dropped on the shortcut or the download's launcher, which Windows passes as an argument;
the files fill the boxes --before and --after leave empty, Before first.
--git: it opens on two commits of that repo; --before and --after then name commits. --snap runs one comparison with no one at the window and writes screenshots, the result and the log:
tests\\check.py uses it.
"""
import argparse
import ctypes
import os
import shlex
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def parse(argv):
    p = argparse.ArgumentParser(prog='python -m TiaArchiveCompare.window')
    p.add_argument('files', nargs='*')
    p.add_argument('--before')
    p.add_argument('--after')
    p.add_argument('--git')
    p.add_argument('--title')
    p.add_argument('--compile', action='store_true')
    p.add_argument('--safety', action='store_true')
    p.add_argument('--hmi', action='store_true')
    p.add_argument('--no-cache', action='store_true')
    p.add_argument('--details', action='store_true')
    p.add_argument('--runner')
    p.add_argument('--runner-args')
    p.add_argument('--settings')
    p.add_argument('--snap')
    p.add_argument('--shots')
    p.add_argument('--cancel-at', type=int)
    p.add_argument('--stop-now-after', type=float)
    p.add_argument('--answer', default='skip')
    p.add_argument('--umc-global', action='store_true')
    p.add_argument('--drop')
    p.add_argument('--timeout', type=int, default=120)
    return p.parse_args(argv)


def inputs(a):
    """Before and after: the options, and the files dropped on the shortcut in the boxes they leave empty, Before
    first."""
    files = iter(a.files)
    before = a.before or next(files, '')
    return before, a.after or next(files, '')


def main(argv=None):
    a = parse(argv)
    from TiaArchiveCompare.window.main_window import MainWindow
    from TiaArchiveCompare.window.runner_process import RunnerCommand
    from TiaArchiveCompare.window.settings import default_path

    prefix = [part.strip('"') for part in shlex.split(a.runner_args, posix=False)] if a.runner_args is not None else None
    ctypes.windll.shcore.SetProcessDpiAwareness(1)     # sharp text on a scaled screen
    window = MainWindow(RunnerCommand.resolve(a.runner, prefix, HERE), a.settings or default_path())
    if a.git:
        window.from_commits.set(True)
        window.use_repo(a.git, a.before, a.after)
    else:
        before, after = inputs(a)
        window.before_path.set(before)
        window.after_path.set(after)
    window.title_text.set(a.title or '')
    window.compile.set(a.compile)
    window.safety.set(a.safety)
    window.hmi.set(a.hmi)
    window.no_cache.set(a.no_cache)
    window.details.set(a.details)
    if a.snap:
        from TiaArchiveCompare.window.snapshot import Snapshot
        return Snapshot(window, a.snap, a).run()
    window.mainloop()
    return 0


def show_failure():
    """pythonw has no console: without this a window that cannot start says nothing."""
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), 'TIA Archive Compare', 0x10)
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
