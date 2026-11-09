"""The tickets as a part of the start page (review_server.py imports this).

An effort is any folder of .scratch with a map.md (wayfinder's map), or with tickets and no map: those share the topic No map.
What is read is the map's Destination and the issues\\ folder: title from the first # line, state from Status: and Type:, what it waits for from Blocked by:, a link from an optional Doc: line,
whether it asks you something from an open ## Question for the maintainer section or a review page named by a Review page: line. herdr, when it is there, adds what is running now, which is live and stored nowhere. A value this cannot read gets its own section,
never a silent place in another one.
"""
import html
import json
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOW_TO = 'docs/user/development-dashboard.md'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)     # a server with no console: a program it starts would open a window
AGENTS_SECONDS = 15
_agents = (0.0, {})

CLOSED = ('done', 'resolved', 'wontfix')
# Status of an open ticket that asks you nothing -> section; display order is SECTIONS. A question, a review page waiting
# for answers, or an open ticket of HUMAN_TYPES puts a ticket under Waits for you, whatever its status.
OPEN = {
    'in-review': 'With the coordinator', 'needs-info': 'With the coordinator',
    'ready-for-human': 'Yours to start',
    'claimed': 'Being worked on',
    'ready-for-agent': 'Ready for an agent',
    'needs-triage': 'Needs triage',
    'open': 'Ready for an agent',
}
# Wayfinder tickets a person has to be in the loop for, once nothing blocks them: their body is a question for that person.
HUMAN_TYPES = ('grilling', 'prototype')
SECTIONS = ['Waits for you', 'Being worked on', 'With the coordinator', 'Yours to start', 'Ready for an agent', 'Needs triage',
            'Blocked', 'Not readable']
# A question for the maintainer, open: answering adds ', answered <when>'. Not wayfinder's ## Question, which every one of its
# tickets carries, for whoever works on it.
QUESTION_HEADING = '## Question for the maintainer'
QUESTION = re.compile(r'(?m)^' + QUESTION_HEADING + r'[ \t]*$')
COMMENTS = re.compile(r'(?m)^## Comments[ \t]*$')
SECTION = re.compile(r'(?m)^## ')
FENCE = re.compile(r'(?m)^ {0,3}(`{3,}|~{3,})(.*)$')

# Section -> (mark, class): the status standard, written down in dashboard.css.
MARKS = {
    'Waits for you': ('●', 'you'), 'With the coordinator': ('…', ''), 'Yours to start': ('◇', ''),
    'Ready for an agent': ('○', ''), 'Needs triage': ('?', ''),
    'Blocked': ('×', 'dim'), 'Not readable': ('!', 'fail'),
}
RUNNING_MARK, CLOSED_MARK, READ_MARK, POSTPONED_MARK = '▸', '✓', '–', '‖'


# Every name git reads a repo from, as git rev-parse --local-env-vars lists them (a test holds this list to git's).
# A parent's: git prefers them to -C
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')


def default_scratch(start=HERE):
    """The .scratch of the main working tree, which every worktree of the repo shares. Outside git: of the folder two
    levels above start, where this repo holds its tools."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
    try:
        out = subprocess.run(['git', '-C', str(start), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                             capture_output=True, text=True, timeout=10, env=env, creationflags=NO_WINDOW)
        if out.returncode == 0:
            return Path(out.stdout.strip()).parent / '.scratch'
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(start).parent.parent / '.scratch'


def plain(line):
    """A line without the bold to-tickets writes (**Status:** value)."""
    return line.rstrip().replace('**', '')


def code_blocks(text):
    """(start, end) of each fenced code block of text, as CommonMark closes one: with a fence of its own character, at least as
    long, with nothing after it. A block left open runs to the end of the text."""
    blocks, opened = [], None
    for m in FENCE.finditer(text):
        mark, rest = m.groups()
        if opened is None:
            if not (mark[0] == '`' and '`' in rest):         # a backtick fence's info string holds no backtick
                opened = (m.start(), mark)
        elif mark[0] == opened[1][0] and len(mark) >= len(opened[1]) and not rest.strip():
            blocks.append((opened[0], m.end()))
            opened = None
    return blocks + ([(opened[0], len(text))] if opened else [])


def heading(pattern, text, start=0):
    """The first match of pattern from start that is not in a code block, which only shows a heading; None."""
    blocks = code_blocks(text)
    return next((m for m in pattern.finditer(text, start) if not any(a <= m.start() < b for a, b in blocks)), None)


def section_end(text, start):
    """Where the section that runs on at start ends: at the next heading of its level, or at the end of the text."""
    end = heading(SECTION, text, start)
    return end.start() if end else len(text)


def question(text):
    """The open question for the maintainer of a ticket's text, '' when it asks none: what stands under its first heading."""
    m = heading(QUESTION, text)
    return text[m.end():section_end(text, m.end())].strip() if m else ''


def with_answer(text, answer, who, at):
    """A ticket's text with its open question answered: the answer as the newest entry under ## Comments, in the person's
    words, saying who and when, and the question's heading saying when it was answered. Lines of the answer are indented
    into the entry, so none of them starts a section; an answer that opens with a code fence starts on a line of its own, so all
    its fences stay alike, and a code block it leaves open is closed in the entry, so the rest of the ticket stays text. Control
    characters are left out, which a watch would report. A ValueError when the ticket asks nothing or the answer is blank."""
    m = heading(QUESTION, text)
    if not m:
        raise ValueError('the ticket asks no question')
    answer = re.sub('[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', answer.replace('\r\n', '\n').replace('\t', '    ')).strip()
    if not answer:
        raise ValueError('the answer is blank')
    lines = [line.rstrip() for line in answer.split('\n')]
    first = '' if FENCE.match(lines[0]) else lines.pop(0)
    entry = '\n'.join([f'- {who}, {at}, answer on the dashboard:' + (f' {first}' if first else '')]
                      + ['  ' + line if line else '' for line in lines])
    blocks = code_blocks(entry + '\n')
    if blocks and blocks[-1][1] == len(entry) + 1:          # left open: it runs to the end
        entry += '\n  ' + FENCE.match(entry, blocks[-1][0]).group(1)
    text = text[:m.start()] + f'{QUESTION_HEADING}, answered {at}' + text[m.end():]
    comments = heading(COMMENTS, text)
    if not comments:
        return text.rstrip('\n') + '\n\n## Comments\n\n' + entry + '\n'
    end = section_end(text, comments.end())
    body = text[comments.end():end].rstrip('\n') or '\n'
    return text[:comments.end()] + body + '\n' + entry + '\n' + ('\n' if end < len(text) else '') + text[end:]


def read_ticket(path, scratch):
    """A ticket file as {num, title, status, blocked, doc, type, review, asks, file}; a field it does not have is ''. The lines
    are read from the head, the first 16 lines; the question from anywhere."""
    num = path.name.split('-')[0]
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    t = {'num': num, 'title': '', 'status': '', 'blocked': None, 'doc': '', 'type': '', 'review': '', 'asks': bool(question(text)),
         'file': path.relative_to(scratch.parent).as_posix()}
    for line in text.splitlines()[:16]:
        line = plain(line)
        if not t['type'] and line.startswith('Type:'):
            t['type'] = line[5:].strip()
        elif not t['title'] and line.startswith('# '):
            t['title'] = re.sub(r'^#\s*' + re.escape(num) + r'\b[\s:.-]*', '', line).lstrip('# ')
        elif not t['status'] and line.startswith('Status:'):
            t['status'] = line[7:].strip()
        elif t['blocked'] is None and line.startswith('Blocked by:'):
            t['blocked'] = line[11:].strip()
        elif not t['doc'] and line.startswith('Doc:'):
            t['doc'] = line[4:].strip()
        elif not t['review'] and line.startswith('Review page:'):
            t['review'] = line[12:].strip()
    return t


def tickets(effort_folder, scratch):
    """Every ticket of an effort, in file order. Two files can hold one number: both are here."""
    return [read_ticket(p, scratch) for p in sorted((effort_folder / 'issues').glob('*.md'))]


def by_number(all_tickets):
    numbers = {}
    for t in all_tickets:
        numbers.setdefault(t['num'], []).append(t)
    return numbers


def blockers(text):
    """The ticket ids in a Blocked by value: None when it is not readable, [] for none."""
    if text is None or not text:
        return None
    if re.fullmatch(r'none( \(can start immediately\))?', text, re.I):     # the second as to-tickets writes it; more could name a blocker
        return []
    ids = [p.strip() for p in text.split(',')]
    return ids if all(re.fullmatch(r'([a-z0-9-]+/)?\d+', i) for i in ids) else None


def is_closed(ident, numbers, scratch):
    """A blocker is satisfied when every ticket with its number is closed; a ticket that cannot be found is not."""
    if '/' in ident:
        effort, num = ident.split('/')
        found = [read_ticket(p, scratch) for p in (scratch / effort / 'issues').glob(num + '-*.md')]
    else:
        found = numbers.get(ident, [])
    return bool(found) and all(t['status'] in CLOSED for t in found)


def placed(path, scratch):
    """(section, note) of the ticket at path, as the start page places it; None in a postponed effort, which places nothing."""
    folder = path.parent.parent
    if any(e['folder'] == folder and e['postponed'] for e in efforts(scratch)):
        return None
    all_tickets = tickets(folder, scratch)
    t = next((t for t in all_tickets if t['file'] == path.relative_to(scratch.parent).as_posix()), None)
    return place(t, by_number(all_tickets), scratch) if t else None


def waits_for_answer(path, scratch):
    """True when the ticket at path waits for an answer to its question: the start page lists it under Waits for you for it.
    Not when it is blocked, closed, not readable or in a postponed effort."""
    return placed(path, scratch) == ('Waits for you', 'question')


def open_session(path, scratch):
    """The name of the herdr session open on the ticket at path, '' when herdr knows none: <prefix><num>, else its audit."""
    folder = path.parent.parent
    prefix = next((e['prefix'] for e in efforts(scratch) if e['folder'] == folder), folder.name)
    num, seen = path.name.split('-')[0], agents()
    return next((name for name in (prefix + num, 'audit' + prefix + num) if name in seen), '')


def place(t, numbers, scratch):
    """(section, note) of an open or closed ticket; section None means closed. numbers is by_number of its effort. t['page'] is
    the state of its review page as the server reads it ('waiting', 'answered', ...), None when there is none."""
    if t['status'] in CLOSED:
        return None, '' if t['status'] == 'done' else t['status']
    ids = blockers(t['blocked'])
    if t['status'] not in OPEN:
        return 'Not readable', 'Status: ' + (t['status'] or 'missing')
    if ids is None:
        return 'Not readable', 'Blocked by: ' + (t['blocked'] + ' (write ticket numbers)' if t['blocked'] else 'missing')
    if len(numbers[t['num']]) > 1:            # nothing can say which of them a Blocked by means
        return 'Not readable', 'number %s is on %d tickets' % (t['num'], len(numbers[t['num']]))
    waiting = [i for i in ids if not is_closed(i, numbers, scratch)]
    if waiting:                # a blocked ticket asks nothing: its answer could change once the blocker is done
        return 'Blocked', 'waits for ' + ', '.join(waiting)
    if t['asks']:
        return 'Waits for you', 'question'
    if t.get('page') == 'waiting':
        return 'Waits for you', 'review page waits'
    if t['status'] == 'open' and t['type'] in HUMAN_TYPES:
        return 'Waits for you', t['type']
    return OPEN[t['status']], t['status'] if t['status'] != 'claimed' else ''


def efforts(scratch):
    """Every effort under scratch, postponed ones last, each as {folder, heading, goal, postponed, prefix}."""
    found = []
    for m in scratch.glob('*/map.md'):
        text = m.read_text(encoding='utf-8', errors='replace')
        goal = re.search(r'(?ms)^## Destination\s*\n(.*?)(?=^## |\Z)', text)
        notes = re.search(r'(?ms)^## Notes\s*\n(.*?)(?=^## |\Z)', text)
        sessions = re.search(r'(?m)^Sessions:\s*(\S+)', text.replace('**', ''))
        name = m.parent.name.replace('-', ' ').capitalize()
        found.append({
            'folder': m.parent,
            'name': name,
            'heading': name + ' tickets',
            'goal': ' '.join(goal.group(1).split()) if goal else '',
            # issue tracker: "a postponed effort is excluded from selection by its map Notes"
            'postponed': bool(notes and re.search(r'(?mi)^\W*(this effort (has been |is )?)?postponed\b', notes.group(1))),
            'prefix': sessions.group(1) if sessions else m.parent.name,
        })
    return sorted(found, key=lambda e: (e['postponed'], e['folder'].name))


def folders_without_a_map(scratch):
    """The folders of scratch with tickets in issues\\ and no map.md."""
    return sorted(p.parent for p in scratch.glob('*/issues') if not (p.parent / 'map.md').exists() and any(p.glob('*.md')))


def agents():
    """Names and states of the herdr agents, asked at most every AGENTS_SECONDS. Without herdr: none."""
    global _agents
    if time.time() - _agents[0] < AGENTS_SECONDS:
        return _agents[1]
    try:
        out = subprocess.run(['herdr', 'agent', 'list'], capture_output=True, text=True, encoding='utf-8', timeout=10,
                             creationflags=NO_WINDOW).stdout
        seen = {a.get('name') or '': a['agent_status'] for a in json.loads(out)['result']['agents']}
    except Exception:
        seen = _agents[1]
    _agents = (time.time(), seen)
    return seen


def session_state(prefix, num, seen):
    """What a session of this ticket is doing, '' when none is open. Sessions are named <prefix><num>, audit<prefix><num>."""
    if seen.get('audit' + prefix + num) == 'working':
        return 'audit running'
    if seen.get(prefix + num) == 'working':
        return 'session working'
    if 'audit' + prefix + num in seen or prefix + num in seen:
        return 'session open'
    return ''


def stays_with_session(where, state):
    """True when a session on the ticket does not make it Running now: a person is needed, as it is not readable or asks
    something, or a session is only open on what is with the coordinator. While an agent works on that, an audit mostly, it runs."""
    return where in ('Not readable', 'Waits for you') or (where == 'With the coordinator' and state == 'session open')


def doc_link(rel):
    return '/doc/' + html.escape(urllib.parse.quote(rel.replace(chr(92), '/')))


def row(t, title, state=''):
    """One ticket: the title opens the ticket's file; an optional Doc: line and a review page that is up get small links."""
    s = '<span class="state">%s</span>' % html.escape(state) if state else ''
    d = '<a class="doc" href="%s">doc</a>' % doc_link(t['doc']) if t['doc'] else ''
    if t.get('page_url'):
        d += '<a class="doc" href="%s">review page</a>' % html.escape(t['page_url'])
    return ('<div class="row"><span class="id">%s</span><span class="title"><a href="%s">%s</a>%s</span>%s</div>'
            % (html.escape(t['num']), doc_link(t['file']), html.escape(title), d, s))


def section(mark, cls, name, rows):
    return ('<section class="status %s"><h3>%s %s (%d)</h3>%s</section>'
            % (cls, mark, html.escape(name), len(rows), ''.join(rows)))


def tickets_html(scratch, pages=None):
    """(html, how many tickets ask you something not on a review page, an entry per topic for contents_html): a ticket that
    waits only for its review page counts once, with the reviews, in the headline. The order is the page's: efforts, then
    No map, then postponed efforts: what counts comes before what does not. pages(title) is (state, address) of the review
    page with that title, None when it is not up; without pages, no review page is known."""
    found = efforts(scratch)
    pages = pages or (lambda title: None)
    topics = [effort_topic(e, scratch, pages) for e in found if not e['postponed']]
    loose = no_map_topic(scratch, pages)
    if loose:
        topics.append(loose)
    topics += [postponed_topic(e, scratch) for e in found if e['postponed']]
    if not topics:
        return ('<h2>Tickets</h2><p class="goal">No tickets yet. Tickets in .scratch/&lt;effort&gt;/issues/ show here: under the '
                'name of the effort with a map.md beside them, under No map without one. <a href="/doc/%s">'
                'How to use this dashboard</a></p>' % HOW_TO), 0, []
    return ''.join(t['html'] for t in topics), sum(t['in_headline'] for t in topics), [
        {k: t[k] for k in ('id', 'name', 'waiting', 'open', 'note')} for t in topics]


def contents_html(entries):
    """The list of topics: what each is called, what waits in it, how many are open, and a jump to it."""
    items = []
    for e in entries:
        waits = '<span class="you">%s %d</span>' % (MARKS['Waits for you'][0], e['waiting']) if e['waiting'] else ''
        counts = ', '.join(filter(None, (e['note'], '%d open' % e['open'] if e['open'] or not e['note'] else '')))
        items.append('<li><a href="#%s"><span class="name">%s</span> %s <span class="open">%s</span></a></li>'
                     % (html.escape(urllib.parse.quote(e['id'])), html.escape(e['name']), waits, html.escape(counts)))
    return '<ul>%s</ul>' % ''.join(items)


def closed_html(folder, rows):
    """The folded list of closed tickets. Its id is what keeps it open over a live update (dashboardBoard): one per folder."""
    if not rows:
        return ''
    return ('<details id="%s"><summary>%s Closed (%d)</summary>%s</details>'
            % (html.escape('closed-' + folder.name), CLOSED_MARK, len(rows), ''.join(rows)))


def effort_sections(folder, prefix, scratch, pages):
    """(html, how many tickets wait for you, how many of them the headline counts, how many are open) of one effort's tickets,
    by section. The headline leaves out a ticket that waits only for its review page: that page counts there."""
    all_tickets = tickets(folder, scratch)
    numbers = by_number(all_tickets)
    seen = agents()
    groups = {s: [] for s in SECTIONS}
    running, done = [], []
    in_headline = 0
    for t in all_tickets:
        t['page'], t['page_url'] = (t['review'] and pages(t['review'])) or (None, '')
        where, note = place(t, numbers, scratch)
        in_headline += where == 'Waits for you' and (t['asks'] or t['page'] != 'waiting')
        title = t['title'] or t['num']
        state = session_state(prefix, t['num'], seen)
        if where is None:
            done.append(row(t, title, note))
        elif state and stays_with_session(where, state):
            groups[where].append(row(t, title, f'{note}, {state}'))
        elif state:
            running.append(row(t, title, state))
        else:
            groups[where].append(row(t, title, note))
    parts = ['<p class="goal">No tickets yet.</p>'] if not all_tickets else []
    for s in SECTIONS:
        if s == 'Being worked on':
            if running:
                parts.append(section(RUNNING_MARK, 'run', 'Running now', running))
        if groups[s]:
            parts.append(section(*MARKS.get(s, (RUNNING_MARK, 'run')), s, groups[s]))
    parts.append(closed_html(folder, done))
    return ''.join(parts), len(groups['Waits for you']), in_headline, len(all_tickets) - len(done)


def effort_topic(effort, scratch, pages):
    body, waiting, in_headline, still_open = effort_sections(effort['folder'], effort['prefix'], scratch, pages)
    ident = 'effort-' + effort['folder'].name
    goal = '<p class="goal">%s</p>' % html.escape(effort['goal']) if effort['goal'] else ''
    return {'id': ident, 'name': effort['name'], 'waiting': waiting, 'in_headline': in_headline, 'open': still_open, 'note': '',
            'html': '<section class="topic" id="%s"><h2>%s</h2>%s%s</section>'
                    % (html.escape(ident), html.escape(effort['heading']), goal, body)}


def no_map_topic(scratch, pages):
    """Every folder with tickets and no map, under its own name: those with something open first. None when there are none."""
    parts = sorted(((f, *effort_sections(f, f.name, scratch, pages)) for f in folders_without_a_map(scratch)),
                   key=lambda p: (p[4] == 0, p[0].name))
    if not parts:
        return None
    body = ''.join('<section class="folder"><h3>%s</h3>%s</section>' % (html.escape(f.name), text) for f, text, *_ in parts)
    return {'id': 'no-map', 'name': 'No map', 'waiting': sum(p[2] for p in parts), 'in_headline': sum(p[3] for p in parts),
            'open': sum(p[4] for p in parts), 'note': '',
            'html': '<section class="topic" id="no-map"><h2>No map</h2><p class="goal">Folders with tickets and no map.md.</p>%s</section>' % body}


def postponed_topic(effort, scratch):
    """A postponed effort stays one closed line: nothing of it is to be picked up, so nothing of it waits."""
    all_tickets = tickets(effort['folder'], scratch)
    rows = [row(t, t['title'] or t['num'], t['status']) for t in all_tickets]
    ident = 'effort-' + effort['folder'].name
    return {'id': ident, 'name': effort['name'], 'waiting': 0, 'in_headline': 0, 'note': 'postponed',
            'open': sum(t['status'] not in CLOSED for t in all_tickets),
            'html': '<details class="topic" id="%s"><summary>%s %s, postponed (%d)</summary>%s</details>'
                    % (html.escape(ident), POSTPONED_MARK, html.escape(effort['heading']), len(rows), ''.join(rows))}


def version(scratch):
    """Changes when what tickets_html shows changes, so the start page updates."""
    files = list(scratch.glob('*/map.md')) + list(scratch.glob('*/issues/*.md'))
    stamps = ','.join(f'{f}:{f.stat().st_mtime_ns}' for f in sorted(files))
    return stamps + json.dumps(agents(), sort_keys=True)
