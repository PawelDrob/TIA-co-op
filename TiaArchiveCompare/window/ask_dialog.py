"""The runner's "ask" event: the safety password, or the project user and password of a UMC-protected project.
The password box is masked; the answer goes to the runner's stdin only."""
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk
from typing import Optional

from TiaArchiveCompare.window.edit_menu import add_edit_menu

HINT_COLOR = '#b8860b'


@dataclass
class AskAnswer:
    skip: bool = False
    user: Optional[str] = None
    password: Optional[str] = None
    umc_global: bool = False        # the user is a UMC server user, not a project user


class AskDialog(tk.Toplevel):
    def __init__(self, parent, ask):
        super().__init__(parent)
        self.wants_user = ask.kind == 'umc_login'
        self.result = AskAnswer(skip=True)
        self.user = tk.StringVar(self)
        self.password = tk.StringVar(self)
        self.umc_global = tk.BooleanVar(self, False)
        self.title('Project login' if self.wants_user else 'Safety password')
        self.transient(parent)
        self.resizable(False, False)
        self.configure(padx=12, pady=12, background=parent.cget('background'))
        self.columnconfigure(1, weight=1)

        project = '"%s"' % ask.project if ask.project else 'the project'
        if self.wants_user:
            info = ('The project %s is protected (UMC). Enter a project user, or a UMC server user, and its password to '
                    'open the copy. Without them the project cannot be compared.' % project)
        else:
            info = ('The project %s has a safety program. Enter its safety password to compile the copy. Skip: the '
                    'F-blocks are then listed under Not in the report.' % project)
        width = parent.px(416)
        ttk.Label(self, text=info, wraplength=width).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        row = 1
        # the fake exporter's sample password, so a tester does not try a real one
        if ask.hint:
            bold = tkfont.nametofont('TkDefaultFont').copy()
            bold.configure(weight='bold')
            ttk.Label(self, text=ask.hint, foreground=HINT_COLOR, font=bold, wraplength=width).grid(
                row=row, column=0, columnspan=2, sticky='w', pady=(0, 8))
            self.hint_font = bold       # tkinter drops a font nothing in Python holds
            row += 1
        self.first = None
        if self.wants_user:
            ttk.Label(self, text='User').grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
            self.first = ttk.Entry(self, textvariable=self.user)
            self.first.grid(row=row, column=1, sticky='ew', pady=4)
            add_edit_menu(self.first)
            row += 1
        ttk.Label(self, text='Password').grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
        box = ttk.Entry(self, textvariable=self.password, show='•')
        box.grid(row=row, column=1, sticky='ew', pady=4)
        add_edit_menu(box, cut=False, copy=False)    # as a Windows password box
        self.first = self.first or box
        row += 1
        if self.wants_user:
            ttk.Checkbutton(self, text='UMC server user (not a user of the project)', variable=self.umc_global).grid(
                row=row, column=1, sticky='w', pady=4)
            row += 1
        buttons = ttk.Frame(self)
        buttons.grid(row=row, column=0, columnspan=2, sticky='e', pady=(12, 0))
        ttk.Button(buttons, text='OK', default='active', command=lambda: self._close(True)).pack(side='left', padx=(0, 8))
        self.skip_button = ttk.Button(buttons, text='Skip', command=lambda: self._close(False))
        self.skip_button.pack(side='left')
        self.bind('<Return>', lambda e: self._close(e.widget is not self.skip_button))    # Enter: the button in focus, else OK
        self.bind('<Escape>', lambda e: self._close(False))
        self.protocol('WM_DELETE_WINDOW', lambda: self._close(False))
        self.update_idletasks()
        self.geometry('+%d+%d' % (parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2,
                                  parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 2))

    def fill(self, user, password, umc_global):
        """For the headless check: fill the boxes as a user would."""
        self.user.set(user or '')
        self.password.set(password or '')
        self.umc_global.set(umc_global)

    def answer(self, ok):
        if not ok:
            return AskAnswer(skip=True)
        return AskAnswer(user=self.user.get() if self.wants_user else None, password=self.password.get(),
                         umc_global=self.wants_user and self.umc_global.get())

    def _close(self, ok):
        self.result = self.answer(ok)
        self.destroy()


def ask(parent, request):
    """Modal: the main window takes no input until it is answered, while the runner's lines keep coming in. A run takes
    minutes, so the window may be minimized: it comes back, as a window it owns stays hidden with it."""
    if parent.state() == 'iconic':
        parent.deiconify()
        parent.update()
    dialog = AskDialog(parent, request)
    parent.attributes('-disabled', True)
    try:
        dialog.lift()
        dialog.first.focus_force()
        parent.wait_window(dialog)
        parent.attributes('-disabled', False)
        parent.focus_force()
    except tk.TclError:     # the window closed behind the question: the run ended and it was to close then
        pass
    return dialog.result
