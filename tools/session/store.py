"""What is known of each session, on disk under <.scratch>\\sessions\\<name>\\: session.json from `session start`, state.json and
session-id.json from the session's own hooks, tokens.txt and tokens.json from its close. Closing a session marks its record and
keeps it, so a later close can still remove the tree."""
import json
import os
import re
import tempfile
import time
from pathlib import Path

NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')    # herdr's rule for an agent's name: all of the adapters can use it
MAX_MESSAGE = 4000
ASKING = {'permission_prompt', 'elicitation_dialog'}
SESSION_ID = 'session-id.json'


class SessionError(Exception):
    """A refusal or failure to show as it is."""


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    """Whole or not at all: a watcher reads these while they are written."""
    write_text(path, json.dumps(data, indent=1))


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    with os.fdopen(handle, 'w', encoding='utf-8') as f:
        f.write(text)
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:    # on Windows a reader holding the file blocks the replace for a moment
            if attempt == 19:
                raise
            time.sleep(0.05)


def write_state(folder, state, message='', background=0):
    write_json(Path(folder) / 'state.json', {'state': state, 'message': message[:MAX_MESSAGE], 'background': background,
                                             'mark': time.time_ns()})


def ids_in(known):
    """Every id a session-id.json holds, oldest first: one written before it kept them all holds only the newest."""
    known = known if isinstance(known, dict) else {}
    ids = known.get('ids') if isinstance(known.get('ids'), list) else []
    return list(dict.fromkeys(i for i in [*ids, known.get('session_id')] if isinstance(i, str) and i))


def record_hook(folder, payload):
    """Writes down what a hook of the session reports, and the id it runs under: `list --resume` needs the newest with herdr down,
    `tokens` every one, as a /clear or a start again gives a new one. Anything else it fires for changes nothing."""
    session_id = payload.get('session_id')
    if session_id:
        known = read_json(Path(folder) / SESSION_ID)
        ids = [i for i in ids_in(known) if i != session_id] + [session_id]
        if known != {'session_id': session_id, 'ids': ids}:
            write_json(Path(folder) / SESSION_ID, {'session_id': session_id, 'ids': ids})
    event = payload.get('hook_event_name')
    if event == 'UserPromptSubmit':
        write_state(folder, 'working')
    elif event == 'Stop':
        write_state(folder, 'ended', str(payload.get('last_assistant_message') or ''), len(payload.get('background_tasks') or []))
    elif event == 'StopFailure':
        write_state(folder, 'failed', str(payload.get('error') or payload.get('error_details') or ''))
    elif event == 'Notification' and payload.get('notification_type') in ASKING:
        write_state(folder, 'asking', str(payload.get('message') or ''))


def record_in(folder):
    """The record in a session's folder, for a hook, which knows only that: {} when there is none."""
    return read_json(Path(folder) / 'session.json') or {}


class Store:
    def __init__(self, scratch):
        self.root = Path(scratch) / 'sessions'

    def folder(self, name):
        if not NAME.match(name or ''):
            raise SessionError(f"{name!r} is not a session name: lowercase letters, digits, - and _, starting with a letter")
        return self.root / name

    def exists(self, name):
        return (self.folder(name) / 'session.json').is_file()

    def save(self, record):
        write_json(self.folder(record['name']) / 'session.json', record)

    def load(self, name):
        """The record of exactly this name, or a refusal: a typo must not reach another session."""
        record = read_json(self.folder(name) / 'session.json')
        if record is None:
            known = ', '.join(r['name'] for r in self.open_sessions()) or 'none'
            raise SessionError(f'no session named {name}. Open sessions: {known}')
        return record

    def all_sessions(self):
        found = (read_json(p) for p in sorted(self.root.glob('*/session.json')))
        return [r for r in found if r]

    def open_sessions(self):
        return [r for r in self.all_sessions() if not r.get('closed')]

    def session_id(self, name):
        """The id the session's hook last reported, which a /clear changes; None before its first hook."""
        return (read_json(self.folder(name) / SESSION_ID) or {}).get('session_id')

    def session_ids(self, name):
        """Every id the session's hook has reported, oldest first."""
        return ids_in(read_json(self.folder(name) / SESSION_ID))

    def state(self, name):
        return read_json(self.folder(name) / 'state.json') or {'state': 'unknown', 'message': '', 'mark': 0}
