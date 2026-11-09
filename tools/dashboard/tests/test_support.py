"""The made-up repos of these tests really go, and one that cannot go fails its test."""
import os
import shutil
import stat
import unittest

from .support import class_repo, made_up_repo


def read_only_file(folder):
    """As git's object files are: on Windows rmtree cannot delete one."""
    path = folder / 'object'
    path.write_text('made up', encoding='utf-8')
    os.chmod(path, stat.S_IREAD)


class Cleanup(unittest.TestCase):
    def test_a_repo_goes_with_its_test(self):
        class Using(unittest.TestCase):
            def runTest(self):
                self.repo = made_up_repo(self)
                read_only_file(self.repo)

        case = Using()
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual(result.errors, [])
        self.assertFalse(case.repo.exists())

    def test_a_repo_goes_with_its_class(self):
        class Using(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.repo = class_repo(cls)
                read_only_file(cls.repo)

            def test_nothing(self):
                pass

        result = unittest.TestResult()
        unittest.TestSuite([Using('test_nothing')]).run(result)
        self.assertEqual(result.errors, [])
        self.assertFalse(Using.repo.exists())

    def test_a_repo_that_cannot_go_fails_the_test(self):
        class Holding(unittest.TestCase):
            def runTest(self):
                self.repo = made_up_repo(self)
                self.held = (self.repo / 'held').open('w')

        case = Holding()
        result = unittest.TestResult()
        case.run(result)
        case.held.close()
        self.addCleanup(shutil.rmtree, case.repo)
        self.assertIn('held', ''.join(text for _, text in result.errors))
