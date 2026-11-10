"""python <repo>\\TiaAgentStatus statusline [--root DIR]
   python <repo>\\TiaAgentStatus watch [--root DIR] [--every S] [--quiet-minutes M] [--once]
   python <repo>\\TiaAgentStatus dashboard [--root DIR] [--port P] [--every S] [--quiet-minutes M]
   python -m TiaAgentStatus report-run --repo R [--root DIR]

(how to use it: TiaAgentStatus/README.md)

statusline  the TIA row of a Claude Code status line (setting statusLine, command): the bridge this Claude session
            started (state files of TiaBridge, <projectsRoot>\\_bridge\\sessions\\), e.g.
            "TIA: Plant · no window · export blocks 31/115 · 2:10 · 3.1 GB"; nothing without one. Reads and ignores
            the JSON Claude Code sends on stdin. Never fails: on an error it prints nothing, but for bridge settings
            it cannot read, which are the row then, with the file named: the folder is unknown.
watch       herdr watcher: the TIA state as a suffix of each agent's herdr tab label, notifications when a TIA without
            window starts or ends, asks something, is gone, or uses no CPU for M minutes (default 5) during a call,
            and its own pane as a live table of the bridges with the last notifications below it. Polls every S
            seconds (default 5); --once for one round, the table printed once as plain text.
dashboard   a local page on 127.0.0.1, port P (default 8771): what happens to the projects, when and how. It reads, and
            works without herdr; its one button starts a report run. Needs you when TIA uses no CPU for M minutes
            (default 5) during a call, among others. Reads everything again every S seconds (default 1).
            Run it with pythonw for no console; a left click on its icon in the notification area opens the page, its
            right-click menu also stops it.
report-run  the change report of the project of repo R as the user's TIA holds it, without an agent: what the
            dashboard's button starts. Attaches through TiaBridge, exports, commits and runs change_report; its record
            in <root>\\_bridge\\report-runs\\ says how it went. Refuses while a bridge is on that TIA or repo.
--root      the projects root (default: projectsRoot of TiaBridge\\settings.json, in any case of the name, else
            %USERPROFILE%\\TIA-Projects). The settings are read as strict JSON: the bridge takes more (single quotes,
            names without quotes), and a file only it can read stops a command that has no --root, with the file named.
            A report run needs the file with --root too: its bridge gets the other settings from it.
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from TiaAgentStatus import state as st    # noqa: E402
from TiaAgentStatus import statusline    # noqa: E402
from TiaAgentStatus.procs import WinProcesses    # noqa: E402


def positive_seconds(text):
    """--every: the seconds between two rounds, more than none and not endless."""
    try:
        s = float(text)
    except ValueError:
        s = math.nan
    if not (s > 0 and math.isfinite(s)):
        raise argparse.ArgumentTypeError(f"takes seconds, more than 0, not '{text}'")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(prog='TiaAgentStatus', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('statusline')
    s.add_argument('--root')
    w = sub.add_parser('watch')
    w.add_argument('--root')
    w.add_argument('--every', type=positive_seconds, default=5.0)
    w.add_argument('--quiet-minutes', type=float, default=5.0)
    w.add_argument('--once', action='store_true')
    d = sub.add_parser('dashboard')
    d.add_argument('--root')
    d.add_argument('--port', type=int, default=8771)
    d.add_argument('--every', type=positive_seconds, default=1.0)
    d.add_argument('--quiet-minutes', type=float, default=5.0)
    r = sub.add_parser('report-run')
    r.add_argument('--repo', required=True)
    r.add_argument('--root')
    a = ap.parse_args(argv)
    if a.command == 'statusline':
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
        try:
            text = statusline.main(WinProcesses(), os.getpid(), a.root)
        except Exception:    # a status line shows nothing rather than a traceback
            text = ''
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)
        return 0
    try:
        if a.command == 'dashboard':
            from TiaAgentStatus import dashboard
            return dashboard.main(a)
        if a.command == 'report-run':
            from TiaAgentStatus import reportrun
            return reportrun.main(a)
        from TiaAgentStatus import watch
        return watch.main(a)
    except st.SettingsUnreadable as e:      # watch or dashboard with no --root: the bridge's settings do not give the folder
        sys.exit(f'{e}. Fix the file, or name the folder with --root.')


if __name__ == '__main__':
    if sys.argv[1:2] == ['dashboard']:      # under pythonw, a wrong option has nowhere else to say so; the status line stays without it
        from TiaAgentStatus import dashboard
        sys.exit(dashboard.guarded(main))
    sys.exit(main())
