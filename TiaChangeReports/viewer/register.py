"""Double-click: .s7dcl files open in the viewer, and "Open with" lists it for .xml files, for the current user only
(HKEY_CURRENT_USER\\Software\\Classes), and back. Nothing else registers: a person runs `--register` and `--unregister`.
Standard library only (winreg).

  register(...)   the program id PROGID with its open command (command()), .s7dcl's default set to it (the program there
                  last kept, to put back), PROGID among .s7dcl's OpenWithProgids, and of .xml one value: PROGID among
                  its OpenWithProgids. .xml's default and a choice made for it stay. Returns the lines to print
  unregister(...) all of that taken back: PROGID removed, .s7dcl's default back to that program, the key gone when empty;
                  of .xml only that value, its key and the other programs' values stay
  state(...)      what is registered now, read only: the open command, whether .s7dcl's default is PROGID, a choice in
                  "Open with" that names another program, whether .xml's OpenWithProgids holds PROGID

classes: the key under HKEY_CURRENT_USER both work in, a test's own key in a test. choice: where Windows keeps a
choice the person made in "Open with" (UserChoice), which beats a default and which no program may write: register
says so when one names another program. notify: tells Explorer that associations changed (SHChangeNotify).
"""
import os
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
PROGID = 'TiaChangeReports.BlockViewer'
EXT = '.s7dcl'
XML_LIST = r'.xml\OpenWithProgids'          # the one key of .xml register writes in, and there only the value PROGID
CLASSES = r'Software\Classes'
CHOICE = r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.s7dcl\UserChoice'
PREVIOUS = 'TiaChangeReports.Previous'      # .s7dcl's default before register, on PROGID's key
TYPE_NAME = 'SIMATIC SD block'
APP_NAME = 'Block viewer'


def command(viewer=HERE, python=None):
    """The open command: pythonw.exe of this tree's .venv (no console) on this folder, the file in quotes."""
    python = python or os.path.join(os.path.dirname(os.path.dirname(viewer)), '.venv', 'Scripts', 'pythonw.exe')
    return '"%s" -X utf8 "%s" "%%1"' % (python, viewer)


def read_value(root, sub, name=''):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + '\\' + sub if sub else root) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def write_value(root, sub, value, name=''):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, root + '\\' + sub, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def delete_tree(root, sub):
    """Delete root\\sub and everything under it; nothing when it is not there."""
    path = root + '\\' + sub
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as k:
            names = []
            while True:
                try:
                    names.append(winreg.EnumKey(k, len(names)))
                except OSError:
                    break
    except OSError:
        return
    for n in names:
        delete_tree(path, n)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def _empty(root, sub):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + '\\' + sub) as k:
            n_keys, n_values, _ = winreg.QueryInfoKey(k)
            return n_keys == 0 and n_values == 0
    except OSError:
        return False


def _notify():
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)      # SHCNE_ASSOCCHANGED, SHCNF_IDLIST


def register(cmd=None, classes=CLASSES, choice=CHOICE, notify=True):
    cmd = cmd or command()
    before = read_value(classes, EXT)
    write_value(classes, PROGID, TYPE_NAME)
    write_value(classes, PROGID + r'\shell\open', APP_NAME, 'FriendlyAppName')
    write_value(classes, PROGID + r'\shell\open\command', cmd)
    if before and before != PROGID:                       # the one there last, to put back
        write_value(classes, PROGID, before, PREVIOUS)
    write_value(classes, EXT, PROGID)
    write_value(classes, EXT + r'\OpenWithProgids', '', PROGID)
    write_value(classes, XML_LIST, '', PROGID)
    if notify:
        _notify()
    lines = ['%s files open in the block viewer: %s' % (EXT, cmd),
             '"Open with" lists the block viewer for .xml files. What a double-click on one opens stays as it was.']
    chosen = other_choice(choice)
    if chosen:
        lines.append(choice_note(chosen))
    return lines


def other_choice(choice=CHOICE):
    """The program a choice in "Open with" names, when it is not the viewer; None without one."""
    chosen = read_value(choice, '', 'ProgId')
    return chosen if chosen and chosen != PROGID else None


def choice_note(chosen):
    return ('Windows opens %s files with %s, as chosen in "Open with": right-click one, Open with, Choose another '
            'app, %s, Always.' % (EXT, chosen, APP_NAME))


def state(classes=CLASSES, choice=CHOICE):
    """What is registered, changing nothing: {'command': PROGID's open command or None, 'default': whether .s7dcl's
    default is PROGID, 'chosen': other_choice(), 'xml': whether .xml's OpenWithProgids holds PROGID}. The command is this
    tree's when it equals command(); "Open with" on an .xml file runs that command too."""
    return {'command': read_value(classes, PROGID + r'\shell\open\command'), 'default': read_value(classes, EXT) == PROGID,
            'chosen': other_choice(choice), 'xml': read_value(classes, XML_LIST, PROGID) is not None}


def unregister(classes=CLASSES, notify=True):
    previous = read_value(classes, PROGID, PREVIOUS)
    delete_tree(classes, PROGID)
    if read_value(classes, EXT) == PROGID:
        if previous:
            write_value(classes, EXT, previous)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes + '\\' + EXT, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, '')
    for sub in (EXT + r'\OpenWithProgids', XML_LIST):
        _delete_value(classes, sub, PROGID)
    for sub in (EXT + r'\OpenWithProgids', EXT):
        if _empty(classes, sub):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, classes + '\\' + sub)
    if notify:
        _notify()
    return ['%s files no longer open in the block viewer%s.' % (EXT, ': back to %s' % previous if previous else ''),
            '"Open with" no longer lists the block viewer for .xml files.']


def _delete_value(root, sub, name):
    """The value name of root\\sub deleted; nothing when it is not there."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + '\\' + sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass

