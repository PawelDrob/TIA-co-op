"""python -X utf8 -m TiaArchiveCompare.window.shortcut [--folder F]    (from the repo folder)

Makes the shortcut that starts the window, with no console at any moment: on the Desktop unless a folder is named. A
shortcut holds the paths of this clone, so each clone makes its own and none is tracked. In an unpacked download it
starts the download's launcher, "TIA Archive Compare.exe" at its top (package\\launcher.cs). No tkinter.
"""
import argparse
import os
import subprocess
import sys

NAME = 'TIA Archive Compare.lnk'
LAUNCHER = 'TIA Archive Compare.exe'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WINDOW_ARGUMENTS = '-X utf8 -m TiaArchiveCompare.window'
NO_WINDOW = subprocess.CREATE_NO_WINDOW

SAVE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$folder = $env:SHORTCUT_FOLDER
if (-not $folder) { $folder = [Environment]::GetFolderPath('Desktop') }
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder $env:SHORTCUT_NAME))
$link.TargetPath = $env:SHORTCUT_TARGET
$link.Arguments = $env:SHORTCUT_ARGUMENTS
$link.WorkingDirectory = $env:SHORTCUT_START_IN
$link.Save()
$link.FullName
"""


class ShortcutError(Exception):
    """In words for the person who ran the command."""


def window_python(root=ROOT):
    """pythonw.exe: a program of the Windows subsystem, so Windows makes it no console. The order of the runner's
    python.exe, RunnerCommand.resolve. Never one from PATH."""
    bundled = os.path.join(root, 'TiaArchiveCompare', 'window', 'python', 'pythonw.exe')
    if os.path.isfile(bundled):
        return bundled
    venv = os.path.join(root, '.venv', 'Scripts', 'pythonw.exe')
    if os.path.isfile(venv):
        return venv
    raise ShortcutError('The Python environment was not found: %s. Run uv sync in %s once.' % (venv, root))


def make(folder=None, root=ROOT, arguments=WINDOW_ARGUMENTS):
    """Writes the shortcut, over one of the same name, and returns its path. No folder: the Desktop, wherever Windows
    keeps it (OneDrive may hold it)."""
    if folder and not os.path.isdir(folder):
        raise ShortcutError('There is no folder %s.' % folder)
    launcher = os.path.join(root, LAUNCHER)
    target, arguments = (launcher, '') if os.path.isfile(launcher) else (window_python(root), arguments)
    env = dict(os.environ, SHORTCUT_FOLDER=os.path.abspath(folder) if folder else '', SHORTCUT_NAME=NAME,
               SHORTCUT_TARGET=target, SHORTCUT_ARGUMENTS=arguments, SHORTCUT_START_IN=root)
    done = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SAVE_SCRIPT], env=env,
                          capture_output=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW)
    if done.returncode:
        raise ShortcutError('The shortcut was not made: %s' % done.stderr.strip())
    return done.stdout.strip()


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m TiaArchiveCompare.window.shortcut', description=__doc__.splitlines()[2])
    p.add_argument('--folder', help='where the shortcut goes (default: your Desktop)')
    a = p.parse_args(argv)
    try:
        print(make(a.folder))
    except ShortcutError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
