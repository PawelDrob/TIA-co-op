"""What the hook's tests share: an environment no outer git or hook run reaches, a repo to commit in, and a cleanup that cannot finish."""
import os
import subprocess
import unittest

# The hook runs these tests; its PRE_COMMIT_ variables (an audit's PRE_COMMIT_NO_SKIP, a CI's PRE_COMMIT_JOBS) would
# reach every hook a test starts.
CLEAN_ENV = {key: value for key, value in os.environ.items() if not key.startswith(('GIT_', 'PRE_COMMIT_'))}


def init_repo(folder):
    for args in (['init', '-q', '-b', 'main'], ['config', 'user.name', 'Tester'], ['config', 'user.email', 'tester@example.com']):
        subprocess.run(['git', '-C', str(folder), *args], check=True, env=CLEAN_ENV, capture_output=True)


def errors_of_a_test_holding_a_file(test, base):
    """What a run of a case of base reports when a file in its repo stays open through its cleanup. test removes the folder afterwards."""
    class Holding(base):
        def runTest(self):
            self.held = (self.repo / 'held').open('w')

    case = Holding()
    result = unittest.TestResult()
    case.run(result)
    case.held.close()
    test.addCleanup(case.temp_folder.cleanup)
    return ''.join(text for _, text in result.errors)
