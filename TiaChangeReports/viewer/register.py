"""Double-click: .s7dcl files open in the viewer, for the current user only (HKEY_CURRENT_USER\\Software\\Classes), and
back. On its own, "Open with" for .xml files lists the viewer, and back. Nothing else registers: a person runs
`--register` and `--unregister`, `--register-xml` and `--unregister-xml`. Standard library only (winreg).

  register(...)   the program id PROGID with its open command (command()), .s7dcl's default set to it (the program there
                  last kept, to put back), PROGID among .s7dcl's OpenWithProgids. Returns the lines to print
  unregister(...) all of that taken back: PROGID removed, .s7dcl's default back to that program, the key gone when empty
  state(...)      what is registered now, read only: the open command, whether .s7dcl's default is PROGID, a choice in
                  "Open with" that names another program
  register_xml(...), unregister_xml(...), xml_state(...)
                  the same for .xml's "Open with", with a program id of its own, XML_PROGID, and of .xml one value:
                  XML_PROGID among its OpenWithProgids. .xml's default and a choice made for it stay. Neither pair
                  touches what the other writes

classes: the key under HKEY_CURRENT_USER both work in, a test's own key in a test. choice: where Windows keeps a
choice the person made in "Open with" (UserChoice), which beats a default and which no program may write: register
says so when one names another program. notify: tells Explorer that associations changed (SHChangeNotify).
"""
import os
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
PROGID = 'TiaChangeReports.BlockViewer'
EXT = '.s7dcl'
CLASSES = r'Software\Classes'
CHOICE = r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.s7dcl\UserChoice'
PREVIOUS = 'TiaChangeReports.Previous'      # .s7dcl's default before register, on PROGID's key
TYPE_NAME = 'SIMATIC SD block'
APP_NAME = 'Block viewer'
XML_PROGID = PROGID + '.Xml'
XML = '.xml'
XML_LIST = XML + r'\OpenWithProgids'        # the one key of .xml register_xml writes in, and there only XML_PROGID
XML_TYPE_NAME = 'SimaticML block export'
MADE = 'TiaChangeReports.XmlKeyMade'        # the topmost key of .xml register_xml made, XML or XML_LIST, on XML_PROGID


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
    if notify:
        _notify()
    lines = ['%s files open in the block viewer: %s' % (EXT, cmd)]
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
    default is PROGID, 'chosen': other_choice()}. The command is this tree's when it equals command()."""
    return {'command': read_value(classes, PROGID + r'\shell\open\command'), 'default': read_value(classes, EXT) == PROGID,
            'chosen': other_choice(choice)}


def unregister(classes=CLASSES, notify=True):
    previous = read_value(classes, PROGID, PREVIOUS)
    delete_tree(classes, PROGID)
    if read_value(classes, EXT) == PROGID:
        if previous:
            write_value(classes, EXT, previous)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes + '\\' + EXT, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, '')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes + '\\' + EXT + r'\OpenWithProgids', 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, PROGID)
    except OSError:
        pass
    for sub in (EXT + r'\OpenWithProgids', EXT):
        if _empty(classes, sub):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, classes + '\\' + sub)
    if notify:
        _notify()
    return ['%s files no longer open in the block viewer%s.' % (EXT, ': back to %s' % previous if previous else '')]



def register_xml(cmd=None, classes=CLASSES, notify=True):
    """XML_PROGID with its open command, and XML_PROGID among .xml's OpenWithProgids. The key made when it is not there,
    and which one kept on XML_PROGID's key, so that unregister_xml takes back only that. Nothing of .s7dcl."""
    cmd = cmd or command()
    made = next((sub for sub in (XML, XML_LIST) if _keys_and_values(classes, sub) is None), None)
    write_value(classes, XML_PROGID, XML_TYPE_NAME)
    write_value(classes, XML_PROGID + r'\shell\open', APP_NAME, 'FriendlyAppName')
    write_value(classes, XML_PROGID + r'\shell\open\command', cmd)
    if made:                                              # kept from the run that made it
        write_value(classes, XML_PROGID, made, MADE)
    write_value(classes, XML_LIST, '', XML_PROGID)
    if notify:
        _notify()
    return ['"Open with" lists the block viewer for .xml files: %s' % cmd,
            'What a double-click on an .xml file opens stays as it was.']


def xml_state(classes=CLASSES):
    """{'command': XML_PROGID's open command or None, 'listed': whether .xml's OpenWithProgids holds XML_PROGID},
    changing nothing."""
    return {'command': read_value(classes, XML_PROGID + r'\shell\open\command'),
            'listed': read_value(classes, XML_LIST, XML_PROGID) is not None}


def unregister_xml(classes=CLASSES, notify=True):
    """XML_PROGID and its value under .xml back, and a key of .xml register_xml made when nothing else is in it. A key
    of .xml that was there before, and the other programs' values, stay. Nothing of .s7dcl."""
    made = read_value(classes, XML_PROGID, MADE)
    delete_tree(classes, XML_PROGID)
    delete_value(classes, XML_LIST, XML_PROGID)
    for sub in {XML: [XML_LIST, XML], XML_LIST: [XML_LIST]}.get(made, []):
        if _empty(classes, sub):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, classes + '\\' + sub)
    if notify:
        _notify()
    return ['"Open with" no longer lists the block viewer for .xml files.']


def delete_value(root, sub, name):
    """The value name of root\\sub deleted; nothing when it is not there."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + '\\' + sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _keys_and_values(root, sub):
    """(subkeys, values) of root\\sub; None when it is not there."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + '\\' + sub) as k:
            return winreg.QueryInfoKey(k)[:2]
    except OSError:
        return None
