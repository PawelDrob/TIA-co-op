"""The temporary folders of these tests really go, and one that cannot go fails its test."""
import os
import shutil
import stat
import unittest

from .fakes import tempdir


class Cleanup(unittest.TestCase):
    def test_a_folder_with_read_only_files_goes_with_the_test(self):
        class Using(unittest.TestCase):
            def runTest(self):
                self.folder = tempdir(self)
                path = os.path.join(self.folder, 'object')      # read-only, as git's object files are
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('made up')
                os.chmod(path, stat.S_IREAD)

        case = Using()
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual(result.errors, [])
        self.assertFalse(os.path.exists(case.folder))

    def test_a_folder_that_cannot_go_fails_the_test(self):
        class Holding(unittest.TestCase):
            def runTest(self):
                self.folder = tempdir(self)
                self.held = open(os.path.join(self.folder, 'held'), 'w', encoding='utf-8')

        case = Holding()
        result = unittest.TestResult()
        case.run(result)
        case.held.close()
        self.addCleanup(shutil.rmtree, case.folder)
        self.assertIn('held', ''.join(text for _, text in result.errors))
