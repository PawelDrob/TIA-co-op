"""The block viewer's registration for a double-click on an .s7dcl and for "Open with" on an .xml, through the
viewer's own register.py, which the commands --register and --unregister run. No tkinter. classes and choice: the keys
under HKEY_CURRENT_USER it works in, a test's own in a test; the real ones tell Explorer of a change."""
from TiaChangeReports.viewer import register as viewer_register


def state(classes=viewer_register.CLASSES, choice=viewer_register.CHOICE):
    """register.state(), with 'this': the command that would open a file in this clone, 'key' and 'progid': where it
    registers and as what, and 'note': what a choice in "Open with" for another program does. {'error': ...} when the
    registry cannot be read."""
    try:
        found = viewer_register.state(classes, choice)
    except OSError as e:
        return {'error': f'The registry could not be read: {e}'}
    found['this'] = viewer_register.command()
    found['key'] = 'HKEY_CURRENT_USER\\' + classes
    found['progid'] = viewer_register.PROGID
    found['note'] = viewer_register.choice_note(found['chosen']) if found['chosen'] else ''
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
