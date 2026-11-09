"""python -m hmipreview validate <repo> [--json] [--import] [--override] [--device NAME]
python -m hmipreview serve <repo> [--port N] [--host H] [--detach] [--verbose] [--device NAME]
python -m hmipreview diff <repo> <name> [--against commit|export] [--kind screen|template|popup] [--json]
                          [--device NAME]
python -m hmipreview png <repo> <name> <out.png> [--kind screen|template|popup] [--lang <culture>] [--device NAME]
python -m hmipreview panel <repo> <panel name | order number | WxH> [--portrait] [--device NAME]
python -m hmipreview changes <repo> REV1 [REV2] [--before-set tia|generated] [--after-set tia|generated]
                             [--device NAME ...] [--json]

--device NAME: the HMI device of a repo with one folder per device (hmi/<device>/...): its name or folder; without
it tiabridge.json hmiDevice, else the only device folder. diff, png and panel exit 2 when no device
can be chosen, serve only for a --device that is not one; validate reports it as the error
resolution.ambiguous-device. serve shows every device of the repo, opening on that one (else the first).
validate: exit code 0: no errors (warnings allowed); 1: errors; 2: usage error.
--json prints the findings as a JSON list of {severity, document, object, rule, message} (read by TiaBridge).
diff: prints the object changes of a document (the generated one, else the export) in words, one per line (exit 0),
or the /api/diff answer with --json; exit 1 when there is no document of that name, 2 on a usage error.
png: headless Edge screenshot of the preview page at device resolution (a pop-up at its own size); prints the PNG
path and size (exit 0); exit 1 when the document does not exist or Edge wrote nothing, 2 on a usage error.
panel: declares the target panel in hmi/[<device>/]panel.json (the resolution of generator, validator and preview); exit 0;
1 when it collides with the HMI device in TIA (resolution.mismatch, nothing written); 2 when the panel is unknown
(the message lists the panels) or on a usage error.
changes: the HMI changes from revision REV1 to REV2 (default: the working tree), each side in its set (tia: the TIA
exports; generated: with the generated documents in place of the exports): one line per changed document (exit 0),
or the whole result with --json (changes.Changes.to_dict); exit 1 when a revision or the repo cannot be read.
"""
import argparse
import json
import os
import sys

from .findings import ERROR
from .validator import validate


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m hmipreview')
    sub = p.add_subparsers(dest='command', required=True)
    v = sub.add_parser('validate', help='validate the HMI documents of a project repo')
    v.add_argument('repo')
    v.add_argument('--json', action='store_true', help='print the findings as JSON')
    v.add_argument('--import', dest='for_import', action='store_true', help='also run the import-only rules')
    v.add_argument('--override', action='store_true', help='import with override (staleness passes)')
    device_help = 'HMI device (name or folder under hmi/); default hmiDevice, else the only device folder'
    v.add_argument('--device', help=device_help)
    s = sub.add_parser('serve', help='start the HMI preview server for a project repo, print its URL')
    s.add_argument('repo')
    s.add_argument('--host', default='127.0.0.1',
                   help='address to bind (default 127.0.0.1: this machine only; 0.0.0.0 also answers clients on '
                        'private networks, such as the host of an engineering VM)')
    s.add_argument('--port', type=int, default=8765, help='port (default 8765, 0 = any free port)')
    s.add_argument('--detach', action='store_true', help='run in the background, print URL and pid, return')
    s.add_argument('--verbose', action='store_true', help='log every request to stderr')
    s.add_argument('--device', help=device_help)
    d = sub.add_parser('diff', help='list the object changes of a document against its last commit or export')
    d.add_argument('repo')
    d.add_argument('name', help='Name of the screen (or template / pop-up with --kind)')
    d.add_argument('--against', choices=('commit', 'export'), default='commit',
                   help='base: the last commit (default) or the TIA export')
    d.add_argument('--kind', choices=('screen', 'template', 'popup', 'textlist'), default='screen')
    d.add_argument('--json', action='store_true', help='print the /api/diff answer as JSON')
    d.add_argument('--device', help=device_help)
    g = sub.add_parser('png', help='write a PNG of a screen as the preview draws it (headless Edge)')
    g.add_argument('repo')
    g.add_argument('name', help='Name of the screen (or template / pop-up with --kind)')
    g.add_argument('out', help='PNG file to write')
    g.add_argument('--kind', choices=('screen', 'template', 'popup'), default='screen')
    g.add_argument('--lang', help='text culture (default en-US, else the first in the text)')
    g.add_argument('--device', help=device_help)
    n = sub.add_parser('panel', help='declare the target HMI panel of a project repo (hmi/panel.json)')
    n.add_argument('repo')
    n.add_argument('panel', help='panel name (TP1200 Comfort, TP1200), order number (6AV2124-0MC01-0AX0) or WxH')
    n.add_argument('--portrait', action='store_true', help='the panel is mounted portrait (width and height swapped)')
    n.add_argument('--device', help=device_help)
    c = sub.add_parser('changes', help='list the HMI changes between two revisions of a project repo')
    c.add_argument('repo')
    c.add_argument('rev1', help='the before revision')
    c.add_argument('rev2', nargs='?', help='the after revision (default: the working tree)')
    c.add_argument('--before-set', choices=('tia', 'generated'), default='tia')
    c.add_argument('--after-set', choices=('tia', 'generated'), default='tia')
    c.add_argument('--device', action='append', help='only this HMI device folder (repeatable)')
    c.add_argument('--json', action='store_true', help='print the whole result as JSON')
    raw = list(sys.argv[1:] if argv is None else argv)
    a = p.parse_args(raw)

    if not os.path.isdir(a.repo):
        p.error('not a directory: %s' % a.repo)
    if a.command in ('diff', 'png', 'panel') or (a.command == 'serve' and a.device):
        problem = device_problem(a.repo, a.device)
        if problem:
            sys.stderr.write(problem + '\n')
            return 2
    if a.command == 'serve':
        from . import server
        try:
            sys.stdout.reconfigure(encoding='utf-8')   # the repo path is in the lines; a pipe on Windows is cp1252
        except (AttributeError, ValueError):
            pass
        if a.detach:
            return server.detach([x for x in raw if x != '--detach'])
        try:
            server.serve(a.repo, a.host, a.port, verbose=a.verbose, device=a.device)
        except OSError as ex:
            sys.stderr.write('cannot listen on %s:%d: %s\n' % (a.host, a.port, ex))
            return 1
        return 0
    if a.command == 'diff':
        return diff_command(a)
    if a.command == 'panel':
        return panel_command(a)
    if a.command == 'changes':
        return changes_command(a)
    if a.command == 'png':
        from . import png
        try:
            path, w, h = png.shoot(a.repo, a.kind, a.name, a.out, a.lang, a.device)
        except png.PngError as ex:
            sys.stderr.write(str(ex) + '\n')
            return 1
        print('%s (%dx%d)' % (path, w, h))
        return 0
    findings = validate(a.repo, for_import=a.for_import, override=a.override, device=a.device)
    if a.json:
        json.dump([f.to_dict() for f in findings], sys.stdout, indent=2)
        sys.stdout.write('\n')
    else:
        for f in findings:
            print(f)
        errors = sum(f.severity == ERROR for f in findings)
        print('%d error(s), %d warning(s)' % (errors, len(findings) - errors))
    return 1 if any(f.severity == ERROR for f in findings) else 0


def device_problem(repo, device):
    """Why no HMI device can be chosen (model.select_device), or None."""
    from . import model
    try:
        with open(os.path.join(repo, 'tiabridge.json'), encoding='utf-8-sig') as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}
    return model.select_device(repo, config, device)[1]


def panel_command(a):
    from . import model, resolution
    try:
        data = resolution.parse_panel(a.panel, a.portrait)
    except ValueError as ex:
        sys.stderr.write(str(ex) + '\n')
        return 2
    declared, _ = resolution.panel_resolution(data)
    repo = model.load(a.repo, device=a.device)
    hardware = repo.hardware
    if hardware is not None and not declared.same_screen(hardware):
        sys.stderr.write('resolution.mismatch: the panel %s differs from the HMI device in TIA, %s; nothing written. '
                         'Declare the panel of the device, or fix the device in TIA.\n'
                         % (declared.describe(), hardware.describe()))
        return 1
    path = os.path.join(a.repo, *repo.panel_file.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(resolution.panel_bytes(data))
    print('%s: %s' % (repo.panel_file, declared.describe()))
    return 0


def changes_command(a):
    from . import changes, sides
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    try:
        result = changes.compare(sides.side(a.repo, a.rev1), sides.side(a.repo, a.rev2), a.before_set,
                                 a.after_set, a.device)
    except ValueError as ex:
        sys.stderr.write(str(ex) + '\n')
        return 1
    if a.json:
        json.dump(result.to_dict(), sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write('\n')
        return 0
    print('%s -> %s' % (result.before, result.after))
    for line in result.lines() or ['No HMI changes.']:
        print(line)
    return 0


def diff_command(a):
    from . import diff, model
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    try:
        data = diff.compare(model.load(a.repo, device=a.device), a.kind, a.name, a.against)
    except diff.DiffError as ex:
        sys.stderr.write(ex.message + '\n')
        return 1
    if a.json:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write('\n')
    elif data['lines']:
        for line in data['lines']:
            print(line)
    else:
        print('No changes against the %s.' % ('last commit' if a.against == 'commit' else 'TIA export'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
