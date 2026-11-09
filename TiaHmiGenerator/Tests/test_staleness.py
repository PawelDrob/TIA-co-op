import json
import unittest
from datetime import datetime

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, group, rect

EXPORT_COMMIT = '2026-10-06T12:00:00+00:00'
COMMIT_TIME = datetime.fromisoformat(EXPORT_COMMIT).timestamp()
HOUR = 3600


def stale_findings(repo, **kw):
    return [(f.severity, f.rule, f.document) for f in validate(repo.path, **kw) if f.rule.startswith('staleness.')]


class StalenessTest(unittest.TestCase):
    def make(self, git=True):
        repo = FixtureRepo(git=git)
        self.addCleanup(repo.cleanup)
        return repo

    def exported_then_generated(self, repo, generated_at):
        """Screen S1 exported and committed at EXPORT_COMMIT, generated (mtime) at generated_at."""
        repo.export('screen', 'S1', document('screen', 'S1', [rect('r1')], Number=10))
        repo.commit('export', date=EXPORT_COMMIT)
        path = repo.generated('screen', 'S1', document('screen', 'S1', [rect('r1', left=20)], Number=10))
        repo.touch(path, generated_at)
        return path

    def test_export_committed_after_generation_is_a_warning_in_the_preview(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME - HOUR)
        self.assertEqual([('warning', 'staleness.export-newer', path)], stale_findings(repo))

    def test_an_export_that_differs_only_in_the_order_counts_as_a_tia_change(self):
        repo = self.make()
        repo.export('screen', 'S1', document('screen', 'S1', [rect('r1'), rect('r2')], Number=10))
        repo.commit('export', date=EXPORT_COMMIT)
        path = repo.generated('screen', 'S1', document('screen', 'S1', [rect('r2'), rect('r1')], Number=10))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([('warning', 'staleness.export-newer', path)], stale_findings(repo))

    def test_an_export_that_differs_only_in_the_groups_counts_as_a_tia_change(self):
        a, x, y = rect('a'), rect('x'), rect('y')
        repo = self.make()
        repo.export('screen', 'S1', document('screen', 'S1', [group('g1', a, x), group('g2', y)], Number=10))
        repo.commit('export', date=EXPORT_COMMIT)
        path = repo.generated('screen', 'S1', document('screen', 'S1', [group('g1', x), group('g2', a, y)], Number=10))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([('error', 'staleness.export-newer', path)], stale_findings(repo, for_import=True))

    def test_recorded_generation_time_wins_over_a_newer_mtime(self):
        # A checkout gives the file a fresh mtime; the time the generator recorded still says it is older.
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME + HOUR)
        repo.write('hmi/generated/generated.json',
                   json.dumps({path: {'generated': '2026-10-06T13:00:00+02:00'}}))      # 11:00 UTC, before the commit
        self.assertEqual([('warning', 'staleness.export-newer', path)], stale_findings(repo))

    def test_recorded_generation_time_wins_over_an_older_mtime(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME - HOUR)
        repo.write('hmi/generated/generated.json', json.dumps({path: {'generated': '2026-10-06T13:00:00+00:00'}}))
        self.assertEqual([], stale_findings(repo))

    def test_document_without_a_recorded_time_falls_back_to_the_mtime(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME - HOUR)
        repo.write('hmi/generated/generated.json', json.dumps({'hmi/generated/screens/Other.xml':
                                                               {'generated': '2026-10-06T13:00:00+00:00'}}))
        self.assertEqual([('warning', 'staleness.export-newer', path)], stale_findings(repo))

    def test_export_equal_to_the_generated_document_is_not_stale(self):
        # The normal round trip (project B 2026-10-06): import, export again, commit. The export is newer, but TIA
        # changed nothing, so there is nothing an import would overwrite.
        repo = self.make()
        repo.export('screen', 'S1', document('screen', 'S1', [rect('r1', left=20)], Number=10))
        repo.commit('export', date=EXPORT_COMMIT)
        path = repo.generated('screen', 'S1', document('screen', 'S1', [rect('r1', left=20)], Number=10))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([], stale_findings(repo))
        self.assertEqual([], stale_findings(repo, for_import=True))

    def test_generated_after_the_export_commit_is_fine(self):
        repo = self.make()
        self.exported_then_generated(repo, COMMIT_TIME + HOUR)
        self.assertEqual([], stale_findings(repo))
        self.assertEqual([], stale_findings(repo, for_import=True))

    def test_stale_document_is_an_error_at_import(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME - HOUR)
        self.assertEqual([('error', 'staleness.export-newer', path)], stale_findings(repo, for_import=True))

    def test_override_turns_the_import_error_back_into_a_warning(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME - HOUR)
        self.assertEqual([('warning', 'staleness.export-newer', path)],
                         stale_findings(repo, for_import=True, override=True))

    def test_latest_commit_of_the_export_counts(self):
        repo = self.make()
        path = self.exported_then_generated(repo, COMMIT_TIME + HOUR)
        repo.export('screen', 'S1', document('screen', 'S1', [rect('r1'), rect('r2')], Number=10))
        repo.commit('export again', date='2026-10-06T15:00:00+00:00')
        repo.touch(path, COMMIT_TIME + HOUR)       # the commit must not have touched the generated file
        self.assertEqual([('warning', 'staleness.export-newer', path)], stale_findings(repo))

    def test_generated_document_without_an_export_is_never_stale(self):
        repo = self.make()
        repo.export('screen', 'Other', document('screen', 'Other', Number=10))
        repo.commit('export', date=EXPORT_COMMIT)
        path = repo.generated('screen', 'New', document('screen', 'New', Number=11))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([], stale_findings(repo, for_import=True))

    def test_uncommitted_export_is_not_compared(self):
        repo = self.make()
        repo.export('screen', 'S1', document('screen', 'S1', Number=10))
        path = repo.generated('screen', 'S1', document('screen', 'S1', Number=10))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([], stale_findings(repo, for_import=True))

    def test_repo_without_git_is_not_compared(self):
        repo = self.make(git=False)
        repo.export('screen', 'S1', document('screen', 'S1', Number=10))
        path = repo.generated('screen', 'S1', document('screen', 'S1', Number=10))
        repo.touch(path, COMMIT_TIME - HOUR)
        self.assertEqual([], stale_findings(repo, for_import=True))

    def test_every_generated_kind_is_checked(self):
        repo = self.make()
        repo.export('popup', 'P1', document('popup', 'P1'))
        repo.export('template', 'T1', document('template', 'T1'))
        repo.commit('export', date=EXPORT_COMMIT)
        p = repo.generated('popup', 'P1', document('popup', 'P1', [rect('r1')]))
        t = repo.generated('template', 'T1', document('template', 'T1', [rect('r1')]))
        repo.touch(p, COMMIT_TIME - HOUR)
        repo.touch(t, COMMIT_TIME - HOUR)
        self.assertEqual([('warning', 'staleness.export-newer', p), ('warning', 'staleness.export-newer', t)],
                         stale_findings(repo))


if __name__ == '__main__':
    unittest.main()
