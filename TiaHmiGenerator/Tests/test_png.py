"""Agent PNGs: python -m hmipreview png <repo> <screen> <out.png> takes a headless Edge (else Chrome) screenshot of the preview page
at device resolution. Checked by the PNG header (size), no pixel comparison. Skipped when neither is installed."""
import os
import struct
import unittest

from Tests.browser import NOT_FOUND, edge_path
from Tests.fixture import FixtureRepo, document, rect
from Tests.test_diff import run_cli

EDGE = edge_path()


def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        raise AssertionError('not a PNG: %r' % head[:16])
    return struct.unpack('>II', head[16:24])


@unittest.skipUnless(EDGE, NOT_FOUND)
class PngCommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)
        self.out = os.path.join(self.repo.path, 'out', 'shot.png')

    def test_screen_at_the_device_resolution(self):
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))

        r = run_cli('png', self.repo.path, 'Silo', self.out)

        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual((1280, 800), png_size(self.out))
        self.assertIn(os.path.abspath(self.out), r.stdout)

    def test_portrait_panel(self):
        repo = FixtureRepo(type_identifier='OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0//Portrait')
        self.addCleanup(repo.cleanup)
        repo.export('screen', 'Tall', document('screen', 'Tall', [rect('r1')], Number=1, Width=800, Height=1280))
        out = os.path.join(repo.path, 'tall.png')

        r = run_cli('png', repo.path, 'Tall', out)

        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual((800, 1280), png_size(out))

    def test_popup_at_its_own_size(self):
        self.repo.generated('popup', 'Confirm', document('popup', 'Confirm', [rect('r1', top=10)],
                                                         Width=400, Height=240))

        r = run_cli('png', self.repo.path, 'Confirm', self.out, '--kind', 'popup')

        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual((400, 240), png_size(self.out))

    def test_unknown_screen_writes_nothing(self):
        r = run_cli('png', self.repo.path, 'Nope', self.out)

        self.assertEqual(1, r.returncode)
        self.assertIn('Nope', r.stderr)
        self.assertFalse(os.path.exists(self.out))


if __name__ == '__main__':
    unittest.main()
