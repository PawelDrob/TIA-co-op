"""By hand, not in the hook: python TiaArchiveCompare\\window\\tests\\check.py [--out FOLDER]

It opens windows, some of them visible, and overwrites the clipboard. On a PC in use, only on a hidden desktop: its
README says how.

Runs the window with --snap in every scenario and checks the result, the log and what reached the runner's stdin:
against tests\\stub_runner.py, against the real runner with its fake exporter, and against the real runner on a made-up
git repo (two commits, a commit with no exports, no repo, a commit that is not there). No TIA starts, also in the
scenario of a wrong TIA folder, which stops before TIA. Screenshots: <out>\\<scenario>\\*.png.
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)      # the part in this process, in_one_window
STUB = os.path.join(HERE, 'stub_runner.py')
SAMPLES = os.path.join(ROOT, 'TiaArchiveCompare', 'runner', 'samples')
BRIDGE_SETTINGS = os.path.join(ROOT, 'TiaBridge', 'settings.json')
PLANT_A, PLANT_B = os.path.join(SAMPLES, 'Plant_2026-09-01.zap20'), os.path.join(SAMPLES, 'Plant_2026-10-28.zap20')
PROTECTED = os.path.join(SAMPLES, 'Plant_protected.zap20')
PASSWORD = 'Pw"x\\yä-42'       # a quote, a backslash and a non-ASCII character
NO_WINDOW = subprocess.CREATE_NO_WINDOW

failed = 0


def check(name, ok):
    global failed
    print('  %s %s' % ('ok  ' if ok else 'FAIL', name))
    failed += 0 if ok else 1


class Run:
    """One window, to its end."""

    def __init__(self, out, scenario, settings, inputs, extra=(), prefix=None):
        self.dir = os.path.join(out, scenario)
        self.record = os.path.join(self.dir, 'rec')
        os.makedirs(self.dir)
        if prefix is None:
            stub_scenario = re.sub(r'-(skip|global|details|hmi|drop|drop-shortcut)$', '', scenario)
            prefix = '"%s" --scenario %s --speed 0.5 --record "%s" run' % (STUB, stub_scenario, self.record)
        command = [sys.executable, '-X', 'utf8', '-m', 'TiaArchiveCompare.window', '--snap', self.dir,
                   '--runner', sys.executable, '--runner-args', prefix, '--settings', settings,
                   '--before', inputs[0], '--after', inputs[1], '--timeout', '60'] + list(extra)
        started = time.time()
        self.exit = subprocess.run(command, cwd=ROOT, env=dict(os.environ, STUB_EXPECT_PASSWORD=PASSWORD),
                                   timeout=120, creationflags=NO_WINDOW).returncode
        self.seconds = time.time() - started
        self.result = self.read('result.txt')
        self.log = self.read('log.txt')
        self.shown = self.read('shown.txt')
        lines = self.read(os.path.join('rec', 'commands.jsonl')).splitlines()
        self.commands = [json.loads(line) for line in lines]
        argv = self.read(os.path.join('rec', 'argv.json'))
        self.argv = json.loads(argv) if argv else []
        self.answers = [c for c in self.commands if c.get('t') == 'answer']
        print('%s (exit %s)' % (scenario, self.exit))

    def read(self, name):
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            return ''
        with open(path, encoding='utf-8') as f:
            return f.read()

    def has(self, pattern):
        return re.search(pattern, self.result) is not None

    def shot(self, name):
        """There, and a picture: one of a single colour is a window Windows had not drawn yet."""
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            return False
        with Image.open(path) as picture:
            darkest, lightest = picture.convert('L').getextrema()
        return lightest - darkest > 100


def process_is_gone(pid):
    out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH'], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return str(pid) not in out


def hung_stub_runners():
    script = ("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*stub_runner.py*--scenario hang*' } | Measure-Object | "
              "ForEach-Object { $_.Count }")
    out = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return int(out.strip() or 0)


def against_the_stub(out, settings, inputs):
    def run(scenario, *extra):
        return Run(out, scenario, settings, inputs, extra)
    before, after = inputs

    r = run('ok', '--shots', '2500,5000')
    check('ends', r.exit == 0)
    check('result line', r.has(r'result: Done in [0-9.]+ s: 7 changed, 3 not in the report, 1 TIA prompt answered, see the log\.'))
    check('all steps done', len(re.findall(r'step: \S+ done', r.result)) == 12)
    check('not in the report list', r.has(r'not exported: FB_Recipe_Secret \| know-how protected'))
    check('open report and folder enabled', r.has('buttons: report=True folder=True copylog=True compare=True'))
    check('prompt is a warning in the log', re.search(r'warn\s+TIA asked: "The project was created', r.log) is not None)
    check('runner got the paths and the default title',
          before in r.argv and after in r.argv and 'Line7 Conveyor_2026-09-01 vs Line7 Conveyor_2026-10-28' in r.argv)
    check('no compile, safety or HMI flags', not {'--compile', '--safety', '--hmi'} & set(r.argv))
    check('bridge diagnostics hidden, kept for Copy log',
          'background start: 8048 ms' not in r.shown and 'background start: 8048 ms' in r.log)
    for text in ('Compile (Uncompiled blocks will not export, not needed if project is already compiled)',
                 'Compare HMIs (slow)', 'Include safety (asks for the safety password)',
                 'Export again (ignore exports kept from earlier runs)'):
        check('option text: %s' % text, 'option: %s |' % text in r.result)
    check('option texts not cut', len(re.findall(r'option: .* \| fits=True', r.result)) == 4)
    with open(settings, encoding='utf-8') as f:
        kept = json.load(f)
    check('remembers the folders', kept['beforeFolder'] == os.path.dirname(before) and kept['afterFolder'] == os.path.dirname(after))

    r = run('ok-details', '--details')
    check('Show details: bridge diagnostics shown', 'background start: 8048 ms' in r.shown)

    r = run('ok-hmi', '--hmi', '--shots', '4200')
    check('HMI: --hmi flag', '--hmi' in r.argv)
    check('HMI: result line', r.has(r'result: Done in [0-9.]+ s: 10 changed, 4 not in the report'))
    check('HMI: screen in the not-in-the-report list', r.has(r'not exported: Conveyor_Diag \(HMI screen, Panel_1\) \| A: TIA did not export it'))
    check('HMI: export step names it', r.has('step: exportA done'))
    check('HMI: screenshot during the export', r.shot('shot-4200.png'))

    r = run('fail')
    check('result names the error and the step', r.has(r'result: Failed: The comparison stopped at a step that failed\. \(step "Unpack and open archive A"\)'))
    check('failed step and skipped rest', r.has('step: openA failed') and r.has('step: report skipped'))
    check('Siemens text in the log', re.search(r'error\s+Siemens\.Engineering\.EngineeringSecurityException', r.log) is not None)
    check('no report buttons', r.has('buttons: report=False folder=False'))

    r = run('cancel', '--cancel-at', '3000')
    check('cancel sent', len([c for c in r.commands if c.get('t') == 'cancel']) == 1)
    check('result cancelled', r.has(r'result: Cancelled after [0-9.:]+( s)?\. TIA was closed; no project was changed\.'))
    check('a step cancelled, the rest skipped', r.has(r'step: \S+ cancelled') and r.has('step: report skipped'))
    check('cancel within seconds', r.seconds < 20)

    r = run('ask-safety', '--compile', '--safety', '--answer', PASSWORD)
    check('compile and safety flags', '--compile' in r.argv and '--safety' in r.argv)
    check('one answer with the password, unchanged (UTF-8, quote, backslash)',
          len(r.answers) == 1 and r.answers[0]['id'] == 'safety-1' and r.answers[0].get('password_matches') and not r.answers[0].get('user'))
    check('password not in the log', PASSWORD not in r.log and 'Pw"x' not in r.log)
    check('log says it was given', 'Asked for the safety password of Line7_Conveyor: given' in r.log)
    check('run done', r.has('result: Done in'))
    check('dialog screenshot', r.shot('ask-1.png'))

    r = run('ask-umc', '--answer', 'maint:secret-umc-7')
    check('umc answer with user', len(r.answers) == 1 and r.answers[0].get('user') == 'maint' and r.answers[0].get('password') == '<12 chars>')
    check('umc project user: no umc_global', 'umc_global' not in r.answers[0])
    check('umc password not in the log', 'secret-umc-7' not in r.log)
    check('run done after login', r.has('result: Done in'))

    r = run('ask-umc-global', '--answer', 'srv:secret-umc-8', '--umc-global')
    check('umc server user: umc_global sent', len(r.answers) == 1 and r.answers[0].get('user') == 'srv' and r.answers[0].get('umc_global') is True)
    check('umc server user: password not in the log', 'secret-umc-8' not in r.log)

    r = run('ask-umc-skip', '--answer', 'skip')
    check('skip sent', len(r.answers) == 1 and r.answers[0].get('skip') and not r.answers[0].get('password'))
    check('run fails with the UMC text', r.has('step: openA failed') and r.has(r'protected \(UMC\)'))

    r = run('crash')
    check('runner ended without a result', r.has(r'result: Failed: the runner ended without a result \(exit code 3\)\. See the log\.'))
    check('stderr in the log', re.search(r'stderr\s+RuntimeError: stub crash', r.log) is not None)
    check('running step failed', r.has('step: exportA failed'))

    r = run('hang', '--cancel-at', '2500', '--stop-now-after', '3')
    with open(os.path.join(r.record, 'tia_pid.txt')) as f:
        tia_pid = int(f.read())
    check('stop now offered', r.shot('stop-offered.png'))
    check('result stopped', r.has(r'result: Stopped after .*: the runner and TIA were ended\.'))
    check('log names the TIA process', 'Stop now: ended the runner and TIA (process %d)' % tia_pid in r.log)
    check('TIA stand-in process is gone', process_is_gone(tia_pid))
    check('runner process is gone', hung_stub_runners() == 0)

    dropped = os.path.join(os.path.dirname(before), 'dropped ä.zap20')
    shutil.copy(before, dropped)
    r = Run(out, 'ok-drop', settings, ('', after), ['--drop', dropped])
    check('a file dropped on the box stands in it and goes to the runner', ('before: %s\n' % dropped) in r.result and dropped in r.argv)
    r = Run(out, 'ok-drop-shortcut', settings, ('', after), [dropped])
    check('a file dropped on the shortcut stands in Before and goes to the runner',
          ('before: %s\n' % dropped) in r.result and dropped in r.argv)


def against_the_real_runner(out, settings):
    def prefix(scenario, exporter=True):
        roots = '--data-root "%s" --out-root "%s"' % (os.path.join(out, scenario, 'data'), os.path.join(out, scenario, 'runs'))
        fake = '--exporter fake --fake-speed 0.02 ' if exporter else ''
        return '-X utf8 -m TiaArchiveCompare.runner run %s%s' % (fake, roots)

    r = Run(out, 'runner-ok', settings, (PLANT_A, PLANT_B), ['--hmi', '--shots', '1500'], prefix('runner-ok'))
    check('runner: report written, open report and folder enabled', r.has('result: Done in') and r.has('buttons: report=True folder=True'))
    check('runner: all steps ended', not r.has(r'step: \S+ (pending|running)'))

    r = Run(out, 'runner-safety', settings, (PLANT_A, PLANT_B), ['--compile', '--safety', '--answer', 'safe-1'], prefix('runner-safety'))
    check('runner: the safety password question, the sample password accepted', r.shot('ask-1.png') and r.has('result: Done in') and 'safety password' in r.log)
    check('runner: the safety password not in the log', 'safe-1' not in r.log.replace('the sample password is safe-1', ''))

    r = Run(out, 'runner-umc', settings, (PROTECTED, PLANT_B), ['--answer', 'engineer:umc-1'], prefix('runner-umc'))
    check('runner: the login question, the sample login accepted', r.shot('ask-1.png') and r.has('result: Done in'))

    # The real exporter: the wrong folder stops the run before TIA starts.
    if os.path.exists(BRIDGE_SETTINGS):
        print('runner-wrong-folder: skipped, %s exists here and is not this check\'s to change' % BRIDGE_SETTINGS)
        return
    wrong = os.path.join(out, 'no TIA here')
    with open(BRIDGE_SETTINGS, 'w', encoding='utf-8') as f:
        json.dump({'tiaRoot': wrong}, f)
    try:
        r = Run(out, 'runner-wrong-folder', settings, (PLANT_A, PLANT_B), [], prefix('runner-wrong-folder', False))
    finally:
        os.remove(BRIDGE_SETTINGS)
    check('wrong folder: the result line names the folder', r.has('result: Failed: .*not found in %s' % re.escape(wrong)))
    check('wrong folder: nothing to open', r.has('buttons: report=False'))


def made_up_repo(folder):
    """A git repo of the made-up test plant, in a commit with no exports and two with; their short hashes."""
    plant = os.path.join(ROOT, 'TiaChangeReports', 'tests', 'fixtures', 'plant')
    os.makedirs(folder)

    def git(*args):
        return subprocess.run(['git', '-C', folder, '-c', 'user.name=check', '-c', 'user.email=check@example.invalid'] + list(args),
                              check=True, capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    git('init', '-q')
    with open(os.path.join(folder, '.gitignore'), 'w') as f:
        f.write('*.tmp')
    git('add', '-A')
    git('commit', '-q', '-m', 'The repo made')
    hashes = [git('rev-parse', '--short', 'HEAD')]
    for version, message in (('v1', 'H001 First export'), ('v2', 'H002 Conveyor changed')):
        git('rm', '-rqf', '--ignore-unmatch', '.')
        shutil.copytree(os.path.join(plant, version), folder, dirs_exist_ok=True)
        git('add', '-A')
        git('commit', '-q', '-m', message)
        hashes.append(git('rev-parse', '--short', 'HEAD'))
    return hashes


def two_commits(out, settings):
    """The real runner on a made-up repo; what is wrong is said in the window, with no runner started."""
    def prefix(scenario):
        return ('-X utf8 -m TiaArchiveCompare.runner run --data-root "%s" --out-root "%s"'
                % (os.path.join(out, scenario, 'data'), os.path.join(out, scenario, 'runs')))

    repo = os.path.join(out, 'in', 'Line7-repo')
    empty, a, b = made_up_repo(repo)
    r = Run(out, 'commits-ok', settings, (a, b), ['--git', repo], prefix('commits-ok'))
    check('commits: the report written, no TIA step', r.has('result: Done in') and r.has('buttons: report=True')
          and re.findall(r'step: (\S+)', r.result) == ['check', 'report'])
    check('commits: the pickers show hash, date and message', r.has(r'before: %s  \d{4}-\d\d-\d\d \d\d:\d\d  H001 First export' % a))
    check('commits: the list says what is not in the report', r.has('list heading: Not in the report: whatever was never exported'))
    check('commits: the log does not repeat it', 'a change never exported is not in it' not in r.shown)

    r = Run(out, 'commits-no-exports', settings, (empty, a), ['--git', repo], prefix('commits-no-exports'))
    check('commits: a commit with no exports is compared', r.has('result: Done in') and r.has('buttons: report=True'))
    check('commits: the log warns of it', 'holds no exports, so everything in the other commit reads as new' in r.shown)

    plain = os.path.join(out, 'in', 'plain')
    os.makedirs(plain)
    r = Run(out, 'commits-no-repo', settings, ('a', 'b'), ['--git', plain], prefix('commits-no-repo'))
    check('commits: no git repo, said in plain words, nothing started',
          r.has('result: .*is no git repo') and not os.path.exists(os.path.join(out, 'commits-no-repo', 'runs')))
    r = Run(out, 'commits-gone', settings, (a, 'abc1234'), ['--git', repo], prefix('commits-gone'))
    check('commits: a commit that is not there, said in plain words, nothing started',
          r.has('result: The after commit abc1234 is not in') and not os.path.exists(os.path.join(out, 'commits-gone', 'runs')))


def windows_clipboard():
    """The text on the clipboard as another program finds it."""
    from TiaArchiveCompare.window.clipboard import CF_UNICODETEXT

    user32, kernel32 = ctypes.WinDLL('user32'), ctypes.WinDLL('kernel32')
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    user32.OpenClipboard(None)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        text = ctypes.wstring_at(kernel32.GlobalLock(handle))
        kernel32.GlobalUnlock(handle)
        return text
    finally:
        user32.CloseClipboard()


def in_one_window(out):
    """What needs a person's hand on a real window: the right-click menus, Enter on Skip, a question while minimized."""
    import tkinter as tk

    from TiaArchiveCompare.window import ask_dialog
    from TiaArchiveCompare.window.edit_menu import add_edit_menu
    from TiaArchiveCompare.window.main_window import MainWindow
    from TiaArchiveCompare.window.model import AskRequest
    from TiaArchiveCompare.window.runner_process import RunnerCommand

    print('one window')
    w = MainWindow(RunnerCommand('x', [], ROOT), os.path.join(out, 'one-window.json'))
    w.attributes('-alpha', 0)
    w.update()
    box = w.before_box
    menu = add_edit_menu(box)
    box.focus_force()
    w.update()
    w.clipboard_clear()
    w.clipboard_append('made-up pasted text')
    menu.invoke('Paste')
    w.update()
    check('menu: Paste', w.before_path.get() == 'made-up pasted text')
    menu.invoke('Select All')
    w.update()
    check('menu: Select All', box.selection_present())
    menu.invoke('Cut')
    w.update()
    check('menu: Cut', w.before_path.get() == '' and w.clipboard_get() == 'made-up pasted text')
    w.clipboard_clear()

    long_name = 'Line7 Conveyor with a made-up long name ' * 3
    w.before_path.set(long_name + 'old.zap20')
    w.after_path.set(long_name + 'new.zap20')
    w.update()
    check('the title cue ends inside its box',
          w.title_cue.winfo_rootx() + w.title_cue.winfo_width() <= w.title_box.winfo_rootx() + w.title_box.winfo_width())
    w.before_path.set('')
    w.after_path.set('')

    request = AskRequest('a1', 'safety_password', 'Line7_Conveyor')
    for button, skipped in (('skip', True), ('box', False)):
        dialog = ask_dialog.AskDialog(w, request)
        dialog.attributes('-alpha', 0)
        dialog.password.set('made-up')
        target = dialog.skip_button if button == 'skip' else dialog.first
        target.focus_force()
        dialog.update()
        target.event_generate('<Return>')
        w.update()
        check('Enter on the %s: %s' % (button, 'skips' if skipped else 'answers'), dialog.result.skip is skipped)

    dialog = ask_dialog.AskDialog(w, request)
    check('the question has the background of the window', dialog.cget('background') == w.cget('background'))
    dialog.password.set('made-up')
    dialog.first.selection_range(0, 'end')
    dialog.update()
    w.clipboard_clear()
    w.clipboard_append('before')
    dialog.first.event_generate('<<Copy>>')
    dialog.first.event_generate('<<Cut>>')
    dialog.update()
    check('the password box keeps its text and gives nothing to the clipboard',
          dialog.password.get() == 'made-up' and w.clipboard_get() == 'before')
    dialog.destroy()

    pressed = []
    button = w.open_folder_button
    button.configure(command=lambda: pressed.append(1))
    button.state(['!disabled'])
    button.focus_force()
    w.update()
    button.event_generate('<Return>')
    w.update()
    check('Enter presses the button in focus', pressed == [1])
    button.state(['disabled'])
    button.event_generate('<Return>')
    w.update()
    check('Enter does not press a button that is off', pressed == [1])
    shown_before = w.result.cget('text')
    w.before_box.focus_force()
    w.update()
    w.before_box.event_generate('<Return>')
    w.update()
    check('Enter in a box starts nothing', w.result.cget('text') == shown_before and not w.running)

    popups = []
    tk_popup = tk.Menu.tk_popup
    tk.Menu.tk_popup = lambda menu, x, y, entry='': popups.append((x, y))
    w.title_cue.event_generate('<Button-3>', rootx=300, rooty=200)
    w.update()
    tk.Menu.tk_popup = tk_popup
    check('a right-click on the empty title box opens its menu', popups == [(300, 200)])

    seen = {}

    def while_asked():
        seen['state'] = w.state()
        dialogs = [c for c in w.winfo_children() if isinstance(c, ask_dialog.AskDialog)]
        seen['shown'] = bool(dialogs) and bool(dialogs[0].winfo_viewable())
        for d in dialogs:
            d.destroy()

    w.iconify()
    w.update()
    w.after(400, while_asked)
    ask_dialog.ask(w, request)
    check('a question brings a minimized window back', seen.get('state') == 'normal' and seen.get('shown'))

    w.log.configure(state='normal')
    w.log.insert('end', 'made-up line 1\nmade-up line 2\n')
    w.log.configure(state='disabled')
    w.update()
    w.clipboard_clear()
    w.clipboard_append('before')
    w.log.event_generate('<<Copy>>')
    w.update()
    check('Copy with nothing selected leaves the clipboard', w.clipboard_get() == 'before')
    w.log.tag_add('sel', '1.0', '3.0')
    w.log.event_generate('<<Copy>>')
    w.update()
    w.destroy()
    check('Copy from the log outlives the window', windows_clipboard() == 'made-up line 1\r\nmade-up line 2\r\n')

    w = MainWindow(RunnerCommand('x', [], ROOT), os.path.join(out, 'one-window.json'))
    w.attributes('-alpha', 0)
    w.after_path.set('made-up.zap20')
    w.update()
    w.after_box.selection_range(0, 'end')
    w.after_box.event_generate('<<Cut>>')
    w.update()
    check('Cut from a box empties it', w.after_path.get() == '')
    w.destroy()
    check('Cut from a box outlives the window', windows_clipboard() == 'made-up.zap20')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'tia-compare-window-check'))
    out = p.parse_args().out
    shutil.rmtree(out, ignore_errors=True)
    folder = os.path.join(out, 'in')
    os.makedirs(folder)
    inputs = (os.path.join(folder, 'Line7 Conveyor_2026-09-01.zap20'), os.path.join(folder, 'Line7 Conveyor_2026-10-28.zap20'))
    for path in inputs:
        with open(path, 'w') as f:
            f.write('made-up')
    settings = os.path.join(out, 'window.json')
    against_the_stub(out, settings, inputs)
    against_the_real_runner(out, settings)
    two_commits(out, settings)
    in_one_window(out)
    print()
    if failed:
        print('%d check(s) failed. Output: %s' % (failed, out))
        return 1
    print('All checks passed. Screenshots: %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
