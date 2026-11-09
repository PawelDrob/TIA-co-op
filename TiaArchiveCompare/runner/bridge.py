"""TiaBridge as the exporter: one child process per archive, driven over MCP stdio as TiaBridge\\Tests\\Smoke.ps1
does (JSON-RPC, one message per line): background_open, full_export per part, background_close.

The child gets its own settings file: projectsRoot is the folder of the export (the repo is the export folder),
backgroundRoot the run's work folder, so nothing goes to %USERPROFILE%\\TIA-Projects; tiaRoot is the one of
TiaBridge\\settings.json, where the check of this PC looked. Passwords travel only in the tool arguments on the
child's stdin. The export folder is a plain one (background_open plain=true: no git) when the bridge offers it.

Progress: TiaBridge's stderr lines `progress {json}` (TiaBridge\\Mcp.ps1): event `tia` (pid), `step`
(step, state start / done / failed, pid), `part` (full_export part start / done), `object` (part, kind, n, of, name,
ok). Without them (an older TiaBridge): the pid comes with the background_open result, export progress per part.

Logins: an export-only session compiles its copy (never saved); the safety password (safety_login password) and the
project login (background_open umc_user, umc_password) are taken in a plain session only, and TiaBridge hides them
in its results, logs and stderr; umc_global (the window's "UMC server user": a UMC user instead of a project user)
is sent when ticked. An older TiaBridge without these arguments is detected from tools/list; the step then fails
saying this TiaBridge cannot do it yet.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading

from . import checks, errors
from .exporter import (HMI_PARTS, PART_TEXT, ExportFailed, Exporter, ExportResult, NeedsLogin, OpenResult,
                       item_name, part_where)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BRIDGE = os.path.join(ROOT, 'TiaBridge', 'TiaBridge.ps1')
POWERSHELL = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0',
                          'powershell.exe')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# the login arguments (checked against tools/list)
UMC_USER_ARG = 'umc_user'
UMC_PASSWORD_ARG = 'umc_password'
UMC_GLOBAL_ARG = 'umc_global'
SAFETY_TOOL = 'safety_login'
SAFETY_PASSWORD_ARG = 'password'

# How this client reads TiaBridge's results (not exported, counts): part of the cache key, since a cached export
# keeps what was read then. Raise it when that reading changes.
CLIENT_VERSION = 2

_PROGRESS = re.compile(r'\bprogress\s+(\{.*\})\s*$')
_OPEN_STEPS = ('retrieve', 'copy', 'open')        # the upgrade runs inside retrieve or open


def bridge_version(root=ROOT):
    """'tiabridge-<12 hex>-c<client>' over TiaBridge's scripts and CLIENT_VERSION: a changed exporter means changed
    exports (normalization)."""
    h = hashlib.sha256()
    base = os.path.join(root, 'TiaBridge')
    for d in (base, os.path.join(base, 'Tools')):
        try:
            names = sorted(n for n in os.listdir(d) if n.lower().endswith('.ps1'))
        except OSError:
            continue
        for n in names:
            with open(os.path.join(d, n), 'rb') as f:
                h.update(n.lower().encode('utf-8') + b'\0' + f.read())
    return 'tiabridge-%s-c%d' % (h.hexdigest()[:12], CLIENT_VERSION)


def parse_progress(line):
    """The JSON object of a `progress {json}` line, else None."""
    m = _PROGRESS.search(line)
    if not m:
        return None
    try:
        p = json.loads(m.group(1))
    except ValueError:
        return None
    return p if isinstance(p, dict) else None


def _decode(raw):
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('mbcs' if os.name == 'nt' else 'latin-1', 'replace')


class BridgeExporter(Exporter):
    name = 'tiabridge'
    needs_tia = True

    def __init__(self, work_dir, command=None):
        """work_dir: this archive's work folder (settings, the copy). command: the child's command line (tests:
        a stand-in server); default powershell.exe -STA TiaBridge.ps1 -SettingsPath <work>\\settings.json."""
        self.work = work_dir
        self.command = command
        self.version = bridge_version()
        self._p = None
        self._reader = None
        self._id = 0
        self._hooks = None
        self._hooks_lock = threading.Lock()     # the stderr thread reports only while a call runs
        self._tools = {}
        self._object_progress = False
        self._stderr_tail = []
        self.tia_pid = 0
        self.opened = False
        self.cancel_ended = False               # a cancel ended TIA and the child during a call

    # ---------------------------------------------------------------- child and protocol
    def _start(self, export_dir):
        os.makedirs(self.work, exist_ok=True)
        settings = os.path.join(self.work, 'settings.json')
        with open(settings, 'w', encoding='utf-8') as f:
            json.dump({'projectsRoot': os.path.dirname(export_dir), 'backgroundRoot': os.path.join(self.work, 'copy'),
                       'tiaRoot': checks.tia_root(), 'maxResponseChars': 50000000}, f, indent=1)
        cmd = self.command or [POWERSHELL, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', BRIDGE,
                               '-SettingsPath', settings]
        self._p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=NO_WINDOW)
        self._reader = threading.Thread(target=self._read_stderr, name='bridge-stderr', daemon=True)
        self._reader.start()
        self._request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                     'clientInfo': {'name': 'TiaArchiveCompare', 'version': '1'}})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        listed = self._request('tools/list', {})
        self._tools = {t['name']: t for t in listed.get('tools', [])}

    def _has_arg(self, tool, arg):
        t = self._tools.get(tool)
        return bool(t and arg in ((t.get('inputSchema') or {}).get('properties') or {}))

    def _send(self, msg):
        data = (json.dumps(msg) + '\n').encode('utf-8')
        try:
            self._p.stdin.write(data)
            self._p.stdin.flush()
        except OSError as ex:
            raise self._gone('the request could not be sent (%s)' % ex)

    def _gone(self, what):
        tail = ' | '.join(self._stderr_tail[-5:])
        return ExportFailed('TIA Portal ended unexpectedly or stopped answering.',
                            'TiaBridge child: %s%s' % (what, ('; last lines: ' + tail) if tail else ''))

    def _request(self, method, params):
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        while True:
            raw = self._p.stdout.readline()
            if not raw:
                raise self._gone('it ended during %s' % method)
            try:
                msg = json.loads(raw.decode('utf-8'))
            except ValueError:
                continue
            if msg.get('id') != rid:
                continue                    # a notification
            if 'error' in msg:
                raise ExportFailed('The exporter refused a request.', '%s: %s' % (method, msg['error'].get('message')))
            return msg.get('result') or {}

    def _call(self, tool, args, hooks):
        """A tools/call; returns the tool's result object. Prompts in it go to the hooks. A cancel during the call
        (not the close) ends the throwaway TIA and the child at once: nothing is lost, the copy is thrown away and
        the cache entry is written only when complete."""
        with self._hooks_lock:
            self._hooks = hooks
        done = threading.Event()
        if tool != 'background_close':
            threading.Thread(target=self._watch_cancel, args=(hooks, done), name='bridge-cancel', daemon=True).start()
        try:
            res = self._request('tools/call', {'name': tool, 'arguments': args})
        except (ExportFailed, OSError, ValueError):
            if self.cancel_ended:
                raise ExportFailed('Cancelled: TIA was ended.')
            raise
        finally:
            done.set()
            with self._hooks_lock:
                self._hooks = None
        try:
            r = json.loads(res['content'][0]['text'])
        except (KeyError, IndexError, ValueError):
            raise ExportFailed('The exporter gave an answer the tool cannot read.', '%s: %r' % (tool, res)[:2000])
        for p in r.get('prompts') or ():
            text = ': '.join(x for x in (p.get('caption'), p.get('text')) if x) or 'TIA asked something.'
            hooks.prompt(text, p.get('answer') or '')
        return r

    def _watch_cancel(self, hooks, done):
        while not done.wait(0.2):
            if hooks.cancelled():
                self.cancel_ended = True
                self.opened = False             # nothing to close any more
                # only the processes: the pipes stay for the call's thread, which then reads the end of stdout
                self._kill_tia()
                if self._p and self._p.poll() is None:
                    _taskkill(self._p.pid, tree=True)
                return

    def _read_stderr(self):
        # Lines that come after the call's answer are dropped (its result has the pid and the times); the lock keeps
        # a report from changing the run's steps after the call returned.
        try:
            for raw in iter(self._p.stderr.readline, b''):
                self._stderr_line(_decode(raw).rstrip('\r\n'))
        except (OSError, ValueError):           # the pipe closed under it
            pass

    def _stderr_line(self, line):
        p = parse_progress(line)
        if p is None:
            self._stderr_tail = (self._stderr_tail + [line])[-20:]
        with self._hooks_lock:
            hooks = self._hooks
            if not hooks:
                return
            if p is not None:
                self._on_progress(p, hooks)
            else:
                hooks.diag('bridge: ' + line)

    def _on_progress(self, p, hooks):
        ev = p.get('event')
        if p.get('pid') and int(p['pid']) != self.tia_pid:
            self.tia_pid = int(p['pid'])
            hooks.tia(self.tia_pid)
        if ev == 'step' and p.get('step') in _OPEN_STEPS and p.get('state') == 'start':
            hooks.phase('open')
        elif ev == 'object' and p.get('of'):
            self._object_progress = True
            part = p.get('part') or p.get('kind') or ''
            name = p.get('name') or ''
            hooks.progress(int(p.get('n') or 0), int(p['of']),
                           ('%s: %s' % (part_where(part, p.get('device') or ''), name)) if part else name)

    # ---------------------------------------------------------------- interface
    def _short_copy(self, source):
        """An archive as a copy named p.<ext> in the work folder: TIA unpacks it into a folder named after the file,
        and a long name pushed the project's file paths over the Windows limit. The user's name stays in the report
        and run.json (they use source). A project folder goes as it is (TiaBridge copies it)."""
        if source.kind != 'archive':
            return source.path
        dest = os.path.join(self.work, 'p' + os.path.splitext(source.path)[1].lower())
        try:
            shutil.copyfile(source.path, dest)
        except OSError as ex:
            raise ExportFailed('The archive could not be copied to the work folder (%s).' % (ex.strerror or ex),
                               '%s -> %s: %s' % (source.path, dest, ex))
        return dest

    def open(self, source, export_dir, hooks, login=None):
        if not self._p:
            self._start(export_dir)
        args = {'path': self._short_copy(source), 'repo': os.path.basename(export_dir)}
        if self._has_arg('background_open', 'plain'):
            args['plain'] = True
        if login:
            if not self._has_arg('background_open', UMC_PASSWORD_ARG):
                raise ExportFailed('The project is protected with user management (UMC); this TiaBridge cannot log on '
                                   'to protected projects yet.')
            if login.get('user'):
                args[UMC_USER_ARG] = login['user']
            args[UMC_PASSWORD_ARG] = login.get('password', '')
            if login.get('umc_global'):
                if not self._has_arg('background_open', UMC_GLOBAL_ARG):
                    raise ExportFailed('This TiaBridge cannot log on with a UMC server user yet; log on with a '
                                       'project user.')
                args[UMC_GLOBAL_ARG] = True
        r = self._call('background_open', args, hooks)
        if not r.get('ok'):
            err = r.get('error') or r.get('refused')
            if r.get('hint'):
                hooks.log('info', 'TiaBridge: ' + r['hint'])
            if errors.is_protected(err):
                raise NeedsLogin('umc_login', errors.plain(err), err, wrong=bool(login))
            raise ExportFailed(errors.plain(err), err)
        self.opened = True
        if r.get('processId'):
            self.tia_pid = int(r['processId'])
            hooks.tia(self.tia_pid)
        times = {}
        for s in r.get('steps') or ():
            k = 'start' if s.get('step') == 'start' else 'open'
            times[k] = times.get(k, 0) + int(s.get('ms') or 0)
        notes = []
        for t in r.get('otherHeadlessTia') or ():
            notes.append('Another TIA Portal without window is running (process %s); it takes memory.'
                         % (t.get('processId') if isinstance(t, dict) else t))
        if r.get('promptGuard'):
            notes.append('TIA prompts cannot be answered in this session: ' + errors.siemens(r['promptGuard']))
        return OpenResult(self.tia_pid, times, bool(r.get('upgraded')), notes)

    def compile(self, hooks, safety_password=None):
        if safety_password is not None:
            if not self._has_arg(SAFETY_TOOL, SAFETY_PASSWORD_ARG):
                raise ExportFailed('This TiaBridge cannot take the safety password from the tool yet.')
            r = self._call(SAFETY_TOOL, {SAFETY_PASSWORD_ARG: safety_password}, hooks)
            if not r.get('ok'):
                err = r.get('error') or r.get('refused')
                if re.search(r'password|Passwort|Kennwort', errors.siemens(err), re.IGNORECASE):
                    raise NeedsLogin('safety_password', 'The safety password was not accepted.', err, wrong=True)
                raise ExportFailed(errors.plain(err, 'The safety login failed (the log has the reason).'), err)
        r = self._call('compile', {'scope': 'plc'}, hooks)
        if r.get('refused'):
            raise ExportFailed('This TiaBridge cannot compile the copy yet.', r['refused'])
        if r.get('error'):
            raise ExportFailed(errors.plain(r['error']), r['error'])
        if r.get('errors'):
            hooks.log('warn', 'The compile left %s error(s); blocks that still fail are not exported.' % r['errors'])
        return list(r.get('failed') or ())

    def export(self, parts, hooks):
        out = []
        counts = {}
        hmi_devices = set()
        for i, part in enumerate(parts):
            if hooks.cancelled():
                return ExportResult(out, cancelled=True, counts=counts)
            self._object_progress = False
            r = self._call('full_export', {'parts': [part]}, hooks)
            if r.get('refused'):
                raise ExportFailed('The exporter refused the export.', r['refused'])
            if r.get('stopped'):
                raise ExportFailed(errors.plain('does not answer any more'), r['stopped'])
            if r.get('error'):
                raise ExportFailed(errors.plain(r['error']), r['error'])
            for d in r.get('details') or ():
                device = d.get('device') or ''
                if part in HMI_PARTS and part != 'graphics':
                    hmi_devices.add(device)
                if d.get('listError'):
                    raise ExportFailed('TIA could not list the %s of the project.' % part_where(part, device),
                                       d['listError'])
                counts[part] = counts.get(part, 0) + int(d.get('exported', d.get('count')) or 0)
                for f in d.get('failed') or ():
                    err = f.get('error') or ' '.join(m.get('description', '') for m in
                                                     ((f.get('messages') or {}).get('messages') or ()))
                    name = item_name(f.get('name', '?'), part, device)
                    out.append({'name': name, 'why': errors.why_not_exported(err)})
                    hooks.log('warn', 'Not exported: %s: %s' % (name, errors.siemens(f.get('error')) or err))
                for name in d.get('knowHowProtected') or ():
                    out.append({'name': name, 'why': 'know-how protected: only its interface is compared'})
                # what TIA does not permit to export (F-system blocks, the F-OB; know-how protected library types)
                for n in d.get('notExported') or ():
                    name = item_name(n.get('name', '?'), part, device)
                    out.append({'name': name, 'why': errors.why_not_exported(n.get('message') or n.get('reason'))})
                    hooks.log('info', 'Not exportable: %s: %s' % (name, n.get('reason') or n.get('message')))
            for line in r.get('parts') or ():
                hooks.log('info', 'Exported ' + line)
            if not self._object_progress:
                hooks.progress(i + 1, len(parts), PART_TEXT.get(part, part))
        if any(p in HMI_PARTS for p in parts) and not hmi_devices:
            hooks.log('info', 'The project has no HMI device: the report compares the PLC only.')
        return ExportResult(out, counts=counts)

    def close(self, hooks):
        try:
            if self.opened:
                r = self._call('background_close', {}, hooks)
                self.opened = False
                for e in r.get('errors') or ():
                    hooks.log('warn', 'Closing TIA: ' + errors.siemens(e))
                if r.get('tiaEnded') is False:
                    hooks.log('warn', 'TIA did not end by itself; the tool ended it (process %s).' % self.tia_pid)
                    self._kill_tia()
        finally:
            self._stop_child()

    def kill(self):
        self._kill_tia()
        if self._p and self._p.poll() is None:
            _taskkill(self._p.pid, tree=True)
            try:
                self._p.wait(10)
            except subprocess.TimeoutExpired:
                pass
        self._release()

    def _kill_tia(self):
        if self.tia_pid:
            _taskkill(self.tia_pid)
            self.tia_pid = 0

    def _stop_child(self):
        if not self._p:
            return
        try:
            self._p.stdin.close()
        except OSError:
            pass
        try:
            self._p.wait(30)
        except subprocess.TimeoutExpired:
            self.kill()
        self._release()

    def _release(self):
        """The pipes of an ended child."""
        if not self._p or self._p.poll() is None:
            return
        if self._reader:
            self._reader.join(2)
        for f in (self._p.stdin, self._p.stdout, self._p.stderr):
            try:
                f.close()
            except (OSError, ValueError):
                pass


def _taskkill(pid, tree=False):
    cmd = [os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe'), '/F', '/PID',
           str(pid)]
    if tree:
        cmd.insert(2, '/T')
    try:
        subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
