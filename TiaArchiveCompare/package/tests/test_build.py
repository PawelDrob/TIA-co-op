"""What the build puts into the download, and the version it is built for. No download, no uv, no PowerShell: the
build itself runs by hand or in the release workflow, and its check (check.py) proves the zip."""
import os
import shutil
import tempfile
import unittest

from TiaArchiveCompare.package import build


class WhatGoesIn(unittest.TestCase):
    def test_the_tools_the_runner_calls_and_the_legal_files(self):
        tracked = ['LICENSE', 'NOTICE', 'TiaArchiveCompare/README.md', 'TiaArchiveCompare/runner/run.py',
                   'TiaArchiveCompare/runner/samples/Plant_2026-09-01.zap20', 'TiaArchiveCompare/window/main_window.py',
                   'TiaChangeReports/__main__.py', 'TiaHmiGenerator/hmipreview/static/app.js',
                   'TiaHmiGenerator/catalogue/catalogue.json', 'TiaBridge/TiaBridge.ps1', 'TiaBridge/Tools/FullExport.ps1']
        self.assertEqual(tracked, build.package_files(tracked))

    def test_no_tests_but_the_plant_the_fake_exporter_plays(self):
        tracked = ['TiaArchiveCompare/runner/tests/test_runner.py', 'TiaArchiveCompare/window/tests/check.py',
                   'TiaBridge/Tests/Smoke.ps1', 'TiaHmiGenerator/Tests/test_diff.py',
                   'TiaChangeReports/tests/test_change_reports.py', 'TiaChangeReports/tests/fixtures/new-block/a.xml',
                   'TiaChangeReports/tests/fixtures/plant/v1/plc/types/Recipe.s7dcl']
        self.assertEqual(['TiaChangeReports/tests/fixtures/plant/v1/plc/types/Recipe.s7dcl'], build.package_files(tracked))

    def test_nothing_of_the_rest_of_the_repo(self):
        tracked = ['README.md', 'AGENTS.md', 'pyproject.toml', 'docs/user/setup.md', 'tools/setup/setup.ps1',
                   'TiaAgentStatus/statusline.py', '.claude/skills/ticket/SKILL.md', '.githooks/pre-commit',
                   'TiaArchiveCompare/.gitignore', 'TiaArchiveCompare/package/build.py']
        self.assertEqual([], build.package_files(tracked))


class TheVersion(unittest.TestCase):
    def repo(self, runner, bridge):
        root = tempfile.mkdtemp(prefix='tia-compare-version-')
        self.addCleanup(shutil.rmtree, root, True)
        for path, text in (('TiaArchiveCompare/runner/__init__.py', '"""The runner."""\n\nVERSION = \'%s\'\n' % runner),
                           ('TiaBridge/Mcp.ps1', "# Mcp.ps1\n\n$script:McpServerName = 'tia'\n"
                                                 "$script:McpServerVersion = '%s'\n" % bridge)):
            os.makedirs(os.path.join(root, os.path.dirname(path)), exist_ok=True)
            with open(os.path.join(root, path), 'w', encoding='utf-8') as f:
                f.write(text)
        return root

    def test_the_one_of_the_runner_and_the_bridge(self):
        self.assertEqual('0.3.1', build.version(self.repo('0.3.1', '0.3.1')))
        self.assertEqual('TIA-Archive-Compare-0.3.1', build.package_name('0.3.1'))

    def test_the_tag_names_it(self):
        self.assertEqual('0.3.1', build.version(self.repo('0.3.1', '0.3.1'), tag='v0.3.1'))
        with self.assertRaisesRegex(build.BuildError, 'The tag v0.3.2 is not v0.3.1'):
            build.version(self.repo('0.3.1', '0.3.1'), tag='v0.3.2')

    def test_the_runner_and_the_bridge_must_agree(self):
        with self.assertRaisesRegex(build.BuildError, 'The versions differ: 0.3.1 in .*0.3.0 in TiaBridge'):
            build.version(self.repo('0.3.1', '0.3.0'))

    def test_this_repo_agrees_with_itself(self):
        build.version()


if __name__ == '__main__':
    unittest.main()
