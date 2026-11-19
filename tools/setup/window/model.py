"""What the setup window shows: its pages, each a list of rows, and the menu that leads to them after the first run. The
rows come from what first setup's steps find (tools\\setup\\setup.py). No tkinter, and no rule of its own about what is set
up: every check and every change is a step of setup.py, the viewer's register.py or a dashboard's own answer, read fresh
each time.

A page has a short title and one line saying what it is; each row says what it is about itself, and whether it is
optional. The first run walks the pages in order; after it, the window opens on the menu, one entry a page. Whether the
first run is done is kept per user, outside the clone (FirstRun).
"""
import json
import os
from dataclasses import dataclass, field

from tools.setup.setup import same_path

# The pages, in the order of the first run: (key, title, what the page is).
PAGES = (
    ('installed', 'Installed', 'Tools used by this repository'),
    ('repository', 'Repository settings', 'Settings of this clone'),
    ('bridge', 'Bridge', 'What Claude Code needs to work on your TIA projects'),
    ('viewer', 'Block viewer', 'Exported blocks opened with a double-click'),
    ('dashboards', 'Dashboards', 'Local pages in your browser'),
    ('by-hand', 'By hand', 'What only you can do'),
)
MENU = ('Settings', 'This clone, by subject')

PAGE_TOPICS = {
    'installed': ('uv', 'git', 'Claude Code', 'TIA Portal', 'Openness group'),
    'repository': ('commit hook', 'tracked settings'),
    'bridge': ('projectsRoot', 'MCP server tia', 'plugin', 'status line'),
}

TITLES = {
    'uv': 'uv', 'git': 'git', 'Claude Code': 'Claude Code', 'TIA Portal': 'TIA Portal V20', 'Openness group': 'Openness group',
    'commit hook': 'Commit checks', 'tracked settings': 'Claude Code settings of this repository',
    'projectsRoot': 'Project repos folder', 'MCP server tia': 'MCP server tia', 'plugin': 'Plugin', 'status line': 'Status line',
}

# What each thing is, in its own row: for a person deciding whether to set it up.
ABOUT = {
    'uv': 'Makes the Python environment every tool here runs on, this window too.',
    'git': 'Keeps this repository and your project repos; the bridge commits each export.',
    'Claude Code': 'Runs the agents that change your TIA projects through the bridge. This repository is tested with it only.',
    'TIA Portal': 'TIA Portal V20 with its TIA Openness option, which the bridge works through.',
    'Openness group': "The Windows group 'Siemens TIA Openness': TIA lets only its members use Openness.",
    'commit hook': 'Runs the checks of this repository on each commit. For changing this repository.',
    'tracked settings': 'The file .claude\\settings.json of this repository: it turns on the plugin and UTF-8 for a Claude Code session in this folder.',
    'projectsRoot': 'Where your project repos live. The bridge keeps its sessions there; Claude Code may read, edit and use git there.',
    'MCP server tia': 'Lets Claude Code start the bridge, TiaBridge, as its server tia.',
    'plugin': 'The engineering skills the work on this repository uses: tickets, reviews, audits.',
    'status line': "A row in Claude Code's status line: what the bridge and its TIA are doing.",
    'viewer': 'A double-click on an exported block (.s7dcl) shows it as the change report draws it.',
}
OPTIONAL = {'Claude Code', 'commit hook', 'plugin', 'status line', 'viewer', 'development', 'tia'}

KINDS = {'ok': 'ok', 'done': 'ok', 'change': 'todo', 'question': 'todo', 'missing': 'missing', 'warning': 'warning'}
CHANGE_LABELS = {'commit hook': 'Turn on', 'MCP server tia': 'Register', 'plugin': 'Install', 'status line': 'Add',
                 'projectsRoot': 'Save'}
# A topic setup prints nothing for while it is right.
QUIET_OK = {'tracked settings': 'Both are on.'}
RESTART = ('Claude Code reads its servers and plugins when a session starts. End a session that ran in this folder before '
           'a change here, and run this there; it comes back with its conversation:')
NO_CLAUDE = 'Needs Claude Code, which this PC does not have yet: the page Installed says how to get it.'


@dataclass
class Action:
    """A button of a row. kind: make (a setup step's change, in finding), register, unregister, start, open (a dashboard,
    target its key), page (a page, target its key)."""
    label: str
    kind: str
    finding: object = None
    target: str = ''


@dataclass
class Row:
    state: str           # ok, todo (not done, can be done here), missing, warning, info
    title: str
    text: str
    actions: list = field(default_factory=list)
    key: str = ''        # what the row is about: a topic of setup, viewer, or a dashboard's key
    about: str = ''      # what it is
    optional: bool = False
    commands: list = field(default_factory=list)    # one a line, as written: the window shows them in a fixed-width font
    details: list = field(default_factory=list)     # what changes, one thing a line, one click away
    note: str = ''       # a line under the commands, about them
    blocks: list = field(default_factory=list)      # [(text, commands)] in reading order, one a finding of setup's


@dataclass
class Look:
    """Everything setup's steps found in one read, by topic; nothing in it is remembered between reads."""
    clone: str
    worktree_of: str = ''        # the main tree when this is a worktree: the window then only says what setup says
    claude: str = ''
    findings: dict = field(default_factory=dict)      # topic: [Finding]
    last_steps: list = field(default_factory=list)    # setup.window_last_steps(): [Finding]
    bridge_settings: dict = field(default_factory=dict)
    bridge_settings_error: str = ''
    viewer: dict = field(default_factory=dict)        # viewer.state()
    dashboards: list = field(default_factory=list)    # (Dashboard, Status)


def read(setup, viewer_state, dashboards):
    """A Look from the steps of setup (the module tools\\setup\\setup.py), changing nothing. viewer_state() gives the
    viewer's registration, dashboards() each dashboard with what its port answers."""
    look = Look(clone=str(setup.CLONE))
    worktree_of = setup.main_tree_if_worktree()
    if worktree_of:
        look.worktree_of = worktree_of
        return look
    look.claude = setup.shutil.which('claude') or ''
    claude_step = [] if look.claude else [setup.claude_step]       # with claude, setup's steps hold it
    for step in [setup.uv_step, *claude_step, *setup.steps(look.claude)]:
        for finding in step():
            look.findings.setdefault(finding.topic, []).append(finding)
    look.last_steps = setup.window_last_steps(look.claude)
    try:
        look.bridge_settings = setup.read_bridge_settings()
    except ValueError as e:
        look.bridge_settings_error = str(e)
    look.viewer = viewer_state()
    look.dashboards = dashboards()
    return look


def without_topic(text, topic):
    """A finding's text without the topic it starts with, which the row's title already says."""
    for head in (topic + ': ', topic + ', '):
        if text.startswith(head):
            return text[len(head):]
    return text


def sentence(text):
    return text[:1].upper() + text[1:]


def shown(finding, topic):
    """A finding's text as a row shows it: what setup writes for the window, else its line as a sentence without the topic."""
    return finding.shown or sentence(without_topic(finding.text, topic))


def topic_row(look, topic):
    """The row of one of setup's topics: the worst state of its findings, their texts, what a person does about one that is
    missing, and a button for a change."""
    found = look.findings.get(topic, [])
    title, about, optional = TITLES.get(topic, topic), ABOUT.get(topic, ''), topic in OPTIONAL
    if not found:
        if topic in ('MCP server tia', 'plugin') and not look.claude:
            return Row('missing', title, NO_CLAUDE, [Action('Go to Installed', 'page', target='installed')], topic, about, optional)
        if topic in QUIET_OK:
            return Row('ok', title, QUIET_OK[topic], key=topic, about=about, optional=optional)
        reason = 'git is missing.' if topic == 'commit hook' else 'its settings file cannot be read.'
        return Row('info', title, 'Not checked: ' + reason, key=topic, about=about, optional=optional)
    states = [KINDS.get(f.kind, 'info') for f in found]
    state = next((s for s in ('missing', 'todo', 'warning', 'ok') if s in states), 'info')
    texts, actions, commands, details, blocks = [], [], [], [], []
    for f in found:
        texts.append(shown(f, topic) if f.shown or f.kind != 'change' else 'Not done. ' + shown(f, topic))
        blocks.append((texts[-1], f.commands))       # a text and the commands it leads to stay together
        commands += f.commands
        details += f.details
        if f.kind == 'change':
            actions.append(Action(CHANGE_LABELS.get(topic, 'Do it'), 'make', f))
    if topic == 'projectsRoot':
        actions = [Action('Change…', 'page', target='bridge')] + actions
    return Row(state, title, '\n'.join(texts), actions, topic, about, optional, commands, details, blocks=blocks)


def viewer_row(look):
    v = look.viewer
    title, about = 'Block viewer (.s7dcl)', ABOUT['viewer']
    if v.get('error'):
        return Row('missing', title, v['error'], key='viewer', about=about, optional=True)
    note = v.get('note', '')     # a choice in "Open with", under the command
    if v.get('command') and v.get('default'):
        if v['command'] == v['this']:
            return Row('ok', title, 'Registered for this clone.', [Action('Unregister', 'unregister')], 'viewer', about, True, note=note)
        return Row('warning', title, 'Registered for another clone. Register this clone to take it over.',
                   [Action('Register this clone', 'register'), Action('Unregister', 'unregister')], 'viewer', about, True,
                   details=[f'It opens with: {v["command"]}'], note=note)
    return Row('todo', title, 'Not registered. Register sets it up for your Windows user only, to open with:',
               [Action('Register', 'register')], 'viewer', about, True, commands=[v.get('this', '')],
               details=[f'{v.get("key", "")}\\{v.get("progid", "")}: the program and its open command',
                        f'{v.get("key", "")}\\.s7dcl: the program a double-click opens'], note=note)


def dashboard_row(dashboard, status, clone):
    """A dashboard: running (its address, and whether it is this clone's), not running, or another program on its port."""
    common = dict(key=dashboard.key, about=dashboard.purpose, optional=True)
    if status.state == 'running':
        whose = '' if not status.clone else (' Of this clone.' if same_path(status.clone, clone) else f' Of the clone {status.clone}.')
        return Row('ok', dashboard.title, f'Running at {dashboard.url}.{whose} Its icon in the notification area stops it.',
                   [Action('Open', 'open', target=dashboard.key)], **common)
    if status.state == 'other':
        return Row('warning', dashboard.title, status.text, **common)
    return Row('todo', dashboard.title, f'Not running. Started, it is at {dashboard.url}, with no console window; nothing starts it with Windows.',
               [Action('Start', 'start', target=dashboard.key)], **common)


def page_rows(look, page):
    """The rows of a page."""
    if page in PAGE_TOPICS:
        rows = [topic_row(look, t) for t in PAGE_TOPICS[page]]
        if page == 'bridge':
            rows += bridge_settings_rows(look)
            if look.claude:
                rows.append(Row('info', 'After a change here', RESTART, key='restart', commands=['claude --continue']))
        return rows
    if page == 'viewer':
        return [viewer_row(look)]
    if page == 'dashboards':
        return [dashboard_row(d, s, look.clone) for d, s in look.dashboards]
    return by_hand_rows(look)


def by_hand_rows(look):
    """What only a person can do: each thing a step found missing that no button here does, then what follows setup."""
    missing = [Row('missing', TITLES.get(f.topic, f.topic), shown(f, f.topic), key=f.topic, about=ABOUT.get(f.topic, ''),
                   commands=f.commands, details=f.details)
               for found in look.findings.values() for f in found if f.person_step]
    return missing + [Row('info', f.topic, shown(f, f.topic), key=f.topic, commands=f.commands) for f in look.last_steps]


def bridge_settings_rows(look):
    """The bridge's other settings, as TiaBridge\\settings.json holds them; the folder has its own row."""
    rows = [Row('missing', 'TiaBridge\\settings.json', look.bridge_settings_error)] if look.bridge_settings_error else []
    return rows + [Row('info', name, 'Value: ' + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)),
                       about='A setting of the bridge, in TiaBridge\\settings.json.')
                   for name, value in look.bridge_settings.items() if name.lower() != 'projectsroot']


def open_count(rows):
    """How many rows are not done or missing. A dashboard that is not running is no part of the setup: it runs when a
    person wants it."""
    return sum(r.state in ('todo', 'missing') for r in rows if r.key not in ('development', 'tia'))


def menu_entries(look):
    """The menu after the first run: (key, title, line, state, what the page holds now) for each page."""
    entries = []
    for key, title, line in PAGES:
        rows = page_rows(look, key)
        count = open_count(rows)
        missing = any(r.state == 'missing' for r in rows if not r.optional)
        if key == 'by-hand':
            todo = sum(r.state == 'missing' for r in rows)
            entries.append((key, title, line, 'missing' if todo else 'info',
                            (f'{todo} missing; ' if todo else '') + f'{len(rows) - todo} to do after setup'))
        elif key == 'dashboards':
            running = sum(r.state == 'ok' for r in rows)
            entries.append((key, title, line, 'ok' if running else 'info', f'{running} of {len(rows)} running'))
        elif count:
            entries.append((key, title, line, 'missing' if missing else 'todo', f'{count} not done or missing'))
        else:
            entries.append((key, title, line, 'ok', 'All set'))
    return entries


def outcome(findings):
    """(failed, text) of a change's findings: a failure in the tool's own words, else what was done."""
    failed = [f for f in findings if f.kind == 'missing']
    return bool(failed), '\n'.join(f.text.strip() for f in (failed or findings))


def with_folder(look, setup, folder):
    """The look with the projects step planned for the folder a person typed: reads files, changes nothing. A text that
    is no folder plans nothing; the step says why."""
    look.findings['projectsRoot'] = setup.projects_root_step(folder.strip() or None)
    return look


def folder_warning(setup, folder):
    """The long-path warning on a typed folder, '' for one that is fine or no full path."""
    try:
        return setup.long_path_warning(setup.normal_root(folder.strip()), setup.WINDOW_LONG_PATH)
    except ValueError:
        return ''


def folder_offered(look, setup):
    """What the folder field starts with: the stored folder, else setup's default."""
    stored = next((v for n, v in look.bridge_settings.items() if n.lower() == 'projectsroot'), None)
    return stored if isinstance(stored, str) and stored else setup.default_projects_root()


def page_index(key):
    """The place of a page among PAGES, by its key."""
    return next(i for i, (k, _, _) in enumerate(PAGES) if k == key)


def first_page(first_run, clone):
    """Where a double-click opens: the first page until the first run of this clone is finished, then the menu (None)."""
    return None if first_run.done(clone) else 0


def first_run_store():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'TIA-co-op', 'setup-window.json')


class FirstRun:
    """Which clones finished the first run: a list of folders in a file of the user's, outside every clone. A file that
    cannot be read counts as none finished: the pages come again, which changes nothing by itself."""

    def __init__(self, path=None):
        self.path = path or first_run_store()

    def _folders(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        folders = data.get('finished') if isinstance(data, dict) else None
        return [f for f in folders if isinstance(f, str)] if isinstance(folders, list) else []

    def done(self, clone):
        return any(same_path(f, clone) for f in self._folders())

    def finish(self, clone):
        folders = [f for f in self._folders() if not same_path(f, clone)] + [clone]
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp = self.path + '.new'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump({'finished': folders}, f, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)
