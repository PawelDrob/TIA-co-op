"""The coordinator's merge, on a real temp git repo: a fake hook in the repo, run by Git's sh, and a fake terminal."""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import session
from store import SessionError
from test_sessions import Case, git

BRANCH = 'feat/work-03-some-thing'
HOOK = '''#!/bin/sh
# what the tests set: each run is a line in runs, a file `fail` makes it fail, a file `then` runs once, after
echo "$(pwd) $*" >> "{top}/runs"
[ -f "{top}/then" ] && {{ mv "{top}/then" "{top}/then.now"; sh "{top}/then.now"; }}
[ -f "{top}/fail" ] && {{ echo "suite x failed"; exit 1; }}
echo "pre-commit: all passed"
'''


class MergeCase(Case):
    def setUp(self):
        super().setUp()
        for key, value in (('user.name', 't'), ('user.email', 't@example.com')):
            git(self.main, 'config', key, value)    # the merge's rebase writes commits
        (self.main / '.githooks').mkdir()
        (self.main / '.githooks' / 'pre-commit').write_text(HOOK.format(top=self.top.as_posix()), encoding='utf-8', newline='\n')
        git(self.main, 'add', '.githooks')
        git(self.main, 'commit', '-q', '-m', 'hook')

    def ready(self, ticket_head=''):
        """A started session whose branch has a commit, its ticket in-review after an audit."""
        self.started()
        (self.tree / 'b.txt').write_text('b', encoding='utf-8')
        git(self.tree, 'add', 'b.txt')
        git(self.tree, 'commit', '-q', '-m', 'work')
        self.ticket.write_text(f'# 03 Some thing\n\nType: task\nStatus: in-review\nBlocked by: none\n{ticket_head}\n## Comments\n\n'
                               'audit, 2026-11-08: pass.\n', encoding='utf-8')

    def runs(self):
        path = self.top / 'runs'
        return path.read_text(encoding='utf-8').splitlines() if path.exists() else []

    def head(self, ref):
        return git(self.main, 'rev-parse', '--short', ref).strip()


class MergeTests(MergeCase):
    def test_it_merges_records_and_closes(self):
        self.ready()
        work = self.head(BRANCH)
        said = self.sessions.merge('wk03')
        self.assertEqual(self.head('main'), work)
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(self.runs()[0].endswith(' main'))
        text = self.ticket.read_text(encoding='utf-8')
        self.assertIn('\nStatus: done\n', text)
        self.assertRegex(text.split('## Comments')[1], rf'merge, \d{{4}}-\d\d-\d\d: {work} on main')
        self.assertEqual(self.terminal.ended, ['wk03'])
        self.assertNotIn('work-03', self.trees())
        self.assertNotIn(BRANCH, self.branches())
        self.assertIn(f'merged wk03: {work} on main', said)

    def test_the_audit_session_in_the_tree_is_closed_too(self):
        self.ready()
        self.sessions.audit('wk03', terminal='fake')
        self.sessions.merge('wk03')
        self.assertEqual(sorted(self.terminal.ended), ['auditwk03', 'wk03'])
        self.assertNotIn('work-03', self.trees())
        self.assertEqual(self.sessions.store.open_sessions(), [])

    def test_a_ticket_session_closed_earlier_still_takes_the_tree_with_the_audit(self):
        self.ready()
        self.sessions.audit('wk03', terminal='fake')
        self.sessions.close('wk03', session_only=True)
        self.sessions.merge('wk03')
        self.assertEqual(sorted(self.terminal.ended), ['auditwk03', 'wk03'])
        self.assertNotIn('work-03', self.trees())

    def test_keep_tree_ends_the_sessions_and_keeps_tree_and_branch(self):
        self.ready()
        self.sessions.audit('wk03', terminal='fake')
        self.sessions.merge('wk03', keep_tree=True)
        self.assertEqual(sorted(self.terminal.ended), ['auditwk03', 'wk03'])
        self.assertIn('Status: done', self.ticket.read_text(encoding='utf-8'))
        self.assertIn('work-03', self.trees())
        self.assertIn(BRANCH, self.branches())

    def commit_on_main(self, name='c.txt', text='c'):
        (self.main / name).write_text(text, encoding='utf-8')
        git(self.main, 'add', name)
        git(self.main, 'commit', '-q', '-m', 'main moved')

    def test_a_branch_behind_main_is_rebased_first(self):
        self.ready()
        self.commit_on_main()
        said = self.sessions.merge('wk03')
        self.assertIn('rebased onto main', said)
        self.assertTrue((self.main / 'b.txt').exists() and (self.main / 'c.txt').exists())

    def test_a_rebase_that_brings_a_change_to_the_environment_syncs_the_tree_before_the_hook(self):
        self.ready()
        self.commit_on_main('uv.lock', 'new pins')
        with mock.patch.object(self.sessions, 'sync_environment', return_value='synced') as sync:
            said = self.sessions.merge('wk03')
        sync.assert_called_once()
        self.assertEqual(Path(sync.call_args.args[0]), self.tree)
        self.assertLess(said.index('synced'), said.index('hook passed'))

    def test_a_rebase_with_no_change_to_the_environment_syncs_nothing(self):
        self.ready()
        self.commit_on_main()
        with mock.patch.object(self.sessions, 'sync_environment') as sync:
            self.sessions.merge('wk03')
        sync.assert_not_called()

    def test_main_moving_during_the_hook_takes_one_more_rebase_and_hook(self):
        self.ready()
        (self.top / 'then').write_text(f'cd "{self.main.as_posix()}" && echo c > c.txt && git add c.txt && git commit -q -m moved\n',
                                       encoding='utf-8', newline='\n')
        said = self.sessions.merge('wk03')
        self.assertEqual(len(self.runs()), 2)
        self.assertIn('main moved during the hook', said)
        self.assertTrue((self.main / 'b.txt').exists() and (self.main / 'c.txt').exists())
        self.assertNotIn('work-03', self.trees())

    def assert_stopped(self, pattern, main_before):
        """Nothing merged, recorded or closed: the stop leaves tree, branch, sessions and ticket."""
        with self.assertRaisesRegex(SessionError, pattern) as caught:
            self.sessions.merge('wk03')
        self.assertIn('Tree and branch kept', str(caught.exception))
        self.assertEqual(self.head('main'), main_before)
        self.assertIn('Status: in-review', self.ticket.read_text(encoding='utf-8'))
        self.assertEqual(self.terminal.ended, [])
        self.assertIn('work-03', self.trees())
        self.assertIn(BRANCH, self.branches())

    def test_a_failing_hook_stops_it_with_its_output(self):
        self.ready()
        (self.top / 'fail').write_text('', encoding='utf-8')
        self.assert_stopped(r'hook failed[\s\S]*suite x failed', self.head('main'))

    def test_a_rebase_conflict_is_undone_and_named(self):
        self.ready()
        before = self.head(BRANCH)
        self.commit_on_main('b.txt', 'other')
        self.assert_stopped(r'rebase onto main failed and was undone, conflicts in b\.txt', self.head('main'))
        self.assertEqual(self.head(BRANCH), before)
        self.assertEqual(git(self.tree, 'status', '--porcelain'), '')
        self.assertEqual(self.runs(), [])

    def test_main_moving_twice_stops_it(self):
        self.ready()
        move = f'cd "{self.main.as_posix()}" && echo $RANDOM >> c.txt && git add c.txt && git commit -q -m moved\n'
        (self.top / 'then').write_text(f'{move}printf %s \'{move}\' > "{self.top.as_posix()}/then"\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(SessionError, 'main moved again during the second hook run'):
            self.sessions.merge('wk03')
        self.assertEqual(len(self.runs()), 2)
        self.assertNotEqual(self.head('main'), self.head(BRANCH))
        self.assertIn('Status: in-review', self.ticket.read_text(encoding='utf-8'))
        self.assertIn('work-03', self.trees())

    def test_local_changes_in_the_main_tree_stop_it_and_stay(self):
        self.ready()
        (self.main / 'b.txt').write_text('mine', encoding='utf-8')    # untracked on main, in the way of the branch's b.txt
        self.assert_stopped(r'merge --ff-only', self.head('main'))
        self.assertEqual((self.main / 'b.txt').read_text(encoding='utf-8'), 'mine')

    def test_a_ticket_not_in_review_is_refused_before_anything(self):
        self.ready()
        self.ticket.write_text(self.ticket.read_text(encoding='utf-8').replace('in-review', 'claimed'), encoding='utf-8')
        with self.assertRaisesRegex(SessionError, 'is claimed, not in-review'):
            self.sessions.merge('wk03')
        self.assertEqual(self.runs(), [])

    def test_a_main_tree_off_main_is_refused(self):
        self.ready()
        git(self.main, 'switch', '-q', '-c', 'elsewhere')
        with self.assertRaisesRegex(SessionError, 'is on elsewhere, not main'):
            self.sessions.merge('wk03')
        self.assertEqual(self.runs(), [])

    def test_uncommitted_changes_in_the_tree_are_refused(self):
        self.ready()
        (self.tree / 'b.txt').write_text('changed', encoding='utf-8')
        self.assert_stopped('holds uncommitted changes', self.head('main'))
        self.assertEqual(self.runs(), [])

    def page(self, title):
        reviews = self.scratch / 'reviews'
        reviews.mkdir(exist_ok=True)
        (reviews / f'{title}.html').write_text('<html></html>', encoding='utf-8')
        return reviews / f'{title}.html'

    def test_the_page_the_ticket_names_and_those_of_its_sessions_come_down(self):
        self.ready('Review page: 03 look\n')
        pages = [self.page('03 look'), self.page('auditwk03'), self.page('wk04')]
        said = self.sessions.merge('wk03')
        self.assertEqual([p.exists() for p in pages], [False, False, True])
        self.assertTrue((self.scratch / 'reviews' / 'done' / '03 look' / '03 look.html').exists())
        self.assertIn('page 03 look taken down', said)

    def test_a_page_already_down_is_no_stop(self):
        self.ready('Review page: 03 look\n')
        said = self.sessions.merge('wk03')
        self.assertNotIn('taken down', said)
        self.assertNotIn('work-03', self.trees())

    def test_a_close_that_refuses_after_the_merge_says_it_merged_and_what_is_left(self):
        self.ready()
        (self.tree / 'local').mkdir()
        (self.tree / 'local' / 'notes.md').write_text('x', encoding='utf-8')    # ignored: close refuses what git would delete
        with self.assertRaisesRegex(SessionError, r'merged wk03: \w+ on main[\s\S]*close wk03 failed: [\s\S]*local[\s\S]*'
                                                  r'Left to do, from the main working tree:\n  session.py close wk03$'):
            self.sessions.merge('wk03')
        self.assertEqual(self.head('main'), self.head(BRANCH))
        self.assertIn('Status: done', self.ticket.read_text(encoding='utf-8'))
        self.assertIn('work-03', self.trees())

    def command(self, *args):
        out, err = (io.TextIOWrapper(io.BytesIO(), encoding='utf-8') for _ in range(2))    # main reconfigures them
        with mock.patch.object(session, 'main_tree', return_value=self.main), \
                mock.patch.object(session, 'Sessions', return_value=self.sessions), \
                mock.patch('sys.stdout', out), mock.patch('sys.stderr', err):
            code = session.main(list(args))
        shown = []
        for stream in (out, err):
            stream.flush()
            shown.append(stream.buffer.getvalue().decode('utf-8').replace('\r\n', '\n'))
        return code, *shown

    def test_the_command_line_merges_and_exits_0(self):
        self.ready()
        code, out, err = self.command('merge', 'wk03')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('merged wk03', out)

    def test_the_command_line_stops_with_one_line_and_exits_1(self):
        self.ready()
        (self.top / 'fail').write_text('', encoding='utf-8')
        code, out, err = self.command('merge', 'wk03')
        self.assertEqual((code, out), (1, ''))
        self.assertTrue(err.startswith('session: merge wk03 stopped: the hook failed'))

    def test_a_typo_merges_nothing(self):
        self.ready()
        with self.assertRaisesRegex(SessionError, 'no session named wk3'):
            self.sessions.merge('wk3')


if __name__ == '__main__':
    unittest.main()
