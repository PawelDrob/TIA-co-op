"""One comparison: archive A, then archive B (each: cache lookup, or start TIA, open a copy, [compile], export, close),
then the change report (python -m TiaChangeReports on the two export folders). Events on stdout, as
docs/dev/tools/tia-archive-compare.md lists them.

Where things go: the run folder <out root>\\<yyyy-MM-dd_HHmm> <A> vs <B>\\ (report.html, run.json, log.txt); under
the data root: exports\\<key>\\ (the cache), work\\<run>\\ (copies, unfinished exports; removed at the end, and
leftovers of a stopped run at the next start), times.json (the last time of each step, for "last run").
"""
import contextlib
import ctypes
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

from . import VERSION, cache, checks, errors, gitrepo, inputs
from .exporter import PART_TEXT, PARTS, ExportFailed, Hooks, NeedsLogin, parts_of

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_ROOT = os.path.dirname(os.path.dirname(HERE))          # holds TiaChangeReports
LOGIN_TRIES = 3
PROGRESS_EVERY_S = 0.1
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SCOPE_TEXT = 'PLC ' + ', '.join(PART_TEXT[p] for p in PARTS)    # PLC blocks, DBs, UDTs, PLC tag tables, ...
HMI_TEXT = ' and the HMI'


class Cancelled(Exception):
    pass


class StepFailed(Exception):
    def __init__(self, plain):
        super().__init__(plain)
        self.plain = plain


def report_counts(res):
    """(blocks changed, new or deleted; blocks and PLC tag tables that only moved to another folder; HMI objects; PLC tag
    tables changed, new or deleted) of a report's --json."""
    moved = sum(b['state'] == 'moved' for b in res.get('blocks', ()))
    tables_moved = sum(t['state'] == 'moved' for t in res.get('plcTags', ()))
    return (len(res.get('blocks', ())) - moved, moved + tables_moved, len(res.get('hmi', ())),
            len(res.get('plcTags', ())) - tables_moved)


def end_counts(report):
    """What the end event says of a report."""
    return {'report': report['path'], 'changed': report['changed'], 'moved': report['moved']}


def documents_folder():
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:      # CSIDL_PERSONAL
            return buf.value
    except (AttributeError, OSError):
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def default_out_root():
    return os.path.join(documents_folder(), 'TIA Compare')


def default_data_root():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'TIA Compare')


class Options:
    def __init__(self, before, after, title=None, compile=False, safety=False, out_root=None, data_root=None,
                 no_cache=False, keep=10, hmi=False, git=None):
        self.git = os.path.abspath(git) if git else None    # before and after are commits of this repo
        self.before = before if git else os.path.abspath(before)
        self.after = after if git else os.path.abspath(after)
        self.title = title
        self.compile = compile
        self.safety = safety
        self.out_root = os.path.abspath(out_root or default_out_root())
        self.data_root = os.path.abspath(data_root or default_data_root())
        self.no_cache = no_cache
        self.keep = keep
        self.hmi = hmi or bool(git)         # the report reads the HMI a commit holds; nothing is slow about it
        self.parts = () if git else parts_of(hmi)   # what each archive exports; part of the cache key


def pid_alive(pid):
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))                 # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    except (AttributeError, OSError):
        return True


def make_junction(target, link):
    import _winapi
    os.makedirs(os.path.dirname(link), exist_ok=True)
    _winapi.CreateJunction(target, link)


def remove_tree(path):
    """Removes a folder; junctions in it are removed as links, never followed into their target (the cache)."""
    if not os.path.lexists(path):
        return
    for d, dirs, files in os.walk(path, topdown=True):
        keep = []
        for x in dirs:
            p = os.path.join(d, x)
            if os.path.islink(p):
                os.unlink(p)
            elif os.path.isjunction(p):
                os.rmdir(p)                 # the link only
            else:
                keep.append(x)
        dirs[:] = keep
    shutil.rmtree(path, onexc=_writable)


# ---------------------------------------------------------------------------- steps

class Steps:
    """The plan's steps and their states; times.json holds the last time of each kind of step ("last run")."""

    def __init__(self, events, times_path):
        self.events = events
        self.times_path = times_path
        self.order = []
        self.info = {}
        self.current = None
        self._started = {}
        try:
            with open(times_path, encoding='utf-8') as f:
                self.times = json.load(f)
        except (OSError, ValueError):
            self.times = {}

    def plan(self, steps):
        """steps: [(id, text, time key)]"""
        for sid, text, key in steps:
            self.order.append(sid)
            self.info[sid] = {'id': sid, 'text': text, 'state': 'pending', 'key': key}
        self.events.emit('plan', steps=[{'id': s, 'text': self.info[s]['text']} for s in self.order])

    def begin(self, sid):
        self.current = sid
        self.info[sid]['state'] = 'running'
        self._started[sid] = time.monotonic()
        self.events.emit('step', id=sid, state='running', last_ms=self.times.get(self.info[sid]['key']))

    def end(self, sid, state, error=None, ms=None):
        if ms is None:
            ms = int((time.monotonic() - self._started[sid]) * 1000) if sid in self._started else 0
        i = self.info[sid]
        i.update(state=state, ms=ms)
        if error:
            i['error'] = error
        if self.current == sid:
            self.current = None
        if state == 'done' and sid in self._started:
            self.times[i['key']] = ms
            self._save_times()
        self.events.emit('step', id=sid, state=state, ms=ms, error=error)

    def end_current(self, state, error=None):
        if self.current:
            self.end(self.current, state, error)

    def skip_pending(self):
        for sid in self.order:
            if self.info[sid]['state'] == 'pending':
                self.end(sid, 'skipped', ms=0)

    def records(self):
        return [{k: v for k, v in self.info[s].items() if k != 'key'} for s in self.order]

    def _save_times(self):
        try:
            os.makedirs(os.path.dirname(self.times_path), exist_ok=True)
            tmp = self.times_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.times, f, indent=1)
            os.replace(tmp, self.times_path)
        except OSError:
            pass


class Side:
    def __init__(self, sid, source):
        self.id = sid
        self.source = source
        self.digest = None
        self.key = None
        self.export = None
        self.not_exported = []
        self.cache = None
        self.compile_mode = 'none'
        self.exported_at = None


class RunHooks(Hooks):
    """The exporter's reports, turned into events of the current step."""

    def __init__(self, run, side):
        self.run = run
        self.side = side
        self.on_phase = None
        self._last = 0.0

    def phase(self, name):
        if self.on_phase:
            self.on_phase(name)

    def tia(self, pid):
        if pid and pid != self.run.tia_pid:
            self.run.tia_pid = pid
            self.run.events.emit('tia', pid=pid)

    def progress(self, done, total, item):
        # at most 10 a second (the last of a part always): the window redraws on each
        now = time.monotonic()
        if self.run.steps.current and (done >= total or now - self._last >= PROGRESS_EVERY_S):
            self._last = now
            self.run.events.emit('progress', id=self.run.steps.current, done=done, total=total, item=item)

    def log(self, level, text):
        self.run.events.log(level, text)

    def diag(self, text):
        self.run.events.text('diag  ' + text)
        print(text, file=sys.stderr)

    def prompt(self, text, answer):
        self.run.prompts.append({'side': self.side.id, 'text': text, 'answer': answer})
        self.run.events.emit('prompt', text=text, answer=answer)

    def cancelled(self):
        return self.run.cancelled()


# ---------------------------------------------------------------------------- the run

class Run:
    def __init__(self, opts, events, commands, make_exporter, check_pc=checks.check_pc, tool_root=TOOL_ROOT):
        """make_exporter(work_dir) -> exporter.Exporter, one per archive."""
        self.o = opts
        self.events = events
        self.commands = commands
        self.make_exporter = make_exporter
        self.check_pc = check_pc
        self.tool_root = tool_root
        self.steps = Steps(events, os.path.join(opts.data_root, 'times.json'))
        self.prompts = []
        self.tia_pid = 0
        self.tia_version = 'none'
        self.tia_problems = []
        self.pc = {}
        self.report = None
        self.run_dir = None
        self._asks = 0
        if opts.git:
            self.exporter_name, self.exporter_version, self.needs_tia = None, None, False
        else:
            probe = make_exporter(None)
            self.exporter_name, self.exporter_version, self.needs_tia = probe.name, probe.version, probe.needs_tia

    def cancelled(self):
        return self.commands.cancel.is_set() or self.events.broken

    def check_cancel(self):
        if self.cancelled():
            raise Cancelled()

    @contextlib.contextmanager
    def step(self, sid):
        self.steps.begin(sid)
        try:
            yield
        except Cancelled:
            self.steps.end_current('cancelled')
            raise
        except StepFailed as e:
            self.steps.end_current('failed', e.plain)
            raise
        except ExportFailed as e:
            if self.cancelled():                # the exporter ended TIA for the cancel
                self.steps.end_current('cancelled')
                raise Cancelled()
            if e.err:
                self.events.log('error', 'TIA: ' + errors.siemens(e.err))
            self.steps.end_current('failed', e.plain)
            raise StepFailed(e.plain)
        except Exception as e:
            self.events.text('error ' + traceback.format_exc().replace('\n', '\n      '))
            traceback.print_exc()
            plain = 'The tool failed (%s: %s).' % (type(e).__name__, e)
            self.steps.end_current('failed', plain)
            raise StepFailed(plain)
        else:
            if self.steps.current == sid:
                self.steps.end(sid, 'done')

    # ------------------------------------------------------------------------ main
    def execute(self):
        o = self.o
        started = datetime.datetime.now().astimezone()
        self.sides = [Side(sid, inputs.CommitSource(rev, o.git) if o.git else inputs.classify(rev))
                      for sid, rev in (('A', o.before), ('B', o.after))]
        names = self._names()
        self.title = o.title or (gitrepo.default_title(o.git, *(s.source.short for s in self.sides)) if o.git
                                 else '%s vs %s' % tuple(names))
        try:
            self.run_dir = self._make_run_dir(names, started)
        except OSError as ex:
            error = 'The run folder could not be made in %s (%s).' % (o.out_root, ex.strerror or ex)
            self.events.emit('end', ok=False, error=error)
            return 1
        self.events.open_log(os.path.join(self.run_dir, 'log.txt'))
        # short: TIA refuses a project file path that is too long (270 characters failed), and TiaBridge's copy adds
        # <stamp>\p\ to it (bridge.py hands TIA the archive as p.<ext>)
        self.work = os.path.join(o.data_root, 'work', str(os.getpid()))
        self.cache = cache.Cache(os.path.join(o.data_root, 'exports'), o.keep)
        self.steps.plan(self._plan())
        self.events.log('info', 'Comparing %s (A) with %s (B)%s; run folder %s'
                        % (o.before, o.after, ' of %s' % o.git if o.git else '', self.run_dir))
        ok, cancelled, error = False, False, None
        try:
            self._cleanup_stale()
            with self.step('check'):
                self._check()
            for s in self.sides:
                self._side(s)
            self._report()
            ok = True
        except Cancelled:
            cancelled = True
            self.events.log('warn', 'Cancelled.' if o.git else 'Cancelled. TIA was closed and its copy deleted; nothing was changed.')
        except StepFailed as e:
            failed = [s for s in self.steps.order if self.steps.info[s]['state'] == 'failed']
            text = self.steps.info[failed[0]]['text'] if failed else ''
            error = '%s: %s' % (text, e.plain) if text else e.plain
            self.events.log('error', error)
        finally:
            self.steps.skip_pending()
            try:
                remove_tree(self.work)
            except OSError as ex:
                self.events.log('warn', 'The work folder %s could not be removed (%s); the next run removes it.'
                                % (self.work, ex.strerror or ex))
            removed = self.cache.prune(keep_keys={self._key(x, x.compile_mode) for x in self.sides if x.digest})
            if removed:
                self.events.log('info', 'Removed %d old export(s) from the cache.' % len(removed))
        not_exported = self._not_exported()
        end = {'ok': ok}
        if ok:
            end.update(end_counts(self.report))
        end['folder'] = self.run_dir
        if not_exported:
            end['not_exported'] = not_exported
        if cancelled:
            end['cancelled'] = True
        if error:
            end['error'] = error
        self._write_run_json(started, end, not_exported)
        self.events.emit('end', **end)
        self.events.close()
        return 0 if ok else 1

    def _names(self):
        names = [s.source.name for s in self.sides]
        if names[0].lower() == names[1].lower():
            names = ['%s (A)' % names[0], '%s (B)' % names[1]]
        return names

    def _make_run_dir(self, names, started):
        # 40 characters a name keep the path short; the part where A and B differ stays (inputs.safe_pair)
        base = os.path.join(self.o.out_root, '%s %s vs %s' % ((started.strftime('%Y-%m-%d_%H%M'),)
                                                               + inputs.safe_pair(names[0], names[1], 40)))
        d, n = base, 1
        while os.path.exists(d):
            n += 1
            d = '%s (%d)' % (base, n)
        os.makedirs(d)
        return d

    def _plan(self):
        if self.o.git:
            return [('check', 'Check the git repo and the two commits (no TIA Portal needed)', 'check.git'),
                    ('report', 'Compare and write the report', 'report')]
        steps = [('check', 'Check this PC (TIA Portal V20, Openness, disk, memory)', 'check')]
        for s in self.sides:
            src, p = s.source, s.id + '.'
            if src.kind == 'exports':
                steps.append((p + 'folder', '%s: use the export folder %s' % (s.id, src.name), 'folder'))
                continue
            if src.kind == 'project':
                open_text, open_key = 'copy and open the project', 'open.project'
            else:
                open_text, open_key = 'unpack and open the archive', 'open.archive'
            if src.upgrade:
                open_text += ', upgrade V%d to V20' % src.version
                open_key += '.upgrade'
            steps += [(p + 'cache', '%s: look for an earlier export of %s' % (s.id, src.name), 'cache'),
                      (p + 'start', '%s: start TIA Portal in the background' % s.id, 'start'),
                      (p + 'open', '%s: %s' % (s.id, open_text), open_key)]
            if self.o.compile:
                steps.append((p + 'compile', '%s: compile the copy%s' % (s.id, ', with the safety program'
                                                                         if self.o.safety else ''),
                              'compile.safety' if self.o.safety else 'compile'))
            steps += [(p + 'export', '%s: export %s%s' % (s.id, SCOPE_TEXT, HMI_TEXT if self.o.hmi else ''),
                       'export.hmi' if self.o.hmi else 'export'),
                      (p + 'close', '%s: close the project and end TIA' % s.id, 'close')]
        steps.append(('report', 'Compare and write the report', 'report'))
        return steps

    def _cleanup_stale(self):
        root = os.path.join(self.o.data_root, 'work')
        try:
            names = os.listdir(root)
        except OSError:
            return
        for n in names:
            pid = n.rsplit('_', 1)[-1]          # <pid>; earlier runner versions: <yyyyMMdd_HHmmss>_<pid>
            # a folder named after this process is a leftover of an ended one that had the same pid
            if not pid.isdigit() or (int(pid) != os.getpid() and pid_alive(int(pid))):
                continue
            try:
                remove_tree(os.path.join(root, n))
                self.events.log('info', 'Removed the work folder of an earlier run (%s).' % n)
            except OSError as ex:
                self.events.log('warn', 'The work folder of an earlier run (%s) could not be removed (%s); a TIA '
                                'Portal without window may still hold it.' % (n, ex.strerror or ex))

    def _check(self):
        if self.o.git:
            problem = gitrepo.compare_problem(self.o.git, self.o.before, self.o.after)
            if problem:
                raise StepFailed(problem)
            warning = gitrepo.no_exports_warning(self.o.git, self.o.before, self.o.after)
            if warning:
                self.events.log('warn', warning)
            return
        for s in self.sides:
            if s.source.problem:
                raise StepFailed('%s: %s' % (s.id, s.source.problem))
        self.pc = self.check_pc(self.o.data_root)
        self.tia_version = self.pc.get('tia') or 'none'
        for f in self.pc.get('facts', ()):
            self.events.log('info', f)
        for w in self.pc.get('warnings', ()):
            self.events.log('warn', w)
        self.tia_problems = list(self.pc.get('problems', ()))
        if self.needs_tia and any(s.source.kind != 'exports' for s in self.sides):
            for p in self.tia_problems:
                self.events.log('warn', p + ' (needed unless the exports are in the cache)')

    # ------------------------------------------------------------------------ one archive
    def _compile_mode(self):
        return 'none' if not self.o.compile else ('plc+safety' if self.o.safety else 'plc')

    def _side(self, s):
        src, p = s.source, s.id + '.'
        if src.kind == 'commit':        # the report reads it from the repo
            return
        if src.kind == 'exports':
            with self.step(p + 'folder'):
                s.export = src.path
            return
        with self.step(p + 'cache'):
            last = [-1]

            def hashed(done, total):
                if done != last[0]:
                    last[0] = done
                    self.events.emit('progress', id=p + 'cache', done=done, total=max(total, 1),
                                     item='%s (MB read)' % src.name)
                self.check_cancel()
            if src.kind == 'archive':
                s.digest = cache.file_digest(src.path, hashed)
            else:
                try:
                    s.digest = cache.folder_digest(os.path.dirname(src.path), hashed)
                except OSError as ex:
                    self.events.log('warn', '%s: %s of the project could not be read (%s): the cache is not used.'
                                    % (s.id, ex.filename or 'a file', ex.strerror or ex))
            if s.digest:
                s.key = self._key(s, self._compile_mode())
            hit = None if self.o.no_cache or not s.key else self.cache.lookup(s.key)
            if hit:
                s.export, s.cache = hit.export, 'hit'
                s.not_exported = hit.meta.get('not_exported', [])
                s.exported_at = hit.meta.get('exported')
                s.compile_mode = hit.meta.get('compile', 'none')
                self.events.log('info', '%s: using the export of %s made %s.' % (s.id, hit.meta.get('source', src.name),
                                                                                 hit.meta.get('exported', '?')))
            elif s.key:
                self.events.log('info', '%s: %s' % (s.id, 'export again (the cache is not used)' if self.o.no_cache
                                                    else 'no earlier export; TIA exports it now.'))
        self.check_cancel()
        tia_steps = [p + x for x in ('start', 'open', 'compile', 'export', 'close') if p + x in self.steps.info]
        if s.cache == 'hit':
            for sid in tia_steps:
                self.steps.end(sid, 'skipped', ms=0)
            return
        if self.needs_tia and self.tia_problems:
            with self.step(p + 'start'):
                raise StepFailed(self.tia_problems[0])
        side_work = os.path.join(self.work, s.id)
        built = os.path.join(side_work, 'entry')
        export_dir = os.path.join(built, 'export')
        os.makedirs(built, exist_ok=True)
        ex = self.make_exporter(side_work)
        hooks = RunHooks(self, s)
        opened = False
        try:
            with self.step(p + 'start'):
                def phase(name):
                    if name == 'open' and self.steps.current == p + 'start':
                        self.steps.end(p + 'start', 'done')
                        self.steps.begin(p + 'open')
                hooks.on_phase = phase
                info = self._open(ex, s, export_dir, hooks)
                opened = True
                if self.steps.current == p + 'start':           # the exporter gave no phase: its own times
                    self.steps.end(p + 'start', 'done', ms=info.times.get('start'))
                    self.steps.begin(p + 'open')
                    self.steps.end(p + 'open', 'done', ms=info.times.get('open'))
                else:
                    self.steps.end(p + 'open', 'done')
                for n in info.notes:
                    self.events.log('warn', n)
            self.check_cancel()
            if self.o.compile:
                with self.step(p + 'compile'):
                    self._compile(ex, s, hooks)
                self.check_cancel()
            with self.step(p + 'export'):
                res = ex.export(self.o.parts, hooks)
                if res.cancelled:
                    raise Cancelled()
                s.not_exported = res.not_exported
                if res.counts:
                    self.events.log('info', '%s: exported %s.' % (s.id, ', '.join(
                        '%d %s' % (n, PART_TEXT.get(k, k)) for k, n in res.counts.items() if n)))
        finally:
            if opened:
                self._close(ex, s, hooks)
            else:
                self._quiet_close(ex, hooks)
        self._store(s, built, export_dir)
        if s.cache == 'stored':
            try:
                remove_tree(side_work)              # settings, the copy if the exporter left it
            except OSError:
                pass                                # the end of the run tries again

    def _key(self, s, mode):
        return cache.make_key(s.digest, self.tia_version, self.exporter_version, self.o.parts, mode)

    def _open(self, ex, s, export_dir, hooks):
        login = None
        for attempt in range(LOGIN_TRIES + 1):
            try:
                return ex.open(s.source, export_dir, hooks, login)
            except NeedsLogin as e:
                if e.err:
                    self.events.log('info', 'TIA: ' + errors.siemens(e.err))
                if attempt == LOGIN_TRIES:
                    raise
                self.events.log('warn', '%s: %s' % (s.id, e.plain))
                ans = self._ask('umc_login', s, ex)
                if ans is None:
                    raise ExportFailed('The project is protected with user management (UMC), and no login was given.')
                login = {'user': ans.get('user') or '', 'password': ans.get('password') or '',
                         'umc_global': bool(ans.get('umc_global'))}

    def _compile(self, ex, s, hooks):
        pw = None
        if self.o.safety:
            ans = self._ask('safety_password', s, ex)
            pw = ans.get('password') if ans else None
            if pw is None:
                self.events.log('warn', '%s: compiling without the safety program; F-blocks that are not compiled '
                                'are not exported.' % s.id)
        for attempt in range(LOGIN_TRIES):
            try:
                failing = ex.compile(hooks, pw)
                break
            except NeedsLogin as e:
                self.events.log('warn', '%s: %s' % (s.id, e.plain))
                if attempt == LOGIN_TRIES - 1:
                    raise
                ans = self._ask('safety_password', s, ex)
                pw = ans.get('password') if ans else None
                if pw is None:
                    failing = ex.compile(hooks, None)
                    break
        s.compile_mode = 'plc+safety' if pw is not None else 'plc'
        if failing:
            self.events.log('warn', '%s: still not compiled after the compile: %s' % (s.id, ', '.join(failing)))

    def _ask(self, kind, s, ex):
        """Asks the window (a password or a login); None when skipped or not answered. The answer is never logged."""
        self._asks += 1
        ask_id = '%s-%s-%d' % (s.id, kind, self._asks)
        hint = ex.login_hint(kind)
        self.events.emit('ask', id=ask_id, kind=kind, project=s.source.name, **({'hint': hint} if hint else {}))
        ans = self.commands.wait_answer(ask_id, self.cancelled)
        self.check_cancel()
        what = 'the safety password' if kind == 'safety_password' else 'the project login'
        if ans is None or ans.get('skip'):
            self.events.log('info', '%s: %s was skipped.' % (s.id, what))
            return None
        self.events.log('info', '%s: %s was given.' % (s.id, what))
        return ans

    def _close(self, ex, s, hooks):
        """The close step: also after a failure or a cancel. A close that fails ends TIA hard; the run goes on."""
        self.steps.begin(s.id + '.close')
        try:
            ex.close(hooks)
        except Exception as e:                  # ExportFailed or anything: TIA must not stay behind
            self.events.log('warn', '%s: TIA did not close cleanly (%s); the tool ended it.'
                            % (s.id, getattr(e, 'plain', e)))
            if getattr(e, 'err', None):
                self.events.log('info', 'TIA: ' + errors.siemens(e.err))
            try:
                ex.kill()
            except Exception:
                traceback.print_exc()
        self.steps.end(s.id + '.close', 'done')

    def _quiet_close(self, ex, hooks):
        try:
            ex.close(hooks)
        except Exception:
            try:
                ex.kill()
            except Exception:
                traceback.print_exc()

    def _store(self, s, built, export_dir):
        git = os.path.join(export_dir, '.git')
        if os.path.isdir(git):
            shutil.rmtree(git, onexc=_writable)
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        s.exported_at = now
        if not s.digest:                                    # no certain identity to find it by later
            s.export, s.cache = export_dir, 'not stored'
            return
        meta = {'source': s.source.name, 'path': s.source.path, 'kind': s.source.kind, 'sha256': s.digest,
                'tia': self.tia_version, 'exporter': '%s %s' % (self.exporter_name, self.exporter_version),
                'scope': list(self.o.parts), 'compile': s.compile_mode, 'exported': now, 'not_exported': s.not_exported}
        try:
            entry = self.cache.store(built, self._key(s, s.compile_mode), meta)
            s.export, s.cache = entry.export, 'stored'
        except OSError as ex:
            s.export, s.cache = export_dir, 'not stored'
            self.events.log('warn', '%s: the export could not be kept in the cache (%s).' % (s.id, ex.strerror or ex))

    # ------------------------------------------------------------------------ report
    def _report(self):
        with self.step('report'):
            out = os.path.join(self.run_dir, 'report.html')
            cmd = ([sys.executable, '-m', 'TiaChangeReports'] + self._report_inputs()
                   + ['-o', out, '--title', self.title, '--json'])
            if not self.o.hmi:
                cmd += ['--only', 'plc']        # an export folder given as input may hold an HMI: not asked for
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            p = subprocess.Popen(cmd, cwd=self.tool_root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, creationflags=NO_WINDOW, env=env)
            while True:
                try:
                    so, se = p.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if self.cancelled():
                        p.kill()
                        p.communicate()
                        raise Cancelled()
            err_lines = [x for x in se.decode('utf-8', 'replace').splitlines() if x.strip()]
            for line in err_lines:
                self.events.text('diag  report: ' + line)
            if p.returncode:
                raise StepFailed('The report could not be written (%s).' % (err_lines[-1] if err_lines else
                                                                             'exit code %d' % p.returncode))
            res = json.loads(so.decode('utf-8'))
            blocks, moved, hmi, tables = report_counts(res)
            others = res.get('otherFiles', [])
            self.report = {'path': res['page'], 'changed': blocks + hmi + tables + len(others), 'blocks': blocks,
                           'moved': moved, 'skipped': res.get('skipped', [])}
            if self.o.hmi:
                self.report['hmi'] = hmi
            if tables:
                self.report['plcTags'] = tables
            if others:                          # the end event's changed holds them: the window cannot say "no changes"
                self.report['otherFiles'] = others
            what = '%d block(s)%s%s%s' % (blocks, ' and %d HMI object(s)' % hmi if self.o.hmi else '',
                                          ' and %d PLC tag table(s)' % tables if tables else '',
                                          ' and %d other file(s), not read,' % len(others) if others else '')
            self.events.log('info', 'Report: %s changed, new or deleted%s; %s'
                            % (what, '; %d only moved' % moved if moved else '', res['page']))

    def _report_inputs(self):
        return ['--git', self.o.git, self.o.before, self.o.after] if self.o.git else self._labelled()

    def _labelled(self):
        """The two export folders under the names the report shows: a junction named after each input (the report
        names a folder by its own name; the cache's is a hash)."""
        names = self._names()
        labels = inputs.safe_pair(*names)
        out = []
        for s, n, label in zip(self.sides, names, labels):
            if s.source.kind == 'exports':
                out.append(s.export)
                continue
            link = os.path.join(self.work, 'compare', label)
            try:
                make_junction(s.export, link)
                out.append(link)
            except (OSError, ImportError, AttributeError) as ex:
                self.events.text('diag  no junction for %s (%s): the report names the cache folder' % (n, ex))
                out.append(s.export)
        return out

    # ------------------------------------------------------------------------ results
    def _not_exported(self):
        merged = {}
        for s in self.sides:
            for x in s.not_exported:
                merged.setdefault((x.get('name', '?'), x.get('why', '')), []).append(s.id)
        out = [{'name': n, 'why': '%s: %s' % (' and '.join(ids), why)} for (n, why), ids in merged.items()]
        for sk in (self.report or {}).get('skipped', ()):
            out.append({'name': os.path.basename(sk.get('path', '?')),
                        'why': 'the report could not read it: %s' % sk.get('reason', '')})
        return out

    def _write_run_json(self, started, end, not_exported):
        doc = {
            'tool': {'name': 'TiaArchiveCompare', 'version': VERSION},
            'started': started.isoformat(timespec='seconds'),
            'ended': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'title': self.title,
            'inputs': [self._input_record(s) for s in self.sides],
            'options': {'compile': self.o.compile, 'safety': self.o.safety, 'hmi': self.o.hmi,
                        'noCache': self.o.no_cache, 'scope': list(self.o.parts)},
            'tia': self.tia_version,
            'exporter': {'name': self.exporter_name, 'version': self.exporter_version},
            'pc': self.pc,
            'steps': self.steps.records(),
            'notExported': not_exported,
            'prompts': self.prompts,
            'report': self.report,
            'result': {k: end[k] for k in ('ok', 'cancelled', 'error') if k in end},
        }
        try:
            with open(os.path.join(self.run_dir, 'run.json'), 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=1)
        except OSError as ex:
            self.events.log('warn', 'run.json could not be written (%s).' % (ex.strerror or ex))

    def _input_record(self, s):
        src = s.source
        if src.kind == 'commit':
            return {'side': s.id, 'kind': src.kind, 'name': src.name, 'repo': src.path, 'commit': src.given,
                    'hash': src.full_hash}
        r = {'side': s.id, 'given': os.path.abspath(src.given), 'kind': src.kind, 'name': src.name}
        if src.problem:
            r['problem'] = src.problem
        if src.version:
            r['version'] = src.version
        if src.kind == 'archive':
            try:
                r['size'] = os.path.getsize(src.path)
            except OSError:
                pass
            r['sha256'] = s.digest
        elif src.kind == 'project' and s.digest:
            r['contentSha256'] = s.digest           # file names and bytes of the project folder
        if s.key:
            r['cacheKey'] = s.key
        r['cache'] = s.cache
        if s.compile_mode != 'none':
            r['compiled'] = s.compile_mode
        if s.exported_at:
            r['exported'] = s.exported_at
        return r


def _writable(func, path, _exc):
    """shutil.rmtree onexc: git's object files are read-only."""
    os.chmod(path, 0o666)
    func(path)
