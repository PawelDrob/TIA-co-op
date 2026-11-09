"""The manual tray check's hold on a dashboard it started: nothing here shows on a desktop."""
import ctypes
import subprocess
import sys
import unittest

from . import tray_check


class DashboardRights(unittest.TestCase):
    def test_they_end_a_dashboard_its_menu_did_not_stop(self):
        """stop_by_menu ends it with TerminateProcess when the menu fails, and waits, so that it holds nothing in the check's folder."""
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        handle = tray_check.kernel32.OpenProcess(tray_check.DASHBOARD_RIGHTS, False, child.pid)
        self.assertTrue(handle)
        self.addCleanup(ctypes.WinDLL('kernel32').CloseHandle, ctypes.c_void_p(handle))
        self.assertTrue(tray_check.kernel32.TerminateProcess(handle, 1), f'error {ctypes.get_last_error()}')
        self.assertEqual(tray_check.kernel32.WaitForSingleObject(handle, 5000), 0)


if __name__ == '__main__':
    unittest.main()
