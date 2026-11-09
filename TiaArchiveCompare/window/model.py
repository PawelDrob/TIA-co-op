"""The window's state of one run, built from the runner's event lines, and the runner's commands and arguments.

No tkinter and no process here, so tests\\test_model.py drives it with no window."""
import json
import ntpath
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from TiaArchiveCompare.runner import VERSION, gitrepo

TITLE = 'TIA Archive Compare %s' % VERSION      # of the window; a download's zip has the version in its name too
STOP_NOW_AFTER = timedelta(seconds=120)


class StepState(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    SKIPPED = 'skipped'


@dataclass
class StepRow:
    id: str
    text: str
    state: StepState = StepState.PENDING
    error: Optional[str] = None
    ms: Optional[int] = None
    last_ms: Optional[int] = None
    started_at: Optional[datetime] = None


@dataclass
class ProgressInfo:
    step_id: Optional[str]
    done: int
    total: int
    item: Optional[str]


@dataclass
class LogLine:
    time: datetime
    level: str
    text: str

    @property
    def detail(self):
        """TiaBridge's own diagnostic lines (the runner's stderr "bridge: ..."): shown only with "Show details"; Copy
        log and the runner's log.txt keep them."""
        return self.level == 'stderr' and self.text.startswith('bridge: ')

    def __str__(self):
        return '%s %-6s %s' % (self.time.strftime('%H:%M:%S'), self.level, self.text)


@dataclass
class AskRequest:
    id: Optional[str]
    kind: Optional[str]
    project: Optional[str]
    hint: Optional[str] = None      # the fake exporter's sample password or login


@dataclass
class NotExportedItem:
    name: Optional[str]
    why: Optional[str]


@dataclass
class EndInfo:
    ok: bool = False
    cancelled: bool = False
    stopped: bool = False
    report: Optional[str] = None
    folder: Optional[str] = None
    error: Optional[str] = None
    changed: Optional[int] = None
    moved: Optional[int] = None
    exit_code: Optional[int] = None
    not_exported: list = field(default_factory=list)
    elapsed: timedelta = timedelta()


@dataclass
class ApplyResult:
    ask: Optional[AskRequest] = None
    ended: bool = False


def _ms_of(delta):
    return delta // timedelta(milliseconds=1)


def format_ms(ms):
    if ms < 60000:
        return '%.1f s' % (ms / 1000.0)
    return clock(timedelta(milliseconds=ms))


def clock(delta):
    """m:ss, or h:mm:ss from an hour."""
    seconds = int(delta.total_seconds())
    if seconds >= 3600:
        return '%d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return '%d:%02d' % (seconds // 60, seconds % 60)


def _str(event, key):
    value = event.get(key)
    return None if value is None else str(value)


def _int(event, key):
    try:
        return int(event.get(key))
    except (TypeError, ValueError, OverflowError):
        return None


class RunModel:
    def __init__(self):
        self.stop_now_timeout = STOP_NOW_AFTER
        self.start(datetime.now())

    def start(self, now, from_commits=False):
        self.from_commits = from_commits    # two commits of a git repo: the report sees only what was exported
        self.steps = []
        self.log = []
        self.prompts = []
        self.progress = None
        self.end = None
        self.tia_pid = 0
        self.cancel_at = None
        self.started_at = now

    def step(self, step_id):
        return next((s for s in self.steps if s.id == step_id), None)

    @property
    def current_step(self):
        return next((s for s in reversed(self.steps) if s.state == StepState.RUNNING), None)

    def apply(self, line, now):
        """One line of the runner's stdout. A line that is no event goes to the log as it is; an event of a kind not
        known here is passed over."""
        result = ApplyResult()
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        kind = _str(event, 't') if isinstance(event, dict) else None
        if kind is None:
            self.add_log(now, 'raw', line)
        elif kind == 'plan':
            self._on_plan(event)
        elif kind == 'step':
            self._on_step(event, now)
        elif kind == 'progress':
            self.progress = ProgressInfo(_str(event, 'id'), _int(event, 'done') or 0, _int(event, 'total') or 0,
                                         _str(event, 'item'))
        elif kind == 'log':
            self.add_log(now, _str(event, 'level') or 'info', _str(event, 'text') or '')
        elif kind == 'tia':
            self.tia_pid = _int(event, 'pid') or 0
        elif kind == 'prompt':
            prompt = 'TIA asked: "%s" Answered: %s' % (_str(event, 'text') or '', _str(event, 'answer') or '')
            self.prompts.append(prompt)
            self.add_log(now, 'warn', prompt)
        elif kind == 'ask':
            result.ask = AskRequest(_str(event, 'id'), _str(event, 'kind'), _str(event, 'project'), _str(event, 'hint'))
        elif kind == 'end' and self.end is None:
            self._on_end(event, now)
            result.ended = True
        return result

    def stderr(self, text, now):
        self.add_log(now, 'stderr', text)

    def add_log(self, now, level, text):
        self.log.append(LogLine(now, level, text))

    def asked(self, kind, project, skipped, now):
        """The log names the question and the choice, never the answer."""
        what = 'the project login' if kind == 'umc_login' else 'the safety password'
        self.add_log(now, 'info', 'Asked for %s%s: %s' % (what, ' of ' + project if project else '',
                                                          'skipped' if skipped else 'given'))

    def runner_exited(self, exit_code, now):
        """stdout closed and the process ended. Without an "end" before, the run failed."""
        if self.end is not None:
            return
        self.end = EndInfo(exit_code=exit_code, elapsed=now - self.started_at)
        self._close_open_steps(StepState.FAILED)

    def stopped(self, now):
        """"Stop now": the window killed the runner and TIA."""
        if self.end is not None:
            return
        self.end = EndInfo(stopped=True, elapsed=now - self.started_at)
        self._close_open_steps(StepState.CANCELLED)

    def cancel_requested(self, now):
        if self.cancel_at is None:
            self.cancel_at = now

    def offer_stop_now(self, now):
        return self.end is None and self.cancel_at is not None and now - self.cancel_at >= self.stop_now_timeout

    def _close_open_steps(self, running_becomes):
        for s in self.steps:
            if s.state == StepState.RUNNING:
                s.state = running_becomes
            elif s.state == StepState.PENDING:
                s.state = StepState.SKIPPED
        self.progress = None

    def _on_plan(self, event):
        self.steps = []
        steps = event.get('steps')
        for s in steps if isinstance(steps, list) else []:
            if isinstance(s, dict) and _str(s, 'id') is not None:
                self.steps.append(StepRow(_str(s, 'id'), _str(s, 'text') or _str(s, 'id')))

    def _on_step(self, event, now):
        s = self.step(_str(event, 'id'))
        try:
            state = StepState(_str(event, 'state'))
        except ValueError:
            return
        if s is None or state == StepState.PENDING:
            return
        s.state = state
        if _int(event, 'last_ms') is not None:
            s.last_ms = _int(event, 'last_ms')
        if state == StepState.RUNNING:
            s.started_at = now
            s.ms = None
            return
        s.ms = _int(event, 'ms')
        if s.ms is None and s.started_at is not None:
            s.ms = _ms_of(now - s.started_at)
        if _str(event, 'error') is not None:
            s.error = _str(event, 'error')
        if self.progress is not None and self.progress.step_id == s.id:
            self.progress = None

    def _on_end(self, event, now):
        end = EndInfo(ok=event.get('ok') is True, cancelled=event.get('cancelled') is True,
                      report=_str(event, 'report'), folder=_str(event, 'folder'), error=_str(event, 'error'),
                      elapsed=now - self.started_at, moved=_int(event, 'moved'))
        if end.folder is None and end.report:
            end.folder = ntpath.dirname(end.report)
        changed = event.get('changed')
        end.changed = len(changed) if isinstance(changed, list) else _int(event, 'changed')
        not_exported = event.get('not_exported')
        for item in not_exported if isinstance(not_exported, list) else []:
            if isinstance(item, dict):
                end.not_exported.append(NotExportedItem(_str(item, 'name'), _str(item, 'why')))
        self.end = end
        self._close_open_steps(StepState.DONE if end.ok else StepState.CANCELLED)

    # --- text for the window ---

    def step_time(self, s, now):
        if s.state == StepState.RUNNING and s.started_at is not None:
            elapsed = clock(now - s.started_at)
            return elapsed if s.last_ms is None else '%s (last %s)' % (elapsed, clock(timedelta(milliseconds=s.last_ms)))
        if s.ms is not None and s.state not in (StepState.PENDING, StepState.SKIPPED):
            return format_ms(s.ms)
        return ''

    def progress_line(self, now):
        if self.progress is not None:
            p = self.progress
            s = self.step(p.step_id)
            text = '%s: %d of %d' % (s.text if s is not None else p.step_id, p.done, p.total)
            return '%s (%s)' % (text, p.item) if p.item else text
        current = self.current_step
        if current is None or current.started_at is None:
            return ''
        elapsed = clock(now - current.started_at)
        if current.last_ms is None:
            return '%s: %s' % (current.text, elapsed)
        return '%s: %s (last run %s)' % (current.text, elapsed, clock(timedelta(milliseconds=current.last_ms)))

    @property
    def step_error(self):
        failed = next((s for s in self.steps if s.state == StepState.FAILED and s.error is not None), None)
        return None if failed is None else '%s: %s' % (failed.text, failed.error)

    def result_line(self):
        end = self.end
        if end is None:
            return None
        took = format_ms(_ms_of(end.elapsed))
        if end.stopped and self.from_commits:
            return 'Stopped after %s: the runner was ended. No report was written.' % took
        if end.stopped:
            return 'Stopped after %s: the runner and TIA were ended. A leftover work copy is removed at the next start.' % took
        if end.cancelled:
            if self.from_commits:
                return 'Cancelled after %s. No report was written.' % took
            return 'Cancelled after %s. TIA was closed; no project was changed.' % took
        if end.ok:
            return self._done_line(end, took)
        if end.exit_code is not None and end.error is None:
            return 'Failed: the runner ended without a result (exit code %d). See the log.' % end.exit_code
        # The failed step's own error stands under the step list; the result names the step only.
        failed = next((s for s in self.steps if s.state == StepState.FAILED), None)
        if end.error is None and failed is not None and failed.error is not None:
            return 'Failed at "%s": %s' % (failed.text, failed.error)
        message = 'Failed: ' + (end.error or 'see the log.')
        if failed is not None and end.error is not None and failed.text not in end.error:
            return '%s (step "%s")' % (message, failed.text)
        return message

    def _done_line(self, end, took):
        parts = []
        only_moved = end.moved or 0
        if end.changed is not None and (end.changed != 0 or only_moved == 0):
            nothing = 'no changes in what was exported and committed' if self.from_commits else 'no changes'
            parts.append(nothing if end.changed == 0 else '%d changed' % end.changed)
        if only_moved > 0:
            parts.append('%d only moved' % only_moved)
        if end.not_exported:
            parts.append('%d not in the report' % len(end.not_exported))
        if self.prompts:
            parts.append('%d %s answered, see the log' % (len(self.prompts), 'TIA prompt' if len(self.prompts) == 1 else 'TIA prompts'))
        return 'Done in %s%s.' % (took, ': ' + ', '.join(parts) if parts else '')

    def stop_now_offer(self):
        return 'The runner did not end within %d s of the cancel. Stop now ends the runner%s.' % (
            self.stop_now_timeout.total_seconds(), '' if self.from_commits else ' and TIA')

    def close_question(self):
        return 'A comparison is running. Cancel it and close the window once %s?' % (
            'it has ended' if self.from_commits else 'TIA is closed')

    def not_exported_heading(self):
        """The heading of the list. After two commits it never says nothing: what was never exported is not in the report."""
        end = self.end
        if end is None or (not end.ok and not end.not_exported):
            return 'Not in the report'
        also = ', and whatever was never exported and committed' if self.from_commits else ''
        if end.not_exported:
            return 'Not in the report (%d)%s' % (len(end.not_exported), also)
        return 'Not in the report: ' + ('whatever was never exported and committed' if self.from_commits else 'nothing')

    def log_text(self):
        return ''.join('%s\r\n' % line for line in self.log)


def _command(**fields):
    return json.dumps(fields, separators=(',', ':'), ensure_ascii=False)


def cancel_command():
    return _command(t='cancel')


def answer_command(ask_id, user, password, umc_global=False):
    """Carries a secret: it goes to the runner's stdin only, never into the log."""
    fields = {'t': 'answer', 'id': ask_id}
    if user is not None:
        fields['user'] = user
    fields['password'] = password
    if umc_global:
        fields['umc_global'] = True
    return _command(**fields)


def skip_command(ask_id):
    return _command(t='answer', id=ask_id, skip=True)


def clean_path(path):
    return (path or '').strip().strip('"').strip()


def name_of(path):
    p = clean_path(path).rstrip('\\/')
    stem, ext = ntpath.splitext(ntpath.basename(p))
    ext = ext.lower()
    if ext in ('.ap20', '.ap19'):
        return ntpath.basename(ntpath.dirname(p))
    if ext in ('.zap20', '.zap19'):
        return stem
    return ntpath.basename(p)


def default_title(before, after):
    return '%s vs %s' % (name_of(before), name_of(after))


def commit_label(commit):
    return '%s  %s  %s' % (commit.short, commit.date, commit.subject)


class CommitChoice:
    """The git mode's repo and two commits. before and after are what goes to the runner: the short hash the list shows,
    or a revision named on the command line."""

    def __init__(self):
        self.set_repo('', [])

    def set_repo(self, repo, commits, problem=None):
        """commits, problem: gitrepo.read_commits. It starts on the last change."""
        self.repo, self.commits, self.problem = repo, commits, problem
        self.before = commits[1].short if len(commits) > 1 else ''
        self.after = commits[0].short if commits else ''

    @property
    def labels(self):
        return [commit_label(c) for c in self.commits]

    def pick(self, is_before, index):
        if is_before:
            self.before = self.commits[index].short
        else:
            self.after = self.commits[index].short

    def name_commits(self, before, after):
        self.before, self.after = before, after

    def _listed(self, rev):
        return next((c for c in self.commits if rev and (c.hash.startswith(rev) or c.short == rev)), None)

    def label_of(self, rev):
        commit = self._listed(rev)
        return commit_label(commit) if commit else rev

    def default_title(self):
        return gitrepo.default_title(self.repo, self.before, self.after)

    def options(self):
        return RunOptions(from_commits=True, repo=self.repo, before=self.before, after=self.after)


@dataclass
class RunOptions:
    before: str = ''
    after: str = ''
    title: str = ''
    compile: bool = False
    safety: bool = False
    hmi: bool = False
    no_cache: bool = False
    from_commits: bool = False      # before and after are commits of repo
    repo: str = ''

    def validate(self):
        """None when the inputs can be given to the runner; else the message for the user."""
        a, b = clean_path(self.before), clean_path(self.after)
        if self.from_commits:
            return self._validate_commits(a, b)
        if not a:
            return 'Choose the before archive.'
        if not b:
            return 'Choose the after archive.'
        if not os.path.exists(a):
            return 'The before archive does not exist: ' + a
        if not os.path.exists(b):
            return 'The after archive does not exist: ' + b
        if _same_path(a, b):
            return 'Before and after are the same.'
        return None

    def _validate_commits(self, a, b):
        if not clean_path(self.repo):
            return 'Choose the git repo.'
        if not a:
            return 'Choose the before commit.'
        if not b:
            return 'Choose the after commit.'
        if a == b:
            return 'Before and after are the same commit.'
        return None


def _same_path(a, b):
    return os.path.normcase(os.path.abspath(a)).rstrip('\\') == os.path.normcase(os.path.abspath(b)).rstrip('\\')


def runner_arguments(prefix, options):
    """prefix: the runner's own arguments before the options, e.g. ['-m', 'TiaArchiveCompare.runner', 'run']."""
    args = list(prefix) + (['--git', clean_path(options.repo)] if options.from_commits else [])
    args += ['--before', clean_path(options.before), '--after', clean_path(options.after)]
    if options.title and options.title.strip():
        args += ['--title', options.title.strip()]
    if options.from_commits:    # the commits hold the exports: nothing to compile or export
        return args
    if options.compile:
        args.append('--compile')
        if options.safety:
            args.append('--safety')
    if options.hmi:
        args.append('--hmi')
    if options.no_cache:
        args.append('--no-cache')
    return args
