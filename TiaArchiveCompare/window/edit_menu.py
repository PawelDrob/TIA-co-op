"""The right-click menu a Windows text box has, which a Tk box lacks. Copy and Cut, by menu or key, hand the text to
Windows at once, so it can still be pasted after the window closed (clipboard.py)."""
import tkinter as tk

from TiaArchiveCompare.window.clipboard import copy_text


def _selected(widget):
    """The text selected in the box as Windows wants it on the clipboard; None when nothing is selected."""
    try:
        if isinstance(widget, tk.Text):
            return widget.get('sel.first', 'sel.last').replace('\n', '\r\n')
        return widget.get()[widget.index('sel.first'):widget.index('sel.last')]
    except tk.TclError:
        return None


def _copy(event):
    """'break' keeps Tk's own Copy from taking the clipboard back; with nothing selected, or the clipboard held, it runs."""
    text = _selected(event.widget)
    return 'break' if text and copy_text(text) else None


def _cut(event):
    if _copy(event) is None:
        return None
    event.widget.delete('sel.first', 'sel.last')
    return 'break'


def _refuse(event):
    """As a Windows password box: Ctrl+C keeps the clipboard, Ctrl+X the password."""
    return 'break'


def add_edit_menu(widget, cut=True, copy=True, paste=True):
    menu = tk.Menu(widget, tearoff=False)
    for label, event, wanted in (('Cut', '<<Cut>>', cut), ('Copy', '<<Copy>>', copy), ('Paste', '<<Paste>>', paste),
                                 ('Select All', '<<SelectAll>>', True)):
        if wanted:
            menu.add_command(label=label, command=lambda e=event: widget.event_generate(e))
    widget.bind('<<Cut>>', _cut if cut else _refuse)
    widget.bind('<<Copy>>', _copy if copy else _refuse)

    def show(event):
        if hasattr(widget, 'instate') and widget.instate(['disabled']):     # locked during a run
            return
        widget.focus_set()
        menu.tk_popup(event.x_root, event.y_root)

    widget.bind('<Button-3>', show)
    return menu
