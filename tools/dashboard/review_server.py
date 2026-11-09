"""Serves the development dashboard on http://127.0.0.1:8770/ and takes the answers to review pages.

    pythonw review_server.py [--port 8770] [--root DIR]

pythonw runs it with no console; python keeps it in the terminal, where it says what stops it. Either way it has an icon in the Windows
notification area while it runs (tray.py): a left click opens the page, its right-click menu also stops it.
--root is the .scratch folder to read (default: the main working tree's, which its worktrees share). GET serves the files of
<root>\\reviews (the start page lists the pages and whether they are answered, the tickets below). A review page gets an answer
box under each question (.ask li) and a Send button, added when it is served (review_form.js). POST /answer/<page> writes
<root>\\reviews\\answers\\<page>.json ({title, at, answers: [{question, answer}], comment}); whoever asked watches that folder.
A ticket's page shows its open ## Question for the maintainer with an answer box; POST /answer-ticket ({ticket, question, answer})
writes the answer into the ticket's comments (board.with_answer) and a record of it to <root>\\reviews\\ticket-answers\\
<effort>-<ticket>.json ({ticket, at, who, answer}), which the coordinator's watch reports for any ticket.
GET /events pushes changes to the open pages (Server-Sent Events, dashboard.js). Only 127.0.0.1 is served and nothing leaves this
machine; another machine reaches it through tailscale serve.
"""
import argparse
import html
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import board
import live
import tray
from review_page import page_round, stem_of

SCRATCH = board.default_scratch()
ROOT = SCRATCH / 'reviews'
ANSWERS = ROOT / 'answers'
TITLE = 'Development dashboard'
FORM_SCRIPT = Path(__file__).with_name('review_form.js')

_lock = threading.Lock()
_ticket_lock = threading.Lock()     # one answer into a ticket at a time
_start = (None, None)     # (version, what the start page shows)


def version():
    """Changes when a page or an answer is added, rebuilt, answered or taken down."""
    files = sorted(list(ROOT.glob('*.html')) + list(ANSWERS.glob('*.json')))
    pages = '|'.join(f'{f.name}:{f.stat().st_mtime_ns}' for f in files)
    try:
        return pages + '|' + board.version(SCRATCH)
    except Exception:  # the questions stay usable without the tickets
        return pages


def plural(n, word):
    return f'{n} {word}' if n == 1 else f'{n} {word}s'


def summary_html(reviews, tickets):
    """The headline of the start page. tickets is None when the tickets could not be read."""
    named = [plural(n, w) for n, w in ((reviews, 'review'), (tickets or 0, 'ticket')) if n]
    if named:
        verb = 'waits' if reviews + (tickets or 0) == 1 else 'wait'
        line = f'{" and ".join(named)} {verb} for you.'
    else:
        line = 'Nothing waits for you.'
    note = '<small>The tickets could not be read, so this counts reviews only.</small>' if tickets is None else ''
    return f'<p class="summary{" you" if named else ""}">{line}{note}</p>'


class Questions(HTMLParser):
    """The questions of a page as the form reads them: the first node of each li inside an element of class ask."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.open, self.text = [], [], []
        self.ask_at = None      # how deep the element of class ask is
        self.node = None        # reading a question: 'first' until its first node shows, then 'text' or 'element'
        self.node_at = 0        # how deep that element is

    def finish(self):
        self.found.append(''.join(self.text).strip())
        self.text, self.node = [], None

    def handle_starttag(self, tag, attrs):
        if self.node == 'text':
            self.finish()
        elif self.node == 'first':
            self.node, self.node_at = 'element', len(self.open)
        if self.ask_at is None and 'ask' in (dict(attrs).get('class') or '').split():
            self.ask_at = len(self.open)
        if tag in self.VOID:
            if self.node == 'element' and self.node_at == len(self.open):
                self.finish()
            return
        self.open.append(tag)
        if tag == 'li' and self.ask_at is not None and self.node is None:
            self.node = 'first'

    def handle_endtag(self, tag):
        if tag not in self.open:
            return
        while self.open.pop() != tag:
            pass
        if self.node in ('first', 'text') or (self.node == 'element' and len(self.open) <= self.node_at):
            self.finish()
        if self.ask_at is not None and len(self.open) <= self.ask_at:
            self.ask_at = None

    def handle_data(self, data):
        if self.node == 'first':
            self.node = 'text'
        if self.node:
            self.text.append(data)


def page_questions(text):
    parser = Questions()
    parser.feed(text)
    parser.close()
    return parser.found


def answer_state(questions, stem):
    """(section of the start page, note) of a review page with these questions. It waits while its answers do not hold an answer
    to every question, so a page rebuilt with a new question waits again, and so does one sent with a box left blank. A page
    with no questions waits for nobody, and a blank send leaves it to read."""
    a = ANSWERS / (stem + '.json')
    if not a.exists():
        return ('waiting', plural(len(questions), 'question')) if questions else ('to_read', 'no questions')
    try:
        answer = json.loads(a.read_text(encoding='utf-8'))
        held = {x['question'].strip() for x in answer['answers'] if x['answer'].strip()}
        at = answer['at']
        if not questions and not answer.get('comment', '').strip():
            return 'to_read', 'no questions'
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 'unreadable', 'answer file not readable'
    left = [q for q in questions if q not in held]
    if left:
        return 'waiting', f'{plural(len(left), "question")} not answered'
    return 'answered', f'answered {at}'


def page_state(f):
    """(section of the start page, note) of a review page, the note saying so from its second round on: a title is often
    used again, and without it a new round looks like the old review coming back."""
    try:
        text = f.read_text(encoding='utf-8')
    except (OSError, ValueError):
        return 'unreadable', 'page not readable'
    where, note = answer_state(page_questions(text), f.stem)
    n = page_round(text)
    return where, f'round {n}, {note}' if n > 1 else note


def review_of(title):
    """(section of the start page, address) of the review page with this title, None when it is not up: what a ticket's
    Review page: line points at."""
    f = ROOT / (stem_of(title) + '.html')
    return (page_state(f)[0], '/' + urllib.parse.quote(f.name)) if f.is_file() else None


def reviews_html():
    """(html, how many pages wait for answers, how many are open). Pages taken down are in reviews\\done and not listed."""
    rows = {'waiting': [], 'to_read': [], 'answered': [], 'unreadable': []}
    for f in sorted(ROOT.glob('*.html'), key=lambda p: p.stat().st_mtime, reverse=True):
        where, note = page_state(f)
        rows[where].append(f'<div class="row"><span class="title"><a href="/{urllib.parse.quote(f.name)}">{html.escape(f.stem)}</a></span>'
                           f'<span class="state">{html.escape(note)}</span></div>')
    parts = ['<h2>Reviews</h2>']
    for where, mark, cls, name in (('waiting', board.MARKS['Waits for you'][0], 'you', 'Waiting for your answers'),
                                   ('to_read', board.READ_MARK, '', 'To read'),
                                   ('answered', board.RUNNING_MARK, 'dim', 'Answered, the agent is on it'),
                                   ('unreadable', board.MARKS['Not readable'][0], 'fail', 'Not readable')):
        if rows[where]:
            parts.append(board.section(mark, cls, name, rows[where]))
    if not any(rows.values()):
        parts.append('<p class="goal">No review pages are open.</p>')
    return ''.join(parts), len(rows['waiting']), sum(map(len, rows.values()))


def start_page():
    """What the start page shows, built again only when version() changes. One lock: herdr is asked once."""
    global _start
    with _lock:
        v = version()
        if v != _start[0]:
            reviews, waiting, pages = reviews_html()
            try:
                tickets, wait_tickets, topics = board.tickets_html(SCRATCH, review_of)
            except Exception as e:  # a fault there never takes the questions down
                tickets = f'<h2>Tickets</h2><p class="fail">The tickets could not be read: {html.escape(str(e))}</p>'
                wait_tickets = None
                topics = [{'id': 'tickets', 'name': 'Tickets', 'waiting': 0, 'open': 0, 'note': 'could not be read'}]
            total = waiting + (wait_tickets or 0)
            contents = board.contents_html([{'id': 'reviews', 'name': 'Reviews', 'waiting': waiting, 'open': pages, 'note': ''}] + topics)
            _start = (v, {'parts': {'summary': summary_html(waiting, wait_tickets), 'topics': contents, 'reviews': reviews, 'tickets': tickets},
                          'title': f'({total}) {TITLE}' if total else TITLE,
                          'updated': datetime.now().strftime('%H:%M:%S')})
        return _start[1]


FORM = '<script src="/review_form.js"></script><script>reviewForm(__STAMP__);</script>'


def with_assets(page):
    """The page with the stylesheet and script at the end of its head: after its own copy of the stylesheet, so a page built
    earlier takes the themes of today's, and after any doctype, which has to stay first."""
    end_of_head = re.search(r'</head>|<body', page, re.I)
    doctype = re.match(r'\s*<!doctype[^>]*>', page, re.I)
    at = end_of_head.start() if end_of_head else doctype.end() if doctype else 0
    return page[:at] + live.ASSET_TAGS + page[at:]


def page_name(name):
    """True when name is one file directly in the reviews folder, not a way out of it."""
    return bool(name) and '/' not in name and '\\' not in name and name not in ('.', '..')


class Handler(live.Handler):
    proxy_suffixes = ('.ts.net',)    # tailscale serve hands on the address it was asked for

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)
        if path == '/':
            return self.send_text(200, index(), 'text/html; charset=utf-8')
        if path == '/events':
            return self._events(urllib.parse.parse_qs(url.query))
        if path == '/review_form.js':
            return self.send_body(200, FORM_SCRIPT.read_bytes(), live.ASSETS['/dashboard.js'])
        if self.send_asset(path):
            return None
        if path.startswith('/doc/'):
            return self.send_text(*doc_page(path[5:]), 'text/html; charset=utf-8')
        if path.endswith('.html') and page_name(path[1:]):
            f = ROOT / path[1:]
            if f.is_file():
                form = FORM.replace('__STAMP__', json.dumps(live.stamp(f)))
                page = f.read_text(encoding='utf-8', errors='replace')
                page = with_assets(page)
                page = page.replace('</body>', form + '</body>') if '</body>' in page else page + form
                return self.send_text(200, page, 'text/html; charset=utf-8')
        return super().do_GET()

    def _events(self, query):
        if 'start' in query:
            return self.stream(start_page)
        if 'page' in query and page_name(query['page'][0]):
            f = ROOT / query['page'][0]
        elif 'doc' in query and doc_file(query['doc'][0]):
            f = doc_file(query['doc'][0])
        else:
            return self.send_text(404, 'Nothing to watch.', 'text/plain; charset=utf-8')
        return self.stream(lambda: {'stamp': live.stamp(f)})

    def do_POST(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        m = re.fullmatch(r'/answer/([^/\\]+)\.html', path)
        if not m and path != '/answer-ticket':
            return self.send_text(404, json.dumps({'ok': False, 'error': 'not found'}), 'application/json')
        # an answer goes straight to an agent: JSON only, which a form on another web site cannot send here
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.send_text(415, json.dumps({'ok': False, 'error': 'JSON only'}), 'application/json')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if not m:
                code, reply = answer_ticket(str(body.get('ticket', '')), str(body.get('question', '')), str(body.get('answer', '')))
                return self.send_text(code, json.dumps(reply), 'application/json')
            at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            out = {'page': m.group(1) + '.html', 'title': body.get('title', m.group(1)), 'at': at,
                   'answers': body.get('answers', []), 'comment': body.get('comment', '')}
            ANSWERS.mkdir(parents=True, exist_ok=True)
            tmp = ANSWERS / (m.group(1) + '.json.tmp')
            tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
            tmp.replace(ANSWERS / (m.group(1) + '.json'))
            return self.send_text(200, json.dumps({'ok': True, 'at': at}), 'application/json')
        except Exception as e:  # the page shows the error
            return self.send_text(500, json.dumps({'ok': False, 'error': str(e)}), 'application/json')


def index():
    """The start page. Each part carries its own text in data-html, so the first update changes nothing it need not."""
    b = start_page()
    part = lambda i: f'<div id="{i}" data-html="{html.escape(b["parts"][i], quote=True)}">{b["parts"][i]}</div>'
    return (live.head(b['title']) +
            f'<body><main class="board"><header class="top"><h1>{TITLE}</h1><span class="live" id="live"></span></header>'
            + part('summary') + '<nav class="topics" aria-label="Topics">' + part('topics') + '</nav>'
            + part('reviews') + part('tickets') + '</main><script>dashboardBoard();</script></body></html>')


def doc_file(rel):
    """The Markdown file rel names (from the repo), or None. It opens at any depth under docs/ and an effort with a map, whose
    Doc: lines use that. A folder with tickets and no map is no effort anyone chose to show: only its issues/ and the files
    directly in it, as such a folder can hold anything further down. The how-to comes from the repo of these tools, wherever
    --root points: the start page links it."""
    if rel == board.HOW_TO:
        own = board.HERE.parent.parent / board.HOW_TO
        return own if own.is_file() else None
    repo = SCRATCH.parent
    f = (repo / rel).resolve()
    if f.suffix != '.md' or not f.is_file():
        return None
    whole = [(repo / 'docs').resolve()] + [m.parent.resolve() for m in SCRATCH.glob('*/map.md')]
    top_only = [p.resolve() for folder in board.folders_without_a_map(SCRATCH) for p in (folder, folder / 'issues')]
    return f if any(a in f.parents for a in whole) or f.parent in top_only else None


def ticket_file(rel):
    """The ticket file rel names: a document of the dashboard directly in the issues folder of a folder of .scratch. Else None."""
    f = doc_file(rel)
    return f if f and f.parent.name == 'issues' and f.parents[2] == SCRATCH.resolve() else None


def who_answers():
    """The name the answers carry: git's user.name in the repo of SCRATCH, else a word for the person at the dashboard."""
    try:
        out = subprocess.run(['git', '-C', str(SCRATCH.parent), 'config', 'user.name'], capture_output=True, text=True,
                             timeout=10, env=board.git_env(), creationflags=board.NO_WINDOW)
        return out.stdout.strip() or 'Dashboard user'
    except (OSError, subprocess.SubprocessError):
        return 'Dashboard user'


def ticket_text(raw):
    """A ticket's bytes as the text its page shows: no byte order mark, every line end a \\n."""
    return raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')


REPLACE_TRIES = 20      # times 0.05 s: an editor or a reader may hold the ticket open for a moment


def answer_ticket(rel, asked, answer):
    """Writes an answer given on a ticket's page into the ticket, then its record for the watch: (status, reply). asked is the
    question the page showed: one changed since then is not answered by it. The ticket keeps its byte order mark and the line
    end of its first line, \\r\\n, \\n or a lone \\r, which every line then has; an edit of the ticket made while the answer is
    written in is never overwritten: the answer is refused and can be sent again."""
    f = ticket_file(rel)
    if not f:
        return 404, {'ok': False, 'error': 'not a ticket'}
    who = who_answers()
    with _ticket_lock:
        raw = f.read_bytes()
        text = ticket_text(raw)
        if board.question(text) != asked.strip():
            return 409, {'ok': False, 'error': 'the ticket\'s question changed since this page was opened: copy your answer and reload'}
        if not board.waits_for_answer(f, f.parents[2]):
            return 409, {'ok': False, 'error': 'the ticket does not wait for your answer now: reload'}
        at = datetime.now().strftime('%Y-%m-%d %H:%M')
        try:
            text = board.with_answer(text, answer, who, at)
        except ValueError as e:
            return 400, {'ok': False, 'error': str(e)}
        bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
        end = re.search(rb'\r\n|\r|\n', raw)
        tmp = f.with_name(f.name + '.tmp')       # not .md: no reader takes it for a ticket
        try:
            tmp.write_bytes(bom + text.replace('\n', end.group().decode() if end else '\n').encode('utf-8'))
            for _ in range(REPLACE_TRIES):
                if f.read_bytes() != raw:
                    return 409, {'ok': False, 'error': 'the ticket changed while your answer was written in: send it again'}
                try:
                    tmp.replace(f)
                    break
                except PermissionError:     # Windows: open in another program
                    time.sleep(0.05)
            else:
                return 503, {'ok': False, 'error': 'the ticket is held open by another program: send again in a moment'}
        finally:
            tmp.unlink(missing_ok=True)
    reply = {'ok': True, 'at': at}
    try:
        record = ROOT / 'ticket-answers' / f'{f.parents[1].name}-{f.stem}.json'
        record.parent.mkdir(parents=True, exist_ok=True)
        part = record.with_name(record.name + '.tmp')
        part.write_text(json.dumps({'ticket': rel, 'at': at, 'who': who, 'answer': answer.strip()}, ensure_ascii=False), encoding='utf-8')
        part.replace(record)
    except OSError as e:        # the answer is in the ticket: only the watch's word on it is missing
        reply['note'] = f'the coordinator\'s watch was not told ({e}): tell them'
    return 200, reply


def ticket_panel(f, rel, text, safe):
    """(html above a ticket, script that runs it) of a ticket's page: its open question with an answer box, its review page
    when it is up, and for an open grilling or prototype that waits for you, that it waits in its session. ('', '') for a ticket
    that asks nothing and has none."""
    parts, script = [], ''
    review = board.read_ticket(f, f.parents[2])['review']      # the head, as the start page reads it
    page = review and review_of(review)
    if page:
        where, url = page
        says = 'This ticket waits for your answers on its review page' if where == 'waiting' else 'Its review page'
        parts.append(f'<p class="ticket-page{" you" if where == "waiting" else ""}">{says}: '
                     f'<a href="{html.escape(url)}">{html.escape(review)}</a></p>')
    where = board.placed(f, f.parents[2])
    if where and where[0] == 'Waits for you' and where[1] in board.HUMAN_TYPES:    # talked through with its agent, not answered here
        session = board.open_session(f, f.parents[2])
        parts.append(f'<p class="ticket-page you">This {html.escape(where[1])} waits for you in its session'
                     f'{", " + html.escape(session) if session else ""}: answer it there.</p>')
    asked = board.question(text) if where == ('Waits for you', 'question') else ''
    if asked:
        parts.append('<section class="ask" id="ticket-ask"><h2>Waits for your answer</h2>'
                     f'<div class="question"><pre>{html.escape(asked)}</pre></div></section>')
        script = f'ticketForm({safe(rel)}, {safe(asked)}, {safe(live.stamp(f))});'
    return ''.join(parts), script


def doc_page(rel):
    """A Markdown document as a page: (status, html). A ticket's page also shows what it asks you, with an answer box."""
    f = doc_file(rel)
    if not f:
        return 404, 'Not a document of docs/ or of an effort under .scratch/.'
    text = ticket_text(f.read_bytes())
    m = re.match(r'---\n.*?\n---\n', text, re.S)
    body = text[m.end():] if m else text
    safe = lambda v: json.dumps(v).replace('<', chr(92) + 'u003c')
    panel, form_script = ticket_panel(f, rel, text, safe) if ticket_file(rel) else ('', '')
    live_part = form_script or f'dashboardDoc({safe(rel)}, {safe(live.stamp(f))});'
    return 200, (live.head(f.stem) +
                 '<body><main><div class="top"><a href="/">All reviews and tickets</a>'
                 '<span class="live" id="live"></span></div>'
                 f'<p class="goal">{html.escape(rel)}</p>{panel}<div id="doc"><pre>{html.escape(body)}</pre></div></main>'
                 '<script src="/vendor/marked.min.js"></script>' + ('<script src="/review_form.js"></script>' if form_script else '') +
                 f'<script>var src = {safe(body)};'
                 'if (window.marked) document.getElementById("doc").innerHTML = marked.parse(src);'
                 f'{live_part}</script></body></html>')


def main():
    global SCRATCH, ROOT, ANSWERS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8770)
    ap.add_argument('--root', type=Path, default=SCRATCH, help='the .scratch folder to read')
    a = ap.parse_args()
    SCRATCH = a.root.resolve()
    ROOT, ANSWERS = SCRATCH / 'reviews', SCRATCH / 'reviews' / 'answers'
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        server = live.Server(('127.0.0.1', a.port), Handler)
    except OSError as e:
        sys.exit(f'Port {a.port} is taken ({e}): another dashboard runs there, or use --port.')
    print(f'http://127.0.0.1:{a.port}/ on {SCRATCH}', flush=True)
    tray.serve(server, tray.DEVELOPMENT_NAME, f'http://127.0.0.1:{a.port}/', tray.DEVELOPMENT_ICON, tray.DEVELOPMENT_ID)


if __name__ == '__main__':
    sys.exit(tray.guarded(TITLE, main))
