"""The HMI part of the report on a project with other languages than the report's default: a change in the third
language stands under its culture, the others stay out of it. Made-up repo: one screen with one text field."""
import base64
import contextlib
import gzip
import io
import json
import os
import re
import tempfile
import unittest

from TiaChangeReports.__main__ import main
from TiaChangeReports.tests.test_change_reports import _git, _put
from TiaChangeReports.tests.test_hmi_part import screen


def field(texts):
    items = ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture><Text><body>'
                    '<p>%s</p></body></Text></AttributeList></MultilingualTextItem>' % ct for ct in texts.items())
    return ('<Hmi.Screen.TextField ID="2" CompositionName="ScreenItems"><AttributeList><Height>40</Height><Left>10</Left>'
            '<ObjectName>txtTitle</ObjectName><Top>100</Top><Width>400</Width></AttributeList><ObjectList>'
            '<MultilingualText ID="3" CompositionName="Text"><ObjectList>%s</ObjectList></MultilingualText></ObjectList>'
            '</Hmi.Screen.TextField>' % items)


class ThirdLanguage(unittest.TestCase):
    def changes(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, 'Plant')
            page = os.path.join(tmp, 'page.html')
            os.makedirs(repo)
            _git(repo, 'init', '-q')
            _git(repo, 'config', 'core.autocrlf', 'false')
            before = {'de-DE': 'Titel', 'fr-FR': 'Titre', 'it-IT': 'Titolo'}
            _put(repo, {'hmi/screens/Door.xml': screen('Door', 1, field(before))})
            _git(repo, 'add', '-A')
            _git(repo, 'commit', '-q', '-m', 'one')
            _put(repo, {'hmi/screens/Door.xml': screen('Door', 1, field(dict(before, **{'it-IT': 'Titolo nuovo'})))})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(['--git', repo, 'HEAD', '-o', page] + list(args)) or 0)
            with open(page, encoding='utf-8') as f:
                data = re.search(r'class="hmidata">([^<]+)<', f.read()).group(1)
        objects = json.loads(gzip.decompress(base64.b64decode(data)))['objects']
        return next(o for o in objects if o['name'] == 'Door')['changes']

    def test_a_change_in_the_third_language_stands_under_its_culture(self):
        for args in ((), ('--lang', 'fr-FR'), ('--lang', 'it-IT')):   # the default en-US is not in this project
            with self.subTest(args=args):
                title = next(c for c in self.changes(*args) if c['object'] == 'txtTitle')
                self.assertEqual([('Text', 'it-IT', 'Titolo', 'Titolo nuovo')],
                                 [(t['part'], t['culture'], t['old'], t['new']) for t in title['texts']])


if __name__ == '__main__':
    unittest.main()
