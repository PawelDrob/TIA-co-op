"""What wakes a coordinator: a ticket file that changed (the whole file: a findings round sets in-review over in-review), a review
answer, an answer given on a ticket's page of the dashboard (to any ticket, watched or not), a session's turn ending, asking permission or failing, a session gone, a session running without its guards, a terminal that
does not answer or is down, and a control character in a watched ticket.

What was seen is kept in a file per scope, so a watcher re-armed later still reports what happened in between. The first look of
a scope only takes the baseline, and reports control characters."""
import hashlib
import re
from pathlib import Path

from control_chars import describe, scan
from store import read_json, write_json

SAYS = {'ended': 'turn ended', 'asking': 'asks', 'failed': 'turn failed'}
QUIET_BETWEEN_TURNS = {'ended', 'failed'}
SHOWN = 160
NO_GUARDS_TEXT = 'its process has no --settings, so no denied tools and no hooks, and its state is stale'


def not_asked(kind, why):
    """The line for a terminal a look stopped asking, by the reason it gave, such as 'did not answer'."""
    return f'{kind} {why}, so not all its sessions were looked at: their state may be stale'


def digest(path):
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def status_of(text):
    found = re.search(r'(?m)^Status:[ \t]*(\S+)', text)
    return found.group(1) if found else '?'


def shortened(line):
    clean = ' '.join(re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', line).split())
    return clean if len(clean) <= SHOWN else clean[:SHOWN - 3] + '...'


def last_line(message):
    lines = [line for line in message.splitlines() if line.strip()]
    return shortened(lines[-1]) if lines else ''


def newest_comment(text):
    _, heading, comments = text.partition('## Comments')
    entries = re.findall(r'(?m)^- (.+)$', comments) if heading else []
    return shortened(entries[-1]) if entries else ''


class Watcher:
    def __init__(self, scratch, store, look_at, efforts=()):
        self.scratch, self.store, self.look_at = Path(scratch), store, look_at
        self.efforts = list(efforts)
        scope = '-'.join(sorted(self.efforts)) or 'all'
        self.baseline = self.store.root / f'watch-{re.sub(r"[^a-zA-Z0-9_-]+", "_", scope)}.json'
        self.seen = read_json(self.baseline)

    def sessions(self):
        found = self.store.open_sessions()
        return [r for r in found if r.get('effort') in self.efforts] if self.efforts else found

    def tickets(self, sessions):
        """{ticket file: name to show it by}"""
        shown = {}
        for effort in self.efforts:
            for path in sorted((self.scratch / effort / 'issues').glob('*.md')):
                shown[str(path)] = path.name
        for record in sessions:
            shown[record['ticket']] = record['name']
        return shown

    def ticket_events(self, shown, old, first):
        events, now = [], {}
        for path, label in shown.items():
            now[path] = digest(path)
            if now[path] is None or now[path] == old.get(path):
                continue
            if not first:
                text = Path(path).read_bytes().decode('utf-8', 'replace')
                comment = newest_comment(text)
                events.append(f'ticket {label} {status_of(text)}' + (f': {comment}' if comment else ''))
            events += [describe(p, f) for p, f in scan(self.scratch, [path])]
        return events, now

    def answer_events(self, old, first):
        events, now = [], {}
        folder = self.scratch / 'reviews' / 'answers'
        for path in sorted(folder.glob('*')) if folder.is_dir() else []:
            now[path.name] = digest(path)
            if now[path.name] != old.get(path.name) and not first:
                events.append(f'answer {path.stem}')
        return events, now

    def ticket_answer_events(self, old, first):
        """An answer given on a ticket's page: the dashboard writes it into the ticket and a record of it here, one per ticket."""
        events, now = [], {}
        folder = self.scratch / 'reviews' / 'ticket-answers'
        for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            now[path.name] = digest(path)
            if now[path.name] == old.get(path.name) or first:
                continue
            record = read_json(path)
            try:
                ticket = record['ticket'].removeprefix('.scratch/')
                events.append(f'answer to ticket {ticket} from {record["who"]}: {shortened(record["answer"])}')
            except (TypeError, KeyError, AttributeError):
                events.append(f'answer to ticket {path.stem}: record not readable')
        return events, now

    def session_events(self, sessions, looks, old, first):
        events, now = [], {}
        for record in sessions:
            name = record['name']
            state = self.store.state(name)
            was = old.get(name, {})
            gone = was.get('gone', False)
            if state['mark'] != was.get('mark') and state['state'] in SAYS and not first:
                waiting = state.get('background', 0)
                still = f', {waiting} background tasks still running' if waiting else ''
                events.append(f'session {name} {SAYS[state["state"]]}{still}: {last_line(state["message"])}')
            between_turns = record.get('terminal') == 'headless' and state['state'] in QUIET_BETWEEN_TURNS
            lives, guards = looks[name]
            if lives is False and not between_turns:
                if not gone and not first:
                    events.append(f'session {name} gone: it no longer runs, last state {state["state"]}')
                gone = True
            elif lives:
                gone = False
            bare = was.get('bare', False)
            if guards is False and not bare and not first:
                events.append(f'session {name} runs without its guards: {NO_GUARDS_TEXT}')
            if isinstance(guards, bool):
                bare = not guards
            now[name] = {'mark': state['mark'], 'gone': gone, 'bare': bare}
        return events, now

    def look(self):
        """The events since the last look."""
        first = self.seen is None
        seen = self.seen or {}
        sessions = self.sessions()
        ticket_events, tickets = self.ticket_events(self.tickets(sessions), seen.get('tickets', {}), first)
        answer_events, answers = self.answer_events(seen.get('answers', {}), first)
        ticket_answer_events, ticket_answers = self.ticket_answer_events(seen.get('ticket_answers', {}), first)
        looks, stopped = self.look_at(sessions)
        session_events, states = self.session_events(sessions, looks, seen.get('sessions', {}), first)
        stopped_events = [not_asked(kind, stopped[kind]) for kind in sorted(set(stopped) - set(seen.get('silent', []))) if not first]
        now = {'tickets': tickets, 'answers': answers, 'ticket_answers': ticket_answers, 'sessions': states, 'silent': sorted(stopped)}    # 'silent': baselines already written
        if now != self.seen:
            write_json(self.baseline, now)
        self.seen = now
        return ticket_events + answer_events + ticket_answer_events + stopped_events + session_events
