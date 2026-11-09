import json
import os
import subprocess
import sys
import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, item, rect

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # TiaHmiGenerator


def run_cli(*args):
    return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'hmipreview'] + list(args), cwd=PACKAGE_ROOT,
                          capture_output=True, encoding='utf-8')


class CliTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Reference', document('screen', 'Reference', [rect('S-Panel')], Number=1))

    def test_clean_repo_exits_zero(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2))
        r = run_cli('validate', self.repo.path)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

    def test_errors_exit_non_zero_and_json_lists_the_findings(self):
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Invented', 'gauge1', Left=1, Top=90, Width=2, Height=2)], Number=2))
        r = run_cli('validate', self.repo.path, '--json')
        self.assertEqual(1, r.returncode, r.stderr)
        findings = json.loads(r.stdout)
        self.assertEqual([{'severity': 'error', 'document': path, 'object': 'gauge1',
                           'rule': 'vocabulary.element-type'}],
                         [{k: f[k] for k in ('severity', 'document', 'object', 'rule')} for f in findings])
        self.assertIn('Hmi.Screen.Invented', findings[0]['message'])

    def test_text_output_names_document_object_and_rule(self):
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Invented', 'gauge1', Left=1, Top=90, Width=2, Height=2)], Number=2))
        r = run_cli('validate', self.repo.path)
        self.assertIn('hmi/generated/screens/New.xml', r.stdout)
        self.assertIn('gauge1', r.stdout)
        self.assertIn('vocabulary.element-type', r.stdout)

    def test_warnings_alone_exit_zero(self):
        self.repo.export('screen', 'Off', document('screen', 'Off', Number=3, Width=800, Height=480))
        r = run_cli('validate', self.repo.path, '--json')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(['resolution.screen-size'], [f['rule'] for f in json.loads(r.stdout)])

    def test_import_and_override_flags_are_accepted(self):
        r = run_cli('validate', self.repo.path, '--import', '--override', '--json')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual([], json.loads(r.stdout))

    def test_missing_repo_is_a_usage_error(self):
        r = run_cli('validate', os.path.join(self.repo.path, 'nope'))
        self.assertEqual(2, r.returncode)


class UnreadableFilesTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def test_document_that_is_not_xml_is_an_error(self):
        path = self.repo.generated('screen', 'Broken', '<Document><Hmi.Screen.Screen')
        self.assertEqual([('error', 'document.parse', path)],
                         [(f.severity, f.rule, f.document) for f in validate(self.repo.path)])

    def test_data_file_that_is_not_json_is_an_error(self):
        path = self.repo.write('hmi/handbuilt.json', '[{')
        self.assertEqual([('error', 'repo.json', path)],
                         [(f.severity, f.rule, f.document) for f in validate(self.repo.path)])


if __name__ == '__main__':
    unittest.main()
