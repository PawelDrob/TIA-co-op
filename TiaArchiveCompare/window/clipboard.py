"""Text to the Windows clipboard. Tk's own clipboard hands the text over only when asked, while its window lives: text
copied and then pasted after the window closed would be gone."""
import ctypes
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
_user32 = ctypes.WinDLL('user32')
_kernel32 = ctypes.WinDLL('kernel32')
_user32.OpenClipboard.argtypes = (wintypes.HWND,)
_user32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)
_user32.SetClipboardData.restype = ctypes.c_void_p
_kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
_kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)


def global_memory(data):
    """The bytes in memory another party takes over (the clipboard, a drop); None when there is no memory for them."""
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    block = _kernel32.GlobalLock(handle) if handle else None
    if not block:
        return None
    ctypes.memmove(block, data, len(data))
    _kernel32.GlobalUnlock(handle)
    return handle


def copy_text(text):
    """False when another program holds the clipboard or there is no memory for the text."""
    handle = global_memory((text + '\0').encode('utf-16-le'))
    if not handle:
        return False
    if not _user32.OpenClipboard(None):
        _kernel32.GlobalFree(handle)
        return False
    try:
        _user32.EmptyClipboard()
        if _user32.SetClipboardData(CF_UNICODETEXT, handle):    # the clipboard owns the memory from here
            return True
        _kernel32.GlobalFree(handle)
        return False
    finally:
        _user32.CloseClipboard()
