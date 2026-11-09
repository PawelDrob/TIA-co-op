import os
import unittest
from xml.sax.saxutils import escape

from hmipreview import validate
from Tests.fixture import FixtureRepo, document, item

FONTS = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
HAVE_TAHOMA = all(os.path.exists(os.path.join(FONTS, f)) for f in ('tahoma.ttf', 'tahomabd.ttf'))
SKIP = 'Tahoma (tahoma.ttf, tahomabd.ttf) not installed in %s; text fit cannot be measured' % FONTS


def font(size, style='Regular', cultures=('en-US', 'es-ES')):
    items_ = ''.join('<Hmi.Globalization.FontItem ID="0" CompositionName="Items"><AttributeList>'
                     '<Culture>%s</Culture><FontFamily>Tahoma</FontFamily><FontSize>%s</FontSize>'
                     '<FontStyle>%s</FontStyle></AttributeList></Hmi.Globalization.FontItem>' % (c, size, style)
                     for c in cultures)
    return ('<Hmi.Globalization.MultiLingualFont ID="0" CompositionName="Font"><ObjectList>%s</ObjectList>'
            '</Hmi.Globalization.MultiLingualFont>' % items_)


def text(comp, texts):
    """texts: {culture: [line, ...]} as rich text on one line."""
    items_ = ''.join('<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
                     '<Text><body><p>%s</p></body></Text></AttributeList></MultilingualTextItem>'
                     % (c, '<br />'.join(escape(l) for l in lines)) for c, lines in texts.items())
    return '<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>' % (
        comp, items_)


def text_field(name, lines, w, h, size=13, style='Regular', es=None, **attrs):
    children = '<ObjectList>%s%s</ObjectList>' % (font(size, style), text('Text', {'en-US': lines,
                                                                                 'es-ES': es or lines}))
    return item('Hmi.Screen.TextField', name, children, Left=10, Top=100, Width=w, Height=h, **attrs)


def button(name, lines, w, h, size=13, style='Regular', **attrs):
    children = '<ObjectList>%s%s%s</ObjectList>' % (font(size, style), text('TextOff', {'en-US': lines}),
                                                   text('TextOn', {'en-US': lines}))
    return item('Hmi.Screen.Button', name, children, Left=10, Top=200, Width=w, Height=h, **attrs)


@unittest.skipUnless(HAVE_TAHOMA, SKIP)
class TextFitTest(unittest.TestCase):
    def make(self):
        repo = FixtureRepo()
        self.addCleanup(repo.cleanup)
        return repo

    def findings(self, repo):
        return [(f.severity, f.rule, f.document, f.object) for f in validate(repo.path) if f.rule.startswith('text.')]

    def screen(self, repo, *objects):
        return repo.generated('screen', 'S', document('screen', 'S', list(objects), Number=1))

    def test_short_text_fits(self):
        repo = self.make()
        self.screen(repo, text_field('ok', ['Silo'], 100, 20), button('b', ['Raise'], 100, 40))
        self.assertEqual([], self.findings(repo))

    def test_text_wider_than_its_box_is_a_warning(self):
        repo = self.make()
        path = self.screen(repo, text_field('long', ['Cooling fan group ready'], 60, 20),
                           button('b', ['Lower guard to bottom'], 50, 40))
        self.assertEqual([('warning', 'text.fit', path, 'b'), ('warning', 'text.fit', path, 'long')],
                         self.findings(repo))

    def test_every_language_is_measured(self):
        repo = self.make()
        path = self.screen(repo, text_field('t', ['Silo'], 60, 20, es=['Silo de almacenamiento']))
        found = [f for f in validate(repo.path) if f.rule == 'text.fit']
        self.assertEqual([('warning', path, 't')], [(f.severity, f.document, f.object) for f in found])
        self.assertIn('es-ES', found[0].message)

    def test_lines_taller_than_the_box_are_a_warning(self):
        repo = self.make()
        path = self.screen(repo, text_field('tall', ['A', 'B', 'C'], 100, 20))
        self.assertEqual([('warning', 'text.fit', path, 'tall')], self.findings(repo))

    def test_margins_and_border_reduce_the_box(self):
        repo = self.make()
        self.screen(repo, text_field('t', ['Silo height'], 100, 20))
        self.assertEqual([], self.findings(repo))
        path = self.screen(repo, text_field('t', ['Silo height'], 100, 20, LeftMargin=40, RightMargin=40))
        self.assertEqual([('warning', 'text.fit', path, 't')], self.findings(repo))

    def test_bold_is_measured_with_the_bold_face(self):
        try:
            from PIL import ImageFont
        except ImportError:
            self.skipTest('Pillow not installed; it is the independent reference for the Tahoma widths')
        s = 'MMMMMMMMMM'
        regular = ImageFont.truetype(os.path.join(FONTS, 'tahoma.ttf'), 20).getlength(s)
        bold = ImageFont.truetype(os.path.join(FONTS, 'tahomabd.ttf'), 20).getlength(s)
        self.assertGreater(bold, regular + 4)
        w = int(regular) + 2
        repo = self.make()
        self.screen(repo, text_field('t', [s], w, 30, size=20))
        self.assertEqual([], self.findings(repo))
        path = self.screen(repo, text_field('t', [s], w, 30, size=20, style='Bold'))
        self.assertEqual([('warning', 'text.fit', path, 't')], self.findings(repo))

    def test_fit_to_largest_and_invisible_buttons_are_not_measured(self):
        repo = self.make()
        self.screen(repo, text_field('auto', ['Cooling fan group ready'], 60, 20, FitToLargest='true'),
                    button('link', ['Lower guard to bottom'], 50, 40, Mode='Invisible'))
        self.assertEqual([], self.findings(repo))

    def test_object_lacking_a_margin_border_or_font_size_is_not_measured(self):
        # Nothing is assumed for an attribute the document leaves out (full exports only, 2026-10-06);
        # document.incomplete reports it.
        repo = self.make()
        long_ = ['Cooling fan group ready']
        no_size = text_field('noSize', long_, 60, 20).replace('<FontSize>13</FontSize>', '')
        self.screen(repo, text_field('noMargin', long_, 60, 20, LeftMargin=None),
                    text_field('noBorder', long_, 60, 20, BorderWidth=None), no_size,
                    button('noTextArea', ['Lower guard to bottom'], 50, 40, TextAreaTopMargin=None))
        self.assertEqual([], self.findings(repo))

    def test_exports_are_not_measured(self):
        repo = self.make()
        repo.export('screen', 'S', document('screen', 'S', [text_field('long', ['Cooling fan group'], 60, 20)],
                                            Number=1))
        self.assertEqual([], self.findings(repo))
