"""python TiaChangeReports\\viewer <file> [--html out.html] [--lang en-US]
python TiaChangeReports\\viewer --register | --unregister

(from anywhere; python: the .venv's, pythonw.exe for no console)

<file>: a block export, .s7dcl (its .s7res beside it) or the SimaticML .xml of a block. Opens a window of its own with
the block drawn as the change report draws it, and a switch to the file's text. A file it cannot draw opens on its
text, with why. --html: writes the page to out.html instead, no window. --lang: the language of titles and comments
(default en-US, else the first language with a text).
--register: a double-click on an .s7dcl opens it here, for the current user; --unregister takes that back.
Exit code 0; 2 on a usage error; 1 when no window could be opened (said in a message box too: pythonw.exe has no
console).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from TiaChangeReports import s7dcl                                  # noqa: E402
from TiaChangeReports.viewer import register, view, window       # noqa: E402


def main(argv=None, open_window=window.open_window, message=window.message):
    p = argparse.ArgumentParser(prog='TiaChangeReports\\viewer')
    p.add_argument('file', nargs='?', help='a block export: .s7dcl, or the SimaticML .xml of a block')
    p.add_argument('--html', metavar='OUT', help='write the page to OUT, no window')
    p.add_argument('--lang', default='en-US', help='text language of titles and comments (default en-US)')
    p.add_argument('--profile', help=argparse.SUPPRESS)          # a browser profile folder: a check's hidden desktop
    todo = p.add_mutually_exclusive_group()
    todo.add_argument('--register', action='store_true', help='open .s7dcl files here on a double-click')
    todo.add_argument('--unregister', action='store_true', help='take --register back')
    a = p.parse_args(argv)
    if a.register or a.unregister:
        if a.file or a.html:
            p.error('--register and --unregister take no file')
        for line in register.register() if a.register else register.unregister():
            _say(line)
        return 0
    if not a.file:
        p.error('give a block export, or --register')
    s7dcl.LANG = a.lang
    html, title = view.page(a.file)
    if a.html:
        with open(a.html, 'w', encoding='utf-8') as f:
            f.write(html)
        _say(os.path.abspath(a.html))
        return 0
    try:
        open_window(window.write_page(html, title), profile=a.profile)
    except Exception as ex:                                       # noqa: BLE001 - said, not a console's traceback
        message(str(ex) if isinstance(ex, LookupError) else 'The block viewer could not open %s: %s' % (a.file, ex))
        return 1
    return 0


def _say(line):
    if sys.stdout:                                                # None under pythonw.exe
        print(line)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if stream:
            stream.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as ex:                                   # noqa: BLE001 - pythonw.exe: no console to show it
        window.message('The block viewer failed: %s: %s' % (type(ex).__name__, ex))
        sys.exit(1)
