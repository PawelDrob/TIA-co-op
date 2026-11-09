"""A fresh clone: no .scratch at all, or an empty one."""
import re
import unittest

from .support import Server, made_up_repo


class EmptyCloneTest(unittest.TestCase):
    def start_page(self, scratch):
        server = Server(scratch)
        self.addCleanup(server.stop)
        return server.get('/')

    def test_no_scratch_folder_shows_what_to_do_next(self):
        text = self.start_page(made_up_repo(self) / '.scratch')
        self.assertIn('<h1>Development dashboard</h1>', text)
        self.assertIn('Nothing waits for you.', text)
        self.assertIn('No review pages are open.', text)
        self.assertIn('No tickets yet.', text)
        self.assertIn('map.md', text)
        self.assertIn('href="#reviews"', text)

    def test_the_how_to_link_opens_with_a_root_outside_any_repo(self):
        server = Server(made_up_repo(self) / '.scratch')
        self.addCleanup(server.stop)
        link = re.search(r'href="(/doc/[^"]+)"[^<]*How to use this dashboard', server.get('/')).group(1)
        self.assertIn('review_server.py', server.get(link))

    def test_no_other_document_of_the_tools_repo_opens_with_a_root_outside_it(self):
        server = Server(made_up_repo(self) / '.scratch')
        self.addCleanup(server.stop)
        self.assertEqual(server.status_code('/doc/docs/user/index.md'), 404)

    def test_empty_scratch_folder_shows_the_same(self):
        scratch = made_up_repo(self) / '.scratch'
        scratch.mkdir()
        self.assertIn('No tickets yet.', self.start_page(scratch))


if __name__ == '__main__':
    unittest.main()
