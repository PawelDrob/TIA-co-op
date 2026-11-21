"""How many tokens a session used, from transcripts made up for these tests in the shape Claude Code writes: a real one holds paths and an
account, and none comes into the repo."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tokens
from store import SessionError, Store, record_hook
from test_merge import MergeCase
from test_sessions import Case
from tokens import find_transcripts, folder_name, full_text, measure, short_text

OPUS = 'claude-opus-5-5'


def usage(fresh=0, write_1h=0, write_5m=0, read=0, out=0, thinking=0):
    return {'input_tokens': fresh, 'cache_creation_input_tokens': write_1h + write_5m, 'cache_read_input_tokens': read,
            'output_tokens': out, 'output_tokens_details': {'thinking_tokens': thinking},
            'cache_creation': {'ephemeral_1h_input_tokens': write_1h, 'ephemeral_5m_input_tokens': write_5m}}


def answer(request, used, model=OPUS, calls=(), stamp='2026-11-21T10:00:00Z', part=None):
    """One line of a request: a request with several parts has a line per part, each with the same usage."""
    content = [part] if part else ([{'type': 'tool_use', 'id': f'{request}-{i}', 'name': name, 'input': given}
                                     for i, (name, given) in enumerate(calls)] or [{'type': 'text', 'text': 'done'}])
    return {'type': 'assistant', 'requestId': request, 'timestamp': stamp, 'isSidechain': False,
            'message': {'id': 'msg-' + request, 'model': model, 'usage': used, 'content': content}}


def hook_ran(folder, stamp='2026-11-21T10:00:01Z'):
    command = f'"C:/clone/.venv/Scripts/python.exe" -X utf8 "C:/clone/tools/session/session.py" hook "{Path(folder).as_posix()}"'
    return {'type': 'system', 'subtype': 'stop_hook_summary', 'timestamp': stamp, 'hookInfos': [{'command': command, 'durationMs': 120}]}


def write_transcript(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join((line if isinstance(line, str) else json.dumps(line)) + '\n' for line in lines), encoding='utf-8')
    return path


class Folder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name)
        self.projects = self.top / 'projects'
        self.worktree = self.top / 'clone-worktrees' / 'work-03'
        self.hook_folder = self.top / 'clone' / '.scratch' / 'sessions' / 'wk03'

    def transcript(self, session_id, lines, folder=None):
        return write_transcript(self.projects / (folder or folder_name(self.worktree)) / f'{session_id}.jsonl', lines)

    def measured(self, ids=('one',)):
        return measure(find_transcripts(self.projects, self.worktree, self.hook_folder, list(ids)), roots=[self.worktree])


class CountTests(Folder):
    def test_a_request_on_several_lines_is_counted_once(self):
        used = usage(fresh=3, write_1h=1000, read=9000, out=200, thinking=50)
        self.transcript('one', [answer('r1', used, part={'type': 'thinking', 'thinking': ''}),
                                answer('r1', used, part={'type': 'text', 'text': 'reading'}),
                                answer('r1', used, part={'type': 'tool_use', 'id': 't', 'name': 'Read', 'input': {}})])
        data = self.measured()
        self.assertEqual(data['requests'], 1)
        self.assertEqual(data['tokens'], {'input': 3, 'write_5m': 0, 'write_1h': 1000, 'write_unknown': 0, 'read': 9000, 'output': 200,
                                          'thinking': 50})

    def test_the_four_meters_and_their_sum_first_with_the_numbers_of_the_ticket(self):
        """The counts ticket 405 measured, on one made-up request: 230 + 269,072 + 22,238,640 + 60,174."""
        self.transcript('one', [answer('r1', usage(fresh=230, write_1h=269_072, read=22_238_640, out=60_174, thinking=20_966))])
        data = self.measured()
        self.assertEqual(data['tokens_in_all'], 22_568_116)
        self.assertNotIn('dollars', data)
        text = short_text('wk03', data)
        self.assertEqual(text.splitlines()[:6], [
            'wk03: 22,568,116 tokens in all, 1 request in 1 transcript, claude-opus-5-5',
            '  uncached input                             230',
            '  cache writes, 5 min                          0',
            '  cache writes, 1 h                      269,072',
            '  cache reads                         22,238,640',
            '  output                                  60,174  thinking 20,966'])
        self.assertNotIn('$', text)

    def test_a_transcript_with_no_request_says_so(self):
        self.transcript('one', [{'type': 'permission-mode', 'permissionMode': 'auto'}, hook_ran(self.hook_folder)])
        data = self.measured()
        self.assertEqual(short_text('wk03', data), 'wk03: no request to the model counted in 1 transcript, so no tokens')
        self.assertEqual(full_text('wk03', data).splitlines()[:3], [
            'wk03: no request to the model counted in 1 transcript, so no tokens',
            'What entered the context: nothing, as no request was counted',
            'Fixed prefix: the transcripts record no request shape'])
        self.assertTrue(full_text('wk03', data).splitlines()[3].startswith('Transcripts: '))

    def test_a_transcript_whose_usage_it_does_not_know_says_what_it_skipped(self):
        """As a new Claude Code release could write it: every request skipped, and said so in each form."""
        self.transcript('one', [answer('r1', {'tokens': {'in': 5}}), answer('r2', {'tokens': {'in': 9}})])
        data = self.measured()
        for text in (short_text('wk03', data), full_text('wk03', data)):
            self.assertIn('wk03: no request to the model counted in 1 transcript, so no tokens', text)
            self.assertIn('  skipped, requests whose usage has a shape this does not know: 2', text)

    def test_a_transcript_that_cannot_be_opened_says_so(self):
        folder = self.projects / folder_name(self.worktree) / 'one.jsonl'
        folder.mkdir(parents=True)    # found as a transcript, opened as none
        data = self.measured()
        self.assertEqual(data['skipped'], {'transcripts that could not be read': 1})
        for text in (short_text('wk03', data), full_text('wk03', data)):
            self.assertIn('wk03: no request to the model counted in 1 transcript, so no tokens', text)
            self.assertIn('  skipped, transcripts that could not be read: 1', text)
            self.assertIn(f'  could not be read: {folder}: ', text)

    def test_a_cache_write_of_no_recorded_lifetime_is_counted_on_its_own(self):
        used = {'input_tokens': 1, 'cache_creation_input_tokens': 700, 'cache_read_input_tokens': 0, 'output_tokens': 10}
        self.transcript('one', [answer('r1', used)])
        data = self.measured()
        self.assertEqual(data['tokens']['write_unknown'], 700)
        self.assertEqual(data['tokens_in_all'], 711)
        self.assertIn('cache writes, lifetime not recorded', short_text('wk03', data))

    def test_what_it_cannot_read_is_skipped_and_said(self):
        self.transcript('one', ['{"type": "assistant", "requestId": "r0", "mess', answer('r1', usage(read=10, out=1)),
                                answer('r2', {'input_tokens': 'many'}), {'type': 'assistant', 'message': {'content': []}}])
        data = self.measured()
        self.assertEqual(data['requests'], 1)
        self.assertEqual(data['skipped'], {'lines that are not JSON': 1, 'requests whose usage has a shape this does not know': 1,
                                           'model lines without a request id or usage': 1})
        self.assertIn('skipped, lines that are not JSON: 1', short_text('wk03', data))

    def test_the_prompt_at_the_first_and_last_request_and_its_mean(self):
        self.transcript('one', [answer('r1', usage(fresh=1, write_1h=999)), answer('r2', usage(read=1000, write_1h=500)),
                                answer('r3', usage(read=1500, write_1h=1500))])
        self.assertEqual(self.measured()['prompt'], {'first': 1000, 'last': 3000, 'mean': 1833})

    def test_a_subagent_counts_in_the_tokens_and_not_in_the_prompt(self):
        self.transcript('one', [answer('r1', usage(write_1h=1000, out=10))])
        write_transcript(self.projects / folder_name(self.worktree) / 'one' / 'subagents' / 'agent-a1.jsonl',
                         [answer('s1', usage(write_1h=50000, out=1000))])
        data = self.measured()
        self.assertEqual((data['requests'], data['sessions']), (2, 1))
        self.assertEqual(data['subagents']['requests'], 1)
        self.assertEqual(data['prompt'], {'first': 1000, 'last': 1000, 'mean': 1000})
        self.assertEqual(data['tokens_in_all'], 52_010)
        self.assertIn('of it 1 subagent: 51,000 tokens, 1 request', short_text('wk03', data))
        self.assertIn('2 requests in 1 transcript and 1 subagent transcript', short_text('wk03', data))


class FindTests(Folder):
    def test_two_transcripts_of_one_session_both_count(self):
        """One by the id its hook holds, one of a start again whose id it never kept: its hooks name the session's folder."""
        self.transcript('earlier', [answer('a1', usage(write_1h=100, out=5), stamp='2026-11-21T09:00:00Z'), hook_ran(self.hook_folder)])
        self.transcript('one', [answer('b1', usage(write_1h=300, out=7), stamp='2026-11-21T10:00:00Z')])
        data = self.measured()
        self.assertEqual(data['sessions'], 2)
        self.assertEqual(data['requests'], 2)
        self.assertEqual(data['tokens']['output'], 12)
        self.assertEqual(data['prompt']['first'], 100)    # oldest first
        self.assertIn('2 requests in 2 transcripts', short_text('wk03', data))

    def test_the_audit_beside_it_in_the_same_tree_is_not_counted(self):
        self.transcript('one', [answer('b1', usage(write_1h=300))])
        self.transcript('audit', [answer('c1', usage(write_1h=900)), hook_ran(self.hook_folder.with_name('auditwk03'))])
        self.assertEqual(self.measured()['requests'], 1)

    def test_an_id_is_found_in_any_folder(self):
        self.transcript('one', [answer('b1', usage(write_1h=300))], folder='C--elsewhere')
        self.assertEqual(self.measured()['requests'], 1)

    def test_a_request_copied_into_a_later_transcript_counts_once(self):
        self.transcript('earlier', [answer('a1', usage(write_1h=100), stamp='2026-11-21T09:00:00Z')])
        self.transcript('one', [answer('a1', usage(write_1h=100), stamp='2026-11-21T09:00:00Z'),
                                answer('b1', usage(read=100, write_1h=50), stamp='2026-11-21T10:00:00Z')])
        self.assertEqual(self.measured(ids=('earlier', 'one'))['requests'], 2)

    def test_no_transcript_found_says_so(self):
        data = self.measured(ids=('gone',))
        self.assertEqual(data['transcripts'], [])
        self.assertEqual(short_text('wk03', data), 'wk03: no transcript of it found')

    def test_an_id_that_is_no_file_name_finds_nothing(self):
        self.transcript('one', [answer('b1', usage(write_1h=300))], folder='C--elsewhere')
        self.assertEqual(self.measured(ids=('*',))['transcripts'], [])


class ContextTests(Folder):
    def rows(self, data):
        return {row['kind']: (row['added'], row['calls'], row['read_again']) for row in data['context']}

    def test_a_steps_added_tokens_go_to_the_call_before_it_times_the_requests_after_it(self):
        guide = str(self.worktree / 'docs' / 'agent' / 'guide.md')
        self.transcript('one', [
            answer('r1', usage(write_1h=1000, out=100), calls=[('Read', {'file_path': guide})]),
            answer('r2', usage(read=1000, write_1h=5100, out=50), calls=[('Bash', {'command': 'cd tree && git status'}),
                                                                       ('Bash', {'command': 'sed -n 1,20p a.txt'})]),
            answer('r3', usage(read=6100, write_1h=450, out=10)),
            answer('r4', usage(read=6550, write_1h=40)),
        ])
        rows = self.rows(self.measured())
        self.assertEqual(rows['first prompt: system text, tools, instructions'], (1000, 0, 3000))
        self.assertEqual(rows['Read docs/agent/guide.md'], (5000, 1, 10000))    # 6100 - 1000 - 100, read by r3 and r4
        self.assertEqual(rows['Bash git'], (200, 1, 200))    # 6550 - 6100 - 50, shared by the two calls of r2
        self.assertEqual(rows['Bash sed a.txt'], (200, 1, 200))
        self.assertEqual(rows['prompts and reminders, no call before'], (30, 0, 0))
        self.assertEqual(rows["the model's own output, fed back"], (160, 0, 250))

    def test_what_came_before_a_compaction_is_read_only_up_to_it(self):
        self.transcript('one', [answer('r1', usage(write_1h=1000)), answer('r2', usage(read=1000, write_1h=1000)),
                                answer('r3', usage(write_1h=300)), answer('r4', usage(read=300, write_1h=10))])
        rows = self.rows(self.measured())
        self.assertEqual(rows['first prompt: system text, tools, instructions'], (1000, 0, 1000))
        self.assertEqual(rows['the context after a compaction'], (300, 0, 300))

    def test_kinds_are_named_from_what_a_call_reads(self):
        roots = [r'C:\tree']
        self.assertEqual(tokens.kind_of_call('Read', {'file_path': r'C:\tree\docs\a.md'}, roots), 'Read docs/a.md')
        self.assertEqual(tokens.kind_of_call('Read', {'file_path': r'C:\Temp\x\tool-results\b.txt'}, roots),
                         "Read a tool's output saved to a file")
        self.assertEqual(tokens.kind_of_call('Bash', {'command': r'cd /c/x && sed -n 1,20p "C:\tree\docs\agent\guide.md"'}, roots),
                         'Bash sed docs/agent/guide.md')
        self.assertEqual(tokens.kind_of_call('PowerShell', {'command': '& "C:\\Program Files\\Git\\bin\\git.exe" log'}, roots),
                         'PowerShell git')
        self.assertEqual(tokens.kind_of_call('Bash', {'command': 'X=1 .venv/Scripts/python.exe -X utf8 t.py | head'}, roots),
                         'Bash python t.py')
        self.assertEqual(tokens.kind_of_call('Skill', {'skill': 'tia-change'}, roots), 'Skill tia-change')
        self.assertEqual(tokens.kind_of_call('mcp__tia__import', {'path': 'x'}, roots), 'mcp__tia__import')

    def test_the_fixed_prefix_by_size_from_the_last_request_shape(self):
        shape = {'system': [{'type': 'text', 'text': 'x' * 10}, {'type': 'text', 'text': 'y' * 30}],
                 'tools': [{'name': 'Small', 'description': 'a'}, {'name': 'Large', 'description': 'b' * 500}]}
        self.transcript('one', [{'type': 'api-request-shape', 'shape': {'system': [], 'tools': []}},
                                {'type': 'api-request-shape', 'shape': shape}, answer('r1', usage(write_1h=10))])
        prefix = self.measured()['prefix']
        self.assertEqual((prefix['system_characters'], prefix['system_parts'], prefix['shapes_recorded']), (40, [10, 30], 2))
        self.assertEqual([tool['name'] for tool in prefix['tools']], ['Large', 'Small'])
        text = full_text('wk03', self.measured())
        self.assertIn('system text 40 in 2 parts, 2 tools', text)

    def test_the_long_form_lists_the_kinds_and_where_the_transcripts_are(self):
        path = self.transcript('one', [answer('r1', usage(write_1h=1000, out=10), calls=[('Grep', {'pattern': 'x'})]),
                                       answer('r2', usage(read=1000, write_1h=200))])
        text = full_text('wk03', self.measured())
        self.assertIn('What entered the context, by kind', text)
        self.assertIn('Grep', text)
        self.assertIn(str(path), text)


class HookTests(unittest.TestCase):
    def test_the_hook_keeps_every_id_and_the_newest_last(self):
        with tempfile.TemporaryDirectory() as top:
            store = Store(Path(top))
            store.save({'name': 'wk03', 'ticket': 't', 'worktree': 'w', 'terminal': 'fake'})
            folder = store.folder('wk03')
            (folder / 'session-id.json').write_text('{"session_id": "before"}', encoding='utf-8')    # as a hook wrote it before
            for session_id in ('first', 'first', 'after-clear'):
                record_hook(folder, {'hook_event_name': 'Stop', 'session_id': session_id})
            self.assertEqual(store.session_ids('wk03'), ['before', 'first', 'after-clear'])
            self.assertEqual(store.session_id('wk03'), 'after-clear')


class CommandTests(Case):
    def give_transcript(self, name, session_id, request, out=100):
        record_hook(self.sessions.store.folder(name), {'hook_event_name': 'Stop', 'session_id': session_id})
        write_transcript(self.projects / folder_name(self.tree) / f'{session_id}.jsonl',
                         [answer(request, usage(write_1h=1_000_000, out=out))])

    def test_tokens_gives_the_numbers_from_the_record_of_an_open_session(self):
        self.started()
        self.give_transcript('wk03', 'id-1', 'r1')
        text = self.sessions.tokens('wk03')
        self.assertIn('wk03: 1,000,100 tokens in all, 1 request in 1 transcript, claude-opus-5-5', text)
        self.assertNotIn('$', text)
        self.assertEqual(json.loads(self.sessions.tokens('wk03', as_json=True))['requests'], 1)

    def test_tokens_of_a_session_with_no_transcript_says_where_it_looked(self):
        self.started()
        with self.assertRaisesRegex(SessionError, 'wk03: no transcript of it found. Looked for transcripts whose hooks name'):
            self.sessions.tokens('wk03')

    def test_close_prints_the_short_form_and_keeps_it(self):
        self.started()
        self.give_transcript('wk03', 'id-1', 'r1')
        said = self.sessions.close('wk03', session_only=True)
        self.assertIn('wk03: 1,000,100 tokens in all, 1 request in 1 transcript', said)
        folder = self.sessions.store.folder('wk03')
        self.assertIn('1,000,100 tokens in all', (folder / 'tokens.txt').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((folder / 'tokens.json').read_text(encoding='utf-8'))['tokens_in_all'], 1_000_100)

    def test_what_close_kept_is_shown_once_the_transcript_is_gone(self):
        self.started()
        self.give_transcript('wk03', 'id-1', 'r1')
        self.sessions.close('wk03', session_only=True)
        (self.projects / folder_name(self.tree) / 'id-1.jsonl').unlink()
        self.assertIn('no transcript of it found now. What its close kept:\nwk03: 1,000,100 tokens in all', self.sessions.tokens('wk03'))

    def test_a_close_whose_transcript_cannot_be_measured_still_closes_and_says_why(self):
        self.started()
        self.give_transcript('wk03', 'id-1', 'r1')
        with mock.patch('session.measure', side_effect=KeyError('usage')):
            said = self.sessions.close('wk03', session_only=True)
        self.assertIn("wk03: its tokens could not be read: KeyError('usage')", said)
        self.assertTrue(self.sessions.store.load('wk03').get('closed'))
        self.assertEqual(self.terminal.ended, ['wk03'])

    def test_a_close_with_no_transcript_says_so_and_still_closes(self):
        self.started()
        said = self.sessions.close('wk03', session_only=True)
        self.assertIn('wk03: no transcript of it found, no tokens kept', said)
        self.assertTrue(self.sessions.store.load('wk03').get('closed'))


class MergeTokensTests(MergeCase):
    def test_merge_prints_and_keeps_the_session_and_its_audit_once_each(self):
        self.ready()
        self.sessions.audit('wk03', terminal='fake')
        for name, session_id, request in (('wk03', 'id-1', 'r1'), ('auditwk03', 'id-2', 'r2')):
            record_hook(self.sessions.store.folder(name), {'hook_event_name': 'Stop', 'session_id': session_id})
            write_transcript(self.projects / folder_name(self.tree) / f'{session_id}.jsonl', [answer(request, usage(write_1h=500_000))])
        said = self.sessions.merge('wk03')
        lines = said.splitlines()
        self.assertEqual(lines.count('wk03: 500,000 tokens in all, 1 request in 1 transcript, claude-opus-5-5'), 1)
        self.assertEqual(lines.count('auditwk03: 500,000 tokens in all, 1 request in 1 transcript, claude-opus-5-5'), 1)
        for name in ('wk03', 'auditwk03'):
            self.assertIn('500,000 tokens in all', (self.sessions.store.folder(name) / 'tokens.txt').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
