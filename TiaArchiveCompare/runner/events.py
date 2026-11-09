"""Events to the window (stdout, one JSON object per line), the run's log.txt, and the window's commands (stdin).

The events are the ones run.py emits and window/model.py reads. Secrets (passwords) never pass
through here: the answers are handed to the exporter by the run, and only "given" or "skipped" is logged.
"""
import json
import queue
import sys
import threading
import time


def _stamp():
    return time.strftime('%H:%M:%S')


class Events:
    """Writes events to `out` (a text stream; None: no stdout) and their human form to log.txt once it is open.
    A broken stdout (the window is gone) sets `broken`; the run treats it as a cancel and goes on cleaning up."""

    def __init__(self, out=None, sink=None):
        self._out = out
        self._lock = threading.Lock()
        self._log = None
        self._early = []            # log lines before log.txt is open
        self.broken = False
        self.sink = sink            # tests: called with every event

    def open_log(self, path):
        with self._lock:
            self._log = open(path, 'a', encoding='utf-8', newline='\n')
            for line in self._early:
                self._log.write(line + '\n')
            self._early = []
            self._log.flush()

    def close(self):
        with self._lock:
            if self._log:
                self._log.close()
                self._log = None

    def emit(self, t, **fields):
        ev = {'t': t}
        ev.update((k, v) for k, v in fields.items() if v is not None)
        with self._lock:
            if self._out and not self.broken:
                try:
                    self._out.write(json.dumps(ev) + '\n')
                    self._out.flush()
                except (OSError, ValueError):
                    self.broken = True
            line = _human(ev)
            if line:
                self.text(line, locked=True)
        if self.sink:
            self.sink(ev)
        return ev

    def text(self, line, locked=False):
        """A line for log.txt only (bridge diagnostics, Siemens texts already sent as a log event)."""
        line = '%s %s' % (_stamp(), line)
        if not locked:
            self._lock.acquire()
        try:
            if self._log:
                self._log.write(line + '\n')
                self._log.flush()
            else:
                self._early.append(line)
        finally:
            if not locked:
                self._lock.release()

    def log(self, level, text):
        return self.emit('log', level=level, text=text)


def _human(ev):
    t = ev['t']
    if t == 'log':
        return '%-5s %s' % (ev['level'], ev['text'])
    if t == 'step':
        s = 'step  %s %s' % (ev['id'], ev['state'])
        if 'ms' in ev:
            s += ' %.1f s' % (ev['ms'] / 1000.0)
        if ev.get('error'):
            s += ': ' + ev['error']
        return s
    if t == 'plan':
        return 'plan  ' + ', '.join(s['id'] for s in ev['steps'])
    if t == 'tia':
        return 'tia   process %s' % ev['pid']
    if t == 'prompt':
        return 'warn  TIA asked: %s -> %s' % (ev['text'], ev['answer'])
    if t == 'ask':
        return 'ask   %s for %s' % (ev['kind'], ev['project'])
    if t == 'end':
        return 'end   ' + json.dumps({k: v for k, v in ev.items() if k != 't'})
    return None                 # progress: too many for the log


class Commands:
    """The window's commands: {"t":"cancel"}, {"t":"answer","id":...,"user"?,"password","umc_global"?} or
    {"t":"answer","id":...,"skip":true}. End of stdin is not a cancel (a missing answer counts as skipped); a closed
    stdout is (Events)."""

    def __init__(self, no_ask=False):
        self.no_ask = no_ask            # --no-ask: no one answers, also with a stdin that stays open
        self.cancel = threading.Event()
        self.eof = threading.Event()
        self._answers = queue.Queue()

    def feed(self, line):
        line = line.strip().lstrip('\ufeff')
        if not line:
            return
        try:
            cmd = json.loads(line)
            t = cmd.get('t')
        except (ValueError, AttributeError):
            # never echo the line: it may hold a password
            print('a command on stdin was not understood (not JSON)', file=sys.stderr)
            return
        if t == 'cancel':
            self.cancel.set()
        elif t == 'answer':
            self._answers.put(cmd)
        else:
            print('unknown command %r on stdin' % (t,), file=sys.stderr)

    def read_from(self, stream):
        """Reads commands on a daemon thread until the stream ends."""
        def loop():
            try:
                while True:
                    raw = stream.readline()
                    if not raw:
                        break
                    self.feed(raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw)
            except (OSError, ValueError):
                pass
            self.eof.set()
        threading.Thread(target=loop, name='commands', daemon=True).start()

    def wait_answer(self, ask_id, cancelled):
        """The answer to `ask_id`, or None when cancelled (cancelled() true), stdin ended without one, or no_ask."""
        if self.no_ask:
            return None
        while True:
            if cancelled():
                return None
            try:
                cmd = self._answers.get(timeout=0.1)
            except queue.Empty:
                if self.eof.is_set() and self._answers.empty():
                    return None
                continue
            if cmd.get('id') == ask_id:
                return cmd
