"""Every state of the three rows that change with what is already there, read as the window shows them: the project repos
folder, the MCP server tia and the block viewer. Each combination is set up in a temp clone with a temp home (the setup
tests' fixture), or under a registry key of the test's own, and its words are held whole."""
import importlib.util
import itertools
import json
import os
import uuid
from unittest import mock

from TiaChangeReports.viewer import register
from tools.setup.tests.test_setup import SetupCase
from tools.setup.window import model, viewer

NEW, OLD = r'C:\Work\Repos', r'C:\Work\Old'
OTHER_CLONE = r'C:\Work\other\TiaBridge\TiaBridge.ps1'
COMMAND = r'C:\Tools\tool.ps1'
REMOVE_LOCAL = 'claude mcp remove --scope local tia'


class Rows(SetupCase):
    def setup_module(self):
        patch = mock.patch.dict(os.environ, {**self.env(), 'SystemRoot': str(self.system_root)}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        spec = importlib.util.spec_from_file_location('first_setup_states', self.clone / 'tools' / 'setup' / 'setup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class Folder(Rows):
    """The folder: none stored, the same stored, another stored; the rules of the new folder none, some or all there; the
    rules of an old folder none or some. The field holds the new folder, as the window plans for it."""

    def folder_row(self, setup, stored, new_rules, old_rules):
        bridge = {'tiaRoot': str(self.tia)}
        if stored != 'none':
            bridge['projectsRoot'] = NEW if stored == 'same' else OLD
        self.bridge_settings.write_text(json.dumps(bridge))
        allow = {'none': [], 'some': setup.allow_rules(NEW)[:3], 'all': setup.allow_rules(NEW)}[new_rules]
        allow = allow + {'none': [], 'some': setup.allow_rules(OLD)[:3]}[old_rules] + ['Bash(a rule of my own)']
        self.user_settings.write_text(json.dumps({'permissions': {'allow': allow}}))
        look = model.with_folder(model.Look(clone=str(self.clone), claude='claude'), setup, NEW)
        return model.topic_row(look, 'projectsRoot')

    def expected(self, stored, new_rules, old_rules):
        user = str(self.user_settings)
        if stored == 'same' and new_rules == 'all':
            return 'ok', [f'Folder: {NEW}', 'The bridge makes its sessions folder there, _bridge\\sessions, each time it starts.',
                          f'Claude Code may read, edit and use git there: 6 allow rules, in {user}.']
        lines = ['Not saved. Save writes:']
        lines += ([f'Folder: {NEW} (stays)'] if stored == 'same' else
                  [f'Folder: {NEW}' + (f' (in place of {OLD})' if stored == 'other' else ''), 'Saved in: TiaBridge\\settings.json'])
        lines.append({'none': f'Claude Code may read, edit and use git there: 6 allow rules to add, in {user}.',
                      'some': f'Claude Code may read, edit and use git there: 3 allow rules to add, in {user}.',
                      'all': f'Claude Code may read, edit and use git there already: its allow rules are in {user}.'}[new_rules])
        if stored == 'other' and old_rules == 'some':
            lines.append(f'Allow rules on the old folder, {OLD}: 3 to take away.')
        return 'todo', lines

    def test_every_combination_reads_as_written(self):
        setup = self.setup_module()
        for stored, new_rules, old_rules in itertools.product(('none', 'same', 'other'), ('none', 'some', 'all'), ('none', 'some')):
            with self.subTest(stored=stored, new_rules=new_rules, old_rules=old_rules):
                row = self.folder_row(setup, stored, new_rules, old_rules)
                self.assertEqual((row.state, row.text.split('\n')), self.expected(stored, new_rules, old_rules))
                self.assertEqual([a.label for a in row.actions if a.kind == 'make'], [] if row.state == 'ok' else ['Save'])

    def test_one_rule_is_one_rule(self):
        setup = self.setup_module()
        self.bridge_settings.write_text(json.dumps({'tiaRoot': str(self.tia), 'projectsRoot': NEW}))
        self.user_settings.write_text(json.dumps({'permissions': {'allow': setup.allow_rules(NEW)[1:]}}))
        row = model.topic_row(model.with_folder(model.Look(clone=str(self.clone), claude='claude'), setup, NEW), 'projectsRoot')
        self.assertIn('1 allow rule to add', row.text)


class Server(Rows):
    """The server tia: of your Windows user none, this clone's, another clone's or another command; of this folder the same."""

    def server_row(self, setup, user, local):
        script = {'this': str(self.clone / 'TiaBridge' / 'TiaBridge.ps1'), 'clone': OTHER_CLONE, 'command': COMMAND}
        state = {}
        if user != 'none':
            state['mcpServers'] = {'tia': {'type': 'stdio', 'command': 'x', 'args': ['-File', script[user]]}}
        if local != 'none':
            state['projects'] = {self.clone.as_posix(): {'mcpServers': {'tia': {'type': 'stdio', 'command': 'x', 'args': ['-File', script[local]]}}}}
        (self.config / '.claude.json').write_text(json.dumps(state))
        return model.topic_row(model.Look(clone=str(self.clone), claude='claude', findings={'MCP server tia': setup.server_step('claude')}),
                               'MCP server tia')

    def expected(self, user, local):
        """(state, [(the start of each text, its commands' starts)])."""
        holder = {'clone': 'another clone', 'command': 'another command'}
        before_yours = (f'In this folder, though, {holder.get(local)} is registered, and a session here starts that one.', [REMOVE_LOCAL])
        if user == 'none' and local == 'this':      # a session here starts this clone already
            return 'todo', [('Registered for this folder only, so a session here starts this clone. Register adds it for your Windows '
                             'user too, for sessions in other folders,', ['claude mcp add --scope user tia'])]
        if user == 'none':
            blocks = [('Not registered. Register adds it for your Windows user,', ['claude mcp add --scope user tia'])]
            return 'todo', blocks + ([before_yours] if local in holder else [])
        if user == 'this':
            ok = ('Registered for your Windows user: it starts the bridge of this clone.', [])
            return ('warning', [ok, before_yours]) if local in holder else ('ok', [ok])
        if local == 'none':
            return 'todo', [(f'Not registered. Register adds it for this folder only, as {holder[user]} has it for your Windows user,',
                             ['claude mcp add --scope local tia'])]
        if local == 'this':
            return 'ok', [(f'Registered for this folder; {holder[user]} has it for your Windows user.', ['claude mcp remove --scope user tia'])]
        return 'missing', [(f'Registered in this folder for {holder[local]}, which stays as it is.', [REMOVE_LOCAL])]

    def test_every_combination_reads_as_written_each_text_before_its_commands(self):
        setup = self.setup_module()
        for user, local in itertools.product(('none', 'this', 'clone', 'command'), repeat=2):
            with self.subTest(user=user, local=local):
                row = self.server_row(setup, user, local)
                state, blocks = self.expected(user, local)
                self.assertEqual(row.state, state)
                self.assertEqual(len(row.blocks), len(blocks), row.blocks)
                for (text, commands), (start, command_starts) in zip(row.blocks, blocks):
                    self.assertTrue(text.startswith(start), (text, start))
                    self.assertEqual(len(commands), len(command_starts))
                    for command, command_start in zip(commands, command_starts):
                        self.assertTrue(command.startswith(command_start), command)

    def test_what_another_one_runs_is_in_the_detail(self):
        setup = self.setup_module()
        self.assertEqual(self.server_row(setup, 'clone', 'none').details, [f'For your Windows user, in other folders, tia starts {OTHER_CLONE}.'])
        self.assertEqual(self.server_row(setup, 'this', 'command').details, [f'In this folder tia starts {COMMAND}.'])
        self.assertEqual(self.server_row(setup, 'command', 'clone').details, [f'In this folder tia starts {OTHER_CLONE}.'])

    def test_the_command_says_once_that_this_folder_starts_another_and_its_exit_code_stays(self):
        """Both states the warning comes in: your Windows user's tia none, which setup then registers, and this clone's.
        A warning is no failure: setup's exit code is that of the same run without it."""
        setup = self.setup_module()
        for user, line_before in (('none', 'done     MCP server tia registered, user scope'), ('this', 'ok       MCP server tia')):
            with self.subTest(user=user):
                self.server_row(setup, user, 'command')
                code, out = self.answered()      # the command, in a process of its own with the fixture's environment
                self.assertEqual(code, 0, out)
                lines = out.splitlines()
                warnings = [i for i, line in enumerate(lines) if 'which a session here starts in place of the one of your Windows user' in line]
                self.assertEqual(len(warnings), 1, out)
                self.assertTrue(lines[warnings[0]].startswith('warning  MCP server tia: in this folder it is registered for '), out)
                self.assertEqual(lines[warnings[0] - 1], line_before, out)


class Viewer(Rows):
    """The viewer: not registered, this clone's, another clone's; with "Open with" naming another program or not."""

    def setUp(self):
        super().setUp()
        root = r'Software\TiaCoopSetupStates-%s' % uuid.uuid4().hex
        self.keys = (root + r'\Classes', root + r'\UserChoice')
        self.addCleanup(register.delete_tree, 'Software', root.split('\\', 1)[1])

    def test_every_combination_reads_as_written_the_note_under_the_command(self):
        other = register.command(r'C:\Work\other\TiaChangeReports\viewer')
        note = ('Windows opens .s7dcl files with Other.Editor, as chosen in "Open with": right-click one, Open with, Choose another app, '
                'Block viewer, Always.')
        for registered, chosen in itertools.product(('none', 'this', 'other'), (False, True)):
            with self.subTest(registered=registered, chosen=chosen):
                register.delete_tree('Software', self.keys[0].split('\\', 1)[1].rsplit('\\', 1)[0])
                if registered != 'none':
                    register.register(None if registered == 'this' else other, *self.keys, notify=False)
                if chosen:
                    register.write_value(self.keys[1], '', 'Other.Editor', 'ProgId')
                row = model.viewer_row(model.Look(clone=str(self.clone), viewer=viewer.state(*self.keys)))
                expected = {'none': ('todo', 'Not registered. Register sets it up for your Windows user only, to open with:', [register.command()]),
                            'this': ('ok', 'Registered for this clone.', []),
                            'other': ('warning', 'Registered for another clone. Register this clone to take it over.', [])}[registered]
                self.assertEqual((row.state, row.text, row.commands), expected)
                self.assertEqual(row.note, note if chosen else '')
                if registered == 'other':
                    self.assertEqual(row.details, [f'It opens with: {other}'])
