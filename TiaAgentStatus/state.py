"""The state files of the TiaBridge processes (<projectsRoot>\\_bridge\\sessions\\<pid>.json, written by
TiaBridge\\State.ps1): finding the folder, reading the live ones, the Claude process of a reader."""
import datetime
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_NAMES = ('claude.exe', 'claude', 'node.exe', 'node')
# a bridge pid whose process started this much later than the file's `started` is a reused pid
REUSE_SLACK = datetime.timedelta(seconds=5)


BRIDGE_SETTINGS = os.path.join(os.path.dirname(HERE), 'TiaBridge', 'settings.json')
DEPTH_LIMIT = 102           # of ConvertFrom-Json, as TiaArchiveCompare\runner\powershell_json.py has it
TOO_DEEP = f'nesting over {DEPTH_LIMIT} levels'


BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'),
        (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))


def as_windows_powershell_reads(raw):
    """Get-Content of Windows PowerShell 5.1, which the bridge reads its settings with: by the BOM, else ANSI. Its
    twins: tools\\setup\\setup.py and TiaArchiveCompare\\runner\\checks.py."""
    for bom, encoding in BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding, 'replace')
    return raw.decode('mbcs' if os.name == 'nt' else 'latin-1', 'replace')


class SettingsUnreadable(ValueError):
    """TiaBridge\\settings.json is there and this tool cannot read it, or cannot use the value it asked for; its text
    names the file and says why. The bridge may still read it: it takes more than JSON
    (TiaArchiveCompare\\runner\\powershell_json.py)."""


def folded(name):
    """A name as the bridge compares the names of its settings, without case (StringComparison.OrdinalIgnoreCase): each
    character's own upper case, where that is one character and not an ASCII one for a character outside ASCII. Its
    twins: tools\\setup\\setup.py and TiaArchiveCompare\\runner\\powershell_json.py."""
    def upper(c):
        u = c.upper()
        return u if len(u) == 1 and (u >= '\x80' or c < '\x80') else c
    return ''.join(upper(c) for c in name)


def spelled(settings, name):
    """The name as the settings spell it, whatever its case, else as given."""
    return next((n for n in settings if folded(n) == folded(name)), name)


def refused_in(value, depth=1):
    """Why the bridge refuses a parsed JSON value, '' when it takes it: nesting over DEPTH_LIMIT levels, an empty name,
    or two names that differ in case only, in the value or anywhere inside it. Its twin: tools\\setup\\setup.py."""
    if depth > DEPTH_LIMIT:
        return TOO_DEEP
    if isinstance(value, list):
        return next(filter(None, (refused_in(item, depth + 1) for item in value)), '')
    if not isinstance(value, dict):
        return ''
    seen = {}
    for name in value:
        first = seen.setdefault(folded(name), name)
        if first != name:
            return f'two names that differ in case only, {first} and {name}'
        if name == '':
            return 'an empty name'
    return next(filter(None, (refused_in(member, depth + 1) for member in value.values())), '')


def blank(text):
    """A text the bridge takes for an empty file. The four separators U+001C to U+001F are white space to Python and
    not to .NET, which refuses a file of them. Its twin: tools\\setup\\setup.py."""
    return not text.strip() and not any('\x1c' <= c <= '\x1f' for c in text)


class TooLarge(ValueError):
    """A number of the settings that overflows a double, which the bridge refuses the file for."""


def number(token):
    """A JSON number as json.loads makes it, TooLarge where it makes infinity of it. Its twin: tools\\setup\\setup.py."""
    if math.isinf(float(token)):
        raise TooLarge(f'the number {token}, too large for it')
    return int(token) if token.lstrip('-').isdigit() else float(token)


def bridge_settings(settings_path=BRIDGE_SETTINGS):
    """TiaBridge\\settings.json beside this folder, decoded as the bridge decodes it. {} without a file, and for an empty
    file or a value that is no object, where the bridge runs on its defaults. Strict JSON only. SettingsUnreadable for
    any other text, and for what the bridge refuses in strict JSON: a number too large for a double (number), deep
    nesting and names (refused_in). A name has one value then, whatever its case (spelled)."""
    try:
        with open(settings_path, 'rb') as f:
            text = as_windows_powershell_reads(f.read())
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise SettingsUnreadable(f'{settings_path} cannot be read ({e})') from e
    if blank(text):
        return {}
    try:
        settings = json.loads(text, parse_float=number, parse_int=number)
        refused = refused_in(settings)
    except TooLarge as e:
        refused = str(e)
    except RecursionError:      # deeper than Python parses
        refused = TOO_DEEP
    except ValueError as e:
        raise SettingsUnreadable(f'{settings_path} is not strict JSON ({e})') from e
    if refused:
        raise SettingsUnreadable(f'{settings_path} holds {refused}, which the bridge refuses')
    return settings if isinstance(settings, dict) else {}


def projects_root(settings_path=BRIDGE_SETTINGS):
    """projectsRoot of TiaBridge\\settings.json beside this folder, else the bridge's default. SettingsUnreadable for a
    file that cannot be read, and for a value that is no text or an empty one, which the bridge takes over its default:
    the bridge's folder is unknown then."""
    settings = bridge_settings(settings_path)
    name = spelled(settings, 'projectsRoot')
    if name not in settings:
        return os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects')
    root = settings[name]
    if not root or not isinstance(root, str):
        raise SettingsUnreadable(f'{settings_path} holds {json.dumps(root)} as projectsRoot, which names no folder')
    return root


def sessions_dir(root=None):
    return os.path.join(root or projects_root(), '_bridge', 'sessions')


def parse_time(text):
    """An ISO time with offset as an aware datetime, None when missing or malformed."""
    try:
        t = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.astimezone()


def read_states(directory):
    """Every state file of the folder that reads as JSON: [(path, dict)]. A file being replaced is skipped."""
    out = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return out
    for name in names:
        if not name.endswith('.json') or not name[:-5].isdigit():
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding='utf-8-sig') as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(s, dict) and s.get('pid') == int(name[:-5]):
            p = s.get('lastPrompt')
            if isinstance(p, dict) and not any(p.get(k) for k in ('kind', 'caption', 'text')):
                s['lastPrompt'] = None    # bridges before 2026-10-31 wrote an empty prompt after a call without one
            out.append((path, s))
    return out


def is_live(state, procs):
    """The bridge of the file still runs: its pid is alive and did not start after the file's `started`."""
    info = procs.info(state.get('pid'))
    if not info:
        return False
    started = parse_time(state.get('started'))
    return started is None or info['created'] <= started + REUSE_SLACK


def same_path(a, b):
    """Two paths of one file or folder, as Windows compares them; False for anything not a path."""
    return isinstance(a, str) and isinstance(b, str) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def live_states(directory, procs):
    return [s for _, s in read_states(directory) if is_live(s, procs)]


def claude_pid(procs, start_pid, env=None):
    """The Claude Code process of a reader: CLAUDE_PID when given, else the nearest ancestor of start_pid named
    claude (or node), else None."""
    env = os.environ if env is None else env
    if str(env.get('CLAUDE_PID', '')).isdigit():
        return int(env['CLAUDE_PID'])
    tree = procs.tree()
    pid, seen = start_pid, set()
    while pid in tree and pid not in seen:
        seen.add(pid)
        parent = tree[pid][0]
        if parent in tree and tree[parent][1].lower() in CLAUDE_NAMES:
            return parent
        pid = parent
    return None


def bridge_of(states, claude):
    """The newest live bridge started by the Claude process `claude`, or None."""
    mine = [s for s in states if (s.get('claude') or {}).get('pid') == claude]
    if not mine:
        return None
    oldest = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    return max(mine, key=lambda s: parse_time(s.get('started')) or oldest)
