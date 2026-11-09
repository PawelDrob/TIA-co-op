"""The state files of the TiaBridge processes (<projectsRoot>\\_bridge\\sessions\\<pid>.json, written by
TiaBridge\\State.ps1): finding the folder, reading the live ones, the Claude process of a reader."""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_NAMES = ('claude.exe', 'claude', 'node.exe', 'node')
# a bridge pid whose process started this much later than the file's `started` is a reused pid
REUSE_SLACK = datetime.timedelta(seconds=5)


BRIDGE_SETTINGS = os.path.join(os.path.dirname(HERE), 'TiaBridge', 'settings.json')


BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'),
        (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))


def as_windows_powershell_reads(raw):
    """Get-Content of Windows PowerShell 5.1, which the bridge reads its settings with: by the BOM, else ANSI. Its
    twins: tools\\setup\\setup.py and TiaArchiveCompare\\runner\\checks.py."""
    for bom, encoding in BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding, 'replace')
    return raw.decode('mbcs' if os.name == 'nt' else 'latin-1', 'replace')


def bridge_settings(settings_path=BRIDGE_SETTINGS):
    """TiaBridge\\settings.json beside this folder, decoded as the bridge decodes it; {} without a file or an object."""
    try:
        with open(settings_path, 'rb') as f:
            settings = json.loads(as_windows_powershell_reads(f.read()))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def projects_root(settings_path=BRIDGE_SETTINGS):
    """projectsRoot of TiaBridge\\settings.json beside this folder, else the bridge's default."""
    return (bridge_settings(settings_path).get('projectsRoot')
            or os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'TIA-Projects'))


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
