"""A registry key of a test's own, for every test that runs the viewer's register.py (register, unregister,
register_xml, unregister_xml): made under HKEY_CURRENT_USER\\Software, deleted after the test, and every key opened to
write, made or deleted outside it fails the test before it is written. So a change that writes elsewhere, .xml's
UserChoice under Explorer's key for one, never reaches the real registry from a test."""
import uuid
import winreg
from unittest import mock

from TiaChangeReports.viewer import register

WRITES = ('CreateKey', 'CreateKeyEx', 'DeleteKey', 'DeleteKeyEx')     # always a write
OPENS = ('OpenKey', 'OpenKeyEx')                                      # a write when the access asks for one


def own_key(case, prefix):
    """Software\\<prefix>-<uuid>: the test's key, guarded from now until it ends and deleted then."""
    root = r'Software\%s-%s' % (prefix, uuid.uuid4().hex)
    case.addCleanup(register.delete_tree, 'Software', root.split('\\', 1)[1])

    def mine(path):
        if not path.lower().startswith(root.lower() + '\\'):
            case.fail('written outside the test key: ' + path)

    def writing(real):
        def call(key, path, *rest, **named):
            mine(path)
            return real(key, path, *rest, **named)
        return call

    def opening(real):
        def call(key, path, reserved=0, access=winreg.KEY_READ):
            if access & (winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY):
                mine(path)
            return real(key, path, reserved, access)
        return call
    for name in WRITES + OPENS:
        guard = opening if name in OPENS else writing
        case.enterContext(mock.patch.object(winreg, name, guard(getattr(winreg, name))))
    return root
