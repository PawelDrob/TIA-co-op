"""The block viewer's registration, through the viewer's own register.py: for a double-click on an .s7dcl, which the
commands --register and --unregister run, and on its own for "Open with" on an .xml, which --register-xml and
--unregister-xml run. No tkinter. classes and choice: the keys under HKEY_CURRENT_USER it works in, a test's own in a
test; the real ones tell Explorer of a change."""
from TiaChangeReports.viewer import register as viewer_register


def state(classes=viewer_register.CLASSES, choice=viewer_register.CHOICE):
    """register.state(), with 'this': the command that would open a file in this clone, 'key' and 'progid': where it
    registers and as what, and 'note': what a choice in "Open with" for another program does; 'xml': the same of the
    .xml entry, register.xml_state() with 'this', 'key' and 'progid'. {'error': ...} when the registry cannot be read."""
    try:
        found = viewer_register.state(classes, choice)
        xml = viewer_register.xml_state(classes)
    except OSError as e:
        return {'error': f'The registry could not be read: {e}'}
    found['this'] = xml['this'] = viewer_register.command()
    found['key'] = xml['key'] = 'HKEY_CURRENT_USER\\' + classes
    found['progid'] = viewer_register.PROGID
    xml['progid'] = viewer_register.XML_PROGID
    found['note'] = viewer_register.choice_note(found['chosen']) if found['chosen'] else ''
    found['xml'] = xml
    return found


def register(classes=viewer_register.CLASSES, choice=viewer_register.CHOICE):
    """(failed, text): the lines --register prints, or the error."""
    try:
        return False, '\n'.join(viewer_register.register(None, classes, choice, notify=classes == viewer_register.CLASSES))
    except OSError as e:
        return True, f'Registering failed: {e}'


def unregister(classes=viewer_register.CLASSES):
    try:
        return False, '\n'.join(viewer_register.unregister(classes, notify=classes == viewer_register.CLASSES))
    except OSError as e:
        return True, f'Unregistering failed: {e}'


def register_xml(classes=viewer_register.CLASSES):
    """(failed, text): the lines --register-xml prints, or the error."""
    try:
        return False, '\n'.join(viewer_register.register_xml(None, classes, notify=classes == viewer_register.CLASSES))
    except OSError as e:
        return True, f'Registering failed: {e}'


def unregister_xml(classes=viewer_register.CLASSES):
    try:
        return False, '\n'.join(viewer_register.unregister_xml(classes, notify=classes == viewer_register.CLASSES))
    except OSError as e:
        return True, f'Unregistering failed: {e}'
