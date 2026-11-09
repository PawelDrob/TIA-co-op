"""herdr watcher: the TIA state of each agent as a suffix of its herdr tab label (`Lead · TIA export blocks 31/115`),
herdr notifications when a TIA without window starts or ends, a bridge ends without cleanup, a TIA asks something,
a TIA is gone while its bridge runs, or a TIA uses no CPU for some minutes while a call runs (CPU time is the sign
of life: a hung TIA uses none, a busy one at least one core), and its own pane as a live table of the bridges with
the last notifications below it (table.py)."""
import collections
import datetime
import json
import re
import shutil
import subprocess
import sys
import time

from TiaAgentStatus import state as st
from TiaAgentStatus import statusline
from TiaAgentStatus import table

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)     # the dashboard has no console: a program it starts would open a window
SUFFIX = re.compile(r' · TIA .*$')
# less CPU time than this within the quiet minutes counts as no CPU
QUIET_CPU_SECONDS = 2.0
# the window of the CPU% column, and how many notifications the pane keeps
CPU_WINDOW = datetime.timedelta(minutes=1)
NOTES_KEPT = 10


class HerdrCli:
    """The herdr commands the watcher uses (herdr 0.9.5, JSON on stdout)."""

    def __init__(self, exe='herdr'):
        self.exe = exe

    def _run(self, *args):
        r = subprocess.run([self.exe, *args], capture_output=True, text=True, encoding='utf-8', timeout=15, creationflags=NO_WINDOW)
        if r.returncode:
            raise RuntimeError(f"herdr {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
        return json.loads(r.stdout).get('result', {}) if r.stdout.strip() else {}

    def tabs(self):
        """{tab id: label}"""
        return {t['tab_id']: t.get('label', '') for t in self._run('tab', 'list').get('tabs', [])}

    def pane_tabs(self):
        """{pane id: tab id}"""
        return {p['pane_id']: p['tab_id'] for p in self._run('pane', 'list').get('panes', [])}

    def pane_pids(self, pane):
        """The pids of the foreground processes of a pane (the agent: claude.exe)."""
        info = self._run('pane', 'process-info', '--pane', pane).get('process_info', {})
        return [p.get('pid') for p in info.get('foreground_processes', [])]

    def rename(self, tab, label):
        self._run('tab', 'rename', tab, label)

    def notify(self, title, body, sound='none'):
        self._run('notification', 'show', title, '--body', body, '--sound', sound)


class Watcher:
    def __init__(self, procs, herdr, root=None, quiet_minutes=5.0, now=None):
        self.procs, self.herdr, self.root = procs, herdr, root
        self.quiet = datetime.timedelta(minutes=quiet_minutes)
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.known = {}          # bridge pid -> what the last round saw
        self.orphans = set()     # state files reported as orphans
        self.claude_tabs = {}    # Claude pid -> herdr tab
        self.panes_read = False  # herdr panes read in this round
        self.first = True
        self.samples = {}        # TIA pid -> [(time, CPU s, process start)] of the last minute, for CPU%
        self.lost = {}           # TIA pid -> its last row, of a bridge that ended cleanly leaving its TIA running
        self.seen_tias = set()   # TIA pids alive in this round
        self.notes = collections.deque(maxlen=NOTES_KEPT)   # (time, text, how often in a row)
        self.view = {'now': self.now(), 'folder': st.sessions_dir(root), 'rows': [], 'notes': self.notes}

    def log(self, text):
        """A line for the pane's notifications; the same text again in a row counts up instead."""
        now = self.now()
        if self.notes and self.notes[-1][1] == text:
            self.notes[-1] = (now, text, self.notes[-1][2] + 1)
        else:
            self.notes.append((now, text, 1))

    # --- herdr, never failing a round
    def _notify(self, title, body, sound='none'):
        self.log(f'{title}: {body}')
        try:
            self.herdr.notify(title, body, sound)
        except Exception as e:
            self.log(f'notification not shown: {e}')

    def _tab_of(self, s):
        tab = (s.get('herdr') or {}).get('tab')
        if tab:
            return tab
        claude = (s.get('claude') or {}).get('pid')
        if claude not in self.claude_tabs and not self.panes_read:
            self.panes_read = True    # once a round, also when a Claude process is in no pane
            try:
                for pane, t in self.herdr.pane_tabs().items():
                    for pid in self.herdr.pane_pids(pane):
                        self.claude_tabs[pid] = t
            except Exception as e:
                self.log(f'herdr panes not read: {e}')
        return self.claude_tabs.get(claude)

    def _label(self, tabs, tab, suffix):
        if tab not in tabs:
            return
        base = SUFFIX.sub('', tabs[tab])
        label = f'{base} · {suffix}' if suffix else base
        if label != tabs[tab]:
            try:
                self.herdr.rename(tab, label)
                tabs[tab] = label
            except Exception as e:
                self.log(f'tab {tab} not renamed: {e}')

    # --- one round
    def round(self):
        now = self.now()
        self.panes_read = False
        files = st.read_states(st.sessions_dir(self.root))
        live, orphans, dead = {}, {}, []
        for path, s in files:
            if st.is_live(s, self.procs):
                live[s['pid']] = s
                continue
            dead.append(s)
            if (path, s.get('started')) not in self.orphans:
                self.orphans.add((path, s.get('started')))
                if not self.first:
                    orphans[s['pid']] = s
        try:
            tabs = self.herdr.tabs()
        except Exception as e:
            self.log(f'herdr tabs not read: {e}')
            tabs = {}

        # one bridge per tab, the newest (a leftover bridge of the same Claude, two Claude panes in one tab)
        oldest = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        shown, rows, self.seen_tias = {}, [], set()
        for pid, s in sorted(live.items(), key=lambda x: st.parse_time(x[1].get('started')) or oldest):
            tab = self._tab_of(s)
            info = self._check(pid, s, self.known.get(pid), tab, now)
            rows.append(self._row(s, tab, tabs, info, now))
            if tab:
                shown[tab] = statusline.short(s)
        for pid, k in list(self.known.items()):
            if pid in live:
                continue
            self._bridge_gone(pid, k, cleanup=pid not in orphans)
            orphans.pop(pid, None)
            if k['tab']:
                shown.setdefault(k['tab'], '')
            del self.known[pid]
        for pid, s in orphans.items():   # started and died between two rounds
            self._bridge_gone(pid, self._seen(s)[0], cleanup=False)
        for tab, suffix in shown.items():
            self._label(tabs, tab, suffix)
        rows += self._orphan_rows(dead, tabs, now)
        self.samples = {pid: v for pid, v in self.samples.items() if pid in self.seen_tias}
        self.view = {'now': now, 'folder': st.sessions_dir(self.root), 'rows': rows, 'notes': self.notes}
        self.first = False

    # --- the pane's rows
    def _row(self, s, tab, tabs, info, now, orphan=None):
        label = SUFFIX.sub('', tabs[tab]) if tab in tabs else None
        tia = (s.get('tia') or {}).get('pid')
        return {'state': s, 'agent': label, 'info': info, 'cpu': self._cpu(tia, info, now), 'orphan': orphan}

    def _cpu(self, tia, info, now):
        """The TIA's CPU time over the last minute (over the rounds so far in its first minute) in percent of one
        core: 100 = one core busy all the time; None before its second round."""
        if not info:
            return None
        self.seen_tias.add(tia)
        got = self.samples.get(tia)
        if not got or got[0][2] != info['created']:
            got = self.samples[tia] = []
        got.append((now, info['cpu'], info['created']))
        while len(got) > 1 and got[1][0] <= now - CPU_WINDOW:
            got.pop(0)
        span = (now - got[0][0]).total_seconds()
        return (info['cpu'] - got[0][1]) * 100 / span if span > 0 else None

    def _orphan_rows(self, dead, tabs, now):
        """A row per TIA whose bridge is gone: from a state file left behind (its TIA started before the file's
        last write: not a reused pid), or from a bridge that ended cleanly without closing it. Both are remembered
        until the TIA ends: the next bridge that starts deletes the file left behind."""
        rows, live_tias = [], set(self.seen_tias)
        for s in dead:
            tia = (s.get('tia') or {}).get('pid')
            info = self.procs.info(tia) if tia and tia not in self.lost and tia not in live_tias else None
            written = st.parse_time(s.get('updated')) or st.parse_time(s.get('started'))
            if info and (written is None or info['created'] <= written + st.REUSE_SLACK):
                self.lost[tia] = {'state': s, 'tab': self._tab_of(s), 'tiaCreated': info['created'],
                                  'bridge': s['pid']}
        for tia, k in list(self.lost.items()):
            info = self.procs.info(tia)
            if not info or info['created'] != k['tiaCreated']:
                del self.lost[tia]
            elif tia not in live_tias:
                live_tias.add(tia)
                rows.append(self._row(k['state'], k['tab'], tabs, info, now, orphan=k['bridge']))
        return rows

    def _seen(self, s):
        """What a round keeps of a state file, and the TIA process info."""
        tia = s.get('tia') or {}
        tia_pid = tia.get('pid')
        info = self.procs.info(tia_pid) if tia_pid else None
        return {'tia': tia_pid, 'window': tia.get('window', True), 'tiaCreated': (info or {}).get('created'),
                'title': f"TIA {s.get('project') or ''}".strip(), 'gone': bool(tia_pid and not info)}, info

    def _bridge_gone(self, pid, k, cleanup):
        """One notification for a bridge that ended: without cleanup, and whether its TIA without window still runs
        (orphaned, holding its memory) or ended with it. A bridge that ends cleanly holding no such TIA is quiet."""
        text = f"bridge {pid} ended" + ('' if cleanup else ' without cleanup')
        sound = 'none'
        if k['tia'] and not k['window'] and not k['gone']:
            info = self.procs.info(k['tia'])
            if info and info['created'] == k['tiaCreated']:
                text, sound = f"{text}, TIA {k['tia']} without window still running", 'request'
                if cleanup:   # no state file left: the pane remembers it
                    self.lost[k['tia']] = dict(k, bridge=pid)
            else:
                text, sound = f"{text}, TIA {k['tia']} without window ended", 'done'
        elif cleanup:
            return
        self._notify(k['title'], text, sound)

    def _check(self, pid, s, k, tab, now):
        new, info = self._seen(s)
        title, tia_pid, window = new['title'], new['tia'], new['window']
        op = s.get('operation')
        prompt = s.get('lastPrompt') or {}
        new.update({'state': s, 'tab': tab, 'prompt': prompt.get('at'), 'since': (op or {}).get('since'), 'cpu': None,
                    'cpuAt': None, 'quiet': False})
        if k is None:
            k = {'tia': None, 'window': True, 'prompt': new['prompt'] if self.first else None, 'since': None,
                 'gone': False, 'cpu': None, 'cpuAt': None, 'quiet': False}
            if self.first and tia_pid:
                k['tia'], k['window'] = tia_pid, window   # already running when the watcher started
        if tia_pid and not window and tia_pid != k['tia']:
            self._notify(title, f"TIA without window started (pid {tia_pid})")
        if k['tia'] and not k['window'] and tia_pid != k['tia']:
            self._notify(title, f"TIA without window ended (pid {k['tia']})", 'done')
        if new['gone'] and not (k['gone'] and k['tia'] == tia_pid):
            self._notify(title, f"TIA process {tia_pid} is gone while the bridge runs", 'request')
        if new['prompt'] and new['prompt'] != k['prompt']:
            text = ': '.join(x for x in (prompt.get('caption'), prompt.get('text')) if x)
            self._notify(title, f"TIA asked ({prompt.get('kind')}): {text} -> {prompt.get('answer')}", 'request')
        # CPU: the reference moves on while the TIA works; a call running quiet minutes without it is reported once
        if op and info:
            same = k['since'] == new['since'] and k['cpu'] is not None
            if same and info['cpu'] - k['cpu'] < QUIET_CPU_SECONDS:
                new['cpu'], new['cpuAt'], new['quiet'] = k['cpu'], k['cpuAt'], k['quiet']
                if not k['quiet'] and now - k['cpuAt'] >= self.quiet:
                    minutes = int((now - k['cpuAt']).total_seconds() // 60)
                    self._notify(title, f"TIA used no CPU for {minutes} min during {statusline.operation_text(op)}"
                                        f" (pid {tia_pid}): look for a message box", 'request')
                    new['quiet'] = True
            else:
                new['cpu'], new['cpuAt'] = info['cpu'], now
        self.known[pid] = new
        return info


def main(a, out=None, procs=None, herdr=None):
    """Round after round, the pane redrawn in place on a console; on anything else (a pipe, a file, --once) the
    table printed as plain ASCII after each round. procs, herdr: fakes in the tests."""
    if procs is None:
        from TiaAgentStatus.procs import WinProcesses
        procs = WinProcesses()
    out = out or sys.stdout
    w = Watcher(procs, herdr or HerdrCli(), a.root, a.quiet_minutes)
    screen = None if a.once or not out.isatty() else table.Screen(out)
    try:
        while True:
            try:
                w.round()
            except Exception as e:    # a round that failed is retried in the next one
                w.log(f'round failed: {e!r}')
            size = shutil.get_terminal_size((120, 40))
            if screen:
                screen.draw(table.render(w.view, size.columns, size.lines, plain=False))
            else:
                out.write('\n'.join(table.render(w.view, size.columns)) + '\n\n')
                out.flush()
            if a.once:
                return 0
            time.sleep(a.every)
    except KeyboardInterrupt:
        return 0
    finally:
        if screen:
            screen.close()


if __name__ == '__main__':
    sys.exit('run: python <repo>\\TiaAgentStatus watch')
