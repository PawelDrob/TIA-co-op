"""The control character check, on text and on real files in a temp folder."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_chars import describe, find, scan


class TextTests(unittest.TestCase):
    def test_clean_text_has_no_finding(self):
        self.assertEqual(find('# 06 A ticket\r\n\r\nStatus: claimed\n\tindented\n| a\t| b |\n'), [])

    def test_form_feed_in_a_path_names_the_path_it_should_be(self):
        found = find(r'see C:\Users\me\docs' + '\x0c' + r'oo\bar.md, then go')
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].line, found[0].column, found[0].char), (1, 21, '\x0c'))
        self.assertEqual(found[0].should_be, r'C:\Users\me\docs\foo\bar.md')

    def test_line_and_column_count_lines_by_line_feed_only(self):
        found = find('one\r\ntwo\x0bthree\nfour\x0c')
        self.assertEqual([(f.line, f.column) for f in found], [(2, 4), (3, 5)])

    def test_a_number_cannot_be_told_from_its_text_so_it_offers_the_forms(self):
        found = find(r'issues' + '\x01' + '-one.md')
        self.assertEqual(found[0].should_be, '')
        self.assertEqual(found[0].could_be, [r'issues\1-one.md', r'issues\01-one.md', r'issues\001-one.md'])

    def test_a_number_is_told_when_one_form_exists_on_disk(self):
        found = find(r'issues' + '\x01' + '-one.md', exists=lambda p: p == r'issues\01-one.md')
        self.assertEqual(found[0].should_be, r'issues\01-one.md')

    def test_a_tab_is_reported_only_inside_a_path(self):
        found = find(r'C:\work' + '\t' + r'ools\x.py and a' + '\t' + 'tab')
        self.assertEqual([f.should_be for f in found], [r'C:\work\tools\x.py'])

    def test_a_carriage_return_inside_a_line_is_reported(self):
        found = find('C:\\tmp\rules\\a.md\r\n')
        self.assertEqual([f.should_be for f in found], ['C:\\tmp\\rules\\a.md'])

    def test_two_in_one_path_are_both_put_back(self):
        found = find(r'C:\x' + '\x08' + 'in' + '\x0c' + 'oo')
        self.assertEqual([f.should_be for f in found], [r'C:\x\bin\foo', r'C:\x\bin\foo'])

    def test_no_word_before_it_gives_no_path(self):
        found = find('here \x0c stands alone')
        self.assertEqual((found[0].should_be, found[0].could_be), ('', []))

    def test_trailing_punctuation_stays_out_of_the_path(self):
        found = find('(`C:\\a' + '\x0c' + 'oo.md`).')
        self.assertEqual(found[0].should_be, r'C:\a\foo.md')


class NumberedTicketTests(unittest.TestCase):
    def test_a_number_that_is_also_a_letter_offers_both_forms(self):
        for char, number in (('\x07', '07'), ('\x08', '10'), ('\x0b', '13'), ('\x0c', '14'), ('\x0d', '15')):
            found = find('issues' + char + '-seven.md')
            self.assertEqual(found[0].should_be, '')
            self.assertIn('issues\\' + number + '-seven.md', found[0].could_be)

    def test_both_forms_of_seven(self):
        found = find('issues\x07-seven.md')
        self.assertEqual(found[0].could_be, [r'issues\a-seven.md', r'issues\7-seven.md', r'issues\07-seven.md', r'issues\007-seven.md'])

    def test_the_disk_tells_a_number_from_a_letter(self):
        found = find('issues\x07-exists.md', exists=lambda p: p == r'issues\07-exists.md')
        self.assertEqual(found[0].should_be, r'issues\07-exists.md')

    def test_the_disk_comes_before_the_letter_also_with_a_letter_after_it(self):
        self.assertEqual(find('issues\x07a.md', exists=lambda p: p == r'issues\07a.md')[0].should_be, r'issues\07a.md')
        self.assertEqual(find('issues\x07a.md')[0].should_be, r'issues\aa.md')

    def test_eleven_is_a_tab_before_a_dash_and_is_found(self):
        found = find('issues\t-eleven.md')
        self.assertEqual(len(found), 1)
        self.assertIn(r'issues\11-eleven.md', found[0].could_be)

    def test_a_digit_after_the_character_leaves_only_the_long_form(self):
        self.assertEqual(find('issues\x012-x.md')[0].should_be, r'issues\0012-x.md')


class NoPathToClaimTests(unittest.TestCase):
    def claims(self, text):
        found = find(text)
        self.assertEqual(len(found), 1, text)
        return found[0].should_be, found[0].could_be

    def test_nothing_after_it_is_no_path(self):
        self.assertEqual(self.claims('some text\x0c'), ('', []))

    def test_a_word_with_no_mark_of_a_path_is_no_path(self):
        self.assertEqual(self.claims('some\x0cthing'), ('', []))
        self.assertEqual(self.claims('a\x85b'), ('', []))
        self.assertEqual(self.claims('a\x01b'), ('', []))

    def test_a_web_address_is_no_path(self):
        self.assertEqual(self.claims('http://x/y\x0cfoo'), ('', []))

    def test_but_the_disk_can_still_tell(self):
        self.assertEqual(find('docs\x07gent', exists=lambda p: p == r'docs\agent')[0].should_be, r'docs\agent')

    def test_a_tab_after_a_label_or_a_web_address_is_only_a_tab(self):
        self.assertEqual(find('Status:\tdone'), [])
        self.assertEqual(find('http://x/y\tfoo'), [])

    def test_a_tab_after_a_drive_is_a_path(self):
        self.assertEqual(find('C:\tools\\x.py')[0].should_be, r'C:\tools\x.py')


class TabBesideAPathTests(unittest.TestCase):
    def test_a_tab_after_a_status_letter_is_no_claim(self):
        found = find('M\ttools/session/x.py')
        self.assertEqual(found[0].should_be, '')
        self.assertIn('M\\ttools/session/x.py', found[0].could_be)

    def test_a_tab_after_a_word_ending_in_a_file_name_is_no_claim(self):
        found = find('tools/x.py\tfound')
        self.assertEqual(found[0].should_be, '')
        self.assertIn('tools/x.py\\tfound', found[0].could_be)

    def test_the_disk_can_still_tell(self):
        found = find('M\ttools/x.py', exists=lambda p: p == 'M\\ttools/x.py')
        self.assertEqual(found[0].should_be, 'M\\ttools/x.py')

    def test_a_tab_with_a_folder_before_it_is_still_told(self):
        self.assertEqual(find('C:\\work\tools\\x.py')[0].should_be, 'C:\\work\\tools\\x.py')


class ReportTests(unittest.TestCase):
    def test_a_report_lists_every_form(self):
        found = find('issues\x07-seven.md')[0]
        self.assertIn(r'issues\007-seven.md', describe('note.md', found))


class FileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'effort' / 'issues').mkdir(parents=True)
        self.note = self.root / 'effort' / 'note.md'

    def test_scan_reads_every_markdown_file_and_names_file_and_line(self):
        self.note.write_bytes('fine\nissues\x01-one.md\n'.encode('utf-8'))
        (self.root / 'effort' / 'issues' / '01-one.md').write_text('x', encoding='utf-8')
        (self.root / 'effort' / 'other.txt').write_bytes(b'not read \x0c')
        found = scan(self.root)
        self.assertEqual([(p, f.line) for p, f in found], [(self.note, 2)])
        self.assertEqual(found[0][1].should_be, r'issues\01-one.md')

    def test_scan_of_named_files_reads_only_those(self):
        self.note.write_bytes(b'a\x0cb\n')
        other = self.root / 'other.md'
        other.write_bytes(b'c\x0cd\n')
        self.assertEqual([p for p, _ in scan(self.root, [other])], [other])

    def test_scan_changes_no_file(self):
        self.note.write_bytes(b'a\x0cb\n')
        before = self.note.stat().st_mtime_ns
        scan(self.root)
        self.assertEqual((self.note.read_bytes(), self.note.stat().st_mtime_ns), (b'a\x0cb\n', before))

    def test_bytes_that_are_not_utf8_do_not_stop_the_scan(self):
        self.note.write_bytes(b'\xff\xfe a\x0cb\n')
        self.assertEqual(len(scan(self.root)), 1)


if __name__ == '__main__':
    unittest.main()
