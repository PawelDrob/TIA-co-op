"""Builds one page of things for a person to look at and puts it on the dashboard. It opens no browser: the start page lists it.

    python review_page.py --title "07 audit" [--note TEXT ...] [--ask TEXT ...] ITEM [ITEM ...]

The title names who the review comes from, for example the agent's tab label; the browser shows it as the tab title. ITEM is a
file path, optionally followed by "::" and a caption. Images are embedded (the page stands on its own); HTML files are shown in a
frame and linked. --note adds a line of context, --ask a question. The page is written to <root>\\reviews\\<title>.html and served
by review_server.py (started when not running), which adds an answer box per question; the answers land in
<root>\\reviews\\answers\\<title>.json. The page's address is printed. --no-open only writes the page: no server. Under a title used before, the page says which
round it is, there and on the start page: a new one starts after --done, or when a page is built again after answers came in.

    python review_page.py --open "07 audit"     opens an existing page in a browser
    python review_page.py --done "07 audit"     takes a page down: page, files and answers go to <root>\\reviews\\done\\<title>

--root is the .scratch folder (default: the main working tree's, which its worktrees share), --port the server's. --open uses the
default browser, or the one the environment variable DASHBOARD_BROWSER names by its path.
"""
import argparse
import base64
import html
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from board import NO_WINDOW, default_scratch

PORT = 8770
SERVER = Path(__file__).with_name('review_server.py')
CSS = Path(__file__).with_name('dashboard.css').read_text(encoding='utf-8')    # inline: the page stands on its own


def page_round(text):
    """The round a page's text says it is; a page from before rounds has no mark and counts as 1."""
    m = re.search(r'<meta name="review-round" content="(\d+)">', text)
    return int(m.group(1)) if m else 1


def answers_stamp(stem, reviews):
    """What tells one sending of a page's answers from another, '' with none. The page keeps it from when it was built: two files
    written one after the other often get the same time here, so comparing the page's time with the answers' does not work."""
    answers = reviews / 'answers' / (stem + '.json')
    return str(answers.stat().st_mtime_ns) if answers.is_file() else ''


def next_round(stem, reviews):
    """The round of a page built now under this name. A rebuild stays in its round until answers come in, as it may only fix a
    word. Then, or after --done, the next one starts."""
    read = lambda f: f.read_text(encoding='utf-8', errors='replace')
    page = reviews / (stem + '.html')
    if page.is_file():
        text = read(page)
        seen = re.search(r'<meta name="review-answers" content="(\d*)">', text)
        stamp = answers_stamp(stem, reviews)
        return page_round(text) + (1 if stamp and stamp != (seen.group(1) if seen else '') else 0)
    taken_down = [page_round(read(f)) for f in (reviews / 'done').glob(f'*/{stem}.html')]
    return 1 + max([len(taken_down)] + taken_down)


def stem_of(title):
    """The page's file name without .html."""
    return re.sub(r'[^\w .-]+', '_', title.removesuffix('.html')).strip()


def item_html(spec, page_stem, reviews):
    path, _, caption = spec.partition('::')
    path = path.strip().strip('"')
    m = re.match(r'^[/\\]([a-zA-Z])[/\\](.*)$', path)    # Git Bash form /c/Users/... (a Windows path never starts so)
    if m:
        path = m.group(1).upper() + ':/' + m.group(2)
    p = Path(path)
    cap = html.escape(caption.strip() or p.name)
    src = html.escape(str(p))
    if not p.exists():
        return f'<section><figure><figcaption>{cap}<small>missing: {src}</small></figcaption></figure></section>'
    kind = mimetypes.guess_type(p.name)[0] or ''
    if kind.startswith('image/'):
        data = base64.b64encode(p.read_bytes()).decode('ascii')
        body = f'<img src="data:{kind};base64,{data}" alt="{cap}">'
    else:
        # copied next to the page and linked relatively: a file:// address does not load in a page served by
        # review_server.py, a relative one works served and opened from disk alike
        dest = reviews / 'files' / page_stem / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        url = html.escape('files/' + urllib.parse.quote(page_stem) + '/' + urllib.parse.quote(p.name))
        if kind == 'text/html':
            body = f'<p><a href="{url}" target="_blank">Open on its own</a></p><iframe src="{url}"></iframe>'
        else:
            body = f'<p><a href="{url}" target="_blank">{cap}</a></p>'
    return f'<section><figure><figcaption>{cap}<small>{src}</small></figcaption>{body}</figure></section>'


def build(a, reviews):
    """Writes the page and returns its path."""
    title = html.escape(a.title)
    stem = stem_of(a.title)
    round_no = next_round(stem, reviews)
    parts = [f'<h1>{title}</h1><div class="when">{datetime.now():%Y-%m-%d %H:%M}{f", round {round_no}" if round_no > 1 else ""}</div>']
    if a.ask:
        parts.append('<section class="ask"><h2>Questions</h2><ul>'
                     + ''.join(f'<li><span>{html.escape(q)}</span></li>' for q in a.ask) + '</ul></section>')
    if a.note:
        parts.append('<section><h2>Notes</h2><ul>' + ''.join(f'<li>{html.escape(n)}</li>' for n in a.note)
                     + '</ul></section>')
    parts += [item_html(s, stem, reviews) for s in a.items]
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="review-round" content="{round_no}">'
            f'<meta name="review-answers" content="{answers_stamp(stem, reviews)}">'
            f'<title>{title}</title><style>{CSS}</style></head><body><main class="review">{"".join(parts)}</main></body></html>')
    reviews.mkdir(parents=True, exist_ok=True)
    out = reviews / (stem + '.html')
    out.write_text(page, encoding='utf-8')
    return out


def take_down(title, reviews):
    """Moves page, files and answers to done\\<title> (done\\<title> 2 when that is taken), in the folders they had, so the
    page's links still work there. The page goes last: until then the command can be run again."""
    stem = stem_of(title)
    page = reviews / (stem + '.html')
    if not page.is_file():
        print(f'No review page named {title} in {reviews}', file=sys.stderr)
        return 1
    target = reviews / 'done' / stem
    n = 1
    while target.exists():
        n += 1
        target = reviews / 'done' / f'{stem} {n}'
    for f in (reviews / 'answers' / (stem + '.json'), reviews / 'files' / stem, page):
        if f.exists():
            dest = target / f.relative_to(reviews)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
    print(target)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--title', help='who the review comes from; also the name of the page')
    ap.add_argument('--note', action='append', default=[], help='a line of context')
    ap.add_argument('--ask', action='append', default=[], help='a question for the person reading')
    ap.add_argument('--no-open', action='store_true', help='only write the page: no server')
    ap.add_argument('--open', metavar='TITLE', help='open an existing page in a browser')
    ap.add_argument('--done', metavar='TITLE', help='take a page down')
    ap.add_argument('--root', type=Path, help='the .scratch folder')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('items', nargs='*')
    a = ap.parse_args(argv)
    scratch = (a.root or default_scratch()).resolve()
    reviews = scratch / 'reviews'
    if a.done:
        return take_down(a.done, reviews)
    if a.open:
        return open_page(stem_of(a.open) + '.html', scratch, a.port)
    if not a.title:
        ap.error('--title is required')
    out = build(a, reviews)
    print(out)
    if a.no_open:
        return 0
    if not ensure_server(scratch, a.port):
        return 1
    print(page_url(out.name, a.port))
    return 0


def page_url(name, port):
    return f'http://127.0.0.1:{port}/{urllib.parse.quote(name)}'


def ensure_server(scratch, port):
    """True when review_server.py runs on the port, started here when it did not; says so when it does not come up."""
    if server_running(port) or start_server(scratch, port):
        return True
    print(f'The server did not start on port {port}. To see why, run: "{sys.executable}" -X utf8 "{SERVER}" '
          f'--port {port} --root "{scratch}"', file=sys.stderr)
    return False


def open_page(name, scratch, port):
    """Opens the page in a browser, the only thing here that does."""
    if not ensure_server(scratch, port):
        return 1
    url = page_url(name, port)
    if not browse(url):
        print('no browser could be started', file=sys.stderr)
    print(url)
    return 0


def browse(url):
    """Opens url in DASHBOARD_BROWSER or the default browser; False when none could be started."""
    browser = os.environ.get('DASHBOARD_BROWSER')
    if browser:
        subprocess.Popen([browser, url], creationflags=NO_WINDOW)
        return True
    return webbrowser.open(url)


def start_server(scratch, port):
    """Starts the server in the background, on its own, so it outlives this command. False when it does not come up."""
    # Not DETACHED_PROCESS: the python.exe of a venv is a launcher, and a child it starts with no console gets a window of its own.
    # pythonw as by hand: Windows keeps the icon's place on the taskbar per program, with python.exe a place of its own.
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    server = subprocess.Popen([windowless_python(), '-X', 'utf8', str(SERVER), '--port', str(port), '--root', str(scratch)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **flags)
    for _ in range(150):
        if server_running(port):
            return True
        if server.poll() is not None:     # it ended; another one may have taken the port just before it
            return server_running(port)
        time.sleep(0.1)
    return False


def windowless_python():
    """pythonw.exe beside this python, where there is one."""
    beside = Path(sys.executable).with_name('pythonw.exe')
    return str(beside) if beside.exists() else sys.executable


def server_running(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


if __name__ == '__main__':
    sys.exit(main())
