"""The icon itself: a hidden window with its message loop, and Shell_NotifyIconW. All of the icon that touches a desktop or needs Windows,
imported only when an icon is made. A left click or Enter opens the page, a right click the menu.
"""
import ctypes
import threading
import time
from ctypes import wintypes

from tray import say_on_stderr

WM_DESTROY, WM_CLOSE, WM_NULL, WM_TIMER, WM_USER, WM_CONTEXTMENU = 0x0002, 0x0010, 0x0000, 0x0113, 0x0400, 0x007B
WM_ICON = WM_USER + 1
NIN_SELECT, NIN_KEYSELECT = WM_USER, WM_USER + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x80
NOTIFYICON_VERSION_4 = 4
IMAGE_ICON, LR_LOADFROMFILE, SM_CXSMICON, SM_CYSMICON = 1, 0x10, 49, 50
MF_STRING, MF_SEPARATOR, TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0, 0x800, 0x2, 0x100, 0x80
PER_MONITOR_AWARE_V2 = -4
OPEN, STOP = 1, 2
RETRY_MS = 5000     # the taskbar may not be up yet, as at logon, or too busy to answer
TIP_CHARS = 127
DOUBLE_CLICK_SECONDS = 1    # a double click, out of habit, is two clicks to the taskbar: one page
CLASS_NAME = 'TiaCoopDashboardIcon'
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT), ('uFlags', wintypes.UINT),
                ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256),
                ('uVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64), ('dwInfoFlags', wintypes.DWORD),
                ('guidItem', ctypes.c_byte * 16), ('hBalloonIcon', wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]


def win32():
    """user32, shell32 and kernel32 of their own, with the types 64-bit handles need."""
    u = ctypes.WinDLL('user32', use_last_error=True)
    s = ctypes.WinDLL('shell32', use_last_error=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetModuleHandleW.restype, k.GetModuleHandleW.argtypes = wintypes.HMODULE, [wintypes.LPCWSTR]
    u.DefWindowProcW.restype, u.DefWindowProcW.argtypes = LRESULT, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterClassW.restype, u.RegisterClassW.argtypes = wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD] + [ctypes.c_int] * 4 + \
        [wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.restype, u.DispatchMessageW.argtypes = LRESULT, [ctypes.POINTER(wintypes.MSG)]
    u.RegisterWindowMessageW.restype, u.RegisterWindowMessageW.argtypes = wintypes.UINT, [wintypes.LPCWSTR]
    u.SetTimer.restype, u.SetTimer.argtypes = ctypes.c_size_t, [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.DestroyIcon.argtypes = [wintypes.HICON]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    u.SetThreadDpiAwarenessContext.restype, u.SetThreadDpiAwarenessContext.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
    s.Shell_NotifyIconW.restype, s.Shell_NotifyIconW.argtypes = wintypes.BOOL, [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    return u, s, k


class Icon:
    """One icon, on a thread of its own that holds a hidden window and its message loop."""

    def __init__(self, name, url, icon_file, icon_id, open_page, stop):
        self.name, self.url, self.icon_file, self.icon_id = name, url, str(icon_file), icon_id
        self.open_page, self.stop = open_page, stop
        self.hwnd = None
        self.shown = False
        self.closing = False
        self.clicked_at = None
        self.ready = threading.Event()
        self.lock = threading.Lock()

    @property
    def tip(self):
        return f'{self.name} - {self.url}'[:TIP_CHARS]

    def start(self):
        threading.Thread(target=self.run, name='tray icon', daemon=True).start()
        self.ready.wait(5)

    def close(self):
        """Any thread may call this, and more than once. The icon goes first: the window goes with the message loop."""
        self.closing = True
        self.remove()
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def run(self):
        try:
            self.loop()
        except Exception as e:      # a session with no desktop: the server goes on without an icon
            say_on_stderr(f'{self.name}: no icon: {e}')
        finally:
            self.ready.set()

    def loop(self):
        self.user32, self.shell32, kernel32 = win32()
        u = self.user32
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2))     # a sharp icon and menu at any display scale
        instance = kernel32.GetModuleHandleW(None)
        self.taskbar_created = u.RegisterWindowMessageW('TaskbarCreated')         # Explorer restarted: its icons are gone
        self.proc = WNDPROC(self.message)     # held here: Windows calls it for as long as the window lives
        cls = WNDCLASSW(lpfnWndProc=self.proc, hInstance=instance, lpszClassName=CLASS_NAME)
        if not u.RegisterClassW(ctypes.byref(cls)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = u.CreateWindowExW(0, CLASS_NAME, self.tip, 0, 0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hicon = u.LoadImageW(None, self.icon_file, IMAGE_ICON, u.GetSystemMetrics(SM_CXSMICON), u.GetSystemMetrics(SM_CYSMICON),
                                  LR_LOADFROMFILE)
        if not self.hicon:
            raise ctypes.WinError(ctypes.get_last_error())
        self.add_or_retry()
        self.ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        u.DestroyIcon(self.hicon)

    def named(self):
        """What tells the taskbar which icon a call is about."""
        return NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=self.icon_id)

    def described(self):
        d = self.named()
        d.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        d.uCallbackMessage, d.hIcon, d.szTip = WM_ICON, self.hicon, self.tip
        return d

    def add(self):
        """True when the icon stands. A taskbar too busy to answer may have added it all the same, so a refused add asks once more."""
        d = self.described()
        with self.lock:
            if not (self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(d)) or self.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d))):
                return False
            d.uVersion = NOTIFYICON_VERSION_4     # the callback then says what happened, also from the keyboard
            self.shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(d))
            self.shown = True
        return True

    def add_or_retry(self):
        if not self.add():
            self.user32.SetTimer(self.hwnd, 1, RETRY_MS, None)

    def remove(self):
        with self.lock:
            if self.shown:
                self.shown = False
                self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.named()))

    def message(self, hwnd, msg, wparam, lparam):
        try:
            event = lparam & 0xFFFF     # of a message from the icon
            if msg == WM_ICON and event in (NIN_SELECT, NIN_KEYSELECT):
                self.clicked()
            elif msg == WM_ICON and event == WM_CONTEXTMENU:
                self.menu()
            elif msg == self.taskbar_created:
                self.add_or_retry()
            elif msg == WM_TIMER and self.add():
                self.user32.KillTimer(hwnd, 1)
            elif msg == WM_CLOSE:
                if not self.closing:    # from outside (taskkill without /F): with the window gone there is no icon left to stop it by
                    self.end_server()
                self.user32.DestroyWindow(hwnd)
            elif msg == WM_DESTROY:
                self.user32.PostQuitMessage(0)
            else:
                return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception as e:      # an exception cannot pass through Windows
            say_on_stderr(f'{self.name}: {e}')
        return 0

    def clicked(self):
        now = time.monotonic()
        if self.clicked_at is None or now - self.clicked_at >= DOUBLE_CLICK_SECONDS:
            self.clicked_at = now
            self.open_page(self.url)

    def end_server(self):
        self.remove()       # gone at once; the server takes a moment to end
        self.stop()

    def menu(self):
        u = self.user32
        items = u.CreatePopupMenu()
        u.AppendMenuW(items, MF_STRING, OPEN, f'Open {self.name}')
        u.AppendMenuW(items, MF_SEPARATOR, 0, None)
        u.AppendMenuW(items, MF_STRING, STOP, f'Stop {self.name}')
        u.SetMenuDefaultItem(items, OPEN, 0)
        at = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(at))
        u.SetForegroundWindow(self.hwnd)      # without it the menu stays up when the person clicks elsewhere
        chosen = u.TrackPopupMenu(items, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, at.x, at.y, 0, self.hwnd, None)
        u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(items)
        if chosen == OPEN:
            self.open_page(self.url)
        elif chosen == STOP:
            self.end_server()
