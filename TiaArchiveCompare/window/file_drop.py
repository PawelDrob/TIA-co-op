"""Dropping a file from Explorer on an entry box. Tk 8.6 has no file drop of its own, so this takes the Windows message
(WM_DROPFILES) on the box's window. No dependency."""
import ctypes
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_shell32 = ctypes.WinDLL('shell32', use_last_error=True)
_user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
_user32.SetWindowLongPtrW.restype = ctypes.c_void_p
_user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallWindowProcW.restype = _LRESULT
_shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
_shell32.DragAcceptFiles.restype = None
_shell32.DragQueryFileW.argtypes = (ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT)
_shell32.DragQueryFileW.restype = wintypes.UINT
_shell32.DragFinish.argtypes = (ctypes.c_void_p,)
_shell32.DragFinish.restype = None


def _first_file(drop):
    try:
        if _shell32.DragQueryFileW(drop, 0xFFFFFFFF, None, 0) == 0:
            return None
        size = _shell32.DragQueryFileW(drop, 0, None, 0) + 1
        buffer = ctypes.create_unicode_buffer(size)
        _shell32.DragQueryFileW(drop, 0, buffer, size)
        return buffer.value
    finally:
        _shell32.DragFinish(drop)


def accept_drops(widget, on_file):
    """on_file(path) gets the first file dropped on `widget`. It runs inside the Windows message and must not touch Tk:
    a Tcl call there leaves tkinter's thread state empty, and the next Tk callback ends the process (Fatal Python error:
    PyEval_RestoreThread). Hand the path on, and take it up on the window's own time."""
    hwnd = widget.winfo_id()

    def window_proc(h, message, wparam, lparam):
        if message == WM_DROPFILES:
            path = _first_file(wparam)
            if path:
                on_file(path)
            return 0
        return _user32.CallWindowProcW(previous, h, message, wparam, lparam)

    callback = _WNDPROC(window_proc)
    previous = _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
    widget.drop_callback = callback     # Windows holds only its address; this keeps it alive with the widget
    _shell32.DragAcceptFiles(hwnd, True)
