"""The TIA row of a Claude Code status line: the state of the bridge this Claude session started, e.g.
TIA: Plant copy · no window · export blocks 31/115 · 2:10 · 3.1 GB
Elapsed time and memory come from the clock and the TIA process: the bridge cannot write during one Openness call."""
import datetime

from TiaAgentStatus import state as st

SEP = ' · '


def elapsed(since, now):
    """m:ss or h:mm:ss from the ISO time `since` to now, '' when it does not parse."""
    t = st.parse_time(since)
    if t is None:
        return ''
    s = max(0, int((now - t).total_seconds()))
    h, m = divmod(s // 60, 60)
    return f'{h}:{m:02}:{s % 60:02}' if h else f'{m}:{s % 60:02}'


def memory(n):
    if n is None:
        return ''
    return f'{n / 2**30:.1f} GB' if n >= 2**30 else f'{n // 2**20} MB'


def operation_text(op):
    """export blocks 31/115, background_open open, ..."""
    words = [op.get('name') or '?']
    where = op.get('part') or op.get('step')
    if where:
        words.append(where)
    if op.get('of'):
        words.append(f"{op.get('n', 0)}/{op['of']}")
    return ' '.join(words)


def prompt_of(s):
    """The caption or text of the last TIA prompt while the call that runs asked it, else ''."""
    p, op = s.get('lastPrompt'), s.get('operation')
    if not p or not op:
        return ''
    at, since = st.parse_time(p.get('at')), st.parse_time(op.get('since'))
    if at is None or since is None or at < since:
        return ''
    text = (p.get('caption') or p.get('text') or p.get('kind') or '').strip().replace('\n', ' ')
    return text[:40] + ('…' if len(text) > 40 else '')


def row(s, procs, now=None):
    """The status line row of state `s`, '' when the bridge holds no TIA and runs no call."""
    if not s:
        return ''
    now = now or datetime.datetime.now(datetime.timezone.utc)
    tia, op = s.get('tia'), s.get('operation')
    if not tia and not op:
        return ''
    parts = [f"TIA: {s.get('project') or '(no project)'}"]
    if tia and not tia.get('window', True):
        parts.append('no window')
    if op:
        parts.append(operation_text(op))
        parts.append(elapsed(op.get('since'), now))
    else:
        parts.append('idle')
    if tia:
        info = procs.info(tia.get('pid'))
        parts.append(memory(info.get('memory')) if info else 'TIA gone')
    asked = prompt_of(s)
    if asked:
        parts.append(f'asked: {asked}')
    return SEP.join(p for p in parts if p)


def short(s, now=None):
    """The tab label suffix: TIA export 31/115, TIA idle; '' when the bridge holds no TIA and runs no call."""
    if not s or (not s.get('tia') and not s.get('operation')):
        return ''
    op = s.get('operation')
    return 'TIA ' + (operation_text(op) if op else 'idle')


def main(procs, pid, root=None, env=None, settings=st.BRIDGE_SETTINGS):
    """The row for the status line process `pid`: its Claude process, that process's newest live bridge. Without a root,
    the bridge's settings give it; settings this tool cannot read are the row, as the bridge's folder is unknown then."""
    try:
        root = root or st.projects_root(settings)
    except st.SettingsUnreadable as e:
        return f'TIA: {e}'
    claude = st.claude_pid(procs, pid, env)
    if claude is None:
        return ''
    return row(st.bridge_of(st.live_states(st.sessions_dir(root), procs), claude), procs)
