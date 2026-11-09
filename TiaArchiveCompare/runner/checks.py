"""Checks of this PC before TIA starts: TIA Portal V20 and its Openness where the bridge will look for them (tiaRoot
of TiaBridge\\settings.json), the group 'Siemens TIA Openness', disk and memory. Each problem is one sentence in plain
words."""
import ctypes
import json
import os
import shutil
import subprocess

TIA_KEY = r'SOFTWARE\Siemens\Automation\_InstalledSW\TIAP20'
NEED_DISK_GB = 2.0          # two copies, two exports, TIA's temporary files
NEED_MEMORY_GB = 4.0        # one background TIA peaks at 2.2 to 3.7 GB
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BRIDGE_SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               'TiaBridge', 'settings.json')
DEFAULT_TIA_ROOT = r'C:\Program Files\Siemens\Automation\Portal V20'     # as Get-BridgeSettings, TiaBridge\Repo.ps1


_BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'),
         (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))


def _as_powershell_decodes(raw):
    """Get-Content of Windows PowerShell 5.1: by the BOM, else ANSI (a UTF-8 file without a BOM too)."""
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding, 'replace')
    return raw.decode('mbcs' if os.name == 'nt' else 'latin-1', 'replace')


def _read_bridge_settings(settings_path=None):
    """The settings by lower-case name, as Get-BridgeSettings (TiaBridge\\Repo.ps1) takes them: names in any case, and
    an empty file or a JSON value that is no object holds none. Its tests hold the two together. One difference stays:
    its parser also takes single quotes and unquoted names, here they are a JSON error."""
    return _settings_in(_as_powershell_decodes(_settings_bytes(settings_path)))


def _settings_bytes(settings_path=None):
    with open(settings_path or BRIDGE_SETTINGS, 'rb') as f:
        return f.read()


def _settings_in(text):
    settings = json.loads(text) if text.strip() else None
    return {k.lower(): v for k, v in settings.items()} if isinstance(settings, dict) else {}


def _text_of(settings, name):
    value = settings.get(name.lower())
    return value if value and isinstance(value, str) else None


def bridge_setting(name, settings_path=None):
    """A text of TiaBridge\\settings.json; None when the file, or that text in it, cannot be had."""
    try:
        return _text_of(_read_bridge_settings(settings_path), name)
    except (OSError, ValueError):
        return None


def bridge_setting_readings(name, settings_path=None):
    """That text as the bridge reads it and as UTF-8, without repeats. A text editor's UTF-8 has no BOM: the bridge
    reads it as ANSI, so a non-ASCII folder is garbled there and what was typed is another folder. For a guard: tiaRoot
    goes by the bridge's reading alone, as that is where the child looks."""
    try:
        raw = _settings_bytes(settings_path)
    except OSError:
        return []
    readings = []
    for decode in (_as_powershell_decodes, lambda data: data.decode('utf-8-sig')):
        try:
            value = _text_of(_settings_in(decode(raw)), name)
        except ValueError:      # a decoding error too
            continue
        if value and value not in readings:
            readings.append(value)
    return readings


def projects_roots(settings_path=None):
    """The folders of the project repos: projectsRoot of TiaBridge\\settings.json as the bridge reads it and as UTF-8
    (they differ for a non-ASCII folder in a file without a BOM; TiaAgentStatus reads UTF-8 only), else the bridge's
    default %USERPROFILE%\\TIA-Projects. The tool never writes into them; the window offers the repos it finds there."""
    return (bridge_setting_readings('projectsRoot', settings_path)
            or [os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects')])


def bridge_settings_problem():
    """Why TiaBridge\\settings.json cannot be read, in plain words; None when it can, or there is none. Its tiaRoot may
    name another folder than the default, so a run does not go on without it."""
    try:
        _read_bridge_settings()
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as ex:
        return ('%s is not valid JSON, so the tool does not know where TIA Portal is (%s). A path in it has each '
                'backslash doubled.' % (BRIDGE_SETTINGS, ex))
    except OSError as ex:
        return ('%s cannot be read, so the tool does not know where TIA Portal is (%s).'
                % (BRIDGE_SETTINGS, ex.strerror or ex))
    return None


def tia_root():
    """The folder of TIA Portal V20, as the bridge goes by it: tiaRoot of its settings, else its default."""
    return bridge_setting('tiaRoot') or DEFAULT_TIA_ROOT


def tia_install():
    """{'version': 'V20.00.00.07', 'path': ..., 'openness': bool}, or None without TIA Portal V20."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TIA_KEY + r'\EditionMain') as k:
            version = winreg.QueryValueEx(k, 'TechnVersion')[0]
            try:
                path = winreg.QueryValueEx(k, 'Path')[0]
            except OSError:
                path = ''
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TIA_KEY + r'\TIA_Opns'))
            openness = True
        except OSError:
            openness = False
        return {'version': version, 'path': path, 'openness': openness}
    except (OSError, ImportError):
        return None


def openness_dll(root):
    """What Import-Openness (TiaBridge\\Tia.ps1) loads."""
    return os.path.join(root, 'PublicAPI', 'V20', 'Siemens.Engineering.dll')


def _same_folder(a, b):
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _version(tia, root, found):
    """Of the cache key and the report. The registry's for the folder it names, and while TIA is not found (no TIA is
    used then, the cache answers); V20 for a folder it does not name: it would describe another install."""
    if found and not (tia and _same_folder(tia['path'], root)):
        return 'V20'
    return tia['version'] if tia else None


def _not_found_text(root, tia):
    text = 'TIA Portal V20 with TIA Openness was not found in %s. ' % root
    if tia and not tia['openness']:
        return text + 'TIA Openness is not installed with TIA Portal V20 (an option of its setup). Ask IT to add it.'
    if tia and tia['path'] and os.path.isfile(openness_dll(tia['path'])):
        return text + 'It is installed in %s: set tiaRoot to that folder in %s.' % (tia['path'], BRIDGE_SETTINGS)
    return text + 'Install it with the TIA Openness option; if it is in another folder, set tiaRoot in %s.' \
        % BRIDGE_SETTINGS


def in_openness_group():
    """True / False; None when it cannot be read."""
    try:
        out = subprocess.run([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'whoami.exe'),
                              '/groups', '/fo', 'csv', '/nh'], capture_output=True, creationflags=NO_WINDOW,
                             timeout=20).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError):
        return None
    return '\\siemens tia openness"' in out.lower()


class _MemoryStatus(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


def free_memory_gb():
    try:
        m = _MemoryStatus()
        m.dwLength = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullAvailPhys / 2.0 ** 30
    except (AttributeError, OSError):
        pass
    return None


def free_disk_gb(path):
    while path and not os.path.exists(path):
        up = os.path.dirname(path)
        if up == path:
            break
        path = up
    try:
        return shutil.disk_usage(path).free / 2.0 ** 30
    except OSError:
        return None


def check_pc(data_root):
    """{'tia': version or None, 'problems': [...] (TIA cannot run), 'warnings': [...], 'facts': [...]}"""
    r = {'tia': None, 'problems': [], 'warnings': [], 'facts': []}
    tia = tia_install()
    root = tia_root()
    found = os.path.isfile(openness_dll(root))
    r['tia'] = _version(tia, root, found)
    unreadable = bridge_settings_problem()
    if unreadable:
        r['problems'].append(unreadable)
    elif found:
        r['facts'].append('TIA Portal %s in %s' % (r['tia'], root))
    else:
        r['problems'].append(_not_found_text(root, tia))
    if (found or tia) and in_openness_group() is False:
        r['problems'].append("Your Windows user may not use TIA Openness. Ask IT to add you to the group "
                             "'Siemens TIA Openness', then sign out and in again.")
    disk = free_disk_gb(data_root)
    if disk is not None:
        r['facts'].append('%.1f GB free on %s' % (disk, os.path.splitdrive(os.path.abspath(data_root))[0] or data_root))
        if disk < NEED_DISK_GB:
            r['problems'].append('The tool needs about %.0f GB free on %s (has %.1f GB).'
                                 % (NEED_DISK_GB, os.path.splitdrive(os.path.abspath(data_root))[0], disk))
    mem = free_memory_gb()
    if mem is not None:
        r['facts'].append('%.1f GB memory free' % mem)
        if mem < NEED_MEMORY_GB:
            r['warnings'].append('Only %.1f GB of memory is free; TIA needs about %.0f GB. Close other programs '
                                 '(another TIA Portal) if the run gets slow.' % (mem, NEED_MEMORY_GB))
    return r
