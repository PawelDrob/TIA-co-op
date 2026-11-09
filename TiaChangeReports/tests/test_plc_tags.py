"""PLC tag tables on the page (plctags.py): plc/tags/*.xml of a --git repo or of two folders, per PLC and table, tags and
user constants added, removed and changed in TIA's columns. Made-up samples, in the shape of a real export."""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from TiaChangeReports.tests.test_change_reports import RES, SRC, _git, _put


def comment_xml(*texts):
    items = ''.join('<MultilingualTextItem ID="9" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                    '<Text>%s</Text></AttributeList></MultilingualTextItem>' % t for t in texts)
    return ('<ObjectList><MultilingualText ID="8" CompositionName="Comment"><ObjectList>%s</ObjectList>'
            '</MultilingualText></ObjectList>' % (items or '<MultilingualTextItem ID="9" CompositionName="Items">'
                                                  '<AttributeList><Culture>en-US</Culture><Text /></AttributeList>'
                                                  '</MultilingualTextItem>'))


def tag(name, address='%M0.0', typ='Bool', comment='', acc='true', wr='true', vis='true', extra='', texts=None):
    return ('<SW.Tags.PlcTag ID="1" CompositionName="Tags"><AttributeList><DataTypeName>%s</DataTypeName>'
            '<ExternalAccessible>%s</ExternalAccessible><ExternalVisible>%s</ExternalVisible><ExternalWritable>%s'
            '</ExternalWritable><LogicalAddress>%s</LogicalAddress><Name>%s</Name>%s</AttributeList>%s</SW.Tags.PlcTag>'
            % (typ, acc, vis, wr, address, name, extra,
               comment_xml(*(texts or ([('en-US', comment)] if comment else [])))))


def const(name, value='1', typ='Int', comment=''):
    return ('<SW.Tags.PlcUserConstant ID="2" CompositionName="UserConstants"><AttributeList><DataTypeName>%s'
            '</DataTypeName><Name>%s</Name><Value>%s</Value></AttributeList>%s</SW.Tags.PlcUserConstant>'
            % (typ, name, value, comment_xml(*([('en-US', comment)] if comment else []))))


def table(name, *items, created='2026-10-06T00:00:00Z'):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" /><DocumentInfo><Created>%s'
            '</Created><ExportSetting>WithDefaults</ExportSetting></DocumentInfo><SW.Tags.PlcTagTable ID="0"><AttributeList>'
            '<Name>%s</Name></AttributeList>%s</SW.Tags.PlcTagTable></Document>\n'
            % (created, name, '<ObjectList>%s</ObjectList>' % ''.join(items) if items else ''))


class Report(unittest.TestCase):
    """Two commits of a made-up repo, the report over them."""

    def repo(self, one, two):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.dir = r = os.path.join(tmp.name, 'Plant')
        os.makedirs(r)
        _git(r, 'init', '-q')
        _git(r, 'config', 'core.autocrlf', 'false')
        _put(r, one)
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'one')
        for path in one:
            if path not in two:
                os.remove(os.path.join(r, path))
        _put(r, two)
        _git(r, 'add', '-A')
        _git(r, 'commit', '-q', '-m', 'two', '--allow-empty')
        return r

    def main(self, *args):
        from TiaChangeReports.__main__ import main
        page = os.path.join(self.tmp, 'out', 'page.html')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--git', self.dir, 'HEAD~1', 'HEAD', '-o', page] + list(args))
        self.assertEqual(0, code, err.getvalue())
        self.stderr = err.getvalue()
        with open(page, encoding='utf-8') as f:
            return out.getvalue(), f.read()

    def report(self, one, two, *args):
        """(the plcTags of --json, the page, the list)."""
        self.repo(one, two)
        res = json.loads(self.main('--json', *args)[0])
        self.res = res
        listing, html = self.main(*args)
        return res.get('plcTags', []), html, listing


T = 'plc/tags/Plant.xml'


class TagsChanged(Report):

    def test_a_tag_added_is_on_the_page_not_no_changes(self):
        tags, html, listing = self.report({T: table('Plant', tag('run', '%M1.0'))},
                                          {T: table('Plant', tag('run', '%M1.0'), tag('stop', '%M900.0'))})
        self.assertNotIn('No changes.', html)
        self.assertEqual(['Plant'], [t['name'] for t in tags])
        self.assertEqual('changed', tags[0]['state'])
        self.assertEqual([('tag', 'stop', 'added')], [(r['kind'], r['name'], r['state']) for r in tags[0]['rows']])
        self.assertEqual('%M900.0', tags[0]['rows'][0]['after']['address'])
        self.assertIn('plctagtable Plant', listing)
        self.assertIn('    added    tag      stop', listing)
        self.assertIn('stop', html)

    def test_a_removed_tag(self):
        tags, _, _ = self.report({T: table('Plant', tag('run', '%M1.0'), tag('stop', '%M2.0'), tag('end', '%M3.0'))},
                                 {T: table('Plant', tag('run', '%M1.0'), tag('end', '%M3.0'))})
        self.assertEqual([('stop', 'removed')], [(r['name'], r['state']) for r in tags[0]['rows']])
        self.assertIsNone(tags[0]['rows'][0]['after'])
        self.assertEqual('%M2.0', tags[0]['rows'][0]['before']['address'])

    def test_a_moved_address_reads_as_one_tag_with_both_addresses(self):
        tags, html, listing = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('run', '%M7.3'))})
        row = tags[0]['rows'][0]
        self.assertEqual(('changed', ['address']), (row['state'], row['changes']))
        self.assertEqual(('%M1.0', '%M7.3'), (row['before']['address'], row['after']['address']))
        self.assertIn('address %M1.0 -> %M7.3', listing)
        body = section(html, 'Plant')
        cell = re.search(r'<span class="tx del">.*?</td>', body).group()
        self.assertEqual('%M1.0 %M7.3', re.sub(r'<[^>]+>', '', cell))
        self.assertIn('<span class="tx ins">', cell)

    def test_a_renamed_tag_is_one_tag_by_its_address(self):
        tags, html, listing = self.report({T: table('Plant', tag('run', '%M1.0'), tag('stop', '%M2.0'))},
                                          {T: table('Plant', tag('running', '%M1.0'), tag('stop', '%M2.0'))})
        self.assertEqual([('running', 'changed', ['name'], 'run')],
                         [(r['name'], r['state'], r['changes'], r['was']) for r in tags[0]['rows']])
        self.assertIn('running  (was "run")', listing)
        self.assertEqual(1, section(html, 'Plant').count('class="chg"'))
        self.assertNotIn('class="ins"', section(html, 'Plant'))

    def test_renamed_with_another_address_is_removed_and_added(self):
        tags, _, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('going', '%M5.0'))})
        self.assertEqual([('going', 'added'), ('run', 'removed')],
                         sorted((r['name'], r['state']) for r in tags[0]['rows']))

    def test_two_left_tags_on_one_address_are_not_guessed_at(self):
        tags, _, _ = self.report({T: table('Plant', tag('a', '%M1.0'), tag('b', '%M1.0'))},
                                 {T: table('Plant', tag('c', '%M1.0'))})
        self.assertEqual([('a', 'removed'), ('b', 'removed'), ('c', 'added')],
                         sorted((r['name'], r['state']) for r in tags[0]['rows']))

    def test_type_comment_and_boxes(self):
        tags, html, _ = self.report(
            {T: table('Plant', tag('run', '%MW2', 'Int', 'old text'))},
            {T: table('Plant', tag('run', '%MW2', 'Word', 'new text', acc='false', wr='false', vis='false'))})
        row = tags[0]['rows'][0]
        self.assertEqual(['accessible', 'comment', 'type', 'visible', 'writable'], row['changes'])
        self.assertEqual(('Int', 'Word'), (row['before']['type'], row['after']['type']))
        self.assertEqual((True, False), (row['before']['accessible'], row['after']['accessible']))
        self.assertEqual(('old text', 'new text'), (row['before']['comment'], row['after']['comment']))
        body = section(html, 'Plant')
        for head in ('Name', 'Data type', 'Address', 'Accessible from HMI/OPC UA', 'Writable from HMI/OPC UA',
                     'Visible in HMI engineering', 'Comment'):
            self.assertIn('>%s</td>' % head, body)
        self.assertIn('<span class="cb on"></span>', body)     # ticked before
        self.assertIn('<span class="cb"></span>', body)        # not after
        self.assertIn('<span class="cb dis"></span>', body)    # TIA grays the boxes of a tag not accessible

    def test_an_absent_box_is_ticked_as_a_new_tag(self):
        written = ('<SW.Tags.PlcTag ID="1" CompositionName="Tags"><AttributeList><DataTypeName>Bool</DataTypeName>'
                   '<LogicalAddress>%M1.0</LogicalAddress><Name>run</Name></AttributeList></SW.Tags.PlcTag>')
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', written)})
        self.assertEqual([], tags)
        self.assertIn('No changes.', html)

    def test_unchanged_tags_are_folded_in_place(self):
        tags, html, _ = self.report({T: table('Plant', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'), tag('d', '%M4.0'))},
                                    {T: table('Plant', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'), tag('d', '%M9.0'))})
        self.assertEqual(['d'], [r['name'] for r in tags[0]['rows']])
        body = section(html, 'Plant')
        self.assertIn('3 unchanged tags', body)
        self.assertEqual(3, body.count('class="ctx"'))

    def test_a_tag_out_of_the_common_order_reads_moved(self):
        tags, html, _ = self.report({T: table('Plant', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'))},
                                    {T: table('Plant', tag('c', '%M3.0'), tag('a', '%M1.0'), tag('b', '%M2.0'))})
        self.assertEqual([('c', 'moved', {'before': 'after b', 'after': 'first'})],
                         [(r['name'], r['state'], r['order']) for r in tags[0]['rows']])
        self.assertIn('order: was after b, now first', section(html, 'Plant'))
        self.assertIn('class="mov"', section(html, 'Plant'))

    def test_names_are_escaped(self):
        tags, html, _ = self.report({T: table('A&amp;B', tag('x', '%M1.0'))},
                                    {T: table('A&amp;B', tag('x', '%M1.0', '"My&lt;Type&gt;"'))})
        self.assertEqual('A&B', tags[0]['name'])
        self.assertEqual('"My<Type>"', tags[0]['rows'][0]['after']['type'])
        self.assertIn('&lt;', section(html, 'A&amp;B'))
        self.assertNotIn('My<Type>', html)


class UserConstants(Report):

    def test_shown_as_tags_are_in_their_own_columns(self):
        tags, html, listing = self.report(
            {T: table('Plant', tag('run', '%M1.0'), const('LIMIT', '10'), const('GONE', '3'))},
            {T: table('Plant', tag('run', '%M1.0'), const('LIMIT', '20', comment='the most'), const('NEW', '7', 'DInt'))})
        rows = {r['name']: r for r in tags[0]['rows']}
        self.assertEqual({'LIMIT', 'NEW', 'GONE'}, set(rows))
        self.assertEqual(('constant', 'changed', ['comment', 'value']),
                         (rows['LIMIT']['kind'], rows['LIMIT']['state'], rows['LIMIT']['changes']))
        self.assertEqual(('10', '20'), (rows['LIMIT']['before']['value'], rows['LIMIT']['after']['value']))
        self.assertEqual(('added', 'DInt'), (rows['NEW']['state'], rows['NEW']['after']['type']))
        self.assertEqual('removed', rows['GONE']['state'])
        self.assertNotIn('accessible', rows['NEW']['after'])
        body = section(html, 'Plant')
        self.assertIn('<b>User constants</b>', body)
        self.assertNotIn('<b>PLC tags</b>', body)              # no tag changed: that list has no row to show
        self.assertIn('>Value</td>', body)
        self.assertNotIn('Accessible', body)
        self.assertIn('value 10 -> 20', listing)

    def test_a_renamed_constant_by_its_type_and_value(self):
        tags, _, _ = self.report({T: table('Plant', const('OLD', '5'))}, {T: table('Plant', const('NEW', '5'))})
        self.assertEqual([('NEW', 'changed', 'OLD')], [(r['name'], r['state'], r['was']) for r in tags[0]['rows']])

    def test_a_tag_and_a_constant_of_one_name_are_two(self):
        tags, _, _ = self.report({T: table('Plant', tag('x', '%M1.0'))}, {T: table('Plant', const('x', '1'))})
        self.assertEqual([('tag', 'removed'), ('constant', 'added')],
                         sorted(((r['kind'], r['state']) for r in tags[0]['rows']), reverse=True))


class Tables(Report):

    def test_listed_a_new_and_a_deleted_table_are_listed(self):
        tags, html, listing = self.report({'plc/tags/Old.xml': table('Old', tag('o', '%M1.0'))},
                                          {'plc/tags/New.xml': table('New', tag('n', '%M2.0'), tag('m', '%M3.0'))},
                                          '--new-blocks-listed')
        by = {t['name']: t for t in tags}
        self.assertEqual(('new', 'deleted'), (by['New']['state'], by['Old']['state']))
        self.assertEqual(({'added': 2}, {'removed': 1}), (by['New']['counts'], by['Old']['counts']))
        self.assertEqual(([], []), (by['New']['rows'], by['Old']['rows']))
        self.assertIn('<span class="st new">new</span>', section(html, 'New'))
        self.assertIn('<span class="st deleted">deleted</span>', section(html, 'Old'))
        self.assertNotIn('<table', section(html, 'New'))
        self.assertIn('new      plctagtable New', listing)

    def test_all_draws_a_new_table_and_lists_the_unchanged(self):
        tags, html, _ = self.report({'plc/tags/Same.xml': table('Same', tag('s', '%M1.0'))},
                                    {'plc/tags/Same.xml': table('Same', tag('s', '%M1.0'), created='2026-07-07T00:00:00Z'),
                                     'plc/tags/New.xml': table('New', tag('n', '%M2.0'))}, '--all')
        by = {t['name']: t for t in tags}
        self.assertEqual(('new', 'same'), (by['New']['state'], by['Same']['state']))
        self.assertEqual(['n'], [r['name'] for r in by['New']['rows']])
        self.assertIn('<table', section(html, 'New'))

    def test_by_default_a_new_and_a_deleted_table_are_drawn(self):
        """A new table with its tags as added, a deleted one with them as removed. --new-blocks, the old way to ask
        for it, is the default now."""
        for args in ((), ('--new-blocks',)):
            tags, html, listing = self.report({'plc/tags/Old.xml': table('Old', tag('o', '%M1.0'))},
                                              {'plc/tags/New.xml': table('New', tag('n', '%M2.0'))}, *args)
            by = {t['name']: t for t in tags}
            self.assertEqual(([('n', 'added')], [('o', 'removed')]),
                             tuple([(r['name'], r['state']) for r in by[n]['rows']] for n in ('New', 'Old')), args)
            self.assertIn('class="ins"', section(html, 'New'))
            self.assertIn('class="del"', section(html, 'Old'))
            self.assertIn('%M1.0', section(html, 'Old'))
            self.assertIn('    removed  tag      o', listing)

    def test_a_renamed_table_by_the_tags_in_common(self):
        tags, html, listing = self.report(
            {'plc/tags/Old.xml': table('Old', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'))},
            {'plc/tags/New.xml': table('New', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'))})
        self.assertEqual([('New', 'Old', 'changed', [])], [(t['name'], t['was'], t['state'], t['rows']) for t in tags])
        self.assertIn('Old → New [PLC tag table]', section(html, 'New'))
        self.assertIn('(was "Old")', listing)

    def test_two_tables_with_little_in_common_are_not_one(self):
        tags, _, _ = self.report({'plc/tags/Old.xml': table('Old', tag('a', '%M1.0'), tag('b', '%M2.0'), tag('c', '%M3.0'))},
                                 {'plc/tags/New.xml': table('New', tag('a', '%M1.0'), tag('x', '%M4.0'), tag('y', '%M5.0'))})
        self.assertEqual({'New': 'new', 'Old': 'deleted'}, {t['name']: t['state'] for t in tags})

    def test_a_table_only_moved_to_another_folder(self):
        tags, html, listing = self.report({'plc/tags/Plant.xml': table('Plant', tag('a', '%M1.0'))},
                                          {'plc/tags/Area/Plant.xml': table('Plant', tag('a', '%M1.0'))})
        self.assertEqual([('Plant', 'moved', 'plc/tags/Plant.xml', 'plc/tags/Area/Plant.xml')],
                         [(t['name'], t['state'], t['movedFrom'], t['movedTo']) for t in tags])
        self.assertIn('plc/tags/Plant.xml → plc/tags/Area/Plant.xml', section(html, 'Plant'))
        self.assertIn('(from plc/tags/Plant.xml to plc/tags/Area/Plant.xml)', listing)
        self.assertIn('<span class="st moved">moved</span>', section(html, 'Plant'))

    def test_a_tag_moved_to_another_table_is_told_on_both(self):
        tags, html, listing = self.report(
            {'plc/tags/A.xml': table('A', tag('run', '%M1.0'), tag('keep', '%M2.0')), 'plc/tags/B.xml': table('B', tag('b', '%M3.0'))},
            {'plc/tags/A.xml': table('A', tag('keep', '%M2.0')), 'plc/tags/B.xml': table('B', tag('b', '%M3.0'), tag('run', '%M1.0'))})
        by = {t['name']: t['rows'][0] for t in tags}
        self.assertEqual(('removed', 'B'), (by['A']['state'], by['A']['movedTo']))
        self.assertEqual(('added', 'A'), (by['B']['state'], by['B']['movedFrom']))
        self.assertIn('<td class="tn"><span>run</span><div class="ex">moved to table B</div></td>', section(html, 'A'))
        self.assertIn('moved from table A', section(html, 'B'))
        self.assertIn('moved to table B', listing)

    MOVED = ({'plc/tags/A.xml': table('A', tag('run', '%M1.0'), tag('keep', '%M2.0'))},
             {'plc/tags/A.xml': table('A', tag('keep', '%M2.0')),
              'plc/tags/N.xml': table('N', tag('run', '%Q9.9', 'Int'), tag('other', '%M5.0'))})

    def test_a_tag_moved_into_a_new_table_stands_among_its_tags(self):
        tags, html, _ = self.report(*self.MOVED)
        new = {t['name']: t for t in tags}['N']
        self.assertEqual([('run', 'A'), ('other', None)], [(r['name'], r.get('movedFrom')) for r in new['rows']])
        self.assertIn('moved from table A', section(html, 'N'))
        self.assertIn('other', section(html, 'N'))

    def test_a_tag_moved_into_a_listed_new_table_shows_its_new_values(self):
        tags, html, _ = self.report(*self.MOVED, '--new-blocks-listed')
        new = {t['name']: t for t in tags}['N']
        self.assertEqual(('new', {'added': 2}), (new['state'], new['counts']))
        self.assertEqual([('run', 'A', '%Q9.9', 'Int')],
                         [(r['name'], r['movedFrom'], r['after']['address'], r['after']['type']) for r in new['rows']])
        body = section(html, 'N')
        self.assertIn('%Q9.9', body)
        self.assertIn('moved from table A', body)
        self.assertNotIn('other', body)                        # the rest of a new table stays listed only

    def test_a_tag_moved_out_of_a_deleted_table_shows_its_old_values(self):
        tags, html, _ = self.report({'plc/tags/Old.xml': table('Old', tag('run', '%M1.0'), tag('gone', '%M2.0')),
                                     'plc/tags/B.xml': table('B', tag('b', '%M3.0'))},
                                    {'plc/tags/B.xml': table('B', tag('b', '%M3.0'), tag('run', '%Q7.7'))})
        old = {t['name']: t for t in tags}['Old']
        self.assertEqual([('run', 'B', '%M1.0'), ('gone', None, '%M2.0')],
                         [(r['name'], r.get('movedTo'), r['before']['address']) for r in old['rows']])
        self.assertIn('%M1.0', section(html, 'Old'))
        self.assertIn('gone', section(html, 'Old'))

    def test_listed_a_deleted_table_keeps_the_tag_moved_out_of_it(self):
        tags, html, _ = self.report({'plc/tags/Old.xml': table('Old', tag('run', '%M1.0'), tag('gone', '%M2.0')),
                                     'plc/tags/B.xml': table('B', tag('b', '%M3.0'))},
                                    {'plc/tags/B.xml': table('B', tag('b', '%M3.0'), tag('run', '%Q7.7'))},
                                    '--new-blocks-listed')
        old = {t['name']: t for t in tags}['Old']
        self.assertEqual([('run', 'B', '%M1.0')], [(r['name'], r['movedTo'], r['before']['address']) for r in old['rows']])
        self.assertIn('%M1.0', section(html, 'Old'))
        self.assertNotIn('gone', section(html, 'Old'))


class SameRulesAsTheReport(Report):

    def test_a_difference_in_created_stays_silent(self):
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'), created='2026-01-01T00:00:00Z')},
                                    {T: table('Plant', tag('run', '%M1.0'), created='2026-06-06T00:00:00Z')})
        self.assertEqual([], tags)
        self.assertNotIn('plcTags', self.res)
        self.assertIn('No changes.', html)

    def test_a_field_no_column_shows_is_the_note_and_nothing_under_it(self):
        from TiaChangeReports.page import NET_NOT_SHOWN, NOT_SHOWN
        tags, html, listing = self.report({T: table('Plant', tag('run', '%M1.0'))},
                                          {T: table('Plant', tag('run', '%M1.0', extra='<Future>42</Future>'))})
        self.assertEqual(('changed', True), (tags[0]['state'], tags[0]['notShown']))
        self.assertEqual([('run', 'changed', ['unread'])], [(r['name'], r['state'], r['changes']) for r in tags[0]['rows']])
        body = section(html, 'Plant')
        self.assertIn('<span class="nsh">%s</span>' % NOT_SHOWN, body)
        self.assertIn('<div class="ex">%s</div>' % NET_NOT_SHOWN, body)
        self.assertNotIn('Future', html)
        self.assertNotIn('42', body)
        self.assertIn(NOT_SHOWN, listing)

    def test_an_object_beside_the_tags_is_the_note(self):
        from TiaChangeReports.page import NOT_SHOWN
        other = '<SW.Tags.Later ID="5" CompositionName="Later"><AttributeList><Name>z</Name></AttributeList></SW.Tags.Later>'
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('run', '%M1.0'), other)})
        self.assertEqual(('changed', True, []), (tags[0]['state'], tags[0]['notShown'], tags[0]['rows']))
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))
        self.assertNotIn('Later', html)

    def test_text_in_another_language_is_the_note(self):
        from TiaChangeReports.page import NOT_SHOWN
        tags, html, _ = self.report(
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Runs'), ('de-DE', 'Laeuft')]))},
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Runs'), ('de-DE', 'Geht')]))})
        self.assertEqual((True, []), (tags[0]['notShown'], tags[0]['rows']))
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))
        self.assertNotIn('Geht', html)

    def swapped(self, *beside):
        """Two tags with one comment swap their comments in another language; beside: more tags of the after version."""
        one = [('en-US', 'Same'), ('de-DE', 'Erster')]
        two = [('en-US', 'Same'), ('de-DE', 'Zweiter')]
        return self.report({T: table('Plant', tag('a', '%M1.0', texts=one), tag('b', '%M2.0', texts=two))},
                           {T: table('Plant', tag('a', '%M1.0', texts=two), tag('b', '%M2.0', texts=one), *beside)})

    def test_two_tags_swapping_their_other_language_comments_is_the_note(self):
        from TiaChangeReports.page import NOT_SHOWN
        tags, html, _ = self.swapped()
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertNotIn('No changes.', html)
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))
        self.assertNotIn('Erster', html)

    def test_the_swap_beside_another_change_is_the_note_too(self):
        tags, _, _ = self.swapped(tag('c', '%M3.0'))
        self.assertTrue(tags[0]['notShown'])
        self.assertEqual([('c', 'added')], [(r['name'], r['state']) for r in tags[0]['rows']])

    def test_a_comment_gaining_the_report_language_with_the_text_shown_before_is_the_note(self):
        from TiaChangeReports.page import NOT_SHOWN
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'x')]))},
                                    {T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'x'), ('en-US', 'x')]))})
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertNotIn('No changes.', html)
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))

    def test_a_comment_losing_the_report_language_with_the_text_shown_after_is_the_note(self):
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'x'), ('en-US', 'x')]))},
                                    {T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'x')]))})
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertNotIn('No changes.', html)

    def test_such_a_comment_beside_a_moved_address_is_the_note_too(self):
        tags, _, _ = self.report({T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'x')]))},
                                 {T: table('Plant', tag('run', '%M2.0', texts=[('de-DE', 'x'), ('en-US', 'x')]))})
        self.assertTrue(tags[0]['notShown'])
        self.assertEqual(['address'], tags[0]['rows'][0]['changes'])

    def test_a_field_inside_the_comment_is_the_note(self):
        bare = tag('run', '%M1.0', comment='Runs')
        tags, html, _ = self.report({T: table('Plant', bare)},
                                    {T: table('Plant', bare.replace('<Text>Runs</Text>', '<Text>Runs</Text><Later>1</Later>'))})
        self.assertTrue(tags[0]['notShown'])
        self.assertNotIn('No changes.', html)

    def test_the_order_of_the_languages_and_an_empty_one_stay_silent(self):
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'x'), ('de-DE', 'y')]))},
                                    {T: table('Plant', tag('run', '%M1.0', texts=[('de-DE', 'y'), ('fr-FR', ''), ('en-US', 'x')]))})
        self.assertEqual([], tags)
        self.assertIn('No changes.', html)

    def test_a_table_file_holding_no_table_is_named_with_the_note(self):
        from TiaChangeReports.page import NOT_SHOWN
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: '<Document><Nothing/></Document>'})
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))
        self.assertEqual([(T, 'unreadable: no PLC tag table in it')], [(s['path'], s['reason']) for s in self.res['skipped']])

    def test_a_table_file_that_held_no_table_before_is_named_with_the_note(self):
        tags, _, _ = self.report({T: '<Document><Nothing/></Document>'}, {T: table('Plant', tag('run', '%M1.0'))})
        self.assertEqual(('Plant', 'changed', True), (tags[0]['name'], tags[0]['state'], tags[0]['notShown']))
        self.assertEqual([T], [s['path'] for s in self.res['skipped']])

    def test_a_file_of_a_device_tags_folder_holding_no_table_too(self):
        path = 'plc/Line1/tags/Plant.xml'
        tags, _, _ = self.report({path: table('Plant', tag('run', '%M1.0'))}, {path: '<Document><Nothing/></Document>'})
        self.assertEqual(('Line1', 'changed', True), (tags[0]['device'], tags[0]['state'], tags[0]['notShown']))

    def test_an_xml_of_no_table_outside_the_tags_folders_is_no_table(self):
        for path in ('plc/blocks/tags/Notes.xml', 'plc/Notes.xml', 'tags/Notes.xml'):
            with self.subTest(path):
                tags, html, _ = self.report({path: '<Document><Nothing/></Document>'}, {path: '<Document><Other/></Document>'})
                self.assertEqual([], tags)
                self.assertNotIn('skipped', self.res)

    def test_the_same_file_of_no_table_in_two_folders_changes_nothing(self):
        from TiaChangeReports.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            _put(d, {'a/%s' % T: '<Document><Nothing/></Document>', 'b/%s' % T: '<Document><Nothing/></Document>'})
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main([os.path.join(d, 'a'), os.path.join(d, 'b'), '-o', os.path.join(d, 'p.html'), '--json'])
        res = json.loads(out.getvalue())
        self.assertEqual(0, code)
        self.assertNotIn('plcTags', res)
        self.assertEqual([T], [s['path'] for s in res['skipped']])

    def test_the_comment_in_the_report_language_edited_is_shown_with_no_note(self):
        tags, _, _ = self.report(
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Runs'), ('de-DE', 'Laeuft')]))},
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Going'), ('de-DE', 'Laeuft')]))})
        self.assertNotIn('notShown', tags[0])
        self.assertEqual(['comment'], tags[0]['rows'][0]['changes'])

    def test_lang_picks_the_comment(self):
        tags, _, _ = self.report(
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Runs'), ('de-DE', 'Laeuft')]))},
            {T: table('Plant', tag('run', '%M1.0', texts=[('en-US', 'Runs'), ('de-DE', 'Geht')]))}, '--lang', 'de-DE')
        self.assertEqual(('Laeuft', 'Geht'), (tags[0]['rows'][0]['before']['comment'], tags[0]['rows'][0]['after']['comment']))

    def test_a_broken_table_is_named_and_the_page_tells_it_differs(self):
        from TiaChangeReports.page import NOT_SHOWN
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))},
                                    {T: '<Document><SW.Tags.PlcTagTable ID="0"><broken'})
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertNotIn('No changes.', html)
        self.assertIn(NOT_SHOWN, section(html, 'Plant'))
        self.assertEqual([T], [s['path'] for s in self.res['skipped']])
        self.assertTrue(self.res['skipped'][0]['reason'].startswith('unreadable: '))
        self.assertIn('skipped %s: unreadable' % T, self.stderr)

    def test_a_text_item_with_no_attributes_is_named_and_the_report_goes_on(self):
        bare = ('<SW.Tags.PlcTag ID="1" CompositionName="Tags"><AttributeList><DataTypeName>Bool</DataTypeName>'
                '<LogicalAddress>%M1.0</LogicalAddress><Name>run</Name></AttributeList><ObjectList><MultilingualText ID="8" '
                'CompositionName="Comment"><ObjectList><MultilingualTextItem ID="9" CompositionName="Items" /></ObjectList>'
                '</MultilingualText></ObjectList></SW.Tags.PlcTag>')
        tags, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', bare)})
        self.assertEqual([('Plant', 'changed', True, [])], [(t['name'], t['state'], t['notShown'], t['rows']) for t in tags])
        self.assertEqual([T], [s['path'] for s in self.res['skipped']])
        self.assertNotIn('No changes.', html)

    def test_a_new_broken_table_is_listed_with_the_note(self):
        tags, html, _ = self.report({'plc/tags/B.xml': table('B', tag('b', '%M2.0'))},
                                    {'plc/tags/B.xml': table('B', tag('b', '%M2.0')), T: '<Document><SW.Tags.PlcTagTable ID="0"><broken'})
        self.assertEqual([('Plant', 'new', True)], [(t['name'], t['state'], t['notShown']) for t in tags])
        self.assertNotIn('No changes.', html)


class OnThePage(Report):

    def test_in_the_tree_under_plc_tags_in_tia_order(self):
        one = {'plc/blocks/A.s7dcl': SRC, 'plc/blocks/A.s7res': RES, 'plc/types/U.s7dcl': UDT,
               T: table('Plant', tag('run', '%M1.0')), 'plc/tags/Area/Sub.xml': table('Sub', tag('s', '%M2.0'))}
        two = dict(one, **{'plc/blocks/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                           'plc/types/U.s7dcl': UDT.replace('x : Bool', 'x : Int'),
                           T: table('Plant', tag('run', '%M9.0')), 'plc/tags/Area/Sub.xml': table('Sub', tag('s', '%M8.0'))})
        _, html, _ = self.report(one, two)
        tree = tree_of(html)
        self.assertLess(tree.index('Program'), tree.index('PLC'))
        self.assertLess(tree.index('PLC'), tree.index('data'))
        self.assertIn('Area', tree)
        self.assertEqual(['plctags:Sub', 'plctags:Plant'],                     # the tree's order: folders first
                         re.findall(r'id="blk-(plctags:[^"]*)"', html))
        self.assertEqual(['PLC', 'tags', '2', 'Area', '1', 'Sub', '[PLC', 'tag', 'table]', 'Plant', '[PLC', 'tag', 'table]'],
                         tree[tree.index('tags') - 1:tree.index('tags') + 12])

    def test_each_tree_entry_opens_its_own_section(self):
        one = {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES, T: table('Plant', tag('run', '%M1.0')),
               'hmi/tags/Hmi.xml': hmi_table('Hmi', [('Motor', '100 ms')])}
        two = dict(one, **{'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'),
                           T: table('Plant', tag('run', '%M9.0')), 'hmi/tags/Hmi.xml': hmi_table('Hmi', [('Motor', '1 s')])})
        _, html, _ = self.report(one, two)
        keys = {k: int(i) for i, k in re.findall(r'data-i="(\d+)" data-key="([^"]*)"', html)}
        self.assertEqual({'A': 0, 'plctags:Plant': 1, 'tagtable:Hmi': 2}, keys)
        heads = re.findall(r'<section class="blk[^>]*><div class="bh" id="blk-([^"]*)"', html)
        self.assertEqual(['A', 'plctags:Plant', 'tagtable:Hmi'], heads)
        self.assertIn('<table class="sum psum">', html)
        self.assertIn('href="#blk-plctags%3APlant"', html)
        self.assertIn('class="hmidata"', html)
        self.assertEqual(['A'], [b['name'] for b in self.res['blocks']])
        self.assertEqual(['Hmi'], [h['name'] for h in self.res['hmi']])

    def test_alone_on_the_page(self):
        _, html, _ = self.report({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('run', '%M9.0'))})
        self.assertIn('<title>PLC tag changes</title>', html)
        self.assertNotIn('class="hmidata"', html)
        self.assertNotIn('<table class="sum', html)            # one object: the header says it all

    def test_the_summary_has_a_device_column_only_with_devices(self):
        _, html, _ = self.report({'plc/tags/A.xml': table('A', tag('a', '%M1.0')), 'plc/tags/B.xml': table('B', tag('b', '%M2.0'))},
                                 {'plc/tags/A.xml': table('A', tag('a', '%M3.0')), 'plc/tags/B.xml': table('B', tag('b', '%M4.0'))})
        self.assertIn('<table class="sum psum"><tr><th>PLC tag table</th><th>State</th>', html)
        self.assertIn('<td>changed</td><td>1 changed</td>', html)

    def test_a_block_beside_it_keeps_its_diff(self):
        one = {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES, T: table('Plant', tag('run', '%M1.0'))}
        two = dict(one, **{'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), T: table('Plant', tag('run', '%M9.0'))})
        self.report(one, two)
        self.assertEqual(('A', 'changed', 1), (self.res['blocks'][0]['name'], self.res['blocks'][0]['state'],
                                               len(self.res['blocks'][0]['networks'])))
        self.assertEqual('Plant', self.res['plcTags'][0]['name'])

    def test_only_and_block(self):
        one = {'plc/A.s7dcl': SRC, 'plc/A.s7res': RES, T: table('Plant', tag('run', '%M1.0'))}
        two = dict(one, **{'plc/A.s7dcl': SRC.replace('I_Contact( #b )', 'I_Contact( #a )'), T: table('Plant', tag('run', '%M9.0'))})
        self.repo(one, two)
        self.assertIn('plcTags', json.loads(self.main('--json', '--only', 'plc')[0]))
        self.assertNotIn('plcTags', json.loads(self.main('--json', '--only', 'hmi')[0]))
        self.assertNotIn('plcTags', json.loads(self.main('--json', '--block', 'A')[0]))
        self.assertNotIn('plctags:', self.main('--block', 'A')[1])

    def test_a_fragment_holds_the_table(self):
        self.repo({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('run', '%M9.0'))})
        html = self.main('--fragment')[1]
        self.assertTrue(html.startswith('<div class="ldiff">'))
        self.assertIn('<section class="blk ptag">', html)


class SeveralPlcs(Report):

    def test_each_plc_has_its_tables(self):
        tags, html, listing = self.report(
            {'plc/Line1/tags/Plant.xml': table('Plant', tag('run', '%M1.0')), 'plc/Line2/tags/Plant.xml': table('Plant', tag('run', '%M1.0'))},
            {'plc/Line1/tags/Plant.xml': table('Plant', tag('run', '%M2.0')), 'plc/Line2/tags/Plant.xml': table('Plant', tag('run', '%M3.0'))})
        self.assertEqual([('Line1', '%M2.0'), ('Line2', '%M3.0')],
                         [(t['device'], t['rows'][0]['after']['address']) for t in tags])
        self.assertIn('id="blk-Line1:plctags:Plant"', html)
        self.assertIn('id="blk-Line2:plctags:Plant"', html)
        self.assertEqual(['Line1', '1', 'PLC', 'tags', '1', 'Plant'], tree_of(html)[:6])
        self.assertIn('Line1/Plant', listing)
        self.assertIn('<th>Device</th>', html)

    def test_a_table_does_not_pair_across_plcs_nor_a_tag_move(self):
        tags, _, _ = self.report(
            {'plc/Line1/tags/Plant.xml': table('Plant', tag('run', '%M1.0')), 'plc/Line2/tags/Other.xml': table('Other', tag('z', '%M9.0'))},
            {'plc/Line2/tags/Other.xml': table('Other', tag('z', '%M9.0')), 'plc/Line2/tags/Plant.xml': table('Plant', tag('run', '%M1.0'))})
        self.assertEqual({('Line1', 'deleted'), ('Line2', 'new')}, {(t['device'], t['state']) for t in tags})
        self.assertEqual([('Line1', 'run', 'removed', False), ('Line2', 'run', 'added', False)],    # each table's own
                         [(t['device'], r['name'], r['state'], 'movedFrom' in r or 'movedTo' in r)
                          for t in tags for r in t['rows']])

    def test_tag_tables_of_a_subfolder_of_one_plc_are_no_device(self):
        tags, _, _ = self.report({'plc/tags/Area/Sub.xml': table('Sub', tag('s', '%M1.0'))},
                                 {'plc/tags/Area/Sub.xml': table('Sub', tag('s', '%M2.0'))})
        self.assertNotIn('device', tags[0])


class Inputs(Report):

    def test_two_folders(self):
        from TiaChangeReports.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            _put(d, {'a/plc/tags/Plant.xml': table('Plant', tag('run', '%M1.0')),
                     'b/plc/tags/Plant.xml': table('Plant', tag('run', '%M2.0')),
                     'a/plc/blocks/A.s7dcl': SRC, 'b/plc/blocks/A.s7dcl': SRC})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([os.path.join(d, 'a'), os.path.join(d, 'b'), '-o', os.path.join(d, 'p.html'), '--json'])
        self.assertEqual(0, code)
        res = json.loads(out.getvalue())
        self.assertEqual(['address'], res['plcTags'][0]['rows'][0]['changes'])
        self.assertEqual([], res['blocks'])

    def test_the_working_tree(self):
        from TiaChangeReports.__main__ import main
        self.repo({T: table('Plant', tag('run', '%M1.0'))}, {T: table('Plant', tag('run', '%M1.0'))})
        _put(self.dir, {T: table('Plant', tag('run', '%M2.0')), 'plc/tags/New.xml': table('New', tag('n', '%M3.0'))})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['--git', self.dir, 'HEAD', '-o', os.path.join(self.tmp, 'p.html'), '--json'])
        self.assertEqual(0, code)
        self.assertEqual({'Plant': 'changed', 'New': 'new'}, {t['name']: t['state'] for t in json.loads(out.getvalue())['plcTags']})

    def test_a_table_that_did_not_change_is_not_read_from_a_revision(self):
        one = {T: table('Plant', tag('run', '%M1.0')), 'plc/tags/Other.xml': '<Document><SW.Tags.PlcTagTable ID="0"><broken'}
        two = dict(one, **{T: table('Plant', tag('run', '%M2.0'))})
        tags, _, _ = self.report(one, two)
        self.assertEqual(['Plant'], [t['name'] for t in tags])
        self.assertNotIn('skipped', self.res)


def tree_of(html):
    """The words of the page's project tree."""
    return re.sub(r'<[^>]+>', ' ', html[html.index('<ul class="tree">'):html.index('</nav>')]).split()


def section(html, name):
    """The section of table `name` on the page."""
    m = re.search(r'<section class="blk ptag"><div class="bh" id="blk-[^"]*plctags:%s".*?</section>' % re.escape(name),
                  html, re.S)
    if not m:
        raise AssertionError('no section of table %s' % name)
    return m.group()


UDT = 'TYPE "U"\nVERSION : 0.1\nSTRUCT\nx : Bool;\nEND_STRUCT;\nEND_TYPE\n'


def hmi_table(name, tags):
    from TiaChangeReports.tests.test_hmi_part import tag_table
    return tag_table(name, tags)


if __name__ == '__main__':
    unittest.main()
