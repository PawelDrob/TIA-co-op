"""The window's git mode without a window: the repo and its two commits, what goes to the runner, and what the result says
of a report that sees only exports. No process and no git: the commits are made up here."""
import json
import unittest
from datetime import datetime, timedelta

from TiaArchiveCompare.runner.gitrepo import Commit
from TiaArchiveCompare.window.model import CommitChoice, RunModel, RunOptions, commit_label, runner_arguments

NEW = Commit('c' * 40, 'ccccccc', '2026-11-03 16:40', 'H003 Pump: start delay')
MID = Commit('b' * 40, 'bbbbbbb', '2026-11-02 09:05', 'H002 Conveyor: new alarm')
OLD = Commit('a' * 40, 'aaaaaaa', '2026-11-01 11:00', 'H001 First export')
T0 = datetime(2026, 11, 5, 8, 0, 0)


class Picking(unittest.TestCase):
    def test_a_commit_shows_by_short_hash_date_and_message(self):
        self.assertEqual('ccccccc  2026-11-03 16:40  H003 Pump: start delay', commit_label(NEW))

    def test_a_repo_starts_on_its_last_change(self):
        c = CommitChoice()
        c.set_repo('D:\\Repos\\Line7', [NEW, MID, OLD])
        self.assertEqual(('bbbbbbb', 'ccccccc'), (c.before, c.after))
        self.assertEqual([commit_label(x) for x in (NEW, MID, OLD)], c.labels)

    def test_picking_from_the_list(self):
        c = CommitChoice()
        c.set_repo('D:\\Repos\\Line7', [NEW, MID, OLD])
        c.pick(True, 2)
        c.pick(False, 1)
        self.assertEqual(('aaaaaaa', 'bbbbbbb'), (c.before, c.after))
        self.assertEqual(commit_label(OLD), c.label_of(c.before))

    def test_a_repo_with_a_problem_leaves_nothing_chosen(self):
        c = CommitChoice()
        c.set_repo('D:\\Repos\\Line7', [NEW, MID])
        c.set_repo('D:\\plain', [], 'D:\\plain is no git repo.')
        self.assertEqual(('', '', []), (c.before, c.after, c.labels))
        self.assertEqual('D:\\plain is no git repo.', c.problem)

    def test_what_goes_to_the_runner(self):
        c = CommitChoice()
        c.set_repo('D:\\Repos\\Line7', [NEW, MID, OLD])
        self.assertEqual('Line7: bbbbbbb vs ccccccc', c.default_title())
        o = c.options()
        self.assertEqual((True, 'D:\\Repos\\Line7', 'bbbbbbb', 'ccccccc'), (o.from_commits, o.repo, o.before, o.after))

    def test_a_revision_named_on_the_command_line(self):
        c = CommitChoice()
        c.set_repo('D:\\Repos\\Line7', [NEW, MID, OLD])
        c.name_commits('a' * 12, 'HEAD')
        self.assertEqual(commit_label(OLD), c.label_of(c.before))       # the list's line for a longer hash
        self.assertEqual('HEAD', c.label_of(c.after))                   # git knows it, the list does not name it
        self.assertEqual(('a' * 12, 'HEAD'), (c.before, c.after))


class Sent(unittest.TestCase):
    def options(self, **kw):
        return RunOptions(from_commits=True, **{'repo': 'D:\\Repos\\Line 7', 'before': 'aaaaaaa', 'after': 'ccccccc', **kw})

    def test_the_arguments_are_the_repo_and_the_commits_alone(self):
        o = self.options(title='Line 7', compile=True, safety=True, hmi=True, no_cache=True)
        self.assertEqual(['run', '--git', 'D:\\Repos\\Line 7', '--before', 'aaaaaaa', '--after', 'ccccccc', '--title', 'Line 7'],
                         runner_arguments(['run'], o))

    def test_what_is_missing_is_said(self):
        self.assertEqual('Choose the git repo.', self.options(repo='').validate())
        self.assertEqual('Choose the before commit.', self.options(before='').validate())
        self.assertEqual('Choose the after commit.', self.options(after='').validate())
        self.assertEqual('Before and after are the same commit.', self.options(after='aaaaaaa').validate())
        self.assertIsNone(self.options().validate())

    def test_a_commit_is_no_path_to_look_for(self):
        self.assertIsNone(RunOptions(from_commits=True, repo='D:\\gone', before='a', after='b').validate())


class TheResult(unittest.TestCase):
    """A result must not read as complete: a change never exported is not in the report."""

    def ended(self, from_commits, **end):
        m = RunModel()
        m.start(T0, from_commits)
        m.apply(json.dumps({'t': 'end', 'ok': True, 'report': 'D:\\r\\report.html', **end}), T0 + timedelta(seconds=2))
        return m

    def test_no_changes_says_in_what(self):
        self.assertEqual('Done in 2.0 s: no changes in what was exported and committed.',
                         self.ended(True, changed=0).result_line())

    def test_an_archive_run_reads_as_before(self):
        m = self.ended(False, changed=0)
        self.assertEqual('Done in 2.0 s: no changes.', m.result_line())
        self.assertEqual('Not in the report: nothing', m.not_exported_heading())

    def test_the_list_never_says_nothing(self):
        self.assertEqual('Not in the report: whatever was never exported and committed',
                         self.ended(True, changed=2).not_exported_heading())
        items = [{'name': 'x.xml', 'why': 'the report could not read it: y'}]
        self.assertEqual('Not in the report (1), and whatever was never exported and committed',
                         self.ended(True, changed=2, not_exported=items).not_exported_heading())

    def test_a_cancel_speaks_of_no_tia(self):
        m = RunModel()
        m.start(T0, True)
        m.apply(json.dumps({'t': 'end', 'ok': False, 'cancelled': True}), T0 + timedelta(seconds=2))
        self.assertEqual('Cancelled after 2.0 s. No report was written.', m.result_line())

    def test_stop_now_speaks_of_no_tia(self):
        m = RunModel()
        m.start(T0, True)
        m.stopped(T0 + timedelta(seconds=2))
        self.assertEqual('Stopped after 2.0 s: the runner was ended. No report was written.', m.result_line())

    def test_stop_now_and_closing_speak_of_tia_only_with_archives(self):
        m = RunModel()
        m.start(T0, True)
        self.assertEqual('The runner did not end within 120 s of the cancel. Stop now ends the runner.', m.stop_now_offer())
        self.assertEqual('A comparison is running. Cancel it and close the window once it has ended?', m.close_question())
        m.start(T0, False)
        self.assertEqual('The runner did not end within 120 s of the cancel. Stop now ends the runner and TIA.', m.stop_now_offer())
        self.assertEqual('A comparison is running. Cancel it and close the window once TIA is closed?', m.close_question())

    def test_a_failed_run_has_no_list_to_speak_of(self):
        m = RunModel()
        m.start(T0, True)
        m.apply(json.dumps({'t': 'end', 'ok': False, 'error': 'x'}), T0)
        self.assertEqual('Not in the report', m.not_exported_heading())


if __name__ == '__main__':
    unittest.main()
