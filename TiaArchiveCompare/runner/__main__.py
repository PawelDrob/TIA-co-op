"""python -m TiaArchiveCompare.runner run --before A --after B [--git REPO] [--title T] [--compile [--safety]] [--hmi]
                                       [--out-root DIR] [--no-cache] [--no-ask] [--exporter tiabridge|fake] [--fake-speed X]
                                       [--data-root DIR]

(from the repo root, or the folder holding TiaArchiveCompare and TiaChangeReports; how to
use it: TiaArchiveCompare/README.md)

One comparison: A (before), then B (after), each exported by its own TIA Portal without window (or taken from the
export cache), then the change report. A and B: a TIA archive (.zap20; .zap19 is upgraded in the copy), a project
(.ap20 file or its folder; copied first) or an earlier export folder. Never a project open in TIA.

--git           A and B are two commits of this git repo, a repo the bridge made or any other: no TIA starts, and the
                report is that of TiaChangeReports --git, the HMI in it whatever --hmi says. It sees only what was
                exported and committed: a change never exported is not in it. Not with --compile, --safety, --no-cache
--title         the report's title (default: "<A> vs <B>")
--compile       compile the throwaway copy so uncompiled blocks export (never saved)
--safety        with --compile: also the safety program; the window is asked for the safety password
--hmi           also export and compare the HMI of every HMI device (WinCC Comfort: screens, templates, pop-ups,
                tags, text and graphic lists, scripts, cycles, connections, project graphics); slower
--out-root      where the run folder goes (default: Documents\\TIA Compare)
--no-cache      export again ("Export again"): the cache is not read, the new exports replace its entries
--no-ask        no one is there to answer (an agent): a password or login TIA asks for counts as skipped at once, so
                a protected project fails with that said, whatever stdin does; without it the run waits for an answer
                on stdin for as long as stdin stays open
--exporter      tiabridge (default: TiaBridge\\TiaBridge.ps1 as a child over MCP stdio) or fake (no TIA: the steps,
                times and failures of runner\\fake.py; the samples\\ archives choose what happens)
--fake-speed    fake only: factor on the measured times (default 1.0; 0: no waiting)
--data-root     cache, work copies and step times (default: %LOCALAPPDATA%\\TIA Compare)

stdout: the events, one JSON object per line (plan, step, progress, log, tia, prompt, ask, end); stderr:
diagnostics. stdin: the window's commands, one JSON object per line ({"t":"cancel"}; {"t":"answer","id":...,
"user":...,"password":...[,"umc_global":true]} or {"t":"answer","id":...,"skip":true}). Passwords come only on
stdin; they are never written to stdout, the log, run.json or a command line.
Exit code 0 when the report is written, 1 when the run failed or was cancelled, 2 on a usage error (an `end`
event says why in each case).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from TiaArchiveCompare.runner.checks import projects_roots          # noqa: E402
from TiaArchiveCompare.runner.events import Commands, Events        # noqa: E402
from TiaArchiveCompare.runner.run import Options, Run                # noqa: E402


def _under(path, root):
    path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root.rstrip('\\/') + os.sep)


def make_exporter_factory(kind, fake_speed=1.0):
    if kind == 'fake':
        from TiaArchiveCompare.runner.fake import FakeExporter
        return lambda work: FakeExporter(speed=fake_speed)
    from TiaArchiveCompare.runner.bridge import BridgeExporter
    return lambda work: BridgeExporter(work)


def main(argv=None, stdin=None, stdout=None):
    p = argparse.ArgumentParser(prog='python -m TiaArchiveCompare.runner')
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='compare two archives')
    r.add_argument('--before', required=True, help='archive, project or export folder A; with --git a commit')
    r.add_argument('--after', required=True, help='archive, project or export folder B; with --git a commit')
    r.add_argument('--git', help='the git repo that holds the two commits')
    r.add_argument('--title')
    r.add_argument('--compile', action='store_true')
    r.add_argument('--safety', action='store_true')
    r.add_argument('--hmi', action='store_true')
    r.add_argument('--out-root')
    r.add_argument('--no-cache', action='store_true')
    r.add_argument('--no-ask', action='store_true')
    r.add_argument('--exporter', choices=('tiabridge', 'fake'), default='tiabridge')
    r.add_argument('--fake-speed', type=float, default=1.0)
    r.add_argument('--data-root')
    a = p.parse_args(argv)
    out = stdout or sys.stdout
    events = Events(out)

    opts = Options(a.before, a.after, a.title, a.compile, a.safety, a.out_root, a.data_root, a.no_cache, hmi=a.hmi,
                   git=a.git)
    problem = None
    if a.safety and not a.compile:
        problem = '--safety needs --compile (the safety program is compiled with the copy).'
    for option, given in (('--compile', a.compile), ('--safety', a.safety), ('--no-cache', a.no_cache)):
        if a.git and given:
            problem = '%s does not go with --git: no TIA exports anything, the commits hold the exports.' % option
    for name, path in (('--out-root', opts.out_root), ('--data-root', opts.data_root)):
        for projects in projects_roots():
            if _under(path, projects):
                problem = '%s %s is under %s; the tool never writes there.' % (name, path, projects)
    if problem:
        print(problem, file=sys.stderr)
        events.emit('end', ok=False, error=problem)
        return 2

    commands = Commands(no_ask=a.no_ask)
    # unbuffered: a thread blocked in a buffered stdin read makes Python 3.14 abort at exit ("could not acquire
    # lock for <stdin> at interpreter shutdown", 0xC0000005) when the window keeps stdin open
    commands.read_from(stdin if stdin is not None else open(sys.stdin.fileno(), 'rb', buffering=0, closefd=False))
    run = Run(opts, events, commands, make_exporter_factory(a.exporter, a.fake_speed))
    return run.execute()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(newline='\n', line_buffering=True)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
