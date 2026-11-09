"""python -X utf8 -m TiaArchiveCompare.package.build [--out DIR] [--tag vX.Y.Z] [--no-check] [--visible]    (from the repo folder)

Builds the download of TIA Archive Compare: dist\\TIA-Archive-Compare-<version>.zip, a folder a person unpacks and starts
with no Python, uv or clone of their own. Then checks the zip (check.py) unless --no-check.

The folder holds the repo's own layout, so the runner finds TiaChangeReports, TiaHmiGenerator and TiaBridge as in a
clone: the tracked files of those (package_files), a standalone CPython with tkinter from uv in
TiaArchiveCompare\\window\\python\\ (where the window and the shortcut look first) with the packages of uv.lock, and
"TIA Archive Compare.exe" at the top, a launcher compiled from launcher.cs by Windows PowerShell's Add-Type.

--out       where the zip goes (default: dist\\ in the repo, which git ignores)
--tag       the release tag: the build stops unless it is v<version> (the release workflow passes the pushed tag)
--no-check  skip the check of the zip
--visible   the check's window on this desktop, not on a hidden one of its own

Needs uv, git and Windows PowerShell; uv downloads the Python the first time. The version is VERSION of
TiaArchiveCompare\\runner, which TiaBridge\\Mcp.ps1 must state too.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from TiaArchiveCompare.window import shortcut

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LAUNCHER = shortcut.LAUNCHER
PYTHON_DIR = os.path.join('TiaArchiveCompare', 'window', 'python')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# What the runner and the window call, as tracked: folders by prefix, files by name
INCLUDE = ('LICENSE', 'NOTICE', 'TiaArchiveCompare/README.md', 'TiaArchiveCompare/runner/', 'TiaArchiveCompare/window/',
           'TiaChangeReports/', 'TiaHmiGenerator/', 'TiaBridge/')
# the plant the fake exporter plays for the samples (runner\fake.py PLANT): the only test files that go in
FAKE_PLANT = 'TiaChangeReports/tests/fixtures/plant/'
# Of the bundled Python: what only building against it or testing it needs, and its pip: the download installs nothing
PRUNE_TOP = {'include', 'libs', 'scripts'}
SITE_PACKAGES = os.path.join('Lib', 'site-packages')
PRUNE_ANYWHERE = re.compile(r'^(__pycache__|EXTERNALLY-MANAGED|_test\w*\.pyd|_ctypes_test\.pyd|\w+\.lib)$', re.IGNORECASE)


class BuildError(Exception):
    """In words for the person who ran the build."""


def package_files(tracked):
    """The tracked paths (forward slashes) that go into the download, in their order."""
    def wanted(path):
        if path == FAKE_PLANT.rstrip('/') or path.startswith(FAKE_PLANT):
            return True
        if not any(path == i or (i.endswith('/') and path.startswith(i)) for i in INCLUDE):
            return False
        parts = path.split('/')
        return parts[-1] != '.gitignore' and not any(p.lower() == 'tests' for p in parts[:-1])
    return [p for p in tracked if wanted(p)]


def version(root=ROOT, tag=None):
    """The version the download is built for: VERSION of the runner, the one TiaBridge\\Mcp.ps1 states and, given, the
    tag without its v."""
    with open(os.path.join(root, 'TiaArchiveCompare', 'runner', '__init__.py'), encoding='utf-8') as f:
        runner = re.search(r"^VERSION = '([^']+)'", f.read(), re.MULTILINE)
    with open(os.path.join(root, 'TiaBridge', 'Mcp.ps1'), encoding='utf-8') as f:
        bridge = re.search(r"^\$script:McpServerVersion = '([^']+)'", f.read(), re.MULTILINE)
    if not runner or not bridge:
        raise BuildError('No version found in TiaArchiveCompare\\runner\\__init__.py or TiaBridge\\Mcp.ps1.')
    if runner.group(1) != bridge.group(1):
        raise BuildError('The versions differ: %s in TiaArchiveCompare\\runner\\__init__.py, %s in TiaBridge\\Mcp.ps1.'
                         % (runner.group(1), bridge.group(1)))
    if tag is not None and tag != 'v' + runner.group(1):
        raise BuildError('The tag %s is not v%s, the version of the tools.' % (tag, runner.group(1)))
    return runner.group(1)


def package_name(number):
    return 'TIA-Archive-Compare-%s' % number


def _run(cmd, **kw):
    done = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW, **kw)
    if done.returncode:
        raise BuildError('%s failed (exit code %d): %s' % (' '.join(cmd[:3]), done.returncode,
                                                          (done.stderr or done.stdout).strip()[-2000:]))
    return done.stdout


def _tracked(root):
    return [p for p in _run(['git', '-C', root, 'ls-files', '-z']).split('\0') if p]


def _changed(root, files):
    """Tracked files of the download that differ from HEAD: the build takes them as they are, and says so."""
    out = _run(['git', '-C', root, 'status', '--porcelain', '-z', '--untracked-files=no'])
    changed = {entry[3:] for entry in out.split('\0') if len(entry) > 3}
    return sorted(changed & set(files))


def _copy_files(root, files, stage):
    for path in files:
        dest = os.path.join(stage, *path.split('/'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(root, *path.split('/')), dest)


def _python_request(root):
    """The Python of the repo's .python-version (3.13: uv takes its newest patch)."""
    with open(os.path.join(root, '.python-version'), encoding='utf-8') as f:
        return f.read().strip()


def _standalone_python(request, work):
    """uv's standalone CPython of that request, installed into work: its folder (the one named by its full version, not
    the link uv makes for the minor version)."""
    installs = os.path.join(work, 'uv-python')
    _run(['uv', 'python', 'install', request, '--install-dir', installs, '--no-bin'])
    found = [os.path.join(installs, n) for n in os.listdir(installs)
             if re.match(r'cpython-\d+\.\d+\.\d+-windows-x86_64-none$', n)
             and os.path.isfile(os.path.join(installs, n, 'python.exe'))]
    if len(found) != 1:
        raise BuildError('uv python install %s gave %d Pythons in %s, not one.' % (request, len(found), installs))
    return found[0]


def _pruner(top):
    """copytree's ignore: PRUNE_TOP in the top folder, all of site-packages, PRUNE_ANYWHERE in any."""
    def ignore(folder, names):
        if os.path.normcase(folder) == os.path.normcase(os.path.join(top, SITE_PACKAGES)):
            return names
        at_top = os.path.normcase(folder) == os.path.normcase(top)
        return [n for n in names if (at_top and n.lower() in PRUNE_TOP) or PRUNE_ANYWHERE.match(n)]
    return ignore


def _bundle_python(root, stage, work):
    """The standalone Python into the stage, with the packages of uv.lock in its site-packages. Returns its version."""
    source = _standalone_python(_python_request(root), work)
    target = os.path.join(stage, PYTHON_DIR)
    shutil.copytree(source, target, ignore=_pruner(source))
    python = os.path.join(target, 'python.exe')
    requirements = os.path.join(work, 'requirements.txt')
    _run(['uv', 'export', '--project', root, '--frozen', '--no-dev', '--no-hashes', '--no-emit-project',
          '--format', 'requirements.txt', '-o', requirements])
    site_packages = os.path.join(target, SITE_PACKAGES)
    _run(['uv', 'pip', 'install', '--python', python, '--target', site_packages, '--link-mode', 'copy', '--no-config',
          '-r', requirements])
    lock = os.path.join(site_packages, '.lock')          # uv's, of the install
    if os.path.exists(lock):
        os.remove(lock)
    return _run([python, '-c', 'import platform; print(platform.python_version())']).strip()


def _launcher(stage, number, work):
    """TIA Archive Compare.exe at the top of the stage: launcher.cs, compiled by Add-Type as a Windows program."""
    with open(os.path.join(HERE, 'launcher.cs'), encoding='utf-8') as f:
        source = f.read().replace('@VERSION@', number)
    cs = os.path.join(work, 'launcher.cs')
    with open(cs, 'w', encoding='utf-8') as f:
        f.write(source)
    script = ("$ErrorActionPreference = 'Stop'; Add-Type -TypeDefinition ([IO.File]::ReadAllText($env:LAUNCHER_CS)) "
              "-OutputAssembly $env:LAUNCHER_EXE -OutputType WindowsApplication "
              "-ReferencedAssemblies System.Windows.Forms")
    _run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
         env=dict(os.environ, LAUNCHER_CS=cs, LAUNCHER_EXE=os.path.join(stage, LAUNCHER)))


def _readme(stage, number, python_version):
    with open(os.path.join(HERE, 'README.txt'), encoding='utf-8') as f:
        text = f.read().replace('@VERSION@', number).replace('@PYTHON@', python_version)
    with open(os.path.join(stage, 'README.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(text)


def _zip(stage, zip_path):
    base = os.path.dirname(stage)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for folder, dirs, files in os.walk(stage):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(folder, name)
                z.write(path, os.path.relpath(path, base).replace(os.sep, '/'))


def build(out=None, tag=None):
    """Builds the zip and returns its path."""
    number = version(ROOT, tag)
    out = os.path.abspath(out or os.path.join(ROOT, 'dist'))
    name = package_name(number)
    zip_path = os.path.join(out, name + '.zip')
    files = package_files(_tracked(ROOT))
    for path in _changed(ROOT, files):
        print('Not committed, taken as it is: %s' % path)
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix='tia-compare-build-')
    try:
        stage = os.path.join(work, name)
        _copy_files(ROOT, files, stage)
        print('%d files of the repo' % len(files))
        python_version = _bundle_python(ROOT, stage, work)
        print('Python %s with the packages of uv.lock' % python_version)
        _launcher(stage, number, work)
        _readme(stage, number, python_version)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        _zip(stage, zip_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print('%s (%.0f MB)' % (zip_path, os.path.getsize(zip_path) / 1e6))
    return zip_path


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m TiaArchiveCompare.package.build', description=__doc__.splitlines()[2])
    p.add_argument('--out', help='where the zip goes (default: dist in the repo)')
    p.add_argument('--tag', help='the release tag, v<version>')
    p.add_argument('--no-check', action='store_true', help='skip the check of the zip')
    p.add_argument('--visible', action='store_true', help="the check's window on this desktop")
    a = p.parse_args(argv)
    try:
        zip_path = build(a.out, a.tag)
    except BuildError as e:
        print(e, file=sys.stderr)
        return 1
    if a.no_check:
        return 0
    from TiaArchiveCompare.package import check
    return check.check(zip_path, visible=a.visible)


if __name__ == '__main__':
    sys.exit(main())
