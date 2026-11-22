"""The generator's calls in the WinCC Comfort guide (docs/agent/wincc-comfort-openness.md, 5.1 and 5.2): every public
function of hmixml is named there with what it takes, and no other, and the worked screen runs as written.
"""
import inspect
import os
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

import hmixml
from Tests.fixture import TP1200, FixtureRepo, document, item

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # TiaHmiGenerator
GUIDE = os.path.join(os.path.dirname(HERE), 'docs', 'agent', 'wincc-comfort-openness.md')


def section(number):
    """The text of section number (### heading) of the guide, up to the next heading."""
    with open(GUIDE, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'^### %s .*?$(.*?)(?=^#{2,3} )' % re.escape(number), text, re.M | re.S)
    if m is None:
        raise AssertionError('no section %s in %s' % (number, GUIDE))
    return m.group(1)


def public_calls():
    """The functions and classes hmixml defines whose names do not start with _."""
    return {n for n, v in vars(hmixml).items()
            if not n.startswith('_') and (inspect.isfunction(v) or inspect.isclass(v))
            and getattr(v, '__module__', None) == 'hmixml'}


class CallsTest(unittest.TestCase):
    def test_every_public_function_is_named_and_nothing_else(self):
        named = set(re.findall(r'`([A-Za-z]\w*)\(', section('5.1')))
        named |= set(re.findall(r'`(GenerationRefused)`', section('5.1')))
        calls = public_calls()
        self.assertEqual(set(), calls - named, 'public in hmixml, not named in the guide, 5.1')
        self.assertEqual(set(), named - calls, 'named in the guide, 5.1, not in hmixml')

    def test_each_call_takes_what_the_guide_writes(self):
        written = dict(re.findall(r'^\| `(\w+)(\(.*?\))` \|', section('5.1'), re.M))
        self.assertEqual({n for n in public_calls() if inspect.isfunction(getattr(hmixml, n))}, set(written))
        for name, args in written.items():
            self.assertEqual(str(inspect.signature(getattr(hmixml, name))), args, name)


def ml(comp, text):
    items = ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                    '<Text><body><p>%s</p></body></Text></AttributeList></MultilingualTextItem>' % (c, text)
                    for c in ('en-US', 'de-DE'))
    return '<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>' % (
        comp, items)


def motors():
    """The reference export the worked screen names: a screen holding the presets it uses."""
    return document('screen', 'Motors', [
        item('Hmi.Screen.Rectangle', 'S-Panel', Left=10, Top=90, Width=100, Height=50),
        item('Hmi.Screen.TextField', 'S-Title', Left=10, Top=150, Width=200, Height=30,
             children='<ObjectList>%s</ObjectList>' % ml('Text', 'Title')),
        item('Hmi.Screen.IOField', 'S-Value', Left=10, Top=190, Width=100, Height=30),
        item('Hmi.Screen.SymbolicIOField', 'S-State', Left=10, Top=230, Width=150, Height=30),
        item('Hmi.Screen.Button', 'S-Button', Left=10, Top=270, Width=120, Height=40,
             children='<ObjectList>%s%s</ObjectList>' % (ml('TextOff', 'Off'), ml('TextOn', 'On'))),
    ], template='Frame', Number=1)


def worked_screen():
    """The generator of section 5.2: its one Python block."""
    blocks = re.findall(r'```python\n(.*?)```', section('5.2'), re.S)
    if len(blocks) != 1:
        raise AssertionError('5.2 holds %d Python blocks, not one' % len(blocks))
    return blocks[0]


class WorkedScreenTest(unittest.TestCase):
    def test_runs_as_the_guide_says_and_writes_what_it_says(self):
        repo = FixtureRepo(type_identifier=TP1200)
        self.addCleanup(repo.cleanup)
        repo.panel()
        repo.export('screen', 'Motors', motors())
        repo.export('template', 'Frame', document('template', 'Frame'))
        repo.write('gen/pump.py', worked_screen())

        # the command line of the guide: <py> -I gen\x.py <tool repo>\TiaHmiGenerator <project repo>
        run = subprocess.run([sys.executable, '-X', 'utf8', '-I', os.path.join(repo.path, 'gen', 'pump.py'), HERE,
                              repo.path], capture_output=True, encoding='utf-8', cwd=repo.path)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertNotIn('error', run.stdout.lower())

        def written(rel):
            return ET.parse(os.path.join(repo.path, *rel.split('/'))).getroot()

        screen = written('hmi/generated/screens/Pumps/2100 - Pump P1.xml').find('Hmi.Screen.Screen')
        names = [e.findtext('AttributeList/ObjectName') for e in screen.iter() if e.get('CompositionName') == 'ScreenItems']
        self.assertEqual(['rectPanel', 'txtTitle', 'ioSpeed', 'symState', 'rectFault', 'btnStart', 'btnBack'], names)
        self.assertEqual('Frame', screen.findtext('LinkList/Template/Name'))
        start = next(e for e in screen.iter('Hmi.Screen.Button') if e.findtext('AttributeList/ObjectName') == 'btnStart')
        tag = next(p for p in start.iter('Hmi.Event.FunctionListEntryParameter')
                   if p.findtext('AttributeList/Name') == 'Tag')
        self.assertEqual(['Value'], [l.tag for l in tag.find('LinkList')])
        self.assertEqual('PumpP1_start', tag.findtext('LinkList/Value/Name'))
        entries = written('hmi/generated/textlists/tlPumpState.xml').iter('Hmi.TextGraphicList.TextListEntry')
        self.assertEqual(['0', '1', '2'], [e.findtext('AttributeList/From') for e in entries])
        tags = [t.findtext('AttributeList/Name') for t in written('hmi/generated/tags/PumpP1.xml').iter('Hmi.Tag.Tag')]
        self.assertEqual(['PumpP1_speed', 'PumpP1_state', 'PumpP1_fault', 'PumpP1_start'], tags)


if __name__ == '__main__':
    unittest.main()
