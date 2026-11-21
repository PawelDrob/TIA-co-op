"""What a ticket or audit session starts without: tools, plugins and skills it never uses, whose definitions every request would
carry again. Measured with a real claude 2.1.330 and `session.py tokens` (ticket 411): a tool in --disallowedTools leaves the
request; a plugin set false in the session's settings leaves with its skills and agents; disableBundledSkills takes the skills
Claude Code brings itself; skillOverrides "off" takes one skill by its exact name, with no pattern. The user's settings are read,
never changed: only the session's own settings file says this.
"""
from dataclasses import dataclass
from pathlib import Path

from store import SessionError, read_json
from tokens import counted

# None is called by a skill a ticket or audit session runs (.claude/skills, the plugin's implement and code-review). Agent stays:
# audits start their reviewers with it.
TOOLS = ('Artifact', 'Workflow', 'SendFeedback', 'ScheduleWakeup', 'ReportFindings', 'ListAgents')
KEPT_PLUGINS = ('mattpocock-skills',)    # the ticket flow's implement, code-review and tdd
BUILT_IN_SKILLS = ('plugin-authoring',)    # of a plugin Claude Code brings itself, which no setting of plugins reaches
BUNDLED = 'bundled'
ALL = 'all'


@dataclass
class LeftOut:
    tools: list
    plugins: list    # as enabledPlugins names them, <plugin>@<marketplace>
    skills: list
    bundled: bool

    def settings(self):
        """What goes into the session's own settings file for it."""
        found = {}
        if self.plugins:
            found['enabledPlugins'] = dict.fromkeys(self.plugins, False)
        if self.bundled:
            found['disableBundledSkills'] = True
        if self.skills:
            found['skillOverrides'] = dict.fromkeys(self.skills, 'off')
        return found

    def summary(self):
        parts = [counted(len(self.tools), 'tool'), counted(len(self.plugins), 'plugin'), counted(len(self.skills), 'skill')]
        return 'left out: ' + ', '.join(parts) + (', the bundled skills' if self.bundled else '') + '. --keep <name> brings one back'


def enabled_plugins(home, tree):
    """The plugins a plain claude in the tree has on: the user's settings, then the tree's own, a later file deciding."""
    found = {}
    for path in (home / 'settings.json', tree / '.claude' / 'settings.json', tree / '.claude' / 'settings.local.json'):
        plugins = (read_json(path) or {}).get('enabledPlugins')
        if isinstance(plugins, dict):
            found.update(plugins)
    return sorted(name for name, on in found.items() if on is True)


def skill_names(folder):
    """The skills of a skills folder, by their folder's name."""
    return sorted(path.parent.name for path in Path(folder).glob('*/SKILL.md')) if Path(folder).is_dir() else []


def synced_skills(home):
    """The skills claude.ai syncs to this machine, a folder per account under <home>\\skills\\synced\\."""
    synced = home / 'skills' / 'synced'
    return sorted({name for account in (synced.iterdir() if synced.is_dir() else []) for name in skill_names(account)})


def plugin_of(key):
    return key.split('@', 1)[0]


def left_out(home, tree, main, keep=()):
    """What the session leaves out, less what keep names. The repo's own skills always stay; the main tree's copies of them,
    listed again under <main folder>:<skill> by --add-dir, always go: the tree's own are the branch's. A name in keep that is
    none of these is refused, with what can be kept."""
    home, tree, main = Path(home), Path(tree), Path(main)
    own = skill_names(tree / '.claude' / 'skills')
    plugins = [key for key in enabled_plugins(home, tree) if plugin_of(key) not in KEPT_PLUGINS]
    skills = [name for name in [*synced_skills(home), *BUILT_IN_SKILLS] if name not in own]
    keep = list(dict.fromkeys(keep))
    known = {ALL, BUNDLED, *TOOLS, *plugins, *map(plugin_of, plugins), *skills}
    unknown = [name for name in keep if name not in known]
    if unknown:
        raise SessionError(f'--keep {", ".join(unknown)}: not among what a session leaves out. It can keep: {ALL}, {BUNDLED}, '
                           f'the tools {", ".join(TOOLS)}, the plugins {", ".join(map(plugin_of, plugins)) or "(none on)"}, '
                           f'the skills {", ".join(skills) or "(none)"}. Nothing started')
    if ALL in keep:
        return LeftOut([], [], [], False)
    copies = [f'{main.name}:{name}' for name in skill_names(main / '.claude' / 'skills')] if main.resolve() != tree.resolve() else []
    return LeftOut(tools=[tool for tool in TOOLS if tool not in keep],
                   plugins=[key for key in plugins if key not in keep and plugin_of(key) not in keep],
                   skills=[name for name in skills if name not in keep] + copies,
                   bundled=BUNDLED not in keep)
