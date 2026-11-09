"""--snap: one comparison with no one at the window, for tests\\check.py. The window is transparent on the screen; it writes
screenshots, the result and the log."""
import ctypes
import os
import time
from ctypes import wintypes
from datetime import datetime, timedelta

from PIL import Image

from TiaArchiveCompare.window.ask_dialog import AskDialog
from TiaArchiveCompare.window.clipboard import global_memory
from TiaArchiveCompare.window.file_drop import WM_DROPFILES
from TiaArchiveCompare.window.main_window import HEIGHT, WIDTH

PW_RENDERFULLCONTENT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
TICK_MS = 100
_user32 = ctypes.WinDLL('user32')
_gdi32 = ctypes.WinDLL('gdi32')
_dwmapi = ctypes.WinDLL('dwmapi')
_dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
_user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.UINT)
_gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
_gdi32.DeleteDC.argtypes = (wintypes.HDC,)


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


def screenshot(window, path):
    """The window as Windows draws it, without the invisible border around it. A window just made needs a moment before
    Windows has its picture."""
    window.update()
    for _ in range(10):
        time.sleep(0.03)
        window.update()
    hwnd = int(window.wm_frame(), 16)
    rect, frame = wintypes.RECT(), wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen = _user32.GetDC(hwnd)
    memory = _gdi32.CreateCompatibleDC(screen)
    bitmap = _gdi32.CreateCompatibleBitmap(screen, width, height)
    old = _gdi32.SelectObject(memory, bitmap)
    try:
        _user32.PrintWindow(hwnd, memory, PW_RENDERFULLCONTENT)
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        _gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    finally:
        _gdi32.SelectObject(memory, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memory)
        _user32.ReleaseDC(hwnd, screen)
    picture = Image.frombuffer('RGB', (width, height), pixels.raw, 'raw', 'BGRX', 0, 1)
    picture.crop((frame.left - rect.left, frame.top - rect.top, frame.right - rect.left, frame.bottom - rect.top)).save(path)


def post_drop(widget, path):
    """Hands the box the message Explorer sends when a file is dropped on it."""
    header = (20).to_bytes(4, 'little') + bytes(12) + (1).to_bytes(4, 'little')    # DROPFILES: pFiles, pt, fNC, fWide
    handle = global_memory(header + (path + '\0\0').encode('utf-16-le'))
    _user32.PostMessageW(widget.winfo_id(), WM_DROPFILES, handle, 0)


class Snapshot:
    def __init__(self, window, folder, args):
        self.window, self.folder = window, folder
        self.shots = [int(v) for v in args.shots.split(',')] if args.shots else []
        self.cancel_at = args.cancel_at
        self.timeout = timedelta(seconds=args.timeout)
        self.answer, self.umc_global = args.answer, args.umc_global
        self.drop = args.drop
        if args.stop_now_after is not None:
            window.model.stop_now_timeout = timedelta(seconds=args.stop_now_after)
        self.asks = 0
        self.ended = False
        self.cancelled = False
        self.stop_pressed = False
        self.code = 0

    def run(self):
        os.makedirs(self.folder, exist_ok=True)
        w = self.window
        w.headless = True
        w.attributes('-alpha', 0)
        w.maxsize(4000, 4000)       # Tk holds a window to the screen: the shots have the same size on any screen
        w.geometry('%dx%d' % (w.px(WIDTH), w.px(HEIGHT)))
        w.ask_handler = self._ask
        w.on_run_ended = self._run_ended
        w.update()
        if self.drop:
            self._drop_then_run()
        else:
            self._begin()
        w.mainloop()
        return self.code

    def _drop_then_run(self):
        post_drop(self.window.before_box, self.drop)
        self.window.after(300, self._begin)

    def _begin(self):
        w = self.window
        self.t0 = datetime.now()
        w.start_run()
        if not w.running:
            self._finish('end.png', 1)
            return
        w.after(TICK_MS, self._tick)

    def _finish(self, shot, code):
        self.code = code
        self._snap(self.window, shot)
        self._write_result()
        self.window.destroy()

    def _run_ended(self):
        self.ended = True

    def _tick(self):
        w = self.window
        ms = (datetime.now() - self.t0).total_seconds() * 1000
        if self.ended:
            self._finish('end.png', 0)
            return
        if self.cancel_at is not None and not self.cancelled and ms >= self.cancel_at:
            self.cancelled = True
            w.press_cancel()
            self._snap(w, 'cancel.png')
        if self.cancelled and not self.stop_pressed and w.stop_offered:
            self.stop_pressed = True
            self._snap(w, 'stop-offered.png')
            w.press_cancel()
        if self.shots and ms >= self.shots[0]:
            self._snap(w, 'shot-%d.png' % self.shots.pop(0))
        if ms > self.timeout.total_seconds() * 1000:
            self._finish('timeout.png', 2)
            return
        w.after(TICK_MS, self._tick)

    def _ask(self, request):
        dialog = AskDialog(self.window, request)
        dialog.attributes('-alpha', 0)
        skip = self.answer == 'skip'
        user, colon, password = self.answer.partition(':')
        dialog.fill(user if colon else '', '' if skip else password if colon else self.answer, self.umc_global)
        self.asks += 1
        self._snap(dialog, 'ask-%d.png' % self.asks)
        answer = dialog.answer(not skip)
        dialog.destroy()
        return answer

    def _snap(self, window, name):
        screenshot(window, os.path.join(self.folder, name))

    def _write_result(self):
        w, m = self.window, self.window.model
        lines = ['result: %s' % w.result.cget('text'),
                 'title: %s' % w.title(),
                 'before: %s' % (w.before_commit.get() if w.from_commits.get() else w.before_path.get()),
                 'after: %s' % (w.after_commit.get() if w.from_commits.get() else w.after_path.get()),
                 'list heading: %s' % w.not_exported_label.cget('text'),
                 'buttons: report=%s folder=%s copylog=%s compare=%s' % (
                     *(not b.instate(['disabled']) for b in (w.open_report_button, w.open_folder_button, w.copy_log_button)),
                     str(w.compare_button.cget('state')) == 'normal')]
        w.update()
        lines += ['option: %s | fits=%s' % (text, box.winfo_reqwidth() <= box.winfo_width()) for text, box in w.options.items()]
        if m.step_error is not None:
            lines.append('step error: %s' % m.step_error)
        lines += ['step: %s %s' % (s.id, s.state.value) for s in m.steps]
        if m.end is not None:
            lines += ['not exported: %s | %s' % (n.name, n.why) for n in m.end.not_exported]
        self._write('result.txt', '\n'.join(lines) + '\n')
        self._write('log.txt', m.log_text())
        self._write('shown.txt', w.shown_log)

    def _write(self, name, text):
        with open(os.path.join(self.folder, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)
