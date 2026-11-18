"""Manual check, outside the suites: what a double-click starts opens one window of the browser with the block drawn, and
no console. It opens that window, so it runs on a desktop of its own, never on yours:

    <py> TiaChangeReports\\viewer\\check_window.py [--out <folder>] [<file> ...]

It registers the viewer in a key of its own under HKEY_CURRENT_USER (never .s7dcl's own), reads the open command back
from there as Explorer would, and runs it on each file (default: a LAD block and a file it cannot draw, made up) on a
hidden desktop, with --profile added: a browser profile folder of its own, as a browser already running for you would
open the window on your desktop. It is the command Explorer runs, started by CreateProcess rather than by Explorer.
Meanwhile it looks for console windows on that desktop, visible or not, and for new visible ones on yours. Each file:
one visible window of the browser titled as the block, a PNG of it in --out (PrintWindow), then the window closed.
Exit code 0 when each file opened one window and no console came up. It writes the PNGs and nothing else outside temp.
"""
import argparse
import ctypes
import os
import shutil
import sys
import tempfile
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from TiaChangeReports.viewer import register, view                  # noqa: E402

CONSOLE_CLASSES = ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS')
GENERIC_ALL, PROCESS_QUERY_LIMITED_INFORMATION = 0x10000000, 0x1000
WM_CLOSE, PW_RENDERFULLCONTENT, SRCCOPY = 0x0010, 2, 0x00CC0020

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ENUM, wintypes.LPARAM]
user32.EnumWindows.argtypes = [ENUM, wintypes.LPARAM]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindow.restype, user32.GetWindow.argtypes = wintypes.HWND, [wintypes.HWND, wintypes.UINT]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetDC.restype, user32.GetDC.argtypes = wintypes.HDC, [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = wintypes.HDC, [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                            wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR)] + \
               [(n, wintypes.DWORD) for n in ('dwX', 'dwY', 'dwXSize', 'dwYSize', 'dwXCountChars', 'dwYCountChars',
                                              'dwFillAttribute', 'dwFlags')] + \
               [('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p)] + \
               [(n, wintypes.HANDLE) for n in ('hStdInput', 'hStdOutput', 'hStdError')]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD),
                ('dwThreadId', wintypes.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


failed = []


def check(ok, what):
    print(('ok    ' if ok else 'FAIL  ') + what, flush=True)
    if not ok:
        failed.append(what)
    return ok


def _text(fn, hwnd):
    buf = ctypes.create_unicode_buffer(512)
    fn(hwnd, buf, 512)
    return buf.value


def program(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return 'process %d' % pid.value
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value) if ok else 'process %d' % pid.value
    finally:
        kernel32.CloseHandle(h)


def windows(desktop=None):
    """[(hwnd, class, title, visible, program)] of the top-level windows on desktop (a handle), or on this one."""
    found = []

    def note(hwnd, _):
        found.append((hwnd, _text(user32.GetClassNameW, hwnd), _text(user32.GetWindowTextW, hwnd),
                      bool(user32.IsWindowVisible(hwnd)), program(hwnd)))
        return True
    if desktop is None:
        user32.EnumWindows(ENUM(note), 0)
    else:
        user32.EnumDesktopWindows(desktop, ENUM(note), 0)
    return found


def consoles(desktop=None, visible_only=False):
    return {w[0]: w[4] for w in windows(desktop) if w[1] in CONSOLE_CLASSES and (w[3] or not visible_only)}


def start(desktop_name, line):
    si = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW), lpDesktop=desktop_name)
    pi = PROCESS_INFORMATION()
    if not kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(line), None, None, False, 0, None, None,
                                   ctypes.byref(si), ctypes.byref(pi)):
        return False
    kernel32.CloseHandle(pi.hProcess)
    kernel32.CloseHandle(pi.hThread)
    return True


def shoot(hwnd, png):
    """A PNG of the window, drawn by itself into a bitmap (PrintWindow): a hidden desktop shows nothing on a screen."""
    from PIL import Image
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    screen = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(dc, bmp)
    try:
        user32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)
        bi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(dc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1).save(png)
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, screen)


LAD = '''FUNCTION_BLOCK "Conveyor"
    VAR_INPUT
        start : Bool;
        stop : Bool;
    END_VAR
    VAR
        running : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #start )
        END_RUNG wire#w1
        RUNG wire#powerrail
            Contact( #running )
        END_RUNG wire#w1
        RUNG wire#w1
            I_Contact( #stop )
            Coil( #running )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''


def main(argv=None):
    p = argparse.ArgumentParser(prog='check_window')
    p.add_argument('files', nargs='*')
    p.add_argument('--out', default='.', help='folder for the PNGs (default: here)')
    a = p.parse_args(argv)
    tmp = tempfile.mkdtemp(prefix='viewer-check-')
    files = a.files
    if not files:
        files = [os.path.join(tmp, 'Conveyor.s7dcl'), os.path.join(tmp, 'Broken.s7dcl')]
        for f, text in zip(files, (LAD, 'FUNCTION_BLOCK "Broken"\n')):
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write(text)
    key = r'Software\TiaChangeReportsViewerCheck-%d' % os.getpid()
    name = 'zz-viewer-check-%d' % os.getpid()
    desktop = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not check(bool(desktop), 'a desktop of its own could be made'):
        return 1
    mine_before = set(consoles(visible_only=True))
    seen_there, seen_here = {}, {}
    try:
        register.register(classes=key + r'\Classes', choice=key + r'\UserChoice', notify=False)
        cmd = register.read_value(key + r'\Classes', register.PROGID + r'\shell\open\command')
        for k, f in enumerate(files):
            title = view.page(f)[1]
            profile = os.path.join(tmp, 'profile-%d' % k)
            line = cmd.replace('%1', os.path.abspath(f)) + ' --profile "%s"' % profile
            if not check(start(name, line), 'started on the hidden desktop: %s' % line):
                continue
            found, until = [], time.time() + 30
            while time.time() < until and not found:
                seen_there.update(consoles(desktop))
                seen_here.update({h: o for h, o in consoles(visible_only=True).items() if h not in mine_before})
                found = [w for w in windows(desktop) if w[3] and w[2] == title]
                time.sleep(0.05)
            time.sleep(2)                                              # the page draws
            found = [w for w in windows(desktop) if w[3] and w[2] == title]
            others = [w for w in windows(desktop) if w[3] and w[2] and w[2] != title and w[4] == (found or [w])[0][4]]
            check(len(found) == 1, '%s: one visible window titled "%s": %s' % (os.path.basename(f), title,
                                                                            [(w[1], w[4]) for w in found]))
            check(not others, '%s: no other visible window of the browser: %s' % (os.path.basename(f),
                                                                                  [(w[2], w[1]) for w in others]))
            for hwnd, *_ in found[:1]:
                png = os.path.abspath(os.path.join(a.out, 'window-%s.png' % os.path.splitext(os.path.basename(f))[0]))
                shoot(hwnd, png)
                print('      ' + png)
            for hwnd, *_ in found:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            time.sleep(2)
    finally:
        register.delete_tree('Software', key.split('\\', 1)[1])
        user32.CloseDesktop(desktop)
        time.sleep(1)
        shutil.rmtree(tmp, ignore_errors=True)
    check(not seen_there, 'no console window on its desktop: %s' % sorted(seen_there.values()))
    check(not seen_here, 'no new console window on this desktop: %s' % sorted(seen_here.values()))
    print('%d failed' % len(failed) if failed else 'all ok')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
