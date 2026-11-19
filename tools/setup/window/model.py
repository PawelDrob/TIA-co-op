"""What the setup window shows: the pages of the first run and the settings, as rows built from what first setup's
steps find (tools\\setup\\setup.py). No tkinter, and no rule of its own about what is set up: every check and every
change is a step of setup.py, the viewer's register.py or a dashboard's own answer, read fresh each time.

A row is one thing: its state, a title, a text and the actions a person can take on it. The window draws rows and runs
their actions; it keeps nothing about what is registered. Whether the first run is done is kept per user, outside the
clone (FirstRun).
"""
import json
import os
from dataclasses import dataclass, field

# The pages of the first run, in order: (key, title).
PAGES = (
    ('pc', 'What this PC has'),
    ('bridge', 'Claude Code and the bridge'),
    ('viewer', 'Block viewer'),
    ('dashboards', 'Dashboards'),
    ('finish', 'What you do by hand'),
)

INTROS = {
    'pc': 'What this repo uses, and whether this PC has it. Something missing does not stop the pages: each item says what '
          'it is for and how to get it. Install what you need, then press Refresh.',
    'bridge': 'TiaBridge lets an agent in Claude Code work on your TIA projects. First the folder your project repos live in, '
              'then what Claude Code needs to start the bridge. Each item says what it changes and where; nothing changes '
              'until you press its button. Skip what you do not want: it shows as not done in the settings.',
    'viewer': 'The block viewer shows an exported block (.s7dcl) as TIA draws it. Registered, a double-click on such a file '
              'opens it there. This is for your Windows user only, and Unregister takes it back.',
    'dashboards': 'Two local pages in your browser. They run with no console window and have an icon in the notification '
                  'area of the taskbar, whose right-click menu stops them. Start one now, or later from the settings: '
                  'nothing starts with Windows.',
    'finish': 'What only you can do. Finish ends the first run: the next double-click on Setup opens the settings, from '
              'which every page here can be opened again.',
}

# Why each thing on the first page is wanted, in the words of a person deciding whether to install it.
NEEDED_FOR = {
    'uv': 'Makes the Python environment every tool of this repo runs on, this window too.',
    'git': 'Keeps this repo and your project repos: the bridge commits each export of a project.',
    'Claude Code': 'Runs the agents that change your TIA projects through the bridge. Tested with Claude Code only; '
                   'without it the bridge and the tools still run.',
    'TIA Portal': 'The bridge works on your projects through TIA Portal V20 and its TIA Openness option.',
    'Openness group': 'TIA lets only members of this Windows group use Openness, which the bridge needs.',
}

TITLES = {
    'uv': 'uv', 'git': 'git', 'Claude Code': 'Claude Code', 'TIA Portal': 'TIA Portal V20', 'Openness group': 'Windows group',
    'commit hook': 'Commit checks', 'MCP server tia': 'MCP server tia', 'plugin': 'Plugin', 'status line': 'Status line',
    'tracked settings': 'Settings of this repo', 'projectsRoot': 'Project repos folder',
}

PAGE_TOPICS = {
    'pc': ('uv', 'git', 'Claude Code', 'TIA Portal', 'Openness group'),
    'bridge': ('projectsRoot', 'MCP server tia', 'plugin', 'status line', 'commit hook', 'tracked settings'),
}

# The settings window's groups of setup's topics; the bridge's other settings and the viewer and dashboards follow.
SETTINGS_GROUPS = (
    ('This clone', ('commit hook', 'tracked settings')),
    ('Claude Code', ('Claude Code', 'MCP server tia', 'plugin', 'status line')),
    ('Bridge', ('projectsRoot',)),
    ('This PC', ('uv', 'git', 'TIA Portal', 'Openness group')),
)

KINDS = {'ok': 'ok', 'done': 'ok', 'change': 'todo', 'question': 'todo', 'missing': 'missing', 'warning': 'warning'}
CHANGE_LABELS = {'commit hook': 'Turn on', 'MCP server tia': 'Register', 'plugin': 'Install', 'status line': 'Add',
                 'projectsRoot': 'Save'}
RESTART = ('Claude Code reads its servers and plugins when a session starts: a session in this folder that was running '
           'before a change here has neither. End it and run claude --continue there; it comes back with its conversation.')
NO_CLAUDE = 'Needs Claude Code, which is not on the PATH (first page).'


@dataclass
class Action:
    """A button of a row. kind: make (a setup step's change, in finding), register, unregister, start, open (a dashboard,
    target its key), page (a page of the first run, target its key)."""
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


@dataclass
class Look:
    """Everything setup's steps found in one read, by topic; nothing in it is remembered between reads."""
    clone: str
    worktree_of: str = ''        # the main tree when this is a worktree: the window then only says what setup says
    claude: str = ''
    findings: dict = field(default_factory=dict)      # topic: [Finding]
    person_steps: list = field(default_factory=list)
    bridge_settings: dict = field(default_factory=dict)
    bridge_settings_error: str = ''
    viewer: dict = field(default_factory=dict)        # viewer.state(): register.state(), 'this' and 'note'
    dashboards: list = field(default_factory=list)    # (Dashboard, Status)


def read(setup, viewer_state, dashboards, folder=None):
    """A Look from the steps of setup (the module tools\\setup\\setup.py), changing nothing. viewer_state() gives the
    viewer's registration, dashboards() each dashboard with what its port answers. folder: a projects folder a person
    typed, which the projects step then plans for."""
    look = Look(clone=str(setup.CLONE))
    worktree_of = setup.main_tree_if_worktree()
    if worktree_of:
        look.worktree_of = worktree_of
        return look
    look.claude = setup.shutil.which('claude') or ''
    claude_step = [] if look.claude else [setup.claude_step]       # with claude, setup's steps hold it
    for step in [setup.uv_step, *claude_step, *setup.steps(look.claude, folder)]:
        for finding in step():
            look.findings.setdefault(finding.topic, []).append(finding)
            if finding.person_step:
                look.person_steps.append(finding.person_step)
    look.person_steps += setup.last_steps(look.claude)
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


# A topic setup prints nothing for while it is right.
QUIET_OK = {'tracked settings': 'Enables the plugin and UTF-8 for a Claude Code session here (.claude\\settings.json).'}


def sentence(text):
    return text[:1].upper() + text[1:]


def shown(finding, topic):
    """A finding's text as a row shows it: what setup gives for the window, else its line without the topic."""
    return finding.shown or without_topic(finding.text, topic)


def topic_row(look, topic, explain=False):
    """The row of one of setup's topics: the worst state of its findings, their texts, a button for a change. explain:
    say what it is for even when it is there, as the first page does."""
    found = look.findings.get(topic, [])
    title = TITLES.get(topic, topic)
    if not found:
        if topic in ('MCP server tia', 'plugin') and not look.claude:
            return Row('missing', title, NO_CLAUDE, [Action('First page', 'page', target='pc')], topic)
        if topic in QUIET_OK:
            return Row('ok', title, QUIET_OK[topic], key=topic)
        reason = 'git is missing.' if topic == 'commit hook' else 'its settings file cannot be read.'
        return Row('info', title, 'Not checked: ' + reason, key=topic)
    states = [KINDS.get(f.kind, 'info') for f in found]
    state = next((s for s in ('missing', 'todo', 'warning', 'ok') if s in states), 'info')
    texts, actions = [], []
    for f in found:
        if f.kind == 'change':
            texts.append('Not done. ' + sentence(shown(f, topic)))
            actions.append(Action(CHANGE_LABELS.get(topic, 'Do it'), 'make', f))
        else:
            texts.append(shown(f, topic))
    if topic == 'projectsRoot':
        actions = [Action('Change…', 'page', target='bridge')] + actions
    if topic in NEEDED_FOR and (explain or state != 'ok'):
        texts.insert(0, NEEDED_FOR[topic])
    return Row(state, title, '\n'.join(texts), actions, topic)


def viewer_row(look):
    v = look.viewer
    title = 'Block viewer (.s7dcl)'
    if v.get('error'):
        return Row('missing', title, v['error'], key='viewer')
    note = ('\n' + v['note']) if v.get('note') else ''
    if v.get('command') and v.get('default'):
        if v['command'] == v['this']:
            return Row('ok', title, 'A double-click on an .s7dcl file opens it in the block viewer of this clone.' + note,
                       [Action('Unregister', 'unregister')], 'viewer')
        return Row('warning', title, f'Registered for another clone: {v["command"]}. Register this clone to take it over.' + note,
                   [Action('Register this clone', 'register'), Action('Unregister', 'unregister')], 'viewer')
    return Row('todo', title, 'Not registered. Register writes, for your Windows user only, the program TiaChangeReports.BlockViewer '
               f'and .s7dcl under HKEY_CURRENT_USER\\Software\\Classes, with the command {v.get("this", "")}' + note,
               [Action('Register', 'register')], 'viewer')


def dashboard_row(dashboard, status, clone):
    """A dashboard: running (its address, and whether it is this clone's), not running, or another program on its port."""
    if status.state == 'running':
        whose = '' if not status.clone else (' Of this clone.' if same_folder(status.clone, clone) else f' Of the clone {status.clone}.')
        text = f'Running at {dashboard.url}.{whose} To stop it, use its icon\'s menu in the notification area.'
        return Row('ok', dashboard.title, dashboard.purpose + '\n' + text, [Action('Open', 'open', target=dashboard.key)], dashboard.key)
    if status.state == 'other':
        return Row('warning', dashboard.title, dashboard.purpose + '\n' + status.text, key=dashboard.key)
    return Row('todo', dashboard.title, f'{dashboard.purpose}\nNot running. Started, it is at {dashboard.url}.',
               [Action('Start', 'start', target=dashboard.key)], dashboard.key)


def same_folder(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def page_rows(look, page):
    """The rows of a page of the first run."""
    if page in PAGE_TOPICS:
        return [topic_row(look, t, explain=page == 'pc') for t in PAGE_TOPICS[page]]
    if page == 'viewer':
        return [viewer_row(look)]
    if page == 'dashboards':
        return [dashboard_row(d, s, look.clone) for d, s in look.dashboards]
    return [Row('info', f'{n}.', step) for n, step in enumerate(look.person_steps, 1)]


def page_note(look, page):
    """A line under a page's rows: the restart that the bridge page's changes need."""
    return RESTART if page == 'bridge' and look.claude else ''


def settings_groups(look):
    """The settings window: (heading, rows) for each group, read fresh."""
    groups = [(heading, [topic_row(look, t) for t in topics]) for heading, topics in SETTINGS_GROUPS]
    by_heading = dict(groups)
    if look.claude:
        by_heading['Claude Code'].append(Row('info', 'After a change here', RESTART))
    bridge = by_heading['Bridge']
    if look.bridge_settings_error:
        bridge.append(Row('missing', 'TiaBridge\\settings.json', look.bridge_settings_error))
    for name, value in look.bridge_settings.items():
        if name.lower() != 'projectsroot':
            bridge.append(Row('info', name, json.dumps(value, ensure_ascii=False)))
    groups.append(('Block viewer', [viewer_row(look)]))
    groups.append(('Dashboards', [dashboard_row(d, s, look.clone) for d, s in look.dashboards]))
    return groups


def open_items(look):
    """How many things of the setup are not done or missing, for the settings' headline. A dashboard that is not running
    is no part of the setup: it runs when a person wants it."""
    return sum(r.state in ('todo', 'missing') for heading, rows in settings_groups(look) if heading != 'Dashboards' for r in rows)


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
        return setup.long_path_warning(setup.normal_root(folder.strip()))
    except ValueError:
        return ''


def folder_offered(look, setup):
    """What the folder field starts with: the stored folder, else setup's default."""
    stored = next((v for n, v in look.bridge_settings.items() if n.lower() == 'projectsroot'), None)
    return stored if isinstance(stored, str) and stored else setup.default_projects_root()


def first_page(first_run, clone):
    """Where a double-click opens: page 1 until the first run of this clone is finished, then the settings (None)."""
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
        return any(same_folder(f, clone) for f in self._folders())

    def finish(self, clone):
        folders = [f for f in self._folders() if not same_folder(f, clone)] + [clone]
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp = self.path + '.new'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump({'finished': folders}, f, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)
