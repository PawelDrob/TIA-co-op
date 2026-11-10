"""Manual check of the real icons, outside the suites. Without --hidden it shows them on your desktop, and moves the mouse for the clicks
on their menus, so leave the mouse alone for a minute, and run it only on a PC nobody is using; each such run leaves entries named with its
test ports in Windows' list of tray icons (Settings, Taskbar, Other system tray icons). Both dashboards on free ports with made-up folders,
removed at the end; the ones you run stay as they are.

    python tools\\dashboard\\tests\\tray_check.py [--shots DIR] [--hold SECONDS]
    python tools\\dashboard\\tests\\tray_check.py --hidden

What it does: starts each as a person does (through the shell, nothing handed on) and as a session does (the review_page.py command);
watches for any new console window all the while; looks for a console in their process trees; starts one twice, by hand and as a session;
a real left click on each icon opens its page, behind the ^ button or on the taskbar; clicks Open and Stop on the real menus, opened by real
right clicks; then the part of --hidden. Open goes to a recorder through the BROWSER setting: no browser opens.
--shots saves pictures of the icons, tooltips, menus and the box, cut to just those; --hold keeps the icons up that long to look at them.

--hidden runs only the part that shows nothing and leaves the mouse alone, so it may run on a PC in use: both dashboards on a desktop of
their own, where no taskbar is. Under pythonw each answers with its icon window up and no icon on a taskbar. Under python.exe, in a
console with no window, each ends with exit 0 on Ctrl+C as a console sends it to its programs (CTRL_C_EVENT, not a key press).
Not measured, as it needs a taskbar: Ctrl+C while the icon stands on one.
"""
import argparse
import ctypes
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO))

import board  # noqa: E402
import review_page  # noqa: E402
import tray  # noqa: E402
import tray_icon  # noqa: E402
from PIL import ImageGrab  # noqa: E402
from TiaAgentStatus.procs import WinProcesses  # noqa: E402

PYTHONW = Path(sys.executable).with_name('pythonw.exe')
BOX_TITLE = 'Development dashboard'
CONSOLE_CLASSES = ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS')
MENU_CLASS, BOX_CLASS = '#32768', '#32770'
SYNCHRONIZE, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE = 0x00100000, 0x1000, 0x0001
DASHBOARD_RIGHTS = SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE     # what the check does with a dashboard's process
MOUSE_MOVE, LEFT_DOWN, LEFT_UP, RIGHT_DOWN, RIGHT_UP = 0x1, 0x2, 0x4, 0x8, 0x10
OVERFLOW_CLASS = 'TopLevelWindowForOverflowXamlIsland'
MAUVE, GREEN = (0xcb, 0xa6, 0xf7), (0xa6, 0xe3, 0xa1)     # of make_icons.py
ATTACH_CHECK = ("import ctypes,sys;k=ctypes.WinDLL('kernel32');u=ctypes.WinDLL('user32');k.GetConsoleWindow.restype=ctypes.c_void_p;"
                "u.IsWindowVisible.argtypes=[ctypes.c_void_p];k.FreeConsole();a=k.AttachConsole(int(sys.argv[1]));w=k.GetConsoleWindow() if a else None;"
                "sys.exit(2 if w and u.IsWindowVisible(w) else 0)")
SEND_CTRL_C = ("import ctypes,sys,time;k=ctypes.WinDLL('kernel32');k.FreeConsole();a=k.AttachConsole(int(sys.argv[1]));k.SetConsoleCtrlHandler(None,1);"
               "sent=a and k.GenerateConsoleCtrlEvent(0,0);time.sleep(1);sys.exit(0 if sent else 2)")

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32')
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [ENUM, wintypes.LPARAM]
user32.FindWindowW.restype, user32.FindWindowW.argtypes = wintypes.HWND, [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.WindowFromPoint.restype, user32.WindowFromPoint.argtypes = wintypes.HWND, [wintypes.POINT]
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
kernel32.OpenProcess.restype, kernel32.OpenProcess.argtypes = wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT), ('guidItem', ctypes.c_byte * 16)]


shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long
shell32.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wintypes.RECT)]

failed = []


def check(ok, what):
    print(('ok    ' if ok else 'FAIL  ') + what, flush=True)
    if not ok:
        failed.append(what)
    return ok


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def windows():
    """{hwnd: (class, title)} of the visible top-level windows."""
    found = {}

    def one(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            cls, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            user32.GetWindowTextW(hwnd, title, 256)
            found[hwnd] = (cls.value, title.value)
        return True

    user32.EnumWindows(ENUM(one), 0)
    return found


class ConsoleWatch(threading.Thread):
    """Any console window that comes up while it runs, also for a moment. Other programs on this machine may open one too, so it names
    them for you to judge."""

    def __init__(self):
        super().__init__(daemon=True)
        self.before = {h for h, (c, _) in windows().items() if c in CONSOLE_CLASSES}
        self.seen = {}
        self.ending = False

    def run(self):
        while not self.ending:
            for h, (c, t) in windows().items():
                if c in CONSOLE_CLASSES and h not in self.before:
                    self.seen[h] = t
            time.sleep(0.02)


class Dashboard:
    def __init__(self, label, name, port, icon_id, colour=None):
        self.label, self.name, self.port, self.icon_id, self.colour = label, name, port, icon_id, colour
        self.hwnd = self.pid = self.handle = None

    def come_up(self):
        check(answers(self.port), f'{self.label}: answers on {self.port}')
        tip = self.tip()
        for _ in range(100):
            self.hwnd = user32.FindWindowW(tray_icon.CLASS_NAME, tip)
            if self.hwnd:
                break
            time.sleep(0.1)
        if check(bool(self.hwnd), f'{self.label}: icon window, tooltip "{tip}"'):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
            self.pid = pid.value
            self.handle = kernel32.OpenProcess(DASHBOARD_RIGHTS, False, self.pid)
            check(self.place() is not None, f'{self.label}: the taskbar holds the icon')
            program = WinProcesses().tree()[self.pid][1]
            check(program.lower() == 'pythonw.exe', f'{self.label}: runs on {program}, as Windows keeps the icon\'s place per program')

    def place(self):
        """Where the taskbar has the icon: the icon, or the ^ button for one behind it. None when the taskbar does not know it."""
        key = NOTIFYICONIDENTIFIER(cbSize=ctypes.sizeof(NOTIFYICONIDENTIFIER), hWnd=self.hwnd, uID=self.icon_id)
        rect = wintypes.RECT()
        return rect if shell32.Shell_NotifyIconGetRect(ctypes.byref(key), ctypes.byref(rect)) == 0 else None

    def on_screen(self):
        """The middle of the icon on the screen, opening the flyout of the ^ button when it is behind that."""
        rect = self.place()
        spot = find_colour(rect, self.colour)
        if spot:
            return spot
        flyout = wait_for(OVERFLOW_CLASS, 0.3)
        if not flyout:
            click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
            flyout = wait_for(OVERFLOW_CLASS, 3)
            time.sleep(1)
        area = wintypes.RECT()
        user32.GetWindowRect(flyout, ctypes.byref(area))
        return find_colour(area, self.colour)

    def open_menu_by_message(self):
        """What the taskbar sends on a click of the icon."""
        user32.SetCursorPos(*safe_place())
        user32.PostMessageW(self.hwnd, tray_icon.WM_ICON, 0, tray_icon.WM_CONTEXTMENU | (self.icon_id << 16))

    def click_icon(self, down, up):
        """A real click on the icon: a right one opens the menu, a left one the page."""
        spot = self.on_screen()
        if check(bool(spot), f'{self.label}: the icon is to be seen'):
            click(*spot, down, up)

    def tooltip_shot(self, shots, picture):
        """By moving the mouse with real input: the flyout's tooltips do not take SetCursorPos for a pointer that moved."""
        x, y = self.on_screen()
        user32.SetCursorPos(x, y)
        step, end = 1, time.monotonic() + 3
        while time.monotonic() < end:
            user32.mouse_event(MOUSE_MOVE, step, 0, 0, 0)
            step = -step
            time.sleep(0.05 if time.monotonic() + 1.6 < end else 0.3)
        time.sleep(0.8)
        shot(shots / picture, wintypes.RECT(x - 230, y - 90, x + 230, y + 50))

    def tip(self):
        return tray_icon.Icon(self.name, f'http://127.0.0.1:{self.port}/', '', self.icon_id, None, None).tip

    def no_console(self):
        table = WinProcesses().tree()
        family, grew = {self.pid}, True
        while grew:
            more = {p for p, (parent, _) in table.items() if parent in family} - family
            grew = bool(more)
            family |= more
        parent = table.get(self.pid, (None,))[0]
        family |= {parent} if parent in table and table[parent][1].lower().startswith('python') else set()
        shown = [p for p in family if run_hidden(sys.executable, '-c', ATTACH_CHECK, str(p)) == 2]
        check(not shown, f'{self.label}: no visible console in its processes {sorted(family)}')

    def click_menu(self, row, open_it=None, shots=None, picture=None):
        """Opens the real menu and clicks a row: 0 Open, 2 Stop (1 is the line between)."""
        (open_it or self.open_menu_by_message)()
        menu = wait_for(MENU_CLASS)
        if not check(bool(menu), f'{self.label}: its menu opens'):
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(menu, ctypes.byref(rect))
        time.sleep(0.3)
        if shots and picture:
            shot(shots / picture, rect, 40)
        height = rect.bottom - rect.top
        x, y = (rect.left + rect.right) // 2, rect.top + (height // 5 if row == 0 else height * 4 // 5)
        under = user32.WindowFromPoint(wintypes.POINT(x, y))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(under, cls, 256)
        if not check(cls.value == MENU_CLASS, f'{self.label}: the click lands on the menu'):
            user32.keybd_event(0x1B, 0, 0, 0)     # Esc
            user32.keybd_event(0x1B, 0, 2, 0)
            return False
        click(x, y)
        return True

    def stop_by_menu(self, open_it=None, shots=None, picture=None):
        if self.click_menu(2, open_it, shots, picture):
            self.check_ended('Stop', self.handle, lambda: not user32.FindWindowW(tray_icon.CLASS_NAME, self.tip()))
        else:
            end_process(self.handle)

    def check_ended(self, by, handle, icon_window_gone):
        ended = kernel32.WaitForSingleObject(handle, 15000) == 0
        code = wintypes.DWORD(99)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        check(ended and code.value == 0, f'{self.label}: {by} ends it, exit {code.value:#x}')
        check(not review_page.server_running(self.port), f'{self.label}: the port is free')
        check(icon_window_gone(), f'{self.label}: its icon window is gone')


def end_process(handle):
    kernel32.TerminateProcess(handle, 1)
    kernel32.WaitForSingleObject(handle, 5000)     # ended before its folder is removed


def click(x, y, down=LEFT_DOWN, up=LEFT_UP):
    user32.SetCursorPos(x, y)
    time.sleep(0.25)
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)


def find_colour(rect, colour):
    """The middle of the pixels of an icon's colour within rect; None when it has none."""
    image = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom), all_screens=True).convert('RGB')
    pixels = image.load()
    found = [(x, y) for y in range(image.height) for x in range(image.width) if all(abs(pixels[x, y][i] - colour[i]) <= 4 for i in range(3))]
    if not found:
        return None
    xs, ys = [p[0] for p in found], [p[1] for p in found]
    return rect.left + (min(xs) + max(xs)) // 2, rect.top + (min(ys) + max(ys)) // 2


def run_hidden(*argv):
    return subprocess.run(argv, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW).returncode


def safe_place():
    """Where a menu opens: a little up from the bottom right of the main screen, where the taskbar's menus open."""
    return user32.GetSystemMetrics(0) - 300, user32.GetSystemMetrics(1) - 300


def wait_for(cls, seconds=5, title=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for h, (c, t) in windows().items():
            if c == cls and (title is None or t == title):
                return h
        time.sleep(0.05)
    return None


def shot(path, rect, margin=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab((rect.left - margin, rect.top - margin, rect.right + margin, rect.bottom + margin), all_screens=True).save(path)


def opened_it(opened, url):
    for _ in range(100):
        if opened.exists() and url in opened.read_text(encoding='utf-8'):
            return True
        time.sleep(0.1)
    return False


def by_hand(*args):
    """As a double-click or Win+R: through the shell, with no handles handed on, so pythonw has no stderr at all."""
    os.startfile(str(PYTHONW), arguments=' '.join(f'"{a}"' for a in ('-X', 'utf8', *args)))


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR)] + \
               [(n, wintypes.DWORD) for n in ('dwX', 'dwY', 'dwXSize', 'dwYSize', 'dwXCountChars', 'dwYCountChars', 'dwFillAttribute', 'dwFlags')] + \
               [('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD), ('lpReserved2', ctypes.c_void_p)] + \
               [(n, wintypes.HANDLE) for n in ('hStdInput', 'hStdOutput', 'hStdError')]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE), ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


class OwnDesktop:
    """A desktop of its own, where no taskbar is and nobody looks: what a session with no desktop gets from Windows when it asks for an icon."""

    def __init__(self):
        self.name = f'zz-no-taskbar-{os.getpid()}'
        self.handle = user32.CreateDesktopW(self.name, None, None, 0, 0x10000000, None)     # GENERIC_ALL

    def start(self, program, args, flags=0):
        """The process, or None when it did not start."""
        si = STARTUPINFOW(cb=ctypes.sizeof(STARTUPINFOW), lpDesktop=self.name)
        pi = PROCESS_INFORMATION()
        line = ctypes.create_unicode_buffer(' '.join(f'"{a}"' for a in (program, '-X', 'utf8', *args)))
        return pi if kernel32.CreateProcessW(None, line, None, None, False, flags, None, None, ctypes.byref(si), ctypes.byref(pi)) else None

    def icon(self, dashboard):
        """(its icon window is there, a taskbar holds its icon), asked from a thread that stands on this desktop: a window is found only
        from its own. None when the thread could not go there."""
        found = []

        def look():
            if user32.SetThreadDesktop(self.handle):
                dashboard.hwnd = user32.FindWindowW(tray_icon.CLASS_NAME, dashboard.tip())
                found.append((bool(dashboard.hwnd), bool(dashboard.hwnd) and dashboard.place() is not None))

        thread = threading.Thread(target=look)
        thread.start()
        thread.join()
        return found[0] if found else None

    def close(self):
        user32.CloseDesktop(self.handle)


def page_answers(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=15) as r:
            return r.status == 200
    except OSError:
        return False


def came_up(desktop, dashboard, process):
    """What both parts ask first of a dashboard started where no taskbar is."""
    if not check(bool(process), f'{dashboard.label}: started'):
        return False
    check(answers(dashboard.port) and page_answers(dashboard.port), f'{dashboard.label}: it answers')
    check(desktop.icon(dashboard) == (True, False), f'{dashboard.label}: its icon window is there, and no taskbar holds an icon of it')
    return True


def under_pythonw(desktop, dashboard, args):
    """As a person starts it."""
    process = desktop.start(PYTHONW, args)
    try:
        if came_up(desktop, dashboard, process):
            time.sleep(tray_icon.RETRY_MS / 1000 + 1)      # past a retry of the icon
            check(page_answers(dashboard.port), f'{dashboard.label}: it still answers after asking for its icon again')
    finally:
        if process:
            end_process(process.hProcess)


def under_python(desktop, dashboard, args):
    """As the how-tos say to read what stops it: under python.exe, which stays in its console. The console has no window; Ctrl+C comes
    from a helper in that console, as the console sends it on a key press."""
    kernel32.SetConsoleCtrlHandler(None, False)     # a child takes over whether Ctrl+C is ignored: here it is not
    process = desktop.start(sys.executable, args, subprocess.CREATE_NO_WINDOW)
    try:
        if came_up(desktop, dashboard, process):
            sent = run_hidden(sys.executable, '-c', SEND_CTRL_C, str(process.dwProcessId))
            check(sent == 0, f'{dashboard.label}: Ctrl+C sent to its console')
            dashboard.check_ended('Ctrl+C', process.hProcess, lambda: desktop.icon(dashboard) == (False, False))
    finally:
        if process:
            end_process(process.hProcess)


def on_a_desktop_of_their_own(folder):
    """Both dashboards where no taskbar is. Nothing shows on the desktop of the person, and the mouse stays where it is."""
    desktop = OwnDesktop()
    if not check(bool(desktop.handle), 'no taskbar: a desktop of its own could be made'):
        return
    try:
        for part, program in ((under_pythonw, 'pythonw'), (under_python, 'python.exe')):
            dev = Dashboard(f'no taskbar, {program}, development', tray.DEVELOPMENT_NAME, free_port(), tray.DEVELOPMENT_ID)
            tia = Dashboard(f'no taskbar, {program}, TIA', tray.TIA_NAME, free_port(), tray.TIA_ID)
            part(desktop, dev, (TOOLS / 'review_server.py', '--port', dev.port, '--root', folder / 'no-taskbar' / '.scratch'))
            part(desktop, tia, (REPO / 'TiaAgentStatus', 'dashboard', '--port', tia.port, '--root', folder))
    finally:
        desktop.close()


def answers(port):
    for _ in range(150):
        if review_page.server_running(port):
            return True
        time.sleep(0.1)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--shots', type=Path)
    ap.add_argument('--hold', type=float, default=0)
    ap.add_argument('--hidden', action='store_true', help='only the part on a desktop of its own: nothing shows, the mouse is left alone')
    a = ap.parse_args()
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))     # real pixels: the icons are found by them
    with tempfile.TemporaryDirectory(prefix='tray-check-') as name:
        return check_all(a, Path(name))


def check_all(a, folder):
    os.environ.pop(tray.NO_ICON, None)
    watch = ConsoleWatch()
    watch.start()
    if not a.hidden:
        on_your_desktop(a, folder)
    on_a_desktop_of_their_own(folder)
    watch.ending = True
    watch.join(2)
    check(not watch.seen, f'no console window came up in all this: {watch.seen or "none"}')
    print('failed: ' + '; '.join(failed) if failed else 'all ok', flush=True)
    return 1 if failed else 0


def on_your_desktop(a, folder):
    opened = folder / 'opened.txt'
    recorder = folder / 'recorder.py'
    recorder.write_text(f'import sys\nopen(r"{opened}", "a").write(sys.argv[1] + "\\n")\n', encoding='utf-8')
    os.environ.pop('DASHBOARD_BROWSER', None)
    os.environ['BROWSER'] = f'{PYTHONW.as_posix()} {recorder.as_posix()} %s'

    print('herdr, asked with no window:', sorted(board.agents())[:3], flush=True)

    dev = Dashboard('by hand, development', tray.DEVELOPMENT_NAME, free_port(), tray.DEVELOPMENT_ID, MAUVE)
    tia = Dashboard('by hand, TIA', tray.TIA_NAME, free_port(), tray.TIA_ID, GREEN)
    server_args = (str(TOOLS / 'review_server.py'), '--port', str(dev.port), '--root', str(folder / 'by-hand' / '.scratch'))
    by_hand(*server_args)
    by_hand(str(REPO / 'TiaAgentStatus'), 'dashboard', '--port', str(tia.port), '--root', str(folder))
    for d in (dev, tia):
        d.come_up()
        d.no_console()

    # what a page makes them run: git and herdr, with no console of their own
    for port in (dev.port, tia.port):
        urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=30).close()

    # started twice by hand: one icon, and a box says why the second did not start
    by_hand(*server_args)
    box = wait_for(BOX_CLASS, 15, BOX_TITLE)
    if check(bool(box), 'started twice by hand: a box says why'):
        rect = wintypes.RECT()
        user32.GetWindowRect(box, ctypes.byref(rect))
        time.sleep(0.3)
        if a.shots:
            shot(a.shots / 'second-start-box.png', rect)
        user32.PostMessageW(box, tray_icon.WM_CLOSE, 0, 0)
    check(kernel32.WaitForSingleObject(dev.handle, 0) != 0, 'started twice by hand: the first runs on')

    # the same as a session starts it, as when two race for the port: stderr on the null device, so no box
    raced = subprocess.run([str(PYTHONW), '-X', 'utf8', *server_args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    check(raced.returncode == 1 and not wait_for(BOX_CLASS, 2, BOX_TITLE), 'started twice as a session: it ends with exit 1, and no box')

    # started by a session: the command an agent runs, which must end and leave the server running
    session = Dashboard('by a session', tray.DEVELOPMENT_NAME, free_port(), tray.DEVELOPMENT_ID)
    built = run_hidden(sys.executable, '-X', 'utf8', str(TOOLS / 'review_page.py'), '--root', str(folder / 'session' / '.scratch'),
                       '--port', str(session.port), '--title', 'Check', '--ask', 'Is it there?')
    check(built == 0, 'by a session: the review_page.py command built its page and ended')
    session.come_up()
    session.no_console()

    if a.hold:
        print(f'holding {a.hold} s', flush=True)
        time.sleep(a.hold)

    for d, picture in ((dev, 'development-menu.png'), (tia, 'tia-menu.png')):
        if d.click_menu(0, None, a.shots, picture):
            url = f'http://127.0.0.1:{d.port}/'
            check(opened_it(opened, url), f'{d.label}: Open opens {url}')
    time.sleep(16)      # past board.AGENTS_SECONDS and a round of the TIA dashboard: their calls of herdr and git
    urllib.request.urlopen(f'http://127.0.0.1:{dev.port}/', timeout=30).close()

    session.stop_by_menu()
    if a.shots:
        spot = dev.on_screen()
        flyout = wait_for(OVERFLOW_CLASS, 0.3)
        if spot and flyout:
            area = wintypes.RECT()
            user32.GetWindowRect(flyout, ctypes.byref(area))
            shot(a.shots / 'icons.png', area, 8)
        dev.tooltip_shot(a.shots, 'development-tooltip.png')
        tia.tooltip_shot(a.shots, 'tia-tooltip.png')
    for d in (dev, tia):
        opened.unlink(missing_ok=True)
        d.click_icon(LEFT_DOWN, LEFT_UP)
        check(opened_it(opened, f'http://127.0.0.1:{d.port}/'), f'{d.label}: a left click opens the page')
        check(not wait_for(MENU_CLASS, 1), f'{d.label}: a left click opens no menu')
    dev.stop_by_menu(lambda: dev.click_icon(RIGHT_DOWN, RIGHT_UP), a.shots, 'development-menu-right-click.png')
    time.sleep(1)
    tia.stop_by_menu(lambda: tia.click_icon(RIGHT_DOWN, RIGHT_UP), a.shots, 'tia-menu-right-click.png')
    user32.keybd_event(0x1B, 0, 0, 0)     # Esc: the flyout, when it is still up
    user32.keybd_event(0x1B, 0, 2, 0)


if __name__ == '__main__':
    sys.exit(main())
